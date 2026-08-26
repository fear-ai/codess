#!/usr/bin/env python3
"""Analyze and visualize an extracted dialog dataset.

Step two of two. It reads the JSONL `dialog_extract` writes and never opens a
store, which is the point of the split: a figure here can be recomputed from a
file a reader already has, and the extraction can be replaced by any other
producer of the same shape.

**What it reports**, each chosen because the extract makes it answerable and a
store alone does not:

- *Bout shape* -- exchanges per sitting, which is the unit work actually happens
  in. A Session spans days; a bout is an hour.
- *Prompt and reply size* -- the distribution, not the mean. The mean of a
  heavy-tailed distribution is a number no individual exchange resembles.
- *Reply fan-out* -- model replies per human prompt, which is how much the
  harness did per instruction.
- *Recency* -- the same measures over a window, so "typical" and "lately" are
  separable rather than averaged together.

Rendered as one self-contained HTML page. Charts are horizontal bars over
labelled categories with a table view beside them; colour distinguishes series
and carries no meaning of its own.
"""

from __future__ import annotations

import argparse
import html
import json
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any

# Two hues, distinguishable in both modes and in the common CVD cases. Kept to
# two because the charts encode one series each and the second exists only to
# separate prompt from reply where both appear.
LIGHT = ("#2a78d6", "#eb6834")
DARK = ("#3987e5", "#d95926")

BUCKETS = (
    ("1", 1, 1), ("2-3", 2, 3), ("4-7", 4, 7),
    ("8-15", 8, 15), ("16-31", 16, 31), ("32+", 32, 10**9),
)

SIZE_BUCKETS = (
    ("<50", 0, 49), ("50-199", 50, 199), ("200-799", 200, 799),
    ("800-3k", 800, 2999), ("3k-10k", 3000, 9999), ("10k+", 10000, 10**9),
)


