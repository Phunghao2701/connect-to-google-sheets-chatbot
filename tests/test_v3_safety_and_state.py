import pytest
from sheet_audit_agent.harness.context_resolver import ConversationContextResolver
from sheet_audit_agent.harness.executor import AgentHarnessExecutor, StructuredResolver, _working_memory, _pending_actions
from sheet_audit_agent.harness.intent_analyzer import IntentAnalyzer
from sheet_audit_agent.harness.planner import PlanSpec
from sheet_audit_agent.models import SheetCell, SheetSnapshot
from sheet_audit_agent.rag.indexer import SheetIndexer
from sheet_audit_agent.structure import detect_regions


def create_dual_region_sheet() -> SheetSnapshot:
    """
    Creates a sheet with distinct THU (cols 0-4) and CHI (cols 5-9).
    THU: 2024 (col 3), 2026 (col 4)
    CHI: 2024 (col 8), 2026 (col 9)
    """
    return SheetSnapshot(
        spreadsheet_id="dual-region-doc",
        sheet_id=1,
        sheet_title="Bảng THU & CHI Hội Đồng Hương",
        row_count=10,
        column_count=10,
        revision="r1",
        complete=True,
        cells=[
            # Row 0: Super-headers
            SheetCell(row=0, column=0, formatted_value="THU"),
            SheetCell(row=0, column=5, formatted_value="CHI"),
            # Row 1: Year headers
            SheetCell(row=1, column=2, formatted_value="2024"),
            SheetCell(row=1, column=4, formatted_value="2026"),
            SheetCell(row=1, column=7, formatted_value="2024"),
            SheetCell(row=1, column=9, formatted_value="2026"),
            # Row 2: Column Sub-headers
            SheetCell(row=2, column=0, formatted_value="STT"),
            SheetCell(row=2, column=1, formatted_value="HỌ VÀ TÊN"),
            SheetCell(row=2, column=2, formatted_value="QUỸ HỘI"),
            SheetCell(row=2, column=3, formatted_value="HÌNH THỨC"),  # THU 2024 -> col 3
            SheetCell(row=2, column=4, formatted_value="HÌNH THỨC"),  # THU 2026 -> col 4
            SheetCell(row=2, column=5, formatted_value="STT"),
            SheetCell(row=2, column=6, formatted_value="NỘI DUNG CHI"),
            SheetCell(row=2, column=7, formatted_value="SỐ TIỀN"),
            SheetCell(row=2, column=8, formatted_value="HÌNH THỨC"),  # CHI 2024 -> col 8
            SheetCell(row=2, column=9, formatted_value="HÌNH THỨC"),  # CHI 2026 -> col 9
            # Row 3: Data row (Alice in THU, Mua nước in CHI)
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


class TestP0RegionColumnScoping:
    def test_region_boundaries_do_not_overlap(self) -> None:
        snapshot = create_dual_region_sheet()
        det = detect_regions(snapshot)
        assert len(det.regions) == 2
        thu_reg = next(r for r in det.regions if r.kind == "THU")
        chi_reg = next(r for r in det.regions if r.kind == "CHI")

        # THU ends where CHI starts (col 5)
        assert thu_reg.start_column == 0
        assert thu_reg.end_column == chi_reg.start_column
        assert chi_reg.end_column == snapshot.column_count

    def test_thu_proposal_writes_to_thu_column_not_chi(self) -> None:
        """P0 #1 Fix: THU target STT 2 Year 2026 MUST write to column 4, NOT column 9."""
        snapshot = create_dual_region_sheet()
        index_data = SheetIndexer.index(snapshot)

        spec = PlanSpec(
            intent="fill_method",
            target_method="CK",
            specified_year=2026,
            target_stt="2",
            target_name=None,
            target_region="THU",
            approach_summary="fill_method | CK | STT: 2 | Year: 2026 | THU",
        )

        proposals, clarification = StructuredResolver.resolve_fill_method(spec, snapshot, index_data)
        assert clarification is None
        assert len(proposals) == 1
        p = proposals[0]
        assert "Alice Nguyen" in p["rowLabel"]
        assert p["row"] == 3
        # MUST BE THU 2026 column (4), NEVER CHI 2026 column (9)!
        assert p["column"] == 4
        assert p["proposedValue"] == "CK"

    def test_chi_proposal_writes_to_chi_column_not_thu(self) -> None:
        """CHI target STT 2 Year 2026 MUST write to column 9, NOT column 4."""
        snapshot = create_dual_region_sheet()
        index_data = SheetIndexer.index(snapshot)

        spec = PlanSpec(
            intent="fill_method",
            target_method="CK",
            specified_year=2026,
            target_stt="2",
            target_name=None,
            target_region="CHI",
            approach_summary="fill_method | CK | STT: 2 | Year: 2026 | CHI",
        )

        proposals, clarification = StructuredResolver.resolve_fill_method(spec, snapshot, index_data)
        assert clarification is None
        assert len(proposals) == 1
        p = proposals[0]
        assert "Mua nước uống" in p["rowLabel"]
        assert p["row"] == 3
        assert p["column"] == 9
        assert p["proposedValue"] == "CK"


class TestP0RAGDataBoundaryIsolation:
    def test_member_does_not_contain_expense_data(self) -> None:
        """P0 #2 Fix: Member semantic data and payment_by_year must not mix with CHI."""
        snapshot = create_dual_region_sheet()
        index_data = SheetIndexer.index(snapshot)

        members = index_data.get("members", [])
        alice = next(m for m in members if "Alice" in m["name"])
        payment_2024 = alice["payment_by_year"][2024]

        # QUỸ HỘI is present
        assert payment_2024.get("QUỸ HỘI") == "500000"
        assert payment_2024.get("method") == "TM"
        # CHI fields MUST NOT be present in Alice's payment_by_year
        assert "SỐ TIỀN" not in payment_2024
        assert "NỘI DUNG CHI" not in payment_2024
        assert "Mua nước uống" not in alice["semantic_text"]


class TestP0StrictReadWriteSeparation:
    @pytest.mark.anyio
    async def test_read_queries_never_generate_proposals(self) -> None:
        """P0 #3 Fix: 'STT 2 đóng CK năm 2026 là ai?' MUST NEVER generate write proposals."""
        snapshot = create_dual_region_sheet()
        response = await AgentHarnessExecutor.process_chat(
            message="STT 2 đóng CK năm 2026 là ai?",
            snapshot=snapshot,
        )

        assert response.action_type != "proposals"
        assert response.method_fill_proposals == []

    def test_payment_method_intent_without_question_is_fill_method(self) -> None:
        """'đổi hình thức thanh toán STT 2 năm 2026 thành CK' must be fill_method, not query_data."""
        intent = IntentAnalyzer.analyze("đổi hình thức thanh toán STT 2 năm 2026 thành CK")
        assert intent.intent == "fill_method"
        assert intent.target_method == "CK"
        assert intent.target_stt == "2"
        assert intent.specified_year == 2026


class TestP1ConversationalStateMachine:
    @pytest.mark.anyio
    async def test_multi_turn_year_clarification_flow(self) -> None:
        """
        Turn 1: 'đổi STT 2 thành CK' (when multiple years exist) -> Bot asks which year.
        Turn 2: '2026' -> ContextResolver merges pending action and completes write.
        """
        snapshot = create_dual_region_sheet()
        session_id = "test-session-year-flow"
        _working_memory.pop(session_id, None)
        _pending_actions.pop(session_id, None)

        # Turn 1
        resp1 = await AgentHarnessExecutor.process_chat(
            message="đổi STT 2 thành CK",
            snapshot=snapshot,
            session_id=session_id,
        )
        assert resp1.action_type == "clarification"
        assert _pending_actions.get(session_id) is not None
        assert _pending_actions[session_id]["missing"] == "year"

        # Turn 2: User provides only the year
        resp2 = await AgentHarnessExecutor.process_chat(
            message="2026",
            snapshot=snapshot,
            session_id=session_id,
        )
        # Because STT 2 exists in both THU and CHI for 2026, bot now asks region clarification or generates proposal
        assert "2026" in resp2.reply or resp2.action_type in ("clarification", "proposals")

    @pytest.mark.anyio
    async def test_multi_turn_region_clarification_flow(self) -> None:
        """
        Turn 1: 'STT 2 năm 2026 là CK' (exists in both THU & CHI) -> Bot asks which table.
        Turn 2: 'THU' -> Proposal created for Alice Nguyen in THU (column 4).
        """
        snapshot = create_dual_region_sheet()
        session_id = "test-session-region-flow"
        _working_memory.pop(session_id, None)
        _pending_actions.pop(session_id, None)

        # Turn 1
        resp1 = await AgentHarnessExecutor.process_chat(
            message="STT 2 năm 2026 là CK",
            snapshot=snapshot,
            session_id=session_id,
        )
        assert resp1.action_type == "clarification"
        assert "THU" in resp1.reply and "CHI" in resp1.reply
        assert _pending_actions.get(session_id) is not None
        assert _pending_actions[session_id]["missing"] == "region"

        # Turn 2: User specifies "bảng THU"
        resp2 = await AgentHarnessExecutor.process_chat(
            message="bảng THU",
            snapshot=snapshot,
            session_id=session_id,
        )
        assert resp2.action_type == "proposals"
        assert len(resp2.method_fill_proposals) == 1
        p = resp2.method_fill_proposals[0]
        assert "Alice Nguyen" in p["rowLabel"]
        assert p["column"] == 4


class TestAllYearsAndNameMatching:
    def test_all_years_intent_detection(self) -> None:
        intent = IntentAnalyzer.analyze("Nguyễn tất Châu cả 2 năm đều là tm")
        assert intent.intent == "fill_method"
        assert intent.target_method == "TM"
        assert intent.all_years is True
        assert intent.target_name == "nguyen tat chau"

    @pytest.mark.anyio
    async def test_all_years_generates_proposals_for_each_year_without_clarification(self) -> None:
        """
        When user specifies 'cả 2 năm đều là TM', proposals must be created for BOTH 2024 and 2026,
        and MUST NOT match unrelated short names like 'Hà' (row 33).
        """
        # Sheet with STT 2 = Nguyen Tat Chau, STT 33 = Ha
        snapshot = SheetSnapshot(
            spreadsheet_id="all-years-doc",
            sheet_id=1,
            sheet_title="Bảng THU Hội",
            row_count=10,
            column_count=5,
            revision="r1",
            complete=True,
            cells=[
                SheetCell(row=0, column=0, formatted_value="THU"),
                SheetCell(row=1, column=3, formatted_value="2024"),
                SheetCell(row=1, column=4, formatted_value="2026"),
                SheetCell(row=2, column=0, formatted_value="STT"),
                SheetCell(row=2, column=1, formatted_value="HỌ VÀ TÊN"),
                SheetCell(row=2, column=2, formatted_value="QUỸ HỘI"),
                SheetCell(row=2, column=3, formatted_value="HÌNH THỨC"),  # 2024 -> col 3
                SheetCell(row=2, column=4, formatted_value="HÌNH THỨC"),  # 2026 -> col 4
                # Row 3: Nguyen Tat Chau
                SheetCell(row=3, column=0, formatted_value="2"),
                SheetCell(row=3, column=1, formatted_value="Nguyễn tất Châu"),
                SheetCell(row=3, column=2, formatted_value="500000"),
                SheetCell(row=3, column=3, formatted_value=""),
                SheetCell(row=3, column=4, formatted_value=""),
                # Row 4: Ha (STT 33)
                SheetCell(row=4, column=0, formatted_value="33"),
                SheetCell(row=4, column=1, formatted_value="Hà"),
                SheetCell(row=4, column=2, formatted_value="500000"),
                SheetCell(row=4, column=3, formatted_value=""),
                SheetCell(row=4, column=4, formatted_value=""),
            ],
        )

        response = await AgentHarnessExecutor.process_chat(
            message="Nguyễn tất Châu cả 2 năm đều là tm",
            snapshot=snapshot,
        )

        assert response.action_type == "proposals"
        assert len(response.method_fill_proposals) == 2
        # Proposal 1: 2024 -> col 3
        p1 = next(p for p in response.method_fill_proposals if "2024" in p["rowLabel"])
        assert p1["column"] == 3
        assert p1["proposedValue"] == "TM"
        assert "Nguyễn tất Châu" in p1["rowLabel"]

        # Proposal 2: 2026 -> col 4
        p2 = next(p for p in response.method_fill_proposals if "2026" in p["rowLabel"])
        assert p2["column"] == 4
        assert p2["proposedValue"] == "TM"
        assert "Nguyễn tất Châu" in p2["rowLabel"]

        # Ensure Ha (STT 33) is NEVER matched
        assert not any("Hà" in p["rowLabel"] or p["stt"] == "33" for p in response.method_fill_proposals)
