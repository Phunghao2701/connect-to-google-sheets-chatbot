"""Planner: converts IntentResult + Memory lessons into a PlanSpec."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sheet_audit_agent.harness.intent_analyzer import IntentResult
from sheet_audit_agent.memory.experience_store import ExperienceRecord


@dataclass
class PlanSpec:
    """Execution specification created by the Planner."""
    intent: str
    target_method: str | None
    specified_year: int | None
    target_stt: str | None
    target_name: str | None
    target_region: str | None = None
    all_years: bool = False
    is_summary: bool = False
    approach_summary: str = ""
    memory_lessons: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    retrieval_tags: set[str] = field(default_factory=set)

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "target_method": self.target_method,
            "specified_year": self.specified_year,
            "target_stt": self.target_stt,
            "target_name": self.target_name,
            "target_region": self.target_region,
            "all_years": self.all_years,
            "is_summary": self.is_summary,
            "approach_summary": self.approach_summary,
            "memory_lessons": self.memory_lessons,
            "constraints": self.constraints,
        }


class Planner:
    """
    Combines IntentResult with Memory lessons to produce a PlanSpec.

    The Executor uses PlanSpec instead of raw user message to ground its actions.
    """

    @classmethod
    def plan(
        cls,
        intent: IntentResult,
        lessons: list[ExperienceRecord] | None = None,
    ) -> PlanSpec:
        lessons = lessons or []
        lesson_texts = [rec.lesson for rec in lessons]
        constraints: list[str] = []

        # Derive constraints from lessons
        for rec in lessons:
            if "năm" in rec.lesson or "year" in rec.lesson.lower():
                constraints.append(
                    f"[MEMORY] Khi có năm chỉ định ({intent.specified_year}), "
                    f"dùng đúng cột HÌNH THỨC của năm đó."
                )
            if "hallucin" in rec.lesson.lower() or "bịa" in rec.lesson:
                constraints.append("[MEMORY] Không sinh số liệu không có trong RAG context.")
            if "stt" in rec.lesson.lower() or "dòng" in rec.lesson.lower():
                constraints.append("[MEMORY] STT matching phải exact, không fuzzy.")

        # Approach summary
        approach_parts = [f"Intent: {intent.intent}"]
        if intent.target_method:
            approach_parts.append(f"Điền: {intent.target_method}")
        if intent.specified_year:
            approach_parts.append(f"Năm: {intent.specified_year}")
        elif intent.all_years:
            approach_parts.append("Tất cả các năm")
        if intent.target_stt:
            approach_parts.append(f"STT: #{intent.target_stt}")
        if intent.target_name:
            approach_parts.append(f"Tên: {intent.target_name}")
        if lessons:
            approach_parts.append(f"Áp dụng {len(lessons)} bài học từ memory")

        # Retrieval tags for lesson-boosted RAG
        retrieval_tags: set[str] = set(intent.raw_tokens)
        if intent.specified_year:
            retrieval_tags.add(str(intent.specified_year))
        if intent.target_method:
            retrieval_tags.add(intent.target_method.lower())
        if intent.target_name:
            retrieval_tags.update(intent.target_name.lower().split())

        return PlanSpec(
            intent=intent.intent,
            target_method=intent.target_method,
            specified_year=intent.specified_year,
            target_stt=intent.target_stt,
            target_name=intent.target_name,
            target_region=intent.target_region,
            all_years=intent.all_years,
            is_summary=intent.is_summary,
            approach_summary=" | ".join(approach_parts),
            memory_lessons=lesson_texts,
            constraints=constraints,
            retrieval_tags=retrieval_tags,
        )
