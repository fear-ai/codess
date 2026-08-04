# CodexSchema — OpenAI Codex CLI Session Storage

Vendor-specific structure for **Codex CLI** sessions. Normalized ingest: `src/codess/adapters/codex.py`. Scan: `src/codess/scan.py` (`_session_metrics_codex`).

**Stability note:** Codex documents the transcript path, but the transcript
format is not a stable public interface and may change. The shapes below
describe the current tolerant Codess adapter and verified local fixtures, not a
compatibility guarantee from Codex.

## 1. Source Scope

| Field | Value |
|-------|--------|
| **Vendor** | OpenAI Codex CLI |
| **Primary paths** | Active: `~/.codex/sessions/**/*.jsonl`; archived: `~/.codex/archived_sessions/**/*.jsonl` |
| **Encoding** | UTF-8 JSONL |
| **Time basis** | `timestamp` on lines: numeric (s or ms) or ISO 8601 string |

## 2. Storage Layout

| Pattern | Role |
|---------|------|
| Date-partitioned or flat tree of `*.jsonl` | **One file = one session** |
| `session_meta` record | Session identity, working directory, source, originator, provider, and CLI version |

Codess searches past blank or malformed prefix lines for `session_meta`.
Active and archived roots are both read by default. Setting
`CODESS_CODEX_SESSIONS` isolates active input and disables the default archive
root; set `CODESS_CODEX_ARCHIVED_SESSIONS` explicitly to add an archive root.
If active and archived roots contain the same session id, the active transcript
wins; within one root the newest file wins. Re-ingest transactionally replaces
the selected session rather than leaving events removed from the transcript.

### 2.1 Names, Projects, and Runtime State

ChatGPT desktop Projects are application groupings of chats. They are not the
same entity as a Codex CLI working directory or a Codess Project. Recent Codex
CLI releases support `/rename`, and local Codex state databases can retain a
thread title, but that title is not present in the session JSONL
`session_meta`. Codess therefore keeps a user-assigned Session name separate
from source title evidence and the stable Codess Session ID.

The live Codex app protocol can report thread runtime states such as active,
idle, not loaded, or system error. The JSONL transcript and persisted thread
index do not reconstruct that live state. Codess may record a dated runtime
observation when such an interface supplies it; source mtime, an unanswered
prompt, or an active-tree pathname alone yields runtime `unknown`.

## 3. Selective Access

| Method | Use |
|--------|-----|
| **Codess scan** | `codess scan --dir <work>`; matches `session_meta.payload.cwd` to project |
| **Codess ingest** | `codess ingest --dir <project>`; collects files whose `cwd` resolves to project root |
| **Direct read** | Open file; locate `session_meta`, then stream records tolerantly |

## 4. Session Metadata

| Field path | Type | Notes |
|------------|------|--------|
| `type` | string | Must be `session_meta` |
| `payload.id` | string | Session id fallback |
| `payload.cwd` | string | Project directory; resolved and compared to scan path |
| `payload.cli_version` | string | Stored as normalized session release and metadata |
| `payload.model_provider`, `originator`, `source` | scalar or version-specific structured value | Retained as bounded session metadata; provider can seed a session-level configuration. Current protocol releases can encode structured Session source/subagent evidence, so mapping must be shape- and release-aware |
| `timestamp` | number or string | Session time for `--days` filter |

## 5. Rollout Records and Mapping

Ingest adapter primarily uses:

| `type` | Role |
|--------|------|
| `session_meta` | Supplies session identity/metadata; not emitted as an event |
| `response_item.message` | Canonical user and assistant messages |
| Paired `event_msg.user_message` plus `response_item.message role=user` | Exact pairing identifies a direct UI prompt in current rollouts. An unpaired user-role message is retained as harness context; the source role remains `user` in mapping evidence |
| `response_item.reasoning.summary[].text` | Vendor-exposed reasoning summary retained as `message.reasoning_summary`; encrypted reasoning state is not decoded |
| `response_item.function_call` / `custom_tool_call` | Tool calls with sanitized JSON input and call-id metadata; structured failed/error/incomplete status becomes `tool_failure` |
| `response_item.tool_search_call` / `tool_search_output` | Server-side tool discovery request/result, retained as one linked tool exchange |
| `response_item.web_search_call` | `web_search` tool call with sanitized action metadata |
| Matching call-output records | Tool results; call id restores the tool name. For an MCP call, an explicit error body is application failure even when the MCP transport completed successfully |
| `compacted` | Replacement-history envelope; its dedicated `compaction` item becomes one bounded `context.compact` event |
| `event_msg.turn_aborted` | Retained as a `turn_aborted` assistant audit event |
| `event_msg.task_started` / `task_complete` | Retained as harness lifecycle events; completion text is not duplicated as another assistant response |
| `event_msg.context_compacted` | Notification paired with `compacted`; recognized but not emitted again |
| `event_msg.web_search_end` / `patch_apply_end` | Linked result/status evidence for the corresponding tool call when a call id is available |
| `event_msg.mcp_tool_call_end` | Harness transport/status evidence for the corresponding MCP invocation: server/tool, connector/app/action/plugin identifiers, duration, and transport result status. The result body is not copied a second time; application status is linked from the matching call-output record |
| `event_msg.thread_rolled_back` | Bounded `context.rollback` lifecycle evidence with the number of removed user turns |
| `turn_context` | Not emitted as conversation text. Exact `payload.model` and `payload.effort`/`reasoning_effort`, plus the specifically identified collaboration mode, are attached to subsequent normalized events with source-record/field provenance; observed `payload.turn_id` becomes vendor `model_turns.source_turn_id` |
| `event_msg.thread_settings_applied` | Newer bounded settings envelope. Exact model, provider, reasoning effort, service tier, approval policy, and collaboration mode update subsequent event/model-turn configuration |
| `response_item.message` with `developer` or `system` role | Bounded harness/context injection, not a human prompt |
| Duplicate `event_msg` message/reasoning notifications | Counted as known duplicate envelopes after the canonical `response_item` representation is retained |
| `event_msg.token_count` | Counted as a known usage observation and consumed by utilization reporting, not duplicated as conversation text |
| `response_item.ghost_snapshot` / `world_state` | Counted as known intermediate state, not conversation text |
| Unsupported record shapes | Counted as unknown ignored diagnostics and require review |

The typed configuration query uses exact provider, model, effort, service, and
mode filters to resolve governing Model Turns and expose their direct `turn_context` or
`thread_settings_applied` field paths, record locators, and Source revisions.

Record timestamps accept Unix seconds, Unix milliseconds, and ISO 8601. Tool
call/result lineage is stored in event metadata through `call_id`.
Every emitted event also retains `response_item`/`event_msg`, the payload type,
line locator, declared mapping rule, and structured trace. Configured active or
archive roots supply explicit session archive state and provenance; an archive
location is not interpreted as successful completion.

`update_plan` is retained as an ordinary named tool call. It is useful
planning-activity evidence, but the name alone does not expose hidden model
reasoning or prove a separate agent. Likewise, an MCP completion notification
is transport evidence, not a second invocation. An `Ok` transport containing a
GitHub/API error body remains transport-success/application-failure; the
adapter preserves both facts rather than allowing transport success to mask
the useful outcome.

An installed Codex plugin or app connector can supply MCP-backed tools without
a hand-written `[mcp_servers.*]` entry. Configuration inventory, tool
discovery, tool invocation, transport completion, and application result are
therefore separate observations. Codess does not infer that an MCP server was
intentionally configured merely because one of those tools appears in a
rollout.

Malformed payload containers, tool inputs, timestamps, and configuration fields
are diagnosed at field scope and dropped independently. A malformed optional
field does not discard an otherwise supported record.

## 6. Scan Observations

| Metric | Definition |
|--------|------------|
| **Sessions** | Count of `*.jsonl` files whose first line is `session_meta` and `cwd` matches project |
| **Events** | Count of non-empty lines per matching file (includes all record types on lines) |
| **Size (mb)** | Sum of `file.stat().st_size` for matching files |
| **days_ago** | From max `timestamp` among matching sessions (parsed to ms) |
| **span_weeks** | Spread of timestamps across matching files |

## 7. Limitations and Coverage Boundaries

