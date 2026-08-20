# CoTasks

CoTasks is the sole list of open Codess engineering work. It contains only
incomplete items: a completed item is removed and its outcome recorded in
[CoReview](CoReview.md), so this document states what is left rather than what
happened.

Identifiers are assigned once and never reused or renumbered. A gap in the
sequence means an item closed; a retained report or a code comment naming an
identifier that is absent here is naming closed work.

Each item states the same four things: what the work is, what evidence closes
it, what blocks it, and what it costs. Analysis that justified an item belongs
in [CoReview](CoReview.md); what an item needs to be built and checked belongs
here.

**A count here bounds work.** A figure appears only where it
bounds the work -- which functions a change touches, how many call sites a rule
must reach -- so it can be re-derived from the code and used to tell a finished
item from an unfinished one. Each states how it was obtained, because a figure
whose basis is unstated cannot be checked: `admin_cmd`'s undocumented flags are
76 by distinct name and 142 by declaration, and an item citing neither basis
matches neither measurement. Figures that only
report a moment, such as a current error total, are not recorded here: they are
read from `tools/quality_report.py` when needed, because a number written down
is wrong by the next change and cannot close an item. No item carries a duration
or an effort estimate; ordering is by dependency and by rebuild cost, both of
which are checkable.

## Table of Contents

