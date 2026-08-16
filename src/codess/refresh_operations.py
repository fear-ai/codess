"""Safe, staged refresh orchestration for explicit or annotated Projects."""

from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from codess.config import (
    LARGE_STORE_BYTES,
    LAST_INGEST_REPORT_FILE,
    RAW_MODES,
    STORE_DIR,
    raw_mode_error,
)
from codess.fileio import hash_file, read_json, write_json_atomic
from codess.hashing import codess_canonical_hash
from codess.project_annotations import build_project_annotations
from codess.project_catalog import durable_project_root, load_catalog
from codess.refresh_receipts import REFRESH_RECEIPT_FORMAT
from codess.schema_contract import contract_digest
from codess.snapshot import SnapshotError, current_snapshot, read_manifest

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
                reference = (
                    item.get("project_id")
                    or item.get("name")
                    or item.get("path")
                )
                if reference:
                    references.append(str(reference))
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
                reference = (
                    row.get("project_id")
                    or row.get("name")
                    or row.get("path")
                    or row.get("directory_path")
                )
                if reference and reference.strip():
                    references.append(reference.strip())
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
    reference: str,
    *,
    by_id: dict[str, dict[str, Any]],
    by_name: dict[str, list[dict[str, Any]]],
    by_path: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], Path | None]:
    if reference in by_id:
        return by_id[reference], None
    name_matches = by_name.get(reference.casefold(), [])
    if len(name_matches) == 1:
        return name_matches[0], None
    if len(name_matches) > 1:
        raise ValueError(f"Project name is ambiguous: {reference!r}")
    path = Path(reference).expanduser().resolve()
    entry = by_path.get(str(path))
    if entry is not None:
        return entry, path
    raise ValueError(
        "Project reference is not a known ID, unique name, or catalog path: "
        f"{reference!r}"
    )


def _automatic_raw_mode(registry: Path, project_id: str) -> str:
    base = durable_project_root(registry, project_id)
    try:
        resolved = current_snapshot(base)
        if resolved is None:
            return "reference"
        snapshot, _pointer = resolved
        manifest = read_manifest(snapshot)
        mode = manifest.get("build_policy", {}).get("raw_mode")
        if mode in RAW_MODES:
            return str(mode)
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
    if source not in {"all", "cc", "codex", "cursor"}:
        raise ValueError("source must be all, cc, codex, or cursor")
    # `auto` is refresh's own value: it means "keep whatever the current
    # snapshot was built under", which only a refresh can resolve.
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
    project: dict[str, Any],
    *,
    validate: bool,
    registry: Path,
    repo_root: Path,
    min_size: int,
    force: bool,
    resource_policy: Path | None,
    timeout_seconds: int,
) -> dict[str, Any]:
    command = [
        sys.executable, "-m", "main", "ingest",
        "--dir", project["path"],
        "--source", project["source"],
        "--raw-mode", project["raw_mode"],
        "--registry", str(registry),
        "--min-size", str(min_size),
        "--no-progress",
    ]
    if validate:
        command.append("--validate")
    if force:
        command.append("--force")
    if resource_policy is not None:
        command.extend(["--resource-policy", str(resource_policy)])
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo_root / "src")
    started_at = datetime.now(UTC).isoformat()
    start_tick = time.monotonic()
    try:
        result = subprocess.run(
            command, cwd=repo_root, env=env, capture_output=True,
            text=True, timeout=timeout_seconds,
        )
        returncode = result.returncode
        stdout = result.stdout or ""
        stderr = result.stderr or ""
        error_type = None
    except subprocess.TimeoutExpired as error:
        returncode = None
        stdout = error.stdout or ""
        stderr = error.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        stderr = (
            f"{stderr}\nrefresh timed out after {timeout_seconds} seconds"
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
        "completed_at": datetime.now(UTC).isoformat(),
        "elapsed_seconds": round(time.monotonic() - start_tick, 3),
        "command": command,
        "stdout_bytes": len(stdout.encode("utf-8")),
        "stdout_tail": stdout[-4_000:] if stdout else "",
        "stderr_tail": stderr[-4_000:] if stderr else "",
        "ingest_summary": _result_summary(project, stdout=stdout),
    }


def refresh_projects(
    registry: Path,
    *,
    repo_root: Path,
    stage: str = "plan",
    project_references: list[str] | None = None,
    project_list: Path | None = None,
    designator: str | None = None,
    source: str = "all",
    raw_mode: str = "auto",
    baseline_selection: Path | None = None,
    reviewed_catalog: Path | None = None,
    large_event_count: int = 25_000,
    large_store_bytes: int = LARGE_STORE_BYTES,
    min_size: int = 0,
    force: bool = False,
    resource_policy: Path | None = None,
    timeout_seconds: int = 3_600,
    receipt_path: Path | None = None,
) -> dict[str, Any]:
    """Plan, preflight, or apply a Project refresh with a durable receipt."""
    if stage not in REFRESH_STAGES:
        raise ValueError("stage must be plan, preflight, or apply")
    if min_size < 0:
        raise ValueError("min_size must be non-negative")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    registry = registry.expanduser().resolve()
    repo_root = repo_root.resolve()
    resolve_args = {
        "project_references": project_references,
        "project_list": project_list,
        "designator": designator,
        "source": source,
        "raw_mode": raw_mode,
        "baseline_selection": baseline_selection,
        "reviewed_catalog": reviewed_catalog,
        "large_event_count": large_event_count,
        "large_store_bytes": large_store_bytes,
    }
    plan = resolve_refresh_selection(registry, **resolve_args)
    receipt: dict[str, Any] = {
        "receipt_format": REFRESH_RECEIPT_FORMAT,
        "created_at": datetime.now(UTC).isoformat(),
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
        receipt["updated_at"] = datetime.now(UTC).isoformat()
        if receipt_path is not None:
            write_json_atomic(receipt_path.expanduser().resolve(), receipt)

    checkpoint()
    if stage == "plan":
        return receipt

    for project in plan["projects"]:
        result = _run_project_ingest(
            project, validate=True, registry=registry,
            repo_root=repo_root, min_size=min_size, force=force,
            resource_policy=resource_policy,
            timeout_seconds=timeout_seconds,
        )
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

    current = resolve_refresh_selection(registry, **resolve_args)
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
        result = _run_project_ingest(
            project, validate=False, registry=registry,
            repo_root=repo_root, min_size=min_size, force=force,
            resource_policy=resource_policy,
            timeout_seconds=timeout_seconds,
        )
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
