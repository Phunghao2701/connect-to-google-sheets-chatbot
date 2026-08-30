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
    target_region: str | None = None # THU | CHI | None
    all_years: bool = False
    is_summary: bool = False
    confidence: float = 1.0
    raw_tokens: list[str] = field(default_factory=list)


# Explicit mutation verbs or assignment patterns like "là ck", "là tm", "đều là tm"
_WRITE_PATTERNS = re.compile(
    r"\b("
    r"dien|dien vao|doi|sua|cap nhat|ghi|set|thay|dat|chuyen thanh|chuyen|"
    r"(?:deu\s+)?la\s+(?:ck|tm)\b"
    r")",
    re.IGNORECASE,
)

# Interrogative keywords and query indicators (avoid generic terms like "thanh toan")
_QUERY_INDICATORS = [
    "ai", "who", "bao nhieu", "how many", "tong", "total",
    "co nhung", "co ai", "danh sach", "xem", "hien thi",
    "ket qua", "co phai", "khong", "the nao",
    "la bao nhieu", "la gi", "la ai", "nhung ai",
]


class IntentAnalyzer:
    """
    Rule-based intent classifier for the fund-management domain.

    Intents:
    - fill_method : user explicitly wants to WRITE CK/TM
      (has write verb/pattern OR short-form "STT X [năm Y] CK" without query words)
    - query_data  : user asks about data (read-only, may mention CK/TM as filter)
    - scan_audit  : user wants duplicate/typo scanning
    - general_chat: everything else
    """

    @classmethod
    def analyze(cls, message: str) -> IntentResult:
        rq = QueryRewriter.rewrite(message)
        norm = rq.normalized
        expanded = rq.expanded

        # Detect region hint from strong signals only
        target_region: str | None = None
        if re.search(r"\b(?:thu|bang thu|dong quy|thanh vien|hoi vien)\b", norm):
            target_region = "THU"
        elif re.search(r"\b(?:chi|bang chi|khoan chi|noi dung chi|chi tieu|mua)\b", norm):
            target_region = "CHI"

        is_question = "?" in message or any(k in norm or k in expanded for k in _QUERY_INDICATORS)

        # --- Check 1: scan_audit ---
        scan_keywords = [
            "trung lap", "trung", "chinh ta", "quet", "soat", "scan", "kiem tra",
        ]
        if any(k in expanded for k in scan_keywords) and not rq.method_hint:
            return IntentResult(
                intent="scan_audit",
                target_method=None,
                specified_year=rq.year_hint,
                target_stt=None,
                target_name=None,
                target_region=target_region,
                all_years=rq.all_years_hint,
                is_summary=False,
                confidence=0.90,
                raw_tokens=list(rq.tokens),
            )

        # --- Check 2: fill_method (Write Intent) ---
        has_write_verb = bool(_WRITE_PATTERNS.search(norm))
        is_short_write_command = bool(rq.stt_hint and rq.method_hint)

        if rq.method_hint and (has_write_verb or is_short_write_command) and not is_question:
            return IntentResult(
                intent="fill_method",
                target_method=rq.method_hint,
                specified_year=rq.year_hint,
                target_stt=rq.stt_hint,
                target_name=cls._extract_name(norm),
                target_region=target_region,
                all_years=rq.all_years_hint,
                is_summary=False,
                confidence=0.95,
                raw_tokens=list(rq.tokens),
            )

        # --- Check 3: query_data (Read Intent) ---
        if rq.method_hint or is_question or rq.is_summary:
            return IntentResult(
                intent="query_data",
                target_method=rq.method_hint,  # preserved as filter
                specified_year=rq.year_hint,
                target_stt=rq.stt_hint,
                target_name=cls._extract_name(norm),
                target_region=target_region,
                all_years=rq.all_years_hint,
                is_summary=rq.is_summary,
                confidence=0.88,
                raw_tokens=list(rq.tokens),
            )

        # --- Check 4: general_chat fallback ---
        return IntentResult(
            intent="general_chat",
            target_method=None,
            specified_year=rq.year_hint,
            target_stt=rq.stt_hint,
            target_name=None,
            target_region=target_region,
            all_years=rq.all_years_hint,
            is_summary=False,
            confidence=0.50,
            raw_tokens=list(rq.tokens),
        )

    @staticmethod
    def _extract_name(norm_text: str) -> str | None:
        """Heuristically extract a person name from normalized text (Vietnamese)."""
        # 1. Trigger-based extraction
        for trigger in ["ten ", "nguoi ", "thanh vien "]:
            idx = norm_text.find(trigger)
            if idx >= 0:
                rest = norm_text[idx + len(trigger):].strip()
                name_tokens = rest.split()[:4]
                if name_tokens:
                    return " ".join(name_tokens)

        # 2. Heuristic extraction: remove command keywords, method words, years, and modifiers
        cleaned = norm_text
        cleaned = re.sub(r"\b(?:dien|doi|sua|cap nhat|ghi|set|thay|dat|chuyen thanh|chuyen|la|deu la|deu)\b", " ", cleaned)
        cleaned = re.sub(r"\b(?:ck|tm|chuyen khoan|tien mat|banking|cash)\b", " ", cleaned)
        cleaned = re.sub(r"\b(?:ca 2 nam|ca hai nam|ca 2|ca hai|tat ca cac nam|tat ca nam|moi nam|cac nam|nam \d+|20\d\d)\b", " ", cleaned)
        cleaned = re.sub(r"\b(?:stt|so tt|dong|row|#)\s*\d+\b", " ", cleaned)
        cleaned = re.sub(r"\b(?:bang thu|bang chi|thu|chi|quy|hoi)\b", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()

        # If cleaned text contains a person name candidate (1 to 5 tokens, no query words)
        tokens = cleaned.split()
        if 1 <= len(tokens) <= 5 and not any(k in cleaned for k in _QUERY_INDICATORS):
            return cleaned

        return None
