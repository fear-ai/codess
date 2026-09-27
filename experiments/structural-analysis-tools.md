# Structural Analysis Beyond Ruff

Ruff answers whether a line is correct. It does not answer whether a
function is too large to reason about, whether two modules say the same
thing twice, or whether the dependency direction the architecture claims is
the one the imports actually take. This records which Ruff rules do carry
structural signal, what four other tools reported when run against the
codebase, and what each finding was worth.

The experiment is retained because the *method* transfers, not because the
counts do: they will be stale by the next change.

## 1. Ruff Rules That Indicate Shape

Selecting these does not require adopting them as gates. Their value is as a
measurement of where structure is degrading. They fall into four categories
by what a finding actually tells you.

### 1.1 Decomposition: one function doing several jobs

| Rule | Count | What it measures |
|---|---|---|
| `C901` | 66 | Cyclomatic complexity -- independent paths through one function |
| `PLR0912` | 44 | Branch count |
| `PLR0915` | 39 | Statement count |
| `PLR0911` | 14 | Return count |

These overlap deliberately: a function can be long without branching, or
branch heavily in few lines, and the combination locates the shape.

- `ingest_cmd.run` -- **56 branches**, 114 complexity. One function
  resolving configuration, selecting Projects, ingesting three vendors, and
  publishing. The command-layer extraction has been reducing it for several increments.
- `query_cmd.run` -- **39 branches, 31 returns**. The return count is the
  sharper signal: it is a dispatch written as a chain of `if ...: return`,
  where a table mapping a flag to a handler would be one branch.
- `query_cmd._typed_output` -- 39 branches, complexity 72. Renders every
  output format for every action in one body.
- `walk_sessions` -- complexity 99 in a 596-line module, which is section 3.

### 1.2 Interface: a function assembled from its callers' state

| Rule | Count | What it measures |
|---|---|---|
| `PLR0913` | 45 | Parameter count |

The count is a proxy for a missing subject. A function taking fifteen
arguments has no object it acts on; it has a pile of values its caller
happened to hold.

- `ingest_cmd._print_preflight_report` -- **15 parameters**. It renders one
  report from settings, roots, sources, staging, progress, options,
  diagnostics, and an outcome, none of which it owns.
- `ingest_cmd._publish_project` -- 9 parameters, which 13.4.1 predicted: the
  publication phase needed a configuration object and got a signature.

This is the rule most worth reading rather than fixing. Some long signatures
are correct -- a function with genuinely independent inputs -- and the
remedy for the rest is a type, which is a design change rather than a
refactor.

### 1.3 Coupling: a boundary being crossed

| Rule | Count | What it measures |
|---|---|---|
| `PLC0415` | 31 | Import inside a function |
| `SLF001` | 1 | Private member accessed from another module |
| `TID252` | 0 | Relative import beyond the intended depth |

- `PLC0415` at `ingest_cmd:135` and `admin_cmd:656` are deferred imports,
  and section 5 shows why: **every one of the 15 import cycles runs through
  one.** The rule is reporting the mechanism that keeps the layering intact,
  not a lapse.
- `SLF001` has one instance: `adapters/cc` reading `field_state._MISSING`, a
  sentinel that arguably belongs in that module's public surface.

### 1.4 Concealed decisions: a literal standing in for a name

| Rule | Count | What it measures |
|---|---|---|
| `PLR2004` | 36 | Magic value in a comparison |
| `ARG` | 4 | Argument accepted and ignored |

`PLR2004` is the rule with the worst signal-to-noise here, which is why it
is measured but not selected: most instances compare against `0`, `1`, or
`2`, where naming the value would add indirection without adding meaning --
the same judgment 3.5.3 records for constants. It is worth re-reading when
a threshold is involved rather than a count.

## 2. Dead Code (`vulture`)

Nothing at 80% confidence. At 60% -- which reports module-private names a
static reader cannot prove unused -- 32 findings, of which **nine were real
and were removed**. Two were refactor residue: `_source_predicate` and
`_limited` in `cli.query_cmd`.

Both were residue from the report-SQL extraction. Their callers moved to `query_reports`
and the originals stayed behind, called by nothing. The suite passed
throughout, because a function nothing calls breaks nothing.

That is the class this tool is for, and it is the same class that found
`store.replace_source_sessions` earlier by hand (3.5.4): code kept alive by
a test, or by nothing at all, after the thing that used it moved. Worth
running after any extraction.

**Seven more had no consumer anywhere** -- not in `src/`, not in tests, not
in tools -- and were removed: `codex_source.read_session_meta` (superseded by
`get_session_meta`), `project_catalog.register_relocation` (superseded by
`catalog_operations.relocate_project`), `vendor_audits.extract_setting_values`,
`config.DEFAULT_AUDIT_MAX_FILES`, `hashing.DEFAULT_CHUNK_BYTES` (a duplicate
of `config.HASH_CHUNK_BYTES`), and `config.BKB`/`BGB` -- the last of which was
the wrong call, see below.

### 2.1 Four Causes, Which Want Four Different Responses

The report is one list, but the findings are not one kind. Classifying each
by *why* it is unreferenced decides what to do with it, and only the first
class is simply deletable:

| Cause | Example | Response |
|---|---|---|
| **Leftover remnant** -- what used it moved | `query_cmd._source_predicate`, `_limited`; `store.replace_source_sessions` | Delete. The suite passes either way, which is why these survive |
| **Redefined elsewhere** -- a second copy exists | `project.path_to_slug`/`slug_to_path`, duplicating `helpers` | Consolidate onto one, after checking which is correct -- see section 4 |
| **Complementary but unused** -- one half of a symmetric set | `config.BKB`/`BGB` | Keep and isolate. Deleting half a set invites the next caller to inline the operation |
| **Should be used but is not** -- built for a boundary that has not been wired | `schema_contract.validate_mapped_event`, `validate_mapping` | Neither delete nor ignore: this is an open work item, and the tool is reporting the gap |

