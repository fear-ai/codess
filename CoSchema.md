# CoSchema v4 candidate

CoSchema is Codess's vendor-neutral logical record model and its current SQLite
store format. Functional meaning is defined by
`schema/coschema/contract.json`; the SQLite layout is defined only by
`schema/coschema/sqlite/schema.sql`. Vendor facts remain in `CCSchema.md`,
`CodexSchema.md`, and `CursorSchema.md`; executable translations are declared in
`schema/mappings/` and implemented by the adapters/store mapper.

## Package and version identity

The format-4 candidate package is `schema/coschema/` plus the three mapping profiles.
`schema/coschema/manifest.json` names and hashes every package file. Runtime
initialization refuses a package whose files do not match that manifest.
Its manifest state remains `candidate`; **CoPlan R1 and R3a/R3b** are the bounded review
checkpoint before release designation or real-baseline promotion. Formats 2/3
remain the currently retained historical baselines during this review.

### Format-3 to format-4 candidate delta

Format 4 is primarily a contract and meaning correction over the existing
physical design, not a wholesale replacement schema.

| Impact | Change | Why it requires review |
|---|---|---|
| Critical | The logical contract now includes `model_configurations`, content links/derivations, event-artifact links, model-turn configuration, event causality/time basis, complete tool relations/status, diagnostic scope, and correlation evidence | Format 3 physically stored most of these but its claimed exhaustive contract omitted them; format 4 makes readers and validators acknowledge the real functional surface |
| Critical | Contract JSON and JSON-extension fields have SQLite `json_valid()` constraints | Invalid Python representations or arbitrary text that previously entered structured columns now fail at write time; adapters must serialize or use a text field |
| Critical | Source record type/subtype and mapping trace mean exact vendor evidence rather than normalized compatibility names | Existing format-3 rows cannot be reinterpreted as exact provenance; they remain historical and corrected rows require rebuilding from source |
| Critical | Source revisions change from mtime/size identity to content-sensitive, non-authenticating update fingerprints, including SQLite WAL state | Session observation IDs and update detection can change even when normalized conversation content does not |
| Significant | Model configuration identity adds family and null-safe uniqueness; occurrence provenance is separated conceptually from reusable configuration values | Duplicate configuration rows reduce, but the final provenance representation remains under **R3a/R3b** review |
| Significant | Vendor mappings add Claude harness/configuration/fork fields, Codex turn/configuration/archive fields, and Cursor permission/subagent fields | Rebuilt counts, turns, archive state, relations, and model/configuration coverage may differ from format 3 |
| Compatibility | Formats 2/3 remain readable; only candidate format 4 is writable by the current writer | Acceptance requires new stores and side-by-side comparison, never an in-place update of retained baselines |

No accepted baseline or approved pointer is changed merely by defining this
candidate.

One monotonic integer versions the whole readable store contract:

- format ID: `codess.coschema`
- format version: `4`
- SQLite `application_id`: `0x434F4445` (`CODE`)
- SQLite `user_version`: `4`
- Codess software version: independent, currently recorded in `store_meta` and
  each snapshot manifest

We do not separately version every table, index, taxonomy, adapter, or vendor
mapping. A change advances the CoSchema format only when the stored contract or
reader requirements change. Adapter corrections normally require a new software
release and rebuilt snapshot, not a new database format.

Once released, packages are immutable. Unknown package or database formats fail
closed. Legacy unversioned stores may be read through the compatibility query
surface but cannot be mutated; rebuild creates v2 stores beside retained
baselines. Format-2 and format-3 stores remain read-only compatibility inputs;
all writes and rebuilds now produce format 4. Format 4 makes the complete
functional DDL surface and JSON obligations machine-verifiable in both
directions; retained format-3 snapshots remain valid historical evidence.

## Core terms

- **Source** — one observed revision of vendor evidence, identified by source
  system, locator, and revision. A source is not a session and need not be
  retained as a raw object.
- **Interaction** — one user- or environment-initiated unit that can encompass
  several model turns, tool calls/results, harness events, and requests for more
  input. Its boundary may be vendor-provided, mapped, inferred, or manual.
- **Model turn** — one bounded model execution within an interaction. It is not
  assumed to equal a displayed message or a user/assistant pair.
- **Actor** — the producer or operative principal represented by
  `actor_kind` (for example human, model, harness, tool, agent, or system).
  `content_role` separately records how content is presented, and `origin_kind`
  records where it came from. This avoids forcing all harness input into
  `user` and all model output into `assistant`.
