#!/usr/bin/env python3
"""Render the comparative measures as one self-contained HTML report.

Separate from `model_metrics` because they answer to different reviewers: the
measures are checked against the store, and this is checked by eye. Keeping the
SQL out of the markup means a figure can be re-derived without reading HTML.

**Form follows the data's job**, which is why this is not one chart type
repeated four times:

- *Headline counts* are stat tiles, not a one-bar bar chart.
- *Tool volume* is a horizontal bar: magnitude over long categorical names.
- *Failure rate* is emphasis -- one hue for the tools above the corpus rate and
  gray for the rest -- because the job is "which of these is unusual", not
  "tell nine series apart".
- *Vendor recording shape* is a table, because five measures over three vendors
  with three different comparabilities is exactly the case a table wins.

Colors come from the validated three-slot categorical palette, which passes the
adjacent CVD, normal-vision, and lightness gates in both modes. The light-mode
contrast WARN on the aqua slot is discharged the way the rule requires: every
mark carries a visible direct label, and the table view repeats every figure.
"""

from __future__ import annotations

import html
from typing import Any

# The validated three-slot categorical palette. Three, not eight: a fourth slot
# puts yellow beside orange, which fails the all-pairs floor, and three is
# exactly the number of vendors this compares.
LIGHT = ("#2a78d6", "#eb6834", "#1baf7a")
DARK = ("#3987e5", "#d95926", "#199e70")

VENDOR_LABEL = {
    "anthropic.claude-code": "Claude Code",
    "openai.codex": "Codex",
    "cursor.composer": "Cursor",
}


def _escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def _vendor_slot(vendor: str, order: list[str]) -> int:
    """Colour follows the vendor, never its rank.

    A filter that drops one vendor must not repaint the others, so the slot is
    keyed on a fixed vendor order rather than on position in a sorted list.
    """
    return order.index(vendor) if vendor in order else len(order) - 1


def _stat_tiles(vendors: list[dict[str, Any]]) -> str:
    total_sessions = sum(row["sessions"] for row in vendors)
    total_events = sum(row["events"] for row in vendors)
    total_prompts = sum(row["human_prompts"] for row in vendors)
    total_turns = sum(row["model_turns"] for row in vendors)
    tiles = [
        ("Sessions", f"{total_sessions:,}", "across three vendors"),
        ("Events", f"{total_events:,}", "45-78% is tool traffic"),
        ("Human prompts", f"{total_prompts:,}", "the one cross-vendor measure"),
        ("Model turns", f"{total_turns:,}", "evidenced model executions"),
    ]
    cells = "".join(
        f'<div class="tile"><div class="tile-label">{_escape(label)}</div>'
        f'<div class="tile-value">{_escape(value)}</div>'
        f'<div class="tile-note">{_escape(note)}</div></div>'
        for label, value, note in tiles
    )
    return f'<div class="tiles">{cells}</div>'


def _tool_volume(tools: list[dict[str, Any]], order: list[str], top: int) -> str:
    rows = [row for row in tools if row["calls"] > 0][:top]
    if not rows:
        return ""
    widest = max(row["calls"] for row in rows)
    bars = []
    for row in rows:
        slot = _vendor_slot(row["vendor"], order)
        width = max(row["calls"] / widest * 100, 0.6)
        label = f"{VENDOR_LABEL.get(row['vendor'], row['vendor'])} · {row['tool']}"
        bars.append(
            f'<div class="row" tabindex="0" role="listitem" '
            f'aria-label="{_escape(label)}: {row["calls"]:,} calls">'
            f'<div class="row-name">{_escape(row["tool"])}'
            f'<span class="row-vendor">{_escape(VENDOR_LABEL.get(row["vendor"], row["vendor"]))}</span></div>'
            f'<div class="track"><div class="bar s{slot}" style="width:{width:.2f}%"></div>'
            f'<span class="row-value">{row["calls"]:,}</span></div>'
            f'<div class="tip">{_escape(label)}<br>{row["calls"]:,} calls · '
            f'{row["failed"]:,} failed</div></div>',
        )
    return (
        '<section><h2>Tool volume, per vendor</h2>'
        '<p class="lede">A tool call is harness-mediated: Cursor records a call '
        'for operations Claude performs another way, so these rank <em>within</em> '
        'a vendor and never across. Bars are coloured by vendor for that reason.</p>'
        f'<div class="chart" role="list">{"".join(bars)}</div></section>'
    )


