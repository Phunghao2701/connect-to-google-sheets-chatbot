"""AutoEvaluator: scores each request and appends to eval_log.jsonl."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sheet_audit_agent.harness.critic import CriticResult
from sheet_audit_agent.harness.planner import PlanSpec
from sheet_audit_agent.models import ChatResponse

_EVAL_LOG = Path(__file__).parents[4] / "data" / "evals" / "eval_log.jsonl"


class AutoEvaluator:
    """
    Records a structured eval entry after every request.
    Entries are appended to eval_log.jsonl for later analysis.
    """

    @staticmethod
    def log(
        session_id: str,
        user_message: str,
        spec: PlanSpec,
        response: ChatResponse,
        critic: CriticResult,
        replan_count: int,
        latency_ms: float,
    ) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "session_id": session_id,
            "user_message": user_message[:200],
            "intent": spec.intent,
            "specified_year": spec.specified_year,
            "target_stt": spec.target_stt,
            "target_method": spec.target_method,
            "proposals_count": len(response.method_fill_proposals or []),
            "critic_passed": critic.passed,
            "critic_confidence": critic.confidence,
            "critic_issues": critic.issues,
            "replan_count": replan_count,
            "latency_ms": round(latency_ms, 1),
            "memory_lessons_used": len(spec.memory_lessons),
        }
        try:
            _EVAL_LOG.parent.mkdir(parents=True, exist_ok=True)
            with _EVAL_LOG.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            pass
        return entry
