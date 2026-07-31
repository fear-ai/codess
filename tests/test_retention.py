"""Latest-only snapshot and raw-object retention."""

import json
import sqlite3

from codess.fileio import hash_file
from codess.retention import apply_retention_plan, build_retention_plan


def _snapshot(
    registry, project="project", snapshot_id="current", raw_name="keep",
    *, source_locator=None, uncompressed_size=None,
):
    root = registry / "projects" / project
    snapshot = root / "snapshots" / snapshot_id
    snapshot.mkdir(parents=True)
    store = snapshot / "sessions_cc.db"
    conn = sqlite3.connect(store)
    conn.execute("CREATE TABLE item(id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()
    raw_root = registry / "raw" / "codess.raw-1"
    raw = raw_root / "objects" / "sha256" / raw_name[:2] / f"{raw_name}.zst"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_bytes(raw_name.encode())
    record = {
        "record_type": "source_revision",
        "object_relpath": str(raw.relative_to(raw_root)),
        "stored_size": raw.stat().st_size,
    }
    if source_locator is not None:
        record.update({
            "availability": "captured",
            "source_system_id": "cursor.composer",
            "source_locator": source_locator,
            "source_revision_id": f"sha256:{raw_name}",
            "uncompressed_size": uncompressed_size,
        })
    raw_manifest = snapshot / "raw-manifest.jsonl"
    raw_manifest.write_text(
        json.dumps({"record_type": "header"}) + "\n" + json.dumps(record) + "\n"
    )
    manifest = {
        "snapshot_id": snapshot_id,
        "raw_manifest_sha256": hash_file(raw_manifest),
        "stores": {store.name: {"sha256": hash_file(store)}},
    }
    manifest_path = snapshot / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    pointer = {
        "snapshot_id": snapshot_id,
        "path": str(snapshot),
        "manifest_sha256": hash_file(manifest_path),
    }
    (root / "current.json").write_text(json.dumps(pointer))
    return snapshot, raw


def test_plan_keeps_current_and_selects_only_unreferenced_storage(tmp_path):
    registry = tmp_path / "registry"
    current, keep_raw = _snapshot(registry)
    old, old_raw = _snapshot(registry, snapshot_id="old", raw_name="delete")
    # Restore the current pointer overwritten by the old fixture.
    pointer = {
        "snapshot_id": current.name, "path": str(current),
        "manifest_sha256": hash_file(current / "manifest.json"),
    }
    (current.parents[1] / "current.json").write_text(json.dumps(pointer))

    plan = build_retention_plan(registry)
    assert plan["safe_to_apply"]
    assert plan["keep"]["snapshots"] == 1
    assert plan["delete"]["snapshots"] == 1
    assert plan["delete"]["raw_objects"] == 1
    assert str(old) in plan["delete"]["snapshot_paths"]
    assert str(old_raw) in plan["delete"]["raw_object_paths"]
    assert str(keep_raw) not in plan["delete"]["raw_object_paths"]


def test_apply_replans_deletes_and_records_receipt(tmp_path):
    registry = tmp_path / "registry"
    current, keep_raw = _snapshot(registry)
    old, old_raw = _snapshot(registry, snapshot_id="old", raw_name="delete")
    pointer = {
        "snapshot_id": current.name, "path": str(current),
        "manifest_sha256": hash_file(current / "manifest.json"),
    }
    (current.parents[1] / "current.json").write_text(json.dumps(pointer))
    receipt_path = tmp_path / "receipt.json"

    receipt = apply_retention_plan(registry, receipt_path=receipt_path)
    assert current.exists() and keep_raw.exists()
    assert not old.exists() and not old_raw.exists()
    assert receipt_path.exists()
    assert receipt["postcondition"]["remaining_candidates"] == 0
    assert receipt["selection"]["keep_comparison_revisions"] is False


def test_stale_selected_catalog_blocks_apply(tmp_path):
    registry = tmp_path / "registry"
    current, _ = _snapshot(registry)
    old, _ = _snapshot(registry, snapshot_id="old", raw_name="delete")
    pointer = {
        "snapshot_id": current.name, "path": str(current),
        "manifest_sha256": hash_file(current / "manifest.json"),
    }
    (current.parents[1] / "current.json").write_text(json.dumps(pointer))
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"projects": [{"snapshot_id": old.name}]}))

    plan = build_retention_plan(registry, reference_catalogs=[catalog])
    assert not plan["safe_to_apply"]
    assert plan["references"]["blocking"][0]["snapshot_id"] == "old"


def test_working_archives_require_explicit_selection_and_current_project(tmp_path):
    registry = tmp_path / "registry"
    _snapshot(registry)
    project = tmp_path / "workspace"
    archive = project / ".codess" / "working-archives" / "pre-package"
    archive.mkdir(parents=True)
    (archive / "sessions.db").write_bytes(b"obsolete")
    (registry / "projects.json").write_text(json.dumps({
        "projects": [{
            "project_id": "codess:project:project",
            "locations": [{"path": str(project), "state": "active"}],
        }],
    }))

    default = build_retention_plan(registry)
    assert default["working_archives"]["candidates"] == 1
    assert default["delete"]["working_archives"] == 0
    assert archive.exists()

    selected = build_retention_plan(
        registry, include_working_archives=True
    )
    assert selected["safe_to_apply"]
    assert selected["delete"]["working_archives"] == 1
    receipt = apply_retention_plan(
        registry, include_working_archives=True,
        receipt_path=tmp_path / "receipt.json",
    )
    assert not (project / ".codess" / "working-archives").exists()
    assert len(receipt["deleted"]["working_archive_paths"]) == 1


def test_multiple_huge_current_revisions_require_explicit_comparison(tmp_path):
    registry = tmp_path / "registry"
    locator = "/shared/Cursor/state.vscdb"
    _snapshot(
        registry, project="one", raw_name="first", source_locator=locator,
        uncompressed_size=1024**3,
    )
    _snapshot(
        registry, project="two", raw_name="second", source_locator=locator,
        uncompressed_size=1024**3,
    )

    default = build_retention_plan(registry)
    assert not default["safe_to_apply"]
    conflicts = default["large_revision_retention"]["conflicts"]
    assert conflicts[0]["revision_count"] == 2
    assert not default["large_revision_retention"]["comparison_retention_explicit"]

    comparison = build_retention_plan(
        registry, allow_large_comparison_revisions=True
    )
    assert comparison["safe_to_apply"]
    assert comparison["large_revision_retention"]["comparison_retention_explicit"]
