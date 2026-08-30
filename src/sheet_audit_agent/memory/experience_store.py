"""Experience Store: persistent JSON-backed CRUD for lesson records."""

from __future__ import annotations

import json
import uuid
from datetime import date
from pathlib import Path
from typing import Any

# Default path relative to package root (can be overridden via env)
_DEFAULT_STORE = Path(__file__).parents[4] / "data" / "experience_store.json"


class ExperienceRecord:
    """One lesson learned by the agent from a past task."""

    def __init__(
        self,
        task_pattern: str,
        lesson: str,
        context_tags: list[str] | None = None,
        approach: str = "",
        failure: str = "",
        root_cause: str = "",
        source: str = "auto",
        confidence: float = 0.80,
        record_id: str | None = None,
        used: int = 0,
        success: int = 0,
        last_used: str | None = None,
    ) -> None:
        self.id = record_id or str(uuid.uuid4())[:8]
        self.task_pattern = task_pattern
        self.context_tags: list[str] = context_tags or []
        self.approach = approach
        self.failure = failure
        self.root_cause = root_cause
        self.lesson = lesson
        self.source = source  # user_correction | replan_failure | confirmed_pattern | user_preference
        self.confidence = confidence
        self.used = used
        self.success = success
        self.last_used = last_used or str(date.today())

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "task_pattern": self.task_pattern,
            "context_tags": self.context_tags,
            "approach": self.approach,
            "failure": self.failure,
            "root_cause": self.root_cause,
            "lesson": self.lesson,
            "source": self.source,
            "confidence": round(self.confidence, 4),
            "used": self.used,
            "success": self.success,
            "last_used": self.last_used,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExperienceRecord":
        return cls(
            task_pattern=data.get("task_pattern", ""),
            lesson=data.get("lesson", ""),
            context_tags=data.get("context_tags", []),
            approach=data.get("approach", ""),
            failure=data.get("failure", ""),
            root_cause=data.get("root_cause", ""),
            source=data.get("source", "auto"),
            confidence=float(data.get("confidence", 0.80)),
            record_id=data.get("id"),
            used=int(data.get("used", 0)),
            success=int(data.get("success", 0)),
            last_used=data.get("last_used"),
        )


class ExperienceStore:
    """JSON-backed persistent store for experience records."""

    def __init__(self, store_path: Path | None = None) -> None:
        self._path = store_path or _DEFAULT_STORE
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._path.write_text(json.dumps({"records": []}), encoding="utf-8")

    def _load(self) -> list[dict[str, Any]]:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return data.get("records", [])
        except (json.JSONDecodeError, OSError):
            return []

    def _save(self, records: list[dict[str, Any]]) -> None:
        self._path.write_text(
            json.dumps({"records": records}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def add(self, record: ExperienceRecord) -> ExperienceRecord:
        """Persist a new record; returns the saved record."""
        records = self._load()
        records.append(record.to_dict())
        self._save(records)
        return record

    def update_outcome(self, record_id: str, succeeded: bool) -> None:
        """Increment usage stats and adjust confidence based on outcome."""
        records = self._load()
        for r in records:
            if r["id"] == record_id:
                r["used"] = r.get("used", 0) + 1
                if succeeded:
                    r["success"] = r.get("success", 0) + 1
                r["last_used"] = str(date.today())
                # Bayesian-style confidence nudge
                total = r["used"]
                successes = r["success"]
                r["confidence"] = round((successes + 1) / (total + 2), 4)
                break
        self._save(records)

    def retire(self, record_id: str) -> None:
        """Remove a lesson that consistently fails (confidence too low)."""
        records = [r for r in self._load() if r["id"] != record_id]
        self._save(records)

    def retrieve_relevant(self, tags: list[str], top_k: int = 5) -> list[ExperienceRecord]:
        """Retrieve lessons whose context_tags overlap with the given tags."""
        norm_tags = {t.lower() for t in tags}
        scored: list[tuple[float, ExperienceRecord]] = []
        for raw in self._load():
            rec = ExperienceRecord.from_dict(raw)
            if rec.confidence < 0.30:
                continue  # Skip retired/low-confidence lessons
            rec_tags = {t.lower() for t in rec.context_tags}
            overlap = len(norm_tags & rec_tags)
            if overlap > 0:
                score = overlap * rec.confidence
                scored.append((score, rec))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [rec for _, rec in scored[:top_k]]

    def all(self) -> list[ExperienceRecord]:
        return [ExperienceRecord.from_dict(r) for r in self._load()]
