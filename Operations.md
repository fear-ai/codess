# Operations — maintainer runbook

**Audience:** corpus curators, release maintainers, evidence maintainers, and
operators responsible for accepted baselines and retained storage.

Daily user investigation belongs in **README.md**. This runbook covers
non-mutating preflight, processing limits, storage and retention, bounded source
access, evidence refresh, curation, and compatibility baselines.

## Ingest preflight

### Cheap assessment before extraction

Use a content-free status pass before `ingest --validate` or full ingest,
especially for Cursor:

```sh
tools/project_status.sh "$PROJECT" ~/.codess
codess scan --dir "$PROJECT" --source cc,codex,cursor --out -
```

The shell helper invokes Git directly for repository/worktree facts and uses
bounded filesystem metadata for current pointers, ingest reports, exact-path
Claude stores, and Project-local `.claude`/`.codess` markers. The scan queries
source-system indexes for the selected Project. It does not transactionally
back up the Cursor database, normalize every selected Event, or create a new
snapshot. Scan does update scan telemetry in the selected registry.

Interpret the signals together. Git commit/worktree state is a strong primary
signal, but vendor source files may change without Git activity. `.claude` or
`~/.claude` changes can indicate harness activity but do not by themselves
establish a conversation mapping. Cursor's global database mtime establishes
only global activity; Project-specific header/workspace/selected-record
observations provide attribution. Build outputs and generated artifacts are
only hints unless a retained invocation links them to the source system.

The helper shows mtimes for a bounded list of dirty/untracked work files,
current HEAD author/committer information, upstream divergence, and the latest
local reflog action. File mtime can reveal an edit after a Session but does not
identify its author. Git stores commit author/committer dates, not file mtimes
or a definitive push timestamp. A push is known only through a dated remote
observation or hosting-provider event; ordinary upstream-ref inspection says
what commit was observed when, not when it arrived there. Treat work not linked
to a retained tool invocation as Project activity without guessing its author.

Proceed to full validation/extraction when a selected source observation
changed, the Project lacks a current snapshot accepted by the selected package
policy, or a deliberate
acceptance run requires fresh evidence. This sequence avoids making the large
operation the discovery mechanism.

### Session names

`codess session name`, `session unname`, and `session names` maintain
`~/.codess/session-names.json`. Each mutable operator name maps to a
`global_session_id` within one stable Project; the name is not the Session ID
and is not copied into immutable Project snapshots. Back up or move this small
registry with the Project catalog. Source titles from Codex, Claude, or Cursor
remain separate source-system evidence.

### Full normalization preflight

`codess ingest --validate` runs real source discovery, vendor adapters, content
policy, CoSchema writes, mapping diagnostics, and SQLite integrity/foreign-key
checks against temporary databases. It forces parsing even when incremental
state says a source is unchanged. It does not alter the Project's `.codess`,
Project catalog, registry statistics, raw store, snapshots, or ingest state.

The `codess.ingest-preflight/1` JSON result contains source/session/event counts,
diagnostics, resource observations, limits, content-failure review records, and
temporary-store checks. This proves current records can normalize under the
current package and records the independent `decoder_version` and
`validator_version`. A policy may require exact processing-profile versions;
an older snapshot is never silently validated under newer interpretation. It does not
prove raw durability, snapshot promotion, or a two-run fixed point;
`codess baseline apply` is the acceptance gate for those properties;
`tools/apply_and_verify.py` is its compatibility wrapper. It owns no validation
or apply logic and remains only for existing automation; new procedures use
the grouped command.

With `--repeat`, baseline apply resolves both immutable rebuilt stores and
streams their canonical rows through the value gate. Identity, sequence, and
lineage vacancies or mismatches are fatal; non-critical differences are
advisory and reported. The comparison is row-streamed and bounds examples, so
its memory use does not scale with database size.

Baseline apply asks ingest to build an immutable `--candidate-snapshot`.
Candidate construction records its path in
`.codess/last-ingest-report.json` but changes neither the Project-local nor
central `current.json`. Validation, repeat-build/value comparison, and query
smoke target that exact candidate. Only after every enabled gate passes does
one publication operation replace the central and local pointer pair. If
either replacement fails, previously existing pointers are restored
byte-for-byte. Rejected candidates remain immutable and retention-visible for
review or later pruning; they never become current.

## Resource bounds and processing

Software 0.2.3 resolves ingest maximums from
`codess.resource-policy/1`. The built-ins are:

| Maximum | Built-in | Current boundary |
|---|---:|---|
| `transcript_bytes` | 256 MiB | One Claude or Codex transcript Source |
| `cursor_container_bytes` | 10 GiB | One Cursor workspace or global SQLite container |
| `events_per_source` | 200,000 | Normalized Events emitted from one Source |
| `events_per_session` | 100,000 | Normalized Events retained for one Session |
| `context_content_chars` | 250,000 characters | One normalized context or compaction body |

