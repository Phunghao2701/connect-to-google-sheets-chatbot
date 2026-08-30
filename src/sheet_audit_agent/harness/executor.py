"""Agent Harness Execution Engine with Planner → RAG → Executor → Critic → Replan."""

from __future__ import annotations

import os
import re
import time
import uuid
from typing import Any

import httpx

from sheet_audit_agent.harness.critic import Critic, CriticResult
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

# Simple working memory: last N (session_id, turn) pairs
_working_memory: dict[str, list[dict[str, str]]] = {}
WORKING_MEMORY_TURNS = 5


class AgentHarnessExecutor:
    """Orchestrates: Intent → Memory → Plan → RAG → Execute → Critic → Replan → Learn."""

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

        # ---------- Stage 1: Intent Analysis ----------
        intent = IntentAnalyzer.analyze(user_msg)

        # ---------- Stage 2: Load Memory lessons ----------
        lessons = _experience_store.retrieve_relevant(
            tags=list(intent.raw_tokens) + ([str(intent.specified_year)] if intent.specified_year else []),
            top_k=3,
        )

        # ---------- Stage 3: Plan ----------
        spec = Planner.plan(intent, lessons)

        # ---------- Stage 4: RAG with lesson-boosted reranking ----------
        rag_context_text = "Không có dữ liệu snapshot."
        relevant_records: list[dict[str, Any]] = []
        available_years: list[int] = []

        if snapshot:
            index_data = SheetIndexer.index(snapshot)
            available_years = sorted(index_data.get("method_cols_by_year", {}).keys())
            lesson_tags = {t.lower() for rec in lessons for t in rec.context_tags}
            relevant_records = SheetRetriever.retrieve(
                index_data, user_msg, top_k=8, lesson_tags=lesson_tags
            )
            rag_context_text = SheetRetriever.format_context_for_prompt(relevant_records)

        # --- Early guard: reject invalid year before even calling LLM ---
        if spec.specified_year and available_years and spec.specified_year not in available_years:
            years_str = ", ".join(str(y) for y in available_years)
            return ChatResponse(
                reply=(
                    f"❌ Năm **{spec.specified_year}** không tồn tại trong bảng tính.\n"
                    f"Các năm hiện có: **{years_str}**.\n"
                    f"Bạn vui lòng dùng đúng năm trong danh sách trên nhé!"
                ),
                action_type="text",
                method_fill_proposals=[],
            )

        # ---------- Stage 5: Execute (with Critic + Replan loop) ----------
        url = (ollama_url or os.getenv("OLLAMA_PORT", "http://localhost:11434")).rstrip("/")
        model = ollama_model or os.getenv("OLLAMA_MODEL", "gemma4:31b-cloud")

        response: ChatResponse | None = None
        critic_result = CriticResult(passed=True)
        replan_count = 0

        for attempt in range(MAX_REPLANS + 1):
            proposals = cls._extract_method_fill_actions(
                user_msg, relevant_records, snapshot, spec
            )

            # For fill_method with proposals: use clean template, skip LLM verbosity
            if proposals and spec.intent == "fill_method":
                llm_reply = cls._format_proposal_reply(proposals, spec)
            else:
                llm_reply = await cls._query_ollama(
                    user_msg, rag_context_text, spec, url, model,
                    replan_hint=(critic_result.issues if attempt > 0 else None),
                    available_years=available_years,
                )

            if not llm_reply:
                llm_reply = cls._fallback_rag_analyzer(user_msg, relevant_records, proposals, snapshot)

            response = ChatResponse(
                reply=llm_reply,
                action_type="proposals" if proposals else "text",
                method_fill_proposals=proposals,
            )

            # ---------- Stage 6: Critic ----------
            critic_result = Critic.validate(spec, response, snapshot)
            if critic_result.passed or attempt == MAX_REPLANS:
                break

            # Replan: refine spec with critic feedback
            replan_count += 1
            spec = cls._refine_spec(spec, critic_result)

        # ---------- Stage 7: Evaluate + Log ----------
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

        # ---------- Stage 8: Update working memory ----------
        wm = _working_memory.setdefault(session_id, [])
        wm.append({"role": "user", "content": user_msg})
        wm.append({"role": "assistant", "content": (response.reply if response else "")})
        _working_memory[session_id] = wm[-WORKING_MEMORY_TURNS * 2:]

        # ---------- Stage 9: Experience extraction (if feedback provided) ----------
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
        """Tighten the spec based on Critic issues before next attempt."""
        refined = PlanSpec(
            intent=spec.intent,
            target_method=spec.target_method,
            specified_year=spec.specified_year,
            target_stt=spec.target_stt,
            target_name=spec.target_name,
            is_summary=spec.is_summary,
            approach_summary=spec.approach_summary + " [REPLAN]",
            memory_lessons=spec.memory_lessons,
            constraints=spec.constraints + [f"[CRITIC] {issue}" for issue in critic.issues],
            retrieval_tags=spec.retrieval_tags,
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
        norm_msg = normalize_text(user_msg)

        if proposals:
            return (
                f"Tôi đã tìm thấy {len(proposals)} dòng phù hợp trong bảng tính. "
                "Đề xuất điền hình thức đã được tạo, bạn hãy xem thẻ Preview bên dưới và bấm Phê duyệt để ghi vào sheet nhé!"
            )

        if any(k in norm_msg for k in ["tong", "bao nhieu", "chi tieu", "thong ke", "quy"]):
            summary_recs = [r for r in relevant_records if r.get("type") == "summary"]
            if summary_recs:
                lines = [f"Theo dữ liệu thực tế từ {snapshot.sheet_title if snapshot else 'bảng tính'}:"]
                for s in summary_recs:
                    for d in s.get("details", []):
                        lines.append(f"- **{d}**")
                return "\n".join(lines)

        if "trùng" in user_msg.lower() or "quét" in user_msg.lower() or "soát" in user_msg.lower():
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
                        # Year doesn't exist — skip this record entirely
                        continue
                    method_col = method_cols_by_year[specified_year]
                elif method_cols_by_year:
                    # No year specified → use first available year
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

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                res = await client.post(
                    f"{ollama_url}/api/chat",
                    json={
                        "model": ollama_model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_message},
                        ],
                        "stream": False,
                    },
                )
                if res.status_code == 200:
                    data = res.json()
                    return data.get("message", {}).get("content", "").strip()
        except Exception:
            return None
        return None
