"""Conservative application-level failure detection for structured tool results."""

from __future__ import annotations

import json
import re
from typing import Any


_FAILURE_PREFIX = re.compile(
    r"^\s*(?:error|failed(?:\s+to)?|failure|fatal)(?:\b|:)",
    re.IGNORECASE,
)
_FAILED_STATUS = frozenset({
    "error", "failed", "failure", "fatal", "unavailable",
})
_WRAPPER_FIELDS = (
    "result", "content", "output", "message", "text",
)


def application_failure_evidence(value: Any, *, max_depth: int = 6) -> str | None:
    """Return bounded evidence for an explicit application failure.

    A transport may successfully return a JSON error body.  This helper only
    recognizes explicit status/error fields and error-prefixed wrapper text;
    it deliberately does not search arbitrary prose for the word ``error``.
    """

    def visit(item: Any, path: str, depth: int) -> str | None:
        if depth > max_depth:
            return None
        if isinstance(item, dict):
            if item.get("isError") is True:
                return f"{path}.isError=true"
            for key in ("status", "serverStatus"):
                status = item.get(key)
                if (
                    isinstance(status, str)
                    and status.strip().lower() in _FAILED_STATUS
                ):
                    return f"{path}.{key}={status.strip().lower()}"
            for key in ("error", "errors"):
                error = item.get(key)
                if error not in (None, "", [], {}):
                    return f"{path}.{key}"
            for key in _WRAPPER_FIELDS:
                if key in item:
                    found = visit(item[key], f"{path}.{key}", depth + 1)
                    if found:
                        return found
            return None
        if isinstance(item, list):
            for index, child in enumerate(item):
                found = visit(child, f"{path}[{index}]", depth + 1)
                if found:
                    return found
            return None
        if not isinstance(item, str):
            return None

        text = item.strip()
        if not text:
            return None
        if _FAILURE_PREFIX.match(text):
            prefix = text.splitlines()[0][:80]
            return f"{path}: {prefix}"

        candidates = [text]
        marker = "\nOutput:\n"
        if marker in text:
            candidates.insert(0, text.rsplit(marker, 1)[1].strip())
        for candidate in candidates:
            if not candidate or candidate[0] not in "[{":
                continue
            try:
                decoded = json.loads(candidate)
            except (json.JSONDecodeError, TypeError):
                continue
            found = visit(decoded, f"{path}.json", depth + 1)
            if found:
                return found
        return None

    return visit(value, "$", 0)