These maximums prevent accidental unbounded work; they are not desired payload
sizes. Cursor's larger container ceiling permits bounded SQL selection from its
machine-wide database and does not authorize copying that database into a
Project store.

Use `--resource-policy FILE` or `CODESS_RESOURCE_POLICY` to load a partial JSON
override. The contract and complete example are
`schema/resource-policy-contract.json` and
`schema/resource-policy.example.json`:

```json
{
  "format": "codess.resource-policy/1",
  "maximums": {
    "transcript_bytes": 268435456,
    "events_per_session": null
  }
}
```

An omitted maximum keeps its built-in. `null` disables only that maximum.
Unknown fields, non-integers, booleans, zero, and negative maximums are rejected
before ingest. Resolution precedence is:

1. built-in defaults;
2. the resource-policy file;
3. individual `CODESS_MAX_*` environment values;
4. individual `--max-*` command-line values;
5. `--no-resource-limits`, which disables every maximum for that invocation.

The same file can be passed explicitly to composed maintainer operations. It is
forwarded unchanged to every ingest they invoke, including both repeated
baseline rebuilds and catalog preflight/apply:

```sh
codess baseline apply --project "$PROJECT" --registry "$REGISTRY" \
  --repeat --resource-policy local-resource-policy.json
codess catalog onboard --catalog reviewed.json --apply \
  --resource-policy local-resource-policy.json
```

The new environment names are `CODESS_MAX_TRANSCRIPT_BYTES`,
`CODESS_MAX_CURSOR_CONTAINER_BYTES`, `CODESS_MAX_EVENTS_PER_SOURCE`,
`CODESS_MAX_EVENTS_PER_SESSION`, and
`CODESS_MAX_CONTEXT_CONTENT_CHARS`. `CODESS_MAX_SOURCE_BYTES` and
`--max-source-bytes` remain compatibility spellings for the transcript limit.
Every runtime and preflight report records the policy format, resolved file and
SHA-256, effective values, and the origin of each value. It retains
`limits.max_source_bytes` as a compatibility alias for
`limits.max_transcript_bytes`.

Each report also contains `resource_summary`. `unique_source_container_bytes`
uses the largest observed size once per container path during the run;
`emitted_events` is additive; `largest_session_events` is a maximum; and
`peak_rss_bytes` is the process high-water mark, never a sum.
`retained_searchable_characters` and `retained_searchable_utf8_bytes` are
additive logical Event-payload measures. They count `content`, `tool_input`,
`tool_output`, and `artifact_path`; when a tool result is projected identically
into both `content` and `tool_output`, it is counted once.

`selected_input_bytes` is separate: it is the input selected for decoding, not
the enclosing container and not source-semantic text. A selected Claude/Codex
JSONL transcript contributes its file bytes; a selectively measured Cursor
source contributes the serialized vendor values for that Project. The summary
reports `selected_input_observations`, `unmeasured_selected_input_observations`,
and `selected_input_complete`; unavailable measurements never become zero.
`normalized_store_usage` and `raw_object_usage` report file counts plus logical,
allocated, and hard-link-aware unique allocated bytes. Referenced raw objects
are deduplicated by resolved object path. These physical quantities must not be
added to retained searchable bytes.

Pre-truncation source-semantic bytes and query-result serialization are
distinct possible observations, not values that may be estimated from decoder
input or retained Event text. They are not current requirements; add one under
A9 only when it answers a concrete limit, completeness, or performance
decision.

`--min-size` remains separate. Its legacy 20 KiB default is a source-selection
noise heuristic, not a validity or safety maximum, and it may hide valid tiny
Sessions. The zero-default and semantic admission work remains postponed under
CoPlan P15. Useful one- and two-byte messages such as `1`, `y`, `go`, and `no`
remain valid when their Source is selected.

`--content-policy` is also separate: it transforms, suppresses, masks, or
truncates selected normalized content. A resource policy bounds work before or
during ingestion. It does not silently transform an oversized Source into
accepted content. Exact over-limit content remains resolvable only when
captured, sealed, or referenced evidence is available.

Current supported-format Source revisions, change markers, raw objects,
manifests, stores, and result identities use SHA-256. Older digest labels are
unsupported for live equality verification; rebuild the derived snapshot with
a supported decoder/validator and never rewrite its immutable manifest.

Any future telemetry or limit change must continue to distinguish:

1. vendor container bytes;
2. bytes in selected source records;
3. source and retained semantic payload bytes per Event;
4. selected totals per Session and Project run;
5. physical raw-capture and normalized-store allocation.

Cursor's global database size is a container health/storage observation.
Selection queries, not the complete database size, determine Project payload.
Repeated observations of the same container are never summed as Project
content or physical allocation.

