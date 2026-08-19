# CursorSchema — Cursor IDE Session Storage

Vendor-specific structure for Cursor chat persistence. `codess.cursor_source`
owns installation discovery, workspace mapping, read-only SQLite access,
selective SQL, and selected-evidence fingerprints. The Cursor adapter decodes
only selected values and maps them to CoSchema; ingest and scan call those
shared components rather than implementing independent database readers.

Cursor's SQLite format is private and can change without notice. Use read-only
access and tolerate missing tables, null values, and new fields.

## Source Scope and Locations

`CODESS_CURSOR_DATA` overrides the platform default Cursor `User` directory.

| Platform | Default base |
|---|---|
| macOS | `~/Library/Application Support/Cursor/User/` |
| Windows | `%APPDATA%\Cursor\User\` |
| Linux | `~/.config/Cursor/User/` |

Relevant paths under that base:

| Path | Role |
|---|---|
| `globalStorage/state.vscdb` | Primary cross-workspace Composer store |
| `workspaceStorage/<workspaceId>/workspace.json` | Maps an opaque workspace id to a project folder |
| `workspaceStorage/<workspaceId>/state.vscdb` | Workspace state; may exist without Composer rows |

`workspace.json` commonly stores `folder` as a `file://` string. Codess also
accepts an object whose `folder.path` contains the path.

### Terminal-Agent Storage

Cursor records agent Sessions driven from a terminal (`cursor-agent`, also
reachable as `cursor agent`) **outside** the SQLite pipeline this document
otherwise describes. Two locations are observed, and only the second is
current:

| Path | State |
|---|---|
| `~/.cursor/projects/<project-slug>/` | **Current.** Holds `agent-transcripts/`, `agent-tools/`, `terminals/`, `canvases/`, and `mcps/` |
| `~/.cursor/chats/<workspace-hash>/<agent-uuid>/store.db` | **Historical.** One SQLite database per Session; no longer written |

Neither is ingested. Characterising the current tree is tracked as an open work
item.

**The historical store is set aside, not decoded.** `chats/` held one SQLite
database per Session -- a `meta` row of hex-encoded JSON carrying `agentId`,
`name`, `mode`, `lastUsedModel`, and an epoch-millisecond `createdAt`, plus a
content-addressed `blobs` table of protobuf messages yielding `role`, typed
`content[]` parts, and tool calls. Every instance observed was written between
9 and 12 August 2025 against one model, and nothing under `chats/` has been
written since while sibling directories have. The decision is to leave it
undecoded: adapter work would be spent on Sessions no current release produces.

What it establishes is worth keeping. Its designators shared almost nothing
with `state.vscdb` -- a Session was `agentId` rather than `composerId`, a tool
carried a `toolName` string rather than a `toolFormerData.tool` numeric enum, a
message carried `role` plus typed `content[]` parts rather than an integer
`type`, and no `serverBubbleId` existed, so the duplication described under
Repetition and Deduplication did not arise. Only `createdAt` in epoch
milliseconds agreed with this document's vocabulary.

The rule that follows: **a Cursor storage location is read on its own terms.**
Carrying a field name across from the GUI store is unsafe even within one
vendor.

**This storage is expired by the vendor.** `~/.cursor/projects/` carries
zero-byte `.agent-data-cleanup-<YYYY-MM-DD>` sentinels, one per run, whose name
is their entire content and whose mtime falls the day before the date they
carry -- so they record that a sweep ran, not what it removed. Eight cover
recent consecutive days.

The window is not short. Measured across 609 files in 53 project directories:
196 are under a week old, 185 one to four weeks, 112 one to three months, and
116 older than three months, with the oldest at roughly six months. So the
sweep is periodic rather than aggressive, and terminal-agent evidence is not
about to vanish -- but it is deleted on a schedule Codess does not control,
which the GUI store's retention does not do.

### Opening a Cursor Store Read-Only

Codess opens vendor databases read-only and does not modify them. Two access
particulars are established:

