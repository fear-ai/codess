"""Immutable CoSchema snapshot build, validation, and atomic promotion."""

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

from codess.hashing import codess_canonical_hash, codess_digest
from codess import __version__
from codess.config import (
    CURRENT_POINTER_FILE, MANIFEST_BACKUP_FILE, MANIFEST_FILE,
    RAW_MANIFEST_FILE, SNAPSHOTS_DIR, STORE_DIR,
)
from codess.fileio import (
    HashMismatchError, hash_file, read_hash, verify_hash,
)
from codess.raw_store import RAW_FORMAT, RawStore
from codess.project_catalog import durable_project_root
from codess.processing_contract import DECODER_VERSION, VALIDATOR_VERSION
from codess.schema_contract import (
    APPLICATION_ID, FORMAT_ID, FORMAT_VERSION, SUPPORTED_READ_FORMATS,
    database_identity, require_store, verify_package,
)


class SnapshotError(RuntimeError):
    """Snapshot construction or verification failed."""


def read_manifest(snapshot_dir: Path) -> dict[str, Any]:
    """Read manifest.json. Plain read: manifest.json is write-once, so no
    hash check is needed here (see current_snapshot for the one
    file that does need one). Falls back to manifest.json.bak if the
    primary is missing, not if it exists but fails to parse."""
    primary = snapshot_dir / MANIFEST_FILE
    if not primary.exists():
        backup = snapshot_dir / MANIFEST_BACKUP_FILE
        if backup.exists():
            return json.loads(backup.read_text(encoding="utf-8"))
        raise SnapshotError(
            f"manifest.json missing and no manifest.json.bak at {snapshot_dir}"
        )
    return json.loads(primary.read_text(encoding="utf-8"))


def current_snapshot(base: Path) -> tuple[Path, dict[str, Any]] | None:
    """Resolve the snapshot base/current.json points to, verifying its
    manifest_sha256 claim via `read_hash`. Returns (snapshot_dir,
    pointer_document), or None if no pointer exists yet."""
    pointer = base / CURRENT_POINTER_FILE
    if not pointer.exists():
        return None
    try:
        current = json.loads(pointer.read_text(encoding="utf-8"))
        snapshot_path = Path(current["path"])
        if not snapshot_path.is_absolute():
            snapshot_path = pointer.parent / snapshot_path
        manifest_path = snapshot_path / MANIFEST_FILE
        if not manifest_path.exists():
            raise SnapshotError(f"current snapshot manifest missing at {manifest_path}")
        read_hash(manifest_path, expected_hash=current["manifest_sha256"])
        return snapshot_path, current
    except SnapshotError:
        raise
    except HashMismatchError as exc:
        raise SnapshotError("current snapshot manifest hash mismatch") from exc
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        raise SnapshotError(f"invalid current snapshot pointer: {exc}") from exc


def current_raw_records(project_path: Path) -> list[dict[str, Any]]:
    """Read the raw-record set from the current project snapshot.

    A partial-vendor ingest starts from this set and replaces observations for
    sources it actually revisits.  That keeps the new snapshot complete when,
    for example, Cursor alone is refreshed while Claude and Codex stores remain
    unchanged.
    """
    resolved = current_snapshot(project_path / STORE_DIR)
    if resolved is None:
        return []
    snapshot_path, _pointer = resolved
    try:
        raw_manifest = snapshot_path / RAW_MANIFEST_FILE
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
    except (OSError, json.JSONDecodeError) as exc:
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
        digest = codess_digest()
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
    manifest: dict[str, Any],
    *,
    local_base: Path,
    project_id: str | None,
) -> dict[str, Any]:
    """Build the new pointer document from an already-read manifest.

    Takes `manifest` rather than reading `snapshot / MANIFEST_FILE` itself
    -- the one caller (`publish_snapshot`) has already parsed it for its own
    project_id check, and the file cannot change between the two calls
    (snapshots are immutable once written). The hash still reads the file
    directly: a checksum must cover the exact bytes as written, not a value
    reconstructed by round-tripping through `json.loads`/`json.dumps`.
    """
    manifest_path = snapshot / MANIFEST_FILE
    if not manifest_path.exists():
        raise SnapshotError(f"cannot publish: manifest.json missing at {manifest_path}")
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
        "manifest_sha256": hash_file(manifest_path),
    }


def _replace_pointer(source: Path, target: Path) -> None:
    """Small publication seam used by failure-injection tests."""
    os.replace(source, target)


