#!/usr/bin/env python3
"""Report, per Project, whether its store still has vendor Sources behind it.

`sources_vanished` is the column that decides retention, and nothing computed
it: Operations documented the row and no producer wrote it. A store whose
Sources are all present duplicates evidence the current Sources still produce
and can be rebuilt; a store with vanished Sources is the last remaining record
of them, and a rebuild, a retention prune, or a superseded-store cleanup that
reaches it destroys evidence nothing can regenerate.

Coverage has three values, not two. A vendor prune removes transcripts
individually, so a Project commonly loses part of its Sources rather than all
of them -- and under a two-value reading a partly purged store reports as
`complete` and loses the protection it most needs.

    complete  every recorded Source resolves
    partial   some resolve and some do not
    purged    none resolves

Run it before any rebuild or deletion. It opens every store read-only and
writes nothing.

    python tools/project_inventory.py               # every published Project
    python tools/project_inventory.py --csv out.csv # machine-readable
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from codess.config import STORE_ROOT  # noqa: E402

COVERAGE_COMPLETE = "complete"
COVERAGE_PARTIAL = "partial"
COVERAGE_PURGED = "purged"


def _coverage(total: int, vanished: int) -> str:
    """Which of the three coverage values a Source count describes."""
    if total == 0:
        return "no sources recorded"
    if vanished == 0:
        return COVERAGE_COMPLETE
    return COVERAGE_PURGED if vanished == total else COVERAGE_PARTIAL


def _logical_names(store_root: Path) -> dict[str, str]:
    """Project id to its catalogued name, for a row a reader can identify."""
    catalog = store_root / "projects.json"
    if not catalog.exists():
        return {}
    try:
        entries = json.loads(catalog.read_text(encoding="utf-8")).get("projects") or []
    except (OSError, json.JSONDecodeError):
        return {}
    names: dict[str, str] = {}
    for entry in entries:
        identity = str(entry.get("project_id", "")).split(":")[-1]
        locations = entry.get("locations") or []
        names[identity] = str(
            entry.get("logical_name")
            or (locations[0].get("path", "") if locations else "")
        )
    return names


def _store_sources(db: Path) -> tuple[int, int, int, int]:
    """One store's Source, vanished, Session, and Event counts."""
    connection = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        paths = [row[0] for row in connection.execute(
            "SELECT DISTINCT source_path FROM sources"
        )]
        sessions = connection.execute("SELECT count(*) FROM sessions").fetchone()[0]
        events = connection.execute("SELECT count(*) FROM events").fetchone()[0]
    finally:
        connection.close()
    vanished = sum(1 for path in paths if not Path(path).exists())
    return len(paths), vanished, sessions, events


def inventory(store_root: Path) -> list[dict[str, object]]:
    """One row per published Project, read from its current snapshot."""
    names = _logical_names(store_root)
    rows: list[dict[str, object]] = []
    for pointer in sorted((store_root / "projects").glob("*/current.json")):
        identity = pointer.parent.name
        try:
            meta = json.loads(pointer.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            rows.append({
                "project_id": identity, "logical_name": names.get(identity, ""),
                "coverage": f"unreadable pointer: {error}",
            })
            continue
        snapshot = Path(meta["path"])
        row: dict[str, object] = {
            "project_id": identity,
            "logical_name": names.get(identity, ""),
            "coschema_format": meta.get("format_version"),
            "snapshot_id": meta.get("snapshot_id"),
        }
        if not snapshot.is_dir():
            row["coverage"] = "snapshot missing"
            rows.append(row)
            continue
        total = vanished = sessions = events = 0
        failure = None
        for db in sorted(snapshot.glob("*.db")):
            try:
                store_total, store_gone, store_sessions, store_events = _store_sources(db)
            except sqlite3.Error as error:
                failure = f"{db.name}: {error}"
                break
            total += store_total
            vanished += store_gone
            sessions += store_sessions
            events += store_events
        row.update({
            "sessions": sessions, "events": events,
            "sources_total": total,
            "sources_on_disk": total - vanished,
            "sources_vanished": vanished,
            "coverage": failure or _coverage(total, vanished),
        })
        rows.append(row)
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--store", dest="store_root", type=Path, default=STORE_ROOT,
        help="the machine's durable store (default: %(default)s)",
    )
    parser.add_argument(
        "--csv", dest="csv_path", type=Path,
        help="also write the rows as CSV to this path",
    )
    args = parser.parse_args(argv)

    rows = inventory(args.store_root)
    if not rows:
        print(f"no published Projects under {args.store_root}")
        return 0

    header = f"{'project':24} {'fmt':>3} {'sess':>6} {'events':>9} {'srcs':>5} {'gone':>5}  coverage"
    print(header)
    for row in rows:
        label = str(row.get("logical_name") or row["project_id"])[:24]
        print(
            f"{label:24} {row.get('coschema_format', ''):>3} "
            f"{row.get('sessions', ''):>6} {row.get('events', ''):>9} "
            f"{row.get('sources_total', ''):>5} {row.get('sources_vanished', ''):>5}  "
            f"{row['coverage']}"
        )

    at_risk = [r for r in rows if r.get("coverage") in {COVERAGE_PARTIAL, COVERAGE_PURGED}]
    print(f"\n{len(rows)} published Projects; {len(at_risk)} hold vanished Sources")
    for row in at_risk:
        print(
            f"  {row.get('logical_name') or row['project_id']}: "
            f"{row['sources_vanished']} of {row['sources_total']} Sources gone, "
            f"{row['events']} Events -- archive before any rebuild or prune"
        )

    if args.csv_path:
        fields = [
            "project_id", "logical_name", "coschema_format", "snapshot_id",
            "sessions", "events", "sources_total", "sources_on_disk",
            "sources_vanished", "coverage",
        ]
        with args.csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        print(f"\nwrote {args.csv_path}")

    return 1 if at_risk else 0


if __name__ == "__main__":
    raise SystemExit(main())
