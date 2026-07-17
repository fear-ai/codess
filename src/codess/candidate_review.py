"""Candidate catalog refresh using production scan and bounded Git observations."""

from __future__ import annotations

import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from codess.catalog import CATALOG_FORMAT, classify_project_path, load_candidate_csv, project_id_for_path
from codess.fileio import read_json, write_json_atomic
from codess.helpers import should_prune_directory, unsafe_traversal_root_reason
from codess.scan import run_scan


REVIEW_FORMAT = "codess.candidate-review/1"
DECISIONS = frozenset({"approved", "deferred", "excluded"})
POLICY_FIELDS = frozenset({
    "policy_format", "min_sessions", "consider_active_git_without_sessions",
})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_policy(policy: dict[str, Any]) -> dict[str, Any]:
    if policy.get("policy_format") != "codess.candidate-policy/1":
        raise ValueError("candidate policy must declare codess.candidate-policy/1")
    unknown = sorted(set(policy) - POLICY_FIELDS)
    if unknown:
        raise ValueError("unknown candidate policy fields: " + ", ".join(unknown))
    minimum = policy.get("min_sessions", 1)
    if isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 0:
        raise ValueError("candidate policy min_sessions must be a nonnegative integer")
    active = policy.get("consider_active_git_without_sessions", True)
    if not isinstance(active, bool):
        raise ValueError(
            "candidate policy consider_active_git_without_sessions must be boolean"
        )
    return policy


def _git_run(path: Path, arguments: list[str], timeout: int = 10) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments], cwd=path, capture_output=True, text=True,
        timeout=timeout,
    )


def observe_git(
    path: Path, *, check_remote: bool = False, since: str | None = None,
) -> dict[str, Any]:
    observed = {"observed_at": _now(), "is_repository": False}
    if not path.exists():
        observed["error"] = "path_missing"
        return observed
    try:
        root_result = _git_run(path, ["rev-parse", "--show-toplevel"])
        if root_result.returncode != 0:
            return observed
        root = Path(root_result.stdout.strip()).resolve()
        observed.update({"is_repository": True, "root": str(root)})
        head = _git_run(root, ["rev-parse", "HEAD"])
        observed["head"] = head.stdout.strip() if head.returncode == 0 else None
        last = _git_run(root, ["log", "-1", "--format=%cI"])
        observed["last_commit_at"] = last.stdout.strip() if last.returncode == 0 else None
        if since:
            recent = _git_run(root, ["rev-list", "--count", f"--since={since}", "HEAD"])
            observed["commits_since"] = (
                int(recent.stdout.strip()) if recent.returncode == 0 else None
            )
            observed["since"] = since
        status = _git_run(root, ["status", "--porcelain=v1", "--untracked-files=normal"])
        observed["dirty"] = bool(status.stdout) if status.returncode == 0 else None
        remote = _git_run(root, ["remote", "get-url", "origin"])
        configured = remote.stdout.strip() if remote.returncode == 0 else None
        observed["remote"] = {
            "configured_url": configured,
            "status": "unchecked" if configured else "unconfigured",
            "checked_at": None,
            "canonical_url": None,
        }
        if check_remote and configured:
            checked = _git_run(root, ["ls-remote", "--exit-code", "origin", "HEAD"], timeout=30)
            observed["remote"].update({
                "checked_at": _now(),
                "status": "available" if checked.returncode == 0 else "unavailable",
                "canonical_url": configured if checked.returncode == 0 else None,
            })
    except (OSError, subprocess.SubprocessError) as exc:
        observed["error"] = str(exc)
    return observed


def discover_git_roots(roots: Iterable[Path], *, max_depth: int) -> list[Path]:
    found: set[Path] = set()
    for raw_root in roots:
        root = raw_root.expanduser().resolve()
        if not root.exists() or unsafe_traversal_root_reason(root):
            continue
        for current, directories, _ in os.walk(root):
            path = Path(current)
            depth = len(path.relative_to(root).parts)
            if depth > max_depth:
                directories[:] = []
                continue
            if ".git" in directories or (path / ".git").is_file():
                found.add(path.resolve())
                # A repository is one candidate boundary. Do not turn nested
                # checkouts, vendored sources, or workspaces into peers.
                directories[:] = []
                continue
            directories[:] = [
                name for name in directories
                if not should_prune_directory(name)
            ]
    return sorted(found)


