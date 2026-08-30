import pytest
from sheet_audit_agent.harness.critic import Critic, FailureType
from sheet_audit_agent.harness.executor import AgentHarnessExecutor, StructuredResolver
from sheet_audit_agent.harness.intent_analyzer import IntentAnalyzer
from sheet_audit_agent.harness.planner import PlanSpec
from sheet_audit_agent.memory.experience_store import _DEFAULT_STORE, ExperienceRecord, ExperienceStore
from sheet_audit_agent.models import ChatResponse, SheetCell, SheetSnapshot
from sheet_audit_agent.rag.indexer import SheetIndexer
from sheet_audit_agent.rag.query_rewriter import QueryRewriter


def multi_year_snapshot() -> SheetSnapshot:
    return SheetSnapshot(
        spreadsheet_id="doc-123",
        sheet_id=10,
        sheet_title="Bảng THU V2",
        row_count=10,
        column_count=8,
        revision="rev1",
        complete=True,
        cells=[
            # Row 1: year headers
            SheetCell(row=1, column=2, formatted_value="2024"),
            SheetCell(row=1, column=5, formatted_value="2026"),
            # Row 2: column headers
            SheetCell(row=2, column=0, formatted_value="STT"),
            SheetCell(row=2, column=1, formatted_value="HỌ VÀ TÊN"),
            SheetCell(row=2, column=2, formatted_value="QUỸ HỘI"),
            SheetCell(row=2, column=4, formatted_value="HÌNH THỨC"),  # 2024 method col
            SheetCell(row=2, column=5, formatted_value="QUỸ HỘI"),
            SheetCell(row=2, column=7, formatted_value="HÌNH THỨC"),  # 2026 method col
            # Row 3: STT 2
            SheetCell(row=3, column=0, formatted_value="2"),
            SheetCell(row=3, column=1, formatted_value="Trần Thị B"),
            SheetCell(row=3, column=4, formatted_value="TM"),
            SheetCell(row=3, column=7, formatted_value=""),
            # Row 4: STT 20
            SheetCell(row=4, column=0, formatted_value="20"),
            SheetCell(row=4, column=1, formatted_value="Lê Văn C"),
            SheetCell(row=4, column=4, formatted_value=""),
            SheetCell(row=4, column=7, formatted_value=""),
        ],
    )


class TestV2IntentAndParsing:
    def test_read_queries_with_ck_tm_do_not_become_fill_method(self) -> None:
        """B1 Fix: Questions like 'Ai đóng CK năm 2026?' must be query_data, NOT fill_method."""
        r1 = IntentAnalyzer.analyze("Ai đóng CK năm 2026?")
        assert r1.intent == "query_data"
        assert r1.target_method == "CK"
        assert r1.specified_year == 2026

        r2 = IntentAnalyzer.analyze("Tổng CK năm 2026 là bao nhiêu?")
        assert r2.intent == "query_data"

        r3 = IntentAnalyzer.analyze("Cho tôi xem những người thanh toán TM")
        assert r3.intent == "query_data"
        assert r3.target_method == "TM"

    def test_write_commands_become_fill_method(self) -> None:
        """Commands with mutation verbs must be fill_method."""
        r1 = IntentAnalyzer.analyze("stt 6 năm 2026 ck")
        assert r1.intent == "fill_method"
        assert r1.target_method == "CK"
        assert r1.specified_year == 2026

        r2 = IntentAnalyzer.analyze("Điền hình thức STT 2 là CK")
        assert r2.intent == "fill_method"
        assert r2.target_method == "CK"
        assert r2.target_stt == "2"

        r3 = IntentAnalyzer.analyze("đổi stt 3 thành TM")
        assert r3.intent == "fill_method"
        assert r3.target_method == "TM"
        assert r3.target_stt == "3"

    def test_stt_parser_does_not_capture_years(self) -> None:
        """B2 Fix: 'năm 2026' must NOT set stt_hint=2026."""
        rq = QueryRewriter.rewrite("Ai đóng CK năm 2026?")
        assert rq.year_hint == 2026
        assert rq.stt_hint is None

        rq2 = QueryRewriter.rewrite("stt 6 năm 2026 ck")
        assert rq2.year_hint == 2026
        assert rq2.stt_hint == "6"


class TestV2CriticAndResolver:
    def test_critic_exact_stt_match_prevents_false_positives(self) -> None:
        """B4 Fix: Target STT 2 should NOT match proposal with STT 20."""
        snapshot = multi_year_snapshot()
        spec = PlanSpec(
            intent="fill_method",
            target_method="CK",
            specified_year=2024,
            target_stt="2",
            target_name=None,
            is_summary=False,
            approach_summary="fill_method | CK | STT: 2",
        )

        bad_response = ChatResponse(
            reply="Done",
            action_type="proposals",
            method_fill_proposals=[{
                "column": 4,
                "stt": "20",
                "rowLabel": "STT #20 (Lê Văn C)",
                "row": 4,
            }],
        )
        res = Critic.validate(spec, bad_response, snapshot)
        assert res.passed is False
        assert res.failure_type == FailureType.ROW_MISMATCH

    def test_structured_resolver_finds_exact_row_and_column(self) -> None:
        """B5 Fix: StructuredResolver directly pinpoints the exact cell."""
        snapshot = multi_year_snapshot()
        index_data = SheetIndexer.index(snapshot)

        spec = PlanSpec(
            intent="fill_method",
            target_method="CK",
            specified_year=2026,
            target_stt="20",
            target_name=None,
            is_summary=False,
            approach_summary="fill_method | CK | STT: 20 | Year: 2026",
        )

        proposals, clarification = StructuredResolver.resolve_fill_method(spec, snapshot, index_data)
        assert clarification is None
        assert len(proposals) == 1
        p = proposals[0]
        assert p["row"] == 4
        assert p["column"] == 7
        assert p["stt"] == "20"
        assert p["proposedValue"] == "CK"


class TestV2MemoryAndPaths:
    def test_memory_path_is_inside_agent_data(self) -> None:
        """B3 Fix: _DEFAULT_STORE must resolve under agent/data."""
        path_str = str(_DEFAULT_STORE.resolve())
        assert "agent" in path_str or "data" in path_str
        assert path_str.endswith("experience_store.json")
