"""Stable project catalog, durable snapshots, and safe relocation."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from codess.config import PROJECT_FILE, STORE_ROOT
from codess.fileio import hash_file
from codess.project_annotations import build_project_annotations
from codess.project_catalog import (
    add_project_location,
    catalog_readiness,
    durable_project_root,
    ensure_project_binding,
    get_project_entry,
    load_catalog,
    load_project_set,
    register_workspace_bindings,
    resolve_project_query_scopes,
    set_project_selection_state,
)
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
        build_policy={"raw_mode": "capture"}, store_root=registry,
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
    # STORE_ROOT is resolved once at import time from CODESS_STORE_ROOT / the
    # real home directory, so this check (identity against the personal
    # registry) is exercised by passing STORE_ROOT itself, not by faking
    # Path.home() after codess.config has already computed it.
    project = tmp_path / "temporary-project"
    project.mkdir()

    with pytest.raises(ValueError, match="ephemeral system location"):
        ensure_project_binding(STORE_ROOT, project)


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
            "store_root": str(registry),
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


def test_a_relocated_location_identity_does_not_abort_the_ingest(tmp_path):
    """One directory, two derived identities, one row.

    `location_id` is derived from `(machine_id, path)`, so changing the
    derivation -- as the format-5 identity change did, moving every value from
    `sha256:` to `id1:` -- produces a second identity for a directory already
    recorded. `project_locations` declares `UNIQUE(machine_id, observed_path)`,
    and an insert handling only the `id` conflict raised `IntegrityError`
    mid-ingest, aborting the Project. Every affected Project was unrebuildable
    until this was fixed, which is exactly when a rebuild was required.
    """
    registry = tmp_path / "registry"
    project = tmp_path / "project"
    project.mkdir()
    binding = ensure_project_binding(registry, project)
    entry = get_project_entry(registry, binding["project_id"])
    store = project / ".codess" / "sessions_codex.db"
    init_db(store)

    # A registry written across an identity change: the same place twice.
    observed = dict(entry["locations"][0])
    stale = dict(observed)
    stale["location_id"] = "codess:location:sha256:" + "0" * 40
    stale["observed_at"] = "2020-01-01T00:00:00+00:00"
    entry = {**entry, "locations": [stale, observed]}

    with connect(store) as conn:
        sync_project_catalog(conn, entry)
        conn.commit()
        rows = conn.execute(
            "SELECT id, observed_path FROM project_locations"
        ).fetchall()
    assert len(rows) == 1, "one directory must not occupy two location rows"
    assert rows[0]["id"] == observed["location_id"], "the current derivation wins"


def test_the_catalog_keeps_one_entry_per_place():
    """Deduplication happens in the catalog, not on the way into SQL.

    The catalog is the operator-visible record, so filtering a duplicate at the
    insert would leave two documents disagreeing about how many locations a
    Project has. Keyed on `(machine_id, path)` because the physical place is the
    identity and `location_id` is derived from it.
    """
    from codess.project_catalog import _merged_locations

    stale = {
        "location_id": "codess:location:sha256:" + "1" * 40,
        "machine_id": "machine:m1",
        "path": "/w/p",
        "state": "active",
        "observed_at": "2020-01-01T00:00:00+00:00",
    }
    current = "codess:location:id1:" + "2" * 40
    merged = _merged_locations(
        {"locations": [stale]}, current,
        machine_id="machine:m1", resolved_path="/w/p",
        observed_at="2026-01-01T00:00:00+00:00",
    )
    assert len(merged) == 1, f"one place, one entry: {merged}"
    assert merged[0]["location_id"] == current, "the current derivation wins"


def test_a_genuinely_different_location_is_retained():
    """The deduplication must not collapse two real directories into one."""
    from codess.project_catalog import _merged_locations

    other = {
        "location_id": "codess:location:id1:" + "3" * 40,
        "machine_id": "machine:m1",
        "path": "/w/other",
        "state": "retired",
        "observed_at": "2020-01-01T00:00:00+00:00",
    }
    merged = _merged_locations(
        {"locations": [other]}, "codess:location:id1:" + "4" * 40,
        machine_id="machine:m1", resolved_path="/w/p",
        observed_at="2026-01-01T00:00:00+00:00",
    )
    assert {item["path"] for item in merged} == {"/w/other", "/w/p"}
    retired = next(item for item in merged if item["path"] == "/w/other")
    assert retired["state"] == "retired", "a retained location keeps its state"


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
            sys.executable, "tools/retire_project.py", "--directory", str(project),
            "--store", str(registry), "--new-location", str(replacement),
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
            "--project-id", project_id, "--store", str(registry),
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
                *selector, "--store", str(registry),
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
    receipts = registry / "receipts" / "refresh"
    receipts.mkdir(parents=True)
    common_plan = {
        "projects": [{
            "project_id": project_id,
            "source": "all",
            "raw_mode": "capture",
        }],
    }
    (receipts / "refresh-older.json").write_text(json.dumps({
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
    (receipts / "refresh-newer.json").write_text(json.dumps({
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
    (receipts / "refresh-plan-only.json").write_text(json.dumps({
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
    manifest["contract_digest"] = "sha256:" + ("0" * 64)
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
            "--project-id", project_id, "--store", str(registry),
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
    assert "different CoSchema contract" in result.stderr


def test_all_current_honors_exact_and_read_compatible_package_policy(
    tmp_path, monkeypatch,
):
    _project, registry, project_id = _captured_project(tmp_path)
    scope = resolve_project_query_scopes(registry, [project_id])[0]
    monkeypatch.setattr(
        "codess.snapshot.contract_digest",
        lambda: "different-current-package-digest",
    )

    with pytest.raises(ValueError, match="no eligible Projects"):
        resolve_project_query_scopes(registry, all_current=True)
    compatible = resolve_project_query_scopes(
        registry,
        all_current=True,
        allow_contract_mismatch=True,
    )
    assert [(item["project_id"], item["snapshot_id"]) for item in compatible] == [
        (project_id, scope["snapshot_id"]),
    ]


def test_catalog_status_distinguishes_contract_mismatch(tmp_path):
    _project, registry, project_id = _captured_project(tmp_path)
    scope = resolve_project_query_scopes(registry, [project_id])[0]
    manifest_path = (
        Path(scope["snapshot_base"])
        / "snapshots"
        / scope["snapshot_id"]
        / "manifest.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["contract_digest"] = "sha256:" + ("0" * 64)
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
    assert row["query_status"] == "contract_mismatch"


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
            "--project-id", project_id, "--store", str(registry),
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
    )
    opened = subprocess.run(
        [
            sys.executable, "-m", "main", "query",
            "--project-id", project_id, "--store", str(registry),
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


# --- extracted binding steps -------------------------------------------------
#
# `ensure_project_binding` and `catalog_readiness` are composed from named steps,
# extracted within this module because catalog identity, locations, and readiness are one
# concern. These call the steps directly; the composed behavior is covered above.

def test_a_missing_binding_file_reads_as_no_binding(tmp_path):
    from codess.project_catalog import _read_existing_binding

    assert _read_existing_binding(tmp_path / "absent.json") is None


def test_a_binding_in_an_unsupported_format_is_refused(tmp_path):
    """Ignoring it would mint a second identity for a Project that has one."""
    from codess.project_catalog import _read_existing_binding

    path = tmp_path / "project.json"
    path.write_text(json.dumps({"binding_format": "something/else"}), encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported project binding format"):
        _read_existing_binding(path)


def test_a_retained_binding_is_the_first_authority():
    from codess.project_catalog import _resolve_project_id

    binding = {"project_id": "codess:project:from-binding"}
    entries = {"codess:project:from-catalog": {
        "project_id": "codess:project:from-catalog",
        "locations": [{"path": "/projects/p"}],
    }}
    assert _resolve_project_id(binding, entries, "/projects/p") == (
        "codess:project:from-binding"
    )


def test_a_catalog_entry_claiming_the_path_is_the_second_authority():
    """A deleted binding file must not split one Project across two identities."""
    from codess.project_catalog import _resolve_project_id

    entries = {"codess:project:known": {
        "project_id": "codess:project:known",
        "locations": [{"path": "/projects/p"}],
    }}
    assert _resolve_project_id(None, entries, "/projects/p") == "codess:project:known"


def test_an_unknown_location_mints_a_new_identity():
    from codess.project_catalog import _resolve_project_id

    minted = _resolve_project_id(None, {}, "/projects/new")
    assert minted.startswith("codess:project:")
    assert minted != _resolve_project_id(None, {}, "/projects/new")


def test_the_observed_location_is_recorded_as_active():
    from codess.project_catalog import _merged_locations

    [location] = _merged_locations(
        {}, "codess:location:a",
        machine_id="m1", resolved_path="/projects/p", observed_at="2026-01-01T00:00:00+00:00",
    )
    assert location["state"] == "active"
    assert location["path_obsolete"] is False
    assert location["observed_at"] == "2026-01-01T00:00:00+00:00"


def test_other_locations_keep_their_state():
    """Observing one location must not retire the Project's other ones."""
    from codess.project_catalog import _merged_locations

    entry = {"locations": [
        {"location_id": "codess:location:old", "path": "/old", "state": "active"},
    ]}
    locations = _merged_locations(
        entry, "codess:location:new",
        machine_id="m1", resolved_path="/new", observed_at="2026-01-01T00:00:00+00:00",
    )
    retained = next(
        item for item in locations if item["location_id"] == "codess:location:old"
    )
    assert retained["state"] == "active"
    assert len(locations) == 2


