"""Cursor record decoder: bubbleId messages to common Events.

**Owns decode.** Normalization, field mapping, truncation, and content
processing for Cursor records. It holds no storage dependency: rows arrive
through `cursor_source` accessors, so this module names no database, table,
or key range (see the ownership table in `cursor_source`).
"""

import json
import logging
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from codess import field_state
from codess.config import TRUNCATE_PROMPT, TRUNCATE_RESPONSE, TRUNCATE_TOOL_RESULT
from codess.content_processing import apply_processing
from codess.context_content import bound_context_content, truncate_content
from codess.cursor_source import (
    open_bubble_rows,
    open_message_request_context_rows,
)
from codess.cursor_source import (
    parse_timestamp as _parse_timestamp,
)
from codess.mapping import annotate_mapping, structured_json
from codess.tool_result_status import application_failure_evidence

log = logging.getLogger(__name__)

_MAPPED_BUBBLE_FIELDS = frozenset({
    "type", "text", "createdAt", "timingInfo", "serverBubbleId",
    "toolFormerData", "toolResults", "modelInfo", "conversationSummary",
    "contextWindowStatusAtCreation",
    # Reasoning. Codex maps its equivalent to `message.reasoning_summary` and
    # produces thousands of Events; without these a reader comparing reasoning
    # across vendors sees Cursor as having none, which is false.
    "thinking", "thinkingStyle", "thinkingDurationMs",
    # The only measured durations Cursor records. `timingInfo` above is already
    # read for a timestamp fallback, so the shape is proven.
    "turnDurationMs",
    # A recorded failure is what a tool-result status should reflect.
    "errorDetails",
    # Artifact and context references the store has a place for.
    "lastTerminalCwd", "symbolLinks", "fileLinks", "todos", "codeBlocks",
    "context",
    # A request and its response are a Model Turn edge; mapping them to one
    # column would erase the direction. `requestId` appears only on user
    # bubbles and `usageUuid` only on assistant bubbles, never both.
    "requestId", "usageUuid",
})

# Nine leaves inside `context` carry values; the outer container is mostly
# empty, which is why reading its top level found nothing. Each names an
# Artifact or a context reference.
_CONTEXT_LEAVES = (
    "terminalFiles", "fileSelections", "externalLinks", "composers",
    "selections", "selectedImages", "terminalSelections",
)
_PROGRESS_ROWS = 1000
_PROGRESS_SECONDS = 5.0


# Cursor names the file a tool operates on differently per tool: `read_file`
# and `edit_file` use `target_file`, `search_replace` uses `file_path`,
# `list_dir` uses `relative_workspace_path`. Ordered by how specific the key
# is, so a call carrying both a target and a workspace root records the
# target.
_TOOL_PATH_KEYS = (
    "target_file",
    "file_path",
    "relative_workspace_path",
    "path",
)


def _tool_file_path(tool_former: dict) -> str | None:
    """The file a Cursor tool call operates on, or None.

    Cursor names the file under four spellings; 2,873 of 4,530 real tool calls carry
    one, so a single field read finds none of them.

    Only a single path is returned, because the column holds one; a call
    naming several (`paths`) records none rather than an arbitrary first,
    and `tool_input` retains the whole argument object either way.
    """
    raw = tool_former.get("rawArgs") or tool_former.get("params")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return None
    if not isinstance(raw, dict):
        return None
    for key in _TOOL_PATH_KEYS:
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _bubble_timestamp(data: dict) -> float | None:
    """Use event creation time, with an epoch-only legacy timing fallback."""
    timestamp = _parse_timestamp(data.get("createdAt"))
    if timestamp is not None:
        return timestamp
    timing = data.get("timingInfo") or {}
    if isinstance(timing, dict):
        return _parse_timestamp(timing.get("clientStartTime"))
    return None





def _context_window_metadata(data: dict) -> dict:
    """Normalize Cursor's per-bubble context-window observation."""
    source = data.get("contextWindowStatusAtCreation")
    if not isinstance(source, dict):
        return {}
    names = {
        "percentageRemaining": "context_percentage_remaining",
        "percentageRemainingFloat": "context_percentage_remaining_float",
        "tokensUsed": "context_tokens_used",
        "tokenLimit": "context_token_limit",
    }
    values = {
        target: source[source_name]
        for source_name, target in names.items()
        if source.get(source_name) is not None
        and not isinstance(source[source_name], (dict, list))
    }
    if values:
        values["context_observation_provenance"] = (
            "bubble.contextWindowStatusAtCreation"
        )
    return values


