"""Dated storage observations for CoSchema stores, snapshots, and Cursor.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from codess.config import (
    LARGE_RAW_OBJECT_BYTES, MAX_CODESS_DB_BYTES, MAX_CURSOR_DB_BYTES,
    RAW_MANIFEST_FILE,
)
from codess.fileio import open_readonly, write_json_atomic
from codess.token_usage import collect_token_usage
from codess.resources import allocated_bytes, file_usage, storage_usage, tree_usage
from codess.store import table_counts, table_names

REPORT_FORMAT = "codess.storage-observation/1"

REPORTED_TABLES = (
    "projects", "sources", "sessions", "interactions", "model_turns", "events",
    "source_records", "content_objects", "tool_invocations", "tool_results",
    "artifacts",
)
"""The content tables this report counts.

A deliberate subset: the report describes what an operator's storage holds,
so it names the entities they reason about rather than every table. The
counting itself is `store.table_counts`, which reads the store's own catalog
-- this list selects, it does not restate the schema."""



def inspect_sqlite(path: Path) -> dict[str, Any]:
    """Inspect allocation and CoSchema content skew without changing the DB."""
    result: dict[str, Any] = {
        "path": str(path), "file_bytes": path.stat().st_size,
        "allocated_bytes": allocated_bytes(path),
    }
    try:
        conn = open_readonly(path)
        try:
            page_size = int(conn.execute("PRAGMA page_size").fetchone()[0])
            page_count = int(conn.execute("PRAGMA page_count").fetchone()[0])
            free_pages = int(conn.execute("PRAGMA freelist_count").fetchone()[0])
            used_pages = max(0, page_count - free_pages)
            result["pages"] = {
                "page_size": page_size, "page_count": page_count,
                "free_pages": free_pages, "used_pages": used_pages,
                "logical_used_bytes": used_pages * page_size,
                "utilization_ratio": round(used_pages / page_count, 6)
                if page_count else None,
            }
            tables = table_names(conn)
            # The report describes storage, so it counts the content tables an
            # operator reads about rather than every table in the store.
            counts = table_counts(conn, REPORTED_TABLES)
            result["counts"] = counts
            if "events" in tables:
                row = conn.execute(
                    "SELECT COUNT(*), COALESCE(SUM(CASE WHEN content IS NOT NULL "
                    "AND content != '' THEN 1 ELSE 0 END),0), "
                    "COALESCE(SUM(length(content)),0), COALESCE(MAX(length(content)),0), "
                    "COALESCE(SUM(length(tool_input)),0), "
                    "COALESCE(SUM(length(tool_output)),0) FROM events"
                ).fetchone()
                result["text"] = {
                    "events": int(row[0]), "events_with_content": int(row[1]),
                    "content_characters": int(row[2]),
                    "largest_content_characters": int(row[3]),
                    "tool_input_characters": int(row[4]),
                    "tool_output_characters": int(row[5]),
                }
                for name, predicate in (
                    ("prompts", "event_kind='message.prompt' OR event_type='user_message' AND subtype IN ('prompt','slash_command')"),
                    ("responses", "event_kind='message.response' OR event_type='assistant_message'"),
                ):
                    value = conn.execute(
                        "SELECT COUNT(*), COALESCE(SUM(length(content)),0) "
                        f"FROM events WHERE ({predicate}) AND content IS NOT NULL AND content != ''"
                    ).fetchone()
                    result["text"][name] = {
                        "records": int(value[0]), "characters": int(value[1])
                    }
            if "sessions" in tables and "events" in tables:
                rows = [dict(zip(("session_id", "source", "events", "characters"), row)) for row in conn.execute(
                    "SELECT s.global_id, s.source, COUNT(e.id), "
                    "COALESCE(SUM(COALESCE(e.content_len,length(e.content),0) + "
                    "COALESCE(length(e.tool_input),0) + COALESCE(length(e.tool_output),0)),0) "
                    "FROM sessions s LEFT JOIN events e ON e.session_id=s.id "
                    "GROUP BY s.id ORDER BY 3 DESC, 4 DESC, s.global_id LIMIT 10"
                )]
                small = int(conn.execute(
                    "SELECT COUNT(*) FROM (SELECT s.id FROM sessions s LEFT JOIN events e "
                    "ON e.session_id=s.id GROUP BY s.id HAVING COUNT(e.id) <= 2)"
                ).fetchone()[0])
                result["session_skew"] = {
                    "sessions_with_at_most_two_events": small,
                    "largest_sessions": rows,
                }
            result["tokens"] = {
                "availability": "not_normalized",
                "reason": "CoSchema v4 does not yet persist vendor token observations",
            }
        finally:
            conn.close()
    except (OSError, sqlite3.Error) as exc:
        result["error"] = str(exc)
    return result


def _load_pointer(path: Path) -> Path | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        target = Path(value["path"])
        return target if target.is_absolute() else path.parent / target
    except (OSError, KeyError, json.JSONDecodeError):
        return None


def all_store_paths(registry: Path) -> tuple[list[Path], set[Path]]:
    stores: list[Path] = []
    current_snapshots: set[Path] = set()
    projects_root = registry / "projects"
    if not projects_root.exists():
        return stores, current_snapshots
    for pointer in projects_root.glob("*/current.json"):
        snapshot = _load_pointer(pointer)
        if snapshot is None or not snapshot.is_dir():
            continue
        current_snapshots.add(snapshot.resolve())
        stores.extend(sorted(snapshot.glob("*.db")))
    return stores, current_snapshots


def _snapshot_inventory(registry: Path, current: set[Path]) -> dict[str, Any]:
    snapshots = [
        path for path in (registry / "projects").glob("*/snapshots/*")
        if path.is_dir()
    ] if (registry / "projects").exists() else []
    current_paths = [path for path in snapshots if path.resolve() in current]
    old_paths = [path for path in snapshots if path.resolve() not in current]
    return {
        "root": str(registry / "projects"),
        "snapshots": len(snapshots),
        "current_snapshots": len(current_paths),
        "superseded_snapshots": len(old_paths),
        "all": tree_usage(registry / "projects"),
        "current": storage_usage(current_paths),
        "superseded": storage_usage(old_paths),
    }


def _raw_inventory(registry: Path, current_snapshots: set[Path]) -> dict[str, Any]:
    raw_root = registry / "raw" / "codess.raw-1"
    objects_root = raw_root / "objects"
    objects = [path for path in objects_root.rglob("*.zst") if path.is_file()]
    by_relpath = {
        str(path.relative_to(raw_root)): path for path in objects
    } if raw_root.exists() else {}
    referenced: set[str] = set()
    references = 0
    # The retention policy keeps only current snapshots. Reading historical
    # manifests here made every routine observation scale with all prior runs
    # and disguised objects that become reclaimable under that policy.
    for manifest in sorted(path / RAW_MANIFEST_FILE for path in current_snapshots):
        try:
            with manifest.open(encoding="utf-8") as stream:
                for line in stream:
                    try:
                        value = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    relpath = value.get("object_relpath")
                    if isinstance(relpath, str):
                        referenced.add(relpath)
                        references += 1
        except OSError:
            continue
    referenced_paths = [by_relpath[key] for key in referenced if key in by_relpath]
    orphan_paths = [path for key, path in by_relpath.items() if key not in referenced]
    large = [path for path in objects if path.stat().st_size > LARGE_RAW_OBJECT_BYTES]
    return {
        "root": str(raw_root),
        # `objects` is already the complete content-addressed inventory; do not
        # walk the multi-gigabyte tree a second time merely to total it.
        **file_usage(objects),
        "reference_scope": "current_snapshots",
        "objects": len(objects), "manifest_references": references,
        "referenced_objects": len(referenced_paths),
        "referenced": file_usage(referenced_paths),
        "unreferenced": file_usage(orphan_paths),
        "objects_over_300_mib": file_usage(large),
    }


def _previous(history_dir: Path) -> dict[str, Any] | None:
    files = sorted(history_dir.glob("*.json")) if history_dir.exists() else []
    if not files:
        return None
    try:
        return json.loads(files[-1].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _totals(report: dict[str, Any]) -> dict[str, int]:
    stores = report.get("stores") or []
    tokens = {
        item.get("source_system_id"): sum(
            int(month.get("total_tokens", 0)) for month in item.get("monthly", [])
        )
        for item in (report.get("token_usage") or {}).get("vendors", [])
    }
    return {
        "current_store_bytes": sum(int(item.get("file_bytes", 0)) for item in stores),
        "sessions": sum(int((item.get("counts") or {}).get("sessions", 0)) for item in stores),
        "interactions": sum(int((item.get("counts") or {}).get("interactions", 0)) for item in stores),
        "events": sum(int((item.get("counts") or {}).get("events", 0)) for item in stores),
        "content_characters": sum(int((item.get("text") or {}).get("content_characters", 0)) for item in stores),
        "cursor_bytes": int((report.get("cursor") or {}).get("file_bytes", 0)),
        "snapshot_bytes": int((((report.get("retention") or {}).get("snapshots") or {}).get("all") or {}).get("logical_bytes", 0)),
        "raw_store_bytes": int(
            ((report.get("retention") or {}).get("raw_store") or {}).get(
                "logical_bytes", 0
            )
        ),
        "claude_tokens": int(tokens.get("anthropic.claude-code", 0)),
        "codex_tokens_provisional": int(tokens.get("openai.codex", 0)),
    }


def build_storage_report(
    registry: Path,
    *,
    cursor_db: Path | None = None,
    history_dir: Path | None = None,
    record: bool = True,
    codess_limit: int = MAX_CODESS_DB_BYTES,
    cursor_limit: int = MAX_CURSOR_DB_BYTES,
) -> dict[str, Any]:
    registry = registry.expanduser().resolve()
    history_dir = history_dir or registry / "observations" / "storage"
    observed = datetime.now(UTC)
    previous = _previous(history_dir)
    stores, current = all_store_paths(registry)
    report: dict[str, Any] = {
        "report_format": REPORT_FORMAT,
        "observed_at": observed.isoformat(),
        "registry": str(registry),
        "thresholds": {
            "codess_db_bytes": codess_limit, "cursor_db_bytes": cursor_limit,
        },
        "stores": [inspect_sqlite(path) for path in stores],
        "retention": {
            "snapshots": _snapshot_inventory(registry, current),
            "raw_store": _raw_inventory(registry, current),
        },
        "warnings": [],
    }
    report["token_usage"] = collect_token_usage(
        stores, cache_path=registry / "cache" / "token-usage-v1.json"
    )
    if cursor_db and cursor_db.exists():
        report["cursor"] = inspect_sqlite(cursor_db)
    for item in report["stores"]:
        if item["file_bytes"] > codess_limit:
            report["warnings"].append({
                "kind": "codess_db_size", "path": item["path"],
                "bytes": item["file_bytes"], "threshold": codess_limit,
            })
    if (report.get("cursor") or {}).get("file_bytes", 0) > cursor_limit:
        report["warnings"].append({
            "kind": "cursor_db_size", "path": report["cursor"]["path"],
            "bytes": report["cursor"]["file_bytes"], "threshold": cursor_limit,
        })
    report["totals"] = _totals(report)
    if previous and previous.get("report_format") == REPORT_FORMAT:
        previous_totals = previous.get("totals") or {}
        report["previous_observed_at"] = previous.get("observed_at")
        report["delta"] = {
            key: value - int(previous_totals[key])
            for key, value in report["totals"].items()
            if key in previous_totals
        }
        report["new_metrics"] = {
            key: value for key, value in report["totals"].items()
            if key not in previous_totals
        }
    if record:
        stamp = observed.strftime("%Y%m%dT%H%M%S.%fZ")
        write_json_atomic(history_dir / f"{stamp}.json", report)
    return report