def _failure_emphasis(tools: list[dict[str, Any]], top: int) -> str:
    """Emphasis, not categorical: the job is which tools are unusual."""
    rows = [row for row in tools if row["calls"] >= 200]
    if not rows:
        return ""
    total_calls = sum(row["calls"] for row in rows)
    total_failed = sum(row["failed"] for row in rows)
    corpus_rate = total_failed / total_calls if total_calls else 0
    rows = sorted(rows, key=lambda row: -row["failure_rate"])[:top]
    widest = max((row["failure_rate"] for row in rows), default=0) or 1
    bars = []
    for row in rows:
        above = row["failure_rate"] > corpus_rate
        width = max(row["failure_rate"] / widest * 100, 0.6)
        label = f"{VENDOR_LABEL.get(row['vendor'], row['vendor'])} · {row['tool']}"
        bars.append(
            f'<div class="row" tabindex="0" role="listitem" '
            f'aria-label="{_escape(label)}: {row["failure_rate"]*100:.1f} percent failed">'
            f'<div class="row-name">{_escape(row["tool"])}'
            f'<span class="row-vendor">{_escape(VENDOR_LABEL.get(row["vendor"], row["vendor"]))}</span></div>'
            f'<div class="track"><div class="bar {"emph" if above else "muted"}" '
            f'style="width:{width:.2f}%"></div>'
            f'<span class="row-value">{row["failure_rate"]*100:.1f}%</span></div>'
            f'<div class="tip">{_escape(label)}<br>{row["failed"]:,} of '
            f'{row["calls"]:,} calls failed</div></div>',
        )
    return (
        '<section><h2>Where tools fail</h2>'
        f'<p class="lede">Tools called at least 200 times, ranked by failure rate. '
        f'The corpus rate is <strong>{corpus_rate*100:.1f}%</strong>; bars above it '
        f'are highlighted and the rest are context. A failure here is the vendor\'s '
        f'own recorded status, not a judgement about the work.</p>'
        f'<div class="chart" role="list">{"".join(bars)}</div></section>'
    )


def _duration_table(tools: list[dict[str, Any]], top: int) -> str:
    rows = [
        row for row in tools
        if row["duration_ms"]["resolution"] == "measured"
    ][:top]
    excluded_all = [
        row for row in tools
        if row["duration_ms"]["resolution"] == "same_timestamp"
    ]
    if not rows and not excluded_all:
        return ""
    body = "".join(
        f'<tr><td>{_escape(row["tool"])}</td>'
        f'<td>{_escape(VENDOR_LABEL.get(row["vendor"], row["vendor"]))}</td>'
        f'<td class="num">{row["duration_ms"]["n"]:,}</td>'
        f'<td class="num">{row["duration_ms"]["p50"]:,}</td>'
        f'<td class="num">{row["duration_ms"]["p90"]:,}</td>'
        f'<td class="num">{row["duration_ms"]["p99"]:,}</td></tr>'
        for row in rows
    )
    excluded = excluded_all
    note = ""
    if excluded:
        names = ", ".join(sorted({row["tool"] for row in excluded})[:4])
        note = (
            f'<p class="lede">Omitted: {len(excluded)} measures whose call and '
            f'result records carry the same timestamp ({_escape(names)}, and others). '
            f'Those pairs state ordering rather than elapsed time, so a percentile '
            f'over them would report the vendor\'s stamping and not the tool.</p>'
        )
    # The table is dropped when nothing is measurable, but the explanation is
    # not: "no rows" and "these could not be measured" are different findings,
    # and only the second tells a reader why.
    table = (
        '<table><thead><tr><th>Tool</th><th>Vendor</th><th class="num">n</th>'
        '<th class="num">p50</th><th class="num">p90</th><th class="num">p99</th>'
        f'</tr></thead><tbody>{body}</tbody></table>'
    ) if rows else ""
    return (
        '<section><h2>How long tools take</h2>'
        '<p class="lede">Milliseconds, from the call Event to its result Event. '
        'The p50-to-p99 gap is the finding: the median is what a run feels like '
        'and the tail is what a reader remembers.</p>'
        f'{note}{table}</section>'
    )