def _reasoning_metadata(data: dict) -> dict:
    """Cursor's per-bubble reasoning, under the names the other vendors use.

    Codex records the same evidence as `message.reasoning_summary`. Naming it
    the same way here is what lets one query compare reasoning across vendors;
    keeping Cursor's spelling would make the comparison a per-vendor special
    case.
    """
    values: dict = {}
    # `thinking` is an object, not a string: `text` carries the reasoning and
    # `redactedThinking` marks a chunk the vendor withheld. Reading it as a
    # string drops every instance silently, which is what the first version of
    # this function did -- measured at 3,546 bubbles on the development machine.
    thinking = data.get("thinking")
    if isinstance(thinking, dict):
        text = thinking.get("text")
        if isinstance(text, str) and text.strip():
            values["reasoning_summary"] = text
        if thinking.get("redactedThinking"):
            # The vendor states that reasoning existed and was withheld, which
            # is not the same as none being produced.
            values["reasoning_redacted"] = True
        if thinking.get("isLastThinkingChunk") is not None:
            values["reasoning_final_chunk"] = bool(
                thinking.get("isLastThinkingChunk")
            )
    elif isinstance(thinking, str) and thinking.strip():
        values["reasoning_summary"] = thinking
    style = data.get("thinkingStyle")
    if style is not None and not isinstance(style, (dict, list)):
        values["reasoning_style"] = style
    duration = data.get("thinkingDurationMs")
    if isinstance(duration, (int, float)) and not isinstance(duration, bool):
        values["reasoning_duration_ms"] = duration
    return values


def _duration_metadata(data: dict) -> dict:
    """The only durations Cursor measures, in milliseconds as the name states."""
    values: dict = {}
    turn = data.get("turnDurationMs")
    if isinstance(turn, (int, float)) and not isinstance(turn, bool):
        values["turn_duration_ms"] = turn
    timing = data.get("timingInfo")
    if isinstance(timing, dict):
        for source_name, target in (
            ("clientStartTime", "client_start_time"),
            ("clientEndTime", "client_end_time"),
            ("clientSettleTime", "client_settle_time"),
            ("clientRpcSendTime", "client_rpc_send_time"),
        ):
            value = timing.get(source_name)
            if value is not None and not isinstance(value, (dict, list)):
                values[target] = value
    return values


def _error_metadata(data: dict) -> dict:
    """A vendor-recorded failure, retained verbatim beside any mapped status.

    The shape is established from few instances, so the whole object is kept
    rather than projected into columns a later sample would contradict.
    """
    details = data.get("errorDetails")
    if not isinstance(details, dict) or not details:
        return {}
    return {"source_error_details": details}


def _reference_metadata(data: dict) -> dict:
    """Artifact and context references Cursor states directly.

    `context` is walked rather than read at its top level: the container is
    mostly empty and its populated leaves are where the references are.
    """
    values: dict = {}
    cwd = data.get("lastTerminalCwd")
    if isinstance(cwd, str) and cwd.strip():
        values["terminal_cwd"] = cwd.strip()
    for source_name, target in (
        ("symbolLinks", "symbol_links"),
        ("fileLinks", "file_links"),
        ("todos", "todos"),
        ("codeBlocks", "code_blocks"),
    ):
        value = data.get(source_name)
        if isinstance(value, list) and value:
            values[target] = value
    context = data.get("context")
    if isinstance(context, dict):
        leaves = {
            name: context[name] for name in _CONTEXT_LEAVES
            if isinstance(context.get(name), list) and context[name]
        }
        if leaves:
            values["context_references"] = leaves
    return values


def _turn_edge_metadata(data: dict) -> dict:
    """The request/response identifiers, kept apart because they differ.

    `requestId` appears only on user bubbles and `usageUuid` only on assistant
    bubbles, and no bubble carries both. They correlate across adjacent
    bubbles, so one identifies a request and the other its response -- mapping
    them to a single column would erase that direction.
    """
    values: dict = {}
    request = data.get("requestId")
    if isinstance(request, str) and request.strip():
        values["source_request_id"] = request.strip()
    usage = data.get("usageUuid")
    if isinstance(usage, str) and usage.strip():
        values["source_usage_id"] = usage.strip()
    return values


def _record_refused(
    opts: dict,
    reason_code: str,
    *,
    source_file: str | None = None,
    bubble_id: str | None = None,
    record_type: str | None = None,
) -> None:
    """Record that one bubble was read and not admitted.

    Mirrors the Claude and Codex recorders: a counter says how many were
    refused, a persisted row says which. `store` aggregates by reason and
    record type before writing, so a kind refused thousands of times costs one
    row carrying the count.
    """
    diagnostics = opts.get("diagnostics")
    if diagnostics is not None:
        diagnostics[reason_code] = diagnostics.get(reason_code, 0) + 1
    pending = opts.get("record_diagnostics")
    if pending is None:
        return
    pending.append({
        "granularity": "record",
        "reason_code": reason_code,
        "source_locator": f"bubble:{bubble_id}" if bubble_id else None,
        "source_file": source_file,
        "source_record_type": record_type,
    })


