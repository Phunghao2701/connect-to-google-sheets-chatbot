"""Reranker: heuristic cross-score combining BM25 + metadata + lesson boost."""

from __future__ import annotations

from typing import Any

from sheet_audit_agent.rag.query_rewriter import RewrittenQuery


class Reranker:
    """
    Combines multiple signals into a final relevance score:

        final = 0.40 * bm25_norm
              + 0.25 * token_overlap_norm
              + 0.20 * metadata_bonus
              + 0.10 * summary_priority
              + 0.05 * lesson_boost

    All components are normalized to [0, 1] before combining.
    """

    @staticmethod
    def rerank(
        candidates: list[dict[str, Any]],
        bm25_scores: dict[int, float],
        rq: RewrittenQuery,
        lesson_tags: set[str] | None = None,
        top_k: int = 8,
    ) -> list[dict[str, Any]]:
        """
        Parameters
        ----------
        candidates   : list of record dicts from the indexer
        bm25_scores  : {original_index: bm25_raw_score}
        rq           : the RewrittenQuery object
        lesson_tags  : context tags from retrieved memory lessons (optional)
        top_k        : how many to return
        """
        lesson_tags = lesson_tags or set()

        # --- normalise bm25 ---
        bm25_vals = list(bm25_scores.values())
        bm25_max = max(bm25_vals) if bm25_vals else 1.0

        scored: list[tuple[float, dict[str, Any]]] = []
        query_tokens = rq.tokens

        for idx, doc in enumerate(candidates):
            # 1. BM25
            bm25_raw = bm25_scores.get(idx, 0.0)
            bm25_norm = bm25_raw / max(bm25_max, 1e-9)

            # 2. Token overlap
            doc_tokens = set(doc.get("semantic_text", "").lower().split())
            overlap = len(query_tokens & doc_tokens)
            token_norm = min(overlap / max(len(query_tokens), 1), 1.0)

            # 3. Metadata bonus
            meta_bonus = 0.0
            doc_year = doc.get("year")
            doc_type = doc.get("type", "")

            if rq.year_hint and doc_year == rq.year_hint:
                meta_bonus += 0.5
            if rq.stt_hint and str(doc.get("stt", "")) == rq.stt_hint:
                meta_bonus += 0.5
            if rq.is_summary and doc_type == "summary":
                meta_bonus += 0.3
            meta_bonus = min(meta_bonus, 1.0)

            # 4. Summary priority
            summary_priority = 0.8 if (rq.is_summary and doc_type == "summary") else 0.0

            # 5. Lesson boost — memory says this doc type / tags are important
            doc_tags = set(str(t).lower() for t in doc.get("context_tags", []))
            lesson_overlap = len(lesson_tags & doc_tags)
            lesson_boost = min(lesson_overlap * 0.25, 1.0)

            final = (
                0.40 * bm25_norm
                + 0.25 * token_norm
                + 0.20 * meta_bonus
                + 0.10 * summary_priority
                + 0.05 * lesson_boost
            )

            if final > 0:
                scored.append((final, doc))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [doc for _, doc in scored[:top_k]]
