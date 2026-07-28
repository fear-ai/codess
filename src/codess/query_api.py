"""Typed, reusable read-only queries over one or more CoSchema stores."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


REQUEST_FORMAT = "codess.query-request/1"
RESULT_FORMAT = "codess.query-result/1"
QUERY_PROCESSOR = "codess.query-api/1"
SUPPORTED_ACTIONS = frozenset({"sessions", "overview", "events", "search"})
SUPPORTED_FILTERS = frozenset({
    "session_ids", "event_ids", "interaction_ids", "model_turn_ids",
    "source_system_ids", "event_kinds", "statuses", "models",
    "artifact", "text", "since", "until",
})
ACTION_FILTERS = {
    "sessions": frozenset({"session_ids", "source_system_ids", "since", "until"}),
    "overview": SUPPORTED_FILTERS,
    "events": SUPPORTED_FILTERS,
    "search": SUPPORTED_FILTERS,
}
REQUEST_FIELDS = frozenset({
    "format", "action", "project_ids", "filters", "limit", "byte_limit",
    "snapshot_id", "active_gap_caps_minutes",
})


class QueryContractError(ValueError):
    """A request/result cannot be executed without silently changing meaning."""


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")


def content_hash(value: Any) -> str:
    """Return a deterministic content identity (not an authenticity proof)."""
    return "sha256:" + hashlib.sha256(_canonical_bytes(value)).hexdigest()


def make_request(
    action: str,
    *,
    project_ids: Iterable[str] = (),
    filters: dict[str, Any] | None = None,
    limit: int | None = None,
    byte_limit: int | None = None,
    snapshot_id: str | None = None,
    active_gap_caps_minutes: Iterable[int] = (5, 30, 120),
) -> dict[str, Any]:
    normalized_filters = dict(filters or {})
    for key in (
        "session_ids", "event_ids", "interaction_ids", "model_turn_ids",
        "source_system_ids", "event_kinds", "statuses", "models",
    ):
        if isinstance(normalized_filters.get(key), list):
            normalized_filters[key] = sorted(set(normalized_filters[key]))
    request = {
        "format": REQUEST_FORMAT,
        "action": action,
        "project_ids": sorted(set(project_ids)),
        "filters": normalized_filters,
        "limit": limit,
        "byte_limit": byte_limit,
        "snapshot_id": snapshot_id,
        "active_gap_caps_minutes": list(active_gap_caps_minutes),
    }
    validate_request(request)
    return request


def validate_request(request: dict[str, Any]) -> None:
    unknown_fields = sorted(set(request) - REQUEST_FIELDS)
    if unknown_fields:
        raise QueryContractError(
            "unsupported request field(s): " + ", ".join(unknown_fields)
        )
    if request.get("format") != REQUEST_FORMAT:
        raise QueryContractError(f"format must be {REQUEST_FORMAT!r}")
    if request.get("action") not in SUPPORTED_ACTIONS:
        raise QueryContractError(
            f"unsupported action {request.get('action')!r}; expected "
            + ", ".join(sorted(SUPPORTED_ACTIONS))
        )
    if not (
        isinstance(request.get("project_ids"), list)
        and all(isinstance(value, str) and value for value in request["project_ids"])
    ):
        raise QueryContractError("project_ids must be an array of non-empty strings")
    if request["project_ids"] != sorted(set(request["project_ids"])):
        raise QueryContractError("project_ids must be unique and canonically sorted")
    if request.get("snapshot_id") is not None and not isinstance(request["snapshot_id"], str):
        raise QueryContractError("snapshot_id must be a string or null")
    filters = request.get("filters")
    if not isinstance(filters, dict):
        raise QueryContractError("filters must be an object")
    unknown = sorted(set(filters) - SUPPORTED_FILTERS)
    if unknown:
        raise QueryContractError("unsupported filter(s): " + ", ".join(unknown))
    incompatible = sorted(set(filters) - ACTION_FILTERS[request["action"]])
    if incompatible:
        raise QueryContractError(
            f"filter(s) not valid for {request['action']}: " + ", ".join(incompatible)
        )
    for key in (
        "session_ids", "event_ids", "interaction_ids", "model_turn_ids",
        "source_system_ids", "event_kinds", "statuses", "models",
    ):
        if key in filters and not (
            isinstance(filters[key], list)
            and all(isinstance(value, str) for value in filters[key])
        ):
            raise QueryContractError(f"filters.{key} must be an array of strings")
        if key in filters and filters[key] != sorted(set(filters[key])):
            raise QueryContractError(f"filters.{key} must be unique and canonically sorted")
    for key in ("artifact", "text"):
        if key in filters and not isinstance(filters[key], str):
            raise QueryContractError(f"filters.{key} must be a string")
    for key in ("since", "until"):
        if key in filters and not isinstance(filters[key], (int, float)):
            raise QueryContractError(f"filters.{key} must be Unix milliseconds")
    if filters.get("since") is not None and filters.get("until") is not None and filters["since"] > filters["until"]:
        raise QueryContractError("filters.since must be <= filters.until")
    for key in ("limit", "byte_limit"):
        value = request.get(key)
        if value is not None and (not isinstance(value, int) or value < 0):
            raise QueryContractError(f"{key} must be a non-negative integer or null")
    caps = request.get("active_gap_caps_minutes", [5, 30, 120])
    if not isinstance(caps, list) or not caps or any(
        not isinstance(value, int) or value <= 0 for value in caps
    ):
        raise QueryContractError("active_gap_caps_minutes must contain positive integers")
    if request["action"] == "search" and not filters.get("text"):
        raise QueryContractError("search requires a non-empty filters.text")
    if request["action"] == "overview" and (
        request.get("limit") is not None or request.get("byte_limit") is not None
    ):
        raise QueryContractError("overview does not accept row or byte limits")
    if request["action"] == "sessions" and request.get("byte_limit") is not None:
        raise QueryContractError("sessions does not return content and does not accept byte_limit")


def load_document(path: Path, expected_format: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise QueryContractError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict) or value.get("format") != expected_format:
        raise QueryContractError(f"{path} is not {expected_format}")
    return value


def save_document(path: Path, value: dict[str, Any]) -> None:
    """Atomically save a canonical request/result document."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(_canonical_bytes(value) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    except Exception:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass
        raise


