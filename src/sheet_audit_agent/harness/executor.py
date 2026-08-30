"""Agent Harness Execution Engine with Planner → RAG → Executor → Critic → Replan."""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from typing import Any

import httpx

from sheet_audit_agent.harness.critic import Critic, CriticResult, FailureType
from sheet_audit_agent.harness.evaluator import AutoEvaluator
from sheet_audit_agent.harness.intent_analyzer import IntentAnalyzer
from sheet_audit_agent.harness.planner import PlanSpec, Planner
from sheet_audit_agent.harness.prompts import build_spec_aware_prompt
from sheet_audit_agent.matching import normalize_text
from sheet_audit_agent.memory.experience_store import ExperienceStore
from sheet_audit_agent.memory.extractor import ExperienceExtractor
from sheet_audit_agent.memory.memory_gate import FeedbackSignal, MemoryGate
from sheet_audit_agent.models import ChatResponse, SheetSnapshot
from sheet_audit_agent.rag.indexer import SheetIndexer
from sheet_audit_agent.rag.retriever import SheetRetriever

MAX_REPLANS = 2

# Module-level store (shared across requests in a single server process)
_experience_store = ExperienceStore()

# Simple working memory and pending action state per session
_working_memory: dict[str, list[dict[str, str]]] = {}
_pending_actions: dict[str, dict[str, Any]] = {}
WORKING_MEMORY_TURNS = 5


from sheet_audit_agent.harness.context_resolver import ConversationContextResolver, ResolvedContext


class StructuredResolver:
    """
    Deterministic resolver for write actions (e.g., fill_method).
    Directly locates target row and year column without relying on fuzzy RAG ranking.
    """

    @classmethod
    def resolve_fill_method(
        cls,
        spec: PlanSpec,
        snapshot: SheetSnapshot,
        index_data: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], str | None]:
        """
        Returns:
            (proposals, clarification_message_if_ambiguous)
        """
        if not spec.target_method:
            return [], None

        target_method = spec.target_method
        specified_year = spec.specified_year
        target_stt = str(spec.target_stt).strip() if spec.target_stt else None
        target_name = normalize_text(spec.target_name) if spec.target_name else None
        target_region = spec.target_region

        cell_map = {(c.row, c.column): c.formatted_value for c in snapshot.cells}
        proposals: list[dict[str, Any]] = []

        members = index_data.get("members", [])
        expenses = index_data.get("expenses", [])

        # Check for Region Ambiguity when STT is specified without explicit region
        if target_stt and not target_region:
            thu_match = next((m for m in members if str(m.get("stt", "")).strip() == target_stt), None)
            chi_match = next((e for e in expenses if str(e.get("stt", "")).strip() == target_stt), None)
            if thu_match and chi_match:
                thu_name = thu_match.get("name", "Thành viên")
                chi_content = chi_match.get("content", "Khoản chi")
                clarification = (
                    f"STT #{target_stt} xuất hiện ở cả bảng THU (**{thu_name}**) "
                    f"và bảng CHI (**{chi_content}**).\n"
                    f"Bạn muốn cập nhật phương thức **{target_method}** cho bảng nào?"
                )
                return [], clarification

        # Filter candidate pool by target_region if specified
        if target_region == "THU":
            all_records = members
        elif target_region == "CHI":
            all_records = expenses
        else:
            all_records = members + expenses

        for rec in all_records:
            rec_stt = str(rec.get("stt", "")).strip()
            rec_name = rec.get("name") or rec.get("content") or ""
            norm_rec_name = normalize_text(rec_name)
            row = rec["row"]

            # Exact STT match takes priority, otherwise robust token-based name match
            stt_matched = bool(target_stt and rec_stt == target_stt)
            name_matched = False
            if not target_stt and target_name and norm_rec_name:
                target_tokens = set(target_name.split())
                rec_tokens = set(norm_rec_name.split())
                if target_name == norm_rec_name:
                    name_matched = True
                elif len(target_tokens) >= 2 and target_tokens.issubset(rec_tokens):
                    name_matched = True
                elif len(rec_tokens) >= 2 and rec_tokens.issubset(target_tokens):
                    name_matched = True
                elif len(target_name) >= 4 and re.search(r"\b" + re.escape(target_name) + r"\b", norm_rec_name):
                    name_matched = True

            if stt_matched or (not target_stt and name_matched):
                method_cols_by_year = rec.get("method_cols_by_year", {})
                target_cols_and_years: list[tuple[int, int | None]] = []

                if spec.all_years and method_cols_by_year:
                    # Generate a proposal for ALL available years
                    for yr, m_col in sorted(method_cols_by_year.items()):
                        target_cols_and_years.append((m_col, yr))
                elif specified_year:
                    if specified_year in method_cols_by_year:
                        target_cols_and_years.append((method_cols_by_year[specified_year], specified_year))
                elif len(method_cols_by_year) == 1:
                    yr = next(iter(method_cols_by_year.keys()))
                    target_cols_and_years.append((method_cols_by_year[yr], yr))
                elif not method_cols_by_year:
                    # Legacy sheet without year headers -> default to standard method offset
                    m_col = rec.get("name_col", 1) + 3 if rec.get("type") == "member" else rec.get("content_col", 1) + 2
                    target_cols_and_years.append((m_col, None))
                else:
                    # Multiple years exist but none specified and not all_years -> cannot guess
                    continue

                for method_col, yr_val in target_cols_and_years:
                    current_val = cell_map.get((row, method_col), "") or "Trống"
                    proposal_id = f"proposal-{snapshot.sheet_id}-{row}-{method_col}"
                    year_label = f" - Năm {yr_val}" if yr_val else ""

                    proposals.append({
                        "id": proposal_id,
                        "sheetId": snapshot.sheet_id,
                        "row": row,
                        "column": method_col,
                        "stt": rec_stt,
                        "rowLabel": f"STT #{rec_stt} ({rec_name}){year_label}",
                        "currentValue": current_val,
                        "proposedValue": target_method,
                        "explanation": f"Khớp chính xác: {rec_name} ➔ {target_method}{year_label}",
                    })

        return proposals, None


