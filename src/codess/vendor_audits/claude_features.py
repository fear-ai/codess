"""Bounded structure-only audit of Claude Code JSONL source shapes."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from codess.bounded_jsonl import DEFAULT_MAX_RECORD_BYTES, iter_bounded_jsonl


def audit_claude_features(
    root: Path,
    *,
    max_files: int = 200,
    max_record_bytes: int = DEFAULT_MAX_RECORD_BYTES,
) -> dict[str, Any]:
    if max_files < 1:
        raise ValueError("Claude audit max_files must be positive")
    files = sorted(root.expanduser().rglob("*.jsonl"))[:max_files]
    record_types: Counter[str] = Counter()
    roles: Counter[str] = Counter()
    content_block_types: Counter[str] = Counter()
    lifecycle: Counter[str] = Counter()
    versions: Counter[str] = Counter()
    parent_links = 0
    sidechains = 0
    malformed = 0
    records = 0
    diagnostics: Counter[str] = Counter()
    compaction_boundaries = 0
    compaction_summaries = 0
    linked_compaction_summaries = 0
    compaction_summary_characters = 0
    compaction_summary_max_characters = 0
    compaction_triggers: Counter[str] = Counter()
    compact_metadata_fields: Counter[str] = Counter()
    model_settings: dict[str, Counter[str]] = {
        "model": Counter(), "service_tier": Counter(),
    }
    setting_provenance: Counter[str] = Counter()
    for path in files:
        try:
            iterator = iter_bounded_jsonl(
                path, max_record_bytes=max_record_bytes
            )
        except OSError:
            diagnostics["io_error"] += 1
            continue
        try:
            for _line, value, error in iterator:
                if error:
                    diagnostics[error] += 1
                    if error == "malformed":
                        malformed += 1
                    continue
                assert value is not None
                records += 1
                kind = str(value.get("type") or "unknown")
                record_types[kind] += 1
                if value.get("parentUuid"):
                    parent_links += 1
                if value.get("isSidechain"):
                    sidechains += 1
                version = value.get("version") or value.get("claudeCodeVersion")
                if version:
                    versions[str(version)] += 1
                subtype = value.get("subtype")
                if kind in {"system", "summary"} and subtype:
                    lifecycle[str(subtype)] += 1
                if kind == "system" and subtype == "compact_boundary":
                    compaction_boundaries += 1
                    compact = value.get("compactMetadata")
                    if isinstance(compact, dict):
                        compact_metadata_fields.update(str(key) for key in compact)
                        if compact.get("trigger") is not None:
                            compaction_triggers[str(compact["trigger"])] += 1
                message = value.get("message")
                if isinstance(message, dict):
                    if value.get("isCompactSummary"):
                        compaction_summaries += 1
                        if value.get("parentUuid"):
                            linked_compaction_summaries += 1
                        summary_body = message.get("content")
                        if isinstance(summary_body, str):
                            size = len(summary_body)
                            compaction_summary_characters += size
                            compaction_summary_max_characters = max(
                                compaction_summary_max_characters, size
                            )
                    model = message.get("model")
                    if model:
                        model_settings["model"][str(model)] += 1
                        setting_provenance["assistant.message.model"] += 1
                    usage = message.get("usage")
                    if isinstance(usage, dict) and usage.get("service_tier"):
                        model_settings["service_tier"][str(usage["service_tier"])] += 1
                        setting_provenance[
                            "assistant.message.usage.service_tier"
                        ] += 1
                    if message.get("role"):
                        roles[str(message["role"])] += 1
                    content = message.get("content")
                    if isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict):
                                content_block_types[str(block.get("type") or "unknown")] += 1
        except OSError:
            diagnostics["io_error"] += 1
    return {
        "audit_format": "codess.claude-feature-audit/1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "privacy_boundary": "structure and aggregate counts only; content bodies not retained",
        "root": str(root.expanduser().resolve()),
        "file_limit": max_files,
        "max_record_bytes": max_record_bytes,
        "files_reviewed": len(files),
        "records_reviewed": records,
        "malformed_records": malformed,
        "diagnostics": dict(diagnostics),
        "record_types": dict(record_types),
        "message_roles": dict(roles),
        "content_block_types": dict(content_block_types),
        "lifecycle_subtypes": dict(lifecycle),
        "parent_links": parent_links,
        "sidechain_records": sidechains,
        "versions": dict(versions),
        "model_settings": {
            key: dict(value) for key, value in model_settings.items() if value
        },
        "setting_provenance": dict(setting_provenance),
        "compaction_evidence": {
            "compact_boundaries": compaction_boundaries,
            "compact_summaries": compaction_summaries,
            "summaries_with_parent_uuid": linked_compaction_summaries,
            "summary_characters": compaction_summary_characters,
            "maximum_summary_characters": compaction_summary_max_characters,
            "triggers": dict(compaction_triggers),
            "compact_metadata_fields": dict(compact_metadata_fields),
        },
    }
