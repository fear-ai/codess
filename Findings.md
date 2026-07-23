# Findings and decisions — schema authority, compaction, consistency, v4

This document records investigation findings and decisions that are cross-cutting
and evidence-based, distinct from the per-vendor fact documents (`CCSchema.md`,
`CodexSchema.md`, `CursorSchema.md`), the combined contract (`CoSchema.md`), and
the borrowed-lessons record (`Schemas.md`). It is the general findings log; the
authoritative work queue, gaps, and decision register remain in **CoPlan.md §8**,
and this document adds to them rather than replacing them.

**Weight of evidence.** Findings here are graded. Statements marked **[measured]**
come from querying real local snapshots or running code; **[web]** from external
sources summarized in §7; **[code]** from reading the implementation. Prior
prose documents were partly LLM-composed suppositions: they can be trusted for
blow-by-blow descriptions of what code does, but their *opinions and certainty*
(especially binary "X is impossible" claims) carry little weight and several were
found wrong here. Everything in Codess is best-effort and representative, not
proven correct at some higher authority.

---

## 1. The contract authority (general principle)

The authority for what a record *means* is the logical contract
`schema/coschema/contract.json`. The SQLite DDL, the vendor mapping profiles,
and the adapter code are *representations that must agree with the contract*,
checked by a gate — none is itself the contract.

The borrowed lesson from `~/Work/Github/Schema` was originally "JSON Schema is
not the authority." Generalized from this project's own evidence:

> No single representation — not JSON Schema, not the SQLite DDL, not a vendor's
> own on-disk format — is the contract. The authority is a representation-
> independent logical contract, enforced by an executable, bidirectional gate.

**[code]** `validate_database_contract()` (`src/codess/schema_contract.py:166`)
is *structural*: it reports missing contracted columns, uncontracted physical
columns, and JSON columns not enforced by SQLite. It is correctly fail-closed —
a missing column is a real defect. It is **not** the value-level gate discussed
in §4; do not conflate the two.

`validate_mapped_event()` (`:125`) adds provenance: each event names its source
identity, primary `mapping_rule`, structured `mapping_trace`, and valid JSON tool
input.

### Roles the physical columns actually play

The DDL columns fall into three deliberate roles; the design succeeds where each
is honored:

1. **Identity/meaning columns** carry the contract. The clearest success is the
   four-way split `actor_kind` / `content_role` / `origin_kind` / `event_kind`,
   which lets a harness-injected message be stored as
   `actor_kind=harness, origin_kind=harness_injected, event_kind=message.context`
   instead of being flattened into `role='user'` — this out-performs every
   vendor's native format. The null-safe `model_configurations` identity
   (eight coalesced columns) is a second success: it keeps *absent*, *default*,
   and *unknown* distinct.
2. **Denormalized query-convenience columns** chosen on purpose:
   `events.tool_name`, `artifact_path`, `event_at` duplicate data reachable via
   joins but are kept flat and indexed so common queries are one indexed scan.
3. **Compatibility-projection columns** explicitly labeled in the DDL
   (`sessions.source/type/release/project_path`,
   `events.event_type/subtype/role/timestamp/file_path`). These are *outputs* of
   the mapping, never inputs; `physical_contract` classifies them so the gate
   does not mistake them for meaning.

An adapter that ever *wrote from* a role-2 or role-3 column, or a role-1 column
denormalized without a contract entry, is caught by the structural gate.

---

## 2. Compaction detection — evidence-first

Prior docs stated Cursor and Codex have no compaction shape and that only
Claude's `compact_boundary` is real. Only Claude has a verified local record:

- **Codex — no local compaction record [measured].** A structure-only scan of
  all 26 local transcripts found **no `compaction` record type** (`response_item`
  payloads seen: reasoning, function_call(_output), message,
  custom_tool_call(_output), ghost_snapshot, web_search_call, tool_search). The
  `encrypted_content` field that a **[web]** summary tied to compaction is
  actually the Fernet-encrypted `reasoning` trace (19,353 items), unrelated.
  Codex compaction is therefore server-side or absent in these releases; Codess
  emits nothing until a real record is observed (**T4**).
- **Cursor** auto-summarizes at ~100% context and offers a `/compress` command
  **[web]**. Whether a stored bubble/composer marker survives is **unconfirmed**;
  establish by running `get_composer_data()` against a summarized session.
