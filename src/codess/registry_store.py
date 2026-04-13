"""Central ``ingested_projects.json``: merged updates from scan, ingest, query, (future) walk.

Each project entry is keyed by resolved ``path``. Top-level keys may include:
``sources`` (ingest store counts), ``scan`` (last index-led metrics), ``query``
(last query snapshot), ``walk`` (future), and timestamps ``last_ingestion``,
``last_scan``, ``last_query``.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from codess.config import get_stats_path


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_registry_data(registry_root: Path) -> dict[str, Any]:
    """Load registry JSON or return an empty shell (for first write)."""
    stats_path = get_stats_path(registry_root)
    if not stats_path.exists():
        return {"projects": [], "updated": _now_iso()}
    try:
        data = json.loads(stats_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"projects": [], "updated": _now_iso()}
    if "projects" not in data:
        data["projects"] = []
    return data


def save_registry_data(registry_root: Path, data: dict[str, Any]) -> None:
    stats_path = get_stats_path(registry_root)
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    data["updated"] = _now_iso()
    stats_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def update_project_entry(
    registry_root: Path,
    path_resolved: str,
    mutator: Callable[[dict[str, Any]], None],
) -> None:
    """Load registry, find or create entry for ``path_resolved``, run ``mutator`` (in-place)."""
    data = load_registry_data(registry_root)
    by_path: dict[str, dict[str, Any]] = {}
    for ent in data.get("projects") or []:
        p = ent.get("path")
        if isinstance(p, str) and p:
            by_path[p] = dict(ent)
    entry = dict(by_path.get(path_resolved, {"path": path_resolved}))
    entry["path"] = path_resolved
    mutator(entry)
    by_path[path_resolved] = entry
    data["projects"] = list(by_path.values())
    save_registry_data(registry_root, data)


def merge_ingest_sources(entry: dict[str, Any], source_stats: dict[str, Any]) -> None:
    entry["last_ingestion"] = _now_iso()
    src = dict(entry.get("sources") or {})
    src.update(source_stats)
    entry["sources"] = src


def merge_scan_rows(entry: dict[str, Any], scan_rows: list[dict[str, Any]]) -> None:
    entry["last_scan"] = _now_iso()
    by_vendor: dict[str, Any] = {}
    for r in scan_rows:
        v = str(r.get("vendor", ""))
        by_vendor[v] = {
            "sess": r.get("sess"),
            "mb": r.get("mb"),
            "span_weeks": r.get("span_weeks"),
        }
    entry["scan"] = {"by_vendor": by_vendor}


def merge_query_stats(entry: dict[str, Any], sessions: int, events: int) -> None:
    entry["last_query"] = _now_iso()
    entry["query"] = {"sessions": int(sessions), "events": int(events)}


def upsert_walk_seen(registry_root: Path, project_paths: Iterable[str]) -> None:
    """Record that walk/discovery saw these project paths (for future ``walk_dirs`` wiring)."""
    for p in project_paths:
        if not p:
            continue
        ts = _now_iso()

        def mut(e: dict[str, Any], t: str = ts) -> None:
            w = dict(e.get("walk") or {})
            w["last_seen"] = t
            e["walk"] = w

        update_project_entry(registry_root, p, mut)