The fourth class is the one worth reading the list for. `validate_mapped_event`
exists, is exercised by four test modules, and is called from no production
path -- which is precisely 13.4.2's finding that "`validate_mapped_event` is
not a common ingest boundary", tracked as the **candidate-contract item**. A dead-code report and an
open architectural item pointed at the same function from opposite
directions.

**`field_state.coarse` and `is_vacant` were misfiled here, and were removed.**
The first reading placed them in the third class -- the vocabulary's own
predicates, named in the module docstring, so a field-state module lacking
"is this vacant" looked like it was missing an obvious member. Mapping the
module's actual consumers refuted that. Of eleven functions, `attach` (15
call sites), `get_state` (12), `compare`, `criticality`, and `diagnose` are
used by the three adapters and `acceptance`; `coarse` and `is_vacant` are
used by nothing.

Neither is the missing half of anything. `is_vacant(state)` is exactly
`state in VACANT_STATES`, a one-line wrapper over a constant the module
already exports, and `compare` performs the equivalent test inline.
`coarse` collapses six states to three, a collapse no caller wants:
`diagnostic_level` already collapses to info/warn/None and `criticality` to
fatal/advisory/None, and those are the two the consumers use.

The distinction from `BKB`/`BGB` is what the third class actually requires.
An inverse converter is re-derived inline by the next caller if it is
missing, so its absence causes duplication. A membership test over an
exported frozenset is not: the constant is public, and the test is the
expression. The test asserting the umbrella's contents was kept and now
asserts it of `VACANT_STATES` directly, which is where the property lives.

**The `BKB`/`BGB` correction.** Deleting them was wrong. They are the inverse
half of a converter set whose forward half is used, and an incomplete set
invites the next caller to write `/ 1024` inline -- which is how one
conversion acquires several spellings. The right change was **isolation**:
all six now live in `codess/units.py`, which owns the conversion, with
`config` re-exporting them because callers have long imported from there. A
tool that reports an asymmetry has not thereby said which side to remove.

The remaining findings are correct to leave: `row_factory` assignments,
`console_main` (a packaging entry point resolved by name), the
`codess_check_*` family (contract surface), and `publication` (a property
with sixteen source references the tool cannot see through).

### 2.2 Counting Callers, Not Text Matches

An earlier pass through this list counted a grep hit as a use, which is wrong
in three ways that all inflate the count toward "still used":

- **A name appears in its own module's docstring.** `field_state.coarse` and
  `is_vacant` are each named in the module docstring that lists the
  vocabulary's predicates, so a text search finds two hits -- the docstring
  line and the `def` -- for a function with no caller at all.
- **A name appears in a comment explaining an adjacent decision.**
  `fileio.rewrite_hash` has exactly two source references: its own docstring
  and a comment in `project.parse_and_run` explaining why the CLI sets an
  environment variable. Production callers: zero.
- **The definition counts itself.** Any search for a symbol matches its
  `def` or assignment.

The rule this experiment settles on: **count call sites, excluding the
definition, docstrings, comments, and the module's own prose.** Where that
count is zero, the next question is which of section 2.1's four causes
applies -- not whether to delete. `console_main` has zero call sites in
`src/`, `tools/`, and `tests/`, and is correct to keep, because
`pyproject.toml` resolves it by name as the `codess` entry point and no
static tool follows that edge.

Tests are counted separately for the same reason. `coarse`, `is_vacant`, and
`rebuild_manifest` each have three to five test references and zero
production callers, which is the signal that separates section 2.1's fourth
class -- built for a boundary not yet wired -- from a genuine remnant.

### 2.3 The Six Decisions

Rerunning `vulture` after this pass leaves 21 findings, of which fifteen are
already explained -- `console_main` (a packaging entry point resolved by
name), `publication` (a property with fourteen real references the tool
cannot see through), the `codess_check_*` family (contract surface), seven
`row_factory` assignments, and `validate_mapped_event`/`validate_mapping`
(the unwired candidate boundary). Six needed a decision, and applying 2.1's causes
gives four different answers:

| Finding | Cause | Decision |
|---|---|---|
| `PROJECT_SCOPED_OPTIONS` | 4 -- built but not wired | **Fixed.** `_begin_project` assigned its seven keys by hand beside a seven-element tuple nothing read, so the two could drift; a test asserted they agreed by parsing the function's AST. The function now builds against the tuple and raises when a declared key has no fresh value, and the AST test is replaced by a behavioural one that adds a key and expects the refusal. |
| `get_selection_marker` | 2 -- redefined elsewhere | **Removed.** A thin singular wrapper over `get_selection_markers`, called only by tests. Tests redirected to the plural function. |
| `get_composer_data` (+ `read_composer_data`) | 1 -- leftover remnant | **Recommend removal, not yet applied.** Exploratory shape-discovery from the original Cursor investigation, whose output fields (`top_keys`, `has_conversation`, `value_null`) appear nowhere else. Production decoding went a different way, through `iter_bubble_rows` and key ranges. The pair is one decision: `read_composer_data`'s only caller is `get_composer_data`. If the question returns, `tools/audit_cursor_features.py` is where it belongs. |
| `VACANT_STATES` | 3 -- complementary | **Keep.** Exported vocabulary, named in the module docstring, and the constant that `is_vacant` wrapped before it was removed -- callers test membership directly. Unlike `is_vacant`, the constant is the thing, not a wrapper over it. |
| `rewrite_hash` | 4 -- built but not wired | **Keep, and record why.** It is the read-modify-write guard for pointer and manifest documents: verify the old hash, transform, write atomically. Every current caller either reads (`read_hash`) or writes (`write_hash`) but never both, so the guard has no caller yet. Deleting it would leave the next read-then-write to hand-roll the check, which is the failure it exists to prevent. |
| `rebuild_manifest`, `recover_current_snapshot` | 4 -- built but not wired | **Keep; the gap is a missing command.** Both are recovery operations, and Operations 10.5 directs an operator with a corrupted snapshot to `codess baseline` -- which does not expose either. They are unreachable from the CLI, which is why they read as dead. The fix is a command, not a deletion; recorded as a work item rather than resolved here. |

