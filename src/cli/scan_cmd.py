"""codess scan CLI command."""

import argparse
import csv
import json
import logging
import sys
from collections import defaultdict
from pathlib import Path

from cli.failure import fail, fail_configuration, warn
from codess import reporting
from codess.codex_source import build_session_index as build_codex_session_index
from codess.config import (
    CC_PROJECTS,
    CODEX_SESSIONS,
    CURSOR_DATA,
    DAYS,
    get_project_state_path,
)
from codess.helpers import unsafe_traversal_root_reason, write_csv
from codess.project import (
    RootsWhenEmpty,
    build_scan_run_options,
    resolve_cli_roots,
    resolve_store_root,
    validate_scan_source_for_cli,
)
from codess.registry_store import (
    merge_scan_rows,
    prune_legacy_cursor_global_entries,
    update_project_entry,
)
from codess.sanitize import protect_csv_row
from codess.walk_sessions import walk_sessions

log = logging.getLogger(__name__)


def _registry_display_ts(ent: dict) -> str:
    return (
        str(ent.get("last_ingestion") or "")
        or str(ent.get("last_scan") or "")
        or str(ent.get("last_query") or "")
    )


def _load_registry_map(store_root: Path) -> tuple[dict[str, dict] | None, str | None]:
    """Load ``projects_state.json`` into path (resolved string) -> entry dict."""
    stats_path = get_project_state_path(store_root)
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


def _print_scan_diagnostics(diagnostics: dict) -> None:
    counts = {
        "malformed": diagnostics.get("malformed_sources", 0),
        "stale_index_entries": diagnostics.get("stale_index_entries", 0),
        "invalid_keys": diagnostics.get("invalid_keys", 0),
        "failed_sources": diagnostics.get("failed_sources", 0),
        "failed_roots": diagnostics.get("failed_roots", 0),
    }
    if any(counts.values()):
        warn('codess: scan diagnostics: ' + ' '.join((f'{key}={value}' for key, value in counts.items())))
    # A Project omitted by the recency window is not a diagnostic among
    # others: the result is incomplete in a way the reader cannot see from
    # the output, so it is stated separately with the way to widen it.
    hidden = diagnostics.get("projects_outside_recency_window", 0)
    if hidden:
        warn(f'codess: {hidden} project(s) have coding work older than the {DAYS}-day window and are not listed; use --days 0 for all, or CODESS_DAYS to change the default')