- Timestamp formats mixed (Unix s, Unix ms, ISO); parser normalizes to ms where possible.
- “Events” in scan ≠ only chat messages; includes structural lines.
- History file `~/.codex/history.jsonl` (if present) is **not** the same as session store; CodexSchema applies to `sessions/`.
- Vendor-exposed reasoning summaries are first-class events. Encrypted
  reasoning state remains raw evidence, token accounting remains a specialized
  utilization input, and snapshots/turn context are not collapsed into chat
  messages. Selected scalar turn settings are normalized into
  `model_configurations`.
- **Compaction is directly stored.** Current local transcripts contain
  top-level `type=compacted` envelopes. Each envelope has a
  `replacement_history` containing one dedicated `type=compaction` item plus
  repeated ordinary message/context history, and is paired with an
  `event_msg.payload.type=context_compacted` notification. Codess emits one
  `context.compact` event from the dedicated item only; it does not duplicate
  replacement-history messages or emit the notification as a second event.
  Newer envelopes also expose window identifiers, which are preserved as
  metadata.
- Product behavior and storage shape are separate contracts. The official
  [`/compact` command](https://developers.openai.com/codex/developer-commands)
  summarizes the visible chat to free context; the
  [configuration reference](https://developers.openai.com/codex/config-reference)
  exposes `model_context_window`, `model_auto_compact_token_limit`, its
  `total|body_after_prefix` scope, and compact-prompt overrides. App-server
  exposes a `contextCompaction` item lifecycle. None of those public interfaces
  makes the local rollout JSONL shape stable: the
  [hooks documentation](https://developers.openai.com/codex/hooks) explicitly
  warns that transcript format may change.
- **`encrypted_content` is context-dependent.** On
  `response_item.payload.type=reasoning` it is per-turn reasoning state and is
  retained only as raw evidence. On the dedicated `type=compaction` item inside
  a `compacted` envelope it is the stored compact representation and is
  preserved as a bounded, vendor-encrypted context body. Field spelling alone
  is not enough to classify it.
- A valid transcript with no supported events removes its prior normalized
  session and is counted in the `empty_sources` diagnostic.

### 7.1 Parent-Session Evidence

Current Codex protocol source defines `parent_thread_id`, `forked_from_id`,
structured `thread_source`
and subagent source values, agent nickname/role/path, and collaboration events
for spawn, interaction, wait, close, resume, and activity. Codess maps direct
parent and fork fields into distinct Session relations and preserves the
remaining participant/source fields as bounded lineage metadata. Collaboration
records map to harness-origin system Events with their sender, receiver,
spawned-thread, prompt, model/effort, status, role/path, and timing evidence.
When a selected local Source does not contain these records, their validation
basis is the current protocol plus focused fixtures rather than a claim of
local occurrence. Codess never infers parentage
from timestamps, path proximity, archive location, or content.

### 7.2 Coverage Boundary and Complete-Transport Capture

The rollout is a durable harness-side event history, not a byte-for-byte model
request/response trace. It preserves user, harness, model-summary, tool,
compaction, lifecycle, settings, MCP, and some collaboration records that the
release elects to record. It does not expose server-hidden reasoning, and
encrypted reasoning bodies are not decoded. The model's active context can be
a compacted subset while the rollout retains the longer accumulated history.

Codex supports opt-in OpenTelemetry for request, streaming, turn, tool, and MCP
timing/usage observations, plus lifecycle hooks. A controlled proxy can also be
selected through the user-level `openai_base_url`. Neither is required for
ordinary Codess local-history ingest. Native telemetry is the preferred first
instrument because it carries harness semantics without copying prompt bodies
by default. A proxy is justified only for a study that requires exact outbound
request assembly, transport retries/stream frames, or otherwise unavailable
wire latency. Even then it does not reveal server-hidden reasoning and does not
capture local tool execution unless harness telemetry is collected too.

### 7.3 Configuration Evidence

`codess evidence audit codex-features` performs a bounded, structure-only
audit. Exact model and effort occur in `turn_context`; settings records can
contain an explicit service tier. No distinct speed-tier field is currently
mapped. Other fields
named `mode` mean sandbox policy or truncation units, so Codess maps only the
identified `collaboration_mode.mode` and records its exact field provenance.
Oversize bodies are counted, drained, and excluded from the structural audit.
