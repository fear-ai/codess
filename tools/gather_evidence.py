#!/usr/bin/env python3
"""Build a structure-only inventory for currently wanted compatibility evidence."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from codess.baseline_validation import write_json_atomic  # noqa: E402
from codess.codex_parent_audit import audit_parentage  # noqa: E402
from codess.cursor_feature_audit import audit_cursor_features  # noqa: E402
from codess.project_catalog import load_catalog  # noqa: E402
from codess.snapshot import current_store_paths  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path, default=Path.home() / ".codess")
    parser.add_argument("--output", type=Path, default=ROOT / "catalog/evidence-inventory.json")
    parser.add_argument("--cursor-db", type=Path, default=Path.home() / "Library/Application Support/Cursor/User/globalStorage/state.vscdb")
    args = parser.parse_args()
    catalog = load_catalog(args.registry)
    artifact_sources: dict[tuple[str, str], set[str]] = defaultdict(set)
    model_settings = defaultdict(int)
    lifecycle = defaultdict(int)
    missing_times = 0
    stores = 0
    for project in catalog.get("projects", []):
        active = next((item.get("path") for item in project.get("locations", []) if item.get("state") == "active"), None)
        if not active:
            continue
        for db in current_store_paths(Path(active)):
            stores += 1
            conn = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
            try:
                for row in conn.execute("""
                    SELECT COALESCE(a.relative_path,a.uri,a.observed_absolute_path) locator,
                           s.source
                    FROM artifacts a JOIN event_artifacts ea ON ea.artifact_id=a.id
                    JOIN events e ON e.id=ea.event_id JOIN sessions s ON s.id=e.session_id
                    WHERE COALESCE(a.relative_path,a.uri,a.observed_absolute_path) IS NOT NULL
                """):
                    artifact_sources[(project["project_id"], row["locator"])].add(row["source"])
                for row in conn.execute("SELECT reasoning_effort,speed_tier,service_tier FROM model_configurations"):
                    for field in ("reasoning_effort", "speed_tier", "service_tier"):
                        if row[field] is not None:
                            model_settings[field] += 1
                for row in conn.execute("SELECT subtype,COUNT(*) n FROM events WHERE subtype IN ('turn_aborted','context_compaction') GROUP BY subtype"):
                    lifecycle[row["subtype"]] += row["n"]
                missing_times += conn.execute("SELECT COUNT(*) FROM events WHERE event_at IS NULL").fetchone()[0]
            finally:
                conn.close()
    shared = [
        {"project_id": project_id, "locator": locator, "sources": sorted(sources)}
        for (project_id, locator), sources in artifact_sources.items() if len(sources) > 1
    ]
    codex = audit_parentage([("active", Path.home()/".codex/sessions"), ("archive", Path.home()/".codex/archived_sessions")])
    cursor = audit_cursor_features(args.cursor_db, catalog)
    report = {
        "inventory_format": "codess.evidence-inventory/1",
        "privacy_boundary": "structural metadata and aggregate counts only; conversation bodies not retained",
        "reviewed_stores": stores,
        "wanted": {
            "cross_vendor_shared_artifact": {"relevance": "high", "available": bool(shared), "matches": shared[:100]},
            "inference_effort_speed_service": {"relevance": "medium", "available": bool(model_settings), "counts": dict(model_settings)},
            "codex_parent_identifier": {"relevance": "medium", "available": codex["support_status"] == "supported", "candidate_fields": codex["parent_candidate_fields"]},
            "real_lifecycle_and_missing_time": {"relevance": "low-to-medium", "available": bool(lifecycle or missing_times), "lifecycle": dict(lifecycle), "events_missing_time": missing_times},
            "cursor_tool_and_model_shapes": {"relevance": "maintenance", "available": True, "evidence": cursor["evidence"]},
        },
        "recommendation": "expand the corpus only for a high-relevance unavailable shape; otherwise maintain audits against approved active workspaces",
    }
    write_json_atomic(args.output, report)
    print(json.dumps({"output": str(args.output), "reviewed_stores": stores, "available": {key: value["available"] for key,value in report["wanted"].items()}}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
