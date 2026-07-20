# CursorSchema — Cursor IDE session storage

Vendor-specific structure for Cursor chat persistence. Codess reads it through
`src/codess/adapters/cursor.py`, `src/codess/project.py`, and
`src/codess/scan.py`.

Cursor's SQLite format is private and can change without notice. Use read-only
access and tolerate missing tables, null values, and new fields.

## 1. Locations

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

The separate `~/.cursor/projects/<project-slug>/agent-transcripts/` tree is not
part of the SQLite pipeline and is not currently ingested.

## 2. SQLite tables

### `cursorDiskKV`

Key/value table with unique text keys and text, blob, or null values.

| Key pattern | Content |
|---|---|
| `bubbleId:<composerId>:<bubbleId>` | One conversation bubble |
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
| `createdAt`, `lastUpdatedAt` | Epoch-millisecond header timestamps |
| `isArchived`, `isSubagent` | Session classification flags |
| `recency`, `checkpointAt`, `value` | Cursor state not currently used by Codess |

Codess uses this as the primary global-session index. Composers whose
`workspaceId` maps to the selected Project are imported. Missing timestamp or
classification columns default to null/false; additional columns are ignored.
The table is not a complete historical catalog: Cursor can retain full
`composerData:*` and `bubbleId:*` rows after removing a composer header.

### `ItemTable`

Most rows are editor/workbench state and are ignored. One workspace-local row,
`composer.composerData`, is a secondary session index. Its `allComposers`
entries preserve composer identity, timestamps, archive/subagent flags, and
other header-like metadata for some sessions missing from the live global
`composerHeaders` table. Codess uses this row only for workspaces already
matched to the Project (including approved source links). A composer occurring
in more than one selected workspace fallback is ambiguous and excluded.

## 3. Bubble JSON

Fields relevant to normalization:

| Field | Meaning | Codess status |
|---|---|---|
| `type` | `1` user, `2` assistant-shaped envelope | Mapped only when the record contains message or tool-result evidence |
| `text` | Message body | Sanitized and truncated |
| `createdAt` | ISO-8601 event timestamp | Primary normalized timestamp and sort key |
| `timingInfo.clientStartTime` | Relative client timing, or an epoch value in some legacy shapes | Used only when it plausibly represents Unix seconds or milliseconds |
| `toolFormerData` | One tool name/call id/model-call id, arguments, result, status, and optional `userDecision` | Emitted as a linked invocation and, for final states or a result body, a result/failure event; exact accepted/rejected permission evidence is retained |
| `toolResults` | Legacy/possible tool-result array | Nonempty arrays are mapped for compatibility; the audited local store contains only empty arrays |
| `modelInfo.modelName` | Model selection attached to a user request | Non-`default` values configure the following inferred model turn with exact source-field provenance; `default` remains source metadata |
| `codeBlocks`, `fileActions`, context fields | Product state and supporting content | Not normalized |

Current `toolFormerData.status` values include `completed`, `error`, `loading`,
and `cancelled`. Codess preserves the source value and maps those to succeeded,
failed, running, and cancelled. Cursor therefore contributes evidence-backed
tool-failure audit rows. The audited store also contains 2,936 accepted and 17
rejected `userDecision` values. Rejection maps to normalized `denied`
independently of the status value; acceptance does not erase an observed error.
Cursor still supplies no verified turn-abort or context-compaction shape;
error-looking prose is not evidence.

The audited `modelInfo` objects contain only `modelName`; Codess therefore does
not infer effort, speed, or service tier from names such as `*-fast` or
`*-thinking`. Those labels remain exact model selections.

The adapter uses parsed `createdAt` for sorting and event timestamps. Numeric
fallback values are accepted only when they plausibly represent Unix seconds or
milliseconds; small relative values are rejected.

The global database may repeat the same logical bubble under several local
`bubbleId` keys. When `serverBubbleId` is present, Codess treats `(type,
serverBubbleId)` as the stable identity within one composer and keeps the
earliest observed copy. It does not deduplicate across composers or by content.
Type-2 envelopes whose `text` is empty or whitespace-only are product/context
state, not model messages; they emit no response event, although tool evidence
is still normalized. Before ordering and deduplication, the reader projects each
decoded bubble to mapped fields; large context/attachment envelopes remain in
captured raw evidence instead of normalized metadata or retained memory.

## 4. Composer data

`composerData:<composerId>` may include identity, title, model/mode, context,
conversation-header, file-state, and opaque conversation-state fields. It can
also be null.

`get_composer_data()` currently reports the composer id, top-level keys,
decode/null status, a legacy `conversation` presence check, and selected possible
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

## 5. Codess mapping

| Codess concept | Workspace DB | Global DB |
|---|---|---|
| Project | `workspace.json` folder plus workspace `composer.composerData` fallback index | `composerHeaders.workspaceId` joined to a matching `workspace.json`, plus explicitly approved source links for renamed/remote identities; observed local workspace bindings are persisted in the Project catalog |
| Session | Distinct composer id with bubble rows | Same |
| Event | Supported message evidence plus derived tool invocation/result events from each decodable `bubbleId:*` row | Same |
| Event timestamp | Parsed bubble `createdAt`, with epoch-only legacy fallback | Same |
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
do not. Exact captured evidence remains fully SHA-256 addressed and verified.

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

## 6. Read-only access

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

## 7. Current limitations

- Global composers without a usable current-header or workspace-fallback
  mapping are excluded from Project ingest.
- Direct workspace traces can exist without either index, and newer composer
  headers can exist without a surviving workspaceStorage mapping. Candidate
  review should use structured composer identity; ambiguous workspace identity
  remains unattributed.
- Scan time ranges remain incomplete when matching headers omit usable
  timestamps. Codess reports header/timestamp coverage in debug output and does
  not decode every bubble merely to improve scan dates.
- Missing required tables or required header identity columns are surfaced as
  source failures or warnings. Optional/more recent header columns are
  tolerated.

Cross-vendor normalized columns are defined in `CoSchema.md`. Implementation
tasks, gaps, and ordering are owned by `CoPlan.md` §8.
