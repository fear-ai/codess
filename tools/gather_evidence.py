#!/usr/bin/env python3
"""Build a structure-only inventory for currently wanted compatibility evidence."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from codess.baseline_validation import write_json_atomic
from codess.evidence import build_evidence_inventory


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--store", type=Path, default=Path.home() / ".codess")
    parser.add_argument("--output", type=Path, default=ROOT / "catalog/evidence-inventory.json")
    parser.add_argument("--cursor-db", type=Path, default=Path.home() / "Library/Application Support/Cursor/User/globalStorage/state.vscdb")
    parser.add_argument("--claude-root", type=Path, default=Path.home() / ".claude/projects")
    parser.add_argument("--claude-max-files", type=int, default=200)
    parser.add_argument("--component-dir", type=Path)
    args = parser.parse_args()
    components = {}
    report = build_evidence_inventory(
        args.store_root, cursor_db=args.cursor_db, claude_root=args.claude_root,
        claude_max_files=args.claude_max_files, component_reports=components,
    )
    if args.component_dir:
        for name, component in components.items():
            write_json_atomic(args.component_dir / f"{name}.json", component)
    write_json_atomic(args.output, report)
    print(json.dumps({"output": str(args.output), "reviewed_stores": report["reviewed_stores"], "available": {key: value["available"] for key,value in report["wanted"].items()}}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
