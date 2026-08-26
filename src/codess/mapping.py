"""Small shared primitives for exact source-to-CoSchema mapping evidence."""

from __future__ import annotations

import json
from typing import Any, NotRequired, TypedDict


class CandidateEvent(TypedDict):
    """The Event shape an adapter hands to the domain layer.

    Declared so the boundary between decode and storage states its shape rather
    than implying it from three adapters agreeing. The four required keys are
    `mapped_event_required` in the released mapping contract, which is what
    `validate_mapped_event` checks at runtime: the type states the shape and the
    validator states the values, and neither substitutes for the other.

    Every other key is optional because vendors record different things, and a
    decoder that must supply a key it has no evidence for would invent one --
    which is the failure the null-rather-than-guess rule exists to prevent. The
    total form is deliberately not used: `total=False` on the whole would drop
    the four keys that make an Event citable.
    """

    source_record_type: str
    source_record_locator: str
    mapping_rule: str
    mapping_trace: str

    source_record_subtype: NotRequired[str | None]
    session_id: NotRequired[Any]
    source_id: NotRequired[Any]
    event_id: NotRequired[Any]
    sequence_no: NotRequired[int | None]
    event_kind: NotRequired[str | None]
    actor_kind: NotRequired[str | None]
    content_role: NotRequired[str | None]
    origin_kind: NotRequired[str | None]
    interaction_id: NotRequired[str | None]
    model_turn_id: NotRequired[str | None]
    parent_event_id: NotRequired[str | None]
    caused_by_event_id: NotRequired[str | None]
    content: NotRequired[str | None]
    content_len: NotRequired[int | None]
    tool_name: NotRequired[str | None]
    tool_input: NotRequired[Any]
    tool_output: NotRequired[str | None]
    event_at: NotRequired[float | None]
    event_at_basis: NotRequired[str | None]
    source_status: NotRequired[str | None]
    source_file: NotRequired[str | None]
    artifact_path: NotRequired[str | None]
    file_path: NotRequired[str | None]
    metadata: NotRequired[Any]
    event_type: NotRequired[str | None]
    subtype: NotRequired[str | None]
    role: NotRequired[str | None]
    timestamp: NotRequired[Any]


def canonical_json(value: Any) -> str:
    """Serialize one structured value as stable, compact JSON."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def structured_json(value: Any) -> str | None:
    """Return valid JSON for structured tool material without double encoding.

    Source strings are retained when they already contain valid JSON. Other
    strings are represented as JSON strings: a JSON column must never contain
    a Python repr or arbitrary non-JSON text.
    """
    if value is None or value == "":
        return None
    if isinstance(value, str):
        try:
            json.loads(value)
        except json.JSONDecodeError:
            return canonical_json(value)
        return value
    return canonical_json(value)


def annotate_mapping(
    event: dict[str, Any],
    *,
    source_record_type: str,
    source_record_subtype: str | None,
    source_record_locator: str,
    mapping_rule: str,
    source_path: str = "$",
    applied_rules: list[str] | None = None,
) -> dict[str, Any]:
    """Attach exact scalar source identity plus structured translation trace."""
    event["source_record_type"] = source_record_type
    event["source_record_subtype"] = source_record_subtype
    event["source_record_locator"] = source_record_locator
    event["mapping_rule"] = mapping_rule
    event["mapping_trace"] = canonical_json({
        "applied_rules": applied_rules or [mapping_rule],
        "source": {
            "locator": source_record_locator,
            "path": source_path,
            "record_subtype": source_record_subtype,
            "record_type": source_record_type,
        },
        "target": {
            "actor_kind": event.get("actor_kind"),
            "event_kind": event.get("event_kind"),
            "origin_kind": event.get("origin_kind"),
        },
    })
    return event
