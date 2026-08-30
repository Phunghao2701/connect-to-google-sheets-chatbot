"""Experience Extractor: derives a structured lesson from a feedback signal."""

from __future__ import annotations

from sheet_audit_agent.memory.experience_store import ExperienceRecord
from sheet_audit_agent.memory.memory_gate import FeedbackSignal, GateDecision


class ExperienceExtractor:
    """
    Given a task context, critic result, and feedback signal, builds an
    ExperienceRecord ready for the Memory Gate to decide on storing.
    """

    @staticmethod
    def extract(
        user_message: str,
        intent: str,
        plan_spec: dict,
        critic_issues: list[str],
        signal: FeedbackSignal,
        replan_count: int,
        gate_decision: GateDecision,
        user_note: str = "",
    ) -> ExperienceRecord | None:
        """
        Returns an ExperienceRecord if the gate approved, else None.
        """
        if not gate_decision.should_save:
            return None

        # Derive context tags from message tokens + intent
        raw_tokens = user_message.lower().split()
        important_tokens = [
            t for t in raw_tokens
            if len(t) > 2 and t not in {"và", "cho", "với", "các", "của", "này", "là"}
        ]
        context_tags = list(set([intent] + important_tokens[:10]))

        # Build a human-readable lesson
        failure_desc = "; ".join(critic_issues) if critic_issues else user_note or "User rejected output"
        lesson = _derive_lesson(intent, failure_desc, plan_spec, user_note)

        approach = plan_spec.get("approach_summary", f"Intent={intent}")
        root_cause = _derive_root_cause(intent, critic_issues, plan_spec)

        confidence = 0.85 if signal == "user_rejected" else 0.75

        return ExperienceRecord(
            task_pattern=f"{intent}: {user_message[:80]}",
            lesson=lesson,
            context_tags=context_tags,
            approach=approach,
            failure=failure_desc,
            root_cause=root_cause,
            source=gate_decision.source,
            confidence=confidence,
        )


def _derive_lesson(intent: str, failure: str, spec: dict, user_note: str) -> str:
    """Compose a concise, actionable lesson string."""
    if user_note:
        return user_note.strip()

    year = spec.get("specified_year")
    method = spec.get("target_method")
    stt = spec.get("target_stt")

    parts: list[str] = []

    if "year" in failure.lower() or (year and "wrong" in failure.lower()):
        parts.append(
            f"Khi điền hình thức có chỉ định năm ({year}), "
            f"phải dùng đúng cột HÌNH THỨC của năm đó, không dùng cột mặc định."
        )
    if "row" in failure.lower() or "stt" in failure.lower():
        parts.append(
            f"Khớp STT #{stt} phải dùng exact match, không fuzzy."
        )
    if "hallucin" in failure.lower() or "số liệu" in failure.lower():
        parts.append(
            "Không bịa số liệu; chỉ trích dẫn số từ snapshot RAG context."
        )

    if not parts:
        parts.append(f"Intent '{intent}': {failure[:120]}")

    return " ".join(parts)


def _derive_root_cause(intent: str, issues: list[str], spec: dict) -> str:
    if not issues:
        return "Không xác định được nguyên nhân gốc rễ."
    # Map known issue patterns to root causes
    for issue in issues:
        il = issue.lower()
        if "year" in il or "cột" in il:
            return "method_cols_by_year mapping không khớp với năm người dùng chỉ định."
        if "row" in il or "stt" in il:
            return "STT matching regex quá rộng, khớp sai dòng."
        if "hallucin" in il:
            return "LLM sinh số liệu không có trong RAG context."
    return issues[0][:120]
