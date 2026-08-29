"""codess.raw/2 exact-source capture and content-addressed object storage."""

from __future__ import annotations

import os
import sqlite3
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from codess.config import RAW_CAPTURE_CHUNK_BYTES, canonical_raw_mode
from codess.config import RAW_MODES as RAW_MODE_VALUES
from codess.fileio import hash_file, open_readonly, read_source_revision, stat_consistency
from codess.hashing import codess_digest, codess_text_hash
from codess.timeval import now_iso
from codess.wallclock import system_clock

# Raw capture needs zstandard, ordinary ingest does not; each entry point
# raises a user-facing error on None before touching it. The None assignment is
# an accepted mypy error, as in `resources.py`.
try:
    import zstandard
except ImportError:  # pragma: no cover - exercised as a user-facing error
    zstandard = None


RAW_FORMAT = "codess.raw/2"
RAW_MODES = frozenset(RAW_MODE_VALUES)
"""The raw modes as a set, for membership tests. `config` owns the vocabulary."""
CAPTURE_CHUNK_SIZE = RAW_CAPTURE_CHUNK_BYTES
CAPTURE_ZSTD_LEVEL = 3


class RawCaptureError(RuntimeError):
    """A requested raw observation/capture could not be completed safely."""


def _read_source_identity(
    path: Path,
    *,
    output: Any = None,
) -> tuple[str, int]:
    """Recover the original source identity from a stored object.

    A stored object is a compressed copy; its identity is that of the source
    bytes it was made from, so recovering the identity means reading the
    object back to its original form. Returns the source digest and size.
    When `output` is given each chunk is also written there, which is the only
    difference between verifying an object and restoring one.
    Compression is incidental -- it is the storage encoding, not the purpose.
    Nothing beyond one chunk is held in memory.
    """
    content_digest = codess_digest()
    uncompressed_size = 0
    with path.open("rb") as compressed, zstandard.ZstdDecompressor().stream_reader(compressed) as source:
        while True:
            chunk = source.read(CAPTURE_CHUNK_SIZE)
            if not chunk:
                break
            if output is not None:
                output.write(chunk)
            content_digest.update(chunk)
            uncompressed_size += len(chunk)
    return content_digest.hexdigest(), uncompressed_size


