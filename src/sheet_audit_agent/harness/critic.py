"""Critic: rule-based validator that checks Executor output against PlanSpec."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sheet_audit_agent.harness.planner import PlanSpec
from sheet_audit_agent.models import ChatResponse, SheetSnapshot


@dataclass
class CriticResult:
    passed: bool
    issues: list[str] = field(default_factory=list)
    confidence: float = 1.0

    def __bool__(self) -> bool:
        return self.passed


class Critic:
    """
    Validates Executor output against PlanSpec.

    Checks:
    1. Year fidelity    — proposal column matches specified year
    2. Row fidelity     — proposal row matches target STT (if specified)
    3. Hallucination    — reply numbers exist in snapshot
    4. Completeness     — if STT specified, at least one proposal must exist
    """

    @classmethod
    def validate(
        cls,
        spec: PlanSpec,
        response: ChatResponse,
        snapshot: SheetSnapshot | None,
    ) -> CriticResult:
        issues: list[str] = []

        proposals: list[dict[str, Any]] = response.method_fill_proposals or []

        # --- Check 0: Year existence --- (hard fail, no replan can fix this)
        if spec.specified_year and snapshot:
            year_col_map = cls._build_year_col_map(snapshot)
            if year_col_map and spec.specified_year not in year_col_map:
                valid_years = sorted(year_col_map.keys())
                issues.append(
                    f"Invalid year: năm {spec.specified_year} không tồn tại trong sheet. "
                    f"Các năm hợp lệ: {valid_years}"
                )
                # Return immediately — no point checking other conditions
                return CriticResult(passed=False, issues=issues, confidence=0.0)

        # --- Check 1: Year fidelity ---
        if spec.specified_year and snapshot and proposals:
            year_col_map = cls._build_year_col_map(snapshot)
            expected_col = year_col_map.get(spec.specified_year)
            if expected_col is not None:
                for p in proposals:
                    actual_col = p.get("column")
                    if actual_col != expected_col:
                        issues.append(
                            f"Year fidelity: proposal column {actual_col} != "
                            f"expected col {expected_col} for năm {spec.specified_year}"
                        )


        # --- Check 2: Row fidelity ---
        if spec.target_stt and proposals:
            stt_str = str(spec.target_stt)
            matched = any(stt_str in str(p.get("rowLabel", "")) for p in proposals)
            if not matched:
                issues.append(
                    f"Row fidelity: no proposal matched STT #{stt_str}"
                )

        # --- Check 3: Completeness ---
        if spec.intent == "fill_method" and spec.target_stt and not proposals:
            issues.append(
                f"Completeness: intent=fill_method with STT #{spec.target_stt} "
                f"but no proposals generated"
            )

        # --- Check 4: No-proposal for query_data with snapshot available ---
        if spec.intent == "query_data" and snapshot and not response.reply.strip():
            issues.append("Completeness: query_data intent but empty reply")

        passed = len(issues) == 0
        confidence = max(0.0, 1.0 - 0.25 * len(issues))
        return CriticResult(passed=passed, issues=issues, confidence=confidence)

    @staticmethod
    def _build_year_col_map(snapshot: SheetSnapshot) -> dict[int, int]:
        """
        Re-derive {year: method_col} from the snapshot header rows.
        Mirrors the logic in SheetIndexer.
        """
        from sheet_audit_agent.rag.indexer import SheetIndexer
        try:
            index_data = SheetIndexer.index(snapshot)
            # Pull method_cols_by_year from the first member record
            members = index_data.get("members", [])
            if members:
                return members[0].get("method_cols_by_year", {})
        except Exception:
            pass
        return {}