Ingest emits `codess: progress` lines to stderr without waiting for Python
DEBUG logging. Stdout remains the final human/structured result. Each line has
a UTC timestamp, elapsed time, a stable phase name, and content-free fields such as
Project/source/composer identity, counts, byte sizes, and phase duration. Cursor
traces selection-marker computation, cohort restore or capture, periodic SQLite
backup progress, compression/object verification, composer read-buffer
heartbeats, composer writes, and unchanged skips. All vendors expose Project,
vendor, snapshot, completion, and failure boundaries. A long operation should
therefore show its current phase; `-v/--verbose` remains separate DEBUG logging.
Use `--no-progress` when cron/CI reserves stderr for warnings and errors; event
collection and report retention remain enabled.

Routine ingest writes `.codess/last-ingest-report.json` with
`progress_format: codess.progress/1`, the same bounded `progress_events`, source
bytes, event counts, largest buffered session, peak process RSS, limits, and
diagnostics. Preflight includes the trace in its JSON result. Progress records
never contain prompt, response, tool, attachment, or raw-source bodies. The
report also records decoder and validator versions. `status: accepted` here
means the ingest transaction completed and the snapshot was promoted to
current; it is not reviewed-baseline approval. The
trace retains the most recent 5,000 events and explicitly reports the number of
older events dropped. This rolling window preserves the point of failure in a
large batch; earlier completed Projects already have their own reports.
`vendor.done` and `project.done` distinguish `processed_*` counts for this run
from `stored_*` totals. Runtime reports use per-Project status and diagnostic
deltas rather than cumulative values from earlier Projects. They also name the
current immutable `snapshot_id`. An unchanged run may reuse the preceding
evidence summary only when that snapshot ID matches; otherwise it recomputes
the summary and traces the phase.
Cursor runs add `cursor_cohort.status` (`unchanged`, `reused`, or `captured`),
bounded-marker/capture elapsed time, source/materialized/stored byte counts when
available, and the process RSS high-water mark.
Event counts are checked while normalized records are collected, so a configured
limit rejects before the complete oversized buffer is retained. Cursor decoding
projects envelopes to mapped fields before retaining them; completed source
buffers are explicitly deleted and garbage collection follows the transaction.
Content excerpts retain per-record limits.

Unchanged runs still synchronize catalog identity with null-safe updates, but
do not rewrite identical Project/location/workspace rows or rerun derived
artifact correlation. Correlation runs only for a vendor whose normalized
store changed or whose projected catalog bindings changed, and it has its own
progress boundary. This prevents derived-store writes and snapshot churn on a
true no-op.

A size, content-type/shape, or character-set failure is not assumed to be bad
content. Preflight and routine reports add a
`codess.ingest-content-review/1` record with the stage, vendor, exception class,
safe size/type/encoding observations, candidate causes, and recommended checks.
Review wrong source scope, wrong session boundary, container/binary content
mistaken for text, and an unmapped vendor variant before classifying the source
as malformed or overriding a limit. These records retain no content excerpts.
An override is an explicit operational decision, not automatic recovery.

Mapping diagnostics keep scope and severity separate. `diagnostic_level`
identifies `source`, `record`, or `field`; `severity` is `info`, `warn`, or
`error`. Informational field-state observations remain queryable but do not
consume policy warning/error allowances.

A selected multi-session Cursor source remains one rollback-capable SQLite
transaction, but only one composer's normalized events are retained in memory.
Store-wide artifact/model/source orphan pruning runs once after that batch;
running it after every composer caused repeated full-store scans. If one real
composer approaches the event maximum, use a staging table and incremental
group construction rather than silently raising the defaults.

Claude and Codex use the shared `codess.ingest_pipeline` transaction shell.
Normalized Session/Event replacement and SQLite Source-availability metadata
commit together; any callback or SQLite write failure rolls the normalized
replacement back. Raw-object capture is separate content-addressed work and
snapshot promotion occurs after source processing. The incremental state marker
advances only after the normalized commit. Cursor retains a separate
transaction because one selected SQLite source may replace many composers, but
it follows the same rollback-before-state rule.

## Storage observations and retention

`codess storage report` records a dated
`codess.storage-observation/1` document under
`~/.codess/observations/storage/` and returns the same JSON. Each run compares
current totals with the preceding observation. `--no-record` is the read-only
inspection form; `--output` writes an additional copy.

The report covers current CoSchema database logical/allocated size, SQLite
page/freelist utilization, table counts, prompt/response/tool text counts,
largest sessions, sessions with at most two events, Cursor database size,
current and superseded snapshot allocation, and referenced/unreferenced raw
objects. It warns above 2 GiB for one CoSchema database and 10 GiB for Cursor;
use `CODESS_MAX_CODESS_DB_BYTES` and `CODESS_MAX_CURSOR_DB_BYTES` for configured
defaults or command options for one report.