def run(args: argparse.Namespace) -> int:
    """Run codess scan. Returns exit code."""
    if fail_configuration():
        return 1

    src_err = validate_scan_source_for_cli(getattr(args, "source", None))
    if src_err:
        return fail(src_err)

    roots, err = resolve_cli_roots(args, when_empty=RootsWhenEmpty.CWD)
    if err or roots is None:
        return fail(err or "no roots resolved")
    for root in roots:
        reason = unsafe_traversal_root_reason(root)
        if reason:
            return fail(f'codess: {reason}; select a project, workspace, or home subtree')

    opts = build_scan_run_options(args)
    if opts["recent_days"] is not None and opts["recent_days"] < 0:
        return fail('codess: --days must be >= 0 (0 means all time)')
    merged: list[tuple[str, dict]] = []
    seen_paths: set[str] = set()
    had_error = False
    diagnostics: dict = {}
    write_root = resolve_store_root(args)
    # `--debug` selects the reporting profile rather than a per-call flag: the
    # discovery diagnostics are debug-level events, and the level gate is what
    # decides whether they are emitted. Roots are registered so a
    # `located` field renders against them under a sharing profile.
    reporting.configure(
        getattr(args, "report_profile", None) or ("debug" if opts["debug"] else None),
        privacy=getattr(args, "report_privacy", None),
        redaction_roots={
            "home": Path.home(),
            "registry": write_root,
            "cc-projects": CC_PROJECTS,
            "codex-sessions": CODEX_SESSIONS,
            "cursor-data": CURSOR_DATA,
        },
    )
    codex_index = None
    if opts["vendors"] is None or "codex" in opts["vendors"]:
        codex_index = build_codex_session_index(
            cache_path=write_root / "cache" / "codex-session-index-v1.json",
            include_record_counts=True,
        )

    for root_index, work_root in enumerate(roots):
        failures_before = diagnostics.get("failed_sources", 0)
        try:
            rows = walk_sessions(
                work_root,
                vendor_filter=opts["vendors"],
                recent_days=opts["recent_days"],
                debug=opts["debug"],
                subagent=opts["subagent"],
                diagnostics=diagnostics,
                include_cursor_global=root_index == 0,
                codex_index=codex_index,
            )
        except Exception:
            log.exception("Scan failed for work root %s", work_root)
            diagnostics["failed_roots"] = diagnostics.get("failed_roots", 0) + 1
            had_error = True
            if opts["stop_on_error"]:
                _print_scan_diagnostics(diagnostics)
                return 1
            continue
        if diagnostics.get("failed_sources", 0) > failures_before:
            had_error = True
            if opts["stop_on_error"]:
                _print_scan_diagnostics(diagnostics)
                return 1
        for r in rows:
            # The Cursor central store is evidence awaiting attribution, not a
            # project nested beneath whichever scan root happened to run first.
            full = "(global)" if r["path"] == "(global)" else str((work_root / r["path"]).resolve())
            if full not in seen_paths:
                seen_paths.add(full)
                merged.append((full, r))

    pruned_global = prune_legacy_cursor_global_entries(write_root)
    if pruned_global:
        # The reporting level decides whether this is shown, rather than an
        # `opts["debug"]` test beside it: two gates for one decision is how a
        # profile and a flag come to disagree.
        reporting.event(
            reporting.code("registry.legacy_cursor_pruned"), projects=pruned_global,
        )
    reg_arg = getattr(args, "store_root", None)
    filter_active = bool(reg_arg and str(reg_arg).strip())

    all_discovered = list(merged)

    registry_entries: dict[str, dict] | None = None
    if filter_active:
        registry_entries, reg_err = _load_registry_map(write_root)
        if reg_err:
            return fail(reg_err)
        if not registry_entries:
            warn('codess: warning: registry has no projects; scan output is empty')
        initial_keys = set(registry_entries.keys())
        merged = [(f, r) for f, r in merged if f in initial_keys]

    by_proj: dict[str, list[dict]] = defaultdict(list)
    for full, r in all_discovered:
        by_proj[full].append(r)
    for proj_path, rows in by_proj.items():
        if proj_path == "(global)":
            continue
        def mut(e: dict, rs: list[dict] = rows) -> None:
            merge_scan_rows(e, rs)

        try:
            update_project_entry(write_root, proj_path, mut)
        except OSError as ex:
            log.warning("Registry update failed for %s: %s", proj_path, ex)

    out_path = getattr(args, "out", "codess_walk.csv")
    reg_cols = registry_entries is not None

    def report_headers() -> list[str]:
        headers = (
            ["path", "dir_path", "vendor", "sess", "mb", "span_weeks"]
            if opts["debug"]
            else ["path", "vendor", "sess", "mb", "span_weeks"]
        )
        if reg_cols:
            headers.extend(["reg_path", "reg_updated", "reg_sources"])
        return headers

    def report_row(full: str, r: dict) -> list:
        """One report row, for either destination.

        The stdout and file paths built this and the header list separately,
        so a column added to one reached the other only if someone edited
        both. They differ in where a row goes, which is the loop, not in what
        a row is.
        """
        row = (
            [r["path"], r["dir_path"], r["vendor"], r["sess"], r["mb"], r["span_weeks"]]
            if opts["debug"]
            else [r["path"], r["vendor"], r["sess"], r["mb"], r["span_weeks"]]
        )
        if reg_cols:
            ent = registry_entries[full]
            row.extend([
                ent.get("path", full),
                _registry_display_ts(ent),
                json.dumps(ent.get("sources") or {}, separators=(",", ":")),
            ])
        return row

    if out_path == "-":
        w = csv.writer(sys.stdout)
        w.writerow(report_headers())
        for full, r in merged:
            w.writerow(protect_csv_row(report_row(full, r)))
    else:
        write_csv(
            Path(out_path),
            [report_row(full, r) for full, r in merged],
            headers=report_headers(),
        )
        print(f"Wrote {len(merged)} rows to {out_path}")

    _print_scan_diagnostics(diagnostics)
    # A command boundary: whatever is still buffered must reach the sink before
    # the process ends, or a batch smaller than the flush threshold is silently
    # lost.
    reporting.flush()
    return 1 if had_error else 0
