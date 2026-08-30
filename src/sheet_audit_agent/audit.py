"""Top-level sheet audit use case."""

from sheet_audit_agent.matching import detect_duplicates, normalize_text
from sheet_audit_agent.models import AuditReport, FindingCandidate, SheetSnapshot
from sheet_audit_agent.structure import detect_regions


def audit_sheet(snapshot: SheetSnapshot) -> AuditReport:
    detection = detect_regions(snapshot)
    cells = {(cell.row, cell.column): cell for cell in snapshot.cells}
    findings = []
    for region in detection.regions:
        for audit_column in region.audit_columns:
            candidates = []
            for row in range(region.start_row, region.end_row):
                source = cells.get((row, audit_column.column))
                original = source.formatted_value if source is not None else ""
                normalized = normalize_text(original)
                if not normalized:
                    continue
                related = {
                    f"column_{column}": cells[(row, column)].formatted_value
                    for column in range(region.start_column, region.end_column)
                    if (row, column) in cells and column != audit_column.column
                }
                candidates.append(
                    FindingCandidate(
                        row=row,
                        column=audit_column.column,
                        original_value=original,
                        normalized_value=normalized,
                        related_values=related,
                    )
                )
            findings.extend(detect_duplicates(candidates))
    status = "partial" if detection.partial else ("findings" if findings else "clean")
    return AuditReport(
        snapshot_revision=snapshot.revision,
        status=status,
        inspected_regions=detection.regions,
        skipped_regions=detection.skipped_regions,
        findings=findings,
    )