- **Claude** is Tier-1 via `system.compact_boundary` (`cc.py:830`), already
  parsed. **[code]**

### Detection tiers (goal is precision/accuracy however reached)

- **Tier 1 — direct vendor record (highest precision).** Claude `compact_boundary`
  only, today. Map to `event_kind=context.compact`, no inference. (Codex would
  join if a real record appears.)
- **Tier 2 — corroborating signals**, always confidence-graded, never a hard
  claim:
  - long engagement gap — **[measured]** Zero400 has real inter-event gaps of
    60,918 / 31,191 / 15,223 minutes (≈42 / 22 / 10 days): these mark
    session-resume boundaries that correlate with, but do not prove, compaction;
  - injected-prompt length/phrasing signature — a long, templated, near-identical
    handoff prompt (Codex's compaction prompt is "nearly identical to the
    open-source versions");
  - memory-file writes near a boundary — queryable via `event_artifacts`;
  - context-size drop — weak alone (no token counts stored).

### Calibration to actual usage (owner's pattern)

The corpus owner rarely tracks context visually and almost never manually
compacts; `/compact` was used mostly on Claude, hardly on Codex. Consequences:
- Claude compactions are user-initiated `compact_boundary` — **Tier-1, solved.**
- Codex compactions leave **no observed local record** (scan above); they cannot
  be detected from the transcript in these releases. Reopen only under **T4**.
- Cursor compactions are rare (never user-triggered); the prompt-signature
  heuristic is weak because the user does not inject. Run the probe first; build
  Cursor inference only if a stored marker exists.

**Conclusion:** Tier-1 covers essentially all real compaction in this corpus
(Claude manual + Codex auto). Signal-based inference is a thin Cursor-only
fallback, low priority. Emit `indeterminate` (see §4) where no evidence exists;
never overclaim. Recorded as decision **D15**.

---

## 3. SQLite access consistency — real vs. aspirational (verified in code)

**Real and working [code]:**
- `raw_store.py:_sqlite_backup()` uses the SQLite online backup API
  (`source.backup(target, pages=256, sleep=0.01, progress=…)`) over a `mode=ro`
  source, forces `journal_mode=DELETE` to make the copy standalone, and runs
  `quick_check`, raising `RawCaptureError` on failure — a genuine transactionally
  consistent snapshot of a live WAL database.
- `cursor_source.py:connect_readonly()` — `mode=ro` + `query_only=ON` +
  `busy_timeout=5000`; `immutable=1` only when no `-wal`/`-shm` sidecar exists.
- `get_selection_markers()` reads all selected rows inside one `BEGIN`
  transaction; `cursor_cohort.py` captures once and reuses a content-addressed
  object.

**Tests that exist [code]:** `test_cursor_cohort.py` (cache reuse asserts
`quick_check=ok`; exact-container/scope marker cache; per-project state;
source-change new revision), `test_snapshot_raw.py`. Full suite: **492 passed
[measured]**.

**Gap (aspirational / missing):** no test simulates a write landing *during* the
backup (torn/advancing read), and there is no capture-verify-recapture stability
loop. The consistency *primitive* is solid; *evidence that it held under
concurrent writes* is not tested. This is why Zero400's live shared Cursor DB
could only be accepted on the observation-independent normalization digest, not
the full semantic digest.

**Orderly harness shutdown:** offered as an **opt-in hint only** — detect a
running harness, suggest closing it, and prefer idle capture windows; never force
a kill. The backup-over-live-WAL path already handles concurrent writes, so
shutdown is a quality bonus, not a requirement. Recorded as **D16**.

### Consistency techniques — effort / impact / reliability / sequence

| # | Technique | Effort | Impact | Reliability | Order |
|---|-----------|:------:|:------:|:-----------:|:-----:|
| 1 | Capture-verify-recapture loop (re-read marker after backup; record `consistency=source_advanced` if advanced) | Low | High | High | 1 |
| 5 | Concurrency fixture: simulate WAL advance mid-capture; assert advance is recorded and digest stable | Med | High | High (test) | 2 |
| 3 | Idle-window detection + opt-in quiesce hint | Med | Med | Med | 3 |
| 2 | WAL frame-count observed before/after capture | Low | Med | Med | 4 (optional) |

`#1` first: lowest effort, and it converts "we hope it was consistent" into
per-capture evidence, unblocking full-semantic acceptance for Zero400. `#5` next
proves `#1`. `#3` is the quality lever. `#2` is redundant once `#1`+`#5` exist.
(A `BEGIN IMMEDIATE` variant is inapplicable to a read-only source.)

---

## 4. The acceptance gate is too strict — three-outcome fix

The over-strict behavior is in the **value-level acceptance/comparison** path
(digest/settings), not the structural contract gate of §1. A single differing
value should not fail an entire store when the difference is an absent or
uninterpreted field.

**Decision:** the gate is a **two-value comparison** (rebuilt store vs. prior
store), so its outcomes name a relationship between two values, per-field/row:
`match` (both `present` and equal) / **`mismatch`** (both `present` and differing)
/ **`vacant`** (a side is not a real value). The `vacant` token and the blocking
`fatal`/`advisory` scale are **shared with the field-state taxonomy** (D18 /
`src/codess/field_state.py`), so ingestion and acceptance name the same concept
identically. **Precedence criterion (encoded in `field_state.compare`):** `vacant`
beats `mismatch` — a difference caused only by one side being absent/uninterpreted
is `vacant`, so `mismatch` is emitted only when both sides are `present` and
differ. A `mismatch` or `vacant` on a **declared-critical** field (identity,
ordering, lineage) is `fatal` and fails; everything else is `advisory`, reported
not fatal. The coarse `present`/`vacant` split is the default; the fine states are
available where the distinction matters. This operationalizes the
vendor-vs-session rule (**D13**): an unsupported / ignored / absent value is a
*declared* outcome, never a silent failure. Recorded as **D17** (harmonized with
D18); prerequisite for v4 *promotion*. (Note: D15 uses `indeterminate` for a
distinct third concept — inconclusive *evidence* — intentionally not merged into
this field/value vocabulary.)

---

## 5. v4 status — already writing, needs hardening not development

**[measured]** The v4 rebuild has **already partially executed**: `current.json`
for Zero400 shows `format_version: 4` with snapshot
`20260718T095547.634299Z-coschema4-…`; at least three projects have `coschema4`
snapshots on disk. `schema_contract.py` has `FORMAT_VERSION = 4`; the full suite
is **492 passed**, including 20 schema-contract tests covering durable identity,
SQLite JSON enforcement, mapping-event provenance, legacy/foreign-package
refusal, null-safe model identity, the materialized event graph, all three
vendor hazards, and a fail-closed evolution gate.

So the honest status is: **the writer is validated and producing real v4
snapshots.** What remains is *hardening and truth-sync*, not writer development:

| Missing | Where |
|---|---|
| Concurrent-write stability test | §3 `#5` |
| Three-outcome (`vacant`) acceptance, harmonized with field states | §4 / D17 |
| Codex compaction Tier-1 parser | §2 / D15 |
| Doc truth-sync (`CoSchema.md` "candidate", `CompatibilityReview.md` "v3", vendor compaction denials) | §6 |

Docs still describe v4 as "candidate / frozen at v3"; that is stale and must be
corrected. Reader compatibility already supports `read: [2,3,4]`, so retiring the
v3 frozen set to read-only historical is safe.

### Delivery sequence — status

These are work items in the **CoPlan §8.2 A register**, not a separate "PR"
designator family (see CoPlan §8.1.0). Delivery order:

1. **A13 — doc truth-sync** — **accepted** (low effort; every later rationale
   references these docs).
2. **A14 — two-value acceptance gate** (`match`/`mismatch`/`vacant`, `vacant`-over-
   `mismatch` precedence, `fatal`/`advisory` scale, shared with field states) +
   test — **accepted** (unblocks promotion; decision D17, harmonized with D18).
3. **A15 — capture-verify-recapture stability loop** + concurrency test —
   **accepted** (lets Zero400 earn the full semantic digest; decision D16).
4. **Codex compaction Tier-1 parser** + Claude parity — **postponed** (covers ~all
   real compaction in this corpus; where evidence is absent the detector reports
   D15's `indeterminate` — the evidence sense, distinct from the gate's `vacant`;
   promoted by **CoPlan T4**).
5. **Opt-in quiesce hint** + idle-window detection — **postponed** (polish;
   decision D16).

Deferred: Cursor signal-based compaction (probe first); intra-session model
attribution (§6, confidence-graded); second-store-per-vendor corpus expansion
(capture under the improved pipeline once A13–A15 land).

---

## 6. Corpus findings — Zero400, entanglement, model attribution

**[measured] from the Zero400 v4 Cursor snapshot:**

- **Grok-4.5 is a mid-session model switch.** 5 Grok-4.5 model turns, all in one
  session (`70439ea9…`) at consecutive sequence numbers **91, 93, 94, 95, 96**.
  `composer-2.5` has 134 turns; 107 turns carry no model config. The session ran
  on `composer-2.5`, then switched to `grok-4.5` for a contiguous late burst.
  Cursor permits mid-conversation model change, captured per-turn via
  `modelInfo.modelName`.
- **Event kinds:** `tool.call` 17,014 · `tool.result` 17,014 ·
  `message.response` 2,582 · `message.prompt` 642. No compaction-shaped event
  kind is currently emitted for Cursor.
- **Prompt length:** 642 prompts, avg 241 chars, range 3–16,463 — the wide range
  is what a templated injected/handoff prompt would sit at the top of.

**"Entanglement" quantified.** Two distinct problems:
1. *Cross-vendor* (Claude + Cursor in one project) — a project-level
   artifact-sharing overlap, resolved by treating each vendor rendition as a
   separate artifact with additive correlation (**D14**).
2. *Intra-session model attribution* — the sharper one: only **15,595 of 37,252
   events (42%) carry a `model_turn_id`.** The other 58% (tool calls/results,
   un-turned messages) are **not tied to a specific model version.** So a
   Grok-vs-composer question can attribute the model *turns* but not most
   surrounding events. This is the real discriminating-ability limit; closing it
   means propagating turn attribution to events within a turn's span — an
   inference, therefore confidence-graded, never asserted.

**Other multi-vendor projects exist** (10+ project snapshots under
`~/.codess/projects/`); some may have one vendor aged/eliminated by session
age/size/compatibility. Only Zero400 was studied in depth here; a full
multi-vendor inventory is available on request.

---

## 7. External references (tightly summarized)

Web sources consulted July 2026. Codess must not assume continued publication or
treat these as authoritative over local evidence.

- **Codex context compaction (badlogic gist).** Codex uses two-tier auto-compact:
  a Session Memory Compact that often avoids an LLM call, then a server-side
  compact returning an opaque `encrypted_content` blob. Sessions persist as JSONL
  rollout files under `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`.
  <https://gist.github.com/badlogic/cd2ef65b0697c4dbe2d13fbecb0a0a5f>
- **Codex compaction deep-dive (danielvaughan).** Confirms token-threshold
  trigger and reconstruction as initial context + recent user messages (≤20k
  tokens) + summary; Codex can run ~7h continuously via auto-compaction.
  <https://codex.danielvaughan.com/2026/04/14/context-compaction-deep-dive-codex-cli-claude-code-opencode/>
- **Codex session lifecycle (danielvaughan).** Slash/CLI surface: `/compact`,
  `/archive`, `codex resume --last`, `codex fork`, `/new`. On-disk record names
  for these were *not* disclosed — verify against source/fixtures.
  <https://codex.danielvaughan.com/2026/06/05/codex-cli-session-lifecycle-archive-resume-fork-compact-management/>
- **Codex compaction reverse-engineering (simzhou).** The server `compact()` uses
  an LLM with a compaction + handoff prompt "nearly identical to the open-source
  versions" — basis for the injected-prompt-signature heuristic.
  <https://simzhou.com/en/posts/2026/how-codex-compacts-context/>
- **Cursor summarization (official docs).** Cursor auto-summarizes older messages
  when the context window is exceeded and resets context within the same chat at
  100%; large files/folders are separately condensed.
  <https://cursor.com/docs/agent/chat/summarization>
- **Cursor `/compress` (community forum).** A manual command to summarize all
  messages and reset the context window on demand.
  <https://forum.cursor.com/t/compact-compress-chat/132097>

Impact: the Codex and Cursor references establish that both write a compaction
shape, justifying the Tier-1 Codex parser and the Cursor probe.

### Local source artifacts (Github/Schema re-review, §9)

Local project `~/Work/Github/Schema` (git through `879da09`, reviewed
2026-07-20). Not a network resource; do not assume publication.
- `docs/roadmap.md` — four-track status (mapping runtime, conformance, publish,
  experiments).
- `experiments/transform-languages/README.md` — the jq/JSONata/JMESPath shootout
  and its result table (source decision 004).
- `experiments/entity-resolution/README.md` — the seeded-corpus matcher scores
  and failure-mode taxonomy.
- `docs/aliases-vocabularies-registries.md` — the three-level reconciliation
  design; `docs/conformance.md` — mutation/parity/gate and the upstream
  `jsonschema` crash.

---

## 8. Elicitation checklist — behaviors to confirm against real records

Open questions where a short real interaction, or a note from the operator, lets
us verify the *stored* form against the *observed* behavior. For each, the
operator supplies the interaction just prior (or a note that it occurred) and
Codess checks the corresponding session/event/tool records. Answers feed **T1**
(vendor fact + fixture) and the postponed compaction/attribution work.

### Codex
1. **`/compact` (manual).** Run `/compact` in a session, note the prompt just
   before. Check: does a `type=compaction` / `encrypted_content` record appear in
   the rollout JSONL, and what surrounds it?
2. **Auto-compaction (threshold).** Note a long session that likely crossed the
   token threshold. Check: same record, unattended — confirms the user-independent
   path.
3. **`/archive` and `codex resume --last`.** Note an archive then a resume. Check:
   how archive state and resume lineage appear (`archive_state`, any parent/resume
   marker) — Codex has no stable parent-session id today (T4).
4. **`codex fork`.** Note a fork. Check: whether any fork lineage is recorded.
5. **`thread_settings_applied`.** Note a mid-session model/effort/service change.
   Check: does the newer settings envelope update `model_configurations` with
   correct provenance?

### Claude
6. **`/compact` (manual).** Note a `/compact`. Check: `compact_boundary` retained
   with `trigger`, summary discarded (baseline behavior — confirm still current).
7. **Injected vs typed prompt.** Note a slash command, a task-notification, and a
   plain typed prompt. Check: the 4-way split
   (`direct_user_input` / `harness_injected` / `task_notification` / `slash_command`)
   classifies each correctly — the strongest per-vendor provenance signal.
8. **Subagent / fork-context.** Note a subagent run or a `--fork`. Check:
   `parent_session_id`, `session_relation_kind`, sidechain linkage.

### Cursor
9. **Auto-summarization at ~100% context.** Note a long chat that hit the limit.
   Check (probe first): does a summarization bubble/`composerData` marker survive
   in `state.vscdb`? This decides whether Cursor compaction is ever Tier-1.
10. **`/compress` (manual).** Run `/compress`, note the state before. Check: same
    — is the manual reset distinguishable from auto-summarization on disk?
11. **Mid-session model switch.** Reproduce the Zero400 pattern: start on one
    model, switch to another mid-chat. Check: per-turn `modelInfo.modelName`
    attribution and how many surrounding events lack `model_turn_id` (the 42%
    attribution gap, §6).
12. **Accept/reject a tool permission.** Note an accepted and a rejected tool
    call. Check: `toolFormerData.userDecision` → `normalized_status` (`denied` on
    reject), source value preserved.

### Cross-vendor
13. **Same repo, two vendors, same file.** Note working the same file in Claude
    and Cursor. Check: shared `relative_path` artifact + a `correlation_assertions`
    link — the additive-correlation path (D14), not a normalization requirement.

---

## 9. Github/Schema re-review (2026-07-20)

Second pass over `~/Work/Github/Schema` (git through `879da09`). The project has
advanced well past the original `Schemas.md` review. Full narrative is in
`Schemas.md §0`; this section records the Codess-facing consequences **[observed]**
and the suggestions for the source project (recorded only — not applied there,
per instruction). The source project's own decision numbers (its 003 = person
linking, 004 = transform language) are distinct from Codess `D`-numbers.

