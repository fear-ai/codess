# CCSchema — Claude Code session storage

Vendor-specific structure for **Claude Code** (`@anthropic-ai/claude-code`). Normalized ingest: `src/codess/adapters/cc.py`. Scan: `src/codess/scan.py` (`_session_metrics_cc`).

**Version note:** Claude Code is distributed as a compiled npm package; on-disk formats evolve. Field names below match current Codess parsing and common installs.

---

## 1. Document metadata

| Field | Value |
|-------|--------|
| **Vendor** | Anthropic Claude Code |
| **Primary paths** | `~/.claude/projects/` (override: `CODESS_CC_PROJECTS`) |
| **Encoding** | UTF-8 JSONL |
| **Time basis** | `fileMtime` (ms) in index; record `timestamp` in JSONL (ISO or ms) |

---

## 2. Storage layout

| Path pattern | Role |
|--------------|------|
| `projects/<slug>/` | One directory per project; **slug** = absolute project path with `/` → `-`, prefixed `-` when absolute |
| `projects/<slug>/sessions-index.json` | Session catalog (preferred for scan) |
| `projects/<slug>/<sessionId>.jsonl` | Main session transcript (ingest: top-level `*.jsonl` only) |
| `projects/<slug>/<sessionId>/` | Session subtree; may contain `**/*.jsonl` (subagents, fragments) |

**Slug quirk:** Decode is lossy (`spank-py` vs `spank/py`); Codess uses resolved `projectPath` from the index when present.

---

## 3. Recommended access

| Method | Use |
|--------|-----|
| **Codess scan** | `codess scan --dir <work>`; `--subagent` / `CODESS_SUBAGENT` for sidechain counts |
| **Codess ingest** | `codess ingest --dir <project>`; reads top-level `*.jsonl` per project slug |
| **Direct read** | Parse `sessions-index.json` + `fullPath` or glob `*.jsonl` |

---

## 4. sessions-index.json

Array under `entries` (typical fields used by Codess):

| Field | Type | Notes |
|-------|------|--------|
| `projectPath` | string | Resolved path must match scan project |
| `sessionId` | string | Directory / file stem |
| `fileMtime` | number | Unix **ms**; drives `--days` / recency |
| `messageCount` | number | Approx. messages (user + assistant); scan “events” |
| `isSidechain` | boolean | **true** = subagent session; excluded from scan unless `--subagent` |
| `fullPath` | string | Optional path to primary JSONL; size metric when present |

**Observed ranges:** `fileMtime` large ms since epoch; `messageCount` ≥ 0.

---

## 5. JSONL records and runtime context

Line-delimited JSON contains both transcript content and Claude Code product
state. Persisted records are not a verbatim copy of the model's runtime context.

Runtime context can include system/project instructions, a conversation working
set or compacted summary, a memory index, skill descriptions, loaded tool
schemas, deferred tool names, attachments, and tool results. Exact contents are
assembled dynamically and are not recoverable from normalized message events.

| Pattern | Notes |
|---------|--------|
| **Main session** | `user` / `assistant` with `message.content` blocks (`text`, `tool_use`, `tool_result`) |
| **Subagent** | Messages may carry `isSidechain: true`, `agentId`; linking to parent session not always in file (see GitHub CC issues on `parentSessionId`) |
| **Product state** | Records can include `system`, `mode`, `permission-mode`, `attachment`, `file-history-snapshot`, `queue-operation`, `ai-title`, and `last-prompt` |

Common record-envelope fields include `sessionId`, `uuid`, `parentUuid`,
`timestamp`, `cwd`, `gitBranch`, `version`, and `isSidechain`. Field presence
varies by record type.

The current adapter emits conversation events from `user` and `assistant`
records and one bounded product-state event from `system` records with subtype
`compact_boundary`. It retains the compaction trigger but not compacted summary
or token-accounting bodies. Error tool results are split into explicit
`permission_denied` evidence and other `tool_failure` results. Each emitted
content block has a distinct stable event id. Event metadata retains `uuid` /
`parentUuid`; tool calls and their results also retain the shared tool-use id,
making record and call/result lineage queryable without copying the full
envelope. Task-list metadata under
`~/.claude/tasks/` is separate from transcript JSONL and from live background
processes.

Re-ingesting a changed or forced transcript transactionally replaces its
normalized session events. If the transcript remains valid but yields no
supported events, Codess removes the prior normalized session and reports an
`empty_sources` diagnostic.

**Timestamps:** `timestamp` on record or nested in `message`; ISO 8601 strings or numeric ms.

---

## 6. Subagent vs main (scan & ingest)

| Aspect | Main | Subagent (sidechain) |
|--------|------|----------------------|
| **Index** | `isSidechain: false` | `isSidechain: true` |
| **Typical files** | Top-level `{sessionId}.jsonl` | Often under `{parent}/subagents/` or dedicated `sessionId` dir |
| **Scan default** | Counted | Excluded |
| **Scan + `--subagent`** | Counted | Counted |
| **Ingest** | Top-level `*.jsonl` | Ingested from `{parent}/subagents/**/*.jsonl` |
| **Stored linkage** | No extra session metadata | `is_sidechain`, `parent_session_id`, and `source_relpath` in session metadata |
| **Size fallback** | `fullPath` or `{sessionId}/**/*.jsonl` | Fallback rglob may include subagent bytes if main path missing |

---

## 7. Scan metrics (Codess)

| Metric | Definition |
|--------|------------|
| **Sessions** | Index entries for project (or top-level `*.jsonl` if no index); respects `isSidechain` unless `subagent` |
| **Events** | Sum of `messageCount` from counted entries |
| **Size (mb)** | Sum of `stat()` on `fullPath` targets; else rglob under `sessionId` |
| **days_ago** | `(now_ms - max fileMtime)` / 1 day |
| **span_weeks** | `(max_ts - min_ts)` / 7 days among counted entries |

---

## 8. Quirks & limitations

- Index may omit `fullPath` → size uses directory rglob (may mix subagent files).
- Ingest deliberately recurses only below `{parent}/subagents/`; unrelated nested JSONL fragments are not treated as sessions.
- CC package version not stored in these files; use your installed `claude-code` version separately.
- **Slug decode (implementation impact):** `slug_to_path` is lossy (e.g. hyphen vs path segment). Discovery prefers `projectPath` from `sessions-index.json` when present; `project.py` / scan fall back to slug-derived paths.

## 9. Open implementation gaps (Codess)

| Gap | Detail |
|-----|--------|
| Product-state coverage | Compaction boundaries are normalized narrowly. Mode, permission-mode, attachment, snapshot, title, queue, and other system records remain unsupported. |
| Runtime-context snapshots | Memory, skills, tool schemas, instructions, compaction summaries, and token usage need a separate model if context analysis becomes a goal; audit events do not represent runtime context faithfully. |

---

## 10. Cross-reference

| Topic | Document |
|-------|----------|
| Unified DB columns | **CoSchema.md** |
| Cursor storage | **CursorSchema.md** |
| Codex storage | **CodexSchema.md** |
| Features & code plan | **CoPlan.md** |
