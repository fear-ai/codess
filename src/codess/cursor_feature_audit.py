"""Structure-only inventory of Cursor tool and model evidence.

This module owns the audit *report*: which counted evidence is worth
reporting, how it is grouped, and the mapping decisions each observation
supports. It owns no vendor storage knowledge -- `cursor_source` opens the
database and states which rows exist, as it does for the ingest path.

Separating them removed a real defect rather than only a boundary: the
connection here was hand-rolled and weaker than the shared one, missing the
query-only pragma, the busy timeout, and the fallback for the sidecar-free
workspace shape that vendor access already handles.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from codess.cursor_source import read_feature_evidence
from codess.timeval import now_iso
from codess.wallclock import system_clock

AUDIT_FORMAT = "codess.cursor-feature-audit/1"

MAPPING_DECISIONS = {
    "toolFormerData": "supported as paired tool call/result evidence with source call and status fields",
    "toolFormerData.userDecision": "accepted/rejected is retained as explicit permission evidence; rejected maps to denied independently of status",
    "toolResults": "do not treat empty arrays as outcomes; retain existing nonempty-array compatibility mapping",
    "modelInfo.modelName": "store non-default values as vendor-reported exact model selection; default remains source metadata only",
    "conversationSummary": "retain the bounded plaintext summary as context.compact with exact truncation-boundary identifiers",
    "messageRequestContext": "retain selected-project request-context JSON as bounded context.inject events",
    "contextWindowStatusAtCreation": "retain exact token use, token limit, and percentage remaining as per-bubble observation metadata",
}
"""What each observed shape is taken to mean, recorded with the counts."""


def _workspace_project_ids(catalog: dict[str, Any]) -> dict[str, str]:
    """Map each bound Cursor workspace to the Project that claims it."""
    bindings: dict[str, str] = {}
    for project in catalog.get("projects", []):
        for binding in project.get("workspace_bindings", []):
            if (
                binding.get("source_system_id") == "cursor.composer"
                and binding.get("workspace_id")
            ):
                bindings[str(binding["workspace_id"])] = str(project["project_id"])
    return bindings


def audit_cursor_features(db_path: Path, catalog: dict[str, Any]) -> dict[str, Any]:
    """Report counted Cursor evidence and the mapping decisions it supports.

    Attributing workspaces to Projects happens here rather than in the query:
    the catalog is Codess state, not vendor storage, so joining it to counted
    evidence is composition.
    """
    evidence = read_feature_evidence(db_path)
    project_ids = _workspace_project_ids(catalog)
    workspace_evidence = [
        {**row, "catalog_project_id": project_ids.get(str(row["workspace_id"]))}
        for row in evidence["workspace_evidence"]
    ]
    return {
        "audit_format": AUDIT_FORMAT,
        "generated_at": now_iso(system_clock),
        "scope": "all valid bubbleId records in the local Cursor global store",
        "privacy_boundary": "message, argument, result, and attachment values were not retained",
        "bubble_records": evidence["bubble_records"],
        "evidence": {
            "populated_toolFormerData_records": evidence["tool_former_records"],
            "nonempty_toolResults_records": evidence["tool_results_records"],
            "modelInfo_modelName_records": evidence["model_name_records"],
            "conversation_summary_records": evidence["conversation_summary_records"],
            "context_window_status_records": evidence["context_window_records"],
            "message_request_context_records": evidence["request_context_records"],
            "message_request_context_bytes": evidence["request_context_bytes"],
        },
        "context_window_ranges": evidence["context_window_ranges"],
        "conversation_summary_stats": evidence["conversation_summary_stats"],
        "messageRequestContext_field_shapes": evidence["request_context_field_shapes"],
        "toolFormerData_field_shapes": evidence["tool_field_shapes"],
        "modelInfo_field_shapes": evidence["model_field_shapes"],
        "tool_names_top_50": evidence["tool_names"],
        "tool_statuses": evidence["tool_statuses"],
        "tool_user_decisions": evidence["tool_user_decisions"],
        "model_name_values": evidence["model_name_values"],
        "workspace_evidence": workspace_evidence,
        "decisions": MAPPING_DECISIONS,
    }
