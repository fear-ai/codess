# CoSchema — Our SQLite designs

Sessions, events, indexes. Executable DDL is `sql/CoSchema.sql`.

---

## Schema file

**sql/CoSchema.sql** — Canonical DDL. store.py reads and executes this file. Enables: `sqlite3 .codess/sessions.db < sql/CoSchema.sql` for manual setup.

---

## Store layout

```

## Replacement semantics

Claude and Codex transcripts own one normalized session. Re-ingesting one
replaces that session's events in a single transaction; a valid source with no
supported events removes the previous session. Cursor databases own many
sessions, so refresh replaces events whose `source_file` is that database and
removes only sessions left without events from any Cursor source. Ingest state
is updated only after the database commit.
<project>/.codess/
├── sessions.db          # Legacy: all vendors
├── sessions_cc.db       # Per-vendor
├── sessions_codex.db
├── sessions_cursor.db
└── ingest_state.json
```

---

## sessions

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| id | TEXT | NOT NULL | session_id (PK) |
| source | TEXT | NOT NULL | Claude, Codex, Cursor |
| type | TEXT | NOT NULL | Code, IDE |
| release | TEXT | NULL | Version string |
| release_value | INTEGER | NULL | major*256 + minor*16 + build |
| started_at | REAL | NOT NULL | Unix ms |
| ended_at | REAL | NULL | Unix ms |
| project_path | TEXT | NULL | Project root; NULL for Cursor global |
| metadata | TEXT | NULL | JSON |

---

## events

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| id | INTEGER | NOT NULL | PK autoincrement |
| session_id | TEXT | NOT NULL | FK sessions(id) |
| event_id | TEXT | NOT NULL | Stable vendor/adapter identifier; UNIQUE(session_id, event_id). Claude uses the line number for the first emitted block and `line:block` for additional blocks. |
| event_type | TEXT | NULL | user_message, assistant_message, tool_call, system_event |
| subtype | TEXT | NULL | prompt, slash_command, response, dialog, truncated, tool_result, permission_denied, tool_failure, turn_aborted, context_compaction |
| role | TEXT | NULL | user, assistant, system |
| content | TEXT | NULL | Truncated |
| content_len | INTEGER | NULL | Full length |
| content_ref | TEXT | NULL | JSON |
| tool_name | TEXT | NULL | |
| tool_input | TEXT | NULL | JSON |
| tool_output | TEXT | NULL | Truncated |
| timestamp | REAL | NULL | Unix ms |
| file_path | TEXT | NULL | |
| source_file | TEXT | NULL | Raw path |
| metadata | TEXT | NULL | JSON; Claude events retain record UUID/parent UUID/tool-use id, Codex calls retain call id/status, and Cursor sessions retain global/header classification |
| source_raw | BLOB | NULL | Debug only |

### Audit event contract

`query --audit` reports only direct upstream evidence. Unsupported means the
adapter emits no audit row; Codess does not infer a state from timing, missing
results, prose similarity, or nearby records.

| Audit state | Claude | Codex | Cursor |
|---|---|---|---|
| Permission request | Unsupported | Unsupported | Unsupported |
| Permission decision | Explicit denial text on an error tool result → `permission_denied`; approvals are not emitted | Unsupported | Unsupported |
| Tool failure | Error tool result that is not an explicit denial → `tool_failure` | Call record with structured status `failed`, `failure`, `error`, or `incomplete` → `tool_failure` | Unsupported |
| Turn abort | Unsupported | `event_msg.turn_aborted` → `turn_aborted` | Unsupported |
| Context compaction | `system` + `compact_boundary` → `context_compaction`; retain trigger only, not summary/token bodies | Unsupported | Unsupported |

The report prints project, session, vendor, timestamp, audit kind, tool name,
and a bounded structural detail such as status or compaction trigger. It does
not print failure bodies or compacted summaries.

---

## Indexes

- idx_events_session
- idx_events_timestamp
- idx_events_tool_name
- idx_sessions_project