- **Artifact** — a file, URI, repository object, or other durable object an event
  reads, creates, modifies, deletes, executes, or mentions. Observed absolute
  paths are evidence; project-relative paths are the preferred portable key.

## Functional entities

| Entity | Purpose and identity |
|---|---|
| `projects` | Stable logical project identity plus observed root/cwd, ownership, activity, and selection state |
| `project_locations` / `workspace_bindings` | Machine-local locations and evidence-backed vendor workspace attribution |
| `sources` | Immutable observed source revision; unique by source system, URI, and revision |
| `model_configurations` | Provider/model family/exact name and independently settable effort, speed, service, and mode values; `source_config` retains bounded vendor-field provenance |
| `sessions` | Vendor/harness container; vendor session ID is scoped by source system and may be absent |
| `interactions` | Initiating work unit, ordered within a session, with explicit boundary source/confidence |
| `model_turns` | Model execution, ordered within a session and optionally linked to an interaction |
| `events` | Ordered normalized observation with preserved vendor type/subtype and mapping trace |
| `source_records` | Stable vendor record position and classification within a source revision |
| `content_objects` / typed links | Deduplicated content identities linked to events and source records |
| `processing_runs` / `content_derivations` | Policy/software identity, actions, accepted/rejected inputs and outputs, and rejection reason |
| `tool_invocations` | Requested operation with source/free-text tool name, optional canonical name, input, and status |
| `tool_results` | One or more ordered results linked to an invocation when source evidence permits |
| `artifacts` / `event_artifacts` | Durable objects and evidence-backed operations on them |
| `mapping_diagnostics` | Source-, record-, or field-level loss, rejection, or ambiguity |
| `correlation_assertions` | Reviewable cross-session/project/vendor claims with method, evidence, and confidence |

The exhaustive field, nullability, reference, ordering, range, and vocabulary
definitions are machine-readable in `contract.json`; this document does not
duplicate that list. SQLite compatibility projection columns in `sessions` and
`events` preserve the existing query surface but are not the global identity model.

## Important field decisions

### Identity and paths

`source_system_id` identifies the source/harness namespace; a vendor session ID
alone is not globally meaningful. Product, vendor, harness, storage format, and
surface are separate because vendors reuse storage structures across IDE, CLI,
desktop, agent, and API packaging.

`sources`, `sessions`, and `events` persist deterministic global IDs. Session
identity derives from source-system namespace plus vendor session ID; event
identity adds the vendor event ID. `sessions.observation_id` additionally binds
the logical session to a source revision and Project, so a copied conversation
can retain one global identity while separate extractions keep distinct
lineage. The current `sessions.id` remains a vendor/local compatibility key. A
path hash or inode is not a Project identity: paths identify locations and
inodes do not survive copying or cloning.

`root_path` is the normalized project anchor. `source_cwd` is what the source
actually reported. `relative_path` is preferred for artifact correlation;
`observed_absolute_path` preserves local evidence. Source locators are URIs or
absolute observed paths and are never treated as portable project identity.
An artifact resolving outside `root_path` is not assigned a misleading `../`
project-relative key. It uses a `file:` URI, retains the absolute observation,
and records `path_scope=external` plus the source spelling in metadata. This
allows later project correlation without claiming that the file belongs to the
session's selected project.

External `file:` URIs are compared with catalog locations and aliases by
longest-root containment. A unique longest match records the matched location,
relative path, method, and confidence as an
`artifact_path_within_project_location` assertion. Equal longest roots remain
explicit candidates. Assertions do not change `artifacts.project_id` or claim
authorship.

### Ordering and time

`sequence_no` is the deterministic within-session order and is required for
interactions/model turns and present for mapped events. Event sequence values
must be positive and are unique within a session. Source record locators and
vendor IDs remain alongside it for lineage.

`started_at`, `ended_at`, and `event_at` are explicit vendor/mapping timestamps
or `NULL`. Codess does not manufacture them from file modification time.
`source_mtime` is captured separately. `time_basis`/`event_at_basis` tells an
application which evidence supports a time value. SQLite stores event-oriented
numeric time as Unix milliseconds; manifests and ingest/observation times use
RFC 3339 UTC strings.

### Types, roles, and tools

Vendor record type/subtype are retained in `source_record_type` and
`source_record_subtype`. Broad common meaning is mapped into open
`event_kind`, `actor_kind`, `content_role`, and `origin_kind` values. New vendor
values therefore remain queryable even before the common vocabulary grows.
Normalized names and formats are the stable mixed-vendor query surface, not a
replacement for source designations. Each mapped event keeps scalar source
type/subtype/locator fields and a named common mapping; `mapping_trace` records
the structured source path and all applied rules. Adapter conformance checks
require those rules to exist in the vendor mapping profile.
Mapping profiles declare their direction. Current vendor profiles are
`source_to_common`; future exports use separate `common_to_external` profiles
and fixtures rather than reversing an ingest rule implicitly. Both directions
use the same rule grammar and retain source/common values needed to explain the
translation.

