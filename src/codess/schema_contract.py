"""CoSchema package identity, integrity, database compatibility, and mappings."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path
from typing import Any

from codess.fileio import hash_file
from codess.hashing import codess_digest
from codess.processing_contract import DECODER_VERSION, VALIDATOR_VERSION

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = REPO_ROOT / "schema" / "coschema"
MANIFEST_PATH = PACKAGE_ROOT / "manifest.json"
CONTRACT_PATH = PACKAGE_ROOT / "contract.json"
DDL_PATH = PACKAGE_ROOT / "sqlite" / "schema.sql"
MAPPINGS_ROOT = REPO_ROOT / "schema" / "mappings"

FORMAT_ID = "codess.coschema"
FORMAT_VERSION = 4
APPLICATION_ID = 0x434F4445
SUPPORTED_READ_FORMATS = frozenset({4})
SUPPORTED_WRITE_FORMATS = frozenset({4})


class SchemaContractError(RuntimeError):
    """The packaged contract is missing, inconsistent, or unsupported."""


class UnsupportedStoreError(SchemaContractError):
    """A database is not writable/readable by this software contract."""


log = logging.getLogger(__name__)

CONTRACT_OVERRIDE_ENV = "CODESS_NO_CONTRACT_CHECK"


def contract_check_disabled() -> bool:
    """Whether the operator has opted out of contract checking.

    Two situations use this. A test may exercise a store whose recorded
    contract deliberately disagrees. A recovery may read or extend a store
    when the released files that produced it are no longer reconstructible --
    vendor sources deleted, a working tree partly restored -- where refusing
    the write protects nothing and leaves retained evidence unreachable.

    Read from the environment rather than `config`, for the same reason
    `fileio._no_hash_active` does: `--no-check` sets the variable after
    config's module-level constants have resolved, so reading the constant
    would miss a flag set on the command line.

    The override is not the default and warns. Each bypass logs a warning,
    and a store written under it records `contract_override` in `store_meta`.
    """
    return os.environ.get(CONTRACT_OVERRIDE_ENV, "0").strip().lower() in (
        "1", "true", "yes",
    )


@lru_cache(maxsize=1)
def load_manifest() -> dict[str, Any]:
    try:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SchemaContractError(f"cannot load CoSchema manifest: {exc}") from exc
    if manifest.get("format_id") != FORMAT_ID:
        raise SchemaContractError("CoSchema manifest format_id mismatch")
    if manifest.get("format_version") != FORMAT_VERSION:
        raise SchemaContractError("CoSchema manifest format_version mismatch")
    if manifest.get("application_id") != APPLICATION_ID:
        raise SchemaContractError("CoSchema manifest application_id mismatch")
    if manifest.get("decoder_version") != DECODER_VERSION:
        raise SchemaContractError("CoSchema manifest decoder_version mismatch")
    if manifest.get("validator_version") != VALIDATOR_VERSION:
        raise SchemaContractError("CoSchema manifest validator_version mismatch")
    return manifest


CONTRACT_ROLES = frozenset({
    "sqlite_schema",
    "contract",
    "mapping_contract",
    "mapping_claude",
    "mapping_codex",
    "mapping_cursor",
})
"""The manifest roles that determine what a store *is*.

These six files are loaded by `src/` at runtime: the DDL fixes the physical
layout, `contract.json` the logical one that `validate_database_contract`
checks against, and the mapping contract and three profiles the mapping
evidence attached to decoded records. Nothing outside this set can change the
layout or the decode of a store, which is the only question the write gate
asks.

