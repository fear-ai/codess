# Codess design decisions

This document records the design decisions behind the implemented CoSchema v2
foundation and the remaining corpus/catalog/query work. `CoSchema.md`,
`schema/coschema/contract.json`, and `schema/coschema/sqlite/schema.sql` are the
authoritative logical description and executable layout.

The immediate goal is reliable ingestion and comparison of recent, active work
from Claude Code, Codex, and Cursor. Exhaustively finding every historical
session or repository is less important than preserving evidence, mapping the
three vendors consistently, rebuilding reproducibly, and supporting mixed
queries.

## 1. Decisions and priorities

### Implemented foundation

1. **Keep two public compatibility versions.** Version the Codess software and
   a durable CoSchema store-format package. Record implementation and upstream
   versions as provenance, but do not operate seven release trains.
2. **Build immutable baselines rather than migrating derived data in place.**
   Build a new snapshot, validate it, then atomically make it current. Preserve
   the previous snapshot and the exact Codess software identity that reads it.
3. **Separate source evidence, normalized entities, and SQLite layout.** Vendor
   records and mappings belong in vendor documents; functional meanings belong
   here; SQLite tables, indexes, types, and SQL belong in the physical schema
   document and DDL.
4. **Add source, ordering, time-provenance, and lineage concepts.** A session ID
   and timestamp are not sufficient to explain where a row came from or how its
   events should be ordered.
5. **Model an interaction as a graph of events.** One user request can produce
   several model turns, tool calls and results, harness messages, subagents,
   user-input requests, and replies. Do not force that into alternating
   `user`/`assistant` messages.
6. **Prioritize active, owned projects and cross-vendor evidence.** Topical
   directory, ownership, meaningful source records, activity, and mapping value
   all matter. Repository recency alone is a poor selector.

### Accepted removals and corrections

- `release_value` is removed from v2. Its packed integer encoding was
  not a general ordering for SemVer, vendor build identifiers, dates, channels,
  or nonnumeric releases. Retain exact version text and parse into a
  version-specific structure only where a comparison is needed.
- Do not use `Code` versus `IDE` as the meaning of session `type`. Products now
  share storage and code across CLI, IDE, desktop, API, and agent packaging, and
  sessions may concern research, documentation, operations, or review rather
  than code. Use separate product, surface, and purpose dimensions.
- Do not interpret an archive flag as completion. Archive is a vendor lifecycle
  or storage state with vendor-specific semantics.
- Do not treat `assistant` as a model identifier. It is at most a source-format
  content role; the actor and model configuration are separate.
- Do not classify every skill invocation as a slash command. Preserve how the
  invocation was represented and normalize command and skill concepts
  independently.

## 2. Versioning and immutable baselines

### Two managed versions, several recorded facts

Seven independently managed version numbers would create ceremony without
useful compatibility. Maintain only these public versions:

| Managed version | Meaning | Changes when |
|---|---|---|
| `software_version` | Released Codess application, currently `0.2.0` | CLI, reader, writer, adapter, or query behavior is released |
| `store_format` | Durable package containing the common logical schema, SQLite layout/DDL, constraints, and normalized taxonomies | A stored baseline can differ in structure or defined meaning |

Use a lasting format identifier such as `codess.coschema` plus a small monotonic
`format_version`. The complete format package contains the logical field
definitions, canonical DDL, taxonomies/lookup values, required indexes, and
validation fixtures. Its files should have a reproducible package digest. A
reader declares the store-format versions it supports; compatibility is tested
against fixtures rather than inferred from Codess release numbers.

The package can change in a disciplined manner without inventing another
public version for each layer:

- a meaning, required field, relationship, taxonomy, or incompatible layout
  change advances `format_version`;
- a purely operational SQLite index change can update the package digest and
  software release without making old data unreadable; advance the format only
  if exact physical reproducibility or reader assumptions require it; and
- a taxonomy is part of the store contract. If a future taxonomy must evolve
  independently at high frequency, store its vocabulary ID in the data then,
  rather than paying that complexity now.

Everything else is recorded provenance, not a separately governed release:

| Recorded fact | Why retain it |
|---|---|
| `software_revision` | Exact Git/build identity, including dirty state |
| adapter implementation identity | The software release/revision and adapter name already identify shipped mapping code; add a separate adapter package version only if adapters become independently distributed |
| `source_format` and observed harness version | Upstream evidence used for support decisions; these are properties of input data, not Codess versions |
| Python, SQLite, and platform versions | Reproduction and diagnosis; the store package may declare a minimum SQLite capability, but the SQLite runtime is not another Codess release train |
| snapshot ID, policy/configuration digest, and source fingerprints | Identify the exact baseline contents without pretending they are schema versions |

For example, a corrected Codex mapping normally advances the Codess software
version and produces a new immutable snapshot, but does not advance
`store_format` if the resulting records obey the same schema and taxonomy. A
schema or taxonomy change advances the store format. This preserves the useful
distinctions without exposing seven knobs.

Per-vendor logical schemas are not separate common schemas. Vendor documents
describe upstream formats and mappings into CoSchema. A vendor-specific staging
database remains a physical implementation detail. If a vendor adapter later
ships independently, its package may acquire one version then; do not design
that release process prematurely.

### Durable encoding

Encode the store contract at three deliberate levels:

1. Codess SQLite files use fixed `PRAGMA application_id = 0x434F4445`. This permanently marks
   the file family and lets readers reject unrelated SQLite databases quickly.
2. Put the integer CoSchema `format_version` in `PRAGMA user_version`. This is
   the fast physical compatibility check and remains readable from the SQLite
   file header.
