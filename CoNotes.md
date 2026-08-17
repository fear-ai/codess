# CoNotes

CoNotes holds developer evidence that is neither intended structure nor an open
item: the audits that found repeated decisions in the code, and the process
misses observed during real review and implementation sessions.

It is kept separate from [CoPlan](CoPlan.md) because a reader asking how Codess
is built should not have to read several hundred lines of audit method to reach
the answer, and separate from [CoReview](CoReview.md) because these are
observations about *how the work was done* rather than findings about the
software.

## Table of Contents

- [1. Duplication and Centralization Audits](#1-duplication-and-centralization-audits)
- [2. Observed Process Misses](#2-observed-process-misses)

## 1. Duplication and Centralization Audits

The same "a module needs one fact, an inline literal is smaller than a
shared-code change" mechanism from 3.4 was checked against numeric
constants, focused on byte-size thresholds after `1024`-scale arithmetic
was found scattered well beyond `config.py`'s already-centralized
`resource_policy`-derived maximums. Unlike the file-literal case, most of
what was found was not duplicated -- the audit therefore had to
distinguish the two before centralizing anything, since collapsing
genuinely independent constants into a false shared value would be a worse
outcome than leaving them alone.

3.5.1 through 3.5.3 record that constant audit and its outcome. 3.5.4
applies the same criterion to repeated standard-library calls, where the
mechanism is identical but the duplication conceals a decision rather than
a value, and is therefore harder to see and more consequential when it
diverges.

### 1.1 Two Confirmed Duplication Clusters

| Value | Meaning | Independent declarations found |
|---|---|---|
| 128 MiB | A normalized store at or above this size is labelled "large" | `cli.admin_cmd` (`--large-bytes` default, two subcommands), `refresh_operations` (two function parameter defaults), `project_annotations` (`DEFAULT_LARGE_STORE_BYTES`) |
| 2 MiB | A single-line source record above this size is rejected | `cli.admin_cmd` (`--max-record-bytes` default, two subcommands), `bounded_jsonl` (`DEFAULT_MAX_RECORD_BYTES`) |

Both clusters shared the same origin as 3.4's file-literal case: the value
was correct everywhere it appeared, nothing was functionally broken, and
each independent declaration was individually reasonable at the moment it
was written. The risk was latent, not active -- a future change to either
threshold would need to be found and applied at every site by hand, with
no mechanism forcing that to happen. Both are now defined once in
`config.py` (`LARGE_STORE_BYTES`, `MAX_RECORD_BYTES`) and imported
everywhere they were previously re-declared.

### 1.2 Genuinely Independent Constants, Centralized on Request

The remaining `1024`-scale constants found were each a distinct, correctly
scoped decision with no duplication:

| Constant | Prior location | What it actually governs |
|---|---|---|
| `LARGE_RAW_REVISION_BYTES` (1 GiB) | `retention.py` | A raw-capture revision this large triggers explicit `--keep-comparison-revisions` review during retention planning |
| `MAX_TOKEN_LINE_BYTES` (8 MiB) | `token_usage.py` | A single JSONL line above this size during token-usage scanning is treated as implausible and skipped |
| `SOURCE_READ_MAX` (64 MB, `CODESS_SOURCE_READ_MAX`) | `config.py` | The largest Source `read_source_revision` reads in full; above it the revision comes from sampled windows plus size, and `method` records which claim was made. 395 of 405 real Sources fall under it. |
| `LARGE_RAW_OBJECT_BYTES` (300 MiB) | `storage_report.py` | A raw-capture object above this size is called out individually in a storage report |
| `DEFAULT_QUERY_BYTE_LIMIT` (16 MiB) | `cli.query_cmd` | Default maximum inline content bytes for one typed query result, overridden by explicit `--byte-limit` |

None of these were wrong or duplicated -- each was the single place its own
governing decision lived, which is the outcome 3.4's consolidation was
working toward for file literals. They were moved to `config.py` on an
explicit decision to optimize for one discoverable location over literal
proximity to the one function that uses each value, not because leaving
them local was a defect. `config.py` records why each one exists inline
(a short comment naming the governed behavior) so a reader scanning the
module does not need to chase the constant back to its sole call site to
learn what it is for.

Three further constants (`DEFAULT_HASH_CHUNK_BYTES`, `SOURCE_SAMPLE_CHUNK_BYTES`,
`RAW_CAPTURE_CHUNK_BYTES`) were centralized on the same basis but are a
different kind of value: streaming I/O buffer sizes, not policy thresholds.
Changing one does not change what Codess accepts, rejects, or flags --
only how much memory one read call buffers at a time. They are grouped
under a separate heading in `config.py` for this reason; a future reader
should not infer a governance meaning from their presence next to the
threshold constants above.

### 1.3 What Was Deliberately Left Alone

Several other `1024`-shaped expressions were checked and are not
duplicated, not policy thresholds, and were left as local arithmetic:

- `resource_policy.BUILTIN_MAXIMUMS` (`transcript_bytes`, `cursor_container_bytes`)
  is the source `config.py` itself already reads from via the table-driven
  env-var defaults (12.1); moving it would invert that ownership rather
  than fix a duplication.
- `bounded_jsonl`'s `1024`-byte floor on `max_record_bytes` is a sanity
  minimum on a caller-supplied value, not a default or a threshold shared
  with anything else.
- `scan.py`'s four `/ (1024 * 1024)` divisors and `admin_cmd.py`'s
  `* 1024**3` are unit-conversion arithmetic (bytes to MB for display,
  GB to bytes for a CLI argument), not limit values -- the same category
  as a Celsius/Fahrenheit conversion constant, not a configuration
  decision.
- `resources.py`'s platform-conditional `* 1024` converts a
  platform-reported unit (KB on non-Darwin, bytes on Darwin) to a common
  unit; the multiplier is a fact about the operating system's reporting
  convention, not a Codess policy value.

Centralizing these would have added indirection without removing any real
duplication -- the same failure mode 3.4.4 warns against for file literals,
applied to numbers instead of names.

### 1.4 The Same Audit Applied to Low-Level Calls

The constant audit above asks one question -- *is this literal a shared
decision or an independent one?* -- and the answer decides whether
centralizing helps or adds indirection. Repeating a standard-library call
is the same mechanism with a different surface: an inline
`datetime.now(...)` or `hashlib.sha256(...)` is smaller than importing a
shared helper, so each site writes its own, and the shared decision inside
it never acquires an owner. Three clusters were found by applying the
constant criterion to calls rather than literals.

| Cluster | Independent sites | Shared decision with no owner | Divergence found |
|---|---|---|---|
| Current UTC time | A private `_now` helper in most modules that stamps records | Which representation is persisted | Yes: most return ISO text, `registry_store` renames it `_now_iso`, `storage_report` returns a `datetime` |
| SHA-256 derivation | A direct `hashlib` call wherever a digest is needed | Algorithm, encoding, truncation width and end | Yes: widths of 48, 64, 96, and 256 bits chosen per site with no stated basis |
| Canonical JSON for digesting | An inline `json.dumps` before each digest | Serialization form that makes equal content give equal digests | Yes: a minority passed `ensure_ascii=False`, the rest took the default |

The pattern is uniform. Each site was individually reasonable, nothing was
visibly broken, and the duplication was accumulated rather than chosen --
the same origin 3.5.1 records for the byte-size clusters. What differs is
the consequence. A duplicated constant risks a *future* inconsistency when
one site is updated and others are missed; a duplicated call already
carries an *embedded decision*, so the sites can diverge without anyone
editing them in relation to each other. All three clusters had in fact
already diverged.

The severity ranking follows from what the divergence produces, and it is
not the ranking the site counts suggest:

- **Silently wrong results.** The `ensure_ascii` split makes two equal
  documents digest differently, with no error and no failing test. This is
  the only cluster that produces a wrong answer rather than a maintenance
  hazard, which is why it was prioritized and resolved first despite being
  the smallest cluster.
- **Unreviewed values.** The SHA-256 widths were selected per site; of the
  five key sites, one turned out not to need a hash at all and the rest moved
  to declared widths (13.4.8). Resolved under W20.
- **Reader confusion.** The `_now` return-type split means a name does not
  predict its own type. No incorrect behavior, but every reader must check.

The three clusters are now resolved differently, which is itself the point.
The SHA-256 and canonical-JSON clusters became one shared module because
each carried a single decision that simply had no owner. The `_now` cluster
remains open because its decision has not been made rather than merely
misplaced.

Concretely, `_now` awaits one choice: **what a timestamp accessor returns.**
Most sites return ISO 8601 text, `storage_report` returns a `datetime`, and
both are legitimate for their callers -- persistence wants text, comparison
and arithmetic want an aware object. The question is whether to provide two
accessors named so the return type is evident, or one canonical type with
conversion at the boundary. Until that is settled a shared helper would
relocate the ambiguity rather than remove it, because the divergence is in
the contract, not the implementation. This is the reverse of the hashing
case, where every site wanted the same thing and just had no common place to
get it.

**A fourth cluster: literal SQL.** The same criterion applied to SQL
statements found the same shape again, and the same already-diverged
outcome. Statements duplicated across modules fell by roughly two thirds
once the shared ones had an owner; what the survey found is more useful than
the count:

| Duplicated read | Sites | Divergence found |
|---|---|---|
| `store_meta` as a mapping | 5 | None; every site wrote the identical expression and picked one key |
| Table-to-count-query map | 2 modules | Yes: one quoted the table name and one did not, one listed eleven tables and the other twenty-two, and the DDL declares twenty-four -- so both were incomplete and neither knew it |
| Read-only connection URI | 19 | Yes: only some also set `query_only`, so whether a read could accidentally write varied by call site rather than by intent |
| Structural checks (`integrity_check`, `foreign_key_check`) | 3 | None, but each assembled the pair by hand |
| Column list of one table | 3 | None; each tolerated an older store by asking SQLite itself |
| Session structure aggregates | 2 | None yet -- but the overview and the orientation audit reported the same four counts from separately written statements, so a change to one would have silently disagreed with the other |
| Source-selection predicate | 2 | Yes: the diagnostics clause re-derived the identifier tuple the predicate had already computed, and spelled the placeholder list differently, so one statement contained `IN (?, ?)` and `IN (?,?)` |

The count map is the sharpest instance of the general point. Two modules
each maintained a list of the schema by hand, both drifted from the DDL, and
neither could detect it, because a hand-written list has nothing to be
checked against. Deriving the tables from the store removed the list, the
drift, and the second spelling together. The read-only URI is the sharpest
*consequence*: a missing `query_only` is not a maintenance hazard but a
weaker guarantee, and it was weaker at some sites and not others for no
stated reason.

The source-selection predicate is the instructive case, because it was
introduced by this very consolidation rather than found by it. Lifting the
command module's `_source_predicate` onto `QueryScope` gave the diagnostics
variant a method to call, and it did call it -- then recomputed the
identifier tuple it had just been handed, because the second half of the
clause needed "the same thing for a different alias" and the parameter was
not there to ask for. Two spellings of the placeholder list followed, in one
statement. The fix was to make the alias a parameter and compose the clause
from two calls, which is what the method should have taken in the first
place. The lesson is narrow and worth stating: extracting a helper does not
by itself remove duplication if the helper cannot express the second
caller's variation, and the second caller will then reimplement it
alongside.

One further finding is a boundary rather than a duplication:
`store.replace_source_sessions` had no production caller at all. The Cursor
streaming path had replaced it and reimplemented its removal logic inline,
so the function survived only because a test still called it -- a test that
therefore verified nothing the software did. Extracting the shared removal
and deleting the dead function kept the behavior its test asserted while
removing the copy.

**The same pattern in test fixtures, surveyed separately.** Test SQL is not
production SQL and was reviewed on its own terms: a fixture may legitimately
build an odd shape, since that shape is often the subject of the test. What
is not legitimate is building the *ordinary* shape differently in each file.
The Cursor vendor tables were created in five modules, the key/value insert
appeared in three spellings, and the header table in four column variants of
which three were incidental. These now come from shared builders, with the
deliberate variants -- a reduced header, an unexpected future column, a BLOB
value -- passing their shape explicitly so the intent is visible rather than
implied by a hand-written statement. The builders are themselves tested
against the vendor module that reads them, because a fixture that lies makes
every test agree with the others and disagree with Cursor.

**A fifth cluster, found by tooling rather than by reading.** The four
clusters above were found by surveying the codebase by hand. Running
duplicate detection (`lizard -Eduplicate`) afterwards found one more that no
survey had: `truncate_content` was byte-identical in all three vendor
adapters -- that name in Claude, `_truncate` in Codex and Cursor. Three
copies of one truncation policy: which character marks elision, whether the
reported length is before or after bounding, and what a non-positive limit
means. It is one definition in `codess/context_content.py` now, and the
codebase-wide duplicate rate is 1.27%.

The lesson is about method rather than about truncation. A reader surveying
constants finds duplicated constants, and a reader surveying calls finds
duplicated calls; neither reliably finds a duplicated *function body*,
because each copy reads as correct in its own file. That is what a tool is
for, and it is why the survey is now recorded with the tools that extend it
in `experiments/structural-analysis-tools.md`.

Dead-code detection over the same tree found nine definitions with no
consumer, of which two -- `_source_predicate` and `_limited` in `query_cmd`
-- were residue from W06 step 6: their callers moved to `query_reports` and
the originals stayed, called by nothing. A suite passing throughout is
expected, since a function nothing calls breaks nothing when removed. The
same class had already been found once by hand (`store.replace_source_sessions`
above), which is the argument for running the check after every extraction
rather than relying on noticing.

**The findings are four kinds, not one.** Classifying each by *why* it is
unreferenced decides the response, and only the first is simply deletable: a
**leftover remnant** whose caller moved (`_source_predicate`,
`replace_source_sessions`); a definition **redefined elsewhere**, which needs
the copies compared before either is removed; a **complementary** half of a
symmetric set, which wants isolation rather than deletion; and something that
**should be used but is not**, which is an open item rather than dead code.

The fourth class is why the list is worth reading. `schema_contract.validate_mapped_event`
is exercised by four test modules and called from no production path --
which is exactly 13.4.2's finding that it "is not a common ingest boundary",
tracked as W04. A dead-code report and an open architectural item pointed at
the same function from opposite directions.

**A definition that existed twice, with copies that disagreed.** `project`
and `helpers` both defined `path_to_slug` and `slug_to_path`. The encoders
were byte-identical; the decoders were not. Claude's slug encoding replaces
a path separator with a hyphen, so a directory whose own name contains a
hyphen is indistinguishable from two nested directories -- `<name>-<suffix>`
and `<name>/<suffix>` produce the same slug. `helpers.slug_to_path` consults
the filesystem to choose a reading; `project.slug_to_path` did not, and
decoded a real hyphenated directory to a nested path that does not exist.
Production imported the correct one and only tests imported the weaker, which
is why nothing failed. `project` now re-exports `helpers`.

This is the case that argues against acting on a dead-code report
mechanically: the *unreferenced* copy was the correct one, and deleting it
would have kept the defect.

**The surviving decoder was also weak, in a way the duplicate hid.**
Consolidating onto `helpers` fixed the disagreement but not the decoding.
The retained fallback rejoined only the final two segments, so it covered a
hyphenated directory one level below its parent and nothing deeper. Measured
against the eighteen real Claude slugs on the development machine, **four
decoded to paths that do not exist**: three whose directory names contain a
hyphen at a depth the fallback did not reach, and one worktree slug carrying
hyphens at four depths. The failure was silent, because a
misdecoded path and a deleted Project are both just a `Path` that does not
exist -- the decoder could not tell a caller which it had produced.

The exposure is bounded by how discovery works. `walk_sessions` prefers
`sessions-index.json`, which records the working directory directly, and
falls back to the slug only when there is none. Six of the eighteen slugs
carry that index; **twelve depend on decoding alone**, including the
worktree slug and two of the hyphenated names. Discovery output is unchanged by
this work, since the wrongly-decoded paths did not exist and were dropped
either way. What changes is that a caller can now distinguish the two cases.

`resolve_slug` replaces the guess with a filesystem walk. It matches slug
tokens against directories that exist, longest name first, so a literal
hyphenated directory is preferred over a nested reading, because a directory
that exists is better evidence than a split that happens to parse. All fourteen live Projects resolve, at
0.09 ms each, and the four whose directories are gone return `None`.
`slug_to_path` keeps the naive split as a fallback so existing callers still
receive a value; the two are separate precisely so a caller acting on the
path can tell a resolved directory from a guess, which one function
returning a `Path` cannot express.

*Traversal was bounded before the change and is now structurally excluded.*
A slug segment reading `..` decoded to a real parent reference -- the old
decoder read a directory legitimately named `..-evil` as `../evil` -- but
`walk_sessions.in_work_root` resolves before comparing, so an escape from
the configured work root was already refused. The residual exposure was
misattribution *within* the root: `A-..-B` decoded to `A/../B`, which
resolves to `B`, so Sessions could be attributed to a sibling Project. The
walk removes that class rather than filtering it, since it only ever
descends into directories that exist and matches `..` as a literal name,
which no filesystem provides.

One of its findings was correct to *reject*. `config.BKB` and `config.BGB`
are unused, but they are the inverse half of a converter set whose forward
half is used, and an incomplete set invites the next caller to write
`/ 1024` inline -- which is precisely how one conversion acquires several
spellings. The right change was isolation rather than deletion: all six
converters now live in `codess/units.py`, which owns the conversion, with
`config` re-exporting them because callers have long imported from there.
A tool that reports an asymmetry has not thereby said which side to remove.

Two conclusions carry back to the constant method. First, applying it to
calls is worthwhile precisely because a call hides a decision that a
literal exposes -- `1024 * 1024` is visibly a number to agree on, while
`hashlib.sha256(x.encode())` looks like an implementation detail until two
sites encode differently. Second, 3.5.3's warning still governs: a shared
helper is justified by a shared decision, not by syntactic similarity. That
is why `codess/hashing.py` offers four modes rather than one function --
streaming, canonical-document, in-memory, and component derivation are
genuinely different operations, and collapsing them would repeat the false
consolidation 3.5.3 rejects. It is also why the 12 incremental digest
constructions keep their read policy in `fileio`: only the digest
construction was a shared decision, not the bounded-window sampling around
it.

### 1.5 Coupling and Separation of Concerns

The audits above work upward from individual values. Two further passes
look at the codebase as a whole -- one from repeated values, one from module
dependencies -- and they converge on the same modules.

**Bottom-up: repeated literals mark absent vocabulary.** Bare strings
recur across many modules, but they are not one problem. Three groups behave
differently and warrant different treatment:

| Group | Examples | Failure mode | Treatment |
|---|---|---|---|
| CoSchema field names | `project_id`, `session_id`, `event_kind`, `snapshot_id` | A typo yields a silently missing value, since `dict.get` returns `None` rather than raising | Leave as literals; see below |
| Closed vocabularies | Actor kinds, origin kinds, content roles, status values, raw modes | An invalid value is accepted and stored, corrupting a controlled vocabulary | Named constants or an enumeration |
| Vendor keys | `cc`, `codex`, `cursor` and their display forms | A missed site silently omits one vendor from an operation | Bundle; see the Vendor discussion below |

**Resolution for field names: keep the literals, add a contract test.**
Three reasons, in order of weight.

First, the indirection loses information. `row["project_id"]` names the
column it reads; `row[FIELD_PROJECT_ID]` names a constant that names the
column, so every reader resolves one extra hop to learn the same fact. That
is the cost 3.5.3 warns about for constants, and it applies with more force
here because the literal *is* the documentation.

Second, constants would not catch the actual failure. A misspelled key fails
because `dict.get` returns `None` rather than raising, and a constant only
moves that risk to whether the right constant was chosen -- `FIELD_SESSION_ID`
where `FIELD_SOURCE_ID` was meant reads as plausibly as the literal would.
Neither form is checked at the point of use.

Third, the real exposure is different from what constants address. These
names are a published contract that CoSchema declares, restated at every use
with nothing connecting declaration to use, so a schema rename is a
search-and-replace with no mechanical check. A test asserting that every
field name used in a query exists in `contract.json` closes exactly that gap,
catches the misspelling case that constants do not, and leaves the call sites
readable. That is the better trade, and it belongs with the mechanical checks
in 13.5 rather than with a renaming pass.

Closed vocabularies are the opposite. Their values are enumerated in
CoSchema and validated at the store boundary, so a wrong literal is a
correctness defect rather than a typo, and the set is small enough that
naming it is genuinely clarifying. These are the ones worth extracting.

**Which vocabularies are actually closed, on inspection.** The examples this
table originally listed -- Actor kinds, origin kinds, content roles -- are
not among them. `contract.json` declares all three `open_vocabulary`, and
CoSchema 6 states the rule directly: "Common classifications remain open
where vendor evidence can introduce useful new values. Closed taxonomies are
used only where stable query behavior requires a bounded vocabulary."
Extracting them as enumerations would have contradicted the design and
rejected the new vendor evidence they exist to admit. The premise was right
and the examples were wrong, which is worth recording because the examples
are what an implementer would have acted on.

The genuinely closed sets are the ones the DDL enforces with a `CHECK`, and
of those only **raw modes** were duplicated: `none`, `reference`, `capture`,
`seal` were written out longhand at nine sites, including one already named
`RAW_MODES` in `raw_store`. That is exactly the stated failure mode -- a mode
added at one site would have been accepted by some boundaries and rejected by
others -- and it now has one owner in `config`, with `raw_store` re-exporting
it as a set. The five rejection messages that each spelled the valid list
into their own prose share one formatter, so adding a mode is one edit rather
than eleven.

`normalized_status` is the instructive non-case. Its eight values look like
the same shape, but the literals in `store._normalized_status` are *source*
values being mapped -- `complete`, `success`, `error` as vendors write them
-- not the closed vocabulary, and the normalized outputs are already enforced
by the column's `CHECK`. Extracting there would have named a vendor's
spelling as if it were Codess's own.

**Vendor keys are a third case, and the strongest.** The three-vendor key
set appears across command modules, discovery, refresh, review, and Project
handling, in several shapes: as a set of valid keys, as key-to-display-name
mappings, and as the reverse mapping. `store.SOURCE_PROFILES` already models
a vendor properly -- source system identity, vendor and product names,
harness, storage format, surface kind, and mapping profile, keyed by display
name -- but it is private to `store` and describes only the fields `store`
needs, so every other module re-derives its own partial view.

A shared vendor description is the natural consolidation, and the existing
table is most of it already. The question is its shape. A frozen dataclass
per vendor, exposed as one vendor table, would give every module the same
fields, make the key-and-display-name pairing a property rather than two
mirrored dictionaries, and turn "iterate the vendors" into iterating a
collection rather than repeating a literal set. It would also give the
per-vendor paths, environment variables, and store filenames -- currently
scattered -- one place to live.

**Where vendor-specific and common concerns actually sit.** The intended
layout is a narrow vendor-specific layer under a common model:

```text
  vendor-specific          common                       consumers
  ───────────────          ──────                       ─────────
  adapters/cc.py    ─┐
  adapters/codex.py  ├──►  candidate records  ──►  store ──►  query
  adapters/cursor.py─┘         (CoSchema)                      CLI

  cursor_source.py  ── vendor storage access ──┘
```

The measured reality diverges: vendor names appear well outside that layer,
so the three change scenarios cost very differently.

| Change | Touches | Assessment |
|---|---|---|
| Improve handling for one vendor | That vendor's adapter, sometimes `cursor_source` | Correct and cheap. The adapter layer works as intended |
| Add a processing step for every vendor | All three adapters, plus `store` if the common model gains a field | Reasonable. Repetition across three adapters is the cost of keeping vendor decode separate, and is preferable to a shared decoder with per-vendor branches |
| Add a fourth vendor | Sixteen files, including every command module, `config`, `walk_sessions`, `project`, `snapshot`, `evidence`, `token_usage`, `storage_report`, and `schema_contract` | The defect. Most of those files need only a *description* of the vendor -- its key, display name, paths, store filename -- not knowledge of how it decodes |

The third row is the argument for W24. The adapters are legitimately
per-vendor and would still be written for a new vendor; what should not be
required is editing a dozen unrelated modules that merely enumerate vendors.
Once one vendor table supplies keys, display names, paths, and store
filenames, adding a vendor becomes: write an adapter, add a table entry, and
add a mapping profile. The rest iterate the table.

**Partitioning beyond vendor coupling.** Reviewing the same 32 files for
structure rather than vendor names surfaces three problems the vendor table
does not address.

*Command modules are the largest code in the tree, and hold domain logic.*
`cli/ingest_cmd.py` is the biggest module at roughly 2,000 lines across
about twenty functions -- an average near a hundred lines each -- and
`cli/query_cmd.py` is third largest. A command module should adapt
arguments, call a domain operation, and render a result; these run ingest
workflows and report SQL directly. This is W06, and the size measurement is
the argument for prioritizing it: the two largest modules in the codebase
are both in the layer that should hold the least.

W06 has since closed on exactly this reading. `ingest_cmd` is about 1,400
lines and `query_cmd` about 1,350, with the workflows in `ingest_sources`,
`ingest_publication`, and `query_reports`; neither command module decodes a
source, opens a publication transaction, or writes a report query. The
measurement above is retained as the state that motivated the work.

**One defect keeps reappearing under different names, and the items that
describe it should be read together.** Each was found by a different route
and each is a face of the same thing: state whose lifetime is not expressed
by the structure holding it.

| Item | Where it shows | Status |
|---|---|---|
| **W06** step 4 | `opts` mixed three lifetimes -- run-wide inputs, run-wide collectors, per-Project state -- in one dict every adapter takes whole | Complete: `ProjectScope` names the per-Project half, so the lifetimes are distinguishable at a call site |
| **W45** | `_ingest_project` took 17 parameters and `_cursor_preflight` 10 -- **5 accumulators and 12 read-only inputs**, the same three lifetimes hoisted from the dict into a signature | Complete |
| **Phase extraction** | It found three calls to `run`'s `cleanup_cursor_cohort` closure from functions where it no longer resolved, plus a bare `1` where a tuple was required -- all correct while the state was implicit in one scope | Complete |
| **W38** | `query_cmd` assembles 27 rows by hand because no object owns "a report row" | Planned |
| **W42** | `codex.process_file`'s 27 `None` guards are the absence of a type that says "content, or dropped by policy" | Planned |

The order held, and both are now closed. **W45 and W06 step 4 were one
change**: `IngestConfig` and `RunTotals` took `_ingest_project` from 17
parameters to 10, and `ProjectScope` finished it by naming the per-Project
lifetime as a type rather than seven keys a reader had to recognize. The
`opts` dict itself stays, because the adapters take it as their diagnostics
sink; what changed is that its three lifetimes are no longer
indistinguishable at a call site.

**W46 followed W45, as required.** The Cursor selection-marker decision --
cache load, scan on miss, container-stability bracket, cache save -- moved to
`cursor_cohort.resolve_selection_markers`, which is the module that declares
it owns Cursor caching. The command now reports what it resolved. Three
statuses (`reused`, `scanned`, `scanned-unstable`) were previously reachable
only by running an ingest against a live Cursor database, and the unstable
branch could not be reached deliberately at all; all three are now unit
tested, and both cache branches were verified against the real Cursor store
(102 ms scanned, 1 ms reused).

*Two modules mix a store with its policy.* `store.py` combines connection
and transaction handling, per-vendor profile data, and event-mapping rules;
`query_api.py` combines request validation, SQL construction, multi-store
merge, and result shaping. Both are cohesive by subject and hard to read by
size. The useful split is by *phase* rather than by entity: validation,
construction, execution, and shaping are separable in `query_api`, and
profiles, schema access, and write operations are separable in `store`.
Neither should be split by vendor or by table.

*Related modules are fragmented without a package.* `codess/` holds around
sixty flat modules including four Cursor-specific ones, three catalog
modules, and three baseline modules. Flatness is a deliberate choice
recorded in 2, and it should not be abandoned wholesale, but a subpackage
per genuine cluster -- as `adapters/` and `vendor_audits/` already are --
would make the dependency direction visible at the file tree rather than
only in imports.

*What not to do.* None of this is an argument for splitting by size alone.
`adapters/codex.py` and `adapters/cc.py` are large because vendor formats
are large, and dividing them would spread one format's decode across
several files for no gain. Size is a symptom worth investigating, not a
defect in itself; the defect is a module doing work that belongs in another
layer.

**Proposed reorganization.** The pieces of a vendor description already
exist; they are split across three owners and then re-derived by every
consumer:

| Fact | Currently owned by | Re-derived in |
|---|---|---|
| Key (`cc`) and display name (`Claude`) | Nowhere; mirrored dictionaries | Command modules, discovery, refresh, review |
| Source system identity (`anthropic.claude-code`) | `store.SOURCE_PROFILES` (private) | `token_usage`, `storage_report` hardcode the strings |
| Vendor storage paths | `config` (`CC_PROJECTS`, `CODEX_SESSIONS`, `CURSOR_DATA`) | `evidence` hardcodes `~/.codex/sessions` again |
| Store filename (`sessions_cc.db`) | `config` (three constants) | `get_store_path` maps display name to constant |
| Mapping profile name | `store.SOURCE_PROFILES` | Adapter tests |

One `vendors.py` module should own all five, as a frozen dataclass per
vendor exposed through an ordered table:

```text
codess/vendors.py
    @dataclass(frozen=True)
    class Vendor:
        key            "cc"                     # CLI and internal selector
        display        "Claude"                 # store-set and report label
        system_id      "anthropic.claude-code"  # CoSchema source_system_id
        product        "claude-code"
        harness        "claude-code-cli"
        storage_format "claude-jsonl"
        surface        "cli"
        mapping        "claude"                 # released mapping profile
        store_db       "sessions_cc.db"
        source_roots   (CC_PROJECTS,)           # from config, not duplicated

    VENDORS: tuple[Vendor, ...]
    by_key(key) / by_display(name) / keys() / displays()
```

The dependency direction stays correct: `vendors` imports `config` for
paths and is imported by everything else, so it is a leaf beside `config`
and `fileio` rather than a new hub. `store.SOURCE_PROFILES` becomes a view
over the vendor table rather than a second source of truth.

**What the refactor changes, by group.** The earlier "sixteen files" figure
was the subset that must change to *add* a vendor. The full footprint is
larger: 32 files name a vendor at least once. Counting them by role shows
why the groups are not multiples of three -- vendors are not represented
symmetrically.

| Group | Files | Vendor references | After the vendor table |
|---|---|---|---|
| Decode | 8 | Heaviest per file | Unchanged. Vendor-specific by design |
| Enumerate | 17 | 3 to 27 each | Iterate `VENDORS`; most drop to zero references |
| Dispatch | 4 | 4 to 138 | Resolve `--source` to a `Vendor`, then pass it |
| Incidental | 3 | 1 to 2 | A stray name in a docstring or constant; no change needed |

Three asymmetries explain the shape. Cursor needs more decode files than the
others (`cursor_source`, `cursor_cohort`, `cursor_feature_audit`) because it
is the only vendor whose storage is a shared SQLite database rather than
per-session files, so selection and caching are separate concerns. Claude
Code and Codex have feature-audit modules while Cursor's sits elsewhere.
And `cli.ingest_cmd` alone carries 138 references -- more than every
adapter combined -- which is not a vendor property at all but the command-
layer concentration W06 tracks.

**Expected reduction.** The vendor table does not delete files; it removes
knowledge from them. The 17 enumerate files should drop to near zero vendor
references, since almost all of what they name is description rather than
behavior. The 4 dispatch files retain argument validation only, and shrink
much further now that W06 has moved their workflows into domain modules. The 8
decode files and 3 incidental ones are unaffected. So the count of files
naming a vendor should fall from 32 to roughly 11 -- the decode layer plus
the vendor table itself -- and the count that must change to add a vendor from
16 to 3.

**Naming: not a registry.** `codess/vendors.py` is unrelated to
the *registry* in the operational sense -- the central `~/.codess` store of
Project records, bindings, and snapshots. That collision is exactly the
vocabulary hazard 14.3 records for overloaded terms, so the module should
not be called a registry in prose or in code. `VENDORS` as an ordered tuple
with lookup helpers needs no collective noun; where one is unavoidable,
"vendor table" or "vendor descriptions" avoids the clash.

**Cursor SQL is a separate axis, and now closed.** W10 concerned *where
vendor SQL lives*, not which modules know vendor names, and it is complete:
`cursor_source` owns every vendor-table query and connection, and
`adapters/cursor.py` has no SQL and no SQLite dependency. The adapter asks
for records by path (`read_composer_data`, `open_bubble_rows`,
`open_message_request_context_rows`) and decides only what they mean. Its
remaining `cursorDiskKV` mentions are record-type labels retained as source
evidence, which is correct.

That leaves W24 free of interference: W10 pushed vendor-specific *access*
down into the source layer, while W24 pulls vendor-specific *description*
out of unrelated modules. The Cursor module partitioning the closed boundary
made assessable was W26, now settled: the four-way split holds, and the one
module that spanned two concerns was corrected (6.4).

**Sequencing.** W24 is unblocked. W06 was complementary rather than
blocking -- the vendor table reduces what command modules *know* about
vendors, while W06 reduced what they *do* at all -- and is now complete, so
W24 runs against a command layer that no longer holds the workflows. The
vendor references remain, since moving a workflow does not remove a name:
`ingest_publication` carries its own vendor table, which is one of the
partial views W24 consolidates.

What it must not become is a home for vendor *behavior*. Decoding differences
belong in the adapters, and a vendor table that starts holding decode callbacks
recreates the vendor mixing 3.5.5 identifies in the command layer, only
centralized. The boundary is that the registry describes vendors and the
adapters interpret them, which is the same separation W10 established for
Cursor source access.

**Top-down: command modules concentrate every concern.** Measuring how many
`codess` modules each module imports gives a direct reading of where
concerns collect:

| Module | Imports many `codess` modules | Also mixes |
|---|---|---|
| `cli.admin_cmd` | Highest fan-out in the tree | Catalog, retention, snapshot, and reporting workflows |
| `cli.ingest_cmd` | Nearly as high | All three vendors by name, plus transactions, raw capture, and publication |
| `cli.query_cmd` | Third | Report SQL alongside argument adaptation |

This is the same finding as **W06**, recorded here with a measurement behind
it rather than an impression; the workflow half is now resolved, and the
vendor-naming half is W24's. The vendor mixing is the sharper half: `cli.ingest_cmd`
names Claude Code, Codex, and Cursor throughout, so adding or changing a
vendor means editing a command module. `store` and `walk_sessions` mix
vendors too, but for a defensible reason -- they implement the common model
over all three, which is their purpose. The test is whether a module *decides*
per vendor (a concern that belongs in an adapter or source module) or merely
*dispatches* across them.

By contrast the most-imported modules are `config`, `fileio`, and `hashing`.
Shared leaf utilities with high fan-in and no fan-out are the intended
shape, and their prominence is evidence the dependency direction is right
even where the command layer is not.

**What this does not justify.** Neither pass is an argument for splitting
modules by size. `project_catalog` is large and contained two functions over
a hundred lines each (`ensure_project_binding`, `catalog_readiness`), which
was worth reducing -- but by extracting the steps those functions perform,
not by dividing the module, since catalog identity, locations, and readiness
are one concern. The failure mode to avoid is the one 3.5.3 records for
constants: rearranging structure without removing a shared decision leaves
the same coupling with more files to read.

**Module count, measured rather than estimated.** The related worry -- that
there are too many files, some barely holding code -- was checked by counting
*code* lines with comments, docstrings, and blanks excluded. Eight of
seventy-one modules fall under forty: three package markers, `codess/__init__`
(1), `processing_contract` (3), `path_label` (28), `tool_identity` (31), and
`context_content` (32). The high comment ratio is intentional --
`processing_contract` is three constants with the reasoning for each -- so a
low code count is not itself a finding.

Fan-in settles it. `processing_contract` is read by six modules, so merging
it into one would make the other five import that module for a constant:
coupling raised to remove a file. The same holds for `identity` (6),
`context_content` (4), and `tool_identity` (2). `path_label` is the only
genuine candidate at 28 code lines and exactly one importer, and it is left
alone because the file is coherent and the merge would save nothing but a
name. The measurement is recorded in
`experiments/structural-analysis-tools.md`; the conclusion is that file count
is not this codebase's problem, and per-function complexity is.

Both are now reduced to their named steps, extracted within the module as
that reasoning requires. `ensure_project_binding` reads any retained binding,
resolves the identity, rebuilds the entry from the observation, and persists;
`catalog_readiness` assesses whether a Project can be queried, composes its
record, and summarizes. Each step is separately testable, which is what made
the identity-resolution order -- binding first, then a catalog entry already
claiming the path, then a new identity -- assertable rather than implied.

The decomposition also exposed a defect the length had concealed. The
function called `datetime.now(UTC)` three times while recording one
observation, so a single logical event could be stamped at three different
instants; the value is now computed once and applied to the entry, the
location, and the catalog together. This is the same failure the removal of
the `_now` wrappers found in this module's other write paths (14.4), which is
evidence for the general point rather than a coincidence: a hundred-line
function hides repeated calls that a four-step one does not.

**Swept for elsewhere, and found twice more.** Because the same defect had
now appeared in two unrelated places, the codebase was checked for functions
that read the clock more than once. Most such functions are correct -- a
started/completed pair, a created/updated pair, and a per-item stamp inside a
loop are genuinely different instants, and collapsing them would be the
opposite error. Two were not:

| Site | What was stamped twice | Why it matters |
|---|---|---|
| `baseline_operations.archive_stale_working_stores` | The archive directory name and the manifest's `archived_at` | The directory is what an operator sorts by, and it could name a different second than the manifest inside it |
| `retention.apply_retention_plan` | The receipt's `applied_at` and the receipt's own filename | A receipt exists to correlate an action with its record; a file named a different instant than its contents defeats that |

Both now compute the instant once and render it twice, and both have a test
asserting the name and the contents agree. The shape is worth naming: the
defect appears wherever one event is written to two places, because the
second write is usually added later and reaches for the clock again rather
than for the value the first write used. The rule that follows is narrow --
*one recorded event, one clock read* -- and it does not extend to intervals
or to per-item stamps, where two reads are the point.

## 2. Observed Process Misses

Specific misses observed during real review and implementation sessions -- in
evaluation, in documentation, and in code -- with the instruction that would have
caught each one earlier. Not a style guide: every entry traces to an actual
incident.

**Grouped by what fails, and ordered within each group by how often it has
recurred.** A flat list of eleven entries could not answer "which of these keeps
happening", which is the question that decides where a standing instruction is
worth its cost. Entries are not removed when the underlying miss is fixed -- the
record of the mistake is what has future value.

### 2.1 Incomplete Sweeps

*The most frequently recurring group: a fix applied to the instance in hand and
not to its siblings.*

### 2.1.1 Duplication Findings Not Propagated to Siblings

**Miss:** `LARGE_STORE_BYTES` was centralized from `project_annotations.py`
into `config.py` as part of a fix for a confirmed 128 MiB duplication
cluster. `DEFAULT_LARGE_EVENT_COUNT`, its immediate sibling constant in the
same file, same function signature, same "large" semantics, was never
checked against the same criterion and was left behind -- an inconsistency
that persisted across several further edits to the same file before being
caught, on direct question, much later in the same session.

**Prompt that would have caught it:** "When centralizing one constant out
of a module because it duplicates elsewhere, also check every other
constant defined in the same few lines for the same criterion, not just the
one already flagged. A sibling constant left behind is a new inconsistency,
not a smaller version of the one just fixed."

### 2.1.2 One Confirmed Fix Pattern Not Swept Across All Structurally Identical Sites

**Miss:** A CLI-argument-default-vs-owning-constant mismatch was found and
fixed at one site (`--large-bytes`/`--max-record-bytes` in `admin_cmd.py`),
closed as resolved, and then found again independently three more times in
the same file (vendor-path defaults, `--large-events`, `--max-files`)
across later turns, each requiring its own separate discovery rather than
being caught by one exhaustive sweep after the first instance.

**Prompt that would have caught it:** "When a fix corrects one instance of
a named pattern (e.g. 'CLI default duplicates a constant defined
elsewhere'), immediately grep the same file, then the same layer
codebase-wide, for every other instance of that exact pattern shape before
considering the finding closed. Fixing one occurrence and moving on treats
a systemic fault as a local one."

### 2.1.3 A Wrong Conclusion Repeated Into Four Places Before Being Checked

**Miss:** Having found the ignores, the next claim was that they "have no
effect" because `S` is not in ruff's default set. That was asserted from
reading the configuration rather than running it, then written into a work
item, a section of analysis, a completion criterion, and a miss record --
each restating the previous one. One command settles it: selecting `S`
reports 73 findings without the ignores and 17 with, so they suppress 56.
The correction had to be applied in four places because the claim had been
propagated before it was tested.

**Prompt that would have caught it:** "Test a claim about what a tool does
before writing it down once, let alone four times. A statement that some
configuration is inert is a claim about behavior, and behavior is checked by
running it. Propagating an untested claim multiplies the correction."
### 2.1.4 A Rename Applied by Substring, Reaching a Call Site It Should Not Have

**Miss:** Renaming a dataclass field from `source` to `vendor_selector` was done
with a text replacement over three modules. The pattern matched two calls to
`_run_ingest_stage`, a *different* function that still took `source=`, producing
`Unexpected keyword argument`. The same session had already made this mistake in
a different form: renaming `tool_use_id` in a definition also rewrote it inside a
call, producing a `SyntaxError`.

**Prompt that would have caught it:** "A rename is applied to declarations and to
the call sites of *that* symbol, not to every occurrence of the word. Confirm the
count of intended sites before replacing, and re-run the type checker after --
a keyword that no longer matches its callee is invisible to the test suite until
that path executes."


### 2.2 Evidence and Verification

*A conclusion asserted, restated, or drawn from a search that could not have found
the answer.*

### 2.2.1 A Finding Reclassified on Assertion Rather Than Evidence

**Miss:** The software version being lower than values already recorded in
published stores was reported as a defect. Told the reset was deliberate, the
item was rewritten as intentional on that assertion alone, without checking.
The record showed a bare one-line edit with no rationale, and stores in the
field whose provenance read higher than the software that would rebuild them:
deliberate at the moment it was made and still a defect in effect. The
rewrite lost the effect and had to be corrected a second time.

**Prompt that would have caught it:** "When told that something reported as
a defect was intentional, check the record before reclassifying it. Intent
and effect are separate findings: an edit can be deliberate and still leave a
broken invariant, and the useful item names both. Reclassifying on assertion
turns a verified observation into an unverified one."

### 2.2.2 Configuration Reported Absent After a Grep That Could Not Find It

**Miss:** `pyproject.toml` was reported as having no ruff configuration,
based on a clean lint run and a grep for `[tool.ruff]` written to match only
a top-level table. The file declares twelve per-file `S608` ignores under
`[tool.ruff.lint.per-file-ignores]`. Reading the file would have taken one
command; the grep pattern encoded an assumption about the table's name and
returned nothing, which was then read as evidence.

**Prompt that would have caught it:** "Before reporting configuration as
missing, read the file. A grep that finds nothing proves the pattern did not
match, not that the setting is absent, and configuration formats nest."

### 2.2.3 A Proposal Restated Until It Read as an Approved Rule

**Miss:** A naming rule -- `_id` for entities, `_key` for lookups,
`_hash` for integrity claims -- was proposed in one section, then referenced
from later sections as though it were settled, and finally used as the
justification for a work item's completion criterion. Nobody had approved it.
The same happened with a replacement for "package": one candidate was called
"the closest", which read on re-reading as a recommendation.

**Prompt that would have caught it:** "Mark a proposal as unapproved every
time it is restated, not only where it is introduced. A rule referenced
three sections later reads as decided, and the reader has no way to tell that
it was one option among several."
### 2.2.4 A Design Rationale Asserted From Reading Two Sites, Not All Five

**Miss:** The rule for which sinks drop an absent field was stated as a per-sink
difference after reading two of five sinks. Testing all five showed the rule
follows the *form of the output* rather than the sink -- `BridgeSink` drops in its
rendered message and keeps in its structured `extra`, so it sits on both sides at
once, which the two-site reading could not have revealed.

**Prompt that would have caught it:** "Before stating a rule that distinguishes
members of a set, exercise every member. Two examples establish a pattern and
cannot establish its boundary."

### 2.2.5 A Correction That Overcorrected, Hiding the Defect It Was Fixing

**Miss:** A result digest compared unequal across two runs because it included the
temporary directory each used. The fix excluded location fields outright -- which
then made a query returning a *different Project's rows* compare EQUAL, silencing
exactly the defect a comparison exists to find. The right fix rewrites the path
relative to the run root, removing what differs by construction while keeping
what the value says about the result.

**Prompt that would have caught it:** "When excluding a field from a comparison,
state what real difference the exclusion now hides, and check that case. An
exclusion is a claim that the field carries no information; verify the claim
rather than assuming it from the one case that prompted it."

### 2.3 Scope and Instruction Handling

*Work requested and not done, or proposed and treated as approved.*

### 2.3.1 A Requested Follow-Up Section Not Actually Created

**Miss:** A request to "add a Prompt Ideas subsection" was acknowledged in
conversation but not translated into an actual document edit or tracked
task -- the acknowledgment was mistaken for the deliverable. The gap was
only caught when the requester asked directly why the earlier "revisit"
comment had not resulted in a task.

**Prompt that would have caught it:** "Before ending a turn that included a
request to add, create, or track something, grep the actual target
document or task list for the artifact just claimed to exist. A sentence
describing an intention is not the same event as the edit that fulfills it,
and only the edit is verifiable."

### 2.3.2 Related Work Split Into Separate Items That Cannot Be Scheduled Apart

**Miss:** Rule selection, the `S608` exemptions, and reducing SQL
interpolation were filed as three items across two priorities. They are one
decision: selecting `S` determines whether the exemptions matter, and
reducing the interpolation determines how many exemptions remain. None can
be completed without settling the others, so three items produced three
partial descriptions of one piece of work and no schedulable unit. It took
being asked why they were separate to notice.

**Prompt that would have caught it:** "After writing several work items in
one area, ask whether any could be finished without the others. If not, they
are one item with parts, and splitting them hides the dependency rather than
recording it."

### 2.3.3 Naming Decisions Made From the Function in Isolation, Not Its Call Site

**Miss:** Early proposals for renaming `catalog.py`'s functions (`scan_`,
`verify_`, `review_`-prefixed candidates) were generated by inspecting the
function bodies alone; each was independently rejected only after the
actual caller (`candidate_review.py`, later `review_project.py`) was read
in full and its real usage pattern -- call frequency, which fields the
return value populated, what the caller's own docstring already claimed --
was checked against the proposed name.

**Prompt that would have caught it, applied earlier:** "Before proposing a
name for a function or module, read every caller's actual invocation
first, not just the function's own signature and docstring -- a name is a
claim about the relationship between a function and its consumers, and
that relationship is only visible from the consumer side."
### 2.4 Collateral Damage

*A change correct in itself that silently broke something adjacent.*

### 2.4.1 A Documentation Diagram's Layout Silently Corrupted an Unrelated Paragraph

**Miss:** Inserting a new subsection (3.4) into CoPlan.md by appending
after a chosen anchor point placed it before a closing paragraph that
belonged to the *previous* section (3.3), silently detaching that paragraph
from its own section and reattaching it to the end of the new one. The
error was only caught later, incidentally, while re-reading the document
for an unrelated addition.

**Prompt that would have caught it:** "After inserting a new section
between two existing ones, re-read several paragraphs on both sides of the
insertion point, not just the immediate anchor line -- a numbered-heading
insertion can silently reassign a trailing paragraph's section by moving
the heading boundary without moving the paragraph."

### 2.4.2 Format-String Value Changes Conflated With Python-Name Changes

**Miss:** Early in the `catalog.py`/`candidate_review.py` rename, module
and function renames were applied without a separate, explicit decision
about the `_FORMAT` constants' *string values* -- which are written into
real saved documents and are a compatibility surface distinct from Python
identifier names (established earlier, independently, for `RAW_FORMAT` and
`SOURCE_LINKS_FORMAT` in 3.4). The distinction had to be re-raised as an
explicit question rather than being applied automatically from the
already-established precedent.

**Prompt that would have caught it:** "A module or function rename and a
`_FORMAT`/wire-value rename are two different decisions with different
blast radii -- one is free, internal, and reversible; the other changes
what a previously saved document will validate against. State which one is
being changed, explicitly, every time either changes, even when a
precedent for the distinction already exists elsewhere in the same
document."

### 2.4.3 An Automatic Import Fix Removing an Import the Same Edit Had Just Required

**Miss:** Adding a type annotation and running `ruff --fix --select F401` in the
same step removed the `Any` import the annotation needed, because the autofix ran
against a file where the annotation had not yet been written. This happened three
times in one session, each time surfacing as a `NameError` at collection.

**Prompt that would have caught it:** "Run an automatic import fixer only after
every edit that changes what a module uses, never between them -- and re-run the
test suite rather than the linter to confirm, since an unused-import fix that
removes a *used* import is syntactically valid."
