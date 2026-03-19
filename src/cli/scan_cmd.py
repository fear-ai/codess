"""codess scan CLI command."""

import csv
import sys
from pathlib import Path

from codess.helpers import parse_dir_list, write_csv
from codess.scan import run_scan


def run(args) -> int:
    """Run codess scan. Returns exit code."""
    dirs_file = Path(args.dirs) if getattr(args, "dirs", None) else None
    dir_list = getattr(args, "dir_list", None) or []
    roots = parse_dir_list(dirs_file, dir_list)
    if not roots:
        roots = [Path.cwd()]

    source_filter = getattr(args, "source", None)
    vendors = [v.strip().lower() for v in source_filter.split(",") if v.strip()] if source_filter else None

    from codess.config import CODESS_DAYS
    recent_days = args.days if getattr(args, "days", None) is not None else CODESS_DAYS

    debug = getattr(args, "debug", False)
    all_rows = []
    seen_paths = set()
    for work_root in roots:
        rows = run_scan(work_root, vendor_filter=vendors, recent_days=None if debug else recent_days, debug=debug)
        for r in rows:
            full = str((work_root / r["path"]).resolve())
            if full not in seen_paths:
                seen_paths.add(full)
                all_rows.append(r)

    out_path = getattr(args, "out", "find_codess.csv")
    if out_path == "-":
        w = csv.writer(sys.stdout)
        headers = ["path", "dir_path", "vendor", "sess", "mb", "span_weeks"] if debug else ["path", "vendor", "sess", "mb", "span_weeks"]
        w.writerow(headers)
        for r in all_rows:
            row = [r["path"], r["dir_path"], r["vendor"], r["sess"], r["mb"], r["span_weeks"]] if debug else [r["path"], r["vendor"], r["sess"], r["mb"], r["span_weeks"]]
            w.writerow(row)
    else:
        headers = ["path", "dir_path", "vendor", "sess", "mb", "span_weeks"] if debug else ["path", "vendor", "sess", "mb", "span_weeks"]
        data = [([r["path"], r["dir_path"], r["vendor"], r["sess"], r["mb"], r["span_weeks"]] if debug else [r["path"], r["vendor"], r["sess"], r["mb"], r["span_weeks"]]) for r in all_rows]
        write_csv(Path(out_path), data, headers=headers)
        print(f"Wrote {len(all_rows)} rows to {out_path}")

    return 0