3. Repeat `format_id`, `format_version`, package digest, `created_by` software,
   and snapshot identity in `store_meta`; put the same contract plus hashes and
   provenance in the external manifest.

The repetition is intentional: SQLite header fields survive detachment,
`store_meta` is descriptive and queryable, and the manifest can be inspected
without opening any database. Validation must require them to agree. The fixed
application ID and monotonic format integer are the lasting encoding; the
package digest identifies the exact DDL/taxonomy/fixture revision without
creating another human-managed version number.

### Names versus authoritative metadata

Do **not** make a database filename or directory name the authoritative version
record. Encoding every version and provenance fact in a path produces long names,
rename churn, and false confidence when a file is copied. Keep a stable current
location and store authoritative values in both:

- a snapshot manifest, readable without opening SQLite; and
- a small `store_meta` relation inside every database, so a detached file is
  self-describing.

A useful physical layout is:

```text
<project>/.codess/
├── current.json                    # points to one immutable snapshot
└── snapshots/
    └── <created>-coschema<format>/
        ├── manifest.json
        ├── sessions_cc.db
        ├── sessions_codex.db
        ├── sessions_cursor.db
        └── raw/
```

The directory suffix is a human hint only. `manifest.json` and `store_meta`
are authoritative. Keeping vendor names in current DB filenames is reasonable
because it identifies a physical partition; putting mapping or schema versions
in every DB filename is not. A future single database can replace the
per-vendor files without changing the logical model.

### Snapshot contract

Each immutable snapshot should record:

- `software_version`, `store_format`, package digest, software revision, build
  timestamp, Python and SQLite versions, and platform;
- the exact configuration and filtering policy that affects inclusion;
- source identities, sizes, mtimes, content hashes where captured, and adapter
  results or rejection reasons;
- database and sidecar hashes, counts, integrity-check results, and validation
  diagnostics;
- the parent baseline, if any, as lineage rather than as an instruction to
  mutate it; and
- the exact command or reproducible recipe used to build it.

Build into a new temporary directory, close all databases, run integrity and
mapping checks, finalize hashes, make the directory immutable by policy, and
atomically replace `current.json`. Never partially update the current baseline.

### Rebuild versus migration

Normalized transcripts are derived data, so **rebuild is the default**. An
in-place migration can preserve old mapping mistakes, lose raw distinctions,
and make rollback ambiguous. Rebuild from source or a captured raw sidecar when
the logical schema, mapping, or taxonomy changes.

Migration is justified only for information that cannot be regenerated, such
as manual curation, review decisions, annotations, or stable project identity.
Keep that information in a small separately versioned catalog and import it
into a new baseline. For an unusually large corpus, an explicit copy-forward
operation may be implemented, but it must create a new snapshot, retain the old
one, and identify every transformed source row.

Prior baselines remain accessible in one of two ways:

1. the current reader advertises and tests read-only compatibility with that
   store format; or
2. the manifest identifies the Git revision, lockfile, release artifact, or
   environment needed to run the matching older reader.

The writer must refuse an unsupported current store rather than silently
opening or upgrading it.

## 3. Documentation and code boundaries

Keep four layers distinct:

| Layer | Contains | Does not contain |
|---|---|---|
| Functional model (`Designs.md`) | Entity meanings, relationships, invariants, vocabularies, selection policy | SQLite types, index names, SQL |
| Vendor documents (`CCSchema.md`, `CodexSchema.md`, `CursorSchema.md`) | Upstream records, evidence, vendor semantics, mapping and limitations | Claims that a vendor field is universally meaningful |
| Logical schema (`CoSchema.md` and `schema/coschema/contract.json`) | Common fields, nullability, cardinality, identity and lineage | SQLite-specific optimization |
| Physical schema (`schema/coschema/sqlite/schema.sql` plus a layout document) | Tables, columns, SQL types, constraints, indexes, pragmas, file partitioning | Product behavior and vendor interpretation except as comments/links |

Code should mirror this boundary: vendor readers and mapping profiles, common
domain records and validation, then a `storage/sqlite` implementation. SQL
column names such as `session_pk` should not leak into application concepts
such as “session identity.” Query code should target a storage interface or
versioned read model, not repeat vendor mapping rules.

Indexes are physical access paths, not functional fields. After the logical
schema and representative mixed queries are fixed, the layout should normally
enforce/index these lookup shapes:

- unique source-system plus vendor-session identity;
- unique session plus `sequence_no`, and source plus record/block position;
- event lookup by session order and by non-null occurrence time;
- source lookup by normalized URI/path and source revision/fingerprint;
- tool invocation lookup by session/source call ID and normalized tool name;
- artifact lookup by project plus relative path or content identity; and
- parent/causation, interaction, model-turn, and parent-session foreign keys.

Do not add indexes for every JSON key or speculative filter. Record actual query
plans and corpus cardinality in the physical-layout review. Repeating a full
`source_file` string on every event is neither a substitute for a Source entity
nor a good indexing strategy.

## 4. Core entities and relationships

These are logical concepts, not a commitment to one table per item.

### Source

A **Source** is a bounded unit of upstream evidence inspected by Codess: for
example one Claude or Codex JSONL transcript, one Cursor SQLite database, or one
API export. It answers “what evidence did this normalized record come from?”

A Source is not a vendor, project, session, or code file merely mentioned in a
chat. One source may contain one session, as transcript files commonly do, or
many sessions, as a Cursor database does. A session may also be reconstructed
from several source revisions or files.

Source identity has two levels:

- a logical source identity: source system plus URI/path or upstream identity;
- an observed source revision: size, mtime, content fingerprint where captured,
  observation time, and extraction status.

If a file changes, it remains the same logical source but yields a new observed
revision. Normalized records link to the revision and source record position so
their lineage is reproducible. A missing source value means no normalized
source link was established; diagnostics must say whether evidence was absent,
unsupported, invalid, redacted, or not retained.

### Interaction versus turn

An **Interaction** is a user-intent grouping inside a session. It starts with a
direct user request or another evidenced initiating input and contains the
events performed to pursue that request: model output, tool calls/results,
harness actions, subagent work, clarification requests, and clarification
replies. It answers “which user goal was this work serving?”

An interaction is broader than a model call. It can contain many model calls
and tool cycles. A harness request for more input and the user's answer normally
remain in the same interaction. A later independent request starts another.
Where a vendor does not expose boundaries, the grouping is nullable or marked
as inferred with method/confidence; it must not be presented as upstream fact.

**Turn** is too overloaded to use unqualified. Vendors may call a whole
user-to-assistant cycle, one inference, or a tool loop a “turn.” In the common
model use **Model Turn** (or eventually **Inference**) narrowly: one evidenced
request to a model and its emitted response/requested actions. A tool result may
lead to another Model Turn within the same Interaction. Preserve any vendor
`turn_id` and vendor meaning separately. If the source does not expose model
invocation boundaries, do not manufacture Model Turns merely by alternating
message roles.

Example:

```text
Interaction: "Fix the failing parser test"
  Model Turn 1: proposes inspection and requests file/test tools
  Tool calls/results: reads files and runs the test
  Model Turn 2: proposes and requests an edit
  Tool call/result: applies the edit
  Model Turn 3: reports verification
```

### Actor

An **Actor** is the identifiable producer or requester responsible for an
event. It answers “who or what originated this event?” Actor is independent of
the serialized message role and of content purpose.

Actor kinds include human, model, harness, agent/subagent, skill, tool, system,
and developer. An actor can be a durable participant (the human user), a scoped
runtime instance (a subagent), or a configured service identity (a particular
model configuration). `assistant` is not an actor identity; it is an upstream
role label that may have been used for model, harness, or agent-generated
content. When the true actor is not supported by evidence, use unknown rather
than interpreting a source role literally.

Do not create actors merely because a label exists. A skill is an actor only
when evidence treats a scoped skill component as producing or requesting the
event; otherwise it is an origin or invoked resource. Likewise, `system` and
`developer` may be source content roles whose actual actor is the harness or an
unknown configuration author.

Actor, content role, and origin stay separate. For example, a harness actor can
inject instruction content with `harness_injected` origin; a model actor can
request a tool; and a tool actor can return result content.

### Artifact

An **Artifact** is a stable referent that work reads, creates, changes, or
mentions: a project-relative file, document, repository/commit state, URL,
notebook, image, generated patch, or similar object. It answers “what subject or
output did this work affect?”

Artifact identity is separate from an observation/version of its content. A
path can move, a file can change hash, and two paths can refer to the same
repository object. Record the strongest available identity and evidence:
project plus relative path, URI, repository plus commit/object ID, content hash,
or vendor object ID. Link events or tool invocations to artifacts with an
operation such as read, create, modify, delete, execute, or mention and a
confidence/source.

A transcript file can occupy two roles without conflation: it is a Source when
Codess ingests it as evidence, and an Artifact if a session itself edited or
discussed that file. A tool result body is event payload, not automatically an
Artifact; it becomes one when it identifies or creates a durable referent.

### Remaining concepts

- **Project**: a stable work identity, independent of its current local path.
- **Project location**: a machine-local observed root, worktree, subdirectory,
  or vendor-reported working directory.
- **Session**: one vendor/harness conversation identity and its lifecycle.
- **Event**: an ordered observation such as content, a tool request/result,
  lifecycle change, context operation, or audit fact.
- **Tool invocation and result**: a request plus zero or more result fragments,
  correlated by a vendor call ID or inferred local identity.
- **Model configuration**: provider/model and configurable inference settings,
  referenced as a session default and optionally overridden per model turn.

Important cardinalities and lineage rules:

- A project can have many locations and sources; a source can yield many
  sessions, as Cursor databases do.
- A session has one source-system identity but may receive records from more
  than one source file or revision. Source ownership must be explicit.
- One interaction can contain many user replies, model turns, tool calls,
  results, subagent actions, and harness events. A request for more user input
  and a structured-choice reply are linked events, not evidence that the first
  interaction ended.
- Events have an authoritative per-session order and may additionally reference
  `parent_event`, `caused_by_event`, `interaction`, `model_turn`, and tool-call
  identities. These links form a graph; they are not all parent/child nesting.
- A session may reference a parent session with `session_relation_kind` such as
  `subagent`, `fork`, `resume`, or `unknown`, plus source and confidence. The
  link is nullable. Claude sidechain evidence supports some parent links;
  current Codex evidence does not justify inventing one.

## 5. Identity, vendor, product, and harness

`session_id` should never stand alone as the global identity. Several products
from one vendor can share code or storage, and the same upstream identifier can
be meaningful only within a source system.

Recommended identity dimensions are:

| Field | Purpose |
|---|---|
| `session_pk` | Internal stable key with no vendor meaning |
| `vendor_name` | Organization or ecosystem, for example `anthropic`, `openai`, `cursor` |
| `product_name` | User-facing product, for example `claude-code`, `codex`, `cursor-composer` |
| `harness_name` | Producing runtime/surface, such as CLI, desktop app, IDE extension, or agent runner |
| `storage_format` | Transcript/database family actually parsed |
| `vendor_session_id` | Exact upstream identifier |
| `source_system_id` | Namespace that makes the upstream identifier unique |