- **The GUI stores accept the read-only URI.** `sqlite3.connect("file:<path>?mode=ro",
  uri=True)` is the form `cursor_source` uses against `state.vscdb`, and the
  form `README` documents for direct inspection.
- **The chat stores did not.** Every read-only URI open against
  `~/.cursor/chats/*/*/store.db` failed with `unable to open database file` --
  at the vendor path, at a copy outside the repository, and at a copy inside
  it -- while a plain path open succeeded immediately on all three. The same
  URI form works against Codess's own stores, so the form alone does not
  explain it and the trigger is not yet identified.

The consequence for discovery is what makes this worth recording: a store that
cannot be opened is indistinguishable from a Source that is not present, so an
open failure must be reported as an unreadable Source rather than counted as
an absence.

## Storage Layout

### `cursorDiskKV`

Key/value table with unique text keys and text, blob, or null values.

| Key pattern | Content |
|---|---|
| `bubbleId:<composerId>:<bubbleId>` | One conversation bubble |
| `messageRequestContext:<composerId>:<bubbleId>` | Harness context assembled for one message request |
| `composerData:<composerId>` | Session UI/state object; shape varies |
| `composer.content.<hash>` | Content blob referenced indirectly |
| `agentKv:<...>` | Agent state not used by Codess |

JSON values are usually UTF-8 JSON text. Codess also attempts base64-wrapped
JSON for bubble and composer data. Null or undecodable values are skipped.

### `composerHeaders`

Session-level index:

| Column | Meaning |
|---|---|
| `composerId` | Session identifier and primary key |
| `workspaceId` | Workspace-storage directory id when known; used to scope global ingest |
| `createdAt`, `lastUpdatedAt` | Epoch-millisecond header timestamps. Present on all 66 headers measured. **Read by scan for its time-range row and by `cursor_source`, and not carried into a Session**: `sessions.started_at` and `ended_at` are null on Cursor stores, so a Cursor Project can hold Events with no time at any level |
| `isArchived`, `isSubagent` | Session classification flags |
| `recency`, `checkpointAt`, `value` | Cursor state not currently used by Codess |

Codess uses this as the primary global-session index. Composers whose
`workspaceId` maps to the selected Project are imported. Missing timestamp or
classification columns default to null/false; additional columns are ignored.
Session metadata records `selection_source=composerHeaders`; the selected
evidence fingerprint includes that designation and uses
`cursor-workspace-header-source-key-length-edge-sha256-fingerprint-v2`.
The table is not a complete Session catalog: Cursor can retain full
`composerData:*` and `bubbleId:*` rows after removing a composer header.

`isSubagent` is Session-relation and record-origin evidence. Codess stores the
Session as `session_relation_kind=subagent`; a `type=1` bubble in that composer
maps to a harness-carried `delegated_prompt` with
`origin_kind=harness_delegated`, not a human prompt. The exact header flag and
source role remain metadata. In the reviewed local layouts the corresponding
parent composer/session is not consistently available, so
`parent_session_id` remains NULL instead of being inferred from time, content,
or workspace proximity.

### `ItemTable`

Most rows are editor/workbench state and are ignored. One workspace-local row,
`composer.composerData`, is a secondary session index. Its `allComposers`
entries preserve composer identity, timestamps, archive/subagent flags, and
other header-like metadata for some sessions missing from the live global
`composerHeaders` table. Codess uses this row only for workspaces already
matched to the Project (including approved source links). A composer occurring
in more than one selected workspace fallback is ambiguous and excluded. A
fallback-selected Session records
`selection_source=workspace.composerData`; current global headers override an
overlapping fallback.

## Selective Access

Use SQLite read-only mode:

```text
file:/absolute/path/to/state.vscdb?mode=ro
```

Useful queries:

