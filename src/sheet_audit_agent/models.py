"""Typed contracts shared by the audit core and HTTP boundary."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ImmutableModel(BaseModel):
    model_config = ConfigDict(frozen=True)


class SheetCell(ImmutableModel):
    row: int = Field(ge=0)
    column: int = Field(ge=0)
    formatted_value: str = ""
    user_entered_value: str | int | float | bool | None = None


class SheetSnapshot(ImmutableModel):
    spreadsheet_id: str
    sheet_id: int
    sheet_title: str
    row_count: int = Field(ge=0)
    column_count: int = Field(ge=0)
    revision: str
    complete: bool
    cells: list[SheetCell]


class AuditColumn(ImmutableModel):
    column: int
    label: str
    semantic: Literal["person-name", "expense-content"]


class DetectedRegion(ImmutableModel):
    id: str
    kind: Literal["THU", "CHI", "UNKNOWN"]
    header_row: int
    start_row: int
    end_row: int
    start_column: int
    end_column: int
    audit_columns: list[AuditColumn]
    confidence: float = Field(ge=0, le=1)


class SkippedRegion(ImmutableModel):
    range: str
    reason: str


class DetectionResult(ImmutableModel):
    regions: list[DetectedRegion]
    skipped_regions: list[SkippedRegion]
    partial: bool


class FindingCandidate(ImmutableModel):
    row: int
    column: int
    original_value: str
    normalized_value: str
    related_values: dict[str, str] = Field(default_factory=dict)


class AuditFinding(ImmutableModel):
    id: str
    classification: Literal["exact", "possible-typo", "possible-abbreviation"]
    confidence: float = Field(ge=0, le=1)
    explanation: str
    candidates: list[FindingCandidate]
    suggested_values: list[str]


class AuditReport(ImmutableModel):
    snapshot_revision: str
    status: Literal["clean", "findings", "partial"]
    inspected_regions: list[DetectedRegion]
    skipped_regions: list[SkippedRegion]
    findings: list[AuditFinding]


class ChatRequest(ImmutableModel):
    message: str
    snapshot: SheetSnapshot | None = None
    session_id: str | None = None


class ChatResponse(ImmutableModel):
    reply: str
    action_type: str = "text"
    method_fill_proposals: list[dict[str, str | int]] = Field(default_factory=list)

