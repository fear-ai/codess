"""Independent reconciliation of typed orientation results against SQLite.

**Reads core tables directly, deliberately.** This module exists to check the
typed executor's answers against the stores, so routing its own reads through
`query_reports` would compare the query layer with itself and agree by
construction. The direct SQL *is* the second opinion.

The reads are bounded and read-only, and every identifier they name is
checked against the released DDL by `tests/test_sql_identifiers.py`.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from codess.project_catalog import catalog_readiness, durable_project_root
from codess.query_api import (
    activity_bucket,
    execute,
    make_request,
    session_structure_counts,
)
from codess.snapshot import snapshot_store_paths_from_base
from codess.store import connect

ORIENTATION_AUDIT_FORMAT = "codess.orientation-reconciliation/1"


def _day(timestamp: float) -> str:
    return datetime.fromtimestamp(
        timestamp / 1000, tz=UTC
    ).date().isoformat()


def _month(timestamp: float) -> str:
    return datetime.fromtimestamp(
        timestamp / 1000, tz=UTC
    ).strftime("%Y-%m")


def _bucket(day: str) -> dict[str, Any]:
    """One day's activity, with the per-Actor and per-relation breakdowns.

    The shared counters come from `query_api.activity_bucket`; the extras here
    are what an orientation report needs and a query result does not.
    """
    return activity_bucket(
        day,
        tool_calls_by_name=Counter(),
        actor_events=Counter(),
        actor_characters=Counter(),
        actor_sessions={},
        actor_interactions={},
        relation_events=Counter(),
        relation_characters=Counter(),
        relation_sessions={},
        relation_interactions={},
        relation_actor_events={},
        first_human_prompt_at=None,
        last_human_prompt_at=None,
        last_human_prompt_interaction=None,
    )


def _sqlite_observations(
    stores: list[dict[str, Any]],
) -> dict[str, Any]:
    """Calculate orientation observations without calling query-api helpers."""
    totals = Counter()
    vendors = Counter()
    kinds = Counter()
    relations = Counter()
    initiations = Counter()
    daily: dict[str, dict[str, Any]] = {}
    times: list[float] = []
    latest_model_by_interaction: dict[tuple[int, str], float] = {}
    month_call_interactions: dict[str, set[tuple[int, str]]] = {}
    month_result_interactions: dict[str, set[tuple[int, str]]] = {}

    for store_index, store in enumerate(stores):
        conn = store["conn"]
        session_ids = {
            row[0] for row in conn.execute(
                "SELECT DISTINCT session_id FROM events"
            )
        }
        totals["sessions"] += len(session_ids)
        structure = session_structure_counts(conn, session_ids)
        totals["interactions"] += structure["interactions"]
        totals["model_turns"] += structure["model_turns"]
        relations.update(structure["session_relations"])
        initiations.update(structure["initiation_kinds"])

        rows = conn.execute(
            """
            SELECT s.source_system_key,e.event_kind,
                   e.event_at,
                   LENGTH(COALESCE(e.content,'')),e.tool_name,e.artifact_path,
                   COALESCE(e.actor_kind,'unknown'),e.content_role,s.session_entity_id,
                   e.interaction_id,
                   COALESCE(s.session_relation_kind,'top_level'),
                   LENGTH(COALESCE(e.tool_input,'')),
                   LENGTH(COALESCE(e.tool_output,''))
            FROM events e JOIN sessions s ON s.id=e.session_id
            """
        )
        for row in rows:
            totals["events"] += 1
            totals["content_characters"] += int(row[3])
            totals["tool_events"] += int(row[4] is not None)
            totals["artifact_events"] += int(row[5] is not None)
            vendors[str(row[0])] += 1
            kinds[str(row[1] or "unknown")] += 1
            if row[2] is None:
                continue
            timestamp = float(row[2])
            times.append(timestamp)
            day = _day(timestamp)
            month = _month(timestamp)
            item = daily.setdefault(day, _bucket(day))
            item["events"] += 1
            item["content_characters"] += int(row[3])
            session_key = (store_index, str(row[8]))
            item["sessions"].add(session_key)
            interaction_key = (
                (store_index, str(row[9])) if row[9] else None
            )
            if interaction_key:
                item["interactions"].add(interaction_key)
            item["first_event_at"] = (
                timestamp if item["first_event_at"] is None
                else min(item["first_event_at"], timestamp)
            )
            item["last_event_at"] = (
                timestamp if item["last_event_at"] is None
                else max(item["last_event_at"], timestamp)
            )

            actor = str(row[6])
            item["actor_events"][actor] += 1
            item["actor_characters"][actor] += int(row[3])
            item["actor_sessions"].setdefault(actor, set()).add(session_key)
            if interaction_key:
                item["actor_interactions"].setdefault(
                    actor, set()
                ).add(interaction_key)
            relation = str(row[10])
            item["relation_events"][relation] += 1
            item["relation_characters"][relation] += int(row[3])
            item["relation_sessions"].setdefault(
                relation, set()
            ).add(session_key)
            if interaction_key:
                item["relation_interactions"].setdefault(
                    relation, set()
                ).add(interaction_key)
            item["relation_actor_events"].setdefault(
                relation, Counter()
            )[actor] += 1

            if row[1] == "tool.call":
                item["tool_calls"] += 1
                item["tool_input_characters"] += int(row[11])
                item["tool_calls_by_name"][str(row[4] or "unknown")] += 1
                if interaction_key:
                    item["tool_call_interactions"].add(interaction_key)
                    month_call_interactions.setdefault(
                        month, set()
                    ).add(interaction_key)
            elif row[1] == "tool.result":
                item["tool_results"] += 1
                item["tool_output_characters"] += int(row[12])
                if interaction_key:
                    item["tool_result_interactions"].add(interaction_key)
                    month_result_interactions.setdefault(
                        month, set()
                    ).add(interaction_key)

            if actor == "human" and (
                row[7] == "prompt" or row[1] == "message.prompt"
            ):
                item["human_prompts"] += 1
                item["human_prompt_characters"] += int(row[3])
                if interaction_key:
                    item["human_prompt_interactions"].add(interaction_key)
                item["first_human_prompt_at"] = (
                    timestamp if item["first_human_prompt_at"] is None
                    else min(item["first_human_prompt_at"], timestamp)
                )
                if (
                    item["last_human_prompt_at"] is None
                    or timestamp >= item["last_human_prompt_at"]
                ):
                    item["last_human_prompt_at"] = timestamp
                    item["last_human_prompt_interaction"] = interaction_key
            if actor == "model" and (
                row[7] == "response" or row[1] == "message.response"
            ):
                item["model_outputs"] += 1
                item["model_output_characters"] += int(row[3])
                if interaction_key:
                    latest_model_by_interaction[interaction_key] = max(
                        timestamp,
                        latest_model_by_interaction.get(
                            interaction_key, timestamp
                        ),
                    )

    times.sort()
    monthly_tools: dict[str, dict[str, int]] = {}
    expected_days: dict[str, dict[str, Any]] = {}
    core_actors = {"human", "harness", "tool", "model", "agent"}
    automated = {"harness", "model", "agent"}
    for day, item in sorted(daily.items()):
        actor_names = core_actors | set(item["actor_events"])
        actor_activity = {
            actor: {
                "events": item["actor_events"][actor],
                "content_characters": item["actor_characters"][actor],
                "sessions": len(item["actor_sessions"].get(actor, set())),
                "interactions": len(
                    item["actor_interactions"].get(actor, set())
                ),
            }
            for actor in sorted(actor_names)
        }
        response_at = latest_model_by_interaction.get(
            item["last_human_prompt_interaction"]
        )
        if (
            response_at is not None
            and item["last_human_prompt_at"] is not None
            and response_at < item["last_human_prompt_at"]
        ):
            response_at = None
        automated_sessions = set().union(*(
            item["actor_sessions"].get(actor, set())
            for actor in automated
        ))
        automated_interactions = set().union(*(
            item["actor_interactions"].get(actor, set())
            for actor in automated
        ))
        expected_days[day] = {
            "events": item["events"],
            "content_characters": item["content_characters"],
            "sessions": len(item["sessions"]),
            "interactions": len(item["interactions"]),
            "human_prompts": item["human_prompts"],
            "human_prompt_characters": item["human_prompt_characters"],
            "model_outputs": item["model_outputs"],
            "model_output_characters": item["model_output_characters"],
            "human_initiated_interactions": len(
                item["human_prompt_interactions"]
            ),
            "human_model_interactions": len(
                item["human_prompt_interactions"]
                & set(latest_model_by_interaction)
            ),
            "first_human_prompt_at": item["first_human_prompt_at"],
            "last_human_prompt_at": item["last_human_prompt_at"],
            "final_model_output_for_last_prompt_at": response_at,
            "actor_activity": actor_activity,
            "combined_harness_model_agent_activity": {
                "events": sum(
                    item["actor_events"][actor] for actor in automated
                ),
                "content_characters": sum(
                    item["actor_characters"][actor] for actor in automated
                ),
                "sessions": len(automated_sessions),
                "interactions": len(automated_interactions),
            },
            "tool_activity": {
                "calls": item["tool_calls"],
                "results": item["tool_results"],
                "input_characters": item["tool_input_characters"],
                "output_characters": item["tool_output_characters"],
                "call_interactions": len(item["tool_call_interactions"]),
                "result_interactions": len(
                    item["tool_result_interactions"]
                ),
                "calls_by_name": dict(item["tool_calls_by_name"]),
            },
            "subagent_session_activity": {
                "events": item["relation_events"]["subagent"],
                "content_characters": item[
                    "relation_characters"
                ]["subagent"],
                "sessions": len(
                    item["relation_sessions"].get("subagent", set())
                ),
                "interactions": len(
                    item["relation_interactions"].get("subagent", set())
                ),
                "actor_events": dict(
                    item["relation_actor_events"].get(
                        "subagent", Counter()
                    )
                ),
            },
        }
        month = day[:7]
        month_item = monthly_tools.setdefault(month, {
            "calls": 0,
            "results": 0,
            "input_characters": 0,
            "output_characters": 0,
            "call_interactions": 0,
            "result_interactions": 0,
        })
        month_item["calls"] += item["tool_calls"]
        month_item["results"] += item["tool_results"]
        month_item["input_characters"] += item["tool_input_characters"]
        month_item["output_characters"] += item["tool_output_characters"]
        month_item["call_interactions"] = len(
            month_call_interactions.get(month, set())
        )
        month_item["result_interactions"] = len(
            month_result_interactions.get(month, set())
        )

    return {
        "totals": dict(totals),
        "vendors_by_event": dict(sorted(vendors.items())),
        "event_kinds": dict(sorted(
            kinds.items(), key=lambda value: (-value[1], value[0])
        )),
        "sessions_by_relation": dict(sorted(relations.items())),
        "interactions_by_initiation": dict(sorted(initiations.items())),
        "events_by_utc_month": dict(sorted(Counter(
            _month(timestamp) for timestamp in times
        ).items())),
        "first_event_at": times[0] if times else None,
        "last_event_at": times[-1] if times else None,
        "daily": expected_days,
        "monthly_tools": dict(sorted(monthly_tools.items())),
    }


def _compare(
    observed: dict[str, Any], expected: dict[str, Any],
) -> list[dict[str, Any]]:
    mismatches: list[dict[str, Any]] = []

    def check(path: str, actual: Any, wanted: Any) -> None:
        if actual != wanted:
            mismatches.append({
                "field": path, "observed": actual, "sqlite": wanted,
            })

    for field, value in expected["totals"].items():
        check(field, observed.get(field, 0), value)
    for field in (
        "vendors_by_event", "event_kinds", "sessions_by_relation",
        "interactions_by_initiation", "events_by_utc_month",
        "first_event_at", "last_event_at",
    ):
        check(field, observed.get(field), expected[field])
    check(
        "tool_activity_by_utc_month",
        observed.get("tool_activity_by_utc_month"),
        expected["monthly_tools"],
    )
    observed_days = {
        item["day"]: item
        for item in observed.get("daily_exchange_activity_utc", [])
    }
    check(
        "daily_exchange_activity_total_days",
        observed.get("daily_exchange_activity_total_days"),
        len(expected["daily"]),
    )
    for day, fields in expected["daily"].items():
        actual = observed_days.get(day)
        if actual is None:
            mismatches.append({
                "field": f"daily.{day}", "observed": None,
                "sqlite": "present",
            })
            continue
        for field, value in fields.items():
            if field == "actor_activity":
                for actor, actor_values in value.items():
                    for actor_field, actor_value in actor_values.items():
                        check(
                            f"daily.{day}.actor.{actor}.{actor_field}",
                            actual[field][actor][actor_field],
                            actor_value,
                        )
            else:
                check(f"daily.{day}.{field}", actual.get(field), value)
    return mismatches


def audit_orientation(
    registry: Path,
    *,
    project_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Reconcile every selected query-ready Project against direct SQLite."""
    registry = registry.expanduser().resolve()
    selected = set(project_ids or [])
    readiness = catalog_readiness(registry)
    projects: list[dict[str, Any]] = []
    for project in readiness["projects"]:
        project_id = str(project["project_id"])
        if selected and project_id not in selected:
            continue
        snapshot_id = project.get("current_snapshot_id")
        if project.get("query_status") != "query_ready" or not snapshot_id:
            projects.append({
                "project_id": project_id,
                "project_name": project.get("logical_name"),
                "status": "skipped",
                "reason": project.get("query_status"),
            })
            continue
        base = durable_project_root(registry, project_id)
        paths = snapshot_store_paths_from_base(base, snapshot_id)
        stores = []
        try:
            for path in paths:
                stores.append({
                    "conn": connect(path, read_only=True),
                    "path": path,
                    "project_id": project_id,
                    "snapshot_id": snapshot_id,
                    "project_path": Path(
                        project.get("canonical_path") or base
                    ),
                })
            expected = _sqlite_observations(stores)
            observed = execute(
                stores,
                make_request("overview", facet_limit=1_000),
            )["summary"]
            mismatches = _compare(observed, expected)
            projects.append({
                "project_id": project_id,
                "project_name": project.get("logical_name"),
                "snapshot_id": snapshot_id,
                "status": "passed" if not mismatches else "mismatch",
                "events": observed.get("events", 0),
                "sessions": observed.get("sessions", 0),
                "days": observed.get(
                    "daily_exchange_activity_total_days", 0
                ),
                "mismatch_count": len(mismatches),
                "mismatches": mismatches[:100],
                "mismatches_truncated": len(mismatches) > 100,
            })
        finally:
            for store in stores:
                store["conn"].close()
    compared = [item for item in projects if item["status"] != "skipped"]
    failures = [item for item in compared if item["status"] != "passed"]
    return {
        "format": ORIENTATION_AUDIT_FORMAT,
        "scope": {
            "registry": str(registry),
            "project_ids": sorted(selected),
            "snapshot_rule": "current query-ready snapshot only",
        },
        "summary": {
            "projects_considered": len(projects),
            "projects_compared": len(compared),
            "projects_passed": len(compared) - len(failures),
            "projects_failed": len(failures),
        },
        "projects": projects,
    }
