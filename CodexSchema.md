# CodexSchema — OpenAI Codex CLI session storage

Vendor-specific structure for **Codex CLI** sessions. Normalized ingest: `src/codess/adapters/codex.py`. Scan: `src/codess/scan.py` (`_session_metrics_codex`).

**Stability note:** Codex documents the transcript path, but the transcript
format is not a stable public interface and may change. The shapes below
describe the current tolerant Codess adapter and verified local fixtures, not a
compatibility guarantee from Codex.

---

## 1. Document metadata

| Field | Value |
|-------|--------|
| **Vendor** | OpenAI Codex CLI |
| **Primary paths** | Active: `~/.codex/sessions/**/*.jsonl`; archived: `~/.codex/archived_sessions/**/*.jsonl` |
| **Encoding** | UTF-8 JSONL |
| **Time basis** | `timestamp` on lines: numeric (s or ms) or ISO 8601 string |

---

## 2. Storage layout

| Pattern | Role |
|---------|------|
| Date-partitioned or flat tree of `*.jsonl` | **One file = one session** |
| `session_meta` record | Session identity, working directory, source, originator, provider, and CLI version |

Codess searches past blank or malformed prefix lines for `session_meta`.
Active and archived roots are both read by default. Setting
`CODESS_CODEX_SESSIONS` isolates active input and disables the default archive
root; set `CODESS_CODEX_ARCHIVED_SESSIONS` explicitly to add an archive root.
Codess does not currently infer Codex subagent parentage from transcripts.
If active and archived roots contain the same session id, the active transcript
wins; within one root the newest file wins. Re-ingest transactionally replaces
the selected session rather than leaving events removed from the transcript.

---

## 3. Recommended access

| Method | Use |
|--------|-----|
| **Codess scan** | `codess scan --dir <work>`; matches `session_meta.payload.cwd` to project |
| **Codess ingest** | `codess ingest --dir <project>`; collects files whose `cwd` resolves to project root |
| **Direct read** | Open file; locate `session_meta`, then stream records tolerantly |

---

## 4. session_meta (first line)

| Field path | Type | Notes |
|------------|------|--------|
| `type` | string | Must be `session_meta` |
| `payload.id` | string | Session id fallback |
| `payload.cwd` | string | Project directory; resolved and compared to scan path |
| `payload.cli_version` | string | Stored as normalized session release and metadata |
| `payload.model_provider`, `originator`, `source` | string | Retained as bounded session metadata; provider can seed a session-level configuration |
| `timestamp` | number or string | Session time for `--days` filter |

---

## 5. Subsequent lines (record types)

Ingest adapter primarily uses:

| `type` | Role |
|--------|------|
| `session_meta` | Supplies session identity/metadata; not emitted as an event |
| `response_item.message` | Canonical user and assistant messages |
| `response_item.reasoning.summary[].text` | Vendor-exposed reasoning summary retained as `message.reasoning_summary`; encrypted reasoning state is not decoded |
| `response_item.function_call` / `custom_tool_call` | Tool calls with sanitized JSON input and call-id metadata; structured failed/error/incomplete status becomes `tool_failure` |
| `response_item.web_search_call` | `web_search` tool call with sanitized action metadata |
| Matching call-output records | Tool results; call id restores the tool name |
| `compacted` | Replacement-history envelope; its dedicated `compaction` item becomes one bounded `context.compact` event |
| `event_msg.turn_aborted` | Retained as a `turn_aborted` assistant audit event |
| `event_msg.task_started` / `task_complete` | Retained as harness lifecycle events; completion text is not duplicated as another assistant response |
| `event_msg.context_compacted` | Notification paired with `compacted`; recognized but not emitted again |
| `event_msg.web_search_end` / `patch_apply_end` | Linked result/status evidence for the corresponding tool call when a call id is available |
| `turn_context` | Not emitted as conversation text. Exact `payload.model` and `payload.effort`/`reasoning_effort`, plus the specifically identified collaboration mode, are attached to subsequent normalized events with source-record/field provenance; observed `payload.turn_id` becomes vendor `model_turns.source_turn_id` |
| `event_msg.thread_settings_applied` | Newer bounded settings envelope. Exact model, provider, reasoning effort, service tier, approval policy, and collaboration mode update subsequent event/model-turn configuration |
| `response_item.message` with `developer` or `system` role | Bounded harness/context injection, not a human prompt |
| Duplicate `event_msg` message/reasoning notifications | Counted as known duplicate envelopes after the canonical `response_item` representation is retained |
| `event_msg.token_count` | Counted as a known usage observation and consumed by utilization reporting, not duplicated as conversation text |
| `response_item.ghost_snapshot` / `world_state` | Counted as known intermediate state, not conversation text |
| Unsupported record shapes | Counted as unknown ignored diagnostics and require review |

