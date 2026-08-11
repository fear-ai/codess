"""CoSchema package identity, integrity, database compatibility, and mappings."""

from __future__ import annotations

import json
import sqlite3
from functools import lru_cache
from pathlib import Path
from typing import Any

from codess.hashing import codess_digest
from codess.fileio import hash_file
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


_sha256 = hash_file


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


@lru_cache(maxsize=1)
def verify_package() -> str:
    """Verify every released package file and return a deterministic digest."""
    manifest = load_manifest()
    failures: list[str] = []
    package_hash = codess_digest()
    for role, entry in sorted(manifest.get("files", {}).items()):
        path = REPO_ROOT / entry["path"]
        if not path.is_file():
            failures.append(f"{role}: missing {entry['path']}")
            continue
        actual = _sha256(path)
        if actual != entry.get("sha256"):
            failures.append(
                f"{role}: hash mismatch for {entry['path']} "
                f"({actual} != {entry.get('sha256')})"
            )
        package_hash.update(role.encode("utf-8"))
        package_hash.update(b"\0")
        package_hash.update(actual.encode("ascii"))
        package_hash.update(b"\n")
    if failures:
        raise SchemaContractError("invalid released CoSchema package: " + "; ".join(failures))
    return package_hash.hexdigest()


@lru_cache(maxsize=1)
def load_contract() -> dict[str, Any]:
    verify_package()
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def load_ddl() -> str:
    verify_package()
    return DDL_PATH.read_text(encoding="utf-8")


def load_mapping(name: str) -> dict[str, Any]:
    verify_package()
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
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    for entity, definition in entities.items():
        if entity not in tables:
            errors.append(f"missing table {entity}")
            continue
        columns = {
            row[1] for row in conn.execute(f'PRAGMA table_info("{entity}")')
        }
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
        columns = {
            row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')
        }
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
    meta = dict(conn.execute("SELECT key, value FROM store_meta"))
    if meta.get("format_id") != FORMAT_ID or int(meta.get("format_version", -1)) != version:
        raise UnsupportedStoreError("store_meta disagrees with SQLite format identity")
    if write and meta.get("package_digest") != verify_package():
        raise UnsupportedStoreError(
            "store package differs from the current released package; rebuild "
            "the derived working store from source"
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
