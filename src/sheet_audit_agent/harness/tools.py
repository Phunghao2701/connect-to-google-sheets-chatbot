"""Structured tool definitions for Agent Harness."""

from typing import Literal
from pydantic import BaseModel, Field


class FillMethodAction(BaseModel):
    """Action to fill the payment method column (TM/CK) for a specific row."""
    row: int = Field(description="0-indexed row index on sheet")
    column: int = Field(description="0-indexed column index of method")
    row_label: str = Field(description="User-friendly label e.g. STT #2 (Nguyễn Tất Châu)")
    current_value: str = Field(default="", description="Current value of the cell")
    proposed_value: Literal["TM", "CK"] = Field(description="Target method value TM or CK")
    explanation: str = Field(description="Short rationale for the change")


class CorrectNameAction(BaseModel):
    """Action to correct or standardize a member name or expense content."""
    row: int = Field(description="0-indexed row index on sheet")
    column: int = Field(description="0-indexed column index")
    row_label: str = Field(description="Label e.g. Dòng 4")
    current_value: str = Field(description="Original value")
    proposed_value: str = Field(description="Standardized replacement value")
    explanation: str = Field(description="Reason for correction")


class ToolResult(BaseModel):
    actions: list[FillMethodAction | CorrectNameAction] = Field(default_factory=list)
    reply_text: str = Field(default="")
