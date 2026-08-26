"""Safe, staged refresh orchestration for explicit or annotated Projects."""

from __future__ import annotations

import csv
import json
import subprocess
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, TypedDict

from codess.child_invocation import ChildInvocation, RunPolicy
from codess.config import (
    LARGE_STORE_BYTES,
    LAST_INGEST_REPORT_FILE,
    RAW_MODES,
    SOURCE_CHOICES,
    STORE_DIR,
    canonical_raw_mode,
    raw_mode_error,
)
from codess.fileio import hash_file, read_json, write_json_atomic
from codess.hashing import codess_canonical_hash
from codess.project_annotations import build_project_annotations
from codess.project_catalog import durable_project_root, load_catalog
from codess.refresh_receipts import REFRESH_RECEIPT_FORMAT
from codess.schema_contract import contract_digest
from codess.snapshot import SnapshotError, current_snapshot, read_manifest
from codess.timeval import now_iso

REFRESH_DESIGNATORS = frozenset({
    "included",
    "core",
    "query_ready",
    "incomplete",
    "large",
    "limited",
    "suspect",
    "multi_vendor",
})
REFRESH_STAGES = frozenset({"plan", "preflight", "apply"})


def _canonical_hash(value: object) -> str:
    return codess_canonical_hash(256, 256, value)


def _load_project_references(path: Path) -> list[str]:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"Project list does not exist: {path}")
    text = path.read_text(encoding="utf-8")
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        value = None
    if isinstance(value, dict) and isinstance(value.get("projects"), list):
        references = []
        for item in value["projects"]:
            if isinstance(item, str):
                references.append(item)
            elif isinstance(item, dict):
                project_ref = (
                    item.get("project_id")
                    or item.get("name")
                    or item.get("path")
                )
                if project_ref:
                    references.append(str(project_ref))
        return references
    lines = [
        line for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not lines:
        return []
    try:
        reader = csv.DictReader(lines)
        fields = set(reader.fieldnames or [])
        supported = fields & {"project_id", "name", "path", "directory_path"}
        if supported:
            references = []
            for row in reader:
                project_ref = (
                    row.get("project_id")
                    or row.get("name")
                    or row.get("path")
                    or row.get("directory_path")
                )
                if project_ref and project_ref.strip():
                    references.append(project_ref.strip())
            return references
    except csv.Error:
        pass
    return [line.strip() for line in lines]


def _entry_paths(entry: dict[str, Any]) -> list[Path]:
    return sorted({
        Path(str(item["path"])).expanduser().resolve()
        for item in entry.get("locations", [])
        if (
            isinstance(item, dict)
            and item.get("state") == "active"
            and item.get("path")
        )
    }, key=str)


def _resolve_reference(
    project_ref: str,
    *,
    by_id: dict[str, dict[str, Any]],
    by_name: dict[str, list[dict[str, Any]]],
    by_path: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], Path | None]:
    if project_ref in by_id:
        return by_id[project_ref], None
    name_matches = by_name.get(project_ref.casefold(), [])
    if len(name_matches) == 1:
        return name_matches[0], None
    if len(name_matches) > 1:
        raise ValueError(f"Project name is ambiguous: {project_ref!r}")
    path = Path(project_ref).expanduser().resolve()
    entry = by_path.get(str(path))
    if entry is not None:
        return entry, path
    raise ValueError(
        "Project reference is not a known ID, unique name, or catalog path: "
        f"{project_ref!r}"
    )


class ResolveArgs(TypedDict):
    """The arguments `resolve_refresh_selection` takes beyond the registry.

    Splatting an untyped `dict[str, Any]` into a typed signature erases every
    argument's type at the boundary, which reported five errors per call site --
    ten in total for two calls that pass the same well-known nine values. Naming
    the shape restores the check without repeating the arguments.
    """

    project_references: list[str] | None
    project_list: Path | None
    designator: str | None
    source: str
    raw_mode: str
    baseline_selection: Path | None
    reviewed_catalog: Path | None
    large_event_count: int
    large_store_bytes: int


