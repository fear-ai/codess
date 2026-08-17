"""The three primitives: `count`, `event`, `span`, and the gates in front of them.

Report R1-R3: a disabled site costs no more than a bare call, a per-record fact
uses a primitive with no allocation, and the run-time check precedes all
construction.

**Why three primitives rather than one.** They answer different questions and
have different costs. `count` answers *how many* and is an integer add against a
preallocated slot -- cheap enough for a per-record site. `event` answers *when
and what* and constructs a tuple. `span` answers *how long* and is two ticks the
sink subtracts. Collapsing them onto one `log()` would charge every per-record
site the cost of the most expensive shape, which is the defect Report 1.3
records.

**The gate order matters and is measured.** The run-time sink check comes before
the field tuple is built, so a run with nothing attached does not construct a
record it will discard (Report 6c). That is the specific thing the current
facility does wrong.

**Measured on the implementation, and one figure is worse than Report 3
predicted.** R1 asks that a disabled site cost no more than a bare call:

    no sink attached, event(code, path=..., events=...)      76 ns
    sink attached, level below MIN_LEVEL                     86 ns
    enabled and buffered                                    618 ns
    count(slot)                                              50 ns   (R3: target 66)
    compile-gated site, `if REPORT_TRACE:`                    16 ns   (R2)

The 76 ns is not the ~16 ns Report 3 estimated, and the reason is structural
rather than fixable by reordering: **`**fields` packs a dict before the function
body runs**, measured at ~43 ns for two fields, so no gate inside the function
can precede it. Report's figure assumed a bare call with no keyword arguments.

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

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from codess.reporting.buffer import EventRing, flush_when
from codess.reporting.clock import duration_seconds, tick
from codess.reporting.codes import (
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
    "code",
    "configure",
    "count",
    "counters",
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
# what Report 12.1 rejects `basicConfig` for while keeping the same shape.
_COUNTERS: list[int] = [0] * COUNTER_COUNT
_SINKS: tuple[Any, ...] = ()
_RING: EventRing | None = None
_MIN_LEVEL: int = WARNING
_PROFILE: Profile | None = None
_ROOTS: Roots = Roots()


def configure(
    profile: str | None = None,
    *,
    privacy: str | None = None,
    roots: dict[str, Any] | None = None,
    sinks: tuple[Any, ...] | None = None,
) -> Profile:
    """Resolve a profile and attach its sinks. Call once per process.

    `sinks` overrides construction for a test that needs to inspect what was
    emitted. Everything else comes from the profile, so a call site cannot know
    or choose its destination (R7).
    """
    global _SINKS, _RING, _MIN_LEVEL, _PROFILE, _ROOTS
    resolved = resolve(profile, privacy)
    _PROFILE = resolved
    _MIN_LEVEL = resolved.min_level
    _ROOTS = Roots(roots) if roots else Roots()
    _SINKS = (
        sinks if sinks is not None
        else build(resolved.sinks, privacy=resolved.privacy, roots=_ROOTS)
    )
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


# --- count -------------------------------------------------------------------


def count(index: int, amount: int = 1) -> None:
    """Add to a preallocated counter slot.

    Ungated on purpose. An integer add against a list slot is 66 ns and
    allocates nothing (Report 2.3), so gating it would add a branch that costs a
    measurable fraction of the operation it protects. Counters are also wanted
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
        # sink materializes a mapping only when it renders (Report 5).
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
