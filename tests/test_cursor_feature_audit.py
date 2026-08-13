"""Cursor feature-audit reporting and its source-access boundary.

The audit previously opened its own SQLite connection and carried fifteen
vendor SQL statements, duplicating what `cursor_source` owns. W26 moved the
queries there and left this module owning the report. These cover both sides:
the counted evidence, and the boundary that keeps them apart.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from cursor_fixtures import build_cursor_db

from codess.cursor_feature_audit import AUDIT_FORMAT, audit_cursor_features
from codess.cursor_source import read_feature_evidence


def bubble(**overrides) -> str:
    value = {"type": 1, "text": "hello", "createdAt": "2026-07-10T00:00:01Z"}
    value.update(overrides)
    return json.dumps(value)


@pytest.fixture
def cursor_db(tmp_path) -> Path:
    """A global store with tool, model, summary, and context evidence."""
    return build_cursor_db(
        tmp_path / "state.vscdb",
        bubbles=[
            ("c1", "b1", bubble(toolFormerData={
                "name": "Read", "status": "completed", "userDecision": "accepted",
            })),
            ("c1", "b2", bubble(
                toolResults=[{"ok": True}],
                modelInfo={"modelName": "claude-opus-5", "temperature": 0},
            )),
            ("c1", "b3", bubble(
                conversationSummary=json.dumps({
                    "summary": "a bounded summary",
                    "truncationLastBubbleIdInclusive": "b1",
                }),
                contextWindowStatusAtCreation={
                    "tokensUsed": 120, "tokenLimit": 200000,
                },
            )),
        ],
        records={"messageRequestContext:c1:r1": {"files": ["main.py"]}},
        headers=[("c1", "ws-1", 0)],
    )


def catalog_binding(workspace_id: str = "ws-1") -> dict:
    return {
        "projects": [{
            "project_id": "codess:project:test",
            "workspace_bindings": [
                {"source_system_id": "cursor.composer", "workspace_id": workspace_id},
            ],
        }],
    }


# --- counted evidence -------------------------------------------------------

def test_evidence_counts_each_supported_shape(cursor_db):
    evidence = read_feature_evidence(cursor_db)
    assert evidence["bubble_records"] == 3
    assert evidence["tool_former_records"] == 1
    assert evidence["tool_results_records"] == 1
    assert evidence["model_name_records"] == 1
    assert evidence["conversation_summary_records"] == 1
    assert evidence["context_window_records"] == 1
    assert evidence["request_context_records"] == 1


def test_an_empty_tool_results_array_is_not_an_outcome(tmp_path):
    """The recorded decision: an empty array is absence, not a result."""
    path = build_cursor_db(
        tmp_path / "state.vscdb",
        bubbles=[("c1", "b1", bubble(toolResults=[]))],
        headers=[],
    )
    assert read_feature_evidence(path)["tool_results_records"] == 0


def test_evidence_reports_context_window_ranges(cursor_db):
    ranges = read_feature_evidence(cursor_db)["context_window_ranges"]
    assert ranges["minimum_tokens_used"] == 120
    assert ranges["maximum_token_limit"] == 200000


def test_evidence_reports_summary_boundaries(cursor_db):
    stats = read_feature_evidence(cursor_db)["conversation_summary_stats"]
    assert stats["truncation_boundary_records"] == 1
    assert stats["summary_characters"] == len("a bounded summary")


def test_evidence_reports_tool_names_and_statuses(cursor_db):
    evidence = read_feature_evidence(cursor_db)
    assert evidence["tool_names"] == [{"tool_name": "Read", "observations": 1}]
    assert [row["source_status"] for row in evidence["tool_statuses"]] == ["completed"]


def test_evidence_reports_a_user_decision_as_permission_evidence(cursor_db):
    [decision] = read_feature_evidence(cursor_db)["tool_user_decisions"]
    assert decision["decision"] == "accepted"


def test_evidence_reports_field_shapes_without_values(cursor_db):
    """Shape queries return field names and JSON types, never content."""
    evidence = read_feature_evidence(cursor_db)
    fields = {row["field"] for row in evidence["model_field_shapes"]}
    assert fields == {"modelName", "temperature"}
    assert all(
        set(row) == {"field", "value_type", "observations"}
        for row in evidence["model_field_shapes"]
    )


def test_evidence_groups_records_by_workspace(cursor_db):
    [row] = read_feature_evidence(cursor_db)["workspace_evidence"]
    assert row["workspace_id"] == "ws-1"
    assert row["composers"] == 1


def test_evidence_ignores_records_that_are_not_valid_json(tmp_path):
    path = build_cursor_db(
        tmp_path / "state.vscdb",
        bubbles=[("c1", "b1", "{not json")],
        headers=[],
    )
    assert read_feature_evidence(path)["bubble_records"] == 0


def test_evidence_reads_a_workspace_without_wal_sidecars(cursor_db):
    """The shared connection falls back for the sidecar-free shape.

    The audit's own connection had no such fallback, so this is the defect the
    repartition removed rather than only a boundary improvement.
    """
    assert not Path(str(cursor_db) + "-wal").exists()
    assert read_feature_evidence(cursor_db)["bubble_records"] == 3


# --- report composition -----------------------------------------------------

def test_the_audit_reports_its_format_and_privacy_boundary(cursor_db):
    report = audit_cursor_features(cursor_db, catalog_binding())
    assert report["audit_format"] == AUDIT_FORMAT
    assert "were not retained" in report["privacy_boundary"]


def test_the_audit_attributes_a_workspace_to_its_project(cursor_db):
    report = audit_cursor_features(cursor_db, catalog_binding())
    [row] = report["workspace_evidence"]
    assert row["catalog_project_id"] == "codess:project:test"


def test_an_unbound_workspace_reports_no_project(cursor_db):
    """Attribution is evidence, so an unclaimed workspace is not invented."""
    report = audit_cursor_features(cursor_db, catalog_binding("other-workspace"))
    [row] = report["workspace_evidence"]
    assert row["catalog_project_id"] is None


def test_the_audit_ignores_bindings_from_another_source_system(cursor_db):
    catalog = {
        "projects": [{
            "project_id": "codess:project:test",
            "workspace_bindings": [
                {"source_system_id": "anthropic.claude-code", "workspace_id": "ws-1"},
            ],
        }],
    }
    [row] = audit_cursor_features(cursor_db, catalog)["workspace_evidence"]
    assert row["catalog_project_id"] is None


def test_the_audit_carries_the_mapping_decisions(cursor_db):
    report = audit_cursor_features(cursor_db, catalog_binding())
    assert "toolFormerData" in report["decisions"]
    assert "empty arrays" in report["decisions"]["toolResults"]


def test_the_audit_reports_the_counts_it_was_given(cursor_db):
    report = audit_cursor_features(cursor_db, catalog_binding())
    assert report["bubble_records"] == 3
    assert report["evidence"]["populated_toolFormerData_records"] == 1
    assert report["evidence"]["message_request_context_records"] == 1


def test_an_empty_catalog_still_produces_a_report(cursor_db):
    report = audit_cursor_features(cursor_db, {})
    assert report["bubble_records"] == 3


# --- module boundary --------------------------------------------------------

def test_the_audit_owns_no_vendor_storage_knowledge():
    """W26's criterion: reporting and selection are different concerns."""
    import codess.cursor_feature_audit as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    assert "sqlite3" not in source
    assert "cursorDiskKV" not in source
    assert "SELECT" not in source


