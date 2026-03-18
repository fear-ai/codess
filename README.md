# CodingSess

**Purpose:** Quick start, status, minimal commands/config — what users need to run the tool.

Session record store for Claude Code. Ingest JSONL transcripts into SQLite; query tool counts, sessions, and session content.

## Status

- **Claude Code (CC):** Implemented. Ingest from `~/.claude/projects/<slug>/*.jsonl`.
- **Codex, Cursor:** Investigated; adapters deferred. See [CodingSess.md](CodingSess.md) §3.3, §3.4.

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

## Commands

Ingest: `--project`, `--force`, `--min-size`, `--redact`, `--debug`. Query: `--stats`, `--sessions`, `--id`, `-sess N --show pr`, `--tool`, `--permissions`, `--task-review`, `--taxonomy`. Full reference: [CSPlan §5](CSPlan.md#5-cli-reference).

## Store

`<project>/.coding-sess/sessions.db`; state in `ingest_state.json`. Details: [CSPlan §2.1](CSPlan.md#21-store-layout).

## Config

`CODINGSESS_CC_PROJECTS_DIR` (default `~/.claude/projects`); `MIN_SESSION_FILE_SIZE` in `config.py` (20 KB).