The manifest's remaining entries are validation fixtures. They are verified
by `verify_package`, which is a release and diagnostic operation, and they
are deliberately excluded from `contract_digest` -- see 13.4.4.
"""


def _digest_manifest_files(roles: Iterable[str] | None, subject: str) -> str:
    """Verify the named released files and fold them into one digest.

    `roles` selects a subset of the manifest by role name, or every file when
    None. Each file is hashed and compared with its recorded value, and the
    per-file hashes are folded in role order so the result is deterministic
    and independent of filesystem ordering.
    """
    manifest = load_manifest()
    entries = sorted(
        (role, entry)
        for role, entry in manifest.get("files", {}).items()
        if roles is None or role in roles
    )
    failures: list[str] = []
    combined = codess_digest()
    for role, entry in entries:
        path = REPO_ROOT / entry["path"]
        if not path.is_file():
            failures.append(f"{role}: missing {entry['path']}")
            continue
        actual = hash_file(path)
        if actual != entry.get("sha256"):
            failures.append(
                f"{role}: hash mismatch for {entry['path']} "
                f"({actual} != {entry.get('sha256')})"
            )
        combined.update(role.encode("utf-8"))
        combined.update(b"\0")
        combined.update(actual.encode("ascii"))
        combined.update(b"\n")
    if failures:
        if contract_check_disabled():
            # Report the digest of what is on disk, so a recovery run is
            # reproducible and the caller sees what it proceeded with.
            log.warning(
                "%s: proceeding despite %d failure(s) because %s is set: %s",
                subject, len(failures), CONTRACT_OVERRIDE_ENV, "; ".join(failures),
            )
        else:
            raise SchemaContractError(f"invalid {subject}: " + "; ".join(failures))
    return combined.hexdigest()


@lru_cache(maxsize=1)
def contract_digest() -> str:
    """Verify the executable contract and return its digest.

    This is the value a store records and the write gate compares. It answers
    one question -- *would extending this store mix records written under
    different rules?* -- and only the six files in `CONTRACT_ROLES` can change
    that answer.

    It replaces a digest over the whole manifest, of which ten of sixteen
    entries were validation fixtures. Editing one made every published store
    unwritable although its layout, decoder, and data were unchanged, and a
    fixture edit that had not yet updated the manifest broke the loaders
    below as well -- so a half-finished edit to a test document disabled the
    program rather than only the write path (13.4.4).
    """
    return _digest_manifest_files(CONTRACT_ROLES, "CoSchema executable contract")


@lru_cache(maxsize=1)
def verify_package() -> str:
    """Verify every released package file and return a deterministic digest.

    A release and diagnostic operation: it answers "is this working tree the
    reviewed one", which covers the validation fixtures as well as the
    contract. Runtime paths use `contract_digest` instead, because a store's
    compatibility does not depend on test data.
    """
    return _digest_manifest_files(None, "released CoSchema package")


@lru_cache(maxsize=1)
def load_contract() -> dict[str, Any]:
    contract_digest()
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def load_ddl() -> str:
    contract_digest()
    return DDL_PATH.read_text(encoding="utf-8")


def load_mapping(name: str) -> dict[str, Any]:
    contract_digest()
    if name not in {"claude", "codex", "cursor"}:
        raise SchemaContractError(f"unknown mapping profile: {name}")
    mapping = json.loads(
        (MAPPINGS_ROOT / f"{name}.json").read_text(encoding="utf-8")
    )
    if mapping.get("decoder_version") != DECODER_VERSION:
        raise SchemaContractError(
            f"{name} mapping decoder_version differs from {DECODER_VERSION}"
        )
    return mapping


def validate_mapping(mapping: dict[str, Any]) -> list[str]:
    """Mechanically validate the deliberately small mapping-spec grammar."""
    contract = json.loads(
        (PACKAGE_ROOT / "mapping-contract.json").read_text(encoding="utf-8")
    )
    errors = [key for key in contract["required"] if key not in mapping]
    if mapping.get("direction") not in contract["direction_values"]:
        errors.append(f"invalid mapping direction {mapping.get('direction')!r}")
    rule_ids: set[str] = set()
    for index, rule in enumerate(mapping.get("rules", [])):
        for key in contract["rule_required"]:
            if key not in rule:
                errors.append(f"rules[{index}] missing {key}")
        rid = rule.get("id")
        if rid in rule_ids:
            errors.append(f"duplicate rule id {rid}")
        if rid is not None:
            rule_ids.add(rid)
        if rule.get("retention") not in contract["retention_values"]:
            errors.append(f"rules[{index}] invalid retention {rule.get('retention')!r}")
        if rule.get("operation", "from") not in contract["allowed_operations"]:
            errors.append(f"rules[{index}] invalid operation {rule.get('operation')!r}")
    return errors


def validate_mapped_event(mapping_name: str, event: dict[str, Any]) -> list[str]:
    """Verify that an adapter event carries executable mapping evidence."""
    mapping = load_mapping(mapping_name)
    mapping_contract = json.loads(
        (PACKAGE_ROOT / "mapping-contract.json").read_text(encoding="utf-8")
    )
    rule_ids = {rule["id"] for rule in mapping.get("rules", ())}
    errors: list[str] = []
    for field in mapping_contract["mapped_event_required"]:
        if not isinstance(event.get(field), str) or not event[field]:
            errors.append(f"missing scalar {field}")
    rule = event.get("mapping_rule")
    if rule and rule not in rule_ids:
        errors.append(f"undeclared mapping rule {rule}")
    trace_raw = event.get("mapping_trace")
    try:
        trace = json.loads(trace_raw) if isinstance(trace_raw, str) else trace_raw
    except json.JSONDecodeError:
        trace = None
    if not isinstance(trace, dict):
        errors.append("mapping_trace is not a JSON object")
    else:
        for applied in trace.get("applied_rules", ()):
            if applied not in rule_ids:
                errors.append(f"undeclared applied mapping rule {applied}")
    tool_input = event.get("tool_input")
    if tool_input is not None:
        try:
            json.loads(tool_input)
        except (TypeError, json.JSONDecodeError):
            errors.append("tool_input is not valid JSON")
    return errors


def database_identity(conn: sqlite3.Connection) -> tuple[int, int]:
    return (
        int(conn.execute("PRAGMA application_id").fetchone()[0]),
        int(conn.execute("PRAGMA user_version").fetchone()[0]),
    )


def table_names(conn: sqlite3.Connection) -> set[str]:
    """The tables a store actually has.

    Readers that must tolerate an older store ask this rather than catching
    an error per table, and it is also what keeps `table_counts` from having
    to carry a hand-maintained list of the schema.
    """
    return {
        str(row[0]) for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }


def column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    """Which columns one table has.

    Readers project a literal in place of a column an older store predates --
    `NULL AS entity_id` rather than a failing query -- and each asked SQLite
    for the column list itself. The identifier is quoted because it cannot be
    a bound parameter; callers pass a table name from the schema, not input.
    """
    return {
        str(row[1]) for row in conn.execute(f'PRAGMA table_info("{table}")')
    }


def store_metadata(conn: sqlite3.Connection) -> dict[str, str]:
    """Read a store's own metadata as a mapping.

    `store_meta` is a key/value table, so every reader wrote the same
    `dict(conn.execute(...))` and then picked one key out of it. Naming the
    read here puts it beside the other store-identity checks and gives the
    table one place to be queried, which is what a column rename would
    otherwise have to find at five call sites.
    """
    return dict(conn.execute("SELECT key, value FROM store_meta"))


def validate_database_contract(conn: sqlite3.Connection) -> list[str]:
    """Return two-way layout/JSON omissions against the logical contract.

    The contract deliberately leaves SQLite types and indexes to the physical
    schema. Explicitly classified physical compatibility details are excluded;
    every other table and column must have a logical definition.
    """
    errors: list[str] = []
    contract = load_contract()
    entities = contract["entities"]
    physical = contract.get("physical_contract", {})
    excluded_tables = set(physical.get("excluded_tables", ()))
    excluded_fields = {
        table: set(fields)
        for table, fields in physical.get("excluded_fields", {}).items()
    }
    tables = table_names(conn)
    for entity, definition in entities.items():
        if entity not in tables:
            errors.append(f"missing table {entity}")
            continue
        columns = column_names(conn, entity)
        expected_fields = set(definition.get("fields", {}))
        expected_fields.update(definition.get("identity", ()))
        expected_fields.update(definition.get("order", ()))
        for field in sorted(expected_fields):
            if field not in columns:
                errors.append(f"{entity}: missing column {field}")
        table_sql_row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (entity,)
        ).fetchone()
        table_sql = str(table_sql_row[0] or "") if table_sql_row else ""
        for field, field_definition in definition.get("fields", {}).items():
            if field_definition.get("type") not in {"json", "json_extension"}:
                continue
            if f"json_valid({field})" not in table_sql:
                errors.append(f"{entity}.{field}: JSON is not enforced by SQLite")
    for table in sorted(tables - excluded_tables):
        if table.startswith("sqlite_"):
            continue
        if table not in entities:
            errors.append(f"uncontracted table {table}")
            continue
        columns = column_names(conn, table)
        definition = entities[table]
        contracted = set(definition.get("fields", {}))
        contracted.update(definition.get("identity", ()))
        contracted.update(definition.get("order", ()))
        for field in sorted(columns - contracted - excluded_fields.get(table, set())):
            errors.append(f"{table}: uncontracted column {field}")
    return errors


def require_store(conn: sqlite3.Connection, *, write: bool) -> int:
    """Validate a database before use and return its logical format version.

    Only the current format is accepted, for reading as well as writing. A
    store written by an earlier format is not migrated: Codess rebuilds from
    vendor sources, which remain the authority, so carrying read support for
    superseded layouts would preserve a path nothing needs.
    """
    application_id, version = database_identity(conn)
    if application_id != APPLICATION_ID:
        raise UnsupportedStoreError(
            f"not a Codess store: application_id={application_id:#x}"
        )
    supported = SUPPORTED_WRITE_FORMATS if write else SUPPORTED_READ_FORMATS
    if version not in supported:
        raise UnsupportedStoreError(
            f"unsupported CoSchema format {version}; supported={sorted(supported)}"
        )
    meta = store_metadata(conn)
    if meta.get("format_id") != FORMAT_ID or int(meta.get("format_version", -1)) != version:
        raise UnsupportedStoreError("store_meta disagrees with SQLite format identity")
    if write and meta.get("package_digest") != contract_digest():
        if contract_check_disabled():
            log.warning(
                "writing a store recorded under contract %s with %s in effect; "
                "records written under different rules may be mixed",
                meta.get("package_digest"), CONTRACT_OVERRIDE_ENV,
            )
        else:
            raise UnsupportedStoreError(
                "store was written under a different CoSchema contract; rebuild "
                "the derived working store from source, or set "
                f"{CONTRACT_OVERRIDE_ENV}=1 to proceed anyway"
            )
    if write and meta.get("decoder_version") != DECODER_VERSION:
        raise UnsupportedStoreError(
            "store decoder version differs from the current decoder; rebuild"
        )
    if write and meta.get("validator_version") != VALIDATOR_VERSION:
        raise UnsupportedStoreError(
            "store validator version differs from the current validator; rebuild"
        )
    layout_errors = validate_database_contract(conn) if version == FORMAT_VERSION else []
    if layout_errors:
        raise UnsupportedStoreError(
            "store layout disagrees with CoSchema contract: " + "; ".join(layout_errors)
        )
    return version
