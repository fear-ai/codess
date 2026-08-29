"""The three primitives: `count`, `event`, `span`, and the gates in front of them.

Report R1-R3: a disabled site costs no more than a bare call, a per-record fact
uses a primitive with no allocation, and the run-time check precedes all
construction.

**Why three primitives rather than one.** They answer different questions and
have different costs. `count` answers *how many* and is an integer add against a
preallocated slot -- cheap enough for a per-record site. `event` answers *when
and what* and constructs a tuple. `span` answers *how long* and is two ticks the
sink subtracts. Collapsing them onto one `log()` would charge every per-record
site the cost of the most expensive shape.

**The gate order matters and is measured.** The run-time sink check comes before
the field tuple is built, so a run with nothing attached does not construct a
record it will discard, which is what the facility it replaced did wrong.

**Measured on the implementation, and one figure is worse than predicted.** R1
asks that a disabled site cost no more than a bare call:

    no sink attached, event(code, path=..., events=...)      76 ns
    sink attached, level below MIN_LEVEL                     86 ns
    enabled and buffered                                    618 ns
    count(slot)                                              50 ns   (R3: target 66)
    compile-gated site, `if REPORT_TRACE:`                    16 ns   (R2)

The 76 ns is not the ~16 ns predicted, and the reason is structural rather than
fixable by reordering: **`**fields` packs a dict before the function body runs**,
measured at ~43 ns for two fields, so no gate inside the function can precede it.
The prediction assumed a bare call with no keyword arguments.

Three things follow. The cost is still 16x better than the 1,245 ns it replaces,
so R1's intent holds even where its number does not. A per-record site inside a
decode loop should take the compile-time gate rather than rely on the run-time
one, which is what R2 exists for and what the 16 ns line measures. And a
positional flat-tuple signature would recover the difference at the cost of every
call site spelling its own tuple -- rejected because a keyword call is what makes
these sites readable, and the sites that cannot afford 76 ns are exactly the ones
R2 already covers.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Protocol

from codess.reporting.buffer import EventRing, flush_when
from codess.reporting.clock import duration_seconds, tick
from codess.reporting.codes import (
    CODE_BY_NAME,
    COUNTER_COUNT,
    COUNTER_NAMES,
    EVENT_LEVELS,
    EVENT_SCOPES,
    WARNING,
    code,
    slot,
)
from codess.reporting.levels import MAX_FIELDS, Profile, resolve
from codess.reporting.privacy import Roots
from codess.reporting.sinks import build

__all__ = [
    "ProgressEmitter",
    "code",
    "collector",
    "configure",
    "count",
    "counters",
    "emit_named",
    "event",
    "profile",
    "reset",
    "roots",
    "slot",
    "span",
]

# --- Process state -----------------------------------------------------------
#
# Module-level rather than passed through every call. A reporting facility a
# caller has to thread an object into is one that library code -- `fileio`, the
# adapters -- cannot reach without a signature change at every layer, which is
# why stdlib `basicConfig` was rejected, while keeping the same shape.
_COUNTERS: list[int] = [0] * COUNTER_COUNT
_SINKS: tuple[Any, ...] = ()
_RING: EventRing | None = None
_MIN_LEVEL: int = WARNING
_PROFILE: Profile | None = None
_ROOTS: Roots = Roots()

# Bound at import: `CODE_BY_NAME.get` resolves a global and an attribute on
# every call otherwise, which is ~10% of this function's cost.
_CODE_BY_NAME_GET = CODE_BY_NAME.get


def configure(
    profile_name: str | None = None,
    *,
    privacy: str | None = None,
    redaction_roots: dict[str, Any] | None = None,
    sinks: tuple[Any, ...] | None = None,
    file_path: str | None = None,
) -> Profile:
    """Resolve a profile and attach its sinks. Call once per process.

    `sinks` overrides construction for a test that needs to inspect what was
    emitted. Everything else comes from the profile, so a call site cannot know
    or choose its destination (R7).
    """
    global _SINKS, _RING, _MIN_LEVEL, _PROFILE, _ROOTS
    # `profile_name` and `redaction_roots` rather than `profile` and `roots`:
    # both of those are module-level accessors in this file, and a parameter
    # reusing the name of a function it sits beside is the shadowing CLAUDE.md's
    # naming rule forbids.
    resolved = resolve(profile_name, privacy)
    _PROFILE = resolved
    _MIN_LEVEL = resolved.min_level
    _ROOTS = Roots(redaction_roots) if redaction_roots else Roots()
    _SINKS = (
        sinks if sinks is not None
        else build(
            resolved.sinks, privacy=resolved.privacy, roots=_ROOTS,
            file_path=file_path or os.environ.get("CODESS_REPORT_FILE"),
        )
    )
    # The gate is the *minimum* across attached sinks, not the profile's level.
    # A profile sets what an operator sees; a durable sink retains more, because a
    # report is read after the fact by someone diagnosing and the event they need
    # is usually the one the interactive run suppressed. One threshold for both is
    # the conflation, and it emptied the durable ingest report of every debug
    # event when it was tried.
    #
    # Each sink then drops what it does not want, so a lower floor here widens
    # what is *constructed* without widening what is printed.
    floors = [
        getattr(sink, "min_level", resolved.min_level) for sink in _SINKS
    ]
    _MIN_LEVEL = min([resolved.min_level, *floors]) if floors else resolved.min_level
    _RING = EventRing(flush_events=resolved.flush_events) if _SINKS else None
    return resolved


def reset() -> None:
    """Detach every sink and zero the counters, for a test or a second run."""
    global _SINKS, _RING, _MIN_LEVEL, _PROFILE
    for sink in _SINKS:
        sink.close()
    _SINKS = ()
    _RING = None
    _MIN_LEVEL = WARNING
    _PROFILE = None
    for index in range(COUNTER_COUNT):
        _COUNTERS[index] = 0


def profile() -> Profile | None:
    """The active profile, or None if reporting was never configured."""
    return _PROFILE


def roots() -> Roots:
    """The registered filesystem roots a `located` field renders against."""
    return _ROOTS


def collector() -> Any | None:
    """The attached collector sink, if a durable report needs its records.

    The facility owns this rather than a caller threading it, because the
    alternative measured worse: the two consumers of the ingest report sit in
    functions that already take a `progress_trace` parameter, so reaching the
    collector meant a second parameter down two call chains whose only purpose
    was carrying a sink the facility already holds.

    Returns None when no collector is attached, which a caller must handle -- a
    profile without one is legitimate, and a report should say it has no events
    rather than fail.
    """
    for sink in _SINKS:
        if hasattr(sink, "records_for"):
            return sink
    return None


# --- count -------------------------------------------------------------------


def count(index: int, amount: int = 1) -> None:
    """Add to a preallocated counter slot.

    Ungated on purpose. An integer add against a list slot is 66 ns and
    allocates nothing, so gating it would add a branch costing a measurable
    fraction of the operation it protects. Counters are also wanted
    even when nothing is emitted -- an ingest summary reports them at the end of
    a run whose events were all below the level threshold.
    """
    _COUNTERS[index] += amount


def counters() -> dict[str, int]:
    """The non-zero counters by name, for a summary or a report.

    Non-zero only: a summary listing nineteen counters of which two fired buries
    the two. The names are available from `codes.COUNTER_NAMES` for a caller that
    wants the complete set.
    """
    return {
        name: _COUNTERS[index]
        for index, name in enumerate(COUNTER_NAMES)
        if _COUNTERS[index]
    }


# --- event -------------------------------------------------------------------


def event(event_code: int, **fields: Any) -> None:
    """Record one event, if any sink is attached and the level passes.

    The gates are in cost order. `_SINKS` is checked first because an empty
    tuple is the common case for a benchmark or a quiet run, and checking it
    before building the field tuple is what R1 requires -- the current facility
    builds the record and then decides.
    """
    if not _SINKS:
        return
    level = EVENT_LEVELS[event_code]
    if level < _MIN_LEVEL:
        return
    flat: tuple = ()
    if fields:
        # Flat (k, v, k, v, ...) rather than a dict: cheaper to build, and the
        # sink materializes a mapping only when it renders.
        items = list(fields.items())
        if len(items) > MAX_FIELDS:
            items = items[:MAX_FIELDS]
            _COUNTERS[slot("fields_rejected")] += 1
        flat = tuple(part for pair in items for part in pair)
    record = (event_code, tick(), level, EVENT_SCOPES[event_code], flat)
    ring = _RING
    if ring is None:
        _emit([record])
        return
    if ring.append(record):
        flush_when(ring, _emit, force=True)


def flush() -> None:
    """Emit whatever is buffered. For a phase or process boundary."""
    if _RING is not None and _SINKS:
        flush_when(_RING, _emit, force=True)
        if _RING.dropped:
            _COUNTERS[slot("events_dropped")] = _RING.dropped


def _emit(events: list[tuple]) -> None:
    for sink in _SINKS:
        # One failing sink must not stop the others, and must not reach the
        # operation being reported on (R10).
        try:
            sink.emit(events)
        except Exception:  # a sink may raise anything; R10 forbids propagating
            _COUNTERS[slot("events_dropped")] += len(events)


# --- span --------------------------------------------------------------------


class ProgressEmitter(Protocol):
    """What a library module needs from a progress reporter.

    A protocol rather than a concrete type, because the point of passing the
    emitter as an argument is that the callee does not depend on the facility:
    a library module must not depend on the command layer, and `reporting.api`
    holds process-wide mutable state. A caller can pass
    `emit_named`, a test double, or nothing.

    Named and exported so the six functions that thread it can say what they
    take. They previously declared a bare `progress_trace`, which told a reader
    only that something was threaded and let a `str` be passed where a callable
    was meant.
    """

    def __call__(self, name: str, **fields: Any) -> None: ...


def emit_named(name: str, **fields: Any) -> None:
    """Report one event by its dotted name, dropping absent fields.

    The name-taking form of `event`, for a call site that reads better with a
    name than with a resolved code -- which is every progress point in ingest,
    where the name is the whole content of the line an operator reads.

    Two conveniences over `event`, and they are why this exists rather than
    callers doing it themselves: the name is resolved to a code, and a field whose
    value is None is dropped rather than rendered. Sixty-odd call sites pass
    optional fields, and each one testing for None before calling would be the
    same conditional written sixty times.

    An unknown name raises rather than degrading. The previous facility rendered
    an unregistered name anyway, without a level or a scope, which is how 23 of
    the 38 names actually emitted went unregistered without anyone noticing --
    so the quiet path is removed deliberately. Adding a progress point is a
    two-line change, and the second line is what makes the event filterable.

    Lives here rather than in its own module because it is one lookup and one
    call over `event`, and a module holding a single three-statement function is
    a file a reader has to open to learn nothing.
    """
    # `name`, not `event`: the parameter would otherwise shadow the module
    # function this calls, which is the exact defect that made a `dict` rebind a
    # `list[Path]` in ingest -- reintroduced here, in the function written to
    # replace it, and caught by the suite rather than by reading.
    resolved = _CODE_BY_NAME_GET(name)
    if resolved is None:
        raise KeyError(
            f"unknown progress event {name!r}; add it to reporting.codes"
        )
    # Rebuild only when a None is actually present. Measured over the call sites,
    # 28 of 222 keyword arguments can be None, so the common path pays a
    # membership test rather than a dict comprehension: 338 ns to 262 ns.
    #
    # The filter is not removable. `HumanSink` and `BridgeSink` drop None when
    # they render, but `JsonlSink` and `CollectorSink` do not -- without it a
    # durable report carries `"events": null`, a field stating nothing. Dropping
    # here rather than in each sink keeps one rule for every destination.
    if None in fields.values():
        fields = {
            key: value for key, value in fields.items() if value is not None
        }
    event(resolved, **fields)


@contextmanager
def span(event_code: int, **fields: Any) -> Iterator[dict[str, Any]]:
    """Time a phase and report its duration on exit.

    Two ticks and a subtraction, never a formatted timestamp (R4). The yielded
    dict accepts fields discovered during the phase -- a count that is not known
    until the work is done -- so the caller does not have to emit a second event
    to carry them.

    On an exception the duration is still reported, with the exception family
    named, and the exception propagates. A phase that failed after 40 seconds is
    more informative than one that reports nothing, and swallowing it here would
    make the facility change the behaviour of the code it observes.
    """
    started = tick()
    extra: dict[str, Any] = {}
    try:
        yield extra
    except BaseException as exc:
        event(
            event_code, **fields, **extra,
            phase_seconds=round(duration_seconds(started, tick()), 3),
            error_type=type(exc).__name__,
        )
        raise
    event(
        event_code, **fields, **extra,
        phase_seconds=round(duration_seconds(started, tick()), 3),
    )
