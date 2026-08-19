"""Central ``ingested_projects.json``: merged updates from scan, ingest, and query.

Each project entry is keyed by resolved ``path``. Top-level keys may include:
``sources`` (ingest store counts), ``scan`` (last index-led metrics), ``query``
(last query snapshot), and timestamps ``last_ingestion``,
``last_scan``, ``last_query``.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from codess.config import get_stats_path


def load_registry_data(store_root: Path) -> dict[str, Any]:
    """Load registry JSON or return an empty shell (for first write)."""
    stats_path = get_stats_path(store_root)
    if not stats_path.exists():
        return {"projects": [], "updated": datetime.now(UTC).isoformat()}
    try:
        data = json.loads(stats_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"projects": [], "updated": datetime.now(UTC).isoformat()}
    if "projects" not in data:
        data["projects"] = []
    return data


def save_registry_data(store_root: Path, data: dict[str, Any]) -> None:
    stats_path = get_stats_path(store_root)
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    data["updated"] = datetime.now(UTC).isoformat()
    stats_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def update_project_entry(
    store_root: Path,
    path_resolved: str,
    mutator: Callable[[dict[str, Any]], None],
) -> None:
    """Load registry, find or create entry for ``path_resolved``, run ``mutator`` (in-place)."""
    data = load_registry_data(store_root)
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
    save_registry_data(store_root, data)


REPORTED_PATH_SAMPLE = 20
"""How many removable paths a prune report lists before counting the rest."""


def stale_entries(store_root: Path) -> list[dict[str, Any]]:
    """Registry entries whose Project path no longer exists.

    The registry gains an entry for every Project ever scanned and drops none,
    so a test run that scans a temporary directory leaves a permanent record:
    an observed registry held 1,455 entries of which 1,424 were vanished
    temporary paths and 31 were live.

    A missing path is the only condition reported. It is deliberately not
    "old" or "unused": a Project on removable media or an unmounted volume is
    absent without being obsolete, which is why this reports candidates and
    `prune_stale_entries` requires an explicit call rather than running on
    every write.
    """
    entries = load_registry_data(store_root).get("projects") or []
    stale = []
    for entry in entries:
        path = entry.get("path")
        if isinstance(path, str) and path and not Path(path).exists():
            stale.append(entry)
    return stale


def prune_stale_entries(
    store_root: Path, *, dry_run: bool = False,
) -> dict[str, Any]:
    """Remove entries whose Project path no longer exists.

    Returns what was removed and what remains, so a caller reports the outcome
    rather than the intent. `dry_run` reports the same figures without
    writing, which is what makes this safe to run before deciding.
    """
    data = load_registry_data(store_root)
    entries = data.get("projects") or []
    removable = {
        entry.get("path") for entry in entries
        if isinstance(entry.get("path"), str)
        and entry["path"]
        and not Path(entry["path"]).exists()
    }
    retained = [e for e in entries if e.get("path") not in removable]
    paths = sorted(p for p in removable if p)
    result = {
        "examined": len(entries),
        "removed": len(entries) - len(retained),
        "retained": len(retained),
        # Bounded: an accumulated registry can hold over a thousand stale
        # entries, and a caller needs the count plus a sample to recognize
        # what it is looking at, not every path on stdout.
        "removed_paths": paths[:REPORTED_PATH_SAMPLE],
        "removed_paths_truncated": max(0, len(paths) - REPORTED_PATH_SAMPLE),
        "dry_run": dry_run,
    }
    if not dry_run and result["removed"]:
        data["projects"] = retained
        save_registry_data(store_root, data)
    return result


def merge_ingest_sources(entry: dict[str, Any], source_stats: dict[str, Any]) -> None:
    entry["last_ingestion"] = datetime.now(UTC).isoformat()
    src = dict(entry.get("sources") or {})
    src.update(source_stats)
    entry["sources"] = src


def merge_scan_rows(entry: dict[str, Any], scan_rows: list[dict[str, Any]]) -> None:
    entry["last_scan"] = datetime.now(UTC).isoformat()
    by_vendor: dict[str, Any] = {}
    for r in scan_rows:
        v = str(r.get("vendor", ""))
        by_vendor[v] = {
            "sess": r.get("sess"),
            "mb": r.get("mb"),
            "span_weeks": r.get("span_weeks"),
        }
    entry["scan"] = {"by_vendor": by_vendor}


def _is_legacy_global_entry(entry: dict[str, Any]) -> bool:
    path = entry.get("path")
    return (
        isinstance(path, str)
        and path.endswith("/(global)")
        and not entry.get("sources")
        and not entry.get("query")
        and set((entry.get("scan") or {}).get("by_vendor") or {}) <= {"Cursor"}
    )


def prune_legacy_cursor_global_entries(store_root: Path) -> int:
    """Remove scan-only pseudo-projects produced by the former global-row bug."""
    data = load_registry_data(store_root)
    projects = list(data.get("projects") or [])
    retained = [entry for entry in projects if not _is_legacy_global_entry(entry)]
    removed = len(projects) - len(retained)
    if removed:
        data["projects"] = retained
        save_registry_data(store_root, data)
    return removed


def merge_query_stats(entry: dict[str, Any], sessions: int, events: int) -> None:
    entry["last_query"] = datetime.now(UTC).isoformat()
    entry["query"] = {"sessions": int(sessions), "events": int(events)}
