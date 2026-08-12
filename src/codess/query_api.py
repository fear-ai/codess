"""Typed, reusable read-only queries over one or more CoSchema stores.
"""

from __future__ import annotations

import heapq
import json
import sqlite3
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from codess.schema_contract import column_names
from codess.hashing import codess_bytes_hash


REQUEST_FORMAT = "codess.query-request/1"
RESULT_FORMAT = "codess.query-result/1"
QUERY_PROCESSOR = "codess.query-api/1"
SUPPORTED_ACTIONS = frozenset({"sessions", "overview", "events", "search"})
SUPPORTED_FILTERS = frozenset({
    "session_ids", "event_ids", "interaction_ids", "model_turn_ids",
    "source_system_ids", "event_kinds", "statuses", "models",
    "model_providers", "model_families", "model_revisions",
    "reasoning_efforts", "speed_tiers", "service_tiers", "model_modes",
    "tool_names", "actor_kinds", "content_roles", "origin_kinds",
    "parent_session_ids", "session_relation_kinds", "initiation_kinds",
    "artifact", "text", "since", "until",
})
ACTION_FILTERS = {
    "sessions": frozenset({
        "session_ids", "source_system_ids", "parent_session_ids",
        "session_relation_kinds", "since", "until", "models",
        "model_providers", "model_families", "model_revisions",
        "reasoning_efforts", "speed_tiers", "service_tiers", "model_modes",
    }),
    "overview": SUPPORTED_FILTERS,
    "events": SUPPORTED_FILTERS,
    "search": SUPPORTED_FILTERS,
}
REQUEST_FIELDS = frozenset({
    "format", "action", "project_ids", "project_snapshots", "filters",
    "limit", "byte_limit", "snapshot_id", "active_gap_caps_minutes", "expand",
    "sequence_before", "sequence_after", "group_repetitions",
    "facet_limit",
})


class QueryContractError(ValueError):
    """A request/result cannot be executed without silently changing meaning."""


# Bound on filters.text / filters.artifact as received from a CLI argument,
# file, or environment variable -- independent of whether the value is later
# bound safely as a SQL parameter. An unbounded value is still a resource
# concern (a very long LIKE pattern) and a legibility concern (control chars,
# markup, or script-like content echoed back in results/errors).
#
# Searched content is bounded UTF-8 (CoPlan.md 7.3) and can legitimately
# contain any Unicode text (non-English strings, emoji, symbols in code).
# The charset bound therefore excludes only control/formatting characters,
# matching sanitize.py's CONTROL_CHARS_RE precedent, not non-ASCII text.
FREE_TEXT_FILTER_MAX_CHARS = 512
_FREE_TEXT_ALLOWED_RE = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]')
_QUESTIONABLE_FREE_TEXT_RES = (
    re.compile(r"<\s*script\b", re.IGNORECASE),
    re.compile(r"<\s*/?\s*[a-z][a-z0-9]*[^>]*>", re.IGNORECASE),
    re.compile(r"\bUNION\b\s+\bSELECT\b", re.IGNORECASE),
    re.compile(r"--\s"),
    re.compile(r";\s*(DROP|DELETE|UPDATE|INSERT)\b", re.IGNORECASE),
)


def sanitize_free_text_filter(
    value: str, *, field: str, mode: str = "reject",
) -> str:
    """Bound and screen one user-supplied free-text filter value.

    `value` is untrusted input reaching this boundary from a CLI argument,
    a file the user pointed at, or an environment variable -- never from
    stored session content, which has its own pipeline in
    content_processing.py.  This function governs size, character set, and
    a short list of patterns associated with injection or markup attempts;
    it does not by itself make string-built SQL safe -- filters.text and
    filters.artifact are always bound as SQL parameters downstream (see
    the module SQL note), so this is a size/legibility/defense-in-depth
    boundary, not the mechanism that prevents SQL injection.

    `mode` selects disposition on a violation:
      "reject" -- raise QueryContractError (the default; used by
        validate_request so a bad filter fails the request explicitly).
      "strip"  -- remove disallowed characters/patterns and return the
        remainder, truncated to the size bound.
      "blank"  -- return "" on any violation, dropping the filter value
        rather than failing or attempting a partial edit.
    """
    if mode not in ("reject", "strip", "blank"):
        raise ValueError(f"unsupported sanitize_free_text_filter mode: {mode!r}")
    violations = []
    if len(value) > FREE_TEXT_FILTER_MAX_CHARS:
        violations.append("too long")
    if _FREE_TEXT_ALLOWED_RE.search(value):
        violations.append("disallowed characters")
    if any(pattern.search(value) for pattern in _QUESTIONABLE_FREE_TEXT_RES):
        violations.append("questionable expression")
    if not violations:
        return value
    if mode == "reject":
        raise QueryContractError(
            f"filters.{field} rejected ({', '.join(violations)})"
        )
    if mode == "blank":
        return ""
    cleaned = _FREE_TEXT_ALLOWED_RE.sub("", value)
    for pattern in _QUESTIONABLE_FREE_TEXT_RES:
        cleaned = pattern.sub("", cleaned)
    return cleaned[:FREE_TEXT_FILTER_MAX_CHARS]


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")


def content_hash(value: Any) -> str:
    """Return a deterministic content identity (not an authenticity proof)."""
    return "sha256:" + codess_bytes_hash(256, 256, _canonical_bytes(value))


