# CoNames

CoNames states, once, what each thing Codess names is called in the database, in
the code, and on the command line. It exists because six work items proposed
renames independently, which is how the inconsistencies below arose: a name
decided against one call site contradicts the same concept named elsewhere.

Any proposed rename is checked against this document. Where a name here differs
from the one in the code, the difference is a scheduled change, recorded in
[Pending Renames](#5-pending-renames), not a discrepancy to fix locally.

Terminology for entities is [Codess 7](Codess.md#7-core-model-and-terminology),
which this document does not restate. CoNames covers designators -- the names of
companies, programs, files, keys, and columns -- which the glossary does not.

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
[Pending Renames](#5-pending-renames): `vendor_name` names a product for Cursor,
`harness_name` embeds a surface claim the decoded `surface_kind` contradicts,
and `product_name` is derivable from `source_system_id`.

## 3. Identifier Suffixes

`_id` currently carries four incompatible formats, so a reader cannot tell from
the suffix whether a value is derived, assigned, or borrowed.

| Suffix | Means | Example |
|---|---|---|
| `_id` on a rowid | SQLite surrogate key, assigned locally | `sources.id`, `model_configurations.id` |
| `_id` from a vendor | Identifier the source system assigned | `sessions.id` (vendor UUID) |
| `global_id` | Derived by Codess from declared components | `codess:session:sha256:…` |
| `_key` | Composed literal, not an identifier | `sessions.source_system_id` (pending rename) |

The rule: **`_id` names an identifier something assigned; a composed or
descriptive literal takes `_key` or no suffix.** `source_system_id` violates it
and is renamed. A bare rowid named `id` is unremarkable and stays.

## 4. Plurality

**The rule: countable entities are plural; mass nouns are singular.**

W53 recorded this as measured over four peer SQLite schemas on this machine --
56 tables, of which the 11 singular ones were all mass nouns. That measurement
no longer reproduces: three of the four databases are gone from disk and the
survivor has 6 tables, so the figure is retained as the rule's origin rather
than as current evidence. The rule stands on CoSchema itself, where 19 of 24
tables are plural and all five exceptions are mass nouns: `store_meta` and the
four `*_content` tables (`artifact_content`, `event_content`,
`source_record_content`, `tool_result_content`).
`store_meta` is correctly singular. `event_content` and the other three
`*_content` tables stay singular as English mass-noun usage, so there is no
`event_contents`; `event_artifacts` is correctly plural. The earlier proposal to
pluralize `event_content` for consistency with `event_artifacts` is withdrawn --
the two names disagree because the nouns differ, not because the convention does.

## 5. Pending Renames

Every rename accepted anywhere in CoPlan, stated once here. None has landed;
all are wire-format and land together in one regeneration.

| From | To | Why | Item |
|---|---|---|---|
| `model_configurations` | `model_params` | Independent parameters a user selects, not a configuration Codess composes | W54.3 |
| `model_config_id` | `model_param_id` | Follows the table | W54.3 |
| `sessions.default_model_config_id` | `session_model_param_id` | `default_` asserts a fallback role; the value is a Session-level statement only Codex makes | W54.3 |
| `sessions.source` | `adapter_key` | Holds the `SOURCE_PROFILES` key, not the Source entity | W51 |
| `sessions.source_system_id` | `source_system_key` | A composed literal, not an assigned identifier | W51 |
| `sessions.vendor_name` | *records the company* | `cursor` is a product; Anysphere is the vendor | W54.3 |
| `sessions.product_name` | *dropped* | A pure function of `source_system_id` | W40 |
| `package_digest` | `contract_digest` | Covers the six-file contract, not the Python package | W33 |
| `content_sha256`, `policy_sha256` | `content_digest`, `policy_digest` | Algorithm names live in `hashing` alone | W34 |
| `tool_invocations.started_at` | `source_started_at` | Distinguishes vendor-reported from Codess-recorded times | W25 |
| `mapping_diagnostics.level` | *names granularity* | Holds `source`/`record`/`field`, a granularity, while `field_state` uses `level` for severity | W50 |
| `events.state.product` | four kinds | `session.label`, `harness.setting`, `content.attachment`, `session.marker` | W36 |

**Not renamed, and why.** `sources.id` -- a bare rowid is unremarkable.
`event_content` -- mass noun, see [4](#4-plurality). `surface_kind`,
`harness_name` as *names* -- the concepts are right; only `harness_name`'s
Claude value is wrong, which is a decode fix rather than a rename.

## 6. How to Use This Document

Before proposing a rename: find the concept in [2](#2-vendor-and-harness-designators)
or [5](#5-pending-renames). If it is already recorded, the name is settled and
the proposal is redundant. If it is not, add the row here in the same change
that proposes it, so the next proposal is checked against a complete list.

Before adding a column: check that its suffix follows [3](#3-identifier-suffixes)
and its plurality follows [4](#4-plurality).
