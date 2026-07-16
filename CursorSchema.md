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

Codess reads this table when ingesting the global DB. Only composers whose
workspace id maps to the selected project are imported. `composerId` and
`workspaceId` are required for that mapping. Missing timestamp or
classification columns default to null/false; additional columns are ignored.

### `ItemTable`

Editor/workbench state. Codess does not use it for session discovery or ingest.

## 3. Bubble JSON

Fields relevant to normalization:

| Field | Meaning | Codess status |
|---|---|---|
| `type` | `1` user, `2` assistant-shaped envelope | Mapped only when the record contains message or tool-result evidence |
| `text` | Message body | Sanitized and truncated |
| `createdAt` | ISO-8601 event timestamp | Primary normalized timestamp and sort key |
| `timingInfo.clientStartTime` | Relative client timing, or an epoch value in some legacy shapes | Used only when it plausibly represents Unix seconds or milliseconds |
| `toolResults` | Tool name and result payloads | Emitted as normalized tool-result events |
| `codeBlocks`, `fileActions`, context fields | Product state and supporting content | Not normalized |

Current verified bubble shapes do not expose stable permission decisions, a
structured tool-failure flag, turn aborts, or context compaction boundaries.
Cursor therefore contributes no `query --audit` rows; missing results or error-
looking prose are not treated as audit evidence.

The adapter uses parsed `createdAt` for sorting and event timestamps. Numeric
fallback values are accepted only when they plausibly represent Unix seconds or
milliseconds; small relative values are rejected.

The global database may repeat the same logical bubble under several local
`bubbleId` keys. When `serverBubbleId` is present, Codess treats `(type,
serverBubbleId)` as the stable identity within one composer and keeps the
earliest observed copy. It does not deduplicate across composers or by content.
Type-2 envelopes whose `text` is empty or whitespace-only are product/context
state, not model messages; they emit no response event, although any
`toolResults` are still normalized. The exact envelopes remain available under
the selected raw-evidence policy.

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

Reliable content normalization currently comes from `bubbleId:*`; session and
workspace metadata should come from `composerHeaders` when that table is
available.

## 5. Codess mapping

| Codess concept | Workspace DB | Global DB |
|---|---|---|
| Project | `workspace.json` folder | `composerHeaders.workspaceId` joined to a matching `workspace.json`, plus explicitly approved source links for renamed/remote identities |
| Session | Distinct composer id with bubble rows | Same |
| Event | Each decodable `bubbleId:*` row, plus derived tool-result events | Same |
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
root. Project-level ingest filters global bubbles to composer headers mapped to
the selected project's workspace ids. Archived and subagent flags are preserved
in session metadata; unmapped composers are excluded.

Re-ingesting a Cursor database replaces events whose `source_file` is that
database. Sessions removed from the database are deleted only when no events
from another Cursor source remain.

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
```

The main DB may have `-wal`, `-shm`, and backup companions. Do not modify or
vacuum Cursor's live database from Codess. Codess uses URI-safe, query-only
connections with a bounded busy timeout; committed rows still present only in
the live WAL are visible. Global ingest issues prefix-range queries for the
mapped composer ids rather than decoding every bubble in the global database.

## 7. Current limitations

- Global composers without a usable header/workspace mapping are excluded from
  project ingest.
- Direct workspace traces can exist without composer headers, and newer
  composer headers can exist without a surviving workspaceStorage mapping.
  Candidate review should use structured composer identity; ambiguous paths
  remain unattributed.
- Scan time ranges remain incomplete when matching headers omit usable
  timestamps. Codess reports header/timestamp coverage in debug output and does
  not decode every bubble merely to improve scan dates.
- Missing required tables or required header identity columns are surfaced as
  source failures or warnings. Optional/more recent header columns are
  tolerated.

Cross-vendor normalized columns are defined in `CoSchema.md`. Implementation
tasks and ordering are owned by `CoPlan.md` §11.