def recommend(
    project: dict[str, Any], policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    policy = validate_policy(policy) if policy else {}
    reasons = []
    path = Path(project["path"])
    curation = project.get("curation", {})
    scan = project.get("observations", {}).get("vendors", {})
    vendor_count = len([
        value for value in scan.values()
        if value is True or (
            isinstance(value, dict) and int(value.get("sessions", 0) or 0) > 0
        )
    ])
    sessions = int(project.get("observations", {}).get("session_count", 0) or 0)
    size_mb = float(project.get("observations", {}).get("session_mb", 0) or 0)
    git = project.get("observations", {}).get("git", {})
    if not path.exists():
        return {"outcome": "exclude", "policy": "codess.candidate-policy/1", "reasons": ["local_path_missing"]}
    if curation.get("ownership") in {"reference", "external"}:
        reasons.append("reference_or_external")
        outcome = "defer"
    elif curation.get("activity_state") == "dormant":
        reasons.append("dormant")
        outcome = "defer"
    elif vendor_count >= 2:
        reasons.append("cross_vendor_evidence")
        outcome = "consider"
    elif sessions >= int(policy.get("min_sessions", 1)):
        reasons.append("minimum_session_evidence")
        outcome = "consider"
    elif (
        policy.get("consider_active_git_without_sessions", True)
        and git.get("is_repository") and git.get("last_commit_at")
    ):
        reasons.append("active_repository_without_session_mapping")
        outcome = "consider"
    else:
        reasons.append("insufficient_current_evidence")
        outcome = "defer"
    if size_mb >= 1:
        reasons.append("session_bytes_at_least_1_mib")
    return {"outcome": outcome, "policy": "codess.candidate-policy/1", "reasons": reasons}


def refresh_candidates(
    roots: list[Path],
    *,
    vendor_filter: list[str] | None = None,
    recent_days: int | None = None,
    candidate_csv: Path | None = None,
    catalog_path: Path | None = None,
    include_git: bool = True,
    discover_git: bool = False,
    max_depth: int = 2,
    check_remotes: bool = False,
    since: str | None = None,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    existing: dict[str, Any] = {"catalog_format": CATALOG_FORMAT, "projects": []}
    if candidate_csv:
        existing = load_candidate_csv(candidate_csv, work_root=roots[0] if len(roots) == 1 else None)
    if catalog_path and catalog_path.exists():
        loaded = read_json(catalog_path)
        if loaded.get("catalog_format") != CATALOG_FORMAT:
            raise ValueError("unsupported candidate catalog format")
        existing_by_path = {item["path"]: item for item in existing.get("projects", [])}
        for item in loaded.get("projects", []):
            prior = existing_by_path.get(item.get("path"), {})
            prior.update(item)
            existing_by_path[item["path"]] = prior
        existing["projects"] = list(existing_by_path.values())
    projects = {item["path"]: dict(item) for item in existing.get("projects", [])}
    diagnostics: dict[str, Any] = {}
    for root in roots:
        for row in run_scan(
            root, vendor_filter=vendor_filter, recent_days=recent_days,
            diagnostics=diagnostics,
        ):
            if row["path"] == "(global)":
                continue
            path = Path(row.get("dir_path") or (root / row["path"])).resolve()
            key = str(path)
            item = projects.get(key, {
                "project_id": project_id_for_path(path), "path": key,
                "logical_name": path.name,
                "curation": classify_project_path(path, work_root=root),
                "observations": {},
                "review": {"decision": None, "notes": None, "reviewed_at": None},
            })
            observations = item.setdefault("observations", {})
            observations.update({
                "local_availability": "present" if path.exists() else "missing",
                "session_count": row["sess"], "session_mb": row["mb"],
                "session_span_weeks": row["span_weeks"], "scan_observed_at": _now(),
                "vendors": row.get("source_metrics") or {
                    name: True for name in row["vendor"].split("|") if name
                },
            })
            projects[key] = item
    if discover_git:
        for path in discover_git_roots(roots, max_depth=max_depth):
            key = str(path)
            projects.setdefault(key, {
                "project_id": project_id_for_path(path), "path": key,
                "logical_name": path.name,
                "curation": classify_project_path(path, work_root=roots[0] if len(roots) == 1 else None),
                "observations": {"vendors": {}},
                "review": {"decision": None, "notes": None, "reviewed_at": None},
            })
    for item in projects.values():
        if include_git:
            item.setdefault("observations", {})["git"] = observe_git(
                Path(item["path"]), check_remote=check_remotes, since=since
            )
        item["recommendation"] = recommend(item, policy)
    return {
        "catalog_format": CATALOG_FORMAT,
        "review_format": REVIEW_FORMAT,
        "generated_at": _now(),
        "roots": [str(root.resolve()) for root in roots],
        "diagnostics": {key: value for key, value in diagnostics.items() if not key.startswith("_")},
        "projects": sorted(projects.values(), key=lambda item: item["path"]),
    }


def record_decision(
    catalog_path: Path,
    *,
    project_ref: str,
    decision: str,
    reviewer: str | None,
    notes: str | None,
) -> dict[str, Any]:
    if decision not in DECISIONS:
        raise ValueError("decision must be approved, deferred, or excluded")
    catalog = read_json(catalog_path)
    matches = [
        item for item in catalog.get("projects", [])
        if item.get("project_id") == project_ref or item.get("path") == str(Path(project_ref).expanduser().resolve())
    ]
    if len(matches) != 1:
        raise ValueError(f"candidate reference resolves to {len(matches)} projects")
    matches[0]["review"] = {
        "decision": decision, "reviewer": reviewer,
        "notes": notes, "reviewed_at": _now(),
    }
    write_json_atomic(catalog_path, catalog)
    return matches[0]
