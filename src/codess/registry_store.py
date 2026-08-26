"""Central ``projects_state.json``: merged updates from scan, ingest, and query.

Each project entry is keyed by resolved ``path``. Top-level keys may include:
``sources`` (ingest store counts), ``scan`` (last index-led metrics), ``query``
(last query snapshot), and timestamps ``last_ingestion``,
``last_scan``, ``last_query``.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from codess.config import get_project_state_path
from codess.timeval import now_iso
from codess.wallclock import system_clock


def load_registry_data(store_root: Path) -> dict[str, Any]:
    """Load registry JSON or return an empty shell (for first write)."""
    stats_path = get_project_state_path(store_root)
    if not stats_path.exists():
        return {"projects": [], "updated": now_iso(system_clock)}
    try:
        data = json.loads(stats_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"projects": [], "updated": now_iso(system_clock)}
    if "projects" not in data:
        data["projects"] = []
    return data


def save_registry_data(store_root: Path, data: dict[str, Any]) -> None:
    stats_path = get_project_state_path(store_root)
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    data["updated"] = now_iso(system_clock)
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


def never_ingested_entries(store_root: Path) -> list[dict[str, Any]]:
    """Registry entries scanned at least once and never ingested.

    Scan records every Project it observes; ingest publishes only what it is
    told to read. The Project catalog holds what ingest published, so a Project
    scanned and never ingested is absent from the catalog entirely -- and any
    enumeration drawn from the catalog inherits the omission without being able
    to detect it. That is not a hypothetical: this repository's own Sessions
    were scanned and left unread for three days, and a full-corpus rebuild
    driven from the catalog could not see them.

    Only a live path is reported. A vanished path is `stale_entries`'s
    condition, and reporting it here would name a Project that cannot be
    ingested anyway.
    """
    entries = load_registry_data(store_root).get("projects") or []
    pending = []
    for entry in entries:
        if entry.get("last_ingestion"):
            continue
        path = entry.get("path")
        if isinstance(path, str) and path and Path(path).exists():
            pending.append(entry)
    return pending


PROJECT_LIFECYCLE_STATES = (
    "scanned", "ingested", "copy", "moved", "removed", "purged",
    "retired", "worktree",
)
"""What has happened to a Project, derived rather than stored.

Derived because each underlying fact already has exactly one writer -- scan
writes `last_scan`, ingest writes `last_ingestion`, the filesystem answers
whether the path exists, and the catalog carries a reviewed disposition. A
stored state would need a fifth writer and could disagree with all four.

| State | Meaning |
|---|---|
| `scanned` | Observed by scan and never ingested |
| `ingested` | A store was published for it |
| `copy` | Another live path carries the same identity; this one is a duplicate of it |
| `moved` | This location was retired and the Project has a live one elsewhere |
| `removed` | The path is gone and no other location holds the Project |
| `purged` | The path exists and the vendor no longer holds Sources the store recorded |
| `retired` | The operator excluded it; the store is kept as evidence |
| `worktree` | A linked git worktree of another Project, not a separate one |

`retired` and `worktree` were one value named `superseded`, which conflated a
duplicate the operator retired with a live sibling of a repository. They are
different conditions with different actions -- one is answered, the other is
ordinary -- so they are named separately.

