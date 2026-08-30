"""Intent Analyzer: classify user message into a structured intent."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sheet_audit_agent.rag.query_rewriter import QueryRewriter


@dataclass
class IntentResult:
    intent: str                      # fill_method | query_data | scan_audit | general_chat
    target_method: str | None        # CK | TM
    specified_year: int | None
    target_stt: str | None
    target_name: str | None
    is_summary: bool
    confidence: float
    raw_tokens: list[str] = field(default_factory=list)


class IntentAnalyzer:
    """
    Rule-based intent classifier for the fund-management domain.

    Intents:
    - fill_method   : user wants to fill CK/TM in the method column
    - query_data    : user asks about amounts, totals, who paid
    - scan_audit    : user wants duplicate/typo scanning
    - general_chat  : everything else
    """

    @classmethod
    def analyze(cls, message: str) -> IntentResult:
        rq = QueryRewriter.rewrite(message)
        norm = rq.normalized
        expanded = rq.expanded

        # --- fill_method ---
        if rq.method_hint:
            return IntentResult(
                intent="fill_method",
                target_method=rq.method_hint,
                specified_year=rq.year_hint,
                target_stt=rq.stt_hint,
                target_name=cls._extract_name(norm),
                is_summary=False,
                confidence=0.95,
                raw_tokens=list(rq.tokens),
            )

        # --- query_data ---
        query_keywords = [
            "ai", "who", "bao nhieu", "how many", "tong", "total",
            "dong quy", "dong so tien", "lon nhat", "nho nhat",
            "nhieu nhat", "co nhung", "co ai", "danh sach",
        ]
        if any(k in expanded for k in query_keywords) or rq.is_summary:
            return IntentResult(
                intent="query_data",
                target_method=None,
                specified_year=rq.year_hint,
                target_stt=rq.stt_hint,
                target_name=cls._extract_name(norm),
                is_summary=rq.is_summary,
                confidence=0.88,
                raw_tokens=list(rq.tokens),
            )

        # --- scan_audit ---
        scan_keywords = ["trung lap", "trùng", "chinh ta", "chinh tả", "quet", "soat", "scan", "kiem tra"]
        if any(k in expanded for k in scan_keywords):
            return IntentResult(
                intent="scan_audit",
                target_method=None,
                specified_year=rq.year_hint,
                target_stt=None,
                target_name=None,
                is_summary=False,
                confidence=0.90,
                raw_tokens=list(rq.tokens),
            )

        # --- general_chat fallback ---
        return IntentResult(
            intent="general_chat",
            target_method=None,
            specified_year=rq.year_hint,
            target_stt=rq.stt_hint,
            target_name=None,
            is_summary=False,
            confidence=0.50,
            raw_tokens=list(rq.tokens),
        )

    @staticmethod
    def _extract_name(norm_text: str) -> str | None:
        """Heuristically extract a person name from normalized text (Vietnamese)."""
        # Look for capitalized-word sequences after common triggers
        for trigger in ["ten ", "nguoi ", "thanh vien "]:
            idx = norm_text.find(trigger)
            if idx >= 0:
                rest = norm_text[idx + len(trigger):].strip()
                name_tokens = rest.split()[:3]
                if name_tokens:
                    return " ".join(name_tokens)
        return None
