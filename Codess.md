# Codess — Central project document

Goals, product framing, architecture, **documentation map** (authoritative index: §4), glossary, references.

**CLI and operations spec:** **CoPlan.md** §6.

---

## 1. Goals and problem

**Problem:** Session records from Claude Code, Cursor, and Codex are valuable for assessing model behaviors, tool usage, cost estimation, and audits—but they are scattered, hard to read (large JSONL, nested structures), and harder to interpret (schema varies by source).

**Solution:** Ingest from multiple sources → normalize to a common schema → query via SQL or CLI. Separation of discovery (scan), ingestion, and querying.

**Goals:** Discover projects with session data; ingest and normalize; query tools/sessions/content; support batch or per-directory workflows.

---

## 2. Product framing (strategy → requirements)

**Re-partitioning (former §2–§5):** Material is ordered **outcomes → capabilities → audiences → traceable requirements** so each layer adds detail without repeating the prior one. Criteria and filters appear once under **2.1**; the feature table **2.2** states *what* we ship; **2.3** states *who cares*; **2.4** links needs to **vendor schema docs** and **CoSchema** instead of restating file layouts here.

### 2.1 Outcomes and constraints

- **Inclusion:** Path exists; session data present; typically git root; not under backup/review dirs.
- **Exclusion:** Invalid paths; slug-decode ambiguity; backup trees (`OLD`, `Save`); review dirs (CodingTools, MCPs, etc.).
- **Filters:** `min_size`, optional future `min_events` / `min_duration` (CC/Codex); Cursor-specific filters TBD — see **CoPlan** backlog.

*Operational criteria imply CLI and walk behavior in **CoPlan.md** §6.*

### 2.2 Capabilities and priorities

| Capability | Priority |
|------------|----------|
| Find projects with session data (scan) | P0 |
| Ingest CC, Codex, Cursor | P0 |
| Query sessions, tool counts, content | P0 |
| Batch / multi-root (`--dirs`, `--dir`) | P0 |
| Per-source filters (`--source`) | P1 |
| Redaction | P1 |
| FTS5 search | P2 |
| Markdown export | P2 |

### 2.3 People and scenarios

| Who | Scenario |
|-----|----------|
| Developer | Tool usage across sessions |
| Researcher | Model behavior, prompt adherence |
| Curator | Discover/prioritize projects to ingest |
| Auditor | Permissions, cost review |

### 2.4 Requirements summary (traceability)

| Need | Detail | Where specified |
|------|--------|-----------------|
| Multi-vendor inputs | CC projects dir, Codex `sessions`, Cursor `state.vscdb` | **CCSchema.md**, **CodexSchema.md**, **CursorSchema.md** |
| Normalized store | SQLite under `<project>/.codess/` | **CoSchema.md**, `sql/CoSchema.sql` |
| Incremental ingest | mtime + state file; idempotent upsert | **CoPlan.md** §3–§4, §7 |
| CLI | `codess scan`, `ingest`, `query` | **CoPlan.md** §6 |

---

## 3. Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   SCAN          │     │   INGEST        │     │   QUERY         │
│ Discovery       │────▶│ Adapters →      │────▶│ SQL / CLI       │
│ + vendor indices│     │ .codess/        │     │                 │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

- **Directory discovery** (walk, excludes, `.codessignore`) is separate from vendor adapters.
- **Vendors:** CC, Codex, Cursor — filter with `--source`.

---

## 4. Documentation map

Each row states **goal** (why the doc exists), **include** (what belongs there), and **exclude** (what belongs elsewhere).

| Document | Goal | Include | Exclude |
|----------|------|---------|---------|
| **Codess.md** (this file) | Single entry point for *what* and *why*; product narrative; doc index | Goals, framing, architecture, glossary, references, **this map only** | Vendor field-level specs; DDL; implementation detail (→ CoPlan §6) |
| **CoPlan.md** | Implement and maintain the codebase | Architecture, feature→module map, coding conventions, **§6 CLI/ops**, phases, backlog, tests, platform | Product vision; vendor paths/fields/values (→ *Schema.md) |
| **CoSchema.md** | Document *our* normalized SQLite | Table/column semantics for `sessions` / `events`; store layout narrative | Vendor source formats (→ CC/Codex/Cursor schema) |
| **sql/CoSchema.sql** | Executable canonical DDL | `CREATE TABLE`, indexes | Prose (→ CoSchema.md) |
| **CCSchema.md** | Claude Code storage truth | Paths, index/JSONL shapes, scan metrics, quirks, open gaps | Codex/Cursor content; architecture/tasks (→ CoPlan) |
| **CodexSchema.md** | Codex CLI session file truth | Same pattern as CCSchema for Codex | CC/Cursor content; architecture/tasks (→ CoPlan) |
| **CursorSchema.md** | Cursor `state.vscdb` truth | Keys, bubble/composer JSON, workspace vs global, scan metrics, quirks, open gaps | CC/Codex content; architecture/tasks (→ CoPlan) |
| **README.md** | Onboard and run commands | Install, minimal examples, pointer to **Codess.md** | **No doc map** (map lives only here, §4) |

**Rule:** Add or change vendor-specific structure only in **CCSchema.md** / **CodexSchema.md** / **CursorSchema.md**. Add implementation tasks only in **CoPlan.md**. Add normalized-store changes in **CoSchema.md** + **sql/CoSchema.sql**.

---

## 5. Glossary

| Term | Definition |
|------|------------|
| adapter | Source-specific parser (CC, Codex, Cursor) |
| event | Normalized record in our DB |
| ingest | Read source → upsert into `.codess/` |
| session | One conversation (varies by vendor; see vendor schema) |
| slug | CC path encoding: `/Users/x/y` → `-Users-x-y` |
| scan | Discover projects with vendor session data (CSV) |

---

## 6. References

- [Claude Code npm](https://www.npmjs.com/package/@anthropic-ai/claude-code)
- [Codex CLI](https://github.com/openai/codex)
- [Cursor forum: chat history](https://forum.cursor.com/t/chat-history-folder/7653)
- [legel: Cursor export gist](https://gist.github.com/legel/ebd0bbc012bf019a1db5212b825e7d16)
