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
python -m main query --dir /path/to/project --snapshot-id SNAPSHOT_ID --stats

# Verify an existing immutable baseline against an explicit acceptance policy
python tools/validate_snapshot.py --project /path/to/project \
  --policy catalog/policies/project.json --raw-store-root ~/.codess/raw \
  --query-smoke --report /tmp/project-validation.json

# Rebuild twice, require a semantic fixed point, then approve atomically
python tools/apply_and_verify.py --project /path/to/project --source all \
  --raw-mode capture --registry ~/.codess \
  --policy catalog/policies/project.json --repeat \
  --approve-catalog catalog/approved-baselines.json \
  --report /tmp/project-apply.json
```

---

## Minimal examples

```bash
# Ingest by source
python -m main ingest --dir /path/to/project --source cc
python -m main ingest --dir /path/to/project --source cursor
python -m main ingest --dir /path/to/project --raw-mode capture

# Fail on lossy source mappings and apply an optional scoped content policy
python -m main ingest --dir /path/to/project --strict-mapping \
  --content-policy schema/content-policy.example.json

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
Session listings show both the exact vendor `id` and a deterministic
source-namespaced `global_id`, so identical vendor strings cannot collide when
several databases are queried together.

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

**Do not delete or replace an ingested project directory as though it were only
a Git checkout.** Its `.codess/` currently contains the normalized outcomes and
snapshot manifests, while Claude, Codex, and Cursor source records also depend
on machine-local vendor stores. Before retirement, ingest with `capture` or
`seal`, validate twice, preserve the snapshot/raw objects, and register the new
location binding. A fresh clone alone restores none of this evidence.

The acceptance tools process exactly one project per invocation. Validation is
read-only. Apply-and-verify refuses unversioned legacy stores unless the
operator explicitly requests preservation, performs two forced ingests when
`--repeat` is set, compares source revision identities and a canonical logical
digest (not SQLite bytes), exercises every version-aware query path, and updates
the approved-baseline catalog only after all gates pass. A reference-only raw
policy remains an explicit reproducibility limitation rather than being called
an exact capture.

Retained snapshot queries require an explicit immutable ID. They require the
recorded package digest by default. `--snapshot-package-policy read-compatible`
allows a same-format historical read only after all retained hashes and the
current database contract pass; it prints a semantic-parity warning and never
updates current registry counts. The frozen reviewed set is checked with
`python tools/verify_reviewed_baselines.py`.
