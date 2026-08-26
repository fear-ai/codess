"""Cursor record decoder: bubbleId messages to common Events.

**Owns decode.** Normalization, field mapping, truncation, and content
processing for Cursor records. It holds no storage dependency: rows arrive
through `cursor_source` accessors, so this module names no database, table,
or key range (see the ownership table in `cursor_source`).
"""

import json
import logging
import re
import time
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from codess import field_state
from codess.config import (
    AGENT_KV,
    TRUNCATE_PROMPT,
    TRUNCATE_RESPONSE,
    TRUNCATE_TOOL_RESULT,
)
from codess.content_processing import apply_processing
from codess.context_content import bound_context_content, truncate_content
from codess.cursor_source import (
    classify_kv_value,
    open_agent_kv_rows,
    open_bubble_rows,
    open_message_request_context_rows,
)
from codess.cursor_source import (
    parse_timestamp as _parse_timestamp,
)
from codess.hashing import codess_text_hash
from codess.mapping import (
    RecordContext,
    annotate_mapping,
    as_mapping,
    structured_json,
)
from codess.settings import resolve_named
from codess.tool_result_status import application_failure_evidence

log = logging.getLogger(__name__)

BUBBLE_FIELD_TOTAL = 98
"""Distinct keys observed on a Cursor bubble, sampled over 20,000 bubbles.

Roughly 40 are present on essentially every bubble and non-empty on none --
`lints`, `commits`, `pullRequests`, `gitDiffs`, `images`, and the rest. Kept as
a measurement with its sample size rather than as a live count, because the
figure a coverage report needs is what the *vendor record* holds, and deriving
it from one store would report that store's population instead.
"""

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
    # Retained whenever the vendor states it, including when it states zero: a
    # recorded zero says the vendor reported no usage, which is not the same as
    # the field being absent, and only the first can be revisited.
    "tokenCount",
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
            # `full`, not `summary`: `thinking.text` is the reasoning itself.
            # The adjacent `redactedThinking` flag only means something beside
            # content, and the text runs to a 2,000-character bound where
            # Codex's summaries have a 50-character median. Codex supplies a
            # précis and this supplies the reasoning; the field says which so a
            # cross-vendor query can compare them without conflating them.
            values["reasoning_fidelity"] = "full"
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
        values["reasoning_fidelity"] = "full"
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


