# Session Record Methodology — Searchable Store for Model Behavior Analysis

Proposal for converting session records (Claude Code, Cursor, Codex) into a searchable store that supports standard and ad-hoc queries. Separates ingestion from indexing and querying.

---

## 1. Problem Statement

Session records in `~/.claude/projects/<slug>/*.jsonl` and similar locations (Cursor, Codex) are valuable for:
- Assessing model behaviors (tool choice, prompt adherence, error recovery)
- Individual and use-case utilization of tools and controls
- Cost estimation, compaction patterns, permission audits

They are hard to read (large JSONL, nested structures) and harder to interpret (schema varies by source, event types differ). Current tooling (`jsonl_names.py` in CContext) answers one question (tool invocation counts) but is tightly coupled to that query. Tool counts remain a valid use case; the store design supports many query types without privileging any single one.

---

## 2. Architecture — Three Layers

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   INGESTION     │     │    INDEXING     │     │     QUERY       │
│                 │     │                 │     │                 │
│ Read JSONL/     │────▶│ Normalize       │────▶│ SQL / FTS /     │
│ SQLite per      │     │ Build indices   │     │ ad-hoc scripts  │
│ source adapter  │     │ Incremental     │     │ Standard +      │
│                 │     │ update          │     │ custom queries  │
└─────────────────┘     └─────────────────┘     └─────────────────┘
        │                         │                         │
        ▼                         ▼                         ▼
   Raw sources             Normalized store            Query results
   (unchanged)             (SQLite)                    (tables, JSON,
                                                        exports)