def make_request(
    action: str,
    *,
    project_ids: Iterable[str] = (),
    project_snapshots: Iterable[dict[str, Any]] = (),
    filters: dict[str, Any] | None = None,
    limit: int | None = None,
    byte_limit: int | None = None,
    snapshot_id: str | None = None,
    active_gap_caps_minutes: Iterable[int] = (5, 30, 120),
    expand: str | None = None,
    sequence_before: int = 0,
    sequence_after: int = 0,
    group_repetitions: bool = False,
    facet_limit: int = 50,
) -> dict[str, Any]:
    normalized_filters = dict(filters or {})
    for key in (
        "session_ids", "event_ids", "interaction_ids", "model_turn_ids",
        "source_system_ids", "event_kinds", "statuses", "models",
        "model_providers", "model_families", "model_revisions",
        "reasoning_efforts", "speed_tiers", "service_tiers", "model_modes",
        "tool_names", "actor_kinds", "content_roles", "origin_kinds",
        "parent_session_ids", "session_relation_kinds", "initiation_kinds",
    ):
        if isinstance(normalized_filters.get(key), list):
            normalized_filters[key] = sorted(set(normalized_filters[key]))
    request = {
        "format": REQUEST_FORMAT,
        "action": action,
        "project_ids": sorted(set(project_ids)),
        "project_snapshots": sorted(
            (
                {
                    "project_id": str(item["project_id"]),
                    "snapshot_id": item.get("snapshot_id"),
                }
                for item in project_snapshots
            ),
            key=lambda item: (
                item["project_id"], item["snapshot_id"] or "",
            ),
        ),
        "filters": normalized_filters,
        "limit": limit,
        "byte_limit": byte_limit,
        "snapshot_id": snapshot_id,
        "active_gap_caps_minutes": list(active_gap_caps_minutes),
        "expand": expand,
        "sequence_before": sequence_before,
        "sequence_after": sequence_after,
        "group_repetitions": group_repetitions,
        "facet_limit": facet_limit,
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
    project_snapshots = request.get("project_snapshots", [])
    if not isinstance(project_snapshots, list):
        raise QueryContractError("project_snapshots must be an array")
    normalized_project_snapshots = []
    for index, item in enumerate(project_snapshots):
        if not isinstance(item, dict) or set(item) != {
            "project_id", "snapshot_id",
        }:
            raise QueryContractError(
                f"project_snapshots[{index}] must contain project_id and snapshot_id"
            )
        if not isinstance(item["project_id"], str) or not item["project_id"]:
            raise QueryContractError(
                f"project_snapshots[{index}].project_id must be non-empty"
            )
        if item["snapshot_id"] is not None and (
            not isinstance(item["snapshot_id"], str) or not item["snapshot_id"]
        ):
            raise QueryContractError(
                f"project_snapshots[{index}].snapshot_id must be non-empty or null"
            )
        normalized_project_snapshots.append(item)
    if project_snapshots != sorted(
        normalized_project_snapshots,
        key=lambda item: (item["project_id"], item["snapshot_id"] or ""),
    ) or len({
        (item["project_id"], item["snapshot_id"])
        for item in project_snapshots
    }) != len(project_snapshots):
        raise QueryContractError(
            "project_snapshots must be unique and canonically sorted"
        )
    if project_snapshots and {
        item["project_id"] for item in project_snapshots
    } != set(request["project_ids"]):
        raise QueryContractError(
            "project_snapshots Project IDs must equal project_ids"
        )
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
        "model_providers", "model_families", "model_revisions",
        "reasoning_efforts", "speed_tiers", "service_tiers", "model_modes",
        "tool_names", "actor_kinds", "content_roles", "origin_kinds",
        "parent_session_ids", "session_relation_kinds", "initiation_kinds",
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
        if key in filters and filters[key]:
            sanitize_free_text_filter(filters[key], field=key)
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
    expand = request.get("expand")
    if expand not in {None, "interaction", "model_turn"}:
        raise QueryContractError("expand must be interaction, model_turn, or null")
    for key in ("sequence_before", "sequence_after"):
        value = request.get(key, 0)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise QueryContractError(f"{key} must be a non-negative integer")
    expanding = bool(
        expand
        or request.get("sequence_before", 0)
        or request.get("sequence_after", 0)
    )
    if expanding and request["action"] != "events":
        raise QueryContractError("expansion and sequence windows require events")
    if expanding and not any(
        filters.get(key)
        for key in ("event_ids", "interaction_ids", "model_turn_ids")
    ):
        raise QueryContractError(
            "expansion and sequence windows require an Event, Interaction, or Model Turn ID"
        )
    if (
        (request.get("sequence_before", 0) or request.get("sequence_after", 0))
        and not filters.get("event_ids")
    ):
        raise QueryContractError("sequence windows require filters.event_ids")
    if expand == "interaction" and filters.get("model_turn_ids"):
        raise QueryContractError(
            "interaction expansion does not accept model_turn_ids"
        )
    if expand == "model_turn" and filters.get("interaction_ids"):
        raise QueryContractError(
            "model_turn expansion does not accept interaction_ids"
        )
    if expanding:
        restricting = set(filters) - {
            "event_ids", "interaction_ids", "model_turn_ids",
            "session_ids", "source_system_ids",
        }
        if restricting:
            raise QueryContractError(
                "complete expansion cannot be combined with event-content "
                "filters: " + ", ".join(sorted(restricting))
            )
    if not isinstance(request.get("group_repetitions", False), bool):
        raise QueryContractError("group_repetitions must be boolean")
    facet_limit = request.get("facet_limit", 50)
    if (
        isinstance(facet_limit, bool)
        or not isinstance(facet_limit, int)
        or not 1 <= facet_limit <= 1000
    ):
        raise QueryContractError("facet_limit must be an integer from 1 to 1000")
    if request.get("group_repetitions") and request["action"] not in {
        "events", "search",
    }:
        raise QueryContractError(
            "group_repetitions requires events or search"
        )


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


def _like_literal(value: str) -> str:
    """Escape one value for a literal substring match using SQLite LIKE."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def session_structure_counts(
    conn: sqlite3.Connection, session_ids: Iterable[str],
) -> dict[str, Any]:
    """Interaction, Model Turn, relation, and initiation counts for Sessions.

    The four aggregates that summarize how a set of Sessions is structured,
    rather than what they contain. The overview and the orientation audit both
    reported them and had written the same four statements out separately, so
    a change to one report silently disagreed with the other.

    Returns zero totals and empty breakdowns for an empty selection rather
    than querying with an empty `IN ()`, which is not valid SQLite.
    """
    ids = sorted(session_ids)
    empty = {
        "interactions": 0, "model_turns": 0,
        "session_relations": {}, "initiation_kinds": {},
    }
    if not ids:
        return empty
    placeholders = ",".join("?" for _ in ids)
    return {
        "interactions": int(conn.execute(
            f"SELECT COUNT(*) FROM interactions WHERE session_id IN ({placeholders})",
            ids,
        ).fetchone()[0]),
        "model_turns": int(conn.execute(
            f"SELECT COUNT(*) FROM model_turns WHERE session_id IN ({placeholders})",
            ids,
        ).fetchone()[0]),
        # A Session with no recorded relation is top level, named rather than
        # left null so the breakdown sums to the Session count.
        "session_relations": {
            str(relation): int(count)
            for relation, count in conn.execute(
                f"""
                SELECT COALESCE(session_relation_kind,'top_level'),COUNT(*)
                FROM sessions WHERE id IN ({placeholders})
                GROUP BY COALESCE(session_relation_kind,'top_level')
                """,
                ids,
            )
        },
        "initiation_kinds": {
            str(kind): int(count)
            for kind, count in conn.execute(
                f"""
                SELECT initiation_kind,COUNT(*) FROM interactions
                WHERE session_id IN ({placeholders})
                GROUP BY initiation_kind
                """,
                ids,
            )
        },
    }


CONFIGURATION_FILTER_COLUMNS = {
    "models": "model_name_exact",
    "model_providers": "provider",
    "model_families": "model_family",
    "model_revisions": "model_revision",
    "reasoning_efforts": "reasoning_effort",
    "speed_tiers": "speed_tier",
    "service_tiers": "service_tier",
    "model_modes": "mode",
}


def _configuration_predicates(
    filters: dict[str, Any],
    where: list[str],
    params: list[Any],
    *,
    alias: str = "mc",
) -> None:
    for filter_name, column in CONFIGURATION_FILTER_COLUMNS.items():
        _in_clause(
            f"{alias}.{column}",
            filters.get(filter_name) or [],
            where,
            params,
        )


def _event_predicate(filters: dict[str, Any]) -> tuple[str, list[Any]]:
    where: list[str] = []
    params: list[Any] = []
    _in_clause("s.global_id", filters.get("session_ids") or [], where, params)
    _in_clause("e.global_id", filters.get("event_ids") or [], where, params)
    _in_clause("e.interaction_id", filters.get("interaction_ids") or [], where, params)
    _in_clause("e.model_turn_id", filters.get("model_turn_ids") or [], where, params)
    _in_clause("s.source_system_id", filters.get("source_system_ids") or [], where, params)
    _in_clause("e.event_kind", filters.get("event_kinds") or [], where, params)
    _in_clause("e.tool_name", filters.get("tool_names") or [], where, params)
    _in_clause("e.actor_kind", filters.get("actor_kinds") or [], where, params)
    _in_clause("e.content_role", filters.get("content_roles") or [], where, params)
    _in_clause("e.origin_kind", filters.get("origin_kinds") or [], where, params)
    _in_clause(
        "s.parent_session_id",
        filters.get("parent_session_ids") or [],
        where,
        params,
    )
    _in_clause(
        "s.session_relation_kind",
        filters.get("session_relation_kinds") or [],
        where,
        params,
    )
    _in_clause(
        "i.initiation_kind",
        filters.get("initiation_kinds") or [],
        where,
        params,
    )
    statuses = filters.get("statuses") or []
    if statuses:
        _in_clause("COALESCE(e.normalized_status,e.source_status)", statuses, where, params)
    _configuration_predicates(filters, where, params)
    if filters.get("since") is not None:
        where.append("COALESCE(e.event_at,e.timestamp)>=?")
        params.append(filters["since"])
    if filters.get("until") is not None:
        where.append("COALESCE(e.event_at,e.timestamp)<=?")
        params.append(filters["until"])
    if filters.get("artifact"):
        where.append("e.artifact_path LIKE ? ESCAPE '\\'")
        params.append(f"%{_like_literal(filters['artifact'])}%")
    if filters.get("text"):
        where.append(
            "(e.content LIKE ? ESCAPE '\\' "
            "OR e.tool_input LIKE ? ESCAPE '\\' "
            "OR e.tool_output LIKE ? ESCAPE '\\' "
            "OR e.artifact_path LIKE ? ESCAPE '\\')"
        )
        params.extend([f"%{_like_literal(filters['text'])}%"] * 4)
    return (" AND ".join(where) if where else "1"), params


def _expanded_event_predicate(
    conn,
    request: dict[str, Any],
) -> tuple[str, list[Any]]:
    """Resolve explicit expansion/window selectors inside one store."""
    expand = request.get("expand")
    before = request.get("sequence_before", 0)
    after = request.get("sequence_after", 0)
    if not expand and not before and not after:
        return _event_predicate(request["filters"])

    filters = request["filters"]
    scope_filters = {
        key: filters[key]
        for key in ("session_ids", "source_system_ids")
        if key in filters
    }
    scope_sql, scope_params = _event_predicate(scope_filters)
    event_ids = filters.get("event_ids") or []
    interaction_ids = set(filters.get("interaction_ids") or [])
    model_turn_ids = set(filters.get("model_turn_ids") or [])
    anchors = []
    if event_ids:
        placeholders = ",".join("?" for _ in event_ids)
        anchors = list(conn.execute(
            f"""
            SELECT global_id,session_id,sequence_no,interaction_id,model_turn_id
            FROM events WHERE global_id IN ({placeholders})
            """,
            event_ids,
        ))
    branches: list[str] = []
    branch_params: list[Any] = []
    if event_ids:
        branches.append(
            f"e.global_id IN ({','.join('?' for _ in event_ids)})"
        )
        branch_params.extend(event_ids)
    if expand == "interaction":
        interaction_ids.update(
            row["interaction_id"] for row in anchors if row["interaction_id"]
        )
    if expand == "model_turn":
        model_turn_ids.update(
            row["model_turn_id"] for row in anchors if row["model_turn_id"]
        )
    if interaction_ids:
        ordered = sorted(interaction_ids)
        branches.append(
            f"e.interaction_id IN ({','.join('?' for _ in ordered)})"
        )
        branch_params.extend(ordered)
    if model_turn_ids:
        ordered = sorted(model_turn_ids)
        branches.append(
            f"e.model_turn_id IN ({','.join('?' for _ in ordered)})"
        )
        branch_params.extend(ordered)
    if before or after:
        for row in anchors:
            sequence = row["sequence_no"]
            if sequence is None:
                continue
            branches.append(
                "(e.session_id=? AND e.sequence_no BETWEEN ? AND ?)"
            )
            branch_params.extend((
                row["session_id"],
                max(1, int(sequence) - before),
                int(sequence) + after,
            ))
    if not branches:
        return "0", []
    return (
        f"({scope_sql}) AND ({' OR '.join(branches)})",
        [*scope_params, *branch_params],
    )


def store_project_ids(conn: sqlite3.Connection) -> list[str]:
    """The Project identities one store holds, in stable order.

    A store normally holds one Project, but a merged or relocated store can
    hold several, and both provenance and selection report them. Ordered by
    identity so two runs over the same store agree.
    """
    return [str(row[0]) for row in conn.execute("SELECT id FROM projects ORDER BY id")]


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
    project_ids = store_project_ids(conn)
    return {
        "project_ids": project_ids,
        "project_path": str(store["project_path"]),
        "store_path": str(store["path"]),
        "snapshot_id": meta.get("snapshot_id"),
        "snapshot_created_at": meta.get("snapshot_created_at"),
        "package_digest": meta.get("package_digest"),
        "format_version": meta.get("format_version"),
        "decoder_version": meta.get("decoder_version"),
        "validator_version": meta.get("validator_version"),
        "policy_sha256": policies,
        "source_availability": availability,
        "selection_kind": store.get("selection_kind"),
        "selection_sha256": store.get("selection_sha256"),
        "resolved_selection_sha256": store.get(
            "resolved_selection_sha256"
        ),
    }


def selected_project_ids(stores: list[dict[str, Any]]) -> list[str]:
    """Return the stable Project IDs the selected stores contain."""
    selected: set[str] = set()
    for store in stores:
        selected.update(
            str(row[0]) for row in store["conn"].execute("SELECT id FROM projects")
        )
    return sorted(selected)


def _store_snapshot_id(store: dict[str, Any]) -> str | None:
    if store.get("snapshot_id"):
        return str(store["snapshot_id"])
    row = store["conn"].execute(
        "SELECT value FROM store_meta WHERE key='snapshot_id'"
    ).fetchone()
    return str(row[0]) if row and row[0] else None


def selected_project_snapshots(
    stores: list[dict[str, Any]],
) -> list[dict[str, str | None]]:
    """Return canonical Project/snapshot observation inputs."""
    selected = []
    for store in stores:
        project_ids = store_project_ids(store["conn"])
        snapshot_id = _store_snapshot_id(store)
        selected.extend({
            "project_id": project_id,
            "snapshot_id": snapshot_id,
        } for project_id in project_ids)
    unique = {
        (item["project_id"], item["snapshot_id"]): item
        for item in selected
    }
    return sorted(
        unique.values(),
        key=lambda item: (item["project_id"], item["snapshot_id"] or ""),
    )


def _observation_id(
    store: dict[str, Any], entity_kind: str, global_id: str | None,
) -> str | None:
    snapshot_id = _store_snapshot_id(store)
    if not snapshot_id or not global_id:
        return None
    digest = content_hash({
        "project_id": store.get("project_id"),
        "snapshot_id": snapshot_id,
        "store": Path(store["path"]).name,
        "entity_kind": entity_kind,
        "global_id": global_id,
    }).removeprefix("sha256:")
    return f"codess:observation:sha256:{digest}"


def _event_heap_sort_key(record, store: dict[str, Any]) -> tuple:
    timestamp = record["event_at"]
    try:
        ordered_time = float(timestamp) if timestamp is not None else 0.0
    except (TypeError, ValueError):
        ordered_time = 0.0
    return (
        timestamp is None,
        ordered_time,
        record["global_session_id"] or "",
        record["sequence_no"] if record["sequence_no"] is not None else -1,
        record["global_id"] or "",
        str(store.get("project_id") or store["project_path"]),
        str(store["path"]),
    )


def _event_rows(stores: list[dict[str, Any]], request: dict[str, Any]) -> tuple[list[dict], dict]:
    if request.get("limit") == 0:
        return [], {
            "matched_rows_read": 0, "returned_rows": 0,
            "returned_content_bytes": 0, "truncated": False,
            "truncation_reasons": [],
        }
    rows: list[dict[str, Any]] = []
    scanned = 0
    byte_limit = request.get("byte_limit")
    used_bytes = 0
    byte_truncated = False
    row_limit_reached = False
    row_limit = request.get("limit")
    limit_sql = " LIMIT ?" if row_limit is not None else ""
    sql_template = """
        SELECT e.global_id,e.event_id,s.global_id AS global_session_id,e.session_id,
               s.project_id,s.source_system_id,s.project_path,
               e.sequence_no,e.interaction_id,
               e.model_turn_id,e.event_kind,e.actor_kind,e.content_role,e.origin_kind,
               COALESCE(e.event_at,e.timestamp) AS event_at,e.event_at_basis,
               e.source_record_locator,e.source_record_type,e.source_record_subtype,
               e.content,e.content_len,e.tool_name,e.tool_input,e.tool_output,
               COALESCE(e.normalized_status,e.source_status) AS status,
               e.artifact_path,e.source_file,
               mc.provider,mc.model_family,mc.model_name_exact,
               mc.model_revision,mc.reasoning_effort,mc.speed_tier,
               mc.service_tier,mc.mode,e.metadata
        FROM events e JOIN sessions s ON s.id=e.session_id
        LEFT JOIN interactions i ON i.id=e.interaction_id
        LEFT JOIN model_turns mt ON mt.id=e.model_turn_id
        LEFT JOIN model_configurations mc ON mc.id=mt.model_config_id
        WHERE {predicate}
        ORDER BY (COALESCE(e.event_at,e.timestamp) IS NULL),
                 COALESCE(e.event_at,e.timestamp),s.global_id,
                 e.sequence_no,e.global_id,e.id
        {limit_sql}
    """

    heap: list[tuple[tuple, int, Any, Any, dict[str, Any]]] = []
    for store_index, store in enumerate(stores):
        predicate, params = _expanded_event_predicate(
            store["conn"], request
        )
        sql = sql_template.format(
            predicate=predicate,
            limit_sql=limit_sql,
        )
        query_params = [
            *params,
            *([row_limit] if row_limit is not None else []),
        ]
        iterator = iter(store["conn"].execute(sql, query_params))
        record = next(iterator, None)
        if record is not None:
            heapq.heappush(
                heap,
                (_event_heap_sort_key(record, store), store_index, record, iterator, store),
            )

    while heap:
        _, store_index, record, iterator, store = heapq.heappop(heap)
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
        try:
            event_metadata = json.loads(record["metadata"] or "{}")
        except json.JSONDecodeError:
            event_metadata = {}
        configuration_provenance = (
            event_metadata.get("configuration_provenance")
            if isinstance(event_metadata, dict) else None
        )
        if not isinstance(configuration_provenance, dict):
            configuration_provenance = None
        configuration_provenance_scope = (
            event_metadata.get("configuration_provenance_scope")
            if isinstance(event_metadata, dict) else None
        )
        if not isinstance(configuration_provenance_scope, dict):
            configuration_provenance_scope = None
        rows.append({
            "observation_id": _observation_id(
                store, "event", record["global_id"]
            ),
            "global_event_id": record["global_id"],
            "event_id": record["event_id"],
            "global_session_id": record["global_session_id"],
            "session_id": record["session_id"],
            "project_id": record["project_id"] or store.get("project_id"),
            "snapshot_id": _store_snapshot_id(store),
            "project_path": str(store["project_path"]),
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
            "model_provider": record["provider"],
            "model_family": record["model_family"],
            "model_revision": record["model_revision"],
            "reasoning_effort": record["reasoning_effort"],
            "speed_tier": record["speed_tier"],
            "service_tier": record["service_tier"],
            "model_mode": record["mode"],
            "configuration_provenance": configuration_provenance,
            "configuration_provenance_scope": (
                configuration_provenance_scope
            ),
        })
        if row_limit is not None and len(rows) >= row_limit:
            row_limit_reached = True
            break
        following = next(iterator, None)
        if following is not None:
            heapq.heappush(
                heap,
                (
                    _event_heap_sort_key(following, store),
                    store_index,
                    following,
                    iterator,
                    store,
                ),
            )
    facet_limit = request.get("facet_limit", 50)
    facets: dict[str, list[dict[str, Any]]] = {}
    for field in (
        "source_system_id", "event_kind", "actor_kind", "content_role",
        "origin_kind", "tool_name", "status", "model", "model_provider",
        "model_family", "model_revision", "reasoning_effort", "speed_tier",
        "service_tier", "model_mode",
    ):
        counts: dict[str, int] = {}
        for row in rows:
            value = row.get(field)
            if value is not None:
                counts[str(value)] = counts.get(str(value), 0) + 1
        facets[field] = [
            {"value": value, "count": count}
            for value, count in sorted(
                counts.items(), key=lambda item: (-item[1], item[0])
            )[:facet_limit]
        ]

    repetition_groups: list[dict[str, Any]] = []
    if request.get("group_repetitions"):
        grouped: dict[tuple, list[dict[str, Any]]] = {}
        for row in rows:
            if not row["content"] or not row["content_complete"]:
                continue
            key = (
                row["content"], row["event_kind"], row["actor_kind"],
                row["content_role"], row["tool_name"], row["status"],
                row["artifact_path"],
            )
            grouped.setdefault(key, []).append(row)
        for key, members in grouped.items():
            if len(members) < 2:
                continue
            times = [
                row["event_at"] for row in members
                if row["event_at"] is not None
            ]
            repetition_groups.append({
                "group_id": content_hash({
                    "content": key[0],
                    "event_kind": key[1],
                    "actor_kind": key[2],
                    "content_role": key[3],
                    "tool_name": key[4],
                    "status": key[5],
                    "artifact_path": key[6],
                }),
                "occurrences": len(members),
                "first_event_at": min(times) if times else None,
                "last_event_at": max(times) if times else None,
                "global_event_ids": sorted(
                    row["global_event_id"] for row in members
                ),
                "observation_ids": sorted(
                    row["observation_id"] for row in members
                    if row.get("observation_id")
                ),
                "event_kind": key[1],
                "actor_kind": key[2],
                "content_role": key[3],
                "tool_name": key[4],
                "status": key[5],
                "artifact_path": key[6],
            })
        repetition_groups.sort(
            key=lambda item: (
                -item["occurrences"],
                item["group_id"],
            )
        )
        repetition_groups = repetition_groups[:facet_limit]

    observations_by_snapshot: dict[str, int] = {}
    global_occurrences: dict[str, int] = {}
    for row in rows:
        snapshot = row.get("snapshot_id") or "working"
        observations_by_snapshot[snapshot] = (
            observations_by_snapshot.get(snapshot, 0) + 1
        )
        identity = row.get("global_event_id")
        if identity:
            global_occurrences[identity] = global_occurrences.get(identity, 0) + 1
    duplicate_global_ids = sorted(
        identity
        for identity, count in global_occurrences.items()
        if count > 1
    )
    return rows, {
        "matched_rows_read": scanned,
        "returned_rows": len(rows),
        "returned_content_bytes": used_bytes,
        "facets_from_returned_rows": facets,
        "repetition_groups_from_complete_returned_content": repetition_groups,
        "observations_by_snapshot": dict(sorted(observations_by_snapshot.items())),
        "duplicate_global_event_ids": duplicate_global_ids[:facet_limit],
        "duplicate_global_event_id_count": len(duplicate_global_ids),
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
    _in_clause(
        "s.parent_session_id",
        filters.get("parent_session_ids") or [],
        where,
        params,
    )
    _in_clause(
        "s.session_relation_kind",
        filters.get("session_relation_kinds") or [],
        where,
        params,
    )
    configuration_where: list[str] = []
    configuration_params: list[Any] = []
    _configuration_predicates(
        filters, configuration_where, configuration_params
    )
    if configuration_where:
        where.append(
            "EXISTS (SELECT 1 FROM model_configurations mc WHERE "
            "(mc.id=s.default_model_config_id OR EXISTS ("
            "SELECT 1 FROM model_turns mt WHERE mt.session_id=s.id "
            "AND mt.model_config_id=mc.id)) AND "
            + " AND ".join(configuration_where)
            + ")"
        )
        params.extend(configuration_params)
    if filters.get("since") is not None:
        where.append("COALESCE(s.ended_at,s.started_at,s.source_mtime)>=?")
        params.append(filters["since"])
    if filters.get("until") is not None:
        where.append("COALESCE(s.started_at,s.ended_at,s.source_mtime)<=?")
        params.append(filters["until"])
    predicate = " AND ".join(where) if where else "1"
    rows = []
    for store in stores:
        session_columns = column_names(store["conn"], "sessions")
        path_obsolete = (
            "s.path_obsolete" if "path_obsolete" in session_columns
            else "0 AS path_obsolete"
        )
        for row in store["conn"].execute(f"""
            SELECT s.global_id,s.id,s.source_system_id,s.vendor_session_id,
                   s.vendor_name,s.product_name,s.harness_name,s.harness_version,
                   s.started_at,s.ended_at,s.time_basis,s.source_cwd,
                   s.project_id,s.project_path,s.parent_session_id,
                   s.session_relation_kind,
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
                "observation_id": _observation_id(
                    store, "session", item["global_id"]
                ),
                "snapshot_id": _store_snapshot_id(store),
                "project_path": str(store["project_path"]),
                "source_project_path": source_project_path,
            })
    rows.sort(key=lambda row: (-(row["ended_at"] or row["started_at"] or 0), row["global_id"]))
    matched = len(rows)
    if request.get("limit") is not None:
        rows = rows[:request["limit"]]
    observations_by_snapshot: dict[str, int] = {}
    global_occurrences: dict[str, int] = {}
    for row in rows:
        snapshot = row.get("snapshot_id") or "working"
        observations_by_snapshot[snapshot] = (
            observations_by_snapshot.get(snapshot, 0) + 1
        )
        identity = row.get("global_id")
        if identity:
            global_occurrences[identity] = global_occurrences.get(identity, 0) + 1
    duplicate_global_ids = sorted(
        identity
        for identity, count in global_occurrences.items()
        if count > 1
    )
    return rows, {
        "matched_rows": matched,
        "returned_rows": len(rows),
        "observations_by_snapshot": dict(sorted(observations_by_snapshot.items())),
        "duplicate_global_session_ids": duplicate_global_ids[
            :request.get("facet_limit", 50)
        ],
        "duplicate_global_session_id_count": len(duplicate_global_ids),
        "truncated": len(rows) < matched,
        "truncation_reasons": ["row_limit"] if len(rows) < matched else [],
    }


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
    providers: dict[str, int] = {}
    families: dict[str, int] = {}
    efforts: dict[str, int] = {}
    speeds: dict[str, int] = {}
    service_tiers: dict[str, int] = {}
    modes: dict[str, int] = {}
    configurations: set[tuple] = set()
    session_relations: dict[str, int] = {}
    initiation_kinds: dict[str, int] = {}
    daily: dict[str, dict[str, Any]] = {}
    monthly_tool_call_interactions: dict[str, set[tuple[int, str]]] = {}
    monthly_tool_result_interactions: dict[str, set[tuple[int, str]]] = {}
    latest_model_response_by_interaction: dict[tuple[int, str], float] = {}

    def day_bucket(timestamp: float) -> dict[str, Any]:
        day = datetime.fromtimestamp(
            timestamp / 1000, tz=timezone.utc
        ).date().isoformat()
        return daily.setdefault(day, {
            "day": day,
            "events": 0,
            "content_characters": 0,
            "sessions": set(),
            "interactions": set(),
            "first_event_at": timestamp,
            "last_event_at": timestamp,
            "first_human_prompt_at": None,
            "last_human_prompt_at": None,
            "last_human_prompt_interaction_key": None,
            "human_prompts": 0,
            "human_prompt_characters": 0,
            "model_outputs": 0,
            "model_output_characters": 0,
            "human_prompt_interactions": set(),
            "tool_calls": 0,
            "tool_results": 0,
            "tool_input_characters": 0,
            "tool_output_characters": 0,
            "tool_call_interactions": set(),
            "tool_result_interactions": set(),
            "tool_calls_by_name": {},
            "actor_activity": {},
            "session_relation_activity": {},
        })

    def actor_bucket(bucket: dict[str, Any], actor: str) -> dict[str, Any]:
        return bucket["actor_activity"].setdefault(actor, {
            "events": 0,
            "content_characters": 0,
            "sessions": set(),
            "interactions": set(),
            "first_event_at": None,
            "last_event_at": None,
        })

    def relation_bucket(bucket: dict[str, Any], relation: str) -> dict[str, Any]:
        return bucket["session_relation_activity"].setdefault(relation, {
            "events": 0,
            "content_characters": 0,
            "sessions": set(),
            "interactions": set(),
            "actor_events": {},
        })

    for store_index, store in enumerate(stores):
        conn = store["conn"]
        selected_sessions = {row[0] for row in conn.execute(f"""
            SELECT DISTINCT s.id FROM events e JOIN sessions s ON s.id=e.session_id
            LEFT JOIN interactions i ON i.id=e.interaction_id
            LEFT JOIN model_turns mt ON mt.id=e.model_turn_id
            LEFT JOIN model_configurations mc ON mc.id=mt.model_config_id
            WHERE {predicate}
        """, params)}
        totals["sessions"] += len(selected_sessions)
        structure = session_structure_counts(conn, selected_sessions)
        totals["interactions"] += structure["interactions"]
        totals["model_turns"] += structure["model_turns"]
        for relation, count in structure["session_relations"].items():
            session_relations[relation] = session_relations.get(relation, 0) + count
        for initiation, count in structure["initiation_kinds"].items():
            initiation_kinds[initiation] = initiation_kinds.get(initiation, 0) + count
        for row in conn.execute(f"""
            SELECT s.source_system_id,e.event_kind,COALESCE(e.event_at,e.timestamp),
                   LENGTH(COALESCE(e.content,'')),e.tool_name,e.artifact_path,
                   mc.provider,mc.model_family,mc.model_name_exact,mc.model_revision,
                   mc.reasoning_effort,mc.speed_tier,mc.service_tier,mc.mode,
                   e.actor_kind,e.content_role,s.global_id,e.interaction_id,e.global_id,
                   COALESCE(s.session_relation_kind,'top_level'),
                   LENGTH(COALESCE(e.tool_input,'')),
                   LENGTH(COALESCE(e.tool_output,''))
            FROM events e JOIN sessions s ON s.id=e.session_id
            LEFT JOIN interactions i ON i.id=e.interaction_id
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
                timestamp = float(row[2])
                times.append(timestamp)
                bucket = day_bucket(timestamp)
                month_key = datetime.fromtimestamp(
                    timestamp / 1000, tz=timezone.utc
                ).strftime("%Y-%m")
                bucket["events"] += 1
                bucket["content_characters"] += int(row[3])
                bucket["sessions"].add((store_index, row[16]))
                if row[17]:
                    bucket["interactions"].add((store_index, row[17]))
                bucket["first_event_at"] = min(
                    bucket["first_event_at"], timestamp
                )
                bucket["last_event_at"] = max(
                    bucket["last_event_at"], timestamp
                )
                actor = row[14] or "unknown"
                activity = actor_bucket(bucket, actor)
                activity["events"] += 1
                activity["content_characters"] += int(row[3])
                activity["sessions"].add((store_index, row[16]))
                if row[17]:
                    activity["interactions"].add((store_index, row[17]))
                activity["first_event_at"] = (
                    timestamp if activity["first_event_at"] is None
                    else min(activity["first_event_at"], timestamp)
                )
                activity["last_event_at"] = (
                    timestamp if activity["last_event_at"] is None
                    else max(activity["last_event_at"], timestamp)
                )
                relation = row[19] or "top_level"
                relation_activity = relation_bucket(bucket, relation)
                relation_activity["events"] += 1
                relation_activity["content_characters"] += int(row[3])
                relation_activity["sessions"].add((store_index, row[16]))
                if row[17]:
                    relation_activity["interactions"].add(
                        (store_index, row[17])
                    )
                relation_activity["actor_events"][actor] = (
                    relation_activity["actor_events"].get(actor, 0) + 1
                )
                if row[1] == "tool.call":
                    bucket["tool_calls"] += 1
                    bucket["tool_input_characters"] += int(row[20])
                    if row[17]:
                        interaction_key = (store_index, row[17])
                        bucket["tool_call_interactions"].add(interaction_key)
                        monthly_tool_call_interactions.setdefault(
                            month_key, set()
                        ).add(interaction_key)
                    tool_name = row[4] or "unknown"
                    bucket["tool_calls_by_name"][tool_name] = (
                        bucket["tool_calls_by_name"].get(tool_name, 0) + 1
                    )
                elif row[1] == "tool.result":
                    bucket["tool_results"] += 1
                    bucket["tool_output_characters"] += int(row[21])
                    if row[17]:
                        interaction_key = (store_index, row[17])
                        bucket["tool_result_interactions"].add(interaction_key)
                        monthly_tool_result_interactions.setdefault(
                            month_key, set()
                        ).add(interaction_key)
                if actor == "human" and (
                    row[15] == "prompt" or row[1] == "message.prompt"
                ):
                    bucket["human_prompts"] += 1
                    bucket["human_prompt_characters"] += int(row[3])
                    if bucket["first_human_prompt_at"] is None:
                        bucket["first_human_prompt_at"] = timestamp
                    bucket["first_human_prompt_at"] = min(
                        bucket["first_human_prompt_at"], timestamp
                    )
                    if (
                        bucket["last_human_prompt_at"] is None
                        or timestamp >= bucket["last_human_prompt_at"]
                    ):
                        bucket["last_human_prompt_at"] = timestamp
                        bucket["last_human_prompt_interaction_key"] = (
                            (store_index, row[17]) if row[17] else None
                        )
                    if row[17]:
                        bucket["human_prompt_interactions"].add(
                            (store_index, row[17])
                        )
                if actor == "model" and (
                    row[15] == "response" or row[1] == "message.response"
                ):
                    bucket["model_outputs"] += 1
                    bucket["model_output_characters"] += int(row[3])
                    if row[17]:
                        key = (store_index, row[17])
                        latest_model_response_by_interaction[key] = max(
                            timestamp,
                            latest_model_response_by_interaction.get(
                                key, timestamp
                            ),
                        )
            if row[8]:
                models[row[8]] = models.get(row[8], 0) + 1
                configurations.add(tuple(row[6:14]))
            for value, bucket in (
                (row[6], providers), (row[7], families),
                (row[10], efforts), (row[11], speeds),
                (row[12], service_tiers), (row[13], modes),
            ):
                if value:
                    bucket[value] = bucket.get(value, 0) + 1
    times.sort()
    span = (times[-1] - times[0]) if len(times) > 1 else 0
    gaps = [max(0.0, right - left) for left, right in zip(times, times[1:])]
    caps = request.get("active_gap_caps_minutes", [5, 30, 120])
    active = {
        str(cap): sum(min(gap, cap * 60_000) for gap in gaps)
        for cap in caps
    }
    gap_histogram = {
        "0_to_1_minute": sum(gap <= 60_000 for gap in gaps),
        "over_1_to_5_minutes": sum(60_000 < gap <= 300_000 for gap in gaps),
        "over_5_to_30_minutes": sum(
            300_000 < gap <= 1_800_000 for gap in gaps
        ),
        "over_30_to_120_minutes": sum(
            1_800_000 < gap <= 7_200_000 for gap in gaps
        ),
        "over_120_minutes": sum(gap > 7_200_000 for gap in gaps),
    }
    events_by_month: dict[str, int] = {}
    for timestamp in times:
        month = datetime.fromtimestamp(
            timestamp / 1000, tz=timezone.utc
        ).strftime("%Y-%m")
        events_by_month[month] = events_by_month.get(month, 0) + 1
    daily_activity: list[dict[str, Any]] = []
    tool_activity_by_month: dict[str, dict[str, int]] = {}
    core_actors = ("human", "harness", "tool", "model", "agent")
    combined_actors = {"harness", "model", "agent"}
    for day in sorted(daily):
        bucket = daily[day]
        actor_rows: dict[str, dict[str, Any]] = {}
        for actor in sorted(set(core_actors) | set(bucket["actor_activity"])):
            activity = bucket["actor_activity"].get(actor, {})
            actor_rows[actor] = {
                "events": int(activity.get("events", 0)),
                "content_characters": int(
                    activity.get("content_characters", 0)
                ),
                "sessions": len(activity.get("sessions", set())),
                "interactions": len(activity.get("interactions", set())),
                "first_event_at": activity.get("first_event_at"),
                "last_event_at": activity.get("last_event_at"),
                "observed_span_ms": (
                    activity["last_event_at"] - activity["first_event_at"]
                    if activity.get("first_event_at") is not None
                    and activity.get("last_event_at") is not None
                    else None
                ),
            }
        automated_events = sum(
            actor_rows[actor]["events"] for actor in combined_actors
        )
        automated_characters = sum(
            actor_rows[actor]["content_characters"]
            for actor in combined_actors
        )
        automated_sessions: set[str] = set()
        automated_interactions: set[str] = set()
        for actor in combined_actors:
            activity = bucket["actor_activity"].get(actor, {})
            automated_sessions.update(activity.get("sessions", set()))
            automated_interactions.update(activity.get("interactions", set()))
        last_prompt_at = bucket["last_human_prompt_at"]
        response_at = latest_model_response_by_interaction.get(
            bucket["last_human_prompt_interaction_key"]
        )
        if (
            response_at is not None
            and last_prompt_at is not None
            and response_at < last_prompt_at
        ):
            response_at = None
        first_prompt_at = bucket["first_human_prompt_at"]
        prompt_count = bucket["human_prompts"]
        subagent_activity = bucket["session_relation_activity"].get(
            "subagent", {}
        )
        daily_activity.append({
            "day": day,
            "events": bucket["events"],
            "content_characters": bucket["content_characters"],
            "sessions": len(bucket["sessions"]),
            "interactions": len(bucket["interactions"]),
            "first_event_at": bucket["first_event_at"],
            "last_event_at": bucket["last_event_at"],
            "observed_event_span_ms": (
                bucket["last_event_at"] - bucket["first_event_at"]
            ),
            "human_prompts": prompt_count,
            "human_prompt_characters": bucket["human_prompt_characters"],
            "model_outputs": bucket["model_outputs"],
            "model_output_characters": bucket["model_output_characters"],
            "human_initiated_interactions": len(
                bucket["human_prompt_interactions"]
            ),
            "human_model_interactions": len(
                bucket["human_prompt_interactions"]
                & set(latest_model_response_by_interaction)
            ),
            "first_human_prompt_at": first_prompt_at,
            "last_human_prompt_at": last_prompt_at,
            "human_prompt_span_ms": (
                last_prompt_at - first_prompt_at
                if first_prompt_at is not None and last_prompt_at is not None
                else None
            ),
            "final_model_output_for_last_prompt_at": response_at,
            "last_prompt_to_final_model_output_ms": (
                response_at - last_prompt_at
                if response_at is not None and last_prompt_at is not None
                else None
            ),
            "first_prompt_to_final_model_output_ms": (
                response_at - first_prompt_at
                if response_at is not None and first_prompt_at is not None
                else None
            ),
            "actor_activity": actor_rows,
            "combined_harness_model_agent_activity": {
                "events": automated_events,
                "content_characters": automated_characters,
                "sessions": len(automated_sessions),
                "interactions": len(automated_interactions),
            },
            "tool_activity": {
                "calls": bucket["tool_calls"],
                "results": bucket["tool_results"],
                "input_characters": bucket["tool_input_characters"],
                "output_characters": bucket["tool_output_characters"],
                "call_interactions": len(
                    bucket["tool_call_interactions"]
                ),
                "result_interactions": len(
                    bucket["tool_result_interactions"]
                ),
                "calls_by_name": dict(sorted(
                    bucket["tool_calls_by_name"].items(),
                    key=lambda item: (-item[1], item[0]),
                )),
            },
            "subagent_session_activity": {
                "events": int(subagent_activity.get("events", 0)),
                "content_characters": int(
                    subagent_activity.get("content_characters", 0)
                ),
                "sessions": len(subagent_activity.get("sessions", set())),
                "interactions": len(
                    subagent_activity.get("interactions", set())
                ),
                "actor_events": dict(sorted(
                    subagent_activity.get("actor_events", {}).items()
                )),
            },
        })
        month_tools = tool_activity_by_month.setdefault(day[:7], {
            "calls": 0,
            "results": 0,
            "input_characters": 0,
            "output_characters": 0,
            "call_interactions": 0,
            "result_interactions": 0,
        })
        month_tools["calls"] += bucket["tool_calls"]
        month_tools["results"] += bucket["tool_results"]
        month_tools["input_characters"] += bucket[
            "tool_input_characters"
        ]
        month_tools["output_characters"] += bucket[
            "tool_output_characters"
        ]
        month_tools["call_interactions"] = len(
            monthly_tool_call_interactions.get(day[:7], set())
        )
        month_tools["result_interactions"] = len(
            monthly_tool_result_interactions.get(day[:7], set())
        )
    daily_activity_total_days = len(daily_activity)
    daily_activity_limit = request.get("facet_limit", 50)
    daily_activity = daily_activity[-daily_activity_limit:]
    summary = {
        **totals,
        "model_configurations": len(configurations),
        "first_event_at": times[0] if times else None,
        "last_event_at": times[-1] if times else None,
        "elapsed_span_ms": span,
        "event_days": len({datetime.fromtimestamp(ts / 1000, tz=timezone.utc).date().isoformat() for ts in times}),
        "active_time_estimates_ms_by_gap_cap_minutes": active,
        "event_gap_histogram": gap_histogram,
        "events_by_utc_month": dict(sorted(events_by_month.items())),
        "tool_activity_by_utc_month": dict(
            sorted(tool_activity_by_month.items())
        ),
        "daily_exchange_activity_utc": daily_activity,
        "daily_exchange_activity_total_days": daily_activity_total_days,
        "daily_exchange_activity_limit": daily_activity_limit,
        "daily_exchange_activity_truncated": (
            daily_activity_total_days > daily_activity_limit
        ),
        "vendors_by_event": dict(sorted(vendors.items())),
        "event_kinds": dict(sorted(kinds.items(), key=lambda item: (-item[1], item[0]))),
        "models_by_event": dict(sorted(models.items(), key=lambda item: (-item[1], item[0]))),
        "model_providers_by_event": dict(sorted(
            providers.items(), key=lambda item: (-item[1], item[0])
        )),
        "model_families_by_event": dict(sorted(
            families.items(), key=lambda item: (-item[1], item[0])
        )),
        "reasoning_efforts_by_event": dict(sorted(
            efforts.items(), key=lambda item: (-item[1], item[0])
        )),
        "speed_tiers_by_event": dict(sorted(
            speeds.items(), key=lambda item: (-item[1], item[0])
        )),
        "service_tiers_by_event": dict(sorted(
            service_tiers.items(), key=lambda item: (-item[1], item[0])
        )),
        "model_modes_by_event": dict(sorted(
            modes.items(), key=lambda item: (-item[1], item[0])
        )),
        "sessions_by_relation": dict(sorted(session_relations.items())),
        "interactions_by_initiation": dict(sorted(initiation_kinds.items())),
        "active_time_semantics": "sum of adjacent event gaps capped independently; sensitivity estimate, not observed or billable time",
        "daily_exchange_activity_semantics": (
            "UTC observations of normalized Events. Actor spans are first-to-last "
            "observed Event spans, not active, billable, or wall-clock work time. "
            "Counts and character lengths are observations; ratios and percentages "
            "are presentation-layer derivations. "
            "The final model output for the last prompt is the latest subsequent "
            "model response in the same normalized Interaction; null means that "
            "the selected evidence cannot establish one. Subagent Session "
            "activity is a separate relation-based view and retains, rather "
            "than reinterprets, each Event's normalized actor."
        ),
    }
    return [], summary


def execute(
    stores: list[dict[str, Any]],
    request: dict[str, Any],
    *,
    derivations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Execute a validated request; stores must contain read-only connections."""
    validate_request(request)
    canonical_request = json.loads(_canonical_bytes(request))
    observed_project_ids = selected_project_ids(stores)
    if (
        canonical_request["project_ids"]
        and canonical_request["project_ids"] != observed_project_ids
    ):
        raise QueryContractError("request project_ids do not match the selected store scope")
    observed_project_snapshots = selected_project_snapshots(stores)
    requested_project_snapshots = canonical_request.get(
        "project_snapshots", []
    )
    if (
        requested_project_snapshots
        and requested_project_snapshots != observed_project_snapshots
    ):
        raise QueryContractError(
            "request project_snapshots do not match the selected store scope"
        )
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
    result = {
        "format": RESULT_FORMAT,
        "processor": QUERY_PROCESSOR,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "request": canonical_request,
        "request_hash": content_hash(canonical_request),
        "provenance": [_store_provenance(store) for store in stores],
        "summary": summary,
        "rows": rows,
        "derivations": list(derivations or []),
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
            row.get("observation_id")
            or row.get("global_event_id")
            or row.get("global_session_id")
            for row in rows
        ],
        "summary": summary,
        "derivations": result["derivations"],
        "limitations": limitations,
    })
    return result


