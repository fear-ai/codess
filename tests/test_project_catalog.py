"""Stable project catalog, durable snapshots, and safe relocation."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from codess.project_catalog import (
    durable_project_root,
    ensure_project_binding,
    get_project_entry,
    register_workspace_bindings,
)
from codess.raw_store import RawStore
from codess.snapshot import create_snapshot, current_store_paths
from codess.store import connect, init_db, replace_session_events, sync_project_catalog


def _captured_project(tmp_path: Path) -> tuple[Path, Path, str]:
    registry = tmp_path / "registry"
    project = tmp_path / "old"
    project.mkdir()
    binding = ensure_project_binding(registry, project)
    entry = get_project_entry(registry, binding["project_id"])
    source = tmp_path / "source.jsonl"
    source.write_text('{"record":"one"}\n', encoding="utf-8")
    store = project / ".codess/sessions_codex.db"
    init_db(store)
    conn = connect(store)
    try:
        sync_project_catalog(conn, entry)
        replace_session_events(
            conn,
            {
                "id": "s1", "source": "Codex", "type": "Code",
                "project_path": str(project), "project_id": binding["project_id"],
            },
            [{
                "session_id": "s1", "event_id": "e1",
                "event_type": "user_message", "subtype": "prompt",
                "role": "user", "content": "hello", "source_file": str(source),
            }],
            session_id="s1",
        )
        conn.commit()
    finally:
        conn.close()
    raw = RawStore(registry / "raw")
    record = raw.observe(
        source, source_system_id="openai.codex",
        storage_format="codex-jsonl", mode="capture",
    )
    create_snapshot(
        project, [store], [record], raw_store=raw,
        build_policy={"raw_mode": "capture"}, registry_root=registry,
        project_id=binding["project_id"],
    )
    return project, registry, binding["project_id"]


def test_project_id_survives_a_new_location(tmp_path):
    registry = tmp_path / "registry"
    first = tmp_path / "first"
    first.mkdir()
    initial = ensure_project_binding(registry, first)
    second = tmp_path / "second"
    second.mkdir()
    (second / ".codess").mkdir()
    (second / ".codess/project.json").write_text(
        json.dumps({
            "binding_format": "codess.project-binding/1",
            "project_id": initial["project_id"],
            "location_id": "provisional",
            "registry_root": str(registry),
        })
    )
    rebound = ensure_project_binding(registry, second)
    assert rebound["project_id"] == initial["project_id"]
    assert len(get_project_entry(registry, initial["project_id"])["locations"]) == 2


def test_ingest_discovered_workspace_binding_is_stable(tmp_path):
    registry = tmp_path / "registry"
    project = tmp_path / "project"
    project.mkdir()
    binding = ensure_project_binding(registry, project)
    register_workspace_bindings(
        registry, binding["project_id"], binding["location_id"], {"workspace-1"},
        source_project_path=str(project.resolve()),
    )
    entry = get_project_entry(registry, binding["project_id"])
    assert entry["workspace_bindings"] == [{
        "source_system_id": "cursor.composer",
        "workspace_id": "workspace-1",
        "relation_kind": "local_workspace_path_binding",
        "source_project_path": str(project.resolve()),
        "target_location_id": binding["location_id"],
        "selection_state": "approved",
    }]


def test_snapshot_is_central_and_relocation_preserves_query_access(tmp_path):
    project, registry, project_id = _captured_project(tmp_path)
    pointer = json.loads((project / ".codess/current.json").read_text())
    assert Path(pointer["path"]).is_absolute()
    assert Path(pointer["path"]).is_relative_to(durable_project_root(registry, project_id))
    assert current_store_paths(project)

    replacement = tmp_path / "new"
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
    result = subprocess.run(
        [
            sys.executable, "tools/retire_project.py", "--project", str(project),
            "--registry", str(registry), "--new-location", str(replacement),
        ],
        cwd=Path(__file__).resolve().parents[1], env=env,
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert current_store_paths(replacement)
    entry = get_project_entry(registry, project_id)
    states = {item["path"]: item["state"] for item in entry["locations"]}
    assert states[str(project.resolve())] == "retired"
    assert states[str(replacement.resolve())] == "active"
