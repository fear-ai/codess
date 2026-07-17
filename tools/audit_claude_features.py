#!/usr/bin/env python3
"""Write a bounded structure-only Claude Code feature evidence report."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from codess.config import CC_PROJECTS  # noqa: E402
from codess.fileio import write_json_atomic  # noqa: E402
from codess.vendor_audits.claude_features import audit_claude_features  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=CC_PROJECTS)
    parser.add_argument("--max-files", type=int, default=200)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = audit_claude_features(args.root, max_files=args.max_files)
    if args.output:
        write_json_atomic(args.output, report)
    print(json.dumps({
        "files_reviewed": report["files_reviewed"],
        "records_reviewed": report["records_reviewed"],
        "parent_links": report["parent_links"],
        "sidechain_records": report["sidechain_records"],
        "versions": len(report["versions"]),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
