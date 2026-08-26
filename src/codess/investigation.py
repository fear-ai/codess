"""Cited investigation records over bounded reusable query results."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from codess.query_api import RESULT_FORMAT, QueryContractError, content_hash
from codess.timeval import now_iso
from codess.wallclock import system_clock

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
        str(row["event_entity_id"]): row
        for row in result.get("rows") or []
        if row.get("event_entity_id")
    }
    requested = sorted({str(value) for value in event_ids if value})
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
            "event_entity_id": row["event_entity_id"],
            "observation_id": row.get("observation_id"),
            "session_entity_id": row.get("session_entity_id"),
            "project_id": row.get("project_id"),
            "snapshot_id": row.get("snapshot_id"),
            "source_system_id": row.get("source_system_id"),
            "source_record_locator": row.get("source_record_locator"),
            "event_kind": row.get("event_kind"),
            "content_digest": content_hash(row.get("content") or ""),
            "row_sha256": content_hash(row),
            "content_complete": row.get("content_complete"),
        })
    record = {
        "format": INVESTIGATION_FORMAT,
        "created_at": now_iso(system_clock),
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
