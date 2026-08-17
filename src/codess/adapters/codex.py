"""Codex JSONL parser and normalizer."""

import json
import logging
import re
from collections import Counter
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from codess import field_state
from codess.config import TRUNCATE_PROMPT, TRUNCATE_RESPONSE, TRUNCATE_TOOL_RESULT
from codess.content_processing import apply_processing
from codess.context_content import bound_context_content
from codess.mapping import annotate_mapping
from codess.sanitize import sanitize_value
from codess.tool_result_status import application_failure_evidence

log = logging.getLogger(__name__)


def iter_codex_records(
    path: Path,
    diagnostics: dict[str, int] | None = None,
    *,
    warn: bool = True,
) -> Iterator[tuple[int, dict, str]]:
    """Stream JSONL; yield (line_num, record, raw_line). Skip empty; on JSON error log and skip."""
    with path.open(encoding="utf-8", errors="replace") as f:
        for line_num, line in enumerate(f, 1):
            raw = line
            line = line.rstrip("\n\r")
            if not line:
                continue
            try:
                record = json.loads(line)
                yield line_num, record, raw
            except json.JSONDecodeError as e:
                if diagnostics is not None:
                    diagnostics["malformed_records"] = (
                        diagnostics.get("malformed_records", 0) + 1
                    )
                if warn:
                    log.warning("JSON error at %s:%d: %s", path, line_num, e)
                continue


def get_session_meta(path: Path) -> tuple[str, str]:
    """Return (session_id, project_path) from first session_meta. Fallback to filename stem and '.'."""
    for _line_num, record, _ in iter_codex_records(path, warn=False):
        if record.get("type") == "session_meta":
            payload = record.get("payload") or {}
            sid = payload.get("id")
            cwd = payload.get("cwd")
            return (
                str(sid) if sid else path.stem,
                str(cwd) if cwd else ".",
            )
    return path.stem, "."


# `source` names where the Session ran. Codex reports the interface directly,
# so this maps its values onto CoSchema's `surface_kind` vocabulary rather
# than inferring one. An unlisted value is left unmapped: the profile default
# is a guess, and a wrong surface is worse than an absent one.
_CODEX_SURFACE = {
    "cli": "cli",
    "vscode": "ide",
    "exec": "cli",
}


def _observed_harness(payload: dict) -> dict:
    """Harness and surface the Session actually reports, where it reports them.

    Codex is the only one of the three vendors that names both: `originator`
    distinguishes `codex_cli_rs`, `Codex Desktop`, `codex-tui`, and `codex_exec`,
    and `source` distinguishes `cli`, `vscode`, and `exec`. Claude states a surface
    only (`entrypoint`) and Cursor neither, so both fall back to the profile.

    `originator` is stored verbatim even though its values conflate the program with
    the surface -- `codex_cli_rs` and `Codex Desktop` are one program under two
    surfaces. It is the exact vendor string, which the schema retains rather than
    normalizes; the surface is recorded separately from `source`, so a reader who
    wants the program alone reads `surface_kind` beside it.

    Only observed values are returned, so `store` falls back to the profile where a
    vendor supplies nothing.
    """
    observed: dict[str, str] = {}
    originator = payload.get("originator")
    if isinstance(originator, str) and originator.strip():
        observed["harness_name"] = originator.strip()
    surface = payload.get("source")
    if isinstance(surface, str):
        mapped = _CODEX_SURFACE.get(surface.strip().lower())
        if mapped:
            observed["surface_kind"] = mapped
    return observed


def get_session_metadata(path: Path) -> dict:
    """Return useful, bounded session-level metadata from session_meta."""
    for _line_num, record, _ in iter_codex_records(path, warn=False):
        if record.get("type") != "session_meta":
            continue
        payload = record.get("payload") or {}
        values = {
            key: payload[key]
            for key in (
                "cli_version", "model_provider", "originator", "source",
                "thread_source", "agent_nickname", "agent_role", "agent_path",
                "multi_agent_version", "subagent_history_start_ordinal",
            )
            if payload.get(key) is not None
        }
        values.update(_observed_harness(payload))
        parent = payload.get("parent_thread_id")
        forked = payload.get("forked_from_id")
        thread_source = str(payload.get("thread_source") or "").lower()
        source = payload.get("source")
        source_text = (
            json.dumps(source, sort_keys=True)
            if isinstance(source, dict) else str(source or "")
        ).lower()
        if parent is not None:
            values["parent_session_id"] = str(parent)
            values["session_relation_kind"] = (
                "subagent"
                if (
                    thread_source == "subagent"
                    or "subagent" in source_text
                )
                else "continuation"
            )
            values["lineage_provenance"] = (
                "session_meta.parent_thread_id"
            )
        elif forked is not None:
            values["parent_session_id"] = str(forked)
            values["session_relation_kind"] = "fork"
            values["lineage_provenance"] = (
                "session_meta.forked_from_id"
            )
        elif thread_source == "subagent" or "subagent" in source_text:
            values["session_relation_kind"] = "subagent"
            values["lineage_provenance"] = (
                "session_meta.thread_source/source"
            )
        return values
    return {}


