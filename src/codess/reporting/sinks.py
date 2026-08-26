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
import logging
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar, Protocol, TextIO

from codess.reporting.clock import elapsed_seconds, wall_ns
from codess.reporting.codes import (
    DEBUG,
    ERROR,
    EVENT_LEVELS,
    EVENT_NAMES,
    INFO,
    LEVEL_NAMES,
    SCOPE_NAMES,
    WARNING,
)
from codess.reporting.privacy import Roots, render_fields

CODE, TICK, LEVEL, SCOPE, FIELDS = range(5)
"""Positional accessors, for readability at sink sites where cost is irrelevant.

The literal position is the documentation on the hot path, the same trade
CoSchema field names make: the literal names what it reads.
"""

# What a rendered line calls itself. `progress` is right for the steps that
# make up a run and wrong for a condition the operator has to act on, which is
# why status sites wrote to stderr directly rather than through this sink.
_SHAPE_BY_LEVEL = {
    DEBUG: "progress",
    INFO: "progress",
    WARNING: "warning",
    ERROR: "error",
}


# --- Absent fields: rendered text drops them, structured data keeps them ------
#
# Verified rather than assumed, because an earlier note described this as a
# per-sink difference and it is not. The rule follows the *form* of the output:
#
#   HumanSink       message text     drops   `vendor=Claude` (no `events=`)
#   BridgeSink      message text     drops   same rendered string
#   BridgeSink      `extra` mapping  keeps   {'vendor': 'Claude', 'events': None}
#   JsonlSink       JSON object      keeps   {"events": null, ...}
#   CollectorSink   report record    keeps   {'events': None, ...}
#
# So `BridgeSink` sits on both sides at once: its message is text and its `extra`
# is structure, and each follows its own form.
#
# **Why text drops.** `events=None` in a line a person reads is noise: the reader
# wants the fields that have values, and a run of `x=None y=None` obscures them.
# There is no schema for a log line, so an absent key costs a reader nothing.
#
# **Why structure keeps.** A JSON consumer distinguishes "the producer said this
# is unknown" from "the producer did not mention this". Dropping the key silently
# converts the first into the second, and a consumer indexing the field then sees
# a `KeyError` rather than a `null` it could handle. That is the same argument
# CoSchema makes for recording a field state rather than omitting the row.
#
# **Which is why the filter belongs in `emit_named`, above all of them.** A field
# whose value is None because a *caller* had nothing to pass is not the same as a
# field a decoder deliberately recorded as unknown. The first should never reach a
# sink at all; the second should reach every one of them. Filtering at the call
# boundary rather than in each sink keeps that distinction, and is why removing
# the filter changed the durable report -- 28 of 222 call-site arguments can be
# None, and every one of them was the first kind.


class Sink(Protocol):
    """What the buffer needs from a destination.

    `min_level` is how Report R6 -- immediacy and permanence selected
    independently -- becomes real. One process-wide threshold conflates them: a
    validation run wants *retention without noise*, so the collector keeps a
    debug event that the human sink must not print. A single gate cannot express
    that, and the defect is not hypothetical: filtering both at one level emptied
    the durable ingest report of every debug event it had always carried.

    The api gate uses the minimum across attached sinks, so an event is
    constructed if *any* sink wants it and each sink then drops what it does not.
    """

    min_level: int

    def emit(self, events: list[tuple]) -> None: ...

    def close(self) -> None: ...