CoSchema v4 deliberately does not persist token observations. The storage
report instead streams distinct current source URIs into a versioned derived
token observation grouped by month/model/source. Claude message usage is
deduplicated and labeled `local_observed`. Codex positive cumulative deltas are
labeled `local_derived_provisional` until their reset/fork/interleave behavior
is validated against the CodexBar lineage algorithm. Cursor remains explicitly
unavailable because no verified local token field is mapped. These are usage
observations, not billed cost, and are never inferred from text length.

`codess storage token-validate` is the Codex validation prototype. It
selects only Codex source files referenced by current stores and reports
cumulative counter drops, repeated points, timestamp regressions, model changes,
and counter points shared across files. Each file is classified as a monotonic
single-file sequence or as reset/interleave, model-transition, or timestamp
ambiguity. `utilization_ready` means usable as a local activity observation;
`billing_ready` is always false because cumulative local counters are not
provider billing records. The report contains counters and
source paths, not conversation text; `--output` saves an explicit copy.

Storage locations and cleanup boundaries are:

- immutable snapshots: `~/.codess/projects/<project-id>/snapshots/`;
- current pointers: `~/.codess/projects/<project-id>/current.json` and the
  project-local `.codess/current.json`;
- content-addressed raw objects: `~/.codess/raw/codess.raw-1/objects/`;
- pre-package working archives: `<project>/.codess/working-archives/`.

The active retention policy keeps exactly the central `current.json` snapshot
for each Project and the raw objects named by those current raw manifests. It
does not retain a historical snapshot merely because it is old, reviewed, or
named as a parent. A parent snapshot ID is durable lineage information, not a
promise that the parent's bytes remain resolvable. Working archives are a
separate, explicitly selected retention class.

Project-local `working-archives` contain pre-package normalized databases, not
vendor transcripts or current source evidence. `storage prune` inventories them
but selects none by default. `--working-archives` selects only archives whose
catalogued Project has a current central snapshot; apply remains explicit and
the receipt records every removed path and reclaimed allocation. They are not
silently folded into raw-object garbage collection. Cleanup receipts retain the
selected paths, validation result, and reclaimed allocation; the runbook does
not preserve dated cleanup chronology.

Pruning is mark-and-sweep and dry-run by default:

```sh
codess storage prune --registry ~/.codess --output /tmp/codess-prune.json
codess storage prune --registry ~/.codess --apply
codess storage prune --registry ~/.codess --working-archives --output /tmp/codess-archives.json
codess storage prune --registry ~/.codess --working-archives --apply
```

The default plan also rejects multiple current, distinct revisions of the same
logical raw source when each revision is at least 1 GiB. This prevents several
Project snapshots from silently pinning near-copies of a mutable global Cursor
database. Use `--keep-comparison-revisions` only when those revisions are
intentional comparison evidence. Otherwise capture one deliberate Cursor
source cohort, rebuild the affected current Project snapshots against it, and
run the dry-run/apply sequence; do not remove an object while an immutable
current manifest still names it.

For a multi-Project Cursor capture, a **cohort** is one transactionally
consistent backup of the mutable global Cursor SQLite database, not a Project
classification. Before any backup, ingest calculates a bounded marker for each
Project's selected workspace headers and composer bubble-key ranges, then
compares those markers with Project ingest state. If all markers are current,
it neither backs up nor materializes the global DB and
does not create no-op snapshots. Otherwise it captures once and applies indexed
workspace/composer queries for every selected Project. A fresh capture is
queried directly from its temporary standalone backup; it is not immediately
decompressed from the raw object again. Each successful Project manifest
therefore names the same content-addressed object and original live source
locator.

`~/.codess/cache/cursor-cohort-v1.json` is a replaceable metadata-only cache; it
does not contain a second database copy. When another Project needs the same
unchanged cohort, ingest verifies and streams the retained raw object into one
temporary query database. `--force` bypasses cache reuse. Cache deletion affects
performance only. The pre-capture selection marker is deliberately retained as
the state guard: if selected header or bubble evidence changes after the marker
was read, the next invocation revisits that Project instead of treating the
backup as current.

`~/.codess/cache/cursor-selection-v1.json` is a separate metadata-only
prefilter for immediate repeat runs. It retains the latest exact
Project-to-workspace selection, main/WAL inode-size-mtime observations, and
selected markers—never SQLite rows or content. Stable before/after container
observations permit marker reuse; any difference performs the full bounded
selected scan. `--force` also bypasses this cache. Deleting either cache is
always safe and changes only performance.

SQLite backups are normalized to `journal_mode=DELETE` before capture so the
standalone object remains queryable through a strict read-only connection
without live WAL sidecars.

Raw object identity is the decompressed source digest. A valid existing zstd
encoding is reused after streaming verification even if a different compressor
version or level would produce different stored bytes; the manifest records the
stored digest and size of the encoding actually retained. Incremental rebuilds
also remove normalized Source revisions no longer referenced by any current
session/event, preventing stale `source_records` from accumulating while raw
snapshot history remains governed by retention.