### 9.1 What changed upstream, and the Codess consequence

- **Transform-language shootout completed (their decision 004).** JMESPath
  eliminated for silent nulls; jq and JSONata tie (7/7, both fail loudly); no
  language removes host functions. → **Codess consequence:** our defer-the-DSL
  stance (`Schemas.md §2.6`, Reject/Defer lists) is now externally validated with
  data. If ever revisited, the candidate is **JSONata specifically** (native
  embedding, `$error()`→dead-letter), and it still would not replace our named
  Python transforms. No Codess change now; recorded so a future revisit starts
  from evidence.
- **Publish direction + round-trip fixed-point tests implemented.** Their engine
  now runs `common_to_external` with ingest→publish→ingest convergence and one
  declared-lossy field. → **Codess consequence:** the `common_to_external`
  profile our `direction` grammar reserves (`CoSchema.md`, mapping profiles) is a
  *proven* pattern upstream, not a hypothesis. Confirms that if a Codess export
  requirement appears it is a separate directional profile with its own fixtures
  and declared loss — never a reversed ingest rule. Still deferred; evidence
  upgraded.
- **Conformance triad green + real bug caught.** Mutation (104, zero survivors),
  parity fuzzing (~1,100 docs, jsonschema vs Ajv), evolution gate (12 tests); the
  fuzzer found a genuine upstream `jsonschema` `hostname`-checker crash. →
  **Codess consequence:** the discipline we adopted (`Schemas.md §2.2`, §6 —
  same fixtures through any two layers claiming one invariant) demonstrably finds
  real defects. Reinforces prioritizing **our own mutation coverage** over the
  SQLite contract/DDL and the app-vs-SQLite constraint pair. Candidate future
  work item, not yet scheduled.