def load(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Read the extract, returning `(exchanges, header)`.

    The header is the extract's own record of what it filtered, so a figure can
    state the population it was computed over rather than implying "everything".
    """
    rows: list[dict[str, Any]] = []
    header: dict[str, Any] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("record") == "header":
            header = record
        elif record.get("record") == "exchange":
            rows.append(record)
    return rows, header


def _bucket(value: int, buckets: tuple[tuple[str, int, int], ...]) -> str:
    for label, low, high in buckets:
        if low <= value <= high:
            return label
    return buckets[-1][0]


def _distribution(values: list[int]) -> dict[str, Any]:
    if not values:
        return {"n": 0}
    ordered = sorted(values)
    return {
        "n": len(ordered),
        "p25": ordered[len(ordered) // 4],
        "p50": statistics.median(ordered),
        "p75": ordered[len(ordered) * 3 // 4],
        "p95": ordered[min(int(len(ordered) * 0.95), len(ordered) - 1)],
        "max": ordered[-1],
    }


def analyze(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Every measure, computed from the extract alone."""
    per_bout: Counter[tuple[str, int]] = Counter()
    by_vendor: Counter[str] = Counter()
    for row in rows:
        per_bout[(row["session_id"], row["bout"])] += 1
        by_vendor[row["vendor"]] += 1

    bout_sizes = Counter(_bucket(count, BUCKETS) for count in per_bout.values())
    prompt_sizes = Counter(
        _bucket(int(row["prompt_chars"] or 0), SIZE_BUCKETS) for row in rows
    )
    fan_out = Counter(_bucket(int(row["replies"] or 0), BUCKETS) for row in rows)

    return {
        "exchanges": len(rows),
        "bouts": len(per_bout),
        "sessions": len({row["session_id"] for row in rows}),
        "exchanges_per_bout": _distribution(list(per_bout.values())),
        "prompt_chars": _distribution([int(r["prompt_chars"] or 0) for r in rows]),
        "reply_chars": _distribution([int(r["reply_chars"] or 0) for r in rows]),
        "replies_per_prompt": _distribution([int(r["replies"] or 0) for r in rows]),
        "bout_size_buckets": [
            {"label": label, "count": bout_sizes.get(label, 0)}
            for label, _low, _high in BUCKETS
        ],
        "prompt_size_buckets": [
            {"label": label, "count": prompt_sizes.get(label, 0)}
            for label, _low, _high in SIZE_BUCKETS
        ],
        "fan_out_buckets": [
            {"label": label, "count": fan_out.get(label, 0)}
            for label, _low, _high in BUCKETS
        ],
        "by_vendor": [
            {"vendor": vendor, "exchanges": count}
            for vendor, count in by_vendor.most_common()
        ],
    }


def _escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def _bars(title: str, lede: str, buckets: list[dict[str, Any]], slot: int) -> str:
    total = sum(item["count"] for item in buckets) or 1
    widest = max((item["count"] for item in buckets), default=0) or 1
    rows = "".join(
        f'<div class="row" tabindex="0" role="listitem" '
        f'aria-label="{_escape(item["label"])}: {item["count"]} '
        f'({item["count"]/total*100:.0f} percent)">'
        f'<div class="row-name">{_escape(item["label"])}</div>'
        f'<div class="track"><div class="bar s{slot}" '
        f'style="width:{max(item["count"]/widest*100, 0.6):.2f}%"></div>'
        f'<span class="row-value">{item["count"]:,}'
        f'<span class="pct">{item["count"]/total*100:.0f}%</span></span></div>'
        f'<div class="tip">{_escape(item["label"])}: {item["count"]:,} of '
        f'{total:,}</div></div>'
        for item in buckets
    )
    return (
        f'<section><h2>{_escape(title)}</h2>'
        f'<p class="lede">{lede}</p>'
        f'<div class="chart" role="list">{rows}</div></section>'
    )


def _summary_table(report: dict[str, Any]) -> str:
    rows = ""
    for key, label in (
        ("exchanges_per_bout", "Exchanges per bout"),
        ("prompt_chars", "Prompt characters"),
        ("reply_chars", "Reply characters"),
        ("replies_per_prompt", "Model replies per prompt"),
    ):
        d = report[key]
        if not d.get("n"):
            continue
        rows += (
            f'<tr><td>{_escape(label)}</td>'
            f'<td class="num">{d["n"]:,}</td>'
            f'<td class="num">{d["p25"]:,.0f}</td>'
            f'<td class="num">{d["p50"]:,.0f}</td>'
            f'<td class="num">{d["p75"]:,.0f}</td>'
            f'<td class="num">{d["p95"]:,.0f}</td>'
            f'<td class="num">{d["max"]:,.0f}</td></tr>'
        )
    return (
        '<section><h2>Distributions</h2>'
        '<p class="lede">Percentiles rather than means: each of these is '
        'heavy-tailed, and a mean is a number no individual exchange '
        'resembles.</p>'
        '<table><thead><tr><th>Measure</th><th class="num">n</th>'
        '<th class="num">p25</th><th class="num">p50</th><th class="num">p75</th>'
        '<th class="num">p95</th><th class="num">max</th></tr></thead>'
        f'<tbody>{rows}</tbody></table></section>'
    )


def _styles() -> str:
    light = "".join(f"  --s{slot}: {value};\n" for slot, value in enumerate(LIGHT))
    dark = "".join(f"  --s{slot}: {value};\n" for slot, value in enumerate(DARK))
    return f"""
.viz-root {{
  color-scheme: light;
  --surface-1: #fcfcfb; --surface-2: #f2f2f0;
  --text-primary: #0b0b0b; --text-secondary: #52514e; --text-muted: #6f6e6a;
  --grid: #e2e2de;
{light}}}
@media (prefers-color-scheme: dark) {{
  :root:where(:not([data-theme="light"])) .viz-root {{
    color-scheme: dark;
    --surface-1: #1a1a19; --surface-2: #232322;
    --text-primary: #ffffff; --text-secondary: #c3c2b7; --text-muted: #9a998f;
    --grid: #333331;
{dark}  }}
}}
:root[data-theme="dark"] .viz-root {{
  color-scheme: dark;
  --surface-1: #1a1a19; --surface-2: #232322;
  --text-primary: #ffffff; --text-secondary: #c3c2b7; --text-muted: #9a998f;
  --grid: #333331;
{dark}}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--surface-1); }}
.viz-root {{ background: var(--surface-1); color: var(--text-primary);
  font: 15px/1.5 ui-sans-serif, -apple-system, "Segoe UI", system-ui, sans-serif;
  padding: 40px 32px 72px; max-width: 980px; margin: 0 auto; }}
h1 {{ font-size: 26px; margin: 0 0 6px; letter-spacing: -0.01em; }}
h2 {{ font-size: 17px; margin: 0 0 6px; }}
.sub {{ color: var(--text-secondary); margin: 0 0 30px; font-size: 14px; }}
.lede {{ color: var(--text-secondary); font-size: 13.5px; margin: 0 0 16px;
  max-width: 74ch; }}
section {{ margin: 0 0 42px; }}
.tiles {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
  gap: 14px; margin: 0 0 40px; }}
.tile {{ background: var(--surface-2); border-radius: 10px; padding: 16px 18px; }}
.tile-label {{ color: var(--text-secondary); font-size: 12px;
  text-transform: uppercase; letter-spacing: 0.05em; }}
.tile-value {{ font-size: 30px; font-weight: 600; margin: 6px 0 2px;
  font-variant-numeric: tabular-nums; letter-spacing: -0.02em; }}
.tile-note {{ color: var(--text-muted); font-size: 12px; }}
.chart {{ display: flex; flex-direction: column; gap: 7px; }}
.row {{ display: grid; grid-template-columns: 96px 1fr; gap: 14px;
  align-items: center; position: relative; padding: 2px 0; border-radius: 4px; }}
.row:hover, .row:focus-visible {{ background: var(--surface-2); }}
.row:focus-visible {{ outline: none; box-shadow: 0 0 0 2px var(--s0); }}
.row-name {{ font-size: 13px; text-align: right; font-variant-numeric: tabular-nums; }}
.track {{ display: flex; align-items: center; gap: 9px; min-height: 20px; }}
.bar {{ height: 15px; border-radius: 0 4px 4px 0; }}
.bar.s0 {{ background: var(--s0); }}
.bar.s1 {{ background: var(--s1); }}
.row-value {{ font-size: 12.5px; color: var(--text-secondary);
  font-variant-numeric: tabular-nums; white-space: nowrap; }}
.pct {{ color: var(--text-muted); margin-left: 7px; }}
.tip {{ position: absolute; left: 110px; bottom: 100%; z-index: 5;
  background: var(--text-primary); color: var(--surface-1); padding: 7px 10px;
  border-radius: 6px; font-size: 12px; white-space: nowrap; opacity: 0;
  pointer-events: none; transition: opacity 90ms; }}
.row:hover .tip, .row:focus-visible .tip {{ opacity: 1; }}
table {{ border-collapse: collapse; width: 100%; font-size: 13.5px; }}
th, td {{ text-align: left; padding: 8px 12px; border-bottom: 1px solid var(--grid); }}
th {{ color: var(--text-secondary); font-weight: 600; font-size: 12px;
  text-transform: uppercase; letter-spacing: 0.04em; }}
td.num, th.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
footer {{ color: var(--text-muted); font-size: 12px; border-top: 1px solid var(--grid);
  padding-top: 18px; max-width: 78ch; }}
"""


def render(report: dict[str, Any], header: dict[str, Any]) -> str:
    tiles = [
        ("Exchanges", f"{report['exchanges']:,}", "one prompt and its replies"),
        ("Bouts", f"{report['bouts']:,}", "a sitting, not a Session"),
        ("Sessions", f"{report['sessions']:,}", "as the vendor recorded them"),
        ("Median bout", f"{report['exchanges_per_bout'].get('p50', 0):.0f}",
         "exchanges before an hour's gap"),
    ]
    cells = "".join(
        f'<div class="tile"><div class="tile-label">{_escape(a)}</div>'
        f'<div class="tile-value">{_escape(b)}</div>'
        f'<div class="tile-note">{_escape(c)}</div></div>'
        for a, b, c in tiles
    )
    excluded = (
        f"{header.get('excluded_status_only', 0):,} status-only prompts and "
        f"{header.get('excluded_not_human', 0):,} harness-generated ones were "
        f"excluded and counted."
    )
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Codess — dialog shape</title>
<style>{_styles()}</style></head>
<body><main class="viz-root">
<h1>How the work is actually shaped</h1>
<p class="sub">Human prompts and the model replies that follow them, from
{_escape(header.get('surface', 'cli'))} Sessions over
{_escape(header.get('since', 'all'))} time. {_escape(excluded)}</p>
<div class="tiles">{cells}</div>
{_summary_table(report)}
{_bars("Exchanges per bout",
       "A bout is a sitting: consecutive prompts less than "
       f"{header.get('bout_gap_minutes', 60)} minutes apart. Sessions span days; "
       "this is the unit work happens in.",
       report["bout_size_buckets"], 0)}
{_bars("Prompt size",
       "Characters per human prompt. The long tail is scripted or pasted "
       "content, not typing.",
       report["prompt_size_buckets"], 0)}
{_bars("Model replies per prompt",
       "How many model messages one instruction produced. This is harness "
       "behaviour as much as model behaviour, so it compares within a vendor.",
       report["fan_out_buckets"], 1)}
<footer>Prompt and reply are paired by Session sequence, which is evidence of
order rather than proof of causality. Harness traffic wearing a user envelope is
excluded by Actor classification, not by guessing at content.</footer>
</main></body></html>
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("extract", type=Path, help="a dialog_extract JSONL file")
    parser.add_argument("--html", type=Path, help="write the visual report here")
    parser.add_argument("--out", type=Path, help="write the measures as JSON here")
    args = parser.parse_args(argv)

    rows, header = load(args.extract)
    report = analyze(rows)
    payload = json.dumps({"header": header, **report}, indent=2, sort_keys=True)
    if args.out:
        args.out.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    if args.html:
        args.html.write_text(render(report, header), encoding="utf-8")
        print(f"wrote {args.html}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