The plan validates each central current pointer and manifest, every current DB
hash and SQLite quick-check, each raw-manifest hash, and retained raw-object
presence and size. Full raw verification separately reads the compressed
representation and the decompressed source in fixed 1 MiB chunks, so a multi-
gigabyte Cursor backup is never materialized in memory. It then lists every
superseded snapshot and every object not
referenced by a current manifest with reclaimable allocation. `--apply`
recomputes that plan immediately, performs only the listed removals, checks the
zero-candidate postcondition, and writes a receipt below
`~/.codess/receipts/retention/` (or `--receipt`). It does not delete vendor
stores, Project working databases, unselected working archives, or observation
history.

Approved/reviewed catalogs are checked before deletion. A catalog whose
selected `snapshot_id` is superseded blocks apply: run `baseline freeze` after
the current baselines have passed validation, or explicitly remove the stale
catalog member if it is no longer approved. Never rewrite only its snapshot ID,
because its semantic digest and validation evidence describe the old build. An
old `parent_snapshot_id` is reported but does not pin storage. Active
Project-local `.codess/current.json` pointers are also checked; a stale one
blocks apply and should be repaired by a validated rebuild/relocation that
updates both central and local pointers.

`baseline freeze` publishes one package-coherent reviewed set: every selected
Project must have a current fixed-point report produced by the same CoSchema
package. Rebuild all selected members after a package change; do not freeze a
single new member beside stale package evidence. `accepted_with_limitations` is
a valid, preserved review state when policy intentionally permits a
reference-only source. It is never rewritten as `accepted`; subsequent
`baseline verify` must reproduce the same qualified state with
`verify_reference_current=False`, because the recorded revision—not the
mutable live locator—is the reviewed cohort. Verification opens the catalog's
exact retained `Project ID + snapshot_id` under the recorded registry;
advancing a Project's current pointer neither changes nor invalidates that
reviewed baseline.

### Full-scan boundaries

Routine work should begin from selected Projects and current pointers, not from
all vendor history:

- Cursor ingestion resolves workspace IDs to current composer headers and the
  workspace-local `composer.composerData` fallback index, then uses indexed key
  ranges for only those composers. Even an explicit all-composer
  audit uses a bounded prefix range rather than `LIKE`. A full transactional
  Cursor backup occurs only for raw capture, not querying.
- Cursor's live `composerHeaders` is the primary selector; workspace
  `composer.composerData` recovers older composers that still have global
  content rows but no current header. `cursorDiskKV`'s unique key index selects
  `bubbleId:<composer-id>:` ranges.
  Counts and byte totals use `COUNT(*)` and `length(value)` without JSON decode;
  ingest decodes only selected rows. A logical export of selected rows can be a
  useful derived artifact, but it is not an exact raw copy of the vendor store.
  Exact `capture`/`seal` still requires one SQLite backup when the bounded
  selection marker changes or a selected Project lacks captured evidence, so
  WAL state is included. Main-file size/mtime is both too coarse and incomplete
  in WAL mode. Routine Cursor change detection reads one SQLite snapshot and
  hashes exact selected primary/fallback header fields plus every selected
  bubble key/length and
  the first/last 512 value bytes. This deliberately ignores unrelated Cursor
  workbench/global state. A retained/reused cohort remains a
  fully SHA-256-addressed raw backup and cache restoration verifies both its
  compressed and decompressed identities. New selected-row and combined-cohort
  change markers also use SHA-256, but remain non-authenticating bounded
  fingerprints. A same-length change wholly inside a large bubble could evade
  the edge sample only if Cursor also failed to update its selected composer
  header; use `--force` when investigating that vendor-behavior boundary.
  Selected bubble rows are ordered by indexed key range, normalized one
  composer at a time, and written within one rollback-capable transaction. This
  bounds multi-composer accumulation, but the largest composer is still the
  unit needed for timestamp ordering, duplicate suppression, and Interaction
  construction. The measured high-water result and remaining within-composer
  streaming work are tracked as **CoPlan L-E3/A9**.
- Claude resolves the selected Project's storage directory. Candidate discovery
  reads top-level session indexes only; feature audit is explicitly bounded by
  `--max-files`.
- Codex has no vendor Project index, so Codess still enumerates active/archive
  JSONL filenames once per operation. A persistent
  `~/.codess/cache/codex-session-index-v1.json` maps
  `(path, size, mtime_ns)` to session ID, cwd, timestamp, and optional record
  count. Unchanged transcripts are not reparsed, missing paths are dropped, and
  one in-memory inventory is shared by every selected root and Project during a
  scan or ingest.