```sql
SELECT COUNT(*) FROM cursorDiskKV WHERE key LIKE 'bubbleId:%';
SELECT COUNT(*) FROM cursorDiskKV WHERE key LIKE 'composerData:%';
SELECT workspaceId, COUNT(*) FROM composerHeaders GROUP BY workspaceId;

-- One composer/session: the cursorDiskKV primary-key index supports this range.
SELECT key, value FROM cursorDiskKV
WHERE key >= 'bubbleId:<composer-id>:'
  AND key <  'bubbleId:<composer-id>:\U0010ffff';
```

The main DB may have `-wal`, `-shm`, and backup companions. Do not modify or
vacuum Cursor's live database from Codess. Codess uses URI-safe, query-only
connections with a bounded busy timeout; committed rows still present only in
the live WAL are visible. Global ingest and project-level scan metrics issue
prefix-range queries for the mapped composer ids rather than scanning or
decoding unrelated bubbles in the global database. Workspace selection and SQL
live in `codess.cursor_source`; the adapter only decodes selected values and
normalizes events.

## Bubble Records

Fields relevant to normalization:

| Field | Meaning | Codess status |
|---|---|---|
| `type` | `1` user, `2` assistant-shaped envelope | Mapped only when the record contains message or tool-result evidence |
| `text` | Message body | Sanitized and truncated |
| `createdAt` | ISO-8601 event timestamp | Primary normalized timestamp and sort key |
| `timingInfo.clientStartTime` | Relative client timing, or an epoch value in alternate shapes | Used only when it plausibly represents Unix seconds or milliseconds |
| `toolFormerData` | One tool name/call id/model-call id, arguments, result, status, and optional `userDecision`. **"Former" does not mean superseded**: this is the only populated tool shape, and its `tool` field is a numeric enum paired with `name` (`5` beside `read_file`, `15` beside `run_terminal_cmd`), so the name reads as a UI component rather than a point in time. What it denotes in Cursor's own vocabulary is not established | Emitted as a linked invocation and, for final states or a result body, a result/failure event; exact accepted/rejected permission evidence is retained |
| `toolResults` | Alternate tool-result array | **Present on every bubble and empty on every one measured**: 6,000 bubbles sampled from the live global store, `toolResults` populated on none. `toolFormerData` was populated on 5,078 of the same sample and produced 60,875 tool results across the current-format Codess stores, against zero from this key. `cursor.tool-result-legacy` is therefore declared and unused; it is retained because a store written when the shape carried data still needs it |
| `modelInfo.modelName` | Model selection attached to a user request | Non-`default` values configure the following inferred model turn with exact source-field provenance; `default` remains source metadata |
| `conversationSummary` | JSON string with summary body and truncation boundary IDs | Bounded `context.compact` event |
| `contextWindowStatusAtCreation` | Context usage observation (`tokensUsed`, `tokenLimit`, percentages) | Preserved as source metadata on the bubble's emitted events |
| `codeBlocks`, `fileActions`, other context fields | Product state and supporting content | Not normalized unless explicitly mapped below |

Current `toolFormerData.status` values include `completed`, `error`, `loading`,
and `cancelled`. Codess preserves the source value and maps those to succeeded,
failed, running, and cancelled. Cursor therefore contributes evidence-backed
tool-failure audit rows. A rejected `userDecision` maps to normalized `denied`
independently of the status value; acceptance does not erase an observed error.
For MCP-qualified tools, `completed` describes the harness call envelope, not
necessarily the operation. An explicit nested `Error:`/`Failed to` result or
structured error field now maps to application failure while retaining
`source_status=completed`.

`get_mcp_tools` and `list_mcp_resources` are discovery operations. Discovery
can itself succeed while reporting `serverStatus=error`, an empty tool list, or
an authentication-only tool for the target server. Those outcomes are not
evidence that the target tool ran. Cursor's product-provided
`cursor-app-control` tools are also distinct from user-configured servers:
workspace-root moves, dialogs, chat renames, and resource display are real
harness operations, but do not prove that an external MCP integration was
configured or useful.

