"""Bounded, structure-only audit of Codex transcript records and settings."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from codess.bounded_jsonl import DEFAULT_MAX_RECORD_BYTES, iter_bounded_jsonl

CODEX_AUDIT_FORMAT = "codess.codex-feature-audit/1"
SETTING_FIELDS = {
    "model": "model",
    "model_name": "model",
    "model_provider": "model_provider",
    "model_provider_id": "model_provider",
    "reasoning_effort": "reasoning_effort",
    "effort": "reasoning_effort",
    "speed": "speed_tier",
    "speed_tier": "speed_tier",
    "service_tier": "service_tier",
    "mode": "mode",
}


def _setting_observations(
    payload: dict[str, Any], *, prefix: str
) -> list[tuple[str, str, str]]:
    observations = []
    seen = set()
    for source_field, common_field in SETTING_FIELDS.items():
        value = payload.get(source_field)
        if value is None or isinstance(value, (dict, list)) or common_field in seen:
            continue
        text = str(value).strip()
        if text:
            observations.append((common_field, text, f"{prefix}.{source_field}"))
            seen.add(common_field)
    collaboration = payload.get("collaboration_mode")
    if isinstance(collaboration, dict) and collaboration.get("mode"):
        observations.append((
            "mode", str(collaboration["mode"]),
            f"{prefix}.collaboration_mode.mode",
        ))
    return observations


def audit_codex_features(
    roots: list[tuple[str, Path]],
    *,
    max_files: int = 200,
    max_record_bytes: int = DEFAULT_MAX_RECORD_BYTES,
) -> dict[str, Any]:
    """Aggregate Codex structures and setting provenance without message text."""
    if max_files < 1:
        raise ValueError("Codex audit max_files must be positive")
    files: list[tuple[str, Path]] = []
    for root_kind, root in roots:
        if root.exists():
            files.extend((root_kind, path) for path in sorted(root.rglob("*.jsonl")))
    files = files[:max_files]
    record_types: Counter[str] = Counter()
    payload_fields: dict[str, Counter[str]] = defaultdict(Counter)
    settings: dict[str, Counter[str]] = defaultdict(Counter)
    setting_provenance: Counter[str] = Counter()
    diagnostics: Counter[str] = Counter()
    records = 0
    session_meta_versions: Counter[str] = Counter()
    compaction_envelopes = compaction_items = 0
    compaction_encrypted_chars = 0
    compaction_encrypted_max_chars = 0
    compaction_replacement_messages = 0
    context_compacted_notifications = 0
    for root_kind, path in files:
        try:
            iterator = iter_bounded_jsonl(
                path, max_record_bytes=max_record_bytes
            )
            for _line, record, error in iterator:
                if error:
                    diagnostics[error] += 1
                    continue
                assert record is not None
                records += 1
                record_type = str(record.get("type") or "unknown")
                record_types[record_type] += 1
                payload = record.get("payload")
                if not isinstance(payload, dict):
                    continue
                payload_fields[record_type].update(str(key) for key in payload)
                if record_type == "compacted":
                    compaction_envelopes += 1
                    history = payload.get("replacement_history")
                    if isinstance(history, list):
                        for item in history:
                            if not isinstance(item, dict):
                                continue
                            if item.get("type") == "message":
                                compaction_replacement_messages += 1
                            if item.get("type") != "compaction":
                                continue
                            compaction_items += 1
                            encrypted = item.get("encrypted_content")
                            if isinstance(encrypted, str):
                                size = len(encrypted)
                                compaction_encrypted_chars += size
                                compaction_encrypted_max_chars = max(
                                    compaction_encrypted_max_chars, size
                                )
                if (
                    record_type == "event_msg"
                    and payload.get("type") == "context_compacted"
                ):
                    context_compacted_notifications += 1
                if record_type == "session_meta" and payload.get("cli_version"):
                    session_meta_versions[str(payload["cli_version"])] += 1
                setting_payload = payload
                setting_type = record_type
                setting_prefix = "payload"
                if (
                    record_type == "event_msg"
                    and payload.get("type") == "thread_settings_applied"
                    and isinstance(payload.get("thread_settings"), dict)
                ):
                    setting_payload = payload["thread_settings"]
                    setting_type = "event_msg.thread_settings_applied"
                    setting_prefix = "payload.thread_settings"
                for common_field, value, source_path in _setting_observations(
                    setting_payload, prefix=setting_prefix
                ):
                    settings[common_field][value] += 1
                    setting_provenance[
                        f"{root_kind}:{setting_type}.{source_path}"
                    ] += 1
        except OSError:
            diagnostics["io_error"] += 1
    return {
        "audit_format": CODEX_AUDIT_FORMAT,
        "generated_at": datetime.now(UTC).isoformat(),
        "privacy_boundary": (
            "record/payload field names, selected scalar configuration values, "
            "and aggregate counts only; message, reasoning, and tool bodies omitted"
        ),
        "file_limit": max_files,
        "max_record_bytes": max_record_bytes,
        "files_reviewed": len(files),
        "records_reviewed": records,
        "diagnostics": dict(diagnostics),
        "record_types": dict(record_types),
        "payload_fields": {
            key: dict(value) for key, value in sorted(payload_fields.items())
        },
        "model_settings": {
            key: dict(value) for key, value in sorted(settings.items())
        },
        "setting_provenance": dict(setting_provenance),
        "cli_versions": dict(session_meta_versions),
        "compaction_evidence": {
            "compacted_envelopes": compaction_envelopes,
            "compaction_items": compaction_items,
            "encrypted_summary_characters": compaction_encrypted_chars,
            "maximum_encrypted_summary_characters": (
                compaction_encrypted_max_chars
            ),
            "replacement_history_messages_not_normalized": (
                compaction_replacement_messages
            ),
            "context_compacted_notifications": (
                context_compacted_notifications
            ),
        },
    }
