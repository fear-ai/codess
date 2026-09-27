#!/usr/bin/env python3
"""Build a structure-only inventory for currently wanted compatibility evidence."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from codess.baseline_validation import write_json_atomic
from codess.config import CC_PROJECTS, CURSOR_DATA, STORE_ROOT
from codess.evidence import build_evidence_inventory


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--store", type=Path, default=STORE_ROOT)
    parser.add_argument("--output", type=Path, help="write the report here instead of stdout")
    parser.add_argument("--cursor-db", type=Path, default=CURSOR_DATA / "globalStorage" / "state.vscdb")
    parser.add_argument("--claude-root", type=Path, default=CC_PROJECTS)
    parser.add_argument("--claude-max-files", type=int, default=200)
    parser.add_argument("--component-dir", type=Path)
    args = parser.parse_args()
    components = {}
    report = build_evidence_inventory(
        args.store, cursor_db=args.cursor_db, claude_root=args.claude_root,
        claude_max_files=args.claude_max_files, component_reports=components,
    )
    if args.component_dir:
        for name, component in components.items():
            write_json_atomic(args.component_dir / f"{name}.json", component)
    if args.output is None:
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    write_json_atomic(args.output, report)
    print(json.dumps({"output": str(args.output), "reviewed_stores": report["reviewed_stores"], "available": {key: value["available"] for key,value in report["wanted"].items()}}, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