- Token accounting selects only distinct source URIs referenced by current
  stores. `~/.codess/cache/token-usage-v1.json` fingerprints that complete
  current source set by path, size, and `mtime_ns`; unchanged observations reuse
  the prior monthly result without opening transcripts. A changed source
  currently causes a complete selected-set recomputation. Specialize this to
  per-file aggregates and Claude deduplication identities only if routine churn
  makes that recomputation material.
- `storage report` enumerates current stores directly. It reads only current raw
  manifests; it lists snapshot directories and raw object filenames once to
  measure reclaimable storage. `storage prune` necessarily performs the same
  one-pass mark/sweep inventory.
- Candidate Git discovery, vendor feature audits, baseline validation, and
  evidence gathering are explicit review operations. Their whole-set scans are
  kept off routine ingest/query paths and bounded by selected roots, depth, file
  limits, or current catalog membership.

### Where text actually resides

- Vendor Claude/Codex JSONL and Cursor `bubbleId:<composer>:*` values contain
  the source prompt/response text that remains in the vendor store. A captured
  or sealed raw object preserves the exact source container.
- `events.content` contains the normalized prompt or response excerpt;
  `tool_input` and `tool_output` contain normalized tool material. These fields
  may be sanitized, redacted by policy, and bounded, so they are searchable
  projections rather than exact raw text.
- `content_objects` and relation tables type/link normalized inline content or
  raw/derived objects; storage class determines whether the content itself is
  inline. A content-object row is not automatically an exact vendor record.
- `sessions`, `interactions`, and `model_turns` define identity and boundaries,
  not prompt/response bodies. `source_records` provides locators,
  classification, and parameters; it does not by itself contain the source
  body. Projects, locations, and workspace bindings likewise contain no chat
  text.

## Evidence inventory

`codess evidence gather` searches current catalog Projects and local vendor
metadata without retaining conversation bodies. It checks cross-vendor artifact
identity, effort/speed/service settings, direct Codex parents,
lifecycle/missing-time evidence, and Cursor tool/model shapes. Relevance-ranked
results live in `catalog/evidence-inventory.json`.

The current source audits find Claude exact model/service tier, Codex exact
model/effort and newer service tier, Cursor exact model selections, and Cursor
accepted/rejected tool decisions. No distinct speed tier or direct Codex parent
identifier has been observed. `available` in the inventory distinguishes raw
source evidence from normalized-store counts so an old baseline cannot make a
source capability look absent. Evidence-gap and corpus-expansion actions are
governed by **CoPlan A12/T4–T5**, not by this procedure.

To inspect the normalized configuration inventory and its bounded occurrence
evidence:

```text
codess query configurations --project-id PROJECT_ID --source codex
codess query configurations --project-id PROJECT_ID --session-id SESSION_ID
codess query events --project-id PROJECT_ID \
  --model MODEL --reasoning-effort high --service-tier default \
  --limit 20 --byte-limit 1048576
codess query sessions --project-id PROJECT_ID --model MODEL
```

The first command reports independent nullable fields, Model-Turn and Session
default occurrence counts, and at most three examples with Source revision,
URI, record locator, and field provenance. `recorded` means occurrence Events
carry that evidence; `representative_only` means only the configuration-level
observation is available in the selected snapshot; `normalized_only` means no
structured source mapping was retained. An Event may additionally mark
`configuration_provenance_scope.state=inherited` and name the governing Event
when a vendor records a selection before the governed model output. These
states describe evidence availability, not model capability or snapshot
freshness.

Use `refresh --force` when decoder, mapping, or store behavior changed but the
vendor source fingerprint did not. Forced ingestion builds selected vendor
stores in a fresh Project-local staging directory and promotes them only after
successful mapping and derived processing; this avoids slow in-place deletion
and upsert against a large indexed store. A failed staged rebuild retains an
existing working store, and the immutable current snapshot pointer remains
guarded by normal publication.

Useful bounded component audits are:

```text
codess evidence audit claude-features --max-record-bytes 65536
codess evidence audit codex-features --max-record-bytes 65536
codess evidence audit cursor-features
codess evidence audit mcp-interactions
codess evidence audit orientation
```

The JSONL audits never retain message, reasoning, instruction, argument, or
result bodies. Records above the configured ceiling are drained and counted as
oversize rather than allocated or parsed.

`mcp-interactions` audits every MCP-qualified observed invocation in current
query-ready Project snapshots. It separates discovery, target-server errors,
operation failures/cancellations, administrative actions, visualizations, and
empty diagnostics. It reports repeated source call IDs as duplicate
candidates, not proven copied operations: those free-text IDs are not assumed
globally unique across Sessions or vendors. Add one or more current raw Codex
rollouts when validating
activity that has not yet reached a Project snapshot:

```text
codess evidence audit mcp-interactions \
  --codex-rollout ~/.codex/sessions/YYYY/MM/DD/rollout-....jsonl \
  --output /tmp/codess-mcp-audit.json
```

