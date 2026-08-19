#!/usr/bin/env python3
"""Review or quarantine missing temporary projects from the stable catalog."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from codess.baseline_validation import write_json_atomic
from codess.project_catalog import durable_project_root, load_catalog

TEMP_PREFIXES = ("/private/var/folders/", "/var/folders/")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--store", dest="store_root", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    registry = args.store_root.expanduser().resolve()
    catalog = load_catalog(registry)
    removable = []
    retained = []
    for project in catalog.get("projects", []):
        paths = [str(item.get("path") or "") for item in project.get("locations", [])]
        temporary = bool(paths) and all(path.startswith(TEMP_PREFIXES) for path in paths)
        missing = bool(paths) and all(not Path(path).exists() for path in paths)
        if temporary and missing:
            removable.append(project)
        else:
            retained.append(project)
    result = {
        "catalog_format": "codess.project-catalog-prune/1",
        "apply": args.apply,
        "candidates": [
            {"project_id": item["project_id"], "paths": [loc["path"] for loc in item["locations"]]}
            for item in removable
        ],
    }
    if args.apply and removable:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        quarantine = registry / "quarantine" / f"missing-temp-projects-{stamp}"
        quarantine.mkdir(parents=True, exist_ok=False)
        for project in removable:
            source = durable_project_root(registry, project["project_id"])
            if source.exists():
                shutil.move(str(source), quarantine / source.name)
        catalog["projects"] = retained
        catalog["updated_at"] = datetime.now(UTC).isoformat()
        write_json_atomic(registry / "projects.json", catalog)
        write_json_atomic(quarantine / "pruned-projects.json", result)
        result["quarantine"] = str(quarantine)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
