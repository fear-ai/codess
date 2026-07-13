# Cursor sessions and status — locations checked

This document records where Composer-related session data was inspected, **how** each location was accessed (including glob patterns and queries), and **what** was found. The original inspection used macOS and Cursor **2.6.20**. It is a point-in-time field report, not a stable Cursor API. A **2026-07-13 recheck against Cursor 3.10.20 and Codess** appears below; statements explicitly described as “found” or “observed” retain their historical meaning.

**Path conventions**

- **`~/`** — home directory (shell tilde expansion). Examples: `~/.cursor/...`, `~/Library/...`.
- **`Users-<user>-Work-ZK-Zero400`** — Cursor’s per-project folder name under `~/.cursor/projects/` includes your macOS short username in the slug. Replace `<user>` with yours (e.g. `Users-alice-Work-ZK-Zero400`).
- **`file://` URLs** — Cursor stores **absolute** paths in JSON (e.g. `workspace.json`). Tilde is not valid there; use `file:///Users/<user>/...` as the generic shape.

---

## Store model: per-project vs user-global

| Store | Root path | Role |
|-------|-----------|------|
| **Per-project Cursor metadata** | `~/.cursor/projects/Users-<user>-Work-ZK-Zero400/` | Cursor’s **project slug** for this folder (derived from filesystem path). Holds agent transcripts for tooling, MCP config pointers, **not** the main Composer SQLite database. |
| **User-global Cursor / VS Code user data** | `~/Library/Application Support/Cursor/User/` | **Single** `globalStorage/state.vscdb` used for Composer `composerData:*` and large KV blobs across workspaces. |
| **Per-workspace VS Code storage** | `~/Library/Application Support/Cursor/User/workspaceStorage/<hash>/` | Folder-to-hash mapping and window state. The original inspection found no `state.vscdb` in the example workspace. Cursor 3.10.20 now creates workspace DBs, although the rechecked example held no `bubbleId:*` or `composerData:*` rows. |

Composer session **records** (titles, bubble headers, timestamps) live in the **user-global** DB. The **per-project** `.cursor/projects/...` tree holds a **narrow** agent transcript export tied to this repo’s project id.

## Current recheck and Codess implementation match

The following facts were rechecked on **2026-07-13** with Cursor **3.10.20**. Counts are volatile while Cursor is running.

### Current global database

The global database now has a third table in addition to the two key/value tables:

```sql
CREATE TABLE composerHeaders (
  composerId TEXT PRIMARY KEY,
  workspaceId TEXT,
  createdAt INTEGER,
  lastUpdatedAt INTEGER,
  isArchived INTEGER,
  isSubagent INTEGER,
  recency INTEGER,
  checkpointAt INTEGER,
  value TEXT
);
```

Observed row counts were **150** `composerData:*` rows, **155,487** `bubbleId:*` rows representing **137** distinct composer ids, and **50** `composerHeaders` rows. Eight `composerData` values and 41 bubble values were `NULL`. The JSON-valued rows remained valid JSON text.

`composerHeaders.workspaceId` now provides an explicit workspace association for the subset of sessions represented in that table. Codess does **not** read `composerHeaders`; it still treats the global DB as an unscoped aggregate.

### Current workspace database

The example workspace hash `243102c47acab6a728df1a9c7dc7067b` now contains `state.vscdb`, WAL, SHM, and backup files. Its DB has `ItemTable`, `cursorDiskKV`, and `composerHeaders`, but at recheck time it contained **zero** `bubbleId:*` and **zero** `composerData:*` rows. The original “no local DB” observation is therefore obsolete as a filesystem claim, while the conclusion that conversation rows were global remained true for this workspace.

### Codess behavior

Codess matches this document in these respects:

- `project.get_cursor_workspace_dbs()` resolves `workspaceStorage/*/workspace.json` and accepts either a string `folder` URI or a `folder.path` object.
- `scan.get_db_metrics()` counts sessions as distinct composer ids in `bubbleId:*` keys and events as bubble rows. It does not count `composerData:*` or `composerHeaders`.
- `adapters.cursor.process_db()` ingests `bubbleId:*` content only. `get_composer_data()` is a metadata probe and is not part of the ingest path.
- Workspace sessions receive the resolved project path. The global DB is also ingested into each selected project's Cursor store, with `project_path = NULL` and metadata `{"storage":"global"}`.

One material mismatch remains: Codess sorts and timestamps bubbles from `timingInfo.clientStartTime`, and `CursorSchema.md` calls that field Unix milliseconds. In the current DB, only **685** bubbles had that field and values ranged from roughly **5,209** to **127,196,698**, which are not epoch milliseconds. By contrast, **147,051** bubbles had a top-level `createdAt` ISO-8601 string ranging from 2025-11-11 through 2026-07-10. Current Cursor ingest can therefore assign incorrect 1970-era session times. The adapter and `CursorSchema.md` should use and test top-level `createdAt`, with an explicit fallback policy for older rows.

