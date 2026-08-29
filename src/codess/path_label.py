"""Path-string curation labeling: conservative classification of a candidate
Project location, and a stable non-identity key derived from its path.

Pure functions only -- no filesystem content is read, no I/O beyond
resolving the path string itself. review_project.py is the sole consumer.
"""

from __future__ import annotations

from pathlib import Path

from codess.config import env_path_list
from codess.hashing import codess_hash

REFERENCE_SEGMENTS: frozenset[str] = frozenset(
    env_path_list("CODESS_REFERENCE_SEGMENTS", ())
)
"""Directory names marking a tree of other people's code rather than one's own.

Empty by default and supplied by the operator, for the same reason as
`config.DEFAULT_AGGREGATORS`: a directory that holds vendored or reference
checkouts is named differently on every machine, and shipping one developer's
names would label unrelated directories as reference work elsewhere.

A path under one of these is labelled `reference`/`dormant`/`deferred`, which
is a curation starting point for review rather than a decision.
"""


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


def local_path_key(path: Path) -> str:
    """Return a reproducible key for one reviewed location on this machine.

    Names a location, not a Project. Derived from the resolved path text
    alone, so the same checkout at a different location -- or on a different
    machine, where case sensitivity and Unicode normalization of path
    components differ -- yields a different key. Review catalogs holding it
    are machine-local.

    The name says so because the previous one did not: `path_key` read as an
    identity, and the review catalog is keyed by `path` rather than by this
    value, which serves only as an alternative reference when recording a
    decision. Codess already has a portable Project identity
    (`project_catalog.ensure_project_binding`), and a candidate acquires one
    when it is approved; a second, path-derived identity would disagree with
    it the first time a directory moved.
    """
    normalized = str(path.expanduser().resolve())
    return "local:path-key:" + codess_hash(256, 128, [normalized])