The pattern worth carrying: **four of the six were not dead code at all.**
Two were reachable-in-principle code with no route to reach it, one was a
constant mistaken for a wrapper, and one was a declared set the code beside
it ignored. Only two were genuinely removable, and one of those is a
recommendation rather than a deletion.

## 3. Complexity and Maintainability (`radon`)

Average cyclomatic complexity across 717 blocks is **B (7.6)**, which is
unremarkable. The distribution is not:

| Function | Complexity |
|---|---|
| `cli.ingest_cmd.run` | 114 |
| `walk_sessions` | 99 |
| `query_cmd._typed_output` | 72 |
| `admin_cmd.run` | 58 |
| `cli.scan_cmd.run` | 45 |

**What the maintainability index actually measured.** Five modules rate `C`
-- `query_cmd`, `store`, `query_api`, `adapters/cc`, `walk_sessions` -- and
the natural reading is that they are the biggest. They are not:

| Module | MI | Lines | Functions | Worst function |
|---|---|---|---|---|
| `walk_sessions` | **C** | 596 | 10 | 99 |
| `query_cmd` | **C** | 1,366 | 39 | 72 |
| `adapters/cc` | **C** | 1,412 | 28 | 89 |
| `query_api` | **C** | 1,808 | 28 | 90 |
| `ingest_cmd` | B | 1,431 | 37 | 114 |

`walk_sessions` is the *smallest* of the five at 596 lines and rates `C`;
`ingest_cmd` is more than twice its size and rates `B`. MI combines volume,
cyclomatic complexity, and comment ratio, so what it is reporting is not
"this file is long" but **"this file has few functions carrying a lot of
branching"** -- 10 functions holding 194 total complexity, where `ingest_cmd`
spreads 199 across 37.

That is the useful reading, and it inverts the obvious one: the module most
worth decomposing is the small one. It is also exactly the `walk_sessions` decomposition's subject, which
is the corroboration worth having -- the case for decomposing
`walk_sessions` is stronger stated as "10 functions, one of them 99" than as
"large".

`ingest_cmd.run` at 114 is the single worst function despite its module
rating `B`, which is the same point from the other side: a module-level
index cannot locate a problem inside a module. Read them together or not at
all.

**Complexity concentrates, which decides where to start.** Per file, the
three worst functions hold most of it:

| Module | Functions | Total CC | Top 3 | Share |
|---|---|---|---|---|
| `walk_sessions` | 10 | 194 | 155 | **79%** |
| `ingest_cmd` | 37 | 199 | 139 | **69%** |
| `adapters/codex` | 18 | 271 | 168 | 61% |
| `query_api` | 28 | 395 | 204 | 51% |
| `query_cmd` | 39 | 344 | 162 | 47% |
| `adapters/cc` | 28 | 356 | 163 | 45% |
| `project_catalog` | 26 | 200 | 64 | 32% |
| `store` | 37 | 261 | 68 | 26% |

So the answer to "is it a few structures causing most of the problem" is
**yes, and the ratio says what kind of work is needed**. Above ~60%, one or
two functions are the module and decomposition is the whole job --
`walk_sessions` (79%) and `ingest_cmd` (69%) are the decomposition and command-extraction remainder.
Below ~30%, complexity is spread and there is no single extraction to make;
`store` at 26% is a large module of ordinary functions, which is a different
condition and not obviously a defect.

## 4. Duplicate Detection (`lizard -Eduplicate`)

The tool Ruff cannot replace, and the one that found something.

**A cross-adapter duplicate.** `truncate_content` was byte-identical in all
three vendor adapters -- that name in Claude, `_truncate` in Codex and
Cursor. Three copies of the truncation policy: which character marks
elision, whether the reported length is before or after bounding, what a
non-positive limit means. Exactly the "shared decision with no owner" shape
3.5.4 describes for constants and calls, now found in whole function bodies.

It is one definition in `context_content` now. Total duplicate rate fell to
**1.27%**, unique 99.02%.

What remains is concentrated in `adapters/codex` (27 blocks), which decodes
more record shapes than the other two and repeats a similar envelope per
shape. That is worth a look under the decode-strengthening work but is not obviously wrong: near-
identical handling of genuinely different vendor records is not the same
defect as one policy written three times.

### 4.1 The Codex Envelope, and What Was Left

The decode-strengthening pass closed the 27-block finding: fifteen call sites each wrote the same
twenty-key dict inline across 405 lines, sixteen keys identical in every
one. One `_base_event` builder replaced them, verified byte-identical over
96,730 real Codex Events. A second pass merged the `user` and
`developer`/`system` context branches, which differed only in the role
recorded and one diagnostic counter -- also verified, over 94,958 events,
with `file_path` the only differing field and that by intent.

**Six blocks remain, at a 0.72% duplicate rate**, and they are not one
backlog. Classified by what a merge would cost:

| Block | Shape | Fix when |
|---|---|---|
| `ingest_sources` 334~342 / 485~493 and 417~433 / 553~569 | The Claude and Codex ingest coordinators: bound events, observe the resource, derive the Session span, publish. Genuinely parallel. | **The decomposition.** That item already separates `walk_sessions` so Project logic is testable apart from vendor scanning; the same seam is what would let one coordinator serve both vendors. Merging first, without the seam, produces a function taking a vendor flag -- the shape 13.4.1 warns about. |
| `walk_sessions` 207~219 / 225~237 | Two metric accumulators summing the same seven fields from `get_db_metrics`. | **The `walk_sessions` decomposition**, same reason, and this is inside the function the decomposition names. |
| `scan_cmd` 209~224 / 235~250 | Two report-row assemblies. | **The row-emitter item.** The duplication is exactly the "27 hand-assembled rows" that item exists to remove. Fixing it separately would build the emitter twice. |
| `ingest_cmd` 885~892 / 904~911 | Cursor container-marker construction, before and after ingest. | **Now, if at all.** Eight lines, one module, no dependency on another item -- but the two occurrences bracket the ingest they compare, and naming them `_container_marker_before` / `_after` would be a rename rather than a merge. Low value; recorded rather than done. |
| `cc` 468~480 / `codex` 336~348 | The `keep`/`provenance` model-configuration helper, defined in both adapters. | **The candidate contract.** Cross-file, and it is model-configuration mapping -- the candidate-record contract the candidate contract defines is what determines whether one shared helper is correct or whether the vendors legitimately differ. |

