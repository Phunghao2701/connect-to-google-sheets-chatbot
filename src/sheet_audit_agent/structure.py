"""Detect supported THU and CHI regions in a sheet snapshot."""

from sheet_audit_agent.matching import normalize_text
from sheet_audit_agent.models import (
    AuditColumn,
    DetectedRegion,
    DetectionResult,
    SheetSnapshot,
    SkippedRegion,
)

_AUDIT_HEADERS = {
    "ho va ten": ("THU", "person-name"),
    "noi dung chi": ("CHI", "expense-content"),
    "khoan chi": ("CHI", "expense-content"),
}


def detect_regions(snapshot: SheetSnapshot) -> DetectionResult:
    values = {(cell.row, cell.column): normalize_text(cell.formatted_value) for cell in snapshot.cells}
    raw_regions: list[dict] = []
    skipped: list[SkippedRegion] = []
    partial = not snapshot.complete

    for (header_row, column), value in sorted(values.items()):
        definition = _AUDIT_HEADERS.get(value)
        if definition is None:
            continue
        kind, semantic = definition
        total_row = next(
            (row for row in range(header_row + 1, snapshot.row_count) if values.get((row, column)) == "tong"),
            None,
        )
        if total_row is None:
            populated_rows = [row for (row, col), text in values.items() if col == column and row > header_row and text]
            total_row = max(populated_rows, default=header_row) + 1
            confidence = 0.7
            partial = True
            skipped.append(
                SkippedRegion(range=f"R{header_row + 1}C{column + 1}", reason="Không tìm thấy hàng TỔNG.")
            )
        else:
            confidence = 1.0
        start_column = 0 if kind == "THU" else max(0, column - 1)
        raw_regions.append({
            "id": f"{kind.lower()}:{header_row}:{column}",
            "kind": kind,
            "header_row": header_row,
            "start_row": header_row + 1,
            "end_row": total_row,
            "start_column": start_column,
            "audit_columns": [AuditColumn(column=column, label=value, semantic=semantic)],
            "confidence": confidence,
        })

    if not raw_regions:
        partial = True
        skipped.append(SkippedRegion(range="sheet", reason="Không nhận diện được bảng THU hoặc CHI."))
        return DetectionResult(regions=[], skipped_regions=skipped, partial=partial)

    # Sort regions by start_column and calculate non-overlapping end_column bounds
    raw_regions.sort(key=lambda r: r["start_column"])
    regions: list[DetectedRegion] = []
    for i, r_dict in enumerate(raw_regions):
        if i + 1 < len(raw_regions):
            end_col = raw_regions[i + 1]["start_column"]
        else:
            end_col = snapshot.column_count

        regions.append(
            DetectedRegion(
                id=r_dict["id"],
                kind=r_dict["kind"],
                header_row=r_dict["header_row"],
                start_row=r_dict["start_row"],
                end_row=r_dict["end_row"],
                start_column=r_dict["start_column"],
                end_column=end_col,
                audit_columns=r_dict["audit_columns"],
                confidence=r_dict["confidence"],
            )
        )

    return DetectionResult(regions=regions, skipped_regions=skipped, partial=partial)
