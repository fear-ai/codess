#!/usr/bin/env python3
"""Report columns that are always absent or always one value, by vendor.

`field_coverage.py` asks which columns are *empty*. This asks the wider
question: which hold no information -- because they are never written, or
because they are written with the same value every time.

The two are different findings and want different responses. An always-absent
column is either a decode gap or a capability not yet built. An always-constant
column is a declared vocabulary the implementation never exercises, which is
worse in one specific way: a reader cannot tell "this never happened" from
"this is never recorded". That distinction is what found `event_at_basis`
asserting vendor provenance for Events that had no vendor timestamp.

Six classes are reported, because what a value is constant *across* changes
what it means:

- **absent for every vendor** -- nothing writes it at all
- **absent for all but one** -- one vendor supplies evidence the others do not
- **absent for exactly one** -- the decode-gap class `field_coverage` gates on
- **one value across every vendor** -- a column carrying no information
- **one value differing per vendor** -- a vendor tag, correct but derivable
- **constant for some vendors only** -- usually a small sample, not a finding

Counting has to aggregate distinct values *across* stores, not per store: a
table holding one row per store is trivially constant within it, which would
report `projects.root_path` as a constant when it is simply per-Project.

Reports column names, counts, and values. A value here is a classification or
identifier -- `utf-8`, `verified`, `anthropic.claude-code` -- not message or
prompt content; `--values` is required to print any of them, and long values
are truncated.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

STORE_FILES = {
    "claude": "sessions_cc.db",
    "codex": "sessions_codex.db",
    "cursor": "sessions_cursor.db",
}

# Above this many distinct values a column is varying, and the exact count
# stops mattering. Kept small: the question is "one value or many", and
# reading every distinct value of a content column would be both slow and
# outside this tool's boundary.
DISTINCT_CAP = 6

VALUE_CHARS = 70


def _is_current_format(conn: sqlite3.Connection) -> bool:
    try:
        return any(row[1] == "event_kind" for row in conn.execute("PRAGMA table_info(events)"))
    except sqlite3.Error:
        return False


def scan_store(conn: sqlite3.Connection) -> dict[str, tuple[int, int, set[str], bool]]:
    """Rows, non-null count, distinct values, and whether the cap was passed."""
    observed: dict[str, tuple[int, int, set[str], bool]] = {}
    tables = [
        row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%'"
        )
    ]
    for table in tables:
        rows = int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])  # noqa: S608
        if not rows:
            continue
        for column in [row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')]:
            present = int(
                conn.execute(f'SELECT COUNT("{column}") FROM "{table}"').fetchone()[0]  # noqa: S608
            )
            values: set[str] = set()
            if present:
                values = {
                    str(row[0])[:VALUE_CHARS]
                    for row in conn.execute(
                        f'SELECT DISTINCT "{column}" FROM "{table}" '  # noqa: S608
                        f'WHERE "{column}" IS NOT NULL LIMIT {DISTINCT_CAP + 1}'
                    )
                }
            observed[f"{table}.{column}"] = (
                rows, present, values, len(values) > DISTINCT_CAP,
            )
    return observed


def merge(reports: list[dict]) -> dict[str, tuple[int, int, set[str], bool]]:
    """Combine one vendor's stores, unioning distinct values across them."""
    merged: dict[str, tuple[int, int, set[str], bool]] = {}
    for report in reports:
        for column, (rows, present, values, capped) in report.items():
            before = merged.get(column, (0, 0, set(), False))
            union = before[2] | values
            merged[column] = (
                before[0] + rows,
                before[1] + present,
                set(sorted(union)[:DISTINCT_CAP]),
                before[3] or capped or len(union) > DISTINCT_CAP,
            )
    return merged


def classify(by_vendor: dict[str, dict]) -> dict[str, list[dict]]:
    """Group every observed column by absence and constancy across vendors."""
    findings: dict[str, list[dict]] = defaultdict(list)
    columns = set().union(*[set(report) for report in by_vendor.values()]) if by_vendor else set()
    for column in sorted(columns):
        seen = {
            vendor: report[column]
            for vendor, report in by_vendor.items()
            if column in report and report[column][0] > 0
        }
        if not seen:
            continue
        empty = sorted(v for v, d in seen.items() if d[1] == 0)
        filled = sorted(v for v, d in seen.items() if d[1] > 0)
        constant = sorted(
            v for v in filled if len(seen[v][2]) == 1 and not seen[v][3]
        )
        entry = {
            "column": column,
            "empty_for": empty,
            "populated_for": {v: seen[v][1] for v in filled},
            "constant_for": {
                v: next(iter(seen[v][2])) for v in constant
            },
        }
        if not filled:
            findings["absent_every_vendor"].append(entry)
        elif len(filled) == 1 and empty:
            findings["absent_all_but_one"].append(entry)
        elif len(empty) == 1:
            findings["absent_exactly_one"].append(entry)
        if constant and len(constant) == len(filled) and len(filled) > 1:
            distinct = set(entry["constant_for"].values())
            key = (
                "one_value_every_vendor" if len(distinct) == 1
                else "one_value_per_vendor"
            )
            findings[key].append(entry)
        elif constant and len(constant) < len(filled):
            findings["constant_for_some"].append(entry)
    return dict(findings)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dir", action="append", dest="dirs", required=True,
        help="Project root holding a .codess store set; repeatable",
    )
    parser.add_argument("--out", type=Path)
    parser.add_argument(
        "--values", action="store_true",
        help="include the constant values themselves; they are "
             "classifications and identifiers, never message content",
    )
    args = parser.parse_args(argv)

    by_vendor: dict[str, list[dict]] = defaultdict(list)
    legacy: list[str] = []
    for value in args.dirs:
        base = Path(value).expanduser().resolve() / ".codess"
        for vendor, name in STORE_FILES.items():
            path = base / name
            if not path.exists():
                continue
            conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            try:
                if _is_current_format(conn):
                    by_vendor[vendor].append(scan_store(conn))
                else:
                    legacy.append(str(path))
            finally:
                conn.close()

    merged = {vendor: merge(reports) for vendor, reports in by_vendor.items()}
    findings = classify(merged)
    if not args.values:
        for entries in findings.values():
            for entry in entries:
                entry["constant_for"] = sorted(entry["constant_for"])
    report = {
        "format": "codess.value-survey/1",
        "boundary": (
            "column names, counts, and classification values only; "
            "no message, prompt, argument, or result content"
        ),
        "vendors": sorted(merged),
        "legacy_stores_skipped": sorted(legacy),
        "counts": {name: len(entries) for name, entries in sorted(findings.items())},
        "findings": findings,
    }
    text = json.dumps(report, indent=2, sort_keys=True)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
