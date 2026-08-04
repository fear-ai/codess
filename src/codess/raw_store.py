"""codess.raw/1 exact-source capture and content-addressed object storage."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from codess.fileio import hash_file, source_fingerprint

try:
    import zstandard
except ImportError:  # pragma: no cover - exercised as a user-facing error
    zstandard = None


RAW_FORMAT = "codess.raw/1"
RAW_MODES = frozenset({"none", "reference", "capture", "seal"})
CAPTURE_CHUNK_SIZE = 1024 * 1024
CAPTURE_ZSTD_LEVEL = 3


class RawCaptureError(RuntimeError):
    """A requested raw observation/capture could not be completed safely."""


def verify_captured_object(path: Path, record: dict[str, Any]) -> dict[str, Any]:
    """Verify a captured object with fixed memory use.

    The compressed representation and decompressed source bytes have distinct
    identities.  They are therefore read in two bounded passes: one for the
    stored-object digest and one through zstd's streaming reader for the exact
    source digest.  No compressed or decompressed object is materialized in
    memory.
    """
    if zstandard is None:
        raise RawCaptureError(
            "raw verification requires the zstandard package; install requirements.txt"
        )
    if record.get("compression") != "zstd":
        raise RawCaptureError(
            f"unsupported raw-object compression: {record.get('compression')!r}"
        )
    try:
        stored_size = path.stat().st_size
        stored_sha256 = hash_file(path, chunk_size=CAPTURE_CHUNK_SIZE)
        content_digest = hashlib.sha256()
        uncompressed_size = 0
        with path.open("rb") as compressed:
            with zstandard.ZstdDecompressor().stream_reader(compressed) as source:
                while True:
                    chunk = source.read(CAPTURE_CHUNK_SIZE)
                    if not chunk:
                        break
                    content_digest.update(chunk)
                    uncompressed_size += len(chunk)
    except (OSError, zstandard.ZstdError) as exc:
        raise RawCaptureError(f"raw verification failed for {path}: {exc}") from exc
    return {
        "stored_size": stored_size,
        "stored_sha256": stored_sha256,
        "uncompressed_size": uncompressed_size,
        "object_id": f"sha256:{content_digest.hexdigest()}",
    }


def materialize_captured_object(
    path: Path, target: Path, record: dict[str, Any],
) -> dict[str, Any]:
    """Restore one captured object atomically with bounded memory use."""
    if zstandard is None:
        raise RawCaptureError(
            "raw materialization requires the zstandard package; install requirements.txt"
        )
    if record.get("compression") != "zstd":
        raise RawCaptureError(
            f"unsupported raw-object compression: {record.get('compression')!r}"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    staged = target.with_name(f".{target.name}.tmp-{os.getpid()}")
    content_digest = hashlib.sha256()
    uncompressed_size = 0
    try:
        stored_size = path.stat().st_size
        stored_sha256 = hash_file(path, chunk_size=CAPTURE_CHUNK_SIZE)
        with path.open("rb") as compressed, staged.open("wb") as output:
            with zstandard.ZstdDecompressor().stream_reader(compressed) as source:
                while True:
                    chunk = source.read(CAPTURE_CHUNK_SIZE)
                    if not chunk:
                        break
                    output.write(chunk)
                    content_digest.update(chunk)
                    uncompressed_size += len(chunk)
            output.flush()
            os.fsync(output.fileno())
        observed = {
            "stored_size": stored_size,
            "stored_sha256": stored_sha256,
            "uncompressed_size": uncompressed_size,
            "object_id": f"sha256:{content_digest.hexdigest()}",
        }
        for key in ("stored_size", "stored_sha256", "uncompressed_size", "object_id"):
            if observed[key] != record.get(key):
                raise RawCaptureError(
                    f"raw materialization {key} mismatch for {path}: "
                    f"{observed[key]!r} != {record.get(key)!r}"
                )
        os.replace(staged, target)
        return observed
    except (OSError, zstandard.ZstdError) as exc:
        raise RawCaptureError(f"raw materialization failed for {path}: {exc}") from exc
    finally:
        staged.unlink(missing_ok=True)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sqlite_backup(
    path: Path,
    backup_path: Path,
    progress: Callable[..., Any] | None = None,
) -> os.stat_result:
    """Write one transactionally consistent backup without materializing it."""
    source = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    target = sqlite3.connect(backup_path)
    backup_started = last_progress = time.monotonic()

    def backup_progress(_status: int, remaining: int, total: int) -> None:
        nonlocal last_progress
        now = time.monotonic()
        if progress is not None and now - last_progress >= 5.0:
            progress(
                "raw.sqlite_backup.progress", source=str(path.resolve()),
                pages_completed=total - remaining, pages_total=total,
                phase_seconds=round(now - backup_started, 3),
            )
            last_progress = now

    try:
        source.execute("PRAGMA query_only = ON")
        source.backup(
            target, pages=256, sleep=0.01, progress=backup_progress,
        )
        target.commit()
        # A backup of a WAL-mode source may retain WAL-mode header bytes even
        # though no WAL sidecar belongs to the standalone backup.  Normalize
        # the container so it remains queryable through a strict read-only
        # connection after this writable handle closes.
        journal_mode = target.execute("PRAGMA journal_mode=DELETE").fetchone()
        if journal_mode is None or str(journal_mode[0]).lower() != "delete":
            raise RawCaptureError(
                f"SQLite backup could not become standalone for {path}"
            )
        result = target.execute("PRAGMA quick_check").fetchone()
        if result is None or result[0] != "ok":
            raise RawCaptureError(f"SQLite backup quick-check failed for {path}")
    except sqlite3.Error as exc:
        raise RawCaptureError(f"SQLite backup failed for {path}: {exc}") from exc
    finally:
        target.close()
        source.close()
    return path.stat()


def _compress_file(
    source_path: Path,
    staged_path: Path,
    *,
    require_stable_stat: bool,
    compression_level: int = CAPTURE_ZSTD_LEVEL,
) -> tuple[str, str, int, int, os.stat_result]:
    """Stream a file into zstd while calculating bounded source/object hashes."""
    before = source_path.stat()
    content_digest = hashlib.sha256()
    uncompressed_size = 0
    try:
        with source_path.open("rb") as source, staged_path.open("wb") as target:
            compressor = zstandard.ZstdCompressor(level=compression_level)
            with compressor.stream_writer(
                target, size=before.st_size, closefd=False
            ) as compressed:
                while True:
                    chunk = source.read(CAPTURE_CHUNK_SIZE)
                    if not chunk:
                        break
                    content_digest.update(chunk)
                    uncompressed_size += len(chunk)
                    compressed.write(chunk)
            target.flush()
            os.fsync(target.fileno())
        after = source_path.stat()
    except OSError as exc:
        raise RawCaptureError(f"raw capture failed for {source_path}: {exc}") from exc
    if require_stable_stat and (
        before.st_mtime_ns, before.st_size
    ) != (
        after.st_mtime_ns, after.st_size
    ):
        raise RawCaptureError(f"source changed during capture: {source_path}")
    if uncompressed_size != before.st_size:
        raise RawCaptureError(
            f"source size changed during capture: {source_path} "
            f"({before.st_size} to {uncompressed_size})"
        )
    return (
        content_digest.hexdigest(),
        hash_file(staged_path, chunk_size=CAPTURE_CHUNK_SIZE),
        uncompressed_size,
        staged_path.stat().st_size,
        after,
    )


class RawStore:
    """Content-addressed raw object repository rooted outside project stores."""

    def __init__(self, root: Path):
        self.root = root / "codess.raw-1"

    def observe(
        self,
        path: Path,
        *,
        source_system_id: str,
        storage_format: str,
        mode: str,
        source_locator: str | None = None,
        materialized_target: Path | None = None,
        progress: Callable[..., Any] | None = None,
    ) -> dict[str, Any]:
        if mode not in RAW_MODES:
            raise RawCaptureError(f"invalid raw mode: {mode}")
        try:
            stat = path.stat()
        except OSError as exc:
            raise RawCaptureError(f"cannot observe raw source {path}: {exc}") from exc
        record: dict[str, Any] = {
            "record_type": "source_revision",
            "raw_format": RAW_FORMAT,
            "source_system_id": source_system_id,
            "storage_format": storage_format,
            "source_locator": source_locator or str(path.resolve()),
            "observed_at": _now(),
            "source_mtime_ns": stat.st_mtime_ns,
            "source_size": stat.st_size,
            "availability": "not_retained" if mode == "none" else "reference",
            "capture_method": "stat",
            "consistency": "observed",
            "redaction": "none",
        }
        if mode in {"none", "reference"}:
            revision, _mtime, size, method, consistency = source_fingerprint(path)
            record.update({
                "source_revision_id": revision,
                "source_size": size,
                "capture_method": method,
                "consistency": consistency,
            })
            return record
        if zstandard is None:
            raise RawCaptureError(
                "raw capture requires the zstandard package; install requirements.txt"
            )
        staging = self.root / ".staging"
        staging.mkdir(parents=True, exist_ok=True)
        staged_fd, staged_name = tempfile.mkstemp(prefix="capture-", suffix=".zst", dir=staging)
        os.close(staged_fd)
        staged_path = Path(staged_name)
        backup_directory = None
        source_stat = stat
        try:
            if storage_format == "cursor-sqlite":
                backup_directory = tempfile.TemporaryDirectory(
                    prefix="codess-raw-sqlite-"
                )
                capture_path = Path(backup_directory.name) / "source.sqlite"
                phase_started = time.monotonic()
                if progress is not None:
                    progress(
                        "raw.sqlite_backup.start",
                        source=str(path.resolve()), source_bytes=stat.st_size,
                    )
                stat = _sqlite_backup(path, capture_path, progress=progress)
                if progress is not None:
                    progress(
                        "raw.sqlite_backup.done",
                        source=str(path.resolve()),
                        backup_bytes=capture_path.stat().st_size,
                        phase_seconds=round(time.monotonic() - phase_started, 3),
                    )
                capture_method = "sqlite-backup"
                consistency = "transactional-snapshot"
                require_stable_stat = False
            else:
                capture_path = path
                capture_method = "stable-file-read"
                consistency = "stable-stat"
                require_stable_stat = True
            phase_started = time.monotonic()
            if progress is not None:
                progress(
                    "raw.compress.start", source=str(path.resolve()),
                    input_bytes=capture_path.stat().st_size,
                )
            (
                content_hash,
                stored_hash,
                uncompressed_size,
                stored_size,
                captured_stat,
            ) = _compress_file(
                capture_path,
                staged_path,
                require_stable_stat=require_stable_stat,
            )
            if progress is not None:
                progress(
                    "raw.compress.done", source=str(path.resolve()),
                    input_bytes=uncompressed_size, stored_bytes=stored_size,
                    phase_seconds=round(time.monotonic() - phase_started, 3),
                )
            if storage_format != "cursor-sqlite":
                source_stat = captured_stat
            object_path = (
                self.root / "objects" / "sha256" / content_hash[:2]
                / f"{content_hash}.zst"
            )
            object_path.parent.mkdir(parents=True, exist_ok=True)
            if object_path.exists():
                phase_started = time.monotonic()
                if progress is not None:
                    progress(
                        "raw.object_verify.start", object_id=f"sha256:{content_hash}",
                        stored_bytes=object_path.stat().st_size,
                    )
                try:
                    existing = verify_captured_object(
                        object_path, {"compression": "zstd"}
                    )
                except RawCaptureError as exc:
                    raise RawCaptureError(
                        f"existing raw object is corrupt: {object_path}: {exc}"
                    ) from exc
                if existing["object_id"] != f"sha256:{content_hash}":
                    raise RawCaptureError(
                        f"raw object content identity collision: {object_path}"
                    )
                # Content identity names the object.  Different zstd versions
                # or settings may produce different stored bytes for the same
                # source, so retain and report the already-promoted encoding.
                stored_hash = existing["stored_sha256"]
                stored_size = existing["stored_size"]
                uncompressed_size = existing["uncompressed_size"]
                if progress is not None:
                    progress(
                        "raw.object_verify.done", object_id=f"sha256:{content_hash}",
                        stored_bytes=stored_size,
                        phase_seconds=round(time.monotonic() - phase_started, 3),
                    )
            else:
                os.replace(staged_path, object_path)
                if progress is not None:
                    progress(
                        "raw.object_promoted", object_id=f"sha256:{content_hash}",
                        stored_bytes=stored_size,
                    )
            if materialized_target is not None:
                if storage_format != "cursor-sqlite":
                    raise RawCaptureError(
                        "materialized capture output is supported only for SQLite"
                    )
                materialized_target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(capture_path, materialized_target)
                if progress is not None:
                    progress(
                        "raw.materialized.done", target=str(materialized_target),
                        materialized_bytes=materialized_target.stat().st_size,
                    )
        finally:
            staged_path.unlink(missing_ok=True)
            if backup_directory is not None:
                backup_directory.cleanup()
        record.update(
            {
                "source_revision_id": f"sha256:{content_hash}",
                "availability": "captured",
                "capture_method": capture_method,
                "consistency": consistency,
                "object_id": f"sha256:{content_hash}",
                "stored_sha256": stored_hash,
                "compression": "zstd",
                "uncompressed_size": uncompressed_size,
                "stored_size": stored_size,
                "object_relpath": str(object_path.relative_to(self.root)),
                "source_mtime_ns": source_stat.st_mtime_ns,
                "source_size": source_stat.st_size,
            }
        )
        return record

    def observe_related(
        self,
        path: Path,
        *,
        source_system_id: str,
        storage_format: str,
        mode: str,
        parent_source_locator: str,
        relation_kind: str,
        progress: Callable[..., Any] | None = None,
    ) -> dict[str, Any]:
        """Observe external content as a linked raw revision.

        The object remains exact raw evidence.  ``record_id`` identifies the
        relationship record, not the content object, so the same object may be
        linked from more than one transcript without losing provenance.
        """
        record = self.observe(
            path,
            source_system_id=source_system_id,
            storage_format=storage_format,
            mode=mode,
            progress=progress,
        )
        identity = "\0".join((
            parent_source_locator,
            relation_kind,
            str(record.get("source_locator") or ""),
            str(record.get("source_revision_id") or ""),
        ))
        record.update({
            "record_type": "related_content_revision",
            "record_id": "rawrel:sha256:" + hashlib.sha256(
                identity.encode("utf-8")
            ).hexdigest(),
            "parent_source_locator": parent_source_locator,
            "relation_kind": relation_kind,
        })
        return record

    def resolve(self, record: dict[str, Any]) -> Path | None:
        relpath = record.get("object_relpath")
        return self.root / relpath if relpath else None
