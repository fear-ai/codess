#!/usr/bin/env python3
"""Daily activity timeline for one Project, with commits and vendor split.

Answers a question the other reports cannot: *when* did work happen, by which
vendor, and how did that line up with what was committed. A total says two
vendors contributed; a timeline says whether they worked together or took
turns, and those are different projects.

**The form is a calendar heat strip, one cell per day per vendor.** Not a line
chart: the data is a count per discrete day with gaps, and a line would draw
slopes across days when nothing happened, implying a decline that is really an
absence. Not a stacked bar: the question is *which vendor was active on this
day*, which is identity, so the two rows stay separate and comparable by
position.

Colour is sequential within a vendor -- one hue, more-is-darker -- because
within a row the job is magnitude. Across rows the hue distinguishes identity.
A day with no activity is the surface colour, so absence reads as absence
rather than as a small value.

    python tools/timeline_report.py --project CodeSess --html timeline.html
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import sqlite3
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from codess.config import STORE_ROOT  # noqa: E402

# One hue per vendor, stepped light-to-dark for magnitude within the row. Two
# hues rather than a categorical set because two vendors are being compared;
# the steps are the sequential ramp each identity carries.
VENDOR_RAMPS = {
    "openai.codex": ("#cfe3d4", "#8fc7a4", "#4ba373", "#1baf7a", "#0f7a52"),
    "anthropic.codex": ("#d6e4f7", "#a8c8ee", "#6b9fe0", "#2a78d6", "#1b5296"),
    "anthropic.claude-code": ("#d6e4f7", "#a8c8ee", "#6b9fe0", "#2a78d6", "#1b5296"),
    "cursor.composer": ("#fbdcc9", "#f5b48a", "#ef8a53", "#eb6834", "#b8471c"),
}
FALLBACK_RAMP = ("#e0e0dc", "#c2c2bd", "#9c9c96", "#75756f", "#4d4d48")

VENDOR_LABEL = {
    "anthropic.claude-code": "Claude Code",
    "openai.codex": "Codex",
    "cursor.composer": "Cursor",
}


def _escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def _day(timestamp: float) -> str:
    return dt.datetime.fromtimestamp(timestamp / 1000, dt.UTC).strftime("%Y-%m-%d")


def project_snapshot(store_root: Path, name: str) -> tuple[str, Path] | None:
    """Find one Project's current snapshot by logical name or path fragment."""
    try:
        catalog = json.loads(
            (store_root / "projects.json").read_text(encoding="utf-8"),
        )
    except (OSError, ValueError):
        return None
    for entry in catalog.get("projects", []):
        logical = str(entry.get("logical_name") or "")
        paths = [
            str(location.get("path") or "")
            for location in entry.get("locations", [])
        ]
        if name.casefold() not in logical.casefold() and not any(
            name.casefold() in path.casefold() for path in paths
        ):
            continue
        identity = str(entry["project_id"]).rsplit(":", 1)[-1]
        pointer = store_root / "projects" / identity / "current.json"
        try:
            snapshot = json.loads(pointer.read_text(encoding="utf-8")).get("path")
        except (OSError, ValueError):
            continue
        if snapshot and Path(snapshot).is_dir():
            return logical or identity, Path(snapshot)
    return None


def daily_activity(snapshot: Path) -> dict[str, dict[str, Any]]:
    """Events and Sessions per day per vendor."""
    days: dict[str, dict[str, Any]] = defaultdict(
        lambda: defaultdict(lambda: {"events": 0, "sessions": set()}),
    )
    for database in sorted(snapshot.glob("*.db")):
        conn = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
        try:
            vendor_row = conn.execute(
                "SELECT source_system_key FROM sessions LIMIT 1",
            ).fetchone()
            if not vendor_row or not vendor_row[0]:
                continue
            vendor = str(vendor_row[0])
            for event_at, session_id in conn.execute(
                "SELECT event_at, session_id FROM events WHERE event_at IS NOT NULL",
            ):
                bucket = days[_day(event_at)][vendor]
                bucket["events"] += 1
                bucket["sessions"].add(session_id)
        except sqlite3.Error:
            continue
        finally:
            conn.close()
    return {
        day: {
            vendor: {"events": values["events"], "sessions": len(values["sessions"])}
            for vendor, values in vendors.items()
        }
        for day, vendors in days.items()
    }


