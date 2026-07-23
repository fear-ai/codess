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
| `response_item.function_call` / `custom_tool_call` | Tool calls with sanitized JSON input and call-id metadata; structured failed/error/incomplete status becomes `tool_failure` |
| `response_item.web_search_call` | `web_search` tool call with sanitized action metadata |
| Matching call-output records | Tool results; call id restores the tool name |
| `event_msg.turn_aborted` | Retained as a `turn_aborted` assistant audit event |
| `turn_context` | Not emitted as conversation text. Exact `payload.model` and `payload.effort`/`reasoning_effort`, plus the specifically identified collaboration mode, are attached to subsequent normalized events with source-record/field provenance; observed `payload.turn_id` becomes vendor `model_turns.source_turn_id` |
| `event_msg.thread_settings_applied` | Newer bounded settings envelope. Exact model, provider, reasoning effort, service tier, approval policy, and collaboration mode update subsequent event/model-turn configuration |
| Other notifications, reasoning, token counts, and snapshots | Counted as ignored diagnostics, not duplicated as conversation events |

Record timestamps accept Unix seconds, Unix milliseconds, and ISO 8601. Tool
call/result lineage is stored in event metadata through `call_id`.
Every emitted event also retains `response_item`/`event_msg`, the payload type,
line locator, declared mapping rule, and structured trace. Configured active or
archive roots supply explicit session archive state and provenance; an archive
location is not interpreted as successful completion.

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
- Reasoning bodies, token accounting, snapshots, and turn context are not a
  first-class common runtime-context model. Selected scalar turn settings are
  nevertheless normalized into `model_configurations`; see CoPlan rows
  **V-CTX1/E-2**.
- **Compaction — no local record observed.** A structure-only scan of all 26
  local active/archive transcripts found **no `compaction` record** of any kind
  (`response_item` payload types present: reasoning, function_call,
  function_call_output, message, custom_tool_call(_output), ghost_snapshot,
  web_search_call, tool_search_call/output). Codex compaction is therefore either
  server-side only or uses a shape these releases do not emit. Codess emits no
  `context.compact` for Codex until a real record is observed (**T4**).
- **`encrypted_content` is not compaction.** It is the Fernet-encrypted
  (`gAAAAAB…`) reasoning trace carried on `payload.type=reasoning` items (19,353
  in the local corpus) so a reasoning model can restore its chain-of-thought
  across turns. It is routine per-turn state, retained only as raw evidence.
- Transcript compatibility must be maintained with fixtures because the
  [official hook guidance](https://developers.openai.com/codex/config-advanced#hooks)
  says the transcript format may change.
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
structure-only audit. The July 2026 local audit reviewed all 28 active/archive
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
