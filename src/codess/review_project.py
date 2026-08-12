"""Candidate Project review: refresh the candidate list from session-walk and
bounded Git observations, seed it from an external CSV, and record decisions.
"""

from __future__ import annotations

import csv
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from codess.path_label import classify_project_path, local_path_key
from codess.fileio import check_policy_format, read_json, write_json_atomic
from codess.helpers import should_prune_directory, unsafe_traversal_root_reason
from codess.codex_source import build_session_index as build_codex_session_index
from codess.walk_sessions import walk_sessions


# The shared shape of one candidate-project list, produced by both
# load_candidate_csv (below) and refresh_candidates -- distinct from
# REVIEW_FORMAT, which identifies the outer refresh-run envelope
# (roots/diagnostics/generated_at) that only refresh_candidates emits.
CANDIDATE_LIST_FORMAT = "codess.catalog/1"
REVIEW_FORMAT = "codess.review-project/1"
DECISIONS = frozenset({"approved", "deferred", "excluded"})
POLICY_FIELDS = frozenset({
    "policy_format", "min_sessions", "consider_active_git_without_sessions",
})
REQUIRED_CSV_FIELDS = frozenset({"title", "directory_path", "repo_url"})


class CandidateReviewError(ValueError):
    """Candidate input cannot be interpreted without unsafe assumptions."""