`purged` is the condition no other state covers: the Project is present and
being worked in, and the *vendor* deleted its own records. It is the state that
must never be acted on automatically, because the store is the only remaining
copy.
"""


def _is_retired(entry: dict[str, Any]) -> bool:
    """Whether a catalog entry has been retired in favour of another."""
    return (entry.get("catalog_disposition") or {}).get("state") == "excluded"


def project_lifecycle(store_root: Path, catalog: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Every Project this machine has known, with what happened to it and when.

    Reconciles the two records that describe a Project without introducing a
    third: `projects_state.json` (what scan saw) and `projects.json` (what
    ingest published). They disagree in ways nothing reported -- a Project
    scanned and never ingested is absent from the catalog entirely, and a
    catalogued path whose directory has been removed stays indefinitely.

    `state` is computed from the facts rather than recorded:

    | State | Condition |
    |---|---|
    | `worktree` | The catalog records a linked worktree relation |
    | `retired` | The operator excluded this Project |
    | `moved` | This location was retired and another is live |
    | `copy` | A live sibling location holds the same identity |
    | `removed` | The path is gone and no sibling holds the Project |
    | `purged` | The path exists and recorded vendor Sources do not |
    | `ingested` | A `last_ingestion` is recorded |
    | `scanned` | Observed by scan and never ingested |

    Checked in that order, so the most specific answer wins: a retired location
    of a moved Project is `moved`, not `removed`, because the work was not lost.

    Each row carries `state_since` and `previous_state` where the catalog
    records a transition, so "excluded on 2026-08-20, previously active" is
    distinguishable from "excluded, always was". An initial state has no
    `previous_state`.

    Ordered by last activity, most recent first, so a reader sees current work
    without sorting.
    """
    entries = load_registry_data(store_root).get("projects") or []
    catalog_entries = (catalog or {}).get("projects") or []
    by_path: dict[str, dict[str, Any]] = {}
    retired_paths: set[str] = set()
    # A Project with several live locations is one identity in two places -- a
    # copy or a restore beside the original, not two Projects. The first live
    # location is the original by observation order; the rest are copies.
    live_siblings: dict[str, str] = {}
    for entry in catalog_entries:
        entry_live: list[str] = []
        for location in entry.get("locations") or []:
            path = location.get("path")
            if not isinstance(path, str) or not path:
                continue
            # A live entry outranks a retired one for the same path. Both can
            # exist -- a retired duplicate beside the current Project -- and
            # taking whichever was read first reported the archived entry's
            # disposition as the live Project's state.
            held = by_path.get(path)
            if held is None or _is_retired(held):
                by_path[path] = entry
            if location.get("state") == "retired" or location.get("path_obsolete"):
                retired_paths.add(path)
            elif Path(path).exists():
                entry_live.append(path)
        for other in entry_live[1:]:
            live_siblings[other] = entry_live[0]

    rows: list[dict[str, Any]] = []
    for entry in entries:
        path = entry.get("path")
        if not isinstance(path, str) or not path:
            continue
        catalogued = by_path.get(path) or {}
        disposition = (catalogued.get("catalog_disposition") or {}).get("state")
        exists = Path(path).exists()
        if disposition == "worktree":
            state = "worktree"
        elif disposition == "excluded":
            state = "retired"
        elif path in retired_paths:
            # A location the operator retired -- typically a Project that moved,
            # where the new path is a live location on the same entry. Reported
            # as `moved` rather than `removed`, because the work was not lost
            # and the row exists to say where it went.
            state = "moved"
        elif path in live_siblings:
            state = "copy"
        elif not exists:
            state = "removed"
        elif entry.get("last_ingestion"):
            state = "ingested"
        else:
            state = "scanned"
        # A recorded transition distinguishes "excluded on 2026-08-20, was
        # active" from "excluded, always was". Only the catalog records one, so
        # a state with no disposition has no transition and that is correct
        # rather than missing.
        transition = catalogued.get("catalog_disposition") or {}
        rows.append({
            "path": path,
            "state": state,
            "state_since": transition.get("updated_at"),
            "previous_state": transition.get("previous_state"),
            "copy_of": live_siblings.get(path),
            "project_id": catalogued.get("project_id"),
            "last_scan": entry.get("last_scan"),
            "last_ingestion": entry.get("last_ingestion"),
            "last_query": entry.get("last_query"),
            "disposition": disposition,
            "path_exists": exists,
        })
    rows.sort(
        key=lambda row: (row["last_ingestion"] or row["last_scan"] or ""),
        reverse=True,
    )
    return rows


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
    entry["last_ingestion"] = now_iso(system_clock)
    src = dict(entry.get("sources") or {})
    src.update(source_stats)
    entry["sources"] = src


def merge_scan_rows(entry: dict[str, Any], scan_rows: list[dict[str, Any]]) -> None:
    entry["last_scan"] = now_iso(system_clock)
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
    entry["last_query"] = now_iso(system_clock)
    entry["query"] = {"sessions": int(sessions), "events": int(events)}
