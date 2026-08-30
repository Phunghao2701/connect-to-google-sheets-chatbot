from sheet_audit_agent.models import SheetCell, SheetSnapshot
from sheet_audit_agent.structure import detect_regions


def cell(row: int, column: int, value: str) -> SheetCell:
    return SheetCell(row=row, column=column, formatted_value=value)


def test_detects_thu_and_chi_in_the_same_sheet() -> None:
    snapshot = SheetSnapshot(
        spreadsheet_id="book",
        sheet_id=10,
        sheet_title="Sheet1",
        row_count=20,
        column_count=16,
        revision="r1",
        complete=True,
        cells=[
            cell(0, 0, "THU"),
            cell(1, 0, "STT"),
            cell(1, 1, "HỌ VÀ TÊN"),
            cell(4, 1, "TỔNG"),
            cell(0, 9, "CHI"),
            cell(1, 9, "STT"),
            cell(1, 10, "NỘI DUNG CHI"),
            cell(4, 10, "TỔNG"),
        ],
    )

    result = detect_regions(snapshot)

    assert [region.kind for region in result.regions] == ["THU", "CHI"]
    assert [region.audit_columns[0].column for region in result.regions] == [1, 10]
    assert result.partial is False


def test_missing_total_marks_detection_partial() -> None:
    snapshot = SheetSnapshot(
        spreadsheet_id="book",
        sheet_id=10,
        sheet_title="Sheet1",
        row_count=5,
        column_count=3,
        revision="r1",
        complete=True,
        cells=[cell(0, 0, "THU"), cell(1, 1, "HO VA TEN"), cell(2, 1, "An")],
    )

    result = detect_regions(snapshot)

    assert result.partial is True
    assert result.regions[0].confidence < 1

