"""Path-string curation labeling: conservative classification of a candidate
Project location, and a stable non-identity key derived from its path.

Pure functions only -- no filesystem content is read, no I/O beyond
resolving the path string itself. review_project.py is the sole consumer.
"""

from __future__ import annotations

import hashlib
from pathlib import Path


REFERENCE_SEGMENTS = frozenset({"sOSS", "Claws", "ZKs", "CodingTools"})


def classify_project_path(path: Path, *, work_root: Path | None = None) -> dict[str, str]:
    """Return conservative initial curation, suitable for explicit review."""
    resolved = path.expanduser().resolve()
    default_work = (Path.home() / "Work").resolve()
    try:
        resolved.relative_to(default_work)
        root = default_work
    except ValueError:
        root = (work_root or default_work).expanduser().resolve()
    try:
        relative = resolved.relative_to(root)
        parts = relative.parts
    except ValueError:
        parts = ()
    topic = parts[0] if parts else "unknown"
    if topic == "Github":
        return {"topic": topic, "ownership": "reference", "activity_state": "dormant", "selection_state": "needs_review"}
    if any(part in REFERENCE_SEGMENTS for part in parts):
        return {"topic": topic, "ownership": "reference", "activity_state": "dormant", "selection_state": "deferred"}
    if topic == "WP":
        return {"topic": topic, "ownership": "own", "activity_state": "dormant", "selection_state": "deferred"}
    return {"topic": topic, "ownership": "own" if parts else "unknown", "activity_state": "active", "selection_state": "candidate"}


def path_key(path: Path) -> str:
    """Return a reproducible review key, never a logical Project identity.

    Derived from the resolved path text alone, so the same checkout at a
    different location -- or on a different machine, where case sensitivity
    and Unicode normalization of path components differ -- yields a
    different key. Review catalogs holding this key are therefore
    machine-local.
    """
    normalized = str(path.expanduser().resolve())
    return "candidate:path-key:" + hashlib.sha256(
        normalized.encode("utf-8")
    ).hexdigest()[:24]
