"""A fixed-capacity ring for events, and the policy that decides when to flush.

Report R5: output is batched, and flush is a policy rather than something every
call performs. The current facility writes and flushes per call, which is why a
progress line costs 1,245 ns of which most is formatting and I/O nobody asked
for (Report 2.1).

**The ring never grows.** A preallocated list with a write index bounds memory
by construction, which is what lets a long ingest report without accumulating a
record per event. Overwriting the oldest event is the right loss: recent events
explain a failure, and the count of what was dropped is itself reported so the
bound is visible rather than silent.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

from codess.reporting.codes import WARNING

DEFAULT_CAPACITY = 2_000
"""Report 6's `MAX_RETAINED`. Sized for a report, not for a transcript."""

DEFAULT_FLUSH_EVENTS = 256
"""Report 6's `FLUSH_EVENTS`: how many events accumulate before a write."""


class EventRing:
    """Bounded event storage with a batch-and-drain flush policy.

    Holds tuples, not rendered strings: a sink decides its own format, and an
    event kept as a structure can reach a second sink in a different one
    (Report 10).
    """

    __slots__ = (
        "_capacity", "_flush_events", "_pending", "_slots", "_stored",
        "_write", "dropped",
    )

    def __init__(
        self, capacity: int = DEFAULT_CAPACITY,
        *, flush_events: int = DEFAULT_FLUSH_EVENTS,
    ) -> None:
        if capacity < 1:
            raise ValueError("ring capacity must be at least 1")
        self._capacity = capacity
        self._slots: list[tuple | None] = [None] * capacity
        self._write = 0
        self._stored = 0
        self._pending = 0
        self._flush_events = max(1, flush_events)
        self.dropped = 0

    def append(self, event: tuple) -> bool:
        """Store one event; return whether the flush threshold was reached.

        A warning or error returns True regardless of the batch count. Deferring
        a failure behind 255 routine events would mean the operator sees the
        problem after the run that caused it, which is the one case where
        latency matters more than throughput (Report 8).
        """
        if self._stored == self._capacity:
            self.dropped += 1
        else:
            self._stored += 1
        self._slots[self._write] = event
        self._write = (self._write + 1) % self._capacity
        self._pending += 1
        return self._pending >= self._flush_events or event[2] >= WARNING

    def drain(self) -> list[tuple]:
        """Return the events written since the last drain, oldest first.

        Clears the pending count but not the ring: retained events remain
        readable for a report after they have been emitted, which is what lets
        one run both stream to stderr and write a durable summary.
        """
        pending = min(self._pending, self._stored)
        self._pending = 0
        if not pending:
            return []
        start = (self._write - pending) % self._capacity
        if start + pending <= self._capacity:
            window = self._slots[start:start + pending]
        else:
            head = self._capacity - start
            window = self._slots[start:] + self._slots[:pending - head]
        return [event for event in window if event is not None]

    @property
    def flush_events(self) -> int:
        """The batch size at which `append` reports a flush is due."""
        return self._flush_events

    @property
    def pending(self) -> int:
        """Events written since the last drain."""
        return self._pending

    def retained(self) -> Iterator[tuple]:
        """Every event still held, oldest first."""
        if self._stored < self._capacity:
            source = self._slots[:self._stored]
        else:
            source = self._slots[self._write:] + self._slots[:self._write]
        for event in source:
            if event is not None:
                yield event

    def __len__(self) -> int:
        return self._stored


def flush_when(
    ring: EventRing, emit: Callable[[list[tuple]], None], *, force: bool = False,
) -> int:
    """Drain and emit, returning how many events were written.

    `force` is for a phase or process boundary, where the remaining partial
    batch must reach the sink before the operation that produced it ends.
    """
    if not force and ring.pending < ring.flush_events:
        return 0
    events = ring.drain()
    if events:
        emit(events)
    return len(events)
