"""Memory Gate: decides whether a feedback signal is worth persisting as a lesson."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

FeedbackSignal = Literal["user_approved", "user_rejected", "replan_failure", "auto_pass"]


@dataclass
class GateDecision:
    should_save: bool
    source: str
    reason: str


class MemoryGate:
    """
    Filters feedback signals to only persist high-value lessons.

    Save when:
    - User explicitly rejected / corrected the agent  -> user_correction
    - Agent needed >1 replan to get it right         -> replan_failure
    - User explicitly stated a preference             -> user_preference
    - Same approach succeeded 3+ times consecutively -> confirmed_pattern
    Do NOT save:
    - Routine successes on first attempt
    - Generic greetings / queries with no action
    - Duplicate patterns already in store
    """

    @staticmethod
    def evaluate(
        signal: FeedbackSignal,
        replan_count: int = 0,
        has_proposals: bool = False,
        preference_keywords: list[str] | None = None,
        existing_pattern_ids: list[str] | None = None,
        task_pattern: str = "",
    ) -> GateDecision:
        pref_kw = preference_keywords or []
        existing = existing_pattern_ids or []

        # 1. User explicitly rejected
        if signal == "user_rejected":
            return GateDecision(
                should_save=True,
                source="user_correction",
                reason="User rejected agent proposal — lesson worth saving.",
            )

        # 2. Agent had to replan
        if replan_count > 0 and signal in ("user_approved", "auto_pass"):
            return GateDecision(
                should_save=True,
                source="replan_failure",
                reason=f"Needed {replan_count} replan(s) before success.",
            )

        # 3. Explicit preference signal
        preference_triggers = [
            "thích", "muốn", "luôn luôn", "đừng", "không muốn",
            "prefer", "always", "never", "instead of",
        ]
        if any(kw in pref_kw for kw in preference_triggers):
            return GateDecision(
                should_save=True,
                source="user_preference",
                reason="User expressed an explicit preference.",
            )

        # 4. Routine success — do NOT save (avoid memory noise)
        return GateDecision(
            should_save=False,
            source="skipped",
            reason="Routine success on first attempt — no lesson needed.",
        )