---

## 1. Per-project store: agent transcripts (JSONL)

### Full paths

- **Directory:** `~/.cursor/projects/Users-<user>-Work-ZK-Zero400/agent-transcripts/`
- **File found:** `~/.cursor/projects/Users-<user>-Work-ZK-Zero400/agent-transcripts/454bcdef-a17c-4a63-ace1-daf28a83a012/454bcdef-a17c-4a63-ace1-daf28a83a012.jsonl`

### How accessed — glob

- **Tool / pattern:** Recursive glob with root = `agent-transcripts` and pattern `**/*.jsonl` (equivalent: `*.jsonl` under each subfolder). In Cursor’s glob UI this is “search under `agent-transcripts` for any `*.jsonl`”.
- **Concrete equivalent (shell):**  
  `find ~/.cursor/projects/Users-<user>-Work-ZK-Zero400/agent-transcripts -name '*.jsonl'`

### Layout

- One subdirectory per **parent** session UUID: `agent-transcripts/<uuid>/<uuid>.jsonl`.

### Format (technical)

- **JSONL:** one JSON object per line.
- **Lines observed:** objects with top-level `role` (`user` | `assistant`) and `message.content[]` (e.g. `type: "text"`, `text` holding the prompt or reply, sometimes wrapped in `<user_query>` in the stored string).

### Listed / found

| Path | Description |
|------|-------------|
| `.../454bcdef-a17c-4a63-ace1-daf28a83a012/454bcdef-a17c-4a63-ace1-daf28a83a012.jsonl` | Single transcript; content was the **same** Composer thread as UUID `454bcdef-a17c-4a63-ace1-daf28a83a012` (not an archive of all past chats). |

---

## 2. Per-project store: entire project metadata tree

### Full path (root)

`~/.cursor/projects/Users-<user>-Work-ZK-Zero400/`

### How accessed — glob

- **Pattern:** `**/*` with root = the directory above (all files recursively).
- **Concrete equivalent:**  
  `find ~/.cursor/projects/Users-<user>-Work-ZK-Zero400 -type f`

### Listed / found (complete file list at time of listing)

| Path |
|------|
| `~/.cursor/projects/Users-<user>-Work-ZK-Zero400/agent-transcripts/454bcdef-a17c-4a63-ace1-daf28a83a012/454bcdef-a17c-4a63-ace1-daf28a83a012.jsonl` |
| `~/.cursor/projects/Users-<user>-Work-ZK-Zero400/mcps/user-brave-search/SERVER_METADATA.json` |
| `~/.cursor/projects/Users-<user>-Work-ZK-Zero400/mcps/user-brave-search/STATUS.md` |

No `state.vscdb`, no `*.sqlite`, no additional Composer index files under this tree.

---

## 3. User-global store: `state.vscdb` (primary Composer session DB)

### Full path

`~/Library/Application Support/Cursor/User/globalStorage/state.vscdb`

Companion files on disk may include `state.vscdb-wal`, `state.vscdb-shm`, `state.vscdb.backup` (SQLite WAL/checkpoint artifacts); the **logical** database is `state.vscdb`.

### How accessed

- **SQLite CLI:** `sqlite3 ~/Library/Application\ Support/Cursor/User/globalStorage/state.vscdb '<SQL>'` (or `sqlite3 "$HOME/Library/Application Support/Cursor/User/globalStorage/state.vscdb"` — `$HOME` is `~` expanded, needed inside double quotes because of spaces)
- **Python:** `sqlite3.connect(path)` → `execute("SELECT …")` → `json.loads(value)` for text JSON blobs.

### Schema (actual DDL in the original inspection)

```sql
CREATE TABLE ItemTable (key TEXT UNIQUE ON CONFLICT REPLACE, value BLOB);
CREATE TABLE cursorDiskKV (key TEXT UNIQUE ON CONFLICT REPLACE, value BLOB);
```

Both tables are key/value: `key` is unique; `value` is **BLOB** (stored content is typically UTF-8 JSON text for Composer-related rows). Cursor 3.10.20 also has `composerHeaders`; see the current recheck above.

### `cursorDiskKV` — Composer-related key families

| Key pattern | Technical role |
|-------------|----------------|
| `composerData:<uuid>` | One row per Composer session. `value` is JSON; see **composerData JSON** below. |
| `composer.content.<64-char-hex>` | Payload chunks keyed by **hash**, not by Composer UUID in direct key name. |
| `composer.autoAccept.lastSeenHeadSha` | String metadata for auto-accept feature. |
| `composer.autoAccept.lastSeenHeadTimestamp` | Timestamp metadata. |
| `bubbleId:<composerUuid>:<bubbleUuid>` | Per-bubble storage scoped to a Composer id. |
| `agentKv:blob:<64-char-hex>` | Opaque/agent KV blobs; not a session directory. |
| `inlineDiff:<workspaceStorageHash>:<uuid>` | Inline diff state tied to a **workspaceStorage** folder hash and id. |