def test_a_retired_location_defaults_to_obsolete():
    """Entries predating the field must not read as current locations."""
    from codess.project_catalog import _merged_locations

    entry = {"locations": [
        {"location_id": "codess:location:old", "path": "/old", "state": "retired"},
    ]}
    locations = _merged_locations(
        entry, "codess:location:new",
        machine_id="m1", resolved_path="/new", observed_at="2026-01-01T00:00:00+00:00",
    )
    retired = next(
        item for item in locations if item["location_id"] == "codess:location:old"
    )
    assert retired["path_obsolete"] is True


def test_locations_are_ordered_deterministically():
    from codess.project_catalog import _merged_locations

    entry = {"locations": [
        {"location_id": "codess:location:z", "path": "/z", "state": "active"},
        {"location_id": "codess:location:a", "path": "/a", "state": "active"},
    ]}
    locations = _merged_locations(
        entry, "codess:location:m",
        machine_id="m1", resolved_path="/m", observed_at="2026-01-01T00:00:00+00:00",
    )
    ids = [item["location_id"] for item in locations]
    assert ids == sorted(ids)


def test_only_an_approved_source_link_binds_a_workspace(tmp_path):
    """A proposed link records a decision pending, not authority to bind."""
    from codess.config import SOURCE_LINKS_FILE, SOURCE_LINKS_FORMAT, STORE_DIR
    from codess.project_catalog import _apply_source_links

    project = tmp_path / "project"
    (project / STORE_DIR).mkdir(parents=True)
    (project / STORE_DIR / SOURCE_LINKS_FILE).write_text(json.dumps({
        "format": SOURCE_LINKS_FORMAT,
        "links": [{
            "source_system_id": "cursor.composer",
            "source_identity": {"workspace_id": "ws-1"},
            "selection_state": "proposed",
        }],
    }), encoding="utf-8")
    bindings, _aliases = _apply_source_links(
        {}, project, "codess:location:a", str(project),
    )
    assert bindings == []


