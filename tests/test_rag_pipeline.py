"""Tests for RAG pipeline: QueryRewriter, BM25, Reranker, SheetRetriever."""

from __future__ import annotations

import pytest

from sheet_audit_agent.rag.query_rewriter import QueryRewriter
from sheet_audit_agent.rag.bm25_index import BM25Index
from sheet_audit_agent.rag.reranker import Reranker


# ── QueryRewriter ─────────────────────────────────────────────────────────────

class TestQueryRewriter:
    def test_year_extraction(self):
        rq = QueryRewriter.rewrite("stt 3 nam 2026 ck")
        assert rq.year_hint == 2026

    def test_no_year(self):
        rq = QueryRewriter.rewrite("stt 5 tm")
        assert rq.year_hint is None

    def test_method_hint_ck(self):
        rq = QueryRewriter.rewrite("STT 2 CK")
        assert rq.method_hint == "CK"

    def test_method_hint_tm(self):
        rq = QueryRewriter.rewrite("tien mat stt 1")
        assert rq.method_hint == "TM"

    def test_summary_intent(self):
        rq = QueryRewriter.rewrite("tổng thu năm 2026 là bao nhiêu?")
        assert rq.is_summary is True

    def test_stt_hint(self):
        rq = QueryRewriter.rewrite("stt 7 ck")
        assert rq.stt_hint == "7"

    def test_synonym_expansion(self):
        rq = QueryRewriter.rewrite("ck")
        # expanded should contain synonym text
        assert "chuyen khoan" in rq.expanded or "banking" in rq.expanded


# ── BM25Index ─────────────────────────────────────────────────────────────────

class TestBM25Index:
    _CORPUS = [
        {"semantic_text": "Nguyen Van A STT 1 quy hoi 2024 hinh thuc CK"},
        {"semantic_text": "Tran Thi B STT 2 quy khac 2026 hinh thuc TM"},
        {"semantic_text": "Tổng thu quy hoi năm 2026 là 1,500,000"},
    ]

    def test_builds_without_error(self):
        idx = BM25Index()
        idx.build(self._CORPUS)
        assert idx._avg_dl > 0

    def test_ranks_relevant_first(self):
        idx = BM25Index()
        idx.build(self._CORPUS)
        results = idx.rank("CK 2024 STT 1", top_k=3)
        assert results[0][1]["semantic_text"].startswith("Nguyen Van A")

    def test_no_match_returns_empty(self):
        idx = BM25Index()
        idx.build(self._CORPUS)
        results = idx.rank("xyz_nonexistent_token", top_k=3)
        assert results == []


# ── Reranker ──────────────────────────────────────────────────────────────────

class TestReranker:
    def test_metadata_year_boost(self):
        rq = QueryRewriter.rewrite("stt 1 nam 2026 ck")
        candidates = [
            {"semantic_text": "Nguyen Van A STT 1 2026 CK", "type": "member", "stt": "1", "year": 2026},
            {"semantic_text": "Tran Thi B STT 1 2024 TM", "type": "member", "stt": "1", "year": 2024},
        ]
        bm25_scores = {0: 1.0, 1: 1.0}  # equal BM25
        results = Reranker.rerank(candidates, bm25_scores, rq, top_k=2)
        # The 2026 candidate should rank first due to year metadata bonus
        assert results[0]["year"] == 2026

    def test_summary_priority_when_summary_query(self):
        rq = QueryRewriter.rewrite("tổng thu là bao nhiêu")
        candidates = [
            {"semantic_text": "Nguyen Van A STT 1 CK", "type": "member", "year": None},
            {"semantic_text": "Tổng thu: 2,000,000", "type": "summary", "year": None},
        ]
        bm25_scores = {0: 0.5, 1: 0.5}
        results = Reranker.rerank(candidates, bm25_scores, rq, top_k=2)
        assert results[0]["type"] == "summary"
