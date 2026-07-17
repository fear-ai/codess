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

*Operational criteria imply CLI scan and configuration behavior in **CoPlan.md** (configuration §4, CLI §5).*

### 2.2 Capabilities and priorities

| Capability | Priority |
|------------|----------|
| Find projects with session data (scan) | P0 |
| Ingest CC, Codex, Cursor | P0 |
| Query sessions, tool counts, content | P0 |
| Batch / multi-root (`--dirs`, `--dir`) | P0 |
| Review candidates using session, local Git, activity, ownership, and topic evidence | P1 |
| Execute an explicit reviewed selection without a hidden “worthy” heuristic | P1 |
| Per-source filters (`--source`) | P1 |
| Redaction | P1 |

**Out of scope:** full-text (FTS5) search and Markdown export. Add them to the
active backlog only if the product revives them.

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
| Incremental ingest | mtime state plus transactional source replacement | **CoPlan.md** §3.4, §5.2; **store** / adapters |
| Candidate selection | Separate observations, recommendations, and explicit decisions; local Git review is complementary evidence | **Designs.md** §12; **CoPlan.md** §5.7 |
| Curated batch ingest | Consume an explicit reviewed selection; preserve stage visibility and receipts | **Designs.md** §12; **CoPlan.md** §5.7, §11.7 |
| Baseline/evidence administration | Keep read-only stages callable while safe orchestrators compose them | **Designs.md** §12; **CoPlan.md** §5.7, §11.7 |
| CLI & configuration | Flags, ENV, defaults, and root resolution | **CoPlan.md** §4–§5 |

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
- **Vendors:** CC, Codex, Cursor — filter with `--source` (scan vs ingest semantics differ; **CoPlan.md** §5).
- **Layers, pipelines, and index-led discovery:** **CoPlan.md** §3. **Code-vs-doc facts** checked against the repo: **CoPlan.md** §3.5–§3.6.

---

## 4. Documentation map

### 4.0 Maintenance rules

1. **Boundaries:** Use §4.1 before moving prose. Vendor on-disk facts live in **\*Schema.md**; normalized store in **CoSchema.md** + **`schema/coschema/sqlite/schema.sql`**; operator flags and ENV in **CoPlan.md** §5; implementation status, **verified wiring vs `src/`** (**§3.5–§3.6**), tests, and backlog in **CoPlan.md** (§8 Tests after code, §11 including §11.5 test work, §14–§15).

   *Why one engineering doc owns this:* avoids split-brain between README, random markdown, and CoPlan; reviewers know where to look for “what’s left to do.”

2. **Core set:** **Codess.md**, **CoPlan.md**, **README.md**, **\*Schema.md**,
   **CoSchema.md**, **CompatibilityReview.md**, and
   **`schema/coschema/sqlite/schema.sql`** are durable docs. The compatibility
   review may identify frozen local evidence through its versioned catalog; it
   is not a chronological work log. Do **not** link or refer from core docs to
   short-lived working notes or scratch status files.

3. **Single source:** Avoid duplicating CLI tables or long architecture exposition here; summarize at product level and point to **CoPlan.md**.

4. **Accuracy:** If behavior and docs diverge, fix code or update **CoPlan.md** in the same change; use **CoPlan.md** §14 (resolved + open) when ownership is unclear.

5. **Navigation:** Long engineering docs (**CoPlan.md**) should lead with a **table of contents** (or equivalent). Do **not** repeat a sequential “read §x before §y” roadmap in section bodies—readers use the ToC; **Codess.md** does not duplicate CoPlan’s section order.

6. **Headings:** No **parenthetical qualifiers** in titles—no “(Provisional)”, “(Status)”, “(planned)”, etc. Put status or scope in the **first sentence** under the heading.

7. **Prose, lists, and tables:** Use a **short intro or lead-in** so the reader knows why the section exists. Then use **lists** for scannable facts and **tables only when many comparable fields** need alignment (e.g. wide CLI or ENV matrices). Avoid two-column tables for a handful of facts—use a **tight list** unless comparison across rows is the point. After lists, a **brief wrap** is fine when it adds non-repetitive context (tradeoff, “when to use X”).

8. **Cross-links:** Link to another section **only** when the reader would otherwise miss a dependency or duplicate content. Do **not** sprinkle “see §x” for every related topic.