def selection_from_result(result: dict[str, Any]) -> dict[str, list[str]]:
    if result.get("format") != RESULT_FORMAT:
        raise QueryContractError(f"selection input must be {RESULT_FORMAT}")
    sessions: set[str] = set()
    events: set[str] = set()
    for row in result.get("rows") or []:
        if row.get("global_session_id"):
            sessions.add(str(row["global_session_id"]))
        if row.get("global_event_id"):
            events.add(str(row["global_event_id"]))
    selected: dict[str, list[str]] = {}
    if sessions:
        selected["session_ids"] = sorted(sessions)
    if events:
        selected["event_ids"] = sorted(events)
    if not selected:
        raise QueryContractError("saved result contains no stable session or event IDs")
    return selected


def merge_selection(request: dict[str, Any], selected: dict[str, list[str]]) -> dict[str, Any]:
    merged = json.loads(json.dumps(request))
    filters = merged.setdefault("filters", {})
    for key, values in selected.items():
        current = set(filters.get(key) or [])
        filters[key] = sorted(current & set(values)) if current else sorted(set(values))
    validate_request(merged)
    return merged


def _in_clause(column: str, values: list[str], where: list[str], params: list[Any]) -> None:
    if values:
        where.append(f"{column} IN ({','.join('?' for _ in values)})")
        params.extend(values)


