# CodingSess — Vision, Methodology, and Provider Comparison

**Purpose:** Vision, methodology, provider comparison — what evaluators need.

---

## Documentation Map

| Document | Purpose | Layout | Rules |
|----------|---------|--------|-------|
| **README.md** | Run the tool. Quick start, status, minimal commands/config. | Status → Quick start → Commands (summary) → Store → Config | No methodology, design, or schema. Link to CodingSess §3 for providers; CSPlan §5 for full CLI. |
| **CSPlan.md** | Build and extend. Requirements, design, implementation, validation. | Status → Requirements → Design → Implementation → Validation → CLI Reference → Expansion | No vision or rationale. Link to CodingSess for provider comparison, platform choices. |
| **CodingSess.md** | Understand and evaluate. Vision, methodology, provider comparison. | Map → Vision → Developer needs → Providers → Architecture → Choices → Concerns → References → Glossary | No implementation details or CLI specs. Link to CSPlan for schema, algorithms. |

**Single source:** Only CodingSess lists documents. Other docs do not repeat the map or document explanations.

**When to add:** New material goes to the doc whose purpose it serves. CLI/commands → CSPlan §5. Provider/source details → CodingSess §3. Schema/algorithm → CSPlan §2. Vision/concern → CodingSess.

---

## 1. Vision and Problem

Session records from Claude Code, Cursor, and Codex are valuable for:
- Assessing model behaviors (tool choice, prompt adherence, error recovery)
- Individual and use-case utilization of tools and controls
- Cost estimation, compaction patterns, permission audits

They are hard to read (large JSONL, nested structures) and harder to interpret (schema varies by source). Current tooling answers one question (tool counts) but is tightly coupled to that query. A unified store supports many query types without privileging any single one.

**Core idea:** Ingest from multiple sources → normalize to a common schema → query via SQL or CLI. Separation of ingestion, indexing, and querying.

---

## 2. Developer Needs

| Need | Description |
|------|--------------|
| **Tool usage analysis** | Which tools are used, how often, per session or project |
| **Session discovery** | List sessions by date, project, duration |
| **Permission audit** | When and which tools were denied |
| **Prompt/response extraction** | Pure conversation without tool chatter |
| **Cross-session search** | Find sessions by content, tool, or metadata |
| **Reproducibility** | Trace decisions, commands, and changes |
| **Cost and usage** | Token/usage when available; estimation fallback |

---

## 3. Provider Comparison — Session Store and Features

### 3.1 Overview

| Aspect | Claude Code | Codex | Cursor |
|--------|-------------|-------|--------|
| **Format** | JSONL | JSONL | SQLite |
| **Location** | `~/.claude/projects/<slug>/*.jsonl` | `~/.codex/sessions/YYYY/MM/DD/*.jsonl` | `state.vscdb` (global + workspace) |
| **Project association** | Slug from path | cwd in session_meta | Workspace hash → path |
| **Tool calls** | In assistant content | In payload (TBD) | toolResults in message |
| **Incremental** | mtime per file | mtime per file | mtime per DB |

### 3.2 Claude Code

- **Source:** `Claude` \| `Code` \| `@anthropic-ai/claude-code` semver
- **Primary:** `projects/<slug>/*.jsonl` — full transcripts
- **Also:** MEMORY.md, history.jsonl, debug/, file-history/, plans/, tasks/ — postponed
- **Slug:** Path encoded as `-Users-walter-Work-Spank-spank-py`
- **Transcript:** user/assistant with content[] (text, tool_use, tool_result)

### 3.3 Cursor

