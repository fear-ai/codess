"""codess.raw/1 exact-source capture and content-addressed object storage."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import zstandard
except ImportError:  # pragma: no cover - exercised as a user-facing error
    zstandard = None


RAW_FORMAT = "codess.raw/1"
RAW_MODES = frozenset({"none", "reference", "capture", "seal"})


class RawCaptureError(RuntimeError):
    """A requested raw observation/capture could not be completed safely."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _stable_file_bytes(path: Path) -> tuple[bytes, os.stat_result]:
    before = path.stat()
    data = path.read_bytes()
    after = path.stat()
    if (before.st_mtime_ns, before.st_size) != (after.st_mtime_ns, after.st_size):
        raise RawCaptureError(f"source changed during capture: {path}")
    return data, after


def _sqlite_backup_bytes(path: Path) -> tuple[bytes, os.stat_result]:
    stat = path.stat()
    with tempfile.TemporaryDirectory(prefix="codess-raw-sqlite-") as directory:
        backup_path = Path(directory) / "source.sqlite"
        source = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        target = sqlite3.connect(backup_path)
        try:
            source.backup(target)
            target.commit()
        except sqlite3.Error as exc:
            raise RawCaptureError(f"SQLite backup failed for {path}: {exc}") from exc
        finally:
            target.close()
            source.close()
        return backup_path.read_bytes(), stat


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
            record["source_revision_id"] = (
                f"stat:{stat.st_mtime_ns}:{stat.st_size}"
            )
            return record
        if zstandard is None:
            raise RawCaptureError(
                "raw capture requires the zstandard package; install requirements.txt"
            )
        if storage_format == "cursor-sqlite":
            data, stat = _sqlite_backup_bytes(path)
            capture_method = "sqlite-backup"
            consistency = "transactional-snapshot"
        else:
            data, stat = _stable_file_bytes(path)
            capture_method = "stable-file-read"
            consistency = "stable-stat"
        content_hash = _digest(data)
        compressed = zstandard.ZstdCompressor(level=6).compress(data)
        stored_hash = _digest(compressed)
        object_path = self.root / "objects" / "sha256" / content_hash[:2] / f"{content_hash}.zst"
        object_path.parent.mkdir(parents=True, exist_ok=True)
        if object_path.exists():
            if _digest(object_path.read_bytes()) != stored_hash:
                raise RawCaptureError(f"raw object hash collision/corruption: {object_path}")
        else:
            tmp = object_path.with_name(f".{object_path.name}.tmp-{os.getpid()}")
            tmp.write_bytes(compressed)
            os.replace(tmp, object_path)
        record.update(
            {
                "source_revision_id": f"sha256:{content_hash}",
                "availability": "captured",
                "capture_method": capture_method,
                "consistency": consistency,
                "object_id": f"sha256:{content_hash}",
                "stored_sha256": stored_hash,
                "compression": "zstd",
                "uncompressed_size": len(data),
                "stored_size": len(compressed),
                "object_relpath": str(object_path.relative_to(self.root)),
                "source_mtime_ns": stat.st_mtime_ns,
                "source_size": stat.st_size,
            }
        )
        return record

    def resolve(self, record: dict[str, Any]) -> Path | None:
        relpath = record.get("object_relpath")
        return self.root / relpath if relpath else None

