"""Stable project catalog, durable snapshots, and safe relocation."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from codess.project_annotations import build_project_annotations
from codess.project_catalog import (
    add_project_location,
    catalog_readiness,
    durable_project_root,
    ensure_project_binding,
    get_project_entry,
    load_project_set,
    register_workspace_bindings,
    resolve_project_query_scopes,
    set_project_selection_state,
)
from codess.config import REGISTRY
from codess.fileio import hash_file
from codess.raw_store import RawStore
from codess.session_names import set_session_name
from codess.snapshot import create_snapshot, current_stores
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


def test_project_annotations_combine_curation_readiness_and_size(tmp_path):
    project, registry, project_id = _captured_project(tmp_path)
    selection = tmp_path / "selection.json"
    selection.write_text(json.dumps({
        "selection_format": "codess.baseline-selection/1",
        "projects": [{"path": str(project)}],
    }))
    reviewed = tmp_path / "reviewed.json"
    reviewed.write_text(json.dumps({
        "catalog_format": "codess.reviewed-baselines/1",
        "projects": [{"project_id": project_id, "path": str(project)}],
    }))

    report = build_project_annotations(
        registry,
        baseline_selection=selection,
        reviewed_catalog=reviewed,
        large_event_count=1,
        large_store_bytes=1024**3,
    )
    item = report["projects"][0]
    assert item["labels"] == [
        "included", "core", "query_ready", "large",
    ]
    assert item["events"] == 1
    assert item["source_systems"] == {"openai.codex": 1}
    assert report["definitions"]["core"].startswith(
        "member of the reviewed compatibility"
    )


def test_project_annotations_reserve_suspect_for_direct_evidence(tmp_path):
    _project, registry, project_id = _captured_project(tmp_path)
    set_project_selection_state(
        registry, project_id, "needs_review", note="inspect identity"
    )

    report = build_project_annotations(registry)
    item = report["projects"][0]
    assert "not_selected" in item["labels"]
    assert "suspect" in item["labels"]
    assert "included" not in item["labels"]


def test_personal_registry_rejects_ephemeral_project_location(tmp_path):
    # REGISTRY is resolved once at import time from CODESS_REGISTRY / the
    # real home directory, so this check (identity against the personal
    # registry) is exercised by passing REGISTRY itself, not by faking
    # Path.home() after codess.config has already computed it.
    project = tmp_path / "temporary-project"
    project.mkdir()

    with pytest.raises(ValueError, match="ephemeral system location"):
        ensure_project_binding(REGISTRY, project)


def test_project_id_survives_a_new_location(tmp_path):
    registry = tmp_path / "registry"
    first = tmp_path / "first"
    first.mkdir()
    initial = ensure_project_binding(registry, first)
    uuid.UUID(initial["project_id"].removeprefix("codess:project:"))
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
        "path_obsolete": False,
        "target_location_id": binding["location_id"],
        "selection_state": "approved",
    }]


def test_store_catalog_sync_does_not_rewrite_identical_projection(tmp_path):
    registry = tmp_path / "registry"
    project = tmp_path / "project"
    project.mkdir()
    binding = ensure_project_binding(registry, project)
    entry = get_project_entry(registry, binding["project_id"])
    store = project / ".codess" / "sessions_codex.db"
    init_db(store)

    with connect(store) as conn:
        assert sync_project_catalog(conn, entry)
        conn.commit()
        assert not sync_project_catalog(conn, entry)


def test_vendor_obsolete_path_is_marked_without_replacing_project_root(
    tmp_path,
):
    registry = tmp_path / "registry"
    project = tmp_path / "current" / "project"
    project.mkdir(parents=True)
    binding = ensure_project_binding(registry, project)
    entry = get_project_entry(registry, binding["project_id"])
    store = project / ".codess" / "sessions_codex.db"
    init_db(store)
    obsolete = tmp_path / "old" / "project"

    with connect(store) as conn:
        sync_project_catalog(conn, entry)
        replace_session_events(
            conn,
            {
                "id": "s1",
                "source": "Codex",
                "project_id": binding["project_id"],
                "project_path": str(obsolete),
                "source_cwd": str(obsolete),
            },
            [],
            session_id="s1",
        )
        root_path = conn.execute(
            "SELECT root_path FROM projects WHERE id=?",
            (binding["project_id"],),
        ).fetchone()[0]
        path_obsolete = conn.execute(
            "SELECT path_obsolete FROM sessions WHERE id='s1'"
        ).fetchone()[0]

    assert root_path == str(project.resolve())
    assert path_obsolete == 1


def test_vendor_path_under_another_active_location_is_not_obsolete(tmp_path):
    registry = tmp_path / "registry"
    project = tmp_path / "primary" / "project"
    worktree = tmp_path / "worktree" / "project"
    project.mkdir(parents=True)
    worktree.mkdir(parents=True)
    binding = ensure_project_binding(registry, project)
    add_project_location(registry, binding["project_id"], worktree)
    entry = get_project_entry(registry, binding["project_id"])
    store = project / ".codess" / "sessions_codex.db"
    init_db(store)

    with connect(store) as conn:
        sync_project_catalog(conn, entry)
        replace_session_events(
            conn,
            {
                "id": "s1",
                "source": "Codex",
                "project_id": binding["project_id"],
                "project_path": str(project),
                "source_cwd": str(worktree),
            },
            [],
            session_id="s1",
        )
        path_obsolete = conn.execute(
            "SELECT path_obsolete FROM sessions WHERE id='s1'"
        ).fetchone()[0]

    assert path_obsolete == 0


def test_snapshot_is_central_and_relocation_preserves_query_access(tmp_path):
    project, registry, project_id = _captured_project(tmp_path)
    pointer = json.loads((project / ".codess/current.json").read_text())
    assert Path(pointer["path"]).is_absolute()
    assert Path(pointer["path"]).is_relative_to(durable_project_root(registry, project_id))
    assert current_stores(project)

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
    assert current_stores(replacement)
    entry = get_project_entry(registry, project_id)
    states = {item["path"]: item["state"] for item in entry["locations"]}
    obsolete = {
        item["path"]: item["path_obsolete"] for item in entry["locations"]
    }
    assert states[str(project.resolve())] == "retired"
    assert states[str(replacement.resolve())] == "active"
    assert obsolete[str(project.resolve())] is True
    assert obsolete[str(replacement.resolve())] is False


def test_exact_project_id_resolves_central_snapshot_without_mutation(tmp_path):
    project, registry, project_id = _captured_project(tmp_path)
    before = (registry / "projects.json").read_bytes()

    scopes = resolve_project_query_scopes(registry, [project_id, project_id])

    assert len(scopes) == 1
    assert scopes[0]["project_id"] == project_id
    assert scopes[0]["project_path"] == project.resolve()
    assert scopes[0]["snapshot_base"] == durable_project_root(
        registry, project_id
    )
    assert scopes[0]["snapshot_id"]
    assert scopes[0]["selection_kind"] == "project_ids"
    assert len(scopes[0]["resolved_selection_sha256"]) == 64
    assert (registry / "projects.json").read_bytes() == before

    result = subprocess.run(
        [
            sys.executable, "-m", "main", "query", "sessions",
            "--project-id", project_id, "--registry", str(registry),
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    document = json.loads(result.stdout)
    assert document["request"]["project_ids"] == [project_id]
    assert document["request"]["project_snapshots"] == [{
        "project_id": project_id,
        "snapshot_id": scopes[0]["snapshot_id"],
    }]
    assert document["rows"][0]["project_id"] == project_id


def test_saved_project_set_and_all_current_resolve_exact_snapshots(tmp_path):
    _project, registry, project_id = _captured_project(tmp_path)
    current = resolve_project_query_scopes(registry, [project_id])[0]
    saved_path = tmp_path / "selection.json"
    saved_path.write_text(json.dumps({
        "format": "codess.project-set/1",
        "name": "reviewed",
        "projects": [{
            "project_id": project_id,
            "snapshot_id": current["snapshot_id"],
        }],
    }), encoding="utf-8")

    loaded = load_project_set(saved_path)
    assert len(loaded["selection_sha256"]) == 64
    saved = resolve_project_query_scopes(
        registry, project_set=saved_path
    )
    assert saved[0]["selection_kind"] == "project_set"
    assert saved[0]["snapshot_id"] == current["snapshot_id"]

    all_current = resolve_project_query_scopes(registry, all_current=True)
    assert [
        (item["project_id"], item["snapshot_id"])
        for item in all_current
    ] == [(project_id, current["snapshot_id"])]

    for selector in (
        ["--project-set", str(saved_path)],
        ["--all-current"],
    ):
        result = subprocess.run(
            [
                sys.executable, "-m", "main", "query", "sessions",
                *selector, "--registry", str(registry),
            ],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        document = json.loads(result.stdout)
        assert document["request"]["project_snapshots"] == [{
            "project_id": project_id,
            "snapshot_id": current["snapshot_id"],
        }]

    catalog_path = registry / "projects.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    catalog["projects"][0]["selection_state"] = "excluded"
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    with pytest.raises(ValueError, match="no eligible Projects"):
        resolve_project_query_scopes(registry, all_current=True)


def test_catalog_readiness_reports_per_project_and_coverage(tmp_path):
    _project, registry, project_id = _captured_project(tmp_path)
    report = catalog_readiness(registry)
    assert report["summary"] == {
        "eligible_projects": 1,
        "query_ready_projects": 1,
        "not_query_ready_projects": 0,
        "query_ready_coverage": "1/1",
        "all_eligible_query_ready": True,
        "source_refresh_assessed_projects": 0,
        "source_refresh_coverage": "0/1",
    }
    row = report["projects"][0]
    assert row["project_id"] == project_id
    assert row["query_status"] == "query_ready"
    assert row["source_refresh_status"] == "not_assessed"
    assert row["refresh_observation"] is None

    (durable_project_root(registry, project_id) / "current.json").unlink()
    report = catalog_readiness(registry)
    assert report["summary"]["query_ready_coverage"] == "0/1"
    assert report["projects"][0]["query_status"] == "missing_current_snapshot"


def test_catalog_readiness_uses_latest_completed_refresh_observation(tmp_path):
    _project, registry, project_id = _captured_project(tmp_path)
    reports = registry / "reports"
    reports.mkdir()
    common_plan = {
        "projects": [{
            "project_id": project_id,
            "source": "all",
            "raw_mode": "capture",
        }],
    }
    (reports / "refresh-older.json").write_text(json.dumps({
        "receipt_format": "codess.refresh-receipt/1",
        "created_at": "2026-07-30T10:00:00+00:00",
        "updated_at": "2026-07-30T10:01:00+00:00",
        "requested_stage": "apply",
        "status": "applied",
        "plan": common_plan,
        "preflight": [],
        "apply": [{
            "project_id": project_id,
            "stage": "apply",
            "status": "passed",
            "completed_at": "2026-07-30T10:01:00+00:00",
            "returncode": 0,
            "ingest_summary": {"snapshot_id": "snapshot-1"},
        }],
    }), encoding="utf-8")
    (reports / "refresh-newer.json").write_text(json.dumps({
        "receipt_format": "codess.refresh-receipt/1",
        "created_at": "2026-07-30T11:00:00+00:00",
        "requested_stage": "preflight",
        "status": "preflight_rejected",
        "plan": common_plan,
        "preflight": [{
            "project_id": project_id,
            "stage": "preflight",
            "status": "failed",
            "completed_at": "2026-07-30T11:01:00+00:00",
            "returncode": 1,
        }],
        "apply": [],
    }), encoding="utf-8")
    (reports / "refresh-plan-only.json").write_text(json.dumps({
        "receipt_format": "codess.refresh-receipt/1",
        "created_at": "2026-07-30T12:00:00+00:00",
        "requested_stage": "plan",
        "status": "planned",
        "plan": common_plan,
        "preflight": [],
        "apply": [],
    }), encoding="utf-8")

    report = catalog_readiness(registry)
    row = report["projects"][0]
    assert row["source_refresh_status"] == "preflight_failed"
    assert row["refresh_observation"]["observed_at"] == (
        "2026-07-30T11:01:00+00:00"
    )
    assert row["refresh_observation"]["source"] == "all"
    assert row["refresh_observation"]["raw_mode"] == "capture"
    assert row["refresh_observation"]["snapshot_id"] is None
    assert report["summary"]["source_refresh_assessed_projects"] == 1
    assert report["summary"]["source_refresh_coverage"] == "1/1"


def test_worktree_disposition_preserves_entry_but_excludes_broad_query(tmp_path):
    _project, registry, primary_id = _captured_project(tmp_path)
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    duplicate = ensure_project_binding(registry, worktree)

    result = set_project_selection_state(
        registry,
        duplicate["project_id"],
        "worktree",
        related_project_id=primary_id,
        note="duplicate identity for linked repository worktree",
    )

    assert result["selection_state"] == "worktree"
    assert result["catalog_disposition"]["related_project_id"] == primary_id
    report = catalog_readiness(registry)
    row = next(
        item for item in report["projects"]
        if item["project_id"] == duplicate["project_id"]
    )
    assert row["query_status"] == "not_selected"
    assert row["catalog_disposition"]["relation_kind"] == "worktree_of"
    scopes = resolve_project_query_scopes(registry, all_current=True)
    assert [item["project_id"] for item in scopes] == [primary_id]


def test_catalog_query_names_project_and_snapshot_on_incompatibility(tmp_path):
    _project, registry, project_id = _captured_project(tmp_path)
    scope = resolve_project_query_scopes(registry, [project_id])[0]
    manifest_path = (
        Path(scope["snapshot_base"])
        / "snapshots"
        / scope["snapshot_id"]
        / "manifest.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["package_digest"] = "sha256:" + ("0" * 64)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    # Isolate the package-digest incompatibility this test targets: recompute
    # the pointer's manifest_sha256 to match the edited bytes above, so
    # current_snapshot's hash check does not fire first and mask it
    # behind a generic "manifest hash mismatch" before the package-digest
    # comparison in snapshot_store_paths_from_base ever runs.
    pointer_path = Path(scope["snapshot_base"]) / "current.json"
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    pointer["manifest_sha256"] = hash_file(manifest_path)
    pointer_path.write_text(json.dumps(pointer), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable, "-m", "main", "query", "sessions",
            "--project-id", project_id, "--registry", str(registry),
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert project_id in result.stderr
    assert scope["snapshot_id"] in result.stderr

    with pytest.raises(ValueError, match="no eligible Projects"):
        resolve_project_query_scopes(registry, all_current=True)
    assert "package digest mismatch" in result.stderr


def test_all_current_honors_exact_and_read_compatible_package_policy(
    tmp_path, monkeypatch,
):
    _project, registry, project_id = _captured_project(tmp_path)
    scope = resolve_project_query_scopes(registry, [project_id])[0]
    monkeypatch.setattr(
        "codess.snapshot.verify_package",
        lambda: "different-current-package-digest",
    )

    with pytest.raises(ValueError, match="no eligible Projects"):
        resolve_project_query_scopes(registry, all_current=True)
    compatible = resolve_project_query_scopes(
        registry,
        all_current=True,
        allow_package_mismatch=True,
    )
    assert [(item["project_id"], item["snapshot_id"]) for item in compatible] == [
        (project_id, scope["snapshot_id"]),
    ]


def test_catalog_status_distinguishes_package_mismatch(tmp_path):
    _project, registry, project_id = _captured_project(tmp_path)
    scope = resolve_project_query_scopes(registry, [project_id])[0]
    manifest_path = (
        Path(scope["snapshot_base"])
        / "snapshots"
        / scope["snapshot_id"]
        / "manifest.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["package_digest"] = "sha256:" + ("0" * 64)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    # Isolate the package-digest check this test targets: recompute the
    # pointer's manifest_sha256 to match the edited bytes above, so
    # current_snapshot's hash check does not fire first and mask it
    # behind a generic "manifest hash mismatch" before the package-digest
    # comparison in snapshot_store_paths_from_base ever runs.
    pointer_path = Path(scope["snapshot_base"]) / "current.json"
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    pointer["manifest_sha256"] = hash_file(manifest_path)
    pointer_path.write_text(json.dumps(pointer), encoding="utf-8")

    row = next(
        item for item in catalog_readiness(registry)["projects"]
        if item["project_id"] == project_id
    )
    assert row["query_status"] == "package_mismatch"


def test_catalog_status_reports_snapshot_fail_for_invalid_store(tmp_path):
    _project, registry, project_id = _captured_project(tmp_path)
    scope = resolve_project_query_scopes(registry, [project_id])[0]
    snapshot = (
        Path(scope["snapshot_base"]) / "snapshots" / scope["snapshot_id"]
    )
    next(snapshot.glob("sessions_*.db")).write_bytes(b"invalid")

    row = next(
        item for item in catalog_readiness(registry)["projects"]
        if item["project_id"] == project_id
    )
    assert row["query_status"] == "snapshot_fail"


def test_human_session_name_lists_and_opens_current_session(tmp_path):
    _project, registry, project_id = _captured_project(tmp_path)
    set_session_name(registry, project_id, "s1", "welcome")

    listed = subprocess.run(
        [
            sys.executable, "-m", "main", "query", "--sessions",
            "--project-id", project_id, "--registry", str(registry),
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
    )
    opened = subprocess.run(
        [
            sys.executable, "-m", "main", "query",
            "--project-id", project_id, "--registry", str(registry),
            "--session-id", "welcome", "--show", "prompt",
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
    )

    assert listed.returncode == 0
    assert "\twelcome\t" in listed.stdout
    assert opened.returncode == 0
    assert "hello" in opened.stdout


def test_project_set_rejects_duplicate_or_unknown_inputs(tmp_path):
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text(json.dumps({
        "format": "codess.project-set/1",
        "projects": [
            {"project_id": "p1"},
            {"project_id": "p1"},
        ],
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="repeats"):
        load_project_set(duplicate)

    unknown = tmp_path / "unknown.json"
    unknown.write_text(json.dumps({
        "format": "codess.project-set/1",
        "unexpected": True,
        "projects": [{"project_id": "p1"}],
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported"):
        load_project_set(unknown)