def _event_predicate(filters: dict[str, Any]) -> tuple[str, list[Any]]:
    where: list[str] = []
    params: list[Any] = []
    _in_clause("s.global_id", filters.get("session_ids") or [], where, params)
    _in_clause("e.global_id", filters.get("event_ids") or [], where, params)
    _in_clause("e.interaction_id", filters.get("interaction_ids") or [], where, params)
    _in_clause("e.model_turn_id", filters.get("model_turn_ids") or [], where, params)
    _in_clause("s.source_system_id", filters.get("source_system_ids") or [], where, params)
    _in_clause("e.event_kind", filters.get("event_kinds") or [], where, params)
    statuses = filters.get("statuses") or []
    if statuses:
        _in_clause("COALESCE(e.normalized_status,e.source_status)", statuses, where, params)
    models = filters.get("models") or []
    if models:
        _in_clause("mc.model_name_exact", models, where, params)
    if filters.get("since") is not None:
        where.append("COALESCE(e.event_at,e.timestamp)>=?")
        params.append(filters["since"])
    if filters.get("until") is not None:
        where.append("COALESCE(e.event_at,e.timestamp)<=?")
        params.append(filters["until"])
    if filters.get("artifact"):
        where.append("e.artifact_path LIKE ? ESCAPE '\\'")
        params.append(f"%{filters['artifact']}%")
    if filters.get("text"):
        where.append("(e.content LIKE ? OR e.tool_input LIKE ? OR e.tool_output LIKE ? OR e.artifact_path LIKE ?)")
        params.extend([f"%{filters['text']}%"] * 4)
    return (" AND ".join(where) if where else "1"), params


def _store_provenance(store: dict[str, Any]) -> dict[str, Any]:
    conn = store["conn"]
    meta = dict(conn.execute("SELECT key,value FROM store_meta"))
    policies = [row[0] for row in conn.execute(
        "SELECT DISTINCT policy_sha256 FROM processing_runs ORDER BY policy_sha256"
    )] if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='processing_runs'"
    ).fetchone() else []
    availability = dict(conn.execute(
        "SELECT availability,COUNT(*) FROM sources GROUP BY availability"
    ))
    project_ids = [row[0] for row in conn.execute("SELECT id FROM projects ORDER BY id")]
    return {
        "project_ids": project_ids,
        "project_path": str(store["project_root"]),
        "store_path": str(store["path"]),
        "snapshot_id": meta.get("snapshot_id"),
        "snapshot_created_at": meta.get("snapshot_created_at"),
        "package_digest": meta.get("package_digest"),
        "format_version": meta.get("format_version"),
        "decoder_version": meta.get("decoder_version"),
        "validator_version": meta.get("validator_version"),
        "policy_sha256": policies,
        "source_availability": availability,
    }


def selected_project_ids(stores: list[dict[str, Any]]) -> list[str]:
    """Return stable Project IDs, with an explicit legacy location fallback."""
    selected: set[str] = set()
    for store in stores:
        ids = [row[0] for row in store["conn"].execute("SELECT id FROM projects")]
        if ids:
            selected.update(str(value) for value in ids)
        else:
            digest = hashlib.sha256(str(store["project_root"]).encode("utf-8")).hexdigest()
            selected.add(f"codess:legacy-project-location:sha256:{digest}")
    return sorted(selected)


