"""Safe, test-only task and message sinks for the synthetic fixture lab.

These helpers deliberately have no network, provider, scheduler, or production
task integration.  They write structured records only to a caller-selected
run directory and, for a screen notice, standard output.  Callers give the
functions a fixed schema rather than arbitrary effect payloads.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_FORBIDDEN_FIELD_NAMES = {
    "phone", "phone_number", "email", "endpoint", "url", "secret", "token",
    "authorization", "provider", "recipient_address", "destination",
}


def _assert_safe(value: Any) -> None:
    """Reject raw-delivery shaped data before it reaches a local test log."""
    if isinstance(value, dict):
        forbidden = _FORBIDDEN_FIELD_NAMES.intersection(value)
        if forbidden:
            raise ValueError(f"local test sink rejects delivery-shaped fields: {sorted(forbidden)}")
        for item in value.values():
            _assert_safe(item)
    elif isinstance(value, list):
        for item in value:
            _assert_safe(item)


class LocalRunRecorder:
    """Record safe local task/message observations for one fixture harness run."""

    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir.resolve()
        self.run_dir.mkdir(parents=True, exist_ok=True)

    def _append(self, filename: str, record: dict[str, Any]) -> dict[str, Any]:
        _assert_safe(record)
        path = (self.run_dir / filename).resolve()
        if path.parent != self.run_dir:
            raise ValueError("local test records must stay in the run directory")
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
        return record

    def create_task(self, *, fixture_id: str, case_id: str, task_type: str, status: str) -> dict[str, Any]:
        """Create a test-only task record; it is not queued or assigned."""
        return self._append("local_tasks.jsonl", {
            "fixture_id": fixture_id,
            "case_id": case_id,
            "task_type": task_type,
            "status": status,
            "sink": "local_file",
            "execution": "not_queued",
        })

    def write_message_file(self, *, fixture_id: str, case_id: str, message_type: str, text: str) -> dict[str, Any]:
        """Render a test notice locally; it has no recipient or transport."""
        return self._append("local_messages.jsonl", {
            "fixture_id": fixture_id,
            "case_id": case_id,
            "message_type": message_type,
            "text": text,
            "sink": "local_file",
            "execution": "rendered_not_sent",
        })

    def write_screen(self, *, fixture_id: str, case_id: str, text: str) -> dict[str, Any]:
        """Render a test notice to the screen and record the same local event."""
        record = {
            "fixture_id": fixture_id,
            "case_id": case_id,
            "message_type": "local.screen-notice@1.0.0",
            "text": text,
            "sink": "screen",
            "execution": "rendered_not_sent",
        }
        _assert_safe(record)
        print("LOCAL TEST NOTICE: " + json.dumps(record, sort_keys=True))
        return self._append("local_screen.jsonl", record)
