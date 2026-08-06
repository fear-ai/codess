"""Structure-only inventory of Cursor tool and model evidence.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _rows(conn: sqlite3.Connection, query: str) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(query)]


def audit_cursor_features(db_path: Path, catalog: dict[str, Any]) -> dict[str, Any]:
    uri = db_path.expanduser().resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        base = "key LIKE 'bubbleId:%' AND json_valid(value)"
        total = conn.execute(
            f"SELECT COUNT(*) FROM cursorDiskKV WHERE {base}"
        ).fetchone()[0]
        tool_former = conn.execute(
            f"SELECT COUNT(*) FROM cursorDiskKV WHERE {base} "
            "AND json_type(value,'$.toolFormerData')='object' "
            "AND COALESCE(json_extract(value,'$.toolFormerData.name'), "
            "json_extract(value,'$.toolFormerData.toolCallId'), "
            "json_extract(value,'$.toolFormerData.status'), "
            "json_extract(value,'$.toolFormerData.rawArgs'), "
            "json_extract(value,'$.toolFormerData.params'), "
            "json_extract(value,'$.toolFormerData.result')) IS NOT NULL"
        ).fetchone()[0]
        tool_results = conn.execute(
            f"SELECT COUNT(*) FROM cursorDiskKV WHERE {base} "
            "AND json_type(value,'$.toolResults')='array' "
            "AND json_array_length(json_extract(value,'$.toolResults'))>0"
        ).fetchone()[0]
        model_rows = conn.execute(
            f"SELECT COUNT(*) FROM cursorDiskKV WHERE {base} "
            "AND json_type(value,'$.modelInfo.modelName')='text'"
        ).fetchone()[0]
        conversation_summaries = conn.execute(
            f"SELECT COUNT(*) FROM cursorDiskKV WHERE {base} "
            "AND json_type(value,'$.conversationSummary')='text'"
        ).fetchone()[0]
        conversation_summary_stats = dict(conn.execute(
            f"SELECT "
            "COALESCE(SUM(length(json_extract("
            "json_extract(value,'$.conversationSummary'),'$.summary'))),0) "
            "AS summary_characters, "
            "COALESCE(MAX(length(json_extract("
            "json_extract(value,'$.conversationSummary'),'$.summary'))),0) "
            "AS maximum_summary_characters, "
            "SUM(CASE WHEN json_type(json_extract("
            "value,'$.conversationSummary'),"
            "'$.truncationLastBubbleIdInclusive') IS NOT NULL "
            "THEN 1 ELSE 0 END) AS truncation_boundary_records, "
            "SUM(CASE WHEN json_type(json_extract("
            "value,'$.conversationSummary'),"
            "'$.clientShouldStartSendingFromInclusiveBubbleId') IS NOT NULL "
            "THEN 1 ELSE 0 END) AS restart_boundary_records "
            f"FROM cursorDiskKV WHERE {base} "
            "AND json_type(value,'$.conversationSummary')='text' "
            "AND json_valid(json_extract(value,'$.conversationSummary'))"
        ).fetchone())
        context_window_observations = conn.execute(
            f"SELECT COUNT(*) FROM cursorDiskKV WHERE {base} "
            "AND json_type(value,'$.contextWindowStatusAtCreation')='object'"
        ).fetchone()[0]
        context_window_ranges = dict(conn.execute(
            f"SELECT "
            "MIN(json_extract(value,'$.contextWindowStatusAtCreation.tokensUsed')) "
            "AS minimum_tokens_used, "
            "MAX(json_extract(value,'$.contextWindowStatusAtCreation.tokensUsed')) "
            "AS maximum_tokens_used, "
            "MIN(json_extract(value,'$.contextWindowStatusAtCreation.tokenLimit')) "
            "AS minimum_token_limit, "
            "MAX(json_extract(value,'$.contextWindowStatusAtCreation.tokenLimit')) "
            "AS maximum_token_limit "
            f"FROM cursorDiskKV WHERE {base} "
            "AND json_type(value,'$.contextWindowStatusAtCreation')='object'"
        ).fetchone())
        request_contexts = conn.execute(
            "SELECT COUNT(*) FROM cursorDiskKV "
            "WHERE key >= 'messageRequestContext:' "
            "AND key < 'messageRequestContext;' AND json_valid(value)"
        ).fetchone()[0]
        request_context_bytes = conn.execute(
            "SELECT COALESCE(SUM(length(value)),0) FROM cursorDiskKV "
            "WHERE key >= 'messageRequestContext:' "
            "AND key < 'messageRequestContext;' AND json_valid(value)"
        ).fetchone()[0]
        request_context_field_shapes = _rows(conn, """
            SELECT fields.key AS field, fields.type AS value_type,
                   COUNT(*) AS observations
            FROM cursorDiskKV kv, json_each(kv.value) fields
            WHERE kv.key >= 'messageRequestContext:'
              AND kv.key < 'messageRequestContext;'
              AND json_valid(kv.value)
            GROUP BY fields.key, fields.type
            ORDER BY fields.key, fields.type
        """)
        workspace_bindings: dict[str, str] = {}
        for project in catalog.get("projects", []):
            for binding in project.get("workspace_bindings", []):
                if binding.get("source_system_id") == "cursor.composer" and binding.get("workspace_id"):
                    workspace_bindings[str(binding["workspace_id"])] = str(project["project_id"])
        join_base = "kv.key LIKE 'bubbleId:%' AND json_valid(kv.value)"
        workspace_rows = _rows(conn, f"""
            SELECT h.workspaceId AS workspace_id,
              SUM(CASE WHEN json_type(kv.value,'$.toolFormerData')='object'
                AND COALESCE(json_extract(kv.value,'$.toolFormerData.name'),
                  json_extract(kv.value,'$.toolFormerData.toolCallId'),
                  json_extract(kv.value,'$.toolFormerData.status')) IS NOT NULL
                THEN 1 ELSE 0 END) AS tool_former_records,
              SUM(CASE WHEN json_type(kv.value,'$.toolResults')='array'
                AND json_array_length(json_extract(kv.value,'$.toolResults'))>0
                THEN 1 ELSE 0 END) AS nonempty_tool_results_records,
              SUM(CASE WHEN json_type(kv.value,'$.modelInfo.modelName')='text'
                THEN 1 ELSE 0 END) AS model_name_records,
              COUNT(DISTINCT h.composerId) AS composers
            FROM cursorDiskKV kv JOIN composerHeaders h
              ON h.composerId=substr(kv.key,10,instr(substr(kv.key,10),':')-1)
            WHERE {join_base}
            GROUP BY h.workspaceId
            HAVING tool_former_records>0 OR model_name_records>0
            ORDER BY tool_former_records DESC, model_name_records DESC
        """)
        for row in workspace_rows:
            row["catalog_project_id"] = workspace_bindings.get(str(row["workspace_id"]))
        names = _rows(conn, f"""
            SELECT json_extract(value,'$.toolFormerData.name') AS tool_name, COUNT(*) AS observations
            FROM cursorDiskKV WHERE {base}
              AND json_type(value,'$.toolFormerData')='object'
              AND json_type(value,'$.toolFormerData.name')='text'
            GROUP BY json_extract(value,'$.toolFormerData.name')
            ORDER BY observations DESC, tool_name LIMIT 50
        """)
        statuses = _rows(conn, f"""
            SELECT COALESCE(json_extract(value,'$.toolFormerData.status'),'[absent]') AS source_status,
                   COUNT(*) AS observations
            FROM cursorDiskKV WHERE {base}
              AND json_type(value,'$.toolFormerData')='object'
            GROUP BY COALESCE(json_extract(value,'$.toolFormerData.status'),'[absent]')
            ORDER BY observations DESC, source_status
        """)
        user_decisions = _rows(conn, f"""
            SELECT json_extract(value,'$.toolFormerData.userDecision') AS decision,
                   json_extract(value,'$.toolFormerData.status') AS source_status,
                   COUNT(*) AS observations
            FROM cursorDiskKV WHERE {base}
              AND json_type(value,'$.toolFormerData.userDecision')='text'
            GROUP BY decision, source_status
            ORDER BY observations DESC, decision, source_status
        """)
        models = _rows(conn, f"""
            SELECT json_extract(value,'$.modelInfo.modelName') AS model_selection, COUNT(*) AS observations
            FROM cursorDiskKV WHERE {base}
              AND json_type(value,'$.modelInfo.modelName')='text'
            GROUP BY json_extract(value,'$.modelInfo.modelName')
            ORDER BY observations DESC, model_selection
        """)
        model_field_shapes = _rows(conn, f"""
            SELECT fields.key AS field, fields.type AS value_type,
                   COUNT(*) AS observations
            FROM cursorDiskKV kv, json_each(kv.value,'$.modelInfo') fields
            WHERE {join_base} AND json_type(kv.value,'$.modelInfo')='object'
            GROUP BY fields.key, fields.type ORDER BY fields.key, fields.type
        """)
        field_shapes = _rows(conn, f"""
            SELECT fields.key AS field, fields.type AS value_type, COUNT(*) AS observations
            FROM cursorDiskKV kv, json_each(kv.value,'$.toolFormerData') fields
            WHERE {join_base} AND json_type(kv.value,'$.toolFormerData')='object'
            GROUP BY fields.key, fields.type ORDER BY fields.key, fields.type
        """)
    finally:
        conn.close()
    return {
        "audit_format": "codess.cursor-feature-audit/1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "all valid bubbleId records in the local Cursor global store",
        "privacy_boundary": "message, argument, result, and attachment values were not retained",
        "bubble_records": total,
        "evidence": {
            "populated_toolFormerData_records": tool_former,
            "nonempty_toolResults_records": tool_results,
            "modelInfo_modelName_records": model_rows,
            "conversation_summary_records": conversation_summaries,
            "context_window_status_records": context_window_observations,
            "message_request_context_records": request_contexts,
            "message_request_context_bytes": request_context_bytes,
        },
        "context_window_ranges": context_window_ranges,
        "conversation_summary_stats": conversation_summary_stats,
        "messageRequestContext_field_shapes": request_context_field_shapes,
        "toolFormerData_field_shapes": field_shapes,
        "modelInfo_field_shapes": model_field_shapes,
        "tool_names_top_50": names,
        "tool_statuses": statuses,
        "tool_user_decisions": user_decisions,
        "model_name_values": models,
        "workspace_evidence": workspace_rows,
        "decisions": {
            "toolFormerData": "supported as paired tool call/result evidence with source call and status fields",
            "toolFormerData.userDecision": "accepted/rejected is retained as explicit permission evidence; rejected maps to denied independently of status",
            "toolResults": "do not treat empty arrays as outcomes; retain existing nonempty-array compatibility mapping",
            "modelInfo.modelName": "store non-default values as vendor-reported exact model selection; default remains source metadata only",
            "conversationSummary": "retain the bounded plaintext summary as context.compact with exact truncation-boundary identifiers",
            "messageRequestContext": "retain selected-project request-context JSON as bounded context.inject events",
            "contextWindowStatusAtCreation": "retain exact token use, token limit, and percentage remaining as per-bubble observation metadata",
        },
    }
