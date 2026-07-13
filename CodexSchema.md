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
| `payload.model_provider`, `originator`, `source` | string | Retained as bounded session metadata |
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
| Other notifications, reasoning, token counts, snapshots, and turn context | Counted as ignored diagnostics, not duplicated as conversation events |

Record timestamps accept Unix seconds, Unix milliseconds, and ISO 8601. Tool
call/result lineage is stored in event metadata through `call_id`.

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
- Reasoning bodies, token accounting, snapshots, and turn context are
  deliberately not normalized until they have a concrete query/audit use case.
- Transcript compatibility must be maintained with fixtures because the
  [official hook guidance](https://developers.openai.com/codex/config-advanced#hooks)
  says the transcript format may change.
- A valid transcript with no supported events removes its prior normalized
  session and is counted in the `empty_sources` diagnostic.

### Parent-session evidence

Current verified `session_meta` fixtures provide session id, working directory,
release/provider/origin fields, but no stable parent-session identifier. Codess
therefore does not infer parentage from timestamps, path proximity, active vs
archived location, or similar content. The evidence-gathering procedure and
acceptance criteria are in **CoPlan.md §11.1**.

---

## 8. Cross-reference

| Topic | Document |
|-------|----------|
| Unified DB columns | **CoSchema.md** |
| Claude Code storage | **CCSchema.md** |
| Cursor storage | **CursorSchema.md** |
| Implementation plan | **CoPlan.md** |
