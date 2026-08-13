"""Small durable-file primitives shared by operations and compatibility tools."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from codess.config import (
    HASH_CHUNK_BYTES,
    SOURCE_FULL_HASH_MAX,
    SOURCE_SAMPLE_CHUNK_BYTES,
)
from codess.hashing import codess_bytes_hash, codess_digest

log = logging.getLogger(__name__)

SOURCE_SAMPLE_WINDOWS = 8


class HashMismatchError(RuntimeError):
    """A file's content did not match the hash a caller expected."""


def open_readonly(
    db_path: Path, *, timeout: float = 5.0, immutable: bool = False,
) -> sqlite3.Connection:
    """Open any SQLite file read-only, without asserting it is a CoSchema store.

    `store.connect(read_only=True)` additionally validates the store contract,
    which is right for querying but wrong for the readers that must open a
    file precisely because its contract may not hold -- a snapshot under a
    package mismatch, an archived store being fingerprinted, a vendor
    database. Those readers had each written the URI by hand, and only some
    also set `query_only`, so the guarantee varied by call site rather than by
    intent.

    `query_only` is set for all of them: a read that opens a file it does not
    own must not be able to write to it even by mistake. This lives beside the
    other durable-file primitives rather than in `store`, since the callers
    include source access and raw storage, which must not depend on the store
    layer.

    `busy_timeout` waits rather than failing immediately when another process
    holds the write lock, which a vendor database being written by its own
    application routinely is. `immutable` opens a file that has no WAL or
    shared-memory sidecar and cannot be opened read-only otherwise; it is
    unsafe for a live database, so the caller asserts the sidecar-free shape
    rather than this function guessing.
    """
    parameters = "?mode=ro&immutable=1" if immutable else "?mode=ro"
    conn = sqlite3.connect(
        db_path.resolve().as_uri() + parameters, uri=True, timeout=timeout,
    )
    conn.execute("PRAGMA query_only = ON")
    conn.execute(f"PRAGMA busy_timeout = {int(timeout * 1000)}")
    return conn


def stat_consistency(
    before: os.stat_result, after: os.stat_result,
) -> str:
    """Classify what happened to a file between two stats of it.

    Both readers of a source compare the same pair of facts around a read --
    modification time and size -- and differed only in what they do with the
    answer. `source_fingerprint` records it, because its digest covers a
    defined prefix and an appending session file is ordinary rather than an
    error; raw capture rejects it, because a raw object claims to be the exact
    bytes of one source state. Deciding is therefore shared and the
    disposition is the caller's.

    Returns `stable`, `appended` when the file only grew, or `rewritten` for
    any other change. A rewrite that restores both values is indistinguishable
    from no change here, which is why capture also compares the bytes it
    actually read against the size it was promised.
    """
    if (before.st_mtime_ns, before.st_size) == (after.st_mtime_ns, after.st_size):
        return "stable"
    return "appended" if after.st_size > before.st_size else "rewritten"


def _no_hash_active() -> bool:
    """True when CODESS_NO_HASH opts out of read_hash/rewrite_hash verification.

    Read directly from os.environ rather than config.NO_HASH: `--no-hash`
    sets the environment variable after config.py's module-level constants
    have already been resolved (see project.parse_and_run), so config.NO_HASH
    would still read stale/false for a CLI-flag-triggered bypass -- checking
    os.environ here is not a leaf-module import restriction, it is what
    makes the flag (not just the env var set before process start) work.
    """
    return os.environ.get("CODESS_NO_HASH", "0").strip().lower() in ("1", "true", "yes")


def hash_file(path: Path, *, chunk_size: int = HASH_CHUNK_BYTES) -> str:
    digest = codess_digest()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_hash(path: Path, *, expected_hash: str | None = None) -> bytes:
    """Read `path` and verify its content against `expected_hash`.

    Returns raw bytes always -- JSON callers do `json.loads(read_hash(...))`
    themselves rather than this primitive knowing about JSON. Verification
    is skipped, with a logged warning, when CODESS_NO_HASH is set; the read
    itself still happens (a missing/unreadable file still raises OSError).
    Raises HashMismatchError, not a plain assertion, so callers can catch it
    distinctly from a malformed-content or missing-file failure.
    """
    content = path.read_bytes()
    if expected_hash is None:
        return content
    if _no_hash_active():
        log.warning("hash verification skipped (CODESS_NO_HASH): %s", path)
        return content
    actual = codess_bytes_hash(256, 256, content)
    if actual != expected_hash:
        raise HashMismatchError(
            f"hash mismatch for {path}: expected {expected_hash}, got {actual}"
        )
    return content


def verify_hash(path: Path, expected_hash: str) -> None:
    """Verify `path`'s content matches `expected_hash` without holding the
    file in memory.

    Use this instead of `read_hash` when a caller only needs pass/fail on a
    file that may be large (a raw-capture object, a SQLite store) and never
    reads its content afterward -- `read_hash` returns full content, which
    is correct for small JSON documents but would read a multi-GB
    file into memory for no reason here. Streams via `hash_file`'s chunked read.
    Raises HashMismatchError on mismatch; a no-op when CODESS_NO_HASH is
    set (still logs a warning, matching read_hash).
    """
    if _no_hash_active():
        log.warning("hash verification skipped (CODESS_NO_HASH): %s", path)
        return
    actual = hash_file(path)
    if actual != expected_hash:
        raise HashMismatchError(
            f"hash mismatch for {path}: expected {expected_hash}, got {actual}"
        )


