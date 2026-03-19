# Codess — Session record store

Link to Codess.md; getting started; minimal applications. Doc map: Codess.md §11.

---

Session record store for Claude Code, Codex, Cursor. Ingest JSONL/SQLite into SQLite; query tool counts, sessions, content.

**See [Codess.md](Codess.md) for goals, architecture, and full documentation.**

---

## Getting started

```bash
pip install -r requirements.txt

# Scan (discover projects with session data; cwd when no dirs)
python -m main scan --out -
python -m main scan --dir /path/to/work --out -

# Ingest (from project root)
python -m main ingest --dir /path/to/project

# Query
python -m main query --dir /path/to/project --stats
python -m main query --dir /path/to/project --sessions --id
python -m main query --dir /path/to/project --tool
```

---

## Minimal applications

```bash
# Ingest by source
python -m main ingest --dir /path/to/project --source cc
python -m main ingest --dir /path/to/project --source cursor

# Show session content
python -m main query --dir /path/to/project -sess 1 --show pr
```

Store: `<project>/.codess/`. Config: `CODESS_*` env vars. Registry: `~/.codess/ingested_projects.json`.