class AgentHarnessExecutor:
    """Orchestrates: Context Resolver → Intent → Memory → Plan → RAG/Resolver → Execute → Critic → Replan → Learn."""

    @classmethod
    def _finalize_response(
        cls,
        session_id: str,
        user_msg: str,
        response: ChatResponse,
        pending_action: dict[str, Any] | None = None,
        clear_pending: bool = False,
    ) -> ChatResponse:
        """Always record user and assistant messages into session working memory and update pending state."""
        wm = _working_memory.setdefault(session_id, [])
        wm.append({"role": "user", "content": user_msg})
        wm.append({"role": "assistant", "content": response.reply})
        _working_memory[session_id] = wm[-WORKING_MEMORY_TURNS * 2:]

        if clear_pending:
            _pending_actions.pop(session_id, None)
        elif pending_action:
            _pending_actions[session_id] = pending_action

        return response

    @classmethod
    async def process_chat(
        cls,
        message: str,
        snapshot: SheetSnapshot | None = None,
        ollama_url: str | None = None,
        ollama_model: str | None = None,
        session_id: str | None = None,
        feedback_signal: FeedbackSignal | None = None,
        user_note: str = "",
    ) -> ChatResponse:
        t0 = time.monotonic()
        session_id = session_id or str(uuid.uuid4())[:8]
        user_msg = message.strip()
        if not user_msg:
            return ChatResponse(reply="Chào bạn! Tôi có thể giúp gì cho bạn?")

        # ---------- Stage 0: Index Sheet Data & Available Years ----------
        available_years: list[int] = []
        index_data: dict[str, Any] = {}
        if snapshot:
            index_data = SheetIndexer.index(snapshot)
            available_years = sorted(index_data.get("method_cols_by_year", {}).keys())

        # ---------- Stage 1: Conversation Context & Pending Action Resolution ----------
        history = _working_memory.get(session_id, [])[-WORKING_MEMORY_TURNS * 2:]
        pending = _pending_actions.get(session_id)

        resolved_ctx = ConversationContextResolver.resolve(
            user_msg, history=history, pending_action=pending, available_years=available_years
        )
        effective_query = resolved_ctx.standalone_query
        if resolved_ctx.cleared_pending:
            _pending_actions.pop(session_id, None)

        # ---------- Stage 2: Intent Analysis ----------
        intent = IntentAnalyzer.analyze(effective_query)
        # Override with resolved context entities if inferred from history or pending action
        if resolved_ctx.active_year and not intent.specified_year:
            intent.specified_year = resolved_ctx.active_year
        if resolved_ctx.active_stt and not intent.target_stt:
            intent.target_stt = resolved_ctx.active_stt
        if resolved_ctx.active_method and not intent.target_method:
            intent.target_method = resolved_ctx.active_method
        if resolved_ctx.active_region and not intent.target_region:
            intent.target_region = resolved_ctx.active_region

        # ---------- Stage 3: Load Memory lessons ----------
        lessons = _experience_store.retrieve_relevant(
            tags=list(intent.raw_tokens) + ([str(intent.specified_year)] if intent.specified_year else []),
            top_k=3,
        )

        # ---------- Stage 4: Plan ----------
        spec = Planner.plan(intent, lessons)

        # ---------- Stage 5: RAG with lesson-boosted reranking ----------
        rag_context_text = "Không có dữ liệu snapshot."
        relevant_records: list[dict[str, Any]] = []

        if snapshot:
            lesson_tags = {t.lower() for rec in lessons for t in rec.context_tags}
            search_tags = lesson_tags | {t.lower() for t in spec.retrieval_tags}
            relevant_records = SheetRetriever.retrieve(
                index_data, effective_query, top_k=8, lesson_tags=search_tags
            )
            rag_context_text = SheetRetriever.format_context_for_prompt(relevant_records)

        # --- Guard 1: reject non-existent specified year ---
        if spec.specified_year and available_years and spec.specified_year not in available_years:
            years_str = ", ".join(str(y) for y in available_years)
            resp = ChatResponse(
                reply=(
                    f"❌ Năm **{spec.specified_year}** không tồn tại trong bảng tính.\n"
                    f"Các năm hiện có: **{years_str}**.\n"
                    f"Bạn vui lòng dùng đúng năm trong danh sách trên nhé!"
                ),
                action_type="text",
                method_fill_proposals=[],
            )
            return cls._finalize_response(session_id, user_msg, resp, clear_pending=True)

        # --- Guard 2: Year Ambiguity for Write Intent (never guess when multiple years exist unless all_years is specified) ---
        if spec.intent == "fill_method" and not spec.specified_year and not spec.all_years and len(available_years) > 1:
            years_str = ", ".join(str(y) for y in available_years)
            new_pending = {
                "intent": "fill_method",
                "target_stt": spec.target_stt,
                "target_name": spec.target_name,
                "target_method": spec.target_method,
                "target_region": spec.target_region,
                "missing": "year",
            }
            resp = ChatResponse(
                reply=(
                    f"Bạn muốn cập nhật phương thức **{spec.target_method or 'thanh toán'}** cho năm nào?\n"
                    f"Các năm hiện có trong bảng tính: **{years_str}**."
                ),
                action_type="clarification",
                method_fill_proposals=[],
            )
            return cls._finalize_response(session_id, user_msg, resp, pending_action=new_pending)

        # ---------- Stage 6: Execute (with Critic + Replan loop) ----------
        url = (ollama_url or os.getenv("OLLAMA_PORT", "http://localhost:11434")).rstrip("/")
        model = ollama_model or os.getenv("OLLAMA_MODEL", "gemma4:31b-cloud")

        response: ChatResponse | None = None
        critic_result = CriticResult(passed=True)
        replan_count = 0

        for attempt in range(MAX_REPLANS + 1):
            if spec.intent == "fill_method" and snapshot:
                # Use StructuredResolver for deterministic write actions
                proposals, region_clarification = StructuredResolver.resolve_fill_method(spec, snapshot, index_data)
                if region_clarification and not proposals:
                    new_pending = {
                        "intent": "fill_method",
                        "target_stt": spec.target_stt,
                        "target_method": spec.target_method,
                        "specified_year": spec.specified_year,
                        "missing": "region",
                    }
                    resp = ChatResponse(
                        reply=region_clarification,
                        action_type="clarification",
                        method_fill_proposals=[],
                    )
                    return cls._finalize_response(session_id, user_msg, resp, pending_action=new_pending)
            else:
                # STRICT WRITE SAFETY: Non-fill_method intents NEVER generate proposals!
                proposals = []

            # For fill_method with proposals: use clean template, skip LLM verbosity
            if proposals and spec.intent == "fill_method":
                llm_reply = cls._format_proposal_reply(proposals, spec)
            else:
                llm_reply = await cls._query_ollama(
                    effective_query, rag_context_text, spec, url, model,
                    replan_hint=(critic_result.issues if attempt > 0 else None),
                    available_years=available_years,
                    history=history,
                )

            if not llm_reply:
                llm_reply = cls._fallback_rag_analyzer(effective_query, relevant_records, proposals, snapshot)

            response = ChatResponse(
                reply=llm_reply,
                action_type="proposals" if proposals else "text",
                method_fill_proposals=proposals,
            )

            # Critic validation
            critic_result = Critic.validate(spec, response, snapshot)
            if critic_result.passed or attempt == MAX_REPLANS:
                break

            # FailureType-aware Replan Policy
            replan_count += 1
            spec = cls._refine_spec(spec, critic_result)

            if snapshot and index_data:
                if critic_result.failure_type == FailureType.COMPLETENESS_FAIL:
                    broad_tags = search_tags | set(effective_query.lower().split())
                    relevant_records = SheetRetriever.retrieve(
                        index_data, effective_query, top_k=15, lesson_tags=broad_tags
                    )
                elif critic_result.failure_type == FailureType.YEAR_MISMATCH and spec.specified_year:
                    relevant_records = SheetRetriever.retrieve(
                        index_data, f"{effective_query} năm {spec.specified_year}", top_k=8, lesson_tags=search_tags
                    )
                else:
                    relevant_records = SheetRetriever.retrieve(
                        index_data, effective_query, top_k=8, lesson_tags=search_tags
                    )
                rag_context_text = SheetRetriever.format_context_for_prompt(relevant_records)

        # Stage 7: Evaluate + Log
        latency_ms = (time.monotonic() - t0) * 1000
        AutoEvaluator.log(
            session_id=session_id,
            user_message=user_msg,
            spec=spec,
            response=response,  # type: ignore[arg-type]
            critic=critic_result,
            replan_count=replan_count,
            latency_ms=latency_ms,
        )

        # Stage 8: Update working memory & finalize response
        cls._finalize_response(session_id, user_msg, response, clear_pending=bool(proposals))

        # Stage 9: Experience extraction
        if feedback_signal and feedback_signal != "auto_pass":
            gate_decision = MemoryGate.evaluate(
                signal=feedback_signal,
                replan_count=replan_count,
                has_proposals=bool(response and response.method_fill_proposals),
                preference_keywords=user_msg.lower().split(),
            )
            record = ExperienceExtractor.extract(
                user_message=user_msg,
                intent=spec.intent,
                plan_spec=spec.to_dict(),
                critic_issues=critic_result.issues,
                signal=feedback_signal,
                replan_count=replan_count,
                gate_decision=gate_decision,
                user_note=user_note,
            )
            if record:
                _experience_store.add(record)

        return response  # type: ignore[return-value]

    # ------------------------------------------------------------------ #
    # Internal helpers                                                      #
    # ------------------------------------------------------------------ #

    @classmethod
    def _refine_spec(cls, spec: PlanSpec, critic: CriticResult) -> PlanSpec:
        """Derive a tightened PlanSpec from Critic issues while preserving target_region."""
        refined_constraints = list(spec.constraints)
        for issue in critic.issues:
            refined_constraints.append(f"CRITIC FIX: {issue}")

        refined = PlanSpec(
            intent=spec.intent,
            target_method=spec.target_method,
            specified_year=spec.specified_year,
            target_stt=spec.target_stt,
            target_name=spec.target_name,
            target_region=spec.target_region,
            all_years=spec.all_years,
            is_summary=spec.is_summary,
            retrieval_tags=set(spec.retrieval_tags),
            constraints=refined_constraints,
            approach_summary=spec.approach_summary + " [REFINED]",
            memory_lessons=spec.memory_lessons,
        )
        return refined

    @staticmethod
    def _format_proposal_reply(proposals: list[dict], spec: "PlanSpec") -> str:
        """
        Clean, deterministic template reply when fill_method proposals are ready.
        Avoids verbose / hallucinated LLM text.
        """
        count = len(proposals)
        year_label = f" năm **{spec.specified_year}**" if spec.specified_year else ""

        lines = [f"✅ Tìm thấy **{count}** dòng phù hợp{year_label}:"]
        lines.append("")
        for p in proposals:
            row_lbl = p.get('rowLabel', '')
            current = p.get('currentValue', 'Trống')
            proposed = p.get('proposedValue', '')
            lines.append(f"- **{row_lbl}** — hiện tại: `{current}` → đề xuất: **{proposed}**")

        lines.append("")
        lines.append("👇 Xem thẻ Đề xuất bên dưới và bấm **Phê duyệt** để ghi vào sheet.")
        return "\n".join(lines)

    @classmethod
    def _fallback_rag_analyzer(
        cls,
        user_msg: str,
        relevant_records: list[dict[str, Any]],
        proposals: list[dict[str, Any]],
        snapshot: SheetSnapshot | None,
    ) -> str:
        """Deterministic fallback when LLM is unavailable."""
        if proposals:
            p = proposals[0]
            return (
                f"Đã tạo đề xuất cập nhật cho {p.get('rowLabel', 'dòng')}: "
                f"chuyển thành '{p.get('proposedValue')}'."
            )

        if relevant_records:
            summary_recs = [r for r in relevant_records if r.get("type") == "summary"]
            if summary_recs:
                lines = [f"Theo dữ liệu thực tế từ {snapshot.sheet_title if snapshot else 'bảng tính'}:"]
                for s in summary_recs:
                    for d in s.get("details", []):
                        lines.append(f"- **{d}**")
                return "\n".join(lines)

        norm_msg = normalize_text(user_msg)
        if "trùng" in norm_msg or "quét" in norm_msg or "soát" in norm_msg:
            return "Tôi đang tự động rà soát bảng tính để phát hiện trùng lặp tên, viết tắt và sai chính tả."

        return (
            "Chào bạn! Tôi là Trợ lý AI Google Sheets. Bạn có thể hỏi số liệu, "
            "yêu cầu điền hình thức (ví dụ: 'STT 2 là CK'), hoặc kiểm tra trùng lặp."
        )

    @classmethod
    def _extract_method_fill_actions(
        cls,
        message: str,
        records: list[dict[str, Any]],
        snapshot: SheetSnapshot | None,
        spec: PlanSpec,
    ) -> list[dict[str, Any]]:
        if not snapshot or not spec.target_method:
            return []

        norm_msg = normalize_text(message)
        target_method = spec.target_method
        specified_year = spec.specified_year

        proposals: list[dict[str, Any]] = []
        cell_map = {(c.row, c.column): c.formatted_value for c in snapshot.cells}

        for rec in records:
            row = rec["row"]
            stt = rec.get("stt", "")
            name = rec.get("name") or rec.get("content") or f"Dòng {row + 1}"
            norm_name = normalize_text(name)

            stt_match = re.search(r"\b(?:stt|dòng|#)?\s*" + re.escape(str(stt)) + r"\b", norm_msg)
            name_match = norm_name and norm_name in norm_msg

            if stt_match or name_match:
                method_cols_by_year = rec.get("method_cols_by_year", {})

                if specified_year:
                    # STRICT: only allow years that actually exist in the sheet
                    if specified_year not in method_cols_by_year:
                        continue
                    method_col = method_cols_by_year[specified_year]
                elif method_cols_by_year:
                    method_col = list(method_cols_by_year.values())[0]
                else:
                    method_col = rec.get("name_col", 1) + 3 if rec.get("type") == "member" else rec.get("content_col", 1) + 2

                current_val = cell_map.get((row, method_col), "") or "Trống"
                proposal_id = f"proposal-{snapshot.sheet_id}-{row}-{method_col}"
                year_label = f" - Năm {specified_year}" if specified_year else ""

                if not any(p["id"] == proposal_id for p in proposals):
                    proposals.append({
                        "id": proposal_id,
                        "sheetId": snapshot.sheet_id,
                        "row": row,
                        "column": method_col,
                        "stt": str(stt),
                        "rowLabel": f"STT #{stt} ({name}){year_label}",
                        "currentValue": current_val,
                        "proposedValue": target_method,
                        "explanation": f"Khớp từ RAG: {name} ➔ {target_method}{year_label}",
                    })

        return proposals

    @classmethod
    async def _query_ollama(
        cls,
        user_message: str,
        context_text: str,
        spec: PlanSpec,
        ollama_url: str,
        ollama_model: str,
        replan_hint: list[str] | None = None,
        available_years: list[int] | None = None,
        history: list[dict[str, str]] | None = None,
    ) -> str | None:
        plan_section = spec.approach_summary
        if spec.constraints:
            plan_section += "\nRàng buộc:\n" + "\n".join(f"  {c}" for c in spec.constraints)
        if available_years:
            years_str = ", ".join(str(y) for y in available_years)
            plan_section += f"\n[QUAN TRỌNG] Các năm hợp lệ trong bảng tính: {years_str}. Nếu user yêu cầu năm ngoài danh sách này, hãy từ chối và thông báo rõ."
        if replan_hint:
            plan_section += "\n[REPLAN] Vòng trước lỗi:\n" + "\n".join(f"  - {h}" for h in replan_hint)

        system_prompt = build_spec_aware_prompt(
            plan_section=plan_section,
            context_section=context_text,
            lessons=spec.memory_lessons,
        )

        messages = [{"role": "system", "content": system_prompt}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_message})

        api_key = os.getenv("OLLAMA_API_KEY", "").strip()
        headers: dict[str, str] = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        try:
            async with httpx.AsyncClient(timeout=25.0) as client:
                res = await client.post(
                    f"{ollama_url}/api/chat",
                    json={
                        "model": ollama_model,
                        "messages": messages,
                        "stream": False,
                    },
                    headers=headers,
                )
                if res.status_code == 200:
                    text = res.text
                    # Parse either single JSON object or multi-line NDJSON
                    content_parts: list[str] = []
                    for line in text.strip().split("\n"):
                        if line.strip():
                            try:
                                d = json.loads(line)
                                msg = d.get("message", {}).get("content", "")
                                if msg:
                                    content_parts.append(msg)
                            except Exception:
                                pass
                    if content_parts:
                        return "".join(content_parts).strip()
        except Exception:
            return None
        return None
