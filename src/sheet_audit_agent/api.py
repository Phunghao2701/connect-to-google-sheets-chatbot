"""FastAPI transport connecting RAG System, Agent Harness, and Ollama Brain."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from sheet_audit_agent.audit import audit_sheet
from sheet_audit_agent.harness.executor import AgentHarnessExecutor, _experience_store
from sheet_audit_agent.memory.extractor import ExperienceExtractor
from sheet_audit_agent.memory.memory_gate import MemoryGate
from sheet_audit_agent.models import AuditReport, ChatRequest, ChatResponse, SheetSnapshot


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    os.environ[key.strip()] = val.strip()
    except Exception:
        pass


# Load .env file natively
env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_env_file(env_path)


class FeedbackPayload(BaseModel):
    session_id: str
    proposal_id: str | None = None
    signal: Literal["user_approved", "user_rejected", "auto_pass"] = "auto_pass"
    user_message: str = ""
    intent: str = "fill_method"
    plan_spec: dict = {}
    critic_issues: list[str] = []
    replan_count: int = 0
    user_note: str = ""


def create_app() -> FastAPI:
    app = FastAPI(title="Sheet Audit Agent — Self-Learning", version="0.3.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": "0.3.0"}

    @app.post("/v1/audits", response_model=AuditReport)
    async def audit(payload: SheetSnapshot) -> AuditReport:
        return audit_sheet(payload)

    @app.post("/v1/chat", response_model=ChatResponse)
    async def chat(payload: ChatRequest) -> ChatResponse:
        load_env_file(env_path)
        return await AgentHarnessExecutor.process_chat(
            message=payload.message,
            snapshot=payload.snapshot,
            session_id=getattr(payload, "session_id", None),
        )

    @app.post("/v1/feedback")
    async def feedback(payload: FeedbackPayload) -> dict[str, str]:
        """Receive user approve/reject signal and persist lesson if valuable."""
        gate_decision = MemoryGate.evaluate(
            signal=payload.signal,
            replan_count=payload.replan_count,
            has_proposals=bool(payload.proposal_id),
            preference_keywords=payload.user_message.lower().split(),
        )
        record = ExperienceExtractor.extract(
            user_message=payload.user_message,
            intent=payload.intent,
            plan_spec=payload.plan_spec,
            critic_issues=payload.critic_issues,
            signal=payload.signal,
            replan_count=payload.replan_count,
            gate_decision=gate_decision,
            user_note=payload.user_note,
        )
        if record:
            _experience_store.add(record)
            return {"status": "saved", "lesson_id": record.id}
        return {"status": "skipped", "reason": gate_decision.reason}

    @app.get("/v1/memory")
    async def get_memory() -> dict:
        """Debug endpoint to inspect all stored lessons."""
        records = _experience_store.all()
        return {
            "count": len(records),
            "lessons": [r.to_dict() for r in records],
        }

    return app


app = create_app()
