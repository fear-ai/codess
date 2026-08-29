"""Evidence-based correlation of external artifact paths to catalog Projects."""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from urllib.parse import unquote, urlparse

from codess.identity import artifact_uri_id
from codess.timeval import now_iso
from codess.wallclock import system_clock

METHOD = "catalog.longest-root-containment/1"
RELATION = "artifact_path_within_project_location"
AMBIGUOUS_RELATION = "artifact_path_candidate_project_location"


def _file_path(uri: str) -> Path | None:
    parsed = urlparse(uri)
    if parsed.scheme != "file" or parsed.netloc not in ("", "localhost"):
        return None
    return Path(os.path.realpath(os.path.expanduser(unquote(parsed.path))))


def _catalog_roots(catalog: dict) -> list[dict[str, str]]:
    roots: list[dict[str, str]] = []
    for project in catalog.get("projects", []):
        project_id = project.get("project_id")
        if not project_id:
            continue
        seen: set[str] = set()
        for location in project.get("locations", []):
            raw = location.get("path")
            if not raw:
                continue
            path = os.path.realpath(os.path.expanduser(str(raw)))
            seen.add(path)
            roots.append({
                "project_id": str(project_id), "path": path,
                "location_id": str(location.get("location_id") or ""),
                "location_state": str(location.get("state") or "unknown"),
                "evidence_kind": "catalog_location",
            })
        for raw in project.get("path_aliases", []):
            path = os.path.realpath(os.path.expanduser(str(raw)))
            if path in seen:
                continue
            roots.append({
                "project_id": str(project_id), "path": path,
                "location_id": "", "location_state": "alias",
                "evidence_kind": "catalog_path_alias",
            })
    return roots


def correlate_external_artifacts(conn: sqlite3.Connection, catalog: dict) -> dict[str, int]:
    """Refresh catalog-derived assertions without changing artifact ownership."""
    roots = _catalog_roots(catalog)
    conn.execute("DELETE FROM correlation_assertions WHERE method=?", (METHOD,))
    result = {"external_artifacts": 0, "matched": 0, "ambiguous": 0, "unmatched": 0}
    artifacts = conn.execute(
        "SELECT uri FROM artifacts WHERE relative_path IS NULL AND uri IS NOT NULL"
    ).fetchall()
    for row in artifacts:
        uri = str(row[0])
        path = _file_path(uri)
        if path is None:
            continue
        result["external_artifacts"] += 1
        candidates: list[tuple[int, dict[str, str], str]] = []
        for root in roots:
            try:
                relative = str(path.relative_to(Path(root["path"])))
            except ValueError:
                continue
            candidates.append((len(Path(root["path"]).parts), root, relative))
        if not candidates:
            result["unmatched"] += 1
            continue
        longest = max(item[0] for item in candidates)
        best_by_project: dict[str, tuple[dict[str, str], str]] = {}
        for depth, root, relative in candidates:
            if depth == longest:
                best_by_project[root["project_id"]] = (root, relative)
        ambiguous = len(best_by_project) > 1
        result["ambiguous" if ambiguous else "matched"] += 1
        relation = AMBIGUOUS_RELATION if ambiguous else RELATION
        confidence = 1.0 / len(best_by_project) if ambiguous else 1.0
        for project_id, (root, relative) in sorted(best_by_project.items()):
            evidence = {
                "artifact_uri": uri,
                "canonical_artifact_path": str(path),
                "matched_root": root["path"],
                "matched_location_id": root["location_id"] or None,
                "matched_location_state": root["location_state"],
                "evidence_kind": root["evidence_kind"],
                "relative_path": relative,
                "candidate_project_count": len(best_by_project),
                "inference_limit": "path containment only; no authorship assertion",
            }
            conn.execute(
                """
                INSERT INTO correlation_assertions(
                  subject_kind, subject_id, object_kind, object_id,
                  relation_kind, method, evidence, confidence, asserted_when)
                VALUES ('artifact', ?, 'project', ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact_uri_id(uri), project_id, relation, METHOD,
                    json.dumps(evidence, sort_keys=True, separators=(",", ":")),
                    confidence, now_iso(system_clock),
                ),
            )
    return result
