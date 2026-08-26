"""Candidate Project review: refresh the candidate list from session-walk and
bounded Git observations, seed it from an external CSV, and record decisions.
"""

from __future__ import annotations

import csv
import os
import subprocess
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from codess.codex_source import build_session_index as build_codex_session_index
from codess.config import (
    MAX_SCAN_DIRECTORIES,
    SCAN_TIMEOUT,
    VENDOR_KEYS,
)
from codess.fileio import check_policy_format, read_json, write_json_atomic
from codess.helpers import should_prune_directory, unsafe_traversal_root_reason
from codess.path_label import classify_project_path, local_path_key
from codess.settings import resolve
from codess.timeval import now_iso
from codess.walk_sessions import walk_sessions
from codess.wallclock import system_clock

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
        "generated_at": now_iso(system_clock),
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
    observed = {"observed_at": now_iso(system_clock), "is_repository": False}
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
                "checked_at": now_iso(system_clock),
                "status": "available" if checked.returncode == 0 else "unavailable",
                "canonical_url": configured if checked.returncode == 0 else None,
            })
    except (OSError, subprocess.SubprocessError) as exc:
        observed["error"] = str(exc)
    return observed


class ScanBudget:
    """What a traversal is allowed to spend, and what it actually spent.

    A scan of an unknown tree needs to be able to stop. Before
    this, `discover_git_roots` took a root, a depth limit, and no bound on the
    work itself: on a slow or enormous tree it ran until it finished, and the
    operator's only signal was that it had not returned. The documented
    procedure recommends a quick probe first because the full scan is unbounded,
    which is a documentation workaround for a missing control.

    **A partial result is returned and marked, not discarded.** A scan that
    examined 90% of a tree has found 90% of the Projects, and throwing that away
    to report nothing is the worse failure.

    The device count is the second half: `os.walk` crosses a filesystem boundary without
    saying so, so a network mount inside the work root turns a seconds-long scan
    into a minutes-long one with no explanation. Reporting rather than refusing,
    because the common case -- an external disk holding real Projects -- is one a
    refusal would break.
    """

    __slots__ = (
        "crossings",
        "directories",
        "max_directories",
        "scan_timeout",
        "started",
        "stopped_reason",
    )

    def __init__(
        self, *, max_directories: int = 0, scan_timeout: int = 0,
    ) -> None:
        self.max_directories = max_directories
        self.scan_timeout = scan_timeout
        self.directories = 0
        self.crossings: list[str] = []
        self.stopped_reason: str | None = None
        self.started = time.monotonic()

    def visit(self) -> bool:
        """Count one directory; return whether the traversal may continue.

        Monotonic rather than wall clock: a backward NTP step would extend the
        timeout unpredictably.
        """
        self.directories += 1
        if self.max_directories and self.directories > self.max_directories:
            self.stopped_reason = "directory_budget"
            return False
        if (
            self.scan_timeout
            and time.monotonic() - self.started > self.scan_timeout
        ):
            self.stopped_reason = "timeout"
            return False
        return True

    @property
    def partial(self) -> bool:
        return self.stopped_reason is not None

    def report(self) -> dict[str, Any]:
        """What the scan spent and whether it finished, for an operator."""
        return {
            "directories": self.directories,
            "partial": self.partial,
            "stopped_reason": self.stopped_reason,
            "max_directories": self.max_directories or None,
            "scan_timeout": self.scan_timeout or None,
            "elapsed_seconds": round(time.monotonic() - self.started, 3),
            "filesystem_crossings": list(self.crossings),
        }


def discover_git_roots(
    roots: Iterable[Path],
    *,
    max_depth: int,
    budget: ScanBudget | None = None,
    same_filesystem: bool = False,
) -> list[Path]:
    """Repository roots under `roots`, bounded by depth, count, and time.

    `budget` accumulates what the traversal spent and is the caller's to read
    afterwards; passing None means depth is the only bound, which is the
    behaviour every existing caller had. `same_filesystem` refuses to cross a
    device boundary rather than reporting it -- off by default, because a Project
    on an external disk is still a Project.
    """
    found: set[Path] = set()
    for raw_root in roots:
        root = raw_root.expanduser().resolve()
        if not root.exists() or unsafe_traversal_root_reason(root):
            continue
        try:
            root_device = root.stat().st_dev
        except OSError:
            root_device = None
        for current, directories, _ in os.walk(root):
            if budget is not None and not budget.visit():
                # Stop the whole traversal, not just this subtree: the budget is
                # a bound on the scan, and continuing into the next root would
                # spend past it.
                return sorted(found)
            path = Path(current)
            depth = len(path.relative_to(root).parts)
            if depth > max_depth:
                directories[:] = []
                continue
            if root_device is not None:
                crossed = _crossed_filesystem(path, root_device)
                if crossed is not None:
                    if budget is not None and crossed not in budget.crossings:
                        budget.crossings.append(crossed)
                    if same_filesystem:
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


