"""Bounded, content-free progress traces for long-running operations.

**A compatibility shim over `codess.reporting`.** This class was the whole
progress facility; it is now one adapter onto the event contract, kept so ingest
keeps emitting what it emits today while the call sites move across (Report 12.3
step 4, gate G3). Its own storage, formatting, and clock are gone -- an event
reaches the ring and a sink renders it.

Two behaviours it must preserve, because callers depend on them:

- `__call__(event, **fields)` returns the record dict it produced. The ingest
  report writes these into `progress_events`, so the shape is a contract rather
  than an implementation detail.
- `records_for(project)` returns global events plus those for one Project, with
  a `progress.events_dropped` entry appended when the bound was reached.

Callers supply identifiers, counts, sizes, and phase names only. Transcript
content must never be passed as a field: these records are operational metadata
and are persisted in the ingest report. The field registry in
`reporting.codes` now enforces that structurally rather than by convention.
"""

from __future__ import annotations

import contextlib
import sys
from collections import deque
from typing import Any, TextIO

from codess import reporting
from codess.reporting.clock import elapsed_seconds, tick, wall_ns
from codess.reporting.codes import CODE_BY_NAME, EVENT_LEVELS, EVENT_SCOPES
from codess.reporting.sinks import HumanSink, wall_text


class ProgressTrace:
    """Emit concise live progress and retain the same structured events.

    Retains its own record list rather than reading the reporting ring, because
    `records_for` filters by Project and the ring is process-wide: two Projects
    ingested in one run share the ring, and the report for each must carry only
    its own events.
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
        self.start_tick = tick()
        # A deque bounded at `max_events` keeps the *newest* records, which is
        # the right loss for a progress trace: the events near a failure explain
        # it, and the count of what was dropped is reported so the bound is
        # visible rather than silent.
        self.records: deque[dict[str, Any]] = deque(maxlen=max_events)
        self.dropped_events = 0
        # Its own sink rather than the process-wide table. Ingest runs as a
        # child process that may never call `reporting.configure`, and a test
        # capturing a stream must see only its own output -- both of which a
        # shared sink table would break. The transition ends when the call sites
        # emit through `reporting` directly and this class goes.
        #
        # The *privacy* profile is read from the configured one rather than
        # defaulted, because a redaction flag that silently does nothing while
        # the transition is in progress is worse than no flag: the operator
        # believes a shared log was redacted.
        active = reporting.profile()
        self._sink = (
            HumanSink(
                self.stream,
                privacy=active.privacy if active else "local",
                roots=reporting.roots(),
            )
            if enabled else None
        )

    def __call__(self, event: str, **fields: Any) -> dict[str, Any]:
        """Record one event and return it, emitting live when enabled."""
        code = CODE_BY_NAME.get(event)
        now = tick()
        record = {
            "at": wall_text(now),
            "elapsed_seconds": round(elapsed_seconds(now), 3),
            "event": event,
            **{key: value for key, value in fields.items() if value is not None},
        }
        if len(self.records) == self.max_events:
            self.dropped_events += 1
        self.records.append(record)
        if self._sink is None:
            return record
        if code is None:
            # An event name the code table does not carry still reaches the
            # operator and the report. Refusing it would make adding a progress
            # point a two-file change, and the table is seeded from these names
            # rather than authoritative over them during the transition.
            self._render_untabled(record)
            return record
        emitted = (
            code, now, EVENT_LEVELS[code], EVENT_SCOPES[code],
            tuple(part for pair in fields.items() for part in pair),
        )
        # A sink must not reach the caller (R10).
        with contextlib.suppress(Exception):
            self._sink.emit([emitted])
            self._sink.close()
        return record

    def _render_untabled(self, record: dict[str, Any]) -> None:
        if not self.enabled:
            return
        rendered = " ".join(
            f"{key}={value}" for key, value in record.items()
            if key not in ("at", "elapsed_seconds", "event")
        )
        suffix = f" {rendered}" if rendered else ""
        # A reporting write never reaches the operation it reports on.
        with contextlib.suppress(OSError, ValueError):
            print(
                f"codess: progress {record['at']} "
                f"+{record['elapsed_seconds']:.3f}s "
                f"{record['event']}{suffix}",
                file=self.stream,
                flush=True,
            )

    def records_for(self, project: str | None = None) -> list[dict[str, Any]]:
        """Return all events, or global events plus events for one Project."""
        selected = [
            dict(record)
            for record in self.records
            if project is None or record.get("project") in {None, project}
        ]
        if self.dropped_events:
            now = tick()
            selected.append({
                "at": wall_text(now),
                "elapsed_seconds": round(elapsed_seconds(now), 3),
                "event": "progress.events_dropped",
                "count": self.dropped_events,
            })
        return selected

    # Retained for the two call sites that read it as a deque-like collection.
    @property
    def events(self) -> deque[dict[str, Any]]:
        return self.records


__all__ = ["ProgressTrace", "wall_ns"]