def publish_snapshot(
    project_path: Path,
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
    project_path = project_path.expanduser().resolve()
    snapshot = snapshot.expanduser().resolve()
    local_base = project_path / STORE_DIR
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
    manifest = read_manifest(snapshot)
    if manifest.get("project_id") != project_id:
        raise SnapshotError("candidate snapshot Project identity mismatch")
    current = _pointer_document(
        snapshot, manifest, local_base=local_base, project_id=project_id
    )
    targets = [expected_base / CURRENT_POINTER_FILE]
    local_target = local_base / CURRENT_POINTER_FILE
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


def recover_current_snapshot(
    project_path: Path,
    *,
    registry_root: Path | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    """Rebuild a lost or corrupted current.json from the newest retained
    snapshot that still validates. Tries each snapshot under `snapshots/`,
    newest first, and republishes the first one that passes
    `snapshot_store_paths_from_base`. Raises SnapshotError only if none do.
    """
    project_path = project_path.expanduser().resolve()
    local_base = project_path / STORE_DIR
    expected_base = (
        durable_project_root(registry_root, project_id).resolve()
        if registry_root is not None and project_id is not None
        else local_base.resolve()
    )
    snapshots_dir = expected_base / SNAPSHOTS_DIR
    if not snapshots_dir.is_dir():
        raise SnapshotError(f"no retained snapshots to recover from: {snapshots_dir}")
    candidates = sorted(
        (entry for entry in snapshots_dir.iterdir() if entry.is_dir()),
        key=lambda entry: entry.name,
        reverse=True,
    )
    errors: list[str] = []
    for candidate in candidates:
        try:
            snapshot_store_paths_from_base(
                expected_base, candidate.name, allow_package_mismatch=True
            )
        except SnapshotError as exc:
            errors.append(f"{candidate.name}: {exc}")
            continue
        return publish_snapshot(
            project_path, candidate,
            registry_root=registry_root, project_id=project_id,
        )
    raise SnapshotError(
        "no retained snapshot could be recovered; tried "
        f"{len(candidates)} candidate(s): " + "; ".join(errors)
    )


def create_snapshot(
    project_path: Path,
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
    local_base = project_path / STORE_DIR
    base = (
        durable_project_root(registry_root, project_id)
        if registry_root is not None and project_id is not None
        else local_base
    )
    snapshots = base / SNAPSHOTS_DIR
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
    policy_digest = codess_canonical_hash(256, 256, policy)
    identity = hashlib.sha256(
        f"{project_path.resolve()}\0{created_at_text}\0{package_digest}\0{policy_digest}".encode("utf-8")
    ).hexdigest()[:12]
    snapshot_id = (
        f"{created_at.strftime('%Y%m%dT%H%M%S.%fZ')}-"
        f"coschema{store_format_version}-{identity}"
    )
    parent_snapshot_id = None
    resolved_previous = current_snapshot(local_base)
    if resolved_previous is not None:
        _previous_snapshot, previous_pointer = resolved_previous
        parent_snapshot_id = previous_pointer.get("snapshot_id")
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
                "sha256": hash_file(target),
                "size": target.stat().st_size,
                "counts": _logical_counts(target),
            }
        if not stores:
            raise SnapshotError("cannot create a snapshot without a CoSchema store")

        raw_manifest = tmp / RAW_MANIFEST_FILE
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
                    try:
                        verify_hash(target_object, record["stored_sha256"])
                    except HashMismatchError as exc:
                        raise SnapshotError(
                            f"sealed raw hash mismatch: {record.get('object_id')}"
                        ) from exc

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
            "raw_manifest_sha256": hash_file(raw_manifest),
            "stores": stores,
        }
        manifest_text = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
        (tmp / MANIFEST_FILE).write_text(manifest_text, encoding="utf-8")
        # Written once, alongside the primary, so it promotes atomically with
        # it and needs no separate staleness handling -- manifests are
        # write-once (see read_manifest). Lets an operator recover the exact
        # original manifest bytes by copying this file over a lost or
        # corrupted manifest.json without needing rebuild_manifest's
        # best-effort store_meta reconstruction at all.
        (tmp / MANIFEST_BACKUP_FILE).write_text(manifest_text, encoding="utf-8")
        final = snapshots / snapshot_id
        os.replace(tmp, final)

    if publish:
        publish_snapshot(
            project_path,
            final,
            registry_root=registry_root,
            project_id=project_id,
        )
    return final


def rebuild_manifest(snapshot_dir: Path) -> dict[str, Any]:
    """Reconstruct manifest.json from surviving store DBs + raw-manifest.jsonl.

    Most fields are recoverable from each store's own store_meta table or
    recomputed from the files themselves. `parent_snapshot_id`,
    `build_policy`, and `build_policy_sha256` are not recorded anywhere
    else and come back as None. Result carries `"reconstructed": True`.
    Raises SnapshotError if no store DB or raw-manifest.jsonl survives.
    """
    if not snapshot_dir.is_dir():
        raise SnapshotError(f"not a snapshot directory: {snapshot_dir}")
    raw_manifest = snapshot_dir / RAW_MANIFEST_FILE
    if not raw_manifest.is_file():
        raise SnapshotError(
            f"cannot reconstruct manifest without raw-manifest.jsonl: {snapshot_dir}"
        )
    store_paths = sorted(
        path for path in snapshot_dir.iterdir()
        if path.is_file() and path.suffix == ".db"
    )
    if not store_paths:
        raise SnapshotError(
            f"cannot reconstruct manifest without a surviving store database: {snapshot_dir}"
        )
    stores: dict[str, Any] = {}
    meta_by_key: dict[str, str] = {}
    format_version: int | None = None
    package_digest: str | None = None
    project_id: str | None = None
    for path in store_paths:
        conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            version = require_store(conn, write=False)
            format_version = format_version or version
            meta = dict(conn.execute("SELECT key, value FROM store_meta"))
            for key in (
                "snapshot_id", "snapshot_created_at", "snapshot_software_version",
                "decoder_version", "validator_version", "package_digest",
            ):
                meta_by_key.setdefault(key, meta.get(key))
            package_digest = package_digest or meta.get("package_digest")
            if project_id is None:
                row = conn.execute("SELECT id FROM projects LIMIT 1").fetchone()
                project_id = row[0] if row else None
            stores[path.name] = {
                "sha256": hash_file(path),
                "size": path.stat().st_size,
                "counts": _logical_counts(path),
            }
        finally:
            conn.close()
    return {
        "snapshot_format": "codess.snapshot/1",
        "snapshot_id": meta_by_key.get("snapshot_id") or snapshot_dir.name,
        "parent_snapshot_id": None,
        "created_at": meta_by_key.get("snapshot_created_at"),
        "software_version": meta_by_key.get("snapshot_software_version"),
        "software_revision": None,
        "decoder_version": meta_by_key.get("decoder_version"),
        "validator_version": meta_by_key.get("validator_version"),
        "build_policy": None,
        "build_policy_sha256": None,
        "format_id": FORMAT_ID,
        "format_version": format_version,
        "package_digest": package_digest,
        "project_id": project_id,
        "raw_format": RAW_FORMAT,
        "sealed": (snapshot_dir / "raw").is_dir(),
        "raw_manifest_sha256": hash_file(raw_manifest),
        "stores": stores,
        "reconstructed": True,
    }


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
    pointer = base / CURRENT_POINTER_FILE
    snapshot = base / SNAPSHOTS_DIR / snapshot_id
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
        manifest = read_manifest(snapshot)
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
        raw_manifest = snapshot / RAW_MANIFEST_FILE
        try:
            verify_hash(raw_manifest, manifest.get("raw_manifest_sha256"))
        except HashMismatchError as exc:
            raise SnapshotError("retained snapshot raw manifest hash mismatch") from exc
        paths = []
        for name, entry in manifest["stores"].items():
            path = snapshot / name
            try:
                verify_hash(path, entry["sha256"])
            except HashMismatchError as exc:
                raise SnapshotError(f"retained store hash mismatch: {name}") from exc
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
    project_path: Path,
    snapshot_id: str,
    *,
    allow_package_mismatch: bool = False,
) -> list[Path]:
    """Resolve one retained snapshot from a Project's local snapshot base."""
    return snapshot_store_paths_from_base(
        project_path / STORE_DIR,
        snapshot_id,
        allow_package_mismatch=allow_package_mismatch,
    )


def current_store_paths_from_base(base: Path) -> list[Path]:
    """Resolve validated current-snapshot DB paths under one snapshot base.

    The dropped `snapshot.name != current["snapshot_id"]` check this
    function used to run is guaranteed by construction, not defense against
    a live threat: `_pointer_document` always writes `path` as the exact
    directory `create_snapshot` created, whose name is always `snapshot_id`
    -- the two fields cannot diverge from any write path this module has.
    """
    base = base.expanduser().resolve()
    resolved = current_snapshot(base)
    if resolved is None:
        return []
    _snapshot_path, current = resolved
    return snapshot_store_paths_from_base(base, current["snapshot_id"])


def current_stores(project_path: Path) -> list[Path]:
    """Resolve validated current-snapshot DB paths, or return an empty list."""
    return current_store_paths_from_base(project_path / STORE_DIR)
