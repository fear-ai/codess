"""Shared bounds for normalized runtime-context and compaction bodies."""

from __future__ import annotations

from typing import Any

from codess.config import MAX_CONTEXT_CONTENT_CHARS


def context_content_limit(opts: dict[str, Any]) -> int | None:
    """Return the per-event normalized context-body limit.

    ``None`` is an explicit unbounded override.  Missing adapter options use
    the configured default so direct adapter callers receive the same bound as
    the CLI.
    """
    if "max_context_content_chars" in opts:
        value = opts["max_context_content_chars"]
        return None if value is None else int(value)
    return MAX_CONTEXT_CONTENT_CHARS


def bound_context_content(
    value: str,
    opts: dict[str, Any],
) -> tuple[str, int, bool]:
    """Return bounded text, full character count, and truncation status."""
    text = str(value)
    full_length = len(text)
    limit = context_content_limit(opts)
    if limit is None or full_length <= limit:
        return text, full_length, False
    if limit <= 0:
        return "", full_length, bool(full_length)
    if limit == 1:
        return "…", full_length, True
    return text[: limit - 1] + "…", full_length, True
