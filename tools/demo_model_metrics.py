#!/usr/bin/env python3
"""Generate bounded model-latency and prompt/response demonstration artifacts.

The tool reads one CoSchema vendor store in read-only mode.  It writes tidy
CSV data, a Markdown latency table, two dependency-free SVG charts, and a
manifest that fixes the selection and calculation policy.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sqlite3
from collections.abc import Iterable
from datetime import datetime
from html import escape
from pathlib import Path
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

FORMAT = "codess.demo-model-metrics/1"
DEFAULT_TABLE_MODELS = (
    "claude-fable-5",
    "claude-opus-4-8",
    "claude-sonnet-5",
)
DEFAULT_PLOT_MODELS = (
    "claude-fable-5",
    "claude-opus-4-8",
)
MODEL_LABELS = {
    "claude-fable-5": "Claude Fable 5",
    "claude-opus-4-8": "Claude Opus 4.8",
    "claude-sonnet-5": "Claude Sonnet 5",
}
MODEL_COLORS = {
    "claude-fable-5": "#168f86",
    "claude-opus-4-8": "#df5b50",
    "claude-sonnet-5": "#d5a321",
}
VENDOR_STORES = {
    "cc": "sessions_cc.db",
    "codex": "sessions_codex.db",
    "cursor": "sessions_cursor.db",
}


def _parse_boundary(value: str, timezone_name: str) -> float:
    """Return an inclusive/exclusive boundary as Unix milliseconds."""
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(timezone_name))
    return parsed.timestamp() * 1000


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} does not contain a JSON object")
    return value


def _catalog_project_id(project: Path, registry: Path) -> str | None:
    binding = project / ".codess" / "project.json"
    if binding.exists():
        project_id = _read_json(binding).get("project_id")
        if isinstance(project_id, str) and project_id:
            return project_id
    catalog = registry / "projects.json"
    if not catalog.exists():
        return None
    resolved = str(project.resolve())
    for record in _read_json(catalog).get("projects", []):
        if any(
            location.get("path") == resolved
            for location in record.get("locations", [])
            if isinstance(location, dict)
        ):
            project_id = record.get("project_id")
            return project_id if isinstance(project_id, str) else None
    return None


def resolve_store(
    *,
    store: Path | None,
    project: Path | None,
    vendor: str,
    registry: Path,
) -> tuple[Path, dict[str, Any]]:
    if store is not None:
        resolved = store.expanduser().resolve()
        return resolved, {"selection_kind": "store", "store": str(resolved)}
    if project is None:
        raise ValueError("either --store or --project is required")
    project = project.expanduser().resolve()
    pointer = project / ".codess" / "current.json"
    project_id = _catalog_project_id(project, registry)
    if not pointer.exists() and project_id:
        pointer = (
            registry
            / "projects"
            / project_id.removeprefix("codess:project:")
            / "current.json"
        )
    if not pointer.exists():
        raise ValueError(f"no current Codess snapshot found for {project}")
    current = _read_json(pointer)
    snapshot = Path(str(current["path"]))
    if not snapshot.is_absolute():
        snapshot = (pointer.parent / snapshot).resolve()
    resolved = snapshot / VENDOR_STORES[vendor]
    return resolved, {
        "selection_kind": "project-current",
        "project": str(project),
        "project_id": current.get("project_id") or project_id,
        "snapshot_id": current.get("snapshot_id"),
        "pointer": str(pointer.resolve()),
        "manifest_sha256": current.get("manifest_sha256"),
        "store": str(resolved),
    }


INTERACTION_SQL = """
WITH interaction_observations AS (
  SELECT e.interaction_id,
         MIN(CASE
               WHEN e.actor_kind = 'human'
                AND e.content_role IN ('prompt', 'command')
               THEN e.event_at END) AS prompt_at,
         MIN(CASE
               WHEN e.actor_kind = 'model'
                AND e.content_role = 'response'
               THEN e.event_at END) AS first_response_at,
         MAX(CASE
               WHEN e.actor_kind = 'model'
                AND e.content_role = 'response'
               THEN e.event_at END) AS last_response_at,
         SUM(CASE
               WHEN e.actor_kind = 'human'
                AND e.content_role IN ('prompt', 'command')
               THEN COALESCE(e.content_len, 0) ELSE 0 END) AS prompt_chars,
         SUM(CASE
               WHEN e.actor_kind = 'model'
                AND e.content_role = 'response'
               THEN COALESCE(e.content_len, 0) ELSE 0 END) AS response_chars,
         SUM(CASE WHEN e.event_kind = 'tool.call' THEN 1 ELSE 0 END)
           AS tool_calls
    FROM events e
   WHERE e.event_at >= ?
     AND e.event_at < ?
     AND e.interaction_id IS NOT NULL
   GROUP BY e.interaction_id
), model_counts AS (
  SELECT e.interaction_id,
         mc.model_name_exact AS model,
         COUNT(*) AS response_events,
         ROW_NUMBER() OVER (
           PARTITION BY e.interaction_id
           ORDER BY COUNT(*) DESC, mc.model_name_exact
         ) AS preference
    FROM events e
    JOIN model_turns mt ON mt.id = e.model_turn_id
    JOIN model_params mc ON mc.id = mt.model_param_id
   WHERE e.actor_kind = 'model'
     AND e.content_role = 'response'
     AND e.event_at >= ?
     AND e.event_at < ?
   GROUP BY e.interaction_id, mc.model_name_exact
)
SELECT observations.*,
       COALESCE(models.model, 'unknown') AS model
  FROM interaction_observations observations
  LEFT JOIN model_counts models
    ON models.interaction_id = observations.interaction_id
   AND models.preference = 1
 WHERE observations.prompt_at IS NOT NULL
 ORDER BY observations.prompt_at, observations.interaction_id
