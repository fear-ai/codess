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
| Harness | `sessions.harness_name` | profile `harness_name`; Codex decodes `originator` | `claude-code-cli`, `codex-cli`, `cursor-ide` |
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

**Three of these are wrong today** and are listed in
[Renames](#6-renames): `vendor_name` names a product for Cursor,
`harness_name` embeds a surface claim the decoded `surface_kind` contradicts,
and `product_name` is derivable from `source_system_id`.

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
| speed | `speed_tier` | `--speed-tier` | A separate dimension, named only when given | `fast` |

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

**A recorded strength does not prove it was selected.** A model offering only
one level states it the same way as one where the user chose among several, so
`high` occludes whether it was the only option. The value is evidence of what
ran, not of a decision.

**An unresolved name is recorded as such, never guessed.** The vendor string is
kept verbatim in `model_name_exact` in every case; only the derived columns are
left null, so "not recognized" stays distinct from "has none".

## 4. Identifier Suffixes

`_id` currently carries four incompatible formats, so a reader cannot tell from
the suffix whether a value is derived, assigned, or borrowed.

| Suffix | Means | Example |
|---|---|---|
| `_id` on a rowid | SQLite surrogate key, assigned locally | `sources.id`, `model_params.id` |
| `_id` from a vendor | Identifier the source system assigned | `sessions.id` (vendor UUID) |
| `global_id` | Derived by Codess from declared components | `codess:session:sha256:…` |
| `_key` | Composed literal, not an identifier | `sessions.source_system_id` (pending rename) |

The rule: **`_id` names an identifier something assigned; a composed or
descriptive literal takes `_key` or no suffix.** `source_system_id` violates it
and is renamed. A bare rowid named `id` is unremarkable and stays.

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
| `model_configurations` | `model_params` | Independent parameters a user selects, not a configuration Codess composes |
| `model_config_id` | `model_param_id` | Follows the table |
| `sessions.default_model_config_id` | `session_model_param_id` | `default_` asserted a fallback role; the value is a Session-level statement Codex and Cursor make and Claude does not |
| `model_family` | `model_gradation` | The column held a capability level, and `family` invited storing a line in it |
| `source_config` | `source_params` | Follows the table |
| *(new)* | `model_line`, `model_generation`, `model_version`, `model_variant` | Axes the decomposition separated, each with a CLI filter |

**Pending**, for the next regeneration:

| From | To | Why |
|---|---|---|
| `sessions.source` | `adapter_key` | Holds the `SOURCE_PROFILES` key, not the Source entity |
| `sessions.source_system_id` | `source_system_key` | A composed literal, not an assigned identifier |
| `sessions.vendor_name` | *records the company* | `cursor` is a product; Anysphere is the vendor |
| `sessions.product_name` | *dropped* | A pure function of `source_system_id` |
| `package_digest` | `contract_digest` | Covers the six-file contract, not the Python package |
| `content_sha256`, `policy_sha256` | `content_digest`, `policy_digest` | Algorithm names live in `hashing` alone |
| `tool_invocations.started_at` | `source_started_at` | Distinguishes vendor-reported from Codess-recorded times |
| `mapping_diagnostics.level` | *names granularity* | Holds `source`/`record`/`field`, a granularity, while `field_state` uses `level` for severity |
| `events.state.product` | four kinds | `session.label`, `harness.setting`, `content.attachment`, `session.marker` |

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
