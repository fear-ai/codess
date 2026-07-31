"""Bounded relational keys derived from vendor tool-invocation identifiers."""

from __future__ import annotations

import hashlib


SOURCE_CALL_ID_MAX_BYTES = 100
_DIGEST_HEX_CHARS = 64
_SUFFIX_PREFIX = "~sha256:"


def bounded_source_call_id(
    value: object,
    *,
    max_bytes: int = SOURCE_CALL_ID_MAX_BYTES,
) -> str:
    """Return a deterministic UTF-8 key no larger than ``max_bytes``.

    Short identifiers remain byte-for-byte unchanged. Long identifiers retain
    a readable prefix and the full SHA-256 digest so equal prefixes do not
    create a practical invocation collision. The exact source value remains in
    Event metadata/raw evidence.
    """
    if max_bytes <= len(_SUFFIX_PREFIX) + _DIGEST_HEX_CHARS:
        raise ValueError("source call ID byte limit is too small")
    text = str(value)
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    suffix = (
        _SUFFIX_PREFIX
        + hashlib.sha256(encoded).hexdigest()[:_DIGEST_HEX_CHARS]
    ).encode("ascii")
    prefix = encoded[: max_bytes - len(suffix)]
    while prefix:
        try:
            decoded = prefix.decode("utf-8")
            break
        except UnicodeDecodeError:
            prefix = prefix[:-1]
    else:
        decoded = ""
    return decoded + suffix.decode("ascii")