def _parse_file_count(value: Any, line: int) -> int | None:
    """Parse the CSV `doc_and_code_file_count` column into a validated int."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        result = int(text)
    except ValueError as exc:
        raise CandidateReviewError(
            f"candidate CSV line {line} has invalid file count {text!r}"
        ) from exc
    if result < 0:
        raise CandidateReviewError(f"candidate CSV line {line} has negative file count")
    return result


def load_candidate_csv(path: Path, *, work_root: Path | None = None) -> dict[str, Any]:
    """Create a review artifact; CSV/remote claims remain observations, not truth."""
    try:
        stream = path.open(newline="", encoding="utf-8-sig")
    except OSError as exc:
        raise CandidateReviewError(f"cannot read candidate CSV {path}: {exc}") from exc
    with stream:
        reader = csv.DictReader(stream)
        missing = REQUIRED_CSV_FIELDS - set(reader.fieldnames or ())
        if missing:
            raise CandidateReviewError(
                f"candidate CSV missing columns: {', '.join(sorted(missing))}"
            )
        projects = []
        seen: set[str] = set()
        for line, row in enumerate(reader, 2):
            raw_path = (row.get("directory_path") or "").strip()
            if not raw_path:
                raise CandidateReviewError(f"candidate CSV line {line} has no directory_path")
            local = Path(raw_path).expanduser().resolve()
            key = str(local)
            if key in seen:
                raise CandidateReviewError(f"candidate CSV repeats local path: {key}")
            seen.add(key)
            remote = (row.get("repo_url") or "").strip() or None
            projects.append({
                "path_key": local_path_key(local),
                "path": key,
                "logical_name": (row.get("title") or local.name).strip(),
                "curation": classify_project_path(local, work_root=work_root),
                "observations": {
                    "candidate_source": str(path.resolve()),
                    "local_availability": "present" if local.exists() else "missing",
                    "reported_last_commit_date": (row.get("last_commit_date") or "").strip() or None,
                    "reported_doc_and_code_file_count": _parse_file_count(row.get("doc_and_code_file_count"), line),
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
        "catalog_format": CANDIDATE_LIST_FORMAT,
        "generated_at": datetime.now(UTC).isoformat(),
        "candidate_source": str(path.resolve()),
        "projects": projects,
    }


def validate_policy(policy: dict[str, Any]) -> dict[str, Any]:
    check_policy_format(
        policy,
        expected_format="codess.candidate-policy/1",
        allowed_fields=POLICY_FIELDS,
        document_name="candidate policy",
    )
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
    observed = {"observed_at": datetime.now(UTC).isoformat(), "is_repository": False}
    if not path.exists():
        observed["error"] = "path_missing"
        return observed
    try:
        root_result = _git_run(path, ["rev-parse", "--show-toplevel"])
        if root_result.returncode != 0:
            return observed
        root = Path(root_result.stdout.strip()).resolve()
        observed.update({"is_repository": True, "root": str(root)})
        git_dir_result = _git_run(root, ["rev-parse", "--absolute-git-dir"])
        common_dir_result = _git_run(root, ["rev-parse", "--git-common-dir"])

        def resolved_git_path(result: subprocess.CompletedProcess[str]) -> str | None:
            if result.returncode != 0 or not result.stdout.strip():
                return None
            value = Path(result.stdout.strip())
            return str((value if value.is_absolute() else root / value).resolve())

        git_dir = resolved_git_path(git_dir_result)
        common_dir = resolved_git_path(common_dir_result)
        branch = _git_run(root, ["branch", "--show-current"])
        observed["worktree"] = {
            "git_dir": git_dir,
            "common_git_dir": common_dir,
            "is_linked": bool(git_dir and common_dir and git_dir != common_dir),
            "branch": branch.stdout.strip() if branch.returncode == 0 else None,
        }
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
                "checked_at": datetime.now(UTC).isoformat(),
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
    existing: dict[str, Any] = {"catalog_format": CANDIDATE_LIST_FORMAT, "projects": []}
    if candidate_csv:
        existing = load_candidate_csv(candidate_csv, work_root=roots[0] if len(roots) == 1 else None)
    if catalog_path and catalog_path.exists():
        loaded = read_json(catalog_path)
        if loaded.get("catalog_format") != CANDIDATE_LIST_FORMAT:
            raise ValueError("unsupported candidate catalog format")
        for item in loaded.get("projects", []):
            if str(item.get("project_id") or "").startswith("project:path:"):
                item.pop("project_id", None)
                item["path_key"] = local_path_key(
                    Path(item["path"])
                )
        existing_by_path = {item["path"]: item for item in existing.get("projects", [])}
        for item in loaded.get("projects", []):
            prior = existing_by_path.get(item.get("path"), {})
            prior.update(item)
            existing_by_path[item["path"]] = prior
        existing["projects"] = list(existing_by_path.values())
    projects = {item["path"]: dict(item) for item in existing.get("projects", [])}
    diagnostics: dict[str, Any] = {}
    codex_index = (
        build_codex_session_index(include_record_counts=True)
        if "codex" in (vendor_filter or ["cc", "codex", "cursor"])
        else None
    )
    for root in roots:
        for row in walk_sessions(
            root, vendor_filter=vendor_filter, recent_days=recent_days,
            diagnostics=diagnostics, codex_index=codex_index,
        ):
            if row["path"] == "(global)":
                continue
            path = Path(row.get("dir_path") or (root / row["path"])).resolve()
            key = str(path)
            item = projects.get(key, {
                "path_key": local_path_key(path), "path": key,
                "logical_name": path.name,
                "curation": classify_project_path(path, work_root=root),
                "observations": {},
                "review": {"decision": None, "notes": None, "reviewed_at": None},
            })
            observations = item.setdefault("observations", {})
            observations.update({
                "local_availability": "present" if path.exists() else "missing",
                "session_count": row["sess"], "session_mb": row["mb"],
                "session_span_weeks": row["span_weeks"], "scan_observed_at": datetime.now(UTC).isoformat(),
                "vendors": row.get("source_metrics") or {
                    name: True for name in row["vendor"].split("|") if name
                },
            })
            projects[key] = item
    if discover_git:
        for path in discover_git_roots(roots, max_depth=max_depth):
            key = str(path)
            projects.setdefault(key, {
                "path_key": local_path_key(path), "path": key,
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
        "catalog_format": CANDIDATE_LIST_FORMAT,
        "review_format": REVIEW_FORMAT,
        "generated_at": datetime.now(UTC).isoformat(),
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
        if item.get("path_key") == project_ref
        or item.get("project_id") == project_ref
        or item.get("path") == str(Path(project_ref).expanduser().resolve())
    ]
    if len(matches) != 1:
        raise ValueError(f"candidate reference resolves to {len(matches)} projects")
    matches[0]["review"] = {
        "decision": decision, "reviewer": reviewer,
        "notes": notes, "reviewed_at": datetime.now(UTC).isoformat(),
    }
    write_json_atomic(catalog_path, catalog)
    return matches[0]
