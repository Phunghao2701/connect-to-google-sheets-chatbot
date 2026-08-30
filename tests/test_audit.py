from sheet_audit_agent.audit import audit_sheet
from sheet_audit_agent.models import SheetCell, SheetSnapshot


def cell(row: int, column: int, value: str) -> SheetCell:
    return SheetCell(row=row, column=column, formatted_value=value)


def snapshot(*values: str, complete: bool = True) -> SheetSnapshot:
    cells = [cell(0, 0, "THU"), cell(1, 1, "HỌ VÀ TÊN")]
    cells.extend(cell(index + 2, 1, value) for index, value in enumerate(values))
    cells.append(cell(len(values) + 2, 1, "TỔNG"))
    return SheetSnapshot(
        spreadsheet_id="book",
        sheet_id=10,
        sheet_title="Sheet1",
        row_count=len(values) + 3,
        column_count=6,
        revision="revision-1",
        complete=complete,
        cells=cells,
    )


def test_exact_duplicate_has_confidence_one() -> None:
    report = audit_sheet(snapshot("Nguyễn Văn An", " NGUYEN-VAN-AN "))

    assert report.status == "findings"
    assert len(report.findings) == 1
    assert report.findings[0].classification == "exact"
    assert report.findings[0].confidence == 1


def test_abbreviation_returns_all_matching_candidates() -> None:
    report = audit_sheet(snapshot("Nguyễn V. An", "Nguyễn Văn An", "Nguyễn Việt An"))

    finding = next(item for item in report.findings if item.classification == "possible-abbreviation")
    assert {candidate.original_value for candidate in finding.candidates} == {
        "Nguyễn V. An",
        "Nguyễn Văn An",
        "Nguyễn Việt An",
    }


def test_typo_at_high_similarity_is_reported_but_short_values_are_not() -> None:
    report = audit_sheet(snapshot("Nguyễn Văn An", "Nguyễn Vă An", "An", "Am"))

    assert any(item.classification == "possible-typo" for item in report.findings)
    assert not any(
        {candidate.original_value for candidate in item.candidates} == {"An", "Am"}
        for item in report.findings
    )


def test_incomplete_snapshot_never_reports_clean() -> None:
    report = audit_sheet(snapshot("An", "Bình", complete=False))

    assert report.status == "partial"


def test_clean_complete_snapshot_reports_clean() -> None:
    report = audit_sheet(snapshot("Nguyễn Văn An", "Trần Thị Bình"))

    assert report.status == "clean"