Record timestamps accept Unix seconds, Unix milliseconds, and ISO 8601. Tool
call/result lineage is stored in event metadata through `call_id`.
Every emitted event also retains `response_item`/`event_msg`, the payload type,
line locator, declared mapping rule, and structured trace. Configured active or
archive roots supply explicit session archive state and provenance; an archive
location is not interpreted as successful completion.

Malformed payload containers, tool inputs, timestamps, and configuration fields
are diagnosed at field scope and dropped independently. A malformed optional
field does not discard an otherwise supported record.

---

## 6. Scan metrics (Codess)

| Metric | Definition |
|--------|------------|
| **Sessions** | Count of `*.jsonl` files whose first line is `session_meta` and `cwd` matches project |
| **Events** | Count of non-empty lines per matching file (includes all record types on lines) |
| **Size (mb)** | Sum of `file.stat().st_size` for matching files |
| **days_ago** | From max `timestamp` among matching sessions (parsed to ms) |
| **span_weeks** | Spread of timestamps across matching files |

---

## 7. Quirks & limitations

- Timestamp formats mixed (Unix s, Unix ms, ISO); parser normalizes to ms where possible.
- “Events” in scan ≠ only chat messages; includes structural lines.
- History file `~/.codex/history.jsonl` (if present) is **not** the same as session store; CodexSchema applies to `sessions/`.
- Vendor-exposed reasoning summaries are first-class events. Encrypted
  reasoning state remains raw evidence, token accounting remains a specialized
  utilization input, and snapshots/turn context are not collapsed into chat
  messages. Selected scalar turn settings are normalized into
  `model_configurations`; see CoPlan rows **V-CTX1/E-2**.
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

### Parent-session evidence

The repeatable metadata-only audit in `tools/audit_codex_parentage.py` inspected
all 28 local active/archive transcripts spanning 16 CLI/Desktop releases. It
found no parent-like field and no resolvable parent reference; message,
reasoning, prompt, and tool bodies were not inspected. The evidence report is
`catalog/codex-parent-audit.json`. Codess therefore does not infer parentage
from timestamps, path proximity, archive location, or content. The authoritative
restart trigger is **CoPlan T4**.

### Configuration evidence

`python -m main evidence audit codex-features` performs a bounded,
structure-only audit. A local audit reviewed all 28 active/archive
transcripts (about 449 MiB) with a 64 KiB per-record ceiling. It found 8,107
`turn_context` records and 143 newer `thread_settings_applied` records. Exact
model and effort are widespread; the newer settings records contain an explicit
`service_tier=default`. No distinct speed-tier field was observed. Other fields
named `mode` mean sandbox policy or truncation units, so Codess maps only the
identified `collaboration_mode.mode` and records its exact field provenance.
Oversize bodies are counted, drained, and excluded from the structural audit.

---

## 8. Cross-reference

| Topic | Document |
|-------|----------|
| Unified DB columns | **CoSchema.md** |
| Claude Code storage | **CCSchema.md** |
| Cursor storage | **CursorSchema.md** |
| Implementation, tests, and work queue | **CoPlan.md** |