def compare_results(prior: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    def logical_request(result: dict[str, Any]) -> dict[str, Any]:
        request = json.loads(json.dumps(result.get("request") or {}))
        request.pop("snapshot_id", None)
        request.pop("project_snapshots", None)
        return request

    issues = []
    if prior.get("format") != RESULT_FORMAT or current.get("format") != RESULT_FORMAT:
        issues.append("both inputs must be codess.query-result/1")
    if content_hash(logical_request(prior)) != content_hash(
        logical_request(current)
    ):
        issues.append(
            "logical requests differ beyond Project snapshot observations"
        )

    def result_row_shapes(result: dict[str, Any]) -> set[str]:
        shapes: set[str] = set()
        rows = result.get("rows")
        if not isinstance(rows, list):
            return {"invalid"}
        for row in rows:
            if not isinstance(row, dict):
                shapes.add("invalid")
            elif row.get("global_event_id"):
                shapes.add("event")
            elif row.get("global_session_id"):
                shapes.add("session")
            else:
                shapes.add("anonymous")
        return shapes

    prior_shapes = result_row_shapes(prior)
    current_shapes = result_row_shapes(current)
    expected_shapes = {
        "sessions": "session",
        "events": "event",
        "search": "event",
    }
    prior_expected = expected_shapes.get(
        (prior.get("request") or {}).get("action")
    )
    current_expected = expected_shapes.get(
        (current.get("request") or {}).get("action")
    )
    if (
        prior_expected
        and (prior_shapes - {"invalid", prior_expected})
    ) or (
        current_expected
        and (current_shapes - {"invalid", current_expected})
    ):
        issues.append(
            "result rows do not match their request action: "
            f"prior={','.join(sorted(prior_shapes)) or 'empty'}; "
            f"current={','.join(sorted(current_shapes)) or 'empty'}"
        )
    if prior_shapes and current_shapes and prior_shapes != current_shapes:
        issues.append(
            "result row shapes differ: "
            f"prior={','.join(sorted(prior_shapes))}; "
            f"current={','.join(sorted(current_shapes))}"
        )
    if "invalid" in prior_shapes | current_shapes:
        issues.append("result rows must be arrays of objects")
    if len(prior_shapes) > 1 or len(current_shapes) > 1:
        issues.append(
            "heterogeneous result row shapes are not supported by comparison"
        )

    def rows_by_identity(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
        found: dict[str, dict[str, Any]] = {}
        repeated: set[str] = set()
        for index, row in enumerate(result.get("rows") or []):
            if not isinstance(row, dict):
                found[f"invalid:{index}:{content_hash(row)}"] = {
                    "_invalid_row": row
                }
                continue
            identity = str(
                row.get("global_event_id")
                or row.get("global_session_id")
                or f"row:{index}:{content_hash(row)}"
            )
            if identity in found:
                repeated.add(identity)
            found[identity] = row
        if repeated:
            issues.append(
                "input contains repeated stable identities from a historical "
                "union: " + ", ".join(sorted(repeated)[:10])
            )
        return found

    before, after = rows_by_identity(prior), rows_by_identity(current)
    common = set(before) & set(after)

    def logical_row(row: dict[str, Any]) -> dict[str, Any]:
        value = dict(row)
        for field in ("observation_id", "snapshot_id", "project_path"):
            value.pop(field, None)
        return value

    return {
        "format": "codess.query-comparison/1",
        "comparable": not issues,
        "comparison_issues": issues,
        "logical_request_hash": content_hash(logical_request(current)),
        "prior_result_hash": prior.get("result_hash"),
        "current_result_hash": current.get("result_hash"),
        "prior_project_snapshots": (
            prior.get("request") or {}
        ).get("project_snapshots", []),
        "current_project_snapshots": (
            current.get("request") or {}
        ).get("project_snapshots", []),
        "same_result_hash": prior.get("result_hash") == current.get("result_hash"),
        "added_ids": sorted(set(after) - set(before)),
        "removed_ids": sorted(set(before) - set(after)),
        "changed_ids": sorted(
            identity
            for identity in common
            if content_hash(logical_row(before[identity]))
            != content_hash(logical_row(after[identity]))
        ),
        "summary_changed": content_hash(prior.get("summary")) != content_hash(
            current.get("summary")
        ),
        "provenance_changed": content_hash(
            prior.get("provenance")
        ) != content_hash(current.get("provenance")),
    }
