"""Project refresh selection, staging, and partial-failure semantics."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from cli.admin_cmd import build_parser
from codess.project_catalog import (
    ensure_project_binding,
    get_project_entry,
)
from codess.raw_store import RawStore
from codess.refresh_operations import (
    _result_summary,
    _run_project_ingest,
    refresh_projects,
    resolve_refresh_selection,
)
from codess.snapshot import create_snapshot
from codess.store import (
    connect,
    init_db,
    replace_session_events,
    sync_project_catalog,
)

REPO_ROOT = Path(__file__).parents[1]


def _project(
    registry: Path, root: Path, name: str,
) -> tuple[Path, str]:
    project = root / name
    project.mkdir()
    binding = ensure_project_binding(registry, project)
    entry = get_project_entry(registry, binding["project_id"])
    source = root / f"{name}.jsonl"
    source.write_text('{"record":"one"}\n', encoding="utf-8")
    store = project / ".codess" / "sessions_codex.db"
    init_db(store)
    with connect(store) as conn:
        sync_project_catalog(conn, entry)
        replace_session_events(
            conn,
            {
                "id": f"{name}-session",
                "source": "Codex",
                "type": "Code",
                "project_path": str(project),
                "project_id": binding["project_id"],
            },
            [{
                "session_id": f"{name}-session",
                "event_id": f"{name}-event",
                "event_type": "user_message",
                "subtype": "prompt",
                "role": "user",
                "content": "hello",
                "source_file": str(source),
            }],
            session_id=f"{name}-session",
        )
        conn.commit()
    raw = RawStore(registry / "raw")
    record = raw.observe(
        source,
        source_system_id="openai.codex",
        storage_format="codex-jsonl",
        mode="capture",
    )
    create_snapshot(
        project,
        [store],
        [record],
        raw_store=raw,
        build_policy={"raw_mode": "capture"},
        store_root=registry,
        project_id=binding["project_id"],
    )
    return project, binding["project_id"]


def test_refresh_resolves_ids_names_paths_and_project_lists(tmp_path):
    registry = tmp_path / "registry"
    first, first_id = _project(registry, tmp_path, "first")
    _second, second_id = _project(registry, tmp_path, "second")
    project_list = tmp_path / "projects.json"
    project_list.write_text(json.dumps({
        "format": "codess.project-list/1",
        "projects": [
            {"project_id": first_id},
            {"name": "second"},
            {"path": str(first)},
        ],
    }))

    plan = resolve_refresh_selection(
        registry, project_list=project_list,
    )
    assert [item["project_id"] for item in plan["projects"]] == [
        first_id, second_id,
    ]
    assert all(item["raw_mode"] == "capture" for item in plan["projects"])
    assert plan["selector"]["kind"] == "explicit_projects"


def test_refresh_designator_uses_annotation_contract(tmp_path):
    registry = tmp_path / "registry"
    first, first_id = _project(registry, tmp_path, "first")
    _second, _second_id = _project(registry, tmp_path, "second")
    selection = tmp_path / "selection.json"
    selection.write_text(json.dumps({
        "selection_format": "codess.baseline-selection/1",
        "projects": [{"path": str(first)}],
    }))

    plan = resolve_refresh_selection(
        registry,
        designator="core",
        baseline_selection=selection,
    )
    assert [item["project_id"] for item in plan["projects"]] == [first_id]
    assert plan["selector"]["kind"] == "annotation_designator"
    assert plan["selector"]["value"] == "core"


def test_refresh_apply_preflights_all_then_applies_each(
    tmp_path, monkeypatch,
):
    registry = tmp_path / "registry"
    _first, _first_id = _project(registry, tmp_path, "first")
    _second, _second_id = _project(registry, tmp_path, "second")
    calls = []

    def fake_run(project, *, validate, **kwargs):
        calls.append((project["name"], validate))
        return {
            "project_id": project["project_id"],
            "name": project["name"],
            "path": project["path"],
            "stage": "preflight" if validate else "apply",
            "status": "passed",
            "returncode": 0,
        }

    monkeypatch.setattr(
        "codess.refresh_operations._run_project_ingest", fake_run
    )
    receipt_path = tmp_path / "refresh.json"
    receipt = refresh_projects(
        registry,
        repo_root=REPO_ROOT,
        stage="apply",
        designator="included",
        receipt_path=receipt_path,
    )
    assert receipt["status"] == "applied"
    assert calls == [
        ("first", True), ("second", True),
        ("first", False), ("second", False),
    ]
    assert json.loads(receipt_path.read_text())["status"] == "applied"
    assert receipt["semantics"]["cross_project_atomic"] is False


def test_refresh_rejects_whole_apply_when_one_preflight_fails(
    tmp_path, monkeypatch,
):
    registry = tmp_path / "registry"
    _first, _first_id = _project(registry, tmp_path, "first")
    _second, _second_id = _project(registry, tmp_path, "second")
    calls = []

    def fake_run(project, *, validate, **kwargs):
        calls.append((project["name"], validate))
        failed = project["name"] == "second"
        return {
            "project_id": project["project_id"],
            "name": project["name"],
            "path": project["path"],
            "stage": "preflight" if validate else "apply",
            "status": "failed" if failed else "passed",
            "returncode": 1 if failed else 0,
        }

    monkeypatch.setattr(
        "codess.refresh_operations._run_project_ingest", fake_run
    )
    receipt = refresh_projects(
        registry,
        repo_root=REPO_ROOT,
        stage="apply",
        designator="included",
    )
    assert receipt["status"] == "preflight_rejected"
    assert calls == [("first", True), ("second", True)]
    assert receipt["apply"] == []


def test_refresh_cli_accepts_distinct_selection_forms():
    parser = build_parser()
    named = parser.parse_args([
        "refresh", "--project", "first", "--project", "second",
    ])
    assert named.projects == ["first", "second"]
    assert named.stage == "plan"
    cohort = parser.parse_args([
        "refresh", "--designator", "query_ready", "--stage", "apply",
    ])
    assert cohort.designator == "query_ready"
    assert cohort.stage == "apply"


def test_refresh_records_timeout_as_project_failure(
    tmp_path, monkeypatch,
):
    def timed_out(*args, **kwargs):
        raise subprocess.TimeoutExpired(
            cmd=args[0], timeout=kwargs["timeout"], output=b"partial"
        )

    monkeypatch.setattr("codess.refresh_operations.subprocess.run", timed_out)
    result = _run_project_ingest(
        {
            "project_id": "project-1",
            "name": "first",
            "path": str(tmp_path),
            "source": "all",
            "raw_mode": "reference",
        },
        validate=True,
        registry=tmp_path / "registry",
        repo_root=REPO_ROOT,
        min_size=0,
        force=False,
        resource_policy=None,
        timeout_seconds=1,
    )
    assert result["status"] == "failed"
    assert result["error_type"] == "timeout"
    assert result["returncode"] is None


def test_refresh_retains_bounded_preflight_measurements(tmp_path):
    summary = _result_summary(
        {"path": str(tmp_path)},
        stdout=json.dumps({
            "report_format": "codess.ingest-preflight/1",
            "status": "accepted",
            "sessions": 2,
            "events": 3,
            "resource_summary": {
                "measurement_format": "codess.ingest-resource-summary/1",
                "selected_input_bytes": 10,
            },
            "progress_events": [{"content": "not copied into receipt"}],
        }),
    )
    assert summary == {
        "report_format": "codess.ingest-preflight/1",
        "status": "accepted",
        "sessions": 2,
        "events": 3,
        "resource_summary": {
            "measurement_format": "codess.ingest-resource-summary/1",
            "selected_input_bytes": 10,
        },
    }