- [Status Vocabulary](#status-vocabulary)
- [Open Items](#open-items)
- [Queue](#queue)
- [Dependencies and Batching](#dependencies-and-batching)
- [Item Detail](#item-detail)
- [Maintenance Directions](#maintenance-directions)
- [Deferred Directions](#deferred-directions)

## Status Vocabulary

| Status | Meaning |
|---|---|
| **Planned** | Accepted, unblocked, and ordered in the queue. |
| **TODO** | Accepted but unscheduled: no dependency blocks it and nothing waits on it. |
| **Needs decision** | Blocked on a judgment, not on effort. The unanswered question is named on the item. Doing the work first would encode the wrong answer. |
| **Postponed** | Deliberately outside the current phase. The reason is recorded on the item. |
| **Withdrawn** | Examined and rejected. Retained so the reasoning is not rediscovered. |
| **Closed** | Work complete and its rule recorded. The row is retained only because an open item continues or depends on it, and is removed once that item closes. |

Priority states how much an item matters. It does not say when the work happens
or what blocks it; the queue says that.

## Open Items

Ordered by identifier, which is stable. Read the queue for what to do next and
[Item Detail](#item-detail) for scope and evidence.

| ID | Priority | Status | Work | Blocked by |
|---|---|---|---|---|
| W04 | High | Planned | Shared candidate-record contract, enforced at the decode boundary | -- |
| W05 | High | Planned | Run named real investigations against the query surface | -- |
| W14 | High | Planned | Require or mark Project identity; duplicates override reviewed dispositions | -- |
| W16 | Normal | Postponed | Evaluate external investigation interfaces | No consumer |
| W17 | Normal | Postponed | Expand cross-Project analysis inputs | Baseline 2 |
| W35 | Low | Postponed | Resolve the validation-fixture inventory | -- |
| W43 | Low | Withdrawn | Table-drive request validation | -- |
| W50 | Normal | Planned | Reconcile schema names with defined terminology | Batches with W51 |
| W51 | Normal | Planned | Resolve source-identity naming and suffix rules | Batches with W50 |
| W55 | Normal | Planned | Unify text and record parsing across the decode layer | -- |
| W64 | Normal | Planned | Decide and enforce the typing posture | -- |
| W65 | Normal | Planned | Consolidate remaining relay parameter groups | W04 (partly) |
| W66 | High | Planned | Unify configuration into one subsystem | -- |
| W67 | Normal | Planned | Move relay fields into the objects that carry them | -- |
| W70 | Normal | Planned | Re-partition documentation; remove cross-document redundancy | -- |
| W71 | Normal | Planned | Adopt the reporting facility in the command layer | -- |
| W72 | Normal | Planned | One Event-record builder per adapter; Cursor has none | -- |
| W73 | High | Planned | Resolve or close the fifteen open vendor decode gaps CoPlan records | -- |
| W74 | High | Planned | Cursor Session times dropped; unread populated fields; two vendor facts to record | Retrieved-reference policy split to W79 |
| W75 | Normal | Postponed | Harness experiments for conditions no stored data records | Execution deferred; restart criteria on the item |
| W76 | Normal | Postponed | Characterise current Cursor terminal-agent storage; the decoded store is obsolete | Restart criteria on the item |
| W77 | Normal | Withdrawn | Time module -- W55 already specifies it | -- |
| W78 | Low | Closed | Guard the module-level import graph against cycles | -- |
| W79 | Normal | Postponed | Content policy for retrieved, attacker-influenced Artifact references | Needs a retrieval-bearing corpus |
| W80 | High | Closed | Read `composerData.modelConfig` for every composer, not only headered ones | -- |
| W81 | Normal | Postponed | Cursor Artifact evidence in adjacent key spaces: patch graphs, checkpoints, file snapshots | Restart criteria on the item |
| W82 | High | Closed | Tools carry unchecked SQL; a renamed column broke the mandated audit silently | -- |
| W83 | High | Postponed | Early-access release readiness | B1 is the owner's decision; restart criteria on the item |
| W84 | Low | Postponed | Characterise `selectedModels` parameters beyond `fast` and `effort` | Both observed ids are mapped; no third has appeared |
| W85 | Normal | Postponed | Composers older than the header retention window are unattributed by design | Handling can improve; the condition itself is vendor retention |
| W86 | High | Planned | Skipped and refused records are counted but not attributed | -- |
| W87 | Normal | Planned | Group the test corpus by subsystem; find superseded and uncovered cases | -- |

## Queue

One ordering. The reason for each position is a dependency or a stated cost,
not a preference.

| Rank | Item | Why here |
|---|---|---|
| 1 | **W05** | The only item whose output is evidence about whether the query surface answers real questions rather than machinery that supports them. Needs no rebuild: format-6 stores exist and are audited, so the work starts against current data. |
| 2 | **W04** | Structural, and coverage reporting states loss against exactly the profiles it enforces -- a report built against unenforced profiles attests to nothing. Baseline 2's substance. |
| 3 | **W50 + W51** | The naming resolutions format 6 did not carry. Both are wire-format, so they land together as one rebuild or they cost two. |
| 4 | **W66** | The largest structural item, and now the prerequisite rather than the sequel: W67's objects are built at the command adapter from values a setting declaration owns, so declaring each setting once must come first or the object's constructor encodes the current duplication. |
| 5 | **W67** | Follows W66 directly and is mechanical once it lands: each relay already has an object to take, the measurement separating a relay from a builder is written down, and the five shared parameters are the same subset `ChildInvocation` carries. |
| 6 | **W64 + W65** | W65's record-context cluster is adapter signatures, so consolidating before W04 rewrites them twice. W64 no longer waits on W04 -- what remains after the naming pass is dominated by optional-narrowing, which is what `strict_optional` decides -- but it is cheapest once the signatures have settled. |

### Next Two Sprints

The queue orders items by dependency and rebuild cost; this names the next two
sessions and what closes each. A sprint is sized to leave the suite green and
the store readable at its end, and is chosen on what is decided-and-unapplied
or shares a rebuild rather than on queue rank.

**Sprint 1 -- the wire-format change.** W50 + W51 naming, W74.3's `duplicate_of`
reference, and `tokenCount` retention for all three vendors. Each needs a column
or a rename, so they land together.

*Also closed here:* W74.1's corpus verification. The header fallback is written
and covered by the suite, but the two Sessions of 86 carrying no `started_at`
stay null until their Projects are reingested, which this sprint does anyway.

*Why first:* these are the changes that have been waiting on a format, and the
naming resolutions are wire-format decisions that every later item reads
through. Doing the field mapping first would mean mapping into column names
W50 and W51 then rename.

*The rebuild is a step, not an obstacle.* Install the contract, `codess ingest
--force` each Project, republish: on the order of minutes of machine time for
the current corpus, once per format regardless of how many columns changed.
Batching is worth doing because it is free to do, not because a rebuild needs
avoiding.

*Ends when:* the format is installed, every Project is reingested and
republished, the Cursor null-`started_at` count is zero, and a `--since` query
returns the previously untimed Session.

**Sprint 2 -- the Cursor field pass.** W74.5a's map decisions: the nine
`context` leaves, the `richText` mentions, `thinking`/`thinkingStyle`/
`thinkingDurationMs`, `turnDurationMs`/`timingInfo`, `errorDetails`,
`codeBlocks`, `requestId`/`usageUuid` as separate columns, `lastTerminalCwd`,
`symbolLinks`/`fileLinks`, and `todos`. These add Event metadata and Artifact
references, so the suite is the whole retest. W72's Cursor Event-record builder
folds in, since these edits touch exactly the sites that lack one.

*Why second:* it is the largest body of decided-and-unapplied work in the list,
and it lands against column names Sprint 1 has settled. W79 is excluded so a
policy question decided by four records cannot hold up the other 33 fields.

*Ends when:* the suite is green, `field_coverage.py` reports the mapped fields
populated, and each unmapped field carries a recorded reason.

**Why not W05 or W04 in these two.** The queue ranks them 1 and 2 and stays
correct for its purpose, which is ordering by dependency. These sprints are
chosen on what is decided and unapplied. W05 produces evidence rather than
consuming it and can start at any point; W04 rewrites adapter signatures, so
running it before the Cursor field pass would mean editing that adapter twice.

**Continuous, not a sprint.** W70 (documentation partition), W71 (reporting
adoption), and W73's decode gaps, which are individually small and each belong
to whichever sprint touches their vendor.

**Not queued**, each for a stated reason rather than for lack of room:

| Item | Why not queued |
|---|---|
| **W14** | Independent. No item blocks it and none waits on it. |
| **W16** | No consumer has asked for external interfaces, and an item nobody is waiting for does not belong in an ordered queue. |
| **W17** | Deferred to Baseline 2. Specifying a cross-Project surface against a decode W04 has not enforced would fix it against a surface still changing underneath. |
| **W35** | No longer gates anything a store does; it is now a question about what the released set should contain. |
| **W43** | Withdrawn on inspection. Retained so the analysis is not repeated. |
| **W55** | Correctness-neutral, so it batches with anything and blocks nothing. |
| **W73** | Fifteen gaps in six groups; each belongs to the round that touches its vendor rather than to a round of its own. |
| **W74** | W74.1 closed in code; the field mapping is Sprint 1 and `duplicate_of` is Sprint 2, since it needs a column. |
| **W75** | Postponed. Designed and segregated into machine and human parts; restarts when a dependent item needs an observation. |
| **W70** | Documentation only, and continuous enough that queuing it would imply an end date it does not have. Do it alongside whatever item touches a document. |

## Dependencies and Batching

**W50 and W51 land together.** Both rename stored columns, and Codess never
migrates a store -- the store is a projection, and the way to change a
projection is to recompute it. Landing them together is simply tidier than
recomputing twice for one result.

**What a rebuild is.** A wire-format change is not an `ALTER TABLE`.
`require_store` accepts only the current format, for reading as well as writing,
so a store is unreadable by the new code until its Project is reingested:
install the contract, `codess ingest --force` each Project, republish. The cost
scales with Project count rather than with the size of the change, which is why
batching is worth doing -- but it is minutes of machine time, so a change that
is ready should not wait for one that is not.

### Corpus Baseline

The scale a rebuild is paid against, and the runtime it costs. Both are read
from the operator's own registry and refresh receipts, so both are re-derivable
and both are expected to move as work is ingested -- they are a status of the
current baseline, not a property of the system.

| Measure | Current | Source |
|---|---|---|
| Published Project store sets | 30 | `~/.codess/projects/*/current.json` |
| Sessions | 635 | `SELECT count(*) FROM sessions` across published stores |
| Events | 329,750 | `SELECT count(*) FROM events` across published stores |
| Store bytes | 2,333 MiB, largest set 560 MiB | Snapshot directory sizes |
| Ingest rate | ~900 Events/s | Refresh receipt: 76,055 Events in 83.7 s, one Project, apply stage |

**What the rate is good for.** A full-corpus rebuild is the ingest rate against
the Event count, so the current corpus is on the order of six minutes of
machine time, plus per-Project publication overhead. That is the figure to
weigh when deciding whether two wire-format changes batch: the cost is real but
small, and the reason to batch is that it is paid once per format and scales
with Project count, not that any single rebuild is expensive.

**The rate is one measurement.** It comes from one Project on
one machine at the apply stage. A Project dominated by Cursor bubbles or by very
large tool outputs will differ; re-read the receipt rather than trusting this
number if the answer matters.

**W04 precedes the typing and signature work.** W04 changes adapter signatures
and the decode boundary. W64's strict-flag decision and W65's record-context
group both target that boundary, so either one done first is done twice.

**W04 also precedes the naming sweep.** Applying the subject-word and
general-word naming rules to existing identifiers is a wide diff with no
behavioural content, so it waits for the signatures W04 rewrites rather than
touching them twice.

### Working Order

One kind of change at a time, each validated before the next begins. The queue
gives the ranking; this gives the discipline, and each rule exists because its
absence produced a defect:

1. **Commit one kind of change before starting another.** Several kinds in one
   diff is more than one reviewable change, and it makes a later bisection
   harder. Each row of the stopping-point table below is a defensible commit
   boundary.
2. **Finish a kind before starting another.** The recurring defect is a change
   of one kind exposing an unrelated one and both being pursued at once -- which
   is how a rename reached a call site it should not have.
3. **Run `ruff check` and `mypy` on the changed files before running tests.**
   A name error is a static fact: both checkers name the file and line in a
   second, while the suite reports the same defect as whichever test executed
   the path -- and inside an ingest subprocess, as a `source.failed` progress
   line with no location at all.
4. **Run `tools/quality_report.py` before declaring a kind complete.** It gates
   ruff and mypy against recorded ceilings and has caught regressions the test
   suite did not. It already runs the three in the right order: ruff, mypy,
   then pytest.

### Stopping Points

Where partly-done work stopped, so an unfinished item is visibly unfinished
rather than mistaken for untouched. None of these is half-applied: each is
either not started or has a stated boundary.

| Work | Stopping point | Item |
|---|---|---|
| Naming convention applied codebase-wide | Enforced for the two cases a checker catches, and both now report zero: builtin shadowing (ruff `A`) and a name rebound to a different type (mypy `assignment`). The subject-word and general-word rules are **not** applied to existing names, which is a wide diff with no behavioural content. | W64 |
| Relay parameter consolidation | `run_ingest` converted as the worked example. Five further relays identified and untouched. | W67 |
| Configuration unification | Measured and not begun. | W66 |
| mypy strict flags | The count was reduced by repair rather than reclassification. Which flags to enable is undecided. | W64 |
| Record-context parameter group | Identified; blocked behind W04 because it changes adapter signatures. | W65 |
| Docstring summaries (`D205`) | The rule is selected and its findings are a recorded ceiling, not zero. Four docstrings in `field_state` were rewritten as the worked example; the rest fall as files are edited. | -- |
| Command-layer help text | 76 distinct flag names in `admin_cmd` carry no help; `project.py` documents all of its own. Two were written where a verification step was being disabled; `parents=` would carry one declaration to every subcommand. | W66 |
| Event-record builders | `cursor` has no module-level builder and `cc`/`codex` have sites that bypass theirs. Found by `pylint R0801`, not started. | W72 |
| Deep audit adoption | `tools/deep_audit.py` runs and logs; nothing yet acts on its DESIGN tier. Counts are read from the tool rather than recorded here. | -- |
| Time parsing consolidation | The three adapter parsers delegate to `units.epoch_milliseconds`, which answers R1-R8. The three inline `fromisoformat` callers -- `walk_sessions`, `token_usage`, `refresh_receipts` -- are untouched, and no check yet prevents a fourth parser appearing. | W55 |
| Cursor Session times | **Closed in code, unverified against the corpus.** The header fallback is written and the suite covers it; the 2 Sessions of 86 that carry no `started_at` are still null in the published stores, because closing them needs the reingest that W74.3's column change also needs. | W74.1 |
| Cursor field mapping | 34 populated bubble fields are dropped with no recorded reason; every decision is written and none is applied. The retrieved-reference policy is split out so the other 33 need not wait. | W74.5a, W79 |
| `duplicate_of` reference | Decided and not built. Needs a column, so it batches with the next wire-format change rather than landing alone. | W74.3 |
| Mechanical enforcement | Import boundaries, SQL ownership, module-level cycles, rejection vectors, and subprocess coverage each have a check. Mapping-profile conformance over emitted fixtures does not. | W04 |
| Terminal-agent storage | The obsolete `chats/` store is characterised; the current `~/.cursor/projects/` tree is identified and not examined. | W76 |
| Harness conditions | Designed, segregated into machine and human parts, and not run. | W75 |

## Item Detail

### W04 -- Candidate-Record Contract

**Work.** Define the shared candidate-record contract and enforce released
mapping profiles at the runtime decode boundary. Adapters currently exchange
`dict[str, Any]` with the domain layer, so a misspelled key, an invalid value
type, or inconsistent null handling is caught only at the store boundary, if at
all. The intended shape is a `TypedDict` family for candidate Session, Event,
tool, configuration, and diagnostic records, plus one runtime validator
post-decode.

**Scope.** All three adapters; the post-decode conformance check; strict versus
diagnostic policy for a non-conforming candidate.

**Where to start reading.** The pieces exist and are not connected:

| File | Holds |
|---|---|
| `adapters/{cc,codex,cursor}.py` | The three producers of candidate dictionaries; the shapes to be typed |
| `mapping.annotate_mapping` | Where a candidate acquires its selected rule and trace today |
| `schema_contract.validate_mapped_event` | The conformance check that exists, is exercised by four test modules, and is called from **no production path** -- wiring it in is the core of this item |
| `schema/mappings/{claude,codex,cursor}.json` | The released profiles the check validates against |
| `ingest_review` | Where a non-conforming candidate's diagnostic lands |

`validate_mapped_event` being test-only is the item in one line: the contract is
written and unenforced.

**Now measured, and the adapters conform.** Coverage reporting gained a
profile-conformance comparison. Over the **21 current-format stores, every one
is conformant**: no Event carries a `mapping_rule` its released profile does not
declare.

Claude's decoder shows why. `_mapping_rule` is a fixed table returning declared
ids only, and `_PRODUCT_STATE_RULES` derives its ids from the kind table by
comprehension -- so a rule and the kind it produces cannot disagree, because one
is computed from the other.

An earlier reading of this comparison surveyed **all 30** stores and found 25
undeclared ids, which looked like a naming-scheme conflict. It was not: those
ids appear only in one stale format-3 store, written by a decoder that derived
`vendor.event_type.subtype` from the record rather than selecting a declared
rule. Nine of the thirty stores predate format 6 and are superseded
observations. Filtering to the current format is what the comparison must do,
and the check now records the store's format so a stale store cannot be read as
a live defect.

**How the profiles and adapters match up.** They already do, and the mechanism
is worth naming because it is what step 1 must preserve:

| Adapter | How a rule id is chosen | Guarantee |
|---|---|---|
| `cc` | `_mapping_rule` is a fixed dispatch table over `event_type`/`subtype`, returning declared ids only | Every branch is a literal; adding an unlisted one is a visible edit |
| `cc` product state | `_PRODUCT_STATE_RULES` is a comprehension over `_PRODUCT_STATE_KINDS` | A rule and the kind it produces are computed from one table, so they cannot disagree |
| `codex`, `cursor` | Literal ids at the `annotate_mapping` call sites | Same property, less centrally |

The derived `vendor.event_type.subtype` form exists only in stores predating the
current contract. No current decoder constructs an id from a record.

**Claude's profile is larger but not finer**, which is worth stating because the
opposite reads naturally from the counts:

| Profile | Rules | Source constructs covered | Constructs per rule |
|---|---|---|---|
| `claude` | 16 | 25 | 1.56 |
| `codex` | 12 | 18 | 1.50 |
| `cursor` | 12 | 12 | 1.00 |

Claude has the **most aggregated** rules, not the most specific: six of its
sixteen cover several vendor constructs at once -- `claude.session-label` spans
`ai-title|custom-title|agent-name`, `claude.lifecycle` spans three unrelated
system records. Cursor is the opposite, with one construct per rule throughout.
Measured against stored Events the same way round: Claude uses 13 rules to
produce 15 Event kinds (1.15 kinds per rule), Codex 8 rules for 12 kinds (1.50),
Cursor 5 for 7 (1.40).

The count difference is what each vendor *records*, not how finely Codess splits
it. Claude writes harness settings, a session label, a version, fork context,
and lineage as separate record shapes; Cursor puts most state in one bubble
structure and needs rules for the bubble's parts instead.

**The forty rules are not forty unrelated things.** Grouped by what they write
rather than by their ids, they collapse to **nineteen CoSchema concepts, nine of
which more than one vendor writes**:

| Concept | Written by | Rules |
|---|---|---|
| `events` | all three | `claude.message`, `codex.message`, `cursor.bubble` |
| `events.context` | all three | compaction and injection, four rules |
| `tool_invocations` | all three | `tool-use`, `tool-call`, `tool-former-invocation` |
| `tool_results` | all three | four rules; Cursor has two because it records the outcome two ways |
| `events.message` | Claude, Codex | typed prompt, context injection, reasoning summary |
| `events.lifecycle` | Claude, Codex | vendor lifecycle, task lifecycle, abort |
| `model_params` | Claude, Codex | both named `configuration` |
| `sessions` | Codex, Cursor | `session-meta`, `header` |
| `sessions.archive_state` | Codex, Cursor | `archive-location`, `archive` |

Nineteen of the forty rules are one vendor's version of a shared concept. The
remaining twenty-one are genuinely vendor-only, and they are exactly the places
a vendor records something the others do not: Claude's harness settings, session
label and marker, harness version, lineage, and fork context; Cursor's context-
window observation, subagent flag, and permission decision; Codex's turn
identity and reasoning summary.

So the ids differ because each names *a vendor's construct*, while the targets
show what they have in common. Rule targets are also nearly one-to-one -- 16 of
16 distinct for Claude, 12 of 12 for Codex, 11 of 12 for Cursor -- so rule count
tracks separable destinations rather than granularity of matching.

**Recommended resolution for W04.** Enforce the property that already holds,
and do not change either scheme:

1. *Keep the declared ids as they are.* They are coarser than `event_type` plus
   `subtype`, deliberately: a rule names a mapping decision, and several record
   subtypes can share one. Making profiles finer to match a derived form would
   turn the profile into a restatement of the taxonomy rather than a contract
   over it.
2. *Keep `_mapping_rule` as a dispatch table.* Its value is that every id is a
   literal a reader can find. A derivation would be shorter and would silently
   admit whatever the record contained -- which is what the stale store shows.
3. *Wire `validate_mapped_event` at the post-decode boundary as step 1 already
   says.* It will not reject current Events, so the change is additive.
4. *Assert conformance on current-format stores only.* The check must exclude a
   store written under a superseded contract, or it reports a store's age as a
   decoder defect -- which it did on the first run of this comparison.

**Per vendor**, because the three adapters choose a rule id three different
ways and each recommendation lands differently:

| | Claude (`cc`) | Codex | Cursor |
|---|---|---|---|
| Mechanism today | `_mapping_rule` dispatch table, plus `_PRODUCT_STATE_RULES` derived from the kind table | `_mapping_rule` dispatch table | Seven literals at their `annotate_mapping` call sites; no dispatch function |
| **1. Keep ids coarse** | Most affected: six of sixteen rules aggregate several constructs, so a finer profile would split `session-label` into three and `lifecycle` into three | Affected: five rules aggregate, including `tool-call` over three call shapes | Not affected: one construct per rule already, so there is nothing to keep coarse |
| **2. Keep the dispatch table** | Applies as written; the product-state comprehension is the pattern to preserve, since rule and kind cannot drift | Applies as written | **Does not apply** -- there is no table. The literals give the same guarantee at seven sites instead of one, so the question is whether to add a table, not whether to keep one |
| **3. Wire the post-decode check** | No change expected; 13 declared ids in use, none undeclared | No change expected | No change expected, and it is the adapter that most needs the check: a literal at a call site is the easiest place for an eighth, unreviewed id to appear |
| **4. Compare current-format stores only** | Identical for all three, and deliberately so: the filter reads `store_meta.contract_digest`, which every store carries regardless of which adapter wrote it. A per-vendor rule here would mean one vendor's stale store was judged by today's profiles and another's was not | Identical | Identical |

**Why Cursor writes `tool_results` twice.** Not two readings of one outcome --
two vendor storage shapes. `toolFormerData.result,status` is the current object
form and `toolResults[]` an older array; CursorSchema records that selected
stores commonly hold the array empty. Measured across the current-format
stores: `cursor.tool-former-result` produced 60,875 Events and
`cursor.tool-result-legacy` produced **zero**. The legacy rule is declared and
unused, which is precisely the `unused` case the conformance check now reports
-- correct to keep, because a store written before the shape changed still
needs it, and removing it would make that store unreadable rather than tidier.

**How Cursor handles `events.message` and `events.lifecycle`.** Measured over
the current-format stores, one rule produces three message kinds and lifecycle
is absent entirely:

| Rule | Event kinds produced | Count |
|---|---|---|
| `cursor.bubble` | `message.prompt`, `message.response`, `message.context` | 4,112 / 9,386 / 25 |
| `cursor.compaction-summary` | `context.compact` | 2 |
| `cursor.request-context` | `context.inject` | 52 |
| `cursor.tool-former-invocation` | `tool.call` | 60,875 |
| `cursor.tool-former-result` | `tool.result` | 60,875 |

So Cursor *does* write `events.message` -- through `cursor.bubble`, whose
classification is decided in the adapter from the bubble's type and content
rather than by a separate rule per kind. That is the mirror image of Claude,
which has `claude.typed-prompt` and `claude.message` as distinct rules. Neither
is wrong: Cursor stores prompts, responses, and injected context in one bubble
structure, so one rule matching that structure is the honest description of the
source.

**Lifecycle is genuinely absent.** Claude produces 1,058 `lifecycle.vendor`
Events and Codex 5,449 across `lifecycle.start`, `lifecycle.complete`, and
`lifecycle.abort`; Cursor produces none, and has no lifecycle rule to produce
them with. Whether Cursor records task start and completion anywhere is a
decode gap rather than a mapping choice, and belongs with the coverage question
in W73 rather than here.

**A follow-on for Cursor, not a blocker.** Its seven literals are correct today
and were each written beside the record they describe, which is a real argument
for leaving them. But they are the one adapter where a new id needs no edit to a
central table, so if the conformance check ever reports an undeclared id, Cursor
is where to look first.

The case for a table there is weaker than it looks, and worth stating so it is
not adopted by symmetry. Claude and Codex need a dispatch function because one
call site emits many kinds: `cc._mapping_rule` has eleven branches over
`event_type`/`subtype`. Cursor's seven ids sit at seven distinct call sites,
each already selected by the surrounding code -- a table would move the id away
from the record it names and add a lookup that decides nothing. The property a
table buys, that every id is a literal a reader can find, Cursor already has.

What Cursor lacks is not the table but the *check*, which is step 3 and applies
to all three adapters equally. Revisit a table only if the conformance test
starts failing there, since that would be evidence the call sites drifted.

**Justification.** The alternative -- reconciling two id schemes -- was the
reading before the measurement, and it would have been a wire-format change
serving a defect that does not exist. The measurement cost one comparison and
removed a step from the item. What remains is the original gap: a property held
by construction with nothing testing it, which is one refactor from being lost.

**Steps.** Ordered by what feeds what, not by size.

| Step | Work | Verified by |
|---|---|---|
| 1 | Call `validate_mapped_event` at one vendor-neutral post-decode boundary, between adapter output and `store` insertion, so every Event passes it regardless of vendor. | A deliberately non-conformant Event routed through each adapter's ingest path meets the same rejection. |
| 2 | Declare the shared candidate-record contract as a type, so the shape crossing that boundary is stated rather than implied by three adapters agreeing. | Adapters type-check against the declared candidate; mypy covers the decode boundary. |
| 3 | Give the boundary diagnostic and strict modes with the same semantics for all three vendors, replacing the Claude-only strict-mapping coverage. | Equivalent partial, malformed, unsupported, and hazard fixtures per vendor produce equivalent dispositions. |
| 4 | Record each non-conformance as a `mapping_diagnostics` row rather than only raising, so diagnostic mode is inspectable after the fact. | Diagnostic-mode ingest of hazard fixtures yields rows carrying the reason codes the profiles declare. |
| 5 | Extend `tools/decode_audit.py` with a per-vendor conformance count, so the current zero is re-measurable rather than observed once. | The audit reports conformance beside its existing invariants and exits nonzero on any failure. |

**Ordering within the item.** Steps 4 and 3 are what coverage reporting depends
on: a loss report states what was *not* mapped, and diagnostic rows are that
record -- without them the report re-derives non-conformance by re-decoding,
which is a second decode path. Step 3 makes the counts comparable, since a
vendor that raises where another tolerates gives the same figure two meanings.
Steps 1 and 2 feed nothing else and can land independently. Step 5 overlaps
coverage reporting in presentation and folds into it.

**Evidence to close.** All three adapters satisfy the typed and runtime candidate
contract, pass the same post-decode conformance check, and share strict/diagnostic
semantics; `validate_mapped_event` is reached from the ingest path and a
non-conforming candidate produces a diagnostic rather than a silent store write.

**Blocks.** W64 (typing posture), W65 (record-context group), W17.

### W05 -- Real Investigations Against the Query Surface

**Work.** Run named real investigations against the query surface and produce the
worked examples they yield. The check cannot use fixtures, which contain the
answer by construction. It needs three to five questions asked before the data is
examined:

- locate where an instruction first appeared;
- decide whether a short prompt was human or harness-generated;
- connect a tool result to its invocation;
- recover what preceded a failure or permission denial.

**Scope.** Run against a real Project. Each question becomes a documented worked
example. A predicate or facet the investigations cannot express is recorded as a
finding with evidence, not as a review opinion.

**Evidence to close.** Named investigations run end to end against a real Project;
each documented as a worked example; every gap recorded as a finding.

**Cost.** No rebuild: format-6 stores exist, so the work begins against current
data rather than regenerating it.

### W14 -- Project Identity for Direct Library Writes

**Work.** Require or explicitly mark Project identity for direct library writes.

**Reproduced, with dates.** The registry now holds **nine paths claimed by two
Projects each**, and every duplicate was created on one day by repeated
`codess ingest --dir <path> --force` runs against Projects that already had a
catalog entry:

| Path | Existing entry | Duplicate created |
|---|---|---|
| `ZK/ZeroPerf` | 2026-07-29, state `worktree` | 2026-08-20 |
| `Code/Misses` | 2026-07-30 | 2026-08-20 |
| `Spank/spank-rs` | 2026-07-29 | 2026-08-20 |
| `WP/wp`, `WP/wpages`, `WP/harduw` | 2026-07-17 to 07-29 | 2026-08-20 |
| `Code/SWEmore`, `Code/wisw`, `Claw/setpack` | 2026-07-17 to 07-29 | 2026-08-20 |

**The ZeroPerf case shows the consequence precisely.** Its 2026-07-29 entry
carries a reviewed disposition -- `state: worktree`, `relation_kind:
worktree_of`, `related_project_id` naming Zero400, and a note reading "Legacy
duplicate Project for the Zero400 linked worktree; retain historical evidence
but exclude broad selection." A new unmarked Project for the same path
**recreates exactly the duplicate that disposition exists to suppress**, and
carries none of the review that settled it.

So the defect is not only that identity is inferred rather than required: an
inferred identity **overrides a reviewed one silently**. A reviewed decision
that a later run can undo without saying so is worse than no decision, because
the operator has no reason to re-check it.

**Evidence to close.** Separate vendor stores cannot silently create unrelated
Project identities for one repository; re-ingesting a Project that already has
a catalog entry reuses that entry; and a path carrying a reviewed disposition
is never claimed by a new Project without the operator being told.

**Cost.** Independent: no item blocks it and none waits on it. The nine
duplicates on this machine are recoverable through the existing catalog
operations rather than needing a migration.

### W16 -- External Investigation Interfaces

**Work.** Evaluate, design, and plan the external investigation interfaces CoPlan
describes. This item does not authorize implementation.

**Evidence to close.** A written decision maps existing capabilities and gaps,
selects or rejects data and code integration paths, specifies any proposed
contracts, and defines staged work with licensing, privacy, security, and
validation criteria.

**Status.** Postponed: no consumer has asked for external interfaces.

### W17 -- Cross-Project Analysis Inputs

**Work.** Expand cross-Project analysis inputs. Cross-Project search is an accepted
advanced feature set, so this waits on the baseline it would be specified against
rather than on a requester.

**Evidence to close.** Baseline 2 is met; a consumer then identifies entities,
fields, selection, transformation, and output checks.

**Status.** Deferred until Baseline 2. Specifying against a decode W04 has not
enforced would fix the surface while it is still changing.

### W35 -- Validation-Fixture Inventory

**Work.** Either wire each released fixture into a test that reads it through the
manifest, or remove it from the released set.

**Scope.** Ten of the sixteen released manifest entries are fixtures. Two are read
by tests, by direct path rather than through the manifest; the remaining eight are
referenced by nothing but the manifest itself, so no test can fail on them.

**Evidence to close.** Every entry in the released manifest has a named consumer,
or is removed; a test fails if an entry acquires none.

**Status.** Postponed and Low: the fixtures were removed from the write gate, so
they no longer gate anything a store does. This is now a question about what the
released set should contain.

### W43 -- Table-Driven Request Validation

**Status: Withdrawn on inspection.** The table was proposed from a complexity
score before the function was read, and the function already is one where a table
can be applied. Five `for key in (...)` loops apply a shared rule to 30 fields
using 10 branches; the remaining 28 branches are each a distinct rule -- format,
action, sortedness, cross-field agreement, range. A table over those needs a
per-entry predicate and message, which is the existing code with a dictionary
wrapped round it.

**Retained note.** `resource_policy` raises 8 field errors with no loop and is the
better candidate if this pattern is pursued.

### W50 -- Schema Names Against Defined Terminology

**Work.** Reconcile schema names with the terminology Codess defines.

**Landed in format 6.** `mapping_diagnostics.level` became `granularity` -- the
one defect of the four that made a reader draw a wrong conclusion, since summing a
granularity overstates loss. The `level`/`diagnostic_level` collision resolved
with it.

**Remaining.**

| Defect | Detail |
|---|---|
| `source` carries three meanings | A transcript file, a vendor, and an adapter key, across 26 columns |
| `*_content` plurality | The four link tables disagree with `event_artifacts` |

**Evidence to close.** Every term in a table or column name is either defined in
Codess's terminology or is a plain English word carrying no Codess meaning;
`source` names one thing; plurality has one rule and one stated exception.

**Cost.** Wire-format. Batches with W51.

### W51 -- Source-Identity Naming

**Work.** Resolve source-identity naming, measured against peer projects.

**The plurality rule**, surveyed across four peer SQLite schemas holding 56 tables:
11 are singular and every one is a mass noun. Countable-entity tables are plural
without exception. This settles CoSchema's `*_content` tables -- `event_content`
averages 1.27 rows per Event, so it is a countable set. `store_meta` is correctly
singular by the same rule.

**The suffix defect.** `_id` carries four incompatible formats, so a reader cannot
tell whether a value is derived, assigned, or borrowed:

| Column | Holds |
|---|---|
| `sessions.id` | A vendor UUID |
| `sessions.entity_id` | A `codess:session:` derivation |
| `sources.id` | A bare SQLite rowid |
| `sessions.source_system_id` | A dotted literal, `anthropic.claude-code` |

`source_system_id` is not an identifier under that reading -- it is
`vendor + "." + product` composed in the mapping profile, so `source_system_key`
says what it is.

**Two contract questions.** `product` is required by `mapping-contract.json` and
defined nowhere: no vocabulary, no examples, no CoSchema entry. Either define it or
drop it. `sessions.source` holds the `SOURCE_PROFILES` dict key, confirmed across
601 real Sessions, so `adapter_key` names it honestly and frees `source` for the
Source entity.

**Excluded.** `vendor_name` is the wrong fact for a harness running another
provider's model, so [CoNames](CoNames.md) owns its disposition rather than this
item.

**Evidence to close.** One suffix rule states whether a value is derived, assigned,
or borrowed; `source` names the Source entity only; every contract-required field
has a definition and examples; plurality follows the mass-noun rule.

**Cost.** Wire-format. Batches with W50.

### W55 -- Parsing Consolidation

**Work.** Unify text and record parsing across the decode layer. The ordering is
sound -- a parser first, a regular expression last -- but the spread is not: 17
modules classify a prefix by hand where 4 use `removeprefix`, and 15 split on a
separator with no shared helper. [CoNames](CoNames.md) holds the measured
inventory and the rule each method follows.

**Three candidates.**

| Candidate | Detail |
|---|---|
| MCP server split | Implemented twice, in `store._tool_namespace` and `mcp_audit._mcp_candidate`, against the same three vendor spellings |
| Timestamp parsing | Three parsers and three direct `fromisoformat` callers, disagreeing on three input classes -- see below |
| Codex output header | The only free-text regex carrying decoded fields; keep the regex, move its field table beside the other vendor vocabularies |

**Time is the largest instance, and it is three parsers rather than two.**
`adapters/cc._parse_timestamp`, `adapters/codex._parse_timestamp`, and
`cursor_source.parse_timestamp` -- the last imported by `adapters/cursor` --
plus three further modules calling `datetime.fromisoformat` directly
(`walk_sessions`, `token_usage`, `refresh_receipts`).

**One of the three disagreements is now closed.** `cc` returned a seconds-scale
number unchanged, so it landed in 1970 in a column CoSchema defines as
milliseconds and read as a duration a thousand times too short; it also
accepted `True` as a number, since `isinstance(True, int)` holds. Both are
fixed, because a decoder disagreeing with the schema's stated unit is a
conformance defect rather than a consolidation question. The remaining
disagreements are what this item consolidates.

Claude writes ISO-8601 strings today -- no numeric timestamp appears in any
Session on the development machine -- so the fix guards a format change rather
than a path real data reaches.

**A test sentinel is a timestamp too.** A test asserting which of two positions
is read used `999` as the nested value, which the scale rule then correctly
multiplied. It is now a millisecond-scale constant, so the test exercises
position selection alone. A fixture number that is not a plausible value of its
own field will be reinterpreted by any rule that later reads it.

They agree on ISO-8601 and disagree on three input classes:

| Input | `cc` | `codex` | `cursor` |
|---|---|---|---|
| `"2026-01-01T00:00:00Z"` | 1767225600000.0 | 1767225600000.0 | 1767225600000.0 |
| `1700000000` (seconds-scale) | 1700000000000.0 | 1700000000000.0 | 1700000000000.0 |
| `1700000000000` (ms) | 1700000000000.0 | 1700000000000.0 | 1700000000000.0 |
| `True` | **1.0** | None | None |
| `"  ...Z  "` (padded) | None | None | **1767225600000.0** |
| `"1700000000000"` (numeric string) | None | None | None |

`codex` and `cursor` scale a value below `1e12` from seconds to milliseconds and
reject `bool` before the numeric branch; `cc` does neither, so a seconds-scale
number is stored a thousand times too small and `True` becomes
1970-01-01T00:00:00.001. Only `cursor` strips surrounding whitespace. None
accepts a numeric string, which is a fourth unstated decision rather than an
agreement.

**The seconds-scale case is reachable in principle.** `fileMtime` is a
POSIX mtime, which is seconds-scale and therefore below `1e12`;
`walk_sessions` compares it against a millisecond cutoff. Whether Claude ever
writes a seconds-valued `timestamp` is not established -- what is established
is that if one arrived, `cc` would store it unscaled and the other two would
not.

**No stored data is affected today**: across 141,753 Events carrying a time in
the current stores, none falls outside 2000-2100, so no vendor has yet supplied
a shape that triggers the disagreement. The defect is that the answer depends on
which adapter read the value, and nothing records which behaviour was intended.

**Time fields are more numerous than the parsers suggest**, which is why one
shared parser is worth more here than in the other parsing clusters: `timestamp`,
`fileMtime`, `createdAt`, `lastUpdatedAt`, `clientStartTime`, `started_at`,
`completed_at`, `started_at_ms`, `completed_at_ms`, `occurred_at_ms`,
`durationMs`, `time_to_first_token_ms`, and `source_mtime` are all read from
vendor records, in seconds, milliseconds, nanoseconds, and ISO text.

#### Requirements for the Shared Time Normalizer

Each row is a decision the three parsers currently make differently or leave
unstated. A normalizer that does not answer all of them reproduces the problem
under one name.

| # | Requirement | Why, and what breaks without it |
|---|---|---|
| R1 | Accept ISO-8601 text, epoch seconds, and epoch milliseconds; return Unix milliseconds as `float` | `events.event_at` is `REAL` holding milliseconds, so the return unit is fixed by the store rather than chosen |
| R2 | A naive ISO string is read as UTC, and that assumption is recorded | All three parsers already do this. Unrecorded, a local-time stamp shifts by the reader's offset with nothing saying it was assumed |
| R3 | State the seconds/milliseconds boundary as a named constant, not an inline `1e12` | `codex` and `cursor` scale below `1e12`; `cc` does not. The threshold is a decision about which epoch range is plausible and belongs where it can be read |
| R4 | Reject `bool` before the numeric branch | `True` is an `int` in Python, so `cc` returns `1.0` -- 1970-01-01T00:00:00.001 -- for a flag misread as a time |
| R5 | Decide numeric strings explicitly | No parser accepts `"1700000000000"` today. That agreement is accidental: three independent omissions, not a stated rule |
| R6 | Decide surrounding whitespace explicitly | Only `cursor` strips it, so the same padded value parses from one vendor and not another |
| R7 | Return `None` for every unparseable input; never raise | Callers treat `None` as "no time" and pair it with a field state. An exception would abort a decode over one bad field |
| R8 | Never infer a time from another value | Codess does not derive time from ordering, adjacency, or file position; the normalizer must not become the place that starts |

**Could be out of scope**, because these are the caller's:

- *Which field to read.* `timestamp`, `createdAt`, `clientStartTime`, and the
  rest are vendor knowledge and stay in the adapters.
- *What a failure means.* The `field_state` upgrade from `present` to
  `malformed` needs the expected type, which only the calling parser knows.
- *Which basis was used.* `events.event_at_basis` records how a time was
  obtained; that is a mapping decision, not a parsing one.

#### Where It Applies

| Site | Today | After |
|---|---|---|
| `adapters/cc._parse_timestamp` | **Delegates** to `units.epoch_milliseconds` | Done |
| `adapters/codex._parse_timestamp` | **Delegates** to `units.epoch_milliseconds` | Done |
| `cursor_source.parse_timestamp` | **Delegates**, keeping its plausibility floor | Done |
| `walk_sessions` | `fromisoformat` inline on a session index | Calls the normalizer |
| `token_usage` | `fromisoformat` inline on usage records | Calls the normalizer |
| `refresh_receipts` | `fromisoformat` inline on receipt text | Calls the normalizer |

**The three parsers are consolidated; the three inline callers are not.**
`units.epoch_milliseconds` answers R1 through R8 and the adapters delegate to
it. `units` was already the home for representation with no Codess import,
which is what R-scope requires of the normalizer.

**One vendor difference survived, and deliberately.** Cursor rejects a numeric
value below `EPOCH_SECONDS_FLOOR` rather than scaling it, because Cursor bubbles
carry counters and enum codes in fields a reader might take for stamps -- `999`
and `0` are values it must refuse, while `cc` and `codex` read a small number as
seconds. That floor is now a named constant applied by the caller, so the
difference is stated rather than emergent from three separate implementations.

**Consolidation removed the last `datetime` use from three modules**, leaving
unused imports the quality gate caught as a lint rise. The gate is the reason
this was noticed rather than committed: a consolidation that deletes the only
caller of an import leaves the import behind.

The thirteen time-bearing vendor fields -- `timestamp`, `fileMtime`,
`createdAt`, `lastUpdatedAt`, `clientStartTime`, `started_at`, `completed_at`,
`started_at_ms`, `completed_at_ms`, `occurred_at_ms`, `durationMs`,
`time_to_first_token_ms`, `source_mtime` -- are read by those six sites, so
consolidating the parsers covers all of them without touching field selection.

**One related defect is a naming problem rather than a parsing one, and stays
with W50/W51**: `sessions.started_at` is `REAL` while
`processing_runs.started_at` is `TEXT`, so one column name denotes two
representations. The normalizer does not fix that; a rename does.

#### Validation

- A table of inputs to expected outputs, one row per requirement above,
  including the three inputs the current parsers disagree on.
- A test asserting no module outside the normalizer calls `fromisoformat` or
  defines its own `_parse_timestamp`, in the shape the layer-boundary tests
  already use -- otherwise a fourth parser appears the way the third did.
- Re-ingest one Project per vendor and confirm `event_at` values are unchanged,
  since a parser change that alters stored times is a wire-format change rather
  than a consolidation.

**Nothing in this is specific to Codess**, which decides where it lives.
`_parse_timestamp` reads a value that may be ISO text, epoch seconds, or epoch
milliseconds and returns milliseconds; that is a general problem, and the five
decisions above are general decisions. The Codess-specific part is only *which
field to read* and *what a failure means* -- the `field_state` upgrade to
`malformed`, and the diagnostic that records it.

So the split is: a self-contained normalizer with no Codess import, taking a
value and a stated contract; and the existing per-adapter code that selects the
field and reports the outcome. That keeps the vendor knowledge in the adapters
and makes the normalizer testable against a table of inputs rather than against
a decoded record.

Whether it becomes a separate distribution is a later question with a higher
bar -- a published package needs a maintainer and a versioning commitment. The
first step is the internal module boundary, which is worth having regardless
and is a precondition for extraction either way.

**Time is the only candidate here with that property.** The MCP server split
matches three vendor spellings of a prefix, and the Codex output header parses
one product's free-text block; both are worth consolidating and neither means
anything outside this codebase. That difference is what makes time worth a
module rather than a helper function.

**Also assess** whether a library replaces hand-rolled work -- `email.parser` or
`dateutil` for the timestamp fallbacks -- and whether SQLite's own JSON functions
can replace materializing rows Python then re-parses.

**Evidence to close.** One helper per parsing concern; no vendor spelling matched
in two modules; a new adapter reaches for the same tools in the same order.

**Cost.** Correctness-neutral; no regeneration.

### W64 -- Typing Posture

**Work.** Decide the codebase-wide typing posture and enforce it. Annotations are
complete: every function has a return type and every argument has one.

**Three decisions.**

1. *Which strict flags to enable.* `disallow_untyped_defs` is within reach.
   `strict_optional` and `warn_return_any` were deferred to W04 on the grounds
   that errors concentrate at the decode boundary, which is measurably false --
   a majority sit outside it. What remains after the naming and annotation pass
   is dominated by optional-narrowing, which is exactly what `strict_optional`
   decides, so this item no longer waits on W04 for its evidence.
2. *Where `Any` is honest.* One explicit `Any` on the heterogeneous env-value table
   removed 50 spurious errors. The rule wants stating: `Any` at a deliberately
   heterogeneous boundary is documentation, `Any` threaded onward is an escape.
3. *Where a `TypedDict` pays.* It typed `refresh_operations`' kwargs bag to zero
   errors at no runtime cost -- an annotated literal is a plain dict, while the
   `TypedDict(...)` constructor form is not. The remaining `arg-type` and
   `assignment` errors concentrate in the `opts` and `settings` bags threaded
   through ingest.

**Evidence to close.** The enabled flag set is recorded with the reasoning for
each; `Any` appears only where a stated rule permits it; the type count falls
rather than being reclassified; `tools/quality_report.py` gates on the baseline.

**Blocked by.** W04, which moves the decode boundary a large share of the
remaining errors sit behind.

### W65 -- Recurring Parameter Groups

**Work.** Consolidate the relay parameter groups that remain. Separating functions
by use gives two populations, and only one is a candidate:

- **Builders** place their parameters into a returned literal and are correct as
  they stand. The parameter list *is* the record's shape.
- **Relays** forward their parameters to another call and are the struct
  candidates.

**Two groups remain.**

| Group | Where | Note |
|---|---|---|
| Record context (`session_id`, `source_file`, `line_num`, `opts`) | Seven adapter functions | The identity of the record being decoded; belongs with W04, which rewrites these signatures anyway |
| Catalog-refresh relay chain | `refresh_candidates` → `apply_project` → `onboard_catalog` | Threads ten values through three layers; owns no other item |

**What consolidation buys, and what it does not.** `ChildInvocation` removed three
specifications of one command line and collapsed a test from two patch points to
one, while leaving every caller's parameter count unchanged -- the callers still
receive those values to build the object. A signature shortens only where a relay
can take the object instead of its fields.

**Evidence to close.** Each recurring parameter group is either one named object or
recorded as a builder whose parameter list is its subject; no argv or environment
is constructed in two places; a test fails when a second builder appears.

**Blocked by.** W04, for the record-context group only.

### W66 -- Configuration Unification

**Work.** One component owning declaration, default, precedence, and validation for
every setting, so a new option is one table row rather than four edits.

**The defect.** A value's default is currently decided in up to four places -- a
compiled constant in `config`, an `env_*` reader, an argparse `default=`, and a
`getattr(args, ..., None) or CONSTANT` fallback at the use site -- and nothing
states which wins. `--registry` and `--dir` each appear in four modules;
`--source`, `--raw-mode`, `--min-size`, `--force`, and `--resource-policy` in
three. [CoReview](CoReview.md) holds the measured counts.

**The ordering constraint is real and undocumented.** `project._settings` resolves
`int(MIN_SIZE if raw is None else raw)` while `schema_contract` and `fileio` read
their environment variables directly *because* `config`'s constants have already
resolved by the time a flag is parsed. Three modules work around this individually;
it should be stated once.

**Also in scope.** A config file admitted as a source, which no current path
supports.

**How the duplication arose.** Not by neglect -- by the absence of a mechanism.
`admin_cmd` builds **42 subparsers** and declares **158 flags inside them**,
and nothing in the file uses argparse's own `parents=` facility for shared
options -- verified to do exactly this job: one declaration on a parent parser,
inherited by every subparser that lists it. So a new subcommand that needs `--registry` gets it the only way the
surrounding code demonstrates: by writing the line again. Sixteen subcommands
need it, so the line exists sixteen times. Each addition was locally correct and
matched its neighbours; the pattern that was being matched is the defect.

That is the same mechanism CoPlan records for the snapshot file literals: a
module needs one fact, an inline declaration is smaller than a shared-code
change, and repetition across many small additions produces the duplication
without any single change being wrong. It predicts where to look next --
wherever a construct is built dozens of times with no shared helper.

**Argument audit: nothing is obsolete, and that is the finding.** All 172
distinct destinations are read somewhere in `src/`; none is dead. But the *way*
they are read splits into two populations:

| Reads via `args.X` | Dests | What it means |
|---|---|---|
| 0 | 13 | Reached only through the `settings` bag or `flag_or_env` |
| 1 | 82 | Read at one call site and passed on |
| 2 or more | 77 | Read at several sites; the top one is read 25 times |

The thirteen -- `--debug`, `--redact`, `--strict-mapping`, `--subagent`,
`--validate-only`, `--no-hash`, `--version`, `--session-relation`, and the five
`--max-*` bounds -- each reach a real consumer, so none should be removed.

**Two options go the other way: read but never set.** `opts` is queried for
`include_product_state` and `max_external_content_bytes`, and nothing in `src/`
writes either, so one is always its `True` default and the other always `None`.
Both have correct fallbacks, so behaviour is right; both are unreachable by an
operator and invisible as inert to a reader. Declare them in the table or
delete them -- an undeclared setting that cannot be set is neither. What
they demonstrate is the cost of the bag: a reader grepping `args.debug` finds
nothing and concludes the flag is dead, when it is read as `settings["debug"]`
two layers away. The setting table fixes this as a side effect, since a declared
setting names its own consumer.

**No flag should be declared twice for the same setting.** The 25 duplicated
names are all one setting reached from several subcommands, so `parents=`
removes every one of them without changing a single `--help` line: argparse
renders an inherited option exactly as a locally declared one. The duplication
is a source-code fact, not a user-visible one, so the fix is in the declaration
and the help text is what must stay identical.

One flag previously carried two superseded spellings --
`--snapshot-contract-policy` and `--snapshot-package-policy` -- and both are
now gone in favour of `--snapshot-policy`. An alias is only worth keeping where
a caller's script would break, and neither spelling had reached that status.

**Every `--no-` flag, and what it turns off.** Seven, and they are not one
family: five disable a check or an output, two invert a default.

| Flag | Command | Disables | Stated |
|---|---|---|---|
| `--no-hash` | ingest, query | Snapshot and manifest hash verification on read | Yes, with "recovery/debugging only" |
| `--no-check` | ingest, query | The released-contract verification | Yes, with "tests and recovery" |
| `--no-resource` | ingest | Transcript, container, event, and context maximums | Yes |
| `--no-progress` | ingest | Live progress on stderr, keeping the structured trace | Yes |
| `--no-propose` | `config discovery` | Reading the work root to propose exclusions | Yes |
| `--no-record` | `storage report` | Writing the observation | Yes, added |
| `--no-smoke` | `baseline apply` | The post-apply query check | Yes, added |

Two carried no help at all, and both gate a verification step -- exactly where
an operator most needs to know what is being skipped. Both are now documented;
the first four already said what they bypass *and* that a bypass is logged,
which is the standard.

**The gap is wider than those two.** 76 distinct flag names carry no help text, and **every
one is in `admin_cmd`** -- `project.py` documents all of its own. So the
administrative surface is undocumented as a class, not by oversight in a few
places: `--registry`, `--source`, `--force`, `--min-size`, and `--raw-mode` are
among them, which is the same set the duplication concentrates in. A flag
declared sixteen times with no help is sixteen chances to write one and none
taken.

This is what makes `parents=` worth more than the deduplication itself: one
declaration carries one help string to every subcommand that inherits it, so
documenting the shared options is a single edit rather than sixteen.

**The naming, settled before the table generates anything.** Three questions,
and they resolve together.

*First: `.codess` is a depository, not a store or a registry.* It sits beside
the work it describes, exactly as `.git` does, and holds derived state a tool
owns rather than content a person edits. `depository`/`depo` parallels
`repository`/`repo` and is the honest word: a repository holds the work, a
depository holds what a tool deposited about it. `STORE_DIR = ".codess"` is
currently named for one of the things inside it -- the stores -- which is the
same part-for-whole error as calling the directory a registry.

*Second: the two `.codess` directories are not the same kind of thing, and
neither is config or state.* Measured rather than assumed: the machine-level
directory is **58 GB, of which 57 GB is `projects/`** -- published store sets,
one per Project. It is a store first and everything else second.

| | Per-Project `<project>/.codess` | Machine `~/.codess` |
|---|---|---|
| Bulk | Working stores and their snapshots | Published store sets, one per Project |
| Also holds | Current pointer, ingest state, last report | Project catalog, activity index, receipts, reports, retention, raw capture, quarantine, `machine-id` |
| Scope | One Project | One machine |
| Lifetime | Deleted with the checkout | Outlives every Project it records |

**The two are not duplicates.** A Project's `current.json` points *into* the
machine directory: the working store is beside the checkout, and the published
one the pointer selects is central. `project_catalog.durable_project_root`
already names that half "durable", which is the distinction the directory names
do not carry.

So a `config`/`state` name would misdescribe both -- neither is predominantly
either, and configuration reaches Codess through the environment and flags
rather than a file in these directories. `depo` fits the per-Project side, where
a tool deposits what it derived beside the work. For the machine side the honest
word is the one already in the code: it holds **durable stores**.

| Now | Proposed | Is |
|---|---|---|
| `STORE_DIR` (`.codess`) | `PROJECT_DEPO` | The Project depo, beside the work: working stores and a pointer |
| `REGISTRY` / `registry` / `registry_root` | `DURABLE_STORE` / `store_root` | The machine's durable store, `~/.codess` |
| `ingested_projects.json` (`STATS_FILE`) | *the activity index* | Per-Project scan/ingest/query timestamps and counts |
| `projects.json` | *the registry* | Project identity, locations, aliases, workspace bindings |
| `registry_store` (module) | `activity_index` | Reads and writes the activity index, not the registry |
| `--registry` | `--store` | Selects the machine's durable store |

**Confirming what "registry" means: central information about every Project and
its status -- yes, and the two files that hold it are separately justified.**

| File | Keyed by | Holds | Written by |
|---|---|---|---|
| `projects.json` | `project_id` | Identity: locations, logical name, path aliases, workspace bindings | Catalog operations only -- onboarding, relocation, retirement |
| `ingested_projects.json` | `path` | Status: `sources`, `last_scan`, `last_ingestion`, `last_query`, and counts | Every `scan`, `ingest`, and `query` run |

**They are not a split that should be merged.** Three measured reasons:

1. *Different keys, and the difference is the point.* The catalog is keyed by
   `project_id` and carries a `locations` list, because one Project can be
   checked out in several places. The status file has **no `project_id` field on
   any entry** -- it is keyed by path, so it cannot express that model at all.
   Merging would either force a path-keyed file to grow an identity it does not
   have, or force identity records to carry per-path activity they do not own.
2. *Different write cadence.* The status file is written by every scan, ingest,
   and query -- three commands, every run. The catalog is written only when a
   Project's identity changes. Merging puts a high-frequency append in the same
   document as the record that must not be lost, and a crash during one would
   risk the other.
3. *Different populations, already.* 32 catalog entries against 31 status
   entries, and nine paths appear in status with no catalog location --
   `~/.codex` and `~/.openclaw-repo/workspace` among them, which are directories
   holding Sessions but never onboarded as Projects. That is correct behaviour:
   activity is observable before identity is established.

Neither module reads the other's file, so the separation is real in the code and
not only on disk.

**Naming them.** `ingested_projects.json` is wrong twice over: it is written by
`scan` and `query` as well as `ingest`, so "ingested" names one of its three
writers; and its subject is what has happened to a Project, not which Projects
were ingested. `projects_state.json` fixes both -- the subject is Project state,
and no writer is privileged. Paired with `projects.json` for identity, the two
read as what they are.

| Now | Proposed | Is |
|---|---|---|
| `projects.json` | `projects.json`, unchanged | The registry: which Projects exist and where |
| `ingested_projects.json` (`STATS_FILE`) | `projects_state.json` (`PROJECT_STATE_FILE`) | Per-Project status: what was scanned, ingested, queried, and when |
| `registry_store` (module) | `project_state` | Reads and writes that file |

`STATS_FILE` is also a poor constant name: the file holds timestamps and source
lists as well as counts, so "stats" describes one column family rather than the
document.

**How the vendors name theirs, checked rather than assumed.** All three keep a
per-user home directory of the same shape -- `~/.claude`, `~/.codex`,
`~/.cursor` -- each mixing configuration, credentials, caches, and session data,
and none names it in its own documentation. Claude Code additionally supports an
optional per-directory `.claude`, but it carries *settings* only: this
repository's holds one file, `settings.local.json`. That is the inverse of the
split here, where both halves are bulk data. So there is no vendor term to
borrow, and the two-level split Codess uses is its own.

**"Primary paths" is the wrong label, and one vendor document already does
better.** CCSchema and CodexSchema head a table row with **Primary paths**,
which says neither whose paths they are nor what makes them primary -- there is
no secondary set to contrast with. CursorSchema does not use the row at all: it
has a section called **Source Scope and Locations** and a table headed **Default
base**, which name the subject and admit that the value is a default an
environment variable overrides.

| Now | Proposed | Why |
|---|---|---|
| **Primary paths** | **Source locations** | Names the subject -- these are where a vendor's Sources are found. "Source" is the defined entity, so the row inherits its meaning |
| (Cursor's) **Default base** | **Default base**, unchanged | Already correct: a base that a platform sets and configuration overrides |

Apply the same row to all three vendor documents so a reader comparing them
reads one heading, and state the override variable in the row as CCSchema
already does.

*Third: `storage registry-prune` names its object, not its subject, and the
verb collides.* Two subcommands prune:

| Subcommand | Removes | Because |
|---|---|---|
| `storage prune` | Retained snapshots under the depository | Retention policy says they are superseded |
| `storage registry-prune` | Entries in the Project index | Their Project path no longer exists |

Same verb, different objects, and neither name says which. The second is not
pruning a registry -- it is removing index entries that no longer refer to
anything, which is a *reconciliation* against the filesystem rather than a
retention decision. Proposed:

| Now | Proposed | Reads as |
|---|---|---|
| `storage prune` | `storage prune-snapshots` | Apply retention to retained snapshots |
| `storage registry-prune` | `registry reconcile` | Drop index entries whose Project is gone |

`reconcile` states the subject: the index is being made to agree with the
filesystem. It also admits the operation's other half honestly -- an entry
pointing at a moved Project is as stale as one pointing at a deleted Project,
and a verb meaning "remove" cannot describe fixing it, while a verb meaning
"agree with what is there" can.

Moving it out of `storage` and under `registry` follows from the first two
answers: `storage` is about the depository's bytes, and this operation is about
the index's accuracy.

**How to do it.** Six steps, each leaving the suite green, so the work can stop
between any two.

| Step | Work | Checked by |
|---|---|---|
| 1 | Extend `config`'s existing env table to a **setting table**: one row per setting naming its env var, flag, type, default, and which commands accept it. The table exists and is table-driven already; what it lacks is the flag half. | A test asserts every row is well-formed and no two rows share a flag |
| 2 | Emit the argparse declarations **from** the table rather than by hand, one helper per command family. | `--help` output is byte-identical before and after, per command |
| 3 | Resolve the three `--registry` variants into the one the table declares. | Below |
| 4 | Replace the `getattr(args, ..., None) or CONSTANT` sites with one accessor that applies the stated precedence. | A test covers each precedence pair: flag over env, env over built-in |
| 5 | State the import-order constraint once, and give the two flags that work around it a supported path. | The `os.environ[...] = "1"` writes in `project.parse_and_run` are gone |
| 6 | Admit a config file as a source, between built-in and environment. | A file-set value loses to both the env var and the flag |

**Step 3 is a real defect, not a tidy-up.** `--registry` is declared **16
times** across two modules in three incompatible forms:

| Form | Where | Consumed by |
|---|---|---|
| `type=Path, default=REGISTRY` | `admin_cmd`, 14 subcommands | `args.registry` directly, so it must be a `Path` |
| `type=str, default=None` | `project.py` | `resolve_registry_directory`, which accepts `str \| None` |
| `type=Path, required=True` | `admin_cmd`, one subcommand | `args.registry` directly |

A caller moving between command families gets a different type from the same
flag name. The table settles it: declare `Path` with the `REGISTRY` default and
route every consumer through `resolve_registry_directory`, which already
normalizes both.

**Step 5, stated exactly.** `config`'s constants resolve at import, which is
before a flag is parsed. Two flags therefore work around it by writing the
environment variable their reader observes -- `project.parse_and_run` sets
`CODESS_NO_CONTRACT_CHECK` and `CODESS_NO_HASH` so `schema_contract` and
`fileio` see them. Both comments say this correctly; neither is wrong. The
constraint is that a **leaf module cannot import `config`**, so it reads the
environment directly and a flag has to reach it that way. The fix is not to
remove the workaround but to make it the declared mechanism: a setting marked
as leaf-visible is written to the environment by the resolver, once, instead of
by two hand-written assignments.

**Scope check.** 257 `add_argument` calls across exactly two files; 152 distinct
flags of which **25 are declared more than once**; 133 `getattr(args, ...)`
sites. The duplication is concentrated -- `--registry` 16, `--output` 11,
`--project-id` 8, `--catalog`/`--source`/`--resource-policy`/`--project` 4 each
-- so eight names account for more than half of it.

**Evidence to close.** One declaration per setting names its flag, variable,
default, and type; precedence is stated and tested; no module reads `os.environ`
for a declared setting except through the leaf-visible mechanism step 5 defines;
a flag name appears in exactly one module.

**Precedent.** `ChildInvocation` is the shape for the argv half and is done.

### W67 -- Relay Fields Into Objects

**Work.** Move relay fields into the objects that carry them. `run_ingest` went
from 8 parameters to 1 by taking `ChildInvocation` rather than its fields, which
also exposed that its two callers built the same invocation twice -- the repeat run
exists to prove the first is reproducible, so the two must not be able to differ.

**Remaining relays**, measured by parameters forwarded rather than used:

| Function | Forwarded |
|---|---|
| `review_project.refresh_candidates` | 10 of 14 |
| `baseline_operations.apply_project` | 10 of 12 |
| `ingest_cmd._ingest_project` | 10 of 10 |
| `catalog_operations.onboard_catalog` | 8 of 10 |
| `ingest_publication.publish_snapshot` | 6 of 10 |

**Do not convert a builder.** `codex._base_event` takes 19 parameters and places
all 19 into its returned dict; an object would name the same fields twice. The
distinction is measurable -- parameters reaching a literal against parameters
reaching another call -- and is the rule to apply.

**Proposed structures.** Three, and the partition between them is by *lifetime*
-- when the value is decided and when it stops being true -- because that is the
axis the existing structures already use and the one the current dicts blur.

| Structure | Holds | Decided | Mutability | Modelled on |
|---|---|---|---|---|
| `RunPolicy` | `registry`, `repo_root`, `min_size`, `raw_mode`, `resource_policy`, `force`, `timeout_seconds`, `source` | Once, before the first Project | `frozen` | `ChildInvocation` |
| `ProjectRef` | `path`, `project_id`, `location_id`, `index`, `total` | Per loop iteration | `frozen` | `ProjectScope` |
| `DiscoveryPolicy` | `roots`, `vendor_filter`, `recent_days`, `include_git`, `discover_git`, `max_depth`, `check_remotes`, `max_directories`, `deadline_seconds`, `same_filesystem` | Once, before traversal | `frozen` | `ResourcePolicy` |

**Why these three and not one.** `RunPolicy` and `DiscoveryPolicy` are both
run-lifetime and could merge, but they have different subjects and different
consumers: discovery bounds a filesystem walk and is read only by
`review_project`, while `RunPolicy` describes what an ingest does and is read by
four modules. Merging them would put a `deadline_seconds` that bounds a walk
beside a `timeout_seconds` that bounds a child process -- two unrelated bounds
one field apart, which is the collision the naming rules exist to prevent.

**Verified against what exists, and one is already built.** `ChildInvocation`
holds `registry`, `repo_root`, `min_size`, `resource_policy`, `force`,
`raw_mode`, and `timeout_seconds` -- every field `RunPolicy` would carry.
`refresh_operations._run_project_ingest` takes eight parameters and immediately
packs seven into a `ChildInvocation`; `refresh_projects` takes seventeen and
threads them down two layers to do it. So `RunPolicy` should not be a new
class: the relays should take `ChildInvocation`, which is what `run_ingest`
already did when it went from eight parameters to one.

That leaves the partition question sharper. `ChildInvocation` currently mixes
two subjects -- a *policy* (`registry`, `repo_root`, `min_size`, `raw_mode`,
`force`, `resource_policy`, `timeout_seconds`) and a *target* (`projects`,
`vendor_selector`, `validate`). The policy half is identical across every
Project in a run; the target half changes per invocation.

**The two `_run_project_ingest` call sites are the evidence.** Both pass the
same six policy arguments verbatim, differing only in `validate` and the loop
variable:

```python
result = _run_project_ingest(
    project, validate=True, registry=registry,
    repo_root=repo_root, min_size=min_size, force=force,
    resource_policy=resource_policy, timeout_seconds=timeout_seconds,
)
```

Six of the eight arguments carry no information at either site -- they restate
what the enclosing `refresh_projects` was given seventeen parameters earlier.
With the split, both become `_run_project_ingest(project, policy,
validate=...)`. Do the split before adding callers, not after.

**Field ownership, checked against the existing structures.**

| Field | Belongs to | Not to | Because |
|---|---|---|---|
| `raw_records`, `raw_store`, `content_actions` | `ProjectScope` | `IngestConfig` | Replaced every iteration; a carried-over value attributes one Project's evidence to the next |
| `outcome`, `diagnostics` | `RunTotals` | `IngestConfig` | Mutated in place; the read-only and mutable halves are deliberately separate |
| `options`, `sources`, `registry_root` | `IngestConfig` | `RunTotals` | Decided before the first Project and unchanging |
| `store_path`, `__getitem__` | `StoreLocator` protocol | `IngestConfig` directly | Publication needs two members, so the dependency points into the domain rather than back out |
| `workspace_ids`, `global_db` | `CursorSelection` | `IngestConfig` | Vendor-specific selection, owned by the module that reads the vendor store |

Each of those five is already correct. The gap is not that the vocabulary is
wrong; it is that the relays do not use it.

**Build the structure at the origin, not at the relay.** A struct constructed
inside a relay moves the packing rather than removing it -- the caller still
passes the fields and the callee still assembles them. Traced to where each
value comes from, every one of these chains starts in the same place:

| Entry point | Sole non-test caller | Where the values come from |
|---|---|---|
| `refresh_projects` (17 params) | `admin_cmd._refresh` | `args.*` and `REPO_ROOT` |
| `onboard_catalog` (10) | `admin_cmd._catalog_onboard` | `args.*` and `REPO_ROOT` |
| `apply_project` (12) | `admin_cmd._baseline_apply` | `args.*` and `REPO_ROOT` |
| `refresh_candidates` (14) | `admin_cmd._catalog_candidates` | `args.*` |

Every value is read off `argparse.Namespace` at one command adapter and then
threaded down two or three layers unchanged. So the object belongs at that
adapter: built once from `args`, passed whole, and never unpacked until
something reads a field.

**Five parameters are shared by all three ingest-side entry points** --
`registry`, `repo_root`, `source`, `raw_mode`, `resource_policy` -- with
`min_size` in two of the three and `force`/`timeout_seconds` in one. That
subset is the object, and it is the same subset `ChildInvocation` already
carries.

**One packing function already exists and shows the shape.**
`refresh_projects` accepts nine parameters it uses exactly once each, purely to
build a `_ResolveArgs` TypedDict and splat it into
`resolve_refresh_selection`. The TypedDict is right; its construction site is
not. Built at the command adapter instead, `refresh_projects` loses nine
parameters and gains one, and the nine names stop appearing in a signature that
does not read them.

Moving it makes `_ResolveArgs` public, which is the correct consequence rather
than a cost: a shape two modules pass between them is an interface, and the
leading underscore currently says it is not. It is already used twice inside
`refresh_projects`, so the second call site keeps working unchanged.

**What moves up, and what does not.** Values decided by the operator move to
the adapter. Values *derived* during the run stay where they are derived:
`plan["projects"]`, the per-Project `project_id` and `location_id`, and the
receipt path when it is defaulted from a timestamp. The test is whether the
value exists before the operation starts -- if it does, the adapter owns it.

**This overlaps W66 and should not be done twice.** The same five names are
redeclared as argparse options per subcommand, which is what W66 measures as
39 names spelled in more than one module. One declaration producing one object
answers both: W66 owns where a setting is declared, W67 owns what carries it
onward, and the object is the seam between them. Doing W67 first with a
hand-built object would encode the current duplication into a constructor.

**Two anti-patterns to avoid, both already demonstrated here.** Do not convert a
builder: `codex._base_event` takes 19 parameters and places all 19 into its
returned dict, so an object would name the same fields twice. And do not add a
structure whose only member is another structure's fields -- `RunPolicy` was
proposed above and then withdrawn on exactly that ground.

**How to do it.** Five steps, in this order because each makes the next
mechanical. Do them after W66's setting table exists, so the object is built
from one declaration rather than from 25 duplicated ones.

| Step | Work | Checked by |
|---|---|---|
| 1 | Split `ChildInvocation` into its policy half (`registry`, `repo_root`, `min_size`, `raw_mode`, `force`, `resource_policy`, `timeout_seconds`) and its target half (`projects`, `vendor_selector`, `validate`). Keep `command()` and `environment()` taking both. | Existing `ChildInvocation` tests pass unchanged; a policy is reusable across two targets |
| 2 | Build the policy at the four command adapters from the W66 table, and pass it whole. | Each adapter constructs it exactly once |
| 3 | Convert the relays innermost-first: `_run_project_ingest`, then `refresh_projects`, then `apply_project`, `onboard_catalog`, `refresh_candidates`. | Parameter counts fall; no call site rebuilds what it was handed |
| 4 | Move `_ResolveArgs` construction to the adapter and make it public. Its nine values are read off `args` and used once each. | `refresh_projects` no longer names those nine |
| 5 | Re-run the relay census. Anything still forwarding five or more is either converted or recorded as a builder with its measurement. | The census runs as a test -- measured at 216 ms over `src/`, so it costs nothing to keep -- and a new relay fails rather than accumulating |

**Innermost-first is what keeps each step small.** `_run_project_ingest` already
packs seven of its eight parameters into a `ChildInvocation`, so converting it
first is a signature change with no body change -- and its two call sites pass
identical policy arguments, so the caller simplifies in the same edit. Working
outside-in instead means each layer is converted twice: once to take the object,
once when the layer below it changes.

**Order these by what they remove, not by size.**

| Relay | Params | Forwarded | Removed by the object |
|---|---|---|---|
| `refresh_operations._run_project_ingest` | 8 | 8 | 6 |
| `refresh_operations.refresh_projects` | 17 | -- | 9 via `_ResolveArgs`, 6 via policy |
| `baseline_operations.apply_project` | 12 | 10 | 6 |
| `catalog_operations.onboard_catalog` | 10 | 8 | 5 |
| `review_project.refresh_candidates` | 14 | 10 | 10 via `DiscoveryPolicy` |

**`refresh_candidates` is the one that needs a new structure.** The other four
are served by splitting `ChildInvocation`; its ten discovery parameters have no
existing home, which is what `DiscoveryPolicy` is for. Build it last, so the
pattern is established before a new type is introduced.

**Evidence to close.** Every relay of five or more parameters takes an object or is
recorded as a builder; a call site cannot mis-order same-typed arguments; no
invocation is constructed twice where one would do; `ChildInvocation`'s policy
and target halves are separable, or the reason they are not is recorded; the
relay census runs as a test.

### W70 -- Documentation Partition and Redundancy

**Work.** Re-partition the documentation set against its stated charters, and
remove the conceptual redundancy that has accumulated across documents.

**The evidence.** Verbatim duplication is not the problem -- exactly one
sentence appears in two documents. The problem is that a single topic is
discussed, from scratch, in many places:

| Topic | Documents discussing it |
|---|---|
| Mapping profiles | 8 |
| Snapshots | 7 |
| Raw mode and capture | 5 |
| Coverage reporting | 4 |
| `quality_report` | 4 |
| Candidate records | 3 |

Work items spread the same way. W04 was mentioned 40 times across four
documents before this item was written, including a five-step implementation
plan with verification criteria in CoReview -- forward-looking planning inside
the document whose charter is "evidence, not a plan". Moving that plan to
CoTasks cut CoReview's W04 mentions from 17 to 5.

**The rule to apply.** One topic has one authoritative location; every other
document states only what its own charter requires and links rather than
restates. Where two documents must both discuss a topic, the second states the
consequence for its own subject, not the topic.

**Method.** For each topic above, identify the charter that owns it, reduce
every other treatment to a consequence or a link, and check the result against
the documentation map. The charters exist and are stated in each document's
opening; the divergence is between them and the contents, so the charter is the
fixed point.

**Evidence to close.** Every topic in the table has one authoritative location
named in the documentation map; no document restates another's subject beyond
the consequence for its own; no work item's scope, steps, or verification
criteria appear outside CoTasks.

**Cost.** Documentation only. No rebuild, no code change.

**Why it is an item.** It has a completion condition and an enumerated scope.
The recurring alternative -- fixing repetition when it is noticed -- is what
produced the current state.

### W71 -- Adopt the Reporting Facility in the Command Layer

**Work.** Route command-layer status, progress, warnings, and errors through
`codess.reporting` instead of writing them directly.

**The gap.** The facility is complete and specified; the callers were never
converted. Measured across `src/`:

| Path | Count | Location |
|---|---|---|
| `reporting.*` call sites | 8 | mixed |
| `print(file=sys.stderr)` | 43 | the four command modules |
| Direct `sys.stderr` writes | 63 | the four command modules |
| `logging` calls | 33 | mixed |

**What is already correct and must not change.** Result output on stdout stays
a plain `print()`. That is the result channel, and it is what lets
`--output-format jsonl` be piped. Only the stderr half is in scope.

**Why it matters beyond tidiness.** Every property the facility provides --
level gating, profile selection, privacy classification, bounded fields,
never raising into the operation it reports on -- applies only to calls that go
through it. A direct `sys.stderr` write has none of them, so the guarantees
currently hold by convention at each call site rather than by construction, and
a redaction profile does not reach the output an operator actually sees.

**Evidence to close.** No command module writes to `sys.stderr` directly; the
channel-separation test asserts it rather than the current convention;
`--output-format jsonl` remains byte-identical on stdout across profiles.

**Cost.** Mechanical per call site, no rebuild. Independent of W04.

### W72 -- The Event Record Shape, Spelled Out Four Times

**Work.** Route every Event construction through one builder per adapter, and
give Cursor the builder the other two have.

**Found by `pylint --enable=R0801`**, which reports near-identical line blocks
across modules -- a capability neither ruff nor the structural-duplication test
has, because the repetition is a *fragment* inside larger functions rather than
a whole function.

**The evidence.** Sixteen clusters; the sharpest is the common Event field
block, appearing in all three adapters:

| Site | Shape |
|---|---|
| `cc.py:940` | `role`, `content`, `content_len`, `content_ref`, `tool_name`, `tool_input`, `tool_output`, `timestamp` |
| `codex.py:1520` | the same eight keys, same order |
| `cursor.py:185` | the same eight keys, same order |

`cc._base_event` and `codex._base_event` exist precisely to prevent this --
`codex._base_event`'s docstring records that fifteen call sites each wrote the
same twenty keys inline, 405 lines collapsed into one builder. The clusters are
the sites that were never converted, plus a third adapter that never got a
builder: **`cursor.py` has no module-level `_base_event`**, only a nested
`base_ev` closure introduced later at line 495, so the earlier construction at
line 178 still spells the record out.

**Remaining clusters, grouped by what they say.**

| Cluster | Modules | Reading |
|---|---|---|
| Event field block | `cc`, `codex`, `cursor` | The builder exists and is not universally used |
| Metrics accumulator (`day`, `events`, `content_characters`, `sessions`, `interactions`) | `orientation_audit`, `query_api` | Two report paths accumulate the same per-day shape; a shared accumulator is the fix |
| Reporting re-export | `reporting.__init__`, `reporting.api` | The package re-exports its own API; expected and correct |
| Catalog entry fields | `project_annotations`, `project_catalog`, `refresh_operations` | Three readers of the same catalog row; a typed accessor is the fix, and it is W04's shape one level up |
| Command preamble | `ingest_cmd`, `query_cmd` | Both resolve roots and store root the same way; W67 territory |

**Landed.** Cursor has a module-level `_base_event`, and its nested `base_ev`
is now a four-value closure over it rather than a second definition. The three
sites that bypassed a builder -- Cursor's request-context path, Codex's
`turn_aborted` path, Claude's assistant-text path -- construct through one.
`cc._base_event` gained `content`, `content_len`, `metadata`, and `**extra`,
which is what its bypassing site needed and the reason it had one.
The per-day activity accumulator is also one definition:
`query_api.activity_bucket` holds the twenty-one counters both sites shared,
and each passes its own extras -- the audit's per-Actor and per-relation
breakdowns, the query's last-human-prompt key. Sets are built per call rather
than defaulted, since one shared set would report the same Sessions on every
day.

`pylint R0801` clusters fell from 16 to 10, and the adapter Event-shape group
from 7 to 4.

**Remaining.** Four adapter clusters, which are not the Event envelope: two are
the shared import and constant blocks at the head of `cc` and `codex`, one is
`codex`/`cursor_source` timestamp parsing (W55), one is a tool-field block. The
catalog row read in three modules is untouched, and is the same shape W04
addresses one level up.

**Evidence to close.** No adapter constructs an Event dict outside its builder;
the per-day accumulator has one definition; `pylint --enable=R0801` reports only
clusters recorded here as accepted.

**Cost.** Correctness-neutral, no rebuild. Overlaps W04 (adapter signatures) and
W67 (command preamble), so it batches with whichever lands first.

### W73 -- The Vendor Decode Gaps CoPlan Records

**Work.** Resolve, or explicitly close, the per-vendor source cases CoPlan lists
as having a remaining action.

**Why it is an item now.** CoPlan's three vendor sections each carry a
`Source case | Current decision | Remaining action` table. Sixteen rows, one
marked Done, **fifteen open** -- and none of the fifteen is named by any work
item, so the largest body of identified decode work in the repository is
tracked only as prose inside an architecture document. That is the same failure
the item list exists to prevent: a reader of CoTasks would conclude the decode
layer has no open questions.

**The fifteen, by vendor.** Codex carries the most, and the split is not even:

| Vendor | Open | Concentrated in |
|---|---|---|
| Claude Code | 4 | Attachments and product state |
| Codex | 6 | Envelope duplication and lineage |
| Cursor | 5 | Composer attribution and projection loss |

**By component, which is what decides who does the work.**

| Component | Cases | Note |
|---|---|---|
| Adapter decode | 6 | `cc` attachment shapes, `codex` reasoning placement and compaction variants, `cursor` projection loss |
| Session relations | 4 | Claude `isSidechain`/`agentId`, Codex `parent_thread_id`/collaboration records, Cursor agent-looking state. One subject, three vendors |
| Mapping and CoSchema | 3 | Artifact/content linkage for Claude images and attachments and for Cursor file-backed content -- all three need the same new mapping |
| Coverage reporting | 2 | Cursor composers absent from an index, and projected-key comparison. Both are reporting over evidence already retained |

**By function, which decides what the work actually is.**

| Function | Cases | What has to happen first |
|---|---|---|
| Measure | 5 | Field availability by release, false-attribution rates, dangling identifier counts. No code changes until the measurement exists |
| Decide | 4 | Whether a subtype earns a mapping, where an inherited setting terminates, what an unbound composer becomes. Judgement, not effort |
| Extend fixtures | 3 | New notification and compaction shapes as vendors ship them. Recurring rather than closable |
| Define a mapping | 3 | The Artifact/content link. One decision serving all three |

**By impact and complexity**, which is the ordering that matters:

| Case group | Impact if unresolved | Complexity | Read |
|---|---|---|---|
| Artifact/content linkage (3) | Image and file-backed content stays unsearchable; the store under-reports what a Session contained | Medium -- one CoSchema mapping, three call sites | Highest value per unit of work; all three close together |
| Session parentage (4) | Subagent and fork relationships stay absent, so Interaction reconstruction misses delegated work | Medium -- measurement first, then a narrow relation | Highest product impact; blocked on evidence, not on code |
| Coverage reporting (2) | A coverage report cannot state what a Cursor projection dropped, so a clean report overstates | Low -- the report exists; this adds two comparisons | Cheapest, and it makes the other groups' progress visible |
| Setting inheritance (1) | Codex Model Turn settings may attach past their real boundary | Medium -- needs a stated termination rule and tests per field | Correctness risk, narrow scope |
| Duplicate envelopes (2) | A vendor release adds a notification shape and it is counted twice | Low per instance, but recurring | Maintenance, not a closable item |
| Retention decisions (3) | Unknown product state stays a diagnostic rather than a queryable subtype | Low each, but each needs the four-part mapping gate | Do only where a query need exists; otherwise close as declined |

**Suggested order**: coverage reporting first because it is cheap and reveals
the rest; then Artifact linkage, which is one decision unlocking three cases
across two vendors; then parentage, which needs measurement before code. The
duplicate-envelope and retention groups are ongoing and should not hold the
item open.

**Evidence to close.** Every row in CoPlan's three remaining-action tables reads
`Done` with the evidence, or states the decision that closed it without work.
The tables stay -- they are the vendor-by-vendor record -- but no row is left
describing an action nobody owns.

**Cost.** Varies per group and is not one change. The Artifact-linkage group is
a mapping decision under W04's gate; the coverage group depends on the coverage
report that already exists; the parentage group needs measurement before any
code. Nothing here is blocked on a rebuild.

**Note.** This item exists to make the gaps visible and to route each group to
its owner. Resolving all fifteen under one identifier would be a batch nobody
can finish; splitting them once each group's decision is made is the expected
path.

### W74 -- Four Measured Cursor and Codex Findings

**Work.** Four findings from reading vendor data rather than stores. Grouped
because each is small and three touch the Cursor adapter.

**1. Cursor Session times are extracted and then dropped. Closed.** The
fallback is in `ingest_sources`: where a composer's bubbles carry no time, the
Session takes `created_at` and `last_updated_at` from the header
`cursor_source` already reads, and `time_basis` records `session` rather than
`event` so a header-stated span is distinguishable from an Event-derived one.
The finding that motivated it, for the re-measurement that confirms the fix: `cursor_source`
reads `created_at` and `last_updated_at` from every composer header -- present
on all 66 on the development machine -- and `adapters/cursor` never references
either. Scan *does* use them, for the time-range row CursorSchema documents, so
the values are proven usable; only the ingest path discards them. The consequence is visible in a store: one Cursor Project has 667 Events
and two Sessions with **no timestamp anywhere**, so it cannot be ordered by time
or filtered by `--since`. This is the closest Cursor has to lifecycle evidence
and it is already selected; only the mapping is missing.

**2. Cursor has no task lifecycle, and that is a vendor fact.** Searching every
bubble field for start, end, complete, abort, cancel, status, and duration
returns `capabilityStatuses`, `statusUpdates`, and `skipRendering` -- none of
which records a task boundary. Codex produces 5,449 lifecycle Events and Claude
1,058 under its own vendor kind; Cursor has nothing to produce them from. Close
the W73 lifecycle row for Cursor as *declined, no source evidence* rather than
leaving it open.

**3. Duplicate tool results are real vendor records, not a decode artifact.**
The first reading blamed the decoder. Comparing the bubbles **field by field**
rather than by the three stored columns settles it: two bubbles carrying one
`toolCallId` differ in exactly three fields -- `bubbleId`, `serverBubbleId`, and
`createdAt` -- and agree on the other ninety-five, including the tool name,
arguments, result, and status.

The `createdAt` values are what identify the mechanism:

| Bubble | serverBubbleId | createdAt |
|---|---|---|
| `c3ccc7f1` | *(none)* | 2026-06-08T08:44:27Z |
| `c556845d` | `814e8729…` | 2026-06-29T08:00:10Z |
| `4d97c7a2` | `814e8729…` | 2026-06-29T08:00:19Z |
| …five more | `814e8729…` | 2026-06-29T08:00:33Z – 08:01:37Z |

One original from 8 June, seven copies written on 29 June seconds apart, all
sharing a single `serverBubbleId`. Across the composer, **28,704 bubbles carry a
`createdAt` of 2026-06-29** against a few hundred on each neighbouring day. That
is one bulk write by the vendor -- a sync, a migration, or a session replay --
not a decoder reading a record twice.

**The existing dedup already works.** Keyed on `(type, serverBubbleId)`, it
collapses the seven server copies to one; measured over all 4,053 groups, the
survivor count is exactly 2 in every case -- the one canonical server copy plus
the one locally-written bubble that has no server identity to be judged by. The
rule is doing what CoPlan describes; two genuine vendor records reach the store.

**Resolution: record the relationship rather than delete a record.** Since both
bubbles are real, dropping either loses evidence. Add an advisory field on the
later Event naming the earlier one -- a `duplicate_of` reference to the prior
Event's identity, with the evidence that justified it (`toolCallId` match, same
composer, later `createdAt`). Justification: this is the standard the rest of
the schema already uses -- a source status and a normalized outcome coexist, an
exact vendor value sits beside a mapped one -- and it keeps a query able to
exclude replays without the store having decided they never happened. Deleting
would also be unrecoverable, while an advisory reference can be ignored by a
reader who wants the raw record count.

**The duplication is circumstance-bound, and the circumstance is measurable.**
Across 145 composers holding tool calls:

| Composer shape | Count | Duplicated |
|---|---|---|
| No server-identified tool bubbles at all | 111 | **0** |
| Has server copies, spans under 3 days | 20 | 0 |
| Has server copies, spans 3-16 days | 14 | **10** |

Server copies are *necessary*: a composer whose tool bubbles are all
locally-written never duplicates, 111 of 111. They are not sufficient -- what
separates the 10 from the 24 is elapsed time. Duplicating composers span a
median of 4 distinct `createdAt` days (3 to 16); non-duplicating ones with
server copies have a median span of **0**, meaning every bubble was written the
same day.

It is not version-bound: `_v` is 3 on every bubble in every composer, duplicated
or not. And it is not type-bound: the copies carry the same `type` as their
original, which is why the `(type, serverBubbleId)` key collapses them
correctly.

So the shape is: **a long-lived composer is re-synced, and the re-sync writes
server-identified copies of bubbles that already exist locally.** The rate
follows how much of the composer predates the sync -- 0.74 and 0.62 in the two
largest, near zero elsewhere.

**What the replay is, and what it is not.** Three hypotheses tested against the
composer with 4,053 duplicate groups:

| Hypothesis | Test | Result |
|---|---|---|
| Context compaction triggered it | Are `conversationSummary` bubbles near the bulk day? | **No** -- this composer has none at all |
| A global migration | Do other composers share the bulk day? | **No** -- peak days are 2026-06-29, 2026-08-17, 2026-06-06, 2026-08-10, one per composer |
| A version change mid-session | Do field shapes differ across the boundary? | **Partly** -- five fields (`checkpointId`, `context`, `contextWindowStatusAtCreation`, `isPlanExecution`, `modelInfo`) appear only after the bulk write, though `_v` stays 3 throughout |

So it is per-session and coincides with a schema change, but the schema change
does not explain it: **none of the five new fields appears on any duplicated
tool bubble**, original or copy, in all 4,053 groups. The new shape arrived with
the write; the duplication is not the new shape being applied.

Two further regularities narrow it. Every group has **exactly seven** server
copies -- not a range, the same number 4,053 times -- and in every group those
seven carry **one** `serverBubbleId` between them. A constant seven is not what
a backfill writing each record once produces, and seven records under a single
server identity are treated as one by the existing dedup key. The actionable
guess is a retry or fan-out within one sync rather than seven separate writes;
what makes it actionable is that a harness experiment can reproduce a sync and
count the copies.

**What this does not settle**, and a harness experiment would: why the local
bubble carries no `serverBubbleId`, and what produces the seven. Both readings
of the local bubble -- an optimistic write later superseded, or a record
retained alongside the copies -- fit what is observed, and the advisory field is
correct under either, which is why it does not wait.

**Original measurement, for reference.****Original measurement, for reference.** Every result links to a
call -- **zero orphans across all three vendors** -- so the call/result count
difference is multiple results per call, not unmatched ones:

| Vendor | Results per call | Reading |
|---|---|---|
| Claude | strictly 1:1 across 3,232 | The vendor pairs them and the decoder preserves it |
| Codex | 25,033 single, 2,680 double, 4 higher | 1,075 calls have no result: a real vendor condition, since an aborted turn leaves a request unanswered |
| Cursor | 45,628 single, 7,248 double, 196 higher | Suspicious, and measurably so |

The Cursor duplicates are **byte-identical** -- same `source_status`,
`normalized_status`, and `output_text` -- and are concentrated: three stores hold
3,243, 3,051, and 111 duplicate groups while three comparable stores hold 0, 0,
and 2. That distribution does not follow from the decode path, which is the
same for every store, so it points at the source data rather than at the reader
-- which the field-by-field comparison above then confirmed.

**4. `toolFormerData` is the current shape, not a former one.** The name invites
reading it as superseded, which is what `cursor.tool-result-legacy` appears to
confirm. Measured over 6,000 bubbles: `toolFormerData` populated on 5,078,
`toolResults` populated on **zero** -- and `toolResults` is present but empty on
every single bubble. So the legacy rule matches a key that always exists and
never carries anything. `tool` inside `toolFormerData` is a numeric enum paired
with the `name` string (`5` beside `read_file`, `15` beside `run_terminal_cmd`),
which suggests "Former" names a UI component rather than a point in time.
Record what it is; do not rename around a guess.

**5a. Every populated field is reviewed, or its exclusion is recorded.** The
standing rule, stated here because the Cursor adapter is where it is currently
broken: a field the vendor populates is evidence, and dropping it needs a reason
someone wrote down. Acceptable reasons are narrow -- it duplicates a field
already carried, its values are inconsistent or malformed, it is unbounded
content the resource policy refuses, or it is an internal identity that means
nothing outside the vendor's process. "We did not get to it" is not one, because
a reader cannot tell that from a decision.

`adapters/cursor._MAPPED_BUBBLE_FIELDS` projects **10 of 98** bubble fields.
Measured over 20,000 bubbles, **34 populated fields are dropped with no recorded
reason**:

| Field | Bubbles | Sample value | Decision | Why |
|---|---|---|---|---|
| `thinking`, `thinkingStyle`, `thinkingDurationMs` | 891 | reasoning text plus a duration | **Map** | Codex's equivalent already maps to `message.reasoning_summary` and produces 4,343 Events. A reader comparing reasoning across vendors currently sees Cursor as having none, which is false |
| `turnDurationMs`, `timingInfo` | 1,651 / 685 | `7050`; four client timestamps | **Map** | The only measured durations Cursor records, and the store has nowhere else to get them. `timingInfo.clientStartTime` is already read for one purpose, so the shape is proven |
| `errorDetails` | 5 | `HTTP 504 [unavailable]` with request id and stack | **Map** | A recorded failure is exactly what a tool-result status should reflect, and five instances is enough to define the shape |
| `checkpointId`, `afterCheckpointId` | 2,717 / 1,364 | a UUID pair around an edit | **Map** | Bounds a change, which is Artifact-adjacent evidence; decide with the W73 Artifact-linkage group rather than separately |
| `codeBlocks` | 1,831 | file URI plus content | **Map** | Content beside `text` that the store currently loses; bounded by the content policy like any other body |
| `requestId`, `usageUuid` | 1,505 / 4,699 | a UUID, never both on one bubble | **Map both, separately** | Not one field under two names, which the first reading assumed. `requestId` appears only on `type=1` (user) bubbles and `usageUuid` only on `type=2` (assistant); no bubble carries both. They correlate: **664 of 1,505** user `requestId` values equal the `usageUuid` of an assistant bubble within the next five. So `requestId` identifies a request and `usageUuid` its response, which is a Model Turn edge -- Codex records the same relation explicitly as `turn_context.payload.turn_id`, and Claude through `parentUuid` lineage. Mapping them to one column would erase the direction |
| `lastTerminalCwd` | 510 | an absolute path | **Map** | Names where a command ran, which is Artifact evidence and currently absent |
| `symbolLinks`, `fileLinks` | 443 / 209 | JSON strings naming a symbol or file | **Map** | Explicit references to Artifacts, which the schema has a place for |
| `todos` | 10 | JSON strings of task text | **Map** | Small, structured, and content a reader would search for |
| `context` | 1,184 | nested containers, mostly empty | **Map the populated leaves** | Nine leaves do carry values: `terminalFiles` (153), `fileSelections` (20), `externalLinks` (5), `composers` (36), `selections`, `selectedImages`, `terminalSelections`. Those are Artifact and context references the store has a place for. The outer container is mostly empty; the leaves are not |
| `webCitations` | 4 | `{"title": …, "url": "https://github.com/…"}` | **Map**; policy is W79 | Title and URL, which is exactly an Artifact. Four instances define the shape completely. It is the first field carrying a URL and a label a model retrieved rather than a person typed, so escaping, redaction, and the no-fetch boundary are decided by W79 rather than here |
| `tokenCount` | 19,999 | `{"inputTokens": 0, "outputTokens": 0}` | **Retain always** | Non-zero on 627 of 30,000. Retained regardless: an explicitly recorded zero is evidence the vendor reported no usage, which is not the same as the field being absent, and the distinction is exactly what a usage question needs. Applied to all three vendors, not only Cursor |
| `conversationState` | 21,606 | base64, decodes to binary | **Record presence, size, digest** | Median length **1** and 95th percentile 1 -- almost every instance is a single character -- with a maximum of 57,101 and 21 MB total. Retaining the bytes stores an undecodable blob; retaining nothing loses the observation that it exists and how large it is. Presence, byte length, and a digest are queryable and bounded |
| `capabilityType`, `capabilityStatuses` | 11,454 / 8,457 | `15`; nine phase names, all empty | **Record presence, document vocabulary** | The vocabulary is in CursorSchema. The values are numeric enums with no published meaning, so decoding them would be a guess; recording that they were present with which values is not |
| `richText` | 1,184 | Lexical editor JSON | **Map its `mention` nodes only** | Extracted text matches `text` once newlines are accounted for -- the 241 apparent differences were all line breaks. But the node types include `mention` (6 instances) alongside `text`, `linebreak`, `tab`, and a mention is a reference `text` cannot carry. Map the mentions, not the second copy of the prose |
| `unifiedMode`, `isAgentic`, `supportedTools`, `editToolSupportsSearchAndReplace`, `isNudge`, `isPlanExecution` | 677-19,999 | `2`; `true`; `[1, 3, 5, …]` | **Record, do not interpret** | `unifiedMode` is `2` on 29,994 of 30,000 and `1` on five, so it is near-constant; `supportedTools` is a numeric enum list with no published meaning. Recording the value costs a column and preserves the observation; interpreting it would be invention. This is a *storage* decision, not a judgement that configuration is uninteresting |
| `_v`, `bubbleId` | 19,999 | `3`; a UUID | **Already carried** | `bubbleId` is the source locator and `_v` the record version; both are retained as source evidence today. Nothing to add |
| `existedPreviousTerminalCommand`, `existedSubsequentTerminalCommand` | 6 / 1 | `true` | **Record** | Booleans naming whether a terminal command bracketed this bubble. Cheap to carry and directly relevant to tool context |
| `serviceStatusUpdate`, `statusUpdates`, `skipRendering` | 1 / 4 / 10 | a UI message; `{}`; `false` | **Record presence only** | `serviceStatusUpdate` is a product notice addressed to the operator rather than evidence about the work; `statusUpdates` holds `{}` wherever it appears; `skipRendering` is `false` on all ten. Presence is the finding |
| `promptDryRunInfo`, `attachedFileCodeChunksMetadataOnly` | 32 / 498 | UI tooltips; chunk metadata | **Record presence and size** | Context-assembly detail rather than the assembled context. Presence and size say whether a bubble had context trimmed |

**The retrieved-content fields raise a policy question, and it is W79's.**
`webCitations`, `context.externalLinks`, and any `mention` resolving to a URL
carry text and locations a model fetched from the open web, which the content
policy does not currently distinguish from locally-authored text. Mapping them
is in scope here; deciding how a retrieved reference is escaped, redacted, and
documented is not, and waiting on that decision would hold the other 33 fields.

**How the decisions were made, revised.** The first pass excluded eleven groups
and three of those exclusions were wrong on the evidence:

- *`context` is not empty.* Nine leaves carry values, including `terminalFiles`
  on 153 bubbles and `fileSelections` on 20. Walking the structure rather than
  reading the top level found them.
- *`richText` is not purely a re-encoding.* Its extracted text does match `text`
  -- the 241 apparent differences were line breaks my extraction dropped -- but
  it also carries `mention` nodes, which `text` cannot represent.
- *`webCitations` is a URL and a title*, which is an Artifact regardless of
  appearing four times.

**The standing preference is to decode what we can and retain the rest**, so an
exclusion now needs one of three specific grounds:

| Ground | Fields | Treatment |
|---|---|---|
| Undecodable without the vendor's encoding | `conversationState` | Presence, byte length, digest -- not the bytes |
| A numeric enum with no published meaning | `capabilityType`, `supportedTools`, `unifiedMode` | Record the value, do not interpret it |
| Already carried under another name | `_v`, `bubbleId`, `richText` prose | Nothing to add |

Nothing is dropped for being small, near-constant, or uninteresting. Four
instances of `webCitations` and one of `existedSubsequentTerminalCommand` are
retained on the same footing as fields appearing twenty thousand times, because
a count bounds how much a field contributes and not whether it is evidence.

**`tokenCount` is retained always, for every vendor.** A recorded zero and an
absent field are different observations, and only the first says the vendor
reported no usage. CoSchema already distinguishes absent from null from empty
through `field_state`; storing the zero is what lets that distinction reach a
usage query. This supersedes the earlier reading that a mostly-zero field would
mislead -- it would only mislead if the store failed to say it was recorded as
zero.

**5b. The Cursor bubble carries 98 fields**5b. The Cursor bubble carries 98 fields and about 40 are never populated.**
Sampled over 20,000 bubbles from the live global store. Present on essentially
every bubble and non-empty on none: `lints`, `commits`, `pullRequests`,
`gitDiffs`, `images`, `attachedFolders`, `interpreterResults`, `notepads`,
`capabilities`, `consoleLogs`, `knowledgeItems`, `webReferences`,
`aiWebSearchResults`, and roughly thirty more. `toolResults` is one of these.

Populated and **not currently read** -- the list worth reviewing before anything
else here:

| Field | Bubbles | What it holds |
|---|---|---|
| `tokenCount` | 19,999 | Present on every bubble |
| `conversationState` | 11,606 | An opaque base64 blob |
| `capabilityType` | 11,454 | A per-bubble capability designator |
| `usageUuid` | 4,699 | A usage identifier |
| `checkpointId` / `afterCheckpointId` | 2,717 / 1,364 | Checkpoint identities around an edit |
| `thinking` / `thinkingStyle` / `thinkingDurationMs` | 891 | Reasoning text and its duration |
| `timingInfo` | 685 | Four client timestamps per turn |
| `turnDurationMs` | 1,651 of 60,000 | The measured duration of one turn |
| `errorDetails` | 5 | A real failure: `HTTP 504 [unavailable]` with request id and stack |

`thinking` is the sharpest of these: Codex maps its reasoning summary to
`message.reasoning_summary` and produces 4,343 such Events, while Cursor's
equivalent is present and unread.

**6. `statusUpdates`, `skipRendering`, and `capabilityStatuses` explain the
lifecycle absence.** All three exist and none carries a boundary:
`statusUpdates` holds `{}` where present (4 bubbles), `skipRendering` is `false`
on all 10, and `capabilityStatuses` is the interesting one -- it names nine
phases including `start-submit-chat`, `chat-stream-finished`, and
`composer-done`, and **every phase list is empty on all 8,457 bubbles that
carry it**. Cursor declares a lifecycle vocabulary and records no instances of
it.

**7. A task boundary is derivable from bubble type, and worth proposing.**
Within a composer the sequence is `type=1` (user) followed by one or more
`type=2` (assistant, some carrying `toolFormerData`). Measured over 60,000
bubbles: 2,823 type-1 against 57,175 type-2, so a type-1 bubble is a turn start
and the following run is its response. `turnDurationMs` on 1,651 bubbles and
`timingInfo` on 685 give a measured duration for part of that run.

This is a derivation rather than vendor evidence, so it must be recorded as
one: an Interaction boundary from sequence carries a different warrant than
Codex's `task_started` record, and CoPlan's rule against inferring relationships
from adjacency applies. Proposing it as an explicit `event_at_basis`-style
derivation, visible as derived, is the honest form.

**Status of each finding.** All seven are diagnosed; **none has changed code.**
Stated because a diagnosed finding reads like a fixed one in a document that
only describes it:

| # | Finding | State | Next action |
|---|---|---|---|
| 1 | Session times extracted and dropped | Diagnosed | Map `created_at`/`last_updated_at` onto Session start/end |
| 2 | No task lifecycle in Cursor | **Settled** -- recorded in CursorSchema | Close the W73 row as declined |
| 3 | Duplicate results are real vendor records | **Detection landed**; the advisory field is not built | `adapters/cursor._count_surviving_repeats` reports `repeated_tool_calls` per Source, so a re-synced Session is now visible. Add the `duplicate_of` reference next, which needs a column and so batches with a rebuild |
| 4 | `toolFormerData` is current, not former | **Settled** -- recorded in CursorSchema | None |
| 5a | 34 populated fields dropped unreviewed | Diagnosed | One recorded decision per field |
| 5b | ~40 fields never populated | **Settled** -- policy recorded | Record as measured-empty in the audit |
| 6 | Capability vocabulary declared, never filled | **Settled** -- recorded in CursorSchema | Consider a matching enum when a release populates it |
| 7 | Task boundary derivable from bubble type | Diagnosed | Decide whether a derived Interaction boundary is admitted |
| 8 | Role/actor disagreement measured, unguarded | Diagnosed | Diagnose a fifth combination; the four observed are the baseline |

**"Settled" means documented and no code follows** -- the finding is a vendor
fact, it is written where a reader will meet it, and nothing further is
outstanding. It does not mean a resolution was chosen and deferred. Where a
resolution *is* chosen but unbuilt, the row says Diagnosed and names the next
action, so the two states are distinguishable.

By that reading: 2, 4, and 6 are closed. 1, 3, 5a, and 7 are open, and two of
them (1 and 3) add columns or values to the store, so they batch with a rebuild
rather than landing alone.

**Retestable now, and how.** Each open finding has a check that already runs, so
a fix is verifiable rather than asserted:

| # | Retest |
|---|---|
| 1 | `SELECT count(*) FROM sessions WHERE started_at IS NULL` on a Cursor store -- currently every row; zero after the mapping |
| 3 | The duplicate-group count per invocation, which is 2 in all 4,053 groups today and stays 2 with a `duplicate_of` reference recorded on the later one |
| 5a | The projected-field count against the populated-field count: 10 of 98 projected, 34 populated and unprojected, both re-derivable from the live store |
| 7 | The type-1 count per composer against the Interaction count, which should agree once a boundary is derived |

**8. Warn on an unobserved role/actor combination.** Comparing the vendor
`role` against the classified `actor_kind` over the current-format stores gives
four combinations that disagree, and all four are expected: `user`/`tool` on
26,933 Codex and 3,232 Claude Events, `user`/`harness` on 229, and
`assistant`/`harness` on 68. Nearly a third of the Codex store carries a `user`
envelope around content no human wrote.

A fifth combination would mean the classifier reached a shape no vendor has been
observed to produce -- a vendor change or a decode fault, both findings. Emit a
record-level diagnostic rather than accepting it silently. The measured set
above is the baseline the check compares against, and it is in CoPlan beside the
per-vendor request/response evidence.

**Evidence to close.** Cursor Sessions carry times where the header supplies
them; the Cursor lifecycle row in W73 is closed as declined for task records and
reopened as a derivation question; duplicate results carry a `duplicate_of`
reference; the 34 unread populated fields each have a decision recorded.

**A policy question these raise: what to do with a field that is always
declared and never filled.** Roughly forty Cursor bubble fields, `toolResults`
among them, are present on every record and empty on every one measured. Three
treatments, and the choice should be stated once rather than per field:

| Treatment | Cost | When it is right |
|---|---|---|
| Ignore silently | Nothing | Never -- it is indistinguishable from not having looked |
| Record as measured-empty in the audit | One count per field | Default: `vendor_audits.cursor_features` already inventories shapes, and "present on 20,000, empty on 20,000" is a finding a later release can contradict |
| Declare a mapping rule | A released rule that never fires | Only where a store written earlier still carries data, which is why `cursor.tool-result-legacy` stays |

The distinction that matters is between *the vendor stopped writing this* and
*we never checked*. An always-empty field recorded with its sample size is the
first; an absent one is the second, and only the first can be revisited when a
vendor release changes.

**Aborted turns beyond Codex.** Codex records `event_msg.turn_aborted` and
produces 68 `lifecycle.abort` Events. Claude produces none and has no abort
rule; Cursor produces none. Whether either records an abort under another shape
is unestablished; W75 carries the conditions that would settle it.

**Cost.** Small each. Finding 1 is a mapping addition, 3 is a decode defect with
a proposed rule, 2 and 4 are documentation, 5 and 7 are decisions, 6 is a
recorded vendor fact.

### W75 -- Harness Experiments for Unrecorded Conditions

**Status: Postponed.** Designed and not run. The design is recorded because it
is the part that decays -- which condition answers which question, and what
counts as an answer -- while the running is an afternoon whenever a dependent
item needs one.

**Work.** Reproduce named conditions against live harnesses and record what
each writes. Stored data contains only what was written, so a question about a
condition nobody has triggered cannot be answered by reading more of it. The
valuable outcome is frequently negative: *triggered and absent* closes a
question permanently, and is the finding inspection cannot produce.

**Why one item.** Six open questions across W73, W74, and W55 reduce to "does
the vendor record this". Each is cheap alone and they share one harness, so
running them together costs little more than running any one.

#### W75.1 Goal and Deliverable

The goal is not a document; it is a decision unblocked. Each condition below
names the item waiting on it, and closes by producing one row:

| Deliverable | Form |
|---|---|
| Observation record | Condition, vendor, harness version, what was triggered, which fields changed, and their values -- including the fields that did **not** change |
| Disposition | For the item waiting: *map it*, *record presence only*, or *declined, no source evidence* |
| Fixture | Where a shape is new, a redacted vendor record added to `schema/coschema/fixtures/` |

An observation that records only populated fields is half an answer. The
absent field is what closes a gap as declined.

#### W75.2 Machine Part

Scriptable end to end, with no operator present. All three harnesses expose a
non-interactive mode: `claude -p`, `codex exec`, and `cursor-agent -p`
(reachable also as `cursor agent`). Each run uses a fresh Project directory so
the vendor writes are isolated, then scans, ingests, and reads the named
fields.

| Condition | Vendor | Question | Feeds |
|---|---|---|---|
| Abort a turn mid-stream | Codex | Is `turn_aborted` the only abort evidence, and is a partial result written? | W73 duplicate-envelope |
| Abort a turn mid-stream | Claude | 1,058 `lifecycle.vendor` Events carry no abort kind -- is one produced? | W73 lifecycle |
| Force a tool failure | Cursor | Does `errorDetails` populate beyond the five observed, and does `toolFormerData.status` distinguish it? | W74.5a |
| Run a turn with no tool call | Cursor | Is a local bubble still written without a `serverBubbleId`? | W74.3 |
| Leave a composer idle across a session boundary | Cursor | Does `last_updated_at` advance with no new bubbles? | W74.1 |
| Run one turn through the terminal agent | Cursor | Does `~/.cursor/chats` gain a store, and do its fields match the GUI store's? | W76 |

The last is new and belongs to the machine part precisely because
`cursor-agent` is scriptable: it is how W76's decoder gets a fixture whose
provenance is known.

**Steps, once per condition.** Create the scratch Project; run the harness
non-interactively; trigger the condition (for an abort, terminate the process
mid-stream); `codess scan` and `codess ingest --dir`; read the named vendor
fields directly from the vendor store; record populated *and* absent.

#### W75.3 Human Part

Two conditions need a person because the trigger is a GUI affordance with no
command equivalent. They are segregated here so that no one waits on a machine
run to produce them, and so a session that has an operator present knows
exactly what to do while they are there.

| Condition | Steps | Record | Feeds |
|---|---|---|---|
| Deny a tool permission | Open the Project in Cursor; issue a prompt that requires a tool needing approval; when the dialog appears, choose **deny**; end the turn | `toolFormerData.userDecision` value, and whether any `capabilityStatuses` phase fired alongside it | W74.6 |
| Interrupt a turn mid-stream | Open the Project in Cursor; issue a prompt producing a long response; press stop while output is streaming | Whether `capabilityStatuses` gains entries, whether `statusUpdates` becomes non-empty, and whether the partial text is retained | W74.6, lifecycle vocabulary |

**Before the operator starts**, capture the composer's current bubble count and
header `lastUpdatedAt`; **after**, re-read both. Without the before-value a
changed field cannot be attributed to the condition.

**Whether the human part is needed at all is itself a question.** If the
terminal agent records a denied permission the same way the GUI does, the
machine part covers it and these two conditions close without an operator.
Establish that first: it is one scripted run, and it may retire this section.

#### W75.4 Cross-Reference

What each waiting item gets, and why it cannot get it by reading:

| Item | Needs | Why inspection fails |
|---|---|---|
| W73 lifecycle | Whether Codex and Claude emit an abort kind | No stored Session on the machine was aborted |
| W74.1 | Whether `last_updated_at` advances without bubbles | Requires a controlled idle interval |
| W74.3 | Whether a no-tool turn writes a local-only bubble | The 4,053 observed groups are all tool bubbles |
| W74.5a | The `errorDetails` shape beyond one cause | Five samples, all `HTTP 504` |
| W74.6 | Whether a permission phase fires | `capabilityStatuses` is present but empty in stored data |
| W76 | A fixture with known provenance | The seven stores are all one model, one month |

W55's seconds-scale question has left this item: CoSchema already defines the
unit, so a decoder disagreeing with it was a conformance defect rather than an
open question. It is fixed, and W77 owns the consolidation.

#### W75.5 Restart Criteria

Reopen when any one becomes true, not on a schedule:

1. **A W74.5a mapping decision is observed to be wrong.** Specifically: a
   `normalized_status` derived from `toolFormerData.status` disagrees with a
   retained `errorDetails` on real data. Checkable by query. Until then both
   are mapped and retained, which is correct under either answer -- the same
   argument W74.3 makes for `duplicate_of`.
2. **W73's lifecycle or duplicate-envelope group reaches a decision** that
   needs abort evidence.
3. **W76's decoder needs a fixture** whose provenance is known rather than
   inferred from seven same-version stores.
4. **An operator is working in Cursor anyway** and can trigger W75.3 at near-zero
   marginal cost.

**Cost.** One session per harness for the machine part; minutes of operator
time for the human part, if it survives criterion in W75.3. No code change; the
output is evidence that unblocks decisions in four other items.

### W76 -- The Cursor Terminal-Agent Storage

**Status: Postponed.** The store that was decoded is obsolete. What replaced it
is identified but not characterised, and characterising it is the work.

**What was decoded, and why it is set aside.** `~/.cursor/chats/<workspace-hash>/
<agent-uuid>/store.db` holds complete terminal-agent Sessions: a `meta` row of
hex-encoded JSON carrying `agentId`, `name`, `mode`, `lastUsedModel`, and a
`createdAt` in epoch milliseconds, plus a content-addressed `blobs` table whose
protobuf messages yield `role`, typed `content[]` parts, and tool calls.
Measured: 7 stores, 1,870 blobs, 236 messages, 219 `tool-call`, 126 `text`, 123
`reasoning`.

It is **not a current format**. Every store dates from 9-12 August 2025, every
one records `gpt-5`, and no file anywhere under `chats/` has been written since.
The directory itself has not been touched since August 2025 while its siblings
have. Decoding it would spend adapter work on Sessions no current Cursor
release produces.

**Where the terminal agent writes now.** `~/.cursor/projects/<project-slug>/`,
last written 18 August 2026, holding five subtrees:

| Subtree | Apparent content |
|---|---|
| `agent-transcripts/<uuid>/` | Per-Session transcript directories |
| `agent-tools/<uuid>.txt` | Per-invocation tool output as plain text |
| `terminals/` | Terminal session records |
| `canvases/` | Generated `.canvas.tsx` artifacts |
| `mcps/` | MCP server records |

CursorSchema already names this tree as outside the SQLite pipeline. That note
predates the observation that it is now the *only* place terminal-agent
Sessions land.

**The vendor is pruning it.** `~/.cursor/projects/` carries
`.agent-data-cleanup-2026-08-<dd>` markers for eleven consecutive recent days,
so this storage is actively expired by Cursor rather than retained
indefinitely. That is a decode consideration and a Codess capability argument
at once: evidence Codess does not ingest promptly may not survive, which is
the opposite of the GUI store's behaviour and worth stating before any adapter
is written.

**Work, when it restarts.** Characterise the `projects/` tree the way the two
vendor stores were characterised: which files carry Session identity, message
sequence, tool evidence, and time; whether a transcript is self-describing or
needs the workspace store to interpret; what the cleanup markers actually
remove. Then decide whether it is a third Cursor Source or an extension of the
existing one.

#### Preserving It Before Expiry

**What the markers say, and what they do not.** `.agent-data-cleanup-<date>`
files are zero bytes; the name is the entire content and the mtime is the day
before the date carried. They record that a sweep ran, not what it removed, so
nothing on disk states which Sessions were deleted or on what rule.

**The window is wide enough that this is not urgent.** Across 609 files in 53
project directories: 196 under a week old, 185 one to four weeks, 112 one to
three months, 116 older than three months, oldest roughly six months. A sweep
that leaves six-month-old files is periodic, not aggressive.

**Archiving the whole tree is cheap.** 89 MiB total -- `agent-tools` 56 MiB,
`agent-transcripts` 30 MiB, `terminals` 1.8 MiB, `canvases` 996 KiB, `mcps`
924 KiB. That is under 4% of the 2,333 MiB the published stores already
occupy, so a copy costs less than one Project's store set.

**Preservation is not ingestion, and separating them is the point.** A copy
made before a decoder exists is only useful if it is faithful and dated: the
raw-evidence path already does exactly this, with content-addressed objects,
recorded observation time, and a manifest. Preferred order:

1. **Copy first, decode later.** Use the existing raw capture rather than
   inventing a second archival mechanism -- the observation record is what
   makes a later decode auditable, and a hand-made copy has no provenance.
2. **Record the sweep boundary.** Retain the marker names alongside the copy;
   they are the only evidence of when the vendor pruned, and a gap in a
   transcript sequence is otherwise unexplainable.
3. **Do not treat a copy as a Source.** An archived tree ingested as if it were
   live would attribute vendor-deleted Sessions to the present, which is the
   opposite of what the raw path is for.

Archiving does not need this item to be started, and is the one part of it
worth doing before the tree is characterised.

#### Vendor Scale and Format, Into One Searchable Representation

The reason the designator table matters is that a query must not need to know
which Cursor storage a Session came from. CoSchema's existing convention
answers this and no new mechanism is required: **a normalized column carries
the common value, a paired `source_*` column carries what the vendor said, and
`metadata` JSON carries the rest.** Applied to the two Cursor formats:

| Vendor field | Format and scale | Common representation | Why that column |
|---|---|---|---|
| `createdAt` (chats), `createdAt` (bubbles) | Epoch ms, and ISO-8601 text on bubbles | `events.event_at` `REAL` ms via `units.epoch_milliseconds` | The store fixes the unit; the normalizer is the only place scale is decided |
| `createdAt`/`lastUpdatedAt` (headers) | Epoch ms | `sessions.started_at`/`ended_at`, `time_basis='session'` | A header-stated span must stay distinguishable from an Event-derived one |
| `agentId` / `composerId` | UUID / opaque id | `sessions.id`, plus `session_entity_id` derived | One identity column; the vendor spelling is a Source fact, not a query key |
| `toolName` string / `toolFormerData.tool` numeric enum + `name` | String vs integer enum | `tool_invocations.tool_name` normalized; the integer retained in `metadata` | A numeric enum with no published meaning is recorded, not interpreted |
| `role` + `content[].type` / integer `type` | Typed parts vs `1`=user `2`=assistant | `events.actor_kind`, `content_role`, `event_kind` | The vocabularies already exist; the integer is a source value |
| `toolFormerData.status` / `errorDetails` | Vendor strings | `source_status` verbatim, `normalized_status` derived | The pairing the schema already uses everywhere |
| `lastUsedModel` / per-bubble `modelInfo` | Session-level vs Event-level | `model_name_exact` verbatim, parts derived where resolvable | An unrecognized name leaves derived values null rather than guessed |
| blob SHA-256 / `bubbleId` UUID | Content address vs assigned id | `source_record_locator` | Both are locators into vendor storage; neither is a common identity |

**What this buys.** A `--tool-name Read` or `--since` query spans both formats
without naming either, because the common columns hold comparable values and
the scale question was answered once. What it does not do is erase the
difference: `source_record_type`, `source_status`, and `metadata` still state
which format a row came from, so a result can say what it is resting on.

**Where the model is recorded differs by format, and the schema already has
the answer.** See [Session and Event Model Evidence](#session-and-event-model-evidence)
below: `chats` states one model per Session, bubbles state one per Event, and
CoSchema carries both levels rather than choosing. The chat store's
`lastUsedModel` becomes `sessions.session_model_param_id`; per-bubble
`modelInfo` stays on the Model Turn.

**Restart criteria.** Any one:

1. A terminal-agent Session is observed under `~/.cursor/projects/` for a
   Project already ingested, so a comparison against the GUI store is possible.
2. Cursor reasoning evidence is wanted and the GUI `thinking` mapping in W74.5a
   proves insufficient.
3. The cleanup markers are shown to remove evidence a reader needed, which
   makes prompt ingestion a requirement rather than a convenience.

**What the obsolete store still establishes**, and the reason this item retains
it rather than deleting the measurement:

- Cursor has recorded terminal-agent Sessions in a form entirely unlike the GUI
  store, so a second Cursor format is a demonstrated pattern rather than a
  hypothetical.
- Its designators shared almost nothing with `state.vscdb`: `agentId` against
  `composerId`, a `toolName` string against a `toolFormerData.tool` numeric
  enum, `role` plus typed `content[]` against an integer `type`, and no
  `serverBubbleId` at all. Only `createdAt` in epoch milliseconds agreed. A
  successor format should be read on its own terms rather than by assuming the
  GUI vocabulary carries across.
- A read-only URI open (`file:<path>?mode=ro`) failed against these files at
  three separate locations while a plain path open succeeded, and the trigger
  was never identified. Recorded in CursorSchema, because a store that cannot
  be opened is indistinguishable from a Source that is absent.

### W79 -- Retrieved References Are Attacker-Influenced

**Status: Postponed.** Lifted out of the Cursor field mapping so that mapping
can land without waiting on a policy question, and because the corpus that
would validate a policy does not exist yet: four instances.

**Work.** State, and enforce, how Codess treats an Artifact reference a model
retrieved rather than a person typed.

**The distinction the content policy does not yet make.** Everything the policy
bounds today was authored locally -- a file path, a command, a message. Cursor's
`webCitations` (4 instances), `context.externalLinks` (5), and `richText`
`mention` nodes resolving to a URL carry a title and a location fetched from the
open web. Three consequences:

- *A title is untrusted text.* `sanitize` strips control characters and ANSI,
  which covers a terminal. Markup or a prompt-injection payload reaching a
  downstream consumer is not covered.
- *A URL is not evidence it is safe to visit.* Codess does not fetch and must
  not start. Storing the string is right; a consumer that follows one is making
  its own decision, and that boundary should be documented where the field is
  rather than assumed.
- *A URL can carry a secret.* A query string with a token is what `redact`
  exists for, and the redaction patterns should be checked against URL shapes
  rather than assumed to cover them.

**Not a reason to drop the field.** A retrieved reference is real evidence about
what informed a response. The resolution is to route these through the content
policy on the same terms as message text, and to record in CoSchema that an
Artifact URI from a retrieval is attacker-influenced where one from a file path
is not.

**Restart criteria.** Any one:

1. A corpus carries enough retrieved references to characterise the shapes --
   nine instances across three fields cannot establish what a title may contain.
2. A consumer exists that renders Artifact titles or follows Artifact URIs,
   which is what makes the escaping question concrete rather than theoretical.
3. Redaction is audited against URL shapes and found not to cover a token in a
   query string.

**Cost.** A policy decision plus its enforcement, both small. The reason it is
not done now is that the evidence to decide it well is four records.

### W80 -- The Cursor Model Is Recorded, and Mostly Not Read

**Work.** Resolve a Cursor Session's model from `composerData.modelConfig` for
every composer, not only for the composers that have a header row.

**The defect.** `session_model_param_id` is filled from header metadata, and
headers exist for **66** composers while `composerData:` rows exist for
**159**. Measured over those 159, `modelConfig` is present on every one and
`modelName` states a real model on **134**:

| Value | Composers |
|---|---|
| `composer-1.5` | 56 |
| `default` | 25 |
| `composer-2` | 15 |
| `composer-2.5` | 13 |
| `composer-2-fast` | 12 |
| `composer-1` | 11 |
| `grok-4.5` | 8 |
| `cursor-grok-4.5-high-fast` | 6 |
| `composer-2.5-fast` | 5 |
| `grok-4.6` | 4 |
| `claude-4.6-sonnet-medium-thinking` | 3 |
| `claude-4.6-opus-high-thinking` | 1 |

`default` is the absence of a choice rather than a model named "default", and
`store` already refuses it -- that rule stands. The other 134 are exact model
names Codess is not reading.

**`selectedModels` is a second shape on 37 composers**, carrying
`{"modelId": "composer-2.5", "parameters": [{"id": "fast", "value": "true"}]}`.
That names a model *and* a speed parameter, which is `speed_tier` evidence the
name alone does not always carry.

**What the timeline shows, and what it cannot.** 44 of 86 ingested Cursor
Sessions carry no model. Grouped by start day, **37 of the 44 fall on a single
day, 2026-02-25**, against one or two on every other day. The no-model Sessions
have a median of 43 Events against 129 for the rest and a median span of 0.4
minutes against 1.2, so they are smaller and shorter but not empty -- none has
zero Events. A 37-on-one-day concentration against a flat background is a bulk
write, matching the replay mechanism already recorded for tool bubbles, rather
than a property of short Sessions.

**Version cannot be ruled in or out from the store**, and reading `release` as
evidence would be a mistake this item should not repeat. Every Cursor Session
reports `3.16.17` because Cursor writes one current client version for the
whole store and `get_client_version` attests the version *observed at read
time*, not the version a Session ran under -- the function says so. So a
uniform `release` across Sessions spanning February to August is an artifact of
how the value is obtained, not a finding. Establishing whether the 2026-02-25
Sessions were written by a different release needs vendor-side evidence the
store does not carry.

**Closed, and the fix found a larger defect than the one it was filed for.**
`_composer_settings` was called with `set(headers)`, so settings were read only
for composers `composerHeaders` lists. The header table is the *smallest* of
three indexes Cursor keeps: 66 headers against 166 global `composerData:` rows,
and **107 composers hold bubbles with no header at all**, carrying 75,473
bubbles between them. The workspace `composer.composerData` fallback already
recovered 75 of those; the remaining 32 were reachable from no index Codess
read.

`_headerless_composers` now recovers a composer from its global `composerData:`
row. Measured after the change, `get_composer_headers` returns **164 composers
against 66**, and **134 carry a model** where 32 did.

**A recovered composer is not attributed to a Project, and must not be.** A
`composerData:` row states no `workspaceId`, and checking all 98 for any
workspace, folder, cwd, or root-path field found **none** -- one carries context
file references, which is not a binding. Ingest selects composers by workspace,
so recovery is applied only when the caller asks for every composer and is
skipped under a workspace filter; admitting an unbound composer there would
widen the selection silently and attribute a Session to a Project on no
evidence. That boundary is the reason ingested Session counts did not move:
what improved is the evidence carried by the Sessions that *are* bound, and
Cursor Event volume rose from 135,327 to 156,138 on reingest.

**What remains open, as its own question rather than as this item.** 98
composers hold decodable bubbles that no Project can claim. Attributing them
needs an identity source that does not exist in the global store -- a workspace
index that lists them, or vendor evidence binding a composer to a folder. Until
one is found the honest state is that they are visible and unattributed, which
is what `selection_source` records.

**`selectedModels` remains unmapped.** 37 composers carry
`{"modelId": ..., "parameters": [{"id": "fast", "value": "true"}]}`, which names
a speed parameter the model name does not always carry. It belongs with
`speed_tier` and is small; it did not land here because the model-name path was
the defect and this is an addition.

### W81 -- Cursor Artifact Evidence in Adjacent Key Spaces

**Work.** Decide, per key space, whether Cursor's file-change records become
Artifact evidence.

**What is there.** `cursorDiskKV` holds 444,476 rows and Codess reads two key
spaces (`bubbleId:`, `composerData:`). The unread ones carry file evidence:

| Key space | Rows | Holds | First reading |
|---|---|---|---|
| `agentKv:blob:` | 209,951 | **A second complete message corpus** -- see below | 77,721 message-shaped blobs |
| `checkpointId:` | 7,718 | `files`, `activeInlineDiffs`, `newlyCreatedFolders`, `nonExistentFiles` | Names files per checkpoint: 1,321 file references in a 500-row sample |
| `codeBlockDiff:` | 1,417 | `newModelDiffWrtV0`, `originalModelDiffWrtV0` | A diff pair per code block |
| `ofsContent:` | 789 | File content keyed by composer and `file://` URI | **586 distinct file URIs**; the key alone is an Artifact reference |
| `messageRequestContext:` | 678 | Harness context per message request | Already documented as separate; not decoded |
| `inlineDiff:` | 545 | Inline diff state | -- |
| `patch-graph:` | 354 | `fileUri`, `patches`, `provenance`, `version` | **162 distinct file URIs**, with `provenance.spans` naming an owner per span |

#### What `agentKv` Actually Holds

Every key is `agentKv:blob:<sha256>`, content-addressed like the terminal-agent
store. Of the rows examined, **77,721 are complete conversation messages** in a
shape the bubble tables do not use:

```json
{"id": "...", "role": "assistant", "content": [{"type": "tool-call", ...}],
 "providerOptions": {"cursor": {"requestId": "6c743a9e-..."}}}
```

| Measure | Value |
|---|---|
| Roles | `tool` 47,372, `assistant` 26,072, `user` 4,254, **`system` 23** |
| Content part types | `tool-call` 47,672, `tool-result` 47,372, `text` 26,541, `reasoning` 4,733, `redacted-reasoning` 3,736 |
| Distinct `requestId` values | 3,762, of which **2,740 also appear on bubbles** |

**Three things here exist nowhere else in what Codess decodes.**

1. **The system prompt.** The 23 `system` messages carry the harness prompt
   itself (`"You are an AI coding assistant, powered by Composer..."`). No
   other Cursor structure records it, and it is the evidence that says what the
   model was instructed to do.
2. **`redacted-reasoning` as a content type**, 3,736 instances. The bubble
   `thinking.redactedThinking` flag says reasoning was withheld; this says so as
   a first-class content part.
3. **`tool-result` beside `tool-call` in one message stream.** The bubble format
   splits these across records joined by `toolCallId`; here they are sequential
   parts of one conversation.

**It joins to what is already decoded.** 2,740 of 3,762 `requestId` values
appear on bubbles Codess already reads, so these messages attach to known
Sessions rather than forming an unattributable pool. The 1,022 that do not are
the interesting remainder: either Sessions whose bubbles were pruned, or
requests that never produced one.

**Recommended handling, and the reason for each part.**

| Part | Treatment | Why |
|---|---|---|
| `system` messages | **Map**, as `message.context` with `origin_kind` harness-injected | Small, bounded, and the only record of the instruction the model received |
| `reasoning` / `redacted-reasoning` | **Map** alongside the bubble reasoning already decoded | Same evidence class, and the redaction flag is a distinct fact from absence |
| `tool-call` / `tool-result` | **Do not map as new Events; use to verify** | The bubbles already produce these Events, and mapping both would double-count every tool interaction. The value is as a cross-check on pairing, which is a decode-audit question rather than a store one |
| `user` / `assistant` text | **Do not map** | Duplicates bubble text for the 2,740 joinable requests; retaining both would double the searchable corpus for no new evidence |
| Binary blobs | **Record presence and size only** | Leading bytes are `0a...`, so protobuf, but the schema is unpublished. Decoding it would be a guess, and the bodies are unbounded content the resource policy governs |

**The rule this follows** is the one already applied to `toolResults` and
`conversationState`: a duplicate of something already carried is not evidence,
and an undecodable blob is recorded by presence rather than retained whole. What
makes `system` and the reasoning parts different is that nothing else carries
them.

**Bounded, not exempt.** At a median 879 bytes and a maximum of 11 MB, these
blobs are unbounded content and belong under the same resource policy as
message text.

**`patch-graph` provenance is the notable one.** Each meta row carries spans of
the form `{"start": 1, "end": 19, "owner": "<uuid>"}`, so the vendor records
*which agent turn owns which line range of a file*. Nothing in CoSchema
currently carries per-span authorship, and it is exactly the evidence an
"what did the model actually change" question wants.

**Bounded by the content policy, not exempt from it.** `ofsContent` and
`agentKv` are file bodies, so they are unbounded content and belong under the
same resource bounds as message text. The references -- URIs, span owners,
checkpoint file lists -- are small and are the part worth mapping first.

**Status: Postponed.** The survey is done and the handling is decided per key
space; what is not done is the mapping. It waits because none of it is
correctness work -- every key space here is evidence Codess does not carry, not
evidence it carries wrongly -- and because two of the decisions depend on
questions other items own.

**Restart criteria.** Any one:

1. **A reader needs the system prompt.** The 23 `system` messages in `agentKv`
   are the only record of what the model was instructed to do, and no other
   Cursor structure carries it. A question about harness behaviour cannot be
   answered without them.
2. **Per-span authorship is wanted.** `patch-graph.provenance` states which
   turn owns which line range of a file. This is the highest-value item here
   and the one with no equivalent anywhere in CoSchema.
3. **W85 needs a Project binding** and a key space here supplies a path per
   composer -- `checkpointId:` names files and `ofsContent:` keys carry
   `file://` URIs, so this survey may resolve that item as a side effect.
4. **The content policy is extended to retrieved references** (W79), which is
   the decision `ofsContent` and `agentKv` blob bodies wait on, since both are
   unbounded file content rather than references.

**Evidence to close.** Each key space above is either mapped, or recorded as
declined with a reason, per the standing rule that a populated field dropped
without a stated reason is a defect.

### W82 -- Tools Carry Unchecked SQL

**Work.** Bring the `tools/` SQL under the same checking the library's SQL has.

**The defect, and how it surfaced.** `decode_audit.py` queried
`mapping_diagnostics.level`. That column was renamed to `granularity` in
format 6 -- deliberately, because `level` reads as an ordering and made summing
its values look meaningful. The tool was never updated, so **the audit that
CoPlan's validation sequence mandates for every decode change had been failing
at runtime**, and nothing reported it.

**Why no checker caught it.** Not a linter gap: SQL in a string is opaque to
ruff and mypy, and the column exists only in the DDL. The real gap is test
coverage -- `decode_audit.py` has **no test**, and of 23 scripts in `tools/`
only two are executed by the suite at all. Five hold SQL against store tables
(`decode_audit`, `demo_model_metrics`, `field_coverage`, `value_survey`,
`workload_bench`), and a rename reaches none of them.

A scan for other stale references found three apparent hits and all three are
false positives -- a loop variable in `coschema_gate`, and prose in
`refresh_schema_manifest` and `reporting_bench`. So the fixed instance was the
only live one, which is luck rather than a property to rely on.

**Options.** A smoke test per SQL-bearing tool over a fixture store is the
cheapest and would have caught this. A stricter alternative parses each tool's
SQL and checks every named column against the DDL, which also catches a query
whose rows are never exercised. The first is proportionate; the second is what
a second occurrence would justify.

**Closed.** `tests/test_tools_smoke.py` ingests the Claude fixture and runs
each SQL-bearing tool against the resulting store, asserting no traceback and
that the audit's report carries its sections. Verified by reintroducing the
`level` query and confirming two tests fail, then restoring.

A second bug surfaced while checking the others: `gather_evidence.py` read
`args.store_root` where the flag defines `args.store`, so it raised
`AttributeError` on every invocation and had never run. Fixed; it now reports
across 90 stores. The two defects share a cause -- a script nothing executes
fails only for the person who needed it.

Not covered by the smoke test: `demo_model_metrics` and `workload_bench`
require arguments a fixture cannot supply cheaply, and `coschema_gate` compares
two contract files rather than reading a store. Recorded rather than silently
excluded.

### W83 -- Early-Access Release Readiness

**Work.** Close what stands between the current state and a build another
person can install, run, and report against.

**The distinction that orders this.** A blocker prevents an outside user from
succeeding at all; a gap makes their report hard to act on; everything else is
work that can proceed after publication. Only the first two are release scope.

#### Blockers

| # | Blocker | Why it stops a release |
|---|---|---|
| B1 | **No `LICENSE` file, and no author or project URL in `pyproject.toml`** | Nobody can lawfully use, fork, or evaluate it, and a package index will not accept it. **Open: the licence terms are the owner's decision, not an engineering default.** `CHANGELOG.md` is written, so the release-notes half of this is done |
| B2 | ~~README announces `v0.0.1`; the package is `0.3.0`~~ | **Closed.** README now names `codess.__version__` and `codess --version` as authoritative and links `CHANGELOG.md`, so the version is stated in one place rather than restated in prose that drifts |
| B3 | ~~Stale formats are unreadable and the message does not say what to do~~ | **Closed.** `UnsupportedStoreError` now names the remedy -- rebuild with `codess ingest --dir <project> --force` -- and says why a migration is not offered. Nine store sets on this machine remain at formats 3 and 4; they belong to Projects whose paths no longer exist |
| B4 | ~~Tools carry unchecked SQL~~ | **Closed** with W82: every SQL-bearing tool now runs against an ingested store in the suite |

#### Gaps That Make a Report Hard to Act On

| # | Gap | Consequence |
|---|---|---|
| G1 | ~~No `CHANGELOG`~~ | **Closed.** `CHANGELOG.md` records format 7 and the decode, correctness, and check changes in this version, and states the rebuild procedure a format change requires |
| G2 | **Command-layer help text is absent on 76 distinct `admin_cmd` flags** (W66) | The interface is self-describing for `project.py` and silent for the administrative half, so a tester guesses |
| G3 | **Operational reporting is built and not adopted** (W71) | Status and errors still reach stderr through direct writes at each call site, so what a tester can capture depends on which module produced it |
| G4 | **Coverage reporting attests against unenforced profiles** (W04) | A completeness claim is only as good as the contract behind it; today it states loss against profiles no decode boundary enforces |

#### Explicitly Not Release Scope

Stated so the list does not grow by assumption. **W16, W17** -- no consumer has
asked. **W66, W67, W64, W65** -- internal structure a tester never observes.
**W75, W76, W79, W81** -- evidence and decode breadth, not correctness of what
already ships. **W05** is the interesting exclusion: running real
investigations would raise confidence, but it is a quality activity rather than
a gate, and early access is itself a way of obtaining that evidence from more
than one machine.

#### What Is Already Sound

Recorded so the remaining list is read as short rather than as a summary of
everything. Decode is validated against real Sessions from all three vendors
with no classification inconsistency; the suite is green and lint, type, and
test counts are gated against recorded ceilings; publication is transactional
and verified; no private path or operator identity appears in tracked files,
and the discovery lists are environment-configurable rather than fixed to one
machine; `.codess/` and `.env*` are excluded from version control.

**Status: Postponed.** Three of four blockers are closed. B1 is not an
engineering task: the licence terms are the owner's decision, and choosing one
by default would be picking a legal posture on their behalf. Everything else
here is a gap rather than a blocker, so the item waits on that single answer
rather than on work.

**Restart criteria.** Either:

1. **The licence is chosen**, at which point B1 is a `LICENSE` file plus the
   `license`, `authors`, and `urls` fields `pyproject.toml` currently omits --
   an afternoon, not a project.
2. **A specific tester is identified**, which would make G1 to G4 concrete:
   what that person needs to file a usable report decides which of the four
   matter, rather than the list deciding it in advance.

**Evidence to close.** A person on another machine installs from a clean
checkout, runs the README quick start against their own vendor data, and can
state which revision they ran and where to report what they find.

### W84 -- The Rest of the `selectedModels` Parameter Space

**Status: Postponed.** Both parameter ids that appear are mapped. What remains
is a question about a shape no observation has produced.

**What is settled.** `modelConfig.selectedModels` holds one entry per composer
-- 37 composers, every one with exactly one entry -- carrying parameters beside
the model id. Two ids appear and both now map:

| Parameter | Composers | Values | Maps to |
|---|---|---|---|
| `fast` | 34 | `"true"` 31, `"false"` 3 | `speed_tier`, only on `"true"` |
| `effort` | 19 | `"high"` 19 | `reasoning_effort` |

Values are strings, so `"false"` is a stated value rather than an assertion and
must not set a tier -- a test covers that case because it is the one a later
edit gets wrong.

**What is open.** Whether other parameter ids exist, and whether `effort`
takes values other than `high`. One machine's composers show one value, which
establishes the shape and not the vocabulary. A vocabulary guessed from a
single value would be worse than none.

**Restart criteria.** Any one:

1. A parameter id other than `fast` or `effort` is observed, which the mapping
   silently ignores today.
2. `effort` is seen with a value other than `high`, which would establish
   whether it is a free string or a closed vocabulary worth checking.
3. A Cursor model-comparison question needs effort or speed as a predicate
   across a corpus wider than one machine.

**Cost.** Small. The reader already walks the parameter list; an unmapped id is
one branch. It is postponed because the branch would be written against no
evidence.

### W85 -- Composers Older Than Their Index

**Status: Postponed. This is a data condition, not a defect.** Cursor prunes
`composerHeaders` on age while retaining `composerData:` and every bubble, so a
composer older than the retention window has no header. Codess reads it, states
where it came from, and does not attribute it to a Project -- which is the
correct handling of a Session whose binding the vendor no longer records, not a
failure to decode one.

The item stays open because the *handling* can improve -- these Sessions are
currently visible only to a caller that asks for every composer -- not because
something is broken.

**What is established.** 98 composers hold decodable bubbles and a global
`composerData:` row, and `composerHeaders` does not list them. Codess now reads
them -- `get_composer_headers` returns 164 composers against the previous 66 --
so they are visible, carry their settings, and 134 of the recovered set state a
model.

**Why they are not ingested.** A `composerData:` row states no `workspaceId`.
Checked across all 98 for any `workspaceId`, `workspace`, `folder`, `cwd`,
`rootPath`, or `projectPath` field: **none present**. One carries context file
references, which names files a Session touched rather than the Project it
belongs to, and treating that as a binding would be the path-and-content
inference the design refuses.

Ingest selects composers by workspace, so these are excluded there. The
exclusion is deliberate and is enforced in code: recovery applies only when the
caller asks for every composer, never under a workspace filter, because
admitting an unbound composer to a workspace selection would attribute a
Session to a Project on no evidence.

**So the honest state is: visible and unattributed.** `selection_source`
records `global.composerData` on each, which is what lets a reader tell an
unattributed composer from an absent one.

**Rounding out the handling.** Three things would make this condition
first-class rather than merely non-fatal, in increasing order of cost:

1. **Report it.** A scan or coverage line stating "98 composers hold bubbles
   older than the header retention window" turns an invisible condition into an
   observation. Nothing currently says the number.
2. **Name the condition in the store.** A Session admitted without a workspace
   would need a binding basis -- the `session_model_basis` pattern -- so a
   query could include or exclude unbound Sessions deliberately. This is the
   change that would let them be ingested at all.
3. **Offer the operator a binding.** The Project catalog already accepts
   approved source links for renamed and remote identities, so a reviewed
   manual binding needs no new mechanism, only a way to list the candidates.

None of these requires guessing a Project, which is the property that makes the
condition safe to expose.

#### Binning the 98, and What It Established

Correlation was run rather than assumed, and it answered the *why* even though
it did not produce a binding.

**The separation is temporal and total.** Grouping every `composerData:` row by
whether a header exists:

| Set | Count | `_v` values | `createdAt` range |
|---|---|---|---|
| Headered | 61 | 14, 16, 17 | 2026-03-26 .. 2026-08-17 |
| Orphaned | 98 | 9, 13, 14 | 2025-08-09 .. 2026-03-20 |

**Zero orphans fall after the earliest header**, and the two ranges do not
overlap by a single day -- orphans end 2026-03-20, headers begin 2026-03-26.
The one shared `_v` value, 14, splits on the same boundary: orphaned `_v=14`
composers run 2026-02-16 to 2026-03-20, headered `_v=14` run 2026-04-10 to
2026-05-01.

**So `composerHeaders` is a retention window, not an index of what exists.**
The vendor prunes header rows on age while retaining the `composerData:` row
and every bubble. That reframes the item: these Sessions are not missing an
identity Codess failed to read, they are older than the index that would carry
it. It also predicts the shape will recur -- today's headered composers become
tomorrow's orphans -- which makes reading `composerData:` a durable fix rather
than a one-time recovery.

**Other attributes bin them but do not discriminate.** Mode is `agent` 82 /
`chat` 16, model is `composer-1.5` 56 / `default` 22 / `composer-1` 11 and a
tail, bubble counts run 2 to 12,209 with a median of 65 and 75,273 in total.
None of these correlates with a Project; they describe the population.

#### Path Correlation, After Applying Two Known Rules

The first two measurements were both wrong, in different ways, and the
corrections are the finding.

**Correction 1: remote ground truth was compared as text.** Nine of 29
workspaces record their folder as `vscode-remote://ssh-remote%2B<hex>/...`. The
authority decodes to `{"hostName":"lazu"}` -- one remote host. Comparing that
string against a bare path fails on the scheme rather than the path.

**Correction 2: the project-boundary rule was not applied.** Discovery already
holds the rule that answers most of these failures: `project_boundary` walks
upward to the nearest ancestor holding `.git` and stops there. A path under
`Zero400/contrib` or `zerowallet400/src` is not evidence of a separate Project;
it is the same repository seen from inside. Ranking raw path prefixes ignored
this and let a subdirectory outrank its own root.

**Applying both -- skip remote workspaces, collapse every observed path to its
git root -- on the 40 local composers:**

| Outcome | Count |
|---|---|
| Correct | 21 |
| Wrong | 5 |
| No path evidence | 8 |
| No git root resolvable | 6 |

**81% precision on the cases that resolve**, against 67% for raw prefixes. The
improvement came from rules the system already states, not from a new signal.

**Why remote workspaces are skipped rather than mapped.** They are a distinct
condition, not a harder version of the same one:

| Remote shape | Count | What it is |
|---|---|---|
| `/home/ubuntu/...`, no local counterpart | 7 | A tree that exists only on the remote host |
| `/Users/walter/...` under the ssh authority | 2 | A path that **also exists locally** -- a mirror of remote logs |

The second shape is the labeling confusion: the same absolute path denotes a
local directory and a remote one, and nothing in the composer says which the
Session meant. Skipping remote workspaces initially is the right first step --
it removes a class that needs host identity to resolve, and the host is stated
in the authority, so the mapping can be built later from vendor evidence rather
than guessed.

**The 5 remaining failures were all rule defects, not correlation defects.**
Checked against the filesystem rather than assumed:

| Case | What it actually is |
|---|---|
| `ZeroPerf` picked as `Zero400`, x3 | **The same repository.** `ZeroPerf/.git` is a file reading `gitdir: …/Zero400/.git/worktrees/ZeroPerf`, and both report origin `zerocurrencycoin/Zero`. A linked worktree, which the Project catalog already has a `worktree` state for |
| `Zero400` picked as `ZeroPerf` | The same, in the other direction |
| `zerowallet400` picked as `ZKs/SevenSeas` | `ZK/ZKs` holds third-party OSS clones -- `bitcoin-src`, `BLAKE3`, `blockbook` -- which are not development Projects and belong in the scan exclusion list, as does `Spank/sOSS`. `zerowallet400` is the wallet repository and has no `.git`, so the collapse could not reach it either |

**Re-measured with three rules -- skip remote, resolve each path to its shared
repository rather than its worktree, exclude OSS containers:**

| Outcome | Count |
|---|---|
| Correct | **25** |
| Wrong | **0** |
| Unresolved | 15 |

The 15 unresolved are honest abstentions, not hidden errors: 8 composers carry
no path evidence at all, and 7 resolve to no repository -- `zerowallet400` is
not a git repository, and some local Sessions reference `/home/ubuntu/...`
paths from remote work.

**What this changes.** Path correlation is not weak; the three rules applied to
it were wrong. Two were already implemented elsewhere in the system --
`project_boundary` stops at a repository, and the catalog carries a `worktree`
relation -- and the third is a configuration list that ships empty by design.
`CODESS_EXCLUDE_REVIEW_DIRS` and `CODESS_AGGREGATORS` are unset on this
machine, which is why `ZK/ZKs` was treated as candidate Projects.

**The measurement lesson worth keeping:** three successive corrections each
moved the result -- 61%, then 81%, then 100% of resolved cases -- and each was
a defect in the *rule* rather than in the data. A correlation reported before
the domain rules are applied measures the rules, not the correlation.

**Where this leaves the item.** On the validation set the rule is now correct
on every case it resolves and abstains on the rest, which is the shape a
binding rule should have. Two cautions before it is used to write anything:

- **The set is small and one machine's.** 25 resolved cases prove the rules are
  right about these repositories, not that the rule generalises. A repository
  layout without worktrees or vendored OSS would exercise none of the
  corrections that produced this result.
- **The exclusions are operator configuration, not facts.** `ZK/ZKs` is OSS
  *because the operator says so*; nothing in the directory distinguishes a
  vendored clone from a Project. So the rule's precision is bounded by whether
  `CODESS_EXCLUDE_REVIEW_DIRS` is set correctly, which makes it a reviewed
  binding by construction.

Both point the same way: propose candidates for the operator to confirm through
the catalog, which is the third resolution path below and needs no new
mechanism.

**What would resolve it**, in order of how much evidence each requires:

1. **A workspace index that lists them.** The workspace
   `composer.composerData` fallback already recovers 75 of the 107 headerless
   composers; the remaining ones may appear in a workspace database not
   currently searched, which is checkable.
2. **Vendor evidence binding a composer to a folder.** A key space not yet
   read -- `checkpointId:` names files, `ofsContent:` keys carry `file://`
   URIs -- may carry a path per composer. That is W81's survey and would answer
   this as a side effect.
3. **An operator-stated binding.** The Project catalog already accepts approved
   source links for renamed and remote identities, so a reviewed manual binding
   is a supported mechanism rather than a new one.

**Restart criteria.** Any one of the three above yields a binding, or an
operator asks to attribute a specific composer through the catalog.

**On inference generally.** Nothing forbids correlating or matching values --
the retention finding above was obtained exactly that way, and the design's
rule is narrower than "no inference": CoSchema forbids treating *timestamp
proximity, adjacency, or textual resemblance* as proof of a **relationship**
between records. A Project binding derived from a measured, validated signal
would be admissible if it recorded how it was obtained; `session_model_basis`
is the precedent, where a derived value is carried beside a column stating that
it was derived.

What is rejected here is the specific path rule, on its measured precision
rather than on principle. Any replacement needs the same treatment: validated
against the headered composers, where ground truth exists, and carrying a basis
column so a reader can exclude derived bindings from a query.

### W86 -- Skipped and Refused Records Are Counted but Not Attributed

**Work.** Make what a decode discarded queryable and attributable, not a
transient stderr line.

**The mechanism exists and is not the problem.** Every discard routes through a
counter -- `_diagnostic(opts, "known_ignored_records")` for a skipped record
type, `_record_refused` for a refused one -- and ingest prints the totals:

```
ingest diagnostics: malformed=0 ignored=4898 empty_sources=0 failed_sources=0
unsupported=0 known_ignored=21580 filtered=0 external_content=0 ...
```

**The volume is why this matters.** One Project reports 21,580
`known_ignored` records and 4,898 `ignored`; another 5,580 and 2,881. These are
not edge cases, they are a substantial fraction of what the vendor wrote.

**Three specific gaps.**

1. **The totals are not stored.** `mapping_diagnostics` holds only four reason
   codes across the whole corpus -- `field_absent` 41,521, `field_empty` 7,810,
   `missing_tool_call_id` 1,075, `field_null` 17 -- all *field*-granularity. Not
   one record-level discard is persisted, so a store cannot answer "what did
   this decode drop" after the run that produced it has scrolled away.
2. **The counters do not say which type.** `known_ignored=21580` aggregates six
   record types (`progress`, `file-history-snapshot`, `file-history-delta`,
   `queue-operation`, `last-prompt`, `system`) into one number. A vendor that
   starts writing meaning into `progress` records would move this total and
   nothing would say which type moved.
3. **A skip is not distinguished from a bound.** `ignored` and `filtered` and
   `unsupported` are separate counters, but a reader cannot tell a record
   dropped because Codess does not map its type from one dropped because it
   exceeded a resource bound -- and those need different responses.

#### Skip Sites, Classified

A static scan of the seven decode and source-access modules found 149
`continue`/bare-`return` sites. Classifying them by the condition that guards
each is what separates noise from a real gap:

| Class | Count | Needs a counter? |
|---|---|---|
| Type or shape guard (`isinstance`, `is None`, empty) | 72 | **No.** No record is lost; a malformed *shape* is a different event from a discarded record |
| Already recorded | 26 | No -- these route through `_diagnostic` or `_record_refused` |
| Unclassified by the scan | 32 | Unknown -- multi-line conditions the regex could not read |
| Exception swallow | 10 | **Yes.** A parse failure discards a record the vendor wrote |
| Value or kind decision | 9 | **Yes.** `type != "assistant"`, `item_type not in (...)` -- a populated record dropped on its kind |

**The exception swallows are measurable and small.** Reading every row of the
decoded Cursor key spaces directly:

| Key space | Rows | Silently skipped |
|---|---|---|
| `bubbleId:` | 210,152 | **41** (null value) |
| `composerData:` | 166 | **7** (null value) |
| `checkpointId:` | 7,718 | 0 |
| `messageRequestContext:` | 678 | 0 |

**48 records, all null-valued, none unparseable.** That is the useful shape of
the answer: the swallow paths *are* reached, at a rate of 0.02%, and every
instance is a vendor row with no value rather than a decoder that failed to
read one. A counter would have said so without this investigation, which is the
argument for adding one.

#### Challenge Taxonomy for KV Interpretation

The Cursor key-value store is one table holding a dozen unrelated record
shapes, so the failure classes are not the same as a line-oriented transcript's.
Naming them separates a decoder defect from a vendor fact.

| Challenge | Observed | How it presents | Handling |
|---|---|---|---|
| **Null value** | 41 bubbles, 7 composerData | Key exists, value is `NULL` | Count it; the vendor wrote a placeholder |
| **Not JSON at all** | 132,207 `agentKv` rows | Binary protobuf under a key space that also holds JSON | Classify by key space first, not by parse attempt |
| **Valid JSON, wrong shape** | 0 in decoded spaces | Parses to a list or scalar where a dict is expected | Count separately from a parse failure |
| **Index disagreement** | 107 composers | `composerHeaders`, workspace and global `composerData` each list a different set | Read all, record `selection_source` |
| **Retention skew** | 98 composers | An index prunes on age while the data it indexes is kept | A data condition, not a gap |
| **Identity absent** | 98 composers | The record states no workspace, so no Project can claim it | Admit without a binding, never infer one |
| **Bulk rewrite** | 4,053 groups, 37 Sessions | A sync re-writes records that already exist, with new identities | Advisory `duplicate_of`, do not delete |
| **Scheme-wrapped path** | 9 workspaces | `vscode-remote://` wrapping both remote and local paths | Skip initially; the host is stated and can be mapped later |

**The first two are why a parse failure must name its key space.** An
unparseable `agentKv` row is expected and an unparseable `bubbleId` row would
be a decoder defect, and today both would increment the same counter.

#### Partial Ingestion on a Parse Error

Currently a record that fails to parse is skipped whole. Two better options,
and the reason for preferring the second:

1. **Retain the raw bytes.** The raw-evidence path already stores
   content-addressed objects, so an unparseable record could be captured for
   later inspection rather than discarded. This is right for a *rare* failure
   and wrong for a common one -- 132,207 binary `agentKv` rows would become
   132,207 raw objects.
2. **Record presence, size, and key space; retain bytes only above a stated
   rarity.** The count answers "is this happening"; the bytes answer "what is
   it", and only the second needs storage. Since the measured rate in decoded
   key spaces is 48 in 218,714 -- 0.02% -- retention is affordable there and
   would be ruinous in `agentKv`, which is the argument for keying the decision
   to the key space rather than to the error.

**What must not happen is a partial *record*.** Ingesting the fields that
parsed from a truncated JSON object would produce a Session whose content is
silently incomplete, which is worse than an absent one because nothing marks
it. Partial ingestion is acceptable at the *record* boundary -- skip this
record, keep the Session -- and not within a record.

**How to separate common, rare, and wrong.** The three need different
treatments and the counter design should make them distinguishable:

- **Common and reasonable** -- a known ignored record type, a shape guard. High
  volume, stable proportion. Expected; worth a total, not an alert.
- **Rare but valid** -- 48 null rows in 218,000. Worth naming so that a change
  in the rate is visible, since a jump from 48 to 48,000 means the vendor
  changed something.
- **Wrong** -- an unparseable value in a key space that should always parse.
  Zero today. This is the class that should be loud, and it is currently
  indistinguishable from the other two.

The distinction is a *reason code*, not a severity: `record_null`,
`record_unparseable`, and `record_kind_not_mapped` are three different facts
about the vendor, and collapsing them into `ignored` is what makes the current
total unactionable.

#### Reason and Condition Codes, Bounded by Ingest Cost

**The design constraint is that `mapping_diagnostics` is written one row per
finding.** It holds 50,423 rows for field-level findings across the corpus, and
record-level discards are an order larger -- one Project alone reports 21,580
`known_ignored`. Writing a row per discarded record would roughly double the
diagnostic table for evidence that is identical 21,580 times over, and it would
do it inside the ingest transaction.

**So the codes are aggregated, not per-record.** One row per
`(source, reason_code, record_kind)` per Source, carrying a count:

| Reason code | Condition | Granularity |
|---|---|---|
| `record_kind_not_mapped` | The record type is in `SKIP_TYPES` or an equivalent list | `record` |
| `record_null` | The vendor row exists with no value | `record` |
| `record_unparseable` | The value is present and does not decode | `record` |
| `record_refused_bound` | A resource bound rejected it before the read | `record` |
| `record_refused_content` | The content policy refused the body | `record` |

The `record_kind` column carries the vendor's own name for what was dropped --
`progress`, `file-history-snapshot` -- so the six types currently summed into
`known_ignored` become six countable facts.

**Cost, stated in the terms that decide it.** Aggregation makes the write count
proportional to *distinct kinds per Source* rather than to records: on the
measured corpus that is single digits per Source against tens of thousands of
records. The counting itself is a dictionary increment already performed by
`_diagnostic`; what is added is one flush per Source at the end of decode,
inside the transaction that already exists. No per-record SQL, no second pass
over the data.

**What this buys coverage reporting.** Today a store can say a *field* was
absent and can say only that 21,580 records were "known ignored". With these
codes it can state what kind of record was dropped and under which condition,
which is the difference between "this decode is incomplete" and "this decode
declined 4,898 `progress` records and refused 2 for exceeding a bound".

**Evidence to close.** Record-level discards reach `mapping_diagnostics` as
aggregated rows carrying a reason code and the vendor's record kind; the
ingest-time cost is one flush per Source rather than one write per record; a
query reports what a store dropped and why; and the 51 sites classified above
as exception swallows or value decisions each increment a counter.

**Why this is High.** Coverage reporting states what a store mapped and missed.
Today it can name missed *fields* precisely and missed *records* only in
aggregate, so the completeness claim is weaker than it reads.

### W87 -- The Test Corpus, Grouped and Assessed

**Work.** Group the suite by subsystem, retire what is superseded, and close the
gaps the grouping exposes.

**The corpus.** 68 files, 1,506 test functions, 27,298 lines:

| Subsystem | Files | Tests | Lines |
|---|---|---|---|
| store | 9 | 320 | 5,725 |
| *unclassified* | 21 | 311 | 5,356 |
| adapter | 4 | 257 | 3,951 |
| cli | 5 | 175 | 4,294 |
| source-access | 6 | 109 | 1,503 |
| query | 4 | 85 | 2,111 |
| reporting | 2 | 80 | 902 |
| identity | 3 | 54 | 542 |
| policy | 5 | 49 | 841 |
| audit-tools | 5 | 39 | 549 |
| integration | 4 | 27 | 1,524 |

**The largest finding is the second row.** 21 files and 311 tests do not group
under any subsystem the architecture names -- `test_acceptance`,
`test_naming`, `test_structural_duplication`, `test_units`, and eighteen
others. Some are genuinely cross-cutting; others are a module's tests filed
under the module's name rather than its layer. Until they are classified, no
statement about per-subsystem coverage is trustworthy.

**Weakest attention, by module size against tests naming the module.** A ratio,
not a coverage percentage -- it says where to look, not what is untested:

| Module | Lines | Tests naming it |
|---|---|---|
| `refresh_receipts` | 119 | **0** → 10 |
| `tool_result_status` | 84 | 3 → 34 |
| `mcp_audit` | 395 | 4 |
| `storage_report` | 310 | 3 |
| `token_usage` | 394 | 5 |
| `retention` | 450 | 6 |
| `ingest_review` | 135 | 2 |

**Two are closed.** `refresh_receipts` was named by no test at all, and it is
the module the corpus baseline reads its ingest-rate evidence from;
`tests/test_refresh_receipts.py` now covers format gating, corrupt-receipt
tolerance, the status vocabulary, recency, the apply-outranks-preflight rank,
and failure-as-observation. `tests/test_tool_result_status.py` covers what
counts as explicit failure evidence and -- the harder half -- what is
deliberately not searched, since a detector that read prose would mark
successful work as failed. Both were mutation-tested: inverting the stage rank
and loosening the empty-`error` rule each fail the test that asserts them.

Four remain, and `retention` at 450 lines against 6 mentions is the largest.

**What is healthy, and worth stating so the list is read as short.** Zero
skipped or `xfail` tests -- nothing is parked. No test references a removed
construct: the `ProgressTrace` hit is the test asserting its removal, and the
`level` and `contract_digest` hits are unrelated words or the current
`contract_digest` field.

**Ten duplicated test names across files** -- `test_empty` six times,
`test_absent` six, `test_relative` four. Harmless to pytest, and a real cost
when a failure is read from a summary line: `test_absent` names neither what is
absent nor which subsystem noticed. These are within-file names that would
benefit from the subject they test.

#### Matching Criteria Beyond the Filename

Grouping by name alone put 21 files in "other". These criteria describe what a
test file *does*, and cut across the name:

| Criterion | Files | What it identifies |
|---|---|---|
| Touches SQLite directly | 30 | Store-shaped tests, wherever they are filed |
| Runs a subprocess | 13 | The installed-CLI surface; these are integration regardless of filename |
| Uses `tmp_path` | most | Filesystem-dependent; distinguishes unit from pure-function tests |
| Declares a fixture | few | Shared setup, so a change there reaches several tests |
| Asserts with `pytest.raises` | -- | Error-path coverage, which is where thin modules are thinnest |
| Uses `parametrize` | -- | Vector-driven; `test_helpers` has 18, most files have none |
| Has no test class | 39 | Flat files, where grouping is by convention rather than structure |

Cross-referencing these against the filename grouping is what would reassign
the 21: `test_snapshot_raw` touches SQLite 14 times and belongs with store;
`test_admin_operations` runs 7 subprocesses and belongs with CLI integration.

**Docstring coverage is 35%** -- 544 of 1,516 tests. That is the gap that makes
a failure summary hard to read, more than the name itself: a name states the
subject, a docstring states why the behaviour is required.

#### Test Names

**Measured.** Median 6 words; 179 names of two words or fewer; **46% contain a
verb stating an outcome**.

The short names are the problem, and they cluster: `test_bash`, `test_read`,
`test_edit`, `test_empty`, `test_none`, `test_progress`. Each names a *subject*
with no claim about it, so a failure line says which input was involved and
nothing about what should have happened.

**The improvement is a stated outcome, not a longer name.** Existing good
examples from this suite show the shape:

| Current | Better | Why |
|---|---|---|
| `test_empty` | `test_an_empty_transcript_yields_no_events` | Says the expected result |
| `test_zero_limit` | `test_a_zero_limit_is_rejected` | Says the decision |
| `test_bash` | `test_a_bash_call_records_its_command` | Says what is retained |
| `test_absent` | `test_an_absent_field_stays_null_rather_than_defaulting` | Says the rule, which is the durable part |

The convention worth adopting: **subject, verb, outcome** -- readable as a
sentence, and failing usefully in a summary line. It applies to new tests
immediately and to existing ones as their files are edited, which is the same
rule the `D205` docstring baseline already follows.

**Not proposed:** renaming all 179 in one pass. It is a wide diff with no
behavioural content, and the same argument that defers the naming sweep for
source identifiers applies here.

**Evidence to close.** Every test file is classified to a subsystem using the
criteria above; the unclassified 21 are reassigned or the grouping gains a
category that honestly describes them; the thin modules named above have tests;
and new test names state an outcome.

### Store Performance Baseline

Measured before adding stored records, so a later change has something to
regress against. Two layers, because they answer different questions.

**Synthetic workloads** (`tools/workload_bench.py`, scale size):

| Workload | Rows | Seconds | Per row |
|---|---|---|---|
| `ingest/scale` store write | 20,000 | 0.543 | **27.2 us** |
| `ingest/correctness` store write | 50 | 0.029 | 582 us |
| `cursor/scale` bubble selection | 200 | 0.0013 | 6.4 us |

The correctness size is dominated by fixed overhead, which is why the scale
size is the figure to compare. Cursor selection is flat between a 200-bubble
and a 20,000-bubble container -- the index range scan does not degrade with
container size, which is the property that workload exists to check.

**Real-corpus ingest**, three Projects spanning the size range:

| Project | Events | Store MiB | Seconds | Per event |
|---|---|---|---|---|
| Largest | 89,288 | 621 | 122.5 | **1,371 us** |
| Median | 2,650 | 15 | 17.1 | 6,442 us |

**The 50x gap between 27 us and 1,371 us is the useful number.** The synthetic
workload measures the store write alone; real ingest also decodes vendor
records, hashes content, applies bounds, and publishes a verified snapshot. So
a store-write optimisation has at most 2% of end-to-end ingest to win, and the
cost of adding a stored record is bounded by the same proportion -- which is
what makes the aggregated reason-code design affordable.

The median Project's higher per-event cost is fixed overhead over a small
corpus, not a scaling problem: publication and verification cost roughly the
same regardless of Event count.

**Query, on the largest store (89,288 Events):**

| Query | Seconds |
|---|---|
| `overview` | 0.24 |
| `sessions` | 0.23 |
| `events --event-kind tool.result --status failed --limit 200` | 0.23 |
| `search --text error --limit 200` | 0.22 |

Flat at roughly 0.23 s, and the variation between a full-store summary and a
bounded predicate is within noise -- process start and store open dominate. A
query change that moved any of these past about half a second would be visible;
below that, this baseline cannot distinguish improvements.

**What this baseline does not cover.** Cross-Project queries over many store
sets, the publication stage in isolation, and memory under concurrent access.
Each is a separate workload and none is currently measured.

### Store Fit as Time Series and as Log Records

Assessed because two questions keep arriving in different forms -- "can this
feed a dashboard" and "can this go into Splunk" -- and they have different
answers.

#### What the Store Already Satisfies

Measured on one populated Cursor store of 84,395 Events:

| Property | Observed | Why it matters |
|---|---|---|
| Timestamp coverage | **100%** of Events carry `event_at` | A record with no time is not a log line |
| Ordering agreement | **0 Events** out of time order within a Session when read by `sequence_no` | Sequence and time do not contradict, so either may be the sort key |
| Sub-second precision | 84,304 of 84,395 carry sub-second values | Millisecond resolution, not second-truncated |
| Time index | `idx_events_event_at` exists, partial on non-null | A range scan is indexed |
| Low-cardinality dimensions | `event_kind` 6, `actor_kind` 4, `tool_name` 24 | These are exactly the fields a log platform facets on |
| Stable identity | `event_entity_id` derived from vendor-stated facts | Re-ingesting the same Session on another machine yields the same identity, so a re-index does not duplicate |
| Line-oriented export | `--output-format jsonl` already exists | The transport a log platform expects |

So the shape is a good fit: a wide, timestamped, low-cardinality-dimensioned
event table with stable identities and a JSON Lines export already built.

#### What Does Not Fit, and Should Not Be Made To

**Timestamps are not unique.** 25,707 of 33,879 distinct timestamps are shared
by more than one Event. Anything that assumes a timestamp identifies a record
-- a naive dedup, a time-keyed join -- is wrong here. `event_entity_id` is the
identity; `event_at` is a measurement. This is normal for machine-generated
events and is stated because it is the mistake an operator makes first.

**The store is a projection, not an append log.** Codess replaces a Source
transactionally and republishes; it never appends. A log platform that tails a
growing file will see wholesale replacement. The correct integration is a
periodic export of a bounded query, not a tail.

**Retention is the vendor's, not Codess's.** Events exist because a vendor
retained them, and a vendor prunes on its own schedule. A dashboard built over
this will show history changing under it, and that is the data, not a defect.

**Codess is not a metrics store.** No counters, no pre-aggregation, no
retention tiers, no downsampling. A question like "tool failures per hour" is a
`GROUP BY` over an indexed range and answers fine at this scale; it is not
served from a rollup and there is no plan for one.

#### Recommendation

**Export, do not become.** The store is already close enough to a log record
that a Splunk, Loki, or ClickHouse integration is an export script over the
existing typed query -- `--output-format jsonl`, a `--since` bound, and the
result identity as the deduplication key. Nothing in the schema needs to change
for that.

**What would need adding is small and should wait for a requester.** A log
platform typically wants a single flat record per line with the Session and
Project fields denormalized onto it, rather than the joins the relational form
requires. That is a projection concern, and building it before a consumer
states its field list is how a system acquires an interface nobody uses -- the
standing rule that already defers the external-interface items.

**What should not be built** is a second write path that emits events to a
platform as they are decoded. It would double the failure modes of ingest,
couple a local investigation tool to a remote service, and contradict the data
safety boundary: these records carry prompts, source code, and credentials, and
publication is an explicit reviewed act rather than a side effect of decoding.

### Session and Event Model Evidence

Where a vendor records the model differs by format, and a query that asks "which
model did this work use" must not need to know which. This inventories what each
level currently holds, states the alternatives, and records the decision.

#### What Is Populated Today

Measured across the 30 published Project store sets:

| Vendor | Sessions | With Session model | Model Turns | With turn model | Events | With turn link |
|---|---|---|---|---|---|---|
| Claude | 351 | **0** | 5,972 | 5,972 | 16,615 | 5,972 |
| Codex | 22 | 22 | 10,607 | 10,607 | 84,862 | 44,281 |
| Cursor | 86 | 32 | 2,878 | 2,644 | 135,327 | 70,261 |

Two facts decide the question. **Turn-level coverage is near total** -- every
Claude and Codex Model Turn carries a model, and 92% of Cursor's do. **Session-level
coverage is vendor-dependent**: Codex states it on every Session, Cursor on 37%,
and Claude on none, because Claude records the model per assistant record and
never as a Session header.

`sessions.session_model_param_id` is not a summary of the turns. It is the
*default that seeds turn resolution*: `_prepare_event_groups` reads it as
`current_model_param_id` and each turn overrides it where the vendor states one.
So a Session-level value answers "what was this Session configured with", and a
turn-level value answers "what actually served this turn". They are different
questions and the second is not derivable from the first.

#### How Often They Would Disagree

Sessions carrying more than one distinct model across their turns:

| Vendor | Sessions with turn models | Exactly one model | More than one |
|---|---|---|---|
| Claude | 351 | 346 | **5** (2 with two, 3 with three) |
| Codex | 22 | 16 | **6** (5 with two, 1 with three) |
| Cursor | 42 | 36 | **6** (5 with two, 1 with three) |

**17 of 415 Sessions use more than one model** -- 4%. Small, and not
negligible: a Session that escalated from a fast model to a reasoning one is
exactly the case a comparison question is asked about, so the 4% is the
interesting population rather than noise to round away.

#### Alternatives

| # | Approach | What it costs |
|---|---|---|
| A1 | **Session-level only.** One model column per Session; drop turn models | Erases the 17 multi-model Sessions and cannot answer which model served a given Event. Claude would report nothing, since it states no Session model |
| A2 | **Event-level only.** Drop `session_model_param_id`; resolve every model from its turn | Loses the vendor's own Session-level statement, which Codex makes explicitly. A configured model that never served a turn becomes unrecorded, and the seeding default disappears, so a turn with no stated model resolves to null rather than to the Session's configuration |
| A3 | **Both levels, populated independently** (current) | Two columns to keep consistent, and a reader must know which one answers their question |
| A4 | **Both levels, with Session derived from turns where the vendor states none** | Would fill Claude's 351 nulls, but by computing a value the vendor never asserted -- and for the 5 multi-model Claude Sessions there is no single correct answer to compute |
| A5 | **Both levels, plus a stored per-Session model set** | Answers "which models appear in this Session" without a join, at the cost of a denormalized column that can disagree with the turns it summarizes |

#### Recommendation

**Keep A3, and document which level answers which question.** The reasons are
measured rather than stylistic:

1. **The levels are not redundant.** Session-level is the configured default,
   turn-level is what served. Codex populates both and they are not always
   equal; collapsing them (A1 or A2) discards a distinction the vendor drew.
2. **Turn coverage is already near total**, so the Event-side question is
   answerable today for all three vendors. Nothing needs building for it.
3. **A4 is the tempting one and should be refused.** Deriving a Session model
   from its turns would fill 351 Claude nulls, which looks like an improvement
   until the 5 multi-model Sessions force a choice the evidence does not
   support -- first turn, most frequent, or last. CoSchema's standing rule is
   that a value the vendor did not state stays null rather than being inferred,
   and this is exactly that case. A null here is the true answer: Claude does
   not record a Session-level model.
4. **A5 is premature.** The join answers it, and no measured query is slow for
   this reason. Revisit if one is.

**What to change is documentation, not structure.** CoSchema should state the
two levels' distinct meanings where it currently states neither, so a reader
does not take `session_model_param_id` for a summary. Cross-vendor model
comparison should query the turn level, because that is the level all three
vendors populate; the Session level is evidence about configuration and is
absent for Claude by vendor design rather than by decode gap.

## Maintenance Directions

Ongoing obligations rather than items. Each recurs or has no completion condition,
so numbering it would produce an identifier that never closes.

- Fix publication, catalog, raw, refresh, or retention behavior when it threatens
  correctness, bounded storage, or normal operation.
- Add resource controls for observed accidental or pathological input.
- Maintain Session names and utilization observations without displacing source
  decode, mapping, or search work.
- Reduce the recorded lint and type-error counts. `tools/quality_report.py` reports
  both against a baseline, so a change can be compared rather than asserted clean.
- Prune orphaned catalog entries. Nine Project paths carry two `project_id` entries
  each, one holding a current store and one a stale earlier-format snapshot --
  residue from before the location-identity fix. Nothing is broken by this: every
  live Project queries successfully, and each duplicated path has a working store
  under one of its identities. Pruning is a reviewed maintenance operation on the
  operator's own registry, not a code change.

### Terminology Debt

This document's vocabulary was audited and found to overload seven terms: Registry
(3 senses), Catalog (4+), Source (the formal entity diluted by lowercase
compositional use), Investigation, Pointer, Store (`legacy`/`working` compounds),
and Contract (5 scoped meanings never enumerated). Snapshot carries a vendor-product
false friend. `Audit` is the model case, disambiguated in text at its point of use.

Findings, line numbers, and a suggested definition per sense are in
`experiments/vocabulary-audit-findings.md`. `matching set` is the settled term for
the released file set a store is written under.

The schema half is **W50**; the prose half is ongoing, because a document does not
finish being consistent.

### Hash Derivation

Whether hash derivation is worth segregating into one module with no `hashlib`
reference permitted elsewhere is a question, not a conclusion. A single module
enforces consistency structurally rather than by convention, but the call sites have
little in common beyond calling SHA-256.

Three groupings are candidates and should be judged separately: file and stream
digests (`fileio`, `snapshot`, `raw_store`, `schema_contract`), canonical-document
digests over serialized JSON (`query_api`, `project_catalog`, `catalog_operations`,
`retention`), and identity or key derivation (`identity`, `path_label`,
`tool_identity`, `store`). Only the last is clearly one concern.

The argument in favour is that no single place states which algorithm Codess uses,
so an algorithm change is a wide edit whose wire-format consequences spread across
as many field names and value prefixes. The argument against is that `identity.py`,
`fileio.py`, and `content_processing.py` legitimately decide encoding, chunking,
truncation, and output prefix differently.

## Deferred Directions

Postponed until a concrete consumer or a measured limitation justifies reopening.
None is a tracked item, and none should acquire one without that trigger:

- a mapping expression language;
- remote schema or mapping registries;
- fuzzy cross-vendor identity resolution;
- a built-in general search engine beyond current SQLite predicates;
- standardized Parquet, DuckDB, or merged-database products;
- automatic narrative or assessment generation;
- cost, quota, or billing analysis;
- broad raw-source search; and
- a portable Project name in the review catalog. `local_path_key` names a
  machine-local location by decision, so a reviewed candidate that moves loses its
  reference. Reopening needs a portable input that exists *before* approval, which
  is the point at which a candidate acquires a real Project identity today.
