# Changelog

Notable changes per released version. The authoritative version is
`codess.__version__`, reported by `codess --version`.

**A CoSchema format change requires a rebuild, not a migration.** Codess never
migrates a store: the store is a projection of vendor Sources, and the way to
change a projection is to recompute it. `require_store` accepts only the
current format for reading as well as writing, so after installing a version
that changes the format, run `codess ingest --force` for each Project and
republish. The cost scales with Project count rather than with the size of the
change, and is minutes of machine time for a corpus of this scale.

## Unreleased

### CoSchema Format 12

**Every published store must be reingested.** The contract digest changed, so a
format-11 store is refused. Gate on `python3 tools/project_inventory.py`, then
`codess refresh --designator included --stage apply --force`; see
[Keeping a Store Current](README.md#keeping-a-store-current). `--force` is what
makes a migration different from a routine refresh: without it every Project
fails on the working store the format change just made unreadable.

- **`product` is removed in favour of `harness_name`.** The mapping contract
  required a second spelling of one fact: `product` named the program, which
  `harness_name` already holds. It was the last instance of a defect fixed twice
  before -- `sessions.product_name` dropped as a pure function of the source
  system, and `harness_name`'s surface suffix removed. Cursor's value changes
  with the rename, `cursor-composer` to `cursor`, because `composer` named a
  surface that `surface_kind` carries in its own column.

  The composition rule it was documented to serve never held: `vendor + "." +
  product` composes `cursor.cursor-composer` against a stored `cursor.composer`.
  `source_system_key` is a per-vendor constant that two of three vendors matched
  by coincidence, and CoNames now says so.

- **The algorithm's name is confined to `hashing`.** Format 11 moved the
  `*_sha256` field names; this moves the two shapes a field-name survey could not
  see. A nested `"sha256"` **key** in each `manifest.json` file and store entry
  is now `digest`. An emitted `sha256:` **value prefix** is now `digest:`, which
  reaches `request_hash`, `result_hash`, every citation digest, raw object ids,
  the raw object directory, and the worktree revision suffix.

  Five documents carry a version for it: `codess.query-result/2`,
  `codess.investigation/2`, `codess.query-row/2`, `codess.raw/2`,
  `codess.source-verification/2`, and `codess.working-archive/2`.

- **`sessions.source` is `adapter_key` in the query row too.** Format 11 renamed
  the column and left `codess.query-row/1` emitting it under the old key, so one
  value had two names one layer apart. `codess.query-row/2` states
  `adapter_key`, and the printed column headers match.

- **Two backward reads, each with a test per spelling.** A snapshot manifest's
  store entry and a `codess.raw/1` object id are read under either name, because
  both are read while the thing holding them is being verified or replaced.
  `store_claim` and `_object_hash` state this once each rather than at call
  sites.

- **An operator-written `source-links.json` is read under either key spelling.**
  `codess.source-links/1` states `source_system_id`, which became
  `source_system_key` in format 11. Codess never regenerates this file -- an
  operator writes it -- so the rename could not reach documents on disk, and an
  approved link silently stopped matching: the Sessions it admits are simply not
  selected, with no error and no diagnostic. Two real documents on the
  development machine were affected. `config.link_source_system` reads either
  name at all three call sites.

  The fixtures for this file were updated with the rename and kept passing, which
  is why the regression test writes the older key explicitly.

- **Cursor's `ItemTable` composer index is read as a qualifier.** Cursor keeps
  two composer indexes: the `composerHeaders` table selects, and
  `ItemTable`'s `composer.composerHeaders` is UI state over a subset of the same
  composers -- 39 against 66, all also in the table, agreeing on the workspace
  for every one. It carries two facts the table does not: `unifiedMode` (`agent`
  or `chat`, split 15/24) and the workspace **path**, where the table holds only
  a storage hash a workspace recreation would change.

  Both now qualify a selected Session. A composer present only in that document
  is still not selected -- UI state does not decide Project membership -- and a
  test asserts it. Neither field reaches a column yet; that is W106.

- **`CODESS_KEEP_SNAPSHOTS` defaults to 3, up from 2.** Two keeps one prior
  generation, and a format migration consumes it: two consecutive bumps left no
  retained copy of the pre-migration store, so a decode comparison across the
  migration could not be made. Three spans one migration.

- **`.python-version` pins the interpreter.** `pyproject.toml` states the
  supported floor; the new file states what the repository is developed against.
  Scripts should call `python3` rather than `python`, which is commonly an alias
  a non-interactive subshell does not inherit.

### CoSchema Format 11

**Every published store must be reingested.** Format 11 renames stored columns,
so a format-10 store is refused rather than read with the old names. Run
`python tools/project_inventory.py` first -- it exits nonzero when a Project's
vendor Sources are gone -- then rebuild the cohort with one command:

```bash
codess refresh --designator included --stage apply
```

`codess ingest --dir <project> --force` rebuilds a single Project. Prefer the
designator for the corpus: it preflights every Project before applying any and
writes a receipt, and it honours catalog exclusions such as a linked worktree.

**A direct-SQL reader must update three names.** The renames are mechanical and
the queries in [README](README.md#direct-database-access) show the current
spelling.

- **`sessions.source` is `sessions.adapter_key`.** The column holds a
  `SOURCE_PROFILES` key -- `Claude`, `Codex`, `Cursor` -- selecting which adapter
  decoded the Session. It is not the Source entity, not `sources.source_path`,
  and not one of the six `source_*` columns beside it that do state Source facts.
  One word had carried three meanings.

- **`source_system_id` is `source_system_key`,** in all three tables that hold it
  -- `sessions`, `sources`, `workspace_bindings`. The value is
  `vendor + "." + product` composed in the mapping profile, so it is a literal
  rather than an identifier something assigned. `_id` had denoted four
  incompatible formats: a rowid, a vendor UUID, a Codess derivation, and this.

- **Seven Codess-recorded time columns take `_when`:** `observed_when` on
  `sources`, `sessions`, and `project_locations`; `started_when` and
  `completed_when` on `processing_runs`; `created_when` on `mapping_diagnostics`;
  `asserted_when` on `correlation_assertions`. A suffix now states the
  representation -- `_at` is `REAL` Unix milliseconds, `_when` is RFC 3339 `TEXT`
  -- where before `started_at` was `REAL` in `sessions` and `TEXT` in
  `processing_runs`, so code reading both had to know which table it was in.
  `sessions.started_at` is unchanged and is why the rule is worth stating.

- **Twelve `*_sha256` fields are `*_digest`,** across snapshot manifests, current
  pointers, raw-object records, baseline selections, and reviewed catalogs. The
  algorithm's name lives in `hashing` alone: a value from
  `codess_canonical_hash(256, 256, …)` *is* a bare SHA-256 at those widths, so
  the old name read as accurate and would have silently stopped being so when a
  width changed. `manifest_sha256` appears in every `current.json`, which is why
  this travelled with a rebuild rather than alone.

  The pass found a name no count could: `schema/field-coverage-baseline.json`
  still documented `sources.content_sha256`, a column renamed in format 5.
  Nothing read it, so nothing had failed.

  `hashlib.sha256` keeps its spelling. The rule governs what a stored field is
  called, not the function that computes it.

- **`current.json` and a stored manifest are read under either spelling.** A
  rebuild reads the pointer it is about to replace, so a release that renamed
  `manifest_sha256` cannot also refuse the name the previous release wrote --
  doing so made all 21 published Projects unrebuildable by the one version that
  could rebuild them. `raw_manifest_sha256` in a stored manifest is the same
  case. Both accept either key on read and write only the current one, which is
  a rule for the files that bootstrap a rebuild and not a general alias.

- **Three tests hold the rules** rather than the instances: no column in any
  table names a hash algorithm, every `_at` column is `REAL` and every `_when`
  column is `TEXT`, and no table carries `source_system_id`. A check that lists
  the columns it knows about does not catch the next one added. The algorithm
  spellings come from `hashing.ALGORITHM_TOKENS`, so the checker does not keep a
  second copy of the list this rule exists to centralise.

- **The `sha256` spelling is confined to the hash library and to prose about how
  a digest is chosen.** Three test names still said `sha256` while asserting
  `digest-fingerprint` values; documentation in CoSchema, Designs, and
  CursorSchema named the algorithm where it meant "a complete digest"; and
  `Operations` and `CoPlan` still named `manifest_sha256`, a key that moved in
  this release. Text describing `manifest.json` keeps the literal `"sha256"` key,
  because an operator opening the file sees exactly that.

  Still live and now tracked on W98: a bare `"sha256"` **key** nested in each
  `manifest.json` file entry and snapshot store entry. A survey of `*_sha256`
  field names cannot see a key inside an object, which is why the format-11 pass
  missed it.

### CoSchema Format 10

**Every published store must be reingested.** `require_store` accepts only the
current format for reading as well as writing, so a store written under format 9
is refused until its Project is rebuilt: install the contract,
`codess ingest --dir <project> --force` each Project, republish. Run
`python tools/project_inventory.py` first -- it exits nonzero when a Project's
vendor Sources are gone, and a store whose Sources no longer exist is the only
remaining record of those Sessions.

- **`events.input_tokens` and `events.output_tokens`** retain recorded usage for
  all three vendors, **including when the vendor records zero**. A recorded zero
  says the vendor reported no usage, which is not the same as the field being
  absent, and only the first can be revisited when a release changes. Cursor
  writes `tokenCount` on essentially every bubble.

- **`events.duplicate_of`** names the Event a record repeats. A long-lived Cursor
  composer is re-synced and the sync writes server-identified copies of bubbles
  that already exist locally, so one `toolCallId` survives on two bubbles after
  dedup. Both are real vendor records -- field by field they differ in three
  fields of ninety-eight -- so the relationship is recorded rather than a record
  deleted. A reader wanting the raw count ignores the column; one excluding
  replays selects on it.

### Time

- **`codess.timeval` is the time subsystem**, and it is standalone by
  constraint rather than by convention: it imports nothing from `codess` and
  reads no ambient clock. `now_ms` takes the callable that reads the clock, so a
  receipt's timestamp does not depend on when the process ran. Two tests walk
  the module's syntax tree to assert both constraints, because a prose rule is
  one an edit can violate silently.

  It exposes what the previously scattered callers each hand-rolled:
  `epoch_ms` for a vendor scalar or ISO string, `parse_iso`, `iso_to_ms` and
  `to_iso` for the two stored representations, `month_key` for bucketing,
  `is_sane` for the plausibility gate, and `now_ms`/`now_iso` for the two
  representations of the current instant.

- **The callers are migrated and the compatibility alias has no importers
  left.** `walk_sessions`, `token_usage`, and `refresh_receipts` read the module
  instead of calling `datetime.fromisoformat` themselves, and the three adapters
  import `epoch_ms` rather than the `units` alias. `token_usage._month` is gone
  in favour of `month_key`, which validates by parsing rather than by slicing --
  `2026-13` has the shape of a month and is not one.

- **`now_iso` is the `_when` counterpart to `now_ms`**, taking the same injected
  clock. It exists because writing the stamp for a recorded observation is the
  commonest use of a clock in the package, and a caller forced to compose
  `to_iso(now_ms(clock))` writes `datetime.now` instead -- which is the ambient
  clock the module exists to remove.

- **`codess.wallclock.system_clock` is the one place the ambient clock is
  read.** 43 sites spelled `datetime.now(UTC).isoformat()` inline, so a test
  needing a fixed clock had 43 things to patch and patched none of them. A
  caller now writes `now_iso(system_clock)`: the injection point stays visible
  at the call site and the clock has one definition.

  It is a separate module rather than a `timeval` function because `timeval`'s
  constraint is that *nothing in it reads a clock*, asserted by walking its
  syntax tree -- and a function whose body is `datetime.now` is what that
  forbids, whoever calls it. A second test asserts the package has no other
  `datetime.now`, so the 43 spellings cannot creep back.

  `reporting.clock` is exempt and stays separate: it anchors monotonic ticks for
  event timing, where a backward NTP step would produce a negative duration.

  Four relay modules are exempt for now, listed individually in the test rather
  than matched by pattern: threading a clock into them changes the signatures
  the relay-consolidation work rewrites, so converting them first converts them
  twice.

- **A plausibility gate separates a reported instant from a counter that
  parses.** `is_sane` requires a converted value to fall within
  `[2020-01-01, now + 24h]`. Cursor's `timingInfo.clientStartTime` is the case
  it exists for: the field holds milliseconds since process start, so read as an
  epoch it lands in 1970 and would be stored as a 1970 instant.

### Decode

- **No adapter constructs an Event dict outside its builder.** Five sites
  bypassed one -- Claude's compaction, tool-call, user-text, and tool-result
  paths, and Codex's compaction path -- each spelling out the same sixteen keys
  inline. Claude now routes 21 constructions through `_base_event`, Codex 17,
  Cursor 3, with none outside.

  Two signature corrections were needed: `cc._base_event.subtype` had to admit
  `None`, which Codex's already did, and `codex._base_event` gained an explicit
  `event_id`, because a compaction record carrying several summaries needs an
  identity per Event rather than the line number that serves the single-Event
  case. Both were found by the type checker rather than by a test.

  Verified against real Sources: 23,470 Events from Claude and Codex
  transcripts decode byte-identically before and after, compared on identity,
  classification, content length, time, tool fields, and metadata. A suite that
  exercises the same builder on both sides cannot detect a change in what the
  builder produces.

### Checks

- **The format number is declared once per file that can be checked.**
  `schema/coschema/sqlite/schema.sql` carried it twice: `PRAGMA user_version`,
  which every check reads, and a header comment, which none did. The comment had
  drifted several formats behind while the pragma stayed correct. It now states
  where the number is declared rather than repeating it -- a number a check
  cannot read is not a declaration to synchronise but one to remove.

- **Every stored Event is validated against its source system's released
  mapping profile.** `validate_mapped_event` was written, exercised by four test
  modules, and reached from no production path, so the property it states -- that
  a stored `mapping_rule` is one the profile declares -- held by construction
  with nothing testing it. It now runs at one vendor-neutral point in
  `store.upsert_event`, so an undeclared rule meets the same disposition whether
  Claude, Codex, or Cursor produced it: a vendor that raises where another
  tolerates would give one conformance figure two meanings.

  The check is scoped to Events carrying a rule, since an Event without one has
  no profile to be measured against and the unmapped-semantics diagnostic
  already reports it. In diagnostic mode a non-conformance becomes a
  `mapping_profile_nonconformance` row; under `CODESS_STRICT_MAPPING` it raises.

- **The candidate-record contract is declared as a type.** `mapping.CandidateEvent`
  states the shape crossing the decode boundary rather than leaving it implied by
  three adapters agreeing. Its four required keys are the released contract's
  `mapped_event_required`; every other key is optional, because a decoder obliged
  to supply a key it has no evidence for would invent one.

- **`tools/project_inventory.py` reports whether a Project's vendor Sources
  still exist.** Operations documented `sources_vanished` as the column that
  decides retention and nothing computed it. The tool exits nonzero when any
  published Project holds vanished Sources, so it gates a rebuild rather than
  merely preceding one. Coverage has three values -- `complete`, `partial`,
  `purged` -- because a vendor prune removes transcripts individually, and
  reading it as two reports a partly purged store as intact.

### Reporting

- **Every command module attaches a sink and reports.** `admin` and `query` now
  call `reporting.configure` before dispatch and emit start and done events --
  INFO for the administrative pair, because each of those subcommands can
  delete, publish, or rewrite state and a run that reports nothing leaves an
  operator holding an exit code. One code per command family rather than per
  subcommand: 42 codes naming what `family` and `command` already carry as
  fields would be a second dispatch table beside the parser's.

  A failure reports on both channels. `command.failed` carries the exception
  family for a structured reader and `cli.failure` carries its text for the
  operator; a sink may be a file, and stderr is what a person is looking at.

  Both flush at the command boundary. The event ring holds 256 and neither
  command approaches it, so without a flush most runs would emit nothing at all.

- **All four command modules validate configuration before acting.**
  `admin_cmd` was the one that did not, and the one that writes most: a wrong
  store root or an unparseable bound reached it and it began deleting or
  publishing under it.

- **Every released manifest entry has a consumer.** Four validation fixtures
  were referenced by nothing but the manifest's own digest, so one could be
  emptied or corrupted and no test would fail. They are now resolved *through*
  `load_manifest` rather than by path -- a test opening a known path keeps
  passing after the manifest stops naming the file.

  Writing those tests found what an unreferenced fixture allows:
  `maximal/event` carries a `timestamp` field the `events` table has not had
  since it became `event_at`. It is still valid input, because `upsert_event`
  accepts the vendor spelling, but nothing had checked either way.

### Structure

- **Every relay takes an object, and the rule is a test.** `refresh_projects`
  went from 17 parameters to 4, `refresh_candidates` from 14 to 6,
  `apply_project` from 12 to 8, `onboard_catalog` from 10 to 7, and
  `_run_project_ingest` from 8 to 3. Three structures carry what they forwarded:
  `RunPolicy` describes what an ingest does, `DiscoveryPolicy` bounds a walk,
  `ChildInvocation` names one invocation's target -- and the three share no
  field.

  The distinction between a relay and a builder is measured rather than judged: a
  builder places its parameters into a returned literal, so its parameter list is
  the record's shape. `codex._base_event` takes 20 and places 14; converting it
  would name every field twice. A test parses `src/` and reports any wide
  signature that does neither.

- **Two traversal helpers replace eight call sites.** Five spelled
  `sorted(dir.glob("*.db"))` and meant *the stores in a snapshot*; three spelled
  a pair of globs and meant *Claude's transcripts, main and subagent*. What the
  helpers own is the layout knowledge -- that a delegated Session lives under
  `<parent>/subagents/` -- not the traversal: a call site that globs directly
  keeps working when the layout changes and quietly reports nothing.

- **`timeout_seconds` named two unrelated bounds** -- a child process's and a
  filesystem walk's. They are `policy_timeout` and `scan_timeout` now, with
  `--policy-timeout` and `--scan-timeout` to match. **Breaking** for both flags.

### Retention

- **`CODESS_KEEP_SNAPSHOTS` counts snapshots kept, current included.** 1 keeps
  only the current, 2 keeps it and one past, 0 keeps every one. The default is 2.

  Counting the total is what gives 0 its own meaning: a count of prior
  generations has no spare value -- "keep nothing past" and "keep everything"
  both want 0 -- and the two retention paths read that one value in opposite
  directions. One implementation, `snapshot.superseded_beyond_depth`, now serves
  both the trim that follows a publication and `codess storage prune`, and each
  takes a parameter as well as reading the variable.

- **`codess.retention-plan/3` names the rule and carries the count as a field.**
  `policy` is `keep-newest` with `keep_total` beside it, rather than
  `keep-2-per-project`: spelling the number into the name makes every value look
  like a separate policy when only 0 and 1 differ in kind.

- **`CODESS_SCAN_DEADLINE_SECONDS` is `CODESS_SCAN_TIMEOUT`**, and
  `--scan-deadline-seconds` is `--scan-timeout`. **Breaking.** A deadline
  is a point in time and the value is a duration; `ScanBudget`'s reported
  `stopped_reason` follows from `deadline` to `timeout`.

- **A relative store root is refused rather than replaced.**
  `CODESS_STORE_ROOT` of `.`, `..`, or `""` named wherever the command happened
  to run, and the resolver quietly substituted the default -- so a command
  succeeded against a store the operator had not chosen. `validate_config`
  reports it and `resolve_store_root` raises.

  Trailing and leading whitespace in a path is now preserved. It was stripped,
  and a directory named `store ` is legal on POSIX and distinct from `store`, so
  stripping retargeted the store to a different existing directory.

- **Six numeric variables gained bounds, split by what 0 means to each.** Two
  are disabled by 0 because their consumer guards with `if bound and ...`; four
  are not, because their consumer compares directly and 0 is the strictest
  possible bound -- `SOURCE_READ_MAX` of 0 reads nothing, a `byte_limit` of 0
  emits no rows. The two floors are checked separately rather than assumed
  equal.

- **`plan_sha256` is `plan_digest`, and the retention formats go to `/2`.** The
  rule that algorithm names live in `hashing` alone was already recorded and this
  field had not been reached by it. The value is what `codess_canonical_hash`
  returns, which is a bare SHA-256 *only because* the widths are currently
  256/256 -- so the name is accurate today and silently stops being so when a
  width changes.

  `codess.retention-plan/2` and `codess.retention-receipt/2`, because a `/1`
  consumer declares a field a `/2` document does not carry. No stored receipt is
  rewritten: a receipt records what happened under the rules of its own version.

- **The prune workflow is documented, including that it does not prune.**
  `codess storage prune` emits a plan and deletes nothing; `--apply` emits a
  receipt naming every path it removed. Operations now records the two-command
  shape, where the receipt lands
  (`~/.codess/receipts/retention/<applied_at>.json`), and the result keys of both
  documents -- a receipt carries `deleted.snapshot_paths` as a **list of paths**,
  with no `snapshots` count and no `applied` key.

### Configuration

- **One declaration per setting, and one stated precedence.** `codess.settings`
  holds a row per setting -- name, flag, environment variable, whether it
  composes, whether a leaf module reads it -- and `resolve` applies **flag, then
  variable, then built-in**, each narrower than the last. Four shapes answered
  that question before, at 162 call sites, and the commonest said nothing:
  `flag_or_env` (10), `getattr(...) or CONSTANT` (3), `bool(getattr(...))` (16),
  and a bare `getattr(args, name, None)` (133).

  A boolean composes rather than overrides, which is deliberate: a `store_true`
  flag cannot express *off*, so treating its absence as an override would make
  `CODESS_FORCE=1` unsettable from any shell that also passes flags. The `or`
  form additionally cannot express a zero -- `--days 0` means all time, and
  `0 or DAYS` is `DAYS`.

  The *value* of a default stays in `config`, which resolves it from the same
  variable at import. Putting it on the row as well would create the second
  declaration the table exists to remove.

- **The leaf-visible workaround is declared rather than hand-written.** `fileio`
  and `schema_contract` read their variable directly, because a leaf module
  cannot import `config` without a cycle, so a flag reaches them only by writing
  it. Two hand-written `os.environ[...] = "1"` assignments did that;
  `apply_leaf_visible` now does it from the table and returns what it wrote, so a
  bypass is reported. Both settings disable a verification step.

  Declaring it exposed an asymmetry: `CODESS_NO_HASH` was in `config`'s
  environment table and `CODESS_NO_CONTRACT_CHECK` was not, so two settings of
  one kind were declared in different places. Both are there now.

- **Every command option carries help.** 90 declarations gained a string; 76
  distinct names in `admin_cmd` had none while `project.py` documented all of its
  own, so the administrative surface was undocumented as a class. The test reads
  the *built parser* rather than the source, because an option inherited from a
  shared parent is declared once and must render documented everywhere it
  appears, and the test holds that rather than a count recorded here.

- **`ingested_projects.json` is `projects_state.json`.** The file is written by
  `scan` and `query` as well as `ingest`, so "ingested" named one of three
  writers, and its subject is what has happened to a Project rather than which
  Projects were ingested. `STATS_FILE` becomes `PROJECT_STATE_FILE` for the same
  reason: the file holds timestamps and source lists as well as counts.

  **Regenerated rather than migrated**, consistent with every other Codess
  state: the file is rebuilt by the next `scan`, `ingest`, or `query`.

### Command Surface

- **A flag name declares one type.** `--store` is declared 22 times across two
  modules and one of them said `type=str` where the other 21 said `type=Path`,
  so a caller moving between command families received a different type from one
  flag name. Behaviour was right because `resolve_store_root` normalizes both --
  which is exactly what made the divergence invisible. `--dirs` and
  `--resource-policy` carried the same split and are now `Path`; the latter also
  described a file path as `metavar="JSON"`.

  A test holds the rule by reading the *declared* type from each `add_argument`
  call, because checking through a resolver that accepts both cannot see the
  condition.

- **Two flags renamed, because one spelling named two subjects.** **Breaking for
  three subcommands.** `--project` named a Project reference under `catalog
  decide`, a repeatable reference list under `refresh`, *and* a directory on
  disk; the directory is now `--directory` under `baseline validate`, `baseline
  apply`, and `baseline recover-pointer`, and `--project` keeps the references.
  `--selection` named a selection state under `catalog candidates` and a file
  under `baseline freeze`; those are now `--select` and `--file`.

  `--since` is deliberately left as it is. It means a git date expression under
  `catalog candidates` and a Unix millisecond timestamp under `query`, and both
  are correct for their command: the first is what `rev-list --since` accepts,
  the second is what an `_at` column holds. Renaming either would make one
  command disagree with the vocabulary of the surface it belongs to.

  Verified by dumping `--help` for all 45 parsers before and after: exactly five
  subcommands changed, each by exactly its intended rename.

  **The same rule reaches the development tools**, because a caller does not
  change vocabulary at the `tools/` boundary. `apply_and_verify`,
  `retire_project`, `validate_snapshot`, and `demo_model_metrics` each took a
  Project directory as `--project`; `codess catalog location add|retire` took
  one as `--path`, which says only what `type=Path` already says. All five are
  `--directory`. Two further collisions found by grouping declarations by `dest`
  rather than by name: `--store-root` in one tool became `--store`, and one
  tool's `--selection` became `--file` to match the command it mirrors.

  `--dir` keeps its name. It is the documented Project selector for `scan`,
  `ingest`, and `query` and is repeatable, where `--directory` is the single
  directory a command operates on -- two names for two things.

- **The command layer has one fatal-error channel.** `cli.failure` holds `fail`,
  `fail_with`, `warn`, and `fail_configuration`; all 59 direct stderr writes
  across the four command modules are converted, and no command module names
  `sys.stderr`. Eleven of those writes had omitted the `codess:` prefix, and the
  same configuration-validation block was written out three times.

  `warn` returns `None` rather than an exit code, so a warning cannot be written
  `return warn(...)` and end a run it was built to survive. The two are separated
  by return type rather than by destination, because they share the destination.

  **A fatal message carries the offending value verbatim**, and that is the
  privacy decision rather than the absence of one: it reports the operator's own
  machine to the operator on their own terminal. This matches `reporting`'s
  `local` privacy profile, the default for every profile, which emits every field
  verbatim including unregistered ones. Redaction exists for the event stream,
  which can be written to a file and shipped; a fatal message has no such path,
  and a redacted one would be the message least able to do its job.

  Not routed through `codess.reporting`, and the reason is measured: only
  `ingest` and `scan` call `reporting.configure()`, so an event emitted from
  `admin` or `query` reaches no sink and is dropped. Its `HumanSink` also renders
  every event as `codess: progress <time> +<elapsed>s key=value`, which is the
  wrong shape for a condition that ends the run.

- **Seven shared command options are declared once and inherited.** `--store` was
  written out 22 times, 19 of them byte-identical, and `--output` 11 times
  identically; with `--project-id`, `--source`, `--project`, `--policy`, and
  `--reviewed` they now come from one parent parser via argparse's `parents=`.
  Total `add_argument` calls fell from 259 to 219.

  The refactor is behaviourally inert and was checked rather than assumed:
  `--help` was dumped for all 45 parsers before and after, and every subcommand
  accepts exactly the same option set. Help text is what changed -- each shared
  option now carries one, which is the point of the mechanism.

  A form that genuinely differs keeps its own declaration. `--store` is required
  for one command, one `--project-id` is repeatable, and `catalog candidates`
  takes a comma-separated `--source` where the shared one takes `choices`.
  Inheriting any of those would change what that subcommand accepts.

- **A stated type convention.** A filesystem path is `type=Path`, which 84
  declarations already did; everything else omits `type` and takes argparse's
  `str`. An explicit `type=str` is reserved for an argument that is a string and
  would otherwise be read as a path: `--source` is a comma-separated vendor spec,
  and `--out` uses `-` as a stdout sentinel that `Path` would turn into a
  relative file named `-`. `--content-policy` was `type=str, metavar="JSON"` for
  an argument the consumer wraps in `Path(...)`, and is now `type=Path`.

- **One status line moved to the reporting facility.** `scan`'s legacy-Cursor
  prune report was gated on `opts["debug"]` *and* written directly to stderr,
  which is two gates for one decision and how a profile and a flag come to
  disagree. It is now `registry.legacy_cursor_pruned` at debug level, and the
  reporting threshold decides alone.

  The remaining command-layer writes stay as they are, and the reason is
  recorded rather than deferred: `reporting.configure()` is called only by
  `ingest` and `scan`, so an event emitted from `admin` or `query` reaches no
  sink and is silently dropped. 50 of the 59 stderr writes report a fatal
  condition immediately before `return 1`.

### Typing

- **The typing posture is decided on measured cost.** `disallow_untyped_defs`
  and `strict_optional` are enabled: the first found ten unannotated signatures
  and, once they were annotated, cost nothing; the second is already mypy's
  default, so enabling it states an existing guarantee -- disabling it raises the
  error count by 31, which is the measurement that settles it.

  `warn_return_any` is not enabled, measured at 26 errors concentrated in the
  `Any` that vendor JSON legitimately carries until validated. It waits on the
  candidate-record contract typing that boundary.

- **Four long-standing type errors are repaired rather than carried.** An
  optional `resource` module declared as a module, `RANK.get` passed as a `max`
  key where its overloaded one-argument form returns `int | None`, a
  heterogeneous result list inferred to its narrowest common member, and a
  `_days_ago` signature narrower than its call sites. Each is a contract the
  code did not state rather than a checker complaint: the count fell from 80 to
  76 by saying what the code means.

  Annotating the ten signatures exposed four optional-handling defects the
  untyped signatures had hidden: a catalog set to `None` and passed to a reader
  expecting a dict, a `raw_store` declared required and passed `None` on every
  unsealed run, an unguarded read of a composer tick where the sibling read
  guards it, and a `roots`/`err` correlation the checker cannot follow. Each was
  repaired rather than suppressed, so the error count returned to its baseline
  instead of being reclassified.

## 0.3.0

### CoSchema Format 7

Requires a rebuild. Stores at format 6 and earlier are unreadable by this
version.

- **Session model evidence is recorded for every vendor that supplies it.**
  `sessions.session_model_basis` states how the Session-level model was
  obtained -- `vendor` where the vendor made a Session-level statement,
  `initial_event` where the first model observed to serve a turn was recorded
  instead. `sessions.session_model_count` holds the number of distinct models
  across the Session's Model Turns, so a model-switch question is a predicate
  rather than a join.

  Claude records the model per assistant record and never as a Session header,
  so its Session-level model coverage was zero and is now complete. A derived
  value is never presented as a vendor statement: the basis column is what
  keeps the two claims distinct.

### Decode

- **Cursor reasoning is decoded and emitted as `message.reasoning_summary`**,
  the Event kind Codex already uses, so a cross-vendor reasoning query needs no
  per-vendor case. Cursor never places reasoning beside a response -- every
  bubble carrying `thinking` has empty `text` -- so the evidence previously
  produced no Event at all.
- **Cursor bubble fields mapped**: turn and client timings, recorded error
  details, terminal working directory, symbol and file links, todos, code
  blocks, the populated `context` leaves, and the request and response
  identifiers, which are kept as separate values because they name the two ends
  of a Model Turn.
- **Cursor Session times fall back to the composer header.** Where a composer's
  bubbles carry no timestamp, `created_at` and `last_updated_at` supply the
  Session span and `time_basis` records `session`, so a header-stated span
  stays distinguishable from an Event-derived one. Sessions that previously
  carried no time at any level could not be ordered or filtered by `--since`.

- **Cursor composers absent from `composerHeaders` are recovered.** The header
  table is the smallest of three indexes the vendor keeps; 107 composers held
  bubbles it does not list. Settings are now read for every known composer
  rather than only for headered ones, raising composer coverage from 66 to 164
  and Sessions carrying a stated model from 32 to 134. A recovered composer
  states no workspace, so it is never admitted under a workspace selection --
  attributing it to a Project would be an inference rather than a decode.
- **`modelConfig.selectedModels` supplies `speed_tier` and `reasoning_effort`.**
  A `fast` parameter is set on models whose name does not encode it, and an
  `effort` parameter on models whose name never does. Values are strings, so
  `"false"` is a stated value rather than an assertion.

### Correctness

- **Timestamp scale is decided once.** `units.epoch_milliseconds` normalizes
  ISO-8601 text, epoch seconds, and epoch milliseconds to the milliseconds
  CoSchema defines, and the three vendor parsers delegate to it. The Claude
  parser previously returned a seconds-scale number unchanged, which would have
  stored a 1970 instant, and accepted `True` as a number.
- **`tools/decode_audit.py` queried a column renamed in format 6**, so the
  audit the validation sequence mandates after every decode change had been
  failing at runtime.
- **`tools/gather_evidence.py` read an argument name that was never defined**,
  so it had never run.

### Checks

- **The module-level import graph is asserted acyclic.** Counting every import
  reports two components; both are closed only by imports deferred into a
  function body, which is the mechanism that keeps the layering loadable.
- **Static checks precede tests in the documented validation sequence.** An
  undefined name is reported by ruff and mypy in about a second with a file and
  line; the same defect reaching the suite surfaces as a subprocess failure
  with no location.
