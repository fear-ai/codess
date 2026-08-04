"""Read bounded routine-refresh receipts as conservative Project observations."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REFRESH_RECEIPT_FORMAT = "codess.refresh-receipt/1"
DEFAULT_RECEIPT_LIMIT = 1_000


def _time_value(value: object, *, fallback: float) -> tuple[float, str]:
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.timestamp(), parsed.astimezone(timezone.utc).isoformat()
        except ValueError:
            pass
    parsed = datetime.fromtimestamp(fallback, tz=timezone.utc)
    return parsed.timestamp(), parsed.isoformat()


def _normalized_status(stage: str, status: object) -> str | None:
    if status not in {"passed", "failed"}:
        return None
    if stage == "apply":
        return "refresh_applied" if status == "passed" else "refresh_failed"
    if stage == "preflight":
        return (
            "preflight_passed" if status == "passed"
            else "preflight_failed"
        )
    return None


def latest_refresh_observations(
    registry_root: Path,
    *,
    receipt_limit: int = DEFAULT_RECEIPT_LIMIT,
) -> dict[str, dict[str, Any]]:
    """Return the newest usable completed refresh result for each Project.

    Receipt discovery is intentionally bounded and operational.  It does not
    inspect vendor stores or infer whether the selected Sources remain fresh.
    """
    if receipt_limit <= 0:
        raise ValueError("receipt_limit must be positive")
    reports = registry_root.expanduser().resolve() / "reports"
    if not reports.is_dir():
        return {}
    candidates = []
    for path in reports.glob("refresh-*.json"):
        try:
            stat = path.stat()
        except OSError:
            continue
        candidates.append((stat.st_mtime, path))
    candidates.sort(key=lambda item: (item[0], str(item[1])), reverse=True)

    latest: dict[str, tuple[tuple[float, int], dict[str, Any]]] = {}
    for file_mtime, path in candidates[:receipt_limit]:
        try:
            receipt = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if (
            not isinstance(receipt, dict)
            or receipt.get("receipt_format") != REFRESH_RECEIPT_FORMAT
        ):
            continue
        projects = {
            str(item["project_id"]): item
            for item in receipt.get("plan", {}).get("projects", [])
            if isinstance(item, dict) and item.get("project_id")
        }
        for stage, stage_rank in (("preflight", 0), ("apply", 1)):
            results = receipt.get(stage)
            if not isinstance(results, list):
                continue
            for result in results:
                if not isinstance(result, dict) or not result.get("project_id"):
                    continue
                status = _normalized_status(stage, result.get("status"))
                if status is None:
                    continue
                project_id = str(result["project_id"])
                observed_timestamp, observed_at = _time_value(
                    result.get("completed_at")
                    or receipt.get("updated_at")
                    or receipt.get("created_at"),
                    fallback=file_mtime,
                )
                selection = projects.get(project_id, {})
                ingest_summary = result.get("ingest_summary")
                if not isinstance(ingest_summary, dict):
                    ingest_summary = {}
                observation = {
                    "status": status,
                    "stage": stage,
                    "result_status": result.get("status"),
                    "observed_at": observed_at,
                    "receipt": str(path.resolve()),
                    "receipt_status": receipt.get("status"),
                    "requested_stage": receipt.get("requested_stage"),
                    "source": selection.get("source"),
                    "raw_mode": selection.get("raw_mode"),
                    "returncode": result.get("returncode"),
                    "error_type": result.get("error_type"),
                    "snapshot_id": ingest_summary.get("snapshot_id"),
                }
                key = (observed_timestamp, stage_rank)
                previous = latest.get(project_id)
                if previous is None or key > previous[0]:
                    latest[project_id] = (key, observation)
    return {project_id: value[1] for project_id, value in latest.items()}
