# CoReview

CoReview records what Codess review and implementation established: the defects
found, the measurements that decided each disposition, and the rule each one
left behind. It is evidence, not a plan -- open work is in
[CoTasks](CoTasks.md), and intended structure is in [CoPlan](CoPlan.md).

**A finding is kept for its rule, not its narrative.** "The guard must precede
the rename" is durable and checkable; the account of how that was discovered is
not, and three paragraphs of it make the rule harder to find. Where a
measurement justifies a constant, a mapping, or a removal, the measurement
stays: it is what makes a decision checkable by a reader who was not present.

**Identifiers are not cited.** A completed item is removed from CoTasks, so
`W12` in a later reader's hands resolves to nothing. Where an item is named
here it is because it is still open and still tracked.

## Table of Contents

- [1. Review Method](#1-review-method)
- [2. Compliance Summary](#2-compliance-summary)
- [3. Open Findings and Their Items](#3-open-findings-and-their-items)
- [4. Findings and Dispositions](#4-findings-and-dispositions)
- [5. Real-Source Validation](#5-real-source-validation)
- [6. Mechanical Enforcement](#6-mechanical-enforcement)

## 1. Review Method

The review examines:

1. package entry points, command dispatch, module imports, and SQL ownership;
2. source discovery, vendor access, adapter output, and mapping enforcement;
3. CoSchema package verification, DDL agreement, transactions, publication,
   and read-only query behavior;
4. identity, provenance, raw evidence, resource bounds, and large-file access;
5. unit, contract, adapter, store, query, CLI, integration, and scale tests; and
6. branch coverage as evidence about which implementation paths the tests
   actually execute in the measured process.

`pytest -q`, package-contract tests, `compileall`, static import inspection,
targeted SQL-location searches, and branch coverage provide the repeatable
automated basis. Real vendor Sources remain a separate validation layer: the
automated suite uses temporary roots and fixtures so it cannot alter a
developer's live harness data.

### 1.1 Retention Rules for Unused and Unproven Code

Reviews generate pressure to keep things. The reasons offered are familiar
and mostly bad, and naming them is what stops them being reused:

- *"It might be needed."* A caller that does not exist has no requirements,
  so the code cannot be right for it. Write it when the caller does.
- *"It was not broken by this change."* Not being broken is the condition
  for leaving code alone, not a reason to keep code that has no consumer.
- *"Removing it is out of scope."* Scope bounds what a change must address,
  not what it may. A finding recorded and not acted on becomes a note.
- *"Tests pass either way."* That is the property of dead code, not evidence
  for it. `store.replace_source_sessions` and the `query_reports` residue
  both passed the suite for months after their callers moved.
- *"It is symmetric."* Symmetry justifies keeping the *inverse of something
  used* -- `BKB` against `KB`, where the next caller would otherwise inline
  `/ 1024`. It does not justify a wrapper over an exported constant:
  `field_state.is_vacant` was `state in VACANT_STATES` and was removed.
- *"A tool flagged it, so it goes."* The opposite failure. The unreferenced
  copy of `slug_to_path` was the *correct* one; deleting it mechanically
  would have kept the defect.

**The rule.** Code stays when it has a consumer, or is the inverse of
something with one, or is a boundary a test exercises deliberately. Anything
else is removed in the change that finds it. Where removal is genuinely
blocked -- a released contract, a wire format, an unlanded decision -- it
gets a work item and an execution category, never a comment saying it might
be useful later.

**The same rule governs recorded exceptions.** An entry in
`schema/field-coverage-baseline.json` states that a column is legitimately
empty for a vendor, which suppresses a check. It is admitted only with
evidence that the source does not carry the value, or that the null is a
property of the sample. "Not yet examined" is not a reason to accept: the
first version of that file accepted all twelve observed gaps, six of which
were merely unexamined, which turned a gate into a record of what had been
noticed. It now accepts six, each with the evidence cited, and the other six
fail the check until they are closed or explained.

## 2. Compliance Summary

| Area | Assessment | Basis |
|---|---|---|
| Entry and packaging | Compliant | The installed `codess` command and source-tree entry both dispatch through `codess.project:console_main`; package discovery follows the documented `src/` layout. |
| Discovery | Largely compliant | Scan is index-led, rejects broad system roots, prunes known generated trees, and attributes nested workspaces to repository Projects. Known-source fallback traversal remains bounded to vendor storage rather than arbitrary work trees. |
| Vendor separation | Compliant | Source traversal is separated from decode for all three vendors. `cursor_source` owns every vendor-table query and connection; no adapter has a SQLite dependency. |
| Mapping and classification | Partially compliant | Mapping profiles, traces, field diagnostics, and representative adapter fixtures exist. Common runtime conformance and strict behavior are not yet enforced uniformly across vendors. |
| CoSchema persistence | Compliant in the principal path | The released package is hash-checked, the DDL is centralized, logical and physical contracts are compared, foreign keys are enabled, and source replacement commits or rolls back atomically. |
| Query | Partially compliant | The typed executor provides bounded, deterministic, multi-store results with provenance and stable identities. The fixed reports are in `query_reports` rather than the command renderer, but remain outside the request contract, so query-contract parity is still incomplete. |
| Publication and evidence | Largely compliant | SQLite backup, manifest hashes, atomic pointer replacement, content-addressed raw objects, and read-time verification implement reproducible publication. Raw-mode semantics are resolved: the least-retaining mode is named `observe` and keeps its manifest observation (13.4.4). |
| Derived values | Compliant | Every digest routes through `codess/hashing.py`, which fixes the algorithm, the canonical JSON form, and the supported widths; a contract test fails if a `hashlib` call or an undeclared width appears elsewhere. Each value's lifetime and resilience requirement is stated in 13.4.8. Where an algorithm name may appear in a stored value remains W34's question. |
| Configuration | Compliant | Scan, ingest, and query validate resolved configuration before source work; built-ins, environment, command arguments, and JSON policies have explicit ownership. |
| Operational reporting | Compliant | `codess.reporting` is one structured facility: counters, events, and spans behind three gates, five sinks selected by profile, and channel separation verified byte-identical for stdout (4.12, 4.15). `ProgressTrace` is gone. |
| Maintenance wrappers | Partially compliant | Most wrappers adapt arguments and call library operations. A small number still contain catalog or pruning workflow logic that belongs in a domain module. |
| Tests | Broad but unevenly observable | Contract, adapter, store, query, CLI, integration, hazard, and scale behaviors are exercised. Subprocess execution prevents the current coverage run from attributing much scan and ingest execution to those modules. |

## 3. Open Findings and Their Items

| Finding | Impact | Related work |
|---|---|---|
| Runtime mapping conformance | Released profiles do not govern every emitted vendor candidate uniformly | W04 |
| Query path fragmentation | Query-contract parity is incomplete; the fixed reports now have a domain home but remain outside the typed executor by design (13.4.1) | W05, W13 |
| Ancillary unbounded reads | Resolved: persisted tool output is refused above a bound *before* the read, the worktree digest records size and mtime past 32 MB, and the raw manifest is streamed (4.14) | Closed |
| Project identity fallback | Direct library writes can create unrelated provisional Project IDs | W14 |
| Test observability | Child-process scan and ingest paths are not attributed by ordinary coverage | W13 |
| Configuration fragmentation | 172 flags, 83 environment variables, and 39 names spelled in more than one module; a default is decided in up to four places with no stated precedence (4.18) | W66 |
| Relay parameter groups | Five functions forward eight or more parameters that exist only to reach another call (4.18) | W67 |
| Operational reporting fragmentation | Resolved: one event contract, three gates, five sinks, and per-sink levels so retention and display are independent (4.12, 4.15) | Closed |
| Discovery scoping | Resolved: both lists are environment-configurable and validated, and traversal now carries a directory budget, a deadline, and filesystem-boundary reporting (4.13) | Closed |
| Registry retention | Resolved: `storage registry-prune` reports by default and removes under `--apply` | Closed |
| Session discovery coupling | Resolved: `in_work_root`, `project_boundary`, `is_aggregator`, and `canonicalize` are module-level with explicit parameters, so the rules are testable without a populated vendor filesystem | Closed |
| Canonical serialization divergence | Resolved: every digest over a structure routes through one canonical encoder, so equal content cannot hash differently | Closed |
| SQLite connection and driver boundary | Resolved: both openers own the same contract, the isolation model is stated, and the store layer raises its own error (13.4.11) | Closed |

## 4. Findings and Dispositions

### 4.1 Source and Command Boundaries

The Cursor source-access boundary violation is resolved: **W10** is complete
and described in 6.4. `cursor_source` owns all vendor SQL and connections;
the adapter receives selected records by path and has no SQLite dependency.

Command-layer separation was tracked by **W06**, which is complete. Vendor
ingest coordinators are in `codess/ingest_sources.py`, publication in
`codess/ingest_publication.py`, and the report queries in
`codess/query_reports.py`. The command modules retain argument adaptation,
presentation, and exit status, and neither decodes a source, opens a
publication transaction, nor writes a report query. The few maintenance
scripts that still perform catalog or pruning workflows require the same
treatment, and are not part of this item.

**What had blocked it.** Nothing external. W06 had no dependency on another
item, no undecided design question, and no missing contract -- it stayed open
because the change was large and had no safe increment. `ingest_cmd.run()`
was roughly a thousand lines, half the module, holding 53 top-level
statements and three nested closures. It opened transactions, handled raw
records, coordinated publication, and rendered results in one scope, so any
edit touched everything and no test covered a part of it in isolation. That
was the obstacle: not difficulty in knowing what to do, but the absence of a
first step that could not break ingest. The six increments below are the
answer that worked, and are retained because the sequencing is the reusable
part -- each preserved behavior, each was verifiable on its own, and none
depended on a later one.

**Increments that are individually safe.** Each step below preserves
behavior, is verifiable by the existing suite passing unchanged, and leaves
the tree working. None depends on a later one.

| Step | Change | Why it is safe | Evidence it worked |
|---|---|---|---|
| 1 | Lift the three closures in `run()` to module level with explicit parameters | They capture argument values, not accumulating state, so lifting is mechanical | Existing ingest tests pass unchanged |
| 2 | Extract each `run()` phase -- configuration resolution, Project selection, per-vendor ingest, publication, reporting -- into named private functions in the same module, still called in order | Pure code motion within one module; no import or signature crosses a boundary | Same, plus each phase is now separately callable in a test |
| 3 | Add tests against the extracted phase functions | Adds coverage without changing code | New tests pass; coverage attributes to the phases rather than one opaque call |
| 4 | Move the vendor ingest coordinators (`_ingest_cc`, `_ingest_codex`, `_ingest_cursor`) into a `codess` domain module | They already take explicit parameters after step 2 and return reports; the command keeps calling them | Existing tests pass; `ingest_cmd` loses its transaction and raw-record handling |
| 5 | Move publication coordination likewise | Same shape as step 4 | Same |
| 6 | Replace `query_cmd`'s direct report SQL with typed-executor calls, one report at a time | Each report is independent, so a single report can be converted and compared against the previous output | Report output is byte-identical before and after |

Steps 1 to 3 are preparation and can be done without deciding anything.
Step 4 is where the module boundary actually moves, and it is only safe
*after* step 2, because extracting a coordinator out of a thousand-line
function and into another module at once is the change that has been
deferred. Step 6 is independent of 1 to 5 and can proceed in parallel.

**Why the vendor blocks are not simply extracted with parameters.** The
obvious move -- lift each `if "cc" in sources:` block into a function -- was
measured rather than assumed. Each vendor block reads 14 to 16 names from the
enclosing scope and the publication block reads 27, for 30 distinct values
overall. Raw counts do not settle the question, though; the roles do:

| Role | Count | Examples | What it implies |
|---|---|---|---|
| Run-wide configuration | 8 | `iopt`, `opts`, `force`, `min_size`, `sources`, `progress_trace`, `staging_root`, `registry_root` | Identical for every Project. Belongs in one object built once, not threaded through each call |
| Per-Project identity | 5 | `project_path`, `project_entry`, `state_path` | Genuinely varies per iteration; the natural parameters |
| Accumulators mutated in place | 5 | `proj_stats`, `changed_vendors`, `diagnostics` | Sets and dicts, so a callee can add to them through a plain parameter |
| Counters read and rebound | 3 | `project_ingested`, `project_had_error` | The hard case: `+=` and `=` on integers and booleans |
| Rollback markers | 3 | `resource_start`, `review_start` | Positions captured before the block so a failure can truncate back |
| Other per-Project state | 6 | `raw_store`, `project_raw_records`, `seal_upgrade` | Mostly one-way inputs |

Two conclusions follow. First, a fourteen-parameter signature is not the
alternative -- eight of those values are run-wide, so the honest shape is a
configuration object plus a handful of per-Project arguments. Second, the
three rebound counters are why the extraction is step 4 rather than step 2:
a function cannot rebind its caller's integer, so each extracted block must
*return* its counters and the caller must accumulate them. That is a real
interface change, not code motion, and it is exactly the sort of change that
should not ride along with a mechanical one.

**How the state should be packaged.** The role analysis above says what
needs to travel; the measurements say where the boundaries are. Two facts
decide the shape.

First, **only three values genuinely accumulate across Projects**:
`had_error`, `total_ingested`, and `total_events`. Everything else assigned
before the loop is either configuration that never changes or a value the
loop overwrites each iteration. A run-level result is therefore small.

Second, **`opts` is already an ad-hoc version of both objects, fused into
one**. It carries nineteen keys, of which six -- `project_id`,
`location_id`, `content_actions`, `raw_records`, `raw_store`, and
`raw_records_changed` -- are reassigned inside the Project loop. A reader
cannot tell from a call site whether `opts["raw_store"]` is run
configuration or this iteration's store, and a function that receives `opts`
receives both. That fusion, not the parameter count, is the actual defect.

Three objects, distinguished by lifetime:

| Object | Lifetime | Mutability | Holds |
|---|---|---|---|
| `IngestConfig` | One run | Frozen | Resolved arguments and policy: sources, resource limits, raw mode, force, minimum size, registry root, staging root, validate-only. Built once by `_resolve_ingest_request` |
| `IngestRun` | One run | Mutable, small | The three accumulators plus the shared services a run owns: progress trace, diagnostics counter, per-vendor `source_stats` |
| `ProjectRun` | One Project | Mutable | Identity (path, entry, binding, state path), this Project's accumulators (`proj_stats`, `changed_vendors`, `catalog_changed_vendors`), counters (`ingested`, `processed_events`, `had_error`), rollback markers, and per-Project services (`raw_store`, `raw_records`) |

Methods rather than bare fields, because the accumulate-and-report pattern
is what the current code spells out longhand at every site:

```text
IngestConfig                       # frozen; no methods beyond accessors
    store_path(project, vendor)    # replaces _store_path's five arguments

IngestRun
    absorb(project_run)            # folds one Project's counters into the run
    note_failure()                 # the had_error = True that appears 8 times
    summary()                      # what _report_ingest_outcome renders

ProjectRun
    record_vendor(display, n, events, failed, store_changed)
                                   # the block repeated for all three vendors
    note_failure()
    rollback_markers()             # resource/review/diagnostic positions
```

`ProjectRun.record_vendor` is the piece that resolves the counter-rebinding
problem: the three per-vendor blocks currently rebind `project_ingested`,
`project_processed_events`, `project_had_error`, `total_ingested`,
`total_events`, and `had_error` in the enclosing scope, which is precisely
what an extracted function cannot do. Calling a method on an object it was
handed works, because the object is mutable and shared rather than rebound.
`IngestRun.absorb` then folds a finished Project into the run once, instead
of six `+=` statements interleaved through the vendor blocks.

Two constraints on the design. The per-Project object must not hold a
reference to the run object: the direction is that a Project reports upward
when it completes, so a Project cannot silently mutate run totals mid-ingest
and leave them inconsistent if it later fails. And `IngestConfig` must be
frozen, because the current `opts` demonstrates what happens otherwise --
values written during one Project silently become inputs to the next.

The migration order follows from lifetimes rather than from size.
`IngestConfig` first, since `_resolve_ingest_request` already computes
exactly its contents and returning a frozen object instead of a tuple
changes nothing else. `ProjectRun` second, which is what makes the vendor
blocks extractable. `IngestRun` last, since its value appears only once the
vendor blocks stop rebinding run totals directly.

`IngestConfig` and `VendorStore` are implemented.

`IngestConfig` wraps the existing options mapping rather than restating its
seventeen keys as fields, since those keys are already contract-documented on
`build_ingest_run_options` and a second copy would be a second thing to keep
current. What it adds is a boundary that actually holds: `frozen=True` stops
field rebinding, and the mapping is stored as a `MappingProxyType` over a
*copy*, so neither `config.sources = ...` nor `config["force"] = ...` nor a
later edit to the caller's dict can change resolved settings. The remaining
gap is nested values, which a deep freeze would cost more to close than it is
worth; the guarantee is "no accidental rewrite through this object", not an
immutable object graph.

One field is deliberately excluded from that guarantee. `staged_store_roots`
is registered partway through a run when a rebuild stages a Project, and
removed on promotion, so it is live shared state rather than a setting.
Copying it broke rebuild staging, which the existing suite caught
immediately; it is now typed `MutableMapping` so the exception is visible
rather than implied.

`VendorStore` unifies three free functions -- path resolution, store creation
with catalog sync, and post-ingest totals -- that each re-derived the same two
facts: where a store lives given the run's staging arrangement, and what the
vendor is called in a report. The vendor display-name mapping had been
written out at two sites and its inverse at a third; all three now read one
table. The class is frozen because a store's identity does not change once
chosen, and its methods are `path`, `exists`, `create`, and `totals`.

`total_errors` replaces the paired `had_error`/`project_had_error` booleans.
The two were always set together, so a count costs nothing extra and carries
strictly more: reports now say how many failures occurred rather than only
that one did, and zero reads naturally as no errors.

`opts` remains the open case. It carries three lifetimes at once -- run-wide
settings mirrored from the options mapping, run-wide collectors that
accumulate across Projects, and six keys reassigned on every loop iteration.
Every adapter takes the whole dict, so splitting it changes their signatures;
that is the step-4 interface change rather than something to do piecemeal.
The boundary is now documented at the construction site so the next reader
sees which keys belong to which lifetime.

**What is actually being counted.** The state threaded through `run()` was
enumerated rather than estimated. Eighteen values are tracked, at three
levels that form a hierarchy, plus a fourth group that is derived and should
never be stored at all:

| Level | Values | Mutation sites |
|---|---|---|
| Per vendor, within one block | `n`, `e`, `failed`, `store_changed` | Returned by `_ingest_*`, consumed immediately |
| Per Project | `project_ingested`, `project_processed_events`, `project_errors`, `proj_stats`, `changed_vendors`, `catalog_changed_vendors` | 8 rebindings plus 6 collection updates |
| Per run | `total_ingested`, `total_events`, `total_errors`, `source_stats`, `diagnostics` | 15 rebindings plus 9 collection updates |
| Derived | `overall_sessions`, `overall_events`, and three `status` expressions | Recomputed at each use |

Two observations shape the design. The counters are **the same three
quantities at two scales** -- sessions ingested, events processed, errors --
so a per-Project tally and a run tally are one type used twice, not two
types. And every `status` is a function of the error count
(`"failed" if total_errors else "accepted"`), which is why status is a
property rather than a field: storing it would allow it to disagree with the
count it summarizes.

**The shape that follows.** One tally type, held at both levels, with the
run holding the Projects' results rather than each Project reaching upward:

```text
IngestTally                       # the three counters, used at both scales
    sessions, events, errors      # ints
    add(sessions=, events=, errors=)
    absorb(other)                 # fold a finished tally into this one
    status                        # property: derived, never stored
    failed                        # property: errors > 0

ProjectOutcome                    # one Project's result
    tally: IngestTally
    store_totals: dict            # per-vendor session/event counts
    changed_vendors: set
    catalog_changed_vendors: set
    record_vendor(display, sessions, events, failed, store_changed)

IngestOutcome                     # the whole run
    tally: IngestTally
    source_stats: dict
    diagnostics: Counter
    absorb(project_outcome)       # the only upward path
    overall_sessions / overall_events   # properties over source_stats
```

The design is implemented. `record_vendor` is what removed the rebinding
problem. The three vendor
blocks currently do six `+=` statements each against enclosing variables;
they would instead call one method on an object they were handed. Because
the object is mutable and shared rather than rebound, an extracted function
can update it -- which is precisely what a plain integer parameter cannot
do, and the reason steps 4 and 5 have been blocked.

`absorb` is the only path from a Project to the run, called from the Project
loop's `finally` so it runs exactly once whether the Project completed or
failed. That direction matters: today a vendor block updates
`project_ingested` and `total_ingested` in adjacent lines, so a Project that
fails after the first vendor has already contributed to the run totals. With
`absorb` the run learns about a Project exactly once, after its outcome is
known.

**Where closures remain, and why.** Nesting is justified when a helper
rebinds enclosing state, because that is precisely what a module-level
function cannot do. Six closures survive; they divide cleanly:

| Closure | Rebinds via `nonlocal` | Verdict |
|---|---|---|
| `_ingest_cursor.flush`, `ingest_db_stream.flush` | `current_events`, `largest`, `current_tick` | Justified. A batch flusher exists to reset the counters it reads; returning them would make every call site do the reset |
| `run.cleanup_cursor_cohort` | `cursor_cohort_temp` | Justified today, but it is the one whose enclosing state should move into the step 4 refactor rather than persist |
| `_sqlite_backup.backup_progress` | `last_progress_tick` | Justified. It is an SQLite progress callback with a fixed signature, so throttling state has nowhere else to live |
| `_ingest_cc.record_source`, `_save_stats.mut` | none | Not justified by rebinding. They read enclosing values only, so they lift to module level with explicit parameters exactly as the three in `run()` did |

The rule the audit applies: a closure that rebinds is a design choice, a
closure that only reads is an accident of where it was written. The two
without `nonlocal` are candidates for the same treatment already applied in
step 1, and are noted here rather than done immediately because they sit
inside functions that step 4 will move.

**Progress.** Steps 1 to 5 are complete and step 6 has begun. `run()` is down
from about a thousand lines to 684, and its top-level statement count from 53
to 35, with every increment landing on an unchanged suite.

| Step | State | What moved |
|---|---|---|
| 1 | Done | Two of three closures lifted to module level. `cleanup_cursor_cohort` stays: it rebinds an enclosing variable through `nonlocal` at four sites, so lifting it means introducing shared state, which belongs with step 4 rather than before it |
| 2 | Done | Request resolution, the completion report, the preflight report, the repeated vendor store-open, and the post-ingest store totals are named functions. The store-open and store-totals cases were verbatim duplication across all three vendors, differing only in the display name |
| 3 | Done | `tests/test_ingest_phases.py` covers source-selector expansion, argument rejection, store-path resolution under preflight and rebuild staging, and vendor store creation -- paths that previously required running a whole ingest to reach |
| 4 | Done | The three vendor coordinators and the nine helpers they share are in `codess/ingest_sources.py`, and `ingest_cmd` no longer decodes a source or writes a store during ingest. Validated as the step required: `tests/test_ingest_sources.py` calls the module directly (46 cases over the helpers and all three coordinators, each against a Project fixture carrying one Session for its vendor), and one Project of each vendor was rebuilt through the moved code, publishing stores and reproducing identical Session and Event counts |
| 5 | Done | Snapshot creation, rebuild promotion, catalog resync, Artifact correlation, and content-processing records are in `codess/ingest_publication.py`; the command module retains `_publish_project`, which orders the phases and translates the run's state into their parameters. `create_snapshot` and `os.replace` no longer appear in `cli/`. The extraction is behavior-preserving and does not decide the W03/W20 identity questions: it moves the derivation without changing it, which is why it no longer waits on them |
| 6 | Done | Every report query is in `codess/query_reports.py`: mapping diagnostics, Artifact evidence, tool lineage, permission denials, audit events, tool totals and per-Session counts, Task invocations and results, Session selection, Session Events, and store counts. `query_cmd` retains its column headers and terminal formatting; the only `execute` left in the module is the store-readability probe, which is a connection check rather than a report |

**Why step 5 no longer waited on W20.** The step was held for the decision on
whether `snapshot_id` is a creation or a content identity, on the ground that
extracting first would fix the current derivation in place. That applies to
*changing* the derivation, not to moving the block: `publish_snapshot` calls
`create_snapshot` with the same arguments the inline code did, so whichever
way W20 settles, the edit lands in one function in the domain module rather
than in a 230-line block inside a Project loop. Moving it first makes that
decision cheaper to apply, not harder.

One boundary was clarified while extracting. `snapshot_required` and
`derived_changed` had been separate locals whose difference was implicit:
the first is why a snapshot is due, the second only records that correlation
or content processing wrote a store. The evidence summary is reused across
runs when the first is false, so folding them together would have reused a
summary for a Project whose stores had in fact changed. `PublicationOutcome`
now carries both, with the distinction stated on the field.

**What step 6 turned out to be.** The step was written as "replace
`query_cmd`'s direct report SQL with typed-executor calls", which assumed the
typed executor could answer these reports. It cannot, and should not: it
executes a validated request over the four structured actions -- sessions,
overview, events, search -- while these are fixed analyses with their own
shapes, and forcing mapping diagnostics or an Artifact histogram through a
request contract would either distort the contract or produce a request no
caller could construct.

The layering goal was nonetheless exactly right, so the reports moved to
`codess/query_reports.py` in the same shape as `ingest_publication`: the
domain owns the query and the ordering, and the command owns the column
headers and terminal formatting. Ordering travels with the query rather than
the renderer, because it is part of what a report *is* -- a caller that
sorted differently would produce a different report under the same name.

Two decisions came out of the move. `QueryScope` gained `source_predicate`
and `diagnostics_predicate` as methods, so a report receives the scope
instead of reaching back into the command module for a helper; the second
exists because a mapping diagnostic reaches a source system through either
its Session or its Source, and a record-level diagnostic often has no Session
at all. And `_project_counts` kept its zero-filling in the command layer:
the domain reports the stores it opened, while whether a named root with no
readable store should appear as a zero row is a question about what the user
asked for.

Verification was byte-identity rather than the suite alone. All ten reports
were captured before and after over a three-vendor Project, then compared
again under each source filter and with a row limit -- thirty comparisons,
all identical.

One observation from doing the work: an attempt to introduce a per-Project
state object *before* extracting the vendor blocks was reverted. The
container looked reasonable in isolation but had no consumer yet, so it
would have been scaffolding committed ahead of the change it was meant to
serve. The increments hold only if each one is complete on its own.

**What remains, measured.** A call-tree survey of `ingest_cmd`'s 37
definitions found that every one except `run` has one to five in-module
callers and no external source consumer -- they are `run`'s private
decomposition, correctly placed, and moving any would create an import for a
single caller. `run` itself is 692 lines, 54% of the module's definition
lines, and its Project loop is 353 of those.

So the module is not a collection of misplaced implementations; it is one
very large function with helpers around it. The remaining W06 target is that
353-line loop rather than the file's function count. Length is not padding
either: of `run`'s 692 lines, 36 are exception handling and none are
multi-line messages, so 94% is decisions
(experiments/structural-analysis-tools.md).

The measurement that made this urgent rather than tidy: `ingest_cmd` and
`query_cmd` were the largest and third-largest modules in the codebase, both
in the layer that should hold the least logic. `ingest_cmd` is now about
fourteen hundred lines and `query_cmd` about thirteen hundred and fifty, with
the domain work in `ingest_sources`, `ingest_publication`, and
`query_reports`.

### 4.2 Mapping and Query Contracts

Uniform runtime mapping conformance is tracked by **W04**. Released profiles are
package-checked and sampled by adapter tests, but `validate_mapped_event` is not
a common ingest boundary. Strict mapping currently covers selected Claude Code
failures without equivalent Codex and Cursor semantics. A vendor-neutral
post-decode stage must provide diagnostic and strict modes over partial,
malformed, unsupported, and hazard records.

##### W04 Decomposition

**What the gap is not.** Running `validate_mapped_event` over every
current-format store on the development machine returns **zero failures across
279,735 Events** -- 73,009 Claude, 84,862 Codex, 121,864 Cursor. All four
required scalars (`source_record_type`, `source_record_locator`,
`mapping_rule`, `mapping_trace`) are populated, every `mapping_rule` names a
rule declared in the vendor's released profile, and every `mapping_trace`
parses as a JSON object whose `applied_rules` are declared.

Three stores under one Project are excluded, and what they are is worth
stating exactly, because "legacy" alone invites the wrong reading. They are
**pre-CoSchema Codess stores**, not an older vendor format: two tables
(`sessions`, `events`), no `application_id`, no `user_version`, and no
`store_meta`, so they record neither a format version nor the decoder that
wrote them. Their `events` table has `event_type` and `role` but no
`event_kind`, `actor_kind`, or mapping columns. The anchor for them is
therefore Codess's own `format_version`, now 4, and they predate its
introduction -- a vendor release number would not identify them, since the
shape is ours. They are superseded observations awaiting re-ingest, not
decode failures, and `verify_store_identity` already refuses them on
`application_id` before any mapping check runs.

So W04 is **not** a data-repair item. `annotate_mapping` already produces
conformant evidence for all three adapters. The gap is that **nothing enforces
it**: the property holds today by construction and would break silently. An
adapter can add a rule id absent from its profile, or emit an Event through a
path that never calls `annotate_mapping`, and no check fails.

**Steps.**

| Step | Work | Verified by |
|---|---|---|
| W04.1 | Call `validate_mapped_event` at one vendor-neutral post-decode boundary, between adapter output and `store` insertion, so every Event passes through it regardless of vendor. | A test that routes a deliberately non-conformant Event through each adapter's ingest path and observes the same rejection. |
| W04.2 | Define the shared candidate-record contract as a type, so the shape passing that boundary is declared rather than implied by three adapters agreeing. | Adapters type-check against the declared candidate; mypy covers the decode boundary. |
| W04.3 | Give the boundary diagnostic and strict modes with the same semantics for all three vendors, replacing the Claude-only strict-mapping coverage. | Equivalent partial, malformed, unsupported, and hazard fixtures per vendor produce equivalent dispositions. |
| W04.4 | Record each non-conformance as a `mapping_diagnostics` row rather than only raising, so diagnostic mode is inspectable after the fact. | Diagnostic-mode ingest of hazard fixtures yields rows with the reason codes the profiles declare. |
| W04.5 | Extend `tools/decode_audit.py` with a conformance count per vendor, so the zero above is re-measurable rather than a one-time observation. | The audit reports conformance alongside its existing invariants and exits nonzero on any failure. |

**Relation to coverage reporting**, which states coverage, loss, and unknown shapes. Two of
the five steps feed it directly and are the ordering constraint:

- **W04.4 supplies its input.** A loss report states what was *not* mapped.
  Diagnostic rows are that record; without them the report has to re-derive
  non-conformance by re-decoding, which is a second decode path.
- **W04.3 makes those counts comparable across vendors.** If Claude raises
  where Cursor tolerates, a coverage figure means something different per
  vendor and the cross-vendor comparison it exists to support is unsound.
- **W04.1 and W04.2 do not feed it** and could land independently. W04.5
  overlaps it in presentation and should be folded into it if the report lands
  first.

This is what the ordering means concretely: a report built first would state
against unenforced profiles, so a clean coverage report would attest to
nothing.

Query-contract parity is part of **W13**. Checked-in JSON schemas and the
hand-written runtime validator do not merely risk drifting independently —
verified during a later review pass that every `schema/*-v1.json` and
`schema/*-contract.json` file declaring `"$schema":
"https://json-schema.org/draft/2020-12/schema"` (`query-request-v1.json`,
`query-result-v1.json`, `query-row-v1.json`, `investigation-v1.json`,
`project-set-v1.json`, `candidate-policy-v1.json`,
`resource-policy-contract.json`, `baseline-selection-v1.json`) has zero
references anywhere in `src/` or `tools/`; none is ever loaded or validated
against at runtime. `query_api.py::validate_request` hand-checks the same
contract `query-request-v1.json` already declares in structured form,
independently and without reference to it.

**The problem being solved.** A query request is not only executed, it is
saved, compared, and re-selected later. Two requests that select exactly the
same thing must therefore be the same document, byte for byte. A JSON array
is an ordered sequence, but the request uses arrays to carry *sets* --
`project_ids` names which Projects to search, and asking for A and B is the
same query as asking for B and A. Without a rule, the same selection has
many valid encodings, so equality comparison and any identity derived from
the serialized request become unreliable.

The fix is to admit exactly one encoding per set. In database terms the
array must be a **distinct, ordered set**: duplicates removed, elements in
a defined collation. The collation here is the codepoint ordering of
Python's default string comparison, which corresponds to SQLite `BINARY` --
not a locale- or case-sensitive collation, so ordering does not vary by
environment. Requests are normalized to this form on construction
(`sorted(set(...))`) and rejected if supplied otherwise, so a
non-canonical request is a caller error rather than something silently
rewritten.

Beyond ordinary structural checks, `validate_request` enforces three rule
classes. They recur below and tag the test vectors, so they are named once
here:

| Rule class | What it constrains | Example |
|---|---|---|
| Structural | One field at a time: presence, type, enumerated value, element uniqueness | `action` must be a supported action name |
| Canonical form | An array must be a distinct, ordered set under `BINARY` collation | `project_ids` must be deduplicated and ordered |
| Related fields | A constraint relating two fields whose values are individually valid | `filters.since` must be at or before `filters.until` |
| Action-dependent | Which filters an action admits, determined by the tables that action's SQL actually joins | A `sessions` query never reads the `events` table, so `event_kinds` cannot apply to it |

The vector fixture tags these `canonical_form`, `related_fields`, and
`action_dependent`. The names describe *what a rule must look at* to be
decided, which is what separates the classes and what determines whether a
declarative schema can express them.

Structural rules look at one field. **Related-field** rules look at two
fields that are individually valid but constrained with respect to each
other; `since` and `until` are each a valid timestamp, and only their
relationship can be wrong. The name says the fields are related, which is
the fact a reader needs -- the previous "cross-field" phrasing described
the check crossing a boundary rather than the fields being connected.
**Action-dependent** rules look at one field's value to decide whether
another field is admissible at all, and additionally depend on knowledge
outside the document: which tables that action's SQL joins. That external
dependency is why it is a different kind of rule, not merely a harder one.

Ordering the three by what they must look at -- one field, two related
fields, another field's value plus external knowledge -- is also the order
of increasing difficulty for any declarative schema, which is why the
distinction is worth naming.

"Unique and canonically sorted" is the wording the runtime error messages
already use, and it is accurate and readable; prefer it in user-facing
documentation over the internal tag names, which exist to classify test
vectors rather than to explain the requirement.

**The two-field comparison could be represented differently.**
`since <= until` is the only related-field rule, and it exists because the
time window is expressed as two independent fields that happen to be
related. Representing the window as one value would eliminate the rule
class rather than validate it:

| Representation | Effect on validation | Cost |
|---|---|---|
| Two fields, compared (current) | Needs a hand-written related-field check; each field is individually valid, so no per-field keyword catches the inversion | None beyond the check itself |
| One `interval` array `[since, until]` | Ordering becomes the array's own canonical-form rule, folding this into a class already enforced | Changes the request wire format; a two-element array is a weaker self-description than two named fields |
| One object with a required ordering invariant | Same comparison, only relocated | No gain; the check moves without disappearing |
| Start plus duration | Inversion becomes unrepresentable, since a duration is validated as non-negative by a per-field bound | Changes user-facing semantics; callers naturally express windows as two instants, and a negative duration is merely a different spelling of the same error |

None is clearly better than the present form. The comparison is one line,
the failure mode is a clear message, and the alternatives trade a
hand-written check for a wire-format change and a less obvious request
document. The rule class is worth *naming* because it constrains validator
choice, not because the representation is wrong. Retain two fields; revisit
only if the request format changes for other reasons.

The `jsonschema` package (a mature, actively released, widely adopted
implementation of the spec) is already an installed dependency but is
likewise never imported. Tested directly against `query-request-v1.json`
and representative request shapes: it correctly validates the structural
half of the contract (types, enums, required fields, `uniqueItems`), but
canonical ordering has no JSON Schema equivalent under any draft (checked
every published draft the library implements, draft3 through 2020-12; none
has a "sorted" keyword -- `uniqueItems` gives distinctness but not order)
and would remain hand-written under any jsonschema adoption. The
related-field `since <= until` comparison is expressible through `if`/`then`
combinators, confirmed working, but reads less directly than the current
one-line check.

Action-dependent filter validity (`ACTION_FILTERS[request["action"]]`) is a
different kind of rule than the other two, not merely a harder one:
`ACTION_FILTERS` encodes which query dimensions each action's SQL
generation can actually join against (`sessions` queries never touch the
`events` table, so `event_kinds`/`tool_names` are not merely disallowed by
convention, they are inexpressible for that action) — this is a fact about
`query_api.py`'s own query-construction code, not a constraint on the
request document's grammar. It is technically expressible via JSON Schema
`if`/`then` (confirmed working against a proof-of-concept) but doing so
would duplicate business logic about query capabilities into a document
meant to describe syntax; it does not belong in a schema regardless of
which validation library is chosen.

Pydantic (also installed and unused) was tested as a materially different
candidate rather than a variant of the same choice: it expresses all three
rule classes as ordinary methods (`@field_validator`, `@model_validator`)
alongside the structural checks, so no rule has to live outside the model.
Its cost is that the standard path from an existing JSON Schema file, the
separately published `datamodel-code-generator`, is a one-time generation
step rather than a live bridge -- the generated class becomes authoritative
and the source `.json` is no longer necessarily kept in sync.

**Decision: the schema files are retained as-is and the migration is
Postponed.** Replacing `validate_request` with jsonschema alone is not
available, since canonical ordering cannot move to a declarative schema and
action-dependent validity should not. Pydantic has neither limitation but
would let the JSON files drift from a generated class. Neither trade is
worth making while the runtime validator is correct and covered by vectors.
The architecture and coverage portions of W13 remain open.

`tests/fixtures/validate_request_vectors.json` and
`tests/test_validate_request_vectors.py` supply the correctness baseline any
future migration would need. Vectors exercising the three named rule classes
carry a `capability` tag; untagged vectors cover the structural rules. The
fixture is tool-agnostic by construction -- request and outcome pairs with
no reference to `validate_request`'s internals -- so a migration would be
complete when every vector still passes against the replacement. The
vectors were written to cover each rejection path, but nothing asserts they
still do, so that completeness claim decays silently as paths are added.

The eight files are the published, language-independent statement of the
request, result, row, investigation, Project-set, candidate-policy,
resource-policy, and baseline-selection document shapes. This paragraph is
the single place recording that they are not consulted at runtime; the
files themselves are not annotated, since a status that may change does not
belong duplicated across eight documents where it would have to be revised
in eight places and could disagree with this section. Their value is as a
portable contract for the interfaces in 9.7, for documenting document
shapes from one source, for validating investigation, Project-set, and
baseline-selection documents produced outside Codess, and as the starting
point if the trade-offs above change.

### 4.3 Bounded Processing

Ancillary large-file handling is tracked by **W07**. Persisted Claude tool output
uses `read_bytes`, while snapshot worktree identity captures complete binary
diffs and untracked files in memory. Both paths can encounter exactly the large
logs or binary objects that resource policy is intended to contain. They must
stat and classify first, then stream through bounded hashing or decoding and
record an explicit rejection or limitation before excessive allocation.

### 4.4 Identity and Evidence Semantics

Uncatalogued Project identity is tracked by **W14**. Store code can generate a
new Project UUID when no catalog binding is supplied. Normal CLI operation
supplies the binding, but direct library writes can assign different Project
identities to separate vendor stores for one repository. Current-format writes
should require Project identity, or mark the generated identity explicitly
provisional and reconcile it before publication.

Raw mode `none` was tracked by **W15**, now closed. The mode retained no bytes
but wrote a `not_retained` source-revision observation, so the name promised
something the implementation did not do. **The observation was kept and the mode
renamed to `observe`**, because that record is what makes a Source's absence
checkable: `availability=not_retained` states that Codess read the Source and
deliberately kept nothing, which a manifest that never mentions the Source
cannot state, and only the first can be audited later.

The rename resolved at one boundary rather than at each comparison.
`config.canonical_raw_mode` maps the previous spelling to the stored name and
doubles as an argparse `type`, which runs before `choices` -- so `--help` lists
one name per mode while `--raw-mode none` in an operator script still parses.
`RAW_MODE_ALIASES` is deliberately outside `RAW_MODE_CHOICES`, since argparse
would otherwise offer both spellings as equals.

**Writing it found a defect the rename would have introduced.**
`refresh_operations._automatic_raw_mode` reads the mode a snapshot was built
under out of its retained manifest and falls back to `reference` on any value it
does not recognize. Without canonicalization a Project built under `none` would
have silently started recording resolvable references on its next refresh --
the failure mode being that a Project which deliberately retained nothing begins
retaining something, with no error. Two further readers compare across
spellings and now canonicalize both sides: the validation policy check
(`policy.raw_mode`) and the annotation that classifies limited retention.

Package identity separation was tracked by **W03**, now closed; the decision
and what implementing it revealed are recorded at the end of this section.

**What the digest covers.** `schema_contract.verify_package()` walks the
released manifest, verifies each listed file against its recorded SHA-256,
and folds every one of those per-file hashes into a single digest over the
whole set. That one value is the *package digest*. Its members fall into
two groups that serve unrelated purposes:

| Group | Members | Runtime role |
|---|---|---|
| Executable contract | The SQLite DDL, the logical contract, the mapping contract, and the three vendor mapping profiles | Loaded by `src/` at runtime; determines the layout a store is written into and the mapping evidence attached to decoded records |
| Validation fixtures | Representative minimal, maximal, golden, edge, negative, hazard, and version-compatibility documents | Read only by the test suite; never loaded by `src/` |

The split is the reason W03 exists. The first group defines what a store
*is*; the second only defines what the tests exercise. The digest does not
distinguish them.

**Why that blocks writes.** Every store records the package digest current
when it was written into its `store_meta`. `require_store(write=True)`
refuses to open a store whose recorded digest differs from the digest
computed now. The intent is sound — a store must not be extended by
software whose schema or mapping has moved underneath it — but because
fixtures are inside the digest, editing a fixture, or any packaged file
not loaded at runtime, changes the digest and makes every already-published
store fail that check. The store's layout, decoder, and data are unchanged;
only a test document moved. Rebuilding from source is then the only way
back, which is disproportionate to a change that provably cannot affect
stored data.

**W03 was reproduced against real data, not only reasoned about.** Removing
the `codess:legacy:uuid:` column defaults changed `schema.sql`, which changed
the package digest, which made every already-published store on this machine
unwritable:

```text
UnsupportedStoreError: store package differs from the current released
package; rebuild the derived working store from source
```

The DDL edit was semantic, so refusing the write was defensible here. What
the incident demonstrates is the mechanism: any packaged-file change produces
this outcome, including edits to fixtures that no runtime code reads. The
same one-line failure would have followed a comment change in a test
document. That is the coupling W03 exists to break.

It also shows the practical cost. Validation had to run in preflight mode
against every real Project rather than ingesting, because ingesting would
have required rebuilding stores unrelated to the change under test.

**Fixture identity is a development-lifecycle concern, not a runtime one.**
Fixtures establish that the decoders behave correctly; that is settled by
running the test suite before a release, not by a check inside the shipped
program. Their digest answers "is this working tree the reviewed one," a
question the test suite already answers more directly and more completely.
Carrying that question into a runtime admission check gives the program an
opinion about its own test data, which it has no use for. Removing fixtures
from the write gate is therefore not a weakening -- the guarantee moves to
where it was already being established.

**One digest must be justified, not assumed.** A shared digest is a claim
that its members change together and mean one thing. That holds within the
executable contract: the DDL, the logical and mapping contracts, and the
vendor profiles jointly determine how a store is written and read, and a
store built under one combination cannot be assumed compatible with
another. It does not hold between that group and the fixtures, which have
an unrelated lifecycle. Grouping by shared lifecycle is the rule; a single
digest spanning groups needs proof that coordinated state across all
members is actually required, and no such proof exists here.

**Checking cost must be proportionate in a development environment.** The
existing integrity machinery is not free: `verify_package()` hashes every
manifest file, and it is reached from the store write gate, snapshot
creation, refresh, baseline catalog operations, and query metadata. Codess
runs locally against a developer's own data, so the threat this guards
against is accidental mismatch, not tampering. That justifies a cheap
check, not a pervasive one. Verification that exists to protect a release
should run at release time; runtime should retain only what prevents a
specific, demonstrated failure. Where a runtime check survives on those
grounds, it should be skippable, so ordinary local work is not paying for
a guarantee it does not need.

**Mismatch means regenerate, which bounds the whole problem.** Codess does
not migrate stores in place; the established approach is to detect that a
store disagrees with current processing and rebuild it from vendor sources,
which remain the authority. That makes the write gate's job narrow. It does
not need to identify precisely which release produced a store or to support
compatibility across versions. It needs to answer one question -- *would
extending this store mix records written under different rules?* -- and on
disagreement, direct the operator to regenerate. Schema evolution is handled
by regeneration rather than by digest precision, so precision beyond that
question buys nothing.

**What separation requires.** The write gate should consult only the
executable contract, and the resulting check should be explicit about
prescribing regeneration. Exact package verification remains available as a
release and diagnostic operation, where its cost is appropriate and its
question is the right one. Each identity needs a named consumer and a test
fixing which question it answers, so adding a file to the manifest cannot
silently reintroduce the coupling.

**Decision and outcome.** Accepted and implemented: `contract_digest()` covers
the six runtime files, is what a store records, and is what the write gate
compares; `verify_package()` retains the whole released set and is reached
from `codess package verify`, which reports both values and names the files
outside the gate. Six is not merely sufficient but exact -- the DDL fixes the
physical layout, `contract.json` the logical one, and the mapping contract
and three profiles the decode; nothing else in the manifest is loaded by
`src/` at all.

Two things measured during implementation changed the argument that was
recorded above, and both are worth keeping:

*The cost argument was wrong and is withdrawn.* `verify_package()` is
`@lru_cache(maxsize=1)`: 3.18 ms cold, 0.0006 ms warm, once per process
rather than per store. The six subsystems that reach it share one cached
result, so cost was never a reason to act here.

*The skip is implemented, and cost was the wrong reason to weigh it.* This
section's requirement that a retained runtime check "should be skippable"
was first read as resting on cost, and dropped when cost measured
negligible. That inverted the argument. Cost is a reason to make a check
cheap; **recovery** is the reason to make it escapable, and it does not
depend on how fast the check runs. A store whose recorded contract
disagrees, whose vendor sources are gone and whose released files are not
reconstructible, is unreadable under a mandatory gate -- the check would
then be protecting nothing and withholding retained evidence. Tests need
the same escape for the opposite reason: to exercise a deliberately
mismatched store without regenerating the released set.

`--no-check` (`CODESS_NO_CONTRACT_CHECK`) covers both the write gate and
digest verification, following the existing `--no-hash` precedent, including
its environment-read (the flag is parsed after config's constants resolve).
The override is not the default and warns: each bypass logs the store and
the failures it passed over, and a store created under it records
`contract_override` in `store_meta`, so a later reader does not have to
infer it from a failing check. Operator-facing behavior for both overrides is
in [Integrity Check Overrides](Operations.md#107-integrity-check-overrides);
this section records why the escape exists.

*A second, sharper failure mode was found by reproducing the first.* The
recorded defect is that a fixture edit makes published stores unwritable.
Editing a fixture *without* updating the manifest is worse: `verify_package`
raises inside `load_ddl`, `load_contract`, and `load_mapping`, so a
half-finished edit to a test document disabled store creation and every
other path that reads the released contract -- not only the write gate. Both
modes were reproduced before the change and confirmed fixed after, with a
control proving a real DDL or mapping-profile change still refuses the write.

**What the manifest's other ten entries turned out to be.** The framing above
treats the fixtures as test data whose lifecycle the test suite settles. That
is true of two of them. The other eight -- both `compatibility/store-meta-v*`,
`maximal/event`, `minimal/session`, `negative/event-sequence-zero`,
`hazard/cursor-tool-former`, and the rest -- are referenced by nothing but
the manifest itself. The two that tests do read are read by direct path, not
through the manifest. So most of the digest's members were inert: they could
not fail a test, because no test read them, yet they gated every store write.
Whether they should be wired into tests or removed from the released set is
a fixture-inventory question rather than an integrity one, and is tracked
separately as **W35** (Postponed).

### 4.5 Test Observability

Subprocess coverage is tracked by **W13**. CLI integration tests execute scan and
ingest in child processes, so ordinary branch coverage cannot attribute those
paths and cannot locate their untested branches reliably. Subprocess coverage
or directly tested domain coordinators should supply that evidence while the
installed-interface subprocess tests remain in place.

### 4.6 Operational Reporting

The current implementation has four distinct reporting paths. Command modules
write requested results and many status or error messages directly with
`print()`. Project, scan, helper, Cursor-source, adapter, and command modules
use standard library loggers, but `parse_and_run()` configures them only through
`logging.basicConfig()` when verbose mode is selected. `ProgressTrace`
independently emits timed ingest events to stderr and retains a bounded deque.
Domain functions also return or mutate report and diagnostic dictionaries that
command code later renders.

`ProgressTrace` is the most complete current contract. It records UTC and
monotonic time, uses stable dotted event names, declares transcript content
out of scope for its call sites, caps retained events, reports drops, and can
select the events attached to each Project report. Ingest, raw capture, Cursor
cohort work, and selected adapters emit useful stage, count, size, reuse, and
completion events through it. Focused tests cover rendering, disabled output,
retention, drop reporting, and representative ingest progress sequences.

Its limits are also concrete. Arbitrary field names and values have no runtime
contract or privacy enforcement. Human rendering is built into the collector,
and only ingest uses it systematically. Scan and query rely primarily on direct
stderr text. Standard logger records and progress records have different
formats and configuration. There is no operation correlation identity, stable
application error code, JSON operational stream, or common boundary that maps
typed failures to messages and exit status.

Error handling is correspondingly distributed. The administrative dispatcher
catches a selected group of exceptions, scan logs some unexpected root
failures, and ingest and query contain many local catches and stderr messages.
`console_main()` handles `BrokenPipeError` but is not a general application
error boundary. Tests establish several valuable surface rules—invalid input
must not expose a traceback, progress stays on stderr, machine outputs remain
parseable, and broken downstream pipes remain quiet—but those rules are not
owned by one implementation component.

This finding does not apply to CoSchema mapping diagnostics. Those diagnostics
are evidence about decoded Source records and must remain queryable beside the
data. W18 consolidates only application operation reporting under the contract
in Section 9.6.1.

### 4.7 Session Discovery Decomposition

`walk_sessions()` is tracked by **W19**. It is the entry point for Project
discovery: given a work root, it returns one row per discovered Project with
its contributing vendors, Session counts, size, and activity span.

**Measured.** `walk_sessions` has cyclomatic complexity **99**, and its
module carries 194 total across only 10 functions -- so 79% of the module's
complexity sits in its three worst functions, the highest concentration in
the codebase. The maintainability index rates the module `C` at 596 lines,
while `ingest_cmd` rates `B` at 1,431: the index is not tracking size, it is
tracking few functions carrying much branching, which is exactly this item's
subject (`experiments/structural-analysis-tools.md`).

**The problem.** Three responsibilities are interleaved in one body rather
than sequenced. Vendor path discovery reads Claude Code, Codex, and Cursor
storage, each with its own index format and fallback traversal. Path
canonicalization then reduces the discovered paths to Project locations:
attributing a nested path to its enclosing Git root, dropping a parent when
a more specific child is present, and excluding aggregator directories.
Row assembly finally gathers per-Project metrics. The middle stage is pure
path algebra with no I/O beyond existence checks, but it is reachable only
by running the first stage, so its rules cannot be tested without a
populated vendor filesystem. That is the practical cost: the logic most
likely to be wrong -- which directory *is* the Project -- is the logic
hardest to test.

**Why the nesting is not load-bearing.** Four helpers are defined inside
the function. Nesting is justified when a helper closes over derived local
state, but none does. `in_work_root`, `_is_agg`, and `canonicalize` capture
only `work_root`, itself a parameter; `project_boundary` captures
`work_root` and one derived set of existing paths. No helper captures
accumulating or loop-local state. Each becomes a module-level function by
adding one or two explicit parameters, which is why the extraction is
mechanical rather than a redesign.

**Candidate designs.** Three options, in increasing scope:

| Design | Change | Gains | Costs |
|---|---|---|---|
| A. Lift helpers only | Move the four helpers to module level with explicit parameters; leave the body otherwise intact | Canonicalization rules become directly testable; smallest possible diff; behavior-preserving by inspection | The function remains long; discovery and assembly stay interleaved |
| B. Lift helpers and separate the three stages | A. plus splitting the body into vendor discovery, canonicalization, and row assembly, passing path sets between them | Each stage independently testable; the pipeline becomes readable as three named steps | Larger diff; requires deciding the intermediate representation passed between stages |
| C. Per-vendor discovery modules | B. plus one discovery function per vendor behind a common signature | Vendor-specific traversal isolated, matching the adapter-layer separation elsewhere | Largest scope; the Cursor boundary it depended on is now closed, so it is unblocked |

Design A is the recommended first step: it removes the testability blocker
at near-zero risk and is a strict prefix of B. B should follow once A's
extracted functions have tests, since the intermediate representation is
easier to choose when the canonicalization contract is pinned by tests.
C is unblocked now that the Cursor source boundary is closed, but should still follow B.

**Validation.** The extraction is behavior-preserving, so the existing
discovery tests must pass unchanged -- that is the primary evidence, and a
change to their expectations indicates a defect in the extraction rather
than a needed update. Beyond that, A is complete when canonicalization has
direct unit tests that construct path sets in a temporary tree and assert
Git-root attribution, parent-versus-child selection, and aggregator
exclusion without invoking vendor discovery. These cases are currently
unreachable, so they are new coverage rather than relocated coverage.

**Excluded from W19: the inline `debug` prints.** These are tracked
separately as **W21** and must not be folded into the extraction.

The two changes differ in kind. Extraction is behavior-preserving: it moves
code without altering what the program does, so its correctness is
established by the existing tests passing unchanged. Rerouting the `debug`
statements is a behavior change. They currently write to stderr immediately
via `print(..., file=sys.stderr)` and only when `debug` is set, whereas
`_record_diagnostic` and its siblings accumulate structured entries into the
`diagnostics` dictionary the caller supplies. Converting them changes where
the information goes, when it appears, whether it survives the call, and
whether it is emitted at all when `diagnostics` is `None`. No existing test
asserts that difference, so a defect introduced here would be silent.

Combining them destroys the extraction's safety argument. If the tests are
expected to pass unchanged and one fails, that failure must mean the
extraction was wrong; once a behavior change rides along, a failure is
ambiguous and the reviewer must decide which change caused it. Keeping them
separate preserves a clean signal in both directions.

W21 belongs with W18, not with W19. `walk_sessions` is one instance of the
reporting fragmentation described in 4.6 -- direct `print` calls
carrying operational status that no shared contract governs -- so the
destination for these statements is whatever W18's event contract defines,
not the module-local diagnostics dictionary. Converting them to
`_record_diagnostic` first would move them into a structure W18 may then
replace. W21 therefore waits on W18's contract and applies it here, using
the extraction as the occasion rather than the justification. Extraction
makes the call sites obvious, which is why the two look related; that is an
argument for sequencing, not for merging.

### 4.8 Derived Key Requirements

Independently derived SHA-256 keys were tracked by **W20**, now closed. The
requirements below are the settled record; each site's outcome is noted with it.

**The identity system, in layers.** Codess derives identifiers in three
distinct groups, and only the third is under review. Confusing them is the
main hazard, since they share a hash function and nothing else.

*Entity identities* (`identity.py`) name logical CoSchema entities across
stores and machines. All use one `_qualified()` construction -- a format tag, an
entity kind, and NUL-separated components -- and all retain the full 32-byte
digest, rendered as `codess:<kind>:<format tag>:<64 hex>`. The tag is
`identity.IDENTITY_FORMAT_TAG`, currently `id1`; it is read from the constant
rather than written out here, because a format tag spelled into prose is a value
that goes stale the next time it changes, and this table previously documented a
`sha256:` prefix and a `global_*` naming scheme two formats after both were
replaced.

They derive from vendor-supplied identifiers rather than local state, which is
what makes them portable:

| Identity | Derived from | Purpose |
|---|---|---|
| `session_entity_id` | Source system ID, vendor session ID | Names one vendor Session independently of any database or path |
| `event_entity_id` | Session identity, vendor event ID | Names one Event within a globally qualified Session |
| `source_revision_entity_id` | Source system, path, revision | Names one immutable observation of an upstream Source |
| `source_record_entity_id` | Source revision identity, locator | Names one record position within that revision |
| `source_observation_id` | Entity identity, source system, path, revision, Project | Names one extraction observation of a logical entity |
| `location_id` | Machine ID, normalized real path | Names a machine-local observed location, explicitly never a Project |
| `artifact_uri_id` | Artifact URI | Names an Artifact locator consistently across Project databases |
| `content_object_id` | Content digest | Names one stored content body by what it contains |
| `workspace_binding_id` | Project identity, source system, workspace ID | Names one vendor workspace bound to a Project |
| `processing_run_id` | Run inputs | Names one processing run for provenance |

These compose deliberately: `event_entity_id` takes a session identity that is
itself qualified, so an Event's name is only meaningful relative to a Session's.
That is layering, not the violation described below -- the Session identity is an
*input* to the Event identity, not a field inside the structure the Event
identity digests.

**A derived value is never the identity of what it was derived from.** This is
the rule the layering above respects and that a later defect broke: `location_id`
is derived from `(machine_id, path)`, and the catalog keyed its locations by that
derived value rather than by the path. When the derivation changed, one directory
acquired two catalog entries and every affected Project became unrebuildable
(4.11). The composition is safe because the *input* is stable; keying on the
*output* is not.

*Vendor identifiers* are the raw values a harness recorded, retained
unchanged as evidence. `tool_use_id` is Claude Code's field naming a tool
invocation; `call_id` is Codex's equivalent. Adapters read whichever the
vendor supplies and place it in Event metadata. These are not Codess
constructs and are never invented.

`source_call_id` is the CoSchema column that stores that vendor value after
bounding (item 5 below). The distinction matters: `call_id`/`tool_use_id`
are *vendor field names* appearing in source records and metadata, while
`source_call_id` is the *common column* holding whichever one applied, so a
cross-vendor query does not need to know which harness produced the row.
The `source_` prefix marks it as a retained vendor value rather than a
Codess-derived identity -- it is not qualified, not hashed except when
over-long, and not comparable across Sessions, which is why the schema
constrains it as `UNIQUE(session_id, source_call_id)` rather than globally.

**Proposed naming rule: name the use, not the algorithm.** Not approved; it
is recorded here as the shape a decision could take, and W34 is blocked on
making one. A name should say what a value is *for*, since that is what a
reader must know to use it correctly and what stays true if the
implementation changes. Three suffixes carry distinct meanings:

| Suffix | Meaning | Consequence if the algorithm changes |
|---|---|---|
| `_id` | Names an entity; expected to be stable and to appear in references | The value changes, so this is a breaking change requiring migration |
| `_key` | A derived lookup or grouping value; equality is all that is promised | Values change together; anything holding old ones must be regenerated |
| `_hash` or `_digest` | An integrity claim to be recomputed and compared | The verifier must know the algorithm, so naming it is correct here |

Under this proposal only the third case mentions the algorithm, because a
verifier must know what to recompute. The competing position is that no name
outside `hashing` should carry an algorithm at all, with verification callers
passing the width they expect and the module choosing how to satisfy it --
which removes the exception entirely at the cost of a less self-describing
field name. Neither has been chosen.

By this rule `candidate:path-sha256:` was wrong, and the earlier
`candidate:path:` was wrong differently -- one advertised the algorithm, the
other implied a path followed. It is now `candidate:path-key:`, which states
the input domain and the class of value.

**Related finding: the algorithm name is pervasive.** `hashlib.sha256` is
called directly wherever a digest was needed, and `sha256` appears in many
field names (`selection_sha256`, `catalog_sha256`,
`manifest_sha256`, `plan_sha256`, and others) plus a dozen stored value
prefixes (`codess:workspace:sha256:`, `codess:processing:sha256:`,
`rawrel:sha256:`, `full-sha256-fingerprint`, and more). Two groups need
separating:

- *Integrity fields* -- `stored_sha256`, `content_sha256`, `manifest_sha256`
  and their kin are verification claims that a reader recomputes. Naming the
  algorithm is correct and should stay.
- *Identity and key prefixes* embedded the algorithm in values that are stored,
  compared, and quoted by operators. These were the ones that made an algorithm
  change a wire-format change.

**Resolved.** The identity prefix carries a format tag rather than an algorithm
name, so `hashing` owns which algorithm is in use and no stored value pins it.
Writing the tests for that change found two more wire-tied sites an inventory
taken by reading had missed -- a `~sha256:` marker inside `source_call_id` and
`sha256-fingerprint:` prefixes on 370 stored `source_revision` values -- which is
the general lesson: an inventory finds the sites a reader thinks to look at, and
the sites that reach a stored value are found by asking what a test would have to
assert.

Integrity fields keep their algorithm names, and that asymmetry is the point: a
verification claim states what a reader must recompute, while an identity states
only that two values match.

**Why the algorithm was called so widely.** The direct calls were not one
duplicated operation; they were three operations that had never been named:

| Group | Calls | What it does | Mode that serves it |
|---|---|---|---|
| Streaming digests | 12 incremental constructions in `fileio`, `snapshot`, `raw_store`, `schema_contract`, `cursor_source`, `baseline_validation` | Feed a file or object in bounded chunks, so an arbitrarily large input never materializes in memory | `codess_stream_hash`, or `codess_digest()` where the read pattern is itself the policy |
| Canonical-document digests | `query_api`, `project_catalog`, `catalog_operations`, `retention`, `refresh_operations` | Serialize a structure to canonical JSON, then digest the bytes | `codess_canonical_hash`, which also fixes the serialization form |
| Key and identity derivation | `identity`, `path_label`, `tool_identity`, `store`, `cli.ingest_cmd`, `content_processing` | Combine a few short values into a stable name or key | `codess_hash` |

Every group is now served, but not by one function: the modes exist because
these operations differ in what they consume and in whether their output
must match an external tool's.

The justification for so many direct calls was therefore partial. Streaming
sites are legitimately distinct in their *read policy*, which stays in
`fileio`; their digest construction was not. The key-derivation sites had no
shared function to call, which is the accidental duplication the shared
module removes. The canonical-document sites revealed a further missing
abstraction -- a canonical-JSON encoder.

**Reading a file that is being appended to.** This is the ordinary case for
session transcripts, not an edge case, and the original handling was wrong in
a way a stat comparison could not fix.

The defect was reading to end-of-file. When a coding assistant is appending,
the end moves, so a read that stops "at EOF" covers a state that never
existed as a whole -- it includes some of the new bytes but not all of them,
and the resulting digest describes nothing. Comparing stat before and after
detected that this had happened but could not make the digest meaningful,
and the check itself was unreliable: a rewrite restoring the original size
and modification time is invisible to it.

The fix is to stop depending on detection. `fileio.read_exactly` reads a
count decided *before* the read begins -- the size the first stat reported --
so the digest always covers a well-defined prefix:

```text
  stat        size 10 MB
  read        exactly 10 MB  ── assistant appends 2 MB during this read
  stat        size 12 MB
  result      digest of the first 10 MB, which is exactly what was there
              consistency = "appended", file_changed = True
```

The prefix is correct whether or not the file grew, so growth is no longer a
correctness problem and does not need to be detected to stay safe. The second
stat is retained only to describe what happened, which is why the outcome is
advisory:

| Observation | Consistency | Outcome |
|---|---|---|
| Size and mtime unchanged | `stable` | Content digest is the revision |
| File grew | `appended` | Digest of the announced prefix is still the revision; the flag records that the source was active |
| Size shrank or mtime moved without growth | `rewritten` | Same digest, weaker claim: the prefix may no longer be a prefix of the current file |

A later scan of a closed session produces a `stable` revision, so evidence
improves without intervention.

**A record caught mid-write is skipped, not treated as corruption.** The
bounded read above protects the *file* digest; the record reader needs the
same treatment. `bounded_jsonl.iter_bounded_jsonl` previously reported a
final line with no terminating newline as `malformed`, which is the same
diagnostic a genuinely corrupt record gets -- so an ordinary open session
looked like damaged data.

It now reports `incomplete` and stops, because nothing can follow an
unterminated line. The distinction matters in both directions: `malformed`
says the vendor wrote something Codess cannot read and is worth
investigating, while `incomplete` says the vendor has not finished writing
and the next read will get the record. Neither raises; the record is skipped
and a warning names the file and line, so a skipped record is visible rather
than silently absent. Existing callers already skip on any diagnostic
reason, so the new value flows through their counts without change.

| Line state | Reason | Meaning |
|---|---|---|
| Parses as an object | none | Ingested |
| Terminated, unparseable | `malformed` | Vendor data problem; investigate |
| Terminated, not an object | `non_object` | Unexpected shape |
| Exceeds the record bound | `oversize` | Rejected by resource policy |
| Not terminated | `incomplete` | Writer still active; retry later |

Capture is the exception and keeps a rejection. A raw object claims to be the
exact bytes of one source state, so a copy taken while the source moved
cannot make that claim and `_compress_file` raises. Its stronger guarantee is
not the stat comparison but the size check that follows -- the bytes written
must equal the size announced -- so the stat comparison there is a cheap
first rejection rather than the guarantee.

`stat_is_stable` is therefore gone. It named a verdict the code should not
have been relying on, and extracting it had made a weak check look
authoritative by giving it a name and a home. The comparison survives inline
at the one site that still wants it, with a comment stating what it does and
does not detect. Window sampling remains in `fileio` as fingerprint policy;
it was never the reusable part.

**Text encoding is the same audit one level down.** Six `encode` variants
are in use: bare `.encode()`, `"utf-8"`, `"ascii"`, and three error
handlers (`surrogatepass`, `surrogateescape`, `replace`). Reviewing which
applies under what circumstance separates deliberate choices from accidents:

| Variant | Circumstance | Assessment |
|---|---|---|
| `"utf-8"` | Default for text that becomes bytes | Correct, and now mostly inside `hashing` rather than at call sites |
| `"ascii"` | Format tags, entity kinds, and offset markers that are ASCII by construction | Deliberate: it asserts the value cannot contain non-ASCII, so a violation raises rather than passing silently |
| `"utf-8", surrogatepass` | Any value that may carry a filesystem path | Correct; see the surrogate hazard below |
| `"utf-8", surrogateescape` | `snapshot`'s untracked-path digest | Correct and self-consistent: it decodes and re-encodes with the same handler, so the bytes round-trip exactly |
| `"utf-8", replace` | Truncated raw-line excerpts in adapter diagnostics | Correct: this is human-readable evidence, not an identity, so lossy substitution is preferable to failing a decode |
| bare `.encode()` | Two preflight key sites, and formerly one digest input | The default happens to be UTF-8, so these work by coincidence rather than statement |

Only the bare form is a defect, and it was worst where a digest depended on
it: `catalog_operations` hand-rolled canonical JSON and encoded it with no
argument, so its digest silently depended on two defaults at once. It now
uses `codess_canonical_hash`. The two remaining bare calls are the preflight
key sites under review.

**Reduced to two real variants.** The three error handlers are not
independent choices; each is determined by what the caller is producing, so
they collapse into the encoding decision rather than multiplying it:

- `surrogatepass` wherever a value may carry a filesystem path and the
  result is an identity -- undecodable bytes must still hash, not raise.
- `surrogateescape` only where bytes are decoded and re-encoded as a pair,
  so the round trip is exact.
- `replace` only for human-readable excerpts, where a lossy substitution is
  better than failing.

That leaves the genuine choice as UTF-8 versus ASCII, and the right default
is UTF-8 with ASCII as a deliberate, local override. ASCII is not a stricter
UTF-8 for the same purpose: it asserts *this value is ASCII by
construction*, so a violation raises instead of passing silently. That
assertion is worth keeping exactly where it holds by construction -- format
tags, entity kinds, and the offset markers in bounded sampling -- and is
wrong everywhere else, because vendor content is not ASCII.

The practical form is that call sites should not pass an encoding at all.
`hashing` already applies UTF-8 with `surrogatepass` internally, so the
majority of sites simply pass text. What remains is the small ASCII set,
where naming the encoding at the call site is the point rather than an
oversight. Collapsing those into UTF-8 would discard a real check, which is
the distinction 3.5.3 draws for constants: syntactic similarity is not
shared meaning.

One case was poor decomposition rather than a missing helper. `raw_store`
carried three near-identical decompress-and-digest loops, differing only in
whether each chunk was also written to an output file. That duplication was
invisible while each loop was read on its own, and became obvious only once
digest construction was the thing being surveyed -- the practical argument
for auditing calls the way 3.5 audits constants.

Reviewing the call sites rather than the loops shows the redundancy was one
level higher than it appeared. `raw_store` exposes three operations over a
stored object -- capture it, verify it, restore it -- and each is really the
same read with a different disposition of the bytes:

| Operation | Consumers | Bytes go to | Compares against a record |
|---|---|---|---|
| `_compress_file` | `raw_store` capture | A new stored object | No, it produces the record |
| `verify_captured_object` | `baseline_validation`, `source_verification` | Discarded | Yes |
| `materialize_captured_object` | `cursor_cohort` | A restored file | Yes |

Two of the three differ only in the destination, which is why one helper
with an optional output absorbs both. Capture differs more substantially --
it reads an uncompressed source and writes a compressed object, the inverse
direction -- so it stays separate rather than being forced into the same
shape. The consumers confirm the split is real: verification is called from
validation paths that never want the bytes, restoration only from the Cursor
cohort cache that does.

The helper is named `_read_source_identity` rather than for decompression.
Decompression is the storage encoding, not the purpose; what every caller
actually wants is the identity of the original source bytes, recovered from
a stored copy. Naming it for the mechanism would have described how it
happens to work today rather than what it is for, and would have to change
if the storage encoding ever did.

**The surrounding names need the same treatment.** `_captured_object` is
weak in both halves. `object` is near-contentless -- it says only that
something is stored -- and `captured` names a *mode* (`capture` is one of
four raw modes) rather than what the thing is, so the name only parses for
a reader who already knows the mode vocabulary. What these functions operate
on is a stored copy of exact vendor bytes: a *raw object* in the
`codess.raw/1` sense, which the module's own format tag already names.
`verify_raw_object` and `restore_raw_object` would say what is verified and
restored without depending on mode vocabulary, and would remain accurate if
capture modes changed.

`materialize` was the sharper problem, because it is a borrowed term used
in two senses in this codebase, only one of which was wrong.

The correct sense survives and should stay: "bring into memory," as in
`fileio.verify_hash`'s note that `read_hash` "would materialize a multi-GB
file for no reason here," and `source_verification`'s "do not materialize or
copy it merely to answer an evidence query." Both describe a cost being
avoided, which is the ordinary meaning.

The wrong sense was the operation name and its parameter. In
Rust, materialization is not a domain term at all -- the relevant senses are
from databases (a materialized view: a query result stored rather than
recomputed) and from lazy evaluation (forcing a deferred computation into
concrete values). Neither describes this function, which decompresses a
stored object back to a file. Nothing was deferred and nothing is being
cached from a computation; bytes are being written back out. `restore` says
that plainly and carries no borrowed connotation. Both renames are applied:
`verify_captured_object` and `materialize_captured_object` are now
`verify_raw` and `restore_raw`.

The parameter `materialized_target` had the same defect with a further one
on top -- it named neither what the file is nor why it exists. It is an
uncompressed copy written beside the capture so a caller can open the
database directly rather than decompressing on each use, so it is now
`working_copy_target`, with `working_copy_path` and `working_copy_bytes`
following. The call chain reads consistently:

```text
cli.ingest_cmd            working_copy_path=cohort_db
  cursor_cohort           working_copy_path: Path            (parameter)
    cache hit  →          restore_raw(object_path, working_copy_path, cached)
    cache miss →          raw_store.observe(..., working_copy_target=working_copy_path)
      raw_store           os.replace(capture_path, working_copy_target)
                          progress("raw.working_copy.done", working_copy_bytes=...)
```

**Partition or bundle the read/decompress/validate/update/compress/store
sequence?** Checking the callers answers this: no caller assembles those
steps. Each direction is already one public operation with private steps
underneath.

```text
WRITE PATH                              READ PATH
RawStore.observe(path, mode)            verify_raw(path, record)
  stat source                             stat stored object
  fingerprint source        ─┐            digest stored bytes
  compress → staged file     │            ┌─ _read_source_identity ─┐
  digest source bytes       ─┴─ shared ───┤   decompress + digest   │
  store object + record                   └─ compare with record ───┘

                                        restore_raw(path, target, record)
                                          same read, plus:
                                            write chunks to target
                                            compare, then os.replace
```

The steps are not independently meaningful -- verifying without reading, or
compressing without storing, is not an operation any caller wants -- so
bundling at the public boundary is right. The seam that does exist is
direction: capture reads an uncompressed source and writes a compressed
object; verify and restore read a compressed object back. That is where the
code divides, and the two read operations differ only in the destination of
the bytes, which is what one helper with an optional output absorbs.

**Read-path naming should correspond to `observe`.** `observe` is a good
name for the write path because it states the epistemic claim the module
makes: Codess is recording that a source existed in a particular state at a
particular moment, not asserting ownership of it. The four raw modes are
degrees of that observation, from recording identity alone to retaining
exact bytes, which is why the parameter is `mode` rather than a boolean.

The read side has no comparable organizing verb. `verify_raw` and
`restore_raw` are accurate but unrelated to each other and to `observe`,
and `RawStore.resolve` returns a path without reading anything, so the
public surface reads as four unrelated verbs. A closer correspondence would
name the read operations after what they do with a prior observation --
`RawStore.observe` writes one, and the read path re-examines it.

W23 carried the renaming that removed the mode vocabulary and the borrowed
database term, and closed there. This further idea -- naming the read
operations as a matched set against `observe` -- was not part of it and is
not scheduled: the current names are accurate, so the change would buy
symmetry at the cost of another wire-visible rename. It is recorded here as
a considered option rather than as pending work, and belongs with 14.4's
vocabulary maintenance if a reader ever finds the four verbs confusing in
practice.

The migration is complete except for three sites whose truncation widths the
shared module does not offer; those wait on the width decisions in this
section. A contract test fails if a new direct `hashlib` call appears
anywhere else, so the boundary is enforced rather than conventional.

##### JSON Serialization: `ensure_ascii=False` Universally

`json.dumps(..., sort_keys=True, separators=(",", ":"))` was written out at
every site that digested a structure, and those sites did **not** agree: a
minority passed `ensure_ascii=False` and the rest took the default `True`.
Two sites in one file disagreed with each other. The two forms produce
different bytes for any non-ASCII content, and therefore different digests
for equal content:

```text
input:  {"n": "café"}

ensure_ascii=True (default)  ->  {"n":"caf\u00e9"}   19 bytes
ensure_ascii=False           ->  {"n":"café"}        17 bytes
```

Both are valid JSON and both parse back to the same object, so nothing
errors and no test fails; two equal documents simply appear to differ. That
makes this a sharper finding than the hashing sprawl, because a digest
comparison is exactly where the difference surfaces as a wrong answer rather
than a crash.

**Recommendation: `ensure_ascii=False` everywhere, applied through one
encoder.** The reasoning, with each claim tested rather than assumed:

| Consideration | Finding |
|---|---|
| Storage compatibility | Both forms satisfy SQLite `json_valid()`, round-trip through `TEXT` unchanged, and give equal `json_extract` results. No storage reason to prefer either |
| Size | UTF-8 is smaller for non-ASCII content -- 43 bytes against 61 for a mixed Latin/CJK/emoji document, and the gap widens as non-ASCII density rises |
| Readability | `{"n":"café"}` is legible in query output, a database browser, and a diff; `{"n":"café"}` is not. Codess stores prompts, paths, and tool output, where non-ASCII is ordinary rather than exotic |
| Output-stream safety | The historical argument for escaping -- a non-UTF-8 stdout -- does not apply. Python forces UTF-8 for stdout from 3.7, confirmed here even under `LC_ALL=C` |
| Interoperability | UTF-8 is the JSON interchange default under RFC 8259, so the unescaped form is what other tools expect to read |

**One real hazard, and its resolution.** Codess digests filesystem paths,
and a path whose bytes are not valid UTF-8 reaches Python as *lone
surrogates* through `os.fsdecode` -- the byte `0xE9` in a Latin-1 filename
becomes `\udce9`. Encoding that strictly raises `UnicodeEncodeError`, so a
single undecodable filename anywhere in a scan would abort the operation.
The escaped form sidesteps this only by accident, since `\udce9` is
representable as an escape sequence.

The resolution is not to prefer escaping but to encode with
`errors="surrogatepass"`, which renders surrogates deterministically instead
of raising. `codess/hashing.py` applies this in both `canonical_bytes` and
component encoding, so an undecodable path yields a stable digest rather
than a failure. This was the substantive risk in the recommendation and is
the reason the choice belongs in one encoder rather than being repeated as
a keyword argument at 16 call sites -- the `surrogatepass` decision would
otherwise have to be remembered independently at each of them.

Every digest over a structure should route through `canonical_bytes`. The
29 sites currently taking the default are the ones that change; because they
produce different bytes today, any digest already stored from a non-ASCII
document will differ after migration, so this is a value-changing change for
that subset rather than a pure refactor. Digests over ASCII-only content are
unaffected, which is the majority.

**`codess/hashing.py` as the single derivation point.** Four modes cover the
operations above. They differ in what they consume, not in the digest they
compute, and each has a matching `..._check` so verification never re-derives
a construction by hand:

| Function | Consumes | Replaces |
|---|---|---|
| `codess_hash(generated, truncated, inputs)` | A list of short values, NUL-separated behind a `codess.hash/1` tag | `identity._qualified` and the ad-hoc key sites |
| `codess_canonical_hash(generated, truncated, value)` | One JSON-serializable structure via `canonical_bytes`, which fixes `sort_keys`, separators, `ensure_ascii=False`, and `surrogatepass` | `query_api.content_hash` and the document-digest sites |
| `codess_bytes_hash(generated, truncated, content)` | One in-memory buffer, untagged | `fileio.write_hash` and content digests already in memory |
| `codess_stream_hash(generated, truncated, chunks)` | An iterable of chunks | `fileio.hash_file` and other bounded reads |

`codess_digest()` additionally returns the incremental object for callers
whose *read pattern is itself the policy* -- the bounded window sampling in
`fileio.read_source_revision`, which interleaves seeks and stat checks. That
policy stays in `fileio`; only the digest construction moves.

Supported widths are 256 generated, and 256, 128, or 64 retained; anything
else raises rather than silently truncating to an unreviewed length.
Truncation keeps *leading* bits, matching every existing site, so adoption
does not change any value already stored -- which is what makes migration a
refactor rather than a data change. Which end is retained does not affect
collision resistance; fixing it does, because a value that changed ends
would invalidate every key derived from it.

Two mode distinctions matter when migrating. The component mode is *tagged*
and separated, so it deliberately does not reproduce today's untagged
`sha256(str(x))` key sites; those map to `codess_bytes_hash` if their values
must be preserved, or to `codess_hash` if they are regenerated. Content
modes are untagged precisely so their output matches what an external tool
computes over the same bytes, which is required for any value a reader
verifies independently. Reproduction of the existing `hash_file`,
`content_hash`, and staging-key constructions was confirmed against all
three.

Callers pass widths and never name the algorithm, so replacing SHA-256
becomes a change to one module rather than to 21. The three widths at 64,
128, and 256 bits replace the former ad-hoc 48, 64, 96, and 256. The
migration is complete: the 48-bit snapshot suffix moved to 64, and the two
96-bit sites (`local_path_key` and the preflight identity) moved to 128 --
each to the nearest declared width at or above what it used, so no site
lost headroom in the process. No `hashlib` call remains outside `codess/hashing.py`, and a
contract test fails if one appears or if a caller requests an undeclared
width.

**Codess-specific naming is spelled out, not abbreviated.** The function is
`codess_hash` rather than `cs_hash` because every existing product-scoped
name in the codebase spells the product out:

| Surface | Convention | Count |
|---|---|---|
| Environment variables | `CODESS_*` -- `CODESS_REGISTRY`, `CODESS_RAW_MODE`, `CODESS_MAX_EVENTS_PER_SOURCE` | 29 distinct |
| Stored value namespaces | `codess:<kind>:...` -- `codess:session`, `codess:observation`, `codess:workspace` | 10 kinds |
| Format tags | `codess.<subsystem>/<version>` -- `codess.coschema`, `codess.id/1`, `codess.snapshot/1` | Several |
| Filesystem | `.codess/` store directory, `~/.codess` registry | Two |
| Package and command | `codess` | One |

Introducing `cs_` would create a second abbreviation for the same product
with no rule for choosing between them, and `cs` is not distinctive -- it
reads as an initialism a newcomer must be told. The cost of spelling it out
is a few characters at each call site; the benefit is that every
Codess-specific name in the project follows one rule. The new module's
format tag `codess.hash/1` matches the existing tag convention for the same
reason.

Two related observations from the same survey. `CODESS_MAX_CODESS_DB_BYTES`
repeats the prefix inside the name and should be `CODESS_MAX_DB_BYTES`, and
`CODESS_DAYS`, `CODESS_FORCE`, and `CODESS_STOP` name a value without
naming what it governs. Neither blocks anything; both belong with the
vocabulary work already listed in this section.

*Locally derived values* are the five sites this section reviews. Four
truncate the digest and one retains it in full. Length is an implementation
detail downstream of three questions that are not answered anywhere: how
long the value must live, what must be able to recompute it, and whether
anything retrieves data by it.
**No site uses a hash for content-addressed retrieval** -- nothing looks up
a dataset by digest. Every use is either equality comparison or a name for
a location. That bounds the whole problem: these are naming and comparison
values, not an addressing scheme, so collision tolerance is governed by how
many values coexist in one namespace, not by any global uniqueness claim.

**Sizes.** SHA-256 produces a 32-byte (256-bit) digest, rendered as 64
hexadecimal characters. Every truncation in this codebase is expressed in
hex characters, so a length in bytes is half the stated figure:

| Truncation | Bytes retained | Bits | Discarded |
|---|---|---|---|
| 12 hex | 6 bytes | 48 | 26 of 32 bytes |
| 16 hex | 8 bytes | 64 | 24 of 32 bytes |
| 24 hex | 12 bytes | 96 | 20 of 32 bytes |
| 64 hex | 32 bytes | 256 | none |

**Portability.** Byte order, struct packing, and word size do not arise:
SHA-256 is defined over byte sequences, and every site hashes UTF-8 encoded
text, so the digest of given input text is identical on any machine and
platform. The exposure is entirely in *what is fed in*. Path text is the
problem case: case sensitivity differs (Linux sensitive, macOS usually
not), separators differ on Windows, the same repository sits at different
absolute paths on different machines, and Unicode normalization differs.

Normalization is the least obvious of these. Unicode can represent the same
visible character in more than one way: `é` is either one code point
(U+00E9) or two (U+0065, the letter `e`, followed by U+0301, a combining
acute accent). The Unicode standard defines normalization forms that convert
between these representations, and two are relevant here:

| Abbreviation | Full name | Effect |
|---|---|---|
| NFC | Normalization Form C, for *Composition* | Combines a base character and its combining marks into one code point where one exists, giving the shorter encoding |
| NFD | Normalization Form D, for *Decomposition* | Separates a composed character into its base and combining marks, giving the longer encoding |

macOS stores filenames decomposed (NFD), while Linux stores whatever bytes
it was given, in practice usually composed (NFC). A directory named `café`
therefore encodes as 4 UTF-8 bytes on one platform and 5 on the other, and
the two forms produce entirely different digests even though the path looks
identical and refers to the same directory. Any key derived from
unnormalized path text is thus platform-dependent whenever a non-ASCII
character appears in the path. Applying
`unicodedata.normalize("NFC", ...)` before hashing removes this specific
difference, though not the case, separator, or location differences above.

Paths are therefore not persistent across computers, and any value derived
from one is machine-local. Two sites are affected and must be documented as
such rather than treated as portable identities:

| Value | Path-derived | Consequence |
|---|---|---|
| `path_label.path_key` | Yes, resolved path text | A review catalog is machine-local; the same checkout elsewhere yields a different key |
| `identity.location_id` | Yes, but deliberately | Already correct: its docstring says "never a logical project," it is qualified by `machine_id`, and it applies `normcase`/`realpath`, so machine-locality is explicit in the design rather than incidental |
| `snapshot.py` snapshot identity | Yes, Project path is one input | Compounds the creation-identity question in item 4; a snapshot moved or rebuilt elsewhere cannot reproduce its own name |

`location_id` is the model to follow: when a value must be path-derived,
qualify it with the machine and say so in the name and docstring.
`identity.py`'s other identities avoid the problem entirely by deriving
from vendor-supplied identifiers rather than from local paths.

**A derived value must never be inside the structure that produces it.**
Two current layouts violate this and should change:

- `_backup_store` writes `snapshot_id` into each store's `store_meta`, and
  the store file is then hashed into the manifest. The recorded content
  digest therefore covers a value derived from that same content, so the
  digest cannot be recomputed from the data alone without first knowing the
  identity it is supposed to help establish.
- The manifest contains `snapshot_id` and is itself hashed as
  `manifest_sha256` in the current-snapshot pointer, repeating the pattern
  one level up.

The rule is that identity and integrity live in a layer above the data they
describe: the payload is hashed, and the resulting digest plus any name is
recorded in a separate document that is not itself an input. Applying it
here means removing `snapshot_id` from `store_meta` and letting the
manifest hold the association, which also removes the circularity noted in
item 4. `identity.py` already follows the rule -- a `sessions` row's
`entity_id` is computed from vendor fields and stored beside them, never
folded back into a digest of the row.

**1. `path_label.path_key` -- review key, 24 hex (12 bytes). Persisted and
used for retrieval.** This is not a transient comparison value, and an
earlier reading of it as one was wrong. `review_project.py` writes it into
the review catalog beside the path, and `record_review_decision` accepts it
as a `project_ref` an operator supplies to attach a review decision to a
Project. It must therefore stay equal across separate command invocations
and remain valid as long as the catalog does. Lifetime: the review
catalog's. Resilience required: stable across runs, process restarts, and
unrelated Projects being added or removed -- all satisfied, since it derives
from the resolved path alone.

*What is hashed:* one string, the resolved absolute path
(`expanduser().resolve()`), UTF-8 encoded. Input size is one filesystem
path, typically well under 200 bytes and bounded by the platform path
limit; output is 24 hex characters.

*Naming.* The value prefix is `candidate:path-key:`, changed from
`candidate:path:` because what follows is a derived value, not a path. The
old form read as though the path itself followed -- the damaging misreading
for a value an operator copies from a catalog and passes back on a command
line, since a reader could expect to recognize or edit the path portion.
`path-key` states the input domain and that this is a lookup key whose only
promise is equality. It deliberately does not name the algorithm: nothing
recomputes this value to verify it, so `sha256` would publish an
implementation choice callers must not depend on. The prefix is a stored
wire value and a separate decision from the Python function name and the
catalog field name; all three changed here, each for its own reason.

Two requirements remain unstated. First, behavior when a reviewed directory
*moves*: the key changes, which is right if a location is being named and
wrong if a Project is, and the catalog would then hold a decision no
reference resolves to. Second, cross-machine use: the same repository
checked out at a different path, or on a different platform, yields a
different key, so a review catalog is machine-specific in practice though
nothing says so. Both must be settled before the derivation changes; they
decide whether a path is the right input at all.

**2. `cli.ingest_cmd` staging directory name -- 16 hex (8 bytes).
Transient equality, not an identity.** Correctly characterized as a hash
rather than a key. It exists only to give each Project a distinct directory
name under one preflight `TemporaryDirectory`, which is deleted when the run
exits. Lifetime: one process. Resilience required: none -- it need not
survive the run, be reproducible later, or be portable anywhere.

*What is hashed:* one string, `str(proj)` -- the Project path as supplied,
without resolution, UTF-8 encoded. Same input class and size as item 1, and
the same path-portability exposure, which does not matter here because the
value never leaves the run. Its only obligation is distinguishing the
handful of Projects in a single invocation, and the sibling call site
already meets that obligation with a plain sequential `project_index`. This
site should lose its hash entirely rather than be consolidated with
anything.

**3. `cli.ingest_cmd` preflight Project identity -- 24 hex (12 bytes). Transient
equality, not an identity.** Also a hash rather than a key, despite being
formatted as `codess:preflight-project:<digest>`. It stands in for a
Project identity while validate-only mode runs and is discarded with the
run; nothing published ever contains it. Lifetime: one process. Resilience
required: none. It exists because surrounding code expects an identity-
shaped string, so the question is not its length but whether preflight
should construct a value that resembles a real Project identity at all --
which is W14's question about marking provisional identities explicitly.

**4. `snapshot.py` snapshot identity -- 12 hex (6 bytes). Requires a decision.**
Persisted indefinitely and used for retrieval, though by path join rather
than by content lookup. `snapshot_id` is the *directory name*: creation
does `snapshots / snapshot_id`, and `baseline_catalog` resolves a reviewed
snapshot as `durable_project_root(...) / "snapshots" / snapshot_id`. It is
also the `parent_snapshot_id` link between successive snapshots. Lifetime:
as long as the snapshot is retained. Resilience required: it must remain
resolvable from a catalog written earlier, which means it must not change
after creation.

**What a snapshot is, on the evidence.** It is a directory location and its
contents at a moment, not a content-addressed dataset. It has a parent
link, a `created_at`, a build policy, and runtime provenance; catalogs
reference it by name to find a directory. Nothing dereferences a content
digest to obtain it, and successive snapshots of identical content are
intended to be distinct retained artifacts, not one deduplicated object.

That resolves the tension in the current derivation, which mixes both
models. Because it folds in `created_at` at microsecond precision, the
identity is unique per creation and the content-derived portion of the
digest is decorative -- the timestamp alone already guarantees uniqueness.
The honest options are:

- **Creation identity (recommended).** Accept what a snapshot already is.
  The identity names an event, not a value. Then the digest should be
  dropped or reduced to a short disambiguator, since the timestamp does the
  work; per-store content hashes remain in the manifest, where they already
  are, for verifying that a snapshot's contents are intact.
- **Content identity.** Only worth adopting if a use case appears that
  requires equal content to yield an equal name -- deduplicating identical
  snapshots, or checking a rebuild against its predecessor by name. No
  such consumer exists today.

**Proposed redesign.** Adopt the creation identity and separate it cleanly
from content verification, which the manifest already performs.

*Current derivation.* `sha256(project_path, created_at, package_digest,
policy_digest)[:12 hex]`, embedded in a name of the form
`<UTC timestamp>-coschema<version>-<12 hex>`, then written into every
store's `store_meta` and into the manifest, both of which are subsequently
hashed.

*Proposed derivation.* Keep the timestamp-plus-format name and derive the
suffix only from inputs that distinguish two snapshots created in the same
microsecond:

| Element | Current | Proposed | Reason |
|---|---|---|---|
| UTC timestamp in name | Yes | Yes | Already guarantees uniqueness and sorts chronologically as a directory listing |
| Format version in name | Yes | Yes | Lets an operator see store compatibility without opening the manifest |
| `project_path` in suffix | Yes | Yes | Distinguishes concurrent snapshots of different Projects |
| `policy_digest` in suffix | Yes | Yes | Distinguishes two builds differing only by build policy |
| `package_digest` in suffix | Yes | **No** | Couples snapshot naming to package identity; removed under W03 |
| `created_at` in suffix | Yes | **No** | Redundant with the timestamp already in the name |
| Suffix length | 12 hex | 12 hex | Adequate: it disambiguates within one microsecond, not across a corpus |
| `snapshot_id` in `store_meta` | Yes | **No** | A name must not sit inside a structure whose digest records it |
| `snapshot_id` in manifest | Yes | Yes | Correct location: the manifest is the layer above the stores |

*Layering after the change.* Stores hold data only. The manifest holds each
store's content digest, the raw-manifest digest, the snapshot name, and the
parent link. The pointer holds the manifest digest. Each layer names and
verifies the one below it and is never an input to it, so every digest is
recomputable from the bytes it covers.

*What this gives up.* Nothing that exists. Equal content still does not
yield an equal name, but no consumer needs that, and per-store digests in
the manifest already answer "are these two snapshots' contents identical"
without an identity scheme. If a deduplication or rebuild-comparison
consumer appears later, a content digest can be added to the manifest as a
separate field without renaming anything -- which is the advantage of not
overloading the name.

*Decision and outcome.* Both settled and implemented. Snapshot identity
stays a **creation** identity, and `snapshot_id` is no longer written into
each copied store's `store_meta`; the manifest and the directory name carry
it. `_backup_store` lost the parameter, `rebuild_manifest` takes the
identity from the directory, and `query_api` reports it from the snapshot
pointer.

Removing it also removed a check, which was worth confirming rather than
assuming. `snapshot_store_paths_from_base` compared each store's recorded
`snapshot_id` against the manifest's -- but the line above it already
verifies that store's content digest against the manifest, which names the
exact file. The digest is the stronger claim: it rejects a store copied from
a sibling snapshot *and* any modification to the correct one, both of which
were confirmed after the change. The identity comparison could only restate
what the digest had established, and it was that restatement that created
the cycle.

`path_key` is settled as a **location** name and renamed `local_path_key`,
with its emitted prefix `local:path-key:`. The review catalog is keyed by
`path` rather than by this value, which serves as an alternative reference
when recording a decision, so nothing depended on it being an identity. The
portable identity a candidate needs already exists and is acquired on
approval (`project_catalog.ensure_project_binding`); a second, path-derived
one would disagree with it the first time a directory moved. Whether the
review catalog should also carry a Project name is recorded as a Postponed
direction rather than an open item.

*Migration.* Existing snapshot directories keep their names; nothing
recomputes an identity after creation. Removing `snapshot_id` from
`store_meta` affects only stores written after the change, and the reader at
`_reconstruct_manifest` already falls back to the directory name when the
key is absent, so older stores remain readable.

Timestamps recorded inside the manifest are the snapshot's own record of
when it was built and are unaffected by file mtimes, so archive and
filesystem moves do not alter the identity -- provided nothing recomputes it
after creation or derives it from filesystem metadata.

**5. `tool_identity.bounded_source_call_id` -- full 64 hex (32 bytes). Persisted, and
the only genuine relational key here.** It carries the vendor's own call
identifier into `tool_invocations.source_call_id`, which the schema
constrains with `UNIQUE(session_id, source_call_id)` and which links an
invocation to its result. Lifetime: the store's. Resilience required:
identical for the same invocation whenever it is decoded again, so
re-ingesting a Session reproduces the same rows rather than duplicating
them; distinct for every distinct invocation, since a collision would merge
separate tool evidence under one unique constraint and lose a record.

**Two identical calls are two invocations, and remain so.** This is a
property of the input, not of the hash. The function does not digest the
tool's inputs or outputs; it digests the vendor-supplied `call_id` or
`tool_use_id` from Event metadata. Two calls to the same tool with
identical arguments and identical results carry different vendor
identifiers, so they produce different keys and occupy two rows. Identity
here means "the same recorded invocation," never "an invocation that looks
the same." Any future change must preserve that: deriving the key from
tool name and arguments would silently collapse legitimate repeat calls --
a plausible-looking change that would destroy evidence, since repeated
identical calls are ordinary in a Session.

The function is also bounded rather than merely hashed: short identifiers
pass through byte-for-byte and only over-long ones are replaced by a
readable prefix plus the full digest, so most stored values remain the
vendor's own string. The full digest is deliberate, the docstring says so,
and it must not be shortened.

**Conclusions.** The five sites do not form a group. Two are transient
equality hashes with no stability requirement (2 and 3), two are persisted
retrieval keys with different inputs and different portability exposure
(1 and 4), and one is a relational key that must preserve record
distinctness (5). What they share is only calling SHA-256, so there is no
shared abstraction to extract beyond one helper deriving a hex key from a
string with the caller supplying the length. Two sites should lose their
hash rather than gain a shared one: the staging key has a working
sequential alternative in the same file, and the snapshot identity's digest
is decorative under the creation-identity reading recommended above.

*Outcome.* The staging key is removed rather than migrated, and removing it
resolved a divergence rather than only a duplication. `VendorStore.path`
hashed the Project path to place preflight stores, while the Project loop
derived the state path from the loop index -- so during preflight a
Project's stores and its ingest state landed in different staging
directories. Nothing failed, because preflight discards both and always runs
with `force`, so the state was never read back; but the two were independent
answers to one question, and either could have changed without the other.
Preflight now registers its staging directory in `staged_store_roots`, the
mapping a rebuild already used, so one registration serves stores and state
alike and the hash has no remaining caller.

The snapshot identity's digest is retained rather than dropped. Under the
creation-identity reading its inputs are already distinguishing -- a
microsecond timestamp plus the Project path -- but the suffix costs nothing,
disambiguates two snapshots created within the same microsecond, and
removing it would change every snapshot directory name for no gain. It moved
from 48 to the supported 64 bits. The remaining three persisted values keep
their hashes, since each is a retrieval or relational key with a stated
requirement.

**Supported truncation lengths.** A shared helper must retain 16 and 32 hex
characters (8 and 16 bytes) as available lengths alongside the full 64. Both
are held open deliberately -- 32 hex in particular has no current site, and
neither has a fixed application yet -- so the helper's contract must not
narrow to whatever the present five sites happen to use. Exact application
remains to be decided per site as the requirements above are settled.

| Length | Bytes | Bits | Status |
|---|---|---|---|
| 12 hex | 6 | 48 | In use (snapshot identity, under review) |
| 16 hex | 8 | 64 | In use, and retained as a supported length |
| 24 hex | 12 | 96 | In use (`path_key`, preflight identity) |
| 32 hex | 16 | 128 | Retained as a supported length; no current site |
| 64 hex | 32 | 256 | Full digest; required for entity identities and item 5 |

Collision likelihood follows the birthday bound -- roughly the square root
of the space -- so 48 bits reaches even odds near twenty million keys, and
each additional 16 bits multiplies that threshold by 256. Every truncating
site here has a population many orders of magnitude below its bound, which
is why none is currently a defect. This is accidental-collision arithmetic
over locally generated values; no adversarial analysis applies, since the
inputs are a developer's own paths and runs.

### 4.9 SQL Construction Volume

10.4 already establishes which interpolation patterns are safe, why a
`.join()` rewrite helps single-line queries and harms multi-line ones, and
that suppression is per-file with the rationale recorded there rather than
in source. This section records only what the audit adds: how many sites
there now are.

Twelve modules originally carried a per-file `S608` ignore, covering 56
findings -- `cursor_feature_audit` 15, `query_cmd` 11, `query_api` 9,
`configuration_audit` 8, the rest one to four each. Every one matches a
pattern 10.4.2 classifies as safe, so the count is not a defect list.

It is still a measurement worth acting on. Fifty-six interpolation sites is
more SQL assembly than the layering intends. The four shapes -- placeholder
runs, column projections, predicate fragments, fixed table names -- each have
a natural home in a helper, so concentrating them reduces the count and the
maintenance surface together, and leaves a smaller set of files where a
per-file ignore names a module rather than covering one.

**What W26 and W06 already moved.** Both boundary changes relocated
interpolation rather than adding it, and the current count is 52 across ten
modules:

| Module | Before | Now | Why |
|---|---|---|---|
| `cursor_feature_audit` | 15 | 0 | Its queries are `cursor_source.read_feature_evidence` (6.4) |
| `cli.query_cmd` | 11 | 0 | Its report queries are `codess/query_reports.py` (4.1) |
| `cursor_source` | 8 | 23 | Received the audit's queries |
| `query_reports` | — | 11 | Received the command module's reports |
| `session_names` | 1 | 0 | No interpolated statement remains |

The exemption list in `pyproject.toml` was corrected to match: two modules no
longer need one, and the new module does. The point is not the total, which
barely moved, but that no command module and no audit module is on the list
any more -- every remaining exemption names a source-access, query, or store
module, which is where SQL assembly belongs. Reducing the sites within those
modules is ordinary cleanup rather than tracked work.

The exemptions do their job whenever the rule runs: selecting `S` reports 73
findings without them and 17 with. What was missing is that `pyproject.toml`
never declared `select`, so `S` ran only when someone passed it on the
command line -- the exemptions were correct and the selection that would
exercise them was not recorded.

**W29's outcome.** The rule set is declared, and it was chosen by measuring
each family before adopting it rather than by taking a default:

| Selected | Why |
|---|---|
| `E`, `W`, `F` | Undefined names and unused imports; the failures that are always defects |
| `I` | Import ordering, so a diff does not depend on where an import landed |
| `B` | `B023` (loop-variable capture) is the one real bug class the survey found |
| `S` | SQL construction and subprocess use -- the two surfaces that touch a store and a shell |
| `C4`, `SIM`, `RET`, `ARG`, `RUF` | Comprehension, branch, return, and argument cleanups |
| `N`, `UP`, `PTH` | Naming, modern syntax, and `pathlib` over `os.path` |

Eleven further families were measured afterwards and eight were added
because they report *zero* -- which is the argument for selecting them, not
against: `DTZ`, `ASYNC`, `LOG`, `G`, `ISC`, `ICN`, `TID`, and `PGH` cost
nothing today and fail the moment the property each checks stops holding.
`PERF`, `FURB`, and `SLF` were added for being small and actionable, and
`FURB162` immediately earned its place by finding all six
`fromisoformat(...replace("Z", "+00:00"))` workarounds that 14.4 records as
removable, plus one in `tools/`.

Three families were measured and declined, each for a stated reason rather
than by omission: `ANN` (990 + 896 findings -- annotation coverage is not a
defect class here), `D` (594 -- docstring shape, where this codebase's
convention is explanatory prose), and `COM` (854 -- trailing commas, which is
formatting). `PL` (627) and `TRY` (361) were also declined: their findings
are largely magic-value comparisons, argument counts, and exception-message
style, which describe this codebase's shape rather than defects in it.
`E501` is disabled because `line-length` sets the same limit; it was
measured at 110 rather than 88 because 460 source lines exceed 88 and 174
exceed 100, so a narrower limit would report existing code rather than new
defects.

Adoption fixed 187 findings automatically and left 91, all genuine
cleanups. Four `S` rules are ignored globally with reasons recorded in
`pyproject.toml`: every `subprocess` call passes a list with no shell and
runs `sys.executable` or `git`; `git` is resolved from PATH deliberately;
`S105` matches the substring `TOKEN` in document format tags; and `S108`
matches `/tmp` in the tables `helpers` uses to *reject* such paths. Tests
additionally ignore `S101` and the `ARG` family, since a test asserts and a
test double takes arguments it deliberately ignores.

Two real defects surfaced. `B023` flagged the `record_source` closure that
4.1 had separately identified as a closure by accident -- it read four
enclosing values and rebound none -- so it is now a module-level function
taking them explicitly. And `mypy` found `ReportScope` declaring
`source_predicate` but not `diagnostics_predicate`, although
`mapping_diagnostics` called it: a protocol that did not describe its own
implementers.

Type checking is configured and its 179 errors are reported as a
measurement rather than a gate. They are dominated by `assignment` and
`arg-type` in code that reads vendor JSON, where a value is legitimately
`Any` until validated; tightening those wants the candidate-record contract
(W04), so `strict_optional` and `warn_return_any` are recorded as not-yet
with the item that would make them achievable.

`tools/quality_report.py` reports all three counts together. Only the test
suite gates its exit status: lint and types have nonzero baselines being
reduced against named items, and failing on them would make the report
unusable exactly while it is most useful.

### 4.10 The SQLite Connection and Driver Boundary

Where SQL may live is 4.10's subject; this is how Codess *talks to* SQLite.
The distinction matters because the properties a caller depends on --
`query_only`, `foreign_keys`, `busy_timeout`, `row_factory` -- are applied by
SQLite **per connection and never per file**, so opening the same store two ways
gives two different guarantees. Tracked as **W56**, now closed in four parts.

**One opener owns each contract.** `fileio.open_readonly` owned the read side
already; `fileio.open_writable` now owns the write side, and `store.init_db`,
`store.connect`, and `snapshot._backup_store` adopt it, the last with
`foreign_keys=False` stated at the call site because `backup()` copies pages and
row-level constraints never apply. Two raw `sqlite3.connect` calls remain, both
inside `fileio`'s own openers, plus one in `raw_store` that states why it differs.
A test fails if a third appears.

**Removing a redundant assignment exposed a real asymmetry.** `store.connect`
re-set `row_factory` and `foreign_keys` after the opener had already applied
them, which read as belt-and-braces. It was not: `open_writable` set
`row_factory` and `open_readonly` did not, so `store.connect` was silently
compensating for the read path -- and a caller opening the same store through
`open_readonly` directly received positional tuples where one going through
`store.connect` received named rows. Deleting the compensation turned that into
52 failing tests, which is how the gap became visible. The fix is that both
openers own `row_factory`. Setting `foreign_keys = ON` unconditionally was also
wrong for the read path, where `query_only` makes constraint enforcement moot.

**The isolation model is stated rather than defaulted silently.** Codess uses
deferred transactions throughout -- SQLite's default, with no `isolation_level`
set, no `BEGIN IMMEDIATE`, and `read_uncommitted` never enabled -- across 16
commit and rollback sites in 7 modules. Deferred is correct for a single-writer
local tool, but the point of writing it down is that a reader could not
previously distinguish the decision from an omission. It is recorded on the
openers, where a reader looks, with the two sites that need more than the
default naming their reason locally: `cursor_source.get_selection_markers`
brackets its reads in one explicit transaction because a vendor database is
written by its own live application and a read snapshot ends with the
transaction, and the `backup()` sites take their own page-level snapshot and are
not governed by the model at all.

**The driver boundary was one handler, not fifteen.** The original inventory
counted `except sqlite3.Error` handlers and read all of them as catching a
driver exception across a layer boundary. Classifying them by *who opened the
connection* gives a different answer: of 14 handlers in 10 modules, 13 are in a
module that opened the connection itself, so the exception originates locally and
catching it there is correct. Exactly one crossed a boundary -- `query_cmd`
opens no connection and caught `sqlite3.Error` raised inside the store layer,
because the store layer had no error of its own while every peer
(`RawCaptureError`, `SnapshotError`, `QueryContractError`) did. `store.StoreError`
closes that: `connect` translates a driver failure, the CLI catches the Codess
error, and a test asserts `StoreError` is not a `sqlite3.Error` subclass so the
boundary is real rather than nominal.

The general lesson is the one 15.7 records in another form: a count is not a
classification. "Fifteen handlers catch the driver" and "one handler catches the
driver across a boundary" were derived from the same grep, and only the second
described work worth doing.

### 4.11 CoSchema Format 6

**Nine columns removed, one renamed, one vendor description.** Each removal was
measured across 90 real stores before it was made, and the measurement is the
argument: a column holding one value on every row is storage and reader
attention spent on a value that answers nothing.

| Removed | Rows measured | Value found |
|---|---|---|
| `content_objects.media_type`, `.charset`, `.storage_class` | 236,535 | `text/plain`, `utf-8`, `inline` |
| `event_content.sequence_no`, `.integrity_state` (and the three sibling link tables) | 494,384 | `1`, `verified` |
| `tool_results.producing_actor_kind` | 127,432 | `tool` |
| `event_artifacts.evidence_source`, `.confidence` | 44,449 | `tool_input`, `1.0` |
| `sessions.session_purpose` | 658 | `coding` |
| `sessions.product_name` | 658 | a pure function of `source_system_id` |

**The removal was per column, not per name.** `sequence_no` appears in nine
tables and genuinely orders rows in four of them -- measured maxima of 19,661 for
`events` and 5,564 for `model_turns` -- so dropping the name everywhere would
have destroyed real ordering. It was removed only from the four `*_content` link
tables, where it was part of the primary key and no `(owner, relation_kind)` pair
ever repeated, so the sequence distinguished nothing.

**One removal found dead code.** `_ensure_content_object` took a `storage_class`
parameter and branched on it to decide whether to store `inline_content`. No
caller ever passed a value, so the branch was unreachable and the column
recorded the default on every row. A constant column and an unreachable branch
are the same defect seen from two sides.

**`mapping_diagnostics.level` became `granularity`** (W50). The column holds
`source`/`record`/`field` -- which part of the input a diagnostic is about --
while `severity` sits beside it holding how much it matters. Named `level` it read
as an ordering, which made summing its values look meaningful when doing so
overstates loss. The rename also resolved the collision W50 described:
`field_state.diagnostic` emitted `level` meaning severity *and*
`diagnostic_level` meaning granularity, and the store read the second into the
column named after the first. Both keys now name their own column, and
`field_state.diagnostic_level` became `field_state.severity`.

**W24's vendor table is `config.VENDORS`.** Three separate encodings of the same
three vendors -- an if-chain selecting a store filename, a profile dict keyed by
display name, a display-name lookup keyed by CLI token -- plus the key tuple
`("cc", "codex", "cursor")` at a dozen call sites. All derive from one table now,
and a test fails if the longhand returns. Two keys per vendor is not redundancy:
`key` is what an operator types and names a file, `adapter_key` is what the
decoder and the store record, and they differ for Claude Code.

**The rebuild found a defect that had nothing to do with format 6.** The first
attempt failed on every one of 22 Projects with
`UNIQUE constraint failed: project_locations.machine_id, observed_path`, then on
six with `FOREIGN KEY constraint failed`. Both trace to the *format-5* identity
change: it re-derived every `location_id` from `sha256:` to `id1:`, and a
registry written across both carried two catalog entries for one directory plus a
workspace binding naming the retired one.

That is worth recording for two reasons. The catalog keyed locations by
`location_id`, which is *derived from* the path -- so a change in the derivation
produced a second entry for one physical place. Keying on the natural key
`(machine_id, path)` is the fix, and the general rule is that a derived value is
never the identity of the thing it was derived from. And the failure was latent:
nothing exercised a re-ingest across an identity change, so it surfaced only when
a rebuild was required, which is exactly when it was most expensive. Both halves
now have regression tests that reproduce the original `IntegrityError`.

### 4.12 The Reporting Facility

**`src/codess/reporting/` implements [Report](Report.md).** Six modules with a
strict dependency direction: `clock`, `buffer`, and `codes` are leaves importing
only the standard library, which is what lets `fileio` and the adapters report
without a cycle. A test asserts that boundary rather than trusting it.

Gates G1 to G5 are met. G3 was verified the way Report 12.2 specifies -- against
a real ingest rather than a fixture -- and the progress output is unchanged with
`ProgressTrace` reduced to a shim over the event contract. G5 holds for scan and
ingest: the discovery diagnostics reach stderr and stdout carries only the
requested result, which a test asserts directly.

**One measured figure is worse than Report 3 predicted, and the reason is
structural.** R1 asks that a disabled site cost no more than a bare call:

| Site | Measured | Report 3 |
|---|---|---|
| No sink attached | 76 ns | ~16 ns |
| Sink attached, below `MIN_LEVEL` | 86 ns | ~14 ns |
| Enabled and buffered | 618 ns | — |
| `count(slot)` | 50 ns | 66 ns |
| Compile-gated site | 16 ns | 0 ns |

`**fields` packs a dict before the function body runs -- ~43 ns for two fields --
so no gate *inside* the function can precede it, and Report's estimate assumed a
bare call with no keyword arguments. Three things follow. The cost is still 16x
better than the 1,245 ns it replaces, so R1's intent holds where its number does
not. A per-record site inside a decode loop should take the compile-time gate,
which is what R2 exists for and what the 16 ns measures. And a positional
flat-tuple signature would recover the difference at the cost of every call site
spelling its own tuple, which was rejected: a keyword call is what makes these
sites readable, and the sites that cannot afford 76 ns are the ones R2 covers.

**The privacy profiles work, and `shared` promises less than it appears to.**
Measured on a real ingest, `strict` reduces every path to a root token and
`shared` renders paths root-relative -- but a Claude source under `shared` still
reads `-Users-<user>-Work-<group>-<project>/<uuid>.jsonl`, because the vendor
encodes the absolute path into a directory *name* and the slug is therefore one
path segment. Keeping the final two segments keeps it whole. The two-segment rule
is retained because the alternative is the textual pattern-matching Report 15.4
rejects for missing every naming convention it was not written against; `strict`
is the profile that closes it, and a test pins both halves so the limit is
recorded rather than assumed.

### 4.13 Bounded Discovery Traversal

**W62 and W61 landed before the measurement they were sequenced behind**, and the
sequence was wrong rather than the work early. Both bound *unbounded* work rather
than optimizing measured work, so what they needed was a default that does not
truncate an ordinary tree -- not a workload defining "too slow".

`discover_git_roots` in `review_project` is the traversal, not `walk_sessions`:
the latter reads vendor indexes, while the former is the `os.walk` over an
operator's work root. It had a depth limit and no bound on the work itself.

**A partial result is returned and marked, never discarded.** A scan that
examined 90% of a tree found 90% of the Projects. Measured on the development
machine's real work root: 727 directories traversed against a 200,000 default, so
the budget bounds a pathological input rather than truncating an ordinary one, and
a deliberate 500-directory bound stopped at 501, reported
`stopped_reason=directory_budget`, and still returned 159 Projects.

**Crossing a filesystem boundary is reported, not refused.** `--same-filesystem`
refuses instead, and the default continues, because the common case -- a Project
on an external disk -- is one a refusal would break. The device test costs no
extra syscall: `os.walk` already stats each directory.

## 6. Mechanical Enforcement

### 4.14 Measured Workloads and the Bounds That Needed Them

**The workloads came first, and that ordering paid immediately.** `codess.workload`
records what CoPlan 11.4 requires together -- phase timing, rows, source bytes,
peak allocation, SQLite plans, and a digest over the ordered result -- and
`tools/workload_bench.py` runs two case sizes per workload, anchored to the
largest real store measured (76,329 Events in 584 MB) rather than chosen.

**A digest that compares environments is worse than none.** The first
implementation hashed the whole result, and two identical runs in different
temporary directories reported DIFFERENT. That false positive would train a reader
to ignore the comparison, so volatile fields -- paths, timestamps, snapshot
identities -- are stripped before digesting. The exclusion list is applied to the
result rather than inside the digest, so what is being compared is inspectable.

**The first scale run found a defect inspection had not.** `overview` cost 5.64 s
over 20,000 Events at a flat 282 us/row while every other query action amortized.
Profiling attributed it to 10,000 `strftime` and 20,000 `fromtimestamp` calls for
5,000 Events -- three datetime constructions per row for two values that change at
most once a day. Caching by day made it 2.96 s, **1.9x faster with results
verified equal**, which is the property that distinguishes an optimization from a
regression. It is the same class of defect Report R4 names in the reporting
facility: formatting a timestamp on a path that runs per record.

**Three ancillary reads are bounded, each against a measured corpus.** Claude's
`persistedOutputPath` is refused above 8 MB, against four observed files whose
largest is 110 KB -- and the size is checked *before* the read, because rejecting
afterwards would already have materialized the body the bound exists to exclude.
Worktree fingerprinting bounds both an uncommitted diff and an untracked file at
32 MB, recording size and mtime instead of content, because a dirty tree whose
fingerprint silently ignored its largest file would report two different trees as
the same build. The raw manifest is streamed rather than read whole: it grows with
a Project's Source count -- 212 KB at the largest observed -- and holding the text
and the parsed records is two copies of a file with no stated upper bound.

**Selective Cursor work is independent of the container, measured rather than
argued.** A shared vendor database holds every workspace an operator has, so the
question is whether reading one Project's Sessions tracks the selection or the
container. Growing the container **1000x** -- 0 to 200,000 unrelated bubbles, 19.5
MB -- changed the selected read cost by **1.21x**, and the plan is an indexed
key-range search in both. The plan is the durable assertion: a timing can be fast
on a warm cache, while a plan that became a scan is the regression that appears
later.

### 4.15 Eliminating the Progress Shim

**The shim was not the thin adapter it appeared to be.** `ProgressTrace` was
retained as a compatibility bridge, and a reading of it suggested it delegated to
the new facility. Reading the call path showed otherwise: it constructed its own
`HumanSink` and called `emit` directly, bypassing the level gate, the ring, and
the counters. Two consequences were live rather than theoretical.

**A quiet profile was not quiet.** Every per-source event printed regardless of
`--report-profile`, because the shim's own sink never consulted `_MIN_LEVEL`. The
gate existed and did nothing on the most-used command.

**Twenty-three of thirty-eight event names were unregistered.** The code table was
seeded from a reading of what ingest emits and was wrong about it. Every unlisted
name took the shim's fallback rendering path, which dropped its level and scope
silently. Extracting the names with `ast` found them; a test now derives the same
set from the call sites, so a progress point added without a code fails rather
than degrading. Two further rounds of that check found ten more events behind a
second helper whose name is its *second* argument, and three more in the Cursor
adapter behind an f-string -- the general lesson being that a scan looking at one
argument position finds the convention it was written for.

**The ring cannot do per-Project retention, and that is not a reason to keep a
parallel store.** One ingest run touches several Projects; the ring is
process-wide; each Project's durable report must carry its own events plus the
run-level ones. The shim solved that with a deque outside the facility.
`CollectorSink.records_for` solves it with a filter, so there is one bounded store
and one drop count -- where a collector per Project would have made the drop
accounting per Project too, reporting several partial truths instead of one.

**Removing it exposed the conflation Report 1.4 names.** One process-wide
threshold governed retention *and* display, so filtering the durable report at the
profile's level emptied it of every debug event it had always carried: a quiet run
produced a report that could not explain what happened. R6 requires that immediacy
and permanence be selected independently, and now they are -- each sink declares
its own `min_level`, the api gate uses the minimum across attached sinks, and each
sink drops what it does not want. Validated on a real ingest: **16 lines printed,
242 events retained**, 229 of them debug-level the operator never saw.

**The behaviour change was made deliberate rather than incidental.** Ingest
defaults to the `validation` profile rather than the global `deployment` default,
because a long-running command whose progress an operator watches is exactly the
case that table describes, and `deployment` would show warnings only -- which for
ingest reads as a hang. `--debug` raises it to full trace. Measured gradient on
one real Project: **debug 245 lines, validation 16, deployment 2**, with
`--no-progress` silent and all 242 events still retained. Four events were
reclassified from debug to info in the process, on one rule: an event stating that
work was *skipped* answers the question an operator asks when a re-run finishes
suspiciously fast, so it is lifecycle rather than trace.

**Gate G5 holds across every profile.** stdout is byte-identical for
`query --output-format jsonl` under `validation`, `debug`, and `deployment`, with
stderr empty -- which is what lets the result be piped safely.

**What survives the deletion, and why.** `raw_store`, `ingest_publication`, and
`cursor_cohort` still take `progress` as a parameter. That is dependency
inversion, not debt: CoPlan 3.3 forbids a library module depending on the command
layer, and `reporting.api` holds process-wide mutable state, so a library function
reaching into it reaches into a global. What changed is what the caller passes --
a function that emits through the contract rather than an object with its own
sink. `codess/progress.py` went from 155 lines to 58 and was then removed
entirely: what remained was one three-statement function, which now lives beside
the primitives it wraps as `reporting.emit_named`.

### 4.16 Two Shadowing Defects, and What Actually Catches Them

**Both were reported precisely by a checker nobody ran.** A `dict` rebound a
`list[Path]` parameter in ingest, and later a `str` parameter shadowed the module
function it called -- the second introduced in the function written to replace the
first. mypy names each at the exact line:

    ingest_cmd.py:1577: Incompatible types in assignment (expression has type
      "dict[str, int | Path | str | None]", variable has type "list[Path]")
    api.py:293: "str" not callable

Verified by reintroducing the first defect: the error count moves 190 to 192 with
the shadowing named. The annotations were already sufficient; the failure was
running `pytest` and `ruff` after every change and never `mypy`.

**The tests caught both, and that is the weaker signal.** Each surfaced as an
`AttributeError` or `TypeError` several frames from the cause, costing a
diagnosis step a type error would have skipped.

**Why the signal was invisible, and what fixed it.** Two new errors in a
190-error report cannot be seen by reading. The recorded justification for that
baseline -- the errors concentrate at the decode boundary W04 will change -- turned
out to be measurably wrong: of 144 errors, **41 are at the decode boundary and 103
are not**, with the largest non-decode clusters in modules no item owns. The
baseline was carrying unrelated debt under a related item's name.

Three things followed. Annotations were completed: every function has a return
type, every argument has one, and `Any` appears explicitly where a value genuinely
is unconstrained -- which cut the `--disallow-untyped-defs` gap from **+85 to
+10**. One explicit `Any` on the heterogeneous env-value table removed **50**
spurious errors, because the inferred `int | str | None` made a `Path` division
report as a `str` operand fault; the general rule is that `Any` at a deliberately
heterogeneous boundary is documentation, while `Any` threaded onward is an escape.
And `tools/quality_report.py` now compares against a recorded ceiling in
`schema/quality-baseline.json` and **fails when a count rises**, which is the same
distinction the workload harness makes between recording a timing and reporting
whether it regressed. Verified by injecting a type error: 145 against a ceiling of
144 exits non-zero and names the section.

**Fixing the unrelated share found a live bug and two more shadowings.** The count
fell from 190 to **107** by repair rather than reclassification, and the work
surfaced what a 190-error report had been hiding:

- `codess baseline freeze` passed `repo_root=` to a callee taking
  `catalog_base=`, so **every invocation raised `TypeError`**. The value was wrong
  too: `catalog_base` is the selection document's own directory, and resolving a
  relative `policy` against the checkout is exactly what moving the catalog out of
  it undid. The library function was well tested and the one-line handler was not,
  which is how a wrong keyword survived; two tests now compare the keywords passed
  against the callee's signature, needing no valid selection document to do it.
- `retention` bound `references` to a `set[str]` from a tuple unpack and rebound
  it to a reference *report* in the same function -- the third instance of the
  rebinding pattern. `ingest_cmd` did the same with `resolved`, a request tuple
  rebound to a `Profile`: the fourth.
- `sys.exc_info()[0]` was called twice, once to guard and once to access, so the
  guard narrowed nothing for a reader or a checker -- and the two calls need not
  agree.

**A `TypedDict` is free where the constructor is not.** Typing
`refresh_operations`' nine-argument kwargs bag took it from 12 errors to zero.
Measured: an annotated literal is a plain dict at 47 ns, while `Args(a=1, b='x')`
costs 120 ns, and `type()` returns `dict` either way. So the annotation form costs
nothing and the constructor form costs 2.5x -- which is the distinction to apply
to the `opts` and `settings` bags that carry most of what remains.

**No lint rule catches the shadowing class.** Tested against every ruff family:
`A002` catches a parameter shadowing a *builtin* and nothing catches one shadowing
a module-level name in the same file. `A` is now selected -- it reports zero today,
which is the argument for locking it in -- and the naming rule that prevents the
rest is stated in `pyproject.toml` and enforced by mypy.

What remains is a decision rather than effort, tracked as W64: which strict flags
to enable, where `Any` is honest, and where a `TypedDict` pays.

### 4.17 The Shadowing Pattern: Four Cases, One Cause

Four name collisions were found in one session. Rather than fix each and move on,
here is where each came from, how long each name was live, and what the four have
in common -- because the recurrence is the finding, not the individual defects.

| Case | Origin | Live bug? | Detected by |
|---|---|---|---|
| `retention.references` -- a `set[str]` rebound to a reference report | **Pre-existing**, committed | No | mypy only |
| `ingest_cmd.roots` -- a `list[Path]` rebound to a redaction-root dict | **Introduced this session** | **Yes** -- aborted every ingest | tests, then mypy |
| `reporting.emit_named(event=...)` -- parameter over module function | **Introduced this session** | **Yes** -- `TypeError` on every call | tests, then mypy |
| `ingest_cmd.resolved` -- a request tuple rebound to a `Profile` | **Introduced this session** on a pre-existing name | **Yes** -- `AttributeError` | tests, then mypy |
| `admin_cmd.name` -- a subparser named after the `--name` option it declares | **Pre-existing**, committed | No | mypy only |

**The two pre-existing cases were harmless and the three new ones were not**, and
the difference is instructive. `retention.references` binds at line 260, is
consumed at 263 inside the loop, and is rebound at 280 -- so the first value is
dead before the second exists. It cost readability and a type check, not
behaviour. The three introduced cases each rebound a name whose first value was
still needed later.

**The structural cause is long functions with a single trailing return.**
`build_retention_plan` is 111 lines with one `return` at the end;
`ingest_cmd.run` is longer. In a function that shape, every local lives from its
binding to the end of the function whether or not it is still wanted, so the
namespace fills with names whose useful lifetime ended long before their scope
did. A reader adding code near the bottom sees a name that "looks free" because
its last *use* is 40 lines above, and Python's rebinding semantics oblige.

That is the relationship to return placement you would expect and it holds here:
a function with early returns has shorter effective lifetimes and fewer names
simultaneously live. None of these collisions could occur in a function short
enough to read at once, which is the argument for the decomposition items rather
than a separate naming item.

**No lint rule catches this class.** Tested against every ruff family: `A002`
reports a parameter shadowing a *builtin*, and nothing reports one shadowing a
module-level name in the same file. mypy reports all four precisely. The tests
caught the three live ones -- as an `AttributeError` or `TypeError` several frames
from the cause, costing a diagnosis step a type error skips.

**What changed as a result.** `A` is selected in ruff (zero findings, so it locks
the property in). The three naming rules are in CLAUDE.md, which had no code
naming section at all -- it covered Markdown, comments, and voice, which is why
the convention lived nowhere. And rule 3 is measured rather than preferred:
across 6,310 installed third-party files, role qualifiers outnumber PEP 8's
trailing underscore 4,977 to 109, with 1,444 files shadowing a builtin outright.

### 4.18 Parameter Groups That Were Structures

Surveyed every signature in `src/`: **787 functions take parameters, 80 take five
or more, 18 take eight or more**, and the largest takes 19. Count alone does not
identify a structure, so the survey looked for parameter *name-sets that recur
across functions* -- a group passed together repeatedly is a shape nobody named.

Two clusters dominate, and both were previously recorded in a task-list row that
was lost when that item closed. Rediscovering them independently is the argument
for putting the analysis somewhere durable:

| Cluster | Members | Functions carrying the complete set |
|---|---|---|
| Run invocation | `registry`, `repo_root`, `resource_policy`, `raw_mode`, `source` | 5 of 7 |
| Record context | `session_id`, `source_file`, `line_num`, `opts` | 4 of 7 |

**A count of five parameters is not the finding; what they are is.** Separating
the 80 large signatures by what they *do* with their arguments gives two
populations that want opposite treatment:

- **Builders** place their parameters into a returned literal --
  `codex._base_event` (19 parameters, all 19 into the dict), `query_api.make_request`
  (13 of 13). The parameter list *is* the record's shape, and collapsing it into an
  object would name the same fields twice.
- **Relays** forward their parameters to another call --
  `review_project.refresh_candidates` (10 of 14 forwarded),
  `baseline_operations.apply_project` (10 of 12), `ingest_cmd._ingest_project`
  (10 of 10). These are the struct candidates, because a relay's parameters exist
  only to reach somewhere else.

**The run-invocation cluster is now `ChildInvocation`.** It was the strongest case:
the five parameters are exactly the argv that `baseline_operations`,
`catalog_operations`, and `refresh_operations` each built by hand. All three spelled
`--source`, `--raw-mode`, `--registry`, and `--min-size` into their own list and
each decided independently whether to add `--no-progress`, `--validate`, `--force`,
or `--candidate-snapshot`, so a flag renamed at the CLI reached all three only if
someone edited each. Measured: **three argv builders and three `PYTHONPATH` setups
became one**, verified against a real child run.

**Two effects worth separating.** The duplication is gone and a test now fails if
a fourth builder appears. The *parameter counts are unchanged*, because the callers
still receive those values in order to construct the invocation -- so this removed
a correctness hazard (three specifications of one command line) without shortening
a signature. Claiming otherwise would overstate it.

**A consolidation also collapsed a test's patch points.** The resource-policy test
patched `subprocess.run` in two modules; it now patches one. That is the same
property in test form: three places to keep in step became one, and the test that
would have caught drift could not, because it was written per module.

**The record-context cluster is not consolidated**, and deliberately: it changes
adapter signatures, which is the decode-boundary work W04 owns. Doing it now would
rewrite the same signatures twice.

## 5. Real-Source Validation

The automated suite runs on fixtures. This records a validation pass over
actual vendor data, which is the separate layer 13.1 names. It ran in
preflight mode, so it read live vendor stores and wrote nothing outside a
temporary directory.

Projects are identified by shape rather than by name: the name is a private
repository on the development machine and is not checkable by a reader, while
the vendor, scale, and layout are what the pass establishes.

| Project | Vendors | Sessions | Events | Shape under test |
|---|---|---|---|---|
| A | Claude Code | 406 | 32,059 | Large single-vendor |
| B | Claude Code | 25 | 22,692 | Mid single-vendor |
| C | Claude Code | 5 | 4,171 | Mid single-vendor |
| D | Claude Code | 1 | 3,594 | Small, one long Session |
| E | Claude Code | 2 | 1,440 | Small single-vendor |
| F | Claude Code | 2 | 3,169 | Small single-vendor |
| G | Codex | 1 | 416 | Small single-vendor |
| H | Codex | 1 | 1,230 | Small, nested layout |
| I | Codex | 1 | 166 | Smallest observed |
| J | Cursor | 47 | 27,513 | Large single-vendor |
| K | Cursor | 1 | 857 | Small, separate work root |
| L | Cursor | 1 | 667 | Small, separate work root |
| M | Codex, Cursor | 4 | 35,758 | Multi-vendor |

**No retained Session format is old enough to warrant skipping.** The
question is worth asking before adding a version gate, so the locally
retained corpus was surveyed rather than assumed.

| Source system | Versions observed | Envelope drift | Oldest decode |
|---|---|---|---|
| Claude Code | 21 releases, all `2.1.x` | None; `user`, `assistant`, `attachment`, `system` appear across every version | Clean |
| Codex | 17 releases, `0.58.0` through `0.145.0` | None; `session_meta`, `response_item`, `event_msg`, `turn_context` in all of them | 309 Events, no failures |
| Cursor | Not versioned per record | None; every sampled bubble carries `text`, with `richText` on user turns only | Clean |

Every Claude Code file carries a `version`, so none is unversioned. The
oldest Codex rollout in the corpus is roughly nine months old and decodes
without error. The only shape difference found across the whole range is
`world_state`, which appears from Codex 0.144 and is already handled.

Two conclusions. First, a version gate would currently exclude nothing and
would add a failure mode -- a version string the gate does not recognize --
in exchange for no benefit. Second, the property that makes this safe is not
that vendors have kept formats stable, but that unknown records are counted
rather than assumed: an unrecognized shape becomes an `unsupported_records`
diagnostic, so a format change appears as a number to investigate instead of
as silently missing data. That is the mechanism to preserve; a skip list
would replace it with a guess about which versions matter.

If a genuinely incompatible format does appear, the evidence will be a rise
in `unsupported_records` for a specific source system, which is the signal
coverage reporting exists to surface.

**Two discovery defects were found and fixed during this validation.** Both
made a scan's result depend on how it was invoked rather than on what was
present.

The recency window omitted Projects silently. `CODESS_DAYS` defaulted to 90,
so a Project whose last Session predated that window produced no row and no
message -- indistinguishable from a directory with no coding work. The
default is now one year. The window exists to keep an incremental rescan
cheap, not to decide what is worth ingesting -- for routine use of coding
tools, 90 days omits most of a Project's history on the first ingest, which
is when the complete record is most wanted. Omissions are now reported with
the flag that widens them.

`--debug` disabled the window entirely, so diagnostic output described a
different selection than an ordinary run. Anything a reader was shown while
debugging could not be reproduced without it. Recency is a selection, not a
diagnostic; `--days 0` is the way to widen it. A regression test asserts the
two runs list the same Projects.

**Discovered inventory.** Scanning the home directory with an all-time
window finds 24 Projects holding retained coding work, 476 Sessions, and
about 1.6 GB of vendor data. Listed rather than summarized, because which
Projects exist is the point:

Projects are labelled by container and shape rather than by name, since the
names are private repositories: what the inventory establishes is the
distribution of vendors, scales, and layouts a discovery pass must handle.

| Project | Vendors | Sessions | MB |
|---|---|---|---|
| `<C1>/p01` | CC, Cursor | 31 | 736 |
| `<C1>/p02` | Cursor | 47 | 196 |
| `<C2>/p03` | Codex, Cursor | 4 | 179 |
| `<C3>/p04` | CC, Codex | 6 | 162 |
| `<C1>/p05` | CC, Cursor | 6 | 77 |
| `<C3>/p06` | CC | 343 | 72 |
| `<C4>/p07` | Codex | 3 | 47 |
| `<C5>/p08` | Codex | 1 | 46 |
| `<C2>/p09` | CC | 5 | 15 |
| `<C1>/p10` | CC | 1 | 8 |
| `<C3>/p11` | CC | 1 | 7 |
| `<C6>/p12` | Cursor | 1 | 6 |
| `<C3>/p13` | CC | 3 | 3 |
| `<C1>/p14` | Codex | 1 | 3 |
| `<C7>/p15` | Cursor | 1 | 3 |
| `<C3>/p16` | Codex | 1 | 2 |
| `<C7>/p17` | Cursor | 1 | 2 |
| `<C4>/p18` | Codex | 1 | 1 |
| `<C3>/p19` | Codex | 1 | 0.6 |
| `<C4>/p20` | Codex | 1 | 0.2 |
| `<C2>/p21` | Cursor | 0 | 0.1 |
| `<C4>/p22`, `<C4>/p22/python`, `<C4>/p23` | CC | 0 | -- |
| `~/<tool-workspace>` | Codex | 1 | 0.1 |
| `~/.codex` | Codex | 1 | 0.03 |

The last two are not repositories. They are tool working directories that
accumulated Sessions because work happened while the current directory was
one of them. They are correctly discovered, and worth keeping in the corpus:
a Project boundary tested only against clean repositories is not being
tested. `<C4>/p22/python` is a repository nested inside another repository,
which is the case 6's boundary rules exist for.

**`<C1>` is large because it is a container, not a Project.** It holds
eighteen directories, of which five have retained coding work; the rest are
papers, test scratch, and archives. One of them -- call it `<C1>/<archive>` --
contains 68 nested repositories and is listed in `EXCLUDE_REVIEW_DIRS` as a
review tree.

That exclusion was root-dependent and is now fixed. `EXCLUDE_REVIEW_DIRS`
entries were matched as a prefix of the path relative to the scan root, so
`<C1>/<archive>` matched when scanning `~/Work` and `Work/<C1>/<archive>` did
not match when scanning `~`. The same directory was therefore excluded or
included depending on where the scan started, which is why an earlier
inventory listed it with 15 Sessions. Matching is now on path segments, so
exclusion is a property of the directory rather than of the invocation.

**Roots and aggregators.** `AGGREGATORS` names directories that group
Projects rather than being Projects -- the seven containers `<C1>` to `<C7>`
above. A directory named in that set is never reported as a Project itself;
its children are. This is why `Work/<C1>` never appears as a row while
`<C1>/p01` does, and why scanning `~/Work` and `~` produce the same Projects
under different labels.

Both `AGGREGATORS` and `EXCLUDE_REVIEW_DIRS` are hardcoded in `config.py`
and specific to one developer's layout. Neither is configurable, and
neither is documented outside the source. That is a limitation worth
recording: another user's aggregator directories would be reported as
Projects, and their review trees would be scanned.

All thirteen Projects reported `accepted` with zero errors, and every store passed
`PRAGMA integrity_check` with no foreign-key violations. Decode depth was
checked rather than assumed: Cursor produced 12,183 tool invocations against
12,186 results, Claude Code 6,427 against 6,424, and Codex 394 against 394,
so call and result linkage holds across all three vendors. Every Project
with locally retained sessions was covered; none was excluded for failing.

Three observations were followed to their source rather than left as
summary figures.

`<C2>/p03` decoded its Codex sessions but produced no Cursor sessions,
despite discovery reporting Cursor evidence for that Project. Reading the
vendor storage directly confirms the decision: the attributed workspace
database has an empty `cursorDiskKV` table, and no composer in the global
store references the Project. The workspace was opened in Cursor without a
conversation being persisted, so there is nothing to decode. The progress
record already said this -- `reason=no-bubble-rows` -- and the check
confirms the skip is correct rather than a selection defect.

`<C3>/p06` reported 7,077 Events with no time, which is not an older storage
format and is not specific to that Project. The records are all
`product_state`, and reading the raw Claude Code JSONL shows the vendor
format itself splits into two groups:

| Vendor record | Carries a timestamp | Fields |
|---|---|---|
| `attachment` | Yes, always | Full envelope: `uuid`, `parentUuid`, `cwd`, `gitBranch`, `version`, `sessionId` |
| `queue-operation` | Yes, always | `operation`, `content`, `timestamp`, `sessionId` |
| `ai-title` | No | `aiTitle`, `sessionId`, `type` |
| `last-prompt` | No | `lastPrompt`, `leafUuid`, `sessionId`, `type` |
| `mode`, `permission-mode` | No | The value, `sessionId`, `type` |
| `custom-title` | No | `customTitle`, `sessionId`, `type` |
| `file-history-snapshot` | No | `snapshot`, `messageId`, `isSnapshotUpdate` |

The distinction is what the record *is*. Timestamped records describe an
event that happened at a moment -- a queued prompt, an attachment delivered
with a turn. The others record current state: the session's title, its mode,
the last prompt text. Claude Code overwrites them as state changes and never
stamps them, so there is no moment to record.

This is why every Claude Code Project shows the pattern -- eleven of eleven
observed, roughly 16,700 such records in total -- rather than it being a
property of one Project's age. `product_state` Events that *do* carry a time
are the `attachment` and `queue-operation` kinds mapped into the same
`event_type`, which is consistent rather than contradictory.

The decode is therefore correct, and the "missing" count is better read as a
measurement of how much of a Session is state rather than activity. What is
worth reconsidering under W01 is the grouping: mapping records with
fundamentally different time semantics into one `event_type` makes a
null-timestamp count look like a gap when it is a category.

`jsonschema` reported 58 tool results against 55 invocations. Reading the
Codex rollout accounts for the difference exactly, and the source itself is
balanced:

| Source records | Count | Produces |
|---|---|---|
| `function_call` | 53 | 53 invocations |
| `function_call_output` | 53 | 53 results |
| `patch_apply_end` | 4 | 4 results, reusing the `call_` id of an existing invocation |
| `web_search_end` | 1 | 1 result, and one further invocation from its distinct `ws_` id |

Codex reports some tool activity twice: once as a request/response pair in
the conversation stream, and again as an event-stream record describing what
the harness did. `patch_apply_end` carries the same `call_id` as its
originating `function_call`, so the store's upsert merges it into that
invocation and adds a second result -- one call, two results, which is the
honest representation of two source records describing one operation.
`web_search_end` carries a `ws_`-prefixed id that matches no `function_call`,
so it creates its own invocation.

So the answer to "more found than looked at" is neither: nothing is missing
and nothing is invented. Every result corresponds to a retained source
record, and the count exceeds the invocation count because Codex emits more
result-shaped records than call-shaped ones.

**All three numbers are correct, and each answers a different question.**
They should be separately recoverable rather than reconciled into one:

| Count | Question it answers | Where it lives |
|---|---|---|
| 53 | How many tool calls did the model make? | Invocations whose evidence includes a request record |
| 55 | How many distinct tool operations does the store hold? | `COUNT(*) FROM tool_invocations` |
| 58 | How many result records did the vendor write? | `COUNT(*) FROM tool_results` |

Collapsing them would lose real information. Reporting only 53 hides the
web search, which happened. Reporting only 58 implies more operations than
occurred. Reporting only 55 conceals that four operations were described
twice, which is exactly the evidence a reader needs when a patch application
reports both a model-visible result and a harness-observed outcome.

The distinction is already recoverable from stored data, so this is a
reporting gap rather than a decode one. `events.source_record_type` retains
the vendor shape -- `response_item` for the conversation stream, `event_msg`
for the harness event stream -- and a Codex store shows both
(`{'response_item': 94, 'event_msg': 49}` in one observed Project). What is
missing is that `tool_invocations.invocation_kind` is written as the
constant `"harness_capability"` for every row, so the column that should
carry this distinction currently carries nothing.

Two changes follow, both belonging to W02. Populate `invocation_kind` from
the evidence actually present -- a request-and-response pair, a
harness-observed operation, or both -- so the 53 is derivable rather than
inferred. And have tool reporting state the pair rather than one number,
since "55 operations, 58 result records" is accurate where either alone
invites a wrong conclusion.

**A published pass, one Project per vendor.** The run above was preflight,
so it never exercised publication. A second pass ingested and published one
peripheral Project for each source system, which is what lets the stored
result be queried rather than only counted:

| Vendor | Project | Sessions | Events |
|---|---|---|---|
| Claude Code | `<C3>/p06` | 353 | 28,772 |
| Codex | `<C2>/p03` | 4 | 35,758 |
| Cursor | `<C1>/p05` | 4 | 16,095 |

`tools/decode_audit.py` reports the classification distributions, the
pairings that must not co-occur, and tool and model linkage over a published
store set. It reports counts, classifications, and record shapes only, never
message, argument, or result content, so a finding can be acted on without
reproducing what a Session said.

*W01 result: no inconsistency in 80,625 Events.* Every Event carries an
Actor kind, content role, and origin kind -- no nulls in any of the three
vocabularies, in any vendor. None of the four contradictions the audit
checks for occurs: no tool Actor without a tool role, no model Actor holding
a tool result, no direct user input from a non-human Actor, no
model-generated content from a non-model Actor.

One pairing the audit initially flagged was the audit's error rather than
the decoder's: eleven Claude Events pair a human Actor with a `command`
role, which is correct -- a human invoking a slash command is neither a
prompt nor a tool. The check now expects it.

*W02 result: one unsupported record type, and two honest gaps.* The Claude
ingest reported 44 unsupported records, and reading the source accounts for
all 44 exactly: `file-history-delta` is a record type the adapter does not
recognize, although its sibling `file-history-snapshot` is handled. That is
a decode gap to close under W02, and the count matching exactly is what
makes it actionable rather than a suspicion.

The other two are the decoder declining to invent, and should not be
"fixed". Codex leaves 12,140 of 14,551 tool results without a normalized
status because the source records none; Cursor attaches a model
configuration to 11 of 70 Model Turns because only some bubbles carry
`modelInfo`. In both cases the alternative would be inferring a value the
vendor did not record, which 10.1 forbids. They are reportable as coverage
(coverage reporting) rather than repairable as decode.

Tool linkage is complete in all three vendors: every result joins the
invocation it belongs to, with none unlinked. That is the pairing the
`invocation_kind` finding above concerns, and it holds at this scale.

**Widened to every local Project.** The three-Project pass was then extended
to all seventeen real Projects the machine holds, excluding only CodeSess
itself and the two used above: **142,470 Events across 17 published store
sets, with zero classification inconsistencies.** The set deliberately
includes awkward roots -- `~/.codex` and `~/.openclaw-repo/workspace` are
themselves Projects with Sessions -- and every ingest completed without
error.

`file-history-delta` is now decoded. It is harness product state like its
snapshot sibling, retaining the message and snapshot identifiers it links
through and the backup version, but recording the tracked path as presence
rather than a second copy of a locator held elsewhere. Re-ingesting the
Project that surfaced it moved unsupported records from 44 to 0 and raised
the Event count by exactly 44, which is the confirmation that the records
are decoded rather than dropped.

*A second, different unsupported count, now closed.* The wider sweep
reported 48 unsupported records in one Project, and they were not the same
shape: user messages whose content is entirely image blocks -- a human
pasting a screenshot with no accompanying text. `normalize_user` produced no
Event for them, so the prompt existed in the Session and not in the store.

The shape is narrow and was measured before acting: 48 records carrying 107
image blocks, all `image/jpeg`, all base64, 19.8 MB of payload, confined to
one Project, and no record anywhere mixes an image with text. They now
decode as human-Actor prompt Events with subtype `attachment`, following the
`attachment` record's established treatment in the same adapter -- the media
type, source encoding, and encoded length are retained; the payload is not.
One Event per image block, so a record carrying seven screenshots reports
seven. Re-ingesting moved that Project's unsupported records from 48 to 0
and raised its Event count by exactly 107.

This does change what counts as a prompt, and a Session's prompt count rises
accordingly. That is the correct direction: the alternative was a store that
reported no prompt where a human had sent one. **A manual review is
outstanding and deliberately unscheduled**: a sample of the 48 should be read
against its source Session to confirm the classification reads correctly in
context, since only the decode is verified so far and not the judgment behind
it.

*Compaction and agent relations are now measured rather than asserted.* Both
were exercised by fixtures with no real-source check. `tools/decode_audit.py`
reports them, and running it found one defect immediately: Cursor marked two
Sessions `subagent` with no `parent_session_id`, so the relation asserted a
parent the store never named. The source records it -- `subagentInfo` in the
Composer header's JSON `value` carries `parentComposerId`,
`rootParentConversationId`, `subagentTypeName`, and the `toolCallId` that
spawned it -- and Codess read only the `isSubagent` flag, discarding the
rest. It now reads the lineage, and the relation and its parent travel
together.

Four invariants were added to the audit and hold across every Project: a
relation names a parent, a parent states a relation, no Session is its own
parent, and `invocation_kind` never disagrees with the evidence it is derived
from. Over 142,470 Events: 240 compactions, 7 rollbacks, 13 injections, 27
related Sessions (23 subagent, 4 fork), zero inconsistencies.

*`invocation_kind` now carries the distinction it exists for.* It was
written as the constant `harness_capability` on every row. The evidence to
derive it was already present and unused: `requested_event_id` is set only
when the Event is a `tool_call`, so an invocation with one rests on a model
request and an invocation without one is an operation the harness performed
and reported. The column is now `model_requested` or `harness_observed`
accordingly.

The upsert can see a result before its request, so the value is promoted
when the request arrives and never demoted -- absence of evidence at one
moment is not evidence of absence once the pair completes. Across all
seventeen Projects the split is 41,712 model-requested against 800
harness-observed, and no row disagrees with the evidence it was derived
from. The three counts 13.4.9 distinguishes are now separately answerable:
`invocation_kind='model_requested'` for calls the model made, all
`tool_invocations` for operations the store holds, and `tool_results` for
records the vendor wrote.

**Status: Postponed.** The test layout matches the intended validation
layers, but file names alone do not prove architectural compliance. Every
check below is nonetheless a consequence of work that is itself incomplete,
so building the enforcement first would fix the current structure in place
and require rework as those items land. Each is therefore recorded against
its owning item and revisited when that item completes, rather than tracked
as separate work:

| Mechanical check | Owning item |
|---|---|
| Import-boundary test for adapter, source, store, query, and CLI layers | W13; a module-level import-cycle count has a defensible expected value of zero and is the cheapest half (experiments/structural-analysis-tools.md) |
| SQL-ownership check recognizing the narrow focused-audit exception | W13; W06 and W26 have supplied the boundary, so every module holding SQL is now a source-access, query, or store module |
| Module-level import-cycle count, expected zero | W13; measured at zero today, with all 15 apparent cycles running through deliberate deferred imports (experiments/structural-analysis-tools.md) |
| Mapping-profile conformance over every emitted adapter fixture | W04 |
| Query-request vectors covering every rejection path, with a check that no path lacks a vector | W13 (13.4.2) |
| Transaction-failure tests at each source replacement and publication edge | Unowned: W03 and W20 both closed, so the publication identity these would test is settled and the check can be built |
| Subprocess-aware coverage for scan and ingest, keeping installed CLI integration tests | W13 |
| Operational-event contract, channel-separation, privacy, and error-boundary tests | Satisfied: `tests/test_reporting.py` and `tests/test_progress.py`, with stdout verified byte-identical across profiles |
| Small real-Source validation per changed vendor decoder, extended to a multi-vendor Project only when common classification or query behavior changes | Satisfied: 17 Projects, 142,363 Events (5) |

Coverage percentage is supporting evidence, not an acceptance criterion by
itself. Completion depends on the named failure, boundary, and use case being
exercised with the expected normalized identities and results.