def _event_rows(stores: list[dict[str, Any]], request: dict[str, Any]) -> tuple[list[dict], dict]:
    if request.get("limit") == 0:
        return [], {
            "matched_rows_read": 0, "returned_rows": 0,
            "returned_content_bytes": 0, "truncated": False,
            "truncation_reasons": [],
        }
    predicate, params = _event_predicate(request["filters"])
    rows: list[dict[str, Any]] = []
    scanned = 0
    byte_limit = request.get("byte_limit")
    used_bytes = 0
    byte_truncated = False
    row_limit_reached = False
    sql = f"""
        SELECT e.global_id,e.event_id,s.global_id AS global_session_id,e.session_id,
               s.source_system_id,s.project_path,e.sequence_no,e.interaction_id,
               e.model_turn_id,e.event_kind,e.actor_kind,e.content_role,e.origin_kind,
               COALESCE(e.event_at,e.timestamp) AS event_at,e.event_at_basis,
               e.source_record_locator,e.source_record_type,e.source_record_subtype,
               e.content,e.content_len,e.tool_name,e.tool_input,e.tool_output,
               COALESCE(e.normalized_status,e.source_status) AS status,
               e.artifact_path,e.source_file,mc.model_name_exact
        FROM events e JOIN sessions s ON s.id=e.session_id
        LEFT JOIN model_turns mt ON mt.id=e.model_turn_id
        LEFT JOIN model_configurations mc ON mc.id=mt.model_config_id
        WHERE {predicate}
        ORDER BY COALESCE(e.event_at,e.timestamp),s.global_id,e.sequence_no,e.id
    """
    for store in stores:
        for record in store["conn"].execute(sql, params):
            scanned += 1
            content = record["content"] or ""
            # Bound every potentially large inline field returned, not merely
            # message content. Tool results commonly appear in both normalized
            # content and the typed tool-output projection, so the serialized
            # result cost includes both copies.
            row_bytes = sum(len(str(value).encode("utf-8")) for value in (
                content, record["tool_input"] or "", record["tool_output"] or "",
                record["artifact_path"] or "",
            ))
            if byte_limit is not None and used_bytes + row_bytes > byte_limit:
                byte_truncated = True
                break
            used_bytes += row_bytes
            rows.append({
                "global_event_id": record["global_id"],
                "event_id": record["event_id"],
                "global_session_id": record["global_session_id"],
                "session_id": record["session_id"],
                "project_path": str(store["project_root"]),
                "source_project_path": record["project_path"],
                "source_system_id": record["source_system_id"],
                "sequence_no": record["sequence_no"],
                "interaction_id": record["interaction_id"],
                "model_turn_id": record["model_turn_id"],
                "event_kind": record["event_kind"],
                "actor_kind": record["actor_kind"],
                "content_role": record["content_role"],
                "origin_kind": record["origin_kind"],
                "event_at": record["event_at"],
                "event_at_basis": record["event_at_basis"],
                "source_record_locator": record["source_record_locator"],
                "source_record_type": record["source_record_type"],
                "source_record_subtype": record["source_record_subtype"],
                "content": content,
                "content_length": len(content),
                "source_content_length": record["content_len"],
                "content_complete": record["content_len"] in (None, len(content)),
                "tool_name": record["tool_name"],
                "tool_input": record["tool_input"],
                "tool_output": record["tool_output"],
                "status": record["status"],
                "artifact_path": record["artifact_path"],
                "source_file": record["source_file"],
                "model": record["model_name_exact"],
            })
            limit = request.get("limit")
            if limit is not None and len(rows) >= limit:
                row_limit_reached = True
                break
        if byte_truncated or row_limit_reached:
            break
    return rows, {
        "matched_rows_read": scanned,
        "returned_rows": len(rows),
        "returned_content_bytes": used_bytes,
        "truncated": bool(byte_truncated or row_limit_reached),
        "truncation_reasons": (["byte_limit"] if byte_truncated else [])
        + (["row_limit_reached"] if row_limit_reached else []),
    }