def test_an_approved_link_binds_its_workspace(tmp_path):
    from codess.config import SOURCE_LINKS_FILE, SOURCE_LINKS_FORMAT, STORE_DIR
    from codess.project_catalog import _apply_source_links

    project = tmp_path / "project"
    (project / STORE_DIR).mkdir(parents=True)
    (project / STORE_DIR / SOURCE_LINKS_FILE).write_text(json.dumps({
        "format": SOURCE_LINKS_FORMAT,
        "links": [{
            "source_system_id": "cursor.composer",
            "source_identity": {"workspace_id": "ws-1"},
            "selection_state": "approved",
            "source_project_path": str(project),
        }],
    }), encoding="utf-8")
    bindings, _aliases = _apply_source_links(
        {}, project, "codess:location:a", str(project),
    )
    assert [item["workspace_id"] for item in bindings] == ["ws-1"]
    assert bindings[0]["path_obsolete"] is False


def test_a_link_from_another_path_marks_that_path_obsolete(tmp_path):
    """A moved Project stops claiming its former location."""
    from codess.config import SOURCE_LINKS_FILE, SOURCE_LINKS_FORMAT, STORE_DIR
    from codess.project_catalog import _apply_source_links

    project = tmp_path / "project"
    (project / STORE_DIR).mkdir(parents=True)
    (project / STORE_DIR / SOURCE_LINKS_FILE).write_text(json.dumps({
        "format": SOURCE_LINKS_FORMAT,
        "links": [{
            "source_system_id": "cursor.composer",
            "source_identity": {"workspace_id": "ws-1"},
            "selection_state": "approved",
            "source_project_path": "/former/location",
        }],
    }), encoding="utf-8")
    bindings, aliases = _apply_source_links(
        {"path_aliases": ["/former/location"]}, project,
        "codess:location:a", str(project),
    )
    assert bindings[0]["path_obsolete"] is True
    assert "/former/location" not in aliases


