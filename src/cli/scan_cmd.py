"""codess scan CLI command."""

import csv
import json
import logging
import sys
from collections import defaultdict
from pathlib import Path

from codess.config import get_stats_path
from codess.helpers import write_csv
from codess.project import (
    RootsWhenEmpty,
    build_scan_run_options,
    resolve_cli_roots,
    resolve_registry_directory,
    validate_scan_source_for_cli,
)
from codess.registry_store import merge_scan_rows, update_project_entry
from codess.scan import run_scan

log = logging.getLogger(__name__)


def _registry_display_ts(ent: dict) -> str:
    return (
        str(ent.get("last_ingestion") or "")
        or str(ent.get("last_scan") or "")
        or str(ent.get("last_query") or "")
    )


def _load_registry_map(registry_root: Path) -> tuple[dict[str, dict] | None, str | None]:
    """Load ``ingested_projects.json`` into path (resolved string) -> entry dict."""
    stats_path = get_stats_path(registry_root)
    if not stats_path.exists():
        return None, f"codess: registry file not found: {stats_path}"
    try:
        data = json.loads(stats_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        return None, f"codess: cannot read registry {stats_path}: {e}"
    m: dict[str, dict] = {}
    for ent in data.get("projects") or []:
        p = ent.get("path")
        if isinstance(p, str) and p:
            m[p] = ent
    return m, None


def run(args) -> int:
    """Run codess scan. Returns exit code."""
    from codess.config import validate_config

    for msg in validate_config():
        print(f"codess: {msg}", file=sys.stderr)

    src_err = validate_scan_source_for_cli(getattr(args, "source", None))
    if src_err:
        print(src_err, file=sys.stderr)
        return 1

    roots, err = resolve_cli_roots(args, when_empty=RootsWhenEmpty.CWD)
    if err:
        print(err, file=sys.stderr)
        return 1

    opts = build_scan_run_options(args)
    merged: list[tuple[str, dict]] = []
    seen_paths: set[str] = set()
    had_error = False

    for work_root in roots:
        try:
            rows = run_scan(
                work_root,
                vendor_filter=opts.vendors,
                recent_days=opts.recent_days,
                debug=opts.debug,
                subagent=opts.subagent,
            )
        except Exception:
            log.exception("Scan failed for work root %s", work_root)
            had_error = True
            if opts.stop_on_error:
                return 1
            continue
        for r in rows:
            full = str((work_root / r["path"]).resolve())
            if full not in seen_paths:
                seen_paths.add(full)
                merged.append((full, r))

    write_root = resolve_registry_directory(args)
    reg_arg = getattr(args, "registry", None)
    filter_active = bool(reg_arg and str(reg_arg).strip())

    all_discovered = list(merged)

    registry_entries: dict[str, dict] | None = None
    if filter_active:
        registry_entries, reg_err = _load_registry_map(write_root)
        if reg_err:
            print(reg_err, file=sys.stderr)
            return 1
        if not registry_entries:
            print(
                "codess: warning: registry has no projects; scan output is empty",
                file=sys.stderr,
            )
        initial_keys = set(registry_entries.keys())
        merged = [(f, r) for f, r in merged if f in initial_keys]

    by_proj: dict[str, list[dict]] = defaultdict(list)
    for full, r in all_discovered:
        by_proj[full].append(r)
    for proj_path, rows in by_proj.items():
        def mut(e: dict, rs: list[dict] = rows) -> None:
            merge_scan_rows(e, rs)

        try:
            update_project_entry(write_root, proj_path, mut)
        except OSError as ex:
            log.warning("Registry update failed for %s: %s", proj_path, ex)

    out_path = getattr(args, "out", "codess_walk.csv")
    reg_cols = registry_entries is not None
    if out_path == "-":
        w = csv.writer(sys.stdout)
        headers = (
            ["path", "dir_path", "vendor", "sess", "mb", "span_weeks"]
            if opts.debug
            else ["path", "vendor", "sess", "mb", "span_weeks"]
        )
        if reg_cols:
            headers.extend(["reg_path", "reg_updated", "reg_sources"])
        w.writerow(headers)
        for full, r in merged:
            row = (
                [r["path"], r["dir_path"], r["vendor"], r["sess"], r["mb"], r["span_weeks"]]
                if opts.debug
                else [r["path"], r["vendor"], r["sess"], r["mb"], r["span_weeks"]]
            )
            if reg_cols:
                ent = registry_entries[full]
                sources = ent.get("sources") or {}
                row.extend(
                    [
                        ent.get("path", full),
                        _registry_display_ts(ent),
                        json.dumps(sources, separators=(",", ":")),
                    ]
                )
            w.writerow(row)
    else:
        headers = (
            ["path", "dir_path", "vendor", "sess", "mb", "span_weeks"]
            if opts.debug
            else ["path", "vendor", "sess", "mb", "span_weeks"]
        )
        if reg_cols:
            headers.extend(["reg_path", "reg_updated", "reg_sources"])
        data = []
        for full, r in merged:
            row = (
                [r["path"], r["dir_path"], r["vendor"], r["sess"], r["mb"], r["span_weeks"]]
                if opts.debug
                else [r["path"], r["vendor"], r["sess"], r["mb"], r["span_weeks"]]
            )
            if reg_cols:
                ent = registry_entries[full]
                sources = ent.get("sources") or {}
                row.extend(
                    [
                        ent.get("path", full),
                        _registry_display_ts(ent),
                        json.dumps(sources, separators=(",", ":")),
                    ]
                )
            data.append(row)
        write_csv(Path(out_path), data, headers=headers)
        print(f"Wrote {len(merged)} rows to {out_path}")

    return 1 if had_error else 0
