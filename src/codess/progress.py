"""Bounded, content-free progress traces for long-running operations."""

from __future__ import annotations

import json
import sys
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any, TextIO


class ProgressTrace:
    """Emit concise live progress and retain the same structured events.

    Callers supply identifiers, counts, sizes, and phase names only.  Transcript
    content must never be passed as a field: these records are operational
    metadata and are persisted in the ingest report.
    """

    def __init__(
        self,
        *,
        stream: TextIO | None = None,
        enabled: bool = True,
        max_events: int = 5000,
    ) -> None:
        self.stream = stream if stream is not None else sys.stderr
        self.enabled = enabled
        self.max_events = max_events
        self.started = time.monotonic()
        self.events: deque[dict[str, Any]] = deque(maxlen=max_events)
        self.dropped_events = 0

    def __call__(self, event: str, **fields: Any) -> dict[str, Any]:
        record = {
            "at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "elapsed_seconds": round(time.monotonic() - self.started, 3),
            "event": event,
            **fields,
        }
        if len(self.events) == self.max_events:
            self.dropped_events += 1
        self.events.append(record)
        if self.enabled:
            rendered = " ".join(
                f"{key}={self._format(value)}"
                for key, value in fields.items()
                if value is not None
            )
            suffix = f" {rendered}" if rendered else ""
            print(
                f"codess: progress {record['at']} "
                f"+{record['elapsed_seconds']:.3f}s "
                f"{event}{suffix}",
                file=self.stream,
                flush=True,
            )
        return record

    @staticmethod
    def _format(value: Any) -> str:
        if isinstance(value, str):
            return json.dumps(value) if any(char.isspace() for char in value) else value
        if isinstance(value, bool):
            return str(value).lower()
        return str(value)

    def records_for(self, project: str | None = None) -> list[dict[str, Any]]:
        """Return all events, or global events plus events for one Project."""
        records = [
            dict(record)
            for record in self.events
            if project is None or record.get("project") in {None, project}
        ]
        if self.dropped_events:
            records.append({
                "at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                "elapsed_seconds": round(time.monotonic() - self.started, 3),
                "event": "progress.events_dropped",
                "count": self.dropped_events,
            })
        return records
