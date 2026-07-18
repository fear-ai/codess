"""Small shared primitives for exact source-to-CoSchema mapping evidence."""

from __future__ import annotations

import json
from typing import Any


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