Source tool names are free text because tool registries are vendor-, harness-,
plugin-, and version-dependent. `canonical_tool_name` is an optional mapping,
not a closed enum. `input_json`, `output_json`, and `output_text` describe the
invocation boundary explicitly; a harness subprocess is not automatically
classified as a model tool call.

`source_status` preserves the vendor value. `normalized_status` is the common
taxonomy (`pending`, `running`, `succeeded`, `failed`, `denied`, `cancelled`,
`incomplete`, `unknown`). Neither silently replaces the other.

### Metadata and mapping trace

Typed, commonly queried meaning belongs in columns/relations. `metadata` is a
JSON extension object for sparse vendor evidence that has not earned a common
field. It must not duplicate canonical fields, conceal required identity, or
become an unbounded raw-record dump. `mapping_rule` and `mapping_trace` identify
the translation responsible for a normalized event. Structured mapping
diagnostics record information that could not be mapped reliably.

JSON is used only where the value is intrinsically compound: mapping traces,
tool argument/result objects, configuration provenance, processing actions,
correlation evidence, and sparse extension objects. Identifiers, field paths,
record names, versions, statuses, normalized taxonomy values, paths, and the
primary `mapping_rule` remain scalar text. SQLite format 4 enforces
`json_valid()` for every contract field typed as `json` or `json_extension`;
writers serialize structured values canonically instead of storing Python
representations. Exact large or unbounded source objects remain in raw evidence.

There is no `release_value`. Version strings remain exact source strings in the
appropriate software/harness/model fields. There is no database `source_raw`
column; raw evidence is handled by the sidecar store.

Configuration values remain nullable and independent. A model name containing
words such as `fast`, `high-thinking`, or `priority` does not populate speed,
effort, or service tier. Per-event `configuration_provenance` records the source
record type, locator, and exact field path for each normalized occurrence.
The candidate currently writes `model_configurations.source_config` as a
bounded representative JSON observation, not an exhaustive history; event
provenance is authoritative. **CoPlan R3a** decides whether that representative
is removed or narrowed, and **R3b** separately decides whether occurrence
provenance also receives a materialized relational projection.
Configuration identity includes provider, family, exact model, revision,
effort, speed, service tier, and mode with null-safe database uniqueness.
Absent, default, and unknown remain distinct.

## Raw evidence and immutable snapshots

Raw retention uses `codess.raw/1`, a content-addressed store outside query
databases. JSONL sources use fixed-size stable-file reads; Cursor SQLite uses a
paged SQLite backup into a temporary database so WAL-visible committed data is
captured consistently. Source and stored hashes are computed in bounded passes,
zstd output is staged, and only a verified content-addressed object is promoted.
Capture and later raw verification both use fixed-size streaming reads, so
memory does not scale with source size. The raw object and normalized SQLite
store remain equally mutable local files. They expose different validation
invariants but have the same local-writer trust boundary. The complete threat
model and digest-role rationale are in **Designs.md §11**.

`--raw-mode` controls retention:

- `none`: record that the source was not retained
- `reference`: record locator plus a bounded source fingerprint (default)
- `capture`: store a content-addressed exact revision
- `seal`: capture and hard-link/copy the objects into the snapshot

Each production ingest builds
`~/.codess/projects/<project-id>/snapshots/<snapshot-id>/`, backs up its format-3
working databases, writes `raw-manifest.jsonl` and `manifest.json`, verifies
package/database/raw hashes and logical counts, then atomically replaces both
the central and project-local current pointers. Project-local `.codess/` holds
working caches, identity/source bindings, validation reports, and a pointer;
the retained baseline no longer depends on survival of the checkout.

`projects.json` is the stable catalog. A minted Project ID owns multiple
locations and vendor workspace bindings. `tools/retire_project.py` requires a
fully accepted captured baseline, marks the old location retired, requires and
binds a replacement, and verifies the replacement can read the durable
snapshot. It never deletes the old directory. Reference mode remains useful
for exploration but cannot authorize retirement.