def _bubble_evidence(data: dict) -> dict:
    """Every mapped-but-uncolumned bubble value, as one metadata dict.

    Grouped so a bubble is enriched the same way wherever an Event is built:
    the alternative is four call sites that drift apart, which is how
    `contextWindowStatusAtCreation` came to be merged at three of them and not
    the fourth.
    """
    values: dict = {}
    for extract in (
        _context_window_metadata, _reasoning_metadata, _duration_metadata,
        _error_metadata, _reference_metadata, _turn_edge_metadata,
    ):
        values.update(extract(data))
    return values


def _merge_metadata(event: dict, values: dict) -> None:
    if not values:
        return
    current = json.loads(event.get("metadata") or "{}")
    current.update(values)
    event["metadata"] = json.dumps(current, separators=(",", ":"))


def _load_message_request_contexts(
    db_path: Path,
    composer_id: str,
) -> dict[str, tuple[str, dict]]:
    """Read one composer's request contexts and release the SQLite handle."""
    contexts: dict[str, tuple[str, dict]] = {}
    try:
        for key, value in open_message_request_context_rows(db_path, {composer_id}):
            if value is None:
                continue
            try:
                decoded = json.loads(value)
            except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
                continue
            if not isinstance(decoded, dict):
                continue
            parts = str(key).split(":", 2)
            if len(parts) == 3:
                contexts[parts[2]] = (str(key), decoded)
    except Exception as exc:  # vendor storage errors stay in cursor_source
        log.warning("Cannot read Cursor request contexts from %s: %s", db_path, exc)
    return contexts


def _base_event(
    *, session_id: str, event_id: str, event_type: str, subtype: str, role: str,
    content: str | None, content_len: int | None, timestamp: float | None,
    source_file: str, metadata: str | None = None, **extra: Any,
) -> dict[str, Any]:
    """One Cursor Event envelope, holding the fields every record shares.

    The eighteen keys below were written out at each construction site, so a
    reader comparing two sites had to diff two blocks to see which few fields
    actually differed. `adapters/cc` and `adapters/codex` each solved this with
    a builder of the same name; Cursor had only a closure inside
    `_bubble_to_events`, which the request-context path could not reach.

    `extra` carries what only some records have -- classification, tool fields,
    a file path -- so a caller with none of them does not spell out a `None`
    per key. An omitted classification is left out of the dict rather than set
    to `None`, because `store._event_classification` fills only absent
    dimensions and a `None` would be an explicit classification of nothing.
    """
    event: dict[str, Any] = {
        "session_id": session_id,
        "event_id": event_id,
        "event_type": event_type,
        "subtype": subtype,
        "role": role,
        "content": content,
        "content_len": content_len,
        "content_ref": None,
        "tool_name": None,
        "tool_input": None,
        "tool_output": None,
        "timestamp": timestamp,
        "file_path": None,
        "source_file": source_file,
        "metadata": metadata,
        "source_raw": None,
    }
    event.update(extra)
    return event


def _count_surviving_repeats(
    ordered: list[tuple[str, dict]], diagnostics: dict | None,
) -> None:
    """Count tool calls still appearing on more than one bubble after dedup.

    The `(type, serverBubbleId)` key collapses server-written copies, and a
    bubble with no server identity is exempt because a missing identity cannot
    prove duplication. That exemption is correct and it leaks: a composer that
    is re-synced gains server copies of bubbles it already held locally, so one
    `toolCallId` survives on two bubbles -- the local original and the canonical
    server copy.

    Measured on the development machine, the leak is bounded by circumstance
    rather than random: a composer whose tool bubbles are all locally written
    never shows it (111 of 111), and it appears in 10 of the 14 composers that
    both hold server copies and span three or more days.

    Counted rather than removed, because both bubbles are real vendor records
    and the store is a projection of what the vendor wrote. The count is what
    lets a reader tell a Session that was re-synced from one that was not.
    """
    if diagnostics is None:
        return
    seen: dict[str, int] = {}
    for _bubble_id, data in ordered:
        call_id = (data.get("toolFormerData") or {}).get("toolCallId")
        if call_id:
            seen[str(call_id)] = seen.get(str(call_id), 0) + 1
    repeats = sum(count - 1 for count in seen.values() if count > 1)
    if repeats:
        diagnostics["repeated_tool_calls"] = (
            diagnostics.get("repeated_tool_calls", 0) + repeats
        )


