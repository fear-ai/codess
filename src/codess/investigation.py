"""Cited investigation records over bounded reusable query results."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from codess.query_api import RESULT_FORMAT, QueryContractError, content_hash


INVESTIGATION_FORMAT = "codess.investigation/1"


def build_investigation(
    result: dict[str, Any],
    *,
    summary: str,
    processor_id: str,
    event_ids: Iterable[str] = (),
) -> dict[str, Any]:
    """Bind a supplied interpretation to exact bounded evidence rows."""
    if result.get("format") != RESULT_FORMAT:
        raise QueryContractError(
            f"investigation input must be {RESULT_FORMAT}"
        )
    if not isinstance(summary, str) or not summary.strip():
        raise QueryContractError("investigation summary must be non-empty")
    if not isinstance(processor_id, str) or not processor_id.strip():
        raise QueryContractError("investigation processor_id must be non-empty")
    by_event = {
        str(row["global_event_id"]): row
        for row in result.get("rows") or []
        if row.get("global_event_id")
    }
    requested = sorted(set(str(value) for value in event_ids if value))
    if requested:
        missing = sorted(set(requested) - set(by_event))
        if missing:
            raise QueryContractError(
                "cited Event IDs are absent from the input result: "
                + ", ".join(missing)
            )
        selected = [by_event[value] for value in requested]
    else:
        selected = [by_event[value] for value in sorted(by_event)]
    if not selected:
        raise QueryContractError(
            "investigation input contains no Event rows to cite"
        )
    citations = []
    for row in selected:
        citations.append({
            "global_event_id": row["global_event_id"],
            "observation_id": row.get("observation_id"),
            "global_session_id": row.get("global_session_id"),
            "project_id": row.get("project_id"),
            "snapshot_id": row.get("snapshot_id"),
            "source_system_id": row.get("source_system_id"),
            "source_record_locator": row.get("source_record_locator"),
            "event_kind": row.get("event_kind"),
            "content_sha256": content_hash(row.get("content") or ""),
            "content_complete": row.get("content_complete"),
        })
    record = {
        "format": INVESTIGATION_FORMAT,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "processor_id": processor_id.strip(),
        "summary": summary,
        "input_result_hash": result.get("result_hash"),
        "input_request_hash": result.get("request_hash"),
        "project_snapshots": (
            result.get("request") or {}
        ).get("project_snapshots", []),
        "input_bounds": result.get("bounds"),
        "input_limitations": result.get("limitations", []),
        "citations": citations,
    }
    record["investigation_hash"] = content_hash({
        key: value
        for key, value in record.items()
        if key != "created_at"
    })
    return record
