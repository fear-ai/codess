# Coding Sessions Plan — Requirements, Design, Implementation, Validation

**Purpose:** Requirements, design, implementation, validation — what builders need.

---

## Implementation Status (Current)

| Feature | Status |
|---------|--------|
| CC ingest | Done |
| Incremental (mtime) | Done |
| 20 KB min file size | Done (`--min-size`, config) |
| Ingest stats (added + overall) | Done |
| `--tool-counts` | Done (legacy) |
| `--tool N` | Done (N=0 all, N=1 most recent; table with session columns) |
| `--sessions --id` | Done (numbered, most recent first) |
| `-sess N --show pr\|prompt\|agent\|tool\|perm` | Done |
| `--stats`, `--taxonomy` | Done |
| `--task-review` | Done (Task/Web tool counts, Task descriptions, outcomes) |
| `--permissions` | Done |
| Codex adapter | Done |
| Cursor adapter | Done |

**Event glossary:** `tool_call`; `user_message` (prompt, slash_command, tool_result, permission_denied); `assistant_message` (response, dialog, truncated). See [§2.5](#25-record-processing-specification) for type mapping.

---

## 1. Requirements

### 1.1 Functional Requirements

| ID | Requirement | Priority | Acceptance Criteria | Edge Cases |
|----|-------------|----------|---------------------|------------|
| R1 | Ingest CC JSONL from `~/.claude/projects/<slug>/*.jsonl` | P0 | All user/assistant records normalized; progress, file-history-snapshot, queue-operation, last-prompt, system skipped | Empty files; malformed lines; mixed encodings; symlinked project dirs |
| R2 | Ingest Cursor SQLite from platform-specific paths | P0 | Deferred Phase 3 | — |
| R3 | Ingest Codex JSONL from `~/.codex/sessions/**` and `history.jsonl` | P0 | Deferred Phase 3 | — |
| R4 | Normalize to unified event model | P0 | All events conform to schema; event_type, subtype, role, content, tool_name, tool_input, tool_output, timestamp populated per [§2.2](#22-schema-specification) | Multi-block content; tool_use_id pairing for permission_denied |
| R5 | Full-text search over session content | P0 | FTS5 postponed; use LIKE for Phase 1 | — |
| R6 | Redaction of secrets before indexing | P1 | Optional `--redact`; configurable regex patterns; replace with `[REDACTED]` | Patterns must not match false positives (e.g. short hex strings) |
| R7 | Export transcript to Markdown | P1 | Deferred | — |
| R8 | Config for paths, redaction patterns, index location | P1 | Config file or env; override CLI args | Missing config: use defaults; invalid config: fail fast |
| R9 | Project-local store at `<project>/.coding-sess/sessions.db` | P0 | Store created under git root; `.coding-sess/` created if missing | Non-writable dir: fail with clear error |
| R10 | Derive project from git repo root | P0 | `git rev-parse --show-toplevel`; fallback to cwd if not in repo | Outside repo: use cwd; git not installed: fail or fallback |
| R11 | Incremental ingestion (skip unchanged files) | P0 | Track (source_file, mtime); skip when unchanged; `--force` overrides | mtime resolution varies by FS; copy-restore may not change mtime |
| R12 | Idempotent upsert by (session_id, event_id) | P0 | Re-run produces identical store state; no duplicate (session_id, event_id) | Deleted source file: existing rows remain (no purge by default) |
| R13 | CLI `session-ingest` | P0 | Discovers `~/.claude/projects/<slug>/` for current project; globs `*.jsonl`; ingests each | No slug match: exit 1 with message; no jsonl files: success, 0 ingested |
| R14 | CLI `session-query` with --tool-counts, --sessions, --permissions | P0 | --tool-counts output matches jsonl_names.py for same project | Empty store: empty output, exit 0 |
| R15 | source_raw BLOB for decoder debug (first 512 bytes) | P2 | Stored when `--debug`; no string ops until sanitized; BLOB only | Invalid UTF-8: replace with replacement char before store |

### 1.2 Non-Functional Requirements

| ID | Requirement | Rationale |
|----|-------------|------------|
| NF1 | Stream JSONL line-by-line; do not load entire file into memory | Sessions can be 10MB+; avoid OOM |
| NF2 | Sanitize before display: control chars, ANSI; no un-sanitized passing of source_raw | Security; avoid terminal injection |
| NF3 | Adapter versioned for schema drift; document CC version compatibility | CC may change record types; adapter must be updatable |
| NF4 | Sidecar off by default; no archive of re-extractable content | Storage; content_ref points to source for fetch |

### 1.3 Out of Scope

- Cursor, Codex adapters
- FTS5, embedding index
- MEMORY.md, summary.md, history.jsonl, debug/, file-history/
- Markdown export
- Sidecar (Edit/Write/Agent content)

---

## 2. Design Specification

### 2.1 Store Layout

```
<project>/.coding-sess/
├── sessions.db          # SQLite; sessions + events
└── ingest_state.json    # Optional: (source_file, mtime) for incremental
```

**Creation:** `mkdir -p .coding-sess` on first ingest; fail if parent dir not writable.

**Projects and vendors:** One store per project. All vendors ingest into the same `sessions.db`. `sessions.source` distinguishes vendor (`Claude`, `Codex`, `Cursor`). `sessions.project_path` is the project root for that session (from slug decode, session_meta.cwd, or workspace path; NULL for Cursor global storage).

### 2.2 Schema Specification

**sessions**

| Column | Type | Nullable | Default | Constraints | Description |
|--------|------|----------|---------|-------------|-------------|
| id | TEXT | NOT NULL | — | PRIMARY KEY | session_id (UUID from filename stem) |
| source | TEXT | NOT NULL | — | — | `Claude` |
| type | TEXT | NOT NULL | — | — | `Code` |
| release | TEXT | NULL | — | — | CC version string (e.g. `2.1.77`) |
| release_value | INTEGER | NULL | — | — | major*256 + minor*16 + build |
| started_at | REAL | NOT NULL | — | — | Unix ms; first event timestamp or file mtime |
| ended_at | REAL | NULL | — | — | Unix ms; last event timestamp or file mtime |
| project_path | TEXT | NULL | — | — | Project root: slug decode (CC), session_meta.cwd (Codex), workspace path (Cursor); NULL for Cursor global |
| metadata | TEXT | NULL | — | — | JSON; extensible |

**events**

| Column | Type | Nullable | Default | Constraints | Description |
|--------|------|----------|---------|-------------|-------------|
| id | INTEGER | NOT NULL | autoincrement | PRIMARY KEY | Surrogate key |
| session_id | TEXT | NOT NULL | — | REFERENCES sessions(id) | FK |
| event_id | TEXT | NOT NULL | — | UNIQUE(session_id, event_id) | Business key component |
| event_type | TEXT | NULL | — | — | user_message, assistant_message, tool_call, tool_result |
| subtype | TEXT | NULL | — | — | prompt, slash_command, response, dialog, permission_denied, truncated |
| role | TEXT | NULL | — | — | user, assistant, system |
| content | TEXT | NULL | — | — | Truncated per policy |
| content_len | INTEGER | NULL | — | — | Actual length before truncation |
| content_ref | TEXT | NULL | — | — | JSON: {path, byte_offset?, line?, length} or {sidecar_file} |
| tool_name | TEXT | NULL | — | — | For tool_call/tool_result |
| tool_input | TEXT | NULL | — | — | JSON |
| tool_output | TEXT | NULL | — | — | Truncated |
| timestamp | REAL | NULL | — | — | Unix ms |
| file_path | TEXT | NULL | — | — | For Read/Edit/Write |
| source_file | TEXT | NULL | — | — | Raw source path (absolute) |
| metadata | TEXT | NULL | — | — | JSON; usage, stop_reason, etc. |
| source_raw | BLOB | NULL | — | — | First 512 bytes; decoder debug only |

**Indices:** `idx_events_session`, `idx_events_timestamp`, `idx_events_tool_name`, `idx_sessions_project`.

**Derived (Phase 1):** `tool_counts` as ad-hoc query; `session_summary` deferred.

### 2.3 Event ID Specification

- **event_id:** `{line}` — 1-based line number in JSONL. Unique within session file.
- **Business key for upsert:** (session_id, event_id). session_id = filename stem (UUID, no extension).
- **DB id:** INTEGER PRIMARY KEY autoincrement; internal only; not used for upsert.
- **Future:** Composite `{line}:{content_hash_short}` if line collisions occur (Cursor/Codex).

### 2.4 Slug ↔ Path Specification

| Operation | Algorithm | Example |
|-----------|-----------|---------|
| **Encode (path → slug)** | Replace `/` with `-`; prefix with `-` if path is absolute | `/Users/walter/Work/Spank/spank-py` → `-Users-walter-Work-Spank-spank-py` |
| **Decode (slug → path)** | Replace `-` with `/`; if leading `-`, treat as absolute | `-Users-walter-Work-Spank-spank-py` → `/Users/walter/Work/Spank/spank-py` |
| **Match** | Given project_path (git root), encode to slug; check `Path.home()/.claude/projects/<slug>/` exists | Return slug or None |

**Edge cases:** Relative paths (no leading `/`): no leading `-` in slug. Empty path: return empty string.

### 2.5 Record Processing Specification

**Processing flow:**

```
for each line in JSONL (1-based line_num):
  record = json.loads(line)
  if should_skip(record): continue
  for event in normalize(record, line_num, session_id, source_file):
    sanitize(event)
    truncate(event)
    upsert_event(conn, event)
  update_session_timestamps(session_id, events)
```

**Type mapping:**

| Raw type | Action | event_type | subtype | Notes |
|----------|--------|------------|---------|-------|
| user, content.text, not slash | Include | user_message | prompt | — |
| user, content.text, starts with `/` | Include | user_message | slash_command | — |
| user, content.tool_result, is_error=false | Include | user_message | tool_result | Pair tool_use_id → tool_name |
| user, content.tool_result, is_error=true | Include | user_message | permission_denied | Same pairing |
| assistant, content.text, no tool_use follows | Include | assistant_message | response | Truncate 1000 |
| assistant, content.text, tool_use follows | Include | assistant_message | dialog | Truncate 200 |
| assistant, content.tool_use | Include | tool_call | (none) | Extract tool_input per extract_tool_input |
| assistant, stop_reason=max_tokens | Include | assistant_message | truncated | — |
| progress, file-history-snapshot, queue-operation, last-prompt, system | Skip | — | — | — |

**tool_use_id pairing:** Build map `tool_use_id → tool_name` from assistant content blocks before processing user tool_result blocks. For permission_denied, lookup tool_name from map.

### 2.6 Truncation Specification

| Field | Limit | content_len | content_ref |
|-------|-------|-------------|-------------|
| response | 1000 chars | Yes | Optional: {path, offset, length} |
| dialog | 200 chars | Yes | Optional |
| tool_result | 500 chars (summary) | Yes | Optional |
| Grep pattern | 120 chars | — | — |
| Agent prompt | 200 chars inline | — | — |

**Algorithm:** `truncated, full_len = truncate_content(text, limit)`. If `len(text) > limit`, append `"…"` (1 char) to truncated; `content_len = full_len`.

### 2.7 Sanitization Specification

| Step | Action | When |
|------|--------|------|
| Control chars | Strip 0x00–0x1F, 0x7F | Always (except --no-sanitize) |
| ANSI | Remove `\x1b\[[0-9;]*m` and similar | Always |
| Line endings | `\r` → `\n` | Always |
| Redact | Regex replace with `[REDACTED]` | When --redact |

**source_raw:** Store `line.encode('utf-8', errors='replace')[:512]` as BLOB. Never decode or concatenate without `sanitize_for_display()`.

### 2.8 Incremental Specification

- **State file:** `ingest_state.json` in `.coding-sess/`. Format: `{"<source_file>": <mtime_float>, ...}`.
- **Logic:** For each candidate file, `stat().st_mtime`; if `state.get(source_file) == mtime`, skip. Else ingest; `state[source_file] = mtime`; write state.
- **--force:** Ignore state; ingest all; update state after.
- **Timestamps:** Prefer `record.timestamp` or `message.timestamp` for started_at/ended_at; fallback to file mtime.

### 2.9 Error Handling Specification

| Condition | Action |
|-----------|--------|
| JSON parse error on line | Log line number; skip line; continue |
| Missing required field | Log; use default or skip record |
| DB constraint violation | Log; abort ingest for that file |
| File not found | Log; skip |
| Permission denied (read) | Log; skip; exit 1 if no files read |
| Store dir not writable | Exit 1 with message |

---

## 3. Implementation

### 3.1 Directory Layout

```
CodeSess/
├── CodingSess.md           # Methodology
├── CSPlan.md               # This file
├── coding-sessions-schema.sql
├── ingest/
│   ├── __init__.py
│   ├── project.py          # project derivation, slug, Codex/Cursor paths
│   ├── cc_adapter.py       # CC JSONL parser, normalizer
│   ├── codex_adapter.py    # Codex JSONL parser, normalizer
│   ├── cursor_adapter.py   # Cursor SQLite bubbleId extractor
│   ├── store.py            # SQLite init, upsert, incremental state
│   └── sanitize.py         # control chars, ANSI, redact
├── cli/
│   ├── __init__.py
│   ├── ingest_cmd.py       # session-ingest
│   └── query_cmd.py        # session-query
├── main.py                 # CLI entry (argparse → subcommands)
├── config.py               # Paths, options, defaults
└── scripts/
    ├── find_candidate.py   # Candidate discovery (ingest workflow)
    └── conf_candidate.py   # Paths, aggregators, exclude patterns (env overrides)
```

### 3.2 Module Dependencies

```
main.py
  └── cli/ingest_cmd, cli/query_cmd

cli/ingest_cmd.py
  └── ingest/project, ingest/cc_adapter, ingest/store, ingest/sanitize, config

cli/query_cmd.py
  └── ingest/store, ingest/project, config

ingest/cc_adapter.py
  └── ingest/sanitize

ingest/store.py
  └── (none; sqlite3 stdlib)

ingest/project.py
  └── (none; pathlib, subprocess)

ingest/sanitize.py
  └── (none; re)
```

### 3.3 File-by-File Implementation Spec

#### config.py

| Symbol | Signature | Description |
|--------|-----------|-------------|
| CC_PROJECTS_DIR | Path | `Path.home() / ".claude" / "projects"` |
| STORE_DIR_NAME | str | `".coding-sess"` |
| STORE_DB_NAME | str | `"sessions.db"` |
| STATE_FILE_NAME | str | `"ingest_state.json"` |
| TRUNCATE_RESPONSE | int | 1000 |
| TRUNCATE_DIALOG | int | 200 |
| TRUNCATE_TOOL_RESULT | int | 500 |
| TRUNCATE_GREP_PATTERN | int | 120 |
| TRUNCATE_PROMPT | int | 10000 (user prompts) |
| CODEX_SESSIONS_DIR | Path | `CODINGSESS_CODEX_SESSIONS_DIR` or `~/.codex/sessions` |
| CURSOR_USER_DATA | Path | `CODINGSESS_CURSOR_USER_DATA` or platform default |
| MIN_SESSION_FILE_SIZE | int | 20*1024 (20 KB) |
| REDACT_PATTERNS | list[re.Pattern] | Default patterns for API keys, tokens |
| get_store_path(project_root: Path) -> Path | Returns `project_root / STORE_DIR_NAME / STORE_DB_NAME` |
| get_state_path(project_root: Path) -> Path | Returns `project_root / STORE_DIR_NAME / STATE_FILE_NAME` |

#### ingest/project.py

| Symbol | Signature | Description |
|--------|-----------|-------------|
| get_project_root(cwd: Path | None = None) -> Path | Run `git rev-parse --show-toplevel` in cwd; on failure (not in repo), return `cwd or Path.cwd()`; log warning if fallback |
| path_to_slug(path: Path) -> str | Encode: `path.as_posix().replace("/", "-")`; if `path.is_absolute()`, ensure leading `-` |
| slug_to_path(slug: str) -> Path | Decode: replace `-` with `/`; if leading `-`, prepend `/` for absolute |
| get_cc_projects_dir() -> Path | Return `CC_PROJECTS_DIR` |
| find_slug_for_project(project_root: Path) -> str | None | Encode project_root; if `(CC_PROJECTS_DIR / slug).is_dir()`, return slug; else None |
| get_cc_session_dir(project_root: Path) -> Path | None | `find_slug_for_project`; if slug, return `CC_PROJECTS_DIR / slug`; else None |

#### ingest/sanitize.py

| Symbol | Signature | Description |
|--------|-----------|-------------|
| CONTROL_CHARS_RE | re.Pattern | `[\\x00-\\x1f\\x7f]` |
| ANSI_ESCAPE_RE | re.Pattern | `\\x1b\\[[0-9;]*[a-zA-Z]` |
| sanitize_text(s: str) -> str | Remove control chars, ANSI; `\\r` → `\\n` |
| sanitize_for_display(s: str, max_len: int = 512) -> str | Sanitize + truncate; for source_raw display only |
| redact(s: str, patterns: list[re.Pattern]) -> str | Replace matches with `[REDACTED]` |
| apply_sanitization(text: str, redact: bool = False) -> str | sanitize_text; if redact, redact(text, REDACT_PATTERNS) |

#### ingest/cc_adapter.py

| Symbol | Signature | Description |
|--------|-----------|-------------|
| SKIP_TYPES | frozenset | `{"progress", "file-history-snapshot", "queue-operation", "last-prompt", "system"}` |
| iter_cc_records(path: Path) -> Iterator[tuple[int, dict]] | Open path; for each non-empty line, `yield (line_num, json.loads(line))`; on JSON error, log and skip |
| should_skip(record: dict) -> bool | `record.get("type") in SKIP_TYPES` or (type=="system" and not record.get("message", {}).get("content")) |
| normalize_user(record, line_num, session_id, source_file, tool_map: dict) -> list[dict] | Extract content blocks; for text→prompt/slash_command; for tool_result→tool_result/permission_denied; use tool_map for tool_name |
| normalize_assistant(record, line_num, session_id, source_file) -> tuple[list[dict], dict] | Extract content; classify response vs dialog; yield events; return (events, tool_map) for tool_use_id→tool_name |
| extract_tool_input(tool_name: str, input_obj: dict) -> dict | Bash→{command}, Read→{path,offset,limit}, Edit→{path,old_len,new_len}, Grep→{pattern,path,output_mode,glob}, Agent/mcp_task→{description,prompt,subagent_type}, Skill→{skill,args}, etc. |
| truncate_content(text: str, limit: int) -> tuple[str, int] | If len<=limit return (text, len); else return (text[:limit-1]+"…", len(text)) |
| process_file(path: Path, session_id: str, opts: dict) -> Iterator[dict] | iter_cc_records; for each record, if not should_skip: normalize (two-pass: first assistant for tool_map, then user); yield events. Apply truncation per opts. |

#### ingest/store.py

| Symbol | Signature | Description |
|--------|-----------|-------------|
| init_db(db_path: Path) -> None | Create parent dir if needed; execute schema SQL; create tables if not exist |
| connect(db_path: Path) -> sqlite3.Connection | Open connection; set row_factory=sqlite3.Row |
| upsert_session(conn, session: dict) -> None | INSERT OR REPLACE sessions (id, source, type, release, release_value, started_at, ended_at, project_path, metadata) |
| upsert_event(conn, event: dict) -> None | INSERT OR REPLACE events; event must have session_id, event_id, event_type, subtype, role, content, content_len, tool_name, tool_input, tool_output, timestamp, source_file, metadata, source_raw (optional) |
| load_ingest_state(state_path: Path) -> dict[str, float] | Read JSON; return {} if missing/invalid |
| save_ingest_state(state_path: Path, state: dict) -> None | Write JSON |
| should_ingest(state_path: Path, source_file: str, mtime: float, force: bool) -> bool | If force: True; else state.get(source_file) != mtime |

#### cli/ingest_cmd.py

**Args:** See [§5](#5-cli-reference). **Flow:**
1. project_root = get_project_root() or --project
2. cc_dir = get_cc_session_dir(project_root); if None, exit 1 "No CC project dir for {project_root}"
3. store_path = get_store_path(project_root); init_db(store_path)
4. state_path = get_state_path(project_root); state = load_ingest_state(state_path)
5. jsonl_files = sorted(cc_dir.glob("*.jsonl"))
6. For each path: if st.st_size < min_size: continue; mtime = path.stat().st_mtime; if not should_ingest(state_path, str(path), mtime, force): continue
7. For each path: session_id = path.stem; conn = connect(store_path); for event in process_file(path, session_id, {debug, redact}): upsert_event(conn, event); upsert_session(conn, {...}); state[str(path)] = mtime
8. save_ingest_state(state_path, state)
9. Print summary: N files ingested, M events; "Added: X sessions, Y events | Overall: Z sessions, W events"

#### cli/query_cmd.py

**Args and behavior:** See [§5](#5-cli-reference).

### 3.4 Data Structures

**Normalized event dict (internal):**
```python
{
  "session_id": str,
  "event_id": str,           # str(line_num)
  "event_type": str,        # user_message | assistant_message | tool_call | tool_result
  "subtype": str | None,    # prompt | slash_command | response | dialog | permission_denied | truncated
  "role": str | None,       # user | assistant | system
  "content": str | None,    # truncated
  "content_len": int | None,
  "content_ref": str | None,  # JSON
  "tool_name": str | None,
  "tool_input": str | None,   # JSON
  "tool_output": str | None,
  "timestamp": float | None,
  "file_path": str | None,
  "source_file": str,
  "metadata": str | None,    # JSON
  "source_raw": bytes | None  # only when --debug
}
```

**Session dict:**
```python
{
  "id": str,              # session_id
  "source": "Claude",
  "type": "Code",
  "release": str | None,
  "release_value": int | None,
  "started_at": float,
  "ended_at": float | None,
  "project_path": str | None,
  "metadata": str | None
}
```

### 3.5 Key Implementation Notes

- **Streaming:** `for line in path.open(encoding="utf-8", errors="replace"):` — never `path.read()`.
- **event_id:** `str(line_num)` for Phase 1.
- **Sessions:** Accumulate started_at (min timestamp), ended_at (max timestamp) during file pass; upsert_session after processing file.
- **source_raw:** Only when `opts.get("debug")`; `line.encode("utf-8", errors="replace")[:512]`.
- **tool_use_id pairing:** First pass over file: collect assistant records, build `tool_use_id → tool_name` from content.tool_use blocks. Second pass: process user records with tool_map for permission_denied.

---

## 4. Validation Plan

### 4.1 Pre-Implementation

| Check | Command / Action | Pass Criteria |
|-------|------------------|---------------|
| Type distribution | `jq -r '.type' file.jsonl` piped to `sort` and `uniq -c` | Confirm progress, user, assistant dominate; note queue-operation, last-prompt, system counts |
| User structure | `jq 'select(.type=="user")' file.jsonl` piped to `head -1` | message.content is array; blocks have type (text, tool_result) |
| Assistant structure | `jq 'select(.type=="assistant")' file.jsonl` piped to `head -1` | message.content has text, tool_use blocks |
| Slug round-trip | Encode project path; check `~/.claude/projects/<slug>/` exists; decode slug → path | path_to_slug(slug_to_path(slug)) == slug |
| Git root | Run `git rev-parse --show-toplevel` from repo root, subdir, non-repo | Repo: returns root; non-repo: exit non-zero |
| Malformed line | Insert invalid JSON line in test file | Ingest skips line; logs; continues |

### 4.2 Post-Ingest

| Check | Query / Action | Expected |
|-------|----------------|----------|
| Row counts | `SELECT COUNT(*) FROM events` | ≈ user + assistant content blocks (exclude progress, etc.) |
| tool_counts parity | `session-query --tool-counts` vs `python3 jsonl_names.py <project>` | Same tool names and counts |
| Duplicates | `SELECT session_id, event_id, COUNT(*) FROM events GROUP BY session_id, event_id HAVING COUNT(*) > 1` | Empty result |
| Sessions | `SELECT COUNT(*) FROM sessions` | One row per JSONL file ingested |
| Timestamps | `SELECT id, started_at, ended_at FROM sessions` | started_at ≤ ended_at; reasonable Unix ms |
| Truncation | `SELECT content, content_len FROM events WHERE content_len > 1000` | content ends with "…"; content_len correct |

### 4.3 Incremental

| Check | Action | Expected |
|-------|--------|----------|
| Re-run unchanged | Ingest; note row count; ingest again | No new rows; same count |
| Modify file, re-run | Append line to JSONL; ingest | New row(s); state updated |
| --force | Ingest; ingest --force | Same result; state updated |

### 4.4 Sanitization

| Check | Action | Expected |
|-------|--------|----------|
| content | Ingest file with control chars, ANSI in content | content has no 0x00-0x1f, 0x7f; no raw ANSI |
| source_raw | --debug; query event with source_raw | Never print/concatenate without sanitize_for_display |
| --redact | Ingest with --redact; content has API key pattern | Replaced with [REDACTED] |

### 4.5 Schema Drift

| Check | Action |
|-------|--------|
| Multiple CC versions | Run ingest on sessions from different CC versions; document adapter compatibility in CHANGELOG or CodingSess |
| New record type | If CC adds new type: sample; add to SKIP_TYPES or mapping |

---

## 5. CLI Reference

### session-ingest

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--project` | PATH | git root or cwd | Project root; store at `<project>/.coding-sess/` |
| `--source` | cc\|codex\|cursor\|all | all | Source(s) to ingest |
| `--cursor-global` | flag | false | Cursor: use globalStorage (v44.9+); skip workspace |
| `--force` | flag | false | Re-ingest all files; ignore mtime |
| `--min-size` | BYTES | 20480 | Skip JSONL files smaller than this |
| `--redact` | flag | false | Apply redaction patterns to content |
| `--debug` | flag | false | Store source_raw BLOB for decoder debug |

### session-query

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--project` | PATH | git root or cwd | Project root |
| `--stats` | flag | — | Print session and event counts |
| `--taxonomy` | flag | — | List event types and subtypes |
| `--sessions` | flag | — | List sessions (ended_at DESC) |
| `--id` | flag | — | With --sessions: show numbered IDs (1=most recent) |
| `--tool` | N? | 0 | Tool histogram; N sessions. N=0 all sessions |
| `--tool-counts` | flag | — | Legacy: tool_name\tcount |
| `-sess N` | int | — | Select session N (1=most recent) |
| `--show` | MODES | — | With -sess: prompt, pr, agent, tool, perm |
| `--permissions` | flag | — | List permission_denied events |
| `--task-review` | flag | — | Task/Web tool counts, descriptions, outcomes |

---

## 6. SQLite Access

Store path: `<project>/.coding-sess/sessions.db` (see [§2.1](#21-store-layout)). Use `sqlite3` CLI or any SQLite client.

### 6.1 Schema

See [§2.2](#22-schema-specification) for full schema. Key tables: `sessions` (id, source, started_at, ended_at, project_path); `events` (session_id, event_id, event_type, subtype, content, tool_name, timestamp).

### 6.2 CLI examples

```bash
# Session count by source
sqlite3 .coding-sess/sessions.db "SELECT source, COUNT(*) FROM sessions GROUP BY source"

# Ingested projects by vendor (source, project_path, session count)
sqlite3 .coding-sess/sessions.db "SELECT source, COALESCE(project_path,'(global)') as project, COUNT(*) FROM sessions GROUP BY source, project_path ORDER BY source, project_path"

# Recent sessions (last 5)
sqlite3 .coding-sess/sessions.db "SELECT id, source, datetime(started_at/1000,'unixepoch') FROM sessions ORDER BY ended_at DESC LIMIT 5"

# Sessions from Claude Code only
sqlite3 .coding-sess/sessions.db "SELECT id, project_path FROM sessions WHERE source='Claude'"

# Sessions from Codex only
sqlite3 .coding-sess/sessions.db "SELECT id, project_path FROM sessions WHERE source='Codex'"

# Sessions from Cursor (global storage has project_path=NULL)
sqlite3 .coding-sess/sessions.db "SELECT id, project_path FROM sessions WHERE source='Cursor'"

# Tool counts per source
sqlite3 .coding-sess/sessions.db "SELECT s.source, e.tool_name, COUNT(*) FROM events e JOIN sessions s ON e.session_id=s.id WHERE e.event_type='tool_call' GROUP BY s.source, e.tool_name"

# Prompt events from session
sqlite3 .coding-sess/sessions.db "SELECT subtype, substr(content,1,80) FROM events WHERE session_id='<id>' AND event_type='user_message' ORDER BY timestamp"
```

### 6.3 Python examples

```python
import sqlite3
from pathlib import Path

db = Path("/path/to/project/.coding-sess/sessions.db")
conn = sqlite3.connect(db)
conn.row_factory = sqlite3.Row

# Sessions by source
for row in conn.execute(
    "SELECT source, COUNT(*) as cnt FROM sessions GROUP BY source"
):
    print(f"{row['source']}: {row['cnt']} sessions")

# Ingested projects by vendor
for row in conn.execute(
    "SELECT source, COALESCE(project_path,'(global)') as proj, COUNT(*) as cnt FROM sessions GROUP BY source, project_path ORDER BY source, proj"
):
    print(f"{row['source']}\t{row['proj']}\t{row['cnt']} sessions")

# Events for a session
session_id = "abc-123"
for row in conn.execute(
    """
    SELECT event_type, subtype, role, content, tool_name, timestamp
    FROM events WHERE session_id = ? ORDER BY timestamp
    """,
    (session_id,),
):
    content_preview = (row['content'] or '')[:60]
    print(f"{row['event_type']}: {content_preview}...")

# Sessions with permission_denied
for row in conn.execute(
    """
    SELECT s.id, s.source, e.tool_name, e.timestamp
    FROM events e
    JOIN sessions s ON e.session_id = s.id
    WHERE e.subtype = 'permission_denied'
    ORDER BY e.timestamp
    """
):
    print(f"{row['id']} ({row['source']}): {row['tool_name']}")

conn.close()
```

### 6.4 SQLite3 shell

```bash
sqlite3 .coding-sess/sessions.db
```

```sql
.tables                    -- list tables
.schema sessions           -- show sessions schema
.schema events             -- show events schema
SELECT * FROM sessions LIMIT 5;
SELECT * FROM events WHERE session_id = (SELECT id FROM sessions LIMIT 1);
.quit
```

---

## 7. Expansion Plans

| Phase | Scope | Details |
|-------|-------|---------|
| **Phase 2** | Derived tables, FTS5 | `session_summary` view; FTS5 when full-text search needed; `tool_counts` as materialized view if useful |
| **Phase 3** | Codex, Cursor adapters | Ingest from `~/.codex/sessions/**` and `history.jsonl`; Cursor `state.vscdb` extraction; unified store; source column distinguishes |
| **Phase 4** | Ad-hoc queries, templates | Query templates; optional embedding index; Markdown export |
| **Later** | MEMORY.md, sidecar | Summary.md, debug/, file-history/; sidecar for Edit/Write/Agent content when needed |

---

## 8. Discovered Projects (~/Work)

Illustrative list (as of scan). Run `find_candidate.py` for current output.

### Claude Code

| Project |
|---------|
| ~/Work/Spank/spank-py |
| ~/Work/WP |
| ~/Work/WP/harduw |
| ~/Work/WP/multiwp |
| ~/Work/WP/multiwp/python |
| ~/Work/WP/must/py |
| ~/Work/WP/spank-py |
| ~/Work/WP/splunk-py |

### Codex

| Project |
|---------|
| ~/Work/CodingTools/codex/codex-rs |
| ~/Work/Claw/openclaw |
| ~/Work/Claw/openclaw-docs |
| ~/Work/WP/ZD |
| ~/Work/WP/harduw |
| ~/Work/WP/wp |
| ~/Work/WP/wpages |
| ~/Work/zduploads |

### Cursor

| Project |
|---------|
| ~/Work/Claude/claude-code |
| ~/Work/Claude/claude-code-system-prompts |
| ~/Work/Claw/openclaw |
| ~/Work/Cursor/Study |
| ~/Work/Cursor/cStudy |
| ~/Work/Github/Schema |
| ~/Work/Github/skip |
| ~/Work/ZK/ZeroM |
| ~/Work/ZK/ZeroMac |
| ~/Work/ZK/zerowalletmac |
| ~/Work/ZK/zerowalletmac/src |

**Sources:** Claude Code from `~/.claude/projects/<slug>/`; Codex from `~/.codex/sessions/**/*.jsonl` session_meta.cwd; Cursor from `workspaceStorage/*/workspace.json` folder. Cursor global storage (v44.9+) not included (project_path NULL).

**Workflow:** Run `python3 scripts/find_candidate.py` to review candidates with metrics: weeks since mtime/commit, git remote status, session count/size. Aggregators (WP, ZK, Claw, Claude, Cursor, Github, CodingTools) are parent dirs; leaf projects are listed. Add `--fetch-check` to verify remote reachability (slow). Full criteria: [CSCandidates §3](CSCandidates.md#3-criteria).

---

## 9. Project-Specific Configuration

Developer and system-specific conventions. Future search/ingest scripts will read these from config or CLI args. See [CSCandidates §3](CSCandidates.md#3-criteria) and [§4](CSCandidates.md#4-directory-categories) for general criteria and directory categories.

### 9.1 Backup and Obsolete Directories

| Pattern | Meaning |
|---------|---------|
| `OLD` | We name backup/obsolete dirs `OLD` (e.g. `WP/OLD`) |
| `*/OLD/*` | Contents under OLD are obsolete |
| `Save`, `Save*` | Dumping grounds; e.g. `Github/Save` holds AVTran backups; `Save*` = any dir starting with Save |

**Config:** `exclude_backup_patterns` = `["*/OLD/*", "*/Save*", "*/Save"]`

### 9.2 Download/Review Directories

Directories of cloned OSS repos for search and implementation review; little or no meaningful coding work. Often named with plural `s`:

| Path | Content |
|------|---------|
| CodingTools | `/Users/walter/Work/CodingTools` — OSS coding tools (cline, continue, codex, WindsurfVS, etc.) |
| MCP/MCPs | MCP-related repos |
| Claw/Claws | (if exists) |
| ZK/ZKs | (if exists) |
| Spank/sOSS | Spank OSS |
| Claude, Claude/Claudes | Mix of tools; Claudes = OSS repos (tweakcc, claude-code-proxy, agency-agents) |

**Config:** `exclude_review_dirs` = `["CodingTools", "MCP/MCPs", "Claw/Claws", "ZK/ZKs", "Spank/sOSS", "Claude/Claudes"]` or pattern `*s` for top-level plural names.

### 9.3 CodeSess vs CodingSess

| Name | Role |
|------|------|
| **CodeSess** | Actual project directory with `.git`, full codebase (main.py, ingest/, cli/, tests/) |
| **CodingSess** | Was retained after repo rename; had docs-only copy (CSCandidates, scripts); now merged into CodeSess |

**History:** Project directory was renamed (likely to CodeSess). We kept working in the old directory (CodingSess), which accumulated new docs and scripts. That work has been merged into CodeSess. Use **CodeSess** as the canonical project path.

### 9.4 Path and Internal Name Issues

| Issue | Detail |
|-------|--------|
| **Slug decode** | CC slug `-Users-walter-Work-Spank-spank-py` decodes to `Spank/spank/py` (hyphen→slash); real path is `Spank/spank-py`. Slug format is lossy for path segments containing hyphens. |
| **Worktree cwd** | Claw/openclaw-docs is worktree of openclaw; Codex `session_meta.cwd` may point to either; sessions can be split. |
| **Github** | Mixed: clones, forks, some active (Transcript/avtran). Requires manual review. `Github/Save` = exclude. |
| **zerowalletmac/src** | Redundant with `zerowalletmac`; prefer parent. |

### 9.5 Config and Future CLI

**Config split:** Ingest/query: `config.py`. Candidate discovery: `conf_candidate.py`. Override via env: ingest uses `CODINGSESS_CC_PROJECTS_DIR`, etc.; find_candidate uses `CODINGSESS_WORK_ROOT`, `CODINGSESS_CC_PROJECTS`, `CODINGSESS_CODEX_SESSIONS`, `CODINGSESS_CURSOR_WS`.

**Planned:** Config file or CLI args for `exclude_backup_patterns`, `exclude_review_dirs`, `aggregators`, `work_root`.
