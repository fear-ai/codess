#!/usr/bin/env python3
"""Verify durable evidence, retire one location, and optionally bind another."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from codess.baseline_validation import validate_project, write_json_atomic  # noqa: E402
from codess.project_catalog import (  # noqa: E402
    durable_project_root,
    ensure_project_binding,
    register_relocation,
)
from codess.snapshot import current_store_paths  # noqa: E402


def _current(project: Path) -> tuple[dict, Path, dict]:
    pointer = json.loads((project / ".codess/current.json").read_text(encoding="utf-8"))
    path = Path(pointer["path"])
    snapshot = path if path.is_absolute() else project / ".codess" / path
    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    return pointer, snapshot, manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--new-location", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    project = args.project.expanduser().resolve()
    registry = args.registry.expanduser().resolve()
    try:
        binding = ensure_project_binding(registry, project)
        pointer, snapshot, manifest = _current(project)
        durable = durable_project_root(registry, binding["project_id"])
        if snapshot.parent.parent != durable:
            raise RuntimeError("current snapshot is not in the durable project catalog")
        report = validate_project(project, raw_store_root=registry / "raw")
        if report["status"] != "accepted":
            raise RuntimeError(
                "retirement requires a fully reproducible accepted baseline: "
                + "; ".join(report.get("errors", []) + report.get("limitations", []))
            )
        raw_records = []
        with (snapshot / "raw-manifest.jsonl").open(encoding="utf-8") as stream:
            for line in stream:
                record = json.loads(line)
                if record.get("record_type") != "header":
                    raw_records.append(record)
        if not raw_records or any(item.get("availability") != "captured" for item in raw_records):
            raise RuntimeError("retirement requires every raw source revision to be captured")
        relocation = register_relocation(
            registry, binding["project_id"], project, args.new_location
        )
        new_root = args.new_location.expanduser().resolve()
        local_pointer = new_root / ".codess/current.json"
        write_json_atomic(local_pointer, pointer)
        if not current_store_paths(new_root):
            raise RuntimeError("replacement location cannot read the durable snapshot")
        receipt = {
            "receipt_format": "codess.project-retirement/1",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "project_id": binding["project_id"],
            "snapshot_id": manifest["snapshot_id"],
            "semantic_digest": report["semantic_digest"],
            "raw_records": len(raw_records),
            **relocation,
        }
        receipt_name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ.json")
        receipt_path = durable / "retirements" / receipt_name
        write_json_atomic(receipt_path, receipt)
        if args.report:
            write_json_atomic(args.report, receipt)
        print(json.dumps(receipt, sort_keys=True))
        return 0
    except (OSError, KeyError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"codess: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