Uniqueness should be based on `(source_system_id, vendor_session_id)`, not
`(vendor, session_id)`. “Harness” is useful but can change packaging; the
source-system identity should be defined by evidence from the storage format.

Replace the current `type = Code|IDE` with independent open dimensions:

- `surface_kind`: `cli`, `ide`, `desktop`, `api`, `agent`, or `unknown`;
- `session_purpose`: `coding`, `review`, `research`, `documentation`,
  `operations`, `general`, or `unknown`; and
- optional product capabilities, inferred only when evidence supports them.

These should be controlled open vocabularies: common values are documented and
validated, but unknown vendor values remain representable.

## 6. Paths, sources, and files

### Project paths

An absolute `project_path` is useful for locating a live checkout and joining
local vendor indexes. It is also machine-specific, private, unstable after a
move, sensitive to symlinks and case normalization, and ambiguous for
worktrees, monorepo subdirectories, and sessions started outside a repository.

Partition it into:

- `project_id`: stable catalog identity;
- `source_cwd`: exact vendor-provided string, if present;
- `resolved_project_root`: observed canonical root on this machine;
- `project_relative_cwd`: portable path below that root;
- `location_uri` or machine-local location record rather than a universal
  absolute path;
- `path_match_method`: `exact`, `vendor_index`, `git_root`, `ancestor`,
  `manual`, or `unknown`; and
- `path_match_confidence`, without converting uncertainty into false identity.

Git remote identity, repository UUID, or content/commit evidence can help
correlate moved checkouts, but none should automatically merge forks or
uncommitted worktrees.

### File meanings

The current names `file_path` and `source_file` conflate different resources.
Use distinct concepts:

- `source_uri`/`source_path`: transcript or vendor database read by Codess;
- `storage_relpath`: source path relative to its configured vendor root;
- `cwd_path`: working directory reported for a session or event;
- `artifact_path`: code or document referenced by an event/tool;
- `artifact_relpath`: preferred portable path relative to a project root; and
- `observed_absolute_path`: optional local evidence when it adds value.

An event may reference multiple artifacts, so artifact relationships should
eventually be rows rather than one `file_path` column. Preserve the source path
at Source level and link events to the source record/offset instead of repeating
the same unindexed string on every event.

### Missing source and file evidence

Missing is not a single condition. Record whether a value was absent upstream,
not supported by the adapter, rejected as invalid, redacted, unresolved, or not
captured by policy. Prefer a compact diagnostic/status on the source or mapping
result rather than sentinel strings in functional fields. `NULL` means no
normalized value; the mapping diagnostic explains why when that distinction is
important.

## 7. Time, ordering, and observation

### Session and event time

Store `started_at` explicitly and allow it to be `NULL`. Do not substitute a
file mtime into the same field. Suggested time facts are:

| Field | Meaning |
|---|---|
| `started_at` / `ended_at` | Vendor-supported session bounds; nullable |
| `event_at` | Vendor-supported event occurrence time; nullable |
| `source_mtime` | Filesystem modification time observed for a source |
| `observed_at` | Time Codess inspected the source |
| `ingested_at` | Time the normalized baseline was built |
| `effective_at` | Optional derived application fallback for display/filtering |
| `effective_at_basis` | `event`, `session`, `source_mtime`, `ingested`, or `unknown` |

Where needed, retain `timestamp_raw`, precision, timezone/basis, and source
field. A generic column named only `timestamp` hides whether it is occurrence,
observation, or filesystem time. Source mtime is valuable for incremental scan
and a fallback UI sort, but it is not evidence that a session started then.

### Ordering

`sequence_no` is required and is authoritative within a session/source
revision. Timestamps can be missing, equal, rounded, delayed, or emitted out of
order; they are unsuitable as the only order key. Preserve source record
position and emitted block position so one source record that normalizes into
several events remains deterministic. A useful ordering tuple is
`(source_order, record_order, block_order)`, exposed as a dense session
`sequence_no` after mapping.

Cross-session chronology remains probabilistic. Correlation queries should use
time plus uncertainty, project/artifact evidence, and source provenance rather
than manufacture a global sequence.

## 8. Core fields, specialized data, JSON, and “not recorded”

JSON is appropriate for sparse, evolving, namespaced vendor attributes and for
configuration whose exact keys must survive mapping. It avoids a schema change
for every rare upstream field. It is poor for stable query predicates because
key names drift, types are weak, constraints and indexes are harder to manage,
and unrelated meanings accumulate in one object.

Use four retention tiers:

1. **Core field** — common, stable, semantically defined, and regularly queried.
2. **Specialized relation** — repeated, multivalued, independently identified,
   or important to one domain such as model configuration, tool calls, artifact
   links, context operations, or status transitions.
3. **Namespaced extension JSON** — sparse vendor facts retained for future use,
   with `extension_namespace`, `extension_schema`, and version. Values must have
   documented types and must not silently override core fields.
4. **Raw-only or not retained** — exact evidence remains in the raw source or
   sidecar, but is intentionally absent from the normalized store.

“Not recorded” must therefore be precise. It can mean `not provided`,
`unsupported`, `not captured`, `redacted`, `invalid`, `derivable`, `duplicate`,
or `discarded by policy`. Vendor mapping documents should maintain a field
disposition table with source field, type, example shape, target tier/field,
mapping version, and reason. This is more useful than an unqualified “not
recorded.”