Conversation/input/result excerpts are absent by default. `--include-excerpts`
adds bounded 240-character evidence excerpts for a local debugging run; do not
publish that output without the same privacy review as normalized content.
This audit reads current snapshots and named rollouts only. It does not scan
all vendor history or inspect configuration secret values.

`orientation` runs the typed UC3 overview for every current query-ready
Project and independently recomputes its core observations from read-only
SQLite. It compares overall and UTC-month totals; daily prompt/response
characters and response anchors; actor, combined-automation, and subagent
partitions; tool call/result/input/output observations and names; and distinct
Session/Interaction counts. A nonzero exit status means at least one Project
does not reconcile. Use repeated `--project-id` to limit the audit, and
`--output` to retain the dated report:

```text
codess evidence audit orientation \
  --registry ~/.codess --output /tmp/codess-orientation-audit.json
```

## Curated workflows

These command families use shared domain operations. Old tools and scripts
remain compatibility entry points during the removal review.

Candidate review combines production scan observations with optional maintained
CSV/catalog data and bounded local Git activity. It is read-only by default,
does not crawl repositories unless requested, and never checks remotes without
an explicit network option. Recommendations explain `consider`, `defer`, or
`exclude`; only an explicit review decision can authorize curated onboarding.

Use `catalog annotations` for the current cross-catalog review list:

```text
codess catalog annotations
codess catalog annotations --label included --label incomplete
codess catalog annotations --format json \
  --output ~/.codess/reports/project-annotations.json
codess catalog annotations --format csv \
  --output ~/.codess/reports/project-annotations.csv
```

Annotations are computed from the authoritative Project catalog, current
snapshot facts, and reviewed compatibility selection. They do not authorize
ingest, claim source freshness, or rewrite curation. `suspect` is deliberately
reserved for direct evidence such as `needs_review`, a missing active
location, or snapshot inspection failure; a known limitation alone does not
make a Project suspect.

### Routine multi-Project refresh

`codess refresh` composes the existing ingest operation for a deliberate
selection. Supply repeated `--project` values, one `--project-list`, or one
computed `--designator`. Project references resolve by stable ID, unique
logical name, or exact catalog path. A project-list file may contain a JSON
`projects` array (strings or objects with `project_id`, `name`, or `path`), a
CSV column named `project_id`, `name`, `path`, or `directory_path`, or one
reference per non-comment text line. Resolution rejects unknown or ambiguous
references, missing active locations, and a Project with multiple live
locations unless the caller supplies an exact catalog path.

```text
codess refresh --project SWEmore
codess refresh --project Zero400 --project zerowalletmac --stage preflight
codess refresh --project-list reviewed-projects.json --stage apply
codess refresh --designator incomplete --stage plan
```

The operation has three explicit stages:

1. `plan` resolves and deduplicates stable Project IDs, paths, source choice,
   and raw mode without parsing vendor content.
2. `preflight` invokes validated ingest separately for every Project and
   records bounded output, timing, and failures.
3. `apply` is allowed only after all preflights pass and the selection,
   catalog, and package fingerprints remain unchanged. Each Project apply then
   proceeds independently; failures do not erase successful earlier snapshots
   or prevent attempts on later Projects.

Preflight and apply default to a dated receipt under
`~/.codess/reports/refresh-*.json`; `--receipt PATH` chooses another location.
The receipt is checkpointed after each Project. A timeout or launch failure is
a Project failure, not an unstructured orchestration exception.

This is routine source refresh. It neither changes curation nor performs
reviewed-baseline fixed-point rebuild, semantic sampling, approval, or freeze.
Use `baseline apply|freeze|verify` for that release-maintainer workflow.
Designators are computed labels rather than durable research identities, so
the receipt retains the exact resolved Project IDs and input fingerprints.

`codess catalog status` reads the latest usable completed result for each
Project from bounded `~/.codess/reports/refresh-*.json` discovery. It reports
`preflight_passed`, `preflight_failed`, `refresh_applied`, `refresh_failed`, or
`not_assessed`, plus the observation time, receipt, requested Source/raw mode,
and snapshot ID when available. Plan-only and malformed receipts are ignored.
This is execution evidence, not a formal freshness claim: a later failed
attempt remains visible even when an older valid snapshot is still queryable.

The normal curator workflow is intentionally two human actions:

1. refresh candidate observations and record decisions; and
2. onboard the `approved` selection.

The decision makes a Project eligible for curated onboarding; it does not
write data. `catalog onboard --apply` is the separate mutation authorization
after successful preflight and unchanged selection/package verification.
Direct `ingest` without `--validate` is also an explicit, path-scoped operator
authorization, but it does not confer curated or compatibility-baseline
approval. Baseline acceptance and publication have their own apply/freeze
gates.

