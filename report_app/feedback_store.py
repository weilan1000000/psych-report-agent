from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ALLOWED_DECISIONS = {
    "confirmed_issue",
    "false_positive",
    "manual_revision",
    "targeted_regeneration",
}
RESOLVED_DECISIONS = {"false_positive", "manual_revision"}
MAX_NOTE_LENGTH = 4000
MAX_REPLACEMENT_LENGTH = 12000


def _redact(value: Any, limit: int) -> str:
    text = str(value or "").strip()[:limit]
    return re.sub(r"sk-[A-Za-z0-9_-]{8,}", "[REDACTED_API_KEY]", text)


class FeedbackStore:
    """Append-only local audit log for reviewer decisions.

    These events are review evidence. They are deliberately not a live RAG source.
    """

    def __init__(self, job_root: Path) -> None:
        self.job_root = job_root.resolve()
        self.job_root.mkdir(parents=True, exist_ok=True)
        self.path = self.job_root / "human_feedback.jsonl"
        self._lock = threading.RLock()

    def append(
        self,
        *,
        job_id: str,
        item_id: str,
        filename: str,
        stage: str,
        issue: dict[str, Any],
        decision: str,
        note: str = "",
        replacement_text: str = "",
        reviewer: str = "",
    ) -> dict[str, Any]:
        decision = str(decision or "").strip()
        if decision not in ALLOWED_DECISIONS:
            raise ValueError(f"unsupported feedback decision: {decision}")
        issue_id = str(issue.get("issue_id") or "").strip()
        if not issue_id:
            raise ValueError("feedback issue_id is required")
        event = {
            "event_id": f"fb_{uuid.uuid4().hex[:16]}",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "job_id": str(job_id),
            "item_id": str(item_id),
            "filename": Path(str(filename)).name,
            "stage": str(stage),
            "issue_id": issue_id,
            "issue": issue,
            "decision": decision,
            "note": _redact(note, MAX_NOTE_LENGTH),
            "replacement_text": _redact(replacement_text, MAX_REPLACEMENT_LENGTH),
            "reviewer": _redact(reviewer, 80),
            "learning_status": "pending_distillation",
        }
        with self._lock:
            with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        return event

    def load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        events: list[dict[str, Any]] = []
        with self._lock:
            for line in self.path.read_text(encoding="utf-8").splitlines():
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict):
                    events.append(value)
        return events

    def summary(self, *, item_id: str, issue_ids: list[str]) -> dict[str, Any]:
        relevant = [event for event in self.load() if event.get("item_id") == item_id]
        latest: dict[str, dict[str, Any]] = {}
        counts: dict[str, int] = {}
        for event in relevant:
            decision = str(event.get("decision") or "")
            counts[decision] = counts.get(decision, 0) + 1
            issue_id = str(event.get("issue_id") or "")
            if issue_id:
                latest[issue_id] = event
        resolved = {
            issue_id
            for issue_id, event in latest.items()
            if event.get("decision") in RESOLVED_DECISIONS
        }
        known = set(issue_ids)
        return {
            "event_count": len(relevant),
            "decision_counts": counts,
            "reviewed_issue_count": len(set(latest) & known),
            "resolved_issue_count": len(resolved & known),
            "unresolved_issue_count": len(known - resolved),
            "latest_decisions": {
                issue_id: {
                    "decision": event.get("decision", ""),
                    "note": event.get("note", ""),
                    "replacement_text": event.get("replacement_text", ""),
                    "reviewer": event.get("reviewer", ""),
                    "created_at": event.get("created_at", ""),
                }
                for issue_id, event in latest.items()
                if issue_id in known
            },
            "learning_status": "pending_distillation" if relevant else "not_started",
        }