The lifecycle separates three operations. **Add location** binds another
observed/active path to an existing Project after identity and conflict checks;
ordinary ingest can ensure a binding for its own path but is not an explicit
cross-location assertion. **Retire location** changes one known location's
state without requiring a replacement and must not strand the last reproducible
evidence. **Relocate** composes add, durable-pointer installation, read
verification, and retirement. The current `retire_project.py` requires
`--new-location`, so its behavior is relocation despite its historical name;
its compatibility-wrapper disposition is centralized in **CoPlan A11**. The
catalog location operations define the current lifecycle surface.

`tools/validate_snapshot.py` verifies the current package and immutable-file
hashes, SQLite integrity and foreign keys, manifest counts, event ordering,
artifact identity/index invariants, JSON fields, raw object recovery, mapping
diagnostic allowances, source-specific minimums, and optional Cursor scoping
and turn rules. `tools/apply_and_verify.py` applies this gate to one project at
a time and can require two rebuilds with unchanged source revisions and equal
canonical logical digests. It runs read-only query smoke tests before atomically
updating `catalog/approved-baselines.json`. Policies are versioned data under
`catalog/policies/`; their contract is
`schema/validation-policy-contract.json`.

Sources at or below 64 MiB receive a full-file MD5 change fingerprint. Larger
sources use an explicitly labeled eight-window MD5 sample plus size and mtime.
MD5 is deliberately used here as a fast, non-authenticating change detector;
neither form proves byte identity or protects against an adversary. Exact raw
capture still hashes the complete stable file or transactional SQLite backup
with SHA-256 because that digest is its content address and integrity identity.
Incremental ingest
state records the revision, method, size, mtime, and consistency, so same-size
and same-mtime changes are detected for fully hashed sources. When a SQLite WAL
exists, its revision is combined with the main-file revision so WAL-only Cursor
updates are not skipped. Every Source and
Session records observation/ingestion time, while immutable snapshot manifests
provide the dated extraction boundary and retain prior versions.

Immediate apply validation compares a reference-only locator's current revision
to the revision just ingested, preventing promotion after source drift. Frozen
reviewed-baseline verification does not require a live mutable
locator to remain unchanged forever; it verifies retained snapshot/store/raw-
manifest identities and reports reference reproducibility as a limitation.

The logical digest deliberately excludes snapshot creation time, surrogate
row identifiers, and SQLite layout. It includes common entities, vendor/source
values, ordering, lineage, diagnostics, artifact relations, and correlation
assertions. It therefore proves repeatable normalization for the same sources;
it is not a substitute for manual semantic review or exact raw capture.

The separate normalization digest excludes source-revision and observation
identity. A policy may explicitly use it for a captured shared database that
advances between repeated reads; this never treats the raw revisions as equal.
Each revision remains independently captured and identified, while the digest
proves that the selected normalized Project records did not change.

Working databases are disposable derived state. A writer refuses a store whose
recorded released-package digest differs from the current package. The guarded
apply workflow first verifies the retained current snapshot, archives the old
working databases and ingest state with hashes, then rebuilds from source. This
is a rebuild boundary, not an in-place schema or mapping migration.

Historical queries select one retained identity with `--snapshot-id`. Exact
package matching is the default. The explicit `read-compatible` package policy
checks immutable hashes and the supported SQLite contract but warns that it
does not recreate the older mapping semantics; historical stats do not update
the current registry.

## Compatibility and change procedure

`tools/coschema_gate.py OLD_CONTRACT NEW_CONTRACT` classifies a change as same,
compatible, breaking, or manual review. It checks entity/field removal,
identity/order changes, type/nullability constraints, and vocabularies; unknown
change shapes fail closed. Fixtures under `schema/coschema/fixtures/` cover
minimal, maximal, edge, negative, and compatibility cases.

Runtime `validate_database_contract()` checks both directions: every logical
field must exist physically, and every physical table/column must be contracted
or listed in `physical_contract` as an internal/compatibility detail. It also
verifies SQLite JSON enforcement. `validate_mapped_event()` checks an adapter
event's source identity, declared mapping rules, structured trace, and JSON tool
input. These checks turn omissions into test failures instead of documentation
drift.

For a proposed store change:

1. Change the logical contract and mapping specs first.
2. Run the compatibility gate and record the decision.
3. Change the SQLite layout without mixing application semantics into SQL.
4. Add/update fixtures and mapping/database tests.
5. Advance `format_version` only when the readable contract requires it.
6. Hash the final package into the manifest and treat it as released.
7. Rebuild, validate, and atomically promote a new snapshot; never overwrite a
   retained baseline in place.

See `Schemas.md` for rationale and compatibility-policy provenance and
`Designs.md` for the broader source, correlation, catalog, and execution design.
