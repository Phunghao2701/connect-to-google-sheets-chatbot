"""Conversation Context Resolver: resolves anaphora and contextual references before Intent & RAG."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from sheet_audit_agent.matching import normalize_text
from sheet_audit_agent.rag.query_rewriter import QueryRewriter


@dataclass
class ResolvedContext:
    standalone_query: str
    active_year: int | None = None
    active_stt: str | None = None
    active_method: str | None = None
    active_name: str | None = None
    active_region: str | None = None
    is_followup: bool = False
    cleared_pending: bool = False


class ConversationContextResolver:
    """
    Resolves conversational references (e.g., 'Thế năm trước?', 'Còn STT 3?', 'ông này')
    using recent conversation history and pending action state.

    Produces a self-contained query so downstream IntentAnalyzer, Planner, and Retriever
    operate on fully grounded context.
    """

    @classmethod
    def resolve(
        cls,
        current_message: str,
        history: list[dict[str, str]] | None = None,
        pending_action: dict[str, Any] | None = None,
        available_years: list[int] | None = None,
    ) -> ResolvedContext:
        user_msg = current_message.strip()
        norm_msg = normalize_text(user_msg)
        current_rq = QueryRewriter.rewrite(user_msg)

        # 0. Check for Pending Action completion (e.g. user answering a clarification question)
        if pending_action:
            missing = pending_action.get("missing")
            if missing == "year" and current_rq.year_hint:
                # User provided the missing year (e.g., "2026", "năm 2026")
                stt = pending_action.get("target_stt")
                method = pending_action.get("target_method", "CK")
                region = pending_action.get("target_region")
                year = current_rq.year_hint
                reg_phrase = f" bảng {region}" if region else ""
                standalone = f"Điền hình thức STT {stt} năm {year} là {method}{reg_phrase}"
                return ResolvedContext(
                    standalone_query=standalone,
                    active_year=year,
                    active_stt=stt,
                    active_method=method,
                    active_region=region,
                    is_followup=True,
                    cleared_pending=True,
                )
            elif missing == "region":
                target_region = None
                if re.search(r"\b(?:thu|bang thu|dong quy|thanh vien|hoi vien)\b", norm_msg):
                    target_region = "THU"
                elif re.search(r"\b(?:chi|bang chi|khoan chi|noi dung chi|chi tieu|mua)\b", norm_msg):
                    target_region = "CHI"

                if target_region:
                    stt = pending_action.get("target_stt")
                    method = pending_action.get("target_method", "CK")
                    year = pending_action.get("specified_year")
                    year_phrase = f" năm {year}" if year else ""
                    standalone = f"Điền hình thức STT {stt}{year_phrase} là {method} cho bảng {target_region}"
                    return ResolvedContext(
                        standalone_query=standalone,
                        active_year=year,
                        active_stt=stt,
                        active_method=method,
                        active_region=target_region,
                        is_followup=True,
                        cleared_pending=True,
                    )

        if not history:
            return ResolvedContext(
                standalone_query=user_msg,
                active_year=current_rq.year_hint,
                active_stt=current_rq.stt_hint,
                active_method=current_rq.method_hint,
            )

        # 1. Extract context entities ONLY from previous USER turns (not assistant)
        user_history = [turn for turn in history if turn.get("role") == "user"][-3:]
        prev_years: list[int] = []
        prev_stts: list[str] = []
        prev_methods: list[str] = []

        for turn in reversed(user_history):
            content = turn.get("content", "")
            turn_rq = QueryRewriter.rewrite(content)
            if turn_rq.year_hint and turn_rq.year_hint not in prev_years:
                prev_years.append(turn_rq.year_hint)
            if turn_rq.stt_hint and turn_rq.stt_hint not in prev_stts:
                prev_stts.append(turn_rq.stt_hint)
            if turn_rq.method_hint and turn_rq.method_hint not in prev_methods:
                prev_methods.append(turn_rq.method_hint)

        last_year = prev_years[0] if prev_years else None
        last_stt = prev_stts[0] if prev_stts else None
        last_method = prev_methods[0] if prev_methods else None

        inferred_year = current_rq.year_hint
        inferred_stt = current_rq.stt_hint
        inferred_method = current_rq.method_hint
        standalone_parts = [user_msg]
        is_followup = False

        # 2. Check for relative year references ("năm trước", "năm ngoái", "năm sau")
        if re.search(r"\b(?:nam truoc|nam ngoai|truoc do)\b", norm_msg):
            is_followup = True
            if last_year:
                prior_year = last_year - 1
                if available_years and (last_year - 1) not in available_years:
                    lower_years = [y for y in available_years if y < last_year]
                    if lower_years:
                        prior_year = max(lower_years)
                inferred_year = prior_year
                standalone_parts.append(f"(năm {prior_year})")
        elif re.search(r"\b(?:nam sau|nam tiep theo)\b", norm_msg):
            is_followup = True
            if last_year:
                next_year = last_year + 1
                if available_years and (last_year + 1) not in available_years:
                    higher_years = [y for y in available_years if y > last_year]
                    if higher_years:
                        next_year = min(higher_years)
                inferred_year = next_year
                standalone_parts.append(f"(năm {next_year})")

        # 3. Check for entity continuation ("còn STT 3?", "thế STT 4?")
        if current_rq.stt_hint and not current_rq.method_hint and not current_rq.year_hint:
            if last_method and any(k in norm_msg for k in ["doi", "la", "con", "the", "dien"]) or len(norm_msg.split()) <= 4:
                is_followup = True
                inferred_method = last_method
                if last_year:
                    inferred_year = last_year
                    standalone_parts.append(f"năm {last_year} là {last_method}")
                else:
                    standalone_parts.append(f"là {last_method}")

        # 4. If query lacks year but refers to prior topic
        if not inferred_year and last_year and any(w in norm_msg for w in ["the con", "the thi", "vay thi", "bao nhieu", "tong so", "nhung ai"]):
            is_followup = True
            inferred_year = last_year
            standalone_parts.append(f"năm {last_year}")

        standalone_query = " ".join(standalone_parts) if is_followup else user_msg

        return ResolvedContext(
            standalone_query=standalone_query,
            active_year=inferred_year,
            active_stt=inferred_stt,
            active_method=inferred_method,
            is_followup=is_followup,
        )
