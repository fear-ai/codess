"""Reusable structural evidence summaries and current-catalog inventory.

**Reads core tables directly** to inventory what a store holds across
vendors, which is a measurement of the stored evidence rather than a
selection over it; the typed request contract expresses selections. Reading
core tables directly is deliberate and recorded here for that reason.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from codess.codex_parent_audit import audit_parentage
from codess.config import CC_PROJECTS
from codess.cursor_feature_audit import audit_cursor_features
from codess.project_catalog import load_catalog
from codess.snapshot import current_stores
from codess.store import connect
from codess.vendor_audits.claude_features import audit_claude_features
from codess.vendor_audits.codex_features import audit_codex_features

_TOTAL_COUNT_QUERIES = {
    "tool_invocations": "SELECT COUNT(*) FROM tool_invocations",
    "tool_results": "SELECT COUNT(*) FROM tool_results",
    "model_params": "SELECT COUNT(*) FROM model_params",
    "correlation_assertions": "SELECT COUNT(*) FROM correlation_assertions",
}


def summarize_store_evidence(paths: Iterable[Path]) -> dict[str, Any]:
    artifact_sources: dict[str, set[str]] = defaultdict(set)
    totals = {
        "tool_invocations": 0,
        "tool_results": 0,
        "model_params": 0,
        "events_missing_time": 0,
        "correlation_assertions": 0,
    }
    settings = {"reasoning_effort": 0, "speed_tier": 0, "service_tier": 0}
    lifecycle: dict[str, int] = defaultdict(int)
    for path in paths:
        if not path.exists():
            continue
        conn = connect(path, read_only=True)
        try:
            for key, query in _TOTAL_COUNT_QUERIES.items():
                totals[key] += conn.execute(query).fetchone()[0]
            totals["events_missing_time"] += conn.execute(
                "SELECT COUNT(*) FROM events WHERE event_at IS NULL"
            ).fetchone()[0]
            for row in conn.execute(
                "SELECT reasoning_effort,speed_tier,service_tier "
                "FROM model_params"
            ):
                for key in settings:
                    settings[key] += int(row[key] is not None)
            for row in conn.execute(
                "SELECT subtype,COUNT(*) n FROM events "
                "WHERE subtype IN ('turn_aborted','context_compaction') "
                "GROUP BY subtype"
            ):
                lifecycle[row["subtype"]] += row["n"]
            for row in conn.execute(
                """
                SELECT COALESCE(a.relative_path,a.uri,a.observed_absolute_path) locator,
                       s.source
                FROM artifacts a JOIN event_artifacts ea ON ea.artifact_id=a.id
                JOIN events e ON e.id=ea.event_id
                JOIN sessions s ON s.id=e.session_id
                WHERE COALESCE(a.relative_path,a.uri,a.observed_absolute_path) IS NOT NULL
                """
            ):
                artifact_sources[row["locator"]].add(row["source"])
        finally:
            conn.close()
    shared = sorted(
        locator for locator, sources in artifact_sources.items() if len(sources) > 1
    )
    return {
        **totals,
        "model_setting_counts": settings,
        "lifecycle_counts": dict(lifecycle),
        "cross_vendor_artifact_count": len(shared),
        "cross_vendor_artifact_examples": shared[:20],
    }


def build_evidence_inventory(
    registry: Path,
    *,
    cursor_db: Path,
    codex_roots: list[tuple[str, Path]] | None = None,
    claude_root: Path = CC_PROJECTS,
    claude_max_files: int = 200,
    component_reports: dict[str, Any] | None = None,
) -> dict[str, Any]:
    catalog = load_catalog(registry)
    project_summaries: list[tuple[str, dict[str, Any]]] = []
    stores = 0
    for project in catalog.get("projects", []):
        active = next(
            (
                item.get("path")
                for item in project.get("locations", [])
                if item.get("state") == "active"
            ),
            None,
        )
        if not active:
            continue
        paths = current_stores(Path(active))
        stores += len(paths)
        project_summaries.append(
            (project["project_id"], summarize_store_evidence(paths))
        )
    shared = []
    settings: dict[str, int] = defaultdict(int)
    lifecycle: dict[str, int] = defaultdict(int)
    missing_times = 0
    for project_id, summary in project_summaries:
        missing_times += summary["events_missing_time"]
        for key, value in summary["model_setting_counts"].items():
            settings[key] += value
        for key, value in summary["lifecycle_counts"].items():
            lifecycle[key] += value
        for locator in summary["cross_vendor_artifact_examples"]:
            shared.append({"project_id": project_id, "locator": locator})
    roots = codex_roots or [
        ("active", Path.home() / ".codex/sessions"),
        ("archive", Path.home() / ".codex/archived_sessions"),
    ]
    codex = audit_parentage(roots)
    codex_features = audit_codex_features(roots)
    cursor = audit_cursor_features(cursor_db, catalog)
    claude = audit_claude_features(claude_root, max_files=claude_max_files)
    if component_reports is not None:
        component_reports.update({
            "claude-feature-audit": claude,
            "codex-parent-audit": codex,
            "codex-feature-audit": codex_features,
            "cursor-feature-audit": cursor,
        })
    return {
        "inventory_format": "codess.evidence-inventory/1",
        "privacy_boundary": (
            "structural metadata and aggregate counts only; "
            "conversation bodies not retained"
        ),
        "reviewed_stores": stores,
        "wanted": {
            "cross_vendor_shared_artifact": {
                "relevance": "high", "available": bool(shared),
                "matches": shared[:100],
            },
            "inference_effort_speed_service": {
                "relevance": "medium",
                "available": any(settings.values()) or bool(
                    codex_features["model_settings"]
                ),
                "normalized_counts": dict(settings),
                "claude_source_evidence": claude["model_settings"],
                "claude_setting_provenance": claude["setting_provenance"],
                "codex_source_evidence": codex_features["model_settings"],
                "codex_setting_provenance": codex_features["setting_provenance"],
            },
            "codex_parent_identifier": {
                "relevance": "medium",
                "available": codex["support_status"] == "supported",
                "candidate_fields": codex["parent_candidate_fields"],
            },
            "real_lifecycle_and_missing_time": {
                "relevance": "low-to-medium",
                "available": bool(lifecycle or missing_times),
                "lifecycle": dict(lifecycle),
                "events_missing_time": missing_times,
            },
            "cursor_tool_and_model_shapes": {
                "relevance": "maintenance", "available": True,
                "evidence": cursor["evidence"],
            },
            "claude_source_shapes": {
                "relevance": "maintenance",
                "available": claude["files_reviewed"] > 0,
                "evidence": {
                    "files_reviewed": claude["files_reviewed"],
                    "record_types": claude["record_types"],
                    "content_block_types": claude["content_block_types"],
                    "parent_links": claude["parent_links"],
                    "sidechain_records": claude["sidechain_records"],
                    "versions": claude["versions"],
                },
            },
        },
        "recommendation": (
            "expand the corpus only for a high-relevance unavailable shape; "
            "otherwise maintain audits against approved active workspaces"
        ),
    }
