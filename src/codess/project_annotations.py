"""Refreshable, evidence-backed annotations for the Project catalog."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from codess.config import LARGE_EVENT_COUNT, LARGE_STORE_BYTES
from codess.project_catalog import (
    catalog_readiness,
    durable_project_root,
    load_catalog,
)
from codess.snapshot import SnapshotError, read_manifest, current_snapshot


ANNOTATION_REPORT_FORMAT = "codess.project-annotations/1"


def _read_json(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _current_snapshot(base: Path) -> tuple[str | None, Path | None]:
    try:
        resolved = current_snapshot(base)
    except SnapshotError:
        return None, None
    if resolved is None:
        return None, None
    snapshot, pointer = resolved
    snapshot_id = pointer.get("snapshot_id")
    return (snapshot_id if isinstance(snapshot_id, str) and snapshot_id else None), snapshot


def _snapshot_facts(snapshot: Path | None) -> dict[str, Any]:
    facts: dict[str, Any] = {
        "normalized_store_bytes": 0,
        "sessions": 0,
        "events": 0,
        "source_systems": {},
        "raw_mode": None,
        "snapshot_read_error": None,
    }
    if snapshot is None or not snapshot.is_dir():
        return facts
    try:
        manifest = read_manifest(snapshot)
    except SnapshotError as exc:
        facts["snapshot_read_error"] = str(exc)
        manifest = {}
    build_policy = manifest.get("build_policy")
    if isinstance(build_policy, dict):
        facts["raw_mode"] = build_policy.get("raw_mode")
    source_counts: Counter[str] = Counter()
    try:
        for store in sorted(snapshot.glob("*.db")):
            facts["normalized_store_bytes"] += store.stat().st_size
            conn = sqlite3.connect(
                store.resolve().as_uri() + "?mode=ro", uri=True
            )
            try:
                conn.execute("PRAGMA query_only = ON")
                facts["sessions"] += int(
                    conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
                )
                facts["events"] += int(
                    conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
                )
                columns = {
                    str(row[1])
                    for row in conn.execute("PRAGMA table_info(sessions)")
                }
                source_column = (
                    "source_system_id"
                    if "source_system_id" in columns else "source"
                )
                for source, count in conn.execute(
                    f"SELECT {source_column},COUNT(*) FROM sessions "
                    f"GROUP BY {source_column}"
                ):
                    source_counts[str(source or "unknown")] += int(count)
            finally:
                conn.close()
    except (OSError, sqlite3.Error) as exc:
        facts["snapshot_read_error"] = str(exc)
    facts["source_systems"] = dict(sorted(source_counts.items()))
    return facts


def _active_paths(entry: dict[str, Any]) -> list[str]:
    return sorted({
        str(item["path"])
        for item in entry.get("locations", [])
        if (
            isinstance(item, dict)
            and item.get("state") == "active"
            and item.get("path")
        )
    })


def build_project_annotations(
    registry: Path,
    *,
    baseline_selection: Path | None = None,
    reviewed_catalog: Path | None = None,
    large_event_count: int = LARGE_EVENT_COUNT,
    large_store_bytes: int = LARGE_STORE_BYTES,
) -> dict[str, Any]:
    """Build annotations from catalog, snapshot, and reviewed-set evidence."""
    if large_event_count <= 0 or large_store_bytes <= 0:
        raise ValueError("large thresholds must be positive")
    registry = registry.expanduser().resolve()
    catalog = load_catalog(registry)
    readiness = catalog_readiness(registry)
    ready_by_id = {
        str(item["project_id"]): item for item in readiness["projects"]
    }
    selection = _read_json(baseline_selection)
    reviewed = _read_json(reviewed_catalog)
    core_paths = {
        str(Path(str(item["path"])).expanduser().resolve())
        for item in selection.get("projects", [])
        if isinstance(item, dict) and item.get("path")
    }
    core_ids = {
        str(item["project_id"])
        for item in reviewed.get("projects", [])
        if isinstance(item, dict) and item.get("project_id")
    }

    projects: list[dict[str, Any]] = []
    label_counts: Counter[str] = Counter()
    for entry in sorted(
        catalog.get("projects", []),
        key=lambda item: (
            str(item.get("logical_name") or "").casefold(),
            str(item.get("project_id") or ""),
        ),
    ):
        if not isinstance(entry, dict) or not entry.get("project_id"):
            continue
        project_id = str(entry["project_id"])
        status = ready_by_id.get(project_id, {})
        paths = _active_paths(entry)
        base = durable_project_root(registry, project_id)
        snapshot_id, snapshot = _current_snapshot(base)
        facts = _snapshot_facts(snapshot)
        annotations: list[dict[str, Any]] = []

        def add(label: str, reason: str) -> None:
            annotations.append({"label": label, "reason": reason})
            label_counts[label] += 1

        eligible = bool(status.get("selection_eligible"))
        query_status = str(status.get("query_status") or "unknown")
        selection_state = status.get("selection_state")
        if eligible:
            add(
                "included",
                "eligible for broad catalog selection",
            )
        else:
            add(
                "not_selected",
                f"catalog selection state is {selection_state or query_status}",
            )
        if (
            project_id in core_ids
            or any(
                str(Path(path).expanduser().resolve()) in core_paths
                for path in paths
            )
        ):
            add(
                "core",
                "member of the reviewed compatibility baseline set",
            )
        if query_status == "query_ready":
            add("query_ready", "current snapshot is package-compatible")
        elif eligible:
            add(
                "incomplete",
                f"eligible Project is not query-ready: {query_status}",
            )
        if (
            facts["events"] >= large_event_count
            or facts["normalized_store_bytes"] >= large_store_bytes
        ):
            add(
                "large",
                (
                    f"{facts['events']} Events and "
                    f"{facts['normalized_store_bytes']} normalized-store bytes"
                ),
            )
        if facts["raw_mode"] in {"none", "reference"}:
            add(
                "limited",
                f"raw evidence mode is {facts['raw_mode']}",
            )
        suspect_reasons = []
        if selection_state == "needs_review":
            suspect_reasons.append("catalog state needs_review")
        if status.get("active_location_count", 0) != status.get(
            "existing_active_location_count", 0
        ):
            suspect_reasons.append("one or more active locations is missing")
        if query_status == "snapshot_fail":
            suspect_reasons.append(
                str(status.get("detail") or "snapshot validation failed")
            )
        if facts["snapshot_read_error"]:
            suspect_reasons.append(
                "current snapshot could not be fully inspected"
            )
        if suspect_reasons:
            add("suspect", "; ".join(suspect_reasons))
        if len(facts["source_systems"]) > 1:
            add(
                "multi_vendor",
                "current snapshot contains more than one source system",
            )

        disposition = entry.get("catalog_disposition")
        projects.append({
            "project_id": project_id,
            "name": entry.get("logical_name"),
            "path": paths[0] if paths else None,
            "active_paths": paths,
            "selection_state": selection_state,
            "query_status": query_status,
            "source_refresh_status": status.get("source_refresh_status"),
            "snapshot_id": snapshot_id,
            "sessions": facts["sessions"],
            "events": facts["events"],
            "normalized_store_bytes": facts["normalized_store_bytes"],
            "source_systems": facts["source_systems"],
            "workspace_bindings": len(entry.get("workspace_bindings", [])),
            "raw_mode": facts["raw_mode"],
            "labels": [item["label"] for item in annotations],
            "annotations": annotations,
            "note": (
                disposition.get("note")
                if isinstance(disposition, dict) else None
            ),
            "related_project_id": (
                disposition.get("related_project_id")
                if isinstance(disposition, dict) else None
            ),
        })

    definitions = {
        "included": "eligible for broad catalog selection; not a freshness claim",
        "core": "member of the reviewed compatibility baseline set; not a business-priority claim",
        "query_ready": "current snapshot is readable under the current package",
        "incomplete": "included Project lacks a compatible current snapshot",
        "large": (
            f"at least {large_event_count} Events or "
            f"{large_store_bytes} normalized-store bytes"
        ),
        "limited": "current raw-evidence mode is none or reference",
        "suspect": "direct review/inconsistency evidence, not merely a known limitation",
        "multi_vendor": "current snapshot contains multiple source systems",
        "not_selected": "excluded from broad catalog selection",
    }
    return {
        "format": ANNOTATION_REPORT_FORMAT,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "registry": str(registry),
        "definitions": definitions,
        "thresholds": {
            "large_event_count": large_event_count,
            "large_store_bytes": large_store_bytes,
        },
        "summary": {
            "projects": len(projects),
            "labels": {
                label: label_counts.get(label, 0)
                for label in definitions
            },
        },
        "projects": projects,
    }
