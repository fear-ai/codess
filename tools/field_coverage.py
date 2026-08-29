#!/usr/bin/env python3
"""Report which CoSchema columns hold no data, and for which vendors.

An empty column is a claim that needs checking, not a fact: it can mean the
vendor does not record the value, that the decoder does not read it, or that
the column was added for a use nobody built. Those want different responses,
and only the first is acceptable without comment.

The distinction the report makes is *which* vendors are empty, because the
scenarios are not the same finding:

- **Empty for one vendor, populated for others.** The strongest signal. The
  column is decodable, so the gap is in one adapter until the source is shown
  not to record it. This is how the Cursor `harness_version` gap surfaced --
  null for all 81 Cursor Sessions while Claude and Codex filled 425 of 426.
- **Empty for every vendor but one.** The column may be vendor-specific and
  correct, or a common field only one adapter ever learned to fill. Which one
  it is cannot be read off the counts.
- **Empty for every vendor.** No adapter writes it. Either the schema is ahead
  of the decoders or the column has no consumer; neither is a decode gap, and
  both are worth a decision.

It reports column names, counts, and null rates -- never a stored value, so
the output can be attached to a work item without reproducing Session content.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from codess.schema_contract import table_names

STORE_FILES = {
    "claude": "sessions_cc.db",
    "codex": "sessions_codex.db",
    "cursor": "sessions_cursor.db",
}

# Single-vendor gaps already reviewed, each with the reason it is accepted.
# `--fail-on-gap` fails on anything absent from this file, so a new gap is a
# finding while a known one does not keep the check permanently red. Removing
# an entry as its work item lands is how the check tightens over time.
BASELINE_PATH = ROOT / "schema" / "field-coverage-baseline.json"

# Present in every current-format store; its absence marks a pre-CoSchema
# store, which is a superseded observation rather than a coverage finding.
CURRENT_FORMAT_MARKER = ("events", "event_kind")


def _is_current_format(conn: sqlite3.Connection) -> bool:
    table, column = CURRENT_FORMAT_MARKER
    if table not in table_names(conn):
        return False
    return any(row[1] == column for row in conn.execute(f"PRAGMA table_info({table})"))


def _column_coverage(conn: sqlite3.Connection, table: str) -> dict[str, tuple[int, int]]:
    """Rows and non-null count for each column of one table."""
    columns = [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]
    if not columns:
        return {}
    # One pass: SQLite counts every column in the same scan.
    projections = ", ".join(f"SUM({name} IS NOT NULL)" for name in columns)
    row = conn.execute(f"SELECT COUNT(*), {projections} FROM {table}").fetchone()  # noqa: S608
    total = int(row[0])
    return {name: (total, int(row[index + 1] or 0)) for index, name in enumerate(columns)}


def scan_store(path: Path) -> dict[str, dict[str, tuple[int, int]]]:
    """Coverage for every table in one store, or empty for a legacy store."""
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        if not _is_current_format(conn):
            return {}
        return {table: _column_coverage(conn, table) for table in sorted(table_names(conn))}
    finally:
        conn.close()


def merge(reports: list[dict[str, dict[str, tuple[int, int]]]]) -> dict[str, tuple[int, int]]:
    """Sum coverage across a vendor's stores, keyed `table.column`."""
    merged: dict[str, tuple[int, int]] = {}
    for report in reports:
        for table, columns in report.items():
            for column, (total, present) in columns.items():
                key = f"{table}.{column}"
                before = merged.get(key, (0, 0))
                merged[key] = (before[0] + total, before[1] + present)
    return merged


def classify(by_vendor: dict[str, dict[str, tuple[int, int]]]) -> dict[str, list[dict]]:
    """Group every observed column by which vendors hold no value for it."""
    columns: set[str] = set()
    for coverage in by_vendor.values():
        columns |= set(coverage)

    findings: dict[str, list[dict]] = {
        "empty_for_one_vendor": [],
        "populated_for_one_vendor": [],
        "empty_for_every_vendor": [],
    }
    for column in sorted(columns):
        # A vendor with no rows at all says nothing about the column.
        observed = {
            vendor: coverage[column]
            for vendor, coverage in by_vendor.items()
            if column in coverage and coverage[column][0] > 0
        }
        if not observed:
            continue
        empty = sorted(v for v, (_, present) in observed.items() if present == 0)
        filled = sorted(v for v, (_, present) in observed.items() if present > 0)
        entry = {
            "column": column,
            "empty_for": empty,
            "populated_for": {
                vendor: {"rows": observed[vendor][0], "present": observed[vendor][1]}
                for vendor in filled
            },
        }
        if not filled:
            findings["empty_for_every_vendor"].append(entry)
        elif len(filled) == 1 and empty:
            findings["populated_for_one_vendor"].append(entry)
        elif empty:
            findings["empty_for_one_vendor"].append(entry)
    return findings


def _load_baseline(path: Path) -> dict[str, str]:
    """Accepted single-vendor gaps, mapped to why each is accepted.

    A missing file means nothing is accepted, so every gap fails. That is the
    right default for a fresh checkout and for a run that deliberately points
    elsewhere.
    """
    if not path.exists():
        return {}
    document = json.loads(path.read_text(encoding="utf-8"))
    return {entry["column"]: entry["reason"] for entry in document.get("accepted", ())}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dir", action="append", dest="dirs", required=True,
        help="Project root holding a .codess store set; repeatable",
    )
    parser.add_argument("--out", type=Path)
    parser.add_argument(
        "--fail-on-gap", action="store_true",
        help="exit nonzero for a single-vendor gap that is not in the "
             "accepted baseline -- the class that indicates a decode gap",
    )
    parser.add_argument(
        "--baseline", type=Path, default=BASELINE_PATH,
        help=f"accepted single-vendor gaps (default {BASELINE_PATH.name}); "
             "pass a nonexistent path to fail on every gap",
    )
    args = parser.parse_args(argv)

    by_vendor: dict[str, list] = {vendor: [] for vendor in STORE_FILES}
    legacy: list[str] = []
    for value in args.dirs:
        base = Path(value).expanduser().resolve() / ".codess"
        for vendor, name in STORE_FILES.items():
            path = base / name
            if not path.exists():
                continue
            report = scan_store(path)
            if report:
                by_vendor[vendor].append(report)
            else:
                legacy.append(str(path))

    merged = {
        vendor: merge(reports) for vendor, reports in by_vendor.items() if reports
    }
    findings = classify(merged)
    accepted = _load_baseline(args.baseline)
    unreviewed = [
        entry for entry in findings["empty_for_one_vendor"]
        if entry["column"] not in accepted
    ]
    report = {
        "format": "codess.field-coverage/1",
        "boundary": "column names, counts, and null rates only; no stored values",
        "vendors": sorted(merged),
        "legacy_stores_skipped": sorted(legacy),
        "findings": findings,
        "counts": {name: len(rows) for name, rows in findings.items()},
        "baseline": {
            "path": str(args.baseline),
            "accepted": len(accepted),
            "unreviewed_gaps": [entry["column"] for entry in unreviewed],
        },
    }
    text = json.dumps(report, indent=2, sort_keys=True)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    if args.fail_on_gap and unreviewed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
