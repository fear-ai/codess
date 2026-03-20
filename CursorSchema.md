# CursorSchema — Cursor IDE `state.vscdb` storage

Vendor-specific structure for **Cursor** chat/composer persistence. Normalized ingest: `src/codess/adapters/cursor.py` (`process_db`, `get_db_metrics`, `get_composer_data`). Scan: `src/codess/scan.py` + `project.py` (workspace + global DB).

**Version note:** Storage moved toward **global** `state.vscdb` for chat in recent versions (e.g. v44.9+); workspace DBs still exist per window. Exact Cursor app version is not embedded in keys.

---

## 1. Document metadata

| Field | Value |
|-------|--------|
| **Vendor** | Cursor |
| **Base dir** | `CODESS_CURSOR_DATA` or OS default under `Cursor/User` |
| **Format** | SQLite 3, table `cursorDiskKV` (key TEXT, value TEXT/BLOB) |
| **Time basis** | `timingInfo.clientStartTime` per bubble (Unix **ms**) |

---

## 2. Storage locations

| Location | Path | Role |
|----------|------|------|
| **macOS** | `~/Library/Application Support/Cursor/User/` | Default base |
| **Windows** | `%APPDATA%\Cursor\User\` | Default base |
| **Linux** | `~/.config/Cursor/User/` | Default base |
| **Global DB** | `{base}/globalStorage/state.vscdb` | Shared / central chat (v44.9+) |
| **Workspace DB** | `{base}/workspaceStorage/<hash>/state.vscdb` | Per workspace folder |

**Workspace hash:** macOS/Windows: birthtime of `workspace.json` parent folder; Linux: inode. `workspace.json` → `folder.path` (or `folder` dict) = project path.

---

## 3. Recommended access

| Method | Use |
|--------|-----|
| **Read-only SQLite** | `file:path?mode=ro` URI; `SELECT key, value FROM cursorDiskKV WHERE key LIKE 'bubbleId:%'` |
| **Codess** | `codess scan`, `codess ingest`; metrics via `get_db_metrics`; metadata probe via `get_composer_data` |
| **Community exports** | legel gist (composerData / bubbleId); prefer **bubbleId** when composerData is null |

---

## 4. Table: cursorDiskKV

### 4.1 Key patterns

| Key pattern | Content summary | Workspace | Central |
|-------------|-----------------|-----------|---------|
| `bubbleId:<composerId>:<bubbleId>` | One chat bubble / message | ✓ | ✓ |
| `composerData:<composerId>` | Optional conversation blob | ✓ | ✓ |

### 4.2 bubbleId value (JSON)

| Field | Type / values | Notes |
|-------|-----------------|--------|
| `type` | 1 = user, 2 = assistant | Maps to roles in adapter |
| `text` | string | Message body |
| `timingInfo.clientStartTime` | number | Unix **ms** |
| `toolResults` | array | Tool name + result payloads |
| `codeBlocks` | array | Optional fenced code |
| `fileActions` | array | Optional file ops |

**Encoding quirk:** Value may be JSON string or **base64-wrapped** JSON (adapter tries both).

**Observed ranges:** Timestamps ms; text length unbounded (adapter truncates on ingest).

### 4.3 composerData value

| Aspect | Detail |
|--------|--------|
| **Shape** | Often JSON with `conversation` array mirroring bubbles |
| **Null** | Frequently **NULL** in DB → exporters skip or error |
| **Project fields** | `workspaceRoot` / `folder` / `projectPath` — **unverified** in public dumps; `get_composer_data()` surfaces them if present |

**Recommendation:** Use **bubbleId** keys for reliable content; use composerData only when non-null and needed.

---

## 5. Project / session / event mapping

| Level | Workspace DB | Central (global) DB |
|-------|--------------|-------------------|
| **Project** | From `workspace.json` → `folder.path` | **None** in DB; scan row `(global)` |
| **Session** | Distinct `composerId` from keys | Same |
| **Event** | Each `bubbleId:*` row | Same |
| **Timestamp** | Per-bubble `clientStartTime` | Same |

---

## 6. Scan metrics (Codess)

| Metric | Definition |
|--------|------------|
| **Sessions** | Count of distinct `composerId` in `bubbleId:%` keys |
| **Events** | Count of `bubbleId:%` rows |
| **Size (mb)** | `state.vscdb` file size on disk |
| **days_ago / span_weeks** | Not computed in scan today; could be derived from min/max bubble times |

---

## 7. Ingest behavior (Codess)

| DB | `project_path` in store | Notes |
|----|-------------------------|--------|
| Workspace | Set to resolved project root | Matched via `workspace.json` |
| Global | `NULL`; `metadata` may include `{"storage":"global"}` | All composers in file |

---

## 8. Quirks & limitations

- **Central DB:** No per-directory filter; all chats in one row in scan output `(global)`.
- **DB bloat:** Forum reports of multi-GB `state.vscdb`; vacuum may not reclaim; use read-only access for tools.
- **composerData null:** Prefer bubbleId pipeline.

---

## 9. Opportunities (engineering)

| Item | Effort |
|------|--------|
| Derive Cursor `days_ago` / `span_weeks` from bubble timestamps | Low |
| Map central composers to project if composerData gains stable path | Medium |
| `--no-central` ingest flag | Low |
| Validate `--source` vendor strings | Low |

---

## 10. Cross-reference

| Topic | Document |
|-------|----------|
| Unified DB columns | **CoSchema.md** |
| Claude Code | **CCSchema.md** |
| Codex | **CodexSchema.md** |
| Backlog / issues | **CoPlan.md** |
