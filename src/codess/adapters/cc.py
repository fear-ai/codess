"""CC JSONL parser and normalizer."""

import json
import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from codess import field_state
from codess.bounded_jsonl import iter_bounded_jsonl
from codess.config import (
    MAX_EXTERNAL_CONTENT_BYTES,
    TRUNCATE_DIALOG,
    TRUNCATE_GREP_PATTERN,
    TRUNCATE_PROMPT,
    TRUNCATE_RESPONSE,
    TRUNCATE_TOOL_RESULT,
)
from codess.context_content import bound_context_content, truncate_content
from codess.hashing import codess_bytes_hash
from codess.mapping import annotate_mapping
from codess.sanitize import apply_sanitization, sanitize_value
from codess.tool_result_status import application_failure_evidence

log = logging.getLogger(__name__)


class SourceCompatibilityError(ValueError):
    """A source record cannot be mapped without silently losing meaning."""

SKIP_TYPES = frozenset({
    "progress", "file-history-snapshot", "file-history-delta", "queue-operation",
    "last-prompt", "system",
})

PERMISSION_DENIAL_MARKERS = (
    "permission for this tool use was denied",
    "tool use was rejected",
    "doesn't want to proceed with this tool use",
)


def _local_command_semantics(text: str) -> dict | None:
    """Classify Claude's tagged local-command records across envelope variants."""
    stripped = text.strip()
    if stripped.startswith("<local-command-caveat>"):
        return {
            "event_type": "system_event",
            "subtype": "local_command_notice",
            "role": "harness",
            "event_kind": "message.context",
            "actor_kind": "harness",
            "content_role": "context",
            "origin_kind": "harness_injected",
            "command_name": None,
        }
    if stripped.startswith("<command-name>"):
        end = stripped.find("</command-name>")
        command_name = None
        if end >= 0:
            command_name = stripped[len("<command-name>"):end].strip() or None
        return {
            "event_type": "user_message",
            "subtype": "slash_command",
            "role": "user",
            "event_kind": "command.invoke",
            "actor_kind": "human",
            "content_role": "command",
            "origin_kind": "direct_user_input",
            "command_name": command_name,
        }
    if stripped.startswith("<local-command-stdout>"):
        return {
            "event_type": "system_event",
            "subtype": "local_command_output",
            "role": "harness",
            "event_kind": "command.result",
            "actor_kind": "harness",
            "content_role": "result",
            "origin_kind": "harness_generated",
            "command_name": None,
        }
    return None


def _user_origin_semantics(record: dict, source_file: str) -> dict:
    """Classify Claude user envelopes from explicit runtime evidence."""
    origin = record.get("origin") or {}
    source_origin_kind = (
        origin.get("kind") if isinstance(origin, dict) else str(origin)
    )
    prompt_source = record.get("promptSource")
    delegated_evidence = []
    if record.get("isSidechain") is True:
        delegated_evidence.append("record.isSidechain")
    if record.get("agentId") is not None:
        delegated_evidence.append("record.agentId")
    if "subagents" in Path(source_file).parts:
        delegated_evidence.append("source_path.subagents")
    if delegated_evidence:
        return {
            "event_type": "system_event",
            "subtype": "delegated_prompt",
            "role": "harness",
            "event_kind": "message.context",
            "actor_kind": "harness",
            "content_role": "delegated_task",
            "origin_kind": "harness_delegated",
            "actor_evidence": delegated_evidence,
            "source_origin_kind": source_origin_kind,
            "prompt_source": prompt_source,
        }
    harness_evidence = []
    if prompt_source == "system":
        harness_evidence.append("record.promptSource=system")
    if source_origin_kind not in {None, "human"}:
        harness_evidence.append(f"record.origin.kind={source_origin_kind}")
    if harness_evidence:
        return {
            "event_type": "system_event",
            "subtype": (
                "task_notification"
                if source_origin_kind == "task-notification"
                else "system_prompt"
            ),
            "role": "harness",
            "event_kind": "message.context",
            "actor_kind": "harness",
            "content_role": (
                "notification"
                if source_origin_kind == "task-notification" else "context"
            ),
            "origin_kind": "harness_injected",
            "actor_evidence": harness_evidence,
            "source_origin_kind": source_origin_kind,
            "prompt_source": prompt_source,
        }
    return {
        "event_type": "user_message",
        "subtype": "prompt",
        "role": "user",
        "event_kind": "message.prompt",
        "actor_kind": "human",
        "content_role": "prompt",
        "origin_kind": "direct_user_input",
        "actor_evidence": (
            ["record.origin.kind=human"]
            if source_origin_kind == "human"
            else ["no delegated_or_harness_marker"]
        ),
        "source_origin_kind": source_origin_kind,
        "prompt_source": prompt_source,
    }


def iter_cc_records(
    path: Path,
    diagnostics: dict[str, int] | None = None,
    *,
    warn: bool = True,
) -> Iterator[tuple[int, dict, str]]:
    """Stream JSONL; yield (line_num, record, raw_line). Skip empty lines; on JSON error log and skip."""
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


# Claude's `entrypoint` mapped onto CoSchema's `surface_kind` vocabulary. An unlisted
# value is left unmapped, since a wrong surface is worse than an absent one. `sdk-cli`
# is `api` rather than `cli`: those records carry `promptSource: sdk`, so the Session was
# driven programmatically rather than typed at a terminal.
_CC_SURFACE = {
    "cli": "cli",
    "claude-desktop": "desktop",
    "sdk-cli": "api",
}

# Resource bound on an otherwise unbounded file, not a claim the facts appear within it:
# one stated later is simply not found. Over 370 real Sessions the latest first statement
# of any fact sought here was line 7.
MAX_FACT_RECORDS = 256


def get_session_metadata(path: Path) -> dict:
    """Return bounded session facts observed directly in Claude records.

    `entrypoint` is a per-record field but a Session-level fact -- across 370 real
    Sessions none mixed two values -- so the first observed value describes the Session.
    Only observed values are returned, so `store` falls back to the vendor profile where
    a record states none.
    """
    facts: dict[str, str] = {}
    for line_num, record, _raw in iter_cc_records(path, warn=False):
        version = record.get("version") or record.get("claudeCodeVersion")
        if version is not None and "harness_version" not in facts:
            facts["harness_version"] = str(version)
        cwd = record.get("cwd")
        if isinstance(cwd, str) and cwd and "source_cwd" not in facts:
            facts["source_cwd"] = cwd
        entrypoint = record.get("entrypoint")
        if (
            isinstance(entrypoint, str) and entrypoint.strip()
            and "entrypoint" not in facts
        ):
            facts["entrypoint"] = entrypoint.strip()
            mapped = _CC_SURFACE.get(entrypoint.strip().lower())
            if mapped:
                facts["surface_kind"] = mapped
        if line_num >= MAX_FACT_RECORDS:
            break
    return facts