def _as_text(value: bytes | str | None) -> str:
    """Child-process output as text, whatever the child was opened as.

    A timeout reports `bytes` when the child was not opened in text mode and
    `str` when it was, so a caller that wants to report the output has to accept
    both. Replacement rather than strict decoding: this text goes into a receipt
    a human reads, and failing a refresh receipt over one undecodable byte in a
    subprocess's stderr would lose the report that explains the timeout.
    """
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _automatic_raw_mode(registry: Path, project_id: str) -> str:
    base = durable_project_root(registry, project_id)
    try:
        resolved = current_snapshot(base)
        if resolved is None:
            return "reference"
        snapshot, _pointer = resolved
        manifest = read_manifest(snapshot)
        # A retained manifest may record the previous spelling of the
        # least-retaining mode, so the stored value is canonicalized before it is
        # matched: a snapshot built under `none` refreshes under `observe`
        # rather than falling through to the `reference` default and silently
        # starting to record references.
        mode = canonical_raw_mode(str(manifest.get("build_policy", {}).get("raw_mode")))
        if mode in RAW_MODES:
            return mode
    except (SnapshotError, OSError, KeyError, TypeError, json.JSONDecodeError):
        pass
    return "reference"


def resolve_refresh_selection(
    registry: Path,
    *,
    project_references: list[str] | None = None,
    project_list: Path | None = None,
    designator: str | None = None,
    source: str = "all",
    raw_mode: str = "auto",
    baseline_selection: Path | None = None,
    reviewed_catalog: Path | None = None,
    large_event_count: int = 25_000,
    large_store_bytes: int = LARGE_STORE_BYTES,
) -> dict[str, Any]:
    """Resolve an immutable refresh plan without parsing vendor sources."""
    registry = registry.expanduser().resolve()
    explicit = list(project_references or [])
    if project_list is not None:
        explicit.extend(_load_project_references(project_list))
    if bool(explicit) == bool(designator):
        raise ValueError(
            "select explicit Projects or exactly one refresh designator"
        )
    if designator is not None and designator not in REFRESH_DESIGNATORS:
        raise ValueError(
            "unsupported refresh designator; expected one of: "
            + ", ".join(sorted(REFRESH_DESIGNATORS))
        )
    if source not in set(SOURCE_CHOICES):
        raise ValueError("source must be all, cc, codex, or cursor")
    # `auto` is refresh's own value: it means "keep whatever the current
    # snapshot was built under", which only a refresh can resolve.
    raw_mode = canonical_raw_mode(raw_mode)
    if raw_mode not in ("auto", *RAW_MODES):
        raise ValueError(raw_mode_error("raw_mode", raw_mode, extra=("auto",)))

    catalog_path = registry / "projects.json"
    catalog = load_catalog(registry)
    entries = [
        item for item in catalog.get("projects", [])
        if isinstance(item, dict) and item.get("project_id")
    ]
    by_id = {str(item["project_id"]): item for item in entries}
    by_name: dict[str, list[dict[str, Any]]] = {}
    by_path: dict[str, dict[str, Any]] = {}
    for entry in entries:
        by_name.setdefault(
            str(entry.get("logical_name") or "").casefold(), []
        ).append(entry)
        for path in _entry_paths(entry):
            by_path[str(path)] = entry
        for alias in entry.get("path_aliases", []):
            if alias:
                by_path.setdefault(
                    str(Path(str(alias)).expanduser().resolve()), entry
                )

    selected: list[tuple[dict[str, Any], Path | None]] = []
    selector: dict[str, Any]
    if designator is not None:
        annotations = build_project_annotations(
            registry,
            baseline_selection=baseline_selection,
            reviewed_catalog=reviewed_catalog,
            large_event_count=large_event_count,
            large_store_bytes=large_store_bytes,
        )
        ids = [
            item["project_id"] for item in annotations["projects"]
            if designator in item["labels"]
        ]
        if not ids:
            raise ValueError(
                f"refresh designator {designator!r} selects no Projects"
            )
        selected = [(by_id[project_id], None) for project_id in ids]
        selector = {
            "kind": "annotation_designator",
            "value": designator,
            "definition": annotations["definitions"][designator],
            "annotation_thresholds": annotations["thresholds"],
        }
    else:
        if not explicit:
            raise ValueError("explicit Project list is empty")
        selected = [
            _resolve_reference(
                reference, by_id=by_id, by_name=by_name, by_path=by_path
            )
            for reference in explicit
        ]
        selector = {
            "kind": "explicit_projects",
            "references": explicit,
            "project_list": (
                str(project_list.expanduser().resolve())
                if project_list is not None else None
            ),
            "project_list_sha256": (
                hash_file(project_list.expanduser().resolve())
                if project_list is not None else None
            ),
        }

    projects = []
    seen: set[str] = set()
    for entry, explicit_path in selected:
        project_id = str(entry["project_id"])
        if project_id in seen:
            continue
        seen.add(project_id)
        paths = [path for path in _entry_paths(entry) if path.is_dir()]
        if explicit_path is not None and explicit_path in paths:
            project_path = explicit_path
            location_choice = "explicit_catalog_path"
        elif len(paths) == 1:
            project_path = paths[0]
            location_choice = "sole_existing_active_location"
        elif not paths:
            raise ValueError(
                f"Project has no existing active location: {project_id}"
            )
        else:
            raise ValueError(
                f"Project has multiple active locations; select an exact path: "
                f"{entry.get('logical_name') or project_id}"
            )
        mode = (
            _automatic_raw_mode(registry, project_id)
            if raw_mode == "auto" else raw_mode
        )
        projects.append({
            "project_id": project_id,
            "name": entry.get("logical_name"),
            "path": str(project_path),
            "location_choice": location_choice,
            "source": source,
            "raw_mode": mode,
            "selection_state": (
                entry.get("selection_state")
                or (entry.get("curation") or {}).get("selection_state")
            ),
            "workspace_bindings": len(entry.get("workspace_bindings", [])),
        })
    projects.sort(key=lambda item: (str(item["name"]).casefold(), item["project_id"]))
    selection_core = [{
        key: item[key]
        for key in ("project_id", "path", "source", "raw_mode")
    } for item in projects]
    return {
        "selector": selector,
        "projects": projects,
        "selection_sha256": _canonical_hash(selection_core),
        "catalog": str(catalog_path),
        "catalog_sha256": (
            hash_file(catalog_path) if catalog_path.is_file() else None
        ),
        "contract_digest": contract_digest(),
    }


