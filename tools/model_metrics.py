#!/usr/bin/env python3
"""Comparative model, tool, and Session measures across published store sets.

Answers the questions a developer or designer asks of their own recorded work:
which tools dominate, how a harness spends a Session, where tools fail, how long
they take, and how the three vendors differ in what they record.

**Every measure is a count or a duration the vendor recorded.** Nothing here
estimates price, quota, or a rate the store cannot see, and nothing rates the
quality of the work: those need authority the local evidence does not have.
Where a figure is comparable only within one vendor, the report says so on the
row rather than in prose a reader may skip.

**Comparability is the hard part, not the SQL.** Three findings shape every
measure below:

- *A tool call is harness-mediated.* Cursor records a call for operations
  Claude performs another way, so a raw tool count ranks harnesses rather than
  work. Tool measures are reported per vendor and never summed across them.
- *Event counts are not comparable either.* Between 46% and 80% of a store is
  tool traffic, and human prompts are 3-4% of Codex and Cursor. A raw Event
  count measures how tool-heavy a harness is.
- *Only the human-prompt count is comparable across vendors*, because Actor
  classification is the part CoSchema normalizes and validates for all three.

    python tools/model_metrics.py                  # every measure, as JSON
    python tools/model_metrics.py --measure tools  # one measure
    python tools/model_metrics.py --html out.html  # the visual report
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from codess.config import STORE_ROOT  # noqa: E402

# A duration longer than this is a Session left open rather than a tool that
# ran for an hour: the result Event carries the time the harness wrote it, and
# a suspended laptop lands between the two. Bounded so one such pair cannot
# move a percentile.
MAX_TOOL_DURATION_MS = 3_600_000

# Percentiles reported for every duration. p50 is what a run feels like; p99 is
# what a reader remembers, and the gap between them is the finding.
PERCENTILES = (50, 90, 99)


def _percentile(ordered: list[float], percentile: int) -> float | None:
    """One percentile of an already-sorted list, or None when it is empty."""
    if not ordered:
        return None
    index = min(int(len(ordered) * percentile / 100), len(ordered) - 1)
    return ordered[index]


def _distribution(values: list[float]) -> dict[str, Any]:
    """Count, percentiles, and whether the durations are measurable at all.

    A percentile over four observations is arithmetic rather than evidence, and
    the `n` beside it is what says so.

    **`resolution` is the load-bearing field.** Cursor writes the call bubble
    and its result bubble with the same `createdAt`, so 83% of its pairs are
    exactly 0 ms -- a property of how the vendor stamps records, not a tool that
    returned instantly. Reporting that as a p50 would state a performance
    result the evidence cannot support, so a measure whose observations are
    mostly zero is marked `same_timestamp` and a reader is told to compare it
    only within its vendor.
    """
    ordered = sorted(values)
    zeros = sum(1 for value in ordered if value == 0)
    summary: dict[str, Any] = {
        "n": len(ordered),
        "zero_share": round(zeros / len(ordered), 4) if ordered else None,
    }
    for percentile in PERCENTILES:
        value = _percentile(ordered, percentile)
        summary[f"p{percentile}"] = round(value) if value is not None else None
    if not ordered:
        summary["resolution"] = "none"
    elif zeros / len(ordered) > 0.5:
        # The vendor timestamps both records identically, so the pair states
        # ordering rather than elapsed time.
        summary["resolution"] = "same_timestamp"
    else:
        summary["resolution"] = "measured"
    return summary


def published_stores(store_root: Path) -> list[tuple[str, Path]]:
    """Every current store, as `(project_id, path)`.

    Reads the published pointer rather than globbing the snapshot tree: a
    superseded snapshot is still on disk, and counting it would report one
    Project twice at two different ages.
    """
    found: list[tuple[str, Path]] = []
    for pointer in sorted((store_root / "projects").glob("*/current.json")):
        try:
            snapshot = json.loads(pointer.read_text(encoding="utf-8")).get("path")
        except (OSError, ValueError):
            continue
        if not snapshot or not Path(snapshot).is_dir():
            continue
        found.extend(
            (pointer.parent.name, database)
            for database in sorted(Path(snapshot).glob("*.db"))
        )
    return found


def _vendor(conn: sqlite3.Connection) -> str:
    row = conn.execute(
        "SELECT source_system_id FROM sessions LIMIT 1",
    ).fetchone()
    return str(row[0]) if row and row[0] else "unknown"


def collect(store_root: Path) -> dict[str, Any]:
    """Gather every measure in one pass per store.

    One pass because opening a store is the expensive part: the largest is
    621 MiB, and a measure-per-open would read it six times to answer six
    questions about the same rows.
    """
    tools: dict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {"calls": 0, "failed": 0, "denied": 0, "durations": []},
    )
    vendors: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "sessions": 0, "events": 0, "tool_calls": 0, "human_prompts": 0,
            "model_turns": 0, "input_tokens": 0, "output_tokens": 0,
            "projects": set(), "kinds": defaultdict(int),
        },
    )
    models: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"turns": 0, "sessions": set(), "vendors": set()},
    )

    for project_id, database in published_stores(store_root):
        conn = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            vendor = _vendor(conn)
            bucket = vendors[vendor]
            bucket["projects"].add(project_id)
            for name, query in (
                ("sessions", "SELECT count(*) FROM sessions"),
                ("events", "SELECT count(*) FROM events"),
                ("model_turns", "SELECT count(*) FROM model_turns"),
                ("tool_calls", "SELECT count(*) FROM tool_invocations"),
            ):
                bucket[name] += int(conn.execute(query).fetchone()[0])
            bucket["human_prompts"] += int(conn.execute(
                "SELECT count(*) FROM events WHERE event_kind='message.prompt' "
                "AND actor_kind='human'",
            ).fetchone()[0])
            row = conn.execute(
                "SELECT coalesce(sum(input_tokens),0), coalesce(sum(output_tokens),0) "
                "FROM events",
            ).fetchone()
            bucket["input_tokens"] += int(row[0])
            bucket["output_tokens"] += int(row[1])
            for kind, count in conn.execute(
                "SELECT event_kind, count(*) FROM events GROUP BY 1",
            ):
                bucket["kinds"][str(kind or "unknown")] += int(count)

            for row in conn.execute(
                "SELECT mp.model_name_exact, count(*) AS turns, "
                "  count(DISTINCT mt.session_id) AS sessions "
                "FROM model_turns mt JOIN model_params mp ON mp.id = mt.model_param_id "
                "WHERE mp.model_name_exact IS NOT NULL GROUP BY 1",
            ):
                entry = models[str(row[0])]
                entry["turns"] += int(row["turns"])
                entry["vendors"].add(vendor)
                entry["sessions"].add((project_id, int(row["sessions"])))

            for row in conn.execute(
                "SELECT i.canonical_tool_name AS name, r.normalized_status AS status, "
                "  count(*) AS calls "
                "FROM tool_invocations i "
                "LEFT JOIN tool_results r ON r.invocation_id = i.id "
                "GROUP BY 1, 2",
            ):
                entry = tools[(vendor, str(row["name"] or "unknown"))]
                entry["calls"] += int(row["calls"])
                if row["status"] == "failed":
                    entry["failed"] += int(row["calls"])
                elif row["status"] == "denied":
                    entry["denied"] += int(row["calls"])

            # Duration from the call Event to the result Event. `tool_results`
            # has no completion time of its own, so the timeline is the only
            # place the pair is measurable.
            for row in conn.execute(
                "SELECT i.canonical_tool_name AS name, "
                "  er.event_at - ec.event_at AS elapsed "
                "FROM tool_invocations i "
                "JOIN events ec ON ec.id = i.requested_event_id "
                "JOIN tool_results r ON r.invocation_id = i.id "
                "JOIN events er ON er.id = r.result_event_id "
                "WHERE ec.event_at IS NOT NULL AND er.event_at IS NOT NULL",
            ):
                elapsed = row["elapsed"]
                if elapsed is None or not 0 <= elapsed <= MAX_TOOL_DURATION_MS:
                    continue
                tools[(vendor, str(row["name"] or "unknown"))]["durations"].append(
                    float(elapsed),
                )
        except sqlite3.Error:
            # A store that cannot answer one question still answers the others,
            # and a report that aborts on the first unreadable store measures
            # whichever ones happened to sort first.
            continue
        finally:
            conn.close()

    return {
        "vendors": _vendor_rows(vendors),
        "tools": _tool_rows(tools),
        "models": _model_rows(models),
    }


def _vendor_rows(vendors: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for vendor, values in vendors.items():
        # A store set holds one database per vendor whether that vendor
        # contributed or not, so an empty one names no vendor and would appear
        # as a row of zeros under `unknown`. Absence of a Session is absence of
        # evidence about a vendor, not a measurement of it.
        if not values["sessions"]:
            continue
        events = values["events"] or 1
        tool_events = sum(
            count for kind, count in values["kinds"].items()
            if kind.startswith("tool.")
        )
        rows.append({
            "vendor": vendor,
            "projects": len(values["projects"]),
            "sessions": values["sessions"],
            "events": values["events"],
            "model_turns": values["model_turns"],
            "tool_calls": values["tool_calls"],
            # The one measure comparable across vendors, because Actor
            # classification is what CoSchema normalizes for all three.
            "human_prompts": values["human_prompts"],
            "tool_event_share": round(tool_events / events, 4),
            "events_per_session": round(values["events"] / max(values["sessions"], 1), 1),
            "input_tokens": values["input_tokens"],
            "output_tokens": values["output_tokens"],
        })
    return sorted(rows, key=lambda row: -row["events"])


def _tool_rows(tools: dict[tuple[str, str], dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for (vendor, name), values in tools.items():
        calls = values["calls"] or 1
        rows.append({
            "vendor": vendor,
            "tool": name,
            "calls": values["calls"],
            "failed": values["failed"],
            "denied": values["denied"],
            "failure_rate": round(values["failed"] / calls, 4),
            "duration_ms": _distribution(values["durations"]),
        })
    return sorted(rows, key=lambda row: -row["calls"])


def _model_rows(models: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows = [
        {
            "model": name,
            "turns": values["turns"],
            "sessions": sum(count for _project, count in values["sessions"]),
            "vendors": sorted(values["vendors"]),
        }
        for name, values in models.items()
    ]
    return sorted(rows, key=lambda row: -row["turns"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--store", dest="store_root", type=Path, default=STORE_ROOT,
        help="the machine's durable store (default: %(default)s)",
    )
    parser.add_argument(
        "--measure", choices=("vendors", "tools", "models"),
        help="report one measure rather than all of them",
    )
    parser.add_argument(
        "--out", type=Path, help="write JSON here instead of stdout",
    )
    parser.add_argument(
        "--html", type=Path, help="also write the visual report here",
    )
    parser.add_argument(
        "--top", type=int, default=12,
        help="rows per ranked measure in the visual report (default: %(default)s)",
    )
    args = parser.parse_args(argv)

    report = collect(args.store_root.expanduser())
    if args.measure:
        report = {args.measure: report[args.measure]}
    payload = json.dumps(report, indent=2, sort_keys=True)
    if args.out:
        args.out.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    if args.html:
        from model_metrics_report import render

        args.html.write_text(render(report, top=args.top), encoding="utf-8")
        print(f"wrote {args.html}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
