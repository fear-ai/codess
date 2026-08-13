"""Shared bounds for normalized runtime-context and compaction bodies."""

from __future__ import annotations

from typing import Any

from codess.config import MAX_CONTEXT_CONTENT_CHARS


def truncate_content(text: object, limit: int) -> tuple[str, int]:
    """Bound one display string, reporting the length before truncation.

    Returns the bounded text and the *original* length, so a reader can see
    that content was longer than what is stored rather than inferring it from
    a trailing ellipsis. A non-positive limit yields the ellipsis alone when
    there was any content, which distinguishes "bounded to nothing" from
    "there was nothing".

    One definition rather than three. This body was byte-identical in all
    three adapters -- `truncate_content` in Claude, `_truncate` in Codex and
    Cursor -- so the truncation policy, the ellipsis character, and the
    boundary arithmetic were a shared decision with no owner (3.5.4). Found
    by duplicate detection rather than by reading, which is the point of
    running it.
    """
    if text is None:
        return "", 0
    value = str(text)
    length = len(value)
    if limit <= 0:
        return "\u2026" if length else "", length
    if length <= limit:
        return value, length
    return value[: limit - 1] + "\u2026", length


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
