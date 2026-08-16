# CoNames

CoNames is the authoritative source for what each thing Codess names is called
in the database, in the code, and on the command line. Where another document
disagrees with it, this document is right and the other is stale. It exists
because six work items proposed renames independently, which is how the
inconsistencies below arose: a name decided against one call site contradicts
the same concept named elsewhere.

Any proposed rename is checked against this document, and a landed one is
recorded in it. Where a name here differs from the one in the code, the
difference is a scheduled change listed under [Renames](#6-renames), not a
discrepancy to fix locally.

**Scope.** CoNames names things. What those things *mean* is
[Codess 7](Codess.md#7-core-model-and-terminology) for entities and
[CoSchema](CoSchema.md) for fields; neither is restated here.

CoNames covers designators -- the names of companies, programs, files, keys, and
columns -- which the glossary does not.

## 1. The Four Facts a Name May Refer To

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

## 2. Vendor and Harness Designators

Each row is one concept. The columns are the places that concept is named.

| Concept | DB column | Code | Values |
|---|---|---|---|
| Adapter key | `sessions.source` | `store.SOURCE_PROFILES` keys | `Claude`, `Codex`, `Cursor` |
| Vendor | `sessions.vendor_name` | profile `vendor_name` | `anthropic`, `openai`, `cursor` |
| Harness | `sessions.harness_name` | profile `harness_name`; Codex decodes `originator` | `claude-code`, `codex`, `cursor` |
| Surface | `sessions.surface_kind` | `adapters/cc._CC_SURFACE`, `adapters/codex._CODEX_SURFACE` | `cli`, `desktop`, `ide`, `api` |
| Source system | `sessions.source_system_id` | profile, composed `vendor + "." + product` | `anthropic.claude-code`, `openai.codex`, `cursor.composer` |
| Product | `sessions.product_name` | profile `product_name` | `claude-code`, `codex`, `cursor-composer` |
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

**Two of these are still wrong** and are listed in [Renames](#6-renames):
`vendor_name` names a product for Cursor, and `product_name` is derivable from
`source_system_id`. Removing the surface suffix makes `harness_name` and
`product_name` identical for Claude and Codex, which is the same finding from
the other side: with the surface in its own column, the program and the product
are one fact spelled twice, and `product_name` is the copy to drop.

**Only Codex names its own program.** Claude states a surface (`entrypoint`) and
no program; Cursor states neither, so both take the profile constant.

## 3. Model Name Parts

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

**Hashing is for identity, integrity, and content addressing -- not for naming.**
Evaluated across all 51 remaining call sites: 4 derive a cross-store identity, 10 are integrity
digests a reader recomputes, 6 are the raw store's content addresses, and 9 are change
detection. The rest were convenience -- a dict or a path hashed to get a name for it --
and two were written and never read at all.

**A name a process invents needs no digest.** A within-run label takes an index; a
temporary directory takes the platform's own facility. Hashing a path to name a staging
directory implied a stable identity the value neither had nor needed.

**A file test records four `stat` facts, and each earns its place**: `size` catches
any length change and is the cheapest discriminator; `mtime_ns` catches an in-place
edit of the same length, at nanosecond resolution because a second-resolution stamp
misses fast successive writes; `inode` catches a replacement by rename, which can carry
the same size and a copied timestamp; `device` because an inode is unique only within a
filesystem. `st_ctime` is excluded -- it moves on a permission change, which is not a
content change -- as are `st_nlink` and `st_mode`, which describe the link rather than
the bytes.

**Three questions, three functions, chosen by what the caller does with the answer.**
`file_unchanged` returns a boolean and suits a caller deciding whether to re-read.
`file_changes` returns `{field: (was, is)}` and suits a caller explaining a difference,
because "size 4,096 to 8,192" and "same size, new inode" are different findings that a
hash comparison flattens into "differs". `read_source_revision` reads content and answers
byte identity, by one size-driven policy: full read under the configured maximum,
sampled windows above it, inode-and-size for a SQLite container.

**Change detection asks a different question from integrity.** `fileio.file_state`
records `(size, mtime_ns, inode)` and `file_unchanged` compares it: that answers "is
this the same file", which is what decides whether to re-read. `read_source_revision`
reads content and answers "are these the same bytes". The first is 216x cheaper on the
real corpus and sufficient for its question; the second is required where byte identity
is the claim. **The inode matters**: a file replaced by rename can carry the same size
and a copied mtime, so those two alone report it unchanged.

**Parsing methods, in the order a decoder should reach for them.** Vendor evidence is
overwhelmingly JSON, so the first choice is a real parser and the last is a regular
expression over free text.

| Method | Uses | Modules | Applies to |
|---|---|---|---|
| `json.loads` | 98 | 38 | vendor records, envelopes, stored metadata |
| SQLite `json_extract` / `json_valid` | 42 | 6 | querying stored JSON without materializing it |
| `str.startswith` / `endswith` | 38 | 17 | prefix classification (`mcp__`, `codess:`) |
| `re` | 31 | 9 | genuinely irregular text, such as the Codex output header |
| `str.split` / `partition` | 20 | 15 | known single separators |
| `removeprefix` / `removesuffix` | 4 | 4 | stripping a declared prefix |
| `datetime.fromisoformat` | 7 | 6 | vendor timestamps |
| `urllib.parse` | 8 | 4 | Artifact URIs |

**SQLite JSON or Python JSON, measured rather than assumed.** Both parse the same
blobs; which is faster depends on how much crosses the boundary, and the intuition that
"push it into the database" always wins is wrong here.

| Case | `json_extract` | `json.loads` |
|---|---|---|
| Extract a field present on most rows (9,695 of 14,267) | 0.104s | **0.025s** |
| Filter where almost nothing matches | **0.009s** | 0.024s |

**The rule: filter in SQLite, read in Python.** Concretely:

```sql
-- Yes: the predicate is selective, so non-matching rows never cross the boundary.
SELECT event_id, content FROM events
WHERE json_extract(metadata,'$.parent_uuid') = ?;
```

```python
# Yes: the rows are being read anyway, so parse once in Python rather than
# asking SQLite to parse the same blob per extracted path.
for row in conn.execute("SELECT event_id, metadata FROM events WHERE metadata IS NOT NULL"):
    meta = json.loads(row["metadata"])
    uuid, parent = meta.get("record_uuid"), meta.get("parent_uuid")
```

```sql
-- No: three extractions parse the same blob three times, for rows already selected.
SELECT json_extract(metadata,'$.record_uuid'),
       json_extract(metadata,'$.parent_uuid'),
       json_extract(metadata,'$.tool_use_id') FROM events;
```
 A selective predicate belongs in the
query, because rows that do not match never cross the boundary. A field wanted from
rows already being read belongs in Python, whose parser is faster than SQLite's and
runs once per row rather than once per extracted path. The 3.6 MB of metadata in one
Project is small enough that transfer is not the deciding cost either way; the
deciding cost is how many times each blob is parsed.

**A regular expression is the last resort, and never over JSON.** The one substantial
use is Codex's output header, where fields are optional, reorderable, and doubly
spelled -- `Wall time:` and `Wall time` -- which `split` cannot express and
`startswith` cannot extract from. Even there the match is per line, so an unrecognized
line rejects the whole header rather than half-populating it.

## 4. Identifier Suffixes

`_id` currently carries four incompatible formats, so a reader cannot tell from
the suffix whether a value is derived, assigned, or borrowed.

| Suffix | Means | Example |
|---|---|---|
| `_id` on a rowid | SQLite surrogate key, assigned locally | `sources.id`, `model_params.id` |
| `_id` from a vendor | Identifier the source system assigned | `sessions.id` (vendor UUID) |
| `entity_id` | Derived by Codess from declared components | `codess:session:id1:…` |

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
| `_key` | Composed literal, not an identifier | `sessions.source_system_id` (pending rename) |

The rule: **`_id` names an identifier something assigned; a composed or
descriptive literal takes `_key` or no suffix.** `source_system_id` violates it
and is renamed. A bare rowid named `id` is unremarkable and stays.

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

## 5. Plurality

**The rule: countable entities are plural; mass nouns are singular.**

CoSchema follows it: 19 of 24 tables are plural, and all five exceptions are
mass nouns -- `store_meta` and the four `*_content` tables.

`event_artifacts` is correctly plural, and the earlier proposal to pluralize
`event_content` to match it is withdrawn: the two names disagree because the
nouns differ, not because the convention does.

## 6. Renames

Every accepted rename, stated once. All are wire-format, so each requires
regenerating every store.

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
| `codess:<kind>:sha256:` in stored values | `codess:<kind>:id1:` | Names the derivation scheme instead of the algorithm, so a reader can tell two schemes apart and changing the algorithm is not a wire-format change |
| `tool_invocations.started_at` | `source_started_at` | Distinguishes vendor-reported from Codess-recorded times |
| `events.state.product` | four kinds | `session.label`, `harness.setting`, `content.attachment`, `session.marker` |
| `allow_package_mismatch`, `--snapshot-package-policy` | `allow_contract_mismatch`, `--snapshot-contract-policy` | The value compared is the contract digest. The old flag spelling stays as a hidden alias, since it is a published CLI surface |

**Pending**, for the next regeneration:

| From | To | Why |
|---|---|---|
| `sessions.source` | `adapter_key` | Holds the `SOURCE_PROFILES` key, not the Source entity |
| `sessions.source_system_id` | `source_system_key` | A composed literal, not an assigned identifier |
| `sessions.vendor_name` | *records the company* | `cursor` is a product; Anysphere is the vendor |
| `sessions.product_name` | *dropped* | A pure function of `source_system_id` |
| `mapping_diagnostics.level` | *names granularity* | Holds `source`/`record`/`field`, a granularity, while `field_state` uses `level` for severity |

**Not renamed, and why.** `sources.id` -- a bare rowid is unremarkable.
`event_content` -- mass noun, see [5](#5-plurality). `surface_kind`,
`harness_name` as *names* -- the concepts are right; only `harness_name`'s
Claude value is wrong, which is a decode fix rather than a rename.

## 7. How to Use This Document

Before proposing a rename: find the concept in [2](#2-vendor-and-harness-designators)
or [6](#6-renames). If it is already recorded, the name is settled and
the proposal is redundant. If it is not, add the row here in the same change
that proposes it, so the next proposal is checked against a complete list.

Before adding a column: check that its suffix follows [4](#4-identifier-suffixes)
and its plurality follows [5](#5-plurality).
