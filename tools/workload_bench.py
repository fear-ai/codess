#!/usr/bin/env python3
"""Run the repeatable ingest and query workloads and report their evidence.

Establishes what "too slow" means, so a bound chosen later has a measurement
behind it rather than an argument. Every figure is reported together: phase
timing, rows, source bytes, peak allocation, SQLite plans, and a digest over
the ordered result.

Two sizes per workload. The correctness case is small enough to assert exact
results on and exists to prove the measurement measures the right thing; the
scale case is large enough that per-record cost dominates fixed overhead and is
where a regression is visible. Sizes are anchored to the largest real store
measured -- 76,329 Events in 584 MB -- rather than chosen.

    python tools/workload_bench.py                    # both sizes, all workloads
    python tools/workload_bench.py --size correctness # fast, for a check
    python tools/workload_bench.py --json report.json # machine-readable
    python tools/workload_bench.py --baseline old.json  # compare two runs

`--baseline` is the comparison that matters: it reports whether the results are
*equal* before it reports whether the run was faster, because a faster run
returning different rows is a defect rather than an improvement.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from codess.cursor_source import (  # noqa: E402
    connect_readonly,
    iter_bubble_rows,
)
from codess.query_api import execute, make_request  # noqa: E402
from codess.store import connect, init_db  # noqa: E402
from codess.workload import (  # noqa: E402
    CASE_SIZES,
    Workload,
    query_plan,
    result_digest,
    store_bytes,
)


def _build_store(path: Path, events: int) -> tuple[int, int]:
    """Write a store with `events` Events spread over Sessions of 500.

    Sessions of 500 rather than one enormous Session, because a real corpus is
    many Sessions and a query that filters by Session behaves differently when
    there is only one to find. The largest real Session observed holds 19,661
    Events, so 500 is well inside what a vendor produces.
    """
    from store_fixtures import insert_event, insert_session

    init_db(path)
    conn = connect(path)
    # Sessions of at most 500, and never more Events than asked for: rounding a
    # requested 50 up to a full 500 would make the correctness case measure a
    # different shape than its name states, and its per-row figure would not be
    # comparable with the scale case.
    per_session = min(500, events)
    sessions = max(1, events // per_session)
    remainder = events - sessions * per_session
    try:
        for index in range(sessions):
            session_id = f"s{index:05d}"
            insert_session(conn, session_id, source="Claude", project_path="/w/p")
            count = per_session + (remainder if index == sessions - 1 else 0)
            for offset in range(count):
                sequence = offset + 1
                insert_event(
                    conn, session_id, f"e{offset:05d}",
                    sequence_no=sequence,
                    event_at=1_700_000_000_000 + sequence,
                    event_kind="message.prompt" if offset % 3 == 0 else "tool.call",
                    actor_kind="human" if offset % 3 == 0 else "model",
                    content_role="prompt" if offset % 3 == 0 else "tool_input",
                    origin_kind="direct",
                    tool_name=None if offset % 3 == 0 else "Read",
                    content=f"workload record {index}-{offset} distinctive-phrase"
                    if offset % 97 == 0 else f"record {index}-{offset}",
                )
        conn.commit()
    finally:
        conn.close()
    return sessions, events


def query_workload(size: str, root: Path) -> Workload:
    """Measure the four typed query actions over one store.

    The actions are measured separately rather than as one total because they
    have different shapes: `overview` aggregates every Event, `search` filters to
    a few, and averaging them hides which one is slow.
    """
    target = CASE_SIZES[size]
    store_dir = root / "project" / ".codess"
    store_dir.mkdir(parents=True, exist_ok=True)
    store = store_dir / "sessions_cc.db"
    sessions, events = _build_store(store, target)

    work = Workload(
        f"query/{size}", size=size, sessions=sessions, events=events,
        store_bytes=store_bytes(store),
    )
    conn = connect(store, read_only=True)
    scope = [{"conn": conn, "path": store, "project_path": root / "project"}]
    try:
        for action, filters in (
            ("overview", {}),
            ("sessions", {}),
            ("events", {"event_kinds": ["tool.call"]}),
            ("search", {"text": "distinctive-phrase"}),
        ):
            def body(m, action=action, filters=filters):
                # `overview` aggregates rather than returning rows, and the
                # request contract refuses a limit on it -- which is the contract
                # being right: a bound on an aggregate would silently change the
                # number rather than truncate a list.
                limit = None if action == "overview" else 1000
                request = make_request(action, filters=filters, limit=limit)
                result = execute(scope, request)
                rows = result.get("rows", [])
                m.rows = len(rows) or int(
                    result.get("summary", {}).get("events", 0) or 0
                )
                m.source_bytes = store_bytes(store)
                m.result_digest = result_digest(rows, run_root=root)
                m.notes = {"action": action}
            work.measure(action, body)

        # The plan for the predicate every Event selection uses. A scan here is
        # the regression a timing may not show until the corpus grows.
        plan_phase = work.measure(
            "events_plan",
            lambda m: m.plans.extend(query_plan(
                conn,
                "SELECT id FROM events WHERE session_id=? AND event_kind=? "
                "ORDER BY sequence_no",
                ("s00000", "tool.call"),
            )),
            trace_memory=False,
        )
        plan_phase.notes = {"subject": "events by session and kind"}
    finally:
        conn.close()
    return work


def ingest_workload(size: str, root: Path) -> Workload:
    """Measure writing Events into a store, which is ingest's dominant cost.

    Decode is measured by the adapter tests against real Sources; this measures
    the store write path, because that is what every vendor shares and what a
    transaction boundary or an index change affects.
    """
    target = CASE_SIZES[size]
    store = root / "ingest" / "sessions_cc.db"
    store.parent.mkdir(parents=True, exist_ok=True)

    work = Workload(f"ingest/{size}", size=size, events=target)

    def body(m):
        sessions, events = _build_store(store, target)
        m.rows = events
        m.source_bytes = store_bytes(store)
        m.notes = {"sessions": sessions}
        conn = connect(store, read_only=True)
        try:
            # The digest is over stored counts rather than every row: the claim
            # is that the same input produces the same store, and reading 20,000
            # rows back to hash them would measure the read path inside a write
            # measurement.
            m.result_digest = result_digest({
                "sessions": conn.execute(
                    "SELECT COUNT(*) FROM sessions").fetchone()[0],
                "events": conn.execute(
                    "SELECT COUNT(*) FROM events").fetchone()[0],
            })
        finally:
            conn.close()

    work.measure("store_write", body)
    return work


def cursor_workload(size: str, root: Path) -> Workload:
    """Measure selected Cursor work as *unrelated* container content grows.

    Only answerable by measurement: a
    shared vendor database holds every workspace an operator has, so the cost of
    reading one Project's Sessions must track the selection rather than the
    container. The two are indistinguishable at one container size, which is why
    this measures the same selection against a small and a large database.

    Independence is the assertion. If the selected read costs the same either
    way, work is proportional to the selection; if it grows with the container,
    the key-range scoping is not doing what it claims.
    """
    from cursor_fixtures import create_bubble_table, put_bubbles

    target = CASE_SIZES[size]
    selected = "c00000"
    work = Workload(
        f"cursor/{size}", size=size, selected_composer=selected,
        unrelated_bubbles=target,
    )

    for label, unrelated in (("small_container", 0), ("large_container", target)):
        db = root / f"{label}.vscdb"
        conn = sqlite3.connect(db)
        try:
            create_bubble_table(conn)
            # The selection is identical in both databases; only the volume of
            # content belonging to other composers differs.
            put_bubbles(conn, [
                (selected, f"b{i:05d}", {"text": f"selected {i}", "type": 1})
                for i in range(200)
            ])
            if unrelated:
                put_bubbles(conn, [
                    (f"z{other:05d}", f"b{i:05d}",
                     {"text": f"unrelated {other}-{i}", "type": 1})
                    for other in range(max(1, unrelated // 200))
                    for i in range(200)
                ])
            conn.commit()
        finally:
            conn.close()

        def body(m, db=db, label=label):
            read = connect_readonly(db)
            try:
                rows = list(iter_bubble_rows(read, {selected}))
                m.rows = len(rows)
                m.source_bytes = store_bytes(db)
                m.result_digest = result_digest(
                    [key for key, _ in rows], run_root=root,
                )
                m.plans = query_plan(
                    read,
                    "SELECT key, value FROM cursorDiskKV WHERE key >= ? AND key < ?",
                    ("bubbleId:x:", "bubbleId:x;"),
                )
                m.notes = {"container": label}
            finally:
                read.close()

        work.measure(label, body)
    return work


WORKLOADS = {
    "query": query_workload,
    "ingest": ingest_workload,
    "cursor": cursor_workload,
}


def _render(reports: list[dict]) -> None:
    for report in reports:
        shape = ", ".join(f"{k}={v}" for k, v in report["shape"].items())
        print(f"\n{report['workload']}  ({shape})")
        print(f"  {'phase':16} {'seconds':>9} {'rows':>8} {'us/row':>9} {'peak KiB':>9}")
        for phase in report["phases"]:
            per_row = phase["per_row_us"]
            print(
                f"  {phase['name']:16} {phase['seconds']:>9.4f} "
                f"{phase['rows']:>8} "
                f"{'-' if per_row is None else format(per_row, '>9.2f')} "
                f"{phase['peak_bytes'] // 1024:>9}"
            )
            for line in phase["plans"]:
                print(f"      plan: {line}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--size", choices=(*CASE_SIZES, "all"), default="all",
        help="which case size to run; correctness is fast",
    )
    parser.add_argument(
        "--workload", choices=(*WORKLOADS, "all"), default="all",
    )
    parser.add_argument("--json", type=Path, help="write the report here")
    parser.add_argument(
        "--baseline", type=Path,
        help="compare against a report written by an earlier --json run",
    )
    args = parser.parse_args(argv)

    sizes = list(CASE_SIZES) if args.size == "all" else [args.size]
    names = list(WORKLOADS) if args.workload == "all" else [args.workload]

    runs: list[Workload] = []
    with tempfile.TemporaryDirectory(prefix="codess-workload-") as tmp:
        root = Path(tmp)
        for name in names:
            for size in sizes:
                case = root / f"{name}-{size}"
                case.mkdir()
                runs.append(WORKLOADS[name](size, case))

    reports = [run.report() for run in runs]
    _render(reports)

    if args.json:
        args.json.write_text(
            json.dumps({"runs": reports}, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"\nwrote {args.json}")

    if args.baseline:
        previous = {
            item["workload"]: item
            for item in json.loads(args.baseline.read_text())["runs"]
        }
        print("\ncomparison against baseline")
        unequal = 0
        for run in runs:
            old = previous.get(run.name)
            if old is None:
                print(f"  {run.name:22} absent from baseline")
                continue
            for phase in run.measurements:
                match = next(
                    (p for p in old["phases"] if p["name"] == phase.name), None
                )
                if match is None:
                    continue
                same = match["result_digest"] == phase.result_digest
                if not same:
                    unequal += 1
                ratio = (
                    phase.seconds / match["seconds"] if match["seconds"] else None
                )
                verdict = "EQUAL" if same else "**DIFFERENT**"
                print(
                    f"  {run.name}/{phase.name:16} results {verdict:14} "
                    f"time x{'-' if ratio is None else format(ratio, '.2f')}"
                )
        if unequal:
            print(
                f"\n{unequal} phase(s) returned different results. A faster run "
                "that returns different rows is a defect, not an improvement."
            )
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