**A "fix it when the owning item lands" rule was proposed here and is
withdrawn.** It was invented in the course of this review and was never
approved; worse, it is CoPlan 13.1.1's *"removing it is out of scope"*
wearing a schedule. Scope bounds what a change must address, not what it
may, and a duplicate deferred to another item is a duplicate that ships.
Two of the six had no dependency at all and were merged as soon as that was
noticed, which is the correct default.

What the dependency actually constrains is narrower: **whether a merge is
*possible* now, not whether it is *allowed*.** Three blocks sit across the
Project-versus-vendor boundary the decomposition exists to create, and merging them
before that boundary exists produces a single function switching on a
vendor flag -- the shape 13.4.1 rejects, and a worse defect than the
duplication. That is a statement about the available seam, not about scope,
and it obliges the merge to be part of that decomposition rather than after it.

| Block | Disposition |
|---|---|
| `ingest_cmd` 885~892 / 904~911 | **Merged.** Cursor container-marker construction before and after ingest; no dependency, so no reason to wait. |
| `scan_cmd` 209~224 / 235~250 | **Merged.** Two report-row assemblies differing in one field. |
| `ingest_sources` ×2, `walk_sessions` | **Part of the decomposition**, whose deliverable is the seam. Not deferred *past* it -- listed as work it must include, so the item cannot close with the duplication intact. |
| `cc` 468~480 / `codex` 336~348 | **Part of the candidate contract.** The shared model-configuration helper is only correct if the candidate contract says the vendors agree here; that item defines it contract. |

The distinction that matters: the 27 blocks fell in one change because the
seam -- the record type -- already existed. Where a seam exists, merge now.
Where it does not, the item that creates it owns the merge. Neither case
permits leaving a duplicate to be someone's later problem.

### 4.2 What the Complexity Scores Point At

Rerunning `radon` after this pass: average **B (7.65)** over 712 blocks,
unchanged, and `codex.process_file` still **F (126)** despite losing 100
lines. That is the useful result -- extracting the twenty-key envelope
removed *duplication*, not *branches*, and complexity counts branches. A
score that does not move after a real improvement is telling you the score
measures something else.

Counting what the branches actually test separates four superficially
similar functions:

| Function | Lines | `if` | Loops | Bool ops | What the branches are |
|---|---|---|---|---|---|
| `codex.process_file` | 783 | 62 | 2 | 23 | 27 `None` guards, 15 dispatch on record type, 5 on role |
| `ingest_cmd.run` | 692 | 43 | 4 | 17 | Sequencing and error handling |
| `walk_sessions` | 321 | 57 | 8 | 30 | Vendor scanning interleaved with Project canonicalization |
| `query_api.validate_request` | 172 | 38 | 6 | 39 | Predicate validation, one clause per field |

Four different designs, and only one shared remedy would help all four --
which is why "reduce complexity" is not an actionable instruction.

**`process_file`: the guards, not the dispatch.** Its 15 dispatch branches
are an enumeration of vendor record shapes and should stay; section 6 already
argues that flattening a readable enumeration into a table trades clarity for
a configuration language. The **27 `None` guards** are different. Seven are
literally `if bounded is None: continue` after an `apply_processing` call,
and the module has 48 bare `continue` statements. Every content-bearing
branch repeats: bound the content, process it, check for `None`, bound again,
build, yield. That sequence is the abstraction -- a helper that returns the
processed content or signals "dropped by policy" would remove roughly a third
of the branches without merging a single record type. Complexity would fall
because the design improved, not because the enumeration was hidden.

**`validate_request`: the table proposal was wrong, and reading the function
is what showed it.** It was recommended from the score -- 38 `if`s carrying
39 boolean operators, one clause per field -- without opening the function.
The function is **already a table where a table applies**: five `for key in
(...)` loops cover **30 fields with 10 branches**, grouping by shared rule
(list-of-strings-and-sorted, string, milliseconds, positive integer,
sequence bound). The remaining **28 branches are each a distinct rule** --
format, action, sortedness, the cross-field requirement that
`project_snapshots` Project IDs equal `project_ids`, `since <= until`.
Tabulating those needs a per-entry predicate and message, which is the
existing code with a dictionary around it: same branch count, one
indirection added.

Where the pattern does apply elsewhere: `resource_policy` raises eight field
errors with no grouping loop, and is the better candidate. `schema_evolution`
and `acceptance` already use field loops. **A score cannot tell a repeated
rule from a distinct one; only the branch bodies can.**

**`walk_sessions`: 30 bool ops, 8 loops, 5 `try`.** The highest density of
the four, and the decomposition item already names the fix -- separate Project canonicalization
from vendor scanning. The complexity is a symptom of the two concerns being
interleaved, so it falls out of the decomposition rather than needing its
own attack.

**`ingest_cmd.run`: 43 ifs over 692 lines is comparatively sparse, and the
actions are grouped, not repeated.** Reading its top level answers the
question directly -- **35 top-level statements in four phases**, with no
repetition between them:

| Phase | Lines | Share | What it does |
|---|---|---|---|
| Resolve and build options | 55 | 8% | 22 statements, mostly single-line assignments into one `opts` dict |
| Cursor preflight | 233 | 35% | **One `if`**, 196 lines, entered only when Cursor roots exist |
| Project loop | 353 | 54% | **One `for`**, the actual work |
| Finish | 11 | 1% | Validate-only branch, cleanup, report, exit code |

