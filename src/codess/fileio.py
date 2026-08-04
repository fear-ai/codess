"""Small durable-file primitives shared by operations and compatibility tools."""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any


SOURCE_FULL_HASH_MAX = 64 * 1024 * 1024
SOURCE_SAMPLE_CHUNK = 1024 * 1024
SOURCE_SAMPLE_WINDOWS = 8


def hash_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_fingerprint(
    path: Path,
    *,
    _include_sidecars: bool = True,
) -> tuple[str, float | None, int | None, str, str]:
    """Fingerprint a stable source with bounded SHA-256 I/O."""
    try:
        before = path.stat()
    except OSError:
        return "unavailable", None, None, "unavailable", "unavailable"
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            if before.st_size <= SOURCE_FULL_HASH_MAX:
                for chunk in iter(lambda: stream.read(SOURCE_SAMPLE_CHUNK), b""):
                    digest.update(chunk)
                method = "full-sha256-fingerprint"
                revision = f"sha256-fingerprint:{digest.hexdigest()}"
            else:
                maximum_offset = max(0, before.st_size - SOURCE_SAMPLE_CHUNK)
                offsets = sorted({
                    (maximum_offset * index) // (SOURCE_SAMPLE_WINDOWS - 1)
                    for index in range(SOURCE_SAMPLE_WINDOWS)
                })
                digest.update(f"size:{before.st_size}\0".encode("ascii"))
                for offset in offsets:
                    stream.seek(offset)
                    chunk = stream.read(SOURCE_SAMPLE_CHUNK)
                    digest.update(f"offset:{offset}:length:{len(chunk)}\0".encode("ascii"))
                    digest.update(chunk)
                method = "bounded-sample-sha256-fingerprint"
                revision = (
                    f"sample-sha256-fingerprint:{digest.hexdigest()}:"
                    f"mtime-ns:{before.st_mtime_ns}:size:{before.st_size}"
                )
        after = path.stat()
    except OSError:
        return (
            f"stat:{before.st_mtime_ns}:{before.st_size}",
            before.st_mtime * 1000,
            before.st_size,
            "stat",
            "read-error",
        )
    if (before.st_mtime_ns, before.st_size) != (after.st_mtime_ns, after.st_size):
        return (
            f"volatile-stat:{after.st_mtime_ns}:{after.st_size}",
            after.st_mtime * 1000,
            after.st_size,
            "stat",
            "changed-during-fingerprint",
        )
    mtime = after.st_mtime * 1000
    size = after.st_size
    consistency = "stable-stat"
    wal_path = Path(str(path) + "-wal")
    if _include_sidecars and wal_path.is_file():
        wal_revision, wal_mtime, wal_size, wal_method, wal_consistency = (
            source_fingerprint(wal_path, _include_sidecars=False)
        )
        combined_digest = hashlib.sha256()
        combined_digest.update(
            f"main:{revision}\0wal:{wal_revision}".encode("utf-8")
        )
        revision = (
            "sqlite-main-wal-sha256-fingerprint:"
            f"{combined_digest.hexdigest()}"
        )
        mtime = max(value for value in (mtime, wal_mtime) if value is not None)
        size += wal_size or 0
        method = f"{method}+wal:{wal_method}"
        consistency = (
            "stable-stat-main-wal-nontransactional"
            if wal_consistency == "stable-stat"
            else f"wal-{wal_consistency}"
        )
    return revision, mtime, size, method, consistency


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)
