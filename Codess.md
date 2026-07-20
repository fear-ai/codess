# Codess

---

## 1. Goals and problem

**Problem:** Session records from Claude Code, Cursor, and Codex are valuable for assessing model behaviors, tool usage, cost estimation, and audits—but they are scattered, hard to read (large JSONL, nested structures), and harder to interpret (schema varies by source).

**Solution:** Ingest from multiple sources → normalize to a common schema → query via SQL or CLI. Separation of discovery (scan), ingestion, and querying.

**Goals:** Discover projects with session data; ingest and normalize; query tools/sessions/content; support batch or per-directory workflows.

---

## 2. Product framing (strategy → requirements)

Material is ordered **outcomes → capabilities → audiences → traceable requirements** so each layer adds detail without repeating the prior one. Criteria and filters appear under **2.1**; the feature table states what ships; the remaining sections link needs to vendor schemas and **CoSchema** instead of copying file layouts.

### 2.1 Outcomes and constraints

- **Inclusion:** Path exists; session data present or explicit curator interest;
  typically a Git root; not under backup/review dirs. Candidate observations
  recommend consideration but never authorize ingest by themselves.
- **Exclusion:** Invalid paths; slug-decode ambiguity; backup trees (`OLD`, `Save`); reference/review trees (`Code/CodingTools`, `MCP/MCPs`, `Spank/sOSS`, etc.). Third-party source may be inspected explicitly but is not promoted as owned work.
- **Filters:** Scan supports source and recency filters. Ingest supports source
  selection and a run-wide minimum source-file size; it does not define
  vendor-specific event-count or duration thresholds.

Command behavior and configuration are documented in **CoPlan.md** §§3–4;
task-oriented use is documented in **README.md**.

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

### 2.4 Requirements summary (traceability)

| Need | Detail | Where specified |
|------|--------|-----------------|
| Multi-vendor inputs | CC projects dir, Codex `sessions`, Cursor `state.vscdb` | **CCSchema.md**, **CodexSchema.md**, **CursorSchema.md** |
| Normalized store | SQLite under `<project>/.codess/` | **CoSchema.md**, `schema/coschema/sqlite/schema.sql` |
| Incremental ingest | mtime state plus transactional source replacement | **CoPlan.md** §§2.4, 4.2; **store** / adapters |
| Candidate selection | Separate observations, recommendations, and explicit decisions; local Git review is complementary evidence | **Designs.md** §12; **Operations.md** |
| Curated batch ingest | Consume an explicit reviewed selection; preserve stage visibility and receipts | **Designs.md** §12; **Operations.md** |
| Baseline/evidence administration | Keep read-only stages callable while safe orchestrators compose them | **Designs.md** §§2, 12; **Operations.md** |
| CLI & configuration | Flags, ENV, defaults, and root resolution | **CoPlan.md** §§3–4; **README.md** |
| Typed investigation | Stable Project-bound request/result contracts, bounded output, chaining, and exact evidence | **README.md**; **Designs.md** §13; `schema/query-*-v1.json` |

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
- **Vendors:** CC, Codex, Cursor — filter with `--source`; scan, ingest, and
  query semantics are documented in **CoPlan.md** §4.
- **Layers, pipelines, and index-led discovery:** **CoPlan.md** §2.

---

## 4. Documentation map

### 4.1 Audience paths

- **Users and customers:** use **README.md** for installation, investigation
  workflows, exports, and direct read-only access.
- **Product and schema reviewers:** use this specification, **CoSchema.md**, the
  three vendor schema documents, **Designs.md**, and **Schemas.md**.
- **Contributors:** use **CoPlan.md** for implementation, tests, priorities, and
  open decisions.
- **Maintainers:** use **Operations.md** for preflight, baseline publication,
  evidence refresh, relocation, storage, and retention.

### 4.2 Document authority

| Document | Authoritative for | Excludes |
|----------|-------------------|----------|
| **README.md** | Installation, Project/vendor selection, investigation use cases, query composition, exports, safe read-only SQL, and audience routing | Baseline publication; code architecture; backlog |
| **Codess.md** | Product goals, requirements, high-level architecture, glossary, and this map | Detailed CLI flags; implementation tasks |
| **Designs.md** / **Schemas.md** | Functional design rationale, content-processing policy, alternatives, compatibility, evolution, and translation policy | Daily commands; work status |
| **CoSchema.md** | Logical normalized data and store semantics | Vendor storage truth; SQLite tuning detail |
| **CCSchema.md**, **CodexSchema.md**, **CursorSchema.md** | Vendor-owned storage, observed fields, mapping evidence, and limitations | Universal product semantics |
| **CoPlan.md** | Repository/code boundaries, runtime and CLI contract, configuration, tests, delivery order, actionable work, and decisions | Product requirements; operating procedures |
| **Operations.md** | Maintainer procedures, safety gates, evidence, storage, retained baselines, and Claude process recovery | End-user research tutorial; design rationale |
| **CompatibilityReview.md** | Evidence-backed coverage of the bounded reviewed corpus | General backlog; chronology |
| **schema/** | Executable and machine-readable contracts | Narrative requirements and rationale |

### 4.3 Maintenance rules

Keep one authority for each fact. Requirements change here; functional or
schema rationale changes in **Designs.md** or **Schemas.md**; implementation,
tests, and actionable work change in **CoPlan.md**;
procedures change in **Operations.md**. Vendor facts belong only in the
matching vendor schema, and executable DDL belongs in
`schema/coschema/sqlite/schema.sql`.

When behavior and prose diverge, update the owning document in the same change.
Do not put dated chronology, copied command catalogs, transient scratch notes,
or duplicate backlogs into the durable documentation set. Project-local
manifests, receipts, and validation reports are operational records rather than
customer documentation.

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
