# Codess — Session record store

Session records for Claude Code, Codex, and Cursor: ingest JSONL/SQLite into SQLite; query tool counts, sessions, and content.

**Full documentation, document index, and goals:** **[Codess.md](Codess.md)**.

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

## Minimal examples

```bash
# Ingest by source
python -m main ingest --dir /path/to/project --source cc
python -m main ingest --dir /path/to/project --source cursor

# Show session content
python -m main query --dir /path/to/project -sess 1 --show pr
```

Store: `<project>/.codess/`. Config: `CODESS_*` env vars. Central registry: `CODESS_REGISTRY` (default `~/.codess`) / `ingested_projects.json` — merged updates from **scan** (index metrics), **ingest** (store stats), **query --stats**; optional **`--registry PATH`** overrides the directory. Subprocess tests should set **`CODESS_REGISTRY`** to a temp dir so runs do not touch your home tree.
