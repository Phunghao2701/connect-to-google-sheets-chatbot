from sheet_audit_agent.models import SheetCell, SheetSnapshot
from sheet_audit_agent.rag.indexer import SheetIndexer
from sheet_audit_agent.rag.retriever import SheetRetriever


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


def test_indexer_extracts_members() -> None:
    snapshot = sample_snapshot()
    index_data = SheetIndexer.index(snapshot)

    assert index_data["total_records"] == 2
    assert len(index_data["members"]) == 2
    assert index_data["members"][0]["name"] == "Nguyễn Văn An"
    assert index_data["members"][1]["name"] == "Nguyễn Tất Châu"


def test_retriever_finds_by_stt() -> None:
    snapshot = sample_snapshot()
    index_data = SheetIndexer.index(snapshot)

    results = SheetRetriever.retrieve(index_data, "STT 2 là CK")
    assert len(results) >= 1
    assert results[0]["name"] == "Nguyễn Tất Châu"


def test_retriever_finds_by_name() -> None:
    snapshot = sample_snapshot()
    index_data = SheetIndexer.index(snapshot)

    results = SheetRetriever.retrieve(index_data, "Nguyễn Văn An")
    assert len(results) >= 1
    assert results[0]["name"] == "Nguyễn Văn An"