"""


def read_interactions(
    store: Path,
    *,
    start_ms: float,
    end_ms: float,
    first_cap_ms: float,
    completion_cap_ms: float,
) -> list[dict[str, Any]]:
    if not store.is_file():
        raise ValueError(f"CoSchema store not found: {store}")
    uri = store.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            INTERACTION_SQL, (start_ms, end_ms, start_ms, end_ms)
        ).fetchall()
    finally:
        conn.close()
    interactions: list[dict[str, Any]] = []
    for row in rows:
        value = dict(row)
        first = (
            value["first_response_at"] - value["prompt_at"]
            if value["first_response_at"] is not None
            else None
        )
        completion = (
            value["last_response_at"] - value["prompt_at"]
            if value["last_response_at"] is not None
            else None
        )
        value["first_response_seconds"] = (
            first / 1000
            if first is not None and 0 <= first <= first_cap_ms
            else None
        )
        value["completion_seconds"] = (
            completion / 1000
            if completion is not None and 0 <= completion <= completion_cap_ms
            else None
        )
        interactions.append(value)
    return interactions


def _percentile(values: Iterable[float], fraction: float) -> float | None:
    ordered = sorted(values)
    if not ordered:
        return None
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return (
        ordered[lower] * (upper - position)
        + ordered[upper] * (position - lower)
    )


def summarize_models(
    interactions: list[dict[str, Any]], models: Iterable[str]
) -> list[dict[str, Any]]:
    summaries = []
    for model in models:
        selected = [row for row in interactions if row["model"] == model]
        first = [
            row["first_response_seconds"]
            for row in selected
            if row["first_response_seconds"] is not None
        ]
        completion = [
            row["completion_seconds"]
            for row in selected
            if row["completion_seconds"] is not None
        ]
        tool_calls = [int(row["tool_calls"]) for row in selected]
        summaries.append({
            "model": model,
            "label": MODEL_LABELS.get(model, model),
            "interactions": len(selected),
            "first_latency_observations": len(first),
            "first_response_p50_seconds": _percentile(first, 0.50),
            "first_response_p90_seconds": _percentile(first, 0.90),
            "completion_latency_observations": len(completion),
            "completion_p50_seconds": _percentile(completion, 0.50),
            "completion_p90_seconds": _percentile(completion, 0.90),
            "median_tool_calls": median(tool_calls) if tool_calls else None,
        })
    return summaries


def _format_number(value: float | int | None, digits: int = 1) -> str:
    if value is None:
        return ""
    return f"{value:.{digits}f}"


def write_latency_outputs(
    out_dir: Path, summaries: list[dict[str, Any]]
) -> None:
    csv_path = out_dir / "model-latency.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(summaries[0]))
        writer.writeheader()
        writer.writerows(summaries)
    lines = [
        "| Model | Interactions | First response p50/p90 | "
        "Completion p50/p90 | Median tool calls |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in summaries:
        first = "/".join((
            _format_number(row["first_response_p50_seconds"]),
            _format_number(row["first_response_p90_seconds"]),
        )).strip("/")
        completion = "/".join((
            _format_number(row["completion_p50_seconds"]),
            _format_number(row["completion_p90_seconds"]),
        )).strip("/")
        lines.append(
            f"| {row['label']} | {row['interactions']} | {first or '—'} sec | "
            f"{completion or '—'} sec | "
            f"{_format_number(row['median_tool_calls']) or '—'} |"
        )
    (out_dir / "model-latency.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def write_prompt_response_csv(
    out_dir: Path,
    interactions: list[dict[str, Any]],
    plot_models: Iterable[str],
) -> list[dict[str, Any]]:
    allowed = set(plot_models)
    selected = [
        {
            "interaction_id": row["interaction_id"],
            "model": row["model"],
            "model_label": MODEL_LABELS.get(row["model"], row["model"]),
            "prompt_characters": int(row["prompt_chars"]),
            "response_characters": int(row["response_chars"]),
            "tool_calls": int(row["tool_calls"]),
            "first_response_seconds": row["first_response_seconds"],
            "completion_seconds": row["completion_seconds"],
        }
        for row in interactions
        if row["model"] in allowed
        and row["prompt_chars"] > 0
        and row["response_chars"] > 0
    ]
    path = out_dir / "prompt-response.csv"
    fields = list(selected[0]) if selected else [
        "interaction_id", "model", "model_label", "prompt_characters",
        "response_characters", "tool_calls", "first_response_seconds",
        "completion_seconds",
    ]
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(selected)
    return selected


def _log_extent(values: Iterable[int]) -> tuple[float, float]:
    logs = [math.log10(value) for value in values if value > 0]
    if not logs:
        return 0.0, 1.0
    low = math.floor(min(logs))
    high = math.ceil(max(logs))
    return (low, high if high > low else low + 1)


def write_prompt_response_svg(
    out_dir: Path,
    rows: list[dict[str, Any]],
    *,
    start: str,
    end: str,
) -> None:
    width, height = 1200, 720
    left, right, top, bottom = 110, 60, 105, 100
    plot_width = width - left - right
    plot_height = height - top - bottom
    x_low, x_high = _log_extent(row["prompt_characters"] for row in rows)
    y_low, y_high = _log_extent(row["response_characters"] for row in rows)

    def x(value: int) -> float:
        return left + (math.log10(value) - x_low) / (x_high - x_low) * plot_width

    def y(value: int) -> float:
        return top + plot_height - (
            (math.log10(value) - y_low) / (y_high - y_low) * plot_height
        )

    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
        f'height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#fbfaf6"/>',
        '<style>text{font-family:Inter,system-ui,sans-serif;fill:#17324d}'
        '.grid{stroke:#dce4e8;stroke-width:1}.axis{stroke:#17324d;stroke-width:2}'
        '.tick{font-size:14px}.label{font-size:18px;font-weight:600}'
        '.title{font-size:28px;font-weight:700}.subtitle{font-size:15px;fill:#53697d}'
        '</style>',
        f'<text class="title" x="{left}" y="42">Prompt and response volume</text>',
        f'<text class="subtitle" x="{left}" y="70">Fable and Opus Interactions; '
        f'{escape(start)} to {escape(end)} (end exclusive)</text>',
    ]
    for power in range(int(x_low), int(x_high) + 1):
        px = x(10**power)
        svg.append(f'<line class="grid" x1="{px:.1f}" y1="{top}" x2="{px:.1f}" y2="{top + plot_height}"/>')
        svg.append(f'<text class="tick" text-anchor="middle" x="{px:.1f}" y="{top + plot_height + 28}">10^{power}</text>')
    for power in range(int(y_low), int(y_high) + 1):
        py = y(10**power)
        svg.append(f'<line class="grid" x1="{left}" y1="{py:.1f}" x2="{left + plot_width}" y2="{py:.1f}"/>')
        svg.append(f'<text class="tick" text-anchor="end" x="{left - 14}" y="{py + 5:.1f}">10^{power}</text>')
    svg.extend([
        f'<line class="axis" x1="{left}" y1="{top + plot_height}" x2="{left + plot_width}" y2="{top + plot_height}"/>',
        f'<line class="axis" x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_height}"/>',
        f'<text class="label" text-anchor="middle" x="{left + plot_width / 2}" y="{height - 30}">Human prompt characters (log scale)</text>',
        f'<text class="label" text-anchor="middle" transform="translate(28 {top + plot_height / 2}) rotate(-90)">Model response characters (log scale)</text>',
    ])
    for row in rows:
        color = MODEL_COLORS.get(row["model"], "#53697d")
        radius = min(12.0, 4.0 + 2.2 * math.log1p(row["tool_calls"]))
        title = (
            f"{row['model_label']}; prompt {row['prompt_characters']}; "
            f"response {row['response_characters']}; tools {row['tool_calls']}"
        )
        svg.append(
            f'<circle cx="{x(row["prompt_characters"]):.1f}" '
            f'cy="{y(row["response_characters"]):.1f}" r="{radius:.1f}" '
            f'fill="{color}" fill-opacity="0.58" stroke="{color}" stroke-width="1">'
            f'<title>{escape(title)}</title></circle>'
        )
    legend_x = left + plot_width - 245
    legend_y = top + 20
    for index, model in enumerate(DEFAULT_PLOT_MODELS):
        row_y = legend_y + index * 30
        svg.append(f'<circle cx="{legend_x}" cy="{row_y}" r="6" fill="{MODEL_COLORS[model]}"/>')
        svg.append(f'<text class="tick" x="{legend_x + 14}" y="{row_y + 5}">{escape(MODEL_LABELS[model])}</text>')
    svg.append('</svg>')
    (out_dir / "prompt-response.svg").write_text(
        "\n".join(svg) + "\n", encoding="utf-8"
    )


def write_latency_svg(
    out_dir: Path, summaries: list[dict[str, Any]], *, start: str, end: str
) -> None:
    width, height = 1200, 510
    left, right, top = 245, 80, 120
    plot_width = width - left - right
    positive = [
        float(value)
        for row in summaries
        for key, value in row.items()
        if key.endswith("_seconds") and value is not None and value > 0
    ]
    low = math.floor(math.log10(min(positive))) if positive else 0
    high = math.ceil(math.log10(max(positive))) if positive else 1
    if high <= low:
        high = low + 1

    def x(value: float) -> float:
        return left + (math.log10(value) - low) / (high - low) * plot_width

    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#fbfaf6"/>',
        '<style>text{font-family:Inter,system-ui,sans-serif;fill:#17324d}'
        '.grid{stroke:#dce4e8}.title{font-size:28px;font-weight:700}'
        '.subtitle{font-size:15px;fill:#53697d}.model{font-size:17px;font-weight:600}'
        '.tick{font-size:14px}.key{font-size:14px}</style>',
        f'<text class="title" x="{left}" y="42">Interaction latency by model</text>',
        f'<text class="subtitle" x="{left}" y="70">p50 dots and p90 whiskers; {escape(start)} to {escape(end)}</text>',
    ]
    for power in range(low, high + 1):
        px = x(10**power)
        svg.append(f'<line class="grid" x1="{px:.1f}" y1="{top - 10}" x2="{px:.1f}" y2="{height - 70}"/>')
        svg.append(f'<text class="tick" text-anchor="middle" x="{px:.1f}" y="{height - 42}">10^{power} sec</text>')
    for index, row in enumerate(summaries):
        y = top + 80 * index
        color = MODEL_COLORS.get(row["model"], "#53697d")
        svg.append(f'<text class="model" text-anchor="end" x="{left - 22}" y="{y + 6}">{escape(row["label"])}</text>')
        svg.append(f'<text class="tick" text-anchor="end" x="{left - 22}" y="{y + 26}">n={row["interactions"]}</text>')
        for offset, prefix, marker in ((-12, "first_response", "circle"), (12, "completion", "square")):
            p50 = row[f"{prefix}_p50_seconds"]
            p90 = row[f"{prefix}_p90_seconds"]
            if p50 is None or p90 is None or p50 <= 0 or p90 <= 0:
                continue
            y2 = y + offset
            svg.append(f'<line x1="{x(p50):.1f}" y1="{y2}" x2="{x(p90):.1f}" y2="{y2}" stroke="{color}" stroke-width="4" stroke-linecap="round"/>')
            if marker == "circle":
                svg.append(f'<circle cx="{x(p50):.1f}" cy="{y2}" r="6" fill="{color}"/>')
            else:
                svg.append(f'<rect x="{x(p50)-6:.1f}" y="{y2-6}" width="12" height="12" fill="{color}"/>')
    svg.extend([
        f'<circle cx="{left}" cy="{height - 12}" r="6" fill="#17324d"/><text class="key" x="{left + 14}" y="{height - 7}">first response</text>',
        f'<rect x="{left + 150}" y="{height - 18}" width="12" height="12" fill="#17324d"/><text class="key" x="{left + 168}" y="{height - 7}">completion</text>',
        '</svg>',
    ])
    (out_dir / "model-latency.svg").write_text(
        "\n".join(svg) + "\n", encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument(
        "--directory", type=Path,
        help="the Project directory to read",
    )
    selection.add_argument(
        "--store-file", dest="store", type=Path,
        help="one source-system store to read instead of a Project directory",
    )
    parser.add_argument("--vendor", choices=sorted(VENDOR_STORES), default="cc")
    parser.add_argument(
        "--store", dest="store_root", type=Path,
        default=Path.home() / ".codess",
        help="the machine's durable store (default: ~/.codess)",
    )
    parser.add_argument("--start", required=True, help="inclusive ISO date/time")
    parser.add_argument("--end", required=True, help="exclusive ISO date/time")
    parser.add_argument("--timezone", default="America/Los_Angeles")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--table-model", action="append")
    parser.add_argument("--plot-model", action="append")
    parser.add_argument("--first-cap-minutes", type=float, default=60)
    parser.add_argument("--completion-cap-minutes", type=float, default=240)
    args = parser.parse_args(argv)
    if args.first_cap_minutes <= 0 or args.completion_cap_minutes <= 0:
        parser.error("latency caps must be positive")
    try:
        start_ms = _parse_boundary(args.start, args.timezone)
        end_ms = _parse_boundary(args.end, args.timezone)
        if start_ms >= end_ms:
            raise ValueError("--start must precede --end")
        store, selection_info = resolve_store(
            store=args.store,
            project=args.directory,
            vendor=args.vendor,
            registry=args.store_root.expanduser().resolve(),
        )
        interactions = read_interactions(
            store,
            start_ms=start_ms,
            end_ms=end_ms,
            first_cap_ms=args.first_cap_minutes * 60_000,
            completion_cap_ms=args.completion_cap_minutes * 60_000,
        )
    except (OSError, ValueError, KeyError, json.JSONDecodeError, sqlite3.Error) as exc:
        parser.error(str(exc))
    table_models = tuple(args.table_model or DEFAULT_TABLE_MODELS)
    plot_models = tuple(args.plot_model or DEFAULT_PLOT_MODELS)
    out_dir = args.out_dir.expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    summaries = summarize_models(interactions, table_models)
    write_latency_outputs(out_dir, summaries)
    plot_rows = write_prompt_response_csv(out_dir, interactions, plot_models)
    write_latency_svg(out_dir, summaries, start=args.start, end=args.end)
    write_prompt_response_svg(
        out_dir, plot_rows, start=args.start, end=args.end
    )
    manifest = {
        "format": FORMAT,
        "selection": selection_info,
        "vendor": args.vendor,
        "start": args.start,
        "end_exclusive": args.end,
        "timezone": args.timezone,
        "table_models": list(table_models),
        "plot_models": list(plot_models),
        "latency_policy": {
            "first_response_cap_minutes": args.first_cap_minutes,
            "completion_cap_minutes": args.completion_cap_minutes,
            "negative_observations": "excluded",
        },
        "outputs": [
            "model-latency.csv", "model-latency.md", "model-latency.svg",
            "prompt-response.csv", "prompt-response.svg",
        ],
    }
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
    manifest["specification_sha256"] = hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "output": str(out_dir),
        "interactions": len(interactions),
        "plotted_interactions": len(plot_rows),
        "table_models": list(table_models),
        "plot_models": list(plot_models),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
