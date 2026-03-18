# CodingSess

**Purpose:** Quick start, status, minimal commands/config — what users need to run the tool.

Session record store for Claude Code. Ingest JSONL transcripts into SQLite; query tool counts, sessions, and session content.

## Status

- **Claude Code (CC):** Implemented. Ingest from `~/.claude/projects/<slug>/*.jsonl`.
- **Codex:** Implemented. Ingest from `~/.codex/sessions/**/*.jsonl` (filtered by project cwd).
- **Cursor:** Implemented. Workspace `state.vscdb` (project-scoped) or global `state.vscdb` (v44.9+; use `--cursor-global`).

## Quick start

```bash
# Ingest (from project root)
python -m main ingest --project /path/to/project

# Query
python -m main query --project /path/to/project --stats
python -m main query --project /path/to/project --sessions --id
python -m main query --project /path/to/project --tool
python -m main query --project /path/to/project -sess 1 --show pr > session1.md
```

## Examples

### Ingest by vendor

```bash
# Claude Code only (default: ~/.claude/projects/<slug>/*.jsonl)
python -m main ingest --project /path/to/project --source cc

# Codex only (~/.codex/sessions/**/*.jsonl, filtered by session_meta.cwd)
python -m main ingest --project /path/to/project --source codex

# Cursor workspace DBs (workspaceStorage/<hash>/state.vscdb)
python -m main ingest --project /path/to/project --source cursor

# Cursor global storage only (v44.9+; globalStorage/state.vscdb)
python -m main ingest --project /path/to/project --source cursor --cursor-global

# All sources (default)
python -m main ingest --project /path/to/project
```

### Display by vendor

```bash
# List sessions with source column
python -m main query --project /path/to/project --sessions --id
# Output: id  num  source   started_at  ended_at  project_path

# Filter by source via SQL (see SQLite Access below)
sqlite3 .coding-sess/sessions.db "SELECT id, source FROM sessions WHERE source='Claude'"
sqlite3 .coding-sess/sessions.db "SELECT id, source FROM sessions WHERE source='Codex'"
sqlite3 .coding-sess/sessions.db "SELECT id, source FROM sessions WHERE source='Cursor'"

# Show session content (works for any source)
python -m main query --project /path/to/project -sess 1 --show pr    # prompt + response
python -m main query --project /path/to/project -sess 1 --show tool   # tool calls
python -m main query --project /path/to/project -sess 1 --show perm   # permission_denied
```

## Commands

Ingest: `--source cc|codex|cursor|all` (default all), `--cursor-global` (Cursor v44.9+ global storage), `--project`, `--force`, `--min-size`, `--redact`, `--debug`. Query: `--stats`, `--sessions`, `--id`, `-sess N --show pr`, `--tool`, `--permissions`, `--task-review`, `--taxonomy`. Full reference: [CSPlan §5](CSPlan.md#5-cli-reference).

## Store

One database per project: `<project>/.coding-sess/sessions.db`. All vendors (Claude, Codex, Cursor) ingest into the same store. State in `ingest_state.json`. Details: [CSPlan §2.1](CSPlan.md#21-store-layout). SQLite access: [CSPlan §6](CSPlan.md#6-sqlite-access).

**Projects and vendors:** The store is project-local. `sessions.source` = `Claude` | `Codex` | `Cursor`. `sessions.project_path` = project root for that session (NULL for Cursor global). To list ingested projects by vendor:

```bash
sqlite3 .coding-sess/sessions.db "SELECT source, project_path, COUNT(*) FROM sessions GROUP BY source, project_path ORDER BY source"
```

## Config

`CODINGSESS_CC_PROJECTS_DIR` (default `~/.claude/projects`); `CODINGSESS_CODEX_SESSIONS_DIR` (default `~/.codex/sessions`); `CODINGSESS_CURSOR_USER_DATA` (override Cursor User dir for tests); `MIN_SESSION_FILE_SIZE` in `config.py` (20 KB).

## Dev

```bash
pip install -r requirements.txt
pytest
```