def daily_commits(repository: Path) -> dict[str, int]:
    """Commits per day, or empty when the path is not a repository.

    Read from git rather than from the store: a commit is the developer's own
    checkpoint and no vendor records it, so it is the one axis that says what
    the work produced rather than how it was conducted.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(repository), "log", "--format=%ad",
             "--date=format:%Y-%m-%d"],
            capture_output=True, text=True, timeout=30, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    if result.returncode != 0:
        return {}
    counts: dict[str, int] = defaultdict(int)
    for line in result.stdout.splitlines():
        if line.strip():
            counts[line.strip()] += 1
    return dict(counts)


def _step(count: int, peak: int, ramp: tuple[str, ...]) -> str:
    """Which ramp step one day's count lands on.

    Proportional to the peak rather than absolute, so a quiet Project is still
    legible; the tooltip carries the count, so the step never has to be read
    as a value.
    """
    if count <= 0:
        return ""
    share = count / peak if peak else 0
    for index, threshold in enumerate((0.05, 0.2, 0.45, 0.75)):
        if share <= threshold:
            return ramp[index]
    return ramp[-1]


def render(
    project: str,
    days: dict[str, dict[str, Any]],
    commits: dict[str, int],
    *,
    since: str | None = None,
) -> str:
    if not days:
        return "<!DOCTYPE html><html><body><p>No dated activity.</p></body></html>"
    ordered = sorted(days)
    start = max(since, ordered[0]) if since else ordered[0]
    span = [
        (dt.date.fromisoformat(start) + dt.timedelta(days=offset)).isoformat()
        for offset in range(
            (dt.date.fromisoformat(ordered[-1]) - dt.date.fromisoformat(start)).days + 1,
        )
    ]
    vendors = sorted({
        vendor for day in days.values() for vendor in day
    }, key=lambda vendor: -sum(
        day.get(vendor, {}).get("events", 0) for day in days.values()
    ))
    peaks = {
        vendor: max(
            (days.get(day, {}).get(vendor, {}).get("events", 0) for day in span),
            default=0,
        )
        for vendor in vendors
    }
    commit_peak = max((commits.get(day, 0) for day in span), default=0)

    rows = []
    for vendor in vendors:
        ramp = VENDOR_RAMPS.get(vendor, FALLBACK_RAMP)
        cells = "".join(
            _cell(day, days.get(day, {}).get(vendor, {}), peaks[vendor], ramp, vendor)
            for day in span
        )
        active = sum(
            1 for day in span if days.get(day, {}).get(vendor, {}).get("events", 0)
        )
        rows.append(
            f'<div class="strip-row"><div class="strip-label">'
            f'{_escape(VENDOR_LABEL.get(vendor, vendor))}'
            f'<span class="strip-note">{active} active days</span></div>'
            f'<div class="strip">{cells}</div></div>',
        )
    commit_cells = "".join(
        _commit_cell(day, commits.get(day, 0), commit_peak) for day in span
    )
    rows.append(
        f'<div class="strip-row"><div class="strip-label">Commits'
        f'<span class="strip-note">{sum(commits.get(d, 0) for d in span)} in span'
        f'</span></div><div class="strip">{commit_cells}</div></div>',
    )

    both = [
        day for day in span
        if sum(
            1 for vendor in vendors
            if days.get(day, {}).get(vendor, {}).get("events", 0)
        ) > 1
    ]
    active_days = [
        day for day in span
        if any(days.get(day, {}).get(vendor, {}).get("events", 0) for vendor in vendors)
    ]
    separation = (
        (len(active_days) - len(both)) / len(active_days) * 100 if active_days else 0
    )
    months = _month_axis(span)

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_escape(project)} — activity timeline</title>
<style>{_styles()}</style></head>
<body><main class="viz-root">
<h1>{_escape(project)} — who worked, when</h1>
<p class="sub">One cell per day. Colour is magnitude within a row and identity
across rows; an empty cell is a day with no recorded activity, not a small
value. Hover any cell for the counts.</p>
<div class="tiles">
  <div class="tile"><div class="tile-label">Span</div>
    <div class="tile-value">{len(span)}</div>
    <div class="tile-note">days, {_escape(span[0])} to {_escape(span[-1])}</div></div>
  <div class="tile"><div class="tile-label">Active</div>
    <div class="tile-value">{len(active_days)}</div>
    <div class="tile-note">days with recorded work</div></div>
  <div class="tile"><div class="tile-label">Shared days</div>
    <div class="tile-value">{len(both)}</div>
    <div class="tile-note">both vendors active</div></div>
  <div class="tile"><div class="tile-label">Separation</div>
    <div class="tile-value">{separation:.0f}%</div>
    <div class="tile-note">active days with one vendor</div></div>
</div>
<div class="axis"><div class="strip-label"></div><div class="strip">{months}</div></div>
{''.join(rows)}
<footer>Commits are read from git and no vendor records them; they are the one
row that says what the work produced rather than how it was conducted. Event
counts are harness-mediated and rank days within a vendor, never across.</footer>
</main></body></html>
"""


def _cell(
    day: str, values: dict[str, Any], peak: int, ramp: tuple[str, ...], vendor: str,
) -> str:
    count = values.get("events", 0)
    colour = _step(count, peak, ramp)
    style = f' style="background:{colour}"' if colour else ""
    tip = (
        f"{day}: {count:,} events, {values.get('sessions', 0)} sessions"
        if count else f"{day}: no activity"
    )
    return (
        f'<div class="cell{"" if colour else " empty"}"{style} tabindex="0" '
        f'role="img" aria-label="{_escape(VENDOR_LABEL.get(vendor, vendor))} '
        f'{_escape(tip)}"><span class="tip">{_escape(tip)}</span></div>'
    )


