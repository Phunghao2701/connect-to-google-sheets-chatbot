"""Hybrid Retriever: QueryRewriter → BM25 + TokenOverlap → Reranker → Context."""

from __future__ import annotations

from typing import Any

from sheet_audit_agent.rag.bm25_index import BM25Index
from sheet_audit_agent.rag.query_rewriter import QueryRewriter, RewrittenQuery
from sheet_audit_agent.rag.reranker import Reranker


class SheetRetriever:
    """Pipeline: rewrite → BM25+token hybrid → rerank → return top-k."""

    @staticmethod
    def retrieve(
        index_data: dict[str, Any],
        query: str,
        top_k: int = 8,
        lesson_tags: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Full retrieval pipeline.

        Parameters
        ----------
        index_data   : output of SheetIndexer.index()
        query        : raw user message
        top_k        : max results to return
        lesson_tags  : tags from retrieved Experience lessons (boosts relevant docs)
        """
        rq: RewrittenQuery = QueryRewriter.rewrite(query)

        if not rq.expanded:
            return []

        # Gather all candidates from the index
        candidates: list[dict[str, Any]] = (
            index_data.get("summaries", [])
            + index_data.get("members", [])
            + index_data.get("expenses", [])
        )

        if not candidates:
            return []

        # --- Stage 1: BM25 over expanded query ---
        bm25 = BM25Index()
        bm25.build(candidates)
        bm25_ranked = bm25.rank(rq.expanded, top_k=len(candidates))
        bm25_score_map: dict[int, float] = {}
        for score, doc in bm25_ranked:
            # Map back to original index position
            for i, c in enumerate(candidates):
                if c is doc:
                    bm25_score_map[i] = score
                    break

        # --- Stage 2: Metadata filter — hard remove mismatched years ---
        filtered: list[dict[str, Any]] = []
        for i, doc in enumerate(candidates):
            doc_year = doc.get("year")
            # Keep if no year hint, or doc has no year, or years match
            if rq.year_hint and doc_year and doc_year != rq.year_hint:
                if doc.get("type") != "summary":  # Always keep summaries
                    bm25_score_map.pop(i, None)
                    continue
            filtered.append(doc)

        # Rebuild index map after filter
        filtered_score_map: dict[int, float] = {}
        for new_i, doc in enumerate(filtered):
            old_i = candidates.index(doc)
            filtered_score_map[new_i] = bm25_score_map.get(old_i, 0.0)

        # --- Stage 3: Rerank ---
        reranked = Reranker.rerank(
            candidates=filtered,
            bm25_scores=filtered_score_map,
            rq=rq,
            lesson_tags=lesson_tags,
            top_k=top_k,
        )

        return reranked

    @staticmethod
    def format_context_for_prompt(retrieved_items: list[dict[str, Any]]) -> str:
        if not retrieved_items:
            return "Không có dữ liệu dòng nào khớp với từ khóa trong sheet."
        lines = ["Dữ liệu ngữ cảnh liên quan từ Google Sheets:"]
        for idx, item in enumerate(retrieved_items, start=1):
            lines.append(f"{idx}. {item['semantic_text']}")
        return "\n".join(lines)