def _session_rows(stores: list[dict[str, Any]], request: dict[str, Any]) -> tuple[list[dict], dict]:
    filters = request["filters"]
    where: list[str] = []
    params: list[Any] = []
    _in_clause("s.global_id", filters.get("session_ids") or [], where, params)
    _in_clause("s.source_system_id", filters.get("source_system_ids") or [], where, params)
    if filters.get("since") is not None:
        where.append("COALESCE(s.ended_at,s.started_at,s.source_mtime)>=?")
        params.append(filters["since"])
    if filters.get("until") is not None:
        where.append("COALESCE(s.started_at,s.ended_at,s.source_mtime)<=?")
        params.append(filters["until"])
    predicate = " AND ".join(where) if where else "1"
    rows = []
    for store in stores:
        session_columns = {
            row[1] for row in store["conn"].execute("PRAGMA table_info(sessions)")
        }
        path_obsolete = (
            "s.path_obsolete" if "path_obsolete" in session_columns
            else "0 AS path_obsolete"
        )
        for row in store["conn"].execute(f"""
            SELECT s.global_id,s.id,s.source_system_id,s.vendor_session_id,
                   s.vendor_name,s.product_name,s.harness_name,s.harness_version,
                   s.started_at,s.ended_at,s.time_basis,s.source_cwd,
                   s.project_path,
                   {path_obsolete},s.archive_state,
                   (SELECT COUNT(*) FROM interactions i WHERE i.session_id=s.id) interactions,
                   (SELECT COUNT(*) FROM model_turns mt WHERE mt.session_id=s.id) model_turns,
                   (SELECT COUNT(*) FROM events e WHERE e.session_id=s.id) events
            FROM sessions s WHERE {predicate}
            ORDER BY COALESCE(s.ended_at,s.started_at,s.source_mtime) DESC,s.global_id
        """, params):
            item = dict(row)
            source_project_path = item.pop("source_cwd") or item["project_path"]
            rows.append({
                **item,
                "project_path": str(store["project_root"]),
                "source_project_path": source_project_path,
            })
    rows.sort(key=lambda row: (-(row["ended_at"] or row["started_at"] or 0), row["global_id"]))
    matched = len(rows)
    if request.get("limit") is not None:
        rows = rows[:request["limit"]]
    return rows, {"matched_rows": matched, "returned_rows": len(rows),
                  "truncated": len(rows) < matched,
                  "truncation_reasons": ["row_limit"] if len(rows) < matched else []}


def _overview(stores: list[dict[str, Any]], request: dict[str, Any]) -> tuple[list[dict], dict]:
    predicate, params = _event_predicate(request["filters"])
    totals = {key: 0 for key in (
        "sessions", "interactions", "model_turns", "events", "content_characters",
        "tool_events", "artifact_events",
    )}
    times: list[float] = []
    vendors: dict[str, int] = {}
    kinds: dict[str, int] = {}
    models: dict[str, int] = {}
    configurations: set[tuple] = set()
    for store in stores:
        conn = store["conn"]
        selected_sessions = {row[0] for row in conn.execute(f"""
            SELECT DISTINCT s.id FROM events e JOIN sessions s ON s.id=e.session_id
            LEFT JOIN model_turns mt ON mt.id=e.model_turn_id
            LEFT JOIN model_configurations mc ON mc.id=mt.model_config_id
            WHERE {predicate}
        """, params)}
        totals["sessions"] += len(selected_sessions)
        if selected_sessions:
            placeholders = ",".join("?" for _ in selected_sessions)
            ids = sorted(selected_sessions)
            totals["interactions"] += conn.execute(
                f"SELECT COUNT(*) FROM interactions WHERE session_id IN ({placeholders})", ids
            ).fetchone()[0]
            totals["model_turns"] += conn.execute(
                f"SELECT COUNT(*) FROM model_turns WHERE session_id IN ({placeholders})", ids
            ).fetchone()[0]
        for row in conn.execute(f"""
            SELECT s.source_system_id,e.event_kind,COALESCE(e.event_at,e.timestamp),
                   LENGTH(COALESCE(e.content,'')),e.tool_name,e.artifact_path,
                   mc.provider,mc.model_family,mc.model_name_exact,mc.model_revision,
                   mc.reasoning_effort,mc.speed_tier,mc.service_tier,mc.mode
            FROM events e JOIN sessions s ON s.id=e.session_id
            LEFT JOIN model_turns mt ON mt.id=e.model_turn_id
            LEFT JOIN model_configurations mc ON mc.id=mt.model_config_id
            WHERE {predicate}
        """, params):
            totals["events"] += 1
            totals["content_characters"] += row[3]
            totals["tool_events"] += int(row[4] is not None)
            totals["artifact_events"] += int(row[5] is not None)
            vendors[row[0]] = vendors.get(row[0], 0) + 1
            kinds[row[1] or "unknown"] = kinds.get(row[1] or "unknown", 0) + 1
            if row[2] is not None:
                times.append(float(row[2]))
            if row[8]:
                models[row[8]] = models.get(row[8], 0) + 1
                configurations.add(tuple(row[6:14]))
    times.sort()
    span = (times[-1] - times[0]) if len(times) > 1 else 0
    caps = request.get("active_gap_caps_minutes", [5, 30, 120])
    active = {
        str(cap): sum(min(max(0.0, right - left), cap * 60_000) for left, right in zip(times, times[1:]))
        for cap in caps
    }
    summary = {
        **totals,
        "model_configurations": len(configurations),
        "first_event_at": times[0] if times else None,
        "last_event_at": times[-1] if times else None,
        "elapsed_span_ms": span,
        "event_days": len({datetime.fromtimestamp(ts / 1000, tz=timezone.utc).date().isoformat() for ts in times}),
        "active_time_estimates_ms_by_gap_cap_minutes": active,
        "vendors_by_event": dict(sorted(vendors.items())),
        "event_kinds": dict(sorted(kinds.items(), key=lambda item: (-item[1], item[0]))),
        "models_by_event": dict(sorted(models.items(), key=lambda item: (-item[1], item[0]))),
        "active_time_semantics": "sum of adjacent event gaps capped independently; sensitivity estimate, not observed or billable time",
    }
    return [], summary


