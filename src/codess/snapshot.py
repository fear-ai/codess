"""Immutable CoSchema snapshot build, validation, and atomic promotion."""

from __future__ import annotations

import json
import os
import platform
import shutil
import sqlite3
import subprocess
import tempfile
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from codess import __version__
from codess.config import (
    CURRENT_POINTER_FILE,
    HASH_CHUNK_BYTES,
    KEEP_SNAPSHOTS,
    MANIFEST_BACKUP_FILE,
    MANIFEST_FILE,
    RAW_MANIFEST_FILE,
    SNAPSHOTS_DIR,
    STORE_DIR,
    WORKTREE_DIGEST_MAX_BYTES,
)
from codess.fileio import (
    HashMismatchError,
    hash_file,
    open_readonly,
    open_writable,
    quote_identifier,
    read_hash,
    verify_hash,
)
from codess.hashing import codess_canonical_hash, codess_digest, codess_hash
from codess.processing_contract import DECODER_VERSION, VALIDATOR_VERSION
from codess.project_catalog import durable_project_root
from codess.raw_store import RAW_FORMAT, RawStore
from codess.reporting import emit_named
from codess.schema_contract import (
    APPLICATION_ID,
    FORMAT_ID,
    FORMAT_VERSION,
    SUPPORTED_READ_FORMATS,
    UnsupportedStoreError,
    contract_digest,
    database_identity,
    require_store,
    store_metadata,
    table_names,
)


class SnapshotError(RuntimeError):
    """Snapshot construction or verification failed."""


class SnapshotContractMismatchError(SnapshotError):
    """The snapshot is well-formed but records a different CoSchema contract.

    Separate from a general failure because callers act on it differently: a
    catalog reports the Project as needing a rebuild rather than as broken,
    and a reader may opt into it explicitly. It was previously distinguished
    by matching the message text, which made the wording a silent interface --
    rewording the message reclassified the status.
    """


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
        # This fingerprints the *Codess source tree* so a store records which
        # build wrote it. Two reads here are unbounded by nature and are bounded
        # explicitly, because the input is a developer's working tree: a diff
        # against a large uncommitted change, and an untracked file of any size
        # -- a downloaded corpus or a stray database left in the checkout.
        #
        # Exceeding a bound is recorded in the fingerprint rather than skipped.
        # A dirty tree whose fingerprint silently ignored its largest untracked
        # file would report two different trees as the same build, which is the
        # one thing this value must not do.
        digest = codess_digest()
        digest.update(b"git-status\0")
        digest.update(status)
        digest.update(b"git-diff\0")
        diff = subprocess.run(
            ["git", "diff", "--binary", "HEAD"], cwd=root,
            capture_output=True, check=True, timeout=10,
        ).stdout
        if len(diff) > WORKTREE_DIGEST_MAX_BYTES:
            digest.update(b"diff-oversize\0")
            digest.update(str(len(diff)).encode("ascii"))
        else:
            digest.update(diff)
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
            try:
                size = path.stat().st_size
            except OSError:
                continue
            if size > WORKTREE_DIGEST_MAX_BYTES:
                # Size and mtime rather than content: enough to notice the file
                # changed, without reading it.
                digest.update(b"oversize\0")
                digest.update(f"{size}:{path.stat().st_mtime_ns}".encode("ascii"))
                continue
            with path.open("rb") as stream:
                for chunk in iter(lambda stream=stream: stream.read(HASH_CHUNK_BYTES), b""):
                    digest.update(chunk)
        return revision + "+worktree.sha256:" + digest.hexdigest()
    except (OSError, subprocess.SubprocessError):
        return None


