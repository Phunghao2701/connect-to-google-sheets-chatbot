"""Query Rewriter: normalize and expand Vietnamese query for better retrieval."""

from __future__ import annotations

import unicodedata
import re

# Vietnamese synonym/abbreviation expansions for the fund-management domain
_SYNONYMS: dict[str, list[str]] = {
    "ck": ["chuyển khoản", "banking", "transfer"],
    "tm": ["tiền mặt", "cash"],
    "stt": ["số thứ tự", "dòng", "row"],
    "tổng": ["total", "sum", "tổng cộng"],
    "quy": ["quỹ", "fund"],
    "hoi": ["hội", "association"],
    "thu": ["thu chi", "bảng thu", "income"],
    "chi": ["chi tiêu", "expense", "bảng chi"],
    "dong": ["đóng", "nộp", "pay"],
    "nam": ["năm", "year"],
    "nguoi": ["người", "thành viên", "member"],
}

# Diacritics strip map for normalization (correctly handles đ/Đ)
def _strip_diacritics(text: str) -> str:
    replaced = text.replace("Đ", "D").replace("đ", "d")
    nfkd = unicodedata.normalize("NFKD", replaced)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


class QueryRewriter:
    """
    Rewrites a raw Vietnamese user query into:
    - normalized form (lowercase, stripped diacritics)
    - expanded form (synonyms added)
    - extracted metadata hints (year, stt, method, intent signals)
    """

    @classmethod
    def rewrite(cls, query: str) -> "RewrittenQuery":
        lowered = query.lower().strip()
        normalized = _strip_diacritics(lowered)

        # Expand synonyms
        tokens = normalized.split()
        expanded_tokens: list[str] = []
        for tok in tokens:
            expanded_tokens.append(tok)
            if tok in _SYNONYMS:
                expanded_tokens.extend(_SYNONYMS[tok])

        expanded = " ".join(expanded_tokens)

        # Extract year hint
        year_match = re.search(r"\b(20\d{2})\b", normalized)
        year_hint: int | None = int(year_match.group(1)) if year_match else None

        # Extract STT hint — prefix is REQUIRED to avoid capturing years as STT
        # Matches: "stt 6", "#3", "dong 2", "row 1" — NOT bare "2026"
        stt_match = re.search(r"(?:(?:\bstt\b|\bdong\b|\brow\b|#)\s*)(\d+)\b", normalized)
        stt_hint: str | None = stt_match.group(1) if stt_match else None

        # Extract method hint
        method_hint: str | None = None
        if re.search(r"\b(ck|chuyen khoan|banking|transfer)\b", normalized):
            method_hint = "CK"
        elif re.search(r"\b(tm|tien mat|cash)\b", normalized):
            method_hint = "TM"

        # Detect all-years / multi-year modifier (e.g. "cả 2 năm", "cả hai năm", "tất cả các năm", "mọi năm")
        all_years_hint = bool(re.search(
            r"\b(?:ca 2 nam|ca hai nam|ca 2|ca hai|tat ca cac nam|tat ca nam|moi nam|cac nam)\b",
            normalized,
        ))

        # Detect summary intent
        is_summary = any(k in normalized for k in [
            "tong", "bao nhieu", "thong ke", "chi tieu", "quy", "tổng",
            "how many", "total", "sum",
        ])

        return RewrittenQuery(
            original=query,
            normalized=normalized,
            expanded=expanded,
            year_hint=year_hint,
            stt_hint=stt_hint,
            method_hint=method_hint,
            all_years_hint=all_years_hint,
            is_summary=is_summary,
            tokens=set(expanded.split()),
        )


class RewrittenQuery:
    """Result of QueryRewriter.rewrite()."""

    def __init__(
        self,
        original: str,
        normalized: str,
        expanded: str,
        year_hint: int | None,
        stt_hint: str | None,
        method_hint: str | None,
        all_years_hint: bool,
        is_summary: bool,
        tokens: set[str],
    ) -> None:
        self.original = original
        self.normalized = normalized
        self.expanded = expanded
        self.year_hint = year_hint
        self.stt_hint = stt_hint
        self.method_hint = method_hint
        self.all_years_hint = all_years_hint
        self.is_summary = is_summary
        self.tokens = tokens

