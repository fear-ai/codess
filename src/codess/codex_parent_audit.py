"""Metadata-only audit for explicit Codex session parentage evidence."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


PARENT_KEY = re.compile(
    r"(^|[._])(parent|parent_session|parent_thread|ancestor|forked_from|"
    r"resumed_from|previous_session|origin_session)([._]|$)", re.IGNORECASE,
)


def _flatten(value: Any, prefix: str = "payload") -> Iterable[tuple[str, Any]]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _flatten(child, f"{prefix}.{key}")
    elif isinstance(value, list):
        for child in value:
            yield from _flatten(child, f"{prefix}[]")
    else:
        yield prefix, value


def _session_meta(path: Path, max_records: int = 50) -> dict[str, Any] | None:
    with path.open(encoding="utf-8", errors="replace") as stream:
        for number, line in enumerate(stream):
            if number >= max_records:
                break
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("type") == "session_meta" and isinstance(record.get("payload"), dict):
                return record
    return None


def audit_parentage(roots: list[tuple[str, Path]]) -> dict[str, Any]:
    """Inspect only session_meta structures and parent-like scalar fields."""
    records: list[dict[str, Any]] = []
    unreadable = 0
    missing_meta = 0
    for root_name, root in roots:
        for path in sorted(root.expanduser().glob("**/*.jsonl")):
            try:
                meta = _session_meta(path)
            except OSError:
                unreadable += 1
                continue
            if meta is None:
                missing_meta += 1
                continue
            payload = meta["payload"]
            records.append({
                "root": root_name,
                "id": str(payload.get("id") or ""),
                "version": str(payload.get("cli_version") or "unknown"),
                "source": (
                    str(payload.get("source"))
                    if not isinstance(payload.get("source"), (dict, list))
                    else type(payload.get("source")).__name__
                ),
                "leaves": list(_flatten(payload)),
            })
    ids = {record["id"] for record in records if record["id"]}
    key_types: Counter[tuple[str, str]] = Counter()
    candidates: list[dict[str, Any]] = []
    for record in records:
        for key, value in record["leaves"]:
            key_types[(key, type(value).__name__)] += 1
            if not PARENT_KEY.search(key):
                continue
            scalar = value if isinstance(value, (str, int, float, bool)) else None
            candidates.append({
                "field_path": key,
                "value_type": type(value).__name__,
                "value_present": scalar not in (None, ""),
                "resolves_to_observed_session": str(scalar) in ids if scalar is not None else False,
                "root": record["root"],
                "cli_version": record["version"],
            })
    resolved = sum(bool(item["resolves_to_observed_session"]) for item in candidates)
    ids_list = [record["id"] for record in records if record["id"]]
    root_counts = Counter(record["root"] for record in records)
    versions = Counter(record["version"] for record in records)
    sources = Counter(record["source"] for record in records)
    return {
        "audit_format": "codess.codex-parent-audit/1",
        "scope": "all local JSONL files under configured active/archive roots; session_meta only",
        "privacy_boundary": "message, reasoning, tool, and prompt bodies were not read",
        "files_with_session_meta": len(records),
        "files_missing_session_meta": missing_meta,
        "unreadable_files": unreadable,
        "root_counts": dict(sorted(root_counts.items())),
        "cli_versions": dict(sorted(versions.items())),
        "source_surfaces": dict(sorted(sources.items())),
        "unique_session_ids": len(set(ids_list)),
        "duplicate_session_ids": len(ids_list) - len(set(ids_list)),
        "session_meta_leaf_shapes": [
            {"field_path": key, "value_type": value_type, "observations": count}
            for (key, value_type), count in sorted(key_types.items())
        ],
        "parent_candidate_fields": candidates,
        "resolved_parent_references": resolved,
        "support_status": "supported" if resolved else "not_observed",
        "decision": (
            "map only explicit identifiers that resolve to observed session IDs"
            if resolved
            else "do not infer parentage from time, path, archive state, or content proximity"
        ),
    }