def get_session_lineage(path: Path) -> dict:
    """Return direct Claude fork evidence without reading unbounded records."""
    try:
        for _line, record, error in iter_bounded_jsonl(path):
            if error or record is None or record.get("type") != "fork-context-ref":
                continue
            parent = record.get("parentSessionId")
            if not parent:
                continue
            return {
                "parent_session_id": str(parent),
                "session_relation_kind": "fork",
                "lineage_provenance": "fork-context-ref.parentSessionId",
                "agent_id": record.get("agentId"),
                "parent_last_uuid": record.get("parentLastUuid"),
            }
    except OSError:
        pass
    return {}


def should_skip(record: dict) -> bool:
    """Return True for progress, file-history-snapshot, queue-operation, last-prompt, system (empty)."""
    rtype = record.get("type")
    if rtype == "system":
        content = record.get("message", {}).get("content")
        if content and (not isinstance(content, list) or content):
            return False  # Include system with content
        return True
    return rtype in SKIP_TYPES


def _is_permission_denial(text: str) -> bool:
    """Recognize explicit Claude denial text; other error results are failures."""
    lowered = text.lower()
    return any(marker in lowered for marker in PERMISSION_DENIAL_MARKERS)


def _normalize_compaction(
    record: dict,
    line_num: int,
    session_id: str,
    source_file: str,
) -> dict:
    """Retain an explicit compact boundary and its observed accounting."""
    compact = record.get("compactMetadata") or {}
    metadata = {"audit_kind": "context_compaction"}
    field_names = {
        "trigger": "trigger",
        "preTokens": "pre_tokens",
        "postTokens": "post_tokens",
        "durationMs": "duration_ms",
        "preCompactDiscoveredTools": "pre_compact_discovered_tools",
        "preservedSegment": "preserved_segment",
        "preservedMessages": "preserved_messages",
        "precomputed": "precomputed",
    }
    for source_name, common_name in field_names.items():
        if compact.get(source_name) is not None:
            metadata[common_name] = compact[source_name]
    return {
        "session_id": session_id,
        "event_id": str(line_num),
        "event_type": "system_event",
        "subtype": "context_compaction",
        "role": "system",
        "content": None,
        "content_len": None,
        "content_ref": None,
        "tool_name": None,
        "tool_input": None,
        "tool_output": None,
        "timestamp": _get_timestamp(record),
        "file_path": None,
        "source_file": source_file,
        "metadata": json.dumps(metadata, separators=(",", ":")),
        "source_raw": None,
    }


def _mapping_rule(event: dict) -> str:
    """Return the declared primary rule for one Claude-derived event."""
    event_type = event.get("event_type")
    subtype = event.get("subtype")
    if event_type == "system_event" and subtype == "context_compaction":
        return "claude.compaction"
    if event_type == "system_event" and subtype == "context_compaction_summary":
        return "claude.compaction-summary"
    if event_type == "external_content":
        return "claude.persisted-tool-result"
    if event_type == "tool_call":
        return "claude.tool-use"
    if subtype in {"tool_result", "tool_failure", "permission_denied"}:
        return "claude.tool-result"
    if event_type == "product_state":
        return _PRODUCT_STATE_RULES.get(subtype or "", "claude.product-state")
    if subtype == "fork_context_reference":
        return "claude.fork-context"
    if event_type == "lifecycle_event":
        return "claude.lifecycle"
    if event_type == "user_message" and subtype in {"prompt", "slash_command"}:
        return "claude.typed-prompt"
    return "claude.message"


def _annotate_source(event: dict, record: dict, line_num: int) -> dict:
    rule = _mapping_rule(event)
    applied = [rule]
    if record.get("parentUuid") or record.get("tool_use_id"):
        applied.append("claude.lineage")
    metadata = event.get("metadata")
    if metadata:
        try:
            if json.loads(metadata).get("configuration_provenance"):
                applied.append("claude.configuration")
        except (AttributeError, json.JSONDecodeError, TypeError):
            pass
    return annotate_mapping(
        event,
        source_record_type=str(record.get("type") or "unknown"),
        source_record_subtype=(
            str(record["subtype"]) if record.get("subtype") is not None else None
        ),
        source_record_locator=str(line_num),
        mapping_rule=rule,
        applied_rules=applied,
    )


def extract_tool_input(tool_name: str, input_obj: dict) -> dict:
    """Per-tool field selection per CSPlan §3.3 extract_tool_input."""
    if not input_obj:
        return {}
    out = {}
    name = (tool_name or "").lower()
    if name == "bash":
        for k in ("command", "description"):
            if k in input_obj:
                out[k] = input_obj[k]
    elif name == "read":
        for k in ("path", "file_path", "offset", "limit", "pages"):
            if k in input_obj:
                out[k] = input_obj[k]
    elif name in ("edit", "write"):
        for k in ("path", "file_path", "old_len", "new_len", "content_len", "replace_all"):
            if k in input_obj:
                out[k] = input_obj[k]
        if "old_string" in input_obj:
            out["old_len"] = len(str(input_obj["old_string"]))
        if "new_string" in input_obj:
            out["new_len"] = len(str(input_obj["new_string"]))
        if "content" in input_obj:
            out["content_len"] = len(str(input_obj["content"]))
    elif name == "grep":
        for k in ("pattern", "path", "output_mode", "glob"):
            if k in input_obj:
                v = input_obj[k]
                if k == "pattern" and isinstance(v, str) and len(v) > TRUNCATE_GREP_PATTERN:
                    v = v[: TRUNCATE_GREP_PATTERN - 1] + "…"
                out[k] = v
    elif name == "glob":
        for k in ("pattern", "path"):
            if k in input_obj:
                out[k] = input_obj[k]
    elif name == "agent":
        for k in ("subagent_type", "description", "model"):
            if k in input_obj:
                out[k] = input_obj[k]
        if "prompt" in input_obj:
            p = input_obj["prompt"]
            if isinstance(p, str):
                truncated, _ = truncate_content(p, TRUNCATE_PROMPT)
                out["prompt"] = truncated
            else:
                out["prompt"] = p
    elif name == "skill":
        for k in ("skill", "args"):
            if k in input_obj:
                out[k] = input_obj[k]
    elif name in ("mcp_task", "task"):
        for k in ("subagent_type", "description"):
            if k in input_obj:
                out[k] = input_obj[k]
        if "prompt" in input_obj:
            p = input_obj["prompt"]
            if isinstance(p, str):
                truncated, _ = truncate_content(p, TRUNCATE_PROMPT)
                out["prompt"] = truncated
            else:
                out["prompt"] = p
    else:
        out = dict(input_obj)
    return out





def _build_tool_map(path: Path) -> dict[str, str]:
    """First pass: build tool_use_id -> tool_name from assistant records."""
    tool_map = {}
    for _line_num, record, _ in iter_cc_records(path, warn=False):
        if record.get("type") != "assistant":
            continue
        content = record.get("message", {}).get("content") or []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                tid = block.get("id")
                tname = block.get("name")
                if tid and tname:
                    tool_map[tid] = tname
    return tool_map