def _backup_store(
    source_path: Path,
    target_path: Path,
    *,
    snapshot_created_at: str,
) -> None:
    """Copy one store into a snapshot, stamping when the snapshot was made.

    The snapshot identity is not written into the copy. It is derived before
    the copy and the manifest then records this file's digest, so storing it
    inside the file would place a derived name inside the structure whose
    digest depends on it. The manifest is the layer above the stores and
    holds the identity (13.4.8); membership is proven by that digest, which
    `snapshot_store_paths_from_base` verifies.
    """
    source = open_readonly(source_path)
    # `backup()` copies pages, so row constraints do not apply during the copy
    # -- but the `store_meta` stamp written below is an ordinary write, and the
    # result is a store other code opens. Stated rather than defaulted.
    target = open_writable(target_path, foreign_keys=False)
    try:
        require_store(source, write=False)
        source.backup(target)
        # The copy is a store the moment `backup` returns, and the stamp below
        # writes to it, so it is gated as a write before that happens rather
        # than only verified afterward.
        require_store(target, write=True)
        target.executemany(
            "INSERT OR REPLACE INTO store_meta(key, value) VALUES (?, ?)",
            (
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
    # Counting rows is a read, and a read that opens a file it does not own
    # must not be able to write to it even by mistake.
    conn = open_readonly(path)
    try:
        available = table_names(conn)
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
            table: int(conn.execute(f"SELECT COUNT(*) FROM {quote_identifier(table)}").fetchone()[0])
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
    contract_digests: set[str] = set()
    for path in paths:
        conn = open_readonly(path)
        try:
            try:
                versions.add(require_store(conn, write=False))
            except UnsupportedStoreError as exc:
                # A store set is published as a whole, so one vendor rebuilt
                # under a new format leaves the others unreadable here. Naming
                # the store and the whole-Project remedy matters because the
                # obvious next step -- re-running the same single-vendor
                # `--force` -- cannot resolve it.
                raise SnapshotContractMismatchError(
                    f"{path.name} cannot join this snapshot: {exc}. Every store "
                    f"in a Project is published together, so rebuild them all "
                    f"with `codess ingest --force` without `--source`"
                ) from exc
            meta = store_metadata(conn)
            digest = meta.get("contract_digest")
            if not digest:
                raise SnapshotError(f"store lacks contract_digest: {path}")
            contract_digests.add(digest)
        finally:
            conn.close()
    if not paths:
        raise SnapshotError("cannot create a snapshot without a CoSchema store")
    if len(versions) != 1 or len(contract_digests) != 1:
        raise SnapshotError(
            "snapshot stores use mixed CoSchema formats or package digests"
        )
    return versions.pop(), contract_digests.pop(), paths


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
    store_root: Path | None = None,
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
        durable_project_root(store_root, project_id).resolve()
        if store_root is not None and project_id is not None
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
        expected_base, snapshot.name, allow_contract_mismatch=True
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
    store_root: Path | None = None,
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
        durable_project_root(store_root, project_id).resolve()
        if store_root is not None and project_id is not None
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
                expected_base, candidate.name, allow_contract_mismatch=True
            )
        except SnapshotError as exc:
            errors.append(f"{candidate.name}: {exc}")
            continue
        return publish_snapshot(
            project_path, candidate,
            store_root=store_root, project_id=project_id,
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
    store_root: Path | None = None,
    project_id: str | None = None,
    publish: bool = True,
) -> Path:
    """Build an immutable snapshot and optionally publish it as current."""
    local_base = project_path / STORE_DIR
    base = (
        durable_project_root(store_root, project_id)
        if store_root is not None and project_id is not None
        else local_base
    )
    snapshots = base / SNAPSHOTS_DIR
    snapshots.mkdir(parents=True, exist_ok=True)
    store_format_version, store_digest, source_stores = _store_package_identity(
        store_paths
    )
    if store_format_version == FORMAT_VERSION and store_digest != contract_digest():
        raise SnapshotError(
            "current-format store was written under a different CoSchema contract"
        )
    created_at = datetime.now(UTC)
    created_at_text = created_at.isoformat()
    policy = build_policy or {"raw_mode": "seal" if seal else "unspecified"}
    policy_digest = codess_canonical_hash(256, 256, policy)
    # A creation identity: the suffix disambiguates snapshots created within
    # one microsecond of each other, not across a corpus, so the narrowest
    # supported width is ample (13.4.8).
    identity = codess_hash(
        256, 64,
        [str(project_path.resolve()), created_at_text, store_digest, policy_digest],
    )
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
                source_path, target,
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
            "build_policy_digest": policy_digest,
            "format_id": FORMAT_ID,
            "format_version": store_format_version,
            "contract_digest": store_digest,
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
            store_root=store_root,
            project_id=project_id,
        )
        _trim_prior_snapshots(snapshots, keep_current=snapshot_id)
    return final