def wall_text(tick: int) -> str:
    """One tick as ISO 8601 text, resolved only because a sink is rendering.

    **The largest single cost on the rendering path, measured at 863 ns, and
    deliberately not cached.** A second-granularity cache was considered and
    is not worth it. Measured on a real
    ingest report it is not: 242 events span 211 distinct millisecond timestamps,
    at most 3 sharing one, so a cache would hit about 13% of the time and add a
    dict lookup to the other 87%.

    The reason the figure is affordable at all is R4 -- this runs once per
    *rendered* event rather than once per recorded one, so a run that reports
    nothing pays none of it. Caching would be the right answer for a sink whose
    events cluster within a millisecond; none does.
    """
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

    Keeps the line shape the previous progress facility emitted, so replacing
    it was not also a change in what an operator reads.
    """

    def __init__(
        self, stream: TextIO | None = None, *, privacy: str = "local",
        roots: Roots | None = None, min_level: int = DEBUG,
    ) -> None:
        self._stream = stream if stream is not None else sys.stderr
        self._privacy = privacy
        self._roots = roots
        self.min_level = min_level

    def emit(self, events: list[tuple]) -> None:
        lines = []
        for event in accepted(self, events):
            fields = render_fields(
                event[FIELDS], privacy=self._privacy, roots=self._roots,
            )
            rendered = " ".join(
                f"{key}={_scalar_text(value)}"
                for key, value in fields.items()
                if value is not None
            )
            suffix = f" {rendered}" if rendered else ""
            # The shape names what the event *is*, not the one thing this sink
            # was first built to carry. Rendering a warning as `progress` was
            # the reason status sites wrote to stderr directly instead: a
            # condition an operator must act on read as a step that completed.
            shape = _SHAPE_BY_LEVEL.get(EVENT_LEVELS[event[CODE]], "progress")
            lines.append(
                f"codess: {shape} {wall_text(event[TICK])} "
                f"+{elapsed_seconds(event[TICK]):.3f}s "
                f"{EVENT_NAMES[event[CODE]]}{suffix}"
            )
        # Nothing accepted means nothing written, not a bare newline. A quiet
        # profile that still emitted blank lines would be quiet in content and
        # noisy on the terminal.
        if lines:
            _write(self._stream, "\n".join(lines) + "\n")

    def close(self) -> None:
        _flush(self._stream)


def _envelope(
    event: tuple, *, privacy: str, roots: Roots | None,
) -> dict[str, Any]:
    """The JSON shape both machine-readable sinks emit.

    Shared so `jsonl` on stderr and `file` on disk cannot drift into two formats
    for one event, which is what a reader parsing either would then have to
    handle.
    """
    record: dict[str, Any] = {
        "at": wall_text(event[TICK]),
        "elapsed_seconds": round(elapsed_seconds(event[TICK]), 3),
        "event": EVENT_NAMES[event[CODE]],
        "level": LEVEL_NAMES[event[LEVEL]],
    }
    scope = SCOPE_NAMES[event[SCOPE]]
    if scope:
        record["scope"] = scope
    record.update(render_fields(event[FIELDS], privacy=privacy, roots=roots))
    return record


class JsonlSink:
    """One JSON object per line on stderr, for a machine-parsed run."""

    def __init__(
        self, stream: TextIO | None = None, *, privacy: str = "local",
        roots: Roots | None = None, min_level: int = DEBUG,
    ) -> None:
        self._stream = stream if stream is not None else sys.stderr
        self._privacy = privacy
        self._roots = roots
        self.min_level = min_level

    def emit(self, events: list[tuple]) -> None:
        lines = [
            json.dumps(
                _envelope(event, privacy=self._privacy, roots=self._roots),
                sort_keys=True, default=str,
            )
            for event in accepted(self, events)
        ]
        if lines:
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
        max_records: int = 5_000, min_level: int = DEBUG,
    ) -> None:
        self._privacy = privacy
        self._roots = roots
        self._max = max_records
        # Retains at debug by default, whatever the human sink prints. A durable
        # report is read after the fact by someone diagnosing, and the event they
        # need is usually the one an interactive run suppressed (Report R6).
        self.min_level = min_level
        self.records: list[dict[str, Any]] = []
        self.dropped = 0

    def emit(self, events: list[tuple]) -> None:
        for event in accepted(self, events):
            if len(self.records) >= self._max:
                self.dropped += 1
                continue
            self.records.append(
                _envelope(event, privacy=self._privacy, roots=self._roots)
            )

    def records_for(self, project: str | None = None) -> list[dict[str, Any]]:
        """Global records plus those for one Project.

        The reporting ring is process-wide and a durable report is per Project,
        so something has to bridge that: one ingest run touches several Projects
        and each Project's report must carry only its own events plus the
        run-level ones that have no Project at all.

        Filtering here rather than keeping a second store is the point. The
        alternative -- a collector per Project -- would make the drop accounting
        per Project too, so a run that dropped events would report several
        partial truths instead of one; and a separate deque outside the facility
        is the parallel store this sink exists to replace.

        A record with no `project` field is a run-level event and belongs in
        every Project's report: `ingest.start` is not about one Project, but a
        report that omitted it would not explain what the run was doing.
        """
        selected = [
            dict(record)
            for record in self.records
            if project is None or record.get("project") in (None, project)
        ]
        if self.dropped:
            # The bound is reported rather than silent, so a truncated report
            # says it is truncated. Without this a reader cannot distinguish a
            # quiet run from a run whose evidence was discarded.
            selected.append({
                "event": "report.events_dropped",
                "level": LEVEL_NAMES[WARNING],
                "count": self.dropped,
            })
        return selected

    def close(self) -> None:
        return None


class FileSink:
    """JSONL to a file, for a long run or a benchmark whose output outlives it.

    Durable where `jsonl` is immediate: stderr disappears with the terminal, and
    a run whose evidence is wanted afterwards -- a scale workload, an overnight
    refresh -- needs the events on disk. The format is the same, so one reader
    parses either.

    Opened lazily and appended: a profile that attaches this sink and emits
    nothing should not leave an empty file, and a second run should not silently
    erase the first's evidence.
    """

    def __init__(
        self, path: Path | str, *, privacy: str = "local",
        roots: Roots | None = None, min_level: int = DEBUG,
    ) -> None:
        self._path = Path(path)
        self._privacy = privacy
        self._roots = roots
        self.min_level = min_level
        self._stream: TextIO | None = None

    def _open(self) -> TextIO | None:
        if self._stream is None:
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                self._stream = self._path.open("a", encoding="utf-8")
            except OSError:
                # A reporting sink that cannot open its file must not abort the
                # operation it reports on (R10). The events are lost and the run
                # continues.
                return None
        return self._stream

    def emit(self, events: list[tuple]) -> None:
        stream = self._open()
        if stream is None:
            return
        lines = [
            json.dumps(
                _envelope(event, privacy=self._privacy, roots=self._roots),
                sort_keys=True, default=str,
            )
            for event in accepted(self, events)
        ]
        if lines:
            _write(stream, "\n".join(lines) + "\n")

    def close(self) -> None:
        if self._stream is not None:
            _flush(self._stream)
            with contextlib.suppress(OSError, ValueError):
                self._stream.close()
            self._stream = None


class BridgeSink:
    """Events into the standard library's `logging`, for a call site that has no
    reporter.

    Stdlib `logging` is adopted for exactly this and rejected as the primary
    path: a `LogRecord` has no place for a counter, and `basicConfig` is
    process-global state a bounded command should not depend on. As a *sink* it
    is the right shape -- a library whose caller configured logging and never
    calls `reporting.configure` still reaches a handler.

    The event's own level maps onto the logging level, so a handler filtering at
    `WARNING` sees warnings and errors and nothing else, which is what a caller
    who configured that handler asked for.
    """

    _LEVELS: ClassVar[dict[int, int]] = {
        DEBUG: 10, INFO: 20, WARNING: 30, ERROR: 40,
    }

    def __init__(
        self, logger_name: str = "codess.reporting", *, privacy: str = "local",
        roots: Roots | None = None, min_level: int = DEBUG,
    ) -> None:
        self._log = logging.getLogger(logger_name)
        self._privacy = privacy
        self._roots = roots
        self.min_level = min_level

    def emit(self, events: list[tuple]) -> None:
        for event in accepted(self, events):
            fields = render_fields(
                event[FIELDS], privacy=self._privacy, roots=self._roots,
            )
            # `extra` rather than the message, so a structured handler keeps the
            # fields as fields. The rendered pairs are also in the message,
            # because the default formatter shows only that.
            rendered = " ".join(
                f"{key}={_scalar_text(value)}"
                for key, value in fields.items() if value is not None
            )
            self._log.log(
                self._LEVELS.get(event[LEVEL], 20),
                "%s %s", EVENT_NAMES[event[CODE]], rendered,
                extra={"codess_event": EVENT_NAMES[event[CODE]],
                       "codess_fields": fields},
            )

    def close(self) -> None:
        return None


class NullSink:
    """Accepts and discards, so a benchmark measures the operation.

    With the compile gate off and this attached, reporting contributes nothing
    measurable to a timing run -- which is what makes the
    measured workloads report ingest rather than ingest plus instrumentation.
    """

    min_level = ERROR

    def emit(self, events: list[tuple]) -> None:  # noqa: ARG002
        # Accepts and discards, which is the whole point: the null sink exists
        # so a measured workload reports ingest rather than instrumentation.
        return None

    def close(self) -> None:
        return None


def accepted(sink: Any, events: list[tuple]) -> list[tuple]:
    """The events one sink wants, from a batch built for the minimum threshold.

    The api gate constructs an event if *any* attached sink accepts its level, so
    each sink drops what it does not want here. Without this the lowest threshold
    would leak into every destination -- which is exactly the conflation R6 names.
    """
    floor = getattr(sink, "min_level", DEBUG)
    return [event for event in events if event[LEVEL] >= floor]


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
    "file": FileSink,
    "bridge": BridgeSink,
    "null": NullSink,
}


def build(
    names: tuple[str, ...], *, privacy: str = "local", roots: Roots | None = None,
    file_path: Path | str | None = None,
) -> tuple[Any, ...]:
    """Construct the named sinks for a profile.

    An empty tuple is the fast path the run-time gate checks: with no sink
    attached, a reporting call returns before constructing an event at all.
    """
    built = []
    for name in names:
        try:
            builder = BUILDERS[name]
        except KeyError:
            raise ValueError(f"unknown sink {name!r}") from None
        if builder is NullSink:
            built.append(builder())
        elif builder is FileSink:
            # The one sink that needs somewhere to write. A profile names sinks
            # but not paths, so the destination comes from the environment --
            # which also means a profile listing `file` without it configured
            # attaches nothing rather than inventing a location in the operator's
            # working directory.
            if file_path is None:
                continue
            built.append(builder(file_path, privacy=privacy, roots=roots))
        else:
            built.append(builder(privacy=privacy, roots=roots))
    return tuple(built)
