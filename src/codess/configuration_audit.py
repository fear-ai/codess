"""Audit normalized model/runtime settings and their source provenance.
"""

from __future__ import annotations

import json
from typing import Any

AUDIT_FORMAT = "codess.configuration-audit/1"
SETTING_FIELDS = (
    "provider", "model_gradation", "model_name_exact", "model_revision",
    "reasoning_effort", "speed_tier", "service_tier", "mode",
)


def audit(
    stores: list[dict[str, Any]],
    *,
    source_system_ids: set[str] | None = None,
    session_ids: set[str] | None = None,
) -> dict[str, Any]:
    configurations = []
    source_values = 0
    invalid_source_params = 0
    turns = linked_turns = 0
    configuration_turn_occurrences = 0
    configuration_default_occurrences = 0
    turns_with_occurrence_provenance = 0
    vendor_coverage: dict[str, dict[str, int]] = {}
    for store in stores:
        conn = store["conn"]
        session_clauses: list[str] = []
        params: list[str] = []
        if source_system_ids:
            values = sorted(source_system_ids)
            session_clauses.append(
                "s.source_system_id IN (" + ",".join("?" for _ in values) + ")"
            )
            params.extend(values)
        if session_ids:
            values = sorted(session_ids)
            session_clauses.append(
                "s.id IN (" + ",".join("?" for _ in values) + ")"
            )
            params.extend(values)
        session_filter = (
            " WHERE " + " AND ".join(session_clauses)
            if session_clauses else ""
        )
        turns += conn.execute(
            "SELECT COUNT(*) FROM model_turns mt JOIN sessions s ON s.id=mt.session_id" + session_filter,
            params,
        ).fetchone()[0]
        linked_turns += conn.execute(
            "SELECT COUNT(*) FROM model_turns mt JOIN sessions s ON s.id=mt.session_id" +
            session_filter + (" AND" if session_filter else " WHERE") +
            " mt.model_param_id IS NOT NULL", params,
        ).fetchone()[0]
        configuration_params = params
        configuration_sql = """
            SELECT mc.id,mc.provider,mc.model_gradation,mc.model_name_exact,
                   mc.model_revision,mc.reasoning_effort,mc.speed_tier,
                   mc.service_tier,mc.mode,mc.source_params
            FROM model_params mc
        """
        if session_clauses:
            selected_sessions = " AND ".join(session_clauses)
            # `selected_sessions` appears once per EXISTS branch below, so its
            # bound params must repeat once per occurrence -- one params list
            # per branch keeps that pairing explicit if a branch is edited.
            turn_branch_params = list(params)
            default_branch_params = list(params)
            configuration_sql += f""" WHERE EXISTS (
                SELECT 1 FROM model_turns mt JOIN sessions s ON s.id=mt.session_id
                WHERE mt.model_param_id=mc.id AND {selected_sessions}
            ) OR EXISTS (
                SELECT 1 FROM sessions s
                WHERE s.session_model_param_id=mc.id AND {selected_sessions}
            )"""
            configuration_params = turn_branch_params + default_branch_params
        configuration_sql += " ORDER BY mc.id"
        source_and = ""
        if session_clauses:
            source_and = " AND " + " AND ".join(session_clauses)
        turn_counts = {
            row["model_param_id"]: row["occurrences"]
            for row in conn.execute(
                """
                SELECT mt.model_param_id,COUNT(*) AS occurrences
                FROM model_turns mt JOIN sessions s ON s.id=mt.session_id
                WHERE mt.model_param_id IS NOT NULL
                """ + source_and + " GROUP BY mt.model_param_id",
                params,
            )
        }
        default_counts = {
            row["session_model_param_id"]: row["occurrences"]
            for row in conn.execute(
                """
                SELECT s.session_model_param_id,COUNT(*) AS occurrences
                FROM sessions s
                WHERE s.session_model_param_id IS NOT NULL
                """ + source_and + " GROUP BY s.session_model_param_id",
                params,
            )
        }
        provenance_counts = {
            row["model_param_id"]: row["occurrences"]
            for row in conn.execute(
                """
                SELECT mt.model_param_id,
                       COUNT(DISTINCT mt.id) AS occurrences
                FROM model_turns mt JOIN sessions s ON s.id=mt.session_id
                JOIN events e ON e.model_turn_id=mt.id
                WHERE mt.model_param_id IS NOT NULL
                """ + source_and + """
                  AND json_type(
                    e.metadata,'$.configuration_provenance'
                  )='object'
                GROUP BY mt.model_param_id
                """,
                params,
            )
        }
        examples_by_configuration: dict[int, list[dict[str, Any]]] = {}
        example_rows = conn.execute(
            """
            WITH ranked_turns AS (
              SELECT mt.model_param_id,s.source_system_id,
                     s.session_entity_id AS session_entity_id,
                     mt.id AS model_turn_id,mt.sequence_no,
                     ROW_NUMBER() OVER (
                       PARTITION BY mt.model_param_id
                       ORDER BY s.source_system_id,s.session_entity_id,
                                mt.sequence_no,mt.id
                     ) AS occurrence_rank
              FROM model_turns mt
              JOIN sessions s ON s.id=mt.session_id
              WHERE mt.model_param_id IS NOT NULL
            """ + source_and + """
            ),
            ranked_events AS (
              SELECT e.id,e.model_turn_id,e.event_entity_id,
                     e.source_record_locator,e.metadata,e.source_id,
                     ROW_NUMBER() OVER (
                       PARTITION BY e.model_turn_id
                       ORDER BY
                         CASE WHEN json_type(
                           e.metadata,'$.configuration_provenance'
                         )='object' THEN 0 ELSE 1 END,
                         e.sequence_no,e.id
                     ) AS event_rank
              FROM events e
              WHERE e.model_turn_id IS NOT NULL
            )
            SELECT rt.model_param_id,rt.source_system_id,
                   rt.session_entity_id,rt.model_turn_id,
                   e.event_entity_id AS event_entity_id,e.source_record_locator,
                   e.metadata,src.source_entity_id AS source_entity_id,
                   src.source_path,src.source_revision
            FROM ranked_turns rt
            LEFT JOIN ranked_events e ON e.model_turn_id=rt.model_turn_id
                                     AND e.event_rank=1
            LEFT JOIN sources src ON src.id=e.source_id
            WHERE rt.occurrence_rank<=3
            ORDER BY rt.model_param_id,rt.occurrence_rank
            """,
            params,
        )
        for example in example_rows:
            try:
                metadata = json.loads(example["metadata"] or "{}")
            except json.JSONDecodeError:
                metadata = {}
            evidence = (
                metadata.get("configuration_provenance")
                if isinstance(metadata, dict) else None
            )
            evidence_scope = (
                metadata.get("configuration_provenance_scope")
                if isinstance(metadata, dict) else None
            )
            examples_by_configuration.setdefault(
                example["model_param_id"], []
            ).append({
                "source_system_id": example["source_system_id"],
                "session_entity_id": example["session_entity_id"],
                "model_turn_id": example["model_turn_id"],
                "event_entity_id": example["event_entity_id"],
                "source_record_locator": example["source_record_locator"],
                "source_entity_id": example["source_entity_id"],
                "source_path": example["source_path"],
                "source_revision": example["source_revision"],
                "configuration_provenance": (
                    evidence if isinstance(evidence, dict) else None
                ),
                "configuration_provenance_scope": (
                    evidence_scope
                    if isinstance(evidence_scope, dict) else None
                ),
            })
        for row in conn.execute(configuration_sql, configuration_params):
            values = {field: row[field] for field in SETTING_FIELDS}
            source_params = None
            if row["source_params"]:
                try:
                    source_params = json.loads(row["source_params"])
                    if not isinstance(source_params, dict):
                        invalid_source_params += 1
                except json.JSONDecodeError:
                    invalid_source_params += 1
            if isinstance(source_params, dict):
                source_values += len(source_params)
            turn_occurrences = int(turn_counts.get(row["id"], 0))
            default_occurrences = int(default_counts.get(row["id"], 0))
            occurrence_provenance = int(
                provenance_counts.get(row["id"], 0)
            )
            occurrence_examples = examples_by_configuration.get(
                row["id"], []
            )
            configuration_turn_occurrences += turn_occurrences
            configuration_default_occurrences += default_occurrences
            turns_with_occurrence_provenance += occurrence_provenance
            configurations.append({
                "project_path": str(store["project_path"]),
                "configuration_id": row["id"], **values,
                "source_params": source_params,
                "provenance_state": "recorded" if source_params else "normalized_only",
                "model_turn_occurrences": turn_occurrences,
                "session_default_occurrences": default_occurrences,
                "model_turns_with_configuration_provenance": (
                    occurrence_provenance
                ),
                "occurrence_provenance_state": (
                    "recorded"
                    if occurrence_provenance
                    else "representative_only"
                    if source_params and turn_occurrences
                    else "normalized_only"
                ),
                "occurrence_examples": occurrence_examples,
                "occurrence_examples_truncated": (
                    turn_occurrences > len(occurrence_examples)
                ),
            })
        coverage_sql = """
            SELECT s.source_system_id,COUNT(*) AS turns,
                   SUM(mt.model_param_id IS NOT NULL) AS configured
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
            "configuration_model_turn_occurrences": (
                configuration_turn_occurrences
            ),
            "configuration_session_default_occurrences": (
                configuration_default_occurrences
            ),
            "model_turns_with_configuration_provenance": (
                turns_with_occurrence_provenance
            ),
            "source_params_values": source_values,
            "invalid_source_params": invalid_source_params,
        },
        "vendor_coverage": dict(sorted(vendor_coverage.items())),
        "configurations": configurations,
        "limitations": [
            "source_params is representative configuration-level evidence; occurrence_examples expose bounded event/source evidence where the adapter recorded it",
            "occurrence_examples contain at most three Model Turns per normalized configuration and are not a complete event-history export",
            "availability varies by vendor and release; NULL must remain distinct from an explicit default",
        ],
    }