Example queries:

```sql
-- All composer session rows
SELECT key FROM cursorDiskKV WHERE key LIKE 'composerData:%';

-- Keys mentioning a known composer id (full UUID)
SELECT key FROM cursorDiskKV WHERE value LIKE '%c1e0ea92-1865-4801-af3b-0ebab84c7b77%' LIMIT 30;

-- Approximate row counts
SELECT COUNT(*) FROM cursorDiskKV WHERE key LIKE 'composerData:%';
```

### `composerData:*` JSON — fields used for listing / “empty” detection

Observed `_v` (e.g. `14`) and representative keys:

- **Identity / labels:** `composerId`, `name`, `subtitle`, `richText`, `text` (often empty when using rich text).
- **Timestamps:** `createdAt`, `lastUpdatedAt` (numeric; treated as ms since epoch in analysis).
- **Conversation shape:** `fullConversationHeadersOnly` — array of `{ bubbleId, type }` entries; **count used as bubble/message header count**.
- **Maps:** `conversationMap` — dict (often empty in stub sessions).
- **Mode / model:** `unifiedMode`, `forceMode`, `modelConfig.modelName`, `maxMode`.
- **Context:** `context` (nested mentions, file selections, etc.), `contextTokensUsed`, `contextTokenLimit`.
- **Agentic flags:** `isAgentic`, `status`, `latestChatGenerationUUID`, branch/worktree fields, `originalFileStates` (file URIs touched in that session).
- **Encryption / large state:** `blobEncryptionKey`, `conversationState` (opaque/base64-like), `speculativeSummarizationEncryptionKey`.

**“Empty session” operational definition (used when deleting stubs):**

- `len(fullConversationHeadersOnly) == 0` **and**
- `len(conversationMap) == 0`  
  (parsed from JSON after `json.loads`.)

**Historical counts from that operation (this host, immediately after cleanup):**

- Rows matching empty definition: **140** deleted from `cursorDiskKV`.
- `composerData:%` row count **after** delete: **106** (`SELECT COUNT(*) FROM cursorDiskKV WHERE key LIKE 'composerData:%';`).
- Implied **before** delete: **246** `composerData:*` rows.

**Backup of deleted rows (user-global, same folder as DB):**

`~/Library/Application Support/Cursor/User/globalStorage/empty_composer_backup.jsonl`  
Each line: `{"key":"composerData:…","value":{…}}` (full JSON object as parsed `value`).

### `ItemTable` — UI / workbench keys touching Composer

| Key pattern | `value` shape (typical) |
|-------------|-------------------------|
| `workbench.panel.composerChatViewPane.<pane-uuid>.hidden` | JSON array of `{ id, isHidden }` where `id` is like `workbench.panel.aichat.view.<view-uuid>`. **Pane UUID ≠ `composerId`.** |
| `workbench.backgroundComposer.persistentData` | JSON: `dataVersion`, `lastOpenedBcIds`, `showControlPanel`, `isBackgroundComposerEnabled` (sample had empty `lastOpenedBcIds`). |
| `composer.hasReopenedOnce`, `composer.planMigrationToHomeDirCompleted` | Scalar / small JSON flags. |
| `cursor/composerAutocompleteHeuristicsAutoApplied`, `cursor/composerAutocompleteHeuristicsEnabled` | Feature flags. |

Example:

```sql
SELECT key FROM ItemTable WHERE key LIKE '%composer%' OR key LIKE '%aichat%' OR key LIKE '%Composer%';
SELECT value FROM ItemTable WHERE key = 'workbench.backgroundComposer.persistentData';
```

### Example `composerData` sessions (identified during inspection)

| `composerId` | `name` (if any) | Notes |
|--------------|-------------------|--------|
| `454bcdef-a17c-4a63-ace1-daf28a83a012` | Loss of prior session data | Non-empty `fullConversationHeadersOnly` (tens of bubbles in sample). |
| `c1e0ea92-1865-4801-af3b-0ebab84c7b77` | Settings for minimizing context usage | Large `fullConversationHeadersOnly` (hundreds of headers); `originalFileStates` referenced `file:///Users/<user>/Work/Claude/CContext/...` URIs. |
| `bbf0d8d7-08da-4044-b96a-f9557e0bd977` | (none) | Empty headers / map (example of pre-cleanup stub). |
| `3753e32b-4c08-4988-ae79-4300c3ef8c76` | (none) | Empty stub example. |
| `3a2c6855-4979-4cc1-b84c-bdbcf2c26bd1` | (none) | Empty stub example. |