```

**Separation principle:** Ingestion produces a normalized store. Indexing enriches it for fast access. Queries never touch raw sources. Schema changes require only ingestion-adapter updates, not query rewrites.

**Store design:** Project-local by default. Derive project from current directory or git repo root; store lives at `<project>/.coding-sess/sessions.db`. Artifacts:
- `coding-sessions-schema.sql` — table definitions
- `session-store-design.md` — store location, incremental logic, config (optional; can live in this doc)

**FTS5:** Postponed. Start with SQLite tables and B-tree indices; add full-text search later.

---

## 3. Source Schemas

### 3.1 Claude Code (CC)

**Source:** `Claude` | **Type:** `Code` | **Version:** `@anthropic-ai/claude-code` semver (e.g. `2.1.77`)

**Session-related locations under `~/.claude/`:**

| Path | Contents |
|------|----------|
| `projects/<slug>/*.jsonl` | Full conversation transcripts (one file per session, UUID filename) |
| `projects/<slug>/memory/` | MEMORY.md, summary.md — persistent project notes |
| `history.jsonl` | Global prompt log: display text, timestamp, project path, sessionId |
| `debug/<uuid>.txt` | Full session debug traces; `latest` symlink → active session |
| `file-history/<uuid>/` | Per-session file edit snapshots (before/after) |
| `session-env/` | Per-session environment snapshots |
| `shell-snapshots/` | Shell env captures (timestamped) |
| `plans/` | Plan-mode markdown files |
| `tasks/<uuid>/` | TodoWrite task state (numbered JSON) |
| `todos/` | Per-session todo persistence |

**Primary ingestion source:** `projects/<slug>/*.jsonl` — full transcripts. `history.jsonl` provides prompt-level index; `debug/`, `file-history/` enrich session context.

**Project slug:** Encoded absolute path (e.g. `-Users-walter-Work-Spank-spank-py`). Derive from current directory or repo root.

**Transcript envelope (per line):**
```json
{
  "message": {
    "role": "user" | "assistant",
    "content": [
      { "type": "text", "text": "..." },
      { "type": "tool_use", "id": "...", "name": "Read", "input": {...} },
      { "type": "tool_result", "tool_use_id": "...", "content": "..." }
    ]
  }
}
```

**Key fields:** `message.content[]` (text, tool_use, tool_result); tool names: Read, Write, Edit, Bash, TodoWrite, Grep, Glob, etc.

---

### 3.2 Cursor

**Source:** `Cursor` | **Type:** `IDE` | **Version:** `major.minor.release` (e.g. `0.40.3`); About Cursor / Help > About

**Locations:**
- **macOS:** `~/Library/Application Support/Cursor/User/globalStorage/state.vscdb`
- **Workspace:** `%APPDATA%\Cursor\User\workspaceStorage/<md5(workspace-path)>/state.vscdb` (Windows); analogous on macOS/Linux

**Format:** SQLite key-value store (VSCode `state.vscdb`). Keys: `composerData:<id>`, `bubbleId:<composerId>:<bubbleId>`, etc. Workspace mapping via `workspace.json`.

**Message structure (decoded JSON values):**
```json
{
  "type": 1,           // 1 = User, 2 = Assistant
  "text": "...",
  "codeBlocks": [...],
  "fileActions": [...],
  "toolResults": [...],
  "timingInfo": { "clientStartTime": "..." }
}
```

---

### 3.3 Codex (OpenAI)

**Source:** `Codex` | **Type:** `Code` | **Version:** `@openai/codex` semver (e.g. `0.115.0`); `codex --version`

**Locations:**
- Sessions: `~/.codex/sessions/YYYY/MM/DD/rollout-YYYY-MM-DDTHH-MM-SS-*.jsonl`
- History: `~/.codex/history.jsonl`

**Format:** JSONL, append-only. Event types: `thread.started`, `turn.started/completed/failed`, `item.started/completed` (agent_message, command_execution, file changes, MCP tool calls, plan updates), `error`.

**Config:** `~/.codex/config.toml` (global), `<project>/.codex/config.toml` (project). Codex `--ephemeral` sessions are not persisted.

---

## 4. Normalized Event Model

Records start with source and type. Timestamps as float (Unix ms, millisecond resolution).

### 4.1 Session record (leading fields)

| Field | Type | Description |
|-------|------|-------------|
| `source` | string | Product: `Claude`, `Cursor`, `Codex` |
| `type` | string | Category: `Code`, `IDE` |
| `release` | string | Vendor version (e.g. `2.1.77`, `0.115.0`) |
| `release_value` | integer | Comparable: `major*256 + minor*16 + build` |
| `started_at` | float | Log start: Unix ms |
| `ended_at` | float | Log end: Unix ms |
| `session_id` | string | Canonical session ID |
| `project_path` | string | Workspace/project path |

### 4.2 Event fields

| Field | Type | Description |
|-------|------|-------------|
| `event_id` | string | Unique within session |
| `event_type` | enum | `user_message`, `assistant_message`, `tool_call`, `tool_result`, `file_change`, `plan_update`, `error`, ... |
| `subtype` | string | Finer grain: `prompt`, `slash_command`, `response`, `dialog`, `permission_denied`, `truncated`, etc. |
| `role` | enum | `user`, `assistant`, `system` |
| `content` | string | Text content |
| `tool_name` | string | For tool events |
| `tool_input` | object | Tool arguments |
| `tool_output` | string | Tool result (truncatable) |
| `timestamp` | float | Unix ms |
| `file_path` | string | For Read/Edit/Write events |
| `metadata` | object | Source-specific extras |
| `source_file` | string | Raw source path (e.g. `~/.claude/projects/<slug>/<uuid>.jsonl`) |
| `content_len` | integer | Actual content length; stored for truncated fields to enable later full fetch |
| `content_ref` | object | Optional fetch reference: `{path, byte_offset?, line?, length}` or `{sidecar_file}`. Byte for file reads; line for interpreters. |

---

## 4.3 Event Taxonomy — Communication Types

### Types captured

| Type | Role | Distinguisher | Disposal |
|------|------|---------------|----------|
| **Prompt** | user | `content.type=text`, no preceding tool_result | Keep; core query surface |
| **Slash command** | user | `content.type=text`, text starts with `/` | Keep; tag `subtype=slash_command` |
| **Tool result** | user | `content.type=tool_result` | Truncate; keep `is_error`, tool_use_id, summary; optional `content_ref` |
| **Approval interaction** | user | `content.type=tool_result`, `is_error=true` for denied | Keep; tag `subtype=permission_denied`; see §4.4 |
| **Response** | assistant | `content.type=text`, no following tool_use in same record | Truncate 1000 chars; store `content_len`; optional `content_ref` |
| **Dialog** | assistant | `content.type=text`, tool_use follows in same record | Truncate 200 chars; store `content_len`; optional `content_ref` |
| **Processing steps** | assistant | Mid-stream text, `progress` records | Drop; see §4.5 (redundant) |
| **Aborted gibberish** | assistant | Truncated output; `stop_reason=max_tokens` or similar | Keep with `subtype=truncated`; flag for analysis |
| **Tool call** | assistant | `content.type=tool_use` | Keep; see §4.6 (tool call elements) |
| **File edit** | assistant | tool_use name=Edit/Write; tool_result confirms | Keep path, len; optionally sidecar; `content_ref` to sidecar |

### Eventual (not yet modeled)

| Type | Source | Notes |
|------|--------|------|
| **Plans** | `~/.claude/plans/` | Plan-mode markdown; link by session or plan id |
| **Agents** | Agent tool_use, agent_return | Subagent delegation; extract prompt, summary, usage |
| **Task lists** | `~/.claude/tasks/<uuid>/`, TodoWrite tool | TodoWrite state; numbered JSON |
| **Thinking blocks** | Some models (not in CC JSONL yet) | Extended reasoning; optional; truncate when available |

### Not captured (gaps)

| Gap | Reason |
|-----|--------|
| **System reminders** | Injected mid-conversation; not in JSONL transcript |
| **Compaction** | Summary replaces history; raw turn sequence lost in next session |
| **Streaming partials** | `progress` records; 1000+ per session; redundant with final assistant record (§4.5) |
| **Rejected tool calls** | User denied; surfaced via tool_result `is_error` |
| **IDE context** | Cursor/Codex: file selections, cursor position, open tabs |
| **Token/usage** | Present in assistant `message.usage`; not in all sources |
| **MCP tool calls** | May differ in structure from built-in tools |
| **Thinking blocks** | Extended reasoning; some models emit; not in CC JSONL yet. Interesting; optional + truncated when available |

---

## 4.4 Approval and Tool Call Information Elements

### Approval interaction (permission_denied)

| Element | Source | Description |
|---------|--------|-------------|
| `tool_use_id` | tool_result.tool_use_id | Which tool call was denied |
| `tool_name` | From paired tool_use | Tool that triggered approval |
| `is_error` | tool_result.is_error | `true` for denied |
| `decision` | Inferred | `user_deny`, `system_deny`, `timeout` |
| `timestamp` | Record timestamp | When user responded |
| `prompt_preview` | Optional | First 200 chars of approval dialog if captured |

### Tool call elements (per tool)

| Tool | Keep | Optional / sidecar |
|------|-----|---------------------|
| **Bash** | `command` (full, strip ANSI) | — |
| **Read** | `file_path`, `offset`, `limit` | — |
| **Edit** | `file_path`, `old_len`, `new_len` | `content_ref` → `<session>_<tool_id>_edit.txt` |
| **Write** | `file_path`, `content_len` | `content_ref` → `<session>_<tool_id>_write.txt` |
| **Grep** | `pattern` (trunc 120), `path`, `output_mode`, `glob` | — |
| **Glob** | `pattern`, `path` | — |
| **Agent** | `subagent_type`, `description`, prompt first 200 chars | `content_ref` → `<session>_<tool_id>_agent.txt` |
| **Skill** | `skill`, `args` | — |

---

## 4.5 Why Processing Steps Are Redundant

**Raw CC record types:** `user`, `assistant`, `progress`, `file-history-snapshot`, `queue-operation`, `last-prompt`, `system`.

**`progress` records** (~60% of lines): Streaming frames emitted as the model generates output. Each frame is a partial assistant turn — text or tool_use mid-stream. The *final* `assistant` record in the same turn contains the complete content: full text, all tool_use blocks, final token counts. Intermediate `progress` records add no information not already in that final record. Dropping them reduces volume (e.g. 1056 → 0 for that turn) without losing analytical content.

**`file-history-snapshot`**: Pre-edit file state for undo. Schema is separate from conversation; useful for audit but not for turn-level tracing. Optional: archive to sidecar zip; reference via `content_ref`.

**`queue-operation`, `last-prompt`, empty `system`**: Infrastructure bookkeeping; no user or model content.

---

## 4.6 JSONL Output Structure and Naming

### Normalized event types (our schema)

| event_type | subtype | Raw CC type | Notes |
|------------|---------|-------------|-------|
| `user_message` | `prompt` | user | content.type=text |
| `user_message` | `slash_command` | user | content.type=text, starts with `/` |
| `user_message` | `tool_result` | user | content.type=tool_result |
| `user_message` | `permission_denied` | user | tool_result, is_error=true |
| `assistant_message` | `response` | assistant | text, no following tool_use |
| `assistant_message` | `dialog` | assistant | text, tool_use follows |
| `assistant_message` | `truncated` | assistant | stop_reason indicates truncation |
| `assistant_message` | (none) | assistant | mixed content |
| `tool_call` | (none) | assistant | content.type=tool_use |
| `tool_result` | (none) | user | content.type=tool_result |

### Types not covered (raw CC → our mapping)

| Raw type | Action | Reason |
|----------|--------|--------|
| `progress` | Drop | Redundant; see §4.5 |
| `file-history-snapshot` | Optional archive | Separate schema; sidecar |
| `queue-operation` | Drop | No content |
| `last-prompt` | Drop | Null/infra |
| `system` | Drop (or keep `subtype=system_cmd` if slash execution) | Usually empty; slash execution may have content |

### NDJSON line structure (per event)

```json
{"event_type":"user_message","subtype":"prompt","role":"user","content":"...","content_len":45,"source_file":"~/.claude/projects/-Users-walter-Work-Spank-spank-py/abc123.jsonl","timestamp":1710000000123.456,"session_id":"abc123",...}
{"event_type":"assistant_message","subtype":"response","role":"assistant","content":"...truncated...","content_len":2847,"content_ref":{"path":"~/.claude/projects/.../abc123.jsonl","offset":12345,"length":2847},"source_file":"...","timestamp":...}
{"event_type":"tool_call","tool_name":"Bash","tool_input":{"command":"ls -la"},"source_file":"...","timestamp":...}
```

---

## 4.7 Content Sanitization

User- and model-generated content can contain material that breaks parsing, leaks secrets, or confuses downstream tools. Sanitization is **optional** (configurable); apply per content type.

### Types and reasons

| Content type | Risk | Sanitization |
|--------------|------|--------------|
| **Prompt** | Secrets, PII, control chars | Strip control chars; optional redact patterns (API keys, paths) |
| **Response / Dialog** | Same as prompt; embedded JSON strings | Strip ANSI; optional redact; decode JSON-escaped strings |
| **Bash command** | Secrets in env vars, paths | Optional redact; strip ANSI |
| **Tool result (Read)** | File contents, secrets | Truncate or drop; never store full file |
| **Tool result (Bash)** | Command output, secrets | Truncate; strip ANSI; optional redact |
| **Edit/Write input** | Code, secrets | Sidecar only; optional redact before write |
| **Agent prompt** | Delegation context, may include paths | Optional redact |

### Optionality

- **Default:** Strip control chars (0x00–0x1F, 0x7F), ANSI escapes, normalize `\r` → `\n`. No redaction.
- **`--redact`:** Apply configured patterns (API keys, tokens, `.env` values). Replace with `[REDACTED]`.
- **`--no-sanitize`:** Raw content; use only for trusted/local analysis.
- **Per-field:** Prompt and Bash command often need different rules than tool results.

---

## 4.8 Disposal Rules (Summary)

- **Drop:** `progress`, `file-history-snapshot`, `queue-operation`, `last-prompt`, empty system
- **Truncate:** response (1000 chars), dialog (200 chars), tool_result (summary); store `content_len`; optional `content_ref` for fetch
- **Sidecar:** Edit old/new, Agent prompt, Write content — `content_ref` to filename
- **Keep full:** Bash command, prompt text, tool name + key input fields

---

## 4.9 Dropped/Skipped Types and Fields — For Later Reexamination

Record types and fields we intentionally omit. Documented so the decision can be revisited when requirements change.

### Record types (dropped)

| Type | Volume (typical) | Explanation | Reexamine when |
|------|------------------|-------------|----------------|
| **progress** | ~60% of lines | Streaming partials; final `assistant` record contains complete content. No analytical value beyond the completed turn. | Need streaming latency analysis, token-by-token timing, or partial-output debugging. Would require schema for `progress` subtypes and turn correlation. |
| **file-history-snapshot** | ~66/session | Pre-edit file state for undo. Schema: `trackedFileBackups` with path and content. Separate from conversation flow. | Need undo/audit trail, diff-from-before-edit, or file-state forensics. Would require sidecar storage and schema for snapshot format. |
| **queue-operation** | ~10/session | Enqueue/dequeue for request queue. Infrastructure only. | Need queue-depth or latency analysis. Schema unknown; would need to dump and inspect. |
| **last-prompt** | ~4/session | Pointers to last prompt; often null uuid/timestamp. Purpose unclear. | Need to understand CC internals for session resumption or prompt replay. Would need reverse-engineering. |
| **system** | ~39/session | Slash command executions, heartbeats, null records. Usually empty content. | Need slash-command audit or execution trace. Some records may have content; would need to sample and classify. |

### Record types (conditionally dropped)

| Type | Condition | Explanation | Reexamine when |
|------|-----------|-------------|----------------|
| **system** | Empty content | Dropped. | If non-empty `system` records found with useful content (e.g. slash execution details), add `subtype=system_cmd` and ingest. |

### Fields (truncated or skipped)

| Field | Location | Explanation | Reexamine when |
|-------|----------|-------------|----------------|
| **content** (response) | assistant text | Truncated to 1000 chars. Full length in `content_len`; `content_ref` can point to source for fetch. | Need full response search, long-form analysis, or training data extraction. Increase truncation or add full-content mode. |
| **content** (dialog) | assistant text | Truncated to 200 chars. Same as above. | Need full reasoning-chain analysis. |
| **content** (tool_result) | user tool_result | Truncated to summary. Read results: drop file content; Bash results: first N chars. | Need full tool output for debugging, or Read-result search. Use `content_ref` to raw JSONL offset. |
| **old_string / new_string** | Edit tool_input | Not stored inline. Sidecar only via `content_ref`. | Need inline diff view or code-change search. Add sidecar write by default. |
| **content** (Write) | Write tool_input | Same. | Same. |
| **prompt** (Agent) | Agent tool_input | First 200 chars kept; full in sidecar. | Need subagent delegation analysis. Add sidecar by default. |
| **message.stop_reason** | assistant | Not in normalized schema. | Need truncation/stop analysis (max_tokens, end_turn, etc.). Add to metadata. |
| **message.usage** (cache fields) | assistant | `cache_read_input_tokens`, `cache_creation_input_tokens` — not always extracted. | Need cache efficiency or cost analysis. Add usage fields to schema. |
| **Grep context params** | Grep tool_input | -A/-B/-C dropped from compact output. | Need grep-pattern analysis. Add to tool_input. |

### Fields (never captured)

| Field | Source | Explanation | Reexamine when |
|-------|--------|-------------|----------------|
| **System reminders** | CC runtime | Injected mid-conversation; not in JSONL. | Not in source; would require CC modification or telemetry hook. |
| **Compaction summary** | CC runtime | Replaces history at boundary; not in same file as raw turns. | Need post-compaction context. May exist in next session's system prompt; would need different extraction. |
| **IDE context** | Cursor/Codex | Selections, cursor position, open tabs. | Need IDE-integration analysis. Schema and location TBD per product. |
| **Thinking blocks** | Some models | Extended reasoning; not in CC JSONL yet. **Interesting** — optional ingest when available; truncate (e.g. 500 chars); store `content_len`, `content_ref`. | If CC adds thinking to JSONL; add `subtype=thinking`; schema TBD. |

### How to reexamine

1. **Sampling:** Run `jq -r '.type' file.jsonl | sort | uniq -c` on representative sessions to confirm type distribution.
2. **Field dump:** For a dropped type, dump one full record: `jq 'select(.type=="progress") | .' file.jsonl | head -1`.
3. **Volume check:** Count bytes/lines for each type; assess storage impact of ingesting.
4. **Schema draft:** Add optional fields or sidecar format; gate behind config flag.

---

## 4.10 Include, Truncate, Sanitize, Skip — Decision Matrix

Consolidated reference for all field- and type-level decisions. See §4.3–4.9 for rationale.

### Record types

| Raw type | Decision | Truncate | Sanitize |
|----------|----------|----------|----------|
| `user` | Include | — | Optional redact |
| `assistant` | Include | response 1000, dialog 200 | Strip control chars, ANSI; optional redact |
| `progress` | Skip | — | — |
| `file-history-snapshot` | Skip (optional archive) | — | — |
| `queue-operation` | Skip | — | — |
| `last-prompt` | Skip | — | — |
| `system` | Skip (or include if non-empty) | — | — |

### Content blocks (user)

| Block | Decision | Truncate | Sanitize |
|-------|----------|----------|----------|
| `content.type=text` (prompt) | Include | — | Strip control chars; optional redact |
| `content.type=text` (slash) | Include | — | Same |
| `content.type=tool_result` | Include | Summary; drop Read file content | Strip ANSI; optional redact |
| `content.type=tool_result` (denied) | Include | — | Same |

### Content blocks (assistant)

| Block | Decision | Truncate | Sanitize |
|-------|----------|----------|----------|
| `content.type=text` (response) | Include | 1000 chars; `content_len` | Strip control chars, ANSI; optional redact |
| `content.type=text` (dialog) | Include | 200 chars; `content_len` | Same |
| `content.type=tool_use` | Include | Per-tool (Grep pattern 120) | Bash: strip ANSI |
| `content.type=thinking` | Optional (when available) | 500 chars | Same as text |

### Tool-specific fields

| Tool | Include | Truncate | Sidecar |
|------|---------|----------|---------|
| Bash | command | — | — |
| Read | path, offset, limit | — | — |
| Edit | path, old_len, new_len | — | old/new strings |
| Write | path, content_len | — | content |
| Grep | pattern (120), path, output_mode, glob | pattern 120 | — |
| Glob | pattern, path | — | — |
| Agent | subagent_type, description, prompt 200 | prompt 200 | full prompt |
| Skill | skill, args | — | — |

### Sanitization (optional)

| Content | Default | `--redact` | `--no-sanitize` |
|---------|---------|------------|-----------------|
| All | Strip control chars, ANSI, `\r`→`\n` | + pattern redaction | Raw |
| Prompt, response, dialog | — | API keys, tokens, paths | — |
| Bash command | Strip ANSI | + env vars, paths | — |
| Tool results | Truncate | + redact | — |

---

## 4.11 Auxiliary Sources — Documented, Postponed

Sources under `~/.claude/` that could enrich session analysis. **Not in scope for Phase 1.** Documented for later analysis and implementation.

| Source | Path | Contents | Potential value |
|--------|------|----------|-----------------|
| **MEMORY.md** | `projects/<slug>/memory/MEMORY.md` | Persistent project notes; auto-updated by CC | Project context across sessions; what the model "remembers"; semantic organization by topic |
| **summary.md** | `projects/<slug>/memory/summary.md` | Session notes; `data-session-memory-template` format | Per-session state, worklog, errors; lifecycle points |
| **history.jsonl** | `~/.claude/history.jsonl` | Global prompt log: display text, timestamp, project, sessionId | Cross-session prompt index; prompt frequency; project attribution without opening transcripts |
| **debug/<uuid>.txt** | `~/.claude/debug/<uuid>.txt` | Full session debug trace; `latest` symlink | Real-time activity; tool execution details; multi-MB per session |
| **file-history/<uuid>/** | `~/.claude/file-history/<uuid>/` | Pre-edit file snapshots | Undo trail; diff-from-before; file-state forensics |

**Postponed:** Schema design, ingestion adapters, storage format, and indexing for these sources are deferred. Revisit when:
- Transcript ingestion is stable and queried
- Use cases emerge (e.g. MEMORY evolution analysis, prompt history search, debug trace correlation)
- Storage and performance impact is assessed

---

## 5. Ingestion Layer

### 5.1 Responsibilities

- Discover session files (scan `~/.claude/projects/`, Cursor dirs, Codex dirs)
- Parse JSONL line-by-line or SQLite key-value (streaming for large files)
- Extract events per source schema
- Normalize to common internal representation
- Write to store (append/upsert by session_id + event_id)
- Support incremental runs (only process new or modified files)

### 5.2 Adapter Approaches

| Source | Approach |
|--------|----------|
| CC | Line-by-line JSONL; extract `message.content` blocks. Reuse `jsonl_names.py` patterns. |
| Cursor | SQLite `SELECT key, value FROM cursorDiskKV WHERE key LIKE 'composerData:%'`; JSON decode values; resolve workspace hash → path via `workspace.json`. |
| Codex | Line-by-line JSONL; map `type`/`item` to normalized events. Handle `rollout-*` and `history.jsonl`. |

### 5.3 Output Format

**Recommendation:** SQLite for primary store (portable, queryable, FTS5). Optional Parquet export for archival or bulk analytics.

---

## 6. Index Schema (SQLite)

See `coding-sessions-schema.sql`. Summary:

```sql
CREATE TABLE sessions (
  id TEXT PRIMARY KEY,
  source TEXT NOT NULL,
  type TEXT NOT NULL,
  release TEXT,
  release_value INTEGER,
  started_at REAL NOT NULL,
  ended_at REAL,
  project_path TEXT,
  metadata TEXT
);

CREATE TABLE events (
  id INTEGER PRIMARY KEY,
  session_id TEXT REFERENCES sessions(id),
  event_id TEXT,
  event_type TEXT,
  role TEXT,
  content TEXT,
  tool_name TEXT,
  tool_input TEXT,
  tool_output TEXT,
  timestamp REAL,
  file_path TEXT,
  metadata TEXT,
  source_raw TEXT
);
-- FTS5 postponed; add when full-text search is needed
```

**Token/usage (Q8):** Store what's readily available (e.g. assistant `message.usage`). No estimation yet; if needed, tokens ≈ 1.3 × words (literature).

### 6.1 Derived Tables (Materialized Views)

| Table | Contents |
|-------|----------|
| `session_summary` | session_id, project_path, event_count, tool_call_count, first_ts, last_ts, size_bytes |
| `tool_counts` | session_id, tool_name, count |
| `permission_events` | session_id, tool_name, decision, timestamp |

---

## 7. Indexing Layer

- B-tree indices on `session_id`, `timestamp`, `tool_name`, `project_path`
- Incremental: track `(file path, mtime)`; skip unchanged; append new events
- FTS5 and embedding index: postponed

---

## 8. Query Layer

### 8.1 Standard Queries

| Query | Implementation |
|-------|----------------|
| Tool invocation counts | `SELECT tool_name, COUNT(*) FROM events WHERE event_type='tool_call' GROUP BY tool_name` |
| Session list | `SELECT * FROM session_summary ORDER BY last_ts DESC` |
| Sessions by project | `WHERE project_path LIKE '%spank%'` |
| Permission audit | `WHERE event_type='permission'` |
| Compaction events | `WHERE event_type='compact' OR content LIKE '%compaction%'` |
| Prompt/response search | `WHERE content LIKE '%...%'` (FTS5 when added) |

### 8.2 Ad-Hoc

- CLI: `session-query --tool-counts`, `--search "git commit"`, `--project spank --since 2026-03-01`
- Query templates: parameterized SQL

---

## 9. Implementation Phases

### Phase 1 — Ingestion + SQLite (Claude Code only)

1. Adapter for `~/.claude/projects/<slug>/*.jsonl`
2. Normalize to `events` table
3. Project-local store: `<project>/.coding-sess/sessions.db`; derive project from cwd or git repo root
4. CLI: `session-ingest` (scans slug matching current project)
5. Standard queries: sessions list, tool counts, permission audit (tool counts is one of many)

### Phase 2 — Indexing + Standard Queries

1. `session_summary`, `tool_counts` derived tables
2. CLI: `session-query --sessions`, `--tool-counts`, `--permissions`
3. FTS5: postponed

### Phase 3 — Multi-Source

1. Cursor adapter (SQLite extraction)
2. Codex adapter (JSONL)
3. Unified store with `source` column
4. Cross-source queries

### Phase 4 — Ad-Hoc + Interpretation

1. Query template config
2. Result formatters, annotation hints
3. Optional: embedding index

---

## 10. Techniques

- **Streaming:** Parse JSONL line-by-line; do not load entire file into memory
- **Content truncation:** Truncate tool results (e.g. first 2KB). Keep `tool_input` (usually small)
- **Idempotent ingestion:** `INSERT OR REPLACE` keyed by (session_id, event_id)
- **Redaction:** Default patterns for API keys, tokens, `.env`; configurable per project

---

## 11. Relation to jsonl_names.py

`jsonl_names.py` (in CContext) is a single-query tool: tool counts per project. It was a specific request and remains valid. Under this methodology:

- **Ingestion:** Replaced by `session-ingest` writing to the store
- **Query:** `session-query --tool-counts` is one of several query modes; same store supports sessions list, permission audit, compaction analysis, etc.
- **Benefit:** Unified data; tool counts do not drive the architecture

`jsonl_names.py` can remain as a lightweight standalone for users who only need counts and don't want a store.

---

## 12. Plan Reference

Requirements, design specification, implementation, and validation plan are in **[CSPlan.md](CSPlan.md)**.

---

## 13. Pre-Implementation: Questions, Decisions, Known Gaps

### 13.1 Open Questions (resolve before or during Phase 1)

| # | Question | Resolution |
|---|----------|------------|
| Q1 | **event_id format** | Composite (line + content hash) not unique enough — exact file copy can duplicate. **DB help:** Use DB-generated id for events table; (session_id, line, content_hash) as business key for idempotent upsert. Or (session_id, source_file, line) if line is stable within a file. Will adjust after Cursor/Codex. |
| Q2 | **Project derivation** | **Try git** (e.g. `git rev-parse --show-toplevel`). If failing, look online and in tool documentation. **Project definitions:** Cursor (like VSCode) has Open directory, Open file, Open workspace, or more. Document how each tool defines "project" for storage paths. |
| Q3 | **Slug ↔ path mapping** | **Propose:** Borrow or lift from CC (path → dash-encoded slug). Will adjust after Cursor/Codex. |
| Q4 | **started_at / ended_at** | Prefer first/last event `timestamp` from records when available. Fallback: file create and last-modify times (Linux `stat`). |
| Q5 | **release / release_value** | Version printed at session start or after compact? Stick in `release` as fallback. **Assure incremental processing** of logs and directories. |
| Q6 | **content_ref offset** | **Both.** File reads want byte offset; interpreters (line-by-line) want line number. Store both when feasible. |
| Q7 | **Sidecar default** | **Off.** Undefined yet; no reason to archive what we can re-extract from source. |
| Q8 | **Token/usage** | Use what's **readily available** in source (e.g. assistant `message.usage`). No need to estimate yet. If needed later: literature suggests tokens ≈ 1.3 × words. |
| Q9 | **Incremental (mtime vs hash)** | **Timestamps in sources?** CC JSONL has `timestamp` per record; history.jsonl has `timestamp`. Use first/last event timestamps when available for started_at/ended_at. For "file changed" detection: mtime if timestamps not in sources; else hash when mtime unreliable (copy-restore, git, NFS). |
| Q10 | **source_raw** | For **decoder debug:** store raw binary (first 512 bytes) with valid size. **Inform DB** (BLOB type); do not apply string operations. No indiscriminate extraction or un-sanitized passing/printing. Only after sanitized and terminating null assured may it be treated as string. |

### 13.2 Decisions (locked for Phase 1)

| Decision | Choice |
|----------|--------|
| Store location | Project-local: `<project>/.coding-sess/sessions.db` |
| Primary source | `~/.claude/projects/<slug>/*.jsonl` only |
| Project scope | Git repo root (coding tools know where to put .files) |
| FTS5 | Postponed |
| Sidecar (Edit/Write/Agent) | Off by default; no archive of re-extractable content |
| Sanitization | Default: control chars + ANSI; redact optional |
| Truncation | Response 1000, dialog 200; store `content_len` |
| Dropped types | progress, file-history-snapshot, queue-operation, last-prompt, system (when empty) |
| Auxiliary sources | MEMORY.md, summary.md, history.jsonl, debug/, file-history/ — postponed |
| content_ref | Both byte offset and line number when feasible |
| source_raw | Decoder debug: BLOB, first 512 bytes; no string ops until sanitized and null-terminated |
| Incremental | mtime default; hash optional when mtime unreliable |

### 13.3 Known Gaps (accept for Phase 1)

| Gap | Mitigation |
|-----|------------|
| **Schema drift** | Challenge for every DB. CC, Cursor, Codex may change record types or fields; adapter may need updates. Sample before ingest; version adapter. |
| **Multi-turn assistant records** | Single assistant turn can produce multiple streaming records; final has full content. Rely on final; correlation TBD. |
| **tool_use_id pairing** | tool_result references tool_use by id; pairing needed for permission_denied. May need two-pass or in-memory lookup. tool_use blocks are in assistant content array; tool_result in user content — correlate by id. |
| **Cursor/Codex** | Phase 1 is CC only. Will return to Cursor and Codex shortly. |
| **Skills, plugins, MCP, Agents, Tasks** | Will revisit all options and extensions. |
| **MCP tools** | Structure may differ from built-in; treat as generic tool_call for now. |
| **Empty user content** | Synthetic turn-boundary records with empty `message.content`; skip or emit minimal event. |
| **Grep/Glob tool_input** | Some tools have variable schemas; extract known fields; put rest in metadata. |
| **Cursor workspace hash** | MD5 of path; algorithm may change. Fallback to "unknown" project_path. |
| **Codex session ↔ project** | Codex sessions are date-dir; project association may require cwd in session file. |

### 13.4 Validation Before Starting

1. **Sample a CC session:** `jq -r '.type' ~/.claude/projects/*/<uuid>.jsonl | sort | uniq -c` — confirm type distribution.
2. **Inspect one user, one assistant:** Dump structure; verify `message.content` array and block types.
3. **Check slug encoding:** List `~/.claude/projects/`; derive path from one slug; verify round-trip.
4. **Git root:** `git rev-parse --show-toplevel` from cwd; confirm behavior outside repo.

---

## 14. References

### Cursor
- [Cursor CLI](https://cursor.com/en/cli)
- [legel: Cursor chat export (SQLite)](https://gist.github.com/legel/ebd0bbc012bf019a1db5212b825e7d16)
- [cursor-chat-browser](https://github.com/thomas-pedersen/cursor-chat-browser)
- [Cursor forum: chat history folder](https://forum.cursor.com/t/chat-history-folder/7653/2)
- [Cursor version / upgrade](https://forum.cursor.com/t/how-do-i-upgrade-and-find-out-the-current-version/15326)

### Codex
- [Codex CLI (openai/codex)](https://github.com/openai/codex)
- [Codex releases](https://github.com/openai/codex/releases)
- [Codex changelog](https://developers.openai.com/codex/changelog)
- [Codex CLI reference](https://developers.openai.com/codex/cli/reference)
- [Codex config reference](https://developers.openai.com/codex/config-reference)
- [Codex config locations (inventivehq)](https://inventivehq.com/knowledge-base/openai/where-configuration-files-are-stored)
- [Codex non-interactive / exec](https://developers.openai.com/codex/noninteractive/)
- [Codex transcript feature #2765](https://github.com/openai/codex/issues/2765)

### Claude Code
- [@anthropic-ai/claude-code (npm)](https://www.npmjs.com/package/@anthropic-ai/claude-code)
- [Inside ~/.claude: filesystem architecture](https://www.diljitpr.net/blog-post-2026-02-24-inside-dot-claude-filesystem-architecture.html)
- [~/.claude directory logic (gist)](https://gist.github.com/samkeen/dc6a9771a78d1ecee7eb9ec1307f1b52)
- [claude-code-system-prompts](https://github.com/Piebald-AI/claude-code-system-prompts) — session memory template, session search assistant, session facets extraction
