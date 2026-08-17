"""Repeatable performance workloads: what to measure, and what to record with it.

A timing on its own is not evidence. CoPlan 11.4 requires that performance
evidence record the selected shape, phase timing, source bytes, selected record
counts, SQLite plans and rows visited, memory, and the ordered result identity --
because an optimization is only complete when *the functional result is
unchanged* and the measured bottleneck improves. A run that got faster and
returned different rows has not improved anything.

**Why this exists before the bounds that need it.** Bounding a read without a
repeatable workload means choosing the limit by argument: any number can be
defended when nothing measures the cost of being wrong. The workloads here are
the measurement those decisions are made against.

**Two case sizes, not one.** A correctness case is small enough to assert exact
results on, and a scale case is large enough for a per-record cost to dominate
the fixed overhead. Both are required for the same reason: the small one proves
the measurement is measuring the right thing, and the large one is where a
regression is visible. A single mid-sized case answers neither question well.

Scale is anchored to measured reality rather than chosen: the largest real store
observed holds 76,329 Events in 584 MB, and 63 stores hold 236,553 Events
between them. A scale case an order of magnitude below that measures fixed
overhead; one far above it measures a situation no operator has.

**Result identity is part of the measurement.** Every workload records a digest
over its ordered result, so two runs can be compared for equality rather than
inspected. That is what makes "the functional result remains equal" checkable
instead of asserted.
"""

from __future__ import annotations

import gc
import sqlite3
import tracemalloc
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from codess.hashing import codess_canonical_hash
from codess.reporting.clock import duration_seconds, tick

WORKLOAD_FORMAT = "codess.workload/1"

# Anchored to the largest real store measured (76,329 Events, 584 MB) rather
# than chosen for convenience. `correctness` is small enough to assert exact
# results on; `scale` is large enough that per-record cost dominates the fixed
# cost of opening a store and parsing a request.
CASE_SIZES: dict[str, int] = {
    "correctness": 50,
    "scale": 20_000,
}


@dataclass
class Measurement:
    """One measured phase, with everything CoPlan 11.4 requires beside it.

    A dataclass rather than a dict so a missing field is a construction error
    rather than a report that silently omits the evidence it was supposed to
    carry.
    """

    name: str
    seconds: float
    rows: int = 0
    source_bytes: int = 0
    peak_bytes: int = 0
    result_digest: str | None = None
    plans: list[str] = field(default_factory=list)
    rows_visited: int | None = None
    notes: dict[str, Any] = field(default_factory=dict)

    def per_row_us(self) -> float | None:
        """Microseconds per row, which is the figure that compares across sizes.

        Total time does not: a scale case is slower than a correctness case by
        construction. Per-row cost is what reveals whether work is proportional
        to the selection or to something else.
        """
        if not self.rows:
            return None
        return (self.seconds * 1_000_000) / self.rows

    def report(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "seconds": round(self.seconds, 6),
            "rows": self.rows,
            "per_row_us": (
                None if self.per_row_us() is None else round(self.per_row_us(), 3)
            ),
            "source_bytes": self.source_bytes,
            "peak_bytes": self.peak_bytes,
            "result_digest": self.result_digest,
            "plans": list(self.plans),
            "rows_visited": self.rows_visited,
            **({"notes": self.notes} if self.notes else {}),
        }


@contextmanager
def measured(name: str, *, trace_memory: bool = True) -> Iterator[Measurement]:
    """Time a phase and record its peak allocation.

    `tracemalloc` rather than `resource.getrusage`: peak RSS is a high-water mark
    for the whole process and does not fall when a buffer is released, so it
    cannot distinguish a phase that streamed from one that materialized and freed.
    Allocation tracing costs roughly 2x, which is why it is optional -- a timing
    run and a memory run measure different things and should not be the same run.

    A collection before starting removes the previous phase's garbage from this
    phase's peak. Without it the first measurement in a sequence looks worse than
    the same code measured alone.
    """
    measurement = Measurement(name=name, seconds=0.0)
    gc.collect()
    if trace_memory:
        tracemalloc.start()
    started = tick()
    try:
        yield measurement
    finally:
        measurement.seconds = duration_seconds(started, tick())
        if trace_memory:
            _current, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            measurement.peak_bytes = peak


# Fields whose value is a wall-clock or duration reading. These cannot be equal
# across two runs and carry no information about the result, so excluding them is
# unconditional.
TIMING_FIELDS = frozenset({
    "observed_at", "ingested_at", "created_at", "at", "elapsed_seconds",
    "data_as_of",
})

# Fields that name a filesystem position or a snapshot identity. **Rewritten, not
# excluded.** Excluding them was the first fix and it overcorrected: a query that
# returned a *different Project's* rows compared EQUAL, because the only field
# distinguishing the two was the one being dropped. That is exactly the defect a
# comparison exists to catch.
#
# The distinction that matters is between a path that is part of the answer and
# the scratch directory a run happened to use. Rewriting relative to the run root
# keeps the first and removes the second: two runs in different temporary
# directories produce the same relative path, while two runs returning different
# Projects do not.
LOCATED_FIELDS = frozenset({
    "project_path", "source_project_path", "path", "store_path", "snapshot",
    "snapshot_id", "observation_id",
})


