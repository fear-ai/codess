"""One derivation and verification point for Codess hash values.

Call sites state how many bits are generated and how many are retained, and
never name the algorithm themselves. Changing the underlying digest is then a
change to this module rather than to every caller, and the supported widths
are declared in one place instead of appearing as bare slice literals.

Four modes cover the operations the codebase performs. They differ in what
they consume, not in the digest they compute:

| Mode | Consumes | Used for |
|---|---|---|
| `codess_hash` | A list of short values | Keys and identities built from a few components |
| `codess_canonical_hash` | One JSON-serializable structure | Digests over a document, where equal content must give equal output |
| `codess_text_hash` | One string, as UTF-8 | Text whose digest is recorded or compared |
| `codess_bytes_hash` | One in-memory buffer | Content already held in memory |
| `codess_stream_hash` | An iterable of chunks | Files and objects too large to hold in memory |

Each has a matching `..._check` that recomputes and compares, so verification
never re-derives the construction by hand. `codess_digest()` returns the
incremental object for callers implementing their own read policy, such as the
bounded window sampling in `fileio.source_fingerprint`; policy of that kind is
deliberately not owned here.

Truncation keeps the leading bits of the digest. Which end is retained does
not affect collision resistance for SHA-256 -- no region of the output is
weaker than another -- but it must be fixed, because a value that changes end
changes every key already derived from it.

This module does not decide what a value means: naming a result `_id`, `_key`,
or `_hash` is the caller's decision and is documented in CoPlan 13.4.8.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable


HASH_FORMAT = "codess.hash/1"

GENERATED_BITS = 256
"""Width the underlying digest produces. Only SHA-256 is supported."""

SUPPORTED_TRUNCATED_BITS = (256, 128, 64)
"""Retained widths. 256 keeps the complete digest; the rest keep leading bits."""

DEFAULT_CHUNK_BYTES = 1024 * 1024

_SEPARATOR = b"\0"


class HashContractError(ValueError):
    """A requested generated or truncated width is not supported."""


def _check_widths(generated_bits: int, truncated_bits: int) -> None:
    if generated_bits != GENERATED_BITS:
        raise HashContractError(
            f"generated width must be {GENERATED_BITS}, not {generated_bits}"
        )
    if truncated_bits not in SUPPORTED_TRUNCATED_BITS:
        raise HashContractError(
            f"truncated width must be one of {SUPPORTED_TRUNCATED_BITS}, "
            f"not {truncated_bits}"
        )


def _encode(value: object) -> bytes:
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    return str(value).encode("utf-8", errors="surrogatepass")


def _truncate(digest: bytes, truncated_bits: int) -> str:
    return digest.hex()[: truncated_bits // 4]


def codess_digest() -> "hashlib._Hash":
    """Return a fresh incremental digest for a caller-owned read policy.

    Use this only when the read pattern itself is the policy -- bounded window
    sampling, or a read bounded to a size decided in advance. Prefer
    `codess_stream_hash` when the input is simply a sequence of chunks.
    """
    return hashlib.sha256()


def canonical_bytes(value: Any) -> bytes:
    """Serialize `value` to the one byte form Codess digests.

    Keys are sorted and separators are compact so that equal content produces
    equal bytes. `ensure_ascii=False` emits UTF-8 directly rather than `\\u`
    escapes; both are valid JSON but they are different bytes, so the choice
    is made once here rather than per call site.

    Encoding uses `surrogatepass` because Codess digests filesystem paths,
    and a path containing bytes that are not valid UTF-8 reaches Python as
    lone surrogates via `os.fsdecode`. Strict encoding raises on those, so a
    single undecodable filename would abort an ingest; `surrogatepass`
    encodes them deterministically instead, which is what a digest needs.
    """
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8", errors="surrogatepass")


def codess_text_hash(
    generated_bits: int,
    truncated_bits: int,
    text: str,
) -> str:
    """Digest one string as UTF-8, with no format tag or separators.

    The result matches an external digest of the same UTF-8 bytes. Encoding
    tolerates lone surrogates for the reason given in `canonical_bytes`.
    """
    _check_widths(generated_bits, truncated_bits)
    encoded = text.encode("utf-8", errors="surrogatepass")
    return _truncate(hashlib.sha256(encoded).digest(), truncated_bits)


def codess_hash(
    generated_bits: int,
    truncated_bits: int,
    inputs: list[object],
) -> str:
    """Derive a hex value of ``truncated_bits`` from ``inputs``.

    Inputs are separated by a NUL byte and prefixed with a format tag, so
    ``["ab", "c"]`` and ``["a", "bc"]`` cannot produce the same value. Byte
    inputs are used as given; everything else is rendered with ``str()`` and
    encoded as UTF-8, which makes the result independent of machine byte
    order and word size but dependent on the exact input text.
    """
    _check_widths(generated_bits, truncated_bits)
    digest = hashlib.sha256()
    digest.update(HASH_FORMAT.encode("ascii"))
    for value in inputs:
        digest.update(_SEPARATOR)
        digest.update(_encode(value))
    return _truncate(digest.digest(), truncated_bits)


def codess_canonical_hash(
    generated_bits: int,
    truncated_bits: int,
    value: Any,
) -> str:
    """Digest one JSON-serializable structure in canonical form.

    Two structures that differ only in key order or whitespace produce the
    same value; anything else produces a different one.
    """
    _check_widths(generated_bits, truncated_bits)
    return _truncate(hashlib.sha256(canonical_bytes(value)).digest(), truncated_bits)


def codess_bytes_hash(
    generated_bits: int,
    truncated_bits: int,
    content: bytes,
) -> str:
    """Digest one in-memory buffer, with no format tag or separators.

    The result is the digest of exactly the bytes supplied, so it matches what
    an external tool computes over the same content.
    """
    _check_widths(generated_bits, truncated_bits)
    return _truncate(hashlib.sha256(content).digest(), truncated_bits)


def codess_stream_hash(
    generated_bits: int,
    truncated_bits: int,
    chunks: Iterable[bytes],
) -> str:
    """Digest a sequence of chunks without holding the whole input in memory.

    Equivalent to `codess_bytes_hash` over the concatenation, so a file read
    in pieces and the same file read whole agree.
    """
    _check_widths(generated_bits, truncated_bits)
    digest = hashlib.sha256()
    for chunk in chunks:
        digest.update(chunk)
    return _truncate(digest.digest(), truncated_bits)


def _matches(actual: str, expected: str | None) -> bool:
    return actual == (expected or "").strip().lower()


def codess_check_hash(
    generated_bits: int,
    truncated_bits: int,
    inputs: list[object],
    expected: str | None,
) -> bool:
    """Recompute a component-derived value and report whether it matches.

    Comparison is case-insensitive on the hex text so a value stored in
    either case verifies. A caller needing failure to be an error should
    raise on a false result rather than expect an exception here.
    """
    return _matches(codess_hash(generated_bits, truncated_bits, inputs), expected)


def codess_check_canonical_hash(
    generated_bits: int,
    truncated_bits: int,
    value: Any,
    expected: str | None,
) -> bool:
    """Recompute a canonical-document digest and report whether it matches."""
    return _matches(
        codess_canonical_hash(generated_bits, truncated_bits, value), expected
    )


def codess_check_bytes_hash(
    generated_bits: int,
    truncated_bits: int,
    content: bytes,
    expected: str | None,
) -> bool:
    """Recompute an in-memory content digest and report whether it matches."""
    return _matches(
        codess_bytes_hash(generated_bits, truncated_bits, content), expected
    )


def codess_check_stream_hash(
    generated_bits: int,
    truncated_bits: int,
    chunks: Iterable[bytes],
    expected: str | None,
) -> bool:
    """Recompute a streamed content digest and report whether it matches."""
    return _matches(
        codess_stream_hash(generated_bits, truncated_bits, chunks), expected
    )