def _trim_prior_snapshots(snapshots: Path, *, keep_current: str) -> list[str]:
    """Remove superseded snapshots beyond the configured limit.

    Runs only after the new snapshot is published, so a failure here leaves a
    complete, current, pointed-at store set behind: the worst outcome is that
    more snapshots are retained than asked for, which is recoverable, while
    trimming first could leave a Project with no readable store at all.

    `CODESS_KEEP_SNAPSHOTS` counts snapshots *besides* the current one,
    so the default of 2 leaves three directories: a rollback target, its
    predecessor, and the snapshot just published. 0 disables trimming, which
    an operator auditing a sequence of rebuilds needs.

    Names sort chronologically because a snapshot id begins with its creation
    timestamp, so the oldest are the ones removed. A directory that cannot be
    removed is reported rather than raised: retention is not the operation the
    caller asked for.
    """
    if KEEP_SNAPSHOTS <= 0:
        return []
    prior = sorted(
        entry.name for entry in snapshots.iterdir()
        if entry.is_dir() and entry.name != keep_current
        and not entry.name.startswith(".")
    )
    removed = []
    for name in prior[:max(0, len(prior) - KEEP_SNAPSHOTS)]:
        try:
            shutil.rmtree(snapshots / name)
        except OSError as exc:
            emit_named("snapshot.trim_failed", snapshot=name, error=type(exc).__name__)
            continue
        removed.append(name)
    if removed:
        emit_named("snapshot.trimmed", removed=len(removed), kept=KEEP_SNAPSHOTS)
    return removed


def rebuild_manifest(snapshot_dir: Path) -> dict[str, Any]:
    """Reconstruct manifest.json from surviving store DBs + raw-manifest.jsonl.

    Most fields are recoverable from each store's own store_meta table or
    recomputed from the files themselves. `parent_snapshot_id`,
    `build_policy`, and `build_policy_digest` are not recorded anywhere
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
    contract_digest: str | None = None
    project_id: str | None = None
    for path in store_paths:
        conn = open_readonly(path)
        try:
            version = require_store(conn, write=False)
            format_version = format_version or version
            meta = store_metadata(conn)
            for key in (
                "snapshot_created_at", "snapshot_software_version",
                "decoder_version", "validator_version", "contract_digest",
            ):
                meta_by_key.setdefault(key, meta.get(key))
            contract_digest = contract_digest or meta.get("contract_digest")
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
        # The directory name is the snapshot identity; the stores no longer
        # carry a copy of it.
        "snapshot_id": snapshot_dir.name,
        "parent_snapshot_id": None,
        "created_at": meta_by_key.get("snapshot_created_at"),
        "software_version": meta_by_key.get("snapshot_software_version"),
        "software_revision": None,
        "decoder_version": meta_by_key.get("decoder_version"),
        "validator_version": meta_by_key.get("validator_version"),
        "build_policy": None,
        "build_policy_digest": None,
        "format_id": FORMAT_ID,
        "format_version": format_version,
        "contract_digest": contract_digest,
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
    allow_contract_mismatch: bool = False,
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
            # Codess rebuilds rather than migrates, so the remedy is named
            # here: a reader who is told only that the format is unsupported
            # has no way to learn that re-ingesting is what resolves it.
            raise SnapshotError(
                f"retained snapshot is CoSchema format "
                f"{manifest.get('format_version')}, and this build reads "
                f"{sorted(SUPPORTED_READ_FORMATS)}; rebuild it from the vendor "
                f"sources with `codess ingest --force --dir <project>`"
            )
        contract_matches = manifest.get("contract_digest") == contract_digest()
        if not contract_matches and not allow_contract_mismatch:
            raise SnapshotContractMismatchError(
                "retained snapshot was written under a different CoSchema "
                "contract; rebuild it with `codess ingest --force`, or pass "
                "--snapshot-policy read-compatible to read it as it "
                "stands"
            )
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
            conn = open_readonly(path)
            try:
                if contract_matches:
                    require_store(conn, write=False)
                else:
                    application_id, version = database_identity(conn)
                    if application_id != APPLICATION_ID or version not in SUPPORTED_READ_FORMATS:
                        raise SnapshotError(f"retained store format mismatch: {name}")
                meta = store_metadata(conn)
                # Membership is established by the manifest hash verified
                # above, which names this exact file; a `snapshot_id` copied
                # into the store would only restate it.
                if meta.get("contract_digest") != manifest.get("contract_digest"):
                    raise SnapshotContractMismatchError(
                        f"retained store records a different CoSchema contract: {name}"
                    )
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
    allow_contract_mismatch: bool = False,
) -> list[Path]:
    """Resolve one retained snapshot from a Project's local snapshot base."""
    return snapshot_store_paths_from_base(
        project_path / STORE_DIR,
        snapshot_id,
        allow_contract_mismatch=allow_contract_mismatch,
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