def test_the_observed_path_is_always_an_alias(tmp_path):
    from codess.project_catalog import _apply_source_links

    project = tmp_path / "project"
    project.mkdir()
    _bindings, aliases = _apply_source_links(
        {}, project, "codess:location:a", str(project),
    )
    assert aliases == [str(project)]


# --- extracted readiness steps -----------------------------------------------

def test_an_unselected_project_is_not_a_failure(tmp_path):
    """`not_selected` means none was asked for, not that one broke."""
    from codess.project_catalog import _assess_query_status

    status, snapshot_id, detail = _assess_query_status(
        tmp_path, "codess:project:x", eligible=False,
    )
    assert (status, snapshot_id, detail) == ("not_selected", None, None)


def test_a_selected_project_without_a_snapshot_reports_it(tmp_path):
    from codess.project_catalog import _assess_query_status

    status, snapshot_id, _detail = _assess_query_status(
        tmp_path, "codess:project:x", eligible=True,
    )
    assert status == "missing_current_snapshot"
    assert snapshot_id is None


def test_readiness_counts_only_eligible_projects_as_coverage():
    """An unselected Project is not one that failed to become ready."""
    from codess.project_catalog import _readiness_summary

    summary = _readiness_summary([
        {"selection_eligible": True, "query_status": "query_ready",
         "source_refresh_status": "completed"},
        {"selection_eligible": False, "query_status": "not_selected",
         "source_refresh_status": "not_assessed"},
    ])
    assert summary["eligible_projects"] == 1
    assert summary["query_ready_coverage"] == "1/1"
    assert summary["all_eligible_query_ready"] is True


def test_readiness_reports_refresh_coverage_over_every_project():
    """A receipt can exist for a Project no longer selected."""
    from codess.project_catalog import _readiness_summary

    summary = _readiness_summary([
        {"selection_eligible": True, "query_status": "query_ready",
         "source_refresh_status": "completed"},
        {"selection_eligible": False, "query_status": "not_selected",
         "source_refresh_status": "completed"},
    ])
    assert summary["source_refresh_coverage"] == "2/2"


def test_an_empty_catalog_is_not_reported_as_fully_ready():
    """Zero of zero must not read as success."""
    from codess.project_catalog import _readiness_summary

    assert _readiness_summary([])["all_eligible_query_ready"] is False


def test_a_readiness_row_reads_curation_or_the_entry():
    """Curation was added later, so older entries carry the values inline."""
    from codess.project_catalog import _readiness_row

    curated = _readiness_row(
        {"project_id": "p", "curation": {"selection_state": "selected",
                                         "activity_state": "active"}},
        query_status="query_ready", current_snapshot_id="s1", detail=None,
        eligible=True, refresh_observation=None,
    )
    legacy = _readiness_row(
        {"project_id": "p", "selection_state": "selected",
         "activity_state": "active"},
        query_status="query_ready", current_snapshot_id="s1", detail=None,
        eligible=True, refresh_observation=None,
    )
    assert curated["selection_state"] == legacy["selection_state"] == "selected"
    assert curated["activity_state"] == legacy["activity_state"] == "active"


def test_a_readiness_row_counts_only_active_locations_that_exist(tmp_path):
    from codess.project_catalog import _readiness_row

    existing = tmp_path / "here"
    existing.mkdir()
    row = _readiness_row(
        {"project_id": "p", "locations": [
            {"path": str(existing), "state": "active"},
            {"path": str(tmp_path / "gone"), "state": "active"},
            {"path": str(existing), "state": "retired"},
        ]},
        query_status="query_ready", current_snapshot_id="s1", detail=None,
        eligible=True, refresh_observation=None,
    )
    assert row["active_location_count"] == 2
    assert row["existing_active_location_count"] == 1


def test_an_unassessed_project_says_so_rather_than_claiming_freshness():
    from codess.project_catalog import _readiness_row

    row = _readiness_row(
        {"project_id": "p"}, query_status="query_ready",
        current_snapshot_id="s1", detail=None, eligible=True,
        refresh_observation=None,
    )
    assert row["source_refresh_status"] == "not_assessed"


def test_one_observation_carries_one_timestamp(tmp_path):
    """A single logical event must not be stamped at three different instants.

    `ensure_project_binding` called `now()` separately for the entry, the
    location, and the catalog, so one observation could record three times.
    """
    registry = tmp_path / "registry"
    registry.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    ensure_project_binding(registry, project)
    entry = get_project_entry(registry, load_catalog(registry)["projects"][0]["project_id"])
    stamps = {entry["updated_at"]} | {
        location["observed_at"] for location in entry["locations"]
    }
    assert len(stamps) == 1


