"""One wall reading, one monotonic anchor, and a tick per event.

Formatting a timestamp costs 816 ns and reading a monotonic tick costs 25 ns
(Report 2.1, 2.5), and most events are never rendered -- so the call site
records a tick and the sink resolves it to wall-clock text only for the events
it actually emits. That is Report R4, and it is 58% of the current per-call
cost.

Resolution works because both clocks advance at the same rate within a process:
an offset captured once converts any later tick to a wall instant. Verified
accurate to the millisecond against a direct reading (Report 2.6).

Monotonic is the tick source rather than wall clock because it cannot move
backwards. An NTP correction mid-run would make a wall-clock duration negative,
which CoPlan 14.4 already records as a real hazard for ingest timing.
"""

from __future__ import annotations

import time

# Captured at import, which is process start for every path that reports.
# Reading both within a few microseconds of each other is what bounds the
# conversion error; taking them lazily on first event would fold whatever
# happened in between into every timestamp.
ANCHOR_WALL_NS = time.time_ns()
ANCHOR_TICK_NS = time.monotonic_ns()

tick = time.monotonic_ns
"""The hot-path clock, bound directly so a call site pays no wrapper.

Report 12.1 rejects `process_time_ns` (203 ns) and a raw hardware counter: the
first measures CPU rather than elapsed time, and the second saves ~20 ns while
giving up frequency-scaling correctness, core-migration safety, and portability.
"""


def wall_ns(event_tick: int) -> int:
    """Resolve one tick to a wall-clock instant in nanoseconds."""
    return ANCHOR_WALL_NS + (event_tick - ANCHOR_TICK_NS)


def elapsed_seconds(event_tick: int) -> float:
    """Seconds from process start to `event_tick`."""
    return (event_tick - ANCHOR_TICK_NS) / 1_000_000_000


def duration_seconds(start_tick: int, end_tick: int) -> float:
    """Seconds between two ticks, never involving the anchor.

    A duration is a difference of monotonic readings and stays correct across a
    clock adjustment. Deriving it from resolved wall instants would reintroduce
    exactly the hazard the monotonic tick avoids.
    """
    return (end_tick - start_tick) / 1_000_000_000
