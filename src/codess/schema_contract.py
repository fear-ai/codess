"""CoSchema package identity, integrity, database compatibility, and mappings."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from functools import lru_cache
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = REPO_ROOT / "schema" / "coschema"
MANIFEST_PATH = PACKAGE_ROOT / "manifest.json"
CONTRACT_PATH = PACKAGE_ROOT / "contract.json"
DDL_PATH = PACKAGE_ROOT / "sqlite" / "schema.sql"
MAPPINGS_ROOT = REPO_ROOT / "schema" / "mappings"

FORMAT_ID = "codess.coschema"
FORMAT_VERSION = 2
APPLICATION_ID = 0x434F4445
SUPPORTED_READ_FORMATS = frozenset({2})
SUPPORTED_WRITE_FORMATS = frozenset({2})


class SchemaContractError(RuntimeError):
    """The packaged contract is missing, inconsistent, or unsupported."""


class UnsupportedStoreError(SchemaContractError):
    """A database is not writable/readable by this software contract."""


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


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
    return manifest


@lru_cache(maxsize=1)
def verify_package() -> str:
    """Verify every released package file and return a deterministic digest."""
    manifest = load_manifest()
    failures: list[str] = []
    package_hash = hashlib.sha256()
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
    return json.loads((MAPPINGS_ROOT / f"{name}.json").read_text(encoding="utf-8"))


def validate_mapping(mapping: dict[str, Any]) -> list[str]:
    """Mechanically validate the deliberately small mapping-spec grammar."""
    contract = json.loads(
        (PACKAGE_ROOT / "mapping-contract.json").read_text(encoding="utf-8")
    )
    errors = [key for key in contract["required"] if key not in mapping]
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


def database_identity(conn: sqlite3.Connection) -> tuple[int, int]:
    return (
        int(conn.execute("PRAGMA application_id").fetchone()[0]),
        int(conn.execute("PRAGMA user_version").fetchone()[0]),
    )


def validate_database_contract(conn: sqlite3.Connection) -> list[str]:
    """Return layout omissions relative to the released logical contract.

    The contract deliberately leaves SQLite types and indexes to the physical
    schema. This check ensures only that every contracted entity and field is
    physically representable.
    """
    errors: list[str] = []
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    for entity, definition in load_contract()["entities"].items():
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
    return errors


def has_legacy_schema(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='sessions'"
    ).fetchone()
    return row is not None and database_identity(conn) == (0, 0)


def require_store(
    conn: sqlite3.Connection,
    *,
    write: bool,
    allow_legacy_read: bool = False,
) -> int:
    """Validate a database before use and return its logical format version."""
    application_id, version = database_identity(conn)
    if application_id == 0 and version == 0 and has_legacy_schema(conn):
        if not write and allow_legacy_read:
            return 1
        raise UnsupportedStoreError(
            "legacy unversioned Codess store is read-only; rebuild into CoSchema v2"
        )
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
    layout_errors = validate_database_contract(conn)
    if layout_errors:
        raise UnsupportedStoreError(
            "store layout disagrees with CoSchema contract: " + "; ".join(layout_errors)
        )
    return version
