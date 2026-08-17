"""Where events go. One interface, selected per run; a call site never knows.

Report R7 and R9: a call site cannot know which sinks exist, and **stdout is
never a sink**. stdout carries the requested result and nothing else, which is
what lets `query --output-format jsonl` be piped safely -- and is the property
gate G5 verifies by comparing stdout byte-for-byte before and after.

Report R10: a sink never raises into the operation it reports on. A reporting
failure is counted and dropped. The alternative is that a full disk or a closed
pipe aborts an ingest, which would make the facility a liability rather than an
aid.

Sinks take rendered events rather than doing their own privacy work, so the
allowlist is applied once for a run rather than once per attached sink.
"""

from __future__ import annotations

import contextlib
import json
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol, TextIO

from codess.reporting.clock import elapsed_seconds, wall_ns
from codess.reporting.codes import (
    EVENT_NAMES,
    LEVEL_NAMES,
    SCOPE_NAMES,
)
from codess.reporting.privacy import Roots, render_fields

CODE, TICK, LEVEL, SCOPE, FIELDS = range(5)
"""Positional accessors, for readability at sink sites where cost is irrelevant.

The literal position is the documentation on the hot path (Report 5); this is
the same trade CoPlan 3.5.5 makes for CoSchema field names.
"""


class Sink(Protocol):
    """What the buffer needs from a destination."""

    def emit(self, events: list[tuple]) -> None: ...

    def close(self) -> None: ...


def wall_text(tick: int) -> str:
    """One tick as ISO 8601 text, resolved only because a sink is rendering."""
    return datetime.fromtimestamp(wall_ns(tick) / 1e9, UTC).isoformat(
        timespec="milliseconds"
    )


def _scalar_text(value: object) -> str:
    if isinstance(value, str):
        return json.dumps(value) if any(ch.isspace() for ch in value) else value
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


class HumanSink:
    """Concise lines on stderr, the interactive default.

    Matches the shape `ProgressTrace` emits today, so the transition is not
    also a change in what an operator reads (Report 12.3 step 4).
    """

    def __init__(
        self, stream: TextIO | None = None, *, privacy: str = "local",
        roots: Roots | None = None,
    ) -> None:
        self._stream = stream if stream is not None else sys.stderr
        self._privacy = privacy
        self._roots = roots

    def emit(self, events: list[tuple]) -> None:
        lines = []
        for event in events:
            fields = render_fields(
                event[FIELDS], privacy=self._privacy, roots=self._roots,
            )
            rendered = " ".join(
                f"{key}={_scalar_text(value)}"
                for key, value in fields.items()
                if value is not None
            )
            suffix = f" {rendered}" if rendered else ""
            lines.append(
                f"codess: progress {wall_text(event[TICK])} "
                f"+{elapsed_seconds(event[TICK]):.3f}s "
                f"{EVENT_NAMES[event[CODE]]}{suffix}"
            )
        _write(self._stream, "\n".join(lines) + "\n")

    def close(self) -> None:
        _flush(self._stream)


class JsonlSink:
    """One JSON object per line on stderr, for a machine-parsed run."""

    def __init__(
        self, stream: TextIO | None = None, *, privacy: str = "local",
        roots: Roots | None = None,
    ) -> None:
        self._stream = stream if stream is not None else sys.stderr
        self._privacy = privacy
        self._roots = roots

    def emit(self, events: list[tuple]) -> None:
        lines = []
        for event in events:
            record: dict[str, Any] = {
                "at": wall_text(event[TICK]),
                "elapsed_seconds": round(elapsed_seconds(event[TICK]), 3),
                "event": EVENT_NAMES[event[CODE]],
                "level": LEVEL_NAMES[event[LEVEL]],
            }
            scope = SCOPE_NAMES[event[SCOPE]]
            if scope:
                record["scope"] = scope
            record.update(
                render_fields(
                    event[FIELDS], privacy=self._privacy, roots=self._roots,
                )
            )
            lines.append(json.dumps(record, sort_keys=True, default=str))
        _write(self._stream, "\n".join(lines) + "\n")

    def close(self) -> None:
        _flush(self._stream)


class CollectorSink:
    """Bounded in-memory records, for the ingest and refresh reports.

    Renders on emit rather than on read, so a record leaving this sink has
    already passed the allowlist -- a report written to disk cannot carry a
    field the profile would have redacted on stderr.
    """

    def __init__(
        self, *, privacy: str = "local", roots: Roots | None = None,
        max_records: int = 5_000,
    ) -> None:
        self._privacy = privacy
        self._roots = roots
        self._max = max_records
        self.records: list[dict[str, Any]] = []
        self.dropped = 0

    def emit(self, events: list[tuple]) -> None:
        for event in events:
            if len(self.records) >= self._max:
                self.dropped += 1
                continue
            record: dict[str, Any] = {
                "at": wall_text(event[TICK]),
                "elapsed_seconds": round(elapsed_seconds(event[TICK]), 3),
                "event": EVENT_NAMES[event[CODE]],
                "level": LEVEL_NAMES[event[LEVEL]],
            }
            record.update(
                render_fields(
                    event[FIELDS], privacy=self._privacy, roots=self._roots,
                )
            )
            self.records.append(record)

    def close(self) -> None:
        return None


class NullSink:
    """Accepts and discards, so a benchmark measures the operation.

    Report 11: with the compile gate off and this attached, reporting
    contributes nothing measurable to a timing run -- which is what makes W08's
    workloads measure ingest rather than ingest plus instrumentation.
    """

    def emit(self, events: list[tuple]) -> None:  # noqa: ARG002
        return None

    def close(self) -> None:
        return None


def _write(stream: TextIO, text: str) -> None:
    """Write without letting a stream failure reach the caller (R10).

    A closed pipe or full disk must not abort the operation being reported. The
    event is lost; the run continues.
    """
    with contextlib.suppress(OSError, ValueError):
        stream.write(text)


def _flush(stream: TextIO) -> None:
    with contextlib.suppress(OSError, ValueError):
        stream.flush()


BUILDERS: dict[str, Callable[..., Any]] = {
    "human": HumanSink,
    "jsonl": JsonlSink,
    "collector": CollectorSink,
    "null": NullSink,
}


def build(
    names: tuple[str, ...], *, privacy: str = "local", roots: Roots | None = None,
) -> tuple[Any, ...]:
    """Construct the named sinks for a profile.

    An empty tuple is the fast path the run-time gate checks: with no sink
    attached, a reporting call returns before constructing an event at all
    (Report 6c).
    """
    built = []
    for name in names:
        try:
            builder = BUILDERS[name]
        except KeyError:
            raise ValueError(f"unknown sink {name!r}") from None
        if builder is NullSink:
            built.append(builder())
        else:
            built.append(builder(privacy=privacy, roots=roots))
    return tuple(built)
