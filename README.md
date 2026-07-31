# Codess — session record store

Codess discovers locally retained Claude Code, Codex, and Cursor sessions,
normalizes them into per-Project SQLite stores, and supports cross-session and
cross-vendor investigation.

## Documentation

This README is the user and customer guide. For the other authoritative views:

- **[Product specification](Codess.md):** goals, requirements, concepts, and the
  complete documentation map.
- **[Engineering guide and work plan](CoPlan.md):** repository architecture,
  configuration, CLI implementation, tests, priorities, and open decisions.
- **[Maintainer runbook](Operations.md):** validation, publication, evidence,
  relocation, storage, retention, and process recovery.

Schema contracts, vendor storage references, design rationale, and compatibility
evidence are indexed from **Codess.md**.

## Install

Install the repository into the active virtual environment or pyenv-selected
interpreter:

```sh
python -m pip install -e .
codess --help
```

Add `[test]` when the environment also needs pytest:

```sh
python -m pip install -e '.[test]'
pytest
```

`python -m main` remains an equivalent source-tree compatibility entry point.
Pyenv selects the interpreter into which the `codess` console script is
installed; it is not part of Codess command syntax. A non-editable wheel must
eventually carry the executable Schema/catalog resources as package data; that
distribution task does not limit the supported editable installation.

## Basic workflow

Vendor session stores are machine-local. `scan` reads vendor indexes and
metadata; `--dir` limits results to that path and does not recursively crawl
its descendants.

```sh
# Discover known session-bearing Projects.
codess scan --dir /path/to/work --out -

# Normalize one Project. Reference mode records source identity without copying
# the complete vendor source container.
codess ingest --dir /path/to/project

# Orient, list sessions, and open one by stable ID.
codess query overview --dir /path/to/project
codess query sessions --dir /path/to/project --limit 50
codess query --dir /path/to/project --sessions --id
codess query --dir /path/to/project \
  --session-id 'codess:session:sha256:…' --show pr tool
```

### Observing ingest

Ingest prints UTC-timestamped, content-free progress to stderr while stdout is
reserved for its final result. Interactive runs show Project, vendor, source,
raw-capture, Cursor composer, derived-correlation, snapshot, skip, and failure
phases. Large source/composer and SQLite-backup phases emit periodic
heartbeats. The final line distinguishes work processed during this invocation
from the totals stored in the selected scope.

For cron or CI that treats any stderr output as exceptional, add
`--no-progress`. This suppresses live lines but still retains the bounded
structured trace in each Project's `.codess/last-ingest-report.json`; preflight
returns it in the JSON result. Each Project report has its own `status` and
diagnostic deltas, so an earlier batch failure does not mark later successful
Projects as failed. Routine reports name the immutable `snapshot_id`; an
unchanged repeat may reuse the evidence summary only for that same snapshot.

```sh
codess ingest --dirs selected-projects.csv --source cursor
codess ingest --dirs selected-projects.csv --source cursor \
  --no-progress
```

## Data and safety

The working store is `<project>/.codess/`; accepted immutable snapshots and
the Project registry live under `~/.codess/` by default. Normalized text may
be bounded, sanitized, or redacted and should not be mistaken for an exact raw
record.

Ingest resource maximums have built-in defaults and may be overridden together
with a partial, versioned JSON file:

```sh
cp schema/resource-policy.example.json local-resource-policy.json
codess ingest --dir /path/to/project \
  --resource-policy local-resource-policy.json
```

