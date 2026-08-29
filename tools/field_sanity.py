#!/usr/bin/env python3
"""Check decoded field values against what each vendor should produce.

`field_coverage.py` asks which columns hold data. This asks whether the data
they hold is plausible, which is a different failure: a column can be fully
populated and wrong -- a timestamp in 1970, a status outside its vocabulary, a
column identical to its neighbour because a decoder copied instead of mapping.

Reports per vendor, because a value plausible for one is not for another: every
Cursor Session is `ide` by vendor profile, and the same value on a Claude
Session would mean something was inferred.

Findings are graded so a long run stays readable:

  ERROR   a value contradicts the schema or the vendor's own record
  WARN    a value is legal and unexpected
  NOTE    a shape worth seeing, not a defect

    python tools/field_sanity.py
    python tools/field_sanity.py --errors    # exit nonzero on ERROR only
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from codess.config import STORE_ROOT  # noqa: E402

PLAUSIBLE_FIRST = datetime(2020, 1, 1, tzinfo=UTC).timestamp() * 1000
"""Earliest instant a recorded Session could plausibly carry.

Before the first coding assistant shipped, so anything earlier is a scale or
epoch error rather than old work.
"""

VOCABULARIES = {
    "surface_kind": {"cli", "ide", "api", "desktop", "web", "unknown"},
    "time_basis": {"event", "session", "source_mtime", "ingested", "unknown"},
    "archive_state": {"active", "archived", "unknown"},
    "session_label_basis": {"vendor_generated", "operator_named"},
    "session_relation_kind": {"subagent", "fork", "resume", "continuation", "unknown"},
}


def _stores(store_root: Path) -> list[tuple[str, Path]]:
    found: list[tuple[str, Path]] = []
    for pointer in sorted((store_root / "projects").glob("*/current.json")):
        try:
            snapshot = Path(json.loads(pointer.read_text(encoding="utf-8"))["path"])
        except (OSError, ValueError, KeyError):
            continue
        found.extend(
            (database.stem.replace("sessions_", ""), database)
            for database in sorted(snapshot.glob("sessions_*.db"))
        )
    return found


def _check_sessions(vendor: str, conn: sqlite3.Connection) -> list[tuple[str, str, str]]:
    """Session-level value checks: vocabularies, ranges, and agreement."""
    out: list[tuple[str, str, str]] = []
    rows = conn.execute(
        "SELECT vendor_session_id, surface_kind, time_basis, archive_state, "
        "session_label, session_label_basis, started_at, ended_at, "
        "source_cwd, source_cwd_count FROM sessions"
    ).fetchall()
    for row in rows:
        identity = str(row[0])[:12]
        for name, value in (
            ("surface_kind", row[1]), ("time_basis", row[2]),
            ("archive_state", row[3]), ("session_label_basis", row[5]),
        ):
            if value is not None and value not in VOCABULARIES[name]:
                out.append(("ERROR", f"{vendor}/{identity}",
                            f"{name}={value!r} is outside its vocabulary"))
        started, ended = row[6], row[7]
        if started is not None and started < PLAUSIBLE_FIRST:
            out.append(("ERROR", f"{vendor}/{identity}",
                        f"started_at {started} predates any coding assistant: "
                        "a scale or epoch error"))
        if started is not None and ended is not None and ended < started:
            out.append(("ERROR", f"{vendor}/{identity}",
                        f"ended_at {ended} precedes started_at {started}"))
        # A label with no basis, or a basis with no label, is half a fact.
        if bool(row[4]) != bool(row[5]):
            out.append(("WARN", f"{vendor}/{identity}",
                        "session_label and session_label_basis disagree on presence"))
        if row[9] is not None and row[9] < 1 and row[8]:
            out.append(("WARN", f"{vendor}/{identity}",
                        f"source_cwd is set and source_cwd_count is {row[9]}"))
    return out


def _check_identical_columns(
    vendor: str, conn: sqlite3.Connection,
) -> list[tuple[str, str, str]]:
    """Column pairs that hold the same value in every row.

    Two columns that never differ are either one fact stored twice or a decoder
    that copied where it should have mapped. Reported rather than judged: the
    schema deliberately keeps some pairs (an exact vendor value beside its
    normalized form) and they are indistinguishable from a defect by shape.
    """
    out: list[tuple[str, str, str]] = []
    for table, pairs in (
        ("events", (("event_at", "timestamp"),)),
        ("sources", (("observed_at", "ingested_at"),)),
    ):
        for left, right in pairs:
            try:
                total, same = conn.execute(  # noqa: S608 - names are literals above
                    f"SELECT COUNT(*), SUM(CASE WHEN {left} IS {right} THEN 1 ELSE 0 END) "
                    f"FROM {table}"
                ).fetchone()
            except sqlite3.Error:
                continue
            if total and same == total:
                out.append(("NOTE", f"{vendor}/{table}",
                            f"{left} and {right} are identical in all {total} rows"))
    return out


def _check_events(vendor: str, conn: sqlite3.Connection) -> list[tuple[str, str, str]]:
    """Event-level checks: time coverage, ordering, and orphan links."""
    out: list[tuple[str, str, str]] = []
    total, timed = conn.execute(
        "SELECT COUNT(*), COUNT(event_at) FROM events"
    ).fetchone()
    if total and timed < total:
        out.append(("WARN", f"{vendor}/events",
                    f"{total - timed} of {total} events carry no time"))
    if total:
        early = conn.execute(
            "SELECT COUNT(*) FROM events WHERE event_at IS NOT NULL AND event_at < ?",
            (PLAUSIBLE_FIRST,),
        ).fetchone()[0]
        if early:
            out.append(("ERROR", f"{vendor}/events",
                        f"{early} events predate 2020: a scale or epoch error"))
        disordered = conn.execute(
            """SELECT COUNT(*) FROM (
                 SELECT event_at, LAG(event_at) OVER (
                   PARTITION BY session_id ORDER BY sequence_no) previous
                 FROM events WHERE event_at IS NOT NULL)
               WHERE previous IS NOT NULL AND event_at < previous"""
        ).fetchone()[0]
        if disordered:
            out.append(("WARN", f"{vendor}/events",
                        f"{disordered} events are earlier than the event before them "
                        "in sequence"))
    orphan = conn.execute(
        "SELECT COUNT(*) FROM tool_results r WHERE r.invocation_id IS NOT NULL "
        "AND NOT EXISTS (SELECT 1 FROM tool_invocations i WHERE i.id=r.invocation_id)"
    ).fetchone()[0]
    if orphan:
        out.append(("ERROR", f"{vendor}/tool_results",
                    f"{orphan} results name an invocation that is not in the store"))
    return out


def _check_uniqueness(vendor: str, conn: sqlite3.Connection) -> list[tuple[str, str, str]]:
    """Identity columns that must not repeat."""
    out: list[tuple[str, str, str]] = []
    for table, column in (
        ("sessions", "session_entity_id"),
        ("events", "event_entity_id"),
        ("sources", "source_entity_id"),
    ):
        try:
            total, distinct = conn.execute(
                f"SELECT COUNT({column}), COUNT(DISTINCT {column}) FROM {table}"
            ).fetchone()
        except sqlite3.Error:
            continue
        if total and distinct != total:
            out.append(("ERROR", f"{vendor}/{table}",
                        f"{column} repeats: {total} values, {distinct} distinct"))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", dest="store_root", type=Path, default=STORE_ROOT)
    parser.add_argument("--errors", action="store_true",
                        help="exit nonzero only when an ERROR is found")
    args = parser.parse_args(argv)

    findings: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    per_vendor: dict[str, Counter] = defaultdict(Counter)
    for vendor, database in _stores(args.store_root.expanduser()):
        try:
            conn = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
        except sqlite3.Error:
            continue
        try:
            sessions = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
            if not sessions:
                continue
            per_vendor[vendor]["stores"] += 1
            per_vendor[vendor]["sessions"] += sessions
            for check in (
                _check_sessions, _check_events, _check_uniqueness,
                _check_identical_columns,
            ):
                findings.extend(check(vendor, conn))
        except sqlite3.Error as exc:
            findings.append(("ERROR", vendor, f"cannot read {database.name}: {exc}"))
        finally:
            conn.close()

    order = {"ERROR": 0, "WARN": 1, "NOTE": 2}
    counts: Counter = Counter()
    for severity, subject, detail in sorted(findings, key=lambda f: (order[f[0]], f[1])):
        counts[severity] += 1
        # One line per distinct finding shape, since a per-Session check repeats
        # its message for every row that trips it.
        key = f"{severity}|{subject.split('/')[0]}|{detail[:60]}"
        if key in seen:
            continue
        seen.add(key)
        print(f"{severity:<6} {subject}\n       {detail}")

    print(f"\nvendors checked: {', '.join(sorted(per_vendor))}")
    for vendor in sorted(per_vendor):
        print(f"  {vendor:<8}{per_vendor[vendor]['stores']:>3} stores, "
              f"{per_vendor[vendor]['sessions']:>5} sessions")
    print(
        f"{counts['ERROR']} error(s), {counts['WARN']} warning(s), "
        f"{counts['NOTE']} note(s)"
    )
    if counts["ERROR"]:
        return 1
    return 0 if args.errors else (1 if counts["WARN"] else 0)


if __name__ == "__main__":
    raise SystemExit(main())
