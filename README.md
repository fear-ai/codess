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

# Structure-only vendor evidence audits (do not retain conversation bodies)
python tools/audit_codex_parentage.py --output catalog/codex-parent-audit.json
python tools/audit_cursor_features.py --output catalog/cursor-feature-audit.json
python tools/gather_evidence.py --output catalog/evidence-inventory.json

# Non-mutating parse/map/integrity preflight
python -m main ingest --validate --dir /path/to/project --source all

# Versioned typed query rows (prototype: sessions and stats)
python -m main query --dir /path/to/project --sessions --output-format jsonl

# Review candidates, record a decision, and preflight the reviewed set
python -m main catalog candidates --dir /path/to/work --format table
python -m main catalog decide --catalog catalog/candidates.json \
  --project PROJECT_ID --decision approved --reviewer NAME
python -m main catalog onboard --catalog catalog/candidates.json \
  --validate-only --receipt /tmp/onboard.json

# Administrative verification, evidence, and schema operations
python -m main baseline verify
python -m main evidence gather --component-dir /tmp/codess-evidence
python -m main schema compare OLD.json NEW.json --declared compatible
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

Working store: `<project>/.codess/`. Ingest creates and atomically promotes a
validated immutable CoSchema v3 snapshot under
`~/.codess/projects/<project-id>/`; raw evidence defaults to reference-only and
can be captured or sealed with `--raw-mode`. Config: `CODESS_*` env vars. Central
registry: `CODESS_REGISTRY` (default `~/.codess`) / `ingested_projects.json` —
merged updates from **scan** (index metrics), **ingest** (store stats), **query
--stats**; optional **`--registry PATH`** overrides the directory. Subprocess
tests should set **`CODESS_REGISTRY`** to a temp dir so runs do not touch your
home tree. Stable Project identities, locations, and workspace bindings live in
`projects.json`; test isolation is enforced by the pytest configuration.

**Do not delete or replace an ingested project directory as though it were only
a Git checkout.** Claude, Codex, and Cursor sources are machine-local. Before
replacing a checkout, ingest with `capture` or `seal` and validate twice, then
run the current relocation wrapper:

```bash
python tools/retire_project.py --project /old/path --registry ~/.codess \
  --new-location /new/path
```

The compatibility wrapper requires captured evidence and a new location, updates the stable
Project/location catalog, and verifies the new location can read the central
snapshot. It does not delete the old directory. First-class operations are
`catalog location add`, `catalog location retire`, and `catalog relocate`;
see Designs.md §12.

`baseline validate` and `baseline apply` process exactly one project per
invocation; the existing tools are compatibility wrappers. Validation is
read-only. Apply refuses unversioned legacy stores unless the
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
updates current registry counts. Check the frozen reviewed set with
`python -m main baseline verify` (or its compatibility wrapper,
`python tools/verify_reviewed_baselines.py`).
