# Operations

This guide gets Codess installed, connected to local Claude Code, Codex, and
Cursor stores, and running against Projects. It covers the normal operating
path and basic diagnosis. Exact command options remain in `codess --help`.

## 1. Requirements

Codess requires:

- Python 3.10 or newer;
- local read access to the vendor stores being examined;
- write access to the selected Project's `.codess/` directory; and
- write access to the central Codess registry, normally `~/.codess/`.

SQLite support is supplied by Python. The `zstandard` package is installed as a
runtime dependency for bounded raw-object capture.

## 2. Installation

Choose the intended Python environment, then install from the repository root:

```bash
python -m pip install -e '.[test]'
codess --version
```

Run the tests when changing the software or local environment:

```bash
pytest -q
```

The installed `codess` command is the normal interface. Running source files
directly is reserved for development and diagnosis.

## 3. Source Locations

Codess uses the ordinary vendor locations by default:

| Source system | Default location |
|---|---|
| Claude Code | `~/.claude/projects/` |
| Codex active Sessions | `~/.codex/sessions/` |
| Codex archived Sessions | `~/.codex/archived_sessions/` |
| Cursor | Platform-specific Cursor `User` directory; on macOS, `~/Library/Application Support/Cursor/User/` |

Override a location only when the installation actually differs:

```bash
export CODESS_CC_PROJECTS=/absolute/path/to/claude/projects
export CODESS_CODEX_SESSIONS=/absolute/path/to/codex/sessions
export CODESS_CODEX_ARCHIVED_SESSIONS=/absolute/path/to/codex/archived_sessions
export CODESS_CURSOR_DATA=/absolute/path/to/Cursor/User
export CODESS_REGISTRY=/absolute/path/to/codess-registry
```

Every configured Source root must be absolute. Pointing Codess at copied test
data is a useful way to diagnose source interpretation without touching live
application state.

## 4. First Project

Use one real repository or Project directory whose Sessions are expected to be
small and easy to recognize.

### 4.1 Discover

```bash
PROJECT=/absolute/path/to/project
codess scan --dir "$PROJECT" --out -
```

Scan consults vendor indexes and bounded metadata. It does not normalize
Session content. Confirm that the row names the intended Project and
source systems before ingesting.

### 4.2 Validate

Run a non-publishing parse and validation when testing a new Source shape or
configuration:

```bash
codess ingest --dir "$PROJECT" --source all --validate
```

Validation uses temporary stores and reports malformed, ignored, empty, and
failed Sources without changing the Project's selected Project store set.

### 4.3 Ingest

```bash
codess ingest --dir "$PROJECT" --source all
```

Ingest selects relevant vendor records, decodes and classifies them, validates
the common records, writes per-source-system SQLite stores, and publishes the
completed Project store set. Progress is emitted on standard error without
printing Session content.

### 4.4 Orient

```bash
codess query overview --dir "$PROJECT"
codess query sessions --dir "$PROJECT"
```

Choose a recognizable Session and inspect or search it:

```bash
codess query search --dir "$PROJECT" --text 'distinctive phrase'
codess query events --dir "$PROJECT" --session-id SESSION_ID
```

If results do not resemble the expected Project work, stop and investigate
Project attribution, Source selection, and vendor mapping before ingesting more
Projects.

## 5. Routine Updates

Repeating ingest performs an assessed update. Unchanged selected evidence is
skipped; changed Sources are decoded and replace their prior normalized
records transactionally.

```bash
codess ingest --dir "$PROJECT" --source all
```

Use `--force` only when source update evidence is suspect or decoder behavior
changed without a detectable Source change:

```bash
codess ingest --dir "$PROJECT" --source all --force
```

For maintained catalog Projects, `refresh` composes assessment, validation, and
application. Plan first:

```bash
codess refresh --project PROJECT_NAME
```

Then select an explicit stage after reviewing the plan:

```bash
codess refresh --project PROJECT_NAME --stage preflight
codess refresh --project PROJECT_NAME --stage apply
```

Use repeated `--project` or a maintained Project list for a bounded batch.
Failures remain Project-specific unless fail-fast behavior is explicitly
selected.

Inspect the known Project inventory and its computed annotations with:

```bash
codess catalog status
codess catalog annotations
```

## 6. Selecting Several Projects

`--dir` may be repeated. `--dirs` accepts a plain path list or a CSV containing
`directory_path`.

```bash
codess query overview \
  --dir /path/to/project-a \
  --dir /path/to/project-b

codess query search --dirs projects.csv --text 'specific interaction'
```

Inspect the resolved Project scope before drawing cross-Project conclusions.
The stores preserve Project and source-system identity even when results are
merged for display.

## 7. Content and Resource Controls

