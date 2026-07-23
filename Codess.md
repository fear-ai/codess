# Codess

---

## 1. Goals and problem

**Problem:** Session records from Claude Code, Cursor, and Codex are valuable for assessing model behaviors, tool usage, cost estimation, and audits—but they are scattered, hard to read (large JSONL, nested structures), and harder to interpret (schema varies by source).

**Solution:** Ingest from multiple sources → normalize to a common schema → query via SQL or CLI. Separation of discovery (scan), ingestion, and querying.

**Goals:** Discover projects with session data; ingest and normalize; query tools/sessions/content; support batch or per-directory workflows.

---

## 2. Product framing (strategy → requirements)

### 2.1 Outcomes and constraints

- **Inclusion:** Path exists; session data present or explicit curator interest;
  typically a Git root; not under backup/review dirs. Candidate observations
  recommend consideration but never authorize ingest by themselves.
- **Exclusion:** Invalid paths; slug-decode ambiguity; backup trees (`OLD`, `Save`); reference/review trees (`Code/CodingTools`, `MCP/MCPs`, `Spank/sOSS`, etc.). Third-party source may be inspected explicitly but is not promoted as owned work.
- **Filters:** Scan supports source and recency filters. Ingest supports source
  selection and a run-wide minimum source-file size; it does not define
  vendor-specific event-count or duration thresholds.

### 2.2 Capabilities and priorities

| Capability | Priority |
|------------|----------|
| Find projects with session data (scan) | P0 |
| Ingest CC, Codex, Cursor | P0 |
| Query sessions, orientation, events, and bounded normalized content | P0 |
| Save/replay typed requests, chain stable result IDs, and verify exact evidence | P1 |
| Batch / multi-root (`--dirs`, `--dir`) | P0 |
| Review candidates using session, local Git, activity, ownership, and topic evidence | P1 |
| Execute an explicit reviewed selection without a hidden “worthy” heuristic | P1 |
| Per-source filters (`--source`) | P1 |
| Redaction | P1 |

**Out of scope:** an FTS5 derivative and Markdown export. Bounded normalized
substring search is implemented. The remaining
dispositions are centralized in **CoPlan §8**.

### 2.3 People and scenarios

| Who | Scenario |
|-----|----------|
| Developer | Tool usage across sessions |
| Researcher | Model behavior, prompt adherence |
| Project operator | Safely ingest, capture, relocate, or retire one owned Project |
| Curator | Discover, compare, decide, and onboard a reviewed Project set |
| Release maintainer | Rebuild, freeze, and verify accepted baselines |
| Schema developer | Compare contracts and investigate vendor-format drift |
| Auditor | Permissions, evidence coverage, and reproducibility review |
| Automation / CI | Run noninteractive preflight and verification with versioned reports |

---

## 3. Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   SCAN          │     │   INGEST        │     │   QUERY         │
│ Discovery       │────▶│ Adapters →      │────▶│ SQL / CLI       │
│ + vendor indices│     │ .codess/        │     │                 │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

- **Project discovery** is index-led and separate from event normalization in vendor adapters.
- **Vendors:** CC, Codex, Cursor — filter with `--source`.

---

## 4. Documentation map

### 4.1 Documents and authority

Each document is the single authority for its subject; others link to it rather
than restating it.

| Document | Authoritative for |
|----------|-------------------|
| **README.md** | Installation, Project/vendor selection, investigation workflows, query composition, exports, read-only SQL |
| **Codess.md** | Product goals, requirements, high-level architecture, glossary, and this map |
| **Designs.md** | Functional design rationale, content-processing policy, and alternatives |
| **Schemas.md** | Schema compatibility, evolution, and vendor-translation policy |
| **CoSchema.md** | Logical normalized data, store semantics, and the format contract |
| **CCSchema.md**, **CodexSchema.md**, **CursorSchema.md** | Vendor-owned storage, observed fields, mapping evidence, and access |
| **CoPlan.md** | Code boundaries, runtime/CLI contract, configuration, tests, active work, decisions, and gaps |
| **Operations.md** | Maintainer procedures, safety gates, evidence, storage, retained baselines |
| **CompatibilityReview.md** | Evidence of the reviewed compatibility corpus |
| **experiments/** | Self-contained evaluations that graduate into decisions |
| **schema/** | Executable and machine-readable contracts |

### 4.2 Maintenance rules

Keep one authority for each fact; update the owning document when behavior
diverges from prose. Vendor facts belong only in the matching vendor schema;
executable DDL belongs in `schema/coschema/sqlite/schema.sql`. Do not add dated
chronology, copied command catalogs, or duplicate backlogs to the durable set.
Project-local manifests, receipts, and validation reports are operational
records, not documentation.

## 5. Glossary

| Term | Definition |
|------|------------|
| adapter | Source-specific parser (CC, Codex, Cursor) |
| event | Normalized record in our DB |
| ingest | Read source → transactionally replace its normalized data in `.codess/` |
| session | One conversation (varies by vendor; see vendor schema) |
| slug | CC path encoding: `/Users/x/y` → `-Users-x-y` |
| scan | Discover projects with vendor session data (CSV) |

---

## 6. References

- [Claude Code npm](https://www.npmjs.com/package/@anthropic-ai/claude-code)
- [Codex CLI](https://github.com/openai/codex)
- [Cursor forum: chat history](https://forum.cursor.com/t/chat-history-folder/7653)
- [legel: Cursor export gist](https://gist.github.com/legel/ebd0bbc012bf019a1db5212b825e7d16)