The file separates transcript bytes from Cursor SQLite container bytes. It also
controls per-source and per-Session Event counts and context/compaction
characters. See **[Operations.md](Operations.md#resource-bounds-and-processing)**
for precedence, per-limit disabling, and validation.

Do not discard or replace a session-bearing checkout as if it contained only
Git data. Claude, Codex, and Cursor retain sources locally, and a moved or
deleted workspace can break their association with the Project. Maintainers
should follow **[Operations.md](Operations.md)** before relocation, raw capture,
baseline publication, or retention cleanup.

## Terms and catalogs

Codess uses **Project** for a stable continuing body of work. For Git-backed
work, exactly one Project represents the repository. Directories, clones, and
linked worktrees are machine-local Project locations; branches and commits are
repository observations; Claude/Codex/Cursor workspaces are source-system
bindings under that same Project. These remain distinct entity types even
though the repository defines the Project boundary. A **Session** is one
namespaced source-system conversation. A **Project snapshot** is one dated
immutable normalized extraction of a Project. An **Assembly** is a reproducible
cross-Project selection over named Project snapshots; SQLite, JSONL, Parquet,
and DuckDB are possible Assembly export formats, not new source
systems. The complete glossary is in **[Codess.md](Codess.md#5-glossary)**.

The current CLI spelling `--dir` accepts a Project location and resolves it to
a Project binding. `--source cc|codex|cursor` selects a source-system
adapter/store family. Some compatibility code and reports still call that
selector `vendor` or `vendor_filter`; this does not make vendor, product,
harness, and source system the same concept. A future naming cleanup must
preserve existing CLI aliases and stored source designations.

Project listings currently have distinct purposes:

| Location | Meaning |
|---|---|
| `~/.codess/projects.json` | Authoritative curated Project IDs, logical names, locations, aliases, and workspace bindings |
| `~/.codess/projects/<project-id>/current.json` | Verified current Project snapshot pointer; sibling `snapshots/` contains retained immutable observations |
| `~/.codess/ingested_projects.json` | Path-keyed scan/ingest/query telemetry; useful for discovery and cleanup, but not an identity catalog or an “all Projects” selection |
| `catalog/approved-baselines.json` and `catalog/reviewed-baselines.json` | Small compatibility/release corpus, not the complete personal Project catalog |
| `~/.codess/assemblies.json` | Planned Assembly catalog and Project↔Assembly input relation; not implemented yet |

Inspect the curated catalog without opening Session content:

```sh
jq -r '.projects[] |
  [.project_id, .logical_name,
   ([.locations[] | select(.state == "active") | .path][0] // "")] |
  @tsv' ~/.codess/projects.json
```

Typed queries can select exact catalog identities directly. Repeat
`--project-id`; do not combine it with `--dir` or `--dirs`:

```sh
codess query sessions \
  --project-id 'codess:project:uuid:…' \
  --project-id 'codess:project:uuid:…'
```

Each ID resolves to its durable central current snapshot, independent of an
obsolete working-tree path. A versioned saved set can pin different named
snapshots per Project. Before selecting a broad catalog cohort, inspect
per-Project readiness and its `N/N` summary:

```json
{
  "format": "codess.project-set/1",
  "name": "reviewed-comparison",
  "projects": [
    {"project_id": "codess:project:…", "snapshot_id": null},
    {"project_id": "codess:project:…", "snapshot_id": "20260729T…"}
  ]
}
```

```sh
codess catalog status --registry ~/.codess
codess catalog annotations --registry ~/.codess
codess catalog annotations --label core --label large
codess query overview --project-set reviewed-projects.json
codess query sessions --all-current
```

`null` means resolve that Project's current snapshot when the set is used;
the resulting request records the exact resolved snapshot. The
`--all-current` spelling is retained as a compatibility selector for eligible
catalog Projects with central current pointers; it is not a freshness or
publication label. `catalog status` reports `query_ready`,
`missing_current_snapshot`, `package_mismatch`, `snapshot_fail`, or
`not_selected`
for each Project and never infers source refresh. Explicit exclusion or defer
curation states are omitted from the compatibility selector. Catalog-attribute
predicates are not yet implemented. Use active paths to create a reviewed
`--dirs` CSV for other selections. Do not feed all entries from
`ingested_projects.json` into ingest, query, or an eventual `all-current`
Assembly: that file may retain obsolete, missing, scan-only, and old temporary
paths.

`catalog annotations` is the refreshable human/machine catalog view. Its
non-exclusive labels retain reasons and measured facts:

- `included` means selection-eligible, not fresh;
- `core` means a reviewed compatibility-baseline member, not business
  priority;
- `query_ready` and `incomplete` report current package compatibility;
- `large` defaults to at least 25,000 Events or 128 MiB of normalized stores;
- `limited` reports `none` or `reference` raw-evidence mode;
- `suspect` requires direct review/inconsistency evidence; and
- `not_selected` retains excluded, deferred, or worktree evidence.

Repeated `--label` values are ANDed. `--format table|json|csv`, `--output`,
`--large-events`, and `--large-bytes` support review and automation without
copying transient counts into project documentation.

Refresh one or more known Projects with the same staged operation:

```sh
# Read-only plan; --project may be repeated and accepts ID, unique name, or path.
codess refresh --project Zero400 --project Misses

# A maintained JSON/CSV/plain-text list; still read-only unless a stage is named.
codess refresh --project-list projects.json --stage preflight

# One distinctive computed catalog cohort.
codess refresh --designator core --stage apply
```

The supported cohort designators are `included`, `core`, `query_ready`,
`incomplete`, `large`, `limited`, `suspect`, and `multi_vendor`. They use the
same definitions and thresholds as `catalog annotations`; `not_selected` is
intentionally unavailable as a broad refresh target. An explicitly named
Project remains selectable so an operator can investigate or repair it.

`plan` is the default and parses no vendor source. `preflight` runs an isolated
validated ingest for every selected Project. `apply` first requires every
preflight to pass and verifies that the selected IDs, Project catalog, and
CoSchema package did not change; it then refreshes each Project independently.
There is no cross-Project transaction: a successful Project snapshot remains
published if a later Project fails, and the dated JSON receipt reports every
result and any partial failure. `--raw-mode auto` retains each current
snapshot's raw mode, defaulting to `reference` for a Project with no usable
current policy. Routine refresh does not freeze or approve a compatibility
baseline.

Stable selectors fail closed: if any selected current/named snapshot is
missing, hash-invalid, a package mismatch, or unable to satisfy the current
read layout, the complete query is rejected rather than silently omitting that
Project. The diagnostic names its logical Project name when available, stable
Project ID, snapshot ID, and incompatibility. Use an explicit reviewed Project
set to narrow scope, or rebuild and validate outdated current snapshots under
the current software before relying on `--all-current`.

Human-readable Session names are mutable catalog metadata, not Session IDs.
Each name maps to one stable `global_session_id`. Assign one by exact or
unambiguous current ID prefix:

```sh
codess session name --project-id PROJECT_ID --session-id c9d1 --name slash_model
codess session names --project-id PROJECT_ID
```

Names are unique within a Project and may change; stable Session IDs remain the
selectors and provenance keys. Source-system titles are separate evidence:
current Codex CLI/app state, Claude title records, and Cursor Composer names
can expose them unevenly, so Codess does not silently promote one to a user
alias.

### Project status before extraction

Query readiness is not source freshness. Before a potentially large Cursor
operation, run the content-free status helper and a Project-limited scan:

```sh
tools/project_status.sh /path/to/project ~/.codess
codess scan --dir /path/to/project --source cc,codex,cursor --out -
```

The helper delegates repository facts to Git and uses shell filesystem
observations for the current pointer, last ingest report, exact Claude
Project-store path, Project-local `.claude`/`.codess` markers, and the global
Cursor container. Git is a strong primary change signal, not an exclusive one:
vendor stores and Project tool-state may advance without a commit, while a Git
change does not prove a new vendor Session. Cursor container mtime alone is
also not Project attribution; the limited scan queries its indexes for the
selected Project without normalizing every conversation or creating another
database copy.

Build results, logs, generated files, and run artifacts are reported as tool
activity only when a retained source record links them to an invocation.
Filesystem changes may justify further assessment, but do not establish which
source system produced them. Proceed to full ingest when selected vendor
observations changed, the current snapshot is absent/incompatible, or an
explicit validation run is required.

## Selecting Project and source-system scope

`--dir PATH` is repeatable. `--dirs FILE` accepts either one path per line or a
CSV containing a `directory_path` column; file entries are applied first and
repeated resolved paths are removed. Query and ingest default to the current
Git root, or the current directory when it is not in a Git worktree. Scan
defaults to the current directory.

For query, repeatable `--project-id ID`, `--project-set FILE`, and
`--all-current` are stable-identity alternatives to paths. A named
`--snapshot-id` is allowed only with one exact Project; put per-Project
historical snapshot IDs in a saved set. Stable selectors and path selectors are
intentionally mutually exclusive.

These paths are selection filters over vendor indexes and retained Project
bindings, not requests to recursively traverse every descendant. A work tree
that contains several repositories therefore needs an explicit Project list or
the Projects returned by `scan`.

Use `--source cc`, `--source codex`, or `--source cursor` to select one
source-system adapter/store family.
Query additionally accepts comma-separated unions such as `cc,codex` and
`all`. Select the Project set before source system, Session, time, or report
filters so every result has an explicit, reproducible scope.

## Investigation and research

Investigation is the primary reason to retain and normalize sessions. Use the
CLI first for stable Project/vendor/session scope and repeatable reports; use
read-only SQLite for event-level questions that the current report surface does
not yet express. The matrix below owns user capability and commands.
**CoPlan.md §8.2.1** is the corresponding separate implementation review:
implemented versus partial status, the responsible work item, and the
recommended development order.

### Capability matrix

| Use case | Current support | Commands and export | Limits |
|----------|-----------------|---------------------|--------|
| **UC1 — list sessions for one or more Projects** | Direct typed result by path, exact Project ID, saved Project/snapshot set, or the compatibility catalog-cohort selector; per-Project readiness reports `N/N` query-ready coverage | Start with `catalog status`; then `query sessions --project-set FILE`, repeat `--project-id ID`, or use `--all-current` only as a transient selector | Source refresh is not inferred; dynamic catalog predicates and broad snapshot discovery remain: **L-S1**, **L-S3** |
| **UC2 — select sessions by source system** | Direct; comma-separated union; typed events add time/model/kind/status/artifact/tool/actor/role/origin and lineage filters | Add `--source`, `--since`, `--until`, `--model`, `--event-kind`, `--status`, `--tool-name`, `--actor-kind`, `--content-role`, `--origin-kind`, `--parent-session-id`, `--session-relation`, or `--initiation-kind` | Saved/dynamic catalog selection and caller-selected projections remain: **L-S1–L-S2** |
| **UC3 — orient by size, activity, and time** | Typed overview reports Session relation and Interaction initiation; turns, Events, characters/tools/artifacts/models; elapsed span, UTC months, Event-gap buckets, event days, and 5/30/120-minute active-time sensitivity. Its bounded UTC daily series adds prompt/response counts and characters, individual actor engagement, separately classified subagent-Session activity, two labelled human/model response windows, and raw tool call/result/input/output measures; monthly tool totals are also returned | `query overview --dir P --facet-limit 50`; `evidence audit orientation`; legacy `--stats`, `--tool`, `--artifacts`; `storage report` | Counts, lengths, timestamps, and identities are primary observations; displays may derive ratios/percentages. These are not cost, quota, timeout, or active-work measures. Delegated-origin mappings are applied for current Claude/Cursor evidence, and independent SQL reconciliation covers current query-ready Projects. Measured distribution/performance extensions remain: **L-M1–L-M4**, **A2/A9** |
| **UC4 — open a known session** | Direct by list ordinal, stable global ID, or an unambiguous vendor ID | `-sess N` or `--session-id ID`; `--show prompt pr agent tool perm` | Whole-session display only; terminal excerpts: **L-S2**, **L-O1**, **L-C2** |
| **UC5 — find and reconstruct an exchange or event group** | Typed event rows select stable Event/Session/Interaction/Model-Turn IDs in global canonical order; an Event can expand to its complete Interaction or Model Turn and a same-Session sequence window. Claude, Codex, and Cursor pass the scoped human → harness → model/tool → harness/model provenance path; Claude/Cursor delegated prompts and current Codex protocol subagent/collaboration shapes are mapped; current Codex server tool-search, MCP transport status, rollback, and direct-versus-injected user-role records are preserved | `query events --event-id ID --expand interaction`; `--expand model-turn`; `--before N --after N`; direct Interaction/turn and actor filters also compose | Current Codex collaboration mapping is protocol/fixture-backed because the reviewed local cohort has no occurrence. New shapes are evidence-triggered maintenance under **A27/T4**: **L-S2**, **L-O2** |
| **UC6 — find text, a path, error, symbol, or topic** | First-class bounded literal-substring search over normalized content, tool input/output, and artifact paths; `%`, `_`, and backslash are ordinary characters. Returned rows include bounded facets, and exact complete-content repetitions can be grouped without removing occurrences | `query search --text TEXT --limit N --byte-limit N --group-repetitions`; use `--facet-limit N` and scope predicates | Search-report refinement, topic classification, near-duplicate grouping, and an explicit wildcard-pattern operator remain; searching raw vendor fields and messages is postponed under **P13**: **L-C1–L-C2**, **L-E2** |
| **UC7 — investigate tool operations, outcomes, failures, or denials** | Direct fixed reports plus typed actor/status/tool Event filtering; denial/failure expansion and exact evidence are tested across Claude, Codex, and Cursor for the scoped human/harness/tool/model path | `--lineage`, `--audit`, `--permissions`, `--task-review`, `--tool N`; typed `query events` filters produce reusable results | Most fixed reports remain table-only; broader runtime-component and context analysis is evidence-triggered: **L-O1–L-O3** |
| **UC8 — correlate work across vendors/artifacts** | Direct aggregate plus read-only SQL drill-down | `--artifacts --source ...`; SQL through `event_artifacts` to sessions/events | Aggregate output omits constituent event IDs: **L-O2**, **L-P1** |
| **UC9 — export and compose** | Typed actions return reusable homogeneous results; Project sets explicitly union named observations; changed-snapshot comparisons use stable IDs; repetition groups retain citeable constituents; cited investigations bind a supplied summary to exact Event rows; saves are atomic and failure-tested | `--save-request`, `--save-result`, `--result-input`, `--compare-result`; `query cite --summary-file FILE --processor-id ID`; legacy JSONL/CSV remain | Caller-selected fields/package presentation are later-phase **P17**; heterogeneous analytical products remain A19/P19: **L-O1–L-O3** |
| **UC10 — verify exact source evidence** | Exact event resolver follows event → source record → verified sealed/central-captured/live candidates without copying the object and reports changed/unavailable revisions | `query evidence --event-id GLOBAL_ID` | Implemented and exercised on representative Claude, Codex, and Cursor evidence; repeat under **T1/T2/T6** when source shapes, mappings, or code change |
| **UC11 — assemble cross-Project analytical data** | Exact/saved/transient broad-cohort selectors provide observation-preserving virtual cross-Project and historical reads; reusable analysis-dataset and Assembly-export requirements are under bottom-up/top-down investigation | Today: Project sets and typed results plus external DuckDB/pandas; candidate export formats wait for a manifest/virtual-query prototype | Dynamic predicates and virtual requirements remain A19; Assembly export formats, reverse lookup, and retention are later P19: **L-S1/L-E5** |

Operationally, UC1–UC11 may be run interactively with live progress or under
automation with `--no-progress`; both modes retain the same per-Project trace
and status evidence.

“All sessions” means all sessions currently ingested and attributed to the
selected Project snapshot. It does not mean every vendor file on the machine,
every superseded snapshot, or a union of a Project's historical versions.

The current CLI and version-1 typed request/result documents are the supported
query-specification interfaces. Layered JSON, caller-selected fields, and query
package infrastructure are postponed together under CoPlan P17. The
compatibility `--all-current` spelling is only a transient selector: saved
results record the exact dated Projects/snapshots and software/schema/policy
identities that actually produced the outcome.

### Workflow A — Project or vendor session research

1. Select exact catalog Project IDs, explicit Project paths, or a maintained
   `--dirs` file.
2. Optionally add `--source`; filtering happens inside each read-only store
   before cross-store ordering and aggregation.
3. List sessions with stable IDs and bounds.
4. Export JSONL for programmatic pipelines or CSV for a spreadsheet/dataframe.
5. Reopen a chosen session by `--session-id`; unlike an ordinal, its global ID
   remains stable when the Project/vendor scope changes.

```sh
codess query --dir ~/Work/ZK/Zero400 --source cursor \
  --sessions --id --limit 50
codess query sessions --project-id 'codess:project:uuid:…' \
  --source cursor --limit 50
codess query --dirs selected-projects.csv --source cc,codex \
  --sessions --output-format csv > selected-sessions.csv
codess query --dir ~/Work/ZK/Zero400 \
  --session-id 'codess:session:sha256:…' --show pr tool
```

Parameters compose as: Project scope → optional retained snapshot → vendor
scope → report mode → report-specific limit/display → renderer. Exactly one
report mode is allowed; `--id` modifies `--sessions`, while `--show` modifies
`-sess` or `--session-id`. Unscoped current `--stats` refreshes the registry's
complete Project counts; vendor-filtered or historical stats are observational
and do not overwrite that all-source registry summary.

### Workflow B — orientation, narrowing, and phases

1. Run scoped `query overview --facet-limit N` and `query sessions` to establish
   corpus size, bounds, vendor/model composition, daily exchange/actor
   engagement, and active-time sensitivity.
2. Use `--tool N`, `--artifacts`, `--audit`, and `--lineage` to identify skew,
   repeated activity, failures, or cross-vendor evidence.
3. Save the request/result when the selection will feed another step.
4. For an activity period or task phase, run `query events` by session,
   event, Interaction, Model Turn, timestamp, kind, status, model, or artifact.
5. Treat `ended_at-started_at`, daily actor spans, and first/last prompt
   endpoints as observed spans. Active duration requires a declared
   inactivity-gap rule and remains a derived measure; none is a billing or
   capacity-utilization statistic.

### Workflow C — locate and reconstruct an exchange

1. Bound the search by Project, vendor, and preferably session/time.
2. Run `query search --text ...` with a row and byte limit; preserve its result.
3. Record the stable Event global ID, source locator, Session, Interaction,
   sequence, event kind, and content-completeness evidence.
4. Feed the result into `query events --result-input ...`; add
   `--expand interaction` or `--expand model-turn` and `--before N --after N`
   to recover complete exchange and same-Session sequence context.
5. Run `query evidence --event-id ...` when the normalized value is excerpted or
   when an exhaustive search must distinguish “absent” from “not retained.”
6. Preserve the SQL/request, snapshot identity, and evidence IDs with any
   external or LLM-produced summary.

```sh
codess query overview --dir "$PROJECT" --source codex,cursor \
  --save-result overview.json
codess query search --dir "$PROJECT" --source codex,cursor \
  --text 'counter reset' --limit 100 --byte-limit 4194304 \
  --save-request search-request.json --save-result hits.json
codess query events --dir "$PROJECT" --result-input hits.json \
  --expand interaction --before 2 --after 2 \
  --save-result selected-events.json
codess query evidence --dir "$PROJECT" --event-id 'codess:event:sha256:…'
codess query cite --dir "$PROJECT" \
  --result-input selected-events.json --summary-file summary.md \
  --processor-id 'human:walter' --save-investigation investigation.json
```

Typed actions reject unknown predicates and incompatible saved-request/action
combinations. Their JSON result always names the canonical request and hash,
store/package/snapshot/policy identities, source-availability counts, limits,
limitations, derivation edges, and a result hash. `--compare-result PRIOR.json`
returns 0 only when row content, membership, summary, and provenance are
unchanged; it returns 3 for an added, removed, or changed stable row or a
summary/provenance change.

Event/search facets describe only the returned bounded rows. Exact repetition
groups include only nonempty, complete retained content with compatible event,
actor, role, tool, status, and artifact dimensions. They preserve every
occurrence and report constituent stable Event IDs and time spans; they do not
claim that repeated evidence is redundant.

### Historical union and comparison

A Project set with multiple named snapshots is an explicit historical union.
Rows retain stable logical IDs plus a snapshot-bound `observation_id`;
summaries report logical IDs observed more than once. No “latest row” is chosen
and no observation is silently deduplicated.

For a diff, run the same canonical typed request against each named snapshot,
save both results, and compare the later run with `--compare-result`. Comparison
rejects requests that differ beyond snapshot observation scope. It reports
added, removed, and content-changed stable rows separately from summary,
package, and provenance change.

### Structured JSONL and CSV

The typed `sessions`, `overview`, `events`, and `search` actions emit one
`codess.query-result/1` JSON document (compact with `--output-format jsonl`,
indented otherwise). Contracts live in `schema/query-request-v1.json` and
`schema/query-result-v1.json`. CSV is intentionally not synthesized from these
partly nested results; use `jq`, Python/pandas, or DuckDB for an explicit
projection.

`query --output-format jsonl` is a versioned interface for `--sessions` and
`--stats`. Stats stream one record per Project followed by one total. Each line
is a `codess.query-row/1` envelope with report, Project scope, optional row
number, and typed data. Its contract is `schema/query-row-v1.json`, independent
of the CoSchema database version.

`query --output-format csv` covers the same two reports. CSV is intended for
spreadsheets, pandas, R, DuckDB, and shell pipelines. It uses Python CSV quoting
and protects string cells that could be interpreted as spreadsheet formulas.
Redirect stdout to a `.csv` file; diagnostics remain on stderr.

Requirements are deterministic ordering, stable global identities, explicit
scope, bounded output, and additive evolution within a row version. An
incompatible JSON row meaning requires a new row version. CSV column additions
must be documented; consumers requiring a strict contract should prefer JSONL.

## Direct read-only SQLite investigation

Direct SQL remains the escape hatch for projections, windows, and joins not yet
expressed by typed actions. Prefer retained snapshot databases: they are
immutable, versioned, hash-checked inputs. Do not edit, vacuum, reindex, attach
with write intent, or create derived search/index tables inside an accepted
snapshot.

Resolve a Project's current retained snapshot and inspect its vendor stores:

```sh
PROJECT="$HOME/Work/ZK/Zero400"
SNAPSHOT="$(jq -r .path "$PROJECT/.codess/current.json")"
ls "$SNAPSHOT"/*.db
sqlite3 -readonly "$SNAPSHOT/sessions_cc.db"
```

Inside the SQLite shell:

```sql
PRAGMA query_only = ON;
.headers on
.mode box

-- Per-session orientation. Times and spans use Unix milliseconds.
SELECT s.source, s.global_id, count(e.id) AS events,
       count(DISTINCT e.interaction_id) AS interactions,
       sum(e.event_kind='message.prompt') AS prompts,
       sum(e.event_type='tool_call') AS tool_calls,
       sum(coalesce(e.content_len,0)) AS original_body_chars,
       sum(length(e.content)) AS stored_body_chars,
       round((s.ended_at-s.started_at)/60000.0,1) AS elapsed_minutes
FROM sessions s LEFT JOIN events e ON e.session_id=s.id
GROUP BY s.id ORDER BY events DESC;

-- Locate candidate hits, retaining stable identity and phase information.
SELECT e.global_id, s.global_id AS session_global_id, e.sequence_no,
       e.interaction_id, e.event_kind, e.tool_name,
       datetime(e.event_at/1000,'unixepoch') AS event_utc,
       substr(e.content,1,240) AS excerpt
FROM events e JOIN sessions s ON s.id=e.session_id
WHERE lower(coalesce(e.content,'')) LIKE '%python 3 fixes%'
ORDER BY e.session_id, e.sequence_no;

-- Reconstruct the selected Interaction in canonical order.
SELECT sequence_no, global_id, event_kind, subtype, tool_name,
       coalesce(content,tool_input,tool_output) AS material
FROM events
WHERE session_id=:session_id AND interaction_id=:interaction_id
ORDER BY sequence_no;

-- Daily activity for a narrowed session selection.
SELECT date(event_at/1000,'unixepoch') AS day, count(*) AS events,
       count(DISTINCT interaction_id) AS interactions
FROM events WHERE session_id=:session_id AND event_at IS NOT NULL
GROUP BY day ORDER BY day;
```

For a one-shot CSV export:

```sh
sqlite3 -readonly -header -csv "$SNAPSHOT/sessions_cursor.db" \
  "SELECT global_id,source,started_at,ended_at FROM sessions ORDER BY ended_at DESC" \
  > cursor-sessions.csv
```

Python's standard library offers the same safety boundary:

```python
import sqlite3
from pathlib import Path

path = Path(snapshot_db).resolve()
conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
conn.execute("PRAGMA query_only = ON")
rows = conn.execute("SELECT global_id, source FROM sessions").fetchall()
conn.close()
```

SQLite's documented `mode=ro` URI opens read-only. Use `immutable=1` only for a
retained snapshot that truly cannot change; SQLite warns that falsely marking a
changing file immutable can yield incorrect results. Never use it against the
live Cursor database or another WAL-backed vendor store.

Useful external exploration tools include:

- [SQLite CLI](https://sqlite.org/cli.html) for reproducible SQL, query plans,
  and CSV/JSON output;
- [sqlite-utils query](https://sqlite-utils.datasette.io/en/stable/cli-reference.html#query)
  for parameterized SQL with JSON, JSONL, CSV, or TSV output; and
- [Datasette immutable mode](https://docs.datasette.io/en/stable/cli-reference.html#datasette-serve)
  for a local browser, facets, SQL, JSON API, and CSV export over retained
  snapshots. Bind only to localhost, disable downloads if appropriate, and do
  not publish private session databases.

Their best use against UC1–UC11 is:

| Tool | Best-fit use cases | Why it is the best fit | Useful secondary cases | Do not use it as |
|---|---|---|---|---|
| **SQLite CLI** | **UC3** orientation and distributions; **UC5** exact Interaction/Event reconstruction; **UC7** tool, failure, denial, and permission joins; **UC8** artifact/correlation drill-down | Gives exact SQL control, window/aggregate/join support, `EXPLAIN QUERY PLAN`, deterministic scripts, and direct inspection of every physical column | **UC1/UC2** scoped listings, **UC4** known-Session inspection, **UC6** bounded `LIKE` searches, **UC9** one-shot CSV/JSON export | **UC10** exact raw-evidence resolver or **UC11** provenance-aware cross-Project Assembly |
| **sqlite-utils query** | **UC1/UC2** parameterized Session/source selections; **UC6** repeatable bounded searches; **UC9** JSON/JSONL/CSV/TSV extraction into shell or data pipelines | Safer and less verbose than hand-built shell SQL for named parameters and machine-readable output; well suited to reusable extraction commands | **UC3** summaries and **UC5/UC7/UC8** queries whose SQL is already understood | An investigation UI, a semantic query planner, **UC10**, or a multi-Project authority |
| **Datasette** | **UC1** interactive Session browsing; **UC3** visual orientation/facets; **UC4** opening and following a known Session; **UC5** exploratory drill-down; **UC7** browsing tool/status/audit records | Browser navigation, sortable/filterable tables, facets, saved SQL links, JSON API, and CSV export make unfamiliar data easier to explore | **UC2** source filtering, **UC6** simple substring/filter exploration, **UC8** same-database joins, and **UC9** ad hoc API/export | An unreviewed derived index, **UC10** exact evidence verification, or **UC11** cross-Project Assembly |

For **UC6**, Codess bounded normalized search remains the default because it
reports scope, byte/row limits, truncation, and missing-source limitations.
SQLite CLI or sqlite-utils is preferable when the needed physical-field
predicate is not yet exposed. Datasette is preferable when the investigator
does not yet know which tables, values, or facets are relevant. None of these
implements postponed raw-source search over authorized vendor fields/messages.

For **UC10**, use `query evidence`; a SQL row can show lineage but cannot by
itself verify that a sealed, captured, or live raw Source still matches the
recorded revision. For **UC11**, use explicit Codess multi-directory results and
exports today, and the future A19 Assembly/DuckDB layer for durable
cross-Project provenance.

Generic tools expose the physical schema and do not implement Codess's
cross-store ordering, Project bindings, source compatibility, or snapshot
contract. SQL that becomes a repeated workflow is a candidate for the typed
query service rather than an indefinitely copied snippet.
Broader evaluated candidates—including DuckDB, Arrow/Parquet, Polars,
NetworkX, near-duplicate and semantic-search libraries, property-based testing,
coverage, and memory profiling—are classified by use case and dependency
boundary in **[Designs.md](Designs.md#applicable-tooling-and-dependency-boundaries)**.