def _parse_timestamp(ts: Any) -> float | None:
    """Convert timestamp to Unix ms. Handles float or ISO 8601 string."""
    if ts is None:
        return None
    if isinstance(ts, (int, float)):
        return float(ts)
    if isinstance(ts, str):
        try:
            # `fromisoformat` parses a `Z` suffix natively since 3.11, which
            # is the declared floor, so the `+00:00` substitution five sites
            # carried is removable duplication rather than a compatibility need.
            dt = datetime.fromisoformat(ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt.timestamp() * 1000
        except (ValueError, TypeError):
            pass
    return None


def _get_timestamp(record: dict, opts: dict | None = None) -> float | None:
    """Return the record's timestamp in Unix milliseconds, or None.

    CCSchema records the stamp as ``timestamp`` on the record or nested in
    ``message``, so both positions are read, top level first.

    **Selects on field state rather than truthiness.** ``_parse_timestamp``
    accepts ``0`` and returns ``0.0``, so an ``or`` chain would skip that value
    and read the nested position instead. A vacant state -- absent, null, or
    empty -- moves to the next position; any other state stops the search, so
    an unparseable value is diagnosed here rather than masked by the nested
    stamp.

    With ``opts``, a stamp that stops the search but does not parse is reported
    as ``malformed``; a vacant one is reported as its own state.
    """
    for source in (record, record.get("message") or {}):
        raw, state = field_state.get_state(source, "timestamp")
        if state not in field_state.VACANT_STATES:
            break
    parsed = _parse_timestamp(raw)
    if opts is not None and parsed is None:
        if state == field_state.PRESENT:
            # `classify` sees a non-empty value; that it had to be a timestamp
            # is known here, so the narrower state is set here.
            state = field_state.MALFORMED
        field_state.diagnose(
            opts, field="event_at", state=state, source_field="timestamp", value=raw
        )
    return parsed


def _block_event_id(line_num: int, emitted_index: int) -> str:
    """Keep the legacy first id while making additional line events unique."""
    return str(line_num) if emitted_index == 0 else f"{line_num}:{emitted_index}"


def _event_metadata(
    record: dict, tool_use_id: str | None = None,
    extra: dict | None = None,
) -> str | None:
    """Retain stable Claude lineage identifiers without copying the envelope."""
    metadata = {}
    if record.get("uuid") is not None:
        metadata["record_uuid"] = record["uuid"]
    if record.get("parentUuid") is not None:
        metadata["parent_uuid"] = record["parentUuid"]
    if tool_use_id is not None:
        metadata["tool_use_id"] = tool_use_id
    if extra:
        metadata.update({key: value for key, value in extra.items() if value is not None})
    return json.dumps(metadata, separators=(",", ":")) if metadata else None


def _assistant_configuration(record: dict) -> dict:
    """Retain verified Claude model settings with their exact source fields.

    `effort` is read from the record's top level, which is where Claude states it, rather
    than from `message` alongside the model.
    """
    message = record.get("message")
    if not isinstance(message, dict):
        message = {}
    values: dict[str, Any] = {}
    provenance: dict[str, Any] = {}

    def keep(common: str, source_field: str, value: Any) -> None:
        if value is None or isinstance(value, (dict, list)):
            return
        text = str(value).strip()
        if text:
            values[common] = text
            provenance[common] = {
                "source_record_type": "assistant",
                "source_record_locator": str(record.get("uuid") or "line"),
                "source_field": source_field,
            }

    keep("model", "message.model", message.get("model"))
    keep("reasoning_effort", "effort", record.get("effort"))
    usage = message.get("usage")
    if isinstance(usage, dict):
        keep(
            "service_tier", "message.usage.service_tier",
            usage.get("service_tier"),
        )
    if provenance:
        values["configuration_provenance"] = provenance
    return values


def _diagnostic(opts: dict, name: str, count: int = 1) -> None:
    diagnostics = opts.get("diagnostics")
    if diagnostics is not None:
        diagnostics[name] = diagnostics.get(name, 0) + count


def _record_refused(
    opts: dict,
    reason_code: str,
    *,
    source_file: str | None = None,
    line_num: int | None = None,
    record_type: str | None = None,
    detail: str | None = None,
) -> None:
    """Record that one source record was read and not admitted.

    The counter alone said *how many* records an adapter refused; this says
    *which*, with the locator the call site already holds. Without it the
    coverage report's record-level loss is structurally zero and that zero is
    unfalsifiable rather than measured -- a reader cannot distinguish "no
    record was refused" from "refusals are not recorded".

    Collected rather than written here: an adapter must not write SQL (3.3),
    so these accumulate on `opts` and `store` persists them against the Source
    once it is known.
    """
    _diagnostic(opts, reason_code)
    pending = opts.get("record_diagnostics")
    if pending is None:
        return
    pending.append({
        "granularity": "record",
        "reason_code": reason_code,
        "source_locator": f"line:{line_num}" if line_num is not None else None,
        "source_file": source_file,
        "source_record_type": record_type,
        "detail": detail,
    })


def _process_text(text: str, opts: dict, *, phase: str, record_type: str) -> str | None:
    from codess.content_processing import apply_processing
    return apply_processing(
        text, opts, vendor="Claude", record_type=record_type, phase=phase
    )


def _base_event(
    *, session_id: str, event_id: str, event_type: str, subtype: str,
    role: str, timestamp: float | None, source_file: str,
) -> dict:
    return {
        "session_id": session_id, "event_id": event_id,
        "event_type": event_type, "subtype": subtype, "role": role,
        "content": None, "content_len": None, "content_ref": None,
        "tool_name": None, "tool_input": None, "tool_output": None,
        "timestamp": timestamp, "file_path": None,
        "source_file": source_file, "metadata": None, "source_raw": None,
    }


def _attach_timestamp_state(event: dict, record: dict, timestamp: Any) -> None:
    if timestamp is not None:
        return
    value, state = field_state.get_state(record, "timestamp")
    if state == field_state.PRESENT:
        state = field_state.MALFORMED
    field_state.attach(
        event, field="event_at", state=state,
        source_field="timestamp", value=value,
    )


def _attach_configuration_state(event: dict, record: dict) -> None:
    message, message_state = field_state.get_state(record, "message")
    if message_state == field_state.PRESENT and not isinstance(message, dict):
        field_state.attach(
            event, field="model", state=field_state.MALFORMED,
            source_field="message", value=message,
        )
        return
    message = message if isinstance(message, dict) else {}
    model, model_state = field_state.get_state(message, "model")
    if model_state == field_state.PRESENT and isinstance(model, (dict, list)):
        model_state = field_state.MALFORMED
    field_state.attach(
        event, field="model", state=model_state,
        source_field="message.model", value=model,
    )
    usage = message.get("usage")
    if usage is None:
        return
    if not isinstance(usage, dict):
        field_state.attach(
            event, field="service_tier", state=field_state.MALFORMED,
            source_field="message.usage", value=usage,
        )
        return
    tier, tier_state = field_state.get_state(usage, "service_tier")
    if tier_state == field_state.PRESENT and isinstance(tier, (dict, list)):
        tier_state = field_state.MALFORMED
    field_state.attach(
        event, field="service_tier", state=tier_state,
        source_field="message.usage.service_tier", value=tier,
    )


def _attach_prompt_origin_state(event: dict, record: dict) -> None:
    origin, origin_state = field_state.get_state(record, "origin")
    prompt_source, prompt_state = field_state.get_state(record, "promptSource")
    if origin_state == field_state.PRESENT and not isinstance(origin, (dict, str)):
        origin_state = field_state.MALFORMED
    if (
        origin_state == field_state.ABSENT
        and prompt_state != field_state.ABSENT
    ):
        return
    field_state.attach(
        event, field="prompt_origin", state=origin_state,
        source_field="origin", value=origin,
    )
    if prompt_state == field_state.PRESENT and isinstance(
        prompt_source, (dict, list)
    ):
        field_state.attach(
            event, field="prompt_origin", state=field_state.MALFORMED,
            source_field="promptSource", value=prompt_source,
        )


PRODUCT_LABEL_LIMIT = 512
"""Bound for a Session label -- a title or agent name, never a message."""

NAMED_LABEL_RECORDS = {
    # record type -> (Event subtype, the field holding the label)
    "ai-title": ("ai_title", "aiTitle"),
    "custom-title": ("custom_title", "customTitle"),
    "agent-name": ("agent_name", "agentName"),
}
"""Records that carry one short label and differ only in where it lives."""


_PRODUCT_STATE_KINDS = {
    "ai_title": "session.label",
    "custom_title": "session.label",
    "agent_name": "session.label",
    "mode": "harness.setting",
    "permission_mode": "harness.setting",
    "context_attachment": "content.attachment",
    "file_history_snapshot": "content.attachment",
    "file_history_delta": "content.attachment",
    "last_prompt_marker": "session.marker",
}
"""Which Event kind each Claude product-state record belongs to.

One kind spanning all nine subtypes made a query for Session titles return
permission settings and file diffs as well -- it was Claude's largest kind,
with more Events than `tool.call`. The four kinds separate what a reader
actually selects on: what the Session is called, how the harness was
configured, what material was attached, and where a position was marked.
`last_prompt_marker` is its own kind rather than attached material because it
points at a position rather than carrying content.
"""


_PRODUCT_STATE_RULES = {
    subtype: f"claude.{kind.replace('.', '-')}"
    for subtype, kind in _PRODUCT_STATE_KINDS.items()
}
"""The released rule id for each subtype, derived from the kind it maps to.

Kept in step with `_PRODUCT_STATE_KINDS` by construction: a rule and the kind
it produces are the same decision, and deriving one from the other is what
stops the profile and the decoder disagreeing.
"""


def _product_state_kind(subtype: str | None) -> str:
    """The Event kind for one product-state subtype.

    An unrecognized subtype keeps the general kind rather than being forced
    into one of the four: `event_kind` is a declared open vocabulary, and a
    newly observed Claude record is evidence to classify deliberately, not to
    guess at from the nearest existing name.
    """
    return _PRODUCT_STATE_KINDS.get(subtype or "", "state.product")


def normalize_product_state(
    record: dict, line_num: int, session_id: str, source_file: str, opts: dict,
) -> dict | None:
    """Map bounded Claude product/lifecycle state without copying envelopes."""
    rtype = record.get("type")
    subtype = record.get("subtype")
    event = None
    metadata: dict = {}
    if rtype == "mode":
        event = _base_event(session_id=session_id, event_id=str(line_num), event_type="product_state", subtype="mode", role="harness", timestamp=_get_timestamp(record), source_file=source_file)
        metadata["mode"] = record.get("mode")
    elif rtype == "permission-mode":
        event = _base_event(session_id=session_id, event_id=str(line_num), event_type="product_state", subtype="permission_mode", role="harness", timestamp=_get_timestamp(record), source_file=source_file)
        metadata["permission_mode"] = record.get("permissionMode")
    elif rtype in NAMED_LABEL_RECORDS:
        # Three records that differ only in which field holds the label and
        # what the resulting Event is called. Written out separately they
        # were three copies of one construction, which is what made a
        # fourteen-branch dispatch look longer than its decisions (3.5.4).
        subtype, field = NAMED_LABEL_RECORDS[rtype]
        event = _base_event(session_id=session_id, event_id=str(line_num), event_type="product_state", subtype=subtype, role="harness", timestamp=_get_timestamp(record), source_file=source_file)
        label = _process_text(record.get(field) or "", opts, phase="pre", record_type=rtype)
        if label is not None:
            event["content"], event["content_len"] = truncate_content(
                label, PRODUCT_LABEL_LIMIT
            )
    elif rtype == "fork-context-ref":
        event = _base_event(session_id=session_id, event_id=str(line_num), event_type="lifecycle_event", subtype="fork_context_reference", role="harness", timestamp=_get_timestamp(record), source_file=source_file)
        metadata = {
            "parent_session_id": record.get("parentSessionId"),
            "parent_last_uuid": record.get("parentLastUuid"),
            "agent_id": record.get("agentId"),
            "context_length": record.get("contextLength"),
            "lineage_provenance": "fork-context-ref.parentSessionId",
        }
    elif rtype == "attachment":
        event = _base_event(session_id=session_id, event_id=str(line_num), event_type="product_state", subtype="context_attachment", role="harness", timestamp=_get_timestamp(record), source_file=source_file)
        attachment = record.get("attachment") or {}
        if isinstance(attachment, dict):
            metadata = {
                "attachment_type": attachment.get("type"),
                "item_count": attachment.get("itemCount"),
                "is_initial": attachment.get("isInitial"),
                "command_mode": attachment.get("commandMode"),
                "has_content": bool(attachment.get("content")),
            }
    elif rtype == "file-history-snapshot":
        event = _base_event(session_id=session_id, event_id=str(line_num), event_type="product_state", subtype="file_history_snapshot", role="harness", timestamp=_get_timestamp(record), source_file=source_file)
        metadata["snapshot_field_count"] = len(record)
    elif rtype == "file-history-delta":
        # Records that one tracked file was backed up, and which snapshot the
        # backup derives from. Harness product state like its snapshot
        # sibling, not a message: the file content is not in the record, only
        # the fact that a backup exists and where the harness tracked it.
        event = _base_event(session_id=session_id, event_id=str(line_num), event_type="product_state", subtype="file_history_delta", role="harness", timestamp=_get_timestamp(record), source_file=source_file)
        backup = record.get("backup")
        backup = backup if isinstance(backup, dict) else {}
        metadata.update({
            # The message this delta belongs to, and the snapshot it extends.
            # Both are vendor identifiers retained as recorded.
            "message_id": record.get("messageId"),
            "snapshot_message_id": record.get("snapshotMessageId"),
            "backup_version": backup.get("version"),
            "backup_time": backup.get("backupTime"),
            # The tracked path is retained as an Artifact locator elsewhere;
            # here only its presence is recorded, so this Event stays a
            # structural observation rather than a second copy of the path.
            "has_tracking_path": bool(record.get("trackingPath")),
            "has_backup": bool(backup),
        })
    elif rtype == "queue-operation":
        event = _base_event(session_id=session_id, event_id=str(line_num), event_type="lifecycle_event", subtype="queue_operation", role="harness", timestamp=_get_timestamp(record), source_file=source_file)
        metadata["operation"] = record.get("operation")
    elif rtype == "last-prompt":
        event = _base_event(session_id=session_id, event_id=str(line_num), event_type="product_state", subtype="last_prompt_marker", role="harness", timestamp=_get_timestamp(record), source_file=source_file)
        value = record.get("lastPrompt") or record.get("prompt") or ""
        metadata["content_len"] = len(str(value))
    elif rtype == "system" and subtype == "turn_duration":
        event = _base_event(session_id=session_id, event_id=str(line_num), event_type="lifecycle_event", subtype="turn_duration", role="harness", timestamp=_get_timestamp(record), source_file=source_file)
        metadata = {"duration_ms": record.get("durationMs"), "message_count": record.get("messageCount")}
    elif rtype == "system" and subtype == "scheduled_task_fire":
        event = _base_event(session_id=session_id, event_id=str(line_num), event_type="lifecycle_event", subtype="scheduled_task_fire", role="harness", timestamp=_get_timestamp(record), source_file=source_file)
    elif rtype == "system" and subtype == "model_consent_fallback":
        # One model was asked for and another answered. Both names are stated, so the
        # fallback is recorded as one fact rather than as two unrelated models: without
        # it the Session shows only the model that ran, and the request is lost.
        event = _base_event(session_id=session_id, event_id=str(line_num), event_type="lifecycle_event", subtype="model_fallback", role="harness", timestamp=_get_timestamp(record), source_file=source_file)
        metadata = {
            "requested_model": record.get("originalModel"),
            "fallback_model": record.get("fallbackModel"),
            "fallback_choice": record.get("choice"),
            "persisted_as_default": record.get("persistedAsDefault"),
        }
    elif rtype == "system" and subtype == "local_command":
        text = str(record.get("content") or "")
        text = _process_text(
            text, opts, phase="pre", record_type="system.local_command"
        )
        if text is None:
            return None
        text = _process_text(
            text, opts, phase="post", record_type="system.local_command"
        )
        if text is None:
            return None
        semantics = _local_command_semantics(text)
        if semantics is None:
            semantics = {
                "event_type": "system_event",
                "subtype": "local_command",
                "role": "harness",
                "event_kind": "command.state",
                "actor_kind": "harness",
                "content_role": "state",
                "origin_kind": "harness_generated",
                "command_name": None,
            }
        event = _base_event(
            session_id=session_id,
            event_id=str(line_num),
            event_type=semantics["event_type"],
            subtype=semantics["subtype"],
            role=semantics["role"],
            timestamp=_get_timestamp(record),
            source_file=source_file,
        )
        event["content"] = text
        event["content_len"] = len(text)
        metadata["command_name"] = semantics["command_name"]
        event.update({
            key: semantics[key]
            for key in ("event_kind", "actor_kind", "content_role", "origin_kind")
        })
    if event is None:
        return None
    if not event.get("event_kind"):
        event.update({
            "event_kind": (
                _product_state_kind(event.get("subtype"))
                if event["event_type"] == "product_state"
                else "lifecycle.vendor"
            ),
            "actor_kind": "harness",
            "content_role": "state",
            "origin_kind": "harness_generated",
        })
    event["metadata"] = _event_metadata(record, extra=metadata)
    return event


def normalize_assistant(
    record: dict,
    line_num: int,
    session_id: str,
    source_file: str,
    opts: dict,
) -> tuple[list[dict], dict[str, str]]:
    """Extract assistant events; return (events, tool_map)."""
    events = []
    tool_map = {}
    message = record.get("message")
    message = message if isinstance(message, dict) else {}
    content = message.get("content") or []
    role = message.get("role", "assistant")
    ts = _get_timestamp(record)
    redact_enabled = opts.get("redact", False)
    model_configuration = _assistant_configuration(record)
    # Build tool_map from tool_use blocks
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            tid = block.get("id")
            tname = block.get("name")
            if tid and tname:
                tool_map[tid] = tname

    stop_reason = message.get("stop_reason", "")
    emitted_index = 0

    for i, block in enumerate(content):
        if not isinstance(block, dict):
            continue
        btype = block.get("type")

        if btype == "text":
            text = block.get("text") or ""
            text = _process_text(text, opts, phase="pre", record_type="assistant.text")
            if text is None:
                continue
            # Response: no tool_use follows in this record. Dialog: tool_use follows.
            follows_tool_use = any(
                isinstance(content[j], dict) and content[j].get("type") == "tool_use"
                for j in range(i + 1, len(content))
            )
            if follows_tool_use:
                subtype = "dialog"
                limit = TRUNCATE_DIALOG
            else:
                subtype = "truncated" if "max_tokens" in str(stop_reason) else "response"
                limit = TRUNCATE_RESPONSE
            truncated, content_len = truncate_content(text, limit)
            processed = _process_text(
                truncated, opts, phase="post", record_type="assistant.text"
            )
            if processed is None:
                continue
            truncated = processed
            events.append({
                "session_id": session_id,
                "event_id": _block_event_id(line_num, emitted_index),
                "event_type": "assistant_message",
                "subtype": subtype,
                "role": role,
                "content": truncated,
                "content_len": content_len,
                "content_ref": None,
                "tool_name": None,
                "tool_input": None,
                "tool_output": None,
                "timestamp": ts,
                "file_path": None,
                "source_file": source_file,
                "metadata": _event_metadata(record, extra=model_configuration),
                "source_raw": None,
            })
            _attach_timestamp_state(events[-1], record, ts)
            _attach_configuration_state(events[-1], record)
            emitted_index += 1

        elif btype == "tool_use":
            tname = block.get("name")
            raw_input, input_state = field_state.get_state(block, "input")
            if input_state == field_state.PRESENT and not isinstance(
                raw_input, dict
            ):
                input_state = field_state.MALFORMED
                tinput = {}
            else:
                tinput = raw_input if isinstance(raw_input, dict) else {}
            tool_input = extract_tool_input(tname or "", tinput)
            tool_input = sanitize_value(tool_input, redact_enabled)
            tool_use_id = block.get("id")
            events.append({
                "session_id": session_id,
                "event_id": _block_event_id(line_num, emitted_index),
                "event_type": "tool_call",
                "subtype": None,
                "role": role,
                "content": None,
                "content_len": None,
                "content_ref": None,
                "tool_name": tname,
                "tool_input": json.dumps(tool_input) if tool_input else None,
                "tool_output": None,
                "timestamp": ts,
                "file_path": (
                    tool_input.get("path") or tool_input.get("file_path")
                    if isinstance(tool_input, dict) else None
                ),
                "source_file": source_file,
                "metadata": _event_metadata(
                    record, tool_use_id, extra=model_configuration
                ),
                "source_raw": None,
            })
            _attach_timestamp_state(events[-1], record, ts)
            _attach_configuration_state(events[-1], record)
            field_state.attach(
                events[-1], field="tool_input", state=input_state,
                source_field="message.content[].input", value=raw_input,
            )
            emitted_index += 1

    return events, tool_map


def normalize_user(
    record: dict,
    line_num: int,
    session_id: str,
    source_file: str,
    tool_map: dict[str, str],
    opts: dict,
) -> list[dict]:
    """Extract user events."""
    events = []
    message = record.get("message")
    message = message if isinstance(message, dict) else {}
    content = message.get("content")
    role = message.get("role", "user")
    ts = _get_timestamp(record)
    emitted_index = 0

    # The post-compaction summary is harness-injected replacement context, not
    # a typed human prompt.  Preserve it as communication and link it to the
    # preceding compact boundary through parentUuid.
    if record.get("isCompactSummary"):
        if not isinstance(content, str):
            _record_refused(
                opts, "unsupported_records",
                source_file=source_file, line_num=line_num,
                record_type="compact_summary",
                detail="compact summary content is not text",
            )
            if opts.get("strict_mapping"):
                raise SourceCompatibilityError(
                    "Claude compact summary content is not text"
                )
            return []
        text = _process_text(
            content, opts, phase="pre", record_type="context.compact.summary"
        )
        if text is None:
            return []
        text, content_len, was_truncated = bound_context_content(text, opts)
        text = _process_text(
            text, opts, phase="post", record_type="context.compact.summary"
        )
        if text is None:
            return []
        text, _post_length, post_truncated = bound_context_content(text, opts)
        was_truncated = was_truncated or post_truncated
        event = _base_event(
            session_id=session_id,
            event_id=str(line_num),
            event_type="system_event",
            subtype="context_compaction_summary",
            role="harness",
            timestamp=ts,
            source_file=source_file,
        )
        event.update({
            "content": text,
            "content_len": content_len,
            "event_kind": "context.inject",
            "actor_kind": "harness",
            "content_role": "context",
            "origin_kind": "harness_injected",
            "metadata": _event_metadata(record, extra={
                "context_kind": "compaction_summary",
                "compaction_boundary_uuid": record.get("parentUuid"),
                "content_truncated": was_truncated,
            }),
        })
        _attach_timestamp_state(event, record, ts)
        return [event]

    if isinstance(content, str):
        text = _process_text(content, opts, phase="pre", record_type="user.prompt")
        if text is None:
            return []
        text = _process_text(text, opts, phase="post", record_type="user.prompt")
        if text is None:
            return []
        local_command = _local_command_semantics(text)
        semantics = _user_origin_semantics(record, source_file)
        if local_command is not None:
            event_type = local_command["event_type"]
            subtype = local_command["subtype"]
            event_role = local_command["role"]
            event_kind = local_command["event_kind"]
            actor_kind = local_command["actor_kind"]
            content_role = local_command["content_role"]
            normalized_origin_kind = local_command["origin_kind"]
            if (
                semantics["actor_kind"] == "harness"
                and local_command["actor_kind"] == "human"
            ):
                event_type = semantics["event_type"]
                subtype = semantics["subtype"]
                event_role = semantics["role"]
                event_kind = semantics["event_kind"]
                actor_kind = semantics["actor_kind"]
                content_role = semantics["content_role"]
                normalized_origin_kind = semantics["origin_kind"]
        else:
            subtype = (
                "slash_command"
                if (
                    semantics["actor_kind"] == "human"
                    and text.strip().startswith("/")
                )
                else semantics["subtype"]
            )
            event_type = semantics["event_type"]
            event_role = semantics["role"]
            event_kind = semantics["event_kind"]
            actor_kind = semantics["actor_kind"]
            content_role = semantics["content_role"]
            normalized_origin_kind = semantics["origin_kind"]
        event = _base_event(
            session_id=session_id, event_id=str(line_num), event_type=event_type,
            subtype=subtype, role=event_role,
            timestamp=ts, source_file=source_file,
        )
        event.update({
            "content": text, "content_len": len(text),
            "event_kind": event_kind,
            "actor_kind": actor_kind,
            "content_role": content_role,
            "origin_kind": normalized_origin_kind,
            "metadata": _event_metadata(record, extra={
                "prompt_source": semantics["prompt_source"],
                "origin_kind": semantics["source_origin_kind"],
                "permission_mode": record.get("permissionMode"),
                "user_type": record.get("userType"),
                "is_sidechain": record.get("isSidechain"),
                "agent_id": record.get("agentId"),
                "actor_evidence": semantics["actor_evidence"],
                "command_name": (
                    local_command["command_name"] if local_command else None
                ),
            }),
        })
        _attach_timestamp_state(event, record, ts)
        if local_command is None or actor_kind == "human":
            _attach_prompt_origin_state(event, record)
        return [event]
    if content is None:
        content = []
    elif not isinstance(content, list):
        _record_refused(
            opts, "unsupported_records",
            source_file=source_file, line_num=line_num,
            record_type=record.get("type"),
            detail=f"user content is {type(content).__name__}, not a list",
        )
        if opts.get("strict_mapping"):
            raise SourceCompatibilityError(
                f"unsupported Claude user content type: {type(content).__name__}"
            )
        return []

    for block in content:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")

        if btype == "text":
            text = block.get("text") or ""
            text = _process_text(text, opts, phase="pre", record_type="user.text")
            if text is None:
                continue
            text = _process_text(text, opts, phase="post", record_type="user.text")
            if text is None:
                continue
            local_command = _local_command_semantics(text)
            semantics = _user_origin_semantics(record, source_file)
            subtype = (
                local_command["subtype"]
                if local_command is not None
                else "slash_command" if (
                    semantics["actor_kind"] == "human"
                    and text.strip().startswith("/")
                )
                else semantics["subtype"]
            )
            if (
                local_command is not None
                and local_command["actor_kind"] == "human"
                and semantics["actor_kind"] == "harness"
            ):
                subtype = semantics["subtype"]
            events.append({
                "session_id": session_id,
                "event_id": _block_event_id(line_num, emitted_index),
                "event_type": (
                    local_command["event_type"]
                    if (
                        local_command is not None
                        and not (
                            local_command["actor_kind"] == "human"
                            and semantics["actor_kind"] == "harness"
                        )
                    )
                    else semantics["event_type"]
                ),
                "subtype": subtype,
                "role": (
                    local_command["role"]
                    if (
                        local_command is not None
                        and not (
                            local_command["actor_kind"] == "human"
                            and semantics["actor_kind"] == "harness"
                        )
                    )
                    else semantics["role"]
                ),
                "content": text,
                "content_len": len(text),
                "content_ref": None,
                "tool_name": None,
                "tool_input": None,
                "tool_output": None,
                "timestamp": ts,
                "file_path": None,
                "source_file": source_file,
                "metadata": _event_metadata(record, extra={
                    "prompt_source": semantics["prompt_source"],
                    "origin_kind": semantics["source_origin_kind"],
                    "user_type": record.get("userType"),
                    "is_sidechain": record.get("isSidechain"),
                    "agent_id": record.get("agentId"),
                    "actor_evidence": semantics["actor_evidence"],
                    "command_name": (
                        local_command["command_name"] if local_command else None
                    ),
                }),
                "source_raw": None,
            })
            if (
                local_command is not None
                and not (
                    local_command["actor_kind"] == "human"
                    and semantics["actor_kind"] == "harness"
                )
            ):
                events[-1].update({
                    key: local_command[key]
                    for key in (
                        "event_kind", "actor_kind", "content_role", "origin_kind"
                    )
                })
            else:
                events[-1].update({
                    key: semantics[key]
                    for key in (
                        "event_kind", "actor_kind", "content_role", "origin_kind"
                    )
                })
            _attach_timestamp_state(events[-1], record, ts)
            if local_command is None or local_command["actor_kind"] == "human":
                _attach_prompt_origin_state(events[-1], record)
            emitted_index += 1

        elif btype == "image":
            # A human pasting a screenshot with no accompanying text. Without this the
            # prompt exists in the Session and not in the store -- 48 of them in one
            # observed Project, counted only as a diagnostic.
            #
            # The payload is deliberately not retained. These are base64
            # images averaging ~185 KB, and the `attachment` record's
            # treatment is the established pattern in this adapter: record
            # that content was present, its type and size, never the bytes.
            source = block.get("source")
            source = source if isinstance(source, dict) else {}
            data = source.get("data") or ""
            semantics = _user_origin_semantics(record, source_file)
            events.append({
                "session_id": session_id,
                "event_id": _block_event_id(line_num, emitted_index),
                "event_type": semantics["event_type"],
                "subtype": "attachment",
                "role": semantics["role"],
                "content": None,
                "content_len": 0,
                "timestamp": ts,
                "source_file": source_file,
                "actor_kind": semantics["actor_kind"],
                "content_role": semantics["content_role"],
                # The normalized origin, as the text branch stores; the raw
                # vendor string travels in metadata rather than the column.
                "origin_kind": semantics["origin_kind"],
                "metadata": _event_metadata(record, extra={
                    "attachment_type": btype,
                    "origin_kind": semantics["source_origin_kind"],
                    "media_type": source.get("media_type"),
                    "attachment_source": source.get("type"),
                    "encoded_length": len(data) if data else 0,
                    "prompt_source": semantics["prompt_source"],
                    "user_type": record.get("userType"),
                    "is_sidechain": record.get("isSidechain"),
                    "actor_evidence": semantics["actor_evidence"],
                }),
            })
            emitted_index += 1
        elif btype == "tool_result":
            tool_use_id = block.get("tool_use_id")
            tool_name = tool_map.get(tool_use_id) if tool_use_id else None
            is_error = block.get("is_error", False)
            content_val = block.get("content")
            if isinstance(content_val, list):
                # Some tool results have content as list of blocks
                parts = []
                for c in content_val:
                    if isinstance(c, dict) and c.get("type") == "text":
                        parts.append(c.get("text", ""))
                content_val = "\n".join(parts)
            text = str(content_val) if content_val else ""
            result_failure = None
            if (
                not is_error
                and isinstance(tool_name, str)
                and tool_name.startswith("mcp__")
            ):
                result_failure = application_failure_evidence(text)
                if result_failure:
                    is_error = True
            text = _process_text(text, opts, phase="pre", record_type="tool_result")
            if text is None:
                continue
            truncated, content_len = truncate_content(text, TRUNCATE_TOOL_RESULT)
            processed = _process_text(
                truncated, opts, phase="post", record_type="tool_result"
            )
            if processed is None:
                continue
            truncated = processed
            if is_error:
                subtype = (
                    "permission_denied"
                    if _is_permission_denial(text)
                    else "tool_failure"
                )
            else:
                subtype = "tool_result"
            events.append({
                "session_id": session_id,
                "event_id": _block_event_id(line_num, emitted_index),
                "event_type": "user_message",
                "subtype": subtype,
                "role": role,
                "content": truncated,
                "content_len": content_len,
                "content_ref": None,
                "tool_name": tool_name,
                "tool_input": None,
                "tool_output": truncated,
                # Claude states the result as a structured object on 12,863 real
                # records -- `stdout` and `stderr` separately, `structuredPatch`,
                # `interrupted` -- which the text projection flattens into one blob.
                # The structure is carried so a reader can select on stderr or find
                # an interrupted result without re-parsing the text.
                "tool_output_structured": (
                    record.get("toolUseResult")
                    if isinstance(record.get("toolUseResult"), (dict, list))
                    else None
                ),
                # What the source said, not what was inferred from it.
                # `result_failure` is a text-pattern inference used only for MCP
                # results; `is_error` is Claude's own flag on the result block. Reading
                # only the inference leaves `source_status` null on the 470 failure and
                # denial Events whose outcome the vendor states directly.
                "source_status": (
                    "application_error" if result_failure
                    else "is_error" if is_error
                    else None
                ),
                "normalized_status": (
                    "succeeded" if subtype == "tool_result"
                    else "failed" if subtype == "tool_failure"
                    else None
                ),
                "timestamp": ts,
                "file_path": None,
                "source_file": source_file,
                "metadata": _event_metadata(
                    record,
                    tool_use_id,
                    extra=({
                        "source_is_error": False,
                        "application_status": "failed",
                        "result_status_evidence": result_failure,
                    } if result_failure else None),
                ),
                "source_raw": None,
            })
            _attach_timestamp_state(events[-1], record, ts)
            emitted_index += 1

    persisted = record.get("toolUseResult")
    if isinstance(persisted, dict) and persisted.get("persistedOutputPath"):
        path = Path(str(persisted["persistedOutputPath"])).expanduser().resolve()
        allowed_root = Path(source_file).with_suffix("").resolve()
        result_event = next(
            (event for event in events if event.get("subtype") in {
                "tool_result", "tool_failure", "permission_denied"
            }),
            None,
        )
        try:
            if not path.is_relative_to(allowed_root):
                raise SourceCompatibilityError(
                    f"persisted tool output outside session tree: {path}"
                )
            before = path.stat()
            # The size is checked before the read, not after: reading first and
            # then rejecting would already have materialized the body this bound
            # exists to keep out of memory. Nothing in the vendor contract bounds
            # this file -- it is written by whatever tool produced the output, so
            # its size is a property of that tool rather than of a Session.
            limit = int(
                opts.get("max_external_content_bytes")
                or MAX_EXTERNAL_CONTENT_BYTES
            )
            if before.st_size > limit:
                _record_refused(
                    opts, "external_content_oversize",
                    source_file=source_file, line_num=line_num,
                    record_type="external.tool_result",
                    detail=(
                        f"persisted tool output is {before.st_size} bytes, "
                        f"above the {limit}-byte bound: {path.name}"
                    ),
                )
                raise SourceCompatibilityError(
                    f"persisted tool output exceeds {limit} bytes: {path}"
                )
            raw = path.read_bytes()
            after = path.stat()
            if (before.st_mtime_ns, before.st_size) != (after.st_mtime_ns, after.st_size):
                raise SourceCompatibilityError(
                    f"persisted tool output changed during read: {path}"
                )
            processor = opts.get("content_processor")
            if processor is not None:
                from codess.content_processing import ContentContext
                decoded = processor.decode(raw, ContentContext(
                    vendor="Claude", record_type="external.tool_result",
                    project_path=opts.get("project_path"),
                    repo_path=opts.get("repo_path"), phase="pre",
                ))
                if not decoded.accepted:
                    _diagnostic(opts, "filtered_records")
                    return events
                full_text = decoded.content
            else:
                full_text = raw.decode("utf-8", errors="replace")
            full_text = apply_sanitization(full_text, opts.get("redact", False))
            extracted, full_len = truncate_content(full_text, TRUNCATE_TOOL_RESULT)
            extracted = _process_text(
                extracted, opts, phase="post", record_type="external.tool_result"
            )
            if extracted is None:
                return events
            expected_size = persisted.get("persistedOutputSize")
            if expected_size is not None and int(expected_size) != len(raw):
                _diagnostic(opts, "external_content_size_mismatch")
            external_id = _block_event_id(line_num, emitted_index)
            external = _base_event(
                session_id=session_id, event_id=external_id,
                event_type="external_content", subtype="persisted_tool_result",
                role="tool", timestamp=ts, source_file=source_file,
            )
            external.update({
                "content": extracted, "content_len": full_len,
                "content_ref": str(path), "file_path": str(path),
                "caused_by_event_id": result_event.get("event_id") if result_event else None,
                "tool_name": result_event.get("tool_name") if result_event else None,
                "event_kind": "content.external", "actor_kind": "tool",
                "content_role": "tool_result_detail", "origin_kind": "tool_generated",
                "metadata": _event_metadata(record, extra={
                    "source_locator": str(path),
                    "content_digest": codess_bytes_hash(256, 256, raw),
                    "byte_size": len(raw), "character_length": full_len,
                    "extraction": "complete" if len(extracted) == full_len else "bounded",
                    "media_type": "text/plain",
                }),
            })
            events.append(external)
            external_sources = opts.get("external_sources")
            if external_sources is not None:
                external_sources.append({
                    "path": str(path), "parent_source": source_file,
                    "relation_kind": "persisted_tool_result",
                })
            _diagnostic(opts, "external_content_records")
        except (OSError, UnicodeError, ValueError, SourceCompatibilityError) as exc:
            _diagnostic(opts, "external_content_errors")
            from codess.ingest_review import record_ingest_review
            record_ingest_review(
                opts, exc, source=path, vendor="Claude",
                stage="external_content_extraction",
                record_type="external.tool_result",
            )
            if opts.get("strict_mapping"):
                if isinstance(exc, SourceCompatibilityError):
                    raise
                raise SourceCompatibilityError(
                    f"cannot extract persisted tool output {path}: {exc}"
                ) from exc

    return events


def process_file(
    path: Path,
    session_id: str,
    opts: dict,
) -> Iterator[dict]:
    """Stream events from CC JSONL. Two-pass: build tool_map, then emit events."""
    source_file = str(path.resolve())
    tool_map = _build_tool_map(path)
    diagnostics = opts.get("diagnostics")

    for line_num, record, raw_line in iter_cc_records(path, diagnostics):
        if record.get("type") == "system" and record.get("subtype") == "compact_boundary":
            yield _annotate_source(
                _normalize_compaction(record, line_num, session_id, source_file),
                record,
                line_num,
            )
            continue
        product_state = normalize_product_state(
            record, line_num, session_id, source_file, opts
        )
        if product_state is not None:
            if opts.get("include_product_state", True):
                yield _annotate_source(product_state, record, line_num)
                _diagnostic(opts, "product_state_records")
            else:
                _diagnostic(opts, "known_ignored_records")
            continue
        if should_skip(record):
            _diagnostic(opts, "known_ignored_records")
            continue
        rtype = record.get("type")
        debug = opts.get("debug", False)
        source_raw = (
            raw_line.encode("utf-8", errors="replace")[:512]
            if debug and not opts.get("redact", False)
            else None
        )

        if rtype == "assistant":
            evs, _ = normalize_assistant(record, line_num, session_id, source_file, opts)
            if not evs and diagnostics is not None:
                blocks = (record.get("message") or {}).get("content") or []
                block_types = {
                    block.get("type") for block in blocks
                    if isinstance(block, dict)
                }
                empty_thinking = bool(blocks) and block_types == {"thinking"} and all(
                    not block.get("thinking")
                    for block in blocks if isinstance(block, dict)
                )
                if empty_thinking or block_types == {"fallback"}:
                    diagnostics["known_ignored_records"] = (
                        diagnostics.get("known_ignored_records", 0) + 1
                    )
                    reason = (
                        "empty_reasoning_state_records"
                        if empty_thinking else "fallback_state_records"
                    )
                    diagnostics[reason] = diagnostics.get(reason, 0) + 1
                else:
                    diagnostics["ignored_records"] = (
                        diagnostics.get("ignored_records", 0) + 1
                    )
            for ev in evs:
                if source_raw is not None:
                    ev["source_raw"] = source_raw
                yield _annotate_source(ev, record, line_num)
        elif rtype == "user":
            evs = normalize_user(
                record, line_num, session_id, source_file, tool_map, opts
            )
            if not evs and diagnostics is not None:
                # Image-only records used to land here and be counted
                # unsupported; they now decode as bounded attachment prompts,
                # so anything still producing no Event is an ordinary ignore.
                diagnostics["ignored_records"] = (
                    diagnostics.get("ignored_records", 0) + 1
                )
            for ev in evs:
                if source_raw is not None:
                    ev["source_raw"] = source_raw
                yield _annotate_source(ev, record, line_num)
        elif diagnostics is not None:
            diagnostics["unsupported_records"] = (
                diagnostics.get("unsupported_records", 0) + 1
            )
            if opts.get("strict_mapping"):
                raise SourceCompatibilityError(
                    f"unsupported Claude record type: {rtype!r} at {path}:{line_num}"
                )