Alternatives to JSON are typed columns, child relations, a document store, or
entity-attribute-value rows. Prefer typed columns for core facts and child
relations for repeated values. EAV should not be the common escape hatch: it
moves schema problems into runtime strings and makes validation and queries
harder. JSON Schema may validate an extension document, but the external
`jsonschema` repository is only a reference/example project; it is not a reason
to make JSON Schema central to Codess.

## 9. Session lifecycle, status, and models

### Releases

`release_value` is removed. Replace ambiguous `release` with the explicit version
fields in section 2. Preserve an exact harness version string even when it
cannot be ordered. If comparisons are required, use a parser declared for that
specific vendor/version scheme and retain the original string.

### Archive and lifecycle

Use `archive_state = active|archived|unknown` plus `archive_source` and the
observed source location. Known meanings differ:

- Cursor supplies `isArchived`, an explicit product/session classification.
- Codex uses active and archived session directories. Location supplies a
  storage/lifecycle observation; active currently wins on a duplicate ID. It
  does not prove completion or deletion.
- Current Claude ingestion has no equivalent common archive evidence.

Keep normalized completion/status separate. For statuses generally, retain
both `source_status` (exact vendor value) and `normalized_status` from a small
taxonomy such as `pending`, `running`, `succeeded`, `failed`, `denied`,
`cancelled`, `incomplete`, or `unknown`, with the mapping version. This applies
to tool calls and lifecycle operations; one generic session `status` should not
collapse all of them.

### Parent sessions

A nullable parent-session link is useful for subagents, forks, resumptions, and
continuations, but these are different relationships. Store the relation kind,
source evidence, and confidence. Do not infer parentage solely from time,
similar text, archive location, or a shared project. Unresolved upstream parent
IDs may be retained as external references until their session is ingested.

### Model configuration

Model identity can change within a session. Store a session default and allow a
model-turn override. Candidate fields are:

- `provider`, `model_family`, `model_name_exact`, and optional model revision;
- reasoning/effort setting;
- speed, service, priority, or latency tier where configurable;
- interaction mode or agent mode;
- sampling parameters where actually exposed;
- context-window or capability declarations only when sourced, not guessed;
- exact source configuration in a namespaced extension.

`assistant` does not mean a model. A model is an actor with a model
configuration. A harness or agent can emit assistant-shaped records without
those records being direct model output.

## 10. Events, roles, commands, tools, context, and memory

### Vendor and normalized event types

Retain both `source_record_type`/`source_record_subtype` and a normalized,
versioned classification. The common taxonomy should cover the large majority
of behavior; vendor-only variants remain extensions or explicitly unmapped
diagnostics rather than forcing every upstream spelling into the common enum.

A hierarchical vocabulary is clearer than the current cross-product of
`event_type` and `subtype`. Initial families should include:

- `message.prompt`, `message.response`, `message.context`, `message.instruction`;
- `tool.call`, `tool.result`, and `tool.status`;
- `interaction.user_input_request`, `interaction.user_input_reply`, and
  `interaction.structured_choice`;
- `lifecycle.abort`, `lifecycle.archive`, and `audit.permission_decision`;
- `context.compact`, `context.inject`, and `context.remove`; and
- `memory.read`, `memory.write`, `memory.update`, `memory.delete`, and
  `memory.load`.

Compaction is a **context operation**, not automatically a memory operation.
It may produce a summary used as future context, while memory has a scope and
lifecycle beyond shrinking a context window. Model memory operations separately
with scope (`session`, `project`, `user`, or vendor-defined), target/reference,
and source evidence. Do not claim a definitive memory write when the source
only exposes a compact boundary.

### Roles are multivariate

The source roles `user` and `assistant` are repeatedly violated by harness
inputs, project instructions, skills, agent output, tool results, and developer
messages being serialized into message-shaped records. Use independent axes:

- `actor_kind`: `human`, `model`, `harness`, `agent`, `skill`, `tool`,
  `system`, `developer`, or `unknown`;
- `content_role`: `instruction`, `prompt`, `response`, `context`,
  `tool_request`, `tool_result`, `status`, `memory`, or `audit`;
- `origin_kind`: `direct_user_input`, `harness_injected`,
  `project_instruction`, `skill_generated`, `agent_generated`,
  `tool_generated`, `model_generated`, or `unknown`; and
- participant/actor identity when known.

Retain the exact vendor role separately. These dimensions should be nullable or
`unknown` when the source does not prove them; mapping a record labeled `user`
to a human actor without checking its origin would preserve the current error.

### Commands and skills

Classify input representation independently:

- `natural_language`, `slash_command`, `command_palette`, `skill_invocation`,
  `structured_choice`, `user_reply`, or `harness_instruction`;
- parsed `command_namespace` and `command_name` when syntax proves them; and
- exact invocation text in content/raw evidence.

Claude Code skills may be invoked through slash-like text or a `Skill` tool,
but a skill is not always a slash command. Codex and Cursor have their own
command or mode mechanisms. Normalize the semantic skill invocation when
known, retain its source representation, and do not infer one from a leading
slash alone if the harness treats the text as ordinary content.

### Tool names and call/result data

Tool names must remain free text because MCP servers, plugins, skills, and
vendor releases create names dynamically. A closed enum would reject real
data. Add an optional registry/alias layer with canonical name, namespace,
provider, category, and version; retain `source_tool_name` exactly. Common tools
can be seeded and validated without making the seed list exhaustive.

`tool_input` and `tool_output` are unclear when several components participate
or when a harness calls subprocess execution “tool calling.” Prefer a Tool
Invocation concept with:

