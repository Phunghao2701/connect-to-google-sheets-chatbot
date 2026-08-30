"""BM25 Index: keyword-frequency scoring for sheet records (zero-dependency)."""

from __future__ import annotations

import math
from typing import Any


class BM25Index:
    """
    Pure-Python BM25 (Okapi BM25) over a corpus of semantic_text strings.
    No external dependencies — uses built-in collections only.

    Parameters
    ----------
    k1 : float
        Controls term frequency saturation (default 1.5).
    b  : float
        Controls document length normalization (default 0.75).
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self._corpus: list[dict[str, Any]] = []
        self._tokenized: list[list[str]] = []
        self._idf: dict[str, float] = {}
        self._avg_dl: float = 0.0

    def build(self, documents: list[dict[str, Any]], text_field: str = "semantic_text") -> None:
        """Build index from a list of record dicts."""
        self._corpus = documents
        self._tokenized = [
            self._tokenize(doc.get(text_field, "")) for doc in documents
        ]
        self._avg_dl = (
            sum(len(toks) for toks in self._tokenized) / max(len(self._tokenized), 1)
        )
        self._idf = self._compute_idf()

    def _tokenize(self, text: str) -> list[str]:
        return text.lower().split()

    def _compute_idf(self) -> dict[str, float]:
        n = len(self._tokenized)
        df: dict[str, int] = {}
        for toks in self._tokenized:
            for tok in set(toks):
                df[tok] = df.get(tok, 0) + 1
        idf: dict[str, float] = {}
        for term, freq in df.items():
            idf[term] = math.log((n - freq + 0.5) / (freq + 0.5) + 1)
        return idf

    def score(self, query_tokens: list[str], doc_idx: int) -> float:
        """Compute BM25 score for a single document."""
        doc_toks = self._tokenized[doc_idx]
        dl = len(doc_toks)
        score = 0.0
        tf_map: dict[str, int] = {}
        for tok in doc_toks:
            tf_map[tok] = tf_map.get(tok, 0) + 1

        for qt in query_tokens:
            if qt not in self._idf:
                continue
            tf = tf_map.get(qt, 0)
            idf = self._idf[qt]
            numerator = tf * (self.k1 + 1)
            denominator = tf + self.k1 * (1 - self.b + self.b * dl / max(self._avg_dl, 1))
            score += idf * numerator / max(denominator, 1e-9)
        return score

    def rank(self, query: str, top_k: int = 10) -> list[tuple[float, dict[str, Any]]]:
        """Return top-k documents with their BM25 scores."""
        q_toks = self._tokenize(query)
        scored: list[tuple[float, dict[str, Any]]] = []
        for i, doc in enumerate(self._corpus):
            s = self.score(q_toks, i)
            if s > 0:
                scored.append((s, doc))
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[:top_k]
