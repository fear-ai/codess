# Codess — Central project document

Goals, product framing, architecture, **documentation map** (authoritative index: §4), glossary, references.

**Implementation guide:** **CoPlan.md** (architecture → configuration → CLI → code & tests).

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

*Operational criteria imply CLI, walk, and configuration behavior in **CoPlan.md** §4–§5.*

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
| Incremental ingest | mtime + state file; idempotent upsert | **CoPlan.md** §3.3, §5.2; **store** / adapters |
| CLI & configuration | Flags, ENV, defaults, walk rules | **CoPlan.md** §4–§5 |

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

**Reading order for implementation:** **CoPlan.md** §2 (tree) → §3 (architecture, before config) → §4 (configuration) → §5 (CLI) → §6–§8 (features, code, tests). This matches progressive detail: mental model, then knobs, then operator contract, then code.

### 4.1 What each document is for (boundaries)

Use this table to decide **where a change belongs** before editing.

| Topic | Document |
|-------|----------|
| Why the product exists; audience; this index | **Codess.md** |
| Repository layout, layers, data flows, **configuration**, **CLI tables**, coding & test strategy, phases, backlog | **CoPlan.md** |
| Claude Code paths, index, JSONL fields, scan metrics | **CCSchema.md** |
| Codex session files | **CodexSchema.md** |
| Cursor `state.vscdb` keys and values | **CursorSchema.md** |
| Our normalized `sessions` / `events` columns | **CoSchema.md** |
| Executable DDL | **sql/CoSchema.sql** |

### 4.2 Map table (goal / include / exclude)

| Document | Goal | Include | Exclude |
|----------|------|---------|---------|
| **Codess.md** (this file) | *What* and *why*; product narrative; **§4 doc index** | Goals, framing, high-level architecture diagram, glossary, references, boundary table §4.1 | Vendor field catalogs; DDL; CLI flag tables (→ **CoPlan** §5) |
| **CoPlan.md** | *How* the repo implements behavior | Tree, layered architecture, persistence notes, **§4 configuration**, **§5 CLI**, features→modules, coding & tests, phases, backlog | Vendor on-disk truth (→ *Schema.md) |
| **CoSchema.md** | Normalized SQLite semantics | Tables, columns, store layout story | Vendor sources |
| **sql/CoSchema.sql** | Single executable DDL (avoids duplicated `CREATE` in code) | `CREATE`, indexes; executed by **`store.init_db()`** | Prose; column definitions → **CoSchema.md**; vendor sources |
| **CCSchema.md** | CC storage truth | Layout, metrics, quirks, gaps | Other vendors |
| **CodexSchema.md** | Codex storage truth | Same role as CC for Codex | Other vendors |
| **CursorSchema.md** | Cursor storage truth | Keys, JSON, workspace vs global | Other vendors |
| **README.md** | Onboard quickly | Install, minimal commands, link to **Codess.md** | Doc map (here only) |

**Rule:** Vendor structure → **\*Schema.md**. Implementation tasks → **CoPlan.md**. Store shape → **CoSchema.md** + **sql/CoSchema.sql**.

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