- **Source:** `Cursor` \| `IDE` \| About Cursor version
- **Locations:** macOS: `~/Library/Application Support/Cursor/User/globalStorage/state.vscdb`; workspace: `workspaceStorage/<md5(workspace-path)>/state.vscdb`; Windows: `%APPDATA%\Cursor\User\...`; Linux: `~/.config/Cursor/User/...`
- **Format:** SQLite. Tables: `ItemTable`, `cursorDiskKV`. Key patterns: `composerData:<composerId>` (metadata; may be null in newer Cursor), `bubbleId:<composerId>:<bubbleId>` (messages)
- **Message (bubbleId):** type (1=User, 2=Assistant), text, codeBlocks, fileActions, toolResults, timingInfo.clientStartTime
- **Adapter approach:** `SELECT key, value FROM cursorDiskKV WHERE key LIKE 'bubbleId:%'`; group by composerId; sort by timingInfo; map to normalized events
- **Caveats:** Schema drift (0.43+); composerData may be empty; use bubbleId; workspace hash = MD5; DB can grow large (2.9 GB observed)
- **Existing tools:** [legel export](https://gist.github.com/legel/ebd0bbc012bf019a1db5212b825e7d16), [cursor-chat-browser](https://github.com/thomas-pedersen/cursor-chat-browser), [cursor-export](https://github.com/WooodHead/cursor-export), [SpecStory](https://marketplace.visualstudio.com/items?itemName=SpecStory.specstory)

### 3.4 Codex

- **Source:** `Codex` \| `Code` \| `@openai/codex` semver
- **Locations:** `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`; `~/.codex/history.jsonl`; config: `~/.codex/config.toml`, `<project>/.codex/config.toml`
- **Format:** JSONL; `timestamp`, `type`, `payload`. Types: `session_meta` (id, cwd, cli_version, base_instructions, git), `response_item` (type=message, role=developer/user, content[]), `event_msg` (task_started, turn_id, model_context_window)
- **Message:** role=developer (assistant) or user; content: `{type: "input_text", text: "..."}`; system prompts, permissions, AGENTS.md as developer messages
- **Project:** `session_meta.payload.cwd` gives project path; no slug encoding
- **Adapter approach:** Glob `~/.codex/sessions/**/*.jsonl`; map type+payload to normalized events; tool calls from payload (structure TBD)
- **Existing tools:** [Codex transcript #2765](https://github.com/openai/codex/issues/2765) — proposed in-repo transcripts; not yet implemented

---

## 4. Architecture (High-Level)

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   INGESTION     │     │    INDEXING     │     │     QUERY       │
│ Read JSONL/     │────▶│ Normalize       │────▶│ SQL / CLI /     │
│ SQLite per      │     │ Incremental     │     │ ad-hoc scripts  │
│ source adapter  │     │ update          │     │                 │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

**Separation:** Ingestion produces a normalized store. Queries never touch raw sources.

**Store:** Project-local `<project>/.coding-sess/sessions.db`. Derive project from git root or cwd.

---

## 5. Platform Choices and Project Direction

### 5.1 Choices

| Choice | Decision | Rationale |
|--------|----------|-----------|
| **Store** | SQLite | Portable, queryable, FTS5 when needed |
| **Location** | Project-local | Coding tools know where to put .files; git-ignorable |
| **Project scope** | Git repo root | Standard for dev tools |
| **FTS5** | Postponed | Start with B-tree; add when full-text needed |
| **Sidecar** | Off by default | No archive of re-extractable content |
| **Redaction** | Optional `--redact` | Default: control chars + ANSI only |

### 5.2 Direction

- **Phase 1:** CC only; ingest + SQLite + CLI
- **Phase 2:** Derived tables, FTS5 when needed
- **Phase 3:** Codex, Cursor adapters; unified store
- **Phase 4:** Ad-hoc queries, templates, optional embedding

---

## 6. Concerns and Gaps

### 6.1 Known Gaps

| Gap | Mitigation |
|-----|------------|
| Schema drift | Version adapter; sample before ingest |
| Cursor/Codex schema changes | Adapter updates; §3.3, §3.4 |
| System reminders | Not in JSONL; would need CC telemetry |
| Compaction | Summary replaces history; raw turns lost |
| IDE context | Cursor/Codex: selections, cursor; TBD per product |
| MCP tools | Structure may differ; treat as generic for now |

### 6.2 Design Concerns

- **progress records:** ~60% of CC lines; redundant with final assistant. Drop.
- **Tool result pairing:** tool_result references tool_use by id; two-pass or lookup needed.
- **Truncation:** Limits and content_len policy in [CSPlan §2.6](CSPlan.md#26-truncation-specification).

---

## 7. References

### Cursor
- [Cursor CLI](https://cursor.com/en/cli)
- [legel: Cursor chat export (SQLite)](https://gist.github.com/legel/ebd0bbc012bf019a1db5212b825e7d16)
- [cursor-chat-browser](https://github.com/thomas-pedersen/cursor-chat-browser)
- [Cursor forum: chat history](https://forum.cursor.com/t/chat-history-folder/7653/2)

### Codex
- [Codex CLI (openai/codex)](https://github.com/openai/codex)
- [Codex CLI reference](https://developers.openai.com/codex/cli/reference)
- [Codex config reference](https://developers.openai.com/codex/config-reference)
- [Codex transcript #2765](https://github.com/openai/codex/issues/2765)

### Claude Code
- [@anthropic-ai/claude-code (npm)](https://www.npmjs.com/package/@anthropic-ai/claude-code)
- [Inside ~/.claude (diljitpr)](https://www.diljitpr.net/blog-post-2026-02-24-inside-dot-claude-filesystem-architecture.html)
- [claude-code-system-prompts](https://github.com/Piebald-AI/claude-code-system-prompts)

---

## 8. Glossary

| Term | Definition |
|------|------------|
| **adapter** | Source-specific parser that extracts events from raw format (JSONL, SQLite) |
| **event** | Normalized record: event_type, subtype, role, content, tool_name, etc. |
| **event_id** | Business key component; line number in JSONL for CC |
| **ingest** | Read source files, normalize, upsert into store |
| **session** | One conversation; one JSONL file (CC) or composer (Cursor) |
| **slug** | Path encoded for CC: `/Users/x/y` → `-Users-x-y` |
| **source** | Product: Claude, Cursor, Codex |
| **tool_call** | Assistant request to run a tool (Bash, Read, Edit, etc.) |
| **tool_result** | User message with tool output or permission_denied |
| **truncation** | Limit content length; store content_len; append … |

---

## 9. Relationship to CSPlan

CodingSess holds rationale and context; CSPlan holds specification. Routing: [Documentation Map](#documentation-map) and "When to add" rules. No intentional duplication; cross-references link levels.