**Compaction and request context.** A durable assistant bubble
`conversationSummary` is verified in the local store. It is a JSON string with
the summary plus `truncationLastBubbleIdInclusive` and
`clientShouldStartSendingFromInclusiveBubbleId`; Codess emits one bounded
`context.compact` event and preserves both boundary IDs. Top-level
`messageRequestContext:<composerId>:<bubbleId>` values are separate harness
request-context objects; selected values become bounded `context.inject`
events linked to the composer and bubble. They are included in the selection
marker, so context-only updates invalidate an otherwise unchanged cohort.
Workspace `composerData` summary fields are retained as audit evidence but do
not create a duplicate event when empty or when a bubble supplies the actual
summary. Cursor still supplies no verified turn-abort shape.

Cursor's public product description matches these local observations but is
not the storage contract. The
[summarization guide](https://docs.cursor.com/en/agent/chat/summarization)
says older messages are summarized automatically as a conversation reaches the
model context limit; current surfaces also document manual `/summarize` or
CLI `/compress`. Cursor's
[dynamic-context description](https://cursor.com/blog/dynamic-context-discovery)
describes writing long tool/MCP outputs to files and giving summarization
access to history files.
Codess therefore treats file references found in future verified records as
candidate external content, not as proof that a guessed filesystem path is
part of this SQLite release. The current mapped subset remains the three
verified shapes above; file-backed Cursor context is an evidence-triggered
extension.

The audited `modelInfo` objects contain only `modelName`; Codess therefore does
not infer effort, speed, or service tier from names such as `*-fast` or
`*-thinking`. Those labels remain exact model selections.

Cursor records that selection on a governing user bubble, not necessarily on
each later model bubble. Normalized writes carry its exact field/locator
provenance to governed model Events and mark the scope `inherited`; the
governing Event remains identifiable. Turns before any observed governing
selection remain unconfigured rather than
receiving a guessed model.

The adapter uses parsed `createdAt` for sorting and event timestamps. Numeric
fallback values are accepted only when they plausibly represent Unix seconds or
milliseconds; small relative values are rejected.

The global database may repeat the same logical bubble under several local
`bubbleId` keys. When `serverBubbleId` is present, Codess treats `(type,
serverBubbleId)` as the stable identity within one composer and keeps the
earliest observed copy. It does not deduplicate across composers or by content.
Type-2 envelopes whose `text` is empty or whitespace-only are known
product/context state, not model messages; they emit no response event or
unknown-loss diagnostic, although tool, compaction, or context evidence is
still normalized. Before ordering and
deduplication, the reader projects each decoded bubble to mapped fields. The
explicitly supported context subset is `conversationSummary`,
`contextWindowStatusAtCreation`, and top-level `messageRequestContext`; other
large attachment/context-selection envelopes remain in captured raw evidence.

### Repetition and Deduplication

Cursor evidence has three distinct repetition cases:

1. **Physical duplicate storage.** The same logical bubble can be stored under
   several local `bubbleId` keys. Within one composer, an available
   `serverBubbleId` proves the duplicate identity described above, so Codess
   retains the earliest observed copy. This is source-level deduplication.
2. **Repeated real events.** Separate file reads, searches, edits, terminal
   commands, tool results, permission decisions, TODO updates, mode changes,
   directory checks, failures, and similar harness actions remain separate
   observations even when their values match. Their source/event identifiers,
   order, time, status, and relationships must be preserved.
3. **Repeated content affecting search presentation.** Distinct events can
   contain equal file bodies, directory responses, status objects, errors,
   prompts, model responses, or result text. This includes a user copy-pasting
   the same prompt and a model emitting the same response more than once.
   Equality of the retained normalized payload is useful for grouping search
   output but is not evidence that the events are duplicates. A truncated
   prefix is not proof that the complete source bodies were equal.

Cases 2 and 3 must never be deleted or coalesced during ingest. Query code may
filter or facet by event kind, actor/role, tool, status, artifact, or source
classification. It may optionally group presentation by content identity plus
semantic dimensions, but a group must retain its occurrence count, time span,
and every constituent stable ID and must expand losslessly to the ordered
events. Corpus measurements and query work belong in generated reports and
the current work registry rather than permanent vendor-format facts here.

“Repeated content” currently means exact equality of the complete retained
normalized content under the same content policy, with compatible event kind,
actor/role, truncation state, tool, and artifact dimensions. Whitespace- or
template-normalized near duplicates, repetitive model phrasing, restatements,
and semantically similar answers are a separate future analysis. Such a method
must be versioned and confidence-bearing, cite its constituent events, and
produce a derived grouping or assertion only; it can never authorize source or
Event removal.

## Capability Vocabulary

Cursor declares a lifecycle vocabulary on the bubble and records no instances of
it. Both halves are worth keeping: the names state which phases the harness
knows about, and the emptiness states that this store is not where they land.

`capabilityStatuses` maps a phase name to a list, present on 8,457 bubbles in
the measured corpus with **every list empty on every one**:

| Phase | Bubbles carrying the key |
|---|---|
| `mutate-request` | 8,457 |
| `start-submit-chat` | 8,457 |
| `before-submit-chat` | 8,457 |
| `process-stream` | 8,457 |
| `chat-stream-finished` | 8,457 |
| `before-apply` | 8,457 |
| `after-apply` | 8,457 |
| `accept-all-edits` | 8,457 |
| `composer-done` | 8,457 |
| `add-pending-action` | 137 |

The order above is a plausible execution order rather than the key order, which
is not stable across bubbles. Nine phases appear together and
`add-pending-action` only sometimes, so it is conditional on the turn rather
than part of the fixed set.

`capabilityType` is a separate numeric enum on 11,454 bubbles with three
observed values: `15` (122,661 occurrences), `30` (44,922), `22` (289). What
each denotes is not established, and it is not the phase set above -- the value
counts match no phase distribution.

**Neither is decoded today.** These names are the closest thing Cursor offers to
the task lifecycle Codex records directly, so if a later release begins
populating the lists, this vocabulary is what a mapping would be built against.
Recording it now is what lets a future comparison show the change.

## Composer Records

`composerData:<composerId>` may include identity, title, model/mode, context,
conversation-header, file-state, and opaque conversation-state fields. It can
also be null.

The Composer title/name is source-system metadata and remains separate from a
mutable Codess Session name. Cursor state fields are version-specific product
evidence; no field is normalized to runtime `active` until a representative
release check establishes its meaning and observation time. Database/change
mtime alone reports Source activity, not a live Session.

`get_composer_data()` currently reports the composer id, top-level keys,
decode/null status, a `conversation` presence check, and selected possible
workspace fields. It is a diagnostic probe, not part of scan or ingest.

Newer composer data may carry stronger structured identity in
`workspaceIdentifier.uri` and `trackedGitRepos[].repoPath`, including remote
workspace URIs. These fields are useful for candidate review. They do not by
themselves authorize mapping a remote or renamed workspace to a local project.
Codess requires an approved project-local `.codess/source-links.json` entry for
that case.

Reliable content normalization currently comes from `bubbleId:*`. Session and
workspace metadata come first from `composerHeaders`; workspace
`composer.composerData` supplies a provenance-labeled fallback when the primary
header is absent. A current header wins when both exist.

## Mapping Boundaries

| Codess concept | Workspace DB | Global DB |
|---|---|---|
| Project | `workspace.json` folder plus workspace `composer.composerData` fallback index | `composerHeaders.workspaceId` joined to a matching `workspace.json`, plus explicitly approved source links for renamed/remote identities; observed local workspace bindings are persisted in the Project catalog |
| Session | Distinct composer id with bubble rows | Same |
| Event | Supported message evidence plus derived tool invocation/result events from each decodable `bubbleId:*` row | Same |
| Event timestamp | Parsed bubble `createdAt`, with epoch-only alternate fallback | Same |
| Stored project path | Resolved workspace folder | Resolved mapped project; header/storage details in metadata |

Scan metrics:

| Metric | Definition |
|---|---|
| Sessions | Distinct composer ids in `bubbleId:*` keys |
| Events | Number of `bubbleId:*` rows |
| Size | Main `state.vscdb` file size |
| Time range | Minimum usable header `createdAt` to maximum usable `lastUpdatedAt` (or `createdAt` fallback) |
| Header coverage | Matched composer headers and headers with at least one usable timestamp; shown by debug scan output |

The global scan row is `(global)` and is not filtered by the requested project
root. Project-level ingest filters global bubbles to the union of current
headers and fallback composer entries mapped to the selected Project's
workspace ids. Archived and subagent flags are preserved
in session metadata and normalized respectively to `archive_state` and
`session_relation_kind=subagent`; unmapped composers are excluded.

Each mapped event retains the `cursorDiskKV.bubble` source designation, numeric
bubble type, exact key locator, declared mapping rule, and structured trace.
`toolFormerData.rawArgs`/`params` are stored as valid JSON: structured values are
serialized, already encoded JSON is retained, and plain strings become JSON
strings. `userDecision=rejected` remains exact metadata and maps to common
`normalized_status=denied` without replacing the source designation.

Malformed timestamps, model values, prompt origins, and tool-input containers
are diagnosed at field scope and omitted independently; other usable content in
the bubble continues through normalization.

Re-ingesting a Cursor database replaces events whose `source_file` is that
database. Sessions removed from the database are deleted only when no events
from another Cursor source remain.

Incremental global ingestion does not use the whole `state.vscdb` mtime as its
functional revision. Cursor frequently changes unrelated global/workbench
state. Codess instead reads each Project's selected `composerHeaders`, the
selected workspace fallback indexes, and `bubbleId:<composerId>:` ranges in
SQLite read transactions and calculates a
non-authenticating change marker from exact header fields, every key and value
length, and the first/last 512 bytes of each value. A changed selected marker
triggers one exact transactional backup for the cohort; unrelated table changes
do not. Selected-row and combined-cohort markers use SHA-256; the bounded edge
method remains a change detector rather than complete content
identity. Exact captured evidence remains fully SHA-256 addressed and verified.

An immediate repeat may reuse those selected markers only when a metadata-only
cache matches the exact Project-to-workspace selection and two observations of
the SQLite main/WAL inode, byte size, and nanosecond mtime are unchanged. This
is a cheap non-authenticating prefilter, not a replacement for the bounded
marker: any main/WAL or selection difference performs the full selected-row
scan in one shared SQLite read transaction. A changing container is rescanned;
`--force` bypasses marker-cache reuse.

Some sidecar-free workspace databases cannot be opened with ordinary SQLite
`mode=ro` even though they are valid standalone files. Codess retries those
only with `immutable=1` after confirming that neither `-wal` nor `-shm` exists.
An indexed prefix existence probe then advances ingest state without parsing or
retaining workspace databases that contain no `bubbleId:*` records.

## Limitations

- Global composers without a usable current-header or workspace-fallback
  mapping are excluded from Project ingest.
- Direct workspace traces can exist without either index, and newer composer
  headers can exist without a surviving workspaceStorage mapping. Candidate
  review should use structured composer identity; ambiguous workspace identity
  remains unattributed. When one fallback composer appears under two or more
  selected workspace indexes, ingest emits the structured diagnostic
  `cursor_ambiguous_fallback_composers` once for that composer and excludes it.
- Scan time ranges remain incomplete when matching headers omit usable
  timestamps. Codess reports header/timestamp coverage in debug output and does
  not decode every bubble merely to improve scan dates.
- Missing required tables or required header identity columns are surfaced as
  source failures or warnings. Optional/more recent header columns are
  tolerated.