def _bounded_ingest_summary(report: object) -> dict[str, Any]:
    if not isinstance(report, dict):
        return {}
    return {
        key: report.get(key)
        for key in (
            "report_format", "status", "snapshot_id",
            "candidate_snapshot_path", "sessions", "events", "sources",
            "diagnostics",
            "cursor_cohort", "resource_summary",
        )
        if report.get(key) is not None
    }


def _result_summary(
    project: dict[str, Any],
    *,
    stdout: str | None = None,
) -> dict[str, Any]:
    if stdout:
        try:
            summary = _bounded_ingest_summary(json.loads(stdout))
        except json.JSONDecodeError:
            summary = {}
        if summary:
            return summary
    path = Path(project["path"]) / STORE_DIR / LAST_INGEST_REPORT_FILE
    try:
        return _bounded_ingest_summary(read_json(path))
    except (OSError, json.JSONDecodeError):
        return {}


def _run_project_ingest(
    project: dict[str, Any], policy: RunPolicy, *, validate: bool,
) -> dict[str, Any]:
    """Ingest one Project in a child process, timed and bounded.

    Takes the policy rather than its six fields: both call sites passed the same
    six values verbatim, differing only in `validate`, so six of the eight
    arguments carried no information at either site.
    """
    # The command and environment come from `ChildInvocation`; the call stays here
    # because refresh wraps it in timing and timeout handling that the other two
    # callers do not want.
    # The per-Project raw mode replaces the policy's, which is the one field a
    # target may override: a refresh plan records a mode per Project.
    invocation = ChildInvocation(
        policy=replace(policy, raw_mode=project["raw_mode"]),
        projects=(Path(project["path"]),),
        vendor_selector=project["source"], validate=validate,
        live_progress=False,
    )
    command = invocation.command()
    started_at = now_iso(policy.clock)
    start_tick = time.monotonic()
    try:
        result = subprocess.run(
            command, cwd=policy.repo_root, env=invocation.environment(),
            capture_output=True, text=True, timeout=policy.policy_timeout,
            check=False,
        )
        returncode = result.returncode
        stdout = result.stdout or ""
        stderr = result.stderr or ""
        error_type = None
    except subprocess.TimeoutExpired as error:
        returncode = None
        # `TimeoutExpired` carries `bytes | str | None` where `CompletedProcess`
        # carries `str`, because the timeout path does not know whether the child
        # was opened in text mode. Decoded into fresh names rather than rebound:
        # the success branch above already fixed `stdout` and `stderr` as `str`,
        # and reassigning a decoded value to them makes the declared type of each
        # depend on which branch a reader is looking at.
        stdout = _as_text(error.stdout)
        stderr = (
            f"{_as_text(error.stderr)}\n"
            f"refresh timed out after {policy.policy_timeout} seconds"
        ).strip()
        error_type = "timeout"
    except OSError as error:
        returncode = None
        stdout = ""
        stderr = f"{type(error).__name__}: {error}"
        error_type = "launch_error"
    return {
        "project_id": project["project_id"],
        "name": project.get("name"),
        "path": project["path"],
        "stage": "preflight" if validate else "apply",
        "status": "passed" if returncode == 0 else "failed",
        "returncode": returncode,
        "error_type": error_type,
        "started_at": started_at,
        "completed_at": now_iso(policy.clock),
        "elapsed_seconds": round(time.monotonic() - start_tick, 3),
        "command": command,
        "stdout_bytes": len(stdout.encode("utf-8")),
        "stdout_tail": stdout[-4_000:] if stdout else "",
        "stderr_tail": stderr[-4_000:] if stderr else "",
        "ingest_summary": _result_summary(project, stdout=stdout),
    }


