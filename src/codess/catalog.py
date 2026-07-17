"""Review-catalog seeding and conservative project classification."""

from __future__ import annotations

import csv
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CATALOG_FORMAT = "codess.catalog/1"
REFERENCE_SEGMENTS = frozenset({"sOSS", "Claws", "ZKs", "CodingTools"})
REQUIRED_CSV_FIELDS = frozenset({"title", "directory_path", "repo_url"})


class CatalogError(ValueError):
    """Candidate input cannot be interpreted without unsafe assumptions."""


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


def project_id_for_path(path: Path) -> str:
    """Match the v2 store's stable path-derived identity without exposing it as a path."""
    normalized = str(path.expanduser().resolve())
    return "project:path:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]


def load_candidate_csv(path: Path, *, work_root: Path | None = None) -> dict[str, Any]:
    """Create a review artifact; CSV/remote claims remain observations, not truth."""
    try:
        stream = path.open(newline="", encoding="utf-8-sig")
    except OSError as exc:
        raise CatalogError(f"cannot read candidate CSV {path}: {exc}") from exc
    with stream:
        reader = csv.DictReader(stream)
        missing = REQUIRED_CSV_FIELDS - set(reader.fieldnames or ())
        if missing:
            raise CatalogError(f"candidate CSV missing columns: {', '.join(sorted(missing))}")
        projects = []
        seen: set[str] = set()
        for line, row in enumerate(reader, 2):
            raw_path = (row.get("directory_path") or "").strip()
            if not raw_path:
                raise CatalogError(f"candidate CSV line {line} has no directory_path")
            local = Path(raw_path).expanduser().resolve()
            key = str(local)
            if key in seen:
                raise CatalogError(f"candidate CSV repeats local path: {key}")
            seen.add(key)
            remote = (row.get("repo_url") or "").strip() or None
            projects.append({
                "project_id": project_id_for_path(local),
                "path": key,
                "logical_name": (row.get("title") or local.name).strip(),
                "curation": classify_project_path(local, work_root=work_root),
                "observations": {
                    "candidate_source": str(path.resolve()),
                    "local_availability": "present" if local.exists() else "missing",
                    "reported_last_commit_date": (row.get("last_commit_date") or "").strip() or None,
                    "reported_doc_and_code_file_count": _optional_int(row.get("doc_and_code_file_count"), line),
                    "notes": (row.get("notes") or "").strip() or None,
                    "remote": {
                        "configured_url": remote,
                        "status": "unchecked" if remote else "unconfigured",
                        "checked_at": None,
                        "canonical_url": None,
                    },
                    "vendors": {},
                },
                "review": {"decision": None, "notes": None, "reviewed_at": None},
            })
    projects.sort(key=lambda item: (item["curation"]["topic"], item["logical_name"].lower(), item["path"]))
    return {
        "catalog_format": CATALOG_FORMAT,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "candidate_source": str(path.resolve()),
        "projects": projects,
    }


def _optional_int(value: Any, line: int) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        result = int(text)
    except ValueError as exc:
        raise CatalogError(f"candidate CSV line {line} has invalid file count {text!r}") from exc
    if result < 0:
        raise CatalogError(f"candidate CSV line {line} has negative file count")
    return result