So the 43 branches are not 43 actions. **Two statements are 90% of the
function**, and both are single-entry blocks with a clear precondition: the
Cursor preflight runs when `cursor_roots and not validate_only`, the loop
runs per Project. Nothing is repeated -- there is no second cohort block, no
second loop -- which is why duplicate detection finds only one small pair
here (now merged) rather than a pattern.

That makes the remedy unambiguous and different from the other three: the
two large blocks are already functions in everything but name, each with one
call site and an evident boundary. Extracting `_cursor_preflight` and
`_ingest_project` leaves a `run` of roughly 90 lines that reads as its four
phases, and neither extraction has to decide anything -- the seam is the
existing `if` and `for`. Branch count barely moves, which is the point:
`run`'s problem was never density.

**The rule: read complexity as a pointer, never as a target.** Each of these
four wants a different change, and two of them (`process_file`'s guards,
`validate_request`'s table) would not have been visible from the score alone
-- they came from counting what the branches test. A score that stays flat
after a genuine improvement, as `process_file`'s did, is the clearest
evidence that the number is not the thing being fixed.

## 5. Import Graph and Cycles

Built from the AST rather than by a tool, because the question is specific:
does the dependency direction 3.3 asserts hold?

| Module | Fan-in |
|---|---|
| `config` | 31 |
| `fileio` | 22 |
| `hashing` | 21 |
| `snapshot` | 14 |
| `project_catalog` | 14 |

Shared leaf utilities with high fan-in and no fan-out are the intended
shape, and this is that shape -- the same conclusion 3.5.5 reached by
counting imports. Highest fan-out is `admin_cmd` (24), `ingest_cmd` (20),
`query_cmd` (14): the command layer, which is where fan-out belongs.

**Cycles: 15 counting every import, 0 counting only module-level imports.**
Every cycle runs through a function-local import -- `config` importing
`snapshot` inside a function body, for instance. Those are deliberate: the
deferred import is what breaks the cycle at import time.

This is the finding worth keeping. A naive cycle count would report fifteen
architectural violations; the layering is in fact intact, and the deferred
imports are the mechanism holding it. It also explains `PLC0415`'s 31
findings, which are that mechanism rather than carelessness -- and means
that rule should not be enforced without first deciding which deferrals are
load-order necessities.

## 6. What Large Functions Are Actually Made Of

A recurring assumption about long functions is that much of the length is
error handling and message formatting. Measured, it is not:

| Function | Lines | `except`/`finally` | Multiline messages | Logic |
|---|---|---|---|---|
| `codex.process_file` | 959 | 0 | 0 | **100%** |
| `query_api.validate_request` | 172 | 0 | 2 | 98% |
| `cc.normalize_user` | 460 | 14 | 0 | 96% |
| `ingest_cmd.run` | 692 | 36 | 0 | **94%** |
| `walk_sessions` | 321 | 22 | 5 | 91% |
| `query_api._overview` | 457 | 0 | 55 | 87% |

Error wrapping accounts for 0-5% and messaging for 0-12%. The length is
decisions, so decomposition is the only thing that shortens these -- there is
no formatting to squeeze out. `_overview` is the sole partial exception, and
its 55 message lines are a single multi-line SQL statement rather than
prose.

**Switch-shaped dispatch.** Four functions contain an `if`/`elif` chain five
branches or deeper, testing one subject throughout:

| Function | Branches | Tested on |
|---|---|---|
| `cc.normalize_product_state` | **14** | `rtype`, `subtype` |
| `cc.extract_tool_input` | 8 | tool `name` |
| `review_project.recommend` | 5 | curation, git state |
| `codex.process_file` | 5 | role, direct-user evidence |

`normalize_product_state` was the clearest case: fourteen branches on one
variable, of which eleven were 2-10 lines building an Event that differed
only in two literals -- thirteen textually identical `_base_event` calls in
one function. Three of them (`ai-title`, `custom-title`, `agent-name`)
differed *only* in which field held a label and what the Event was called,
and are now one branch over a table. The rest are genuinely different
constructions and stay as branches: converting a dispatch to a table helps
where the arms are uniform and hurts where they are not.

## 7. Call Trees: Where an Implementation Belongs

`cli.ingest_cmd` has 37 definitions, which invites the question of whether
some belong elsewhere. Mapping each to its callers answers it:

- **`run` alone is 692 lines, 54% of the module's definition lines**, and
  its Project loop is 353 of those -- half of `run` in one loop body.
- **Every other function has 1-5 in-module callers and zero external source
  use.** They are `run`'s private decomposition, and moving any of them
  would create an import for a single caller.
- The classes are the exception and are correctly shared: `IngestTally`,
  `ProjectOutcome`, and `VendorStore` members are referenced from tests and
  from `ingest_publication`.

So the module is not a collection of misplaced implementations; it is one
very large function with helpers around it. That reframes the remaining command-extraction
work: the target is the 353-line Project loop, not the file's function
count.

### 7.1 Does Each Separated Function Have a Test

A function extracted so a caller could shrink is worth less than one
extracted so a behavior could be asserted. The check is whether the
extraction actually acquired a test, and where it did not, whether the
separation still earns its place.

Auditing the modules that extraction created -- `ingest_sources`, `ingest_publication`,
`query_reports`, `units` -- plus `helpers`:

| Finding | Count | Disposition |
|---|---|---|
| Public function called directly by a test | 30 | Correct as separated |
| Private helper with 2 or more in-module call sites, covered through its public caller | 6 | Keep: inlining restores the duplication the extraction removed |
| Private helper with 1 call site, covered through the ingest path | 2 | Keep: `_record_cc_source` is passed as a callback, so the indirection *is* the interface; `_record_related_raw` is 25 lines of raw-capture logic with its own failure modes |
| Public function with no direct test | 2 | **Fixed** -- tests added |

The two gaps were both in `helpers`, and both were security boundaries:

- **`local_path_from_uri`** rejects remote URI schemes. A vendor workspace
  record may carry a plain path, a `file://` URI, or a `vscode-remote://`
  or `ssh://` URI for a container or remote workspace. Accepting a remote
  one attributes another machine's Sessions to a local Project. Untested.
- **`user_root_string_disallowed`** rejects `..` and hidden relative
  segments in a user-supplied root. Untested.

Thirty cases now cover them, including remote schemes, `file://localhost`,
percent-escapes, and each traversal form. That a rejection function had no
test is the more useful finding than the count: the tested functions were the
ones whose output someone wanted to read, and the ones that only ever say
"no" were the ones nobody exercised.

**The scan's own limit.** Counting `name(` in the test tree misses functions
exercised through a parametrized table -- `units.BKB` and `BGB` read as
untested and are in fact covered by `@pytest.mark.parametrize` over converter
pairs. Section 2.2's rule applies here too: a reference count is a starting
question, not a verdict.

### 7.2 High Call Counts: Reuse or Repetition

A frequently called helper is usually read as successful factoring. It can
equally be the visible half of a missing abstraction -- the same shape
written out repeatedly, with one small piece extracted. The counts do not
distinguish those. **Call sites per file does.**

| Function | Calls | Files | Reading |
|---|---|---|---|
| `write_json_atomic` | 30 | 16 | Shared primitive |
| `open_readonly` | 19 | 12 | Shared primitive |
| `read_json` | 19 | 9 | Shared primitive |
| `contract_digest` | 17 | 9 | Shared primitive |
| `sanitize_tabular` | 44 | 2 | **43 in one file** |
| `_add_check` | 34 | 1 | Single-module |
| `_annotate_source` | 22 | 2 | Single-module |
| `_base_event` | 15 | 1 | Single-module |

The top group is what healthy reuse looks like: a small function, many
callers, spread wide. Nothing to do.

The bottom group is concentrated, and concentration is the signal. A helper
called thirty times inside one module is not being reused -- it is being
*repeated*, and what surrounds each call is the part that was never
factored.

**`sanitize_tabular`, 43 calls in `query_cmd`, is the clearest case.** The
function itself is right: five lines, one job, correctly shared. What it
reveals is the code around it. `query_cmd` has **105 `print` calls** and
**27 places that assemble a row by hand**, each joining sanitized fields
with tabs or interpolating several into an f-string:

```python
f"{sanitize_tabular(row['project_path'])}\t{sanitize_tabular(row['kind'])}\t"
f"{sanitize_tabular(row['locator'])}\t{sanitize_tabular(row['sources'])}\t"
```

Every one of those sites re-decides the separator, the column order, and
which fields need sanitizing. A field added to one report reaches the others
only if someone edits each. The missing piece is a row emitter that takes
fields and a format and owns the joining -- at which point `sanitize_tabular`
is called once, inside it, and the call count drops from 43 to 1 without
removing a single capability. That the count is high is not the problem; it
is the measurement that located one.

**The other three are benign, for a reason worth stating.** `_add_check`
(34), `_annotate_source` (22), and `_base_event` (15) are each called once
per *variant* in a dispatch over source record shapes -- one call per record
type, per check, per event family. The repetition is in the vendor data,
not in the code: fifteen record shapes need fifteen constructions. Section
6 already found the same structure in `normalize_product_state`, where three
of fourteen branches were identical and became a table. The rest were not,
and forcing them into one would trade a readable enumeration for a
configuration language.

**The rule this yields.** A high call count is a question, not a verdict,
and the follow-up is *where*:

- **Many files** -- a shared primitive. Leave it.
- **One file, one call per data variant** -- an enumeration. Check whether
  any branches are identical (those become a table) and leave the rest.
- **One file, many calls in similar surrounding code** -- a missing
  abstraction. The helper was extracted; its context was not.

Only the third is a defect, and it is the one a raw count most resembles a
success.

### 7.3 The 183 `conn.execute` Calls

A first pass reported `execute` at 184 calls across 23 files, which was a
regex conflating the `sqlite3` cursor method with a module function of the
same name; only one call is the latter. The corrected number still invites
the question -- does the system really do that much varied database work, or
is one query written 183 times?

Applying the same distribution test, by module and then by statement.
All 183 calls, not a sample -- an earlier pass examined the top two, which
covered 91 and left 92 unaccounted, so the conclusion rested on half the
evidence:

| Module | Calls | Shape | Distinct tables |
|---|---|---|---|
| `store` | 66 | 27 INSERT, 24 SELECT, 12 DELETE, 3 PRAGMA | 25 |
| `cursor_source` | 25 | 18 SELECT, 4 PRAGMA, 2 dynamic, 1 BEGIN | 4 |
| `query_api` | 16 | 15 SELECT, 1 dynamic | 9 |
| `query_reports` | 14 | 14 SELECT | 5 |
| `baseline_validation` | 11 | 7 SELECT, 3 dynamic, 1 PRAGMA | 6 |
| `configuration_audit` | 8 | 5 dynamic/fragment, 3 other | 4 |
| `storage_report` | 7 | 4 SELECT, 3 PRAGMA | 2 |
| `schema_contract` | 6 | 3 SELECT, 3 PRAGMA | 2 |
| `evidence` | 5 | 4 SELECT, 1 dynamic | 3 |
| `snapshot` | 4 | 2 SELECT, 1 INSERT, 1 PRAGMA | 2 |
| 14 others | 1–3 each | mostly single SELECT or PRAGMA | ≤2 |

Overall: **105 SELECT, 29 INSERT, 20 PRAGMA, 13 DELETE, 1 UPDATE**, and 9
dynamically composed. Writes are concentrated -- 29 of 30 INSERTs and 12 of
13 DELETEs are in `store`, which is the intended boundary and holds. **Reads
are not.**

**`store` is genuinely varied, and the schema proves it.** Its 27 INSERTs
resolve to **23 distinct target tables** against a 24-table schema -- one
insert per entity, with four tables written from two places. SELECT spans 11
tables and DELETE 10. There is no dominant statement and nothing to fold:
persisting 23 entity types takes 23 inserts, and a generic writer would
replace readable per-entity SQL with a column-mapping layer that hides
exactly the constraints the schema exists to enforce. The count tracks
schema breadth.

**`cursor_source` is the opposite, at smaller scale.** Fourteen of its
queries hit one table, `cursorDiskKV`, because Cursor stores everything in a
single key-value table -- that concentration is the vendor's schema, not
ours. But the *predicate* repeats: `key >= ? AND key < ?` is written out six
times. The module already solved this for a different predicate, naming
`_BUBBLE_ROWS` and `_BUBBLE_ROWS_JOINED` as constants and interpolating them
at seven sites. The key-range bound simply never got the same treatment. The
remedy is already present in the file.

**The four writes outside `store` are each defensible, and one is not
gated.** 29 of 30 INSERTs and 12 of 13 DELETEs are in `store`, so the write
boundary holds in the large. The exceptions:

- `artifact_correlation` DELETEs and re-INSERTs `correlation_assertions`
  scoped to its own `method`. That is a refresh of derived assertions, and
  keeping it beside the correlation logic is more readable than a `store`
  function taking the correlation's intermediate state.
- `snapshot` INSERTs two `store_meta` keys into a freshly copied database.
  The copy is the snapshot, so the stamp belongs to snapshotting.
- `ingest_sources` UPDATEs `sources` to attach raw-capture evidence after
  the capture completes. It is the one place the capture outcome is known.

The finding is not the placement but the gate: `snapshot` opens its target
with `require_store(target, write=False)` and then writes to it, while
`artifact_correlation` and `ingest_sources` call no gate at all. The
contract check that the write-gate narrowing produced and `--no-check` escapes is therefore not
covering three of the four write sites outside `store`.

**Twenty PRAGMAs are twenty distinct questions, with one duplication.** They
are connection setup (`query_only`, `foreign_keys`, `busy_timeout`,
`journal_mode`), identity (`application_id`, `user_version`), integrity
(`integrity_check` ×3, `quick_check` ×2, `foreign_key_check`), introspection
(`table_info`, `index_list`), and size reporting (`page_size`, `page_count`,
`freelist_count`). None has a non-PRAGMA equivalent in SQLite, so the count
is not a smell. The one repetition is the setup trio, applied in
`fileio.open_readonly`, `store.connect`, and three times in `cursor_source`
-- five places deciding independently what a read-only connection means.

**The remaining 92 calls hold the finding the top two hid.** Filtering to
SELECTs against core CoSchema tables -- `events`, `sessions`,
`tool_results`, `tool_invocations`, `model_turns`, `interactions`,
`artifacts`, `event_content` -- issued from outside `store` and the query
layer gives **21 statements across 9 modules**:

| Module | Reads |
|---|---|
| `baseline_validation` | `artifacts` ×2, `model_turns` ×2, `sessions`, `events` |
| `storage_report` | `events` ×2, `sessions` ×2 |
| `evidence` | `events` ×2, `artifacts` |
| `orientation_audit` | `events` ×2 |
| `mcp_audit` | `tool_invocations`, `events` |
| `artifact_correlation`, `evidence_resolver`, `project_annotations`, `session_names` | 1 each |

Every one of those modules knows the events/sessions schema directly. A
column rename -- which the time-column and Event-kind items both propose -- has to find them, and
nothing points to them: they are not in the query layer, so a reader
auditing "who depends on the Event schema" would look at `query_api` and
`query_reports` and miss two thirds of it. This is the wide-primitive
concern from 7.4 in its concrete form, except the coupling is through a
*table shape* rather than a function.

So the answer to "do we do that much varied work" is: **yes for writes, no
for reads.** `store` earns its 66 calls at one insert per entity.
`cursor_source` repeats one predicate six times. And the long tail nobody
counted contains 21 direct reads of core tables from modules whose job is
auditing and reporting, which is the part that will make a schema change
expensive. **Counting calls answers nothing; counting what the calls say
answers it -- and counting only the top of the distribution answers it
wrongly.**

### 7.4 When a Wide Primitive Is Not Good News

Section 7.2 read "many files" as evidence of healthy reuse. That is too
generous as stated. A function used in sixteen files is only good when its
job is *bounded and orthogonal* to what its callers do -- hashing, atomic
writes, sanitizing, opening a file read-only. Those are operations any layer
may need without implying a relationship between layers.

The dangerous case is a wide primitive carrying *domain* meaning: if
sixteen modules call something that knows what a Session is, they are
coupled through it, and the count is measuring how far a decision has spread
rather than how well it was factored. The check is what the function would
have to change for -- a `write_json_atomic` changes for filesystem reasons,
and no caller cares; a shared `normalize_session` would change for decode
reasons, and every caller inherits them.

Applied here, the wide primitives are `write_json_atomic` (16 files),
`open_readonly` (12), `read_json` (9), `hash_file` (8), and `contract_digest`
(9). The first four are I/O with no domain content. `contract_digest` is the
borderline one: it is a hash, but it is a hash *of the released contract*,
so nine modules depend on the contract's identity. That is defensible --
it is the value the write gate compares, and the narrowing reduced what it covers to
six files -- but it is the one to watch, and the `contract_digest` rename is partly about
making what it covers legible at those nine sites.

## 8. Module Size and Count

Seventy-one modules, and the question is whether some are too small to
justify a file. Measured as *code* lines -- comments, docstrings, and blanks
excluded -- eight modules fall under forty:

| Module | Code lines | Total | Imported by |
|---|---|---|---|
| `cli/__init__`, `adapters/__init__`, `vendor_audits/__init__` | 0 | 1 | package markers |
| `codess/__init__` | 1 | 3 | version only |
| `processing_contract` | 3 | 9 | 6 modules |
| `path_label` | 28 | 59 | 1 module |
| `tool_identity` | 31 | 44 | 2 modules |
| `context_content` | 32 | 64 | 4 modules |

The comment ratio is high by intent -- `processing_contract` is three
constants with the reasoning for each -- so a low code count is not by
itself a finding.

**Fan-in decides it.** `processing_contract` is three lines read by six
modules; merging it into any one of them would make the other five import
that module for a constant, which raises coupling to remove a file. The same
holds for `context_content` (4), `tool_identity` (2), and `identity` (6).

`path_label` is the one genuine candidate: 28 code lines, imported by
exactly one module (`review_project`). It is not merged here because the
decision is small and the file is coherent, but it is the only one where
merging would not cost a dependency.

**A related finding, and the opposite correction.** Dead-code detection
reported `config.BKB` and `config.BGB` as unused, and deleting them was the
wrong move: they are the inverse half of a converter set whose forward half
is used, and an incomplete set invites the next caller to write `/ 1024`
inline. The right change was **isolation, not deletion** -- all six now live
in `codess/units.py`, which owns the conversion, with `config` re-exporting
them because callers have long imported from there. That is a case where the
tool identified a real asymmetry and the obvious remedy was backwards.

## 9. Helper Placement, by Consumer Profile

Mapping every public function in the utility-shaped modules to the modules
that call it gives a placement test: a helper belongs where its consumers
are, and a module whose functions serve unrelated consumers is a bag rather
than a subject.

Most hold up. `fileio` (11 consumers for `open_readonly`, 15 for
`write_json_atomic`), `hashing` (3-7 each), and `context_content` (3 each,
all adapters) are shared leaves with the fan-in that justifies a module.
`identity`'s seven functions each have one consumer, but they are one
vocabulary and splitting them would scatter the derivation rules the module
exists to state.

Two findings:

**`helpers` is three concerns, not one.** Its twelve functions divide into
path judgment (`should_prune_directory`, `is_excluded`,
`unsafe_traversal_root_reason`, `ephemeral_project_location_reason`,
`local_path_from_uri`, `user_root_string_disallowed`), Claude slug encoding
(`path_to_slug`, `slug_to_path`), and CLI input parsing (`parse_dir_list`,
`validate_dirs_file`, `write_csv`). The consumer sets barely overlap: the
CLI-parsing group is used by `project` and `admin_cmd`, the path group by
`walk_sessions` and `review_project`. That is a candidate split, recorded
rather than done because it moves six functions to save one concept.

**The slug pair was defined twice, and the copies disagreed.** `project` and
`helpers` both defined `path_to_slug` and `slug_to_path`. The encoders were
byte-identical; the decoders were not. `helpers.slug_to_path` consults the
filesystem to resolve a hyphen inside a directory name -- the encoding is
lossy, since `name-suffix` and `name/suffix` produce the same slug -- and
`project.slug_to_path` did not, so it decoded a real path
(`/home/user/work/<group>/name-suffix`) to a non-existent one (`<group>/name/suffix`). Production
imported the correct one and only tests imported the weaker, which is why no
failure surfaced. `project` now re-exports `helpers`, and the fallback's
stated limit -- it rejoins the last two segments only, not every combination
-- is now a test rather than an assumption.

This is the "redefined elsewhere" class from section 2.1, and it is the one
where deleting the unreferenced copy without comparing behavior would have
kept the wrong implementation.

## 10. Tools Not Yet Run, With Their Question

| Tool | Question it answers | Why it may be worth running |
|---|---|---|
| `import-linter` | Does the layering in 3.3 hold, as a contract? | Already on PATH. It expresses "adapters must not import store" as a checkable rule, which is the import-boundary item; the AST graph in section 5 proves the property holds today but does not keep it holding |
| `pytest-cov` with `--cov-branch` | Which branches no test reaches | Already used; 13.4.5 records that subprocess execution hides scan and ingest coverage, which is the mechanical-enforcement item's other half |
| `mutmut` / `cosmic-ray` | Do the tests fail when the code is wrong? | Coverage says a line ran, not that an assertion would catch its being wrong. Expensive, but the decode paths are where a weak assertion is most costly |
| `hypothesis` | Do the bounded readers hold for inputs nobody wrote a fixture for? | The resource bounds, truncation, and JSONL readers have properties -- idempotence, monotonic length -- that a generator tests better than examples |
| `pyright` | Stricter typing than mypy, notably on `Any` propagation | 13.4.10 records mypy's 178 errors concentrating at the decode boundary; a second checker would say whether that is mypy's inference or the code |
| `diff-cover` | Is *new* code covered, regardless of the total? | Turns coverage into a per-change gate without demanding a repo-wide number |
| `bandit` | Security patterns beyond Ruff's `S` subset | Overlaps heavily with what is already selected; likely low yield |
| `pip-audit` | Dependency vulnerabilities | One runtime dependency (`zstandard`), so nearly free to run and nearly always clean |

The two with the clearest value are `import-linter`, because it converts a
property currently verified by hand into one verified on every run, and
mutation testing on the adapters, because that is where a test passing
without asserting anything would go unnoticed longest.

## 11. What to Run, and When

| Tool | Answers | When |
|---|---|---|
| `ruff` with `C901`/`PLR09xx` | Which function is growing | Continuously; already selected |
| `vulture` at 60% | What an extraction left behind | After any move or refactor; read every finding, since 9 of 32 were real |
| `lizard -Eduplicate` | Which decision is written twice | Before consolidating anything; it finds what reading misses |
| `radon cc`/`mi` | Where complexity concentrates, and whether it is one function or many | When arguing for a decomposition, to make the claim numeric |
| AST import graph | Whether the layering holds | When a dependency rule changes; distinguish module-level from deferred |

None belongs in the test suite. All are diagnostics whose output is a prompt
for judgment, and each reports findings that are correct to leave alone. The
one exception worth automating is the module-level cycle count, which has a
defensible expected value of zero and would become part of the mechanical
checks.