- source call ID, canonical/source tool identity, requesting actor/event, and
  optional parent invocation;
- exact structured request arguments (`input_json`) plus bounded display text;
- start/end times and source/normalized status;
- zero or more Tool Result records, each with sequence, producing component,
  text/JSON/artifact reference, error evidence, and status; and
- an invocation subtype such as `harness_capability`, `mcp`, `process`,
  `subagent`, or `unknown` when supported.

The harness-mediated capability is the tool call. An OS process started by that
capability is a child execution fact, not necessarily a second tool call.
Avoid duplicating result content in both generic `content` and `tool_output`;
define one canonical payload with typed projections for display and query.

## 11. Raw evidence and sidecars

Do not put full `source_raw` blobs in the main query database. They enlarge
backups, mix sensitive evidence with normalized search data, and make retention
and redaction all-or-nothing. Raw capture should be explicit and policy-driven.

The older local `SessionRec.md` proposed a useful hybrid—normalized SQLite plus
raw sidecar JSONL. Retain the hybrid architecture, but do not make converted
JSONL the raw format: it cannot preserve a Cursor SQLite source byte-for-byte
and may discard unknown fields, ordering, encoding, or database structure.

### Proposed `codess.raw/1` format

Treat this as part of the CoSchema store package, not another regularly managed
release train. `codess.raw/1` is a fixed format namespace; create `/2` only if a
future reader cannot understand the layout.

```text
~/.codess/raw/codess.raw-1/
├── objects/
│   └── sha256/ab/<uncompressed-content-sha256>.zst
└── locks/                         # writer coordination; not snapshot content

<snapshot>/
├── manifest.json
├── raw-manifest.jsonl             # references objects used by this snapshot
└── raw/objects/...                # present only in a sealed export
```

An object contains the exact bytes of one consistently observed source
revision, compressed with Zstandard. Its identity is the SHA-256 of the
**uncompressed** bytes. The raw manifest also records the stored-object hash,
compression, sizes, and media/storage format so corruption can be distinguished
from a changed source. Never use the original filename as the object path.

Each `raw-manifest.jsonl` begins with one header record, followed by one record
per observed Source revision. A representative source record is:

```json
{
  "record_type": "source_revision",
  "source_revision_id": "srcv_...",
  "source_system": "cursor-composer",
  "storage_format": "sqlite",
  "source_locator": "cursor-user-global/state.vscdb",
  "observed_at": "2026-07-13T22:00:00Z",
  "source_mtime_ns": null,
  "source_size": 42819584,
  "availability": "captured",
  "capture_method": "sqlite-backup",
  "consistency": "transactional-snapshot",
  "object_id": "sha256:<uncompressed-content-sha256>",
  "stored_sha256": "<compressed-object-sha256>",
  "compression": "zstd",
  "uncompressed_size": 42819584,
  "stored_size": 7182640,
  "redaction": "none"
}
```

Numeric values above illustrate JSON types, not defaults. Omit or use `null` for
an unknown fact; never write a fabricated mtime or size. Define the JSONL record
schema and allowed values in the CoSchema package. Keep machine-sensitive
absolute paths in a private location mapping where possible; the portable
locator should be relative to a configured source root.

`object_id` is location-independent. A resolver finds it first in a sealed
snapshot and then in the configured central raw store; the manifest does not
hard-code a machine path.

Capture rules differ by storage format:

- Claude/Codex JSONL and exports: capture the exact file bytes after a stable
  size/mtime check or open-file snapshot; record whether the source changed
  during capture.
- Cursor SQLite: use the SQLite backup API or a vendor-safe read transaction so
  WAL contents are included consistently. Copying only the live main DB file is
  not a valid raw snapshot.
- API/stream sources: preserve the exact received body or framed records plus
  transport metadata needed to interpret them; do not claim byte identity with
  server-side data that was never received.

The normalized Source revision stores record locators such as JSONL line/byte
position or Cursor table/key identity. Whole-file Zstandard objects are enough
initially because ordinary queries use normalized SQLite; reparsing can stream
the raw object. Add chunking or a seek index only after measured random-access
need.

### Capture and portability modes

- `none`: normalized data only; manifest records that raw evidence was not
  retained.
- `reference`: record source identity/fingerprint and external location without
  copying bytes. Useful locally but not independently reproducible.
- `capture`: place exact bytes in the central content-addressed store and pin
  them from the snapshot manifest.
- `seal`: hardlink, reflink, or copy all pinned objects into an exported
  snapshot so it is self-contained; verify every hash afterward.

The central object store deduplicates a global Cursor database and identical
transcripts instead of copying them into every project store. Garbage
collection may remove only objects unreferenced by retained manifests. Apply
permissions, encryption, retention, and deletion policy to raw objects
separately. A redacted derivative is a different object/class and must never be
labeled exact raw evidence.

## 12. Project inventory and selection policy

### What the inventory is

The central registry should be a reviewable **catalog**, not an accidental log
of every scan/test path and not proof that a project deserves ingestion. Keep
these dimensions separately:

- `topic`: the first controlled grouping such as `Code`, `Claude`, `Spank`,
  `WP`, or `ZK`, derived initially from the `~/Work` subtree but editable;
- `ownership`: `own`, `reference`, `external`, `mixed`, or `unknown`;
- `activity_state`: `active`, `dormant`, `archived`, or `unknown`;
- `selection_state`: `priority`, `candidate`, `fixture`, `deferred`,
  `excluded`, or `needs_review`;
- source evidence per vendor, meaningful session counts, last observed event,
  last source change, and mapping diagnostics;