class TestLostBindingIsReported:
    """A minted identity says so, because a silent one splits a Project.

    The binding lives inside the Project directory, so it is lost whenever that
    directory is cleaned, re-cloned, or restored from a copy predating it. The
    catalog search exists to recover from that and is only reached when the
    binding is absent -- so a *stale* binding wins, and one path acquires a
    second Project carrying none of the first one's review. Nine such
    duplicates were created on one machine in a single session before anything
    reported it.
    """

    def test_minting_warns(self, tmp_path, caplog):
        """The first ingest of a Project mints, and says which identity."""
        registry = tmp_path / "registry"
        project = tmp_path / "proj"
        project.mkdir()
        with caplog.at_level(logging.WARNING):
            binding = ensure_project_binding(registry, project)
        assert binding["project_id"].startswith("codess:project:")
        assert any("minting" in record.message for record in caplog.records)

    def test_a_retained_binding_does_not_warn(self, tmp_path, caplog):
        """The ordinary path is silent; only a new identity is news."""
        registry = tmp_path / "registry"
        project = tmp_path / "proj"
        project.mkdir()
        ensure_project_binding(registry, project)
        caplog.clear()
        with caplog.at_level(logging.WARNING):
            ensure_project_binding(registry, project)
        assert not [r for r in caplog.records if "minting" in r.message]

    def test_a_lost_binding_recovers_from_the_catalog(self, tmp_path, caplog):
        """Deleting the binding must not mint: the catalog still knows the path."""
        registry = tmp_path / "registry"
        project = tmp_path / "proj"
        project.mkdir()
        first = ensure_project_binding(registry, project)
        (project / ".codess" / PROJECT_FILE).unlink()
        caplog.clear()
        with caplog.at_level(logging.WARNING):
            second = ensure_project_binding(registry, project)
        assert second["project_id"] == first["project_id"]
        assert not [r for r in caplog.records if "minting" in r.message]

    def test_a_binding_disagreeing_with_the_catalog_warns(self, tmp_path, caplog):
        """A stale binding wins by design; the disagreement is reported."""
        registry = tmp_path / "registry"
        project = tmp_path / "proj"
        project.mkdir()
        first = ensure_project_binding(registry, project)
        binding_path = project / ".codess" / PROJECT_FILE
        binding = json.loads(binding_path.read_text(encoding="utf-8"))
        binding["project_id"] = "codess:project:00000000-0000-0000-0000-000000000000"
        binding_path.write_text(json.dumps(binding), encoding="utf-8")
        caplog.clear()
        with caplog.at_level(logging.WARNING):
            second = ensure_project_binding(registry, project)
        assert second["project_id"] != first["project_id"]
        assert any(
            "several Projects" in record.message for record in caplog.records
        )


class TestStateTransitionRecord:
    """A disposition records the state it left, not only the one it entered.

    Without it, "excluded, always was" and "excluded on this date, previously
    active" are one value -- and only the second raises the question of what
    changed and whether it should be revisited.
    """

    def _catalogued(self, tmp_path):
        registry = tmp_path / "registry"
        project = tmp_path / "proj"
        project.mkdir()
        binding = ensure_project_binding(registry, project)
        return registry, binding["project_id"]

    def test_an_initial_state_has_no_previous(self, tmp_path):
        registry, project_id = self._catalogued(tmp_path)
        set_project_selection_state(registry, project_id, "candidate")
        entry = get_project_entry(registry, project_id)
        assert entry["catalog_disposition"]["state"] == "candidate"
        assert "previous_state" not in entry["catalog_disposition"]

    def test_a_change_records_what_it_left(self, tmp_path):
        registry, project_id = self._catalogued(tmp_path)
        set_project_selection_state(registry, project_id, "candidate")
        set_project_selection_state(registry, project_id, "excluded")
        disposition = get_project_entry(registry, project_id)["catalog_disposition"]
        assert disposition["state"] == "excluded"
        assert disposition["previous_state"] == "candidate"

    def test_setting_the_same_state_records_no_transition(self, tmp_path):
        """Re-stating a state is not a change and must not read as one."""
        registry, project_id = self._catalogued(tmp_path)
        set_project_selection_state(registry, project_id, "excluded")
        set_project_selection_state(registry, project_id, "excluded")
        disposition = get_project_entry(registry, project_id)["catalog_disposition"]
        assert "previous_state" not in disposition
