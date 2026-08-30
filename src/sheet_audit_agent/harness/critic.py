"""Critic: rule-based validator that checks Executor output against PlanSpec."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from sheet_audit_agent.harness.planner import PlanSpec
from sheet_audit_agent.models import ChatResponse, SheetSnapshot


class FailureType(str, Enum):
    INVALID_YEAR = "invalid_year"
    YEAR_MISMATCH = "year_mismatch"
    ROW_MISMATCH = "row_mismatch"
    COMPLETENESS_FAIL = "completeness_fail"
    HALLUCINATION = "hallucination"


@dataclass
class CriticResult:
    passed: bool
    issues: list[str] = field(default_factory=list)
    confidence: float = 1.0
    failure_type: FailureType | None = None

    def __bool__(self) -> bool:
        return self.passed


class Critic:
    """
    Validates Executor output against PlanSpec.

    Checks:
    0. Year existence   — year must exist in the sheet
    1. Year fidelity    — proposal column matches specified year
    2. Row fidelity     — proposal row matches target STT exactly
    3. Completeness     — if STT specified and fill_method, proposal must exist
    4. Data Query Valid — query_data must not return empty reply with snapshot
    """

    @classmethod
    def validate(
        cls,
        spec: PlanSpec,
        response: ChatResponse,
        snapshot: SheetSnapshot | None,
    ) -> CriticResult:
        issues: list[str] = []
        failure_type: FailureType | None = None

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
                return CriticResult(
                    passed=False,
                    issues=issues,
                    confidence=0.0,
                    failure_type=FailureType.INVALID_YEAR,
                )

        # --- Check 1: Year fidelity (per region) ---
        if snapshot and proposals:
            method_cols_by_region, global_year_map = cls._build_region_year_col_maps(snapshot)
            for p in proposals:
                actual_col = p.get("column")
                # Infer region from row or label
                region_map = method_cols_by_region.get("THU", global_year_map)
                if spec.target_region and spec.target_region in method_cols_by_region:
                    region_map = method_cols_by_region[spec.target_region]

                # Extract year from proposal label if present, e.g. "Năm 2026"
                p_label = str(p.get("rowLabel", "")) + " " + str(p.get("explanation", ""))
                p_year_match = re.search(r"Năm\s*(\d{4})", p_label)
                p_year = int(p_year_match.group(1)) if p_year_match else spec.specified_year

                if p_year:
                    expected_col = region_map.get(p_year)
                    if expected_col is not None and actual_col != expected_col:
                        issues.append(
                            f"Year fidelity: proposal column {actual_col} != "
                            f"expected col {expected_col} for năm {p_year}"
                        )
                        failure_type = FailureType.YEAR_MISMATCH

        # --- Check 2: Row fidelity (Exact STT matching) ---
        if spec.target_stt and proposals:
            stt_str = str(spec.target_stt).strip()
            matched = any(
                str(p.get("stt", "")).strip() == stt_str
                or re.search(r"\bSTT\s*#?" + re.escape(stt_str) + r"\b", str(p.get("rowLabel", "")), re.IGNORECASE)
                for p in proposals
            )
            if not matched:
                issues.append(
                    f"Row fidelity: no proposal matched STT #{stt_str} exactly"
                )
                failure_type = failure_type or FailureType.ROW_MISMATCH

        # --- Check 3: Completeness ---
        if spec.intent == "fill_method" and spec.target_stt and not proposals:
            issues.append(
                f"Completeness: intent=fill_method with STT #{spec.target_stt} "
                f"but no proposals generated"
            )
            failure_type = failure_type or FailureType.COMPLETENESS_FAIL

        # --- Check 4: No-proposal for query_data with snapshot available ---
        if spec.intent == "query_data" and snapshot and not response.reply.strip():
            issues.append("Completeness: query_data intent but empty reply")
            failure_type = failure_type or FailureType.COMPLETENESS_FAIL

        passed = len(issues) == 0
        confidence = max(0.0, 1.0 - 0.25 * len(issues))
        return CriticResult(
            passed=passed,
            issues=issues,
            confidence=confidence,
            failure_type=failure_type if not passed else None,
        )

    @staticmethod
    def _build_year_col_map(snapshot: SheetSnapshot) -> dict[int, int]:
        from sheet_audit_agent.rag.indexer import SheetIndexer
        try:
            index_data = SheetIndexer.index(snapshot)
            return index_data.get("method_cols_by_year", {})
        except Exception:
            pass
        return {}

    @staticmethod
    def _build_region_year_col_maps(snapshot: SheetSnapshot) -> tuple[dict[str, dict[int, int]], dict[int, int]]:
        from sheet_audit_agent.rag.indexer import SheetIndexer
        try:
            index_data = SheetIndexer.index(snapshot)
            return index_data.get("method_cols_by_region", {}), index_data.get("method_cols_by_year", {})
        except Exception:
            pass
        return {}, {}