- repository evidence such as Git root, last commit, worktree state, and remote,
  without assuming a recent upstream commit means recent personal work; and
- explicit review notes and decisions, kept separately from reproducible scan
  facts.

Local project identity and remote repository identity are separate. For each
remote, store a dated observation: configured URL, checked time, result
(`available`, `not_found`, `access_denied`, `redirected`, or `unchecked`),
observed canonical URL, visibility/archive facts when available, and checking
credential/profile identity without secrets. A 404 may mean deletion, rename,
transfer, or inaccessible private data. It must never delete or disqualify a
local project automatically. Old lists of repositories in the `wkarshat`,
`fear-ai`, `tearodactyl`, or `zerocurrencycoin` accounts/organizations are
candidate evidence only until checked again.

Scanning updates observed facts. A review operation updates curation. Ingestion
uses an explicit saved selection policy or selection set. Tests must always use
an isolated registry; temporary test projects must never enter the personal
catalog.

### Reference collections and topical defaults

Most known OSS/reference collections are below path segments `sOSS`, `Claws`,
and `ZKs`. Current code already excludes the exact prefixes `Spank/sOSS`,
`Claw/Claws`, and `ZK/ZKs` from ordinary candidate discovery (and also has
other review/reference exclusions). Preserve those defaults, generalize the
catalog classification to recognizable collection segments, and allow an
explicit per-project override. A path inside a reference collection is not
owned/active merely because its upstream repository committed recently.

Treat `~/Work/Github` as dormant/reference by default: its local collection is
currently dated by months. A project there requires an explicit review override
to enter the active corpus even if copied or maintenance commits make Git dates
look recent. Continue reporting reference-collection counts separately so they
remain available for fixtures and additional candidates without dominating
rankings.

### Selection order

Rank candidates in this order:

1. owned, active projects with recent meaningful sessions from Claude, Codex,
   or Cursor;
2. projects with evidence from two or more vendors, because they directly test
   schema mapping and mixed queries;
3. recent sources that exercise unsupported records, new harness versions, or
   mapping regressions;
4. compact fixtures selected to cover a vendor feature or source format;
5. dormant owned projects retained for compatibility; then
6. external/reference repositories only when they add a concrete format or
   cross-vendor test.

Filters should include minimum supported harness version **per vendor**, event
recency, source mtime/change size, session/event volume, mapping success,
ownership, topic, and selection state. Apply equivalent filters during scan,
ingest, and query, but retain the raw observed values so policy can change.
Set a vendor minimum only from tested format/capability evidence, not by making
version strings numerically comparable. An unknown version should be flagged
for review and attempted safely; it should not be silently treated as either
supported or obsolete.
WP projects are currently dormant/deferred, not permanently abandoned.
`Code/jsonschema` is external/reference and should be considered only as a
small compatibility/example case, not a priority corpus.

### Review catalog seed

Repository counts and commit-recency totals are deliberately not retained here;
they age quickly and overrepresent reference collections. Repository discovery
and vendor-session discovery remain separate observations. Use
`~/Work/Code/SWEmore/active_work_projects_since_2026-05.csv` as the maintained
active-work candidate input, not Git-repository recency or an old GitHub list.
Its rows seed this review queue, which must be refreshed with current vendor
observations before selection:

| Local candidate | Evidence and current disposition |
|---|---|
| `ZK/Zero400` | Priority: active-work list plus meaningful Claude/Cursor evidence |
| `ZK/zerowalletmac` | Imported compatibility candidate: one current Claude session plus two Cursor sessions linked explicitly from the former `zerowallet400` workspace; direct root/`src` Cursor traces still have no headers |
| `Code/Misses` | Priority candidate: substantial recent work and harness markers; reconcile root identity with the previously discovered nested `petri/petri` project |
| `Code/CodeSess` | Priority: active implementation and `.codess`; locate/validate current sources from all three vendors |
| `Spank/spank-py` | Priority: active-work list, harness markers, meaningful source evidence, and an old store that should be rebuilt |
| `Spank/spank-rs` | Candidate: active-work list and Claude marker; validate whether the `perf` zero-session trace maps to this root |
| `Claude/CContext` | Candidate/path-mapping case: active-work list, weak marker, and current zero-session trace |
| `Claw/setpack` | Candidate: active-work list and meaningful session evidence despite no repository marker |
| `Spank/HECpoc` | Candidate/path-mapping case: substantial local work but current zero-session trace and no marker |
| `ZK/Zebro` | Local active candidate with no harness marker yet; current configured GitHub remote was unavailable, which does not invalidate the local repository |
| `ZK/Requihash` | Local active candidate with no harness marker yet; current configured GitHub remote was unavailable, which does not invalidate the local repository |
| `Codex` | Candidate: recent local work but no harness marker; verify relevant session evidence before inclusion |
| `Github/Schema` | Needs explicit review: present in the CSV, but `Work/Github` is dormant by default and its current zero-session trace is not an ingestion success |

The CSV remains a list of **local active-work candidates**, not a promise that
any recorded remote still exists. The generated catalog therefore marks every
remote `unchecked`; remote availability is updated only by a new, dated
observation and never inferred from an old list.

Supplement the CSV with evidence-driven candidates it does not currently list:
`Code/SWEmore` itself and `ZK/ZeroPerf` remain priority candidates because the
fresh vendor scan found recent meaningful sessions. `WP/harduw` remains a
deferred cross-vendor compatibility baseline. `WP/multiwp`, `WP/must-py`,
`WP/wp`, and `WP/wpages` remain reviewable but dormant. `Code/jsonschema` is an
external/reference fixture only.

