"""Immutable CoSchema snapshot build, validation, and atomic promotion.

# ruff S608 exemption: CoPlan.md 10.4.2.2
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import sqlite3
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from codess import __version__
from codess.fileio import hash_file
from codess.raw_store import RAW_FORMAT, RawStore
from codess.project_catalog import durable_project_root
from codess.processing_contract import DECODER_VERSION, VALIDATOR_VERSION
from codess.schema_contract import (
    APPLICATION_ID, FORMAT_ID, FORMAT_VERSION, SUPPORTED_READ_FORMATS,
    database_identity, require_store, verify_package,
)


class SnapshotError(RuntimeError):
    """Snapshot construction or verification failed."""


_sha256 = hash_file


def current_raw_records(project_root: Path) -> list[dict[str, Any]]:
    """Read the verified raw-record set from the current project snapshot.

    A partial-vendor ingest starts from this set and replaces observations for
    sources it actually revisits.  That keeps the new snapshot complete when,
    for example, Cursor alone is refreshed while Claude and Codex stores remain
    unchanged.
    """
    pointer_path = project_root / ".codess" / "current.json"
    if not pointer_path.exists():
        return []
    try:
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        snapshot_path = Path(pointer["path"])
        if not snapshot_path.is_absolute():
            snapshot_path = pointer_path.parent / snapshot_path
        manifest_path = snapshot_path / "manifest.json"
        if _sha256(manifest_path) != pointer["manifest_sha256"]:
            raise SnapshotError("current snapshot manifest hash mismatch")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        raw_manifest = snapshot_path / "raw-manifest.jsonl"
        if _sha256(raw_manifest) != manifest["raw_manifest_sha256"]:
            raise SnapshotError("current snapshot raw manifest hash mismatch")
        records: list[dict[str, Any]] = []
        with raw_manifest.open(encoding="utf-8") as stream:
            for number, line in enumerate(stream, 1):
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise SnapshotError(
                        f"invalid raw manifest record at line {number}"
                    )
                if value.get("record_type") != "header":
                    records.append(value)
        return records
    except SnapshotError:
        raise
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        raise SnapshotError(f"cannot read current raw records: {exc}") from exc


def _software_revision() -> str | None:
    configured = os.environ.get("CODESS_BUILD_REVISION")
    if configured:
        return configured
    try:
        root = Path(__file__).resolve().parents[2]
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
            text=True, check=True, timeout=5,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
            cwd=root, capture_output=True, check=True, timeout=5,
        ).stdout
        if not status:
            return revision
        digest = hashlib.sha256()
        digest.update(b"git-status\0")
        digest.update(status)
        digest.update(b"git-diff\0")
        digest.update(subprocess.run(
            ["git", "diff", "--binary", "HEAD"], cwd=root,
            capture_output=True, check=True, timeout=10,
        ).stdout)
        for entry in status.split(b"\0"):
            if not entry.startswith(b"?? "):
                continue
            relative = entry[3:].decode("utf-8", errors="surrogateescape")
            path = root / relative
            if not path.is_file():
                continue
            digest.update(b"untracked\0")
            digest.update(relative.encode("utf-8", errors="surrogateescape"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
        return revision + "+worktree.sha256:" + digest.hexdigest()
    except (OSError, subprocess.SubprocessError):
        return None


def _backup_store(
    source_path: Path,
    target_path: Path,
    *,
    snapshot_id: str,
    snapshot_created_at: str,
) -> None:
    source = sqlite3.connect(source_path.resolve().as_uri() + "?mode=ro", uri=True)
    target = sqlite3.connect(target_path)
    try:
        require_store(source, write=False)
        source.backup(target)
        target.executemany(
            "INSERT OR REPLACE INTO store_meta(key, value) VALUES (?, ?)",
            (
                ("snapshot_id", snapshot_id),
                ("snapshot_created_at", snapshot_created_at),
                ("snapshot_software_version", __version__),
            ),
        )
        target.commit()
        result = target.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise SnapshotError(f"integrity_check failed for {source_path}: {result}")
        require_store(target, write=False)
    finally:
        target.close()
        source.close()


def _logical_counts(
    path: Path, only: Iterable[str] | None = None
) -> dict[str, int]:
    conn = sqlite3.connect(path)
    try:
        available = {
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        requested = tuple(only) if only is not None else (
            "projects", "project_locations", "workspace_bindings", "sources",
            "sessions", "interactions", "model_turns", "events",
            "source_records", "content_objects", "event_content",
            "source_record_content", "tool_result_content", "artifact_content",
            "processing_runs", "content_derivations",
            "tool_invocations", "tool_results", "artifacts",
            "mapping_diagnostics",
        )
        return {
            table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in requested if table in available
        }
    finally:
        conn.close()


def _store_package_identity(
    store_paths: Iterable[Path],
) -> tuple[int, str, list[Path]]:
    """Return the common on-disk format/package without relabeling old stores."""
    paths = [path for path in store_paths if path.exists()]
    versions: set[int] = set()
    package_digests: set[str] = set()
    for path in paths:
        conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            versions.add(require_store(conn, write=False))
            meta = dict(conn.execute("SELECT key, value FROM store_meta"))
            digest = meta.get("package_digest")
            if not digest:
                raise SnapshotError(f"store lacks package_digest: {path}")
            package_digests.add(digest)
        finally:
            conn.close()
    if not paths:
        raise SnapshotError("cannot create a snapshot without a CoSchema store")
    if len(versions) != 1 or len(package_digests) != 1:
        raise SnapshotError(
            "snapshot stores use mixed CoSchema formats or package digests"
        )
    return versions.pop(), package_digests.pop(), paths


def _pointer_document(
    snapshot: Path,
    *,
    local_base: Path,
    project_id: str | None,
) -> dict[str, Any]:
    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    return {
        "snapshot_id": manifest["snapshot_id"],
        "path": str(
            snapshot
            if snapshot.parent.parent.resolve() != local_base.resolve()
            else snapshot.relative_to(local_base)
        ),
        "project_id": project_id,
        "format_id": manifest["format_id"],
        "format_version": manifest["format_version"],
        "decoder_version": manifest["decoder_version"],
        "validator_version": manifest["validator_version"],
        "manifest_sha256": _sha256(snapshot / "manifest.json"),
    }


def _replace_pointer(source: Path, target: Path) -> None:
    """Small publication seam used by failure-injection tests."""
    os.replace(source, target)


def publish_snapshot(
    project_root: Path,
    snapshot: Path,
    *,
    registry_root: Path | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    """Promote one verified candidate while preserving pointer-pair consistency.

    Candidate construction is intentionally separate from publication.  If
    replacing either the central or Project-local pointer fails, every pointer
    is restored byte-for-byte to its prior state.
    """
    project_root = project_root.expanduser().resolve()
    snapshot = snapshot.expanduser().resolve()
    local_base = project_root / ".codess"
    expected_base = (
        durable_project_root(registry_root, project_id).resolve()
        if registry_root is not None and project_id is not None
        else local_base.resolve()
    )
    if snapshot.parent.parent.resolve() != expected_base:
        raise SnapshotError(
            f"candidate snapshot is outside the expected snapshot base: {snapshot}"
        )
    # This checks the manifest, every retained database hash, and the supported
    # read contract before publication can change a pointer. Current-format
    # package equality was already enforced during construction.
    snapshot_store_paths_from_base(
        expected_base, snapshot.name, allow_package_mismatch=True
    )
    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("project_id") != project_id:
        raise SnapshotError("candidate snapshot Project identity mismatch")
    current = _pointer_document(
        snapshot, local_base=local_base, project_id=project_id
    )
    targets = [expected_base / "current.json"]
    local_target = local_base / "current.json"
    if local_target.resolve() != targets[0].resolve():
        targets.append(local_target)

    payload = (json.dumps(current, indent=2, sort_keys=True) + "\n").encode("utf-8")
    previous: dict[Path, bytes | None] = {}
    temporary: dict[Path, Path] = {}
    replaced: list[Path] = []
    try:
        for target in targets:
            target.parent.mkdir(parents=True, exist_ok=True)
            previous[target] = target.read_bytes() if target.exists() else None
            temp = target.parent / (
                f".{target.name}.candidate-{os.getpid()}-{snapshot.name}"
            )
            temp.write_bytes(payload)
            temporary[target] = temp
        for target in targets:
            _replace_pointer(temporary[target], target)
            replaced.append(target)
    except Exception as exc:
        for target in reversed(replaced):
            prior = previous[target]
            if prior is None:
                target.unlink(missing_ok=True)
                continue
            rollback = target.parent / f".{target.name}.rollback-{os.getpid()}"
            rollback.write_bytes(prior)
            os.replace(rollback, target)
        raise SnapshotError(f"snapshot publication failed; prior pointers restored: {exc}") from exc
    finally:
        for temp in temporary.values():
            temp.unlink(missing_ok=True)
    return current


def create_snapshot(
    project_root: Path,
    store_paths: Iterable[Path],
    raw_records: list[dict[str, Any]],
    *,
    raw_store: RawStore,
    seal: bool = False,
    build_policy: dict[str, Any] | None = None,
    registry_root: Path | None = None,
    project_id: str | None = None,
    publish: bool = True,
) -> Path:
    """Build an immutable snapshot and optionally publish it as current."""
    local_base = project_root / ".codess"
    base = (
        durable_project_root(registry_root, project_id)
        if registry_root is not None and project_id is not None
        else local_base
    )
    snapshots = base / "snapshots"
    snapshots.mkdir(parents=True, exist_ok=True)
    store_format_version, package_digest, source_stores = _store_package_identity(
        store_paths
    )
    if store_format_version == FORMAT_VERSION and package_digest != verify_package():
        raise SnapshotError(
            "current-format store package differs from the current package"
        )
    created_at = datetime.now(timezone.utc)
    created_at_text = created_at.isoformat()
    policy = build_policy or {"raw_mode": "seal" if seal else "unspecified"}
    policy_digest = hashlib.sha256(
        json.dumps(policy, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    identity = hashlib.sha256(
        f"{project_root.resolve()}\0{created_at_text}\0{package_digest}\0{policy_digest}".encode("utf-8")
    ).hexdigest()[:12]
    snapshot_id = (
        f"{created_at.strftime('%Y%m%dT%H%M%S.%fZ')}-"
        f"coschema{store_format_version}-{identity}"
    )
    parent_snapshot_id = None
    pointer = local_base / "current.json"
    if pointer.exists():
        try:
            previous = json.loads(pointer.read_text(encoding="utf-8"))
            previous_path = Path(previous["path"])
            previous_snapshot = previous_path if previous_path.is_absolute() else local_base / previous_path
            previous_manifest = previous_snapshot / "manifest.json"
            if _sha256(previous_manifest) != previous["manifest_sha256"]:
                raise SnapshotError("refusing to replace an invalid current snapshot pointer")
            parent_snapshot_id = previous.get("snapshot_id")
        except SnapshotError:
            raise
        except (OSError, KeyError, json.JSONDecodeError) as exc:
            raise SnapshotError(
                f"refusing to replace an unreadable current snapshot pointer: {exc}"
            ) from exc
    with tempfile.TemporaryDirectory(prefix=".snapshot-", dir=snapshots) as tmp_name:
        tmp = Path(tmp_name)
        stores: dict[str, Any] = {}
        for source_path in sorted(source_stores, key=lambda p: p.name):
            target = tmp / source_path.name
            _backup_store(
                source_path, target, snapshot_id=snapshot_id,
                snapshot_created_at=created_at_text,
            )
            stores[source_path.name] = {
                "sha256": _sha256(target),
                "size": target.stat().st_size,
                "counts": _logical_counts(target),
            }
        if not stores:
            raise SnapshotError("cannot create a snapshot without a CoSchema store")

        raw_manifest = tmp / "raw-manifest.jsonl"
        with raw_manifest.open("w", encoding="utf-8") as stream:
            stream.write(json.dumps({"record_type": "header", "raw_format": RAW_FORMAT}, sort_keys=True) + "\n")
            for record in raw_records:
                stream.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
                if seal and record.get("availability") == "captured":
                    source_object = raw_store.resolve(record)
                    if source_object is None or not source_object.exists():
                        raise SnapshotError(f"missing raw object for {record.get('object_id')}")
                    target_object = tmp / "raw" / record["object_relpath"]
                    target_object.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        os.link(source_object, target_object)
                    except OSError:
                        shutil.copy2(source_object, target_object)
                    if _sha256(target_object) != record["stored_sha256"]:
                        raise SnapshotError(f"sealed raw hash mismatch: {record.get('object_id')}")

        manifest: dict[str, Any] = {
            "snapshot_format": "codess.snapshot/1",
            "snapshot_id": snapshot_id,
            "parent_snapshot_id": parent_snapshot_id,
            "created_at": created_at_text,
            "software_version": __version__,
            "software_revision": _software_revision(),
            "decoder_version": DECODER_VERSION,
            "validator_version": VALIDATOR_VERSION,
            "runtime": {
                "python": platform.python_version(),
                "sqlite": sqlite3.sqlite_version,
                "platform": platform.platform(),
            },
            "build_policy": policy,
            "build_policy_sha256": policy_digest,
            "format_id": FORMAT_ID,
            "format_version": store_format_version,
            "package_digest": package_digest,
            "project_id": project_id,
            "raw_format": RAW_FORMAT,
            "sealed": seal,
            "raw_manifest_sha256": _sha256(raw_manifest),
            "stores": stores,
        }
        (tmp / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        final = snapshots / snapshot_id
        os.replace(tmp, final)

    if publish:
        publish_snapshot(
            project_root,
            final,
            registry_root=registry_root,
            project_id=project_id,
        )
    return final


def snapshot_store_paths_from_base(
    base: Path,
    snapshot_id: str,
    *,
    allow_package_mismatch: bool = False,
) -> list[Path]:
    """Resolve and validate one retained snapshot under a snapshot base.

    Package mismatch is rejected unless a caller explicitly requests the
    format-compatible reader path. That path verifies every retained hash and
    the current reader's database contract, but cannot promise identical
    mapping semantics.
    """
    base = base.expanduser().resolve()
    if not snapshot_id or snapshot_id in {".", ".."} or "/" in snapshot_id:
        raise SnapshotError(f"invalid snapshot identity: {snapshot_id!r}")
    pointer = base / "current.json"
    snapshot = base / "snapshots" / snapshot_id
    if pointer.exists():
        try:
            current = json.loads(pointer.read_text(encoding="utf-8"))
            current_path = Path(current["path"])
            if current_path.is_absolute():
                snapshot = current_path.parent / snapshot_id
        except (OSError, KeyError, json.JSONDecodeError):
            pass
    if not snapshot.is_dir():
        raise SnapshotError(f"retained snapshot not found: {snapshot_id}")
    try:
        manifest_path = snapshot / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("snapshot_id") != snapshot_id:
            raise SnapshotError("snapshot directory and manifest identity disagree")
        if (
            manifest["format_id"] != FORMAT_ID
            or manifest["format_version"] not in SUPPORTED_READ_FORMATS
        ):
            raise SnapshotError("retained snapshot format is unsupported")
        package_matches = manifest.get("package_digest") == verify_package()
        if not package_matches and not allow_package_mismatch:
            raise SnapshotError("retained snapshot exact CoSchema package digest mismatch")
        raw_manifest = snapshot / "raw-manifest.jsonl"
        if _sha256(raw_manifest) != manifest.get("raw_manifest_sha256"):
            raise SnapshotError("retained snapshot raw manifest hash mismatch")
        paths = []
        for name, entry in manifest["stores"].items():
            path = snapshot / name
            if _sha256(path) != entry["sha256"]:
                raise SnapshotError(f"retained store hash mismatch: {name}")
            conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
            try:
                if package_matches:
                    require_store(conn, write=False)
                else:
                    application_id, version = database_identity(conn)
                    if application_id != APPLICATION_ID or version not in SUPPORTED_READ_FORMATS:
                        raise SnapshotError(f"retained store format mismatch: {name}")
                meta = dict(conn.execute("SELECT key, value FROM store_meta"))
                if meta.get("snapshot_id") != manifest.get("snapshot_id"):
                    raise SnapshotError(f"retained store snapshot identity mismatch: {name}")
                if meta.get("package_digest") != manifest.get("package_digest"):
                    raise SnapshotError(f"retained store package digest mismatch: {name}")
                if _logical_counts(path, entry.get("counts", {}).keys()) != entry.get("counts"):
                    raise SnapshotError(f"retained store logical counts mismatch: {name}")
            finally:
                conn.close()
            paths.append(path)
        return sorted(paths)
    except SnapshotError:
        raise
    except (OSError, KeyError, json.JSONDecodeError, sqlite3.Error) as exc:
        raise SnapshotError(f"invalid retained snapshot: {exc}") from exc


def snapshot_store_paths(
    project_root: Path,
    snapshot_id: str,
    *,
    allow_package_mismatch: bool = False,
) -> list[Path]:
    """Resolve one retained snapshot from a Project's local snapshot base."""
    return snapshot_store_paths_from_base(
        project_root / ".codess",
        snapshot_id,
        allow_package_mismatch=allow_package_mismatch,
    )


def current_store_paths_from_base(base: Path) -> list[Path]:
    """Resolve validated current-snapshot DB paths under one snapshot base."""
    base = base.expanduser().resolve()
    pointer = base / "current.json"
    if not pointer.exists():
        return []
    try:
        current = json.loads(pointer.read_text(encoding="utf-8"))
        current_path = Path(current["path"])
        snapshot = current_path if current_path.is_absolute() else base / current_path
        manifest_path = snapshot / "manifest.json"
        if _sha256(manifest_path) != current["manifest_sha256"]:
            raise SnapshotError("current snapshot manifest hash mismatch")
        if snapshot.name != current["snapshot_id"]:
            raise SnapshotError("current snapshot path and identity disagree")
        return snapshot_store_paths_from_base(base, current["snapshot_id"])
    except SnapshotError:
        raise
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        raise SnapshotError(f"invalid current snapshot pointer: {exc}") from exc


def current_store_paths(project_root: Path) -> list[Path]:
    """Resolve validated current-snapshot DB paths, or return an empty list."""
    return current_store_paths_from_base(project_root / ".codess")
