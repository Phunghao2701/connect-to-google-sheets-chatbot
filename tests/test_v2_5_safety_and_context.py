import pytest
from sheet_audit_agent.harness.context_resolver import ConversationContextResolver
from sheet_audit_agent.harness.executor import AgentHarnessExecutor, StructuredResolver
from sheet_audit_agent.harness.planner import PlanSpec
from sheet_audit_agent.models import SheetCell, SheetSnapshot
from sheet_audit_agent.rag.indexer import SheetIndexer


def dual_region_multi_year_snapshot() -> SheetSnapshot:
    """
    Snapshot containing BOTH a THU table (STT 2 = Alice)
    and a CHI table (STT 2 = Mua nước) across years 2024 and 2026.
    """
    return SheetSnapshot(
        spreadsheet_id="dual-region-doc",
        sheet_id=1,
        sheet_title="Bảng THU & CHI",
        row_count=10,
        column_count=10,
        revision="r1",
        complete=True,
        cells=[
            # Row 0: Table labels
            SheetCell(row=0, column=0, formatted_value="THU"),
            SheetCell(row=0, column=5, formatted_value="CHI"),
            # Row 1: Year headers
            SheetCell(row=1, column=2, formatted_value="2024"),
            SheetCell(row=1, column=4, formatted_value="2026"),
            SheetCell(row=1, column=7, formatted_value="2024"),
            SheetCell(row=1, column=9, formatted_value="2026"),
            # Row 2: Sub-headers
            SheetCell(row=2, column=0, formatted_value="STT"),
            SheetCell(row=2, column=1, formatted_value="HỌ VÀ TÊN"),
            SheetCell(row=2, column=2, formatted_value="QUỸ HỘI"),
            SheetCell(row=2, column=3, formatted_value="HÌNH THỨC"),  # 2024 method
            SheetCell(row=2, column=4, formatted_value="HÌNH THỨC"),  # 2026 method
            SheetCell(row=2, column=5, formatted_value="STT"),
            SheetCell(row=2, column=6, formatted_value="NỘI DUNG CHI"),
            SheetCell(row=2, column=7, formatted_value="SỐ TIỀN"),
            SheetCell(row=2, column=8, formatted_value="HÌNH THỨC"),  # CHI 2024 method
            SheetCell(row=2, column=9, formatted_value="HÌNH THỨC"),  # CHI 2026 method
            # Row 3: Data row (STT 2 in THU = Alice, STT 2 in CHI = Mua nước)
            SheetCell(row=3, column=0, formatted_value="2"),
            SheetCell(row=3, column=1, formatted_value="Alice Nguyen"),
            SheetCell(row=3, column=2, formatted_value="500000"),
            SheetCell(row=3, column=3, formatted_value="TM"),
            SheetCell(row=3, column=4, formatted_value=""),
            SheetCell(row=3, column=5, formatted_value="2"),
            SheetCell(row=3, column=6, formatted_value="Mua nước uống"),
            SheetCell(row=3, column=7, formatted_value="200000"),
            SheetCell(row=3, column=8, formatted_value="TM"),
            SheetCell(row=3, column=9, formatted_value=""),
        ],
    )


class TestWriteSafetyAndAmbiguity:
    @pytest.mark.anyio
    async def test_write_without_year_in_multi_year_sheet_asks_clarification(self) -> None:
        """When multiple years exist (2024, 2026), user says 'đổi STT 2 thành CK' without year -> ask clarification."""
        snapshot = dual_region_multi_year_snapshot()
        response = await AgentHarnessExecutor.process_chat(
            message="đổi STT 2 thành CK",
            snapshot=snapshot,
        )

        assert response.action_type == "clarification"
        assert response.method_fill_proposals == []
        assert "2024" in response.reply and "2026" in response.reply

    def test_region_ambiguity_when_stt_exists_in_both_thu_and_chi(self) -> None:
        """When STT 2 exists in both THU and CHI without region specified, StructuredResolver returns clarification."""
        snapshot = dual_region_multi_year_snapshot()
        index_data = SheetIndexer.index(snapshot)

        spec = PlanSpec(
            intent="fill_method",
            target_method="CK",
            specified_year=2026,
            target_stt="2",
            target_name=None,
            target_region=None,  # Not specified
            approach_summary="fill_method | CK | STT: 2",
        )

        proposals, clarification = StructuredResolver.resolve_fill_method(spec, snapshot, index_data)
        assert proposals == []
        assert clarification is not None
        assert "THU" in clarification and "CHI" in clarification
        assert "Alice Nguyen" in clarification or "Mua nước uống" in clarification

    def test_region_explicit_targets_only_selected_table(self) -> None:
        """When user targets 'THU', only Alice is proposed, not Mua nước."""
        snapshot = dual_region_multi_year_snapshot()
        index_data = SheetIndexer.index(snapshot)

        spec = PlanSpec(
            intent="fill_method",
            target_method="CK",
            specified_year=2026,
            target_stt="2",
            target_name=None,
            target_region="THU",
            approach_summary="fill_method | CK | STT: 2 | THU",
        )

        proposals, clarification = StructuredResolver.resolve_fill_method(spec, snapshot, index_data)
        assert clarification is None
        assert len(proposals) == 1
        assert "Alice Nguyen" in proposals[0]["rowLabel"]
        assert proposals[0]["stt"] == "2"


class TestConversationContextResolver:
    def test_resolves_relative_year_from_history(self) -> None:
        """User asked 2026 before, then asks 'Thế năm trước?' -> resolves to 2025 (or prior available year)."""
        history = [
            {"role": "user", "content": "Cho tôi số liệu năm 2026"},
            {"role": "assistant", "content": "Số liệu năm 2026 gồm có..."},
        ]
        resolved = ConversationContextResolver.resolve(
            current_message="Thế năm trước?",
            history=history,
            available_years=[2024, 2026],
        )

        assert resolved.is_followup is True
        assert resolved.active_year == 2024 or resolved.active_year == 2025
        assert "2024" in resolved.standalone_query or "2025" in resolved.standalone_query

    def test_resolves_stt_continuation_write_command(self) -> None:
        """User said 'STT 2 là CK năm 2026', then said 'Còn STT 3?' -> resolves to STT 3 năm 2026 là CK."""
        history = [
            {"role": "user", "content": "STT 2 là CK năm 2026"},
            {"role": "assistant", "content": "Đã tạo đề xuất cho STT 2..."},
        ]
        resolved = ConversationContextResolver.resolve(
            current_message="Còn STT 3?",
            history=history,
            available_years=[2024, 2026],
        )

        assert resolved.is_followup is True
        assert resolved.active_stt == "3"
        assert resolved.active_method == "CK"
        assert resolved.active_year == 2026


class TestRAGPaymentByYearModel:
    def test_indexer_extracts_structured_payment_by_year(self) -> None:
        snapshot = dual_region_multi_year_snapshot()
        index_data = SheetIndexer.index(snapshot)

        members = index_data.get("members", [])
        assert len(members) >= 1
        alice = next(m for m in members if "Alice" in m["name"])
        assert "payment_by_year" in alice
        assert 2024 in alice["payment_by_year"]
        assert alice["payment_by_year"][2024]["method"] == "TM"
        # Semantic text contains formatted year bullet points
        assert "Năm 2024:" in alice["semantic_text"]
        assert "Hình thức: TM" in alice["semantic_text"]
