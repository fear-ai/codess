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
item from an unfinished one. Each states how it was obtained. Figures that only
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

Priority states how much an item matters. It does not say when the work happens
or what blocks it; the queue says that.

## Open Items

Sixteen items, ordered by identifier. Read the queue for what to do next and
[Item Detail](#item-detail) for scope and evidence.

| ID | Priority | Status | Work | Blocked by |
|---|---|---|---|---|
| W04 | High | Planned | Shared candidate-record contract, enforced at the decode boundary | -- |
| W05 | High | Planned | Run named real investigations against the query surface | -- |
| W14 | Normal | TODO | Require or mark Project identity for direct library writes | -- |
| W16 | Normal | Postponed | Evaluate external investigation interfaces | No consumer |
| W17 | Normal | Postponed | Expand cross-Project analysis inputs | Baseline 2 |
| W35 | Low | Postponed | Resolve the validation-fixture inventory | -- |
| W43 | Low | Withdrawn | Table-drive request validation | -- |
| W50 | Normal | Planned | Reconcile schema names with defined terminology | Batches with W51 |
| W51 | Normal | Planned | Resolve source-identity naming and suffix rules | Batches with W50 |
| W55 | Normal | Planned | Unify text and record parsing across the decode layer | -- |
| W64 | Normal | Planned | Decide and enforce the typing posture | W04 |
| W65 | Normal | Planned | Consolidate remaining relay parameter groups | W04 (partly) |
| W66 | High | Planned | Unify configuration into one subsystem | -- |
| W67 | Normal | Planned | Move relay fields into the objects that carry them | -- |
| W70 | Normal | Planned | Re-partition documentation; remove cross-document redundancy | -- |
| W71 | Normal | Planned | Adopt the reporting facility in the command layer | -- |

## Queue

One ordering. The reason for each position is a dependency or a stated cost,
not a preference.

| Rank | Item | Why here |
|---|---|---|
| 1 | **W05** | The only item whose output is evidence about whether the query surface answers real questions rather than machinery that supports them. Needs no rebuild: format-6 stores exist and are audited, so the work starts against current data. |
| 2 | **W04** | Structural, and coverage reporting states loss against exactly the profiles it enforces -- a report built against unenforced profiles attests to nothing. Baseline 2's substance. |
| 3 | **W50 + W51** | The naming resolutions format 6 did not carry. Both are wire-format, so they land together as one rebuild or they cost two. |
| 4 | **W67** | Immediate and mechanical: each relay already has an object to take, and the measurement separating a relay from a builder is written down. Above the configuration work because it is the smaller half of the same problem and does not wait on it. |
| 5 | **W66** | The largest structural item, and the one whose absence keeps producing the defects above. Below W67 only because `ChildInvocation` already proved the shape on the argv half. |
| 6 | **W64 + W65** | After W04, which changes the decode boundary a third of the type errors sit behind; deciding the strict-flag set first would decide it against a boundary about to move. W65's record-context cluster is adapter signatures, so consolidating first rewrites them twice. |

**Not queued**, each for a stated reason rather than for lack of room:

| Item | Why not queued |
|---|---|
| **W14** | Independent. No item blocks it and none waits on it. |
| **W16** | No consumer has asked for external interfaces, and an item nobody is waiting for does not belong in an ordered queue. |
| **W17** | Deferred to Baseline 2. Specifying a cross-Project surface against a decode W04 has not enforced would fix it against a surface still changing underneath. |
| **W35** | No longer gates anything a store does; it is now a question about what the released set should contain. |
| **W43** | Withdrawn on inspection. Retained so the analysis is not repeated. |
| **W55** | Correctness-neutral, so it batches with anything and blocks nothing. |
| **W70** | Documentation only, and continuous enough that queuing it would imply an end date it does not have. Do it alongside whatever item touches a document. |

## Dependencies and Batching

**W50 and W51 must land together.** Both rename stored columns, and each alone
owes a full rebuild of every Project from vendor Sources -- Codess never migrates
a store, because the store is a projection and the way to change a projection is
to recompute it. Landing them separately costs two rebuilds for one result.

**What a rebuild costs.** A wire-format change is not an `ALTER TABLE`.
`require_store` accepts only the current format, for reading as well as writing,
so every `.codess` store on a machine is unreadable by the new code until its
Project is reingested. Concretely: install the new contract, `codess ingest
--force` every Project, republish -- once per Project on the machine, regardless
of how many columns the format changed. That is the argument for batching: the
cost scales with the number of Projects and not with the size of the change, so a
change that is ready should not wait, and a change that is not ready should not
force the batch to wait for it.

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
3. **Run `tools/quality_report.py` before declaring a kind complete.** It gates
   ruff and mypy against recorded ceilings and has caught regressions the test
   suite did not.

### Stopping Points

Where partly-done work stopped, so an unfinished item is visibly unfinished
rather than mistaken for untouched. None of these is half-applied: each is
either not started or has a stated boundary.

| Work | Stopping point | Item |
|---|---|---|
| Naming convention applied codebase-wide | Written and mechanically enforced for the two cases a checker catches: a parameter shadowing a builtin (ruff `A`), and a name rebound to a different type (mypy `assignment`). The subject-word and general-word rules are **not** applied to existing names. | W64 |
| Relay parameter consolidation | `run_ingest` converted as the worked example. Five further relays identified and untouched. | W67 |
| Configuration unification | Measured and not begun. | W66 |
| mypy strict flags | The count was reduced by repair rather than reclassification. Which flags to enable is undecided. | W64 |
| Record-context parameter group | Identified; blocked behind W04 because it changes adapter signatures. | W65 |

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

**Evidence to close.** Separate vendor stores cannot silently create unrelated
Project identities for one repository.

**Cost.** Independent: no item blocks it and none waits on it.

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
| Timestamp parsing | In all three adapters with differing fallbacks, where one bounded parser would serve |
| Codex output header | The only free-text regex carrying decoded fields; keep the regex, move its field table beside the other vendor vocabularies |

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
   `strict_optional` and `warn_return_any` were deferred to W04 on the grounds that
   errors concentrate at the decode boundary, which is measurably false -- a
   majority sit outside it.
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

**Evidence to close.** One declaration per setting names its flag, variable,
default, and type; precedence is stated and tested; no module reads `os.environ`
for a declared setting; a flag name appears in exactly one module.

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

**Evidence to close.** Every relay of five or more parameters takes an object or is
recorded as a builder; a call site cannot mis-order same-typed arguments; no
invocation is constructed twice where one would do.

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
