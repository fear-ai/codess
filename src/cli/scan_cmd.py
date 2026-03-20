"""codess scan CLI command."""

import csv
import logging
import sys
from pathlib import Path

from codess.project import RootsWhenEmpty, build_scan_run_options, resolve_cli_roots
from codess.helpers import write_csv
from codess.scan import run_scan

log = logging.getLogger(__name__)


def run(args) -> int:
    """Run codess scan. Returns exit code."""
    from codess.config import validate_config

    for msg in validate_config():
        print(f"codess: {msg}", file=sys.stderr)

    roots, err = resolve_cli_roots(args, when_empty=RootsWhenEmpty.CWD)
    if err:
        print(err, file=sys.stderr)
        return 1

    opts = build_scan_run_options(args)
    all_rows = []
    seen_paths = set()
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
                all_rows.append(r)

    out_path = getattr(args, "out", "codess_walk.csv")
    if out_path == "-":
        w = csv.writer(sys.stdout)
        headers = (
            ["path", "dir_path", "vendor", "sess", "mb", "span_weeks"]
            if opts.debug
            else ["path", "vendor", "sess", "mb", "span_weeks"]
        )
        w.writerow(headers)
        for r in all_rows:
            row = (
                [r["path"], r["dir_path"], r["vendor"], r["sess"], r["mb"], r["span_weeks"]]
                if opts.debug
                else [r["path"], r["vendor"], r["sess"], r["mb"], r["span_weeks"]]
            )
            w.writerow(row)
    else:
        headers = (
            ["path", "dir_path", "vendor", "sess", "mb", "span_weeks"]
            if opts.debug
            else ["path", "vendor", "sess", "mb", "span_weeks"]
        )
        data = [
            (
                [r["path"], r["dir_path"], r["vendor"], r["sess"], r["mb"], r["span_weeks"]]
                if opts.debug
                else [r["path"], r["vendor"], r["sess"], r["mb"], r["span_weeks"]]
            )
            for r in all_rows
        ]
        write_csv(Path(out_path), data, headers=headers)
        print(f"Wrote {len(all_rows)} rows to {out_path}")

    return 1 if had_error else 0
