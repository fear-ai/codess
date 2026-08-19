# Operations

This guide gets Codess installed, connected to local Claude Code, Codex, and
Cursor stores, and running against Projects. It covers the normal operating
path and basic diagnosis. Exact command options remain in `codess --help`.

## Requirements

Codess requires:

- Python 3.11 or newer;
- local read access to the vendor stores being examined;
- write access to the selected Project's `.codess/` directory; and
- write access to the machine store, normally `~/.codess/` (see
  [Two `.codess` Directories](#two-codess-directories)).

SQLite support is supplied by Python. The `zstandard` package is installed as a
runtime dependency for bounded raw-object capture.

### Two `.codess` Directories

Codess writes to two directories that share a name and hold different things.
Both appear in every operation below, so it is worth separating them once.

| | Project depo `<project>/.codess` | Machine store `~/.codess` |
|---|---|---|
| Holds | The Project's working stores, its current pointer, ingest state, and the last report | Published store sets, one per Project, plus receipts, reports, retention records, raw capture, and the machine id |
| Scope | One Project | One machine |
| Selected by | `--dir` | `--store` (`--registry` is the older spelling and still works) |
| Removable | Yes -- deleting it costs a re-ingest | Yes, but it holds the only copy of every published store |

A Project's `current.json` **points into the machine store**: the working store
sits beside the checkout, and the published store the pointer selects is
central. They are not copies of each other.

**Why the machine store grows, and what bounds it.** Each publication writes a
complete new store set rather than a delta, so a Project ingested repeatedly
accumulates one full copy per run.

`CODESS_KEEP_SNAPSHOTS` bounds that: it counts snapshots *besides* the
current one, defaults to **2**, and **0 keeps every snapshot**. Trimming runs
after the new snapshot is published, so an interruption leaves more snapshots
than asked for rather than none -- the failure that matters is a Project with no
readable store, and this ordering cannot produce it. The oldest are removed
first, and a directory that will not delete is reported rather than raised.

Set 0 when auditing a sequence of rebuilds, where every intermediate store is
evidence. Raise it where a rollback further back than one publication is worth
the disk.

This bounds accumulation from here on; it does not reclaim what a machine has
already retained. Run `codess storage report` for the split between current and
superseded, and `codess storage prune` to apply a retention plan to the rest.

**Two files hold the Project lists, and they answer different questions.**

| File | Answers |
|---|---|
| `projects.json` | Which Projects exist, their identity, locations, and workspace bindings |
| `ingested_projects.json` | What has been scanned, ingested, or queried for each path, and when |

The first is keyed by Project identity and is the registry proper; the second is
keyed by path and records activity. A path can appear in the second without
being in the first, which is how a directory holding Sessions shows up before it
is onboarded as a Project.

## Installation

Choose the intended Python environment, then install from the repository root:

```bash
python -m pip install -e '.[test]'
codess --version
```

Run the tests when changing the software or local environment:

```bash
pytest -q
```

The installed `codess` command is the normal interface. Running source files
directly is reserved for development and diagnosis.

## Source Locations

Codess uses the ordinary vendor locations by default:

| Source system | Default location |
|---|---|
| Claude Code | `~/.claude/projects/` |
| Codex active Sessions | `~/.codex/sessions/` |
| Codex archived Sessions | `~/.codex/archived_sessions/` |
| Cursor | Platform-specific Cursor `User` directory; on macOS, `~/Library/Application Support/Cursor/User/` |

Override a location only when the installation actually differs:

```bash
export CODESS_CC_PROJECTS=/absolute/path/to/claude/projects
export CODESS_CODEX_SESSIONS=/absolute/path/to/codex/sessions
export CODESS_CODEX_ARCHIVED_SESSIONS=/absolute/path/to/codex/archived_sessions
export CODESS_CURSOR_DATA=/absolute/path/to/Cursor/User
export CODESS_STORE_ROOT=/absolute/path/to/machine-store
```

Every configured Source root must be absolute. Pointing Codess at copied test
data is a useful way to diagnose source interpretation without touching live
application state.

### Scan Scoping

Scan treats some directories as groupings that contain Projects rather than
as Projects themselves, and skips others as review or backup trees. Both
lists default to one set of names and are replaced wholesale:

```bash
# Directories that group Projects rather than being one.
export CODESS_AGGREGATORS='Clients,Research,Tools,Github,Sandbox'

# Path prefixes, relative to the work root, skipped as review/backup trees.
export CODESS_EXCLUDE_REVIEW_DIRS='Tools,Vendor/Bundled,Research/Archive'
```

Entries are comma-separated and relative to the work root; an absolute entry
is reported by configuration validation, because it would never match. An
empty value means an empty list, which is how a tree with no grouping
directories says so -- `CODESS_AGGREGATORS=''` makes every directory a
candidate Project.

Set these when scanning an unfamiliar tree. The defaults describe one
developer's layout, so on another machine they may both group directories
that are Projects and scan trees that should be skipped.

## Regenerating After a Schema or Package Change

Read this first if `ingest` reports:

```text
UnsupportedStoreError: store package differs from the current released
package; rebuild the derived working store from source
```

Codess does not migrate stores. Vendor sources remain the authority, so a
store written under a different released package is rebuilt rather than
converted. The procedure preserves the old data instead of deleting it, so a
comparison remains possible if a rebuild produces something unexpected.

Move existing stores aside, keeping them:

```bash
# One Project.
mv /path/to/project/.codess /path/to/project/.codess.old

# Every Project the machine store has recorded.
python - <<'PY'
import json, shutil
from pathlib import Path
registry = Path.home() / ".codess" / "ingested_projects.json"
for entry in json.loads(registry.read_text())["projects"]:
    store = Path(entry["path"]) / ".codess"
    if store.is_dir():
        shutil.move(str(store), str(store) + ".old")
PY
```

The Project state file accumulates an entry per Project ever scanned,
including temporary directories from test runs, and has no retention policy.
Move it aside as well so the rebuilt list reflects what currently exists:

```bash
mv ~/.codess/ingested_projects.json ~/.codess/ingested_projects.old.json
```

Rediscover and rebuild. Use `--days 0` for the first scan so Projects older
than the default window are not silently omitted:

```bash
codess scan --dir ~/Work --days 0 --out -
codess ingest --dir /path/to/project
codess query overview --dir /path/to/project
```

Read the warnings rather than only the exit status. Both commands report on
stderr while results go to stdout, so they are easy to miss when redirecting:

| Message | Meaning |
|---|---|
| `N project(s) have coding work older than the ... window` | Projects exist but were not listed; widen with `--days 0` |
| `scan diagnostics: stale_index_entries=N` | A vendor index references Sessions whose files are gone |
| `ingest diagnostics: malformed=N unsupported=N` | Records that could not be decoded; investigate before trusting counts |
| `skipping incomplete final record` | A Session was being written during the read; re-ingest later to pick it up |
| `cursor.workspace.skip ... reason=no-bubble-rows` | A Cursor workspace exists with no retained conversation |

`.codess.old` is a working archive, not a retained artifact. Keep it only
while confirming the rebuild: `codess query overview` against the new store
should report Session and Event counts consistent with the
`last-ingest-report.json` inside the archived directory. Delete
`.codess.old` once that comparison holds -- it is a copy of derived data
that vendor sources can reproduce, so keeping it past validation costs disk
for no evidence.

No vendor format currently requires skipping, and Codess keeps no
supported-version list. Sessions written by many harness releases decode
through the same path, because the vendors' record envelopes have been
stable across the range retained locally. A record shape the decoder does
not recognize is counted as `unsupported` rather than dropped, so a format
change appears as a rising diagnostic on one source system instead of as
missing data.

The harness version is recorded per Session, so the range actually present
is a query rather than an assumption:

```bash
sqlite3 -readonly path/to/.codess/sessions_cc.db \
  "SELECT harness_version, COUNT(*) FROM sessions GROUP BY 1 ORDER BY 2 DESC"
```

To rehearse the decode without writing anything, add `--validate`: ingest
stages into a temporary directory, reports the same diagnostics, and leaves
the Project, registry, and raw store untouched.

## First Project

Use one real repository or Project directory whose Sessions are expected to be
small and easy to recognize.

### Discover

```bash
PROJECT=/absolute/path/to/project
codess scan --dir "$PROJECT" --out -
```

Scan consults vendor indexes and bounded metadata. It does not normalize
Session content. Confirm that the row names the intended Project and
source systems before ingesting.

### Validate

Run a non-publishing parse and validation when testing a new Source shape or
configuration:

```bash
codess ingest --dir "$PROJECT" --source all --validate
```

Validation uses temporary stores and reports malformed, ignored, empty, and
failed Sources without changing the Project's selected Project store set.

### Ingest

```bash
codess ingest --dir "$PROJECT" --source all
```

Ingest selects relevant vendor records, decodes and classifies them, validates
the common records, writes per-source-system SQLite stores, and publishes the
completed Project store set. Progress is emitted on standard error without
printing Session content.

### Orient

```bash
codess query overview --dir "$PROJECT"
codess query sessions --dir "$PROJECT"
```

Choose a recognizable Session and inspect or search it:

```bash
codess query search --dir "$PROJECT" --text 'distinctive phrase'
codess query events --dir "$PROJECT" --session-id SESSION_ID
```

If results do not resemble the expected Project work, stop and investigate
Project attribution, Source selection, and vendor mapping before ingesting more
Projects.

## Routine Updates

Repeating ingest performs an assessed update. Unchanged selected evidence is
skipped; changed Sources are decoded and replace their prior normalized
records transactionally.

```bash
codess ingest --dir "$PROJECT" --source all
```

Use `--force` only when source update evidence is suspect or decoder behavior
changed without a detectable Source change:

```bash
codess ingest --dir "$PROJECT" --source all --force
```

For maintained catalog Projects, `refresh` composes assessment, validation, and
application. Plan first:

```bash
codess refresh --project PROJECT_NAME
```

Then select an explicit stage after reviewing the plan:

```bash
codess refresh --project PROJECT_NAME --stage preflight
codess refresh --project PROJECT_NAME --stage apply
```

Use repeated `--project` or a maintained Project list for a bounded batch.
Failures remain Project-specific unless fail-fast behavior is explicitly
selected.

Inspect the known Project inventory and its computed annotations with:

```bash
codess catalog status
codess catalog annotations
```

## Selecting Several Projects

`--dir` may be repeated. `--dirs` accepts a plain path list or a CSV containing
`directory_path`.

```bash
codess query overview \
  --dir /path/to/project-a \
  --dir /path/to/project-b

codess query search --dirs projects.csv --text 'specific interaction'
```

Inspect the resolved Project scope before drawing cross-Project conclusions.
The stores preserve Project and source-system identity even when results are
merged for display.

## Content and Resource Controls

Built-in bounds protect against accidental binary ingestion, extremely large
transcripts, oversized context bodies, and excessive Event counts. They are
safety ceilings, not expected payload sizes.

Use the versioned policy files when a Project requires deliberate overrides:

- `schema/resource-policy.example.json`
- `schema/content-policy.example.json`

```bash
codess ingest --dir "$PROJECT" \
  --resource-policy /path/to/resource-policy.json \
  --content-policy /path/to/content-policy.json
```

When a limit is exceeded, inspect the classified Source and representative
record before raising it. Oversize or non-text input can indicate incorrect
Project selection, a vendor format change, or a record that should remain
external rather than searchable content.

## Raw Evidence

The ordinary `reference` mode records the Source locator and bounded update
evidence without retaining another complete copy. `observe` retains even less,
recording the fingerprint and update evidence with no reference, which states
that Codess read the Source and kept nothing. `capture` and `seal` are for
investigations requiring exact retained Source bytes.

`--raw-mode none` was the previous spelling of `observe` and still parses, so
existing operator scripts do not need editing.

```bash
codess ingest --dir "$PROJECT" --raw-mode reference
```

Raw capture can contain private code, prompts, tool data, and credentials. Use
it only with an explicit retention purpose and adequate local storage. Raw
objects support provenance and recovery; they are not inserted wholesale into
the searchable database. The functional tradeoffs and mode boundaries are
defined in [Raw Evidence and Integrity](Designs.md#raw-evidence-and-integrity).

## Basic Diagnosis

### No Project Appears in Scan

Check:

1. the configured vendor Source root exists and is readable;
2. the vendor record actually names or binds the selected Project location;
3. the Session falls within the selected recency scope;
4. the Project path has not moved without a recorded binding; and
5. the Source is not a subagent or another excluded relationship.

Use `--debug` for bounded source-selection diagnostics. It must not be treated
as a routine content dump.

### Ingest Reports Malformed or Unsupported Records

Start with the coverage report, which states what was mapped and what was
not for each store in a Project:

```bash
codess query --dir "$PROJECT" --coverage
```

It reports admitted Events against classified Events, the record shapes seen
and their counts, and diagnostic reasons split by level. The split matters
when reading it: a **source** or **record** reason means something did not
become an Event, while a **field** reason means an Event exists with a value
missing. A Project can show thousands of field diagnostics and lose nothing.

A record shape appearing there that no mapping profile names is an unknown
shape -- usually a vendor format change rather than a decoder fault. A shape
that has stopped appearing is the same evidence from the other direction.

Then identify the source system, Source locator, record locator, exact type,
and diagnostic reason for a representative record, and compare it with the
vendor schema and adapter fixture. A malformed optional field should not
remove an otherwise usable Event; a core identity or ordering failure should
remain explicit.

### Search Returns Unexpected Counts

Verify:

- selected Project and source-system scope;
- direct human versus harness/delegated classification;
- exact Event kind and source type;
- repeated physical storage versus repeated real Events;
- time and status predicates; and
- whether Interaction or Model Turn expansion added surrounding Events.

Use direct read-only SQLite queries to reconcile a focused result.

### Cursor Is Slow or Busy

Codess queries selected Cursor headers and composer key ranges through read-only
SQLite connections. Confirm that the selected workspace mapping is narrow and
that the live database is not continuously changing. Do not copy, vacuum,
rewrite, or fully decode the Cursor database merely to diagnose one Project.

### First Discovery on a New Machine

Codess ships with empty grouping and exclusion lists, so a fresh install
classifies nothing by name. Discovery is a three-step process rather than a
configuration exercise: scan broadly, review what was found, then narrow.

```text
  1. scan            ~/Work or ~, all-time window, empty lists
        │
        ▼
  2. review          which rows are Projects, which are containers,
        │            which are review or vendored trees
        ▼
  3. configure       CODESS_AGGREGATORS   -- containers, reported as children
        │            CODESS_EXCLUDE_REVIEW_DIRS -- trees holding others' code
        ▼
  4. rescan          confirm the same Projects, minus the excluded trees
```

```bash
# 1. Discover with nothing configured.
codess scan --dir ~/Work --days 0 --out -

# 3. Narrow, using names from your own tree.
export CODESS_AGGREGATORS='Clients,Research,Sandbox'
export CODESS_EXCLUDE_REVIEW_DIRS='Tools,Vendor/Bundled,Research/Archive'

# 4. Confirm the narrowing removed only what you intended.
codess scan --dir ~/Work --days 0 --out -
```

**What discovery does without configuration**, verified on a tree of 21
Projects across three vendors:

| Property | Behavior |
|---|---|
| Coverage | Scanning `~` and `~/Work` find the same Projects; `~` additionally finds tool working directories outside the work root |
| System locations | Never reported. `/`, `/var`, and similar roots are refused: *broad system traversal root is not allowed* |
| Depth | A container holding 68 nested repositories reports as **one** row, not 68. Scan is index-led and does not walk into candidates |
| Backup trees | `OLD` and `Save` segments are excluded without configuration, being conventions rather than one tree's names |
| Matching | On path segments, so `OSS` excludes `group/OSS/proj` and not `OSSproject/x`, and a directory is excluded by where it sits rather than by where the scan started |

**Why the lists ship empty.** A default derived from one machine's tree
misclassifies directories on every other machine, and the operator cannot see
why: a Project silently absent from a scan looks like a discovery failure. An
empty value is also a statement -- *this tree has no grouping directories* --
which a frozen default could not make.

`~/Work` remains the default work root when no `--dir` is given, since it is
home-relative and costs nothing when absent.

#### What Is Excluded Without Configuration

Two exclusion mechanisms exist, and they differ in what they name:

| | Discovery policy | `CODESS_EXCLUDE_REVIEW_DIRS` |
|---|---|---|
| Where | `schema/discovery-policy.json`, replaced by `CODESS_DISCOVERY_POLICY` | Environment variable |
| Names | Directory **names**, matched case-folded on any segment | **Paths** relative to the work root |
| Ships | Populated | Empty |
| Portable | Yes -- `obj` is build output everywhere | No -- names one machine's layout |
| Examples | `build`, `dist`, `obj`, `bin`, `x64`, `.vs`, `packages`, `node_modules`, `vendor`, `tmp`, `temp`, `.git`, `__pycache__`, `.venv` | whatever the operator configures |

The policy file also records **names that look skippable and are deliberately
traversed**, each with its reason -- `lib`, `etc`, `conf`, `data`, `web`,
`windows`, `private`, `secrets`, and others. They are data rather than a
comment so `tools/setup_discovery.py` can report them to an operator deciding
what to exclude for their own tree. Each is a source directory in a common
layout, so pruning it by name would hide the Project rather than the noise.

**`secrets` and `credentials` are traversed deliberately.** Pruning stops
traversal, which changes what is discovered rather than what is protected: a
Session that already read a credential file records it whether or not Codess
later walks that directory. Content exclusion is the content policy's
subject, and a name-based skip that looked like protection would be worse
than none.

A malformed or unreadable policy warns and falls back to the released set: a
scan that will not start because a policy has a trailing comma is a worse
failure than one that uses the shipped names.

The built-in set covers four kinds: version-control and editor state, caches,
build output on POSIX **and Windows** conventions, and scratch directories.
Matching is case-folded, so `TMP`, `Tmp`, and `tmp` are one entry. Ordinary
source directories -- `src`, `lib`, `docs`, `tests` -- are never pruned.

`OLD` and `Save` segments are additionally excluded as backup conventions.

**Links, mounts, and other filesystems.** Every path is resolved before it is
compared to a root, so a symbolic link pointing outside the work root is
detected as outside it and not followed -- otherwise a link would attribute
another tree's Sessions to this one. A link to its own parent resolves rather
than recursing. Codess does not stop at a filesystem boundary: a network
mount or external volume inside the work root is scanned like any other
directory, which is usually wanted and is slow when the mount is remote. Use
an explicit `--dir` or an exclusion entry if a mounted tree should be skipped.

#### Recommended Setup Sequence

A first scan over an unfamiliar tree can be long. This order informs the
operator before committing to it:

```text
  1. show defaults      what is pruned, what is empty, where the work root is
        │
  2. quick probe        ~ with a short recency window -- seconds, not minutes
        │               "here is what a full scan would look at"
        ▼
  3. choose roots       inclusion: which trees to scan at all
        │               exclusion: which to skip within them
        ▼
  4. full scan          the long pass, over a scope the operator chose
        │
  5. review and ingest  sort the discovered Projects, ingest the wanted ones
```

```bash
# 1. What will happen, before anything is read: resolved roots, which lists
#    are empty, what is pruned, and what is deliberately traversed.
codess config discovery --no-propose

# 1b. The same, plus candidate containers read from your own tree.
codess config discovery

# 2. A quick probe: recent work only, so it finishes in seconds.
codess scan --dir ~ --days 30 --out -

# 3. Configure from what the probe showed.
export CODESS_AGGREGATORS='<containers>'
export CODESS_EXCLUDE_REVIEW_DIRS='<review trees>'

# 4. The long pass, now bounded.
codess scan --dir ~/work --days 0 --out -

# 5. Ingest what review selected.
codess ingest --dir <project>
```

**Why a probe before a full scan.** A recency-windowed scan reads the same
vendor indexes as a full one but stops at the cutoff, so it costs a fraction
of the time and answers the question that decides the configuration: which
containers hold work, and which trees are someone else's code. Configuring
first and scanning once is faster than scanning, discovering the tree is
wrong, and scanning again.

**Exclusions matter less than they appear, because discovery is index-led.**
Measured against a tree holding five vendored directories with 145 nested
third-party repositories between them: only **one** appeared in a scan with
no exclusions configured, and it appeared because coding work had actually
happened there. The other four have no vendor sessions, so an index-led scan
never reaches them however many repositories they contain.

Configure exclusions for trees where you *have* worked and do not want
reported -- a reference checkout you opened an assistant in, an archive you
edited. A directory full of code nobody has run an assistant against needs no
exclusion, and adding one is a rule that silently stops matching when the
directory is renamed.

**Findings outside the work root are expected.** Scanning `~` rather than a
work root additionally reports tool working directories such as `~/.codex`,
where work happened while the current directory was one of them. These are
correctly discovered: a Project boundary tested only against clean
repositories is not being tested. Cursor's shared store appears as
`(global)`, which is an observation rather than a Project and is never
written to the registry.

### Current Snapshot Manifest Hash Mismatch

`scan`, `ingest`, and `query` verify the current snapshot's `manifest.json`
against the hash recorded in its `current.json` pointer before trusting it.
A mismatch produces an explicit error naming the affected Project and
snapshot rather than silently accepting stale or tampered content; see
[Publication and Integrity](CoPlan.md#84-publication-and-integrity) for what
the check does and does not protect against.

Investigate before bypassing: compare `current.json`'s recorded
`manifest_sha256` against a fresh hash of the retained `manifest.json`, and
confirm whether the snapshot directory was touched outside normal Codess
operation (an interrupted publish, manual editing, or a restored backup are
the ordinary causes).

Two recovery commands rebuild what was lost, and which to use depends on
which file is damaged:

```bash
# current.json lost or corrupt: republish the newest snapshot that validates.
codess baseline recover-pointer --project /path/to/project

# manifest.json corrupt: reconstruct it from the surviving stores.
codess baseline recover-manifest --snapshot /path/to/project/.codess/snapshots/<id>
codess baseline recover-manifest --snapshot <...> --apply
```

`recover-pointer` republishes an existing snapshot and creates nothing, so it
needs no confirmation. `recover-manifest` reports by default and writes only
under `--apply`, because `parent_snapshot_id`, `build_policy`, and
`build_policy_digest` are recorded nowhere else and come back null: review
what is recoverable before overwriting what is there. The reconstructed
document carries `"reconstructed": true`.

`--no-hash` skips this verification; see
[Integrity Check Overrides](#integrity-check-overrides) for its behavior
and the conditions under which it is appropriate.

### Integrity Check Overrides

Two checks guard reads and writes, and each has one escape. Both are recovery
and test options rather than routine flags. Each accepts a command-line flag
or an environment variable, and the environment variable is what the checking
code reads: a flag is parsed after configuration constants resolve, so the
flag's effect is to set the variable.

The two answer different questions and are not interchangeable.

| Override | Environment | Question the check answers | What it covers |
|---|---|---|---|
| `--no-hash` | `CODESS_NO_HASH=1` | Is this file the bytes we recorded? | Content verification of an individual retained file against a hash stored beside it: snapshot manifests, pointer documents, and raw-capture objects. |
| `--no-check` | `CODESS_NO_CONTRACT_CHECK=1` | Were these records written under the rules in force now? | Verification of the released CoSchema package -- DDL, contract, mapping profiles -- and comparison of a store's recorded `contract_digest` against the current one before a write. |

The distinction that matters operationally: `--no-hash` concerns **one file's
integrity**, and a mismatch means the file changed since it was recorded.
`--no-check` concerns **agreement between a store and the schema package**,
and a mismatch means the rules changed since the store was written. A store
can pass every hash check and still fail the contract check, which is the
ordinary case after a schema change; the reverse means a file was altered.

Their scope differs accordingly. `--no-hash` affects reads throughout, since
hashes are verified wherever a recorded file is loaded. `--no-check` gates
store creation and writes; reads of an already-written store are not blocked
by a contract mismatch.

Neither override is the default, and both warn. Every bypassed hash check
logs the path. Every bypassed contract check logs the store and each failure
it passed over, and a store created under `--no-check` records
`contract_override` in its `store_meta`, so a later reader observes the
override directly rather than inferring it from a failing check. `--no-check`
does not weaken the identity checks around it: a store whose SQLite
`application_id`, format version, decoder version, or validator version
disagrees is still refused.

Neither override repairs the underlying inconsistency. Two situations justify
one:

- **Recovery.** A store whose recorded contract disagrees with the installed
  one, whose vendor Sources are gone, and whose released files cannot be
  reconstructed is unreadable under a mandatory gate. The check would then
  withhold retained evidence rather than protect anything.
- **Tests.** Exercising a deliberately mismatched store, or a deliberately
  corrupted manifest, without regenerating the released set.

Outside those, identify and fix the cause. For a contract mismatch, [Schema
Maintenance](#schema-maintenance) covers comparing the two contracts; for a
hash mismatch, the investigation steps are in
[10.6](#current-snapshot-manifest-hash-mismatch).

## Schema Maintenance

Normal ingest verifies the installed schema package before it writes a store.
When changing CoSchema, a mapping profile, or SQLite DDL, run the focused
contract checks and compare the complete package declaration:

```bash
pytest -q tests/test_schema_contract.py
codess schema compare /path/to/baseline-contract.json \
  /path/to/candidate-contract.json \
  --declared same
```

Choose `same`, `compatible`, `breaking`, or `manual` only after reviewing the
reported contract changes. Then run the full test suite and the smallest real
source-system example that exercises the changed translation.

## Repository Tools

The `codess` command is the supported interface. The scripts under `tools/`
are development and diagnosis aids that are not installed as commands and are
run with the repository's Python. They are grouped here by what they answer.

### Where a Measurement Is Read From

A figure that describes the current state is read from a producer, not from a
document: prose goes stale silently while a producer is re-run. This is the
quick reference for which producer answers what, and which of them fails a
build rather than merely reporting.

| Producer | Location | Holds | Gated |
|---|---|---|---|
| `tools/quality_report.py` | `schema/quality-baseline.json` | Lint and type counts per rule and category, against recorded ceilings | **Yes** -- exits nonzero when a count rises |
| `pytest` | -- | Pass and fail counts | **Yes** -- via the same report |
| Refresh receipts | Registry, per Project | Ingest rate, Event counts, per-stage seconds | No |
| `~/.codess/projects/*/current.json` | Registry | Published Project count, snapshot sizes and identity | No |
| `tools/deep_audit.py` | Run output | Design-tier findings: `PLR`, `TRY`, `C901`, duplicate clusters | No |
| `tools/field_coverage.py` | Run output | Which columns are empty, and for which vendors | Optional -- `--fail-on-gap` |
| `tools/decode_audit.py` | Run output | Classification and relation consistency | **Yes** -- exits nonzero on any inconsistency |
| `tools/value_survey.py` | Run output | Columns carrying no information, in six classes | No |

**The gated ones are the durable record.** A count written into a document is
strictly weaker than a baseline file, because the file fails the build when it
drifts and the prose does not. Accept a new ceiling deliberately:

```bash
python tools/quality_report.py            # report and compare
python tools/quality_report.py --accept   # record a new ceiling, and say why
```

**What a document should carry instead.** A count belongs in a work item only
where it bounds the work -- which fields a mapping must decide, how many call
sites a rule must reach -- because that is what tells a finished item from an
unfinished one. A count that reports a moment belongs to a producer above, and
the document names the producer.

### Decode and Evidence Audits

These read ingested stores or vendor Sources and report structure, counts, and
classifications. They report record shapes and never message, prompt,
argument, or result content, so a finding names a source record type or field
and can be acted on without reproducing what a Session said.

| Tool | Answers |
|---|---|
| `decode_audit.py` | Do classification, relation, and decode coverage hold across ingested stores? Reports Actor, role, origin, and Event-kind distributions, tool and model linkage, Session relations, context Events, and nine pairings that should not co-occur. Exits nonzero when any inconsistency is found. |
| `audit_claude_features.py` | Which Claude Code record features appear in local Sources? |
| `audit_codex_parentage.py` | What parent-Session evidence do Codex rollouts carry? |
| `audit_cursor_features.py` | Which Cursor tool and model structures appear in the selected workspaces? |
| `value_survey.py` | Which columns carry no information -- never written, or written with the same value every time? Six classes, because what a value is constant *across* changes what it means: absent everywhere, absent for all but one vendor, absent for exactly one, one value across all vendors, one value differing per vendor, constant for some. Values are printed only with `--values`, and are classifications rather than content. |
| `field_coverage.py` | Which CoSchema columns hold no data, and for which vendors? Classifies every column as empty for one vendor, populated for only one, or empty for all -- three different findings. `--fail-on-gap` exits nonzero on the first class, where a column is demonstrably decodable and one adapter does not fill it. |
| `gather_evidence.py` | What compatibility evidence is currently available across all three vendors and the registry? |
| `demo_model_metrics.py` | What model latency and prompt/response measures does one store hold over a bounded period? |

```bash
python tools/decode_audit.py --dir "$PROJECT" --out audit.json
```

`--dir` is repeatable, so several Projects can be audited as one report.

### Contract and Quality Checks

| Tool | Answers |
|---|---|
| `quality_report.py` | What are the current lint, type, and test counts? Reports all three so a change is compared against the state before it. Only the test suite gates the exit status; lint and type counts have a nonzero baseline being reduced against named work items. |
| `coschema_gate.py` | Is a CoSchema contract change compatible with its declared rank? Fail-closed; this is what `codess schema compare` wraps. |
| `report_sql_suppressions.py` | Which files currently hold a Ruff `S608` exemption, and does the exemption list still match the code? |

| `deep_audit.py` | What does the whole tool set see, beyond the rules the gate selects? Runs twenty Ruff families one at a time, plus Pylint duplicate detection, Radon complexity, and Vulture, grades each finding, and writes a timestamped log. |

```bash
python tools/quality_report.py
python tools/quality_report.py --skip-tests
```

**The two are not interchangeable.** `quality_report.py` is the gate: fast,
run before a change lands, and it fails when a recorded count rises.
`deep_audit.py` is a periodic audit: slower, reports findings nobody will act on
today, and depends on tools that may be absent -- so it says which ones did not
run, because a missing tool reporting nothing looks exactly like a clean result.

```bash
python tools/deep_audit.py                          # report and log
python tools/deep_audit.py --no-log                 # report only
python tools/deep_audit.py --compare output/audits/deep-audit-<stamp>.json
```

Findings are graded and each line names the tool that produced it:

| Tier | Meaning |
|---|---|
| `DEFECT` | A selected rule reported something; the gate expects zero, so read every one |
| `DESIGN` | Not wrong today, but the shape that produced past defects here |
| `GAP` | A tool did not run, so it reported nothing rather than found nothing |

Pylint, Radon, and Vulture are development-only and not runtime dependencies;
install them when running the audit.

### Snapshot and Catalog Maintenance

These operate on published state. Review their reports before applying a
change, and see [Maintenance Boundaries](#maintenance-boundaries).

| Tool | Answers |
|---|---|
| `validate_snapshot.py` | Does one Project's current snapshot verify, and does a smoke query succeed against it? |
| `build_review_catalog.py` | What reviewable catalog seed does a scan candidate CSV produce? |
| `prune_project_catalog.py` | Which catalog Projects no longer exist on disk? Reports by default; quarantines only with `--apply`. |
| `project_status.sh` | What state is a Project in before any large vendor extraction? Content-free orientation over the Project directory and the registry. |
| `retire_project.py`, `apply_and_verify.py`, `freeze_reviewed_baselines.py`, `verify_reviewed_baselines.py` | Validated Project relocation, and reviewed-baseline apply, freeze, and verification. Each is a compatibility wrapper over the corresponding `codess baseline` or `codess catalog` operation; prefer the command. |

## Maintenance Boundaries

Snapshots, raw objects, catalogs, and receipts support repeatable operation but
are not the primary product surface. Before deleting any of them:

1. run `codess storage report`;
2. generate a dry-run retention plan with `codess storage prune`;
3. confirm that current Project pointers and referenced evidence remain valid;
4. apply only the reviewed plan; and
5. retain the receipt.

Do not modify vendor-owned stores. Do not commit `.codess/` content to a source
repository. Use `codess --help` and each administrative family's `--help` for
the complete current command contract.