def write_hash(path: Path, content: bytes) -> str:
    """Write `content` to `path` atomically and return its SHA-256 hash.

    Uses the same temp-file-then-replace pattern as write_json_atomic so a
    reader never observes a partially written file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    temporary.write_bytes(content)
    temporary.replace(path)
    return codess_bytes_hash(256, 256, content)


def rewrite_hash(
    path: Path,
    expected_old_hash: str,
    mutator: Callable[[bytes], bytes],
) -> str:
    """Read-modify-write `path`: verify its current hash, transform its
    content, write the result atomically, and return the new hash.

    Refuses to clobber a file that changed underneath the caller's assumed
    `expected_old_hash` (raises HashMismatchError, same as read_hash) --
    this is the guard a hand-rolled read-then-write of a pointer or manifest
    document would otherwise have to reimplement at every call site.
    """
    old_content = read_hash(path, expected_hash=expected_old_hash)
    new_content = mutator(old_content)
    return write_hash(path, new_content)


def read_exactly(stream: Any, limit: int, chunk_size: int) -> Iterator[bytes]:
    """Yield at most `limit` bytes from `stream`, in chunks.

    Reading to end-of-file is wrong for a file something else is writing:
    the end moves, so the read covers a state that never existed as a whole.
    Reading a fixed count decided before the read starts gives a well-defined
    prefix instead. If the file has since grown, the prefix is still exactly
    the bytes that were there at the start; if it has been truncated, the
    stream simply ends early and the caller sees fewer bytes than requested.
    """
    remaining = limit
    while remaining > 0:
        chunk = stream.read(min(chunk_size, remaining))
        if not chunk:
            return
        remaining -= len(chunk)
        yield chunk


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
    digest = codess_digest()
    try:
        with path.open("rb") as stream:
            if before.st_size <= SOURCE_FULL_HASH_MAX:
                # Hash exactly the bytes the first stat announced, not to EOF:
                # a session file being appended to has no stable end.
                read_bytes = 0
                for chunk in read_exactly(
                    stream, before.st_size, SOURCE_SAMPLE_CHUNK_BYTES
                ):
                    digest.update(chunk)
                    read_bytes += len(chunk)
                method = "full-sha256-fingerprint"
                revision = (
                    f"sha256-fingerprint:{digest.hexdigest()}:size:{read_bytes}"
                )
            else:
                maximum_offset = max(0, before.st_size - SOURCE_SAMPLE_CHUNK_BYTES)
                offsets = sorted({
                    (maximum_offset * index) // (SOURCE_SAMPLE_WINDOWS - 1)
                    for index in range(SOURCE_SAMPLE_WINDOWS)
                })
                digest.update(f"size:{before.st_size}\0".encode("ascii"))
                for offset in offsets:
                    stream.seek(offset)
                    chunk = stream.read(SOURCE_SAMPLE_CHUNK_BYTES)
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
    # The fingerprint above covers a defined prefix, so growth does not
    # invalidate it: the digest still describes exactly the bytes that were
    # present when the read began. Report the change as advisory rather than
    # discarding a usable revision -- an appending session file is ordinary,
    # not an error.
    mtime = after.st_mtime * 1000
    size = before.st_size
    consistency = stat_consistency(before, after)
    wal_path = Path(str(path) + "-wal")
    if _include_sidecars and wal_path.is_file():
        wal_revision, wal_mtime, wal_size, wal_method, wal_consistency = (
            source_fingerprint(wal_path, _include_sidecars=False)
        )
        combined_digest = codess_digest()
        combined_digest.update(
            f"main:{revision}\0wal:{wal_revision}".encode()
        )
        revision = (
            "sqlite-main-wal-sha256-fingerprint:"
            f"{combined_digest.hexdigest()}"
        )
        mtime = max(value for value in (mtime, wal_mtime) if value is not None)
        size += wal_size or 0
        method = f"{method}+wal:{wal_method}"
        consistency = (
            "stable-main-wal-nontransactional"
            if wal_consistency == "stable"
            else f"wal-{wal_consistency}"
        )
    return revision, mtime, size, method, consistency


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_versioned_policy(path: Path, *, document_name: str) -> dict[str, Any]:
    """Load one versioned JSON policy document from `path`.

    Callers own the "no policy file selected" case (see
    baseline_validation.load_policy) and must not call this with `path=None`.
    Wraps read/parse failures as ValueError so every policy caller raises
    the same error type as its own field-specific checks, rather than
    letting OSError/JSONDecodeError escape with unrelated exception types.
    Does not check policy_format or field names -- see
    check_policy_format(), applied separately once the caller knows its own
    expected format and allowed-fields set.
    """
    try:
        policy = read_json(path)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot load {document_name} {path}: {exc}") from exc
    if not isinstance(policy, dict):
        raise ValueError(f"{document_name} must be a JSON object")
    return policy


def check_policy_format(
    policy: dict[str, Any],
    *,
    expected_format: str,
    allowed_fields: frozenset[str] | set[str],
    document_name: str,
) -> None:
    """Check the shape two independent policy validators shared verbatim.

    candidate_review.validate_policy and baseline_validation.load_policy
    each hand-rolled this exact format-marker-then-unknown-fields sequence
    for their own differently-shaped policy documents; every field beyond
    this is genuinely specific to each document and stays in its own
    module -- see CoPlan.md 13.4.2 for why this is a narrow, not a
    5-function, consolidation.
    """
    if policy.get("policy_format") != expected_format:
        raise ValueError(f"{document_name} must declare {expected_format}")
    unknown = sorted(set(policy) - allowed_fields)
    if unknown:
        raise ValueError(
            f"{document_name} has unknown fields: " + ", ".join(unknown)
        )


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)