def _commit_cell(day: str, count: int, peak: int) -> str:
    colour = _step(count, peak, FALLBACK_RAMP)
    style = f' style="background:{colour}"' if colour else ""
    tip = f"{day}: {count} commit{'s' if count != 1 else ''}" if count else f"{day}: none"
    return (
        f'<div class="cell{"" if colour else " empty"}"{style} tabindex="0" '
        f'role="img" aria-label="{_escape(tip)}">'
        f'<span class="tip">{_escape(tip)}</span></div>'
    )


def _month_axis(span: list[str]) -> str:
    cells = []
    seen = set()
    for day in span:
        month = day[:7]
        if month not in seen:
            seen.add(month)
            cells.append(
                f'<div class="cell month">'
                f'<span class="month-label">{_escape(month[5:])}</span></div>',
            )
        else:
            cells.append('<div class="cell month"></div>')
    return "".join(cells)


def _styles() -> str:
    return """
.viz-root { color-scheme: light;
  --surface-1: #fcfcfb; --surface-2: #f2f2f0; --empty: #ebebe7;
  --text-primary: #0b0b0b; --text-secondary: #52514e; --text-muted: #6f6e6a;
  --grid: #e2e2de; }
@media (prefers-color-scheme: dark) {
  :root:where(:not([data-theme="light"])) .viz-root { color-scheme: dark;
    --surface-1: #1a1a19; --surface-2: #232322; --empty: #2b2b29;
    --text-primary: #fff; --text-secondary: #c3c2b7; --text-muted: #9a998f;
    --grid: #333331; } }
:root[data-theme="dark"] .viz-root { color-scheme: dark;
  --surface-1: #1a1a19; --surface-2: #232322; --empty: #2b2b29;
  --text-primary: #fff; --text-secondary: #c3c2b7; --text-muted: #9a998f;
  --grid: #333331; }
* { box-sizing: border-box; }
body { margin: 0; background: var(--surface-1); }
.viz-root { background: var(--surface-1); color: var(--text-primary);
  font: 15px/1.5 ui-sans-serif, -apple-system, "Segoe UI", system-ui, sans-serif;
  padding: 40px 32px 60px; max-width: 1180px; margin: 0 auto; }
h1 { font-size: 25px; margin: 0 0 6px; letter-spacing: -0.01em; }
.sub { color: var(--text-secondary); margin: 0 0 30px; font-size: 14px;
  max-width: 76ch; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 14px; margin: 0 0 34px; }
.tile { background: var(--surface-2); border-radius: 10px; padding: 15px 17px; }
.tile-label { color: var(--text-secondary); font-size: 12px;
  text-transform: uppercase; letter-spacing: 0.05em; }
.tile-value { font-size: 28px; font-weight: 600; margin: 5px 0 2px;
  font-variant-numeric: tabular-nums; letter-spacing: -0.02em; }
.tile-note { color: var(--text-muted); font-size: 12px; }
.strip-row, .axis { display: grid; grid-template-columns: 140px 1fr; gap: 14px;
  align-items: center; margin-bottom: 8px; }
.strip-label { font-size: 13px; text-align: right; color: var(--text-primary); }
.strip-note { display: block; font-size: 11px; color: var(--text-muted); }
.strip { display: flex; gap: 2px; flex-wrap: nowrap; }
.cell { flex: 1 1 0; min-width: 5px; height: 26px; border-radius: 3px;
  background: var(--empty); position: relative; outline: none; }
.cell.month { height: 14px; background: none; }
.month-label { position: absolute; left: 0; top: 0; font-size: 10px;
  color: var(--text-muted); white-space: nowrap; }
.cell:focus-visible { box-shadow: 0 0 0 2px var(--text-primary); }
.tip { position: absolute; left: 50%; transform: translateX(-50%);
  bottom: 130%; z-index: 9; background: var(--text-primary);
  color: var(--surface-1); padding: 6px 9px; border-radius: 6px; font-size: 12px;
  white-space: nowrap; opacity: 0; pointer-events: none; transition: opacity 90ms; }
.cell:hover .tip, .cell:focus-visible .tip { opacity: 1; }
footer { color: var(--text-muted); font-size: 12px; margin-top: 30px;
  border-top: 1px solid var(--grid); padding-top: 16px; max-width: 78ch; }
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, help="logical name or path fragment")
    parser.add_argument(
        "--store", dest="store_root", type=Path, default=STORE_ROOT,
    )
    parser.add_argument("--repo", type=Path, help="repository for the commit row")
    parser.add_argument("--since", help="first day to show, as YYYY-MM-DD")
    parser.add_argument("--html", type=Path, required=True)
    args = parser.parse_args(argv)

    found = project_snapshot(args.store_root.expanduser(), args.project)
    if not found:
        print(f"codess: no published Project matches {args.project!r}", file=sys.stderr)
        return 1
    project, snapshot = found
    days = daily_activity(snapshot)
    commits = daily_commits(args.repo.expanduser()) if args.repo else {}
    args.html.write_text(
        render(project, days, commits, since=args.since), encoding="utf-8",
    )
    print(f"wrote {args.html}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