**Locking:** If Cursor holds the DB open, writes can fail or race with WAL; prefer quitting Cursor before manual `DELETE`/`INSERT`.

---

## 4. User-global store: `workspaceStorage` (per-folder hash, not Composer DB)

### Full path (parent)

`~/Library/Application Support/Cursor/User/workspaceStorage/`

### How accessed

- **List child dirs:** `ls ~/Library/Application\ Support/Cursor/User/workspaceStorage`
- **Resolve folder → hash:** content search for workspace folder string, e.g.  
  `rg -l 'Zero400' ~/Library/Application\ Support/Cursor/User/workspaceStorage`  
  then read matching `workspace.json`.

### Listed / found for this repo

**Mapping file (example full path — hash is opaque and can differ):**

`~/Library/Application Support/Cursor/User/workspaceStorage/243102c47acab6a728df1a9c7dc7067b/workspace.json`

**Contents (shape Cursor stores — absolute `file://`, not `~/`):**

```json
{
  "folder": "file:///Users/<user>/Work/ZK/Zero400"
}
```

The directory name `243102c47acab6a728df1a9c7dc7067b` is an **opaque hash** for this workspace binding; it is **not** the Composer `composerId` and may differ on another machine.

**Glob under that hash** — pattern `**/*`:

| Path |
|------|
| `~/Library/Application Support/Cursor/User/workspaceStorage/243102c47acab6a728df1a9c7dc7067b/workspace.json` |
| `~/Library/Application Support/Cursor/User/workspaceStorage/243102c47acab6a728df1a9c7dc7067b/anysphere.cursor-retrieval/high_level_folder_description.txt` |
| `~/Library/Application Support/Cursor/User/workspaceStorage/243102c47acab6a728df1a9c7dc7067b/anysphere.cursor-retrieval/embeddable_files.txt` |

At the original inspection there was **no** `state.vscdb` under this hash; Composer session rows remained in **global** `globalStorage/state.vscdb`. The 2026-07-13 recheck found a workspace DB at this location, but it contained no Composer or bubble rows.

---

## 5. Cursor CLI (user-global install)

### Full path (binary)

`/usr/local/bin/cursor` → symlink to `/Applications/Cursor.app/Contents/Resources/app/bin/code` (reports **Cursor 2.6.20** with `cursor --help` on the host used).

### How accessed

```bash
cursor --help
```

### Found

Standard file/window/diff/merge options; **no** subcommand or flag documented to open or focus a Composer session by `composerId`.

---

## 6. Application bundle: `product.json`

### Full path

`/Applications/Cursor.app/Contents/Resources/app/product.json`

### How accessed

```bash
rg 'urlProtocol' '/Applications/Cursor.app/Contents/Resources/app/product.json'
```

### Found

`"urlProtocol": "cursor"` — registers the **cursor://** URL scheme at the product level. No verified, stable **cursor://…** URL was documented in these checks for “open Composer id = …”.

---

## Summary table

| Store | Path | Glob / access | What was found |
|-------|------|---------------|----------------|
| Per-project | `~/.cursor/projects/Users-<user>-Work-ZK-Zero400/agent-transcripts/` | `**/*.jsonl` | One JSONL under `454bcdef-…/454bcdef-….jsonl`. |
| Per-project | `~/.cursor/projects/Users-<user>-Work-ZK-Zero400/` | `**/*` | 3 files: transcript + 2 MCP files under `mcps/user-brave-search/`. |
| User-global | `~/Library/Application Support/Cursor/User/globalStorage/state.vscdb` | SQLite + JSON | Original: `ItemTable` + `cursorDiskKV`. Current: also `composerHeaders`; `composerData:*`, `bubbleId:*`, `composer.content.*`, and related rows remain here. |
| User-global | `~/Library/Application Support/Cursor/User/globalStorage/empty_composer_backup.jsonl` | Read line-by-line JSON | Backup of 140 removed empty `composerData:*` rows (if cleanup ran). |
| User-global | `~/Library/Application Support/Cursor/User/workspaceStorage/243102c47acab6a728df1a9c7dc7067b/` | `**/*` after `rg` locate | Original: `workspace.json` + retrieval files, no DB. Current: workspace DB files exist but contain no Composer rows. |
| Install | `/Applications/Cursor.app/Contents/Resources/app/product.json` | `rg` / read | `urlProtocol`: `cursor`. |

---

## Limitations

- Paths use **`~/`** and **`Users-<user>-…`** placeholders; substitute your home and macOS short username. Stored **`file://`** values remain absolute (`/Users/<user>/...`).
- **Cursor version** and internal schema can change; `composerData` field set is **observed**, not a public API.
- **`state.vscdb`** can be large (multi-GB) and contains sensitive content—do not commit it or backups into the repo.
- This file does not define Cursor’s supported behavior; it only documents one inspection and one cleanup.
