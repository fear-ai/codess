"""Evidence-backed audit of discovered and invoked MCP-related tools.

**Reads core tables directly**, because the audit distinguishes an MCP tool
that was *discovered* from one that was *invoked*, which is a join over
`events` and `tool_invocations` against vendor tool-name spellings rather than
a selection the typed request contract expresses.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from codess.adapters.codex import process_file
from codess.project_catalog import catalog_readiness, durable_project_root
from codess.store import connect
from codess.tool_identity import bounded_source_call_id, is_mcp_tool
from codess.tool_result_status import application_failure_evidence

MCP_AUDIT_FORMAT = "codess.mcp-interaction-audit/1"
_MCP_NAMES = (
    "get_mcp_tools",
    "list_mcp_resources",
    "open_resource",
)


def _mcp_candidate(name: str) -> bool:
    """An MCP call by any vendor spelling, or one of the named built-in bridges."""
    return is_mcp_tool(name) or name.lower() in _MCP_NAMES


def _bounded(value: object, limit: int = 240) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).replace("\x00", "\uFFFD")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _json_value(value: object) -> object:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return value


def _is_empty_discovery(value: object) -> bool:
    decoded = _json_value(value)
    if isinstance(decoded, str):
        decoded = _json_value(decoded)
    if decoded in (None, "", [], {}):
        return True
    if isinstance(decoded, dict):
        for key in ("tools", "resources"):
            if key in decoded and decoded[key] == []:
                return True
        for key in ("result", "content", "output"):
            if key in decoded and _is_empty_discovery(decoded[key]):
                return True
    return False


def _discovery_details(value: object, depth: int = 0) -> dict[str, Any]:
    """Extract bounded target-server facts through known wrapper layers."""
    if depth > 6:
        return {}
    decoded = _json_value(value)
    if decoded is not value:
        return _discovery_details(decoded, depth + 1)
    if isinstance(decoded, list):
        for item in decoded:
            details = _discovery_details(item, depth + 1)
            if details:
                return details
        return {}
    if not isinstance(decoded, dict):
        return {}
    details = {}
    if decoded.get("server") is not None:
        details["target_server"] = _bounded(decoded["server"], 120)
    if decoded.get("serverStatus") is not None:
        details["target_server_status"] = _bounded(
            decoded["serverStatus"], 40
        )
    tools = decoded.get("tools")
    if isinstance(tools, list):
        details["discovered_tool_names"] = [
            str(item.get("name"))
            for item in tools[:40]
            if isinstance(item, dict) and item.get("name") is not None
        ]
    if details:
        return details
    for key in ("result", "content", "output", "message", "text"):
        if key in decoded:
            details = _discovery_details(decoded[key], depth + 1)
            if details:
                return details
    return {}


def classify_mcp_invocation(
    tool_name: str,
    *,
    source_status: str | None,
    normalized_status: str | None,
    result: object,
) -> tuple[str, str]:
    """Classify outcome and likely use without treating discovery as execution."""
    name = tool_name.lower()
    evidence = application_failure_evidence(result)
    status = (normalized_status or source_status or "").lower()
    if name in {"get_mcp_tools", "list_mcp_resources"}:
        if evidence:
            return "discovery_target_error", "tool/resource discovery"
        if _is_empty_discovery(result):
            return "discovery_empty", "tool/resource discovery"
        return "discovery_success", "tool/resource discovery"
    if status in {"cancelled", "denied"}:
        return f"operation_{status}", "operation"
    if evidence or status in {"failed", "error", "failure"}:
        return "operation_failure", "operation"
    if not result and status not in {"succeeded", "completed", "complete"}:
        return "ambiguous_no_result", "operation"
    if any(part in name for part in (
        "mark_chapter", "spawn_task", "dismiss_task", "rename_chat",
        "move_agent_to_root", "cursor_dialog",
    )):
        return "administrative_success", "session/workspace administration"
    if any(part in name for part in (
        "show_widget", "read_me", "open_resource",
    )):
        return "visualization_success", "visualization/resource display"
    if "list_connected_browsers" in name and _is_empty_discovery(result):
        return "diagnostic_empty", "browser availability diagnostic"
    return "operation_success", "operation"


def _store_records(
    db_path: Path,
    *,
    project: dict[str, Any],
    snapshot_id: str,
    include_excerpts: bool,
) -> list[dict[str, Any]]:
    conn = connect(db_path, read_only=True)
    try:
        rows = conn.execute(
            """
            SELECT ti.id,ti.session_id,ti.interaction_id,ti.source_call_id,
                   COALESCE(ti.source_tool_name,ti.canonical_tool_name) tool_name,
                   ti.input_json,ti.source_status,ti.normalized_status,
                   s.source,s.vendor_name,
                   tr.output_text,tr.output_json,tr.source_status result_source_status,
                   tr.normalized_status result_normalized_status
            FROM tool_invocations ti
            JOIN sessions s ON s.id=ti.session_id
            LEFT JOIN tool_results tr ON tr.invocation_id=ti.id
            ORDER BY ti.session_id,ti.source_started_at,ti.id,tr.sequence_no
            """
        ).fetchall()
        records = []
        seen: set[str] = set()
        for row in rows:
            tool_name = str(row["tool_name"] or "")
            if not _mcp_candidate(tool_name) or row["id"] in seen:
                continue
            seen.add(row["id"])
            result = (
                row["output_json"]
                if row["output_json"] is not None
                else row["output_text"]
            )
            outcome, likely_use = classify_mcp_invocation(
                tool_name,
                source_status=row["result_source_status"] or row["source_status"],
                normalized_status=(
                    row["result_normalized_status"]
                    or row["normalized_status"]
                ),
                result=result,
            )
            record = {
                "project_id": project["project_id"],
                "project_name": project.get("logical_name"),
                "snapshot_id": snapshot_id,
                "store": db_path.name,
                "vendor": row["vendor_name"] or row["source"],
                "session_id": row["session_id"],
                "interaction_id": row["interaction_id"],
                "invocation_id": row["id"],
                "source_call_id": (
                    bounded_source_call_id(row["source_call_id"])
                    if row["source_call_id"] is not None else None
                ),
                "tool_name": tool_name,
                "source_status": row["source_status"],
                "normalized_status": row["normalized_status"],
                "result_source_status": row["result_source_status"],
                "result_normalized_status": row["result_normalized_status"],
                "result_present": result not in (None, ""),
                "result_failure_evidence": application_failure_evidence(result),
                "classification": outcome,
                "likely_use": likely_use,
            }
            if tool_name.lower() in {
                "get_mcp_tools", "list_mcp_resources"
            }:
                record.update(_discovery_details(result))
            if include_excerpts:
                prompt = None
                if row["interaction_id"]:
                    prompt_row = conn.execute(
                        """
                        SELECT content FROM events
                        WHERE interaction_id=?
                          AND (actor_kind='human' OR role='user')
                          AND content IS NOT NULL AND trim(content)<>''
                        ORDER BY sequence_no,id LIMIT 1
                        """,
                        (row["interaction_id"],),
                    ).fetchone()
                    prompt = prompt_row["content"] if prompt_row else None
                record.update({
                    "input_excerpt": _bounded(row["input_json"]),
                    "result_excerpt": _bounded(result),
                    "interaction_human_prompt_excerpt": _bounded(prompt),
                })
            records.append(record)
        return records
    finally:
        conn.close()


def _codex_rollout_records(
    path: Path,
    *,
    include_excerpts: bool,
) -> list[dict[str, Any]]:
    by_call: dict[str, dict[str, Any]] = {}
    for event in process_file(path, path.stem, ".", {}):
        metadata = json.loads(event.get("metadata") or "{}")
        call_id = metadata.get("call_id")
        if not call_id:
            continue
        call_id = str(call_id)
        item = by_call.setdefault(call_id, {
            "project_id": None,
            "project_name": None,
            "snapshot_id": None,
            "store": str(path),
            "vendor": "Codex",
            "session_id": event["session_id"],
            "interaction_id": event.get("interaction_id"),
            "invocation_id": None,
            "source_call_id": bounded_source_call_id(call_id),
        })
        if event.get("event_kind") == "tool.transport":
            item["transport_status"] = event.get("normalized_status")
            item["mcp_server"] = metadata.get("mcp_server")
            item["tool_name"] = event.get("tool_name")
        elif event.get("event_type") == "tool_call":
            item["tool_name"] = event.get("tool_name")
            item["source_status"] = event.get("source_status")
            item["normalized_status"] = event.get("normalized_status")
            if include_excerpts:
                item["input_excerpt"] = _bounded(event.get("tool_input"))
        elif event.get("subtype") in {"tool_result", "tool_failure"}:
            item["result_source_status"] = event.get("source_status")
            item["result_normalized_status"] = event.get("normalized_status")
            item["result_present"] = event.get("tool_output") not in (None, "")
            item["result_failure_evidence"] = application_failure_evidence(
                event.get("tool_output")
            )
            if include_excerpts:
                item["result_excerpt"] = _bounded(event.get("tool_output"))
    records = []
    for item in by_call.values():
        tool_name = str(item.get("tool_name") or "")
        if not item.get("mcp_server") or not tool_name:
            continue
        outcome, likely_use = classify_mcp_invocation(
            tool_name,
            source_status=(
                item.get("result_source_status")
                or item.get("source_status")
            ),
            normalized_status=(
                item.get("result_normalized_status")
                or item.get("normalized_status")
                or item.get("transport_status")
            ),
            result=item.get("result_excerpt") if include_excerpts else (
                {"error": "application failure"}
                if item.get("result_failure_evidence") else "present"
            ),
        )
        item["classification"] = outcome
        item["likely_use"] = likely_use
        records.append(item)
    return records


def audit_mcp_interactions(
    registry: Path,
    *,
    codex_rollouts: list[Path] | None = None,
    include_excerpts: bool = False,
) -> dict[str, Any]:
    """Audit current query-ready snapshots and selected live Codex rollouts."""
    readiness = catalog_readiness(registry)
    records: list[dict[str, Any]] = []
    for project in readiness["projects"]:
        snapshot_id = project.get("current_snapshot_id")
        if project.get("query_status") != "query_ready" or not snapshot_id:
            continue
        root = durable_project_root(registry, project["project_id"])
        snapshot = root / "snapshots" / snapshot_id
        for db_path in sorted(snapshot.glob("*.db")):
            records.extend(_store_records(
                db_path, project=project, snapshot_id=snapshot_id,
                include_excerpts=include_excerpts,
            ))
    for path in codex_rollouts or []:
        records.extend(_codex_rollout_records(
            path.expanduser().resolve(), include_excerpts=include_excerpts
        ))

    counts = Counter(
        (str(item.get("vendor")), item["classification"])
        for item in records
    )
    duplicate_groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in records:
        call_id = item.get("source_call_id")
        if call_id:
            duplicate_groups[(str(item.get("vendor")), str(call_id))].append(item)
    duplicates = [
        {
            "vendor": key[0],
            "source_call_id": key[1],
            "occurrences": len(items),
            "sessions": sorted({
                str(item["session_id"]) for item in items
            }),
            "projects": sorted({
                str(item["project_name"]) for item in items
            }),
        }
        for key, items in duplicate_groups.items()
        if len(items) > 1
    ]
    repeated_id_occurrences = sum(
        item["occurrences"] - 1 for item in duplicates
    )
    return {
        "format": MCP_AUDIT_FORMAT,
        "scope": {
            "registry": str(registry.expanduser().resolve()),
            "snapshot_rule": "current query-ready snapshot only",
            "codex_rollouts": [
                str(path.expanduser().resolve())
                for path in codex_rollouts or []
            ],
            "content_excerpts": include_excerpts,
        },
        "summary": {
            "observed_invocations": len(records),
            "candidate_distinct_source_calls": (
                len(records) - repeated_id_occurrences
            ),
            "repeated_source_call_id_occurrences": repeated_id_occurrences,
            "vendors": sorted({
                str(item.get("vendor")) for item in records
            }),
            "by_vendor_and_classification": [
                {"vendor": vendor, "classification": classification, "count": count}
                for (vendor, classification), count in sorted(counts.items())
            ],
            "candidate_duplicate_source_call_id_groups": len(duplicates),
        },
        "duplicate_groups": duplicates,
        "invocations": records,
        "interpretation": [
            "discovery is not proof that a target tool executed",
            "transport success is not proof that the returned application result succeeded",
            "a repeated source call ID is only a duplicate candidate: source IDs "
            "need not be globally unique across Sessions or vendors",
            "likely_use is a tool-family description, not a claim that the operation was valuable",
        ],
    }