def test_the_adapter_keeps_no_storage_dependency():
    """The adapter decodes records; it must not open a Cursor database."""
    import codess.adapters.cursor as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    assert "import sqlite3" not in source
    assert "connect_readonly" not in source


def test_the_cohort_cache_owns_no_vendor_sql():
    """Caching decides what to reuse, not which rows exist."""
    import codess.cursor_cohort as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    assert "cursorDiskKV" not in source
    assert "import sqlite3" not in source


@pytest.mark.parametrize(
    "module_name,concern",
    [
        ("codess.cursor_source", "Owns selection"),
        ("codess.cursor_cohort", "Owns caching"),
        ("codess.adapters.cursor", "Owns decode"),
    ],
)
def test_each_cursor_module_states_the_concern_it_owns(module_name, concern):
    """A split is only maintainable if each part says which one it is."""
    import importlib

    assert concern in (importlib.import_module(module_name).__doc__ or "")


def test_a_workspace_database_is_rejected_by_name(tmp_path):
    """The audit is scoped to the global store, so say so rather than failing.

    A workspace database holds bubbles but no Composer headers, so the
    per-workspace grouping has nothing to join against. Pointing `--db` at one
    previously produced a bare "no such table" from SQLite.
    """
    # No header table: this is a workspace database, not a global store.
    path = build_cursor_db(
        tmp_path / "state.vscdb", bubbles=[("c1", "b1", bubble())],
    )
    with pytest.raises(ValueError, match="not a Cursor global store"):
        audit_cursor_features(path, {})