- **Reconciliation three-level design partly implemented** (generic `vocab(name)`
  transform; GLEIF connector behind a W3C Reconciliation interface with
  evidence-graded assertions). New rules: normalize before alias lookup, never
  fuzzy-match, SKOS `exactMatch` vs `closeMatch` per row. → **Codess
  consequence:** confirms our alias/vocabulary/correlation split (`Schemas.md §2.8`)
  and the "record the matched surface value + rule, fuzzy is not a default"
  policy. The exact/close distinction is worth carrying into any Codess
  vocabulary artifacts (tool-name canonicalization, status maps) as a per-row
  facet.
- **Entity-resolution testbed ran** — failure-mode taxonomy: contact-point
  equality is not identity evidence (name-derived emails false-merge twins);
  **postal address > employer domain** as independent corroborator (domain
  correlates with name); phone confirms but cannot find. → **Codess consequence
  (actionable for D14/D15):** for `correlation_assertions` across
  vendor/session/artifact, rank corroborators by *independence*: a shared
  **`relative_path`** behaves like address (independent, strong); a shared
  **model name or tool name** behaves like domain (correlated with the activity,
  weak); never assert a cross-vendor identity on a single
  contact-point-equivalent signal. This tightens the confidence grading of D14
  (separate renditions) and D15 (compaction signals) with no schema change —
  e.g. a large-gap signal alone is "phone-like" (confirms, cannot find).