def verify_raw(path: Path, record: dict[str, Any]) -> dict[str, Any]:
    """Verify a captured object with fixed memory use.

    The compressed representation and decompressed source bytes have distinct
    identities.  They are therefore read in two bounded passes: one for the
    stored-object digest and one through zstd's streaming reader for the exact
    source digest.  No compressed or decompressed object is held whole in
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
        stored_digest = hash_file(path, chunk_size=CAPTURE_CHUNK_SIZE)
        content_hex, uncompressed_size = _read_source_identity(path)
    except (OSError, zstandard.ZstdError) as exc:
        raise RawCaptureError(f"raw verification failed for {path}: {exc}") from exc
    return {
        "stored_size": stored_size,
        "stored_digest": stored_digest,
        "uncompressed_size": uncompressed_size,
        "object_id": f"digest:{content_hex}",
    }


def restore_raw(
    path: Path, target: Path, record: dict[str, Any],
) -> dict[str, Any]:
    """Restore one captured object atomically with bounded memory use."""
    if zstandard is None:
        raise RawCaptureError(
            "raw restore requires the zstandard package; install requirements.txt"
        )
    if record.get("compression") != "zstd":
        raise RawCaptureError(
            f"unsupported raw-object compression: {record.get('compression')!r}"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    staged = target.with_name(f".{target.name}.tmp-{os.getpid()}")
    try:
        stored_size = path.stat().st_size
        stored_digest = hash_file(path, chunk_size=CAPTURE_CHUNK_SIZE)
        with staged.open("wb") as output:
            content_hex, uncompressed_size = _read_source_identity(path, output=output)
            output.flush()
            os.fsync(output.fileno())
        observed = {
            "stored_size": stored_size,
            "stored_digest": stored_digest,
            "uncompressed_size": uncompressed_size,
            "object_id": f"digest:{content_hex}",
        }
        for key in ("stored_size", "stored_digest", "uncompressed_size", "object_id"):
            if observed[key] != record.get(key):
                raise RawCaptureError(
                    f"raw restore {key} mismatch for {path}: "
                    f"{observed[key]!r} != {record.get(key)!r}"
                )
        os.replace(staged, target)
        return observed
    except (OSError, zstandard.ZstdError) as exc:
        raise RawCaptureError(f"raw restore failed for {path}: {exc}") from exc
    finally:
        staged.unlink(missing_ok=True)


def _sqlite_backup(
    path: Path,
    backup_path: Path,
    progress: Callable[..., Any] | None = None,
) -> os.stat_result:
    """Write one transactionally consistent backup without loading it."""
    source = open_readonly(path)
    # A pure `backup()` target: SQLite copies pages, so row-level constraints
    # never apply and nothing is written through this connection afterwards.
    # It therefore does not use `open_writable`, and says so rather than
    # leaving the difference to be inferred.
    target = sqlite3.connect(backup_path)
    backup_start_tick = last_progress_tick = time.monotonic()

    def backup_progress(_status: int, remaining: int, total: int) -> None:
        nonlocal last_progress_tick
        now_tick = time.monotonic()
        if progress is not None and now_tick - last_progress_tick >= 5.0:
            progress(
                "raw.sqlite_backup.progress", source=str(path.resolve()),
                pages_completed=total - remaining, pages_total=total,
                phase_seconds=round(now_tick - backup_start_tick, 3),
            )
            last_progress_tick = now_tick

    try:
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
    content_digest = codess_digest()
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
    # A raw object claims to be the exact bytes of one source state, so a
    # source that moved during the copy cannot be stored. The shared guard
    # decides what changed; capture differs from fingerprinting only in
    # rejecting any change rather than recording it. It cannot detect a
    # rewrite that restores both values, so the size check below is the
    # stronger guarantee and this is the cheap first rejection.
    if require_stable_stat and stat_consistency(before, after) != "stable":
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

    def __init__(self, root: Path) -> None:
        self.root = root / "codess.raw-1"

    def observe(
        self,
        path: Path,
        *,
        source_system_key: str,
        storage_format: str,
        mode: str,
        source_locator: str | None = None,
        working_target: Path | None = None,
        progress: Callable[..., Any] | None = None,
    ) -> dict[str, Any]:
        mode = canonical_raw_mode(mode)
        if mode not in RAW_MODES:
            raise RawCaptureError(f"invalid raw mode: {mode}")
        try:
            stat = path.stat()
        except OSError as exc:
            raise RawCaptureError(f"cannot observe raw source {path}: {exc}") from exc
        record: dict[str, Any] = {
            "record_type": "source_revision",
            "raw_format": RAW_FORMAT,
            "source_system_key": source_system_key,
            "storage_format": storage_format,
            "source_locator": source_locator or str(path.resolve()),
            "observed_at": now_iso(system_clock),
            "source_mtime_ns": stat.st_mtime_ns,
            "source_size": stat.st_size,
            "availability": "not_retained" if mode == "observe" else "reference",
            "capture_method": "stat",
            "consistency": "observed",
            "redaction": "none",
        }
        if mode in {"observe", "reference"}:
            revision, _mtime, size, method, consistency = read_source_revision(path)
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
                phase_tick = time.monotonic()
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
                        phase_seconds=round(time.monotonic() - phase_tick, 3),
                    )
                capture_method = "sqlite-backup"
                consistency = "transactional-snapshot"
                require_stable_stat = False
            else:
                capture_path = path
                capture_method = "stable-file-read"
                consistency = "stable"
                require_stable_stat = True
            phase_tick = time.monotonic()
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
                    phase_seconds=round(time.monotonic() - phase_tick, 3),
                )
            if storage_format != "cursor-sqlite":
                source_stat = captured_stat
            object_path = (
                self.root / "objects" / "digest" / content_hash[:2]
                / f"{content_hash}.zst"
            )
            object_path.parent.mkdir(parents=True, exist_ok=True)
            if object_path.exists():
                phase_tick = time.monotonic()
                if progress is not None:
                    progress(
                        "raw.object_verify.start", object_id=f"digest:{content_hash}",
                        stored_bytes=object_path.stat().st_size,
                    )
                try:
                    existing = verify_raw(
                        object_path, {"compression": "zstd"}
                    )
                except RawCaptureError as exc:
                    raise RawCaptureError(
                        f"existing raw object is corrupt: {object_path}: {exc}"
                    ) from exc
                if existing["object_id"] != f"digest:{content_hash}":
                    raise RawCaptureError(
                        f"raw object content identity collision: {object_path}"
                    )
                # Content identity names the object.  Different zstd versions
                # or settings may produce different stored bytes for the same
                # source, so retain and report the already-promoted encoding.
                stored_hash = existing["stored_digest"]
                stored_size = existing["stored_size"]
                uncompressed_size = existing["uncompressed_size"]
                if progress is not None:
                    progress(
                        "raw.object_verify.done", object_id=f"digest:{content_hash}",
                        stored_bytes=stored_size,
                        phase_seconds=round(time.monotonic() - phase_tick, 3),
                    )
            else:
                os.replace(staged_path, object_path)
                if progress is not None:
                    progress(
                        "raw.object_promoted", object_id=f"digest:{content_hash}",
                        stored_bytes=stored_size,
                    )
            if working_target is not None:
                if storage_format != "cursor-sqlite":
                    raise RawCaptureError(
                        "a working file for the capture is supported only for SQLite"
                    )
                working_target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(capture_path, working_target)
                if progress is not None:
                    progress(
                        "raw.working_file.written", target=str(working_target),
                        working_bytes=working_target.stat().st_size,
                    )
        finally:
            staged_path.unlink(missing_ok=True)
            if backup_directory is not None:
                backup_directory.cleanup()
        record.update(
            {
                "source_revision_id": f"digest:{content_hash}",
                "availability": "captured",
                "capture_method": capture_method,
                "consistency": consistency,
                "object_id": f"digest:{content_hash}",
                "stored_digest": stored_hash,
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
        source_system_key: str,
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
            source_system_key=source_system_key,
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
            "record_id": "rawrel:digest:" + codess_text_hash(256, 256, identity),
            "parent_source_locator": parent_source_locator,
            "relation_kind": relation_kind,
        })
        return record

    def resolve(self, record: dict[str, Any]) -> Path | None:
        relpath = record.get("object_relpath")
        return self.root / relpath if relpath else None
