"""Audit normalized model/runtime settings and their source provenance."""

from __future__ import annotations

import json
from typing import Any


AUDIT_FORMAT = "codess.configuration-audit/1"
SETTING_FIELDS = (
    "provider", "model_family", "model_name_exact", "model_revision",
    "reasoning_effort", "speed_tier", "service_tier", "mode",
)


def audit(
    stores: list[dict[str, Any]],
    *,
    source_system_ids: set[str] | None = None,
) -> dict[str, Any]:
    configurations = []
    source_values = 0
    invalid_source_config = 0
    turns = linked_turns = 0
    vendor_coverage: dict[str, dict[str, int]] = {}
    for store in stores:
        conn = store["conn"]
        session_filter = ""
        params: list[str] = []
        if source_system_ids:
            params = sorted(source_system_ids)
            session_filter = " WHERE s.source_system_id IN (" + ",".join("?" for _ in params) + ")"
        turns += conn.execute(
            "SELECT COUNT(*) FROM model_turns mt JOIN sessions s ON s.id=mt.session_id" + session_filter,
            params,
        ).fetchone()[0]
        linked_turns += conn.execute(
            "SELECT COUNT(*) FROM model_turns mt JOIN sessions s ON s.id=mt.session_id" +
            session_filter + (" AND" if session_filter else " WHERE") +
            " mt.model_config_id IS NOT NULL", params,
        ).fetchone()[0]
        configuration_params = params
        configuration_sql = """
            SELECT mc.id,mc.provider,mc.model_family,mc.model_name_exact,
                   mc.model_revision,mc.reasoning_effort,mc.speed_tier,
                   mc.service_tier,mc.mode,mc.source_config
            FROM model_configurations mc
        """
        if source_system_ids:
            placeholders = ",".join("?" for _ in params)
            configuration_sql += f""" WHERE EXISTS (
                SELECT 1 FROM model_turns mt JOIN sessions s ON s.id=mt.session_id
                WHERE mt.model_config_id=mc.id AND s.source_system_id IN ({placeholders})
            ) OR EXISTS (
                SELECT 1 FROM sessions s
                WHERE s.default_model_config_id=mc.id AND s.source_system_id IN ({placeholders})
            )"""
            configuration_params = params + params
        configuration_sql += " ORDER BY mc.id"
        for row in conn.execute(configuration_sql, configuration_params):
            values = {field: row[field] for field in SETTING_FIELDS}
            source_config = None
            if row["source_config"]:
                try:
                    source_config = json.loads(row["source_config"])
                    if not isinstance(source_config, dict):
                        invalid_source_config += 1
                except json.JSONDecodeError:
                    invalid_source_config += 1
            if isinstance(source_config, dict):
                source_values += len(source_config)
            configurations.append({
                "project_path": str(store["project_root"]),
                "configuration_id": row["id"], **values,
                "source_config": source_config,
                "provenance_state": "recorded" if source_config else "normalized_only",
            })
        coverage_sql = """
            SELECT s.source_system_id,COUNT(*) AS turns,
                   SUM(mt.model_config_id IS NOT NULL) AS configured
            FROM model_turns mt JOIN sessions s ON s.id=mt.session_id
        """ + session_filter + " GROUP BY s.source_system_id"
        for row in conn.execute(coverage_sql, params):
            entry = vendor_coverage.setdefault(row[0], {"turns": 0, "configured_turns": 0})
            entry["turns"] += row[1]
            entry["configured_turns"] += row[2]
    return {
        "format": AUDIT_FORMAT,
        "semantics": (
            "nullable settings are independent observations; absence is unknown, "
            "and model labels never imply effort, speed, service tier, or mode"
        ),
        "totals": {
            "configurations": len(configurations), "model_turns": turns,
            "configured_model_turns": linked_turns,
            "unconfigured_model_turns": turns - linked_turns,
            "source_config_values": source_values,
            "invalid_source_configurations": invalid_source_config,
        },
        "vendor_coverage": dict(sorted(vendor_coverage.items())),
        "configurations": configurations,
        "limitations": [
            "source_config is configuration-level evidence, not complete per-event occurrence history",
            "availability varies by vendor and release; NULL must remain distinct from an explicit default",
        ],
    }
