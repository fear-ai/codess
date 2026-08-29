# CoNames

CoNames is the authoritative source for what each thing Codess names is called
in the database, in the code, and on the command line. Where another document
disagrees with it, this document is right and the other is stale. It exists
because six work items proposed renames independently, which is how the
inconsistencies below arose: a name decided against one call site contradicts
the same concept named elsewhere.

Any proposed rename is checked against this document, and a landed one is
recorded in it. Where a name here differs from the one in the code, the
difference is a scheduled change listed under [Renames](#renames), not a
discrepancy to fix locally.

**Scope.** CoNames names things. What those things *mean* is
[Codess](Codess.md#core-model-and-terminology) for entities and
[CoSchema](CoSchema.md) for fields; neither is restated here.

CoNames covers designators -- the names of companies, programs, files, keys, and
columns -- which the glossary does not.

## The Four Facts a Name May Refer To

Seven concepts currently share three words. They separate as follows, and no
name may conflate two of them.

| Fact | Definition | Values observed |
|---|---|---|
| **vendor** | The company a harness originates from | Anthropic, OpenAI, Anysphere |
| **harness** | The program mediating the work | Claude Code, Codex, Cursor |
| **surface** | Where that program was driven from | cli, desktop, ide, api |
| **provider** | The company whose model answered a Model Turn | Anthropic, OpenAI, xAI, Anysphere |

Harness does not imply provider. Cursor is the observed case: of the 6 distinct
model names in the current stores, 3 are Anthropic's or xAI's rather than
Anysphere's own (`claude-4.6-opus-high-thinking`, `grok-4.5`, `grok-4.6`
against three `composer-*`). So "which company made the harness" and "which
company's model answered" are two questions with two answers, and they differ
in half the rows of the one harness where it matters.

`claude` is the sharpest collision. It denotes a harness (Claude Code), a
company's product line, a model family, and a token appearing inside another
harness's model names (`claude-4.6-opus-high-thinking`, recorded by Cursor). A
token match on `claude` therefore cannot tell product from model, which is why
the designators below are matched exactly rather than by substring.

## Vendor and Harness Designators

Each row is one concept. The columns are the places that concept is named.

| Concept | DB column | Code | Values |
|---|---|---|---|
| Adapter key | `sessions.adapter_key` | `store.SOURCE_PROFILES` keys | `Claude`, `Codex`, `Cursor` |
| Vendor | `sessions.vendor_name` | profile `vendor_name` | `anthropic`, `openai`, `cursor` |
| Harness | `sessions.harness_name` | profile `harness_name`; Codex decodes `originator` | `claude-code`, `codex`, `cursor` |
| Surface | `sessions.surface_kind` | `adapters/cc._CC_SURFACE`, `adapters/codex._CODEX_SURFACE` | `cli`, `desktop`, `ide`, `api` |
| Source system | `sessions.source_system_key` | profile constant, stated per vendor | `anthropic.claude-code`, `openai.codex`, `cursor.composer` |
| Storage format | `sessions.storage_format` | profile `storage_format` | `claude-jsonl`, `codex-jsonl`, `cursor-sqlite` |
| Adapter module | -- | `codess/adapters/{cc,codex,cursor}.py` | `cc`, `codex`, `cursor` |
| Store filename | -- | `config.STORE_DB_{CC,CODEX,CURSOR}` | `sessions_cc.db`, … |
| CLI token | -- | `project.SCAN_SOURCE_TOKENS` | `cc`, `codex`, `cursor` |
| Mapping profile | -- | profile `mapping`; `schema/mappings/*.json` | `claude`, `codex`, `cursor` |

**Claude has five spellings for three things**: `cc` (adapter module, store
filename, CLI token), `Claude` (adapter key), `claude-code` (product),
`anthropic.claude-code` (source system), `anthropic` (vendor). Codex and Cursor
each have four. The local designators (`cc`, filename, token) are deliberately
short and are not vendor facts; they need not match the vendor spellings, but
they must not be confused with them.

**A harness name states the program only.** The constants held
`claude-code-cli`, `codex-cli`, and `cursor-ide` -- a surface suffix beside a
`surface_kind` column that names the surface itself, so a Desktop or SDK Session
was stored as a CLI one. Fixed: the program does not change with the surface.
Codex's decoded `originator` values keep their vendor spelling (`Codex Desktop`,
`codex_cli_rs`) because an exact source value is retained rather than
normalized; the surface is read separately from its `source` field.