def _request_context_event(
    composer_id: str,
    bubble_id: str,
    source_key: str,
    value: dict,
    source_file: str,
    timestamp: float | None,
    opts: dict,
) -> dict | None:
    """Map a separately stored Cursor harness request-context body."""
    text = json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    text = apply_processing(
        text, opts, vendor="Cursor",
        record_type="messageRequestContext",
        event_kind="context.inject", phase="pre",
    )
    if text is None:
        return None
    text, content_len, truncated = bound_context_content(text, opts)
    text = apply_processing(
        text, opts, vendor="Cursor",
        record_type="messageRequestContext",
        event_kind="context.inject", phase="post",
    )
    if text is None:
        return None
    text, _post_length, post_truncated = bound_context_content(text, opts)
    truncated = truncated or post_truncated
    event = _base_event(
        session_id=composer_id,
        event_id=f"{composer_id}:{bubble_id}:request-context",
        event_type="system_event",
        subtype="context_injection",
        role="harness",
        content=text,
        content_len=content_len,
        timestamp=timestamp,
        source_file=source_file,
        metadata=json.dumps({
            "context_kind": "message_request_context",
            "request_bubble_id": bubble_id,
            "context_fields": sorted(value),
            "content_truncated": truncated,
        }, separators=(",", ":")),
        event_kind="context.inject",
        actor_kind="harness",
        content_role="context",
        origin_kind="harness_injected",
    )
    return annotate_mapping(
        event,
        source_record_type="cursorDiskKV.messageRequestContext",
        source_record_subtype=None,
        source_record_locator=source_key,
        mapping_rule="cursor.request-context",
        source_path="$",
    )


def _iter_bubbles(
    db_path: Path,
    stats: dict[str, int] | None = None,
    composer_ids: set[str] | None = None,
) -> Iterator[tuple[str, str, dict]]:
    """Yield (composer_id, bubble_id, message_dict) from cursorDiskKV bubbleId keys."""
    if composer_ids == set():
        return
    try:
        for key, value in open_bubble_rows(db_path, composer_ids):
            if stats is not None:
                stats["rows"] = stats.get("rows", 0) + 1
            if value is None:
                if stats is not None:
                    stats["null_values"] = stats.get("null_values", 0) + 1
                continue
            parts = key.split(":", 2)
            if len(parts) < 3:
                if stats is not None:
                    stats["invalid_keys"] = stats.get("invalid_keys", 0) + 1
                continue
            composer_id, bubble_id = parts[1], parts[2]
            try:
                data = json.loads(value)
            except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
                try:
                    import base64
                    decoded = base64.b64decode(value)
                    data = json.loads(decoded)
                except Exception:
                    if stats is not None:
                        stats["decode_errors"] = stats.get("decode_errors", 0) + 1
                    continue
            if isinstance(data, dict):
                if stats is not None:
                    stats["yielded"] = stats.get("yielded", 0) + 1
                # Large attachment/context envelopes are not mapped. Drop them
                # before composer-level ordering/deduplication retains records.
                projected = {
                    key: data[key] for key in _MAPPED_BUBBLE_FIELDS if key in data
                }
                yield composer_id, bubble_id, projected
            elif stats is not None:
                stats["non_objects"] = stats.get("non_objects", 0) + 1
    except Exception as exc:  # vendor storage errors stay in cursor_source
        log.warning("Cannot read Cursor bubbles from %s: %s", db_path, exc)


def process_db(
    db_path: Path,
    project_path: str,
    opts: dict,
    *,
    composer_ids: set[str] | None = None,
    source_file: str | None = None,
    session_headers: dict[str, dict] | None = None,
) -> Iterator[tuple[str, dict]]:
    """Stream (session_id, event) from Cursor state.vscdb. Groups by composerId."""
    source_file = source_file or str(db_path.resolve())
    diagnostics = opts.get("diagnostics")
    stats: dict[str, int] = {}
    progress = opts.get("progress")

    current_composer: str | None = None
    bubbles: list[tuple[str, dict]] = []
    composer_start_tick: float | None = None
    last_progress: float | None = None

    def emit(event: str, **fields) -> None:
        if progress is not None:
            progress(
                event, project=project_path, source=source_file,
                composer_id=current_composer, **fields,
            )

    def finish_read() -> None:
        if current_composer is None:
            return
        emit(
            "cursor.composer.read.done", bubbles=len(bubbles),
            phase_seconds=(
                round(time.monotonic() - composer_start_tick, 3)
                if composer_start_tick is not None else None
            ),
        )

    for composer_id, bubble_id, data in _iter_bubbles(
        db_path,
        stats,
        composer_ids,
    ):
        if current_composer is not None and composer_id != current_composer:
            finish_read()
            yield from _process_composer(
                current_composer,
                bubbles,
                _load_message_request_contexts(db_path, current_composer),
                source_file,
                opts,
                diagnostics,
                (session_headers or {}).get(current_composer),
            )
            bubbles.clear()
        if composer_id != current_composer:
            current_composer = composer_id
            composer_start_tick = last_progress_tick = time.monotonic()
            emit("cursor.composer.read.start")
        bubbles.append((bubble_id, data))
        now_tick = time.monotonic()
        if len(bubbles) % _PROGRESS_ROWS == 0 or (
            last_progress is not None
            and now_tick - last_progress_tick >= _PROGRESS_SECONDS
        ):
            emit(
                "cursor.composer.read.progress", bubbles=len(bubbles),
                phase_seconds=round(now_tick - composer_start_tick, 3),
            )
            last_progress_tick = now_tick
    if current_composer is not None:
        finish_read()
        yield from _process_composer(
            current_composer,
            bubbles,
            _load_message_request_contexts(db_path, current_composer),
            source_file,
            opts,
            diagnostics,
            (session_headers or {}).get(current_composer),
        )

    skipped = sum(
        stats.get(key, 0)
        for key in ("null_values", "invalid_keys", "decode_errors", "non_objects")
    )
    if skipped:
        if diagnostics is not None:
            diagnostics["malformed_records"] = (
                diagnostics.get("malformed_records", 0) + skipped
            )
        log.warning(
            "Cursor skipped %d/%d bubble rows from %s "
            "(null=%d invalid_key=%d decode=%d non_object=%d)",
            skipped,
            stats.get("rows", 0),
            db_path,
            stats.get("null_values", 0),
            stats.get("invalid_keys", 0),
            stats.get("decode_errors", 0),
            stats.get("non_objects", 0),
        )
    elif opts.get("debug"):
        log.debug(
            "Cursor decoded %d bubble rows from %s",
            stats.get("yielded", 0),
            db_path,
        )