def _vendor_table(vendors: list[dict[str, Any]]) -> str:
    body = "".join(
        f'<tr><td>{_escape(VENDOR_LABEL.get(row["vendor"], row["vendor"]))}</td>'
        f'<td class="num">{row["sessions"]:,}</td>'
        f'<td class="num">{row["events"]:,}</td>'
        f'<td class="num">{row["events_per_session"]:,.0f}</td>'
        f'<td class="num">{row["tool_event_share"]*100:.0f}%</td>'
        f'<td class="num">{row["human_prompts"]:,}</td>'
        f'<td class="num">{row["model_turns"]:,}</td></tr>'
        for row in vendors
    )
    return (
        '<section><h2>What each vendor records</h2>'
        '<p class="lede">Five measures with three different comparabilities, '
        'which is why this is a table and not a chart. <strong>Only the '
        'human-prompt column compares across rows</strong>: Actor classification '
        'is what CoSchema normalizes for all three. Events per Session measures '
        'how much a harness writes down, not how much work happened.</p>'
        '<table><thead><tr><th>Vendor</th><th class="num">Sessions</th>'
        '<th class="num">Events</th><th class="num">Events/Session</th>'
        '<th class="num">Tool share</th><th class="num">Human prompts</th>'
        f'<th class="num">Model turns</th></tr></thead><tbody>{body}</tbody></table>'
        '</section>'
    )