def _parse_timestamp(value: Any) -> float | None:
    """Normalize Unix seconds/ms or ISO-8601 to Unix milliseconds."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number * 1000 if number < 1e12 else number
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value)
        except (TypeError, ValueError):
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.timestamp() * 1000
    return None


def _extract_text_from_content(content: list) -> str:
    """Extract text from Codex content blocks (input_text, etc.)."""
    if not content:
        return ""
    parts = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "input_text" or "text" in block:
            parts.append(block.get("text", ""))
    return "\n".join(parts)


def _extract_reasoning_summary(summary: Any) -> str:
    """Extract vendor-exposed summary text, never encrypted reasoning state."""
    if not isinstance(summary, list):
        return ""
    parts = []
    for item in summary:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict) and isinstance(item.get("text"), str):
            parts.append(item["text"])
    return "\n".join(part for part in parts if part)


def _user_message_key(value: str) -> str:
    """Canonical comparison key for paired Codex user-message envelopes."""
    return str(value).strip()


def _build_record_maps(
    path: Path,
) -> tuple[
    dict[str, str],
    Counter[str],
    set[str],
    dict[str, str],
]:
    """Collect call names and direct-user evidence in one bounded pre-pass.

    Current Codex rollouts persist direct UI submissions twice: a canonical
    ``response_item.message`` and an ``event_msg.user_message`` notification.
    Harness-injected context can use the same Responses ``user`` role without
    the notification.  The pairing therefore distinguishes observed human
    submissions from harness-carried model input without inspecting meaning.
    Older rollouts with no notifications retain the legacy role-based fallback.
    """
    calls: dict[str, str] = {}
    direct_user_messages: Counter[str] = Counter()
    mcp_call_ids: set[str] = set()
    output_by_call: dict[str, object] = {}
    for _line_num, record, _raw in iter_codex_records(path, warn=False):
        payload = record.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        if (
            record.get("type") == "event_msg"
            and payload.get("type") == "user_message"
            and isinstance(payload.get("message"), str)
        ):
            direct_user_messages[_user_message_key(payload["message"])] += 1
            continue
        if (
            record.get("type") == "event_msg"
            and payload.get("type") == "mcp_tool_call_end"
            and payload.get("call_id")
        ):
            mcp_call_ids.add(str(payload["call_id"]))
            continue
        if record.get("type") != "response_item":
            continue
        item_type = payload.get("type")
        if item_type in ("function_call_output", "custom_tool_call_output"):
            call_id = payload.get("call_id")
            if call_id:
                output_by_call[str(call_id)] = payload.get("output")
            continue
        if item_type == "tool_search_call":
            call_id = payload.get("call_id")
            if call_id:
                calls[str(call_id)] = "tool_search"
            continue
        if item_type not in ("function_call", "custom_tool_call"):
            continue
        call_id = payload.get("call_id")
        name = payload.get("name")
        if call_id and name:
            calls[str(call_id)] = str(name)
    mcp_failures = {
        call_id: evidence
        for call_id in mcp_call_ids
        if (evidence := application_failure_evidence(
            output_by_call.get(call_id)
        ))
    }
    return calls, direct_user_messages, mcp_call_ids, mcp_failures


def _tool_input(payload: dict, redact_enabled: bool) -> str | None:
    """Normalize function/custom tool input to a JSON value."""
    field = "arguments" if payload.get("type") == "function_call" else "input"
    raw = payload.get(field)
    if raw is None:
        return None
    value = raw
    if isinstance(raw, str):
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            value = {field: raw}
    value = sanitize_value(value, redact_enabled)
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


_PATCH_FILE_HEADER = re.compile(r"^\*\*\* (?:Add|Update|Delete) File: (.+)$", re.MULTILINE)


def _patched_file(payload: dict) -> str | None:
    """The file an `apply_patch` call operates on, or None.

    Codex names no path in a tool argument -- `exec_command` carries a shell
    string and `apply_patch` an envelope -- so the Artifact a Codex Session
    touched was not recoverable from any field. It is recoverable from the
    patch envelope, whose `*** Add|Update|Delete File:` headers name each
    path, and every one of the 4,639 `apply_patch` calls observed carries at
    least one.

    Only the first path is returned, because `events.file_path` holds one
    value; a patch touching several files records the first and keeps the
    rest in `tool_input`, which is retained whole. Naming one file is
    evidence; inventing a join across several would not be.
    """
    if payload.get("name") != "apply_patch":
        return None
    raw = payload.get("arguments") or payload.get("input")
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = raw
        raw = parsed.get("input") if isinstance(parsed, dict) else parsed
    if not isinstance(raw, str):
        return None
    match = _PATCH_FILE_HEADER.search(raw)
    return match.group(1).strip() if match else None


def _metadata(payload: dict) -> str | None:
    values = {
        key: payload[key]
        for key in ("call_id", "status")
        if payload.get(key) is not None
    }
    return json.dumps(values, separators=(",", ":")) if values else None


def _configuration_values(
    record_type: str,
    payload: dict,
    line_num: int,
) -> dict:
    """Extract only settings whose Codex field semantics were verified."""
    source = payload
    prefix = "payload"
    if record_type == "thread_settings_applied":
        source = payload.get("thread_settings") or {}
        prefix = "payload.thread_settings"
    if not isinstance(source, dict):
        return {}
    values = {}
    provenance = {}

    def keep(common: str, source_field: str, value: Any) -> None:
        if value is None or isinstance(value, (dict, list)):
            return
        text = str(value).strip()
        if text:
            values[common] = text
            provenance[common] = {
                "source_record_type": record_type,
                "source_record_locator": str(line_num),
                "source_field": f"{prefix}.{source_field}",
            }

    keep("model", "model", source.get("model"))
    keep(
        "model_provider",
        "model_provider_id" if "model_provider_id" in source else "model_provider",
        source.get("model_provider_id") or source.get("model_provider"),
    )
    keep(
        "reasoning_effort",
        "reasoning_effort" if "reasoning_effort" in source else "effort",
        source.get("reasoning_effort") or source.get("effort"),
    )
    # Codex states the tier the client *requested*, in `thread_settings` beside
    # `model_provider`. Claude states the tier the API *served*, in `message.usage`
    # beside the token counts. Different facts, so different columns.
    keep("request_tier", "service_tier", source.get("service_tier"))
    collaboration = source.get("collaboration_mode")
    if isinstance(collaboration, dict):
        keep("mode", "collaboration_mode.mode", collaboration.get("mode"))
        keep(
            "collaboration_mode_kind",
            "collaboration_mode.kind",
            collaboration.get("kind"),
        )
    keep("approval_policy", "approval_policy", source.get("approval_policy"))
    if source.get("turn_id") is not None:
        values["source_turn_id"] = str(source["turn_id"])
    if values:
        values["configuration_provenance"] = provenance
    return values


def _mapping_rule(event: dict) -> str:
    if event.get("subtype") == "context_compaction":
        return "codex.compaction"
    if event.get("subtype") == "context_injection":
        return "codex.context-injection"
    if event.get("subtype") in {"task_started", "task_complete"}:
        return "codex.task-lifecycle"
    if event.get("subtype") == "reasoning_summary":
        return "codex.reasoning-summary"
    if str(event.get("subtype") or "").startswith("collab_") or (
        event.get("subtype") == "subagent_activity"
    ):
        return "codex.collaboration"
    if event.get("event_type") == "tool_call":
        return "codex.tool-call"
    if event.get("subtype") == "tool_result":
        return "codex.tool-result"
    if event.get("subtype") == "turn_aborted":
        return "codex.abort"
    return "codex.message"


def _base_event(
    *, session_id: str, line_num: int, event_type: str, subtype: str | None,
    role: str, timestamp: float | None, source_file: str,
    event_kind: str | None = None, actor_kind: str | None = None,
    content_role: str | None = None, origin_kind: str | None = None,
    content: str | None = None, content_len: int | None = None,
    tool_name: str | None = None, tool_input: str | None = None,
    tool_output: str | None = None, metadata: str | None = None,
    file_path: str | None = None, source_raw: object = None,
    **extra: object,
) -> dict:
    """One Codex Event envelope, holding the fields every record shares.

    Fifteen call sites each wrote the same twenty keys inline -- 405 lines in
    which sixteen keys were identical everywhere and only the classification
    and content varied, so finding what a record type does differently meant
    diffing two blocks. This mirrors `adapters/cc._base_event`, with one
    difference: Codex usually classifies where it builds, so the four
    classification fields are arguments here. Three record types -- tool
    search, function and custom tool calls -- omit them, and an omitted field
    is left out of the dict rather than set to `None`, because the two are
    not the same to `store._event_classification`: it fills only absent
    dimensions, so a `None` would be an explicit classification of nothing.

    That omission is deliberate and correct. `_inferred_classification` derives the
    four values from `event_type` and `role`, which for a tool call is
    unambiguous, and it produces `tool.call`/`model`/`tool_request`/
    `model_generated` for all 18,709 such Events in the real stores --
    identical to what the sites that state them inline produce. Repeating
    them here would add fifteen lines that could disagree with the resolver
    and be believed over it.

    `extra` carries fields only some records have -- `source_status` and
    `normalized_status` on tool results -- so the callers that have none do
    not each spell out a `None`.
    """
    classification = {
        key: value
        for key, value in (
            ("event_kind", event_kind), ("actor_kind", actor_kind),
            ("content_role", content_role), ("origin_kind", origin_kind),
        )
        if value is not None
    }
    return {
        "session_id": session_id,
        "event_id": str(line_num),
        "event_type": event_type,
        "subtype": subtype,
        "role": role,
        **classification,
        "content": content,
        "content_len": content_len,
        "content_ref": None,
        "tool_name": tool_name,
        "tool_input": tool_input,
        "tool_output": tool_output,
        "timestamp": timestamp,
        "file_path": file_path,
        "source_file": source_file,
        "metadata": metadata,
        "source_raw": source_raw,
        **extra,
    }


def _annotate_source(
    event: dict, record_type: str, payload: dict, line_num: int,
) -> dict:
    event = dict(event)
    source_path = event.pop("_source_path", "$.payload")
    rule = _mapping_rule(event)
    applied = [rule]
    if event.get("metadata") and record_type == "response_item":
        applied.append("codex.configuration")
    if event.get("actor_kind") == "model" or event.get("role") == "assistant":
        metadata = event.get("metadata")
        try:
            configuration = json.loads(metadata) if metadata else {}
        except (TypeError, json.JSONDecodeError):
            configuration = {}
        model, state = field_state.get_state(configuration, "model")
        field_state.attach(
            event, field="model", state=state,
            source_field="effective_configuration.model", value=model,
        )
    if event.get("event_type") == "user_message":
        field_state.attach(
            event, field="prompt_origin", state=field_state.ABSENT,
            source_field="payload.origin",
        )
    if event.get("event_type") == "tool_call":
        input_field = (
            "arguments"
            if payload.get("type") == "function_call" else "input"
        )
        value, state = field_state.get_state(payload, input_field)
        field_state.attach(
            event, field="tool_input", state=state,
            source_field=f"payload.{input_field}", value=value,
        )
    return annotate_mapping(
        event,
        source_record_type=record_type,
        source_record_subtype=(
            str(payload["type"]) if payload.get("type") is not None else None
        ),
        source_record_locator=str(line_num),
        mapping_rule=rule,
        source_path=source_path,
        applied_rules=applied,
    )


def _update_configuration(current: dict, observed: dict) -> None:
    provenance = dict(current.get("configuration_provenance") or {})
    provenance.update(observed.get("configuration_provenance") or {})
    current.update({
        key: value for key, value in observed.items()
        if key != "configuration_provenance"
    })
    if provenance:
        current["configuration_provenance"] = provenance


def _merge_metadata(payload: dict, configuration: dict) -> str | None:
    values = json.loads(_metadata(payload) or "{}")
    values.update(configuration)
    return json.dumps(values, separators=(",", ":")) if values else None


def _failed_status(payload: dict) -> bool:
    return str(payload.get("status") or "").lower() in {
        "failed", "failure", "error", "incomplete",
    }


_EXIT_CODE = re.compile(r'\\?"exit_code\\?":\s*(-?\d+)')


# Codex prefixes most tool output with a fixed header -- `Exit code`, `Wall time`,
# `Total output lines` -- then `Output:` and the body. 18,543 of 19,576 real results
# carry it. The fields are stated, not inferred, so they are decoded rather than left
# inside the text; the body stays a string because that is what it is.
# Codex prefixes tool output with a header of stated facts, then `Output:` and the
# body. 18,543 of 19,576 real results carry one. The fields are matched per line rather
# than as one expression, because the set and order vary by tool and the spellings do
# too: the exit code appears as `Process exited with code N` on 14,934 results and
# `Exit code: N` on 1,319, and the wall time with and without a colon.
_HEADER_FIELDS = (
    (re.compile(r"\AExit code: (-?\d+)\Z"), "exit_code", int),
    (re.compile(r"\AProcess exited with code (-?\d+)\Z"), "exit_code", int),
    (re.compile(r"\AWall time:? ([\d.]+) seconds?\Z"), "wall_seconds", float),
    (re.compile(r"\ATotal output lines: (\d+)\Z"), "output_lines", int),
    (re.compile(r"\AOriginal token count: (\d+)\Z"), "output_tokens", int),
    (re.compile(r"\AChunk ID: (\S+)\Z"), "chunk_id", str),
    (re.compile(r"\AProcess running with session ID (\S+)\Z"), "process_session_id", str),
    (re.compile(r"\A(Script completed)\Z"), "script_completed", bool),
)
_OUTPUT_MARKER = "Output:"


def _output_text(output: object) -> str | None:
    """The text Codex wrapped, from whichever wrapper it used.

    Three transports carry the same payload: a bare string, a `{"output": ...}`
    envelope, and a list of `{type, text}` content blocks. The wrapper is retained
    verbatim in `output_json`; this returns only the text so one header decode serves
    all three.
    """
    if isinstance(output, str):
        stripped = output.strip()
        if stripped[:1] == "{":
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError:
                return output
            if isinstance(parsed, dict) and isinstance(parsed.get("output"), str):
                return parsed["output"]
            return output
        return output
    if isinstance(output, list):
        parts = [
            block["text"] for block in output
            if isinstance(block, dict) and isinstance(block.get("text"), str)
        ]
        return "\n".join(parts) if parts else None
    return None


def _decoded_output(output: object) -> dict | None:
    """Header fields plus body, where Codex states a header.

    Returns None when no `Output:` marker is present, or when the lines before it
    state nothing recognized: a result Codex did not annotate has no fields, and an
    envelope holding only the body would claim structure that is not there.
    """
    text = _output_text(output)
    if not isinstance(text, str):
        return None
    marker = text.find(_OUTPUT_MARKER)
    if marker < 0:
        return None
    decoded: dict = {}
    for line in text[:marker].split("\n"):
        line = line.strip()
        if not line:
            continue
        for pattern, name, cast in _HEADER_FIELDS:
            match = pattern.match(line)
            if match is None:
                continue
            decoded[name] = True if cast is bool else cast(match.group(1))
            break
        else:
            # An unrecognized header line means the marker was body text rather than
            # a header, so nothing is claimed for this result.
            return None
    if not decoded:
        return None
    body = text[marker + len(_OUTPUT_MARKER):]
    decoded["output"] = body[1:] if body[:1] in ("\n", " ") else body
    return decoded


def _exit_code_status(payload: dict) -> str | None:
    """The shell exit code Codex reports inside its output text, or None.

    Codex states no `status` field on most tool outputs, so 26,917 of 30,415
    real results carried neither a source nor a normalized outcome. It does
    report `exit_code` -- but inside the output body, as JSON embedded in
    text, which is why no field read reached it. About 11% of sampled
    outputs carry one.

    Returned as the exact source spelling (`exit_code:0`) so
    `store._normalized_status` maps it and the raw value is retained. Where
    no code is present the result stays unknown, which is the honest answer:
    Codex did not say.
    """
    raw = payload.get("output")
    if not isinstance(raw, str):
        raw = json.dumps(raw) if raw is not None else ""
    match = _EXIT_CODE.search(raw)
    if match:
        return f"exit_code:{match.group(1)}"
    # The header states the same fact in words on far more results -- 14,795 against
    # 79 -- and the two forms never co-occur, so the header is the larger source.
    decoded = _decoded_output(payload.get("output"))
    if decoded and "exit_code" in decoded:
        return f"exit_code:{decoded['exit_code']}"
    return None


def _compaction_events(
    payload: dict,
    *,
    session_id: str,
    source_file: str,
    line_num: int,
    timestamp: float | None,
    source_raw: bytes | None,
    opts: dict,
) -> Iterator[dict]:
    """Map each explicit encrypted Codex compaction summary once.

    ``replacement_history`` reconstructs a context window and repeats ordinary
    transcript messages.  Only its dedicated ``type=compaction`` item is new
    compaction communication; copying the rest would multiply large messages.
    """
    history = payload.get("replacement_history")
    if not isinstance(history, list):
        history = []
    summaries = [
        (index, item)
        for index, item in enumerate(history)
        if isinstance(item, dict) and item.get("type") == "compaction"
    ]
    if not summaries:
        summaries = [(-1, {})]
    for emitted_index, (history_index, item) in enumerate(summaries):
        encrypted = item.get("encrypted_content")
        text = encrypted if isinstance(encrypted, str) else ""
        text = apply_processing(
            text,
            opts,
            vendor="Codex",
            record_type="compacted.encrypted_content",
            event_kind="context.compact",
            phase="pre",
        )
        if text is None:
            continue
        text, content_len, truncated = bound_context_content(text, opts)
        text = apply_processing(
            text,
            opts,
            vendor="Codex",
            record_type="compacted.encrypted_content",
            event_kind="context.compact",
            phase="post",
        )
        if text is None:
            continue
        text, _post_length, post_truncated = bound_context_content(text, opts)
        truncated = truncated or post_truncated
        metadata = {
            "audit_kind": "context_compaction",
            "context_kind": "compaction_summary",
            "content_encoding": (
                "vendor_encrypted" if isinstance(encrypted, str) else "absent"
            ),
            "content_truncated": truncated,
            "replacement_history_items": len(history),
            "replacement_history_messages_not_duplicated": sum(
                isinstance(entry, dict) and entry.get("type") == "message"
                for entry in history
            ),
        }
        for key in (
            "window_number", "first_window_id", "previous_window_id", "window_id"
        ):
            if payload.get(key) is not None:
                metadata[key] = payload[key]
        if item.get("id") is not None:
            metadata["compaction_item_id"] = item["id"]
        yield {
            "session_id": session_id,
            "event_id": (
                str(line_num)
                if len(summaries) == 1
                else f"{line_num}:{emitted_index}"
            ),
            "event_type": "system_event",
            "subtype": "context_compaction",
            "role": "harness",
            "content": text or None,
            "content_len": content_len if encrypted is not None else None,
            "content_ref": None,
            "tool_name": None,
            "tool_input": None,
            "tool_output": None,
            "timestamp": timestamp,
            "file_path": None,
            "source_file": source_file,
            "metadata": json.dumps(metadata, separators=(",", ":")),
            "source_raw": source_raw,
            "event_kind": "context.compact",
            "actor_kind": "harness",
            "content_role": "context",
            "origin_kind": "harness_injected",
            "_source_path": (
                "$.payload.replacement_history"
                if history_index < 0
                else f"$.payload.replacement_history[{history_index}]"
            ),
        }


def process_file(
    path: Path,
    session_id: str,
    project_path: str,
    opts: dict,
) -> Iterator[dict]:
    """Stream events from Codex JSONL. Maps session_meta, response_item to normalized events."""
    source_file = str(path.resolve())
    redact_enabled = opts.get("redact", False)
    debug = opts.get("debug", False)
    diagnostics = opts.get("diagnostics")
    (
        call_map,
        direct_user_messages,
        _mcp_call_ids,
        mcp_failures,
    ) = _build_record_maps(path)
    has_direct_user_notifications = bool(direct_user_messages)
    current_configuration: dict = {}

    for line_num, record, raw_line in iter_codex_records(path, diagnostics):
        rtype = record.get("type")
        payload = record.get("payload") or {}
        if not isinstance(payload, dict):
            if diagnostics is not None:
                diagnostics["malformed_records"] = (
                    diagnostics.get("malformed_records", 0) + 1
                )
            continue
        timestamp = _parse_timestamp(record.get("timestamp"))

        source_raw = (
            raw_line.encode("utf-8", errors="replace")[:512]
            if debug and not redact_enabled
            else None
        )

        if rtype == "session_meta":
            # Codex states provider and model on different records: `session_meta` carries
            # `model_provider` and no model, `turn_context` the reverse. The provider is a
            # Session-level fact, so it seeds the configuration every later turn extends.
            _update_configuration(
                current_configuration,
                _configuration_values("session_meta", payload, line_num),
            )
            if diagnostics is not None:
                diagnostics["session_metadata_records"] = (
                    diagnostics.get("session_metadata_records", 0) + 1
                )
            continue

        if rtype == "compacted":
            for event in _compaction_events(
                payload,
                session_id=session_id,
                source_file=source_file,
                line_num=line_num,
                timestamp=timestamp,
                source_raw=source_raw,
                opts=opts,
            ):
                yield _annotate_source(event, rtype, payload, line_num)
            continue

        if rtype == "turn_context":
            _update_configuration(
                current_configuration,
                _configuration_values("turn_context", payload, line_num),
            )
            if diagnostics is not None:
                diagnostics["configuration_records"] = (
                    diagnostics.get("configuration_records", 0) + 1
                )
            continue

        if (
            rtype == "event_msg"
            and payload.get("type") == "thread_settings_applied"
        ):
            _update_configuration(
                current_configuration,
                _configuration_values(
                    "thread_settings_applied", payload, line_num
                ),
            )
            if diagnostics is not None:
                diagnostics["configuration_records"] = (
                    diagnostics.get("configuration_records", 0) + 1
                )
            continue

        if rtype == "response_item":
            item_type = payload.get("type", "")
            if item_type == "reasoning":
                text = _extract_reasoning_summary(payload.get("summary"))
                if not text:
                    if diagnostics is not None:
                        diagnostics["known_ignored_records"] = (
                            diagnostics.get("known_ignored_records", 0) + 1
                        )
                        diagnostics["reasoning_without_summary_records"] = (
                            diagnostics.get(
                                "reasoning_without_summary_records", 0
                            ) + 1
                        )
                    continue
                bounded = _bounded_content(
                    text, opts, record_type="reasoning_summary",
                    event_kind="message.reasoning_summary",
                    limit=TRUNCATE_RESPONSE,
                )
                if bounded is None:
                    continue
                truncated, content_len = bounded
                if diagnostics is not None:
                    diagnostics["reasoning_summary_records"] = (
                        diagnostics.get("reasoning_summary_records", 0) + 1
                    )
                yield _annotate_source(_base_event(
                    line_num=line_num,
                    session_id=session_id,
                    event_type="assistant_message",
                    subtype="reasoning_summary",
                    role="assistant",
                    event_kind="message.reasoning_summary",
                    actor_kind="model",
                    content_role="reasoning_summary",
                    origin_kind="model_generated",
                    timestamp=timestamp,
                    source_file=source_file,
                    content=truncated,
                    content_len=content_len,
                    metadata=_merge_metadata( payload, current_configuration ),
                    source_raw=source_raw,
                ), rtype, payload, line_num)
                continue

            if item_type == "message":
                role = payload.get("role", "")
                content = payload.get("content") or []
                text = _extract_text_from_content(content)
                direct_user = False
                if role == "user":
                    key = _user_message_key(text)
                    direct_user = (
                        not has_direct_user_notifications
                        or direct_user_messages.get(key, 0) > 0
                    )
                    if (
                        has_direct_user_notifications
                        and direct_user_messages.get(key, 0) > 0
                    ):
                        direct_user_messages[key] -= 1
                message_kind = (
                    "message.prompt"
                    if role == "user" and direct_user
                    else "message.context"
                    if role in {"developer", "system", "user"}
                    else "message.response"
                )
                text = apply_processing(
                    text, opts, vendor="Codex", record_type="message",
                    event_kind=message_kind,
                    phase="pre",
                )
                if text is None:
                    continue

                if role == "user" and direct_user:
                    subtype = "slash_command" if text.strip().startswith("/") else "prompt"
                    truncated, content_len = _truncate(text, TRUNCATE_PROMPT)
                    truncated = apply_processing(
                        truncated, opts, vendor="Codex", record_type="message",
                        event_kind="message.prompt", phase="post",
                    )
                    if truncated is None:
                        continue
                    yield _annotate_source(_base_event(
                        line_num=line_num,
                        session_id=session_id,
                        event_type="user_message",
                        subtype=subtype,
                        role="user",
                        event_kind="message.prompt",
                        actor_kind="human",
                        content_role="prompt",
                        origin_kind="direct_user_input",
                        timestamp=timestamp,
                        source_file=source_file,
                        content=truncated,
                        content_len=content_len,
                        metadata=_merge_metadata(payload, { **current_configuration, "source_role": "user", "actor_evidence": ( "event_msg.user_message" if has_direct_user_notifications else "legacy_user_role_fallback" ), "content_truncated": ( content_len > TRUNCATE_PROMPT ), }),
                        source_raw=source_raw,
                    ), rtype, payload, line_num)
                    if diagnostics is not None:
                        diagnostics["direct_user_message_records"] = (
                            diagnostics.get("direct_user_message_records", 0)
                            + 1
                        )
                elif role in {"user", "developer", "system"}:
                    # One branch for three roles. Codex injects harness
                    # context under any of them and the handling was
                    # identical, differing only in the role recorded and in
                    # whether the unpaired-user diagnostic applies -- so the
                    # two copies could drift on the bounding or processing
                    # they share, which is the part that matters.
                    bounded, content_len, truncated = bound_context_content(
                        text, opts
                    )
                    bounded = apply_processing(
                        bounded, opts, vendor="Codex", record_type="message",
                        event_kind="message.context", phase="post",
                    )
                    if bounded is None:
                        continue
                    bounded, _post_len, post_truncated = bound_context_content(
                        bounded, opts
                    )
                    evidence = (
                        {"actor_evidence": "unpaired_response_item_user_role"}
                        if role == "user" else {}
                    )
                    yield _annotate_source(_base_event(
                        line_num=line_num,
                        session_id=session_id,
                        event_type="system_event",
                        subtype="context_injection",
                        role=role,
                        event_kind="message.context",
                        actor_kind="harness",
                        content_role="context",
                        origin_kind="harness_injected",
                        timestamp=timestamp,
                        source_file=source_file,
                        content=bounded,
                        content_len=content_len,
                        metadata=_merge_metadata(payload, {
                            **current_configuration,
                            "source_role": role,
                            **evidence,
                            "content_truncated": truncated or post_truncated,
                        }),
                        source_raw=source_raw,
                    ), rtype, payload, line_num)
                    if role == "user" and diagnostics is not None:
                        diagnostics["harness_user_role_context_records"] = (
                            diagnostics.get(
                                "harness_user_role_context_records", 0
                            ) + 1
                        )
                elif role == "assistant":
                    truncated, content_len = _truncate(text, TRUNCATE_RESPONSE)
                    truncated = apply_processing(
                        truncated, opts, vendor="Codex", record_type="message",
                        event_kind="message.response", phase="post",
                    )
                    if truncated is None:
                        continue
                    yield _annotate_source(_base_event(
                        line_num=line_num,
                        session_id=session_id,
                        event_type="assistant_message",
                        subtype="response",
                        role="assistant",
                        event_kind="message.response",
                        actor_kind="model",
                        content_role="response",
                        origin_kind="model_generated",
                        timestamp=timestamp,
                        source_file=source_file,
                        content=truncated,
                        content_len=content_len,
                        metadata=_merge_metadata(payload, { **current_configuration, "source_role": "assistant", "actor_evidence": "response_item_assistant_role", "content_truncated": ( content_len > TRUNCATE_RESPONSE ), }),
                        source_raw=source_raw,
                    ), rtype, payload, line_num)
                elif diagnostics is not None:
                    diagnostics["ignored_records"] = (
                        diagnostics.get("ignored_records", 0) + 1
                    )
                continue

            if item_type == "tool_search_call":
                arguments = sanitize_value(
                    payload.get("arguments") or {}, redact_enabled
                )
                yield _annotate_source(_base_event(
                    line_num=line_num,
                    session_id=session_id,
                    event_type="tool_call",
                    subtype="tool_failure" if _failed_status(payload) else None,
                    role="assistant",
                    event_kind="tool.call",
                    actor_kind="model",
                    content_role="tool_request",
                    origin_kind="model_generated",
                    timestamp=timestamp,
                    source_file=source_file,
                    tool_name="tool_search",
                    tool_input=json.dumps( arguments, separators=(",", ":"), ensure_ascii=False ),
                    metadata=_merge_metadata( payload, current_configuration ),
                    source_raw=source_raw,
                ), rtype, payload, line_num)
                continue

            if item_type == "tool_search_output":
                tools = sanitize_value(
                    payload.get("tools") or [], redact_enabled
                )
                text = json.dumps(
                    tools, separators=(",", ":"), ensure_ascii=False
                )
                bounded = _bounded_content(
                    text, opts, record_type="tool_search_output",
                    event_kind="tool.result", limit=TRUNCATE_TOOL_RESULT,
                )
                if bounded is None:
                    continue
                truncated, content_len = bounded
                yield _annotate_source(_base_event(
                    line_num=line_num,
                    session_id=session_id,
                    event_type="system_event",
                    subtype="tool_result",
                    role="harness",
                    event_kind="tool.result",
                    actor_kind="harness",
                    content_role="tool_result",
                    origin_kind="harness_generated",
                    timestamp=timestamp,
                    source_file=source_file,
                    content=truncated,
                    content_len=content_len,
                    tool_name="tool_search",
                    tool_output=truncated,
                    metadata=_merge_metadata( payload, current_configuration ),
                    source_raw=source_raw,
                ), rtype, payload, line_num)
                continue

            if item_type in ("function_call", "custom_tool_call"):
                yield _annotate_source(_base_event(
                    line_num=line_num,
                    session_id=session_id,
                    event_type="tool_call",
                    subtype="tool_failure" if _failed_status(payload) else None,
                    role="assistant",
                    timestamp=timestamp,
                    source_file=source_file,
                    tool_name=payload.get("name"),
                    tool_input=_tool_input(payload, redact_enabled),
                    file_path=_patched_file(payload),
                    metadata=_merge_metadata(payload, current_configuration),
                    source_raw=source_raw,
                ), rtype, payload, line_num)
                continue

            if item_type == "web_search_call":
                action = sanitize_value(
                    payload.get("action") or {}, redact_enabled
                )
                yield _annotate_source(_base_event(
                    line_num=line_num,
                    session_id=session_id,
                    event_type="tool_call",
                    subtype=None,
                    role="assistant",
                    timestamp=timestamp,
                    source_file=source_file,
                    tool_name="web_search",
                    tool_input=json.dumps( action, separators=(",", ":"), ensure_ascii=False ),
                    metadata=_merge_metadata(payload, current_configuration),
                    source_raw=source_raw,
                ), rtype, payload, line_num)
                continue

            if item_type in ("function_call_output", "custom_tool_call_output"):
                call_id = payload.get("call_id")
                call_id_text = str(call_id) if call_id else ""
                application_failure = mcp_failures.get(call_id_text)
                output = payload.get("output")
                text = output if isinstance(output, str) else json.dumps(output, ensure_ascii=False)
                bounded = _bounded_content(
                    text, opts, record_type="tool_result",
                    event_kind="tool.result", limit=TRUNCATE_TOOL_RESULT,
                )
                if bounded is None:
                    continue
                truncated, content_len = bounded
                yield _annotate_source(_base_event(
                    line_num=line_num,
                    session_id=session_id,
                    event_type="user_message",
                    subtype="tool_failure" if application_failure else "tool_result",
                    role="user",
                    timestamp=timestamp,
                    source_file=source_file,
                    content=truncated,
                    content_len=content_len,
                    tool_name=call_map.get(str(call_id)) if call_id else None,
                    tool_output=truncated,
                    metadata=_merge_metadata(payload, { **current_configuration, **({ "application_status": "failed", "result_status_evidence": application_failure, } if application_failure else {}), }),
                    source_raw=source_raw,
                    # The wrapper is kept verbatim; the header fields are lifted beside
                    # it so wall time, token count, and exit code are queryable without
                    # re-parsing the text.
                    tool_output_structured=_decoded_output(payload.get("output")),
                    # Codex states `status` on few outputs, so the exit code it states
                    # in the output header is the fallback; where neither exists the
                    # result stays unknown rather than being assumed successful.
                    source_status=(
                        "application_error" if application_failure
                        else payload.get("status") or _exit_code_status(payload)
                    ),
                    normalized_status="failed" if application_failure else None,
                ), rtype, payload, line_num)
                continue

            if diagnostics is not None:
                if item_type == "ghost_snapshot":
                    diagnostics["known_ignored_records"] = (
                        diagnostics.get("known_ignored_records", 0) + 1
                    )
                    diagnostics["intermediate_state_records"] = (
                        diagnostics.get("intermediate_state_records", 0) + 1
                    )
                else:
                    diagnostics["ignored_records"] = (
                        diagnostics.get("ignored_records", 0) + 1
                    )
            continue

        elif rtype == "event_msg":
            msg_type = payload.get("type", "")
            collaboration = {
                "collab_agent_spawn_begin": (
                    "collab_agent_spawn_begin",
                    "collaboration.spawn.begin",
                    "delegated_task",
                ),
                "collab_agent_spawn_end": (
                    "collab_agent_spawn_end",
                    "collaboration.spawn.end",
                    "status",
                ),
                "collab_agent_interaction_begin": (
                    "collab_agent_interaction_begin",
                    "collaboration.message.begin",
                    "delegated_task",
                ),
                "collab_agent_interaction_end": (
                    "collab_agent_interaction_end",
                    "collaboration.message.end",
                    "status",
                ),
                "collab_waiting_begin": (
                    "collab_waiting_begin",
                    "collaboration.wait.begin",
                    "status",
                ),
                "collab_waiting_end": (
                    "collab_waiting_end",
                    "collaboration.wait.end",
                    "status",
                ),
                "collab_close_begin": (
                    "collab_close_begin",
                    "collaboration.close.begin",
                    "status",
                ),
                "collab_close_end": (
                    "collab_close_end",
                    "collaboration.close.end",
                    "status",
                ),
                "collab_resume_begin": (
                    "collab_resume_begin",
                    "collaboration.resume.begin",
                    "status",
                ),
                "collab_resume_end": (
                    "collab_resume_end",
                    "collaboration.resume.end",
                    "status",
                ),
                "sub_agent_activity": (
                    "subagent_activity",
                    "collaboration.activity",
                    "status",
                ),
                "subagent_activity": (
                    "subagent_activity",
                    "collaboration.activity",
                    "status",
                ),
            }.get(msg_type)
            if collaboration is not None:
                subtype, event_kind, content_role = collaboration
                prompt = payload.get("prompt")
                content = None
                content_len = None
                if isinstance(prompt, str) and prompt:
                    prompt = apply_processing(
                        prompt, opts, vendor="Codex",
                        record_type=msg_type,
                        event_kind=event_kind, phase="pre",
                    )
                    if prompt is None:
                        continue
                    content, content_len = _truncate(
                        prompt, TRUNCATE_PROMPT
                    )
                    content = apply_processing(
                        content, opts, vendor="Codex",
                        record_type=msg_type,
                        event_kind=event_kind, phase="post",
                    )
                    if content is None:
                        continue
                metadata_fields = (
                    "call_id", "sender_thread_id", "receiver_thread_id",
                    "new_thread_id", "agent_thread_id", "agent_path", "kind",
                    "status", "model", "reasoning_effort",
                    "new_agent_nickname", "new_agent_role",
                    "receiver_agent_nickname", "receiver_agent_role",
                    "started_at_ms", "completed_at_ms", "occurred_at_ms",
                    "receiver_thread_ids", "agents_states",
                )
                metadata = {
                    key: sanitize_value(payload[key], redact_enabled)
                    for key in metadata_fields
                    if payload.get(key) is not None
                }
                metadata.update(current_configuration)
                yield _annotate_source(_base_event(
                    line_num=line_num,
                    session_id=session_id,
                    event_type="system_event",
                    subtype=subtype,
                    role="harness",
                    event_kind=event_kind,
                    actor_kind="harness",
                    content_role=content_role,
                    origin_kind="harness_generated",
                    timestamp=timestamp,
                    source_file=source_file,
                    content=content,
                    content_len=content_len,
                    metadata=json.dumps(metadata, separators=(",", ":")) if metadata else None,
                    source_raw=source_raw,
                ), rtype, payload, line_num)
                continue
            if msg_type == "context_compacted":
                if diagnostics is not None:
                    diagnostics["known_ignored_records"] = (
                        diagnostics.get("known_ignored_records", 0) + 1
                    )
                continue
            if msg_type == "thread_rolled_back":
                yield _annotate_source(_base_event(
                    line_num=line_num,
                    session_id=session_id,
                    event_type="system_event",
                    subtype="thread_rolled_back",
                    role="harness",
                    event_kind="context.rollback",
                    actor_kind="harness",
                    content_role="status",
                    origin_kind="harness_generated",
                    timestamp=timestamp,
                    source_file=source_file,
                    metadata=json.dumps({ "removed_user_turns": payload.get("num_turns"), }, separators=(",", ":")),
                    source_raw=source_raw,
                ), rtype, payload, line_num)
                continue
            if msg_type in {"task_started", "task_complete"}:
                is_start = msg_type == "task_started"
                metadata = {
                    key: payload.get(key)
                    for key in (
                        "turn_id", "started_at", "completed_at", "duration_ms",
                        "time_to_first_token_ms", "model_context_window",
                        "collaboration_mode_kind",
                    )
                    if payload.get(key) is not None
                }
                if isinstance(payload.get("last_agent_message"), str):
                    metadata["last_agent_message_characters"] = len(
                        payload["last_agent_message"]
                    )
                    metadata["last_agent_message_not_duplicated"] = True
                yield _annotate_source(_base_event(
                    line_num=line_num,
                    session_id=session_id,
                    event_type="lifecycle_event",
                    subtype=msg_type,
                    role="harness",
                    event_kind="lifecycle.start" if is_start else "lifecycle.complete",
                    actor_kind="harness",
                    content_role="status",
                    origin_kind="harness_generated",
                    timestamp=timestamp,
                    source_file=source_file,
                    metadata=json.dumps(metadata, separators=(",", ":")),
                    source_raw=source_raw,
                ), rtype, payload, line_num)
                continue
            if msg_type in {"web_search_end", "patch_apply_end"}:
                call_id = payload.get("call_id")
                failed = (
                    payload.get("success") is False
                    or str(payload.get("status") or "").lower()
                    in {"failed", "failure", "error"}
                )
                metadata = {
                    "call_id": str(call_id) if call_id is not None else None,
                    "status": payload.get("status"),
                    "success": payload.get("success"),
                    "change_count": (
                        len(payload["changes"])
                        if isinstance(payload.get("changes"), dict) else None
                    ),
                    "duplicate_output_not_retained": True,
                }
                yield _annotate_source(_base_event(
                    line_num=line_num,
                    session_id=session_id,
                    event_type="user_message",
                    subtype="tool_failure" if failed else "tool_result",
                    role="tool",
                    event_kind="tool.result",
                    actor_kind="tool",
                    content_role="tool_result",
                    origin_kind="tool_generated",
                    timestamp=timestamp,
                    source_file=source_file,
                    tool_name="web_search" if msg_type == "web_search_end" else "apply_patch",
                    metadata=json.dumps( {key: value for key, value in metadata.items() if value is not None}, separators=(",", ":"), ),
                    source_raw=source_raw,
                    source_status=payload.get("status"),
                    normalized_status="failed" if failed else "succeeded",
                ), rtype, payload, line_num)
                continue
            if msg_type == "mcp_tool_call_end":
                invocation = payload.get("invocation") or {}
                if not isinstance(invocation, dict):
                    invocation = {}
                duration = payload.get("duration") or {}
                duration_ms = None
                if isinstance(duration, dict):
                    seconds = duration.get("secs")
                    nanos = duration.get("nanos")
                    if isinstance(seconds, int) and isinstance(nanos, int):
                        duration_ms = seconds * 1000 + nanos / 1_000_000
                result = payload.get("result")
                succeeded = (
                    isinstance(result, dict)
                    and "Ok" in result
                )
                failed = (
                    isinstance(result, dict)
                    and "Err" in result
                )
                metadata = {
                    "call_id": payload.get("call_id"),
                    "mcp_server": invocation.get("server"),
                    "mcp_tool": invocation.get("tool"),
                    "connector_id": payload.get("connector_id"),
                    "app_name": payload.get("app_name"),
                    "action_name": payload.get("action_name"),
                    "link_id": payload.get("link_id"),
                    "plugin_id": payload.get("plugin_id"),
                    "read_only_hint": payload.get("read_only_hint"),
                    "duration_ms": duration_ms,
                    "result_status": (
                        "succeeded" if succeeded
                        else "failed" if failed
                        else "unknown"
                    ),
                    "transport_status": (
                        "succeeded" if succeeded
                        else "failed" if failed
                        else "unknown"
                    ),
                    "application_status": (
                        "failed"
                        if str(payload.get("call_id")) in mcp_failures
                        else None
                    ),
                    "result_status_evidence": mcp_failures.get(
                        str(payload.get("call_id"))
                    ),
                    "duplicate_result_body_not_retained": True,
                }
                yield _annotate_source(_base_event(
                    line_num=line_num,
                    session_id=session_id,
                    event_type="system_event",
                    subtype="mcp_tool_call_end",
                    role="harness",
                    event_kind="tool.transport",
                    actor_kind="harness",
                    content_role="status",
                    origin_kind="harness_generated",
                    timestamp=timestamp,
                    source_file=source_file,
                    tool_name=invocation.get("tool"),
                    metadata=json.dumps( { key: value for key, value in metadata.items() if value is not None }, separators=(",", ":"), ),
                    source_raw=source_raw,
                    source_status=metadata["result_status"],
                    normalized_status="succeeded" if succeeded else "failed" if failed else None,
                ), rtype, payload, line_num)
                continue
            if msg_type != "turn_aborted":
                if diagnostics is not None:
                    known_kind = {
                        "agent_message": "duplicate_envelope_records",
                        "user_message": "duplicate_envelope_records",
                        "agent_reasoning": "duplicate_reasoning_records",
                        "token_count": "usage_records",
                    }.get(msg_type)
                    if known_kind:
                        diagnostics["known_ignored_records"] = (
                            diagnostics.get("known_ignored_records", 0) + 1
                        )
                        diagnostics[known_kind] = (
                            diagnostics.get(known_kind, 0) + 1
                        )
                    else:
                        diagnostics["ignored_records"] = (
                            diagnostics.get("ignored_records", 0) + 1
                        )
                continue
            content = str(payload.get("reason") or payload.get("info") or "turn aborted")
            content = apply_processing(
                content, opts, vendor="Codex", record_type="turn_aborted",
                event_kind="lifecycle.abort", phase="pre",
            )
            if content is None:
                continue
            truncated, content_len = _truncate(content, 500)
            truncated = apply_processing(
                truncated, opts, vendor="Codex", record_type="turn_aborted",
                event_kind="lifecycle.abort", phase="post",
            )
            if truncated is None:
                continue
            ev = {
                "session_id": session_id,
                "event_id": str(line_num),
                "event_type": "assistant_message",
                "subtype": "turn_aborted",
                "role": "assistant",
                "content": truncated,
                "content_len": content_len,
                "content_ref": None,
                "tool_name": None,
                "tool_input": None,
                "tool_output": None,
                "timestamp": timestamp,
                "file_path": None,
                "source_file": source_file,
                "metadata": json.dumps({"event_msg_type": msg_type}) if msg_type else None,
                "source_raw": source_raw,
            }
            yield _annotate_source(ev, rtype, payload, line_num)
        elif diagnostics is not None:
            if rtype == "world_state":
                diagnostics["known_ignored_records"] = (
                    diagnostics.get("known_ignored_records", 0) + 1
                )
                diagnostics["intermediate_state_records"] = (
                    diagnostics.get("intermediate_state_records", 0) + 1
                )
            else:
                diagnostics["ignored_records"] = (
                    diagnostics.get("ignored_records", 0) + 1
                )


def _bounded_content(
    text: str | None,
    opts: dict,
    *,
    record_type: str,
    event_kind: str,
    limit: int,
) -> tuple[str, int] | None:
    """Apply content policy, bound the result, and apply it again.

    Returns `(content, original_length)`, or None when the policy dropped the
    value at either phase -- which the caller reads as "skip this record".

    Every content-bearing branch repeated the same five steps: process before
    bounding, check for a drop, truncate, process after bounding, check again.
    Twenty of `process_file`'s branches were those two `None` guards rather
    than record dispatch, so the shape of the function said "many kinds of
    record" when it mostly said "one policy applied many times".

    Both phases are kept because they answer different questions: the pre
    phase sees the whole value and can reject it on content, while the post
    phase sees what will actually be stored. Collapsing them into one call
    would change what the policy is applied to, not merely how it is written.
    """
    if text is None:
        return None
    processed = apply_processing(
        text, opts, vendor="Codex", record_type=record_type,
        event_kind=event_kind, phase="pre",
    )
    if processed is None:
        return None
    truncated, content_len = _truncate(processed, limit)
    truncated = apply_processing(
        truncated, opts, vendor="Codex", record_type=record_type,
        event_kind=event_kind, phase="post",
    )
    if truncated is None:
        return None
    return truncated, content_len


def _truncate(text: str, limit: int) -> tuple[str, int]:
    """Return (truncated, full_len)."""
    if text is None:
        return "", 0
    s = str(text)
    n = len(s)
    if limit <= 0:
        return "…" if n else "", n
    if n <= limit:
        return s, n
    return s[: limit - 1] + "…", n