def refresh_projects(
    policy: RunPolicy,
    selection: ResolveArgs,
    *,
    stage: str = "plan",
    receipt_path: Path | None = None,
) -> dict[str, Any]:
    """Plan, preflight, or apply a Project refresh with a durable receipt."""
    if stage not in REFRESH_STAGES:
        raise ValueError("stage must be plan, preflight, or apply")
    if policy.min_size < 0:
        raise ValueError("min_size must be non-negative")
    if policy.policy_timeout <= 0:
        raise ValueError("policy_timeout must be positive")
    registry = policy.registry
    # A `TypedDict` annotation, not a `TypedDict(...)` construction. Measured:
    # an annotated literal is a plain dict at 47 ns, while the constructor form
    # costs 120 ns -- so typing this bag is free at run time, and `type()` returns
    # `dict` either way. The alternative of repeating nine arguments at both call
    # sites is what the bag exists to avoid.
    plan = resolve_refresh_selection(registry, **selection)
    receipt: dict[str, Any] = {
        "receipt_format": REFRESH_RECEIPT_FORMAT,
        "created_at": now_iso(policy.clock),
        "receipt_path": (
            str(receipt_path.expanduser().resolve())
            if receipt_path is not None else None
        ),
        "status": "planned",
        "requested_stage": stage,
        "plan": plan,
        "semantics": {
            "cross_project_atomic": False,
            "preflight_gate": (
                "all selected Projects must pass before any apply"
            ),
            "apply_failure": (
                "completed Project snapshots remain published; later Projects "
                "continue and the receipt reports partial failure"
            ),
            "source_freshness": (
                "assessed by ingest source-specific change detection, not by "
                "catalog readiness or Git activity alone"
            ),
            "baseline_publication": (
                "routine refresh only; reviewed baseline freeze is separate"
            ),
        },
        "preflight": [],
        "apply": [],
    }

    def checkpoint() -> None:
        receipt["updated_at"] = now_iso(policy.clock)
        if receipt_path is not None:
            write_json_atomic(receipt_path.expanduser().resolve(), receipt)

    checkpoint()
    if stage == "plan":
        return receipt

    for project in plan["projects"]:
        result = _run_project_ingest(project, policy, validate=True)
        receipt["preflight"].append(result)
        checkpoint()
    preflight_failures = [
        item for item in receipt["preflight"]
        if item["status"] != "passed"
    ]
    if preflight_failures:
        receipt["status"] = "preflight_rejected"
        checkpoint()
        return receipt
    receipt["status"] = "preflight_accepted"
    checkpoint()
    if stage == "preflight":
        return receipt

    current = resolve_refresh_selection(registry, **selection)
    changed = []
    for key, label in (
        ("selection_sha256", "refresh selection"),
        ("catalog_sha256", "Project catalog"),
        ("contract_digest", "CoSchema package"),
    ):
        if current[key] != plan[key]:
            changed.append(label)
    if changed:
        receipt["status"] = "apply_blocked"
        receipt["error"] = (
            "preflight inputs changed before apply: " + ", ".join(changed)
        )
        receipt["current_plan_fingerprints"] = {
            key: current[key]
            for key in (
                "selection_sha256", "catalog_sha256", "contract_digest"
            )
        }
        checkpoint()
        return receipt
    for project in plan["projects"]:
        result = _run_project_ingest(project, policy, validate=False)
        receipt["apply"].append(result)
        checkpoint()
    failures = [
        item for item in receipt["apply"] if item["status"] != "passed"
    ]
    successes = len(receipt["apply"]) - len(failures)
    if not failures:
        receipt["status"] = "applied"
    elif successes:
        receipt["status"] = "partial_failure"
    else:
        receipt["status"] = "apply_failed"
    checkpoint()
    return receipt