def execute(stores: list[dict[str, Any]], request: dict[str, Any]) -> dict[str, Any]:
    """Execute a validated request; stores must contain read-only connections."""
    validate_request(request)
    canonical_request = json.loads(_canonical_bytes(request))
    observed_project_ids = selected_project_ids(stores)
    if (
        canonical_request["project_ids"]
        and canonical_request["project_ids"] != observed_project_ids
    ):
        raise QueryContractError("request project_ids do not match the selected store scope")
    action = canonical_request["action"]
    if action == "sessions":
        rows, summary = _session_rows(stores, canonical_request)
    elif action == "overview":
        rows, summary = _overview(stores, canonical_request)
    else:
        rows, summary = _event_rows(stores, canonical_request)
    limitations = []
    if action == "search":
        limitations.append(
            "search covers normalized inline event content/tool fields/artifact paths; "
            "a miss does not prove absence from truncated, filtered, redacted, or external evidence"
        )
    if any(row.get("content_complete") is False for row in rows):
        limitations.append("one or more returned rows has incomplete normalized content")
    if any(value.startswith("codess:legacy-project-location:") for value in observed_project_ids):
        limitations.append("one or more legacy stores lacks a stable Project ID; scope is location-bound")
    result = {
        "format": RESULT_FORMAT,
        "processor": QUERY_PROCESSOR,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "request": canonical_request,
        "request_hash": content_hash(canonical_request),
        "provenance": [_store_provenance(store) for store in stores],
        "summary": summary,
        "rows": rows,
        "limitations": limitations,
    }
    result["data_as_of"] = sorted({
        item["snapshot_created_at"] for item in result["provenance"]
        if item.get("snapshot_created_at")
    })
    result["bounds"] = {
        "row_limit": canonical_request.get("limit"),
        "byte_limit": canonical_request.get("byte_limit"),
        "truncated": bool(summary.get("truncated", False)),
        "truncation_reasons": summary.get("truncation_reasons", []),
    }
    result["result_hash"] = content_hash({
        "request_hash": result["request_hash"],
        "snapshots": sorted(
            {(item.get("snapshot_id"), item.get("package_digest"))
             for item in result["provenance"]},
            key=lambda item: tuple(str(value or "") for value in item),
        ),
        "row_ids": [
            row.get("global_event_id") or row.get("global_session_id")
            for row in rows
        ],
        "summary": summary,
        "limitations": limitations,
    })
    return result


def compare_results(prior: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    def identities(result: dict[str, Any]) -> set[str]:
        found = set()
        for index, row in enumerate(result.get("rows") or []):
            found.add(str(row.get("global_event_id") or row.get("global_session_id") or f"row:{index}:{content_hash(row)}"))
        return found
    before, after = identities(prior), identities(current)
    return {
        "same_result_hash": prior.get("result_hash") == current.get("result_hash"),
        "added_ids": sorted(after - before),
        "removed_ids": sorted(before - after),
    }