def stable_rows(rows: Any, *, run_root: str | None = None) -> Any:
    """Normalize a result for comparison across runs.

    Timing fields are dropped; located fields are rewritten relative to
    `run_root` when one is given and dropped when it is not. Applied to the
    result rather than inside the digest so a caller can inspect exactly what is
    being compared -- a comparison whose exclusions are invisible is one nobody
    can check.

    `run_root` is the scratch directory a run built its stores in. Supplying it
    is what preserves a path's information content while removing the part that
    differs by construction; omitting it falls back to dropping, which is safe
    but blind to the case above.
    """
    if isinstance(rows, dict):
        normalized = {}
        for key, value in sorted(rows.items()):
            if key in TIMING_FIELDS:
                continue
            if key in LOCATED_FIELDS:
                if run_root is None:
                    continue
                normalized[key] = _relative_to_run(value, run_root)
                continue
            normalized[key] = stable_rows(value, run_root=run_root)
        return normalized
    if isinstance(rows, (list, tuple)):
        return [stable_rows(item, run_root=run_root) for item in rows]
    return rows


def _relative_to_run(value: Any, run_root: str) -> Any:
    """A path with the run's scratch root replaced by a stable token.

    Only the root is replaced, so everything the path says *about the result* --
    which Project, which vendor store, which snapshot -- survives.
    """
    if not isinstance(value, str) or run_root not in value:
        return value
    return value.replace(run_root, "<run>")


def result_digest(rows: Any, *, run_root: str | Path | None = None) -> str:
    """A digest over an ordered result, for comparing two runs.

    Canonical rather than `repr`: the point is that equal content gives an equal
    digest across processes, which `repr` of a dict did not guarantee before
    insertion order was specified and still does not guarantee for a set.

    `run_root` is the scratch directory this run used. Passing it is what lets the
    digest answer "did this return the same rows" while still noticing that a
    *different Project* was returned -- the case a blanket path exclusion missed.
    """
    root = str(run_root) if run_root is not None else None
    return codess_canonical_hash(256, 256, stable_rows(rows, run_root=root))


def query_plan(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[str]:
    """The SQLite plan for one statement, as text lines.

    Recorded because a timing that improved without a plan change is usually
    measuring the page cache, and a plan that changed to a scan is a regression
    a timing may not show until the data grows.
    """
    try:
        return [
            str(row[3]) for row in conn.execute(f"EXPLAIN QUERY PLAN {sql}", params)
        ]
    except sqlite3.Error as exc:
        return [f"unavailable: {exc}"]


def scans_a_table(plans: list[str]) -> bool:
    """Whether any plan line reports a full table scan.

    The assertion a bounded-read workload actually wants to make. A scan is not
    always wrong -- a small table is cheaper scanned than indexed -- so this
    reports rather than judges, and a caller decides which tables may be scanned.
    """
    return any("SCAN" in line and "COVERING INDEX" not in line for line in plans)


class Workload:
    """One named workload: a setup, a measured body, and its recorded evidence.

    Holds its measurements so a caller can compare two runs or assert on one
    phase. The `notes` carry the selected shape -- which Project, which vendor,
    how many records -- because a measurement without its input is not
    reproducible.
    """

    def __init__(self, name: str, **shape: Any) -> None:
        self.name = name
        self.shape = shape
        self.measurements: list[Measurement] = []

    def measure(
        self, phase: str, body: Callable[[Measurement], None],
        *, trace_memory: bool = True,
    ) -> Measurement:
        with measured(phase, trace_memory=trace_memory) as measurement:
            body(measurement)
        self.measurements.append(measurement)
        return measurement

    def phase(self, name: str) -> Measurement | None:
        for measurement in self.measurements:
            if measurement.name == name:
                return measurement
        return None

    def report(self) -> dict[str, Any]:
        return {
            "format": WORKLOAD_FORMAT,
            "workload": self.name,
            "shape": self.shape,
            "phases": [m.report() for m in self.measurements],
        }

    def compare(self, other: Workload) -> dict[str, Any]:
        """Compare two runs: equal results first, then relative cost.

        Result equality is checked before timing and reported first, because a
        faster run that returns different rows is a defect rather than an
        improvement -- which is the property CoPlan 11.4 requires and the reason
        a digest is recorded at all.
        """
        phases: dict[str, Any] = {}
        for mine in self.measurements:
            theirs = other.phase(mine.name)
            if theirs is None:
                phases[mine.name] = {"comparable": False, "reason": "absent"}
                continue
            same = mine.result_digest == theirs.result_digest
            phases[mine.name] = {
                "comparable": True,
                "results_equal": same,
                "seconds": [round(mine.seconds, 6), round(theirs.seconds, 6)],
                "ratio": (
                    round(theirs.seconds / mine.seconds, 3) if mine.seconds else None
                ),
                "peak_bytes": [mine.peak_bytes, theirs.peak_bytes],
            }
        return {
            "workload": self.name,
            "all_results_equal": all(
                item.get("results_equal", False)
                for item in phases.values() if item.get("comparable")
            ),
            "phases": phases,
        }


def store_bytes(path: Path) -> int:
    """Source size, including the WAL sidecar when one exists.

    A store's file size alone understates what was read from a database with an
    active WAL, which is the ordinary state of a vendor container being written
    by its own application.
    """
    total = path.stat().st_size if path.exists() else 0
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(path) + suffix)
        if sidecar.exists():
            total += sidecar.stat().st_size
    return total
