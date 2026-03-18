# Codex and Cursor Session Storage — Investigation

Investigation for CodingSess adapters. SessionRec §3.2, §3.3, §5.2.

---

## Codex (OpenAI)

### Locations
- **Sessions:** `~/.codex/sessions/YYYY/MM/DD/rollout-YYYY-MM-DDTHH-MM-SS-<uuid>.jsonl`
- **History:** `~/.codex/history.jsonl`
- **Config:** `~/.codex/config.toml`, `<project>/.codex/config.toml`

### Format
JSONL, one JSON object per line. Top-level keys: `timestamp`, `type`, `payload`.

### Event types (observed)
| type | payload | Notes |
|------|---------|-------|
| `session_meta` | id, timestamp, cwd, cli_version, base_instructions, git | Session start |
| `response_item` | type=message, role=developer/user, content[] | User/assistant messages |
| `event_msg` | type=task_started, turn_id, model_context_window | Turn boundaries |

### Message structure
- `role`: `developer` (assistant) or `user`
- `content`: array of `{type: "input_text", text: "..."}` blocks
- System prompts, permissions, AGENTS.md injected as `developer` messages

### Adapter approach
1. Glob `~/.codex/sessions/**/*.jsonl` (recursive by date dirs)
2. Parse line-by-line; map `type` + `payload` to normalized events
3. Extract `response_item` with `payload.type=message` → user_message / assistant_message
4. Map tool calls from `payload` (structure TBD — need to inspect command_execution, MCP tool events)
5. `session_meta` → session record (id, cwd → project_path)
6. `history.jsonl` → prompt-level index (optional)

### Project association
`session_meta.payload.cwd` gives project path. No slug encoding like CC.

### Existing tools
- [Codex transcript feature #2765](https://github.com/openai/codex/issues/2765) — proposed in-repo transcripts; not yet implemented
- Session files are append-only; `--ephemeral` sessions not persisted

---

## Cursor

### Locations
- **macOS:** `~/Library/Application Support/Cursor/User/globalStorage/state.vscdb`
- **Workspace:** `~/Library/Application Support/Cursor/User/workspaceStorage/<md5(workspace-path)>/state.vscdb`
- **Windows:** `%APPDATA%\Cursor\User\...`
- **Linux:** `~/.config/Cursor/User/...`

### Format
SQLite. Tables: `ItemTable`, `cursorDiskKV`. Key patterns:
- `composerData:<composerId>` — metadata (allComposers, selectedComposerId); **may have null values** (see gist comments)
- `bubbleId:<composerId>:<bubbleId>` — individual messages

### Message structure (bubbleId)
- `type`: 1 = User, 2 = Assistant
- `text`: main content
- `codeBlocks`: `[{language, code}]`
- `fileActions`: `[{type, path, content?}]`
- `toolResults`: `[{toolName, result}]`
- `timingInfo.clientStartTime`: ms Unix timestamp

### Adapter approach
1. **Global:** `SELECT key, value FROM cursorDiskKV WHERE key LIKE 'bubbleId:%'`
2. **Workspace:** scan `workspaceStorage/*/state.vscdb`; resolve workspace hash → path via `workspace.json`
3. Decode value: JSON or base64→JSON
4. Group by `composerId` (from key `bubbleId:composerId:bubbleId`)
5. Sort by `timingInfo.clientStartTime`
6. Map to normalized events: user_message, assistant_message, tool_call, tool_result

### Caveats
- **Schema drift:** Cursor 0.43+ changed structure; `composerData` may be empty; `bubbleId` works (per gist fork)
- **AI responses server-side:** Some users report assistant content stored server-side; only prompts in `aiService.prompts`
- **Workspace hash:** MD5 of path; algorithm may change
- **DB size:** Can grow large (2.9 GB observed); read-only access

### Existing tools
- [legel export cursor chat history](https://gist.github.com/legel/ebd0bbc012bf019a1db5212b825e7d16) — `composerData` (fails on null); fork uses `bubbleId`
- [cursor-chat-browser](https://github.com/thomas-pedersen/cursor-chat-browser) — browse, export MD/HTML/PDF
- [cursor-export](https://github.com/WooodHead/cursor-export) — export to MD/HTML/JSON
- [SpecStory extension](https://marketplace.visualstudio.com/items?itemName=SpecStory.specstory) — export from Cursor UI
- [cursor-chat-transfer](https://github.com/ibrahim317/cursor-chat-transfer) — transfer between workspaces

---

## Comparison

| Aspect | Claude Code | Codex | Cursor |
|-------|-------------|-------|--------|
| Format | JSONL | JSONL | SQLite |
| Location | `~/.claude/projects/<slug>/*.jsonl` | `~/.codex/sessions/YYYY/MM/DD/*.jsonl` | `state.vscdb` (global + workspace) |
| Project | slug from path | cwd in session_meta | workspace hash → path |
| Structure | user/assistant + tool_use/tool_result | response_item + event_msg | bubbleId messages |
| Tool calls | In assistant content | In payload (TBD) | toolResults in message |
| Incremental | mtime per file | mtime per file | mtime per DB |

---

## Implementation priority

1. **Codex** — JSONL similar to CC; `session_meta` + `response_item` mapping straightforward; tool calls need schema inspection
2. **Cursor** — SQLite + different key layout; `bubbleId` extraction proven; workspace resolution needed
