<p align="center">
  <img
    src="prism34.png"
    alt="Codess prism transforming session-record streams into diverse useful outcomes"
    width="800"
  >
</p>

# Codess

Codess discovers, decodes, normalizes, and searches local coding-assistant
Sessions from Claude Code, Codex, and Cursor. It preserves exact vendor evidence
while providing regular Project, Session, Event, tool, model, and Artifact
structures that can be queried together.

Use Codess to find work associated with a repository, reconstruct an Interaction,
inspect tool or model activity, compare source systems, and supply structured
inputs to later research or assessment.

## Choose a Starting Point

### I Want to Explore One Project

Follow the [basic setup and first run](Operations.md#5-first-project) to scan,
ingest, orient, and search one repository. Start here if you want to answer:

- Which Sessions exist for this Project?
- Which source systems contributed them?
- What are the largest or most active Sessions?
- Where did a particular prompt, response, tool call, error, or file appear?

### I Want to Investigate Sessions or Interactions

Read [Search and Investigation](Codess.md#5-search-and-investigation), then use the typed query
actions described under [Investigation](#investigation). These operations can
filter Events, expand complete Interactions or Model Turns, and retain stable
identities for later evidence review.

### I Want to Compare Projects, Vendors, or Models

Read [Vendor, Harness, and Model Comparison](Codess.md#43-vendor-harness-and-model-comparison) and
the relevant vendor reference:

- [Claude Code Source Schema](CCSchema.md)
- [Codex Source Schema](CodexSchema.md)
- [Cursor Source Schema](CursorSchema.md)

Repeated `--dir`, a path list passed with `--dirs`, or an explicit Project set
can select several Project store sets as one unified query scope. Common fields
support mixed-source queries; exact vendor types and mapping evidence remain
available to qualify results.

### I Operate or Maintain Codess

Use [First Project](Operations.md#5-first-project) for ordinary operation and
[Basic Diagnosis](Operations.md#10-basic-diagnosis) when results or performance
are unexpected.

## Quick Start

Codess requires Python 3.11 or newer. From the repository root:

```bash
python -m pip install -e .
```

The ordinary path relies on defaults for all three source systems, the registry,
raw references, and resource bounds:

```bash
codess scan --dir /path/to/project --out -
codess ingest --dir /path/to/project
codess query overview --dir /path/to/project
codess query search --dir /path/to/project --text 'distinctive phrase'
```

Codess reads vendor-owned stores and writes Codess data under the selected
Project's `.codess/` directory and the central registry, normally `~/.codess/`.
Review [Data Safety](#data-safety) before capturing raw evidence or exporting
content.

## Investigation

The typed query interface supplies four primary actions:

| Action | Purpose |
|---|---|
| `sessions` | List selected Sessions and their source, time, relationship, and model evidence. |
| `overview` | Summarize volumes, time coverage, Actors, tools, models, and activity. |
| `events` | Select exact Events or structured Event groups. |
| `search` | Find bounded content and structured matches. |

Common filters include:

```text
--source
--session-id
--event-id
--interaction-id
--model-turn-id
--event-kind
--actor-kind
--content-role
--origin-kind
--tool-name
--status
--model
--reasoning-effort
--service-tier
--artifact
--text
--since / --until
```

Use `codess --help` for the current flag contract. Useful compositions include:

```bash
# Tool failures in one Project.
codess query events --dir /path/to/project \
  --event-kind tool.result --status failed

# Search one source system and expand each match to its complete Interaction.
codess query search --dir /path/to/project --source codex \
  --text 'permission denied' --expand interaction

# Structured output for another program.
codess query events --dir /path/to/project \
  --tool-name Read --output-format jsonl
```

For a reproducible investigation, save the initial selection, expand it, and
bind the reviewed result to a summary:

```bash
codess query search --dir /path/to/project --text 'distinctive phrase' \
  --save-result selected.json
codess query events --dir /path/to/project --result-input selected.json \
  --expand interaction --save-result context.json
codess query cite --dir /path/to/project --result-input context.json \
  --summary-file summary.md --processor-id analyst/manual-1 \
  --save-investigation investigation.json
```

## Direct Database Access

Each source-system store is a SQLite database and may be inspected read-only
with the SQLite command line, Python's `sqlite3`, database browsers, notebooks,
or other query tools. The physical schema is
`schema/coschema/sqlite/schema.sql`; the
[Query Contract](CoSchema.md#14-query-contract) explains the logical access
surface.

Open a store without allowing writes:

```bash
sqlite3 'file:/absolute/path/to/sessions_codex.db?mode=ro'
```

Examples:

```sql
SELECT source_system_id, COUNT(*) AS sessions
FROM sessions
GROUP BY source_system_id;

SELECT event_kind, actor_kind, COUNT(*) AS events
FROM events
GROUP BY event_kind, actor_kind
ORDER BY events DESC;

SELECT sequence_no, event_kind, actor_kind, content
FROM events
WHERE session_id = ?
ORDER BY sequence_no;
```

Direct SQL is useful for exploratory joins, distributions, query-plan review,
and access to physical fields. The Codess query interface is preferable when
you need Project selection, cross-store composition, stable structured output,
Interaction expansion, or evidence resolution.

## Data Safety

Vendor session stores can contain source code, prompts, tool input and output,
local paths, credentials, and other private material.

- Codess opens vendor databases read-only and does not vacuum or modify them.
- The default raw mode records Source identity without making a complete raw
  copy.
- Content bounds prevent accidental ingestion or display of unbounded records.
- Redaction and content policies are available but do not replace review.
- Export or third-party indexing must be explicitly selected.
- `.codess/` data should not be committed to a Project repository.

The [Raw Evidence](Operations.md#9-raw-evidence) procedure covers explicit
capture. Storage deletion remains a reviewed maintenance operation.

## Documentation Map

| Document or area | Focus |
|---|---|
| [Codess](Codess.md) | Problem, solution, product capabilities, terminology, boundaries, and longer-term vision |
| [Operations](Operations.md) | Installation, source locations, normal execution, diagnosis, and maintenance commands |
| [Functional Design](Designs.md) | Decided functional behavior, rationale, invariants, and explicitly optional directions |
| [Implementation Plan](CoPlan.md) | Software layers, vendor processing, common mapping, database lifecycle, CLI construction, test coverage, current state, code review, and task list |
| [CoSchema](CoSchema.md) | Common entities, relationships, fields, vocabularies, and query/store contracts |
| [Claude Code Source Schema](CCSchema.md) | Claude Code storage, records, selective access, mapping, and limitations |
| [Codex Source Schema](CodexSchema.md) | Codex storage, records, selective access, mapping, and limitations |
| [Cursor Source Schema](CursorSchema.md) | Cursor storage, records, selective access, mapping, and limitations |
| `schema/` | Executable SQL, JSON, mapping, policy, and fixture contracts |
| `catalog/` and the configured registry | Project selections, source bindings, observations, reports, and receipts |
| `experiments/` | Bounded investigations that are not part of the accepted design or implementation plan |

## Release Notes

### v0.0.1 — Initial Three-Vendor Prototype

Codess v0.0.1 is the first integrated pre-release of a local investigation
system for coding-assistant Sessions. It converts locally retained records
from Claude Code, Codex, and Cursor into regular, provenance-preserving stores
that can be searched individually or together.

The release establishes the core architecture and a working path from vendor
evidence to bounded investigation results. It does not claim complete support
for every vendor release, replace the vendors' own stores, or provide a hosted
analytics service.

#### Release Capabilities

- **Specialized decoding for three source systems.** Claude Code JSONL, Codex
  rollout JSONL, and selected Cursor SQLite records are accessed through
  source-specific discovery and decoding paths. Codess supports the record
  shapes observed and validated during development, while retaining unknown
  or source-specific evidence rather than claiming that every vendor structure
  has an exact common equivalent.

- **Project and Session discovery.** Codess associates locally retained
  Sessions with repository-oriented Projects and records the contributing
  source systems, directories, workspaces, and Source observations. It can
  recognize selected workspaces and worktrees without treating every nested
  directory as a separate Project, but it does not attempt fuzzy identification
  of unrelated clones or automatically merge repositories that lack sufficient
  identity evidence.

- **A regular but provenance-preserving data model.** CoSchema represents
  Projects, Sources, Sessions, Interactions, Model Turns, Events, Actors,
  tools, models, Artifacts, and their relationships in constrained SQLite
  databases. Common fields support cross-vendor work while source types,
  source values, locators, and mapping evidence remain available when
  normalization would otherwise conceal meaningful differences.

- **Transactional Project store sets.** Each source system contributes a
  separate database to a validated Project store set. Replacement is
  transactional, and an incomplete or invalid conversion is not published as
  current. This release does not maintain one continuously growing global
  content database; several selected Project store sets are composed at query
  time.

- **Structured Session orientation.** Queries can summarize available
  Sessions, time coverage, Event and content volumes, Actors, tools, models,
  and source-system participation. These are measurements of retained local
  evidence, not complete measures of everything transmitted between a harness
  and a remote model.

- **Bounded Event and content search.** Events can be selected by Project,
  source system, Session, Interaction, Model Turn, Event kind, Actor kind,
  content role, origin, tool, model, status, time, Artifact, stable identity,
  or literal content. The current search is structured and bounded; it is not
  fuzzy search, embedding search, a general raw-source search engine, or an
  unrestricted full-corpus scan.

- **Interaction reconstruction.** A selected Event can be expanded to its
  recorded Interaction or Model Turn, or examined with nearby Session Events.
  Reconstruction follows stored sequence and explicit relationships;
  timestamps or textual resemblance are not silently treated as proof of
  causality.

- **Tool and automation evidence.** Supported tool invocations, results,
  statuses, permission outcomes, commands, and Artifact references are
  retained and linked where the vendor supplies adequate identifiers. Codess
  does not invent a successful result, failure, or parent relationship when
  the source evidence is absent or ambiguous.

- **Agent, context, and compaction evidence.** Supported parent and delegated
  Session relationships, context records, summaries, and compaction bodies are
  preserved when present in vendor data. Codess can only expose planning,
  agent, subagent, harness, or model traffic that the local source actually
  records; it is not a proxy capturing the complete network exchange.

- **Observed model configuration.** Exact model names and supported provider,
  family, revision, reasoning-effort, speed-tier, service-tier, and mode values
  can be queried when directly recorded or justifiably inherited. Missing
  settings remain unknown rather than being inferred from unrelated defaults
  or current product behavior.

- **Cross-Project and cross-vendor investigation.** Explicitly selected
  Project store sets can be queried as one bounded scope with deterministic
  ordering and retained Project, Source, Session, and snapshot identity. The
  release does not yet publish standardized merged SQLite, Parquet, or DuckDB
  products.

- **Reproducible query results.** Canonical query requests, structured JSON
  results, stable row identities, completeness information, facets, and
  derivation metadata can be saved and compared. Results can be narrowed or
  expanded in later operations, but this is not yet a general-purpose query
  language or workflow orchestration system.

- **Evidence-bound summaries.** A human, model, or external process can bind a
  summary to a saved result and record its processor identity. Codess preserves
  the relationship between the selection and the resulting analysis; it does
  not automatically judge, narrate, or rate the underlying development work.

- **Direct analytical access.** Individual stores can be queried read-only
  through SQLite and consumed by Python, notebooks, database browsers, or other
  analytical tools. JSON Lines and CSV output support external processing, but
  this release contains no built-in graphical interface, dashboard,
  visualization service, or notebook package.

- **Resource and content controls.** Configurable bounds cover Source size,
  Event counts, context bodies, retained content, and query output. Exceeding a
  bound is treated as evidence to inspect—potentially a changed vendor format,
  misclassification, external payload, or truncation condition—not merely as
  permission to discard arbitrary content.

- **Raw-evidence choices without mandatory duplication.** The normal reference
  mode records Source identity and update evidence without copying every
  complete vendor record. Explicit capture modes can retain exact raw objects
  for investigations that require them, but raw capture is not inserted
  wholesale into searchable tables and is not intended as routine archival
  duplication.

- **Integrity and provenance checks.** Released schema files, mappings,
  manifests, snapshots, and retained raw objects have explicit identities and
  verification paths. Integrity checks detect accidental mismatch; they are
  not presented as protection against an attacker able to rewrite both the
  database and its verification metadata.

- **Catalog and refresh operation.** Maintained Project records can carry
  source bindings, annotations, review status, observations, and refresh
  receipts. Refresh can assess and validate a Project before publishing an
  update, but scheduling and unattended recurring execution remain
  responsibilities of external operating-system tools.

- **Executable contracts and validation fixtures.** The repository includes
  SQLite DDL, JSON contracts, mapping profiles, controlled vocabularies,
  representative fixtures, hazard cases, and automated unit, contract,
  adapter, integration, and scale tests. Real vendor Sources remain a separate
  validation layer, and coverage is not yet equally strong across every vendor
  feature and command path.

#### Important Boundaries

Codess operates on locally retained evidence. It cannot recover omitted
messages, remote-only activity, deleted vendor data, or traffic that was never
written to a local store.

Codess is an investigation and extraction system, not a billing monitor. It
may report recorded tokens and activity measures, but it does not estimate
prices, quota balances, reset windows, or account-level utilization.

Vendor formats evolve independently. This release preserves source values and
mapping diagnostics so unsupported shapes can be identified and improved
without silently forcing them into misleading common categories.

Session data may include private prompts, source code, file paths, commands,
tool output, credentials, or other sensitive material. Local operation is the
normal boundary; publication, remote indexing, or third-party processing
requires explicit review.

#### Release Status

This release is suitable for controlled local evaluation, decoder validation,
Project and Session investigation, and development of downstream research
workflows. It remains a pre-release while cross-vendor classification, runtime
mapping conformance, selective Cursor processing, performance workloads, and
structured operational reporting continue to mature.