def _crossed_filesystem(path: Path, root_device: int) -> str | None:
    """The path, if it sits on a different device than the work root.

    A `stat` per directory is what the traversal already pays through `os.walk`,
    so testing the device adds no syscall of its own on the common path.
    """
    try:
        if path.stat().st_dev != root_device:
            return str(path)
    except OSError:
        return None
    return None


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


@dataclass(frozen=True, slots=True)
class DiscoveryPolicy:
    """How far a candidate scan traverses, decided once before the walk.

    The eight parameters that bound a filesystem traversal rather than describe
    what is being looked for. Separate from `RunPolicy` because the subjects
    differ and so do the consumers: this bounds a walk and is read only here,
    while `RunPolicy` describes what an ingest does and is read by four modules.
    Merging them would put a `scan_timeout` that bounds a walk beside a
    `scan_timeout` that bounds a child process -- two unrelated bounds one
    field apart, which is the collision the naming rules exist to prevent.

    `max_directories` and `scan_timeout` stay `int | None` because `None`
    means "use the configured default" and 0 means "no bound"; the two are
    different answers and `settings.resolve` distinguishes them.
    """

    vendor_filter: list[str] | None = None
    recent_days: int | None = None
    include_git: bool = True
    discover_git: bool = False
    max_depth: int = 2
    check_remotes: bool = False
    max_directories: int | None = None
    scan_timeout: int | None = None
    same_filesystem: bool = False


def refresh_candidates(
    roots: list[Path],
    discovery: DiscoveryPolicy,
    *,
    candidate_csv: Path | None = None,
    catalog_path: Path | None = None,
    since: str | None = None,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Discover candidate Projects under `roots` and merge them with what exists.

    `discovery` carries the eight traversal bounds; what remains describes the
    subject rather than the walk -- which catalog to merge with, which commits to
    count, which policy to apply.
    """
    vendor_filter = discovery.vendor_filter
    recent_days = discovery.recent_days
    include_git = discovery.include_git
    discover_git = discovery.discover_git
    max_depth = discovery.max_depth
    check_remotes = discovery.check_remotes
    max_directories = discovery.max_directories
    scan_timeout = discovery.scan_timeout
    same_filesystem = discovery.same_filesystem
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
        if "codex" in (vendor_filter or VENDOR_KEYS)
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
                "session_span_weeks": row["span_weeks"], "scan_observed_at": now_iso(system_clock),
                "vendors": row.get("source_metrics") or {
                    name: True for name in row["vendor"].split("|") if name
                },
            })
            projects[key] = item
    # The precedence is `settings.resolve`'s. Passed as a namespace rather than
    # `args` because this function takes the two values directly: a library
    # caller supplies them without ever building a parser.
    supplied = SimpleNamespace(
        max_directories=max_directories, scan_timeout=scan_timeout,
    )
    budget = ScanBudget(
        max_directories=resolve(supplied, "max_directories", MAX_SCAN_DIRECTORIES),
        scan_timeout=resolve(supplied, "scan_timeout", SCAN_TIMEOUT),
    )
    if discover_git:
        for path in discover_git_roots(
            roots, max_depth=max_depth, budget=budget,
            same_filesystem=same_filesystem,
        ):
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
        "generated_at": now_iso(system_clock),
        "roots": [str(root.resolve()) for root in roots],
        "diagnostics": {key: value for key, value in diagnostics.items() if not key.startswith("_")},
        # What the traversal spent and whether it finished. Reported
        # unconditionally, so a partial scan says so rather than looking like a
        # complete one with fewer Projects in it.
        "scan": budget.report(),
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
        "notes": notes, "reviewed_at": now_iso(system_clock),
    }
    write_json_atomic(catalog_path, catalog)
    return matches[0]