The remaining zero-session traces (`Github/skip` and any unresolved paths
above) are discovery diagnostics or path-mapping work, not evidence of usable
session ingestion.

The old personal registry is not reused as catalog truth. The maintained CSV is
now transformed into `catalog/active-work-review.json`, with observed CSV facts,
local availability, remote status `unchecked`, path-derived conservative
curation, and an empty human-review decision kept in separate objects. Refresh
it with `tools/build_review_catalog.py`; then merge current vendor scan evidence
and explicit review decisions without overwriting observations.

### Cross-vendor work on the same code or document

Project-level overlap is only the first signal. To identify code or documents
worked on by more than one coding system, capture artifact relationships:

- project/repository identity and Git commit/tree before and after a session;
- artifact path relative to the project, content hash when safely available,
  and observed operation (`read`, `create`, `modify`, `delete`, `mention`);
- event/session/vendor links and time intervals; and
- confidence and evidence source, avoiding unsupported authorship claims.

Queries can then find the same project, file identity, commit range, or content
hash touched by multiple vendors. Git and tool evidence are stronger than
matching prompt text. Uncommitted changes and concurrent sessions require
explicit uncertainty; Codess should report correlation, not claim which model
authored a line without evidence.

## 13. Seven key directions and execution order

The numbered directions below are also the intended execution order. Each step
establishes the contract or evidence needed by the next; avoid broad historical
ingestion until this path works on a small, representative corpus.

### 1. Establish a durable store contract — implemented

Package the logical schema, SQLite layout/DDL, constraints, required indexes,
taxonomies, validation rules, and fixtures as `codess.coschema`. Define the
manifest and `store_meta`, assign the SQLite application ID, encode the CoSchema
format in `user_version`, declare reader compatibility, and reject unsupported
formats. A detached database must be self-identifying and safely readable by a
known Codess release.

### 2. Finalize CoSchema v2 — implemented

Define Source and Source Revision, Session, Interaction, Model Turn, Event,
Actor, Tool Invocation/Result, Model Configuration, Artifact, and Artifact Link,
including identities, relationships, ordering, time provenance, nullability,
and lineage. Disposition every current field as keep, rename, partition,
specialize, raw-only, or remove. `release_value` is removed and fabricated
fallback values and overloaded fields before writing the new DDL.

### 3. Produce explicit vendor mappings — implemented with evidence gaps

Create field-by-field Claude, Codex, and Cursor mapping matrices. Preserve exact
source types, roles, statuses, model settings, and tool names alongside common
values. Document absent, unsupported, inferred, invalid, redacted, and discarded
evidence. Cover parent/subagent relationships, archive semantics, commands,
skills, tool call/results, context compaction, and memory. Every normalized fact
must be traceable to source evidence and a tested mapping rule.

### 4. Build immutable snapshots and raw capture — implemented

Implement a writer that builds beside the current store, validates the result,
and atomically promotes it without modifying the prior baseline. Implement
`codess.raw/1` for exact JSONL capture and transactionally consistent Cursor
backup, with `none`, `reference`, `capture`, and `seal` modes. Hash sources, raw
objects, stores, and manifests; preserve the matching software identity. Rebuild
derived data by default rather than migrating it in place.

For a clean worktree, software revision is the Git commit. For a dirty
worktree, snapshot identity also includes a SHA-256 over status, the binary Git
diff, and every untracked file's path and bytes; `commit+dirty` alone is not a
reproducible software identity.

### 5. Repair project discovery and cataloging — catalog seed implemented

Permanently isolate test registries and retire the polluted personal registry
as evidence. Seed the clean review catalog from
`active_work_projects_since_2026-05.csv`, then add vendor-session observations.
Separate scan facts from human curation; record topic, ownership, activity,
selection state, mapping quality, and dated remote observations. Treat reference
collections and `Work/Github` as non-active by default, without allowing missing
remotes to invalidate local work.

### 6. Create a small compatibility corpus — implemented with known gaps

The frozen SWEmore, spank-py, and Zero400 set covers Claude, Codex, Cursor, tool
cycles for Claude/Codex, subagents, compaction, mixed-vendor project timing, and
current mapping hazards. Golden fixtures cover same-artifact multi-vendor
queries and shapes absent from the real corpus. Current real evidence does not
contain a Cursor tool-call/result shape or a shared cross-vendor artifact;
those remain explicit gaps rather than reasons for broad historical ingest.

### 7. Deliver useful mixed queries — implemented; correlation enrichment next

Implement and test cross-vendor session/event queries, deterministic ordering,
Interaction and evidenced Model Turn grouping, tool call/result correlation,
source versus normalized status, model configuration, and artifact correlation.
Queries may report that multiple coding systems touched the same project or
artifact, with evidence and confidence, but must not assert unsupported
authorship.

### Remaining maintenance sequence

1. Correlate external artifact `file:` URIs to known catalog project roots with
   explicit evidence and confidence; do not infer authorship.
2. Resolve Codex parent-session support only from direct referential fields.
3. Monitor for a bounded Cursor tool-call/result shape; current Zero400 and
   zerowallet400 samples contain none. Add a hazard/golden fixture before any
   future mapping change.
4. Add a real same-artifact multi-vendor corpus member or richer model settings
   only when current source evidence supplies them.
5. Re-run fixed-point and semantic sampling, then replace the frozen reviewed
   set atomically whenever a mapping or corpus member changes.

Broad historical discovery, ranking refinements, large-scale raw capture, and
additional vendors remain outside this sequence until a concrete consumer or
compatibility gap requires them.
