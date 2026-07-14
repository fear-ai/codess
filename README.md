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
python -m main query --dir /path/to/project --lineage
python -m main query --dir /path/to/project --audit --limit 100
python -m main query --dir /path/to/project --diagnostics
python -m main query --dir /path/to/project --artifacts
python -m main query --dir /path/to/project-a --dir /path/to/project-b --stats
```

---

## Minimal examples

```bash
# Ingest by source
python -m main ingest --dir /path/to/project --source cc
python -m main ingest --dir /path/to/project --source cursor
python -m main ingest --dir /path/to/project --raw-mode capture

# Show session content
python -m main query --dir /path/to/project -sess 1 --show pr
```

Query aggregates all selected project and vendor stores read-only. Session
numbers form one global most-recent-first order; `--stats` prints aggregate
totals while updating the registry with per-project counts. `--lineage`
joins tool calls to results and identifies missing or orphaned outcomes.
`--audit` reports evidence-backed denials, failures, aborts, and compactions.
`--diagnostics` exposes mapping loss and ambiguity. `--artifacts` correlates
project-relative artifact evidence across vendor stores without asserting
authorship.
`--limit N` bounds globally ordered session, permission, lineage, and audit
rows after merging all selected stores.

Changed or forced source ingestion is replacement-based: stale normalized
events are removed transactionally. A valid transcript with no supported
events removes its previous normalized session and is reported as an empty
source.

Store: `<project>/.codess/`. Ingest creates and atomically promotes a validated
immutable CoSchema v2 snapshot; raw evidence defaults to reference-only and can
be captured or sealed with `--raw-mode`. Config: `CODESS_*` env vars. Central
registry: `CODESS_REGISTRY` (default `~/.codess`) / `ingested_projects.json` —
merged updates from **scan** (index metrics), **ingest** (store stats), **query
--stats**; optional **`--registry PATH`** overrides the directory. Subprocess
tests should set **`CODESS_REGISTRY`** to a temp dir so runs do not touch your
home tree.
