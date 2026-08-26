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

- [Active Work](#active-work)
- [Status Vocabulary](#status-vocabulary)
- [Open Items](#open-items)
- [Queue](#queue)
- [Dependencies and Batching](#dependencies-and-batching)
- [Item Detail](#item-detail)
- [Maintenance Directions](#maintenance-directions)
- [Deferred Directions](#deferred-directions)

## Active Work

What is ready to work on now, what is in progress, and what waits on a decision
rather than on effort. The full register is [Open Items](#open-items); this is
the short list a reader needs first.

### In Progress

| ID | Work | State |
|---|---|---|
| **Sprint 1** | Wire-format change: token columns, time triple, `duplicate_of`, W50+W51 renames, `page_size` | Decisions captured in `experiments/format-decisions.md`; not applied |

### Ready

Unblocked, decided, and startable without waiting on anything.

| ID | Work | Note |
|---|---|---|
| **W04** | Candidate-record contract, steps 3-4 | Unblocked: W35 closed, so the per-vendor hazard fixtures the strict/diagnostic semantics need are reachable and tested |
| **W71** | Nine `warn` sites to the facility | Unblocked: every command module now attaches a sink |
| **W94** | Reduce four format-number declarations toward one | The unchecked fifth location is removed; what remains is a pre-commit check moving detection from test run to commit |
| **W89** | Path inclusion and exclusion belong in the discovery policy | Specification settled on the item; `exclude_dirs`/`exclude_paths`/`include_paths`, with Operations documenting the design ahead of the rename |
| **W95** | Tighten message and comment wording | Low priority, batches with anything |
| -- | Cursor `agentKv` tier-1 decode | Attribution solved via `toolFormerData.toolCallId`; supplies model names and 111,000+ tool invocations |
| -- | Codex declared parentage | `forked_from_id`, `parent_thread_id`, `agent_role`, `thread_source` are declared in the protocol |

### Blocked on a Decision

The unanswered question, not the effort, is what holds each.

| ID | Question | Whose |
|---|---|---|
| **W83** | Licence terms | Owner. Postponed entire; restarts on the licence decision |
| **W93** | Session-utilization inclusion policy | Detection **designed** on the item; what a report includes is not |
| -- | Symlink traversal in discovery | Recommendation: do not follow. See [Item Detail](#item-detail) |

### Under Developer Review

Held pending review of requirements and proposed designs, not for lack of work.

| ID | Work |
|---|---|
| **W04** | Candidate-record contract |
| **W05** | Real investigations against the query surface |

### Analysis Only

Design and analysis proceed; implementation is postponed.

| ID | Work |
|---|---|
| **W73** | Vendor decode gaps. Codex half is now answered by the protocol source |
| -- | Hash derivation: whether to segregate `hashlib` into one module |

### Postponed Infrastructure

| ID | Work | Restarts when |
|---|---|---|
| **W66** | Configuration unification | Deliberately deferred |
| **W71** | Reporting adoption in the command layer | Fatal half done; nine status sites wait on whether two commands report at all |
| -- | Linking-tooling retest | More development and capability expansion land first |

Exception: the **time and datetime module** is not postponed. It is standalone,
takes an injected clock, and is developed, validated, and deployed in this round.

### Recently Closed

Recorded so closed work is not re-derived. Outcomes are in
[CoReview](CoReview.md).

| ID | Work |
|---|---|
| W04.1-2, .5 | `validate_mapped_event` at one vendor-neutral boundary, the candidate contract declared as a type, and a per-vendor conformance count in `decode_audit` that found an undeclared Cursor rule |
| W35 | Every released manifest entry has a consumer that reads it through the manifest; four fixtures had none, and one was stale |
| W99 | Receipts under one tree, `receipts/<kind>/`; a misplaced retention receipt is what the old prefix glob silently ignored |
| W101 | `reasoning_fidelity` distinguishes Codex's precis from Cursor's reasoning: 12 `summary` and 6,374 `full` in one store set |
| W67 | Every relay takes an object: 17 parameters to 4, 14 to 6, 12 to 8, 10 to 7, 8 to 3 |
| W100 | One retention count, current included, shared by the publication trim and the prune |
| -- | Two traversal helpers; `admin` and `query` attach a reporting sink and report start, done, and failure |
| W66 (part) | Setting table with one stated precedence, `parents=` for seven shared options, help on every option, one declared type per flag, and the leaf-visible mechanism |
| W71 (part) | The fatal-error channel: `cli.failure`, and no command module writes `sys.stderr` |
| -- | Corpus recreated under the current contract and pruned to one snapshot per Project; the baseline table carries the resulting figures |
| W55 | Time parsing consolidated onto `codess.timeval`; the `units` compatibility shim has no importers left |
| W64 | Typing posture decided on measured cost: two flags enabled, one deferred with its figure |
| W72 | One Event-record builder per adapter; 23,470 real Events decode byte-identically after |
| W74.1 | Cursor Session times -- corpus-verified: 0 of 37 Cursor Sessions carry a null `started_at` |
| W86 | Refusal reason codes reaching the store, aggregated |
| W90 | Scanned and never ingested |
| W91 | Reconciled lifecycle view and its command |
| W78 | Module-level import cycles |
| W82 | Unchecked tool SQL |
| W80 | `composerData.modelConfig` read for every composer |
| -- | Sprint 2 Cursor field pass: turn and client timings, error details, terminal cwd, symbol and file links, todos, code blocks, `context` leaves, request and response identifiers |
| -- | Three duplicate time columns removed: `events.timestamp`, `sources.ingested_at`, `sessions.ingested_at` |

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
| W04 | High | Planned | Candidate-record contract. Steps 1, 2, and 5 landed; steps 3-4 are unblocked now that W35 is closed | -- |
| W05 | High | Planned | Run named real investigations against the query surface | -- |
| W14 | High | Planned | Require or mark Project identity. The 2026-08-25 recreation reingested all 21 Projects and minted no duplicate, so the guard holds for a reingest; the direct-library-write path is still unguarded | -- |
| W16 | Normal | Postponed | Evaluate external investigation interfaces | No consumer |
| W17 | Normal | Postponed | Expand cross-Project analysis inputs | Baseline 2 |
| W35 | Normal | Closed | Every released entry has a consumer that reads it through the manifest | -- |
| W43 | Low | Withdrawn | Table-drive request validation | -- |
| W50 | Normal | Planned | Reconcile schema names with defined terminology | Batches with W51 |
| W51 | Normal | Planned | Resolve source-identity naming and suffix rules | Batches with W50 |
| W55 | Normal | Closed | Text and record parsing unified on `codess.timeval`; the `datetime.now` sites remain and batch with W67 | -- |
| W64 | Normal | Closed | Typing posture decided and enforced; `warn_return_any` recorded at 26 errors against W04 | -- |
| W65 | Normal | Planned | Consolidate remaining relay parameter groups | W04 (partly) |
| W66 | Normal | Planned | Configuration unification: table, `parents=`, help, types, the leaf mechanism, and the precedence sweep landed; a config file as a source remains | -- |
| W67 | Normal | Closed | Every relay takes an object; the builder/relay distinction is a test; the three structures share no field | -- |
| W70 | Normal | Planned | Re-partition documentation; remove cross-document redundancy | -- |
| W71 | Normal | Planned | Fatal channel done; `admin` and `query` now configure a sink and report start/done. Nine `warn` sites remain to convert | -- |
| W72 | Normal | Closed | One Event-record builder per adapter; no adapter constructs an Event dict outside it | -- |
| W73 | High | Analysis | Resolve or close the twenty-one open vendor decode gaps CoPlan records; Codex half answered by the protocol source | -- |
| W74 | High | Planned | Cursor Session times dropped; unread populated fields; two vendor facts to record | Retrieved-reference policy split to W79 |
| W75 | Normal | Postponed | Harness experiments for conditions no stored data records | Execution deferred; restart criteria on the item |
| W76 | Normal | Postponed | Characterise current Cursor terminal-agent storage; the decoded store is obsolete | Restart criteria on the item |
| W77 | Normal | Withdrawn | Time module -- W55 already specifies it | -- |
| W78 | Low | Closed | Guard the module-level import graph against cycles | -- |
| W79 | Normal | Postponed | Content policy for retrieved, attacker-influenced Artifact references | Needs a retrieval-bearing corpus |
| W80 | High | Closed | Read `composerData.modelConfig` for every composer, not only headered ones | -- |
| W81 | Normal | Postponed | Cursor Artifact evidence in adjacent key spaces: patch graphs, checkpoints, file snapshots | Restart criteria on the item |
| W82 | High | Closed | Tools carry unchecked SQL; a renamed column broke the mandated audit silently | -- |
| W83 | High | Postponed | Early-access release readiness | Postponed entire, including the licence split; restarts on the owner's licence decision |
| W84 | Low | Postponed | Characterise `selectedModels` parameters beyond `fast` and `effort` | Both observed ids are mapped; no third has appeared |
| W85 | Normal | Postponed | Composers older than the header retention window are unattributed by design | Handling can improve; the condition itself is vendor retention |
| W86 | High | Closed | Skipped and refused records are counted but not attributed | -- |
| W87 | Normal | Planned | Group the test corpus by subsystem; find superseded and uncovered cases | -- |
| W88 | Normal | Planned | Cursor KV decode: classify by content kind before parsing | -- |
| W89 | Normal | Planned | Path inclusion and exclusion belong in the discovery policy file; specification settled, not applied | -- |
| W90 | High | Closed | Scanned Projects are never ingested unless named again | -- |
| W91 | High | Closed | One authoritative Project record spanning scanned, ingested, moved, and removed | Structural half tracked on W14 |
| W92 | Normal | Planned | Event-kind aggregation: most volume is machine traffic, not human work | -- |
| W93 | Normal | Postponed | Session utilization: report counts and `surface_kind`, not a derived class | Link-detection design recorded; inclusion policy undecided |
| W94 | Normal | Planned | Four files carry the format number; two drift silently | -- |
| W95 | Low | Planned | Tighten message and comment wording against a worked example | -- |
| W96 | High | Planned | Project location changes: detect, report, and direct the operator | W14 (partly) |
| W97 | Normal | Planned | Read the Codex thread name; reconcile archive location with archive state | -- |
| W98 | Low | Planned | Ten field names still spell the algorithm rather than the value: `*_sha256` against the `*_digest` rule | Each is wire-format or a released document, so each costs a regeneration or a version bump |
| W99 | Normal | Closed | One tree `receipts/<kind>/`; the refresh reader globs `*.json` and the directory states the kind | -- |
| W102 | Low | Planned | Review the option classification against what each flag actually does: 110 flag-only, 34 default-only, 24 with a variable | The classification is recorded in CoNames and has not been critiqued per flag |
| W101 | Normal | Closed | `reasoning_fidelity` set by the adapter that read it; verified `summary` on Codex and `full` on Cursor in one store set | -- |
| W100 | Normal | Closed | One retention count, current included, read by both paths through one implementation; `--keep` and `create_snapshot(keep_total=)` override it per run | -- |

## Queue

One ordering. The reason for each position is a dependency or a stated cost,
not a preference.

| Rank | Item | Why here |
|---|---|---|
| 1 | **W05** | Unchanged, and now more clearly first: it is the only item whose output is evidence about whether the query surface answers real questions rather than machinery that supports them. The corpus was just rebuilt and audited, so the work starts against current data with no rebuild of its own. |
| 2 | **W67** | Promoted from 5. Its prerequisite landed -- the setting table declares each value once, so a policy object built at the command adapter no longer encodes duplication. It also carries the twelve remaining ambient clock reads, which are in four of its five relay modules. |
| 3 | **W04** (steps 3-4) | Steps 1, 2, and 5 landed, and step 5 found a real non-conformance on its first run. W35 is closed, so the per-vendor hazard fixtures the strict/diagnostic semantics need are now reachable and tested. |
| 4 | **W50 + W51 + W98** | The naming resolutions no format has yet carried, now three rather than two. All are wire-format, so they land as one regeneration or they cost three. |
| 5 | **W66** (config file) | Everything measured has landed, including the precedence sweep. What remains is admitting a config file as a source, which is a design question rather than a sweep and blocks nothing. |
| 6 | **W65** | W64 closed. W65's record-context cluster is adapter signatures, so it still wants W04's steps to settle first -- which is why it now trails rank 3 rather than sharing a row with a closed item. |

### Resuming: Project Location Changes

**Where the work stopped.** W96 is the open thread: the seven ways a Project's
location can change, of which three are handled and four are not. Read W96 for
the conditions, W14 for the identity fix underneath them, and this for what to
do first.

**Do these in order. Each is small and leaves the suite green.**

1. **Make one report directive.** `registry_check` finds an absent catalogued
   directory and says so; it should also print
   `codess catalog location retire --project-id <id> --directory <path>`. One
   finding, one command, no guessing -- and it is the pattern the rest follow.
2. **Detect the Claude slug split.** Two slug directories whose decoded paths
   differ, where one path is absent and the other live, are one Project's
   history. Report the pair and the `path_aliases` entry that joins them.
3. **Surface `sources_vanished`.** It is computed in the Project inventory and
   no command reports it. It decides whether a superseded store may be deleted,
   and getting that wrong is unrecoverable.
4. **Document `catalog relocate` as the pre-move step**, which is the only
   up-front direction that exists and is undocumented.
5. **Then W14's five steps**, which remove the restore-and-copy failure rather
   than reporting it.

**State at the pause.** The suite is green and lint and types are within their
recorded ceilings; the figures are read from `tools/quality_report.py`, which is
where a number that is wrong by the next change belongs. `project_inventory`
reports 0 Projects holding vanished Sources, `registry_check` 0 errors and 0
warnings, and `variable_reference --check` current. `catalog lifecycle`
reports 20 ingested and 1
worktree. `registry_check` reports 0 errors, 0 warnings, 1 note **when the
discovery variables are unset**, which is not the same as a clean result: the
layout checks do not run, and a skipped check currently reads as a passing one.
Configured, the same command reported 0 errors, 7 warnings, 14 notes. Making a
skipped check state that it was skipped is [Item Detail](#item-detail)'s
discovery-configuration work.

**Closed in the session that produced this**, so they are not re-derived: W86
(refusal reason codes reaching the store, aggregated), W90 (scanned and never
ingested), W91 (reconciled lifecycle view and its command), W78 (module-level
import cycles), W82 (unchecked tool SQL). W80 and W74.1 landed earlier.

**Two conditions on the development machine that are evidence rather than
defects**, and should not be "fixed" by a later reader: one archived format-4
store is the only remaining record of 22 vendor Sessions the vendor has pruned,
and one Project pair is a linked git worktree recorded as such.

**The archived store was located and protected**, because the earlier
description of it did not match what is on disk. Measured across all 21
published store sets, **every recorded Source still resolves** -- 0 vanished --
so nothing in the registry holds unreproducible evidence. The two stores W14
identified (154 Sources with 122 vanished, and 8 with 8) are **gone**: neither
survives anywhere on this machine. What does survive is a different store, at
`ZK/ZKs`, found only because a test scratch tree happened to retain it:

| Measure | Value |
|---|---|
| Sessions | 22 |
| Events | 20,235 |
| Recorded Sources | 22, of which **22 vanished** |
| Format | 4 |

Its vendor directory holds no transcripts, it has no catalog entry, and its
working store under the checkout holds zero Sessions -- so the copy in test
scratch was the only record. It is now at
`~/.codess/archive/ZKs-coschema4-20260812T072113Z`, read-only by permission,
with an `ARCHIVE.md` stating what it holds and why deleting it is
unrecoverable. The original was left in place rather than moved.

**What a recreation cannot re-derive, captured before it runs.** The catalog's
reviewed decisions are in `catalog/inventory/dispositions-20260824.json`: one
`worktree_of` relation (ZeroPerf to Zero400) and 13 Cursor workspace bindings
across 8 Projects, every one `approved`. Cursor keys its data by an opaque
workspace hash rather than by path, so a binding is what connects a composer to
a Project at all.

Ten are ordinary `local_workspace_path_binding` rows that a re-ingest can
rediscover by matching `workspace.json`. **Three cannot be rediscovered**, and
they are the reason the capture exists:

| Relation | Count | Asserts |
|---|---|---|
| `project_path_alias` | 2 | A different path is the same Project: `ZeroMac` is Zero400, `zerowallet400` is zerowalletmac |
| `remote_workspace_local_binding` | 1 | An SSH remote URI is this local Project |

No vendor store records either fact. `zerowalletmac` additionally holds three
distinct workspace hashes for one path -- Cursor opened a new workspace on
separate occasions -- and only the bindings record that they are one Project's
work.

**The recreation ran, and it was already overdue.** Every catalogued Project
was reingested with `--force` and republished, with no error and no Project
rejected. The resulting figures are the [Corpus Baseline](#corpus-baseline),
which exists to price a rebuild and states where each is read from; repeating
them here would be a second copy that goes stale first.

**The rebuild was not caused by any change made here.** `PRAGMA user_version` is
still 9, but the *contract digest* had moved: the schema files were last
committed 2026-08-24 and the stores were published 2026-08-22, so every store was
already unreadable by `require_store` before this session began. `codess query`
said so directly, which is the gate working -- a store written under a superseded
contract is refused rather than read as though it agreed.

**The corpus grew rather than merely moving**, which is the fact worth keeping
rather than the totals. CodeSess went from 70,571 to 74,839 Events and ZeroPerf
from 39,417 to 40,998 across the three days between publications: two measured
pairs, retained because they demonstrate what a rebuild does rather than what the
store currently holds. A rebuild reads what the
Sources hold now, which is the property that makes it safe when they are intact
and destructive when they are not.

**Every reviewed disposition survived**, checked rather than assumed: the
ZeroPerf `worktree_of` relation and all 13 Cursor workspace bindings are intact,
21 catalog entries in and 21 out, and **no path is claimed by two Projects** --
so W14's minting defect did not recur. The catalog is keyed by `project_id` and
written only when identity changes, which is why a reingest leaves it alone.

**The archive was not reached.** `~/.codess/archive/ZKs-coschema4-…` still holds
its 22 Sessions and 20,235 Events and is still read-only, which is what the
permission is for: a rebuild sweep that reached it would have destroyed the only
record of them.

**The 27 superseded snapshots were pruned**, after both checks Operations
requires. Counts alone can mislead -- two stores for one Project once read as
one superseding the other while the older held two months the newer did not --
so the date range was compared as well: **0 superseded snapshots covered time
its current one does not**. The plan reported `safe_to_apply`, no blocking
references, and all 21 current pointers present in `keep` and absent from
`delete`.

Applied with a receipt at `~/.codess/reports/prune-20260825.json`, whose
`plan_digest` matches the plan that was reviewed, so what was applied is what
was inspected, and `remaining_candidates` is 0. The count deleted and the bytes
reclaimed are in the receipt rather than here: they describe one run, and a run's
figures cannot close an item or be re-derived once the snapshots are gone.

**The archive was not reached**, verified after the fact rather than assumed: it
still holds its 22 Sessions and 20,235 Events and is still read-only. A prune is
one of the three operations that can destroy a store whose Sources are gone, and
the permission is what stops it.

**What this changes about the rebuild.** A full recreation is safe for the
published set, because nothing there depends on a Source that is gone. The
hazard was real and sat outside the registry, which is the argument for running
the inventory before the rebuild rather than trusting the recorded figure: the
figure named two stores that no longer exist and missed the one that does.

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
| **W74** | W74.1 closed and corpus-verified; the Cursor field mapping landed in Sprint 2. `duplicate_of` needs a column, so it is Sprint 1 with the rest of the wire-format change. |
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
| Published Project store sets | 21 | `~/.codess/projects/*/current.json` |
| Sessions | 434 | `SELECT count(*) FROM sessions` across published stores |
| Events | 266,219 | `SELECT count(*) FROM events` across published stores |
| Vanished Sources | **0 of 403** | Each published store's `source_path` tested against disk |
| Store bytes | 1.8 GB across 21 snapshots, one per Project, with 0 superseded | Snapshot directory sizes; `tools/snapshot_inventory.py` |
| CoSchema format | 9 | `PRAGMA user_version` |
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
| Relay parameter consolidation | Done. All five relays take an object; `test_a_wide_signature_is_a_builder_or_takes_a_structure` holds the rule. | W67 |
| Configuration unification | Step 3 closed ahead of the table: `--store`, `--dirs`, and `--resource-policy` each declared one type, and a test holds the rule. Steps 1-2 and 4-6 not begun. | W66 |
| mypy strict flags | Decided on measured cost: `disallow_untyped_defs` and `strict_optional` enabled at zero cost, `warn_return_any` deferred at 26 errors against W04. The count returned to its 80 baseline by repair, not reclassification. | W64 |
| Record-context parameter group | Identified; blocked behind W04 because it changes adapter signatures. | W65 |
| Docstring summaries (`D205`) | The rule is selected and its findings are a recorded ceiling, not zero. Four docstrings in `field_state` were rewritten as the worked example; the rest fall as files are edited. | -- |
| Command-layer help text | 76 distinct flag names in `admin_cmd` carry no help; `project.py` documents all of its own. Two were written where a verification step was being disabled; `parents=` would carry one declaration to every subcommand. | W66 |
| Event-record builders | `cursor` has no module-level builder and `cc`/`codex` have sites that bypass theirs. Found by `pylint R0801`, not started. | W72 |
| Deep audit adoption | `tools/deep_audit.py` runs and logs; nothing yet acts on its DESIGN tier. Counts are read from the tool rather than recorded here. | -- |
| Time parsing consolidation | `codess.timeval` is the standalone module: `epoch_ms`, `parse_iso`, `iso_to_ms`, `to_iso`, `month_key`, `is_sane`, `now_ms`, and `now_iso`. `codess.wallclock.system_clock` is the ambient clock the last two are handed, and is a separate module because `timeval`'s constraint forbids a clock read inside it. Three tests assert the constraints -- no `codess` import in `timeval`, no ambient clock in `timeval`, and no `datetime.now` anywhere in the package outside `wallclock` and `reporting.clock`. **Done:** the `fromisoformat` callers, the `epoch_milliseconds` importers, and 44 of the 56 clock reads. **Remaining:** 12 reads in four relay modules, listed in the test's `DEFERRED` set -- threading a clock through them changes the signatures W67 rewrites, so doing it first converts them twice. | W55, W67 |
| Cursor Session times | **Closed in code, unverified against the corpus.** The header fallback is written and the suite covers it; the 2 Sessions of 86 that carry no `started_at` are still null in the published stores, because closing them needs the reingest that W74.3's column change also needs. | W74.1 |
| Cursor field mapping | The Sprint 2 pass landed: timings, error details, terminal cwd, symbol and file links, todos, code blocks, `context` leaves, and the request and response identifiers. **Remaining:** `richText` mention nodes and `isAgentic`, both populated on 390 of 4,984 sampled bubbles. | W74.5a, W79 |
| `duplicate_of` reference | Decided and not built. Needs a column, so it batches with the next wire-format change rather than landing alone. | W74.3 |
| Mechanical enforcement | Import boundaries, SQL ownership, module-level cycles, rejection vectors, subprocess coverage, and now mapping-profile conformance each have a check. **Remaining:** the strict/diagnostic semantics of a non-conformance are not yet equal across vendors (W04 step 3), which needs the per-vendor hazard fixtures W35 inventories. | W04 |
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
| 1 | **Done.** `_check_mapping_conformance` calls `validate_mapped_event` in `store.upsert_event`, beside the unmapped-semantics diagnostic, so every Event passes it regardless of vendor. | Done: `TestMappingProfileConformance` routes an undeclared rule through each of the three adapters and asserts one `mapping_profile_nonconformance` row each. |
| 2 | **Done.** `mapping.CandidateEvent` declares the shape crossing that boundary: four required keys, matching the released contract's `mapped_event_required`, and the rest `NotRequired`. | Done: mypy reports `typeddict-item` on a candidate missing a required key. |
| 3 | Give the boundary diagnostic and strict modes with the same semantics for all three vendors, replacing the Claude-only strict-mapping coverage. | Equivalent partial, malformed, unsupported, and hazard fixtures per vendor produce equivalent dispositions. |
| 4 | Record each non-conformance as a `mapping_diagnostics` row rather than only raising, so diagnostic mode is inspectable after the fact. | Diagnostic-mode ingest of hazard fixtures yields rows carrying the reason codes the profiles declare. |
| 5 | Extend `tools/decode_audit.py` with a per-vendor conformance count, so the current zero is re-measurable rather than observed once. **Not started**, and the smallest remaining piece. | The audit reports conformance beside its existing invariants and exits nonzero on any failure. |

**What step 1 settled that the item did not anticipate.** The check is scoped to
Events that carry a `mapping_rule`. An Event without one has no profile to be
measured against, and the unmapped-semantics diagnostic recorded beside it
already reports the condition -- validating it anyway reported one condition
under two reason codes and raised every fixture's diagnostic count by one, which
is what twelve suite failures showed on the first wiring. The boundary is also
*after* the insert rather than between decode and insert: a diagnostic row
references `event_id`, so recording one before the row exists cannot link it.

**Strict mode raises `SchemaContractError`, not `SourceCompatibilityError`.** The
latter is defined in the Claude adapter, so a vendor-neutral boundary importing
it would depend on one vendor and invert the dependency the check exists to
remove. A profile violation is a contract violation, which is what the neutral
class already names.

**Ordering within the item.** Steps 4 and 3 are what coverage reporting depends
on: a loss report states what was *not* mapped, and diagnostic rows are that
record -- without them the report re-derives non-conformance by re-decoding,
which is a second decode path. Step 3 makes the counts comparable, since a
vendor that raises where another tolerates gives the same figure two meanings.
Steps 1 and 2 feed nothing else and can land independently. Step 5 overlaps
coverage reporting in presentation and folds into it.

#### Where This Item Stands

**Steps 1 and 2 are in the code.** `store._check_mapping_conformance` calls
`validate_mapped_event` at one vendor-neutral boundary, and `mapping.CandidateEvent`
declares the shape crossing it. `TestMappingProfileConformance` routes an
undeclared rule through each of the three adapters and asserts one diagnostic
each, so the property the item was opened for is now tested rather than held by
construction.

**Step 5 landed, and immediately found what it was built to find.**
`decode_audit` now reports `mapping_conformance` per store: the profile, the
declared and in-use rule counts, the undeclared ids, and the declared-but-unused
ones. Run against the corpus it reported one non-conformance -- `cursor.reasoning`,
emitted by `adapters/cursor` at its `mapped(...)` call site and absent from
`schema/mappings/cursor.json`.

The rule is legitimate: it maps a Cursor bubble's `thinking` to
`message.reasoning_summary`, with a model Actor and a reasoning content role. The
*profile* was wrong, not the decoder, so the rule is declared and the schema
manifest refreshed.

**This is the drift the item predicted, in the place it predicted.** W04 records
that Cursor is the one adapter where a new id needs no edit to a central table --
seven literals at seven call sites -- and says to look there first if the
conformance check ever reports an undeclared id. It did, and that is where it
was. The follow-on the item leaves open is whether Cursor gains a dispatch table;
the check catching this without one is evidence that it does not need one.

**Step 5 also justifies itself against step 1.** The check at write time refuses
a non-conforming Event as it is stored; the audit at read time states whether a
store *already holds* one, which a store written before the check existed can.
Enforcement and measurement are different jobs, and only the second could have
found this.

**Steps 3 and 4 are blocked, and on a named item rather than on effort.**
Equivalent partial, malformed, unsupported, and hazard fixtures *per vendor* are
what make a strict-versus-diagnostic disposition comparable, and inventorying
them is W35 -- which was Low/Postponed on the assumption that nothing waited for
it. Something does now.

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

**Cost.** No rebuild: current-format stores exist, so the work begins against
current data rather than regenerating it.

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

#### Diagnosed

`_resolve_project_id` consults three sources in falling authority: the
Project's own binding at `<project>/.codess/project.json`, then a catalog entry
already claiming that exact location, then a new UUID.

**The catalog fallback exists precisely for this case and was never reached.**
Both duplicate entries record the same `locations[].path`, so the search would
have matched -- but the binding file returns first, and on this machine the
binding named the *new* identity. Once minted it is authoritative for every
later run, which is why re-ingesting nine Projects produced nine duplicates
once and never again.

**What made the binding wrong is the open question.** It is stored inside the
Project directory, so it is lost whenever that directory is cleaned, re-cloned,
or restored from a copy predating it -- and losing it is indistinguishable from
a Project that has never been ingested. The catalog fallback is the intended
repair, and it cannot run because a fresh binding is written before anything
asks whether the catalog already knows the path.

#### Proposed Resolution

**The registry becomes authoritative; the in-project file becomes a cache.**
That inverts the current order and removes the failure mode rather than
guarding it, and the reason is a property neither file shares: the registry
outlives the working tree. A Project directory is cleaned, re-cloned, or
restored from a copy predating its binding, and each of those loses an identity
that the registry still holds.

**Steps, in dependency order. Each leaves the suite green.**

1. **Add a registry-side binding index.** `~/.codess/project-bindings.json`
   mapping resolved path to `project_id`, written by the same call that writes
   the in-project file today, so both exist during the transition. No reader
   changes yet.
2. **Backfill it from the catalog**, which already records `locations[].path`
   per Project. This is derivable rather than observed, so the index starts
   complete for every Project ever published.
3. **Invert the resolution order** in `_resolve_project_id`: registry index,
   then in-project binding, then catalog locations, then mint. The in-project
   file stops deciding and starts confirming.
4. **Report disagreement rather than resolving it silently.** Where the
   in-project file names a different identity than the registry, that is a
   Project that was moved, copied, or restored -- all real conditions with
   different answers, and none that a decode should choose. Warn and take the
   registry's.
5. **Retire the in-project file as authority**, keeping it written for a reader
   who has a Project directory and no registry. Mark it in the file itself, so
   a later maintainer does not restore its precedence by reading the code.

**What each step costs.** Steps 1 and 2 are additive and reversible. Step 3 is
the behaviour change and is where a test must pin the new order. Steps 4 and 5
are documentation and a warning.

**Why not simply check the catalog first.** That was the cheaper option and is
the guard now in place: minting warns, and a binding disagreeing with the
catalog warns. It does not fix the case that produced the nine duplicates,
because the binding named a *valid* identity -- freshly minted -- and no check
can tell a legitimately new Project from one whose binding was lost. Only a
record that survives the loss can.

**What this does not solve.** A Project ingested on one machine and moved to
another still mints, because the registry is per-machine. That is correct --
`location_id` is machine-scoped by design -- and the catalog's
`path_aliases` is where a cross-machine identity would be stated. Out of scope
here and worth naming so it is not mistaken for a gap in this fix.

#### What the Recreation Settled, and What It Did Not

**The reingest path is proven and the defect did not recur.** Every catalogued
Project was reingested with `--force` on 2026-08-25 and the catalog came out with
the same entries it went in with: no path claimed by two Projects, ZeroPerf's
`worktree_of` relation intact, and every Cursor workspace binding retained. The
catalog is keyed by `project_id` and written only when identity changes, which is
why a reingest leaves it alone.

That is a real result and a narrow one. It exercises the path the nine duplicates
came from -- repeated `codess ingest --dir <path> --force` against Projects that
already had catalog entries -- and shows the guards added since hold there.

**What it does not settle is the item's actual subject.** W14 is about *direct
library writes*: a caller reaching `store` or `project_catalog` without going
through a command, which is the path that has no guard and which no CLI run
exercises. A reingest proving the CLI is safe says nothing about a library caller
minting an identity, because they are different entry points.

**So the disposition is unchanged.** The item stays open, at the same priority,
and the recreation is recorded here as evidence about one path rather than as
progress on the item.

**Evidence to close.** Separate vendor stores cannot silently create unrelated
Project identities for one repository; re-ingesting a Project that already has
a catalog entry reuses that entry; and a path carrying a reviewed disposition
is never claimed by a new Project without the operator being told.

#### Disposition of the Nine Duplicates

**The question that decides it is whether the vendor Sources still exist**, not
which store is newer. Checked per store, by testing whether each recorded
`source_uri` is still a file on disk:

| Store | Format | Sources | Still on disk | Vanished | Events |
|---|---|---|---|---|---|
| A | 4 | 154 | 32 | **122** | 29,161 |
| B | 3 | 8 | 0 | **8** | 7,398 |
| Other seven | 3-4 | 1-4 each | all | 0 | 20,663 |

**Only two of nine hold evidence that cannot be regenerated.** 130 vendor
source files no longer exist -- Claude prunes its own transcripts -- so those
two stores are the last remaining record of 36,559 Events. The other seven
duplicate what the current Sources still produce and can be discarded.

**Both stores A and B are gone**, established by scanning every SQLite store
under the work root and the registry: neither the 154-Source store nor the
8-Source store survives anywhere on this machine, so the archive disposition
below was never carried out and can no longer be. The 36,559 Events are lost.
Recorded because a disposition that reads as pending invites a later reader to
go looking for stores that are not there -- and because it is the measurement
that argues for archiving on discovery rather than on a later scheduled pass.

A **different** unreproducible store was found and archived in the same sweep;
it is described under [Resuming](#resuming-project-location-changes) and is not
one of these nine.

**Disposition:**

1. **Seven stores: dump.** Their Sources are intact, the current-format store
   already holds the same evidence, and retaining an unreadable copy of
   reproducible data costs disk for nothing.
2. **Two stores: archive, do not dump.** Retain outside the active registry,
   where they are not queried and not carried forward by a format change.
3. **Restore the `worktree` relation** the new Project lost.

**This corrects an earlier over-broad claim on this item**, which recommended
retaining all nine on the strength of one measurement. Applying the same test
to the rest showed seven were reproducible. The rule that survives is narrower
and checkable: **a superseded store is retained only where a recorded Source no
longer exists**, which is a query rather than a judgement.

#### Archive Rather Than Retain In Place

Keeping unreadable stores in the active registry has three costs and no
benefit: `require_store` refuses them, so they answer no query; they are
counted in registry size and in every inventory; and each format change invites
the question again.

**The shape.** An archival area outside `~/.codess/projects`, holding the store
directory as-is plus a manifest stating why it was kept -- which Sources
vanished, when, and which current Project superseded it. Nothing reads it
automatically; recovering evidence from it is a deliberate act.

**What makes this safe to do now.** The evidence for keeping a store is
recorded as data (the vanished-source count) rather than as a memory, so the
decision is re-checkable. Without that, archiving is indistinguishable from
losing track of something.

**Then start afresh.** With the two archived and seven dumped, the active
registry holds only current-format stores built under current rules, and the next
format change costs one reingest per live Project rather than a decision per
stale one.

**Cost.** Independent: no item blocks it and none waits on it. The nine
duplicates are annotated through existing catalog operations rather than needing
a migration.

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

**Closed.** `tests/test_released_fixtures.py` resolves every entry *through*
`load_manifest` rather than by path, which is the distinction that matters: a
test opening a known path keeps passing after the manifest stops naming the file,
and the manifest is what a package consumer resolves.

**The count on this item was stale.** Six of the ten fixtures had a reader, not
two. Four did not: both `store_meta` compatibility fixtures, `maximal/event`,
and `hazard/cursor-tool-former` -- which is the one W04's strict/diagnostic work
needs, so the gap and the dependency were the same fixture.

**Writing the tests found the defect the gap allows.** `maximal/event` carries a
`timestamp` field, which the `events` table has not had since it became
`event_at`. The fixture is still valid -- `store.upsert_event` accepts `timestamp`
as the vendor spelling -- but nothing had checked either way, which is what an
unreferenced fixture means. It is now asserted against `mapping.CandidateEvent`,
the contract it actually describes.

**A fixture added to the released set is covered by construction**: the
parametrized consumer derives its cases from the manifest, so a new entry is
resolved and parsed without anyone remembering to add a test.

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

#### Decided on Measured Cost

Each flag was enabled alone, the error count read, and the flag kept where the
count did not rise. The method is what makes the answer checkable: a flag
argued for on where errors *seem* to concentrate is how `strict_optional`
reached this item attributed to a decode boundary it has nothing to do with.

| Flag | Measured | Disposition |
|---|---|---|
| `disallow_untyped_defs` | 10 findings, all variadic bags or parameters whose type is spelled elsewhere in the package | **Enabled.** Annotating them exposed four optional-handling defects the untyped signatures had hidden; with those repaired it costs nothing |
| `strict_optional` | 0 -- it is mypy's default. Disabling it *raises* the count by 31 | **Enabled.** States an existing guarantee rather than adding one |
| `warn_return_any` | 26, concentrated in `query_api` (4), `schema_contract` (3), `snapshot`, `project`, `project_catalog` (2 each) | **Not enabled.** These are the `Any` vendor JSON legitimately carries until validated, which is what W04 types |

**The four defects the annotations exposed**, each repaired rather than
suppressed, because a flag whose findings are silenced measures nothing:

| Where | Was | Now |
|---|---|---|
| `ingest_publication` | `catalog` set to `None` when no vendor changed, then passed to a reader expecting a dict | Defaults to an empty catalog, which is what the loop would read anyway |
| `snapshot.create_snapshot` | `raw_store` declared required and passed `None` whenever the run was not sealing | Declared optional; the seal path raises if it is absent, which is the only path that resolves it |
| `adapters/cursor` | Progress emission read `composer_start_tick` unguarded where a sibling read at line 555 guards it | Guarded, matching the sibling |
| `cli/ingest_cmd` | `roots` is `None` exactly when `err` is set, a correlation the checker cannot follow | The absent case is stated rather than implied |

**Evidence to close.** The enabled flag set is recorded with the reasoning for
each; `Any` appears only where a stated rule permits it; the type count falls
rather than being reclassified; `tools/quality_report.py` gates on the baseline.

**Closed.** Two flags enabled at zero cost, the third recorded with its figure
and its owning item. The count returned to its baseline of 80 rather than being
reclassified: the four defects were repaired, not ceiling-raised.

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
states which wins. `--store` and `--dir` each appear in four modules;
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
inherited by every subparser that lists it. So a new subcommand that needs `--store` gets it the only way the
surrounding code demonstrates: by writing the line again. Twenty-two
subcommands need it, so the line exists twenty-two times. Each addition was locally correct and
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
places: `--store`, `--source`, `--force`, `--min-size`, and `--raw-mode` are
among them, which is the same set the duplication concentrates in. A flag
declared twenty-two times with no help is twenty-two chances to write one and none
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
| 3 | **Done.** Resolve the three `--store` variants into one declared type. | Done: `test_a_flag_name_declares_one_type` |
| 4 | Replace the `getattr(args, ..., None) or CONSTANT` sites with one accessor that applies the stated precedence. | A test covers each precedence pair: flag over env, env over built-in |
| 5 | State the import-order constraint once, and give the two flags that work around it a supported path. | The `os.environ[...] = "1"` writes in `project.parse_and_run` are gone |
| 6 | Admit a config file as a source, between built-in and environment. | A file-set value loses to both the env var and the flag |

**Step 3 is a real defect, not a tidy-up, and it is now closed.** The flag is
`--store` since the rename; re-measured, it is declared **22 times** across two
modules in three forms:

| Form | Where | Consumed by |
|---|---|---|
| `type=Path, default=STORE_ROOT` | `admin_cmd`, 20 subcommands | `args.store_root` directly, so it must be a `Path` |
| `type=Path, required=True` | `admin_cmd`, one subcommand | `args.store_root` directly |
| `type=str, default=None` | `project.py` | `resolve_store_root`, which accepts either |

A caller moving between command families got a different type from one flag
name. Behaviour was right -- `resolve_store_root` normalizes both -- and that is
precisely what made the divergence invisible. `project.py` now declares `Path`,
matching the other 21.

**Extending the check found four more, of which one was the same defect.**
`--dirs` and `--resource-policy` were `str` in `project.py` against `Path` in
`admin_cmd`, and are now `Path`. `--resource-policy` also carried
`metavar="JSON"` in one declaration for an argument that is a file path, which
named the file's content rather than the argument.

**Three flag names were reused for genuinely different subjects.** Two are
renamed; the third stays, and the difference between those cases is the rule:

| Was | Now | Because |
|---|---|---|
| `--project` (a directory) | **`--directory`** | The spelling named three subjects at once -- a reference under `catalog decide`, a repeatable reference list under `refresh`, and a path on disk. `--project` keeps the two that are references |
| `--selection` (a state) | **`--select`** | The value is a selection state and the flag now names the act of filtering by one |
| `--selection` (a file) | **`--file`** | Under `baseline freeze` the selection is already the subcommand's subject, so the flag names which part of it |
| `--since` | unchanged | **Both spellings are correct for their command.** A git date expression is what `rev-list --since` accepts and a Unix millisecond timestamp is what an `_at` column holds; each matches the vocabulary of the surface it belongs to, and renaming either would make one command disagree with the tool it wraps |

Verified by dumping `--help` for all 45 parsers before and after: exactly five
subcommands changed, each by exactly the intended rename, and no other option
moved.

**Applied across the tools as well, because a caller does not change vocabulary
at the `tools/` boundary.** Four scripts took a Project directory and called it
`--project` -- `apply_and_verify`, `retire_project`, `validate_snapshot`, and
`demo_model_metrics` -- and `catalog location add|retire` called one `--path`,
which says only that the value is a path, a thing `type=Path` already says. All
five are `--directory`.

**Two further one-subject-two-spellings cases**, found by grouping declarations
by `dest` rather than by name: `tools/demo_model_metrics` spelled the durable
store `--store-root` where the CLI spells it `--store`, and
`tools/freeze_reviewed_baselines` kept `--selection` after the command it
mirrors became `--file`. Both now match.

**`--dir` is exempt and is not a lapse.** It is the documented Project selector
for `scan`, `ingest`, and `query`, appearing 33 times across README and
Operations, and it is repeatable where `--directory` is singular and required.
Two names because they are two things: a selector that accumulates a set, and
the one directory a command operates on.

`test_a_directory_valued_flag_is_named_directory` holds the rule over `src/` and
`tools/` together. It keys on `type=Path`, which is what separates a directory
from a reference: `catalog decide --project` and `refresh --project` take an id,
a name, or a path as text, and keep the reference spelling.

`test_a_flag_name_declares_one_type` holds the rule and now exempts only
`--since`, with the reason on the exemption. It checks the *declared* type
rather than any resolver, because a resolver accepting both is what hides the
condition.

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

**Scope check**, re-measured by parsing both files rather than by grep, since a
grep counts a flag inside a help string. 259 `add_argument` calls across exactly
two files; 166 distinct long flags of which **32 are declared more than once**;
133 `getattr(args, ...)` sites across `src/`, of which 3 take the
`or CONSTANT` fallback form. The duplication is concentrated -- `--store` 22,
`--output` 11, `--project-id` 9, `--source` 5, `--project` 5 -- so five names
account for more than half of it.

#### Execution Order

The six steps above are the work; this states where they stop and what splits.

| Order | Step | Boundary |
|---|---|---|
| 1 | **Done.** `codess.settings` declares one row per setting: name, flag, variable, composition rule, leaf visibility | Done: `tests/test_settings.py` asserts no name, flag, or variable repeats, and that every row's variable exists in `config`'s table |
| 2 | **Partly done.** Seven shared options inherit via `parents=`; the table itself is not built | Done for those seven: all 45 subcommands accept the same options, verified by dumping `--help` before and after |
| 3 | **Done.** Every option renders help | Done: 90 declarations gained one, which is what the work was; `test_every_command_option_carries_help` reads the built parser and holds the condition thereafter |
| 4 | **Done, ahead of the table.** Resolve `--store`'s three incompatible forms | Done: one declared type per flag, asserted by `test_a_flag_name_declares_one_type` |
| 5 | The precedence accessor, replacing the `getattr(args, ...) or CONSTANT` sites | A test per precedence pair |
| 6 | **Done.** The leaf-visible mechanism | Done: `apply_leaf_visible` performs the writes from the table, and both hand-written assignments are gone |

**Step 2 splits in two, and the reason is its own check.** Emitting declarations
from the table and adding 76 help strings cannot both hold `--help`
byte-identical -- the strongest check in the item would have to be dropped to do
them together. Emit first and verify identity, then populate help as a diff that
is only help text.

**`parents=` ran second, and also did not need the table.** Seven shared
options are now declared once on a parent parser and inherited: `--store` (was
22 declarations, 19 byte-identical), `--output` (11, all identical),
`--project-id`, `--source`, `--project`, `--policy`, and `--reviewed`. Total
`add_argument` calls fell from 259 to 219.

**The refactor is behaviourally inert, and that was checked rather than
assumed.** `--help` was dumped for all 45 parsers before and after, and every
subcommand accepts exactly the same option set. What did change is help text:
the seven shared options each carry one now, which is the point -- one
declaration carries one help string to every inheritor, so documenting them is a
single edit rather than 22.

**A form that genuinely differs keeps its own line.** `--store` is
`required=True` for one command, one `--project-id` is repeatable, `--catalog` is
required for two commands and defaulted for a third, and `--apply` carries a
different help string per command because it enables a different action.
Inheriting any of those would change what that subcommand accepts, which is a
behaviour change wearing a deduplication's clothes. `catalog candidates` declares
its own `--source` for the same reason: it takes a comma spec where the shared
one takes `choices`.

**A type convention, stated because 84 declarations already follow it.** A
filesystem path is `type=Path`; everything else omits `type` and takes
argparse's `str`. An explicit `type=str` is reserved for the case where the
argument is a string *and* a reader would otherwise assume a path -- `--source`
is a comma-separated vendor spec, `--out` uses `-` as a stdout sentinel that
`Path` would turn into a relative file named `-`. Both now say so in a comment.
`--content-policy` was `type=str, metavar="JSON"` for an argument the consumer
wraps in `Path(...)`; it is `type=Path, metavar="PATH"`.

**Direct reads are reconciled with the resolver.** `admin_cmd` read
`args.store_root` at 24 sites and hand-rolled `.expanduser().resolve()` at two of
them -- which is what `resolve_store_root` does. Both now call it. The remaining
direct reads are fine: argparse applies the `STORE_ROOT` default, so the value is
already a resolved `Path` by the time they see it. The resolver exists for the
case argparse cannot cover, which is a value that arrives as a string or unset.

**What the table owns, and what it deliberately does not.** `codess.settings`
holds one row per setting -- name, flag, variable, whether it composes, whether a
leaf module reads it -- and `resolve` applies one stated precedence: **flag, then
variable, then built-in**, each narrower than the last. The *value* of a default
stays in `config`, which resolves it from the same variable at import; putting it
on the row as well would create the second declaration the table exists to
remove. The row owns the name and the rule; `config` owns the value.

**A boolean composes rather than overrides**, and that is not an inconsistency.
`--force` with `CODESS_FORCE=0` is force, and so is `CODESS_FORCE=1` with no
flag, because a `store_true` flag cannot express *off* -- treating its absence as
an override would make the variable unsettable from any shell that also passes
flags, which is every shell that runs the command. This is `flag_or_env`'s
existing behaviour, now stated rather than repeated at ten sites.

**Three shapes answered one question before this**, and one of them said nothing:
`flag_or_env` at 10 sites, `getattr(...) or CONSTANT` at 3, `bool(getattr(...))`
at 16, and a bare `getattr(args, name, None)` at 133 whose precedence a reader
could not recover. The `or` form also cannot express a zero: `--days 0` means all
time, and `0 or DAYS` is `DAYS`.

**The leaf-visible mechanism is declared rather than worked around.** `fileio`
and `schema_contract` read their variable directly, because a leaf module cannot
import `config` without a cycle, so a flag reaches them only by writing that
variable. Two hand-written `os.environ[...] = "1"` assignments did this;
`apply_leaf_visible` now does it from the table and *returns what it wrote*, so a
bypass is reported rather than silent -- both settings disable a verification
step, which is where an operator most needs telling.

**Declaring it found an asymmetry.** `CODESS_NO_HASH` was in `config`'s env
table and `CODESS_NO_CONTRACT_CHECK` was not, so two settings of the same kind
were declared in different places and only one was visible to a reader of that
table. Both are there now.

**Every option carries help.** 90 declarations gained a string -- the figure
that bounded the work, obtained by parsing `add_argument` calls that carried no
`help`. `test_every_command_option_carries_help` reads the *built parser* rather
than the source, because an option inherited from a shared parent is declared
once and must render documented everywhere it appears; the current count of
undocumented options is what that test asserts rather than something to write
down.

**Type unification ran first, and did not need the table.** The three forms
were a defect the table would have fixed as a side effect; fixing it directly
took one declaration per flag and a test, and leaves the table free to be
introduced for what only it can do -- one declaration, one precedence, one help
string. What the table still owes is the *default* and *precedence* half: the
type is now consistent, and where a value comes from is not.

**What remains is tidiness plus one hazard.** Steps 1-3 remove duplicated
declarations and document 76 undocumented flag names, neither of which can
produce a wrong value. The hazard left is step 5: a default resolved in up to
four places with nothing stating which wins, so a flag, an environment variable,
and a constant can each be right about a value and disagree about it. Stop after
step 5 if the work stops early.

**Step 6 of the original table -- a config file as a source -- is deferred.** It
is the only piece that adds a precedence *level* rather than documenting existing
ones, and the only one with no measured defect behind it. It costs less once the
table it would feed exists.

**`ingested_projects.json` -> `projects_state.json` waits for the recreation.**
The rename touches a file in the machine's durable store, so applying it before
means writing migration code for a file the recreation regenerates anyway. The
code-level renames carry no on-disk consequence and ride with step 1.

#### What Remains

Five of the seven pieces landed. What is left is one mechanical sweep and one
addition, and neither blocks another item:

**The sweep ran.** Every setting that has an environment variable now resolves
through `settings.resolve`: the nine `flag_or_env` calls, the three
`getattr(...) or CONSTANT` fallbacks, and the hand-written
`MIN_SIZE if raw is None else raw`. `flag_or_env` had no callers left and is
removed -- it was the older spelling of the table's boolean rule, and keeping
both would have been the duplication this item exists to end.

`resolve_store_root` now calls `resolve` for its precedence and keeps only its
normalization, which is what it uniquely adds: a declaration may supply a `Path`
or a string, and an empty string is not a path.

**The remaining `getattr(args, ...)` sites are not unstated precedence.** They
read report-mode selectors and per-command options -- `--sessions`,
`--permissions`, `--snapshot-policy` -- which have no environment variable, so
there is no precedence to state. Verified by intersecting every `getattr` name
against `config`'s declared variables: `store_root` was the only overlap, and it
is now routed.

| Remaining | Scope | Why it is not done |
|---|---|---|
| A config file as a source | None yet | It adds a precedence *level* rather than documenting existing ones, and it is the only piece with no measured defect behind it. Deciding where a file sits relative to a variable is a design question, not a sweep |

**Evidence to close.** One declaration per setting names its flag, variable,
default, and type; precedence is stated and tested; no module reads `os.environ`
for a declared setting except through the leaf-visible mechanism; a flag name
appears in exactly one module; and no call site restates a precedence the table
already states.

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

**Twelve ambient clock reads ride with this item.** `baseline_operations`,
`catalog_operations`, `refresh_operations`, and `review_project` are the four
modules still reading `datetime.now` directly, and they are four of the five
relays converted here. Take `system_clock` on the policy object rather than
threading a separate parameter: the clock is decided once before the first
Project, which is the same lifetime every other field on that object has.
`tests/test_timeval.py` names them in `DEFERRED`; remove each name as its module
converts and the test holds it thereafter.

**`refresh_candidates` is the one that needs a new structure.** The other four
are served by splitting `ChildInvocation`; its ten discovery parameters have no
existing home, which is what `DiscoveryPolicy` is for. Build it last, so the
pattern is established before a new type is introduced.

#### Every Relay Converted

**All five are done**, and the measurement that separates a relay from a builder
is now a test rather than a note. `test_a_wide_signature_is_a_builder_or_takes_a_structure`
parses `src/` and reports any function of ten parameters or more that neither
places most of them into a returned literal nor forwards most of them onward.

| Relay | Was | Now | Takes |
|---|---|---|---|
| `refresh_projects` | 17 | 4 | `RunPolicy`, `ResolveArgs` |
| `refresh_candidates` | 14 | 6 | `DiscoveryPolicy` |
| `apply_project` | 12 | 8 | `RunPolicy` |
| `onboard_catalog` | 10 | 7 | `RunPolicy` |
| `_run_project_ingest` | 8 | 3 | `RunPolicy` |

**Four builders remain wide and correctly so.** `codex._base_event` takes 20
parameters and places 14 into its returned dict; `cc` and `cursor` place all 10
of theirs. An object there would name every field twice, which is the
anti-pattern this item records rather than the fix it asks for.

**The three structures share no field.** `RunPolicy` describes what an ingest
does, `DiscoveryPolicy` bounds a walk, `ChildInvocation` names one invocation's
target -- verified by comparing their `__dataclass_fields__` pairwise. The last
collision between them was `timeout_seconds`, which named a child-process bound
on one and a traversal bound on the other; they are `policy_timeout` and
`scan_timeout` now.

#### Formerly Unblocked and Unstarted

**The prerequisite landed.** W66's setting table declares each value once, which
is what step 2 needs: a policy object built at the command adapter now draws from
one declaration rather than encoding the duplication the object was meant to
remove. Nothing else stands in front of this item.

**The measurements still hold**, re-derived by parsing the current source rather
than trusted from the earlier pass:

| Relay | Parameters |
|---|---|
| `refresh_operations.refresh_projects` | 17 |
| `review_project.refresh_candidates` | 14 |
| `baseline_operations.apply_project` | 12 |
| `catalog_operations.onboard_catalog` | 10 |
| `ingest_publication.publish_snapshot` | 10 |
| `refresh_operations._run_project_ingest` | 8 |

No relay has been converted, so the item is unstarted rather than partly done.

**The clock is now uniform, and `RunPolicy` carries it.** All twelve remaining
`datetime.now` reads are converted: `refresh_operations`' four take the clock
from the policy, and the other eight -- stamps in functions that take no policy --
go through `now_iso(system_clock)` like the rest of the package.
`tests/test_timeval.py`'s `DEFERRED` set is empty, so the test now holds the
whole package with no exemption, and `wallclock.system_clock` is the only
`datetime.now` outside `reporting.clock`.

**`RunPolicy` holds the clock** rather than taking it as a parameter, for the
reason it holds the store root: decided once before the first Project, read many
times after. A run that needs a fixed clock sets it on the policy instead of
threading an argument through three layers.

**One relay is converted.** `_run_project_ingest` went from 8 parameters to 3 --
`project`, `policy`, and `validate` -- because both call sites passed the same six
policy values verbatim. Four relays remain, and step 2 moves construction from
`refresh_projects` to the command adapter, at which point that function loses the
six fields it currently names.

**Evidence to close.** Every relay of five or more parameters takes an object or is
recorded as a builder; a call site cannot mis-order same-typed arguments; no
invocation is constructed twice where one would do; `ChildInvocation`'s policy
and target halves are separable, or the reason they are not is recorded; the
relay census runs as a test; and `DEFERRED` is empty.

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

**The gap, re-measured, and it is not what the item recorded.** The earlier
counts do not hold and the conversion they describe would break the command
layer. Measured across `src/cli/`:

| Path | Recorded | Measured | Note |
|---|---|---|---|
| `print(file=sys.stderr)` | 43 | **59** | 4 admin, 9 scan, 11 ingest, 35 query |
| Direct `sys.stderr` writes | 63 | **0** | None remain; the figure counted something else or was already converted |
| Of those prints, fatal | -- | **50** | Immediately precede `return 1` |
| Of those prints, status | -- | **9** | The only genuine conversion candidates |

**Converting the fatal sites would silence them.** `reporting.configure()` is
called by `ingest_cmd` and `scan_cmd` only. In `admin_cmd` and `query_cmd` no
sink is ever attached, so `event()` returns at its first gate and the message
reaches nobody -- verified by calling it with no sink and observing no output.
39 of the 59 prints are in those two modules, and nearly all report a fatal
condition before `return 1`.

**Even where a sink exists, the rendering is wrong for an error.** `HumanSink`
emits `codess: progress <time> +<elapsed>s key=value` for every event. A fatal
error rendered as a progress line is a worse result than the direct write.

**The event and the print are not duplicates**, which two tests state directly.
`TestProjectIdentityChange` asserts the operator reads "identity changed during
ingest" on stderr and records why: a raised exception reaches the same exit code,
so a test asserting only "the run reported a failure" cannot tell a set-aside
Project from a crash. Removing the print in favour of the existing
`project.identity_changed` event failed that test, because the subprocess has no
sink. The event is the structured trace; the print is what an operator reads.

**So the item splits in two, and the fatal half is now done.** A fatal message
belongs on a channel of its own rather than in the event stream, and it now has
one: `cli.failure`, holding `fail`, `fail_with`, `warn`, and
`fail_configuration`. All 59 direct writes are converted and no command module
names `sys.stderr` at all.

| Helper | For | Returns |
|---|---|---|
| `fail(message)` | A fatal condition this code composed | 1, so a caller writes `return fail(...)` |
| `fail_with(exc, context)` | A fatal condition from an exception | 1, carrying the exception's text |
| `warn(message)` | A condition the run continues past | `None`, so it cannot be returned by accident |
| `fail_configuration()` | Every configuration fault at once | 1 if any, else 0 |

**`warn` returns `None` deliberately.** A warning that could be written
`return warn(...)` eventually would be, and the run would exit on a condition it
was built to survive. The two are separated by return type rather than by
destination, because they share the destination.

**Observability is maximal, and that is the privacy decision rather than an
omission of one.** A fatal line reports the operator's own machine to the
operator on their own terminal, so it carries the offending path, flag, or
exception text verbatim. This matches `reporting`'s own `local` privacy profile
-- the default for every profile, which emits every field verbatim including
unregistered ones -- and for the same reason: nothing is leaving the machine.
The redaction profiles exist for the *event stream*, which can be written to a
file and shipped. A fatal message has no such path, and a redacted one would be
the single message least able to do its job. If a support bundle ever wants
these, the answer is a sink that captures them, not a policy that blinds them at
the source.

**The status half is unblocked: both commands now configure a sink.**
`admin_cmd` and `query_cmd` call `reporting.configure` before dispatch and emit
`admin.start`/`admin.done` and `query.start`/`query.done` -- INFO for the
administrative pair because each of those subcommands can delete, publish, or
rewrite state, and a run that reports nothing leaves an operator holding only an
exit code.

**One code per command family, not per subcommand.** 42 codes naming what
`family` and `command` already carry as fields would be a second dispatch table
beside the parser's.

**A failure reports on both channels.** `command.failed` carries the exception
family for a structured reader and `fail` carries its text for the operator;
neither substitutes for the other, because a sink may be a file and stderr is
what a person is looking at.

**Both flush at the boundary.** The ring holds 256 events and neither command
comes close, so without a flush most runs would emit nothing at all. `query.run`
is a wrapper around `_run` for exactly this: `_run` returns from a dozen places,
and a flush at each is a dozen chances to omit one.

**Verified:** stdout is byte-identical across profiles, so `--output-format
jsonl` remains pipeable.

**What remains.** Nine `warn` sites still write through `cli.failure` rather than
the facility. They can move now that a sink exists; the reason to do it in a
separate pass is that each needs a code and a level decided on what it reports.

**The status half, as originally recorded:** One site converted to
the facility: `scan_cmd`'s legacy-Cursor-prune line, which was `opts["debug"]`-
gated *and* written directly -- two gates for one decision. It is now
`registry.legacy_cursor_pruned` at DEBUG. The other nine went to `warn` rather
than to the facility, because the question below is unanswered:

1. **Do `admin_cmd` and `query_cmd` have a progress model at all?** Neither calls
   `reporting.configure()`, so an event from them reaches no sink. Until that is
   decided, a status site in those modules cannot be converted either.
2. **Should `HumanSink` render more than one shape?** It emits every event as
   `codess: progress <time> +<elapsed>s key=value`, which suits progress and not
   a warning.

**Evidence to close.** Done for the fatal half: no command module writes to
`sys.stderr`, `tests/test_failure_channel.py` asserts it over the syntax tree,
and the prefix, the verbatim value, and `warn`'s return type each have a test.
Remaining: the nine `warn` sites move to the facility once question 1 is
answered, and `--output-format jsonl` stays byte-identical on stdout across
profiles.

**What is already correct and must not change.** Result output on stdout stays
a plain `print()`. That is the result channel, and it is what lets
`--output-format jsonl` be piped. Only the stderr half is in scope.

**Why it matters beyond tidiness.** Every property the facility provides --
level gating, profile selection, privacy classification, bounded fields,
never raising into the operation it reports on -- applies only to calls that go
through it. A direct `sys.stderr` write has none of them, so the guarantees
currently hold by convention at each call site rather than by construction, and
a redaction profile does not reach the output an operator actually sees.

#### Execution Order

**Cut by module, not by channel.** A channel cut splits every module's diff in
two and touches all four twice; `query_cmd` alone holds 35 of the 60 `sys.stderr`
references, so cutting it by channel produces two large diffs against one file
instead of one. Ascending size, so the pattern is established on the small
modules before the large one:

| Order | Module | `sys.stderr` references |
|---|---|---|
| 1 | `src/cli/admin_cmd.py` | 4 |
| 2 | `src/cli/scan_cmd.py` | 10 |
| 3 | `src/cli/ingest_cmd.py` | 11 |
| 4 | `src/cli/query_cmd.py` | 35 |
| 5 | The channel-separation test | -- |

Counts are `grep -c 'sys.stderr'` per file and include the import and the
result-channel writes that stay; they order the work rather than bound it.

**Run the stdout byte-identity check per module, not once at the end.**
Per-module it names the commit that crossed the result-channel boundary; at the
end it says one of four did. `query_cmd` holds 111 of the 146 `print(` calls and
nearly all are the result channel, which is what makes the boundary worth
checking at every step.

**Run W71 before W66.** They are independent -- one touches output calls, the
other argument declarations -- but they share all four files, and W66 step 2
checks `--help` byte-identity. Converting output first means that check is
established against files whose output calls are already uniform.

**Cost.** Mechanical per status call site once the two decisions above are
answered, and no rebuild. Independent of W04.

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

**Closed.** No adapter constructs an Event dict outside its builder. The five
remaining bypass sites were converted -- Claude's compaction, tool-call,
user-text, and tool-result paths, and Codex's compaction path -- so `cc` routes
21 constructions through `_base_event`, `codex` 17, and `cursor` 3, with none
outside. Two signature corrections were needed and both were found by the type
checker rather than by a test: `cc._base_event.subtype` had to admit `None`,
which Codex's already did, and `codex._base_event` gained an explicit `event_id`
parameter because a compaction record carrying several summaries needs an
identity per Event rather than the line number that serves the single-Event
case. Converting the user-text site also collapsed one predicate that was
written twice: `event_type` and `role` each chose between the local command and
the derived semantics using the same three-clause condition, and they must not
disagree about which source named the Event.

`pylint --enable=R0801` reports 10 clusters, none of them the Event envelope:
the shared import and constant blocks at the head of `cc` and `codex`, the
reporting package's re-export of its own API, `codex`/`cursor` timestamp parsing
(W55), and the catalog row read in three modules (W04's shape one level up).
Each is recorded above as accepted.

**Verified against real Sources rather than fixtures.** 23,470 Events decoded
from the development machine's own Claude and Codex transcripts are
byte-identical before and after, comparing event identity, classification,
content length, time, tool fields, and metadata. A refactor that claims to
preserve behaviour is checkable that way and is not checkable by a suite that
exercises the same builder on both sides.

**Cost.** Correctness-neutral, no rebuild.

### W73 -- The Vendor Decode Gaps CoPlan Records

**Work.** Resolve, or explicitly close, the per-vendor source cases CoPlan lists
as having a remaining action.

**Why it is an item now.** CoPlan's three vendor sections each carry a
`Source case | Current decision | Remaining action` table. Twenty-two rows, one
marked Done, **twenty-one open** -- and none of the twenty-one is named by any work
item, so the largest body of identified decode work in the repository is
tracked only as prose inside an architecture document. That is the same failure
the item list exists to prevent: a reader of CoTasks would conclude the decode
layer has no open questions.

**By vendor.** The tables grew from sixteen rows to twenty-two as vendor
understanding deepened, so the earlier per-vendor split is superseded. Re-derive
the counts from CoPlan's three tables rather than from a figure recorded here.

**The Codex half is now answerable from the source.** Codex is open source, and
`codex-rs/protocol/src/protocol.rs` declares the fields several of these rows
proposed to measure first: `SessionMeta` carries `forked_from_id`,
`parent_thread_id`, `agent_nickname`, `agent_role`, and `agent_path`, and
`ThreadSource` distinguishes `User`, `Subagent`, `Feature(String)`, and
`MemoryConsolidation`. The parentage group therefore moves from *measure field
availability, then decide* to *decode declared fields*. Three further findings
are recorded in `experiments/format-decisions.md`: `instructions` moved from
`SessionMeta` to `TurnContext`, three `RolloutItem` variants are unhandled
(`InterAgentCommunication`, its metadata form, and `WorldState`), and
`RolloutLine.ordinal` supplies an explicit sequence Codess does not read.

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
a repository's own subdirectory is not evidence of a separate Project;
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
| A repository picked as a neighbour under a vendored-clone container | The container held third-party clones read for reference, which are not development Projects and belong in the scan exclusion list. The true repository's directory had since been removed from the machine, so no `.git` was reachable to collapse to |

**Re-measured with three rules -- skip remote, resolve each path to its shared
repository rather than its worktree, exclude OSS containers:**

| Outcome | Count |
|---|---|
| Correct | **25** |
| Wrong | **0** |
| Unresolved | 15 |

The 15 unresolved are honest abstentions, not hidden errors: 8 composers carry
no path evidence at all, and 7 resolve to no repository -- some name a
directory that has since been removed from the machine, and some local Sessions
reference remote-host paths from work done over SSH.

**What this changes.** Path correlation is not weak; the three rules applied to
it were wrong. Two were already implemented elsewhere in the system --
`project_boundary` stops at a repository, and the catalog carries a `worktree`
relation -- and the third is a configuration list that ships empty by design.
`CODESS_EXCLUDE_REVIEW_DIRS` and `CODESS_AGGREGATORS` are unset on this
machine, which is why a container of vendored clones was treated as candidate
Projects.

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
- **The exclusions are operator configuration, not facts.** A container of
  vendored clones is third-party *because the operator says so*; nothing in the
  directory distinguishes a clone read for reference from a Project under
  development. So the rule's precision is bounded by whether
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
| **Not JSON at all** | 132,207 `agentKv` rows | Several encodings under one key space -- see below | Classify by key space and by content sniff, not by a parse attempt |
| **Valid JSON, wrong shape** | 0 in decoded spaces | Parses to a list or scalar where a dict is expected | Count separately from a parse failure |
| **Index disagreement** | 107 composers | Three indexes list three different composer sets -- see below | Read all, record `selection_source` |
| **Retention skew** | 98 composers | An index prunes on age while the data it indexes is kept -- see below | A data condition, not a gap |
| **Identity absent** | 98 composers | The record states no workspace, so no Project can claim it | Admit without a binding, never infer one |
| **Bulk rewrite** | 4,053 groups, 37 Sessions | A sync re-writes records that already exist, with new identities | Advisory `duplicate_of`, do not delete |
| **Scheme-wrapped path** | 9 workspaces | `vscode-remote://` wrapping both remote and local paths | Refuse as a Project location; bind by approved source link |

**Index disagreement, concretely.** Cursor maintains three lists of the same
composers and no two agree:

| Index | Composers | States a workspace |
|---|---|---|
| `composerHeaders` table | 66 | Yes |
| Workspace `composer.composerData` | 94 | Implicitly, by which database holds it |
| Global `composerData:` keys | 166 | No |

107 composers hold bubbles that `composerHeaders` omits. The disagreement is
not corruption -- each index is internally consistent -- so a decoder that
trusts one index reports a smaller corpus than exists and cannot tell that it
did.

**Retention skew, concretely.** The disagreement above is not random; it is
temporal. Headered composers were created 2026-03-26 to 2026-08-17 with `_v`
14, 16, 17. Orphaned ones were created 2025-08-09 to 2026-03-20 with `_v` 9,
13, 14. **The ranges do not overlap by a single day.** So `composerHeaders` is
a retention window: the vendor prunes header rows on age while keeping the
`composerData:` row and every bubble. It looks like missing data and is
retained data with a pruned index.

**Non-JSON content, and whether text is reviewed.** Yes -- the sniff
distinguishes four kinds, measured over 30,000 `agentKv` blobs:

| Kind | Rows | What it is |
|---|---|---|
| Valid JSON | 10,977 | Conversation messages |
| Not UTF-8 | 17,197 | Protobuf; leading bytes `0a…` |
| Plain text, printable | 1,603 | **File contents** -- a Markdown project brief, a `wp-config.php`, a `.gitmodules` listing |
| Mostly binary but decodable | 223 | Protobuf carrying readable embedded paths |

The plain-text rows matter because they are not decode failures at all: they
are file bodies stored verbatim, and treating them as malformed JSON would
count real content as an error. A content sniff on the first bytes -- `{`/`[`
for JSON, a UTF-8 decode with a printable ratio for text, otherwise binary --
separates the three cheaply and before any parse is attempted.

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

#### Reviewing What an Ingest Reported

The counters are printed and then lost, so nothing reviews them. Two
observations from one session show what that costs:

| Observed | Reading |
|---|---|
| `unsupported=110` on this repository's own ingest | 110 records of a kind no adapter maps. The number names no kind, so whether that is one unmapped type or thirty is unknown |
| `known_ignored=21317` on the same run | Expected volume, but indistinguishable from a regression that started ignoring a mapped type |
| `external_content=5, external_errors=1` | A single external-content error. One is exactly the count that gets lost in a scrolled line |
| `ignored=4898` on another Project | Large, unattributed, and unexplained |

**A per-ingest review needs three things the counters do not supply:** which
record kind each count refers to, whether the count moved since the previous
ingest of the same Project, and which counts are expected to be non-zero. The
first is the reason-code work above. The second needs the counts stored -- a
per-ingest observation already exists for storage and not for diagnostics. The
third is a policy statement: `malformed` should be zero, `known_ignored` should
not, and nothing currently says so.

#### Closed

**Every refusal path in all three adapters now persists a reason code.** The
mechanism existed -- `_record_refused` writes a row where `_diagnostic` only
counts -- and the skip paths beside it used the counter. `adapters/codex` and
`adapters/cursor` had no recorder at all; both now have one mirroring Claude's.
`known_ignored_records` is gone from every adapter, replaced by codes naming
the condition: `record_kind_not_mapped`, `record_context_compacted`,
`record_duplicate_envelope_records`, `record_intermediate_state`,
`record_reasoning_without_summary`, `record_usage_records`,
`record_empty_assistant_envelope`, and five more.

**Aggregated by `(reason_code, record type)` at the store boundary.** A refusal
that recurs is one fact repeated, so the row carries `occurrences` and the
first locator. Measured on this repository: **21,314 refused records reach the
store as 20 rows**, each naming its reason, the vendor's own record type, the
count, and a line to reach one instance:

```
record_usage_records          token_count        8810 records, first at line:16
record_reasoning_without_summary reasoning       5876 records, first at line:11
record_duplicate_envelope_records agent_message  1354 records, first at line:12
```

Writing a row per record would have added 21,314 rows to a diagnostics table
holding 50,423 for the whole corpus.

**Two coordinators never collected them.** `record_diagnostics` was reset and
passed through only in the Claude path, so Codex and Cursor refusals
accumulated into `None` and were discarded -- which is why the first
measurement showed the codes counted and zero rows written. Both now reset per
Source, for the reason the Claude path already documented: a refusal names the
record it read, so carrying the previous file's list misattributes one Source's
losses to the next.

**The ingest summary reports every counter that fired**, rather than eleven
named keys. Zeros are omitted, because a zero for a condition a run cannot
produce reads the same as a zero for one it can. Five test assertions named the
old aggregate and were updated to the specific codes.

**Evidence to close.** Record-level discards reach `mapping_diagnostics` as
aggregated rows carrying a reason code and the vendor's record kind; the
ingest-time cost is one flush per Source rather than one write per record; a
query reports what a store dropped and why; the sites classified above as
exception swallows or value decisions each increment a counter; and an ingest
can be compared against the previous ingest of the same Project so a moved
count is visible.

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

### W88 -- Cursor KV Decode by Content Kind

**Work.** Classify a `cursorDiskKV` value by what it is before attempting to
parse it, and count each kind.

**Why the current order is wrong.** Decode tries `json.loads` and treats a
failure as a skip. That conflates three unrelated facts, measured over 30,000
`agentKv` blobs:

| Kind | Rows | What it is | Today |
|---|---|---|---|
| Valid JSON | 10,977 | Conversation messages | Decoded |
| Not UTF-8 | 17,197 | Protobuf, leading bytes `0a…` | "Parse failure" |
| Plain printable text | 1,603 | **File contents** -- a Markdown brief, a `wp-config.php`, a `.gitmodules` listing | "Parse failure" |
| Mostly binary, decodable | 223 | Protobuf with readable embedded paths | "Parse failure" |

**The plain-text rows are the finding.** They are not malformed anything; they
are file bodies stored verbatim under a key space that also holds JSON. Calling
them a parse error counts real content as a defect, and the count is the only
signal an operator has.

**The sniff is cheap and must precede the parse.** First byte `{` or `[` means
attempt JSON; a successful UTF-8 decode with a high printable ratio means text;
otherwise binary. This costs a few bytes per row against a full parse attempt
per row, so it is faster than what it replaces as well as more accurate.

**What each kind should produce.**

| Kind | Treatment |
|---|---|
| JSON | Decode as now |
| Text | Record presence, byte length, and a digest; the body is unbounded content the resource policy governs |
| Binary | Record presence, byte length, and the leading bytes; do not guess the schema |
| JSON that fails to parse | **This** is the error class, and it should be rare enough to be loud |

**Evidence to close.** A parse failure in a decoded key space is distinguishable
from binary and text content; each kind carries its own count; and the counts
appear per key space, so an unparseable `bubbleId` row is separable from an
expected `agentKv` blob.

**Depends on** W86's reason codes, which supply the counters this would fill.

### W89 -- Path Rules Belong in the Discovery Policy

**Work.** Move path-based inclusion and exclusion into the checked-in discovery
policy file, where the directory-name rules already live.

**Where the rules are today**, which is three places:

| Rule | Location | Editable how |
|---|---|---|
| Pruned directory names (`.git`, `node_modules`, caches) | `schema/discovery-policy.json` | **A file**, with an `editing_note` and a `security_note` |
| Broad system roots refused (`/tmp`, `/var`, `/usr`, `/Users`, 25 entries) | `helpers._BROAD_TRAVERSAL_ROOTS` | Python constant, not configurable |
| Ephemeral locations refused (`/private/var/folders`, `/tmp`) | `helpers._EPHEMERAL_LOCATION_PREFIXES` | Python constant, not configurable |
| Backup conventions (`OLD`, `Save`) | `schema/discovery-policy.json` | **A file**, with per-name match rules |
| Grouping directories (`AGGREGATORS`) | Environment variable | `CODESS_AGGREGATORS`, ships empty |
| Third-party trees (`EXCLUDE_REVIEW_DIRS`) | Environment variable | `CODESS_EXCLUDE_REVIEW_DIRS`, ships empty |

**Progress is real and partial.** The redesign did produce a policy file, and
it is the right shape: checked in, versioned by `policy_format`, carrying its
own editing and security notes, and reported by `tools/setup_discovery.py`
rather than only documented. What it covers is directory *names*. Everything
keyed to a *path* -- the two lists an operator most needs to set -- stayed in
environment variables, and the two refusal lists stayed compiled in.

**The defect this produced is measured.** Both path lists ship empty, so on an
unconfigured machine a container of third-party clones is ranked as candidate
Projects. That is not a wrong default -- shipping one derived from a single
tree would be worse -- it is that the setting has no durable home, so
configuring it means exporting a variable that a later shell forgets.

#### Four Scenarios, Four Different Rules

The current split -- some rules compiled in, some in a file, some in the
environment -- is not organised by *who decides*, which is why it satisfies
none of the cases well. Sorting by that instead:

| Scenario | Who decides | Changes how often | Belongs in |
|---|---|---|---|
| **System-wide, per platform** | Codess | Per release | Compiled in. `/tmp`, `/var`, `/usr` are not traversal roots on any Unix, and `%APPDATA%` behaves differently on Windows. An operator has no useful opinion here, and a wrong edit breaks discovery |
| **Ecosystem convention** | Codess, extensible | Per release, plus local additions | The released policy file. `node_modules`, `.venv`, `target`, `__pycache__` are generated everywhere; `OLD` and `Save` are kept-aside copies. Portable *names*, and a tree with different conventions replaces the list |
| **Development environment layout** | The operator | Once per machine, then rarely | **A machine-local policy file** -- which does not exist today. "This container groups repositories", "this tree holds vendored clones" is a durable fact about one machine, and an environment variable is the wrong home for a durable fact |
| **Individual preference** | The operator | Per invocation | Command flags and environment. "Exclude this tree for this run" is a scope decision, not a layout fact |

**The third row is the gap.** Both `CODESS_AGGREGATORS` and
`CODESS_EXCLUDE_REVIEW_DIRS` are machine layout expressed as environment
variables, so the judgment lives in a shell profile or nowhere. Measured
consequence: on this machine both were unset, and a container of vendored
clones was ranked as candidate Projects.

**Reasonable defaults with fast clean ingest, then tuning.** The four rows
suggest the sequence rather than one answer:

1. **Ship with rows one and two populated.** Platform roots and ecosystem
   conventions are safe defaults because they are not one tree's names -- which
   is exactly why the current empty path lists are *not* a counterexample to
   shipping defaults.
2. **Discover row three, do not guess it.** `tools/setup_discovery.py` already
   proposes candidates from the operator's own tree; what is missing is a file
   for it to propose *into*.
3. **Leave row four to flags**, where a per-run scope decision belongs.

**What should not move.** The broad-root and ephemeral-location refusals stay
compiled in: they are safety rails rather than preferences, and a file an
operator edits is the wrong home for a rule whose purpose is refusing a
mistake. Documenting them in the policy file as read-only is worthwhile; making
them editable is not.

**The settled specification.** Three settings replace the two, split by whether
a value is portable:

| Setting | Answers | Form | Ships |
|---|---|---|---|
| `exclude_dirs` | Which directory *names* are never traversed | Names | Non-empty sample |
| `exclude_paths` | Which trees on this machine are not the operator's work | Absolute paths | Empty |
| `include_paths` | Which trees to admit despite a rule that would skip them | Absolute paths | Empty |

`AGGREGATORS` is retired rather than renamed. It was defined here as "a
container holding many repositories", which is a structural test; the operator's
actual criterion is *intent* -- a collection kept for reference rather than
developed in, which may hold one repository or fifty. On that definition it and
`EXCLUDE_REVIEW_DIRS` were the same setting, and `exclude_paths` is it.

**Names ship non-empty and paths ship empty**, which is the distinction the
current all-empty default gets wrong. `tmp`, `var`, `windows`, `node_modules`
mean the same thing on every machine, so a shipped list discloses nothing about
one tree and is always correct. A reference tree's *location* is one machine's
layout, so it stays empty and env-supplied. The Environment Separation rule
distinguishes platform facts from operator facts; the current default treats
both as operator facts.

**Hidden names are a rule, not a list.** Any name beginning with `.` is skipped,
so the policy file stops enumerating `.git`, `.venv`, `.mypy_cache` and the
thirty others -- an enumeration of a rule is permanently incomplete, since each
new tool adds a name. `.codess` and `.claude` are read by explicit path rather
than traversal, so the rule does not reach them; a test must assert that,
because it is the kind of thing that breaks silently.

**Syntax, stated once.** Lists are comma-separated, not colon-separated: a colon
is excluded from the value character set so a comma is unambiguous, and PATH
notation would wrongly imply precedence by position. Whitespace is stripped from
a file and the command line alike. A name is alphanumeric with `-`, `_`, and `.`
permitted, no `/`, at most 255 characters; a path starts with `/`, may end with
one, and is at most 1023 characters. `..` is rejected in either, because a
traversal segment lets an entry escape the scope it appears to name.

**Precedence:** `include_paths > exclude_paths > exclude_dirs > hidden names >
default traversal`. Most specific wins, and an `include_paths` entry is honoured
even where a parent is excluded and a segment name is on the list -- which is the
whole reason it exists, since name-based exclusion over-reaches by design. This
must be asserted by a test; a documented-only ordering rule regresses.

**Symbolic links are not followed.** Following them breaks the precedence rule:
a link inside an excluded tree pointing into an included one re-admits excluded
content by a path that never matches `exclude_paths`, so an exclusion the
operator wrote is silently void. Links also admit cycles and report one Project
twice under two paths. A tree that lives behind a link is admitted by naming its
real location in `include_paths`. Hardlinked directories are not creatable on
the platforms in scope; hardlinked files affect source identity only, where
`source_dir_inode` already records the evidence.

**A skipped check must say so.** With the path settings unset, `registry_check`
runs no layout check and reports zero findings -- indistinguishable from clean.
Measured: 0 errors, 0 warnings, 1 note unset, against 0/7/14 configured. It
should name the checks that did not run and the variable that enables them, and
point at `tools/setup_discovery.py --propose`. Not a hard error: that would
break a first run on a clean checkout, which is the early-access path W83 cares
about.

**Evidence to close.** A machine's inclusion and exclusion judgment survives a
new shell; `tools/setup_discovery.py` proposes into that file; and the
compiled-in refusals are documented in the same place without becoming editable.

### W90 -- Scanned but Never Ingested

**Work.** Close the gap between a Project that scan found and a Project that
ingest ever read.

**How it was found.** This repository's own Sessions were absent from every
store. `~/.claude/projects` held 10 transcripts and 77 MiB for it, and
`ingested_projects.json` recorded a scan on 2026-08-17 -- 10 Sessions, 60.5 MiB
across Claude and Codex -- with **no `last_ingestion` at any point**. Ingesting
it produced **26 Sessions and 68,655 Events**, making it the second-largest
Project in the registry.

**It is not one Project.** Eight tracked paths have a `last_scan` and no
`last_ingestion`, and the same eight are absent from the Project catalog
entirely. Scan records them; ingest never saw them; the catalog only holds what
ingest published, so every list derived from the catalog omits them silently.

**The mechanism.** `codess ingest --dir <path>` ingests what it is told.
Nothing walks the scanned set and asks which members have never been ingested,
so a Project enters the store only when a person names it. A tool that
enumerates Projects from the catalog -- which is the obvious way to write one,
and is what was used here for a full-corpus rebuild -- inherits the omission
and cannot detect it.

**Why this is High.** Every completeness claim rests on the corpus being what
the operator thinks it is. A Project scanned and never ingested is invisible to
coverage reporting, to the corpus baseline, and to any audit, and nothing
reports the discrepancy. The failure is silent in exactly the way the system is
otherwise careful to avoid.

**Closed.** `registry_store.never_ingested_entries` returns every entry with a
`last_scan`, no `last_ingestion`, and a path that still exists -- the last
condition deliberately, because a vanished path is `stale_entries`'s subject
and cannot be ingested anyway. `codess storage report` emits a
`scanned_never_ingested` warning naming up to ten paths and counting the rest,
which is the command an operator runs to ask what the registry holds.

The eight Projects found in this state were ingested, recovering roughly 74,000
Events, of which 68,655 were this repository's own Sessions.

**What is deliberately not changed.** Ingest still reads what it is told; it
does not walk the scanned set and ingest everything. Reporting the gap is the
fix, because ingesting on discovery would publish Projects an operator has not
chosen -- including the temporary directories a test run scans.

### W91 -- One Authoritative Project Record

**Work.** Reconcile the three records that describe a Project into one with a
stated owner, covering Projects that were scanned, ingested, moved, or removed.

**Three records disagree today and nothing reconciles them.**

| Record | Holds | Written by |
|---|---|---|
| `ingested_projects.json` | Every path scan saw, with `last_scan`, `last_ingestion`, per-vendor counts | scan and ingest |
| `projects.json` | The Project catalog: identity, locations, aliases, dispositions | ingest, at publication |
| `projects/<id>/` | Snapshots and the current pointer | publication |

Measured disagreements on one machine: **9 paths claimed by two Projects each**,
**8 paths scanned and never ingested** (and therefore absent from the catalog
entirely), **1 catalogued directory no longer on disk**, and **1 Project with
no `current.json`**.

**The proliferation question, and why a fourth record is the wrong answer.**
Adding a unified record without retiring the others produces four descriptions
and no authority. The design constraint is therefore that one record is
authoritative *per fact*, not that one record holds everything:

| Fact | Authority | Why not elsewhere |
|---|---|---|
| Does this path exist, and is it a repository | The filesystem | Any cached answer is stale the moment a directory moves |
| Was it scanned, and when | `ingested_projects.json` | Scan is the only writer |
| Is it a Project, and what is its identity | `projects.json` | Identity must survive a path change, so it cannot be keyed by path |
| What has been published for it | `projects/<id>/current.json` | The pointer is the publication transaction |

**So the work is reconciliation, not a new store.** What is missing is a
lifecycle *state* on the catalog entry -- `scanned`, `ingested`, `moved`,
`removed`, `superseded` -- with the date of the transition, so a Project that
has left the machine remains a record rather than disappearing from every list.
The dates already exist across the three records; nothing joins them.

**Correctness follows from writers, not from schema.** Each fact keeps exactly
one writer. A reconciliation that lets two components write a lifecycle state
recreates the disagreement it was built to fix, which is what happened with
Project identity (W14): ingest inferred an identity and silently overrode a
reviewed one.

#### Partly Done

`registry_store.project_lifecycle` reconciles the two records without adding a
third. It joins `ingested_projects.json` and `projects.json` by path and
derives a state from facts that each already have one writer:

| State | Condition | Writer of the fact |
|---|---|---|
| `superseded` | The catalog entry carries a retiring disposition | The operator, through `catalog state` |
| `removed` | The path no longer exists | The filesystem |
| `ingested` | A `last_ingestion` is recorded | ingest |
| `scanned` | Observed and never ingested | scan |

**Derived rather than stored, deliberately.** A stored state would need a fifth
writer and could disagree with all four facts beneath it -- which is the
failure W14 demonstrated, where an inferred identity overrode a reviewed one.
Ordered by last activity so current work reads first.

On this machine after the consolidation: 30 `ingested`, 1 `superseded`, and the
two records agree on all 31 paths. Before it they disagreed on 8.

**`codess catalog lifecycle` is the operator surface.** It reports the rows
with a per-state summary and `--state` to filter, and **exits nonzero when a
Project was scanned and never ingested** -- the one state worth acting on
rather than reading, and the one invisible to every list drawn from the
catalog. `registry_check` stays the disagreement report; this is the state
report, and they answer different questions.

#### Remaining

**Re-ingesting a catalogued Project can still add an entry**, which is W14's
structural half: the binding inside the Project directory wins over the
catalog, so a lost binding still splits a Project. The guard reports it; the
fix moves the authoritative binding to the registry. That is tracked on W14
rather than here.

**Evidence to close.** A single query answers "every Project this machine has
known, with what happened to it and when"; each fact in it names its writer;
and re-ingesting a Project already catalogued updates its entry rather than
adding one.

**`tools/registry_check.py` is the interim.** It reports the disagreements
without changing anything, so the reconciliation can be designed against
measured conditions rather than imagined ones.

### W92 -- Event Kinds: Most Volume Is Machine Traffic

**Work.** Report Event volume by kind and Actor, so a count states what kind of
activity it measures.

**The measurement that motivates it.** Grouped by `event_kind` and
`actor_kind` across the corpus:

| Vendor | Events | tool.call + tool.result | message.prompt (human) |
|---|---|---|---|
| Claude | 96,957 | 44,226 (**46%**) | not in the top eight |
| Codex | 162,142 | 115,928 (**71%**) | 6,910 (4%) |
| Cursor | 161,821 | 129,782 (**80%**) | 4,333 (**3%**) |

**Between 46% and 80% of every store is tool traffic**, and human prompts are
3-4% of Codex and Cursor. A raw Event count therefore measures how tool-heavy a
harness is, not how much work a person did -- and the vendors differ enough
that comparing raw counts across them compares harness design.

Claude's profile differs in a second way: `content.attachment` (9%),
`state.product` (8%), `harness.setting` (5%), and `session.label` (3%) are
harness bookkeeping that the other two either do not emit or do not retain.

**Consequence for existing figures.** `content_objects` -- 130,934 for Codex
against 41,619 for Claude -- is dominated by tool results for the same reason,
so it is a proxy for tool volume rather than for retained content of interest.

**Evidence to close.** Overview reports Event counts split by kind and Actor;
any cross-vendor comparison states which kinds it includes; and the corpus
baseline distinguishes human-authored from machine-generated volume.

### W93 -- Session Utilization: Detection and Disposition

**Status: Postponed for policy, ready for recording.** What each class *means*
for ingestion, search, and counts is a decision this item does not pre-empt.
Recording the class costs nothing and is what makes the decision possible.

#### What the 318 Actually Are

Characterized rather than guessed:

| Property | Value |
|---|---|
| Session count | 327 with `surface_kind='api'`; 318 hold exactly 9 Events |
| `metadata.entrypoint` | `sdk-cli` on every one |
| Distinct prompt openings | **1** -- `"You are an impartial judge reviewing a conversation between…"` |
| Days spanned | 2: 311 on 2026-07-30, 16 on 2026-07-31 |
| Models | `claude-sonnet-5` 154, `claude-opus-5` 153, `claude-fable-5` 16 |
| Tool invocations | 0, across all 327 |
| `source_cwd` | One Project directory |

So: a **batch evaluation run** -- one scripted prompt issued 327 times across
two days against three models, each producing a JSON score block. The operator
identifies it as scripted invocations of an evaluation harness, which the
evidence matches exactly.

**The vendor states this for Claude, and only for Claude.** `surface_kind`
separates the batch runs perfectly *within* the Claude store:

| Vendor | `api` | `cli` | `ide` | Derived from |
|---|---|---|---|---|
| Claude | **327** (0 with tools) | 202 (170 with tools) | 0 | Record `entrypoint`; `sdk-cli` maps to `api` |
| Codex | 0 | 28 | 10 | Payload `source` |
| Cursor | 0 | 0 | 90 | **Nothing -- the vendor profile default** |

**Three corrections to what I claimed.**

1. **`api` appears only in Claude.** No Codex or Cursor Session carries it, so
   "every `api` Session has no tool use" is a statement about 327 Claude
   Sessions from one batch run, not a cross-vendor rule.
2. **Cursor's `surface_kind` is not evidence.** `adapters/cursor` never sets
   it; every Cursor Session is `ide` because the vendor profile says so. A
   predicate filtering on it filters on a constant.
3. **The three vendors derive it from three different fields**, so the values
   are not comparable in the way one column implies. Claude reads `entrypoint`,
   Codex reads the payload `source`, Cursor reads nothing.

So `surface_kind` is a reliable discriminator *for Claude batch runs* and
nothing more. Whether Codex or Cursor can produce a comparable scripted run,
and how it would appear, is not established -- Codex has an `exec`
non-interactive mode and Cursor a terminal agent, and neither has been observed
here.

#### Reframed Again: What Axis Is This

The earlier framing named `tool_invocation_count` as the "what it contains"
axis and called the combination "development work". Both are wrong, and the
reason is the same: **a tool invocation is a vendor-mediated event, not a unit
of work.**

Measured, Cursor records a tool call for 87 of 90 Sessions and Claude for 170
of 529. That difference is harness design -- Cursor's agent invokes tools for
operations Claude performs another way -- not a difference in how much work was
done. A threshold on the count therefore ranks harnesses, not Sessions.

**What can be stated per Session without inventing a comparison:**

| Fact | Field | Comparable across vendors |
|---|---|---|
| How the Session was started | `surface_kind` | **No** -- three derivations, one absent |
| Whether a human typed a prompt | count of `message.prompt` with `actor_kind='human'` | Yes -- the classification is common |
| Whether the model called tools | `tool_invocation_count` | **No** -- harness-dependent rate |
| How many Events | `event_count` | **No** -- 5,435 to 8,511 bytes per Event by vendor |

**Only the human-prompt count is comparable**, because Actor classification is
the part CoSchema normalizes and validates across all three vendors. Everything
else is a per-vendor measurement that may be compared *within* a vendor.

**So there is no "development work" axis**, and asserting one would repeat the
error this item was opened to fix. What exists is a set of per-Session counts,
each with a stated comparability, and one vendor-specific signal that happens
to isolate a known batch run.

#### Turn-Pattern Digest, Reassessed

The digest is still worth having and for a narrower reason than I gave. It does
not identify these Sessions -- `surface_kind` does that, more cheaply and with
vendor authority. What it identifies is a **repeated shape whose cause is not
yet known**, which is a different and rarer job:

- 296 of the 318 share one exact Event-kind sequence and 22 share another. The
  22 differ by carrying `state.product` where the 296 carry
  `content.attachment` -- a real difference in what the harness recorded, on
  the same scripted prompt.
- Nothing in `surface_kind` predicts that split. The digest is what surfaced it.

So it belongs as a diagnostic rather than a stored column: computed by an audit
that asks "which Sessions repeat a shape", not written per row.

#### Link Detection: The Design

**Reframed from classification to link detection**, which separates what can be
measured from the policy this item postpones. Detecting that 296 Sessions share
one Event-kind sequence is a measurement; deciding what a report does about them
is the undecided half. The design covers only the first.

**The signal is the turn-pattern digest**: the ordered Event-kind sequence of a
Session, hashed. Two Sessions are linked when their digests match. It is
computed by an audit that asks "which Sessions repeat a shape", not written per
row -- a stored column would imply the value is a property of the Session, and
it is a property of the *set*.

**What it must not become.** It does not identify the batch run; `surface_kind`
does that more cheaply and with vendor authority. It earns its place on the case
`surface_kind` cannot predict: 296 of the 318 share one sequence and 22 share
another, differing by `state.product` against `content.attachment` on an
identical scripted prompt. So the output is a digest-group table carrying the
variance between groups, not a classification of each Session.

**Comparability carries over unchanged.** A digest is compared *within* a
vendor. Event counts differ 5,435 to 8,511 bytes per Event by vendor and tool
invocation is harness-dependent, so a digest group spanning two vendors would
be an artifact of how each harness records, not a repeated shape. Only the
human-`message.prompt` count is comparable across vendors, and it is not what
this detects.

**What stays undecided**, and is why the item remains postponed: whether a
detected group is excluded from counts, marked, or merely reported. Detection
does not pre-empt it, which is the point of separating them.

#### Project-Level Classes

| Class | Count | Signal |
|---|---|---|
| Published with no Sessions | 6 | 0 Events, ~1 MiB of empty store |
| Single Session, no tool use | 1 | 8 Events, 0 tool calls |
| Single Session, minimal tool use | ~4 | 63-236 Events |

**A zero must be distinguishable from a failure.** An empty Project consumes a
catalog entry, a store directory, a snapshot, and a row in every inventory, and
in those lists it is indistinguishable from a Project whose decode failed. The
first question a reader asks of a zero is "empty or broken", and nothing
answers it.

### W94 -- Four Files Carry the Format Number

**Work.** Reduce four declarations of the CoSchema format to one declaration
and derivations that cannot go stale unnoticed.

**Current state**, after making two of the four checkable:

| Location | Read by code | Drift detected | When |
|---|---|---|---|
| `FORMAT_VERSION` | Everything | It is the declaration | -- |
| `manifest.json` | `load_manifest`, `snapshot` | Yes | On the next store open, or `refresh_schema_manifest.py --check` |
| `schema.sql` | Executed | Yes | At store creation, naming the file |
| `contract.json` | Declarative only | Yes | On any contract read |

**A fifth location existed and is removed.** `schema.sql` carried the format
number twice: `PRAGMA user_version`, which every check reads, and a header
comment, which none did. The comment had drifted several formats behind while
the pragma stayed correct -- the precise failure this item describes, in the one
place no check could see it. The comment now states where the number is declared
instead of repeating it. A number a check cannot read is not a fifth declaration
to synchronise; it is one to delete.

**The silent gap is closed; one problem remains.** `load_contract` now compares
the contract's `format_version` against the declaration, so all four locations
are checked.

**Detection is no longer incidental.** The format-7 bump was caught by 289
tests failing on `manifest format_version mismatch` -- real detection, but a
side effect of those tests opening stores. `TestFormatNumberAgreement` now
asserts the four directly, so a bump that misses a file fails on that file.

**Detection now precedes the suite.** `pytest_configure` checks the four stated
formats and every released digest before collection, so a stale file stops the
run in under a second naming the file and its remedy. Measured against the
alternative: a stale contract digest previously produced 391 failures and 38
collection errors.

**Correction is still manual**, and one step further out remains: a pre-commit
hook would move detection from *test run* to *commit*. Four locations with four
checks, a pre-collection gate, and direct assertions is a defensible state; the
count itself is what W94 would still reduce.

**Options, with the tradeoff each makes.**

| Option | Reduces to | Cost |
|---|---|---|
| Compare `contract.json` in `load_contract` | 4 locations, 3 checked | Smallest change; does not reduce the count |
| Generate `manifest.json` and `contract.json` at build time | 2 authored | Needs a build step the repository does not have |
| Add a pre-commit check that all four agree | 4 locations, 4 checked | Catches drift at the edit; another thing to install |
| Fold the format into one released file both others reference | 2 | A JSON document cannot reference another without a loader; helps `contract.json` only |

**The first is done** -- `load_contract` compares the contract, which closed
the silent gap for a few lines. **The third is what remains**: a pre-commit
check moving every detection from "next store open" to "the commit that broke
it". Neither reduces the count to two, and the honest statement is that four
locations with four checks is acceptable while four with two was not.

**Evidence to close.** Every file stating the format number is compared against
the declaration; a stale value fails at the edit rather than at the next store
open; and the reason each location exists is recorded beside it.

### W95 -- Message and Comment Wording

**Work.** Tighten operator-facing messages and code comments to a stated
standard, and record the standard with a worked example.

**The standard.** State the observation and the action. Omit the explanation a
reader does not need at the moment of failure.

**Worked example**, from the DDL version check:

Before -- 4 lines, 2 of explanation the reader did not ask for:

```
released DDL stamps user_version 6 while the declared CoSchema format is 7;
update schema.sql to match
```

After -- the same two facts and the same action:

```
DDL user_version 6, declared CoSchema 7: update schema.sql
```

The docstring above it went from 10 lines to 6 by the same rule: the *why* a
maintainer needs stays, the restatement of what the code does goes.

**Where this applies.** Error messages, log lines, progress events, and code
comments. Not documentation, where a reader is looking for explanation.

**Why it is Low and not Withdrawn.** No defect follows from a verbose message,
so nothing forces it. But `require_store`'s unsupported-format message is now
four lines of prose in an exception, and every error a reader meets is one they
are meeting while something is already wrong.

**Evidence to close.** The standard is written where a contributor will meet
it; the messages in `schema_contract` and `store` are revised against it; and
the example above is retained as the reference.

### W96 -- Project Location Changes

**Work.** Detect, classify, and act on every way a Project's location can
change, with a stated response per condition and per vendor.

#### Following the Vendor Stance

**A worktree is two Projects, because every vendor already treats it as two.**
Claude gives each its own slug and its own prompt history, Codex records a
distinct `cwd`, Cursor a distinct workspace. That a repository shares a `.git`
is a git attribute; what Codess indexes is a *work area with its own Session
history*, and by that measure a worktree is two.

So `worktree` is withdrawn as a **disposition** -- it was recording a git fact
in a field that states operator intent -- and the `multiplicity` dimension is
withdrawn with it. What remains is a relation between two ordinary Projects,
which `related_project_id` already carries without implying either is less than
a Project.

**`copy` survives the same test and for the opposite reason.** Two live paths
holding one identity is not two work areas; it is one, duplicated. The vendors
see one, because only one is being worked in.

#### The Dimensions

Three, after withdrawing multiplicity. Each is independent and a Project has a
value in each:

| Dimension | Subject | Answers | Values | Decided by |
|---|---|---|---|---|
| **Presence** | The directory | Is it on this machine | present, absent, copy | The filesystem, plus catalog locations |
| **Coverage** | The store | Do the vendor Sources still exist | complete, partial, purged | Recorded `source_path` against disk |
| **Disposition** | The operator | What was decided | none, priority, included, deferred, excluded, review | The operator |

**Disposition vocabulary, revised.** `needs_review` becomes `review` -- the
value is already a noun in a field named for a decision, and `needs_` restates
it. `candidate` becomes `included`, because the question the field answers is
whether a Project takes part, and `candidate` describes a stage in someone's
process rather than the answer. `priority` remains as included-and-first.
`worktree` is removed.

**Precedence is documented rather than implied.** A single `state` label is
kept as a derived convenience, and where two dimensions both have something to
say the label takes disposition first, then coverage, then presence -- because
an operator's decision outranks a measurement, and a measurement outranks a
default. Stated here so the order is arguable rather than incidental to
statement order.

#### Harness Worktrees Are a Setting

Claude Code has run Sessions in worktrees it created under
`<project>/.claude/worktrees/<name>` -- one holding 1,350 turns. Those are the
tool's working area: generated names, created and removed by the tool, pruned
from git without the operator acting, and one observed registration outlived
its directory.

`CODESS_CLAUDE_WORKTREES` admits them and is **off by default**, because such a
Session is *about* the parent Project and publishing it creates a Project whose
path will not exist next week. Set it when the question is about harness
behaviour rather than about a repository.

**This is the first of a family.** Ingest needs settings that state what is
admitted rather than deciding it in code, and this one names the pattern:
`CODESS_<AREA>_<SUBJECT>`, boolean, off where admitting costs more than
omitting.

#### The Conditions, and What Each Means

Eight, distinguishable by evidence rather than by guess. The first three are
handled; the rest are not.

**Coverage has three values, not two, and the third is the dangerous one.** A
vendor prune removes transcripts individually, so a Project commonly loses part
of its Sources rather than all of them. Under a two-value dimension a partly
purged store reads as `complete` and loses the delete-gate that the whole
protection below depends on -- which is the unrecoverable case, not an edge of
it. `sources_vanished` is a count, so the evidence to tell the three apart is
already computed; what collapses them is the derived label.

| Condition | Evidence | Identity survives | Status |
|---|---|---|---|
| **Moved / renamed** whole | Binding travels; old path retired, new path holds the same `project_id` | **Yes**, automatically | Reported `moved`; retirement is manual |
| **Copied** beside the original | Two **live** locations on one entry | Yes, and ambiguously -- both claim it | Reported `copy` with `copy_of` |
| **Restored** | A move if the original is gone, a copy if it remains -- the same two states, decided by whether the original path still exists | Depends | Reported as `moved` or `copy` |
| **Deleted** | Path absent, no live sibling | Entry retained as a record | Reported `removed` |
| **Retired** | Operator excluded it | Retained as evidence, out of selection | Reported `retired` |
| **Worktree** | Catalog records a `worktree_of` relation | Yes; an ordinary live sibling | Reported `worktree` |
| **Partly purged** | Some recorded Sources resolve and some do not | Store outlives part of its Sources | **Measurable, not yet reported** |
| **Purged** (vendor deleted its own records) | Path exists; no recorded vendor Source does | Store outlives its Sources | **Measurable, not yet reported** |
| **Restored from archive** | A store at a superseded format | Not contract-readable | Manual only |

**`superseded` was withdrawn.** It named `excluded` and `worktree` as one
state, which conflated a duplicate the operator answered with a live sibling of
a repository -- different conditions, different actions. They are now `retired`
and `worktree`.

**Restore is not a distinct condition.** Restoring a directory produces a
*move* when the original is gone and a *copy* when it remains, and the same two
checks decide it. Naming it separately would imply a third answer that does not
exist.

**A copy must not be re-ingested.** Two live locations on one entry is one
Project in two places; ingesting the second writes the same Sessions under the
same identity from a second path. `copy_of` names the original so a scan can
report the duplicate and decline. **Not yet enforced** -- the state is derived
and nothing consults it at ingest.

**The distinction that organises the work:** whether the *Project directory*
moved, or the *vendor's record of it* changed. They fail differently and are
detected by different evidence.

#### Worktrees, as the Vendors See Them

A linked worktree is one repository checked out at two paths on two branches.
Measured on this machine:

| Vendor | Treats a worktree as | Evidence |
|---|---|---|
| Claude | **A separate Project.** Each worktree gets its own slug directory and its own prompt history | `-Users-walter-Work-ZK-Zero400` and `-Users-walter-Work-ZK-ZeroPerf` both exist |
| Codex | Whatever `cwd` each record states, so a worktree is a distinct value with no relation recorded | Per-record `cwd`; no index |
| Cursor | A separate workspace, since `workspace.json` names the folder | One workspace per opened folder |

**None of the three records the relation.** Each sees two directories; nothing
in any vendor store says they share a repository. Only `git` knows, which is
why the catalog's `worktree_of` disposition is operator-stated rather than
decoded -- and why it has to be.

**The harness creates worktrees too, and they are not the operator's.** Claude
Code writes them under `<project>/.claude/worktrees/<name>`. Found here:
`Spank/spank-py/.claude/worktrees/epic-proskuriakova` (registered in git,
target directory gone, `prunable`) and a `Code/Misses/.claude/worktrees`
directory. `usage.db` records three such sessions -- `epic-proskuriakova` 9
turns, `beautiful-euler` 0, and **`reverent-austin-cd76da` 1,350 turns**.

That last one matters twice: it is substantial work in a harness-created
worktree, and its turns span **three different `cwd` values** --
`spank-py/.claude/worktrees/reverent-austin-cd76da`, `spank-py`, and
`spank-rs`. So a Session is not necessarily one directory, which every
path-based binding in this system assumes. Two of 35 sessions in `usage.db`
span more than one `cwd`.

**Second example beyond Zero400/ZeroPerf:** `Spank/spank-py` registers
`epic-proskuriakova`, whose directory no longer exists -- a worktree that was
removed without `git worktree prune`, leaving a registration pointing at
nothing. The Claw fork of `openclaw` no longer has worktrees under
`/Users/walter/Work/Claw`; only an `openclaw/workspace` path appears in
`usage.db`, and no `.git` file records a link today.

#### Per-Vendor Specifics

Each vendor binds a Session to a path by a different mechanism, so a move
affects them differently:

| Vendor | Binds by | A moved Project |
|---|---|---|
| Claude | The directory **slug encodes the absolute path** (`-Users-walter-Work-Code-Misses`) | Old Sessions stay under the old slug; new Sessions appear under a new one. **The Project's history splits across two slugs and nothing joins them** |
| Codex | A rollout records `cwd` per record | Old rollouts keep the old `cwd`; discovery matches on it, so old Sessions stop matching the moved Project |
| Cursor | `workspace.json` names the folder | The workspace entry is rewritten by the editor, so the binding follows -- but the composer keeps its own id, and a stale `workspace.json` elsewhere may still name the old path |

**Claude's is the sharp case and is not handled.** After a move, the vendor
holds two slug directories for one Project and Codess ingests them as two
Projects, because the slug *is* the path. `path_aliases` already exists on a
catalog entry and is where the join belongs; nothing currently populates it
from a slug.

**A vendor directory beside a Project is not a vendor record of it.** A
`.claude` or `.cursor` directory inside a Project says a harness ran there; it
does not mean the harness maintains a central index entry for that path, and
the two can disagree. Claude's central index *is* the slug directory name, so
it cannot disagree -- but it also cannot follow a move. Codex has no
path-derived index at all, only `cwd` recorded per record. Cursor's
`workspace.json` is the index and the editor rewrites it, so it follows a move
made through the editor and not one made in a shell.

**Per-vendor impact of a move, in order of severity:**

| Vendor | After a move | Recovery |
|---|---|---|
| Claude | History splits across two slugs; both ingest as separate Projects | `path_aliases` joining the two decoded paths -- not built |
| Codex | Old rollouts keep the old `cwd` and stop matching; new ones match | Match on either path once aliases exist |
| Cursor | Follows if moved through the editor; a shell move leaves `workspace.json` stale | Re-open the folder in the editor, or an approved source link |

**What an experiment would settle**, and is not yet run: whether each harness
rewrites, duplicates, or abandons its index when a directory is renamed
underneath it. That is W75's method -- trigger the condition, read the vendor
store -- applied to a condition W75 does not currently list.

#### What Exists Today

- `tools/registry_check.py` reports duplicates, nesting, exclusion conflicts,
  absent directories, worktrees, and dangling pointers. Retired locations are
  skipped so an answered condition stops being reported.
- `codess catalog lifecycle` reports `scanned`, `ingested`, `moved`, `removed`,
  `superseded` per Project, derived rather than stored.
- `codess catalog location retire` and `catalog relocate` are the manual
  adjustments.
- `_resolve_project_id` warns on minting and on a binding disagreeing with the
  catalog.

#### What Is Missing

1. **Nothing retires a location automatically**, and deliberately so: an absent
   path is a move, an unmounted volume, or a deletion, and those differ. What
   is missing is not automation but a *directed* report -- naming the command
   that resolves the condition it just found, rather than describing the
   condition and stopping.
2. **A copy is not resolvable at all.** Two live paths, one binding, and no
   rule says which is the Project. Needs an operator decision and a way to
   record it.
3. **The Claude slug split is undetected.** Two slugs whose decoded paths differ
   only by the move are one Project's history, and `path_aliases` is the
   existing mechanism.
4. **Purge is measurable and unreported, and needs protection rather than a
   report alone.** `sources_vanished` answers it; no command surfaces it.

   **A purged Project must not be acted on automatically.** Its store is the
   only remaining copy of Sessions the vendor deleted, so a prune, a format
   rebuild, or a "superseded store" cleanup can destroy evidence nothing can
   regenerate. Required behaviour:

   - **Never delete without explicit approval.** The state is the gate, not a
     size or an age.
   - **A broken reference is fixed, not followed.** A snapshot pointer into a
     removed store, or an alias to a path that no longer exists, is repaired
     rather than left dangling -- and repairing it must not silently drop the
     purged store.
   - **Access is guarded by a status check.** A reader asking for a purged
     store gets it with the condition stated, so a result carries the fact
     that its Sources are gone.

   **Observed from Claude only, and that is not a property of Claude.** Claude
   prunes on a 30-day default and a known defect bypasses the setting on
   update. Codex and Cursor have not been observed pruning here -- which is
   evidence about this machine, not about those vendors. A policy change, an
   administrator, or Codess itself can purge records unexpectedly, so the
   protection is keyed to the *condition* rather than to the vendor.
5. **Up-front direction does not exist.** An operator about to move a Project
   has no way to say so, and doing it afterwards is strictly harder --
   `catalog relocate` exists and is not documented as the pre-move step.

#### Proposed Approach

**Report, direct, then adjust -- in that order, and never guess.** The pattern
already works for retirement: a check finds the condition, the operator runs one
command, and the check stops reporting it. Extend it so each finding carries the
command that resolves it. Where a condition is ambiguous -- a copy, a restore --
the report states the choices rather than picking one.

**Evidence to close.** Each condition above is detected and named; a report
naming a condition also names the command that resolves it; the Claude slug
split is joined through `path_aliases`; and a Project can be relocated before
the move as well as after.

### W97 -- Codex Thread Names and Archive State

**Work.** Read the operator's own name for a Codex thread, and make the archive
location and the recorded archive state agree.

**Two findings, both measured.**

**1. The thread name is not read.** `~/.codex/session_index.jsonl` holds
`id`, `thread_name`, `updated_at` per thread -- the name the operator gave it
in the interface. Measured: 25 entries, of which **21 are Sessions Codess has
ingested**, carrying names like `Codess Continue` and `AGENTS.md WPages.md
Status.md`. The rollout does not carry the name, so a store built from rollouts
alone reports Sessions the operator cannot recognise by their own label.

This is distinct from `~/.codess/session-names.json`, which records an alias
*within Codess*. One is the vendor's label and one is ours; conflating them
would make an operator alias indistinguishable from a vendor-stated name, so
the vendor's belongs in its own field with its own provenance.

**2. Archive location and archive state disagree.** 6 rollouts sit in
`~/.codex/archived_sessions/`, all 6 are ingested, and **3 carry
`archive_state='archived'`**. The other 3 are decoded from the archive
directory with the state unset, so the file's location and the store's record
of it say different things. Either the state should follow the location, or the
disagreement is a vendor fact worth recording -- and which it is has not been
established.

**Neither is a decode failure.** Both are evidence Codess does not read,
sitting beside evidence it does.

**Evidence to close.** A Codex Session carries the vendor's thread name where
one exists, distinguishable from a Codess alias; and a rollout's archive
location and its `archive_state` agree, or the disagreement is recorded as a
vendor observation with its reason.

### W102 -- The Option Classification, Reviewed per Flag

**Work.** The distribution in [CoNames](CoNames.md#which-options-take-a-variable)
was measured and the rule it states -- a flag names this invocation's subject, a
variable states a standing choice -- fits it. What has not happened is the
reverse check: reading each flag and asking whether its class is right for what
it does, rather than whether the totals look plausible.

**Three questions the totals cannot answer.**

1. *Which of the 110 flag-only options should have a variable.* Selection is
   correctly flag-only, but `--format`, `--raw-store-root`, and the audit tools'
   `--max-files` are standing choices an operator would set once.
2. *Which of the 34 default-only options should have neither.* A default derived
   from a measurement is evidence; a default chosen once is a decision that
   should be stated where decisions live.
3. *Whether any variable should not exist.* `CODESS_CLAUDE_WORKTREES` is off by
   default and admits Sessions about a Project rather than in it -- a per-run
   question wearing a machine-wide answer.

**Not urgent, and the reason is the measurement.** Every collision the earlier
passes found -- one spelling for two subjects, two spellings for one, a
precedence stated four ways -- is closed and tested. What is left changes which
of two correct mechanisms an option uses, which no current defect depends on.

**Evidence to close.** Each flag's class is stated with its reason, or recorded
as reviewed and correct; the CoNames distribution is regenerated from the result
rather than from the current state.

### W101 -- Reasoning Content Stored as a Summary

**The condition.** Two vendors supply different evidence and Codess stores both
under one name. Codex's `_extract_reasoning_summary` reads `payload.summary`
and its docstring is explicit -- "vendor-exposed summary text, never encrypted
reasoning state". Cursor's `thinking.text` is the reasoning itself, and the
adjacent `redactedThinking` flag marks what the vendor withheld, which only
makes sense if what remains is the content rather than a précis of it.

Both are stored as `event_kind = message.reasoning_summary` with the text in a
`reasoning_summary` metadata field.

**Why it was done, and why that reason is still partly right.** The adapter
records it: naming Cursor's evidence the way Codex names its own is what lets
one query compare reasoning across vendors, and a per-vendor spelling would make
that comparison a special case. The rule ids already differ correctly --
`codex.reasoning-summary` against `cursor.reasoning` -- so the mapping evidence
distinguishes them even though the common field does not.

**What is wrong with it.** A common value should let two vendors be selected
together without claiming they mean the same thing, and here it claims exactly
that. A reader filtering `message.reasoning_summary` gets one vendor's summary
and another's full reasoning in one result set, with nothing in the common
fields to tell them apart -- which is the "normalization conceals a meaningful
difference" case CoSchema exists to avoid.

**Options.**

| Option | Cost | Buys |
|---|---|---|
| A `reasoning_fidelity` field: `summary` or `full` | One column, one format bump | The comparison keeps working and a reader can qualify it |
| Split the Event kind: `message.reasoning` and `message.reasoning_summary` | Wire-format, and every cross-vendor reasoning query becomes a two-kind query | The kinds stop lying, at the cost the adapter comment predicted |
| Leave it, document the difference in CoSchema | Nothing | The evidence stays queryable and the difference stays findable only in prose |

**The measurement was run, and it decides it.** Over the published stores, the
text stored under `message.reasoning_summary`:

| Vendor | Rows | Median chars | Mean | Max |
|---|---|---|---|---|
| Cursor | 13,361 | 236 | 419 | 2,000 |
| Codex | 5,133 | 50 | 109 | 1,506 |

Cursor's median is nearly five times Codex's, and its maximum sits exactly on a
2,000-character bound -- a truncation, which a summary would not reach. A
50-character median is a précis; a 236-character median that clips at a bound is
reasoning. The two are different evidence and the common field says they are the
same, so **option A is the smallest honest fix**: a `reasoning_fidelity` value of
`summary` or `full`, set by the adapter that knows which it read.

**Done: `reasoning_fidelity`, set by the adapter that read the field.**

`summary` where the vendor supplied a précis, `full` where it supplied the
reasoning. Codex sets `summary` because `_extract_reasoning_summary` reads
`payload.summary` and its docstring already says what that is; Cursor sets `full`
because `thinking.text` is the reasoning and `redactedThinking` marks what was
withheld -- a flag that only makes sense beside content.

**Why not split the Event kind.** `message.reasoning` and
`message.reasoning_summary` as separate kinds would stop the lie, and would make
every cross-vendor reasoning query a two-kind query. The adapter comment predicts
exactly this: naming Cursor's evidence the way Codex names its own is what lets
one query compare reasoning across vendors, and the fix should keep that rather
than trade it.

**Why not leave it documented.** The difference is 5x in the median and the
common fields do not carry it, so a reader who has not read CoSchema cannot see
it at all. A prose note is findable only by someone who already suspects.

**Why a field rather than a longer name.** Fidelity is a property of the
evidence, not of the kind: a vendor that later exposes both would need two kinds
and one Event, which a field handles and a name cannot.

**Cost, and it was lower than proposed.** No column and no format bump: the
value lives in the Event's metadata, which is where a fact an adapter
*establishes* rather than reads belongs. `_merge_metadata` gained an `extra`
argument for exactly that -- the fidelity is known from which field was parsed
and appears nowhere in the payload. The `event_kind` vocabulary is unchanged, so
no stored query breaks.

**Verified in one store set**, which is the condition that made the item worth
opening: Zero400 holds 12 Codex rows marked `summary` and 6,374 Cursor rows
marked `full` under one Event kind, now distinguishable from the common fields
alone.

**Evidence to close.** A query selecting reasoning across vendors can state,
from the common fields alone, whether each row is a summary or the reasoning
itself.

### W98 -- Field Names That Spell the Algorithm

**Work.** Rename the ten `*_sha256` fields to `*_digest`, which is the rule
[CoNames](CoNames.md#digest-fields) states and the majority already follow: 34
`contract_digest`, 12 `content_digest`, 11 `semantic_digest` against ten names
carrying the algorithm.

**Why it is not cosmetic.** A value from `codess_canonical_hash(256, 256, …)`
*is* a bare SHA-256 at those widths, so the name reads as accurate. Change a
width and the name is wrong with nothing to catch it: the value still exists,
still verifies against itself, and now misdescribes what it is. The rule keeps
the algorithm's name in `hashing` alone, so changing it is one edit rather than a
rename across every document that carries a value.

| Name | Occurrences | Where it is written |
|---|---|---|
| `selection_sha256` | 13 | Baseline selection documents |
| `stored_sha256` | 8 | Raw-object records |
| `resolved_selection_sha256` | 5 | Baseline selection documents |
| `catalog_sha256` | 4 | Reviewed-catalog documents |
| `raw_manifest_sha256` | 4 | Snapshot manifests |
| `manifest_sha256` | 3 | Snapshot manifests and current pointers |
| `content_sha256`, `file_sha256`, `project_list_sha256`, `row_sha256` | 1 each | Assorted |

**Cost, and why it is Low rather than deferred.** Each is wire-format or a
released document, so each costs a regeneration or a format-version bump --
unlike `plan_digest`, which was renamed on sight because a retention document is
produced per run and read immediately, so it cost one version bump and no stored
data. `manifest_sha256` is the sharp one: it appears in every `current.json`, so
renaming it makes every published pointer unreadable until republished.

**Batches with the next wire-format change**, which is Sprint 1. Renaming them
alone would pay a full regeneration for a change with no behavioural content.

**Evidence to close.** No field name outside `hashing` names an algorithm; a test
asserts it over the released schema and the documents Codess writes.

### W99 -- Two Trees for One Kind of Artifact

**The condition.** Codess writes format-versioned records of what a command did
into two directories under the machine store, by two different mechanisms, and
reads back only one of them:

| | Refresh | Retention |
|---|---|---|
| Written to | `reports/refresh-<stamp>.json` | `receipts/retention/<stamp>.json` |
| Default decided in | `admin_cmd._refresh`, the command layer | `retention.apply_plan`, the domain layer |
| Format key | `receipt_format` | `format` |
| Format value | `codess.refresh-receipt/1` | `codess.retention-receipt/3` |
| Read back | Yes -- `latest_refresh_observations` feeds the Project inventory | No reader |

**Both are receipts by their own naming**, and the split is not a distinction
between kinds of document -- it is two independent decisions that never met. The
path construction is the same shape in both places: a timestamp under a store
subdirectory. What differs is which subdirectory, and which layer decides.

**The cost is not hypothetical.** Passing `--receipt` to `storage prune` with a
path under `reports/` puts a retention receipt in the refresh tree, where
`refresh_receipts` ignores it -- it globs `refresh-*.json` -- so the record exists
and nothing will ever read it. That happened during the 2026-08-25 prune and was
found by inspection rather than by any check.

**What is not obviously wrong**, and is why this is an item rather than a fix:

- *A tree per subject is defensible.* `receipts/retention/` admits a second
  retention-adjacent document later without the glob becoming ambiguous, which a
  flat `reports/` with a filename prefix does not.
- *`reports/` may be the wrong name rather than the wrong tree.* It holds
  receipts, and `codess storage report` writes an observation elsewhere, so the
  directory is named for a thing it does not contain.
- *`receipt_format` cannot simply become `format`.* It is the gate
  `refresh_receipts` uses to skip unrelated JSON and it is read from files
  already on disk, so the rename is wire-format for every stored receipt --
  unlike `plan_digest`, which cost one version bump because nothing had been
  stored.

**Done: one tree, `receipts/<kind>/`, and `receipt_format` unchanged.**

| Option | Cost | Buys |
|---|---|---|
| **One tree, `receipts/<kind>/`** | Move refresh receipts; the reader's glob changes | One place to look; a third kind needs no decision |
| One tree, flat with prefixes | Same move; glob per prefix | Fewer directories, ambiguous as kinds grow |
| Keep both, document the rule | Nothing | The condition stays, and the next author decides again |

**Why the tree and not the flat form.** `receipts/retention/` already exists and
already works. A kind per directory means a reader globs one directory and gets
one kind; a flat tree with prefixes means every reader carries a prefix its
producer must match, which is the coupling the current `refresh-*.json` glob
already demonstrates -- the retention receipt I wrote into `reports/` was ignored
by exactly that filter.

**Why `receipt_format` stays and `format` does not become it.** The key is the
gate `refresh_receipts` uses to skip unrelated JSON, and it is read from files
already on disk. Renaming it is wire-format for every stored receipt, and buys
consistency with 21 documents that were never read back. The retention documents
use `format` and are produced per run, so they cost nothing to change and have
already moved twice; the refresh receipts are the ones with history.

**What tips it.** The two receipts are read differently and that is not going to
change: refresh receipts feed the Project inventory, retention receipts are read
by a person after a deletion. A shared tree makes them findable together without
claiming they are interchangeable, which a shared *format key* would.

**Migration is a move, not a rewrite.** `reports/refresh-*.json` becomes
`receipts/refresh/*.json` with the name unchanged; `latest_refresh_observations`
globs the new directory. A receipt left in the old location is not read, which
is the current behaviour for a misplaced one anyway.

**Not urgent.** Nothing is lost today: both kinds are written and the refresh
half is read. What the split costs is a reader's time and the next author's
decision, which is why this is Normal and not High.

**Evidence to close.** One rule states where a receipt is written and which
layer decides; a receipt written by any command is readable by whatever consumes
that kind; and the format key is spelled one way or the two spellings are
recorded with the reason.

### W100 -- What `storage prune` Can Be Asked For

**The options it has**, and what each decides:

| Flag | Decides | Default |
|---|---|---|
| `--apply` | Whether anything is deleted at all; without it the command emits a plan | Report only |
| `--receipt PATH` | Where the receipt is written | `receipts/retention/<applied_at>.json` |
| `--reference-catalog PATH` | A catalog whose snapshot references block deletion; repeatable | None |
| `--working-archives` | Whether working archives are candidates | Excluded |
| `--keep-comparison-revisions` | Whether to retain several >=1 GiB revisions of one logical source | One kept |
| `--output PATH` | Where the plan or receipt goes instead of stdout | stdout |
| `--store PATH` | Which durable store | The configured one |

**Resolved: one counting rule, one implementation, and `--keep` on the
command.** `CODESS_KEEP_SNAPSHOTS` counts snapshots kept, current included, and
both retention paths read it through `snapshot.superseded_beyond_depth`:

| Value | Keeps | |
|---|---|---|
| 0 | Every snapshot | The audit case: an operator comparing a sequence of rebuilds |
| 1 | The current alone | The shallowest retention |
| 2 | The current and one past | The default: a rollback target |
| N | The current and N-1 past | |

**Counting the total rather than the prior generations is what made this
settleable.** A count of prior generations has no spare value -- "keep nothing
past" and "keep everything" both want 0 -- and the two paths read that one value
in opposite directions: the trim kept everything, the prune kept one. Including
the current snapshot in the count gives 0 its own meaning and leaves 1 to say
what the prune was hard-coding.

**Both paths take a parameter as well as reading the variable.**
`create_snapshot(keep_total=...)` bounds the trim for a caller producing a
throwaway snapshot, and `codess storage prune --keep N` bounds a deliberate
reclaim. The variable remains the machine's standing policy; neither path
requires setting it to vary one run.

**The plan records what it applied.** `policy` is `keep-N-per-project` rather
than a constant, so a receipt read later states the rule it followed rather than
the rule in force when it is read.

**Evidence to close.** One retention depth governs both publication trimming and
`storage prune`, or the two are separately named and each states why; a plan
records which policy it applied rather than a constant.

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