### 9.2 Net effect on prior decisions

No adopt/adapt/defer/reject entry in `Schemas.md §3` reverses. Upgrades:
- Defer-DSL, defer-publish/round-trip, and the conformance discipline move from
  "borrowed principle" to "borrowed principle with upstream running evidence."
- One designated tool changes: **JSONata** (was unspecified) if a DSL is ever
  wanted.
- One ranking is added: **independent corroborator (path) > correlated signal
  (model/tool)** for cross-vendor links — folded into D14/D15 confidence grading.

### 9.3 Suggestions for the source project (recorded only, not applied)

Per instruction, these are *proposals for `~/Work/Github/Schema`* to consider;
Codess makes no edits there.

1. **Graduate the entity-resolution caveat into the corpus generator.** Its own
   caveat notes `name_and_address` scores perfectly only because twins never
   share an address by construction; adding a dorm/family-business case where
   twins *do* share an address would make the taxonomy honest about address's
   real ceiling.
2. **Record the parity-found `jsonschema` crash as a decision/known-issue**, not
   only in `conformance.md` prose, so downstream embedders using a plain
   `FormatChecker()` are warned at the contract level.
3. **State the publish-direction lossy-field policy as a first-class artifact**
   (a declared-loss manifest) rather than an inline note on `Website` hostname —
   mirrors their own "loss is explicit" rule and eases adding future publish
   specs.
4. **When `from_any` (structural alias) is implemented, ship it with the same
   `mapping_trace`-style provenance** the design already specifies for value
   aliases, so the two reconciliation levels stay symmetric.

These do not affect Codess and require no Codess follow-up; they are captured so
the relationship review is complete.

### 9.4 Tooling-shootout methodology (moved)

The transform-DSL evaluation method and Codess's own postponed decision are
recorded in `experiments/JsonDSL.md`, not here — the verdict is *postpone*, so it
belongs in `experiments/`, and the methodology is reused for any future one-way
tooling choice. The Schema project's "adapters are the product" line is *its*
thesis for a CRM hub; it does **not** describe Codess, whose value is the
correctness and resilience of every pipeline step (ingest → normalize → snapshot
→ query), not the mapping step alone.