def _enrich_from_bubble(event: dict, data: dict) -> None:
    """Apply every per-bubble value an Event carries, columns and metadata.

    One function rather than two calls per site, for the reason
    `_bubble_evidence` already records: four construction sites drift, which is
    how `contextWindowStatusAtCreation` came to be merged at three of them and
    not the fourth. A value that acquires a column later is added here and
    reaches every site at once.
    """
    _merge_metadata(event, _bubble_evidence(data))
    counts = data.get("tokenCount")
    if not isinstance(counts, dict):
        return
    # A recorded zero states that the vendor measured no usage, which a query
    # distinguishes from an absent field only if the zero is stored.
    for vendor_key, column in (
        ("inputTokens", "input_tokens"), ("outputTokens", "output_tokens"),
    ):
        value = counts.get(vendor_key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            event[column] = value


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


def _repeat_references(ordered: list[tuple[str, dict]]) -> dict[str, str]:
    """Map each repeated bubble to the earlier one it repeats.

    A long-lived composer is re-synced and the sync writes server-identified
    copies of bubbles that already exist locally, so one `toolCallId` survives
    on two bubbles after dedup. Both are real vendor records: field by field
    they differ only in `bubbleId`, `serverBubbleId`, and `createdAt` and agree
    on the other ninety-five.

    The reference names the *earlier* bubble because `ordered` is sorted, so
    the first occurrence is the original and every later one repeats it.
    Recording the relationship rather than deleting a record is the standard
    the rest of the schema already uses -- an exact vendor value beside a mapped
    one -- and deleting would be unrecoverable where an advisory reference can
    simply be ignored.
    """
    first: dict[str, str] = {}
    references: dict[str, str] = {}
    for bubble_id, data in ordered:
        call_id = as_mapping(data.get("toolFormerData")).get("toolCallId")
        if not call_id:
            continue
        key = str(call_id)
        if key in first:
            references[bubble_id] = first[key]
        else:
            first[key] = bubble_id
    return references


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
        call_id = as_mapping(data.get("toolFormerData")).get("toolCallId")
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


def _carries_unique_evidence(role: str, data: dict) -> bool:
    """Whether a blob holds evidence no other Cursor structure records.

    The system prompt and the reasoning parts do; text and tool parts duplicate
    what the bubble tables already carry. The distinction decides which reason
    code an unattributed blob is counted under, so a reader can tell a corpus
    that is merely redundant from one that is lost.
    """
    if role == "system":
        # Its content is a plain string rather than typed parts, so a list
        # check would answer False for the one record that most needs a True.
        return True
    content = data.get("content")
    return isinstance(content, list) and any(
        isinstance(part, dict)
        and part.get("type") in ("reasoning", "redacted-reasoning")
        for part in content
    )


_PROMPT_SECTION = re.compile(r"^<([a-z_][a-z0-9_]*)>\s*$", re.MULTILINE)
# `powered by <model>` is the form every observed prompt uses to name the model
# it addressed, and the name runs to end-of-sentence or end-of-line. A dot is
# not a terminator: `claude-4.6-opus-high-thinking` contains one, and stopping
# at the first produced `claude-4`. `You are gpt-5.3-codex.` has no `powered
# by`, so the bare form is a second alternative rather than an optional group --
# optional matched the prose in `You are a powerful agentic AI coding
# assistant powered by Cursor` and captured the adjective.
_PROMPT_MODEL = re.compile(
    r"^You are (?:.*?powered by )?([A-Za-z0-9][\w.\- ]*?)\.?\s*(?:$|\. )",
    re.MULTILINE,
)


def harness_prompt_evidence(text: str) -> dict[str, Any]:
    """What a harness system prompt states about itself, as queryable fields.

    Every prompt observed is textually unique and they fall into families: two
    prompts of the same family measured 97.6% similar and differed in one line,
    while prompts of different families differ in length by a factor of ten.
    Storing 23 near-duplicate bodies would answer no question the body alone
    cannot; storing the *structure* lets a reader group them, diff two
    variants, and see which model each addressed.

    Three facts, each read rather than inferred:

    - `harness_prompt_model` is the model the prompt names in its first line.
      It is what the *harness told the model it was*, which is not necessarily
      the model that served the turn -- Cursor's `Auto` router says "You are
      Auto" while a model name appears on the bubble.
    - `harness_prompt_sections` is the ordered list of `<section>` tags. These
      are the prompt's own structure and are what differs between versions:
      a release that adds `mode_selection` adds the tag.
    - `harness_prompt_digest` identifies the exact text, so two Sessions can be
      compared for having received the same instruction without either body
      being read.

    The body itself is retained as ordinary Event content under the content
    policy, so a reader who wants the text has it and a reader who wants the
    shape does not have to parse it.
    """
    sections = _PROMPT_SECTION.findall(text)
    model = _PROMPT_MODEL.search(text)
    values: dict[str, Any] = {
        "harness_prompt_digest": codess_text_hash(256, 256, text),
        "harness_prompt_chars": len(text),
        "harness_prompt_sections": sections,
        "harness_prompt_section_count": len(sections),
    }
    if model:
        values["harness_prompt_model"] = model.group(1).strip()
    return values


def _agent_kv_tool_ids(data: dict) -> list[str]:
    """Every tool-call identity stated on one `agentKv` message."""
    content = data.get("content")
    if not isinstance(content, list):
        return []
    found = []
    for part in content:
        if not isinstance(part, dict):
            continue
        if part.get("type") not in ("tool-call", "tool-result"):
            continue
        call_id = part.get("toolCallId")
        if isinstance(call_id, str) and call_id.strip():
            found.append(call_id.strip())
    return found


def agent_kv_events(
    rows: Iterable[tuple[str, object]],
    *,
    source_file: str,
    request_sessions: dict[str, str],
    tool_call_sessions: dict[str, str] | None = None,
    opts: dict,
) -> Iterator[dict]:
    """Map the `agentKv` message corpus that no other Cursor structure records.

    Three things here exist nowhere else in what Codess decodes: the harness
    system prompt, which is the only record of what the model was instructed to
    do; `redacted-reasoning` as a first-class content part, where the bubble
    format has only a flag saying reasoning was withheld; and reasoning text on
    requests whose bubbles the vendor has since pruned.

    **Text and tool parts are deliberately not mapped.** Every `tool-call` and
    `tool-result` here already produces an Event from the bubble tables, and
    user and assistant text duplicates bubble text for the requests that join.
    Mapping both would double-count every tool interaction and double the
    searchable corpus for no new evidence -- which is the rule already applied
    to `toolResults` and `conversationState`.

    **Two join keys, both vendor-stated.** `providerOptions.cursor.requestId`
    binds a message to a request the bubbles also record, but it reaches only
    user messages: over 20,000 sampled blobs, 382 user messages carry one and
    6,919 assistant, tool, and system messages carry none.

    `toolCallId` is the second and it reaches what the first cannot. A
    `tool-call` or `tool-result` part states the same identity Cursor writes to
    `toolFormerData.toolCallId` on a bubble, so a message carrying one is bound
    to whichever composer holds that bubble -- measured, 6,258 matches reaching
    20 composers. **76 of the 80 messages carrying reasoning also carry a
    tool-call**, so the reasoning is bound with it: the binding is a vendor-
    stated identifier on the *same record*, not an inference from adjacency.

    **What remains unattributed has no key, and the near-miss was tested.**
    Measured over the whole corpus rather than a sample: 23 system messages and
    1,230 reasoning messages carry neither identifier. Every one of those 1,230
    carries assistant `text` beside the reasoning, and that text matches a
    bubble exactly 6,054 times across 47 composers -- so matching on it looks
    like a binding and is not one. **1,943 distinct bubble texts appear in more
    than one composer**, one of them (`"continue"`) in eleven, so a text match
    resolves to the wrong Session often enough to be worse than no binding.
    That is the textual-resemblance case CoSchema forbids, and the measurement
    is why rather than the rule alone.

    Attributing by key order is equally refused: the key is a content hash, so
    order carries no sequence. Both classes are counted under a reason code
    naming the condition, so the corpus is countable rather than silently
    absent.
    """
    tool_call_sessions = tool_call_sessions or {}
    for key, value in rows:
        kind = classify_kv_value(value)
        if kind != "json":
            # Counted by content kind rather than as a parse failure: most of
            # these are protobuf and file bodies, and calling them malformed
            # counts real content as a decoder defect.
            _record_refused(
                opts, f"record_agent_kv_{kind}",
                source_file=source_file, bubble_id=str(key),
                record_type="agentKv.blob",
            )
            continue
        try:
            data = json.loads(
                value if isinstance(value, str | bytes | bytearray) else str(value)
            )
        except (ValueError, TypeError):
            _record_refused(
                opts, "record_unparseable",
                source_file=source_file, bubble_id=str(key),
                record_type="agentKv.blob",
            )
            continue
        if not isinstance(data, dict):
            continue
        provider = data.get("providerOptions")
        cursor_options = provider.get("cursor") if isinstance(provider, dict) else None
        request_id = (
            cursor_options.get("requestId") if isinstance(cursor_options, dict) else None
        )
        role = str(data.get("role") or "")
        content = data.get("content")
        # A system message states its content as a plain string; every other
        # role states a list of typed parts. Reading only the list form skipped
        # all 23 system prompts silently, which is the shape this normalizes.
        parts = (
            [{"type": "text", "text": content}]
            if isinstance(content, str) and content.strip()
            else content if isinstance(content, list) else []
        )
        session_id = request_sessions.get(str(request_id or ""))
        if not session_id:
            # The tool-call identity on this same message, which is what binds
            # the reasoning beside it. First match wins: a message states one
            # exchange, so its tool ids resolve to one composer or to none.
            for call_id in _agent_kv_tool_ids(data):
                session_id = tool_call_sessions.get(call_id)
                if session_id:
                    break
        if not session_id:
            # Named by what is lost rather than by the join that failed. A
            # system prompt or a reasoning part with no binding is evidence
            # that exists and cannot be placed; a tool or text part is a
            # duplicate of what the bubbles already carry, and losing it costs
            # nothing. Counting them together would report the second volume
            # and hide the first.
            _record_refused(
                opts,
                "record_agent_kv_unattributed"
                if _carries_unique_evidence(role, data)
                else "record_agent_kv_unbound_duplicate",
                source_file=source_file, bubble_id=str(key),
                record_type=f"agentKv.{role or 'unknown'}",
            )
            continue
        for index, part in enumerate(parts):
            if not isinstance(part, dict):
                continue
            event = _agent_kv_part_event(
                part, index,
                RecordContext(
                    session_id=session_id, source_file=source_file,
                    line_num=index, opts=opts,
                ),
                key=str(key), role=role, request_id=str(request_id),
            )
            if event is not None:
                yield event


def _agent_kv_part_event(
    part: dict,
    index: int,
    context: RecordContext,
    *,
    key: str,
    role: str,
    request_id: str,
) -> dict | None:
    """One `agentKv` content part, where it carries evidence nothing else does.

    The blob key is the locator rather than `context.line_num`: a blob is
    content-addressed, so there is no line to cite, and `line_num` carries the
    part's index within the message instead.
    """
    session_id, source_file, opts = (
        context.session_id, context.source_file, context.opts,
    )
    part_type = str(part.get("type") or "")
    if role == "system":
        subtype, rule = "harness_instruction", "cursor.agent-system-prompt"
        event_kind, content_role = "message.context", "context"
        text = part.get("text") if part_type == "text" else None
        origin_kind = "harness_injected"
        prompt_evidence = (
            harness_prompt_evidence(text) if isinstance(text, str) else {}
        )
    elif part_type in ("reasoning", "redacted-reasoning"):
        subtype, rule = "reasoning_summary", "cursor.agent-reasoning"
        event_kind, content_role = "message.reasoning_summary", "reasoning"
        text = part.get("text")
        origin_kind = "model_generated"
    else:
        # Every other part duplicates evidence the bubble tables already carry.
        return None
    if not isinstance(text, str) or not text.strip():
        if part_type == "redacted-reasoning":
            text = ""
        else:
            return None
    text = apply_processing(
        text, opts, vendor="Cursor", record_type=f"agentKv.{part_type}",
        event_kind=event_kind, phase="pre",
    )
    if text is None:
        return None
    text, content_len, truncated = bound_context_content(text, opts)
    metadata = {
        "agent_kv_role": role,
        "agent_kv_part_type": part_type,
        "request_id": request_id,
        "content_truncated": truncated,
    }
    if role == "system":
        # Structure beside the body: every observed prompt is textually unique
        # and they group into families, so the sections and the digest are what
        # make them comparable without reading 23 near-identical texts.
        metadata.update(prompt_evidence)
    if part_type in ("reasoning", "redacted-reasoning"):
        # The same distinction `reasoning_fidelity` draws for the bubble path:
        # this is the reasoning itself rather than a vendor précis of it.
        metadata["reasoning_fidelity"] = "full"
        if part_type == "redacted-reasoning":
            # A first-class part saying the vendor withheld it, which is a
            # different fact from the field being absent.
            metadata["reasoning_redacted"] = True
    event = _base_event(
        session_id=session_id,
        event_id=f"{key}:{index}",
        event_type="system_event" if role == "system" else "assistant_message",
        subtype=subtype,
        role="harness" if role == "system" else "assistant",
        content=text,
        content_len=content_len,
        timestamp=None,
        source_file=source_file,
        metadata=json.dumps(metadata, separators=(",", ":"), sort_keys=True),
        event_kind=event_kind,
        actor_kind="harness" if role == "system" else "model",
        content_role=content_role,
        origin_kind=origin_kind,
    )
    return annotate_mapping(
        event,
        source_record_type="cursorDiskKV.agentKv",
        source_record_subtype=part_type or None,
        source_record_locator=key,
        mapping_rule=rule,
        source_path=f"$.content[{index}]",
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


def _agent_kv_by_session(
    db_path: Path,
    source_file: str,
    composer_ids: set[str] | None,
    opts: dict,
) -> dict[str, list[dict]]:
    """Decode the `agentKv` corpus once, grouped by the Session it binds to.

    A prior pass rather than an accumulation, because the join map must be
    complete before the first Session is emitted: the blobs are
    content-addressed and arrive in hash order, so a message binding to the
    first composer can appear after a message binding to the last.

    Reads only the bubbles' identifiers, not their content, so the cost is one
    scan of the selected key ranges rather than a second decode.
    """
    request_sessions: dict[str, str] = {}
    tool_call_sessions: dict[str, str] = {}
    for key, value in open_bubble_rows(db_path, composer_ids):
        parts = str(key).split(":", 2)
        if len(parts) < 2 or not isinstance(value, str | bytes | bytearray):
            continue
        try:
            data = json.loads(value)
        except (ValueError, TypeError):
            continue
        if not isinstance(data, dict):
            continue
        composer_id = parts[1]
        request = data.get("requestId")
        if isinstance(request, str) and request.strip():
            request_sessions[request.strip()] = composer_id
        usage = data.get("usageUuid")
        if isinstance(usage, str) and usage.strip():
            request_sessions.setdefault(usage.strip(), composer_id)
        call_id = as_mapping(data.get("toolFormerData")).get("toolCallId")
        if isinstance(call_id, str) and call_id.strip():
            tool_call_sessions.setdefault(call_id.strip(), composer_id)
    if not (request_sessions or tool_call_sessions):
        return {}
    grouped: dict[str, list[dict]] = {}
    for event in agent_kv_events(
        open_agent_kv_rows(db_path),
        source_file=source_file,
        request_sessions=request_sessions,
        tool_call_sessions=tool_call_sessions,
        opts=opts,
    ):
        grouped.setdefault(str(event["session_id"]), []).append(event)
    return grouped


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
    # Decoded once, before any composer is emitted, and consumed per Session
    # below. The consumer flushes on each change of `session_id` and refuses a
    # Session it has already flushed, so an `agentKv` Event must travel with
    # its Session's bubbles rather than after all of them -- and the join map
    # has to be complete before the first Session is emitted, which is why this
    # is a prior pass rather than an accumulation.
    agent_kv_by_session: dict[str, list[dict]] = {}
    if resolve_named(opts.get("include_agent_kv"), "include_agent_kv", AGENT_KV):
        agent_kv_by_session = _agent_kv_by_session(
            db_path, source_file, composer_ids, opts,
        )
    composer_start_tick: float | None = None
    last_progress: float | None = None

    def emit(event: str, **fields: object) -> None:
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
            for event in agent_kv_by_session.pop(current_composer, ()):
                yield current_composer, event
            bubbles.clear()
        if composer_id != current_composer:
            current_composer = composer_id
            composer_start_tick = last_progress_tick = time.monotonic()
            emit("cursor.composer.read.start")
        bubbles.append((bubble_id, data))
        now_tick = time.monotonic()
        if composer_start_tick is not None and (
            len(bubbles) % _PROGRESS_ROWS == 0
            or (
                last_progress is not None
                and now_tick - last_progress_tick >= _PROGRESS_SECONDS
            )
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
        for event in agent_kv_by_session.pop(current_composer, ()):
            yield current_composer, event

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
    repeated = _repeat_references(ordered)
    for bubble_id, data in ordered:
        events = list(
            _bubble_to_events(
                composer_id, bubble_id, data, source_file, opts,
                session_header=session_header,
            )
        )
        original = repeated.get(bubble_id)
        if original is not None:
            for event in events:
                # Advisory, not a deletion: both bubbles are real vendor
                # records, so a reader wanting the raw count ignores this and
                # one excluding replays selects on it.
                event["duplicate_of"] = original
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
        _enrich_from_bubble(event, data)
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
            _enrich_from_bubble(response, data)
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
                    _enrich_from_bubble(think_ev, data)
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
                    compact["metadata"] = json.dumps(
                        metadata, separators=(",", ":")
                    )
                    _enrich_from_bubble(compact, data)
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