def _process_composer(
    composer_id: str,
    bubbles: list[tuple[str, dict]],
    request_contexts: dict[str, tuple[str, dict]],
    source_file: str,
    opts: dict,
    diagnostics: dict[str, int] | None,
    session_header: dict | None = None,
) -> Iterator[tuple[str, dict]]:
    """Order/deduplicate one composer so other composers can be released."""
    def sort_key(item: tuple[str, dict]) -> tuple[bool, float, str]:
        timestamp = _bubble_timestamp(item[1])
        return timestamp is None, timestamp or 0, item[0]

    canonical: dict[tuple[object, str], tuple[str, dict]] = {}
    without_server_identity: list[tuple[str, dict]] = []
    duplicate_count = 0
    for item in bubbles:
        server_bubble_id = item[1].get("serverBubbleId")
        if not server_bubble_id:
            without_server_identity.append(item)
            continue
        key = (item[1].get("type"), str(server_bubble_id))
        previous = canonical.get(key)
        if previous is None or sort_key(item) < sort_key(previous):
            canonical[key] = item
        if previous is not None:
            duplicate_count += 1
    if duplicate_count and diagnostics is not None:
        diagnostics["duplicate_records"] = (
            diagnostics.get("duplicate_records", 0) + duplicate_count
        )
    ordered = without_server_identity + list(canonical.values())
    _count_surviving_repeats(ordered, diagnostics)
    ordered.sort(key=sort_key)
    for bubble_id, data in ordered:
        events = list(
            _bubble_to_events(
                composer_id, bubble_id, data, source_file, opts,
                session_header=session_header,
            )
        )
        if not events and diagnostics is not None:
            empty_assistant_envelope = (
                data.get("type") == 2
                and not str(data.get("text") or "").strip()
                and data.get("toolResults") in (None, [])
                and not isinstance(data.get("toolFormerData"), dict)
                and not data.get("conversationSummary")
            )
            if empty_assistant_envelope or not data:
                reason = (
                    "record_empty_assistant_envelope"
                    if empty_assistant_envelope else "record_empty_bubble"
                )
                _record_refused(
                    opts, reason, source_file=source_file,
                    bubble_id=bubble_id, record_type=str(data.get("type") or ""),
                )
            else:
                _record_refused(
                    opts, "record_unclassified", source_file=source_file,
                    bubble_id=bubble_id, record_type=str(data.get("type") or ""),
                )
        for event in events:
            yield composer_id, event
        request_context = request_contexts.pop(bubble_id, None)
        if request_context is not None:
            source_key, value = request_context
            context_event = _request_context_event(
                composer_id, bubble_id, source_key, value, source_file,
                _bubble_timestamp(data), opts,
            )
            if context_event is not None:
                yield composer_id, context_event
    for bubble_id, (source_key, value) in sorted(request_contexts.items()):
        context_event = _request_context_event(
            composer_id, bubble_id, source_key, value, source_file, None, opts
        )
        if context_event is not None:
            yield composer_id, context_event
    request_contexts.clear()


def _parsed_result(value: object) -> object | None:
    """Cursor's tool result as structure, where the vendor serialized structure.

    The result arrives as a string; where that string is a JSON object or array it is
    the vendor's own encoding of a structured result, so it is parsed on the same terms
    as `rawArgs`. A plain string result stays text: quoting it as JSON would assert a
    structure the vendor did not record.
    """
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text[:1] not in "{[":
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, (dict, list)) else None