**One of these is still wrong** and is listed in [Renames](#renames):
`vendor_name` names a product for Cursor. A second, `product_name`, is already
gone: removing the surface suffix made `harness_name` and `product_name`
identical for Claude and Codex, so with the surface in its own column the
program and the product were one fact spelled twice, and the copy was dropped.

**Only Codex names its own program.** Claude states a surface (`entrypoint`) and
no program; Cursor states neither, so both take the profile constant.

### `product` Is Gone

**Removed in CoSchema format 12.** `product` named the program, which is what
`harness_name` holds, so the mapping contract required a second spelling of one
fact. It was the last surviving instance of a defect already fixed twice:
`sessions.product_name` was dropped for being a pure function of the source
system, and `harness_name` had its surface suffix removed for the same reason.

The three profiles now carry `harness_name`, and Cursor's value changed with the
rename -- `cursor-composer` to `cursor` -- because the `composer` part named a
surface that `surface_kind` already carries in its own column.

**The composition rule it was supposed to serve never held.** `source_system_key`
was documented as `vendor + "." + product`. For Cursor that composes
`cursor.cursor-composer` against a stored `cursor.composer`, so the value is a
per-vendor constant that two of three vendors matched by coincidence. The
designator table says constant, because that is what it is.

## Model Name Parts

A model name decomposes along three axes -- line, generation, version -- plus a
gradation, and carries settings a user selected. Each has a column on
`model_params` and a CLI filter. `schema/model-aliases.json` is the data that
resolves a vendor string into them.

| Part | Column | Filter | Means | Values |
|---|---|---|---|---|
| line | `model_line` | `--model-line` | The model series a vendor ships | `claude`, `gpt`, `grok`, `composer` |
| generation | `model_generation` | `--model-generation` | The major step of a line, in whole numbers | Claude 3, 4, 5; GPT 3, 4, 5 |
| version | `model_version` | `--model-version` | The release within a generation | Claude 4.8; GPT 5.6 |
| gradation | `model_gradation` | `--model-gradation` | The capability level within a version | see below |
| variant | `model_variant` | `--model-variant` | A superseded or purpose-marking designator in the same position | `codex`, `codex-max`, `latest` |
| revision | `model_revision` | `--model-revision` | A dated build | `20251001` |
| strength | `reasoning_effort` | `--reasoning-effort` | Reasoning effort selected | `high`, `medium`, `low` |
| served tier | `service_tier` | `--service-tier` | The tier the API reported serving (Claude, in `message.usage`) | `standard` |
| requested tier | `request_tier` | `--request-tier` | The tier the client asked for (Codex, in `thread_settings`) | `default` |
| speed | `speed_tier` | `--speed-tier` | A separate dimension, named only when given | `fast` (the only value any vendor names) |

**Gradations, lowest to highest capability.** The order is the vendor's own and
is not recoverable from the names -- nothing in `haiku`, `sonnet`, `opus` says
which is more capable -- so it is recorded as data and exposed as a rank.

| Vendor | Gradations, ascending |
|---|---|
| Anthropic | `haiku`, `sonnet`, `opus`, `fable`, `mythos` |
| OpenAI | `luna`, `terra`, `sol` |

Anthropic names these after literary and mythological forms, OpenAI after
celestial bodies, and other vendors write `thinking` or `coding` in the same
slot -- one axis under different naming habits. Mythos is named and not
generally available. Grok and Composer state no gradation at all.

**Generation and version are different, and both are kept.** Claude has gone
through generations 3, 4, and 5, and GPT likewise; `claude-opus-4-8` is version
4.8 of generation 4, exactly as `gpt-5.6` is version 5.6 of generation 5.
Conflating them would put `4.8` and `5` on one scale. Generation is the whole
part of the version, so the two can never disagree.

**A gradation is not a line.** `gpt` names OpenAI's series as `claude` names
Anthropic's; `opus` and `sol` are levels *within* one version. A column holding
both was the defect this decomposition fixed.

**Variant is kept apart from gradation because one position has carried both.**
`codex` and `latest` occupied the slot where `sol` and `terra` now sit, so
reading a historical `codex` as a current capability level would assert
something the vendor no longer means.

**Strength and speed are independent, and one label can state both.**
`cursor-grok-4.5-high-fast` is a high strength at a fast speed, so collapsing
them loses one. Only `fast` is ever named -- no vendor writes `slow` or
`standard` -- so an absent speed means *not stated*, not standard.

**Served and requested tiers are two facts, not one.** Claude records
`service_tier` in `message.usage`, beside the token counts -- what the API
reported serving. Codex records its tier in `thread_settings`, beside
`model_provider` -- what the client asked for. One is an outcome, the other a
request, so they occupy separate columns and a cross-vendor comparison of the
two is a comparison of different things.

**Cursor states a model name twice, and the two disagree.**
`composerData.modelConfig.modelName` is the composer's current setting, decoded
as **`model_name`**; the bubble's `modelInfo.modelName` is what ran for that
message, decoded as **`model_set`**. Across 38 composers stating both, 15
disagree -- one records `claude-4.6-opus-high-thinking` while every bubble
records `composer-1.5`. The composer value is last-write-wins for the Session
and carries the speed variants; the bubble value is per-turn evidence and
appears on 1.6% of bubbles. Both are kept because neither substitutes for the
other.

**`speed_tier` is the weakest of these columns and is on notice.** No vendor
states a speed as a field; all three non-null values are parsed from a Cursor
label suffix, so it is the one model column filled purely by inference. Its only
value is `fast`, which makes every other row null by construction and leaves a
reader unable to distinguish "no speed named" from "no fast variant exists". It
earns its place only because `composer-2` and `composer-2-fast` are genuinely
different selections; if that stops being true it should be removed rather than
carried.

**A recorded strength does not prove it was selected.** A model offering only
one level states it the same way as one where the user chose among several, so
`high` occludes whether it was the only option. The value is evidence of what
ran, not of a decision.

**An unresolved name is recorded as such, never guessed.** The vendor string is
kept verbatim in `model_name_exact` in every case; only the derived columns are
left null, so "not recognized" stays distinct from "has none".

**Resolution is a table first, a tokenizer second.** `schema/model-aliases.json`
is consulted by case-folded whole-string match; a name absent from it falls to
the per-vendor tokenizer; anything else is unresolved. Each result records which
path produced it, so a curated mapping is distinguishable from a parsed one.

**API names are stated explicitly, not inferred at read time.** Cursor's
`claude-4.6-sonnet-medium-thinking` resolves to `claude-sonnet-4-6` because the
alias table says so. Correcting a mapping is a data edit, not a code change.

**MCP tool names state their server, in three spellings.** Claude and Codex write
`mcp__<server>__<tool>`; Cursor writes both `mcp_<Server>_<tool>` and
`mcp-<server>-<tool>`, and the hyphen form gives no boundary -- no field states
the server, and splitting on the first hyphen would record `cursor` rather than
`cursor-app-control`. That server is therefore declared in `store._MCP_HYPHEN_SERVERS`
rather than parsed, and an undeclared one stays unresolved. A built-in tool has no
namespace: it belongs to the harness, not a server.


## Identifier Suffixes

`_id` carried four incompatible formats, so a reader could not tell from the
suffix whether a value was derived, assigned, or borrowed. The composed literals
moved to `_key` in format 11; the three remaining suffixes are distinct.

| Suffix | Means | Example |
|---|---|---|
| `_id` on a rowid | SQLite surrogate key, assigned locally | `sources.id`, `model_params.id` |
| `_id` from a vendor | Identifier the source system assigned | `sessions.id` (vendor UUID) |
| `entity_id` | Derived by Codess from declared components | `codess:session:id1:…` |
| `_key` | Composed literal, not an identifier | `sessions.source_system_key`, `sessions.adapter_key` |

The rule: **`_id` names an identifier something assigned; a composed or
descriptive literal takes `_key` or no suffix.** A bare rowid named `id` is
unremarkable and stays.

### Time Suffixes

A time column's suffix states its representation, so a reader needs neither the
DDL nor a convention memo to know which a column holds.

| Suffix | Representation | Type | Who observed the instant |
|---|---|---|---|
| `_at` | Unix milliseconds | `REAL`, nullable | The vendor, or the filesystem |
| `_when` | RFC 3339 UTC | `TEXT`, `NOT NULL` | Codess |

The two representations are both correct and differ because the values answer
different questions. A vendor instant arrives in epoch form, is compared and
aggregated across hundreds of thousands of Events, and may be absent, so a
nullable number preserves both the arithmetic and the vendor's silence. A
Codess-recorded instant is a provenance statement read by a person auditing what
ran, never aggregated, and RFC 3339 carries its own offset so the record is
unambiguous outside the database.

**One name currently denotes both, which is the defect the rule fixes.**
`started_at` is `REAL` in `sessions` and `tool_invocations` and `TEXT` in
`processing_runs`, so code reading both must know which table it is in.
Renaming the Codess-recorded columns to `_when` leaves `started_at` meaning
milliseconds everywhere it appears. No other time name is ambiguous, which is
what makes the rule cheap. [CoSchema](CoSchema.md#time-column-naming) holds the
analysis and `experiments/format-decisions.md` the columns renamed.

A comparison across the two converts at query time -- `timeval.iso_to_ms`, or
`strftime('%s', ...)` for a direct-SQL reader -- rather than in a stored numeric
copy, which would be a duplicate column that can drift.

**`entity_id` is a poor name, and for `sources` it is also wrong.** The value is a
digest of vendor-stated facts, so two machines ingesting the same Session derive the
same identity -- that is the property "global" is claiming, and for Sessions, Events,
and Artifacts it holds. But the name defines the value by where it is *not* valid
rather than by what it identifies, and it invites reading "global" as registered or
resolvable, which nothing does. The scope is also already visible in the value, which
begins `codess:<kind>:`.

**Three kinds do not have the property their column claims.** `source-revision`
derives from `source_path`, `source-record` and `observation` inherit it, and every one
of 405 real Source rows has an absolute local path there -- so the same Source
observed on two machines yields two identities, and cross-store deduplication on
`sources.entity_id` silently fails. `location_id` is honest in its function name,
taking `machine_id` explicitly, but lands in a column that is not.

The settled name is **`entity_id`** for the portable kinds, with the scope stated per
kind here rather than asserted in the column name. `sources.entity_id` needs the
derivation corrected before any rename, since that one is a defect rather than a
wording problem.

**The correction**: drop the path from the derivation, leaving
`hash(source_system_id, source_revision)`. `source_revision` is already a content
fingerprint and therefore portable, so the identity becomes machine-independent
without a new component. Measured over 405 real Sources, that pair is already
unique -- zero collisions -- so nothing is lost. The path stays on the row as an
observation attribute, which is the split `projects` and `project_locations`
already model: identity is what the entity is, the path is where a machine found
it. `source-record` and `observation` inherit the fix, since both derive from the
source-revision identity.

**Every entity row carries two identities, and both are needed.** `sources`,
`sessions`, and `events` each hold a local `id` -- a rowid, or the vendor's own string
for a Session -- and a derived cross-store identity. The local one addresses a row
inside this store; the derived one is the same value on any machine that ingested the
same evidence, which is what `--session-id` and `--event-id` select on.

| Table | Local id | Cross-store identity |
|---|---|---|
| `sessions` | `id` (vendor session id) | `session_entity_id` |
| `events` | `id` (rowid) | `event_entity_id` |
| `sources` | `id` (rowid) | `source_entity_id` |

**The identity column is qualified by table on purpose.** All three were named
`entity_id`, which said nothing in a join and forced an alias wherever two were
selected together. Qualifying them costs a stutter in a fully qualified reference
(`sessions.session_entity_id`) and removes the ambiguity everywhere else. A query
joining Sessions to Events now selects both without aliasing either.

**Which one to use.** Join and filter inside a store by `id`; cite, deduplicate across
stores, or hand an identifier to a later query by `*_entity_id`. A `*_entity_id` is
stable across machines; an `id` is not.

## The `source` Family

**Checked against the built schema after format 11, not against the DDL text.**
27 column names begin `source`, across 13 tables, and the bare `source` column is
gone. Every survivor falls in one of two groups, and the split is what makes the
word unambiguous again:

| Group | Names | Reading |
|---|---|---|
| The Source entity | `source_entity_id`, `source_path`, `source_revision`, `source_mtime`, `source_size`, `source_id`, `source_locator`, `source_sequence`, `source_record_*`, `source_system_key` | A fact about the upstream evidence container |
| The vendor's own value | `source_status`, `source_call_id`, `source_tool_name`, `source_started_at`, `source_turn_id`, `source_field`, `source_value`, `source_params`, `source_cwd`, `source_file` | The exact upstream value, retained beside its normalized form |

The second group is why `source` could not simply be banned: `source_status`
beside `normalized_status` is the pattern that keeps vendor evidence inspectable,
and it reads correctly. What did not read correctly was a third use --
`sessions.source` holding an adapter key -- which is neither a Source fact nor a
vendor value. It is `adapter_key` as of format 11.

**No table was ever renamed.** `git log -S` over the DDL finds no prior spelling
for `event_content`, and no singular `session` table ever existed. The names have
been what they are since the schema was introduced; what changed is that one
column stopped borrowing a word that already had two jobs.

**Two Session listings exist and they answer differently, which is correct.**
`query --sessions --output-format jsonl` emits `codess.query-row/1`, whose
`sessionData` requires a non-null `source`; it is built from `selected_sessions`,
where the column now arrives as `adapter_key` and is emitted under the contract's
`source` key. The typed `query sessions` action emits `codess.query-result/1`,
whose `rows` are deliberately unconstrained, and its rows carry no `source` at
all -- they carry `source_system_key`, `vendor_name`, and `harness_name`, which
are the three separable facts the adapter key summarises.

Both are right for their contract, and the released schemas say so: one pins the
row shape, the other pins the envelope and leaves rows open. A reader comparing
the two should not expect `source` in the typed result, and the absence is not a
dropped field.

## Plurality

**The rule: countable entities are plural; mass nouns are singular.**

CoSchema follows it: 19 of 24 tables are plural, and all five exceptions are
mass nouns -- `store_meta` and the four `*_content` tables.

`event_artifacts` is correctly plural, and the proposal to pluralize
`event_content` to match it is withdrawn. The two names disagree because the
nouns differ, not because the convention does.

**Re-opened and re-confirmed against the corpus, because the first answer was
right for a reason that does not hold.** The earlier reasoning was that a link
table holds at most one row per owner, so the noun is a mass noun. That is false:
`event_content` is keyed `(event_id, relation_kind)`, and the key is used. Across
the two populated stores it averages 1.335 and 1.309 rows per Event, and 13,622
Events in the Claude store carry two -- a `body` beside a `tool.output`. A table
averaging more than one row per owner is holding a countable set by any test that
counts.

The name is still right, and the reason is the noun rather than the cardinality.
`content` is a mass noun in English: two content rows are not "two contents". The
pluralization test is the noun's own grammar, not how many rows an owner has --
which is exactly why `event_artifacts`, whose noun *is* countable, is plural
while sitting on the same shape of key. Recorded because the withdrawn proposal
would otherwise be re-derived from the cardinality, which points the other way.

## Command Arguments

A flag is a designator like any other, so the rules above apply to it: one
spelling per subject, and a name that says what the value *is* rather than what
type carries it. Four measured conventions, each recorded because a flag was
declared against it.

### Which Options Take a Variable

**A flag names this invocation's subject; a variable states a standing choice.**
That is the rule, and the distribution across 168 distinct flags follows it
closely enough to be checkable rather than asserted:

| Topic | Flag only | Has a default | Has a variable |
|---|---|---|---|
| Selection (`--dir`, `--project-id`, `--session-id`) | 11 | 0 | 0 |
| Policy (`--raw-mode`, `--redact`, `--resource-policy`) | 1 | 1 | 5 |
| Bounds (`--min-size`, `--days`, `--keep`) | 5 | 9 | 4 |
| Action (`--force`, `--apply`, `--no-hash`) | 9 | 0 | 5 |
| Store (`--store`, `--snapshot`) | 4 | 0 | 2 |
| Output (`--output`, `--format`) | 4 | 2 | 2 |

**Selection is entirely flag-only, and that is the rule working rather than an
omission.** No machine-wide variable can sensibly name which Session an
operator is asking about. Policy is the inverse -- five of seven carry a
variable -- because a policy is exactly the kind of choice made once for a
machine and inherited by every run.

**A default without a variable is a discovered location or a measured bound.**
`--claude-root` defaults to `CC_PROJECTS`, `--max-record-bytes` to a measured
limit: the value is derived or evidenced rather than chosen, so an operator who
wants a different one says so per run, and there is nothing for a variable to
override that the default does not already state.

**A variable without a flag is a machine policy no run should vary.**
`CODESS_KEEP_SNAPSHOTS` is the only one: retention depth governs the trim that
follows every publication, and a flag there would let one ingest quietly change
what a later one retains. `codess storage prune --keep` overrides it for a
deliberate reclaim, which is a different command answering a different question.

### One Spelling per Subject

**A flag name means the same thing in every command that takes it.** Three
spellings named two subjects each, which a caller moving between subcommands
could not see:

| Was | Now | The two subjects |
|---|---|---|
| `--project` | `--directory` for the directory; `--project` keeps the reference | A Project *reference* -- id, name, or path as text -- against a *directory on disk* |
| `--selection` | `--select` for the state; `--file` for the path | A reviewed selection *state* to filter by against the selection *file* to read |
| `--store` | `--store` for the durable store; `--store-file` for the file | The machine's durable store *directory* against one source-system store *file* |

**`--since` is deliberately left naming two subjects.** It is a git date
expression under `catalog candidates`, passed to `rev-list --since`, and a Unix
millisecond timestamp under `query`. Both are correct for their command, because
each matches the vocabulary of the surface it wraps -- renaming either would make
one command disagree with the tool underneath it. The exemption is named in
`test_a_flag_name_declares_one_type` rather than left to be rediscovered.

### `--dir` and `--directory` Are Two Flags

They differ in arity, not in subject, and the difference is load-bearing:

| | `--dir` | `--directory` |
|---|---|---|
| Arity | Repeatable (`action="append"`) | Singular |
| Required | No in the CLI; yes in the audit tools | Yes |
| Empty | Falls back to the current or Project root | Rejected by argparse |
| Companion | `--dirs`, a *file* listing directories | none |
| Callee takes | `list[Path]` | one `Path` |

`--dir` is the Project **selector**: it accumulates a set, defaults when omitted,
and every consumer routes through `resolve_cli_roots`, which merges it with the
`--dirs` file and validates each root. It is the documented selector for `scan`,
`ingest`, and `query`, appearing 33 times across README and Operations.

`--directory` is a required singular **operand**: the one directory a command
acts on. Every callee -- `add_project_location`, `retire_location`,
`validate_project`, `apply_project` -- takes exactly one `Path`, so there is no
list to pass and a default would be a guess.

**Merging them was considered and rejected.** One name would stop predicting
arity: `catalog location retire --dir X` would be singular and required while
`scan --dir X` stayed repeatable and optional, which is the same
one-name-two-behaviours defect the renames above removed. It would also break
the `--dir`/`--dirs` pairing on commands that have no list file, and it would
turn five commands' "no argument is an error" into "no argument means here",
which is a default appearing where a refusal used to be.

### Type States the Subject

A filesystem path is `type=Path` -- 84 declarations already were. Everything else
omits `type` and takes argparse's `str`. An explicit `type=str` is reserved for
the case a reader would otherwise assume a path, and says why in a comment:

| Flag | Why `str` | Would break as `Path` |
|---|---|---|
| `--source` | A comma-separated vendor spec | Nothing, but the name suggests a file |
| `--out` | `-` is the stdout sentinel | `Path("-")` is a relative file named `-` |

`--content-policy` was `type=str, metavar="JSON"` for an argument the consumer
wraps in `Path(...)`; the metavar named the file's *content* rather than the
argument. It is `type=Path, metavar="PATH"`.

**A setting may still arrive as either.** `content_policy` and `resource_policy`
are `Path | str | None`: a `Path` from the flag and a `str` from the environment
variable, since `env_str` reads text. The consumer normalizes, and that
normalization is not redundant -- removing it breaks the environment spelling.

### A Shared Option Is Declared Once

Seven options are declared on a parent parser and inherited via argparse's
`parents=`: `--store`, `--output`, `--project-id`, `--source`, `--project`,
`--policy`, and `--reviewed`. `--store` had been written out 22 times, 19 of them
byte-identical, and `--output` 11 times identically.

An inherited option renders exactly as a locally declared one, so the
deduplication is invisible to a caller: `--help` was dumped for all 45 parsers
before and after, and every subcommand accepts the same option set. What changed
is help text, which is the point -- one declaration carries one help string to
every inheritor.

**A form that genuinely differs keeps its own declaration.** `--store` is
`required=True` for one command, one `--project-id` is repeatable, `--catalog` is
required for two commands and defaulted for a third, and `catalog candidates`
takes a comma-separated `--source` where the shared one takes `choices`.
Inheriting any of those would change what that subcommand accepts, which is a
behaviour change wearing a deduplication's clothes.

## Renames

Every accepted rename, stated once. The stored ones are wire-format, so each
requires regenerating every store; the command-argument ones are not, and cost a
caller's script instead.

### Command Arguments

**Breaking for the named subcommands, and not for any store.** A renamed flag
changes what a caller types; nothing on disk moves.

| From | To | Where | Why |
|---|---|---|---|
| `--project` | `--directory` | `baseline validate\|apply\|recover-pointer`; `apply_and_verify`, `retire_project`, `validate_snapshot`, `demo_model_metrics` | The value is a directory, and `--project` names a *reference* elsewhere in the same CLI |
| `--path` | `--directory` | `catalog location add\|retire` | Said only that the value is a path, which `type=Path` already says |
| `--selection` | `--select` | `catalog candidates` | The value is a selection *state*, and the flag now names filtering by one |
| `--selection` | `--file` | `baseline freeze`; `freeze_reviewed_baselines` | The selection is already the subcommand's subject, so the flag names which part of it |
| `--store-root` | `--store` | `demo_model_metrics` | One spelling for the durable store, matching the CLI |
| `--store` | `--store-file` | `demo_model_metrics` | Freed the CLI spelling: this one is a source-system store *file*, not the durable store |
| `--registry` | `--store` | every command | Selects the machine's durable store; `registry` named one file inside it |

### Digest and Fingerprint

**Both words are kept, because they answer different questions about the same
value.** `digest` states how it was computed; `fingerprint` states what job it
does. A revision value spells both -- `full-digest-fingerprint`,
`bounded-sample-digest-fingerprint` -- and the leading qualifier states a third
thing, the coverage:

| Part | Answers | Values in use |
|---|---|---|
| `full` / `bounded-sample` / `sqlite-main-wal` / `edge` | What was read | Complete file, sampled windows, two SQLite forks, first/last bytes |
| `digest` | How the read was reduced | Always the `hashing` construction |
| `fingerprint` | What the value is for | Detecting that content changed |

Dropping `fingerprint` would leave `full-digest`, which says how a value was made
and not that it identifies content -- and CoSchema is explicit that a fingerprint
alone does not identify a Source, so the role needs its own word. Dropping
`digest` would leave `full-fingerprint`, which cannot distinguish a digest from a
size-and-mtime pair, and Cursor's edge method is exactly that distinction.

A bare `fingerprint` with no `digest` would be the right name for a
non-cryptographic change detector. None currently exists; if one is added, the
absence of `digest` is what will say so.

### Digest Fields

**A field holding a digest is named `*_digest`, never `*_sha256`.** The
algorithm's name lives in `hashing` and nowhere else, so changing it is one
edit rather than a rename across every document that carries a value.

The failure the rule prevents is subtle and has occurred: a value produced by
`codess_canonical_hash(256, 256, …)` *is* a bare SHA-256 at those widths, so a
`_sha256` name reads as accurate. Change either width and the name is wrong with
nothing to catch it -- the value still exists, still verifies against itself, and
now lies about what it is.

**The ten that carried the algorithm moved in format 11**, batched with the
identity and time-suffix renames so the regeneration was paid once rather than
ten times: `selection_digest`, `stored_digest`, `resolved_selection_digest`,
`catalog_digest`, `raw_manifest_digest`, `manifest_digest`, and four singletons.
`plan_digest` went earlier and alone, because a retention document is produced
per run and read immediately, so it cost one version bump and no stored data --
which is the test for whether a digest rename can travel by itself.

The one exception is `hashlib.sha256`, which names the algorithm because it *is*
the algorithm. The rule constrains what a stored field is called, not what the
function that computes it is called, and `hashing.ALGORITHM_TOKENS` holds the
spellings a checker looks for so no other module keeps its own copy.

**Two shapes a field-name survey cannot see, both moved in format 12.** A
`"sha256"` *key* nested inside an object -- one per released file in
`schema/coschema/manifest.json`, one per store in every snapshot manifest -- and
an emitted `sha256:` *value prefix*, which reached `request_hash`,
`result_hash`, every citation digest, raw object ids, the raw object directory,
and the worktree revision suffix. Both are `digest` now.

The lesson is about the survey rather than the names: three passes looked for
`*_sha256` and found field names each time, because that is the shape a grep for
a suffix returns. A key inside a per-file object and a prefix inside a value are
the same defect wearing a shape the search could not match.

### Stored Names

**Landed.** The model-parameter set went in one regeneration:

| From | To | Why |
|---|---|---|
| `global_id` | `entity_id` | Named the value by where it was *not* valid; the scope is already in the value's `codess:<kind>:` prefix |
| `sources.source_uri` | `source_path` | Held a bare absolute path on all 407 real rows -- none carried a scheme, which RFC 3986 requires, while `artifacts.uri` does |
| `content_derivations.input_content_id`, `output_content_id` | *dropped* | Required a hash of every processed input and output that nothing compared |
| `model_configurations` | `model_params` | Independent parameters a user selects, not a configuration Codess composes |
| `model_config_id` | `model_param_id` | Follows the table |
| `sessions.default_model_config_id` | `session_model_param_id` | `default_` asserted a fallback role; the value is a Session-level statement Codex and Cursor make and Claude does not |
| `model_family` | `model_gradation` | The column held a capability level, and `family` invited storing a line in it |
| `source_config` | `source_params` | Follows the table |
| *(new)* | `model_line`, `model_generation`, `model_version`, `model_variant` | Axes the decomposition separated, each with a CLI filter |

**Landed in CoSchema format 5:**

| From | To | Why |
|---|---|---|
| `package_digest` | `contract_digest` | Covers the six-file contract, not the Python package |
| `content_sha256`, `policy_sha256` | `content_digest`, `policy_digest` | Algorithm names live in `hashing` alone. `digest` rather than `hash`: the column holds a digest value, and `codess_hash` is the function that produces it |
| `plan_sha256` | `plan_digest` | The same rule, applied to a field the earlier pass did not reach. The value is what `codess_canonical_hash` returns, which is a bare SHA-256 *only because* the widths are currently 256/256 -- so the name is accurate today and silently stops being so when a width changes. `codess.retention-plan` and `-receipt` go to `/2`, since a `/1` consumer declares a field a `/2` document does not carry |
| `codess:<kind>:sha256:` in stored values | `codess:<kind>:id1:` | Names the derivation scheme instead of the algorithm, so a reader can tell two schemes apart and changing the algorithm is not a wire-format change |
| `tool_invocations.started_at` | `source_started_at` | Distinguishes vendor-reported from Codess-recorded times |
| `events.state.product` | four kinds | `session.label`, `harness.setting`, `content.attachment`, `session.marker` |
| `allow_package_mismatch`, `--snapshot-package-policy` | `allow_contract_mismatch`, `--snapshot-policy` | The value compared is the contract digest. Both superseded spellings are removed rather than aliased: the flag names the policy, and the policy has one subject |

**Landed in CoSchema format 6:**

| From | To | Why |
|---|---|---|
| `sessions.product_name` | *dropped* | A pure function of `source_system_id` |
| `mapping_diagnostics.level` | `granularity` | Held `source`/`record`/`field`, a granularity, while `field_state` uses `level` for severity |

**Landed in CoSchema format 11**, the identity and time-suffix batch:

| From | To | Why |
|---|---|---|
| `sessions.source` | `adapter_key` | Holds the `SOURCE_PROFILES` key, not the Source entity |
| `sessions.source_system_id`, and the column in `sources` and `workspace_bindings` | `source_system_key` | A composed literal, not an assigned identifier. All three carry the same value, so all three move together |
| `sources.observed_at`, `sessions.observed_at`, `project_locations.observed_at` | `observed_when` | Codess-recorded RFC 3339 text; see [Time Suffixes](#time-suffixes) |
| `processing_runs.started_at`, `completed_at` | `started_when`, `completed_when` | Removes the one time name denoting two representations |
| `mapping_diagnostics.created_at` | `created_when` | Codess-recorded |
| `correlation_assertions.asserted_at` | `asserted_when` | Codess-recorded |
| The ten `*_sha256` fields | `*_digest` | [Digest Fields](#digest-fields). `sources.content_sha256` was already gone -- `field-coverage-baseline.json` was still naming a column dropped in format 5, which is what a rename pass finds and a review does not |

`sessions.started_at` keeps its name and is the reason the rule is worth stating:
it is `REAL` vendor-recorded milliseconds, so it is already correct under the
suffix rule while the `TEXT` column two rows below it was not.

**What the batch deliberately did not reach, and why.** Three name families carry
the superseded spellings and are governed by their own versioned contracts, so
renaming them with CoSchema would break a document the CoSchema bump does not
otherwise touch:

| Name | Where | Its own version |
|---|---|---|
| `source_system_ids` | The typed query request's filter key | `codess.query-request/1` |
| `observed_at` | Catalog location records, refresh receipts, raw-manifest rows | Each states its own format |

Each is a rename with a real argument and a separate cost. A CoSchema format
bump is not a licence to renumber every other contract in the repository, and
batching is only economical among names that regenerate together.

**Landed in CoSchema format 12**, the batch that finished the two rules format 11
started:

| From | To | Why |
|---|---|---|
| `product` in the mapping contract and the three profiles | `harness_name` | Named the program, which `harness_name` already holds. Cursor's value moves `cursor-composer` to `cursor`, because `composer` named a surface `surface_kind` carries in its own column |
| `"sha256"` key in each `manifest.json` file and store entry | `digest` | The rule's own subject at a nesting level a field-name survey cannot see |
| `sha256:` value prefix | `digest:` | Reaches `request_hash`, `result_hash`, citation digests, raw object ids, the raw object directory, and the worktree revision suffix |
| `"source"` in the query row | `adapter_key` | Format 11 renamed the column and left the row emitting the old key, so one value had two names one layer apart |

Six documents carry a version for it: `codess.query-result/2`,
`codess.investigation/2`, `codess.query-row/2`, `codess.raw/2`,
`codess.source-verification/2`, and `codess.working-archive/2`.

**A second backward read, on the same rule as the first.** A snapshot manifest's
store entry is verified while its snapshot is being replaced, and a
`codess.raw/1` object id is read while its manifest is, so `store_claim` and
`_object_hash` accept either spelling and write only the current one. Both have a
test per spelling.

**One renamed key had to stay readable under its old spelling, and the rebuild
is what proved it.** `manifest_sha256` lives in every `current.json`, and a
rebuild *reads the pointer it is about to replace*. Renaming the key on both the
read and the write side made all 21 published Projects refuse to rebuild --
`invalid current snapshot pointer: 'manifest_digest'` -- with the release that
renamed it and no other. The same applies to `raw_manifest_sha256` in a stored
manifest, which is verified while its snapshot is being replaced.

The rule this yields: **a document Codess must read before it can write its
replacement accepts both spellings on read and emits only the current one on
write.** It is not a general alias -- a stored column has no such problem,
because a format change rebuilds the store from vendor Sources rather than
reading the old one. It applies to exactly the files that bootstrap a rebuild,
and `raw_manifest_claim` states it in one place with a test per spelling.

**The tolerance is needed only for the upgrade, and that is checkable rather
than asserted.** `current_snapshot` returns `None` before reading any key when
no pointer exists, so a **fresh ingest at format 11 never reads a format-10
name** -- a Project with no `.codess/` is unaffected either way. The read matters
for exactly one case, an existing published Project moving 10 to 11, which is
the case all 21 were in. Two tests hold both halves: a format-10 pointer
resolves, and a strict read of the same pointer raises `KeyError` -- the failure
that stopped the first rebuild attempt.

The consequence for a future rename is a question worth asking once: *can a
Project that has never been ingested still be ingested if this key is refused?*
When the answer is yes, the tolerance is upgrade-only and can be dropped after
the corpus moves. It has not been dropped here, because a store written by an
earlier release can be presented at any time -- from a backup, another machine,
or a Project not rebuilt in this pass.

**Still pending**, and not part of this batch:

| From | To | Why |
|---|---|---|
| `sessions.vendor_name` | *records the company* | `cursor` is a product; Anysphere is the vendor. A decode change rather than a rename: the column name is right and its value is wrong, so a regeneration alone would not fix it |
| `units.epoch_milliseconds` | `timeval.epoch_ms` | `_ms` is the convention the same module already used for `SECOND_MS` and `DAY_MS`; landed, with the old name kept as an alias |

**Not renamed, and why.** `sources.id` -- a bare rowid is unremarkable.
`event_content` -- mass noun, see [Plurality](#plurality). `surface_kind`,
`harness_name` as *names* -- the concepts are right; only `harness_name`'s
Claude value is wrong, which is a decode fix rather than a rename.

## How to Use This Document

Before proposing a rename: find the concept in
[Designators](#vendor-and-harness-designators) or [Renames](#renames). If it is already recorded, the name is settled and
the proposal is redundant. If it is not, add the row here in the same change
that proposes it, so the next proposal is checked against a complete list.

Before adding a column: check that its suffix follows
[Identifier Suffixes](#identifier-suffixes) and its plurality follows
[Plurality](#plurality).