def _styles() -> str:
    light = "".join(f"  --s{slot}: {value};\n" for slot, value in enumerate(LIGHT))
    dark = "".join(f"  --s{slot}: {value};\n" for slot, value in enumerate(DARK))
    return f"""
.viz-root {{
  color-scheme: light;
  --surface-1: #fcfcfb;
  --surface-2: #f2f2f0;
  --text-primary: #0b0b0b;
  --text-secondary: #52514e;
  --text-muted: #6f6e6a;
  --grid: #e2e2de;
  /* Emphasis is a magnitude hue and deliberately not a categorical slot: the
     chart above colours bars by vendor, so reusing slot 1 here would imply
     every highlighted tool were Cursor's. */
  --emph: #b0341f;
  --muted-bar: #c8c8c3;
{light}}}
@media (prefers-color-scheme: dark) {{
  :root:where(:not([data-theme="light"])) .viz-root {{
    color-scheme: dark;
    --surface-1: #1a1a19;
    --surface-2: #232322;
    --text-primary: #ffffff;
    --text-secondary: #c3c2b7;
    --text-muted: #9a998f;
    --grid: #333331;
    --emph: #e07a5f;
    --muted-bar: #4a4a47;
{dark}  }}
}}
:root[data-theme="dark"] .viz-root {{
  color-scheme: dark;
  --surface-1: #1a1a19;
  --surface-2: #232322;
  --text-primary: #ffffff;
  --text-secondary: #c3c2b7;
  --text-muted: #9a998f;
  --grid: #333331;
  --emph: #e07a5f;
  --muted-bar: #4a4a47;
{dark}}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--surface-1); }}
.viz-root {{
  background: var(--surface-1); color: var(--text-primary);
  font: 15px/1.5 ui-sans-serif, -apple-system, "Segoe UI", system-ui, sans-serif;
  padding: 40px 32px 72px; max-width: 1080px; margin: 0 auto;
}}
h1 {{ font-size: 26px; margin: 0 0 6px; letter-spacing: -0.01em; }}
h2 {{ font-size: 17px; margin: 0 0 6px; letter-spacing: -0.005em; }}
.sub {{ color: var(--text-secondary); margin: 0 0 36px; font-size: 14px; }}
.lede {{ color: var(--text-secondary); font-size: 13.5px; margin: 0 0 18px; max-width: 74ch; }}
section {{ margin: 0 0 44px; }}
.tiles {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
  gap: 14px; margin: 0 0 44px; }}
.tile {{ background: var(--surface-2); border-radius: 10px; padding: 16px 18px; }}
.tile-label {{ color: var(--text-secondary); font-size: 12px; text-transform: uppercase;
  letter-spacing: 0.05em; }}
.tile-value {{ font-size: 30px; font-weight: 600; margin: 6px 0 2px;
  font-variant-numeric: tabular-nums; letter-spacing: -0.02em; }}
.tile-note {{ color: var(--text-muted); font-size: 12px; }}
.chart {{ display: flex; flex-direction: column; gap: 7px; }}
.row {{ display: grid; grid-template-columns: 230px 1fr; gap: 14px; align-items: center;
  position: relative; padding: 2px 0; border-radius: 4px; outline: none; }}
.row:hover, .row:focus-visible {{ background: var(--surface-2); }}
.row:focus-visible {{ box-shadow: 0 0 0 2px var(--emph); }}
.row-name {{ font-size: 13px; text-align: right; color: var(--text-primary);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
.row-vendor {{ display: block; font-size: 11px; color: var(--text-muted); }}
.track {{ display: flex; align-items: center; gap: 9px; min-height: 20px; }}
.bar {{ height: 15px; border-radius: 0 4px 4px 0; }}
.bar.s0 {{ background: var(--s0); }}
.bar.s1 {{ background: var(--s1); }}
.bar.s2 {{ background: var(--s2); }}
.bar.emph {{ background: var(--emph); }}
.bar.muted {{ background: var(--muted-bar); }}
.row-value {{ font-size: 12.5px; color: var(--text-secondary);
  font-variant-numeric: tabular-nums; white-space: nowrap; }}
.tip {{ position: absolute; left: 244px; bottom: 100%; z-index: 5;
  background: var(--text-primary); color: var(--surface-1); padding: 7px 10px;
  border-radius: 6px; font-size: 12px; line-height: 1.45; white-space: nowrap;
  opacity: 0; pointer-events: none; transition: opacity 90ms; }}
.row:hover .tip, .row:focus-visible .tip {{ opacity: 1; }}
table {{ border-collapse: collapse; width: 100%; font-size: 13.5px; }}
th, td {{ text-align: left; padding: 8px 12px; border-bottom: 1px solid var(--grid); }}
th {{ color: var(--text-secondary); font-weight: 600; font-size: 12px;
  text-transform: uppercase; letter-spacing: 0.04em; }}
td.num, th.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
.legend {{ display: flex; gap: 18px; flex-wrap: wrap; margin: 0 0 16px;
  font-size: 12.5px; color: var(--text-secondary); }}
.legend span {{ display: inline-flex; align-items: center; gap: 7px; }}
.swatch {{ width: 11px; height: 11px; border-radius: 3px; }}
footer {{ color: var(--text-muted); font-size: 12px; border-top: 1px solid var(--grid);
  padding-top: 18px; max-width: 78ch; }}
"""


def render(report: dict[str, Any], *, top: int = 12) -> str:
    """One self-contained page: no network, no build step, no external asset."""
    vendors = report.get("vendors", [])
    tools = report.get("tools", [])
    order = [row["vendor"] for row in vendors]
    legend = "".join(
        f'<span><i class="swatch" style="background:var(--s{index})"></i>'
        f'{_escape(VENDOR_LABEL.get(vendor, vendor))}</span>'
        for index, vendor in enumerate(order[:3])
    )
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Codess — model and tool measures</title>
<style>{_styles()}</style></head>
<body><main class="viz-root">
<h1>What the recorded work shows</h1>
<p class="sub">Measured from published Codess store sets. Every figure is a count
or a duration a vendor recorded — nothing here estimates price, quota, or the
quality of the work.</p>
{_stat_tiles(vendors)}
{_vendor_table(vendors)}
<div class="legend">{legend}</div>
{_tool_volume(tools, order, top)}
{_failure_emphasis(tools, top)}
{_duration_table(tools, top)}
<footer>Comparability is stated per measure rather than assumed. Tool counts and
event counts are harness-mediated and rank vendors rather than work; the
human-prompt count is the one measure CoSchema normalizes across all three.
Durations whose call and result records share a timestamp are omitted rather
than reported as fast.</footer>
</main></body></html>
"""
