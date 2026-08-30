"""Normalization and deterministic duplicate matching."""

from collections import defaultdict
from collections.abc import Iterable
import re
from typing import Literal
import unicodedata

from sheet_audit_agent.models import AuditFinding, FindingCandidate

TYPO_THRESHOLD = 0.90
_SEPARATORS = re.compile(r"[.,\-_]+")
_WHITESPACE = re.compile(r"\s+")


def normalize_text(value: str) -> str:
    """Return a comparison key without changing the source value."""
    decomposed = unicodedata.normalize("NFD", value.strip().replace("Đ", "D").replace("đ", "d"))
    without_marks = "".join(char for char in decomposed if unicodedata.category(char) != "Mn")
    separated = _SEPARATORS.sub(" ", without_marks.lower())
    return _WHITESPACE.sub(" ", separated).strip()


def levenshtein_similarity(left: str, right: str) -> float:
    if left == right:
        return 1.0
    if not left or not right:
        return 0.0
    previous = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_char in enumerate(right, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[right_index] + 1,
                    previous[right_index - 1] + (left_char != right_char),
                )
            )
        previous = current
    return 1 - previous[-1] / max(len(left), len(right))


def _abbreviation_match(left: str, right: str) -> bool:
    left_tokens = left.split()
    right_tokens = right.split()
    if len(left_tokens) != len(right_tokens) or left_tokens == right_tokens:
        return False
    has_abbreviation = False
    for left_token, right_token in zip(left_tokens, right_tokens, strict=True):
        if left_token == right_token:
            continue
        if len(left_token) == 1 and right_token.startswith(left_token):
            has_abbreviation = True
            continue
        if len(right_token) == 1 and left_token.startswith(right_token):
            has_abbreviation = True
            continue
        return False
    return has_abbreviation


def _typo_compatible(left: str, right: str) -> bool:
    if min(len(left), len(right)) < 4:
        return False
    left_tokens, right_tokens = left.split(), right.split()
    if not left_tokens or not right_tokens:
        return False
    return left_tokens[0] == right_tokens[0] and left_tokens[-1] == right_tokens[-1]


def _components(edges: list[tuple[int, int]], count: int) -> list[list[int]]:
    adjacency: dict[int, set[int]] = defaultdict(set)
    for left, right in edges:
        adjacency[left].add(right)
        adjacency[right].add(left)
    components: list[list[int]] = []
    visited: set[int] = set()
    for start in range(count):
        if start in visited or start not in adjacency:
            continue
        stack = [start]
        component: list[int] = []
        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            component.append(current)
            stack.extend(adjacency[current] - visited)
        components.append(sorted(component))
    return components


def detect_duplicates(candidates: Iterable[FindingCandidate]) -> list[AuditFinding]:
    values = sorted(candidates, key=lambda item: (item.row, item.column))
    findings: list[AuditFinding] = []
    exact_groups: dict[str, list[FindingCandidate]] = defaultdict(list)
    for candidate in values:
        if candidate.normalized_value:
            exact_groups[candidate.normalized_value].append(candidate)
    exact_pairs: set[tuple[int, int]] = set()
    for key, group in exact_groups.items():
        if len(group) < 2:
            continue
        indexes = [values.index(item) for item in group]
        exact_pairs.update((min(a, b), max(a, b)) for a in indexes for b in indexes if a != b)
        findings.append(_finding("exact", 1.0, "Cùng giá trị sau chuẩn hóa.", group, key))

    abbreviation_edges: list[tuple[int, int]] = []
    typo_pairs: list[tuple[int, int, float]] = []
    for left_index, left in enumerate(values):
        for right_index in range(left_index + 1, len(values)):
            right = values[right_index]
            if (left_index, right_index) in exact_pairs:
                continue
            if _abbreviation_match(left.normalized_value, right.normalized_value):
                abbreviation_edges.append((left_index, right_index))
                continue
            score = levenshtein_similarity(left.normalized_value, right.normalized_value)
            if score >= TYPO_THRESHOLD and _typo_compatible(left.normalized_value, right.normalized_value):
                typo_pairs.append((left_index, right_index, score))

    for component in _components(abbreviation_edges, len(values)):
        group = [values[index] for index in component]
        findings.append(
            _finding(
                "possible-abbreviation",
                0.95,
                "Tên viết tắt tương thích với một hoặc nhiều tên đầy đủ.",
                group,
                group[0].normalized_value,
            )
        )
    for left_index, right_index, score in typo_pairs:
        group = [values[left_index], values[right_index]]
        findings.append(
            _finding(
                "possible-typo",
                score,
                "Giá trị khác một số ít ký tự và vượt ngưỡng tương đồng 0.90.",
                group,
                group[0].normalized_value,
            )
        )
    return sorted(findings, key=lambda item: min(candidate.row for candidate in item.candidates))


def _finding(
    classification: Literal["exact", "possible-typo", "possible-abbreviation"],
    confidence: float,
    explanation: str,
    candidates: list[FindingCandidate],
    key: str,
) -> AuditFinding:
    unique_suggestions = list(dict.fromkeys(item.original_value for item in candidates))
    first = min(candidates, key=lambda item: (item.row, item.column))
    return AuditFinding(
        id=f"{classification}:{first.row}:{first.column}:{key}",
        classification=classification,
        confidence=confidence,
        explanation=explanation,
        candidates=candidates,
        suggested_values=unique_suggestions,
    )
