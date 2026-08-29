#!/usr/bin/env python3
"""Report what each retained snapshot holds, and which are safe to delete.

Publication writes a new snapshot and repoints `current.json`, so superseded
generations accumulate. Deciding which to remove needs three facts per
snapshot: what it holds, whether the current one holds it too, and whether its
vendor Sources still exist.

**Most of this needs no database open.** The manifest already records per-store
row counts, a SHA-256 per store, the byte size, the creation time, and the
parent snapshot -- so volume, lineage, and identity are read from JSON. Only
the Session date range requires opening a store, which is why `--ranges` is
opt-in: it is the slow half and is not needed to identify an obvious subset.

A snapshot is reported as `SUBSET` when the current snapshot holds at least as
many Sessions and Events in every store. That is a *candidate* rather than a
verdict: equal counts are strong evidence and not proof of equal content, so
the recommendation is stated and the deletion is the operator's.

    python tools/snapshot_inventory.py                # every project, summary
    python tools/snapshot_inventory.py --ranges       # add Session date ranges
    python tools/snapshot_inventory.py --csv out.csv  # machine-readable
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from codess.config import STORE_ROOT  # noqa: E402


def _iso(milliseconds: float | None) -> str:
    """A stored Unix-millisecond instant as a date, or empty."""
    if not milliseconds:
        return ""
    try:
        return datetime.fromtimestamp(milliseconds / 1000, UTC).strftime("%Y-%m-%d")
    except (OverflowError, OSError, ValueError):
        return ""


def _session_range(snapshot: Path) -> tuple[str, str]:
    """Earliest and latest Session instant across a snapshot's stores.

    Reads `started_at`/`ended_at`, which are the materialized Session bounds,
    rather than scanning Events: the answer is the same and the cost is a table
    of tens of rows instead of tens of thousands.
    """
    low: float | None = None
    high: float | None = None
    for store in sorted(snapshot.glob("sessions_*.db")):
        try:
            connection = sqlite3.connect(f"file:{store}?mode=ro", uri=True)
        except sqlite3.Error:
            continue
        try:
            row = connection.execute(
                "SELECT MIN(started_at), MAX(COALESCE(ended_at, started_at)) "
                "FROM sessions"
            ).fetchone()
        except sqlite3.Error:
            row = None
        finally:
            connection.close()
        if not row:
            continue
        first, last = row
        if first is not None:
            low = first if low is None else min(low, first)
        if last is not None:
            high = last if high is None else max(high, last)
    return _iso(low), _iso(high)


def _totals(manifest: dict) -> tuple[int, int, int]:
    """Sessions, Events, and bytes across every store the manifest names."""
    stores = manifest.get("stores") or {}
    sessions = sum(s.get("counts", {}).get("sessions", 0) for s in stores.values())
    events = sum(s.get("counts", {}).get("events", 0) for s in stores.values())
    size = sum(s.get("size", 0) for s in stores.values())
    return sessions, events, size


def _per_store(manifest: dict) -> dict[str, tuple[int, int]]:
    stores = manifest.get("stores") or {}
    return {
        name: (
            store.get("counts", {}).get("sessions", 0),
            store.get("counts", {}).get("events", 0),
        )
        for name, store in stores.items()
    }


def _is_subset(candidate: dict, current: dict) -> bool:
    """Whether the current snapshot holds at least as much, store by store.

    Compared per store rather than in total, because a total can hide a store
    that lost rows while another gained more -- which is exactly the case where
    deleting the older one would lose evidence.
    """
    candidate_stores = _per_store(candidate)
    current_stores = _per_store(current)
    for name, (sessions, events) in candidate_stores.items():
        held = current_stores.get(name)
        if held is None:
            return False
        if held[0] < sessions or held[1] < events:
            return False
    return True


def collect(store_root: Path, *, ranges: bool) -> list[dict]:
    rows: list[dict] = []
    projects = store_root / "projects"
    if not projects.is_dir():
        return rows
    for project in sorted(projects.iterdir()):
        snapshots = project / "snapshots"
        pointer = project / "current.json"
        if not snapshots.is_dir():
            continue
        current_path = None
        if pointer.is_file():
            try:
                current_path = json.loads(pointer.read_text(encoding="utf-8")).get("path")
            except (OSError, json.JSONDecodeError):
                current_path = None
        manifests: dict[Path, dict] = {}
        for snapshot in sorted(snapshots.iterdir()):
            manifest_path = snapshot / "manifest.json"
            if not manifest_path.is_file():
                continue
            try:
                manifests[snapshot] = json.loads(
                    manifest_path.read_text(encoding="utf-8")
                )
            except (OSError, json.JSONDecodeError):
                continue
        current_manifest = next(
            (m for p, m in manifests.items() if str(p) == current_path), None
        )
        for snapshot, manifest in manifests.items():
            sessions, events, size = _totals(manifest)
            live = str(snapshot) == current_path
            if live:
                recommendation = "CURRENT"
            elif current_manifest is None:
                recommendation = "REVIEW: no current snapshot to compare against"
            elif _is_subset(manifest, current_manifest):
                recommendation = "SUBSET: current holds at least as much"
            else:
                recommendation = "REVIEW: holds rows the current snapshot does not"
            first = last = ""
            if ranges:
                first, last = _session_range(snapshot)
            rows.append({
                "project_id": project.name,
                "snapshot_id": manifest.get("snapshot_id", snapshot.name),
                "created_at": (manifest.get("created_at") or "")[:19],
                "format": manifest.get("format_version"),
                "sessions": sessions,
                "events": events,
                "bytes": size,
                "first_session": first,
                "last_session": last,
                "parent_snapshot_id": manifest.get("parent_snapshot_id") or "",
                "live": live,
                "recommendation": recommendation,
            })
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", dest="store_root", type=Path, default=STORE_ROOT,
                        help="registry root to inventory (default: the configured one)")
    parser.add_argument("--ranges", action="store_true",
                        help="open each store to report Session date ranges")
    parser.add_argument("--csv", type=Path,
                        help="write every row to this file as CSV")
    args = parser.parse_args(argv)

    rows = collect(args.store_root.expanduser(), ranges=args.ranges)
    if not rows:
        print("no snapshots found", file=sys.stderr)
        return 1

    header = f"{'project':<14}{'created':<20}{'sess':>6}{'events':>9}{'MiB':>6}"
    if args.ranges:
        header += f"  {'first':<11}{'last':<11}"
    print(header + "  recommendation")
    reclaimable = 0
    for row in rows:
        line = (
            f"{row['project_id'][-12:]:<14}{row['created_at'][:19]:<20}"
            f"{row['sessions']:>6}{row['events']:>9}{row['bytes'] // 1048576:>6}"
        )
        if args.ranges:
            line += f"  {row['first_session']:<11}{row['last_session']:<11}"
        print(line + f"  {row['recommendation']}")
        if row["recommendation"].startswith("SUBSET"):
            reclaimable += row["bytes"]

    superseded = [r for r in rows if not r["live"]]
    review = [r for r in superseded if r["recommendation"].startswith("REVIEW")]
    print(
        f"\n{len(rows)} snapshots, {len(superseded)} superseded, "
        f"{len(review)} needing review, "
        f"{reclaimable // 1048576} MiB reclaimable from subsets"
    )
    if args.csv:
        with args.csv.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        print(f"wrote {args.csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
