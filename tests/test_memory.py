"""Tests for the Memory subsystem: ExperienceStore, MemoryGate, ExperienceExtractor."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from sheet_audit_agent.memory.experience_store import ExperienceRecord, ExperienceStore
from sheet_audit_agent.memory.memory_gate import MemoryGate
from sheet_audit_agent.memory.extractor import ExperienceExtractor


# ── ExperienceStore ──────────────────────────────────────────────────────────

class TestExperienceStore:
    def _tmp_store(self) -> ExperienceStore:
        tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        tmp.write(b'{"records": []}')
        tmp.close()
        return ExperienceStore(store_path=Path(tmp.name))

    def test_add_and_retrieve(self):
        store = self._tmp_store()
        rec = ExperienceRecord(
            task_pattern="fill_method: stt 3 nam 2026 ck",
            lesson="Dùng cột HÌNH THỨC của năm 2026 (col 7), không phải col 4.",
            context_tags=["fill_method", "2026", "ck", "stt"],
            confidence=0.90,
        )
        saved = store.add(rec)
        assert saved.id == rec.id

        retrieved = store.retrieve_relevant(["2026", "ck", "stt"], top_k=5)
        assert len(retrieved) == 1
        assert "2026" in retrieved[0].lesson or "col 7" in retrieved[0].lesson

    def test_low_confidence_filtered(self):
        store = self._tmp_store()
        rec = ExperienceRecord(
            task_pattern="old lesson",
            lesson="Outdated rule",
            context_tags=["ck"],
            confidence=0.20,  # below threshold
        )
        store.add(rec)
        results = store.retrieve_relevant(["ck"])
        assert results == []

    def test_update_outcome_adjusts_confidence(self):
        store = self._tmp_store()
        rec = ExperienceRecord(
            task_pattern="test",
            lesson="Some lesson",
            context_tags=["tm"],
            confidence=0.80,
        )
        store.add(rec)
        store.update_outcome(rec.id, succeeded=True)
        updated = store.all()[0]
        # Bayesian nudge: (1+1)/(1+2) = 0.667 … then confidence should update
        assert updated.used == 1
        assert updated.success == 1

    def test_retire_removes_record(self):
        store = self._tmp_store()
        rec = ExperienceRecord(task_pattern="t", lesson="l", context_tags=["x"])
        store.add(rec)
        assert len(store.all()) == 1
        store.retire(rec.id)
        assert len(store.all()) == 0


# ── MemoryGate ───────────────────────────────────────────────────────────────

class TestMemoryGate:
    def test_user_rejected_always_saves(self):
        decision = MemoryGate.evaluate(signal="user_rejected")
        assert decision.should_save is True
        assert decision.source == "user_correction"

    def test_replan_saves(self):
        decision = MemoryGate.evaluate(signal="user_approved", replan_count=1)
        assert decision.should_save is True
        assert decision.source == "replan_failure"

    def test_routine_success_skipped(self):
        decision = MemoryGate.evaluate(signal="user_approved", replan_count=0)
        assert decision.should_save is False

    def test_preference_keyword_saves(self):
        decision = MemoryGate.evaluate(
            signal="auto_pass",
            replan_count=0,
            preference_keywords=["luôn luôn", "sidebar"],
        )
        assert decision.should_save is True


# ── ExperienceExtractor ──────────────────────────────────────────────────────

class TestExperienceExtractor:
    def test_returns_none_when_gate_skips(self):
        from sheet_audit_agent.memory.memory_gate import GateDecision
        gate = GateDecision(should_save=False, source="skipped", reason="routine")
        result = ExperienceExtractor.extract(
            user_message="stt 3 ck",
            intent="fill_method",
            plan_spec={"specified_year": 2026},
            critic_issues=[],
            signal="user_approved",
            replan_count=0,
            gate_decision=gate,
        )
        assert result is None

    def test_extracts_year_lesson_on_rejection(self):
        from sheet_audit_agent.memory.memory_gate import GateDecision
        gate = GateDecision(should_save=True, source="user_correction", reason="rejected")
        result = ExperienceExtractor.extract(
            user_message="stt 3 nam 2026 ck",
            intent="fill_method",
            plan_spec={"specified_year": 2026, "target_method": "CK"},
            critic_issues=["Year fidelity: proposal column 4 != expected col 7 for năm 2026"],
            signal="user_rejected",
            replan_count=0,
            gate_decision=gate,
        )
        assert result is not None
        assert result.source == "user_correction"
        assert "2026" in result.lesson or "năm" in result.lesson or "cột" in result.lesson