def _bubble_to_events(
    composer_id: str,
    bubble_id: str,
    data: dict,
    source_file: str,
    opts: dict | bool,
    *,
    session_header: dict | None = None,
) -> Iterator[dict]:
    """Convert bubble to normalized event(s). Yields 0 or more events."""
    msg_type = data.get("type", 0)
    event_id = f"{composer_id}:{bubble_id}"
    if isinstance(opts, bool):
        opts = {"redact": opts}
    text = data.get("text") or ""
    timestamp = _bubble_timestamp(data)

    def base_ev(
        etype: str, subtype: str, role: str, content: str, content_len: int,
    ) -> dict[str, Any]:
        """This bubble's Event envelope, binding the four per-bubble values.

        A thin closure over `_base_event` rather than a second definition: the
        surrounding function already knows the composer, event id, timestamp,
        and source file, so every call would otherwise repeat them.
        """
        return _base_event(
            session_id=composer_id, event_id=event_id, event_type=etype,
            subtype=subtype, role=role, content=content,
            content_len=content_len, timestamp=timestamp,
            source_file=source_file,
        )

    def mapped(event: dict, rule: str, source_path: str = "$.bubble") -> dict:
        metadata = json.loads(event.get("metadata") or "{}")
        applied_rules = [rule]
        if metadata.get("context_observation_provenance"):
            applied_rules.append("cursor.context-window-observation")
        return annotate_mapping(
            event,
            source_record_type="cursorDiskKV.bubble",
            source_record_subtype=str(msg_type),
            source_record_locator=f"bubbleId:{composer_id}:{bubble_id}",
            mapping_rule=rule,
            source_path=source_path,
            applied_rules=applied_rules,
        )

    if msg_type == 1:
        text = apply_processing(
            text, opts, vendor="Cursor", record_type="bubble.user",
            event_kind="message.prompt", phase="pre",
        )
        if text is None:
            return
        subtype = "slash_command" if text.strip().startswith("/") else "prompt"
        truncated, content_len = truncate_content(text, TRUNCATE_PROMPT)
        truncated = apply_processing(
            truncated, opts, vendor="Cursor", record_type="bubble.user",
            event_kind="message.prompt", phase="post",
        )
        if truncated is None:
            return
        is_subagent = bool(
            isinstance(session_header, dict)
            and session_header.get("is_subagent")
        )
        event = base_ev(
            "system_event" if is_subagent else "user_message",
            "delegated_prompt" if is_subagent else subtype,
            "harness" if is_subagent else "user",
            truncated,
            content_len,
        )
        if is_subagent:
            event.update({
                "event_kind": "message.context",
                "actor_kind": "harness",
                "content_role": "delegated_task",
                "origin_kind": "harness_delegated",
            })
            _merge_metadata(event, {
                "actor_evidence": "composerHeaders.isSubagent",
                "source_is_subagent": True,
            })
        model_info, model_info_state = field_state.get_state(data, "modelInfo")
        if isinstance(model_info, dict):
            selection, selection_state = field_state.get_state(
                model_info, "modelName"
            )
            if isinstance(selection, str) and selection.strip():
                metadata: dict[str, Any] = {"model_set": selection.strip()}
                if selection.strip().lower() != "default":
                    metadata["model"] = selection.strip()
                    metadata["configuration_provenance"] = {
                        "model": {
                            "source_record_type": "bubble.user",
                            "source_record_locator": event_id,
                            "source_field": "modelInfo.modelName",
                        }
                    }
                _merge_metadata(event, metadata)
            else:
                if selection_state == field_state.PRESENT:
                    selection_state = field_state.MALFORMED
                field_state.attach(
                    event, field="model", state=selection_state,
                    source_field="modelInfo.modelName", value=selection,
                )
        else:
            if model_info_state == field_state.PRESENT:
                model_info_state = field_state.MALFORMED
            field_state.attach(
                event, field="model", state=model_info_state,
                source_field="modelInfo", value=model_info,
            )
        field_state.attach(
            event, field="prompt_origin", state=field_state.ABSENT,
            source_field="bubble.origin",
        )
        _merge_metadata(event, _bubble_evidence(data))
        yield mapped(event, "cursor.bubble")
        return

    if msg_type == 2:
        if text.strip():
            text = apply_processing(
                text, opts, vendor="Cursor", record_type="bubble.assistant",
                event_kind="message.response", phase="pre",
            )
        if text and text.strip():
            truncated, content_len = truncate_content(text, TRUNCATE_RESPONSE)
            truncated = apply_processing(
                truncated, opts, vendor="Cursor", record_type="bubble.assistant",
                event_kind="message.response", phase="post",
            )
            if truncated is None:
                return
            response = base_ev(
                "assistant_message", "response", "assistant",
                truncated, content_len,
            )
            _merge_metadata(response, _bubble_evidence(data))
            yield mapped(response, "cursor.bubble")

        # Reasoning is its own Event, because Cursor never puts it beside a
        # response: measured over 40,000 bubbles, every one carrying `thinking`
        # has empty `text`, so the response branch above emits nothing for them
        # and the reasoning would be lost with the bubble. Codex already emits
        # `message.reasoning_summary` for the same evidence, so a cross-vendor
        # reasoning query needs no per-vendor case.
        reasoning = _reasoning_metadata(data)
        summary_text = reasoning.get("reasoning_summary")
        if isinstance(summary_text, str) and summary_text.strip():
            processed = apply_processing(
                summary_text, opts, vendor="Cursor",
                record_type="bubble.thinking",
                event_kind="message.reasoning_summary", phase="pre",
            )
            if processed and processed.strip():
                bounded, reasoning_len = truncate_content(
                    processed, TRUNCATE_RESPONSE
                )
                # `retained` rather than reassigning `bounded`: post-processing
                # may refuse the body and return `None`, which is a different
                # type from the bounded text, and a second name keeps both
                # readable and checkable.
                retained = apply_processing(
                    bounded, opts, vendor="Cursor",
                    record_type="bubble.thinking",
                    event_kind="message.reasoning_summary", phase="post",
                )
                if retained is not None:
                    think_ev = base_ev(
                        "assistant_message", "reasoning_summary", "assistant",
                        retained, reasoning_len,
                    )
                    think_ev["event_id"] = f"{event_id}:reasoning"
                    think_ev["event_kind"] = "message.reasoning_summary"
                    think_ev["actor_kind"] = "model"
                    think_ev["content_role"] = "reasoning"
                    think_ev["origin_kind"] = "model_generated"
                    _merge_metadata(think_ev, _bubble_evidence(data))
                    yield mapped(think_ev, "cursor.reasoning")

        summary_value = data.get("conversationSummary")
        if isinstance(summary_value, str) and summary_value.strip():
            try:
                summary = json.loads(summary_value)
            except json.JSONDecodeError:
                summary = {"summary": summary_value}
            if not isinstance(summary, dict):
                summary = {"summary": str(summary)}
            body = summary.get("summary")
            if isinstance(body, str):
                body = apply_processing(
                    body, opts, vendor="Cursor",
                    record_type="bubble.conversationSummary",
                    event_kind="context.compact", phase="pre",
                )
            if isinstance(body, str):
                body, summary_len, truncated_summary = bound_context_content(
                    body, opts
                )
                body = apply_processing(
                    body, opts, vendor="Cursor",
                    record_type="bubble.conversationSummary",
                    event_kind="context.compact", phase="post",
                )
                if body is not None:
                    body, _post_length, post_truncated = bound_context_content(
                        body, opts
                    )
                    truncated_summary = (
                        truncated_summary or post_truncated
                    )
                    compact = base_ev(
                        "system_event", "context_compaction", "harness",
                        body, summary_len,
                    )
                    compact["event_id"] = f"{event_id}:compaction"
                    compact["event_kind"] = "context.compact"
                    compact["actor_kind"] = "harness"
                    compact["content_role"] = "context"
                    compact["origin_kind"] = "harness_injected"
                    metadata = {
                        "audit_kind": "context_compaction",
                        "context_kind": "conversation_summary",
                        "content_truncated": truncated_summary,
                    }
                    for key in (
                        "truncationLastBubbleIdInclusive",
                        "clientShouldStartSendingFromInclusiveBubbleId",
                        "previousConversationSummaryBubbleId",
                        "includesToolResults",
                    ):
                        if summary.get(key) is not None:
                            metadata[key] = summary[key]
                    metadata.update(_bubble_evidence(data))
                    compact["metadata"] = json.dumps(
                        metadata, separators=(",", ":")
                    )
                    yield mapped(
                        compact,
                        "cursor.compaction-summary",
                        "$.bubble.conversationSummary",
                    )

        tool_former = data.get("toolFormerData")
        if isinstance(tool_former, dict):
            tool_name = tool_former.get("name")
            call_id = tool_former.get("toolCallId") or f"{event_id}:toolFormerData"
            status = str(tool_former.get("status") or "unknown")
            has_tool_evidence = any(
                tool_former.get(key) not in (None, "")
                for key in ("name", "toolCallId", "rawArgs", "params", "result", "status")
            )
            if has_tool_evidence:
                raw_input = tool_former.get("rawArgs")
                if raw_input in (None, ""):
                    raw_input = tool_former.get("params")
                input_text = "" if raw_input is None else (
                    json.dumps(raw_input, ensure_ascii=False, separators=(",", ":"))
                    if isinstance(raw_input, (dict, list)) else str(raw_input)
                )
                input_text = apply_processing(
                    input_text, opts, vendor="Cursor", record_type="tool_input",
                    event_kind="tool.call", phase="pre",
                )
                normalized = {
                    "completed": "succeeded", "complete": "succeeded",
                    "error": "failed", "failed": "failed",
                    "loading": "running", "running": "running",
                    "pending": "pending", "cancelled": "cancelled",
                }.get(status.lower(), "unknown")
                user_decision = str(tool_former.get("userDecision") or "").lower()
                if user_decision == "rejected":
                    normalized = "denied"
                result_failure = None
                tool_name_text = str(tool_name or "")
                if (
                    normalized == "succeeded"
                    and (
                        tool_name_text.startswith("mcp-")
                        or tool_name_text.startswith("mcp__")
                    )
                ):
                    result_failure = application_failure_evidence(
                        tool_former.get("result")
                    )
                    if result_failure:
                        normalized = "failed"
                metadata_values = {
                    "call_id": str(call_id),
                    "model_call_id": tool_former.get("modelCallId"),
                    "status": status,
                    "source_field": "toolFormerData",
                }
                if user_decision:
                    metadata_values.update({
                        "user_decision": user_decision,
                        "permission_provenance": "toolFormerData.userDecision",
                    })
                if result_failure:
                    metadata_values.update({
                        "application_status": "failed",
                        "result_status_evidence": result_failure,
                    })
                metadata_json = json.dumps(metadata_values, separators=(",", ":"))
                call = base_ev("tool_call", "tool_call", "assistant", "", 0)
                call["event_id"] = f"{event_id}:tool-call"
                call["tool_name"] = str(tool_name or "unknown")
                call["tool_input"] = structured_json(input_text)
                call["file_path"] = _tool_file_path(tool_former)
                call["metadata"] = metadata_json
                call["source_status"] = status
                call["normalized_status"] = normalized
                _input_value, input_state = field_state.get_state(
                    tool_former,
                    "rawArgs" if "rawArgs" in tool_former else "params",
                )
                field_state.attach(
                    call, field="tool_input", state=input_state,
                    source_field=(
                        "toolFormerData.rawArgs"
                        if "rawArgs" in tool_former
                        else "toolFormerData.params"
                    ),
                    value=_input_value,
                )
                yield mapped(
                    call,
                    "cursor.tool-former-invocation",
                    "$.bubble.toolFormerData",
                )

                result_value = tool_former.get("result")
                final_status = normalized in {"succeeded", "failed", "denied", "cancelled", "incomplete"}
                if result_value is not None or final_status:
                    result_text = "" if result_value is None else str(result_value)
                    result_text = apply_processing(
                        result_text, opts, vendor="Cursor", record_type="tool_result",
                        event_kind="tool.result", phase="pre",
                    )
                    if result_text is not None:
                        result_text, result_len = truncate_content(result_text, TRUNCATE_TOOL_RESULT)
                        result_text = apply_processing(
                            result_text, opts, vendor="Cursor", record_type="tool_result",
                            event_kind="tool.result", phase="post",
                        )
                        if result_text is not None:
                            result = base_ev(
                                "user_message",
                                (
                                    "permission_denied" if normalized == "denied"
                                    else "tool_failure" if normalized == "failed"
                                    else "tool_result"
                                ),
                                "tool", result_text, result_len,
                            )
                            result["event_id"] = f"{event_id}:tool-result"
                            result["tool_name"] = str(tool_name or "unknown")
                            result["tool_output"] = result_text
                            # Cursor serializes both its arguments and its results as
                            # JSON strings; `rawArgs` is already parsed into
                            # `tool_input`, so the result is parsed on the same terms.
                            # The text projection is bounded and keeps the whole value.
                            result["tool_output_structured"] = _parsed_result(result_value)
                            result["metadata"] = metadata_json
                            result["source_status"] = status
                            result["normalized_status"] = normalized
                            yield mapped(
                                result,
                                "cursor.tool-former-result",
                                "$.bubble.toolFormerData",
                            )

        tool_results = data.get("toolResults") or []
        for i, tr in enumerate(tool_results):
            tname = tr.get("toolName") or "unknown"
            result = tr.get("result")
            result_str = str(result) if result is not None else ""
            result_str = apply_processing(
                result_str, opts, vendor="Cursor", record_type="tool_result",
                event_kind="tool.result", phase="pre",
            )
            if result_str is None:
                continue
            ttrunc, tlen = truncate_content(result_str, TRUNCATE_TOOL_RESULT)
            ttrunc = apply_processing(
                ttrunc, opts, vendor="Cursor", record_type="tool_result",
                event_kind="tool.result", phase="post",
            )
            if ttrunc is None:
                continue
            ev = base_ev("user_message", "tool_result", "user", ttrunc, tlen)
            ev["event_id"] = f"{event_id}:tr{i}"
            ev["tool_name"] = tname
            ev["tool_output"] = ttrunc
            yield mapped(
                ev,
                "cursor.tool-result-legacy",
                f"$.bubble.toolResults[{i}]",
            )