Built-in bounds protect against accidental binary ingestion, extremely large
transcripts, oversized context bodies, and excessive Event counts. They are
safety ceilings, not expected payload sizes.

Use the versioned policy files when a Project requires deliberate overrides:

- `schema/resource-policy.example.json`
- `schema/content-policy.example.json`

```bash
codess ingest --dir "$PROJECT" \
  --resource-policy /path/to/resource-policy.json \
  --content-policy /path/to/content-policy.json
```

When a limit is exceeded, inspect the classified Source and representative
record before raising it. Oversize or non-text input can indicate incorrect
Project selection, a vendor format change, or a record that should remain
external rather than searchable content.

## 8. Raw Evidence

The ordinary `reference` mode records the Source locator and bounded update
evidence without retaining another complete copy. `capture` and `seal` are for
investigations requiring exact retained Source bytes.

```bash
codess ingest --dir "$PROJECT" --raw-mode reference
```

Raw capture can contain private code, prompts, tool data, and credentials. Use
it only with an explicit retention purpose and adequate local storage. Raw
objects support provenance and recovery; they are not inserted wholesale into
the searchable database. The functional tradeoffs and mode boundaries are
defined in [Raw Evidence and Integrity](Designs.md#48-raw-evidence-and-integrity).

## 9. Basic Diagnosis

### 9.1 No Project Appears in Scan

Check:

1. the configured vendor Source root exists and is readable;
2. the vendor record actually names or binds the selected Project location;
3. the Session falls within the selected recency scope;
4. the Project path has not moved without a recorded binding; and
5. the Source is not a subagent or another excluded relationship.

Use `--debug` for bounded source-selection diagnostics. It must not be treated
as a routine content dump.

### 9.2 Ingest Reports Malformed or Unsupported Records

Identify the source system, Source locator, record locator, exact type, and
diagnostic reason. Compare the representative record with the vendor schema and
adapter fixture. A malformed optional field should not remove an otherwise
usable Event; a core identity or ordering failure should remain explicit.

### 9.3 Search Returns Unexpected Counts

Verify:

- selected Project and source-system scope;
- direct human versus harness/delegated classification;
- exact Event kind and source type;
- repeated physical storage versus repeated real Events;
- time and status predicates; and
- whether Interaction or Model Turn expansion added surrounding Events.

Use direct read-only SQLite queries to reconcile a focused result.

### 9.4 Cursor Is Slow or Busy

Codess queries selected Cursor headers and composer key ranges through read-only
SQLite connections. Confirm that the selected workspace mapping is narrow and
that the live database is not continuously changing. Do not copy, vacuum,
rewrite, or fully decode the Cursor database merely to diagnose one Project.

### 9.5 Current Snapshot Manifest Hash Mismatch

`scan`, `ingest`, and `query` verify the current snapshot's `manifest.json`
against the hash recorded in its `current.json` pointer before trusting it.
A mismatch produces an explicit error naming the affected Project and
snapshot rather than silently accepting stale or tampered content; see
[Publication and Integrity](CoPlan.md#84-publication-and-integrity) for what
the check does and does not protect against.

Investigate before bypassing: compare `current.json`'s recorded
`manifest_sha256` against a fresh hash of the retained `manifest.json`, and
confirm whether the snapshot directory was touched outside normal Codess
operation (an interrupted publish, manual editing, or a restored backup are
the ordinary causes). `codess baseline` commands can rebuild or verify a
snapshot from its retained stores.

`--no-hash` (or `CODESS_NO_HASH=1`) skips this verification and trusts the
retained manifest as-is. It is a recovery and debugging option, not a
routine flag: every bypassed check is logged as a warning, and using it
does not repair the underlying inconsistency. Prefer identifying and fixing
the cause of the mismatch over routinely suppressing the check.

## 10. Schema Maintenance

Normal ingest verifies the installed schema package before it writes a store.
When changing CoSchema, a mapping profile, or SQLite DDL, run the focused
contract checks and compare the complete package declaration:

```bash
pytest -q tests/test_schema_contract.py
codess schema compare /path/to/baseline-contract.json \
  /path/to/candidate-contract.json \
  --declared same
```

Choose `same`, `compatible`, `breaking`, or `manual` only after reviewing the
reported contract changes. Then run the full test suite and the smallest real
source-system example that exercises the changed translation.

## 11. Maintenance Boundaries

Snapshots, raw objects, catalogs, and receipts support repeatable operation but
are not the primary product surface. Before deleting any of them:

1. run `codess storage report`;
2. generate a dry-run retention plan with `codess storage prune`;
3. confirm that current Project pointers and referenced evidence remain valid;
4. apply only the reviewed plan; and
5. retain the receipt.

Do not modify vendor-owned stores. Do not commit `.codess/` content to a source
repository. Use `codess --help` and each administrative family's `--help` for
the complete current command contract.