Onboarding itself exposes plan, preflight, and apply in one structured receipt,
with stop points after plan or preflight. Operators and CI retain direct access
to each stage; ordinary users do not have to manually shuttle a scan CSV through
several scripts. `ingest --dirs` remains available for an explicit path list.

Baseline publication similarly composes safe stages: validate accepted member
reports, atomically replace each selected catalog with pair rollback on a
detected failure, then verify the written set.
The read-only verify operation remains separately callable for CI. Evidence
gathering runs vendor audit functions once and can emit both detailed component
reports and the aggregate inventory.

Location management distinguishes adding a second location, retiring a location
without replacement, and relocating from old to new. The historical
`retire_project.py` requires a new location and is therefore a relocation
wrapper; the explicit operations are under `catalog location` and
`catalog relocate`. It owns no location logic and remains because existing
automation and a relocation regression test exercise the historical entry
point. Do not add features to either wrapper. Removing either requires an
explicit deprecation/release decision; immediate deletion would provide no
code consolidation benefit.

## Baseline inventories

Three different records must not be conflated:

- `catalog/reviewed-baselines.json` is the frozen, bounded compatibility set
  described in **CompatibilityReview.md**.
- `catalog/approved-baselines.json` is the explicitly published operational
  selection.
- `~/.codess/projects/*/current.json` points to every Project's current central
  snapshot, including snapshots that are not members of either catalog.

The JSON catalogs and current pointers are authoritative; this runbook does not
copy their Project lists or snapshot IDs. Run `codess baseline verify` to check
the frozen reviewed compatibility set—not each Project's mutable current
snapshot—against package identity, policy, hashes, SQLite integrity, global
IDs, ordering, raw evidence, and query-smoke requirements.

Routine reconciliation may pass
`~/Work/Code/SWEmore/active_work_projects_since_2026-05.csv` to `--dirs`.
Cursor's central database is measured once per multi-root scan; its unattributed
aggregate may appear as `(global)`, but is not a Project or registry member.
Project rows use only composer IDs linked by workspace headers.

A relocated Project can retain vendor-owned evidence at its original local
locator. An approved `.codess/source-links.json` maps that immutable source
identity to the current Project location. `ZK/insight`, for example, retains
Claude evidence under its prior storage slug; neither the vendor store nor
source locators are rewritten.

## Claude background process recovery

This appendix covers hung tests and Claude-managed background commands. It is
an operating procedure, not a project work queue; current work remains in
**CoPlan.md §8**.

Claude's task view and the operating-system process list track different state.

| State | Inspect | Stop or update |
|---|---|---|
| Shell process | `jobs`, `ps` | `kill`, or a timeout around the command |
| Claude-managed background command or agent | `/tasks` | Task controls in Claude Code or `TaskStop` |
| Claude task-list item | `~/.claude/tasks/<session>/` | Update task status; it is metadata, not a process |

Stopping one layer does not prove that the others changed. Files under
`~/.claude/tasks/` contain task descriptions and statuses, not live PIDs.

### Bound commands that may hang

Use the project's selected Python environment. Add GNU `gtimeout` when a
command needs a hard deadline:

```bash
python -m pytest tests/
gtimeout --kill-after=5s 180s python -m pytest tests/
```

After 180 seconds `gtimeout` sends `TERM`; five seconds later it sends `KILL` if
the command is still alive. Do not add `--foreground` when children must also be
timed out. Exit status `124` means the deadline expired; `137` indicates `KILL`.

Claude Code may move a long Bash call into the background. The environment
variables `BASH_DEFAULT_TIMEOUT_MS` and `BASH_MAX_TIMEOUT_MS` control Bash tool
timing, but neither proves that an external process exited.

### Inspect before killing

```bash
jobs -l
ps -o pid=,ppid=,pgid=,state=,etime=,command= -p <pid>
ps ax -o pid=,ppid=,pgid=,etime=,command= | rg '[p]ytest|[p]ython.*specific_script'
```

Match a distinctive script, test path, or argument. Counts such as
`pgrep -c python3` include unrelated work and are not safe cleanup criteria.

Stop only a confirmed process:

```bash
kill -TERM <pid>
ps -p <pid>
kill -KILL <pid>  # only if the same process remains
```

Before signaling a process group, compare its PGID with the current shell:

```bash
ps -o pid=,ppid=,pgid=,command= -p <pid>
ps -o pgid= -p $$
```

Use `kill -TERM -- -<pgid>` only when the target group is confirmed to be
separate from the shell. Never use blanket commands such as `pkill python3`, and
never reuse PIDs copied from an old log.

### Reconcile Claude-managed work

Use `/tasks` to inspect work known to the current Claude session. Stop the
selected command or agent through Claude Code, then check `ps` if it launched
external workers or detached a daemon. Deleting `~/.claude/tasks/` files does
not stop an OS process.

Tests that create child processes should own teardown in a fixture or `finally`
block. The project does not need a general-purpose reaper.
