# CoPlan.md Controlled-Vocabulary Ambiguity Audit

Scope: `/Users/walter/Work/Code/CodeSess/CoPlan.md`, cross-checked against
CoSchema.md, Designs.md, Codess.md, Operations.md, CCSchema.md, CodexSchema.md,
CursorSchema.md. Findings only — no proposed rewrites of CoPlan.md itself.
Ordered most severe/confusing first.

---

## 1. "Registry" — three distinct senses, one term

**Sense A — the config path / CLI flag (`config.REGISTRY`, `~/.codess`, `--registry`).**
- Line 515: "vendor-directory env vars ... are forwarded only by call sites
  that need a non-default vendor source location" refers to `CODESS_REGISTRY`
  in the same table row.
- Line 519: "the child's own `--dir`/`--registry` arguments select the
  Project and registry, not `cwd`" — uses "registry" twice in one sentence,
  once as the literal CLI flag name and once as the generic noun for what it
  selects.
- Confirmed in code: `config.py` — `CODESS_REGISTRY` env var, `REGISTRY`
  module constant, both meaning "the root directory containing all Project
  store sets" (`~/.codess` by default).

**Sense B — "the work registry" (§14, CoPlan's own tracked-item list).**
- Line 5: "It is the sole current implementation-status and work registry."
- Line 18: "the work registry turns each unresolved finding into a
  prioritized item"
- Line 806: "This work is tracked explicitly in the work registry and code
  review."
- Line 1255: "Named use case, defect, source gap, or measured limitation in
  the work registry"
- Line 1856/1858: `## 14. Current Work Registry` — "This registry contains
  only incomplete work."
- This sense has nothing to do with Sense A. It is a section of a Markdown
  document (a table of tracked items), not a filesystem location or runtime
  concept at all.

**Sense C — `registry_store.py`, a usage-statistics store keyed by the
Sense-A root, but a distinct artifact from the Sense-A path itself.**
- Line 142: `registry_store` is listed under "Project catalog" component
  implementation, alongside `project_catalog`, `catalog_operations`,
  `project_annotations`.
- Confirmed in code: `registry_store.py` has `load_registry_data(registry_root)`
  / `save_registry_data(registry_root)` — it reads/writes a JSON stats file
  *located under* the Sense-A registry root, but "registry data" here means
  the stats payload, not the root path itself. A reader who has just learned
  Sense A (registry = `~/.codess`, the store-set root) will plausibly misread
  "registry_store" as "the module that stores/returns the registry [path]"
  rather than its actual job (a small stats cache file living inside that
  root).
- Additional near-miss: line 203/268, `storage_report`'s "whole-registry ...
  scan" (Sense A, adjectival) and the renamed `registry_current_stores`
  function (per session task history — not in CoPlan.md text directly, but a
  live code symbol that will need to be read against this same ambiguity).

**Why ambiguous:** All three senses are capitalization-indistinguishable
(CoPlan never capitalizes any of them as a proper controlled term — all
lowercase "registry"), so nothing in the text signals which sense is meant
at a given point except surrounding context. Sense B in particular has zero
etymological connection to Sense A/C — it reuses the English word "registry"
in its plain "list of registered/tracked items" sense (like a "flight
registry"), which happens to also describe what a Windows-style registry or
a package registry is, compounding the risk of a reader assuming a data-store
meaning throughout.

**Companion-doc cross-check:** Neither Designs.md nor Codess.md uses the word
"registry" at all (confirmed by grep — zero hits in both). CoPlan.md is the
only document using this term, in all three senses, without ever defining
any of them explicitly. This is a CoPlan-only vocabulary gap, not an
inconsistency with the companion docs — but it means CoPlan cannot lean on
those docs for a shared definition.

**Suggested precise definitions (for the next step, not written here):**
- Sense A: "registry root" or "store-set registry" — the filesystem directory
  (default `~/.codess`) that holds all published Project store sets; set by
  `CODESS_REGISTRY` / `--registry`.
- Sense B: "work registry" or, to avoid the word entirely, "work item list" /
  "§14 work items" — Section 14's table of tracked engineering items.
- Sense C: "registry stats" or "usage stats store" — the small JSON file
  `registry_store.py` reads and writes inside the Sense-A root.

---

## 2. "Catalog" — at least four senses, inconsistent capitalization

**Sense A — `catalog/` top-level repo directory ("reviewed Project policies
and evidence").**
- Line 56: `├── catalog/                    # reviewed Project policies and evidence`

**Sense B — "Catalog Services" / "Project catalog", the architecture
component (`project_catalog`, `catalog_operations`, `project_annotations`,
`registry_store`) whose behavioral authority is "Project identity, locations,
workspace bindings, selection, and observations."**
- Line 98/111 (mermaid diagram): `Catalog["Catalog Services"]`
- Line 125: "Query and catalog services share storage infrastructure"
- Line 142: `| Project catalog | ... | Project identity, locations, workspace
  bindings, selection, and observations. |`
- Line 171: "catalog code must not become hidden vendor parsers"
- This sense has *no necessary relationship* to Sense A's directory — the
  component is implemented in flat modules like `project_catalog.py`,
  `catalog_operations.py`, not inside `catalog/`. A reader who just learned
  "catalog/ holds reviewed Project policies and evidence" (Sense A) would
  reasonably expect "Catalog Services" (Sense B) to read/write that
  directory; nothing in the text confirms or denies this.

**Sense C — `codess catalog`, the CLI command family ("Project identity,
selection, locations, and onboarding").**
- Line 952: "`catalog` for Project identity, selection, locations, and
  onboarding"
- Confirmed matching in Operations.md lines 157–158: `codess catalog status`,
  `codess catalog annotations`. This sense is consistent with Sense B (same
  underlying domain), but is a distinct thing — a subcommand namespace, not a
  module or a directory.

**Sense D — generic English "catalog" meaning "list/inventory," used
adjectivally and disconnected from Senses A–C.**
- Line 24: "Catalog, publication, raw evidence, refresh, and retention are
  supporting services." — here "Catalog" (capitalized, sentence-initial) is
  shorthand for Sense B, but reads identically to a generic list-of-services
  enumeration, and its capital-C is an artifact of starting the sentence
  rather than a deliberate proper-noun signal (contrast with "Catalog
  Services" in the diagram, which is unambiguously proper because of the
  diagram-label styling).
- Line 417/426/427/450 (mermaid Scan Flow): `Catalog["Catalog Record"]` — yet
  another variant, "Catalog Record" as a data-flow stage output (scan
  produces "Catalog Record" observations). This is related to but not
  identical to Sense B (the component) — it's the *artifact* the component
  produces during scan, not the component itself.
- Line 1564: "catalog bindings" (lowercase) — refers to the same domain as
  Sense B/C but never capitalized here, alongside capitalized "Catalog
  Services" elsewhere.
- Line 1625/1655/1895: "catalog or pruning workflow logic" — lowercase,
  generic-sounding, but means Sense B/C's domain specifically (maintenance
  scripts that duplicate `catalog_operations` behavior).

**Why ambiguous:** Capitalization is inconsistent across at least five
distinct appearances of what is conceptually "the same" domain (Project
identity/selection/location bookkeeping): "Catalog Services" (proper, in
diagram), "Project catalog" (proper, in table), "catalog bindings" (lower),
"catalog or pruning workflow" (lower), "Catalog Record" (proper, but a
*different* concept — a data artifact, not the component). A reader cannot
tell from capitalization alone whether "catalog" refers to the directory,
the component, the CLI command, or a scan-flow data artifact.

**Companion-doc cross-check:** Codess.md and Designs.md do not use "catalog"
as a term at all (zero hits by grep) — they describe the same domain via
"Project identity," "Project location," "workspace binding" without ever
saying "catalog." This means CoPlan's "catalog" vocabulary is entirely
implementation-internal and has no anchor definition in the higher-level
docs — same gap pattern as "Registry."

**Suggested precise definitions:**
- Sense A: "`catalog/` directory" — repo-tree location for reviewed Project
  policy/evidence files (data, not code).
- Sense B: "Catalog Services" (keep capitalized, consistently) — the
  architecture component owning Project identity/location/binding/selection
  logic (`project_catalog`, `catalog_operations`, `project_annotations`,
  `registry_store`).
- Sense C: "`catalog` command" or "`codess catalog`" — the CLI subcommand
  family.
- Sense D ("Catalog Record" in the scan-flow diagram): rename to something
  that doesn't reuse "Catalog," e.g. "Observation Record" or "Scan
  Observation," since it denotes the *output* of scanning, not the Catalog
  Services component itself.

---

## 3. "Source" — heavily overloaded, at least four senses in active use

**Sense A — CoSchema entity `sources` / "Source revision" (a specific,
capitalized, identity-bearing concept: "unique by source-system namespace,
Source URI, and revision evidence" per CoSchema.md §4.2).**
- Line 402: "Project and Source identity ... Source revisions, and
  provenance keys"
- Line 545: "Source access supplies an adapter with bounded records plus a
  Source revision, stable locator..."
- Consistently capitalized when used this way throughout §6.

**Sense B — "source system" (Claude Code / Codex / Cursor as a vendor
family) — related to but distinct from Sense A (one source *system* can have
many Source *revisions*).**
- Line 41: "one vendor decoder per source system"
- Line 617: "CLI version, source surface" — "source surface" is yet another
  sub-variant.
- Line 1564: "Index-led source observation" (ambiguous between "observation
  of a Source revision" and "observation via the source system")

**Sense C — plain-English "source" meaning origin/provenance in a
non-CoSchema sense: "source code," "source tree," "source-tree development
entry."**
- Line 31: "It answers where implementation, contracts, tests, catalogs, and
  maintenance wrappers live in the source tree."
- Line 36: `main.py # source-tree development entry`
- Line 40: `codess/  # source, domain, store, query, operations` — here
  "source" appears to mean source-*access* modules (Sense B/A adjacent) but
  reads, out of context, as "source code" (Sense C) because it's positioned
  in a code-directory comment.

**Sense D — "source" as a general-purpose modifier compounded dozens of
different ways with different scopes**: `source-annotated`, `source
locator`, `source record`, `source line`, `source evidence`, `source field`,
`source-to-common`, `source-owned`, `source ownership`, `source
relationship`, `source format`, `source case`, `source shape`. Most of these
are compositional (source + noun) rather than distinct controlled terms, but
"source case" (lines 597, 631, 671 — table column headers) and "Source case"
functions almost as a per-section controlled heading without ever being
defined as such, and could be confused with "Source" (Sense A, the entity)
+ "case" (an instance/scenario) versus a standalone controlled term "Source
Case" naming a row-category.

**Why ambiguous:** "Source" is CoSchema's single most heavily used entity
name (Sense A), formally defined in CoSchema.md §4.2, but CoPlan.md
continues to use bare lowercase "source" dozens of times per section for
Sense B/C/D without the reader being able to rely on capitalization as a
disambiguator — CoPlan does capitalize Sense A reasonably consistently
("Source revision," "Source access," "Source identity") but the sheer
density of compound "source-X" phrases in prose (not proper nouns) makes it
easy to misattribute a Sense-B/C/D usage as Sense A, especially for a reader
skimming rather than parsing capitalization carefully. Line 40's directory
comment ("source, domain, store, query, operations") is the clearest single
misreadable instance — a reader primed by CoSchema's "Source" entity could
read this list as "Source [the entity], domain, store, query, operations"
(five architectural concerns) rather than its intended, much more mundane
meaning of "vendor source-access modules" as one item among flat-file
categories.

**Companion-doc cross-check:** CoSchema.md defines "Source" precisely (§4.2)
and Designs.md/Codess.md use it consistently capitalized for the entity
sense. CoPlan.md's usage does not contradict the entity definition, but adds
substantial additional lowercase, non-entity usage the companion docs don't
need to disambiguate against (they don't have a "source tree" / "source
code" layout section).

**Suggested precise definitions:**
- Sense A (keep as-is): "Source" — CoSchema entity, a specific vendor-data
  revision uniquely identified by source-system namespace + URI + revision
  evidence.
- Sense B: "source system" or "vendor" (CoPlan already uses "vendor" as a
  near-synonym elsewhere — e.g. "vendor record processing," "vendor decode"
  — worth checking whether "source system" and "vendor" are meant as
  synonyms or a deliberate distinction; if synonyms, prefer one term).
- Sense C: "source code" / "source tree" (repo-layout sense) — already
  fairly clear from context, lowest-risk of the four, but worth an explicit
  note that this sense is unrelated to the CoSchema entity.
- Sense D: no single fix; these are compositional phrases, not a controlled
  term, but "Source case" specifically (used as a recurring table-column
  header) is a candidate for an explicit controlled heading if it's meant to
  be one.

---

## 4. "Investigation" — component name, doc heading, and generic verb, three senses

**Sense A — `investigation` module (query engine component).**
- Line 147: `| Query engine | `query_api`, `investigation`,
  `configuration_audit`, `artifact_correlation` | ... |`
- Confirmed matching JSON contract: `investigation-v1.json` (line 1671).

**Sense B — "External Investigation Interfaces" (§9.7 heading) — a
completely different subject: third-party BI/observability tool integration
(Datasette, ccusage, OpenTelemetry, etc.), unrelated to the `investigation`
module.**
- Line 1089: `### 9.7 External Investigation Interfaces`
- Line 1889: "Evaluate, design, and plan the external investigation
  interfaces described in Section 9.7"
- This "investigation" is generic English (a user investigating their coding
  session history via some external tool), not a reference to the
  `investigation.py` module or its expansion/correlation logic.

**Sense C — generic verb/gerund "investigation" describing what a user does
with query results (session reconstruction), not a named component.**
- Line 1108: "Session investigation | Search content and structured fields;
  expand a match through Session order, Interaction, Model Turn, tool, and
  Artifact links" — this row header describes a *use case*, and its behavior
  description (expansion through Session/Interaction/Model Turn links)
  actually matches what the `investigation` module (Sense A) implements —
  making this instance a plausible but unconfirmed collision: is "Session
  investigation" here referring to the `investigation.py` module's feature
  set, or coincidentally using the same word for an unrelated user-facing
  description? The text does not say.

**Why ambiguous:** Sense A is an internal module name doing expansion/
correlation query work. Sense B is a document section about integrating
external third-party analysis tools — arguably the *opposite* concern
(external tools looking at Codess data, rather than Codess's own internal
query expansion). A reader encountering "Investigation Interfaces" in a
table of contents, having already learned about the `investigation` module
in §3.2, could easily assume §9.7 documents that module's public interface,
when it in fact documents unrelated third-party tool evaluation.

**Companion-doc cross-check:** Designs.md line 53 uses "cross-Project
investigation" generically (Sense C-like) without reference to the module.
No companion doc defines `investigation.py` explicitly by that name, so
there's no independent anchor to check against.

**Suggested precise definitions:**
- Sense A: keep "investigation module" or "`investigation.py`" for the query
  engine's expansion/correlation code.
- Sense B: rename the §9.7 heading concept to something that doesn't share
  the word, e.g. "External Analysis Interfaces" or "External Reporting
  Tool Integration" — since its subject (Datasette, ccusage, OpenTelemetry)
  is about external consumption/presentation, not query-side investigation.
- Sense C: if "Session investigation" (line 1108) is meant to reference the
  Sense-A module's capability, say so explicitly; if it's coincidental
  reuse of the English word, consider "Session reconstruction" (a phrase
  CoPlan already uses elsewhere, e.g. line 1108's own later text "required
  for reconstruction") for consistency.

---

## 5. "Pointer" — controlled snapshot term vs. incidental generic usage

**Sense A — "current pointer" (the snapshot subsystem's specific artifact:
`current.json`, verified via `manifest_sha256`, read through
`current_snapshot()`).**
- Line 831: "The manifest and current pointer combine the selected
  source-system databases into a Project store set."
- Line 879: "the Project pointer continues to select the last complete
  published store set"
- Lines 196, 212, 247, 263: repeated "pointer" usage in the snapshot
  case-study (§3.4), always meaning this specific file/concept.
- Also matches Designs.md line 373 ("manifest, and current pointer") and
  Codess.md line 155 ("its current pointer form a Project store set") —
  consistent across all three documents. This sense is well-defined and not
  itself a problem.

**Sense B — generic "pointer" meaning an in-source-code cross-reference
comment, entirely unrelated to snapshots.**
- Line 1322: "A source file carries at most a single-line pointer at its
  first S608 site or in its module docstring naming the permitted pattern"
- Line 1454: "no source file carries a docstring note, a pointer comment, or
  any other reference to this section"

**Why ambiguous:** Both usages appear in the same document, unglossed, and
"pointer" is a loaded word in software contexts generally (memory pointer,
foreign-key pointer, file pointer) in addition to Codess's specific
snapshot-pointer meaning. A reader who has internalized §3.4/§8's "current
pointer" as a controlled term (a verified, hash-checked file reference) could
momentarily misread §10.4.4's "pointer comment" as implying some kind of
verified or structured reference, when it just means an ordinary source
comment pointing a reader to §10.4.

**Companion-doc cross-check:** Designs.md and Codess.md only use "pointer"
in Sense A (the snapshot artifact) — they don't have an SQL-suppression
section, so Sense B doesn't arise there. This confirms Sense B is a
CoPlan-only incidental collision, not a cross-document inconsistency.

**Suggested precise definitions:**
- Sense A (keep as-is): "current pointer" — the verified `current.json`
  snapshot-selection artifact.
- Sense B: replace with a word that doesn't collide, e.g. "reference" or
  "citation" ("a single-line citation at its first S608 site").

---

## 6. "Audit" — explicitly disambiguated in-document, but worth flagging as a model case

- Line 684–685: "'Audit' is Codess implementation terminology, not a vendor
  record type or a CoSchema field. It does not mean a security or
  compliance audit. It is a read-only, bounded source-shape measurement..."

This is the *one* term in CoPlan.md that receives an explicit,
self-contained disambiguation against its plain-English meaning (security/
compliance audit) directly in the text. It is not a finding of unresolved
ambiguity — the document already does the disambiguation work — but it is
worth surfacing because (a) it demonstrates a plain-English collision risk
of the exact kind this audit is looking for, confirming the risk is real
enough that the author already felt the need to call it out once, and (b)
the same treatment is not extended to "Registry," "Catalog," "Source," or
"Investigation" above, despite comparable or greater collision risk. Line
10.4.5 also uses "audit" once more generically ("a narrower spot check
during this review... does not license treating S603/S607/S105 as cleared")
without the capital-A controlled sense — but this is low-risk since it's
clearly a verb in ordinary use, not competing with the defined noun sense.

**Suggested precise definition (for consistency, not because it's currently
broken):** "Audit" (capitalized when used as the controlled term) — a
read-only, bounded, structure-only measurement of vendor source shape or
stored capability performed by a `vendor_audits.*`/`*_audit` module; never a
security/compliance review and never an alternate ingest path.

---

## 7. "Store" — extremely high frequency, mostly consistent, one real risk

`Store`/`store` appears ~80+ times. The overwhelming majority are
consistent and low-risk: "Store API," "Storage services," "Project store
set," "source-system store," "store hash," "store boundary" — all
compositionally derived from CoSchema.md's formal §13 definition ("Codess
writes per-source-system SQLite stores... publishes them... as one Project
store set"). This is a large vocabulary but not an *ambiguous* one — context
reliably disambiguates "store" (the persisted SQLite database) from ordinary
English "store" (retail store; the risk flagged in the task brief as
plausible) because the latter sense never actually occurs in CoPlan.md.

One narrower risk: "Legacy-store archival, working-store reset" (line 195)
introduces two new compound terms — "legacy store" and "working store" —
that are not defined anywhere in CoPlan.md, CoSchema.md, Designs.md, or
Codess.md (confirmed by grep: these exact phrases occur only in that one
table cell). A reader encounters them once, in a code-review table, with no
antecedent definition, distinct from the well-established "Project store
set" / "source-system store" vocabulary used everywhere else. This is a
definitional gap rather than a collision, but it means two store-related
compound terms exist entirely outside the otherwise-consistent "store"
vocabulary.

**Suggested precise definition:** Define "legacy store" and "working store"
at first use (likely: "working store" = the live/current source-system
SQLite database(s) prior to baseline preservation; "legacy store" = a prior
version archived by `baseline_operations` before a working-store reset), or
replace with existing vocabulary ("prior published store set" / "current
store set") if they mean the same thing as terms already defined elsewhere.

---

## 8. "Contract" — high frequency, appears consistent but spans several distinct artifact types

`Contract` is used for: the machine-readable JSON schema files
(`schema/*.json`, "Structured Contracts"), the mapping-contract
(`mapping-contract.json`), the "Physical Contract" (a mermaid diagram node
label distinct from the DDL itself), "Executable Contracts" (an architecture
layer in §3.1's diagram, encompassing decode/mapping/query/storage
constraints collectively), and informally "the candidate contract" (§7.1,
not yet a real enforced artifact — described as work-in-progress). None
of these usages plainly collide with each other or with plain English (a
"contract" as an agreement is a reasonable metaphor extension throughout),
but the term names at least five differently-scoped things (one architecture
layer, one diagram node, several file formats, and one not-yet-built
runtime concept) under a single word with no enumeration anywhere of what
counts as "a contract" in Codess. Lower severity than the terms above —
flagged for completeness since the task brief asked about "Contract"-
adjacent generic-vs-controlled patterns, but this one reads more like a
consistent metaphor family than a genuine collision. No quotes reproduced
here since no single pair of usages is actually confusable; noting only
because it's a candidate the next step may want to scope explicitly (e.g.
"which of these five are 'a contract' for the mechanical-enforcement
purposes?").

---

## Terms Checked but Not Found Ambiguous

- **Session** — consistently capitalized as the CoSchema entity throughout
  CoPlan.md; no lowercase/generic collision found (unlike "Source").
  Matches CoSchema.md §4.3 definition exactly.
- **Snapshot** — consistently used for the `.codess/` publication artifact
  (`snapshot.py`, "snapshot root," "snapshot facts," "current snapshot").
  One informal lowercase use as a vendor-side product-state subtype name
  (line 603, "Mode, permission, title, queue, snapshot, and similar product
  state" — a Claude-Code-specific record kind, not Codess's own snapshot
  concept) is a minor false-friend risk worth a one-line note: this list
  item means a vendor UI/product "snapshot" feature, unrelated to Codess's
  own snapshot/publication system, and the coincidence is unglossed.
- **Project** — consistently capitalized and used per Designs.md/Codess.md's
  formal definition ("Stable identity for a continuing body of work").
  No collision found.
- **Interaction**, **Model Turn**, **Event**, **Actor** — all consistently
  capitalized as CoSchema entities when used in the entity sense; "Actor"
  appears only in the entity sense (no generic "actor" usage found). No
  within-document collision found for any of these four.
- **Manifest** — consistently used for the snapshot-publication manifest
  file (`manifest.json`, `manifest_sha256`); no competing sense found.

---

## Summary Ranking

1. **Registry** — three genuinely distinct senses (config path, work-item
   list, stats-cache module), zero capitalization signal, zero definition
   anywhere in CoPlan.md.
2. **Catalog** — four-plus senses (directory, architecture component, CLI
   command, scan-flow data artifact) with inconsistent capitalization across
   them.
3. **Source** — CoSchema's formally defined entity collides in density (not
   meaning) with dozens of lowercase compositional "source-X" phrases,
   including one directly misreadable directory comment (line 40).
4. **Investigation** — module name vs. unrelated §9.7 heading subject
   (external BI tools) vs. one ambiguous coincidental use (line 1108).
5. **Pointer** — well-defined snapshot term collides with two incidental,
   unrelated "source-comment pointer" usages in §10.4.
6. **Store** ("legacy store" / "working store") — undefined compound terms
   outside the otherwise-consistent store vocabulary; not a collision, a
   gap.
7. **Contract** — spans five scoped meanings under one metaphor; consistent
   but unenumerated.
8. **Audit** — already self-disambiguated in-text (line 684); cited as the
   model the other terms lack, not a live finding.
9. **Snapshot** — one minor false-friend (vendor product-state "snapshot"
   subtype vs. Codess's own snapshot system), lowest severity.
