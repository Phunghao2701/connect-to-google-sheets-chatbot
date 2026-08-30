import pytest
from sheet_audit_agent.harness.executor import AgentHarnessExecutor
from sheet_audit_agent.harness.critic import Critic
from sheet_audit_agent.harness.planner import PlanSpec
from sheet_audit_agent.models import ChatResponse, SheetCell, SheetSnapshot


def sample_snapshot() -> SheetSnapshot:
    return SheetSnapshot(
        spreadsheet_id="test-doc",
        sheet_id=1,
        sheet_title="Bảng THU",
        row_count=6,
        column_count=5,
        revision="r1",
        complete=True,
        cells=[
            SheetCell(row=0, column=0, formatted_value="THU"),
            SheetCell(row=1, column=1, formatted_value="HỌ VÀ TÊN"),
            SheetCell(row=1, column=2, formatted_value="QUỸ HỘI"),
            SheetCell(row=1, column=4, formatted_value="HÌNH THỨC"),
            SheetCell(row=2, column=0, formatted_value="1"),
            SheetCell(row=2, column=1, formatted_value="Nguyễn Văn An"),
            SheetCell(row=2, column=2, formatted_value="500000"),
            SheetCell(row=2, column=4, formatted_value="TM"),
            SheetCell(row=3, column=0, formatted_value="2"),
            SheetCell(row=3, column=1, formatted_value="Nguyễn Tất Châu"),
            SheetCell(row=3, column=2, formatted_value="500000"),
            SheetCell(row=3, column=4, formatted_value=""),
            SheetCell(row=4, column=1, formatted_value="TỔNG"),
        ],
    )


def sample_multi_year_snapshot() -> SheetSnapshot:
    """Snapshot with year 2024 and 2026 columns (NO 2027)."""
    return SheetSnapshot(
        spreadsheet_id="test-doc-multi",
        sheet_id=2,
        sheet_title="Bảng THU",
        row_count=6,
        column_count=8,
        revision="r1",
        complete=True,
        cells=[
            SheetCell(row=1, column=2, formatted_value="2024"),
            SheetCell(row=1, column=5, formatted_value="2026"),
            SheetCell(row=2, column=0, formatted_value="STT"),
            SheetCell(row=2, column=1, formatted_value="HỌ VÀ TÊN"),
            SheetCell(row=2, column=2, formatted_value="QUỸ HỘI"),
            SheetCell(row=2, column=3, formatted_value="QUỸ KHÁC"),
            SheetCell(row=2, column=4, formatted_value="HÌNH THỨC"),
            SheetCell(row=2, column=5, formatted_value="QUỸ HỘI"),
            SheetCell(row=2, column=6, formatted_value="QUỸ KHÁC"),
            SheetCell(row=2, column=7, formatted_value="HÌNH THỨC"),
            SheetCell(row=3, column=0, formatted_value="6"),
            SheetCell(row=3, column=1, formatted_value="Nguyễn văn Minh"),
            SheetCell(row=3, column=4, formatted_value="TM"),
            SheetCell(row=3, column=7, formatted_value=""),
        ],
    )


@pytest.mark.anyio
async def test_harness_generates_method_proposal_from_command() -> None:
    snapshot = sample_snapshot()
    response = await AgentHarnessExecutor.process_chat(
        message="STT 2 là CK",
        snapshot=snapshot,
    )
    assert response.action_type == "proposals"
    assert len(response.method_fill_proposals) == 1
    proposal = response.method_fill_proposals[0]
    assert proposal["row"] == 3
    assert proposal["proposedValue"] == "CK"
    assert "Nguyễn Tất Châu" in proposal["rowLabel"]
    # New: reply should be the clean template, not verbose LLM text
    assert "✅" in response.reply
    assert "Phê duyệt" in response.reply


@pytest.mark.anyio
async def test_harness_handles_general_question() -> None:
    snapshot = sample_snapshot()
    response = await AgentHarnessExecutor.process_chat(
        message="Xin chào trợ lý",
        snapshot=snapshot,
    )
    assert len(response.reply) > 0
    assert response.action_type == "text"


@pytest.mark.anyio
async def test_harness_rejects_nonexistent_year() -> None:
    """Year 2027 does not exist → must return error message, NO proposals."""
    snapshot = sample_multi_year_snapshot()
    response = await AgentHarnessExecutor.process_chat(
        message="stt 6 năm 2027 ck",
        snapshot=snapshot,
    )
    assert response.method_fill_proposals == []
    assert response.action_type == "text"
    # Reply must mention 2027 is invalid OR list valid years
    reply_lower = response.reply.lower()
    assert "2027" in reply_lower or "2024" in reply_lower or "2026" in reply_lower


@pytest.mark.anyio
async def test_harness_accepts_valid_year_2026() -> None:
    """Year 2026 exists → should generate a proposal for col 7."""
    snapshot = sample_multi_year_snapshot()
    response = await AgentHarnessExecutor.process_chat(
        message="stt 6 năm 2026 ck",
        snapshot=snapshot,
    )
    assert response.action_type == "proposals"
    assert len(response.method_fill_proposals) >= 1
    p = response.method_fill_proposals[0]
    assert p["column"] == 7
    assert p["proposedValue"] == "CK"


def test_critic_flags_invalid_year() -> None:
    """Critic.validate must immediately fail when year does not exist in sheet."""
    snapshot = sample_multi_year_snapshot()
    spec = PlanSpec(
        intent="fill_method",
        target_method="CK",
        specified_year=2027,
        target_stt="6",
        target_name=None,
        is_summary=False,
        approach_summary="fill_method | CK | Năm: 2027",
    )
    response = ChatResponse(
        reply="Done",
        action_type="proposals",
        method_fill_proposals=[{"column": 4, "rowLabel": "STT #6", "row": 3}],
    )
    result = Critic.validate(spec, response, snapshot)
    assert result.passed is False
    assert any("2027" in issue for issue in result.issues)