9. **Work items:** **All** actionable tasks, test work, and tracked issues belong in **CoPlan.md**: **§11** themed backlog tables (including **§11.5** testing), **§8** for strategy and module↔test map, **§14** for current and open decisions, **§15** for consolidated gap themes. **Why:** one queue for triage; **Codess** and **\*Schema** stay spec-only. Ordering and blockers: **§11** intro + row **Notes**, or **§14.2**.

10. **Gaps and open items:** When listing an open question or gap, add enough for discussion: **background** (what broke or what we deferred), **options** with **pro/con**, and a **recommended direction** when the author has one. If undecided, say so explicitly.

**Reading order for implementers:** Use the **table of contents** in **CoPlan.md**; start from **§2** (tree) or **§3** (architecture) as needed.

### 4.1 What each document is for (boundaries)

Use this table to decide **where a change belongs** before editing.

| Topic | Document |
|-------|----------|
| Why the product exists; audience; this index | **Codess.md** |
| Repository layout, layers, data flows, configuration, **CLI tables**, coding, **§8 Tests**, **§3.5–§3.6** status and verified wiring, delivery sequence, backlog **§11**, decisions **§14**, gap themes **§15** | **CoPlan.md** |
| Claude Code paths, index, JSONL fields, scan metrics | **CCSchema.md** |
| Codex session files | **CodexSchema.md** |
| Cursor `state.vscdb` keys and values | **CursorSchema.md** |
| Our normalized `sessions` / `events` columns | **CoSchema.md** |
| Frozen compatibility evidence and coverage gaps | **CompatibilityReview.md** and `catalog/reviewed-baselines.json` |
| Executable DDL | **schema/coschema/sqlite/schema.sql** |

### 4.2 Map table (goal / include / exclude)

| Document | Goal | Include | Exclude |
|----------|------|---------|---------|
| **Codess.md** (this file) | *What* and *why*; product narrative; **§4 doc index** | Goals, framing, high-level architecture diagram, glossary, references, §4.0 rules, boundary table §4.1 | Vendor field catalogs; DDL; CLI flag tables (→ **CoPlan** §5) |
| **CoPlan.md** | *How* the repo implements and validates behavior | Tree, layered architecture, persistence notes, **§3.5–§3.6** status and verified wiring, **§4 configuration**, **§5 CLI**, features→modules, coding, **§8 Tests**, delivery sequence, backlog **§11**, **§14–§15** | Vendor on-disk truth (→ *Schema.md) |
| **CoSchema.md** | Normalized SQLite semantics | Tables, columns, store layout story | Vendor sources |
| **CompatibilityReview.md** | Evidence-backed state of the bounded reviewed corpus | Frozen identities, semantic findings, real-vs-fixture coverage, known gaps | General backlog; chronological work log; copied prompt bodies |
| **schema/coschema/sqlite/schema.sql** | Single executable DDL (avoids duplicated `CREATE` in code) | `CREATE`, indexes; executed by **`store.init_db()`** | Prose; column definitions → **CoSchema.md**; vendor sources |
| **CCSchema.md** | CC storage truth | Layout, metrics, quirks, gaps | Other vendors |
| **CodexSchema.md** | Codex storage truth | Same role as CC for Codex | Other vendors |
| **CursorSchema.md** | Cursor storage truth | Keys, JSON, workspace vs global | Other vendors |
| **README.md** | Onboard quickly | Install, minimal commands, link to **Codess.md** | Doc map (here only) |

Audience separation is intentional:

- **User/operator path:** `README.md` for safe commands and retention warnings,
  then this document for product concepts and selection policy.
- **Contributor/developer path:** `CoPlan.md` for implementation and the one
  work queue, `Designs.md`/`Schemas.md` for rationale, and the vendor/common
  schema documents for source and normalized contracts.
- **Machine contracts:** files below `schema/`; prose explains their meaning but
  does not duplicate executable fields or DDL.
- **Project-local evidence:** `.codess/source-links.json`, manifests, validation
  reports, and snapshots are operational records, not end-user documentation.

**Rule:** Vendor structure → **\*Schema.md**. Implementation tasks → **CoPlan.md** (**§11** backlog, **§8** tests, **§14–§15** questions and themes). Store shape → **CoSchema.md** + **schema/coschema/sqlite/schema.sql**. Core-doc hygiene → **§4.0**; CoPlan editing conventions → **CoPlan §12**.

---

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
