#!/usr/bin/env python3
"""Measure the costs Report.md's design rests on.

Every figure in Report.md 2 comes from here. It exists so a reader can
re-run the measurements rather than trust them, and so a later change to the
reporting facility can be checked against the same baseline on the machine
that will run it -- these are platform and interpreter specific, and the
design conclusions follow from ratios rather than absolutes.
"""

from __future__ import annotations

import argparse
import platform
import sys
import time
import timeit
from collections import Counter, deque
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import NamedTuple


def _ns(fn, number: int) -> float:
    return timeit.timeit(fn, number=number) / number * 1e9


class _EventTuple(NamedTuple):
    code: str
    tick: int
    a: int
    b: str


@dataclass(slots=True)
class _EventSlots:
    code: str
    tick: int
    a: int
    b: str


@dataclass
class _EventDataclass:
    code: str
    tick: int
    a: int
    b: str


def clocks(number: int) -> list[tuple[str, float, str]]:
    """Cost and resolution of every candidate time source."""
    candidates = {
        "time.monotonic": time.monotonic,
        "time.monotonic_ns": time.monotonic_ns,
        "time.perf_counter": time.perf_counter,
        "time.perf_counter_ns": time.perf_counter_ns,
        "time.time": time.time,
        "time.time_ns": time.time_ns,
        "time.process_time_ns": time.process_time_ns,
    }
    rows = []
    for name, fn in candidates.items():
        try:
            resolution = f"{time.get_clock_info(name.split('.')[1].removesuffix('_ns')).resolution * 1e9:.0f} ns"
        except (ValueError, AttributeError):
            resolution = "-"
        rows.append((name, _ns(fn, number), resolution))
    return rows


def structures(number: int) -> list[tuple[str, float]]:
    """Cost of constructing one event, by candidate structure."""
    return [
        ("plain tuple", _ns(lambda: ("x", 1, 2, "y"), number)),
        ("dict literal, 4 keys", _ns(lambda: {"code": "x", "tick": 1, "a": 2, "b": "y"}, number)),
        ("dataclass(slots=True)", _ns(lambda: _EventSlots("x", 1, 2, "y"), number)),
        ("dataclass", _ns(lambda: _EventDataclass("x", 1, 2, "y"), number)),
        ("NamedTuple", _ns(lambda: _EventTuple("x", 1, 2, "y"), number)),
    ]


def counters(number: int) -> list[tuple[str, float]]:
    """Cost of one counter increment, by candidate structure."""
    mapping: dict[str, int] = {}
    counter: Counter[str] = Counter()
    slots = [0] * 64
    return [
        ("list[index] += 1", _ns(lambda: slots.__setitem__(7, slots[7] + 1), number)),
        ("dict.get(k, 0) + 1", _ns(lambda: mapping.__setitem__("k", mapping.get("k", 0) + 1), number)),
        ("Counter[k] += 1", _ns(lambda: counter.__setitem__("k", counter["k"] + 1), number)),
    ]


def formatting(number: int) -> list[tuple[str, float]]:
    """Cost of the timestamp work the current facility does per call."""
    anchor_wall, anchor_tick = time.time_ns(), time.monotonic_ns()
    tick = time.monotonic_ns()

    def resolve() -> str:
        wall = anchor_wall + (tick - anchor_tick)
        return datetime.fromtimestamp(wall / 1e9, UTC).isoformat(timespec="milliseconds")

    ring: deque = deque(maxlen=2000)
    return [
        ("datetime.now(UTC).isoformat(ms)  [eager]", _ns(
            lambda: datetime.now(UTC).isoformat(timespec="milliseconds"), number)),
        ("datetime.now(UTC)", _ns(lambda: datetime.now(UTC), number)),
        ("monotonic_ns()  [deferred]", _ns(time.monotonic_ns, number)),
        ("resolve one tick at flush", _ns(resolve, number)),
        ("deque append", _ns(lambda: ring.append(1), number)),
    ]


def guards(number: int) -> list[tuple[str, float]]:
    """Cost of each gate that can reject a disabled call site."""
    namespace: dict = {"slots": [0] * 64}
    exec(compile("def folded():\n if False:\n  slots[7] += 1\n", "<bench>", "exec"), namespace)

    enabled = False

    def module_global() -> None:
        if enabled:
            namespace["slots"][7] += 1

    class _Reporter:
        __slots__ = ("sinks",)

        def __init__(self) -> None:
            self.sinks: tuple = ()

        def event(self, code: str, **fields: object) -> dict | None:
            if not self.sinks:
                return None
            return {"code": code, **fields}

    reporter = _Reporter()
    return [
        ("if False:  [compile-time folded]", _ns(namespace["folded"], number)),
        ("bare function call  [the floor]", _ns(lambda: None, number)),
        ("closure variable guard", _ns(module_global, number)),
        ("run-time sink check, no sinks", _ns(lambda: reporter.event("decode.record", n=1), number)),
    ]


def flushing(number: int) -> list[tuple[str, float]]:
    """Per-event cost of writing, batched against unbatched."""
    import io

    events = max(1000, number // 20)

    def per_call() -> None:
        stream = io.StringIO()
        for index in range(events):
            print(f"codess: progress evt n={index}", file=stream, flush=True)

    def batched() -> None:
        stream = io.StringIO()
        buffer: list[str] = []
        for index in range(events):
            buffer.append(f"codess: progress evt n={index}")
            if len(buffer) >= 256:
                stream.write("\n".join(buffer) + "\n")
                buffer.clear()
        if buffer:
            stream.write("\n".join(buffer) + "\n")

    return [
        ("per-call write + flush", timeit.timeit(per_call, number=5) / 5 / events * 1e9),
        ("batched, 256 events", timeit.timeit(batched, number=5) / 5 / events * 1e9),
    ]


def current_facility(number: int) -> list[tuple[str, float]]:
    """What `ProgressTrace` costs today, with output disabled."""
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1] / "src"))
    from codess.progress import ProgressTrace

    trace = ProgressTrace(enabled=False)
    return [("ProgressTrace(enabled=False)", _ns(lambda: trace("decode.record", n=1), number))]


SECTIONS = {
    "clocks": clocks,
    "structures": structures,
    "counters": counters,
    "formatting": formatting,
    "guards": guards,
    "flushing": flushing,
    "current": current_facility,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--number", type=int, default=200_000, help="iterations per case")
    parser.add_argument(
        "--section", action="append", choices=sorted(SECTIONS),
        help="run only these sections (repeatable)",
    )
    args = parser.parse_args(argv)

    print(f"python {sys.version.split()[0]}  {platform.machine()}  {platform.system()}")
    print(f"iterations per case: {args.number:,}\n")

    for name in args.section or list(SECTIONS):
        rows = SECTIONS[name](args.number)
        print(f"--- {name}")
        for row in rows:
            label, cost = row[0], row[1]
            suffix = f"   {row[2]}" if len(row) > 2 else ""
            print(f"  {label:44s} {cost:9.1f} ns{suffix}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
