# CursorSchema — Cursor state.vscdb schema (emerging)

cursorDiskKV, composerData, bubbleId, workspace.

---

## Locations

- **macOS:** `~/Library/Application Support/Cursor/User/`
- **Windows:** `%APPDATA%\Cursor\User\`
- **Linux:** `~/.config/Cursor/User/`

- **Global:** `{base}/globalStorage/state.vscdb` (v44.9+ chat)
- **Workspace:** `{base}/workspaceStorage/<hash>/state.vscdb`

---

## Tables

### cursorDiskKV

Key-value store. Key patterns:

- `bubbleId:<composerId>:<bubbleId>` — chat messages
- `composerData:<id>` — may be null in 0.43+

### bubbleId value (JSON)

- `type`: 1=User, 2=Assistant
- `text`: message text
- `codeBlocks`, `fileActions`, `toolResults`
- `timingInfo.clientStartTime` — ms (relative to session)

### Workspace hash

- **macOS/Windows:** birthtime_ms of workspace.json folder
- **Linux:** inode
- `workspaceStorage/<hash>/workspace.json` → `folder.path` = project path

---

## Notes

- Global DB: no per-workspace path in bubbleId keys; project_path filter deferred
- composerData may have workspace info; often null
