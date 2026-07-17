"""Policy-driven baseline validation and semantic reproducibility tests."""

import json
from pathlib import Path

import pytest

from codess.baseline_validation import (
    load_policy,
    run_query_smoke,
    semantic_digest,
    validate_project,
)
from codess.raw_store import RawStore
from codess.snapshot import create_snapshot, current_store_paths
from codess.store import connect, init_db, replace_session_events


def _snapshot(tmp_path: Path, *, orphan_tool_result: bool = False) -> tuple[Path, Path]:
    project = tmp_path / "project"
    project.mkdir()
    store_path = tmp_path / "sessions_claude.db"
    init_db(store_path)
    conn = connect(store_path)
    replace_session_events(
        conn,
        {
            "id": "session-1",
            "source": "Claude",
            "type": "Code",
            "project_path": str(project),
            "started_at": 1.0,
        },
        [
            {
                "session_id": "session-1",
                "event_id": "event-1",
                "event_type": "user_message",
                "role": "user",
                "content": "test",
                "source_file": "/source.jsonl",
            },
            *(
                [
                    {
                        "session_id": "session-1",
                        "event_id": "event-2",
                        "event_type": "tool_result",
                        "role": "tool",
                        "content": "orphan",
                        "source_file": "/source.jsonl",
                    }
                ]
                if orphan_tool_result
                else []
            ),
        ],
        session_id="session-1",
    )
    conn.commit()
    conn.close()

    source = tmp_path / "source.jsonl"
    source.write_text('{"type":"user"}\n', encoding="utf-8")
    raw_root = tmp_path / "raw"
    raw_store = RawStore(raw_root)
    raw_record = raw_store.observe(
        source,
        source_system_id="claude-code",
        storage_format="claude-jsonl",
        mode="capture",
    )
    create_snapshot(
        project,
        [store_path],
        [raw_record],
        raw_store=raw_store,
        build_policy={"raw_mode": "capture"},
    )
    return project, raw_root


def test_validate_snapshot_and_semantic_fixed_point(tmp_path):
    project, raw_root = _snapshot(tmp_path)
    policy = {
        "policy_format": "codess.validation-policy/1",
        "project": str(project),
        "required_sources": ["Claude"],
        "minimum_sessions": {"Claude": 1},
        "minimum_events": {"Claude": 1},
        "raw_mode": "capture",
        "expected_raw_records": 1,
        "allowed_diagnostics": {},
    }

    first = validate_project(project, policy=policy, raw_store_root=raw_root)
    assert first["status"] == "accepted", first["errors"]
    assert not first["limitations"]
    assert len(first["semantic_digest"]) == 64

    before = semantic_digest(current_store_paths(project))
    pointer = json.loads((project / ".codess/current.json").read_text())
    snapshot = project / ".codess" / pointer["path"]
    raw_record = json.loads((snapshot / "raw-manifest.jsonl").read_text().splitlines()[1])
    create_snapshot(
        project,
        current_store_paths(project),
        [raw_record],
        raw_store=RawStore(raw_root),
        build_policy={"raw_mode": "capture"},
    )
    assert semantic_digest(current_store_paths(project)) == before


def test_policy_rejects_unapproved_mapping_diagnostic(tmp_path):
    project, raw_root = _snapshot(tmp_path, orphan_tool_result=True)
    report = validate_project(
        project,
        policy={
            "policy_format": "codess.validation-policy/1",
            "allowed_diagnostics": {},
        },
        raw_store_root=raw_root,
    )
    assert report["status"] == "rejected"
    assert report["diagnostics"] == {"unmapped_event_semantics": 1}
    assert any("policy.diagnostics.known" in error for error in report["errors"])


def test_load_policy_rejects_unknown_fields(tmp_path):
    path = tmp_path / "policy.json"
    path.write_text(
        json.dumps(
            {
                "policy_format": "codess.validation-policy/1",
                "surprise": True,
            }
        )
    )
    with pytest.raises(ValueError, match="unknown fields"):
        load_policy(path)


def test_repository_acceptance_policies_are_valid():
    root = Path(__file__).resolve().parents[1]
    policies = sorted((root / "catalog/policies").glob("*.json"))
    assert {path.name for path in policies} == {
        "ci-fixture.json", "harduw.json", "insight.json", "misses.json", "setpack.json", "spank-logs.json",
        "spank-py.json", "spank-rs.json", "swemore.json", "wp.json",
        "wpages.json", "zero400.json", "zeroperf.json", "zerowalletmac.json",
    }
    assert all(load_policy(path)["require_fixed_point"] for path in policies)


def test_ci_fixture_policy_covers_three_vendors_without_home_data(tmp_path):
    root = Path(__file__).resolve().parents[1]
    project = tmp_path / "project"
    project.mkdir()
    stores = []
    raw_root = tmp_path / "registry" / "raw"
    raw_store = RawStore(raw_root)
    raw_records = []
    for source, suffix, source_system in (
        ("Claude", "cc", "anthropic.claude-code"),
        ("Codex", "codex", "openai.codex"),
        ("Cursor", "cursor", "cursor.composer"),
    ):
        store_path = tmp_path / f"sessions_{suffix}.db"
        init_db(store_path)
        conn = connect(store_path)
        session_id = f"fixture-{suffix}"
        replace_session_events(
            conn,
            {
                "id": session_id, "source": source, "type": "Code",
                "project_path": str(project),
            },
            [{
                "session_id": session_id, "event_id": "prompt",
                "event_type": "user_message", "subtype": "prompt",
                "role": "user", "content": source,
            }],
            session_id=session_id,
        )
        conn.commit()
        conn.close()
        stores.append(store_path)
        raw_source = tmp_path / f"{suffix}.source"
        raw_source.write_text(source + "\n", encoding="utf-8")
        raw_records.append(
            raw_store.observe(
                raw_source,
                source_system_id=source_system,
                storage_format=f"fixture-{suffix}",
                mode="capture",
            )
        )

    create_snapshot(
        project, stores, raw_records, raw_store=raw_store,
        build_policy={"raw_mode": "capture"},
    )
    policy = load_policy(root / "catalog/policies/ci-fixture.json")
    first = validate_project(project, policy=policy, raw_store_root=raw_root)
    assert first["status"] == "accepted", first["errors"]
    create_snapshot(
        project, current_store_paths(project), raw_records, raw_store=raw_store,
        build_policy={"raw_mode": "capture"},
    )
    second = validate_project(project, policy=policy, raw_store_root=raw_root)
    assert second["source_revisions"] == first["source_revisions"]
    assert second["semantic_digest"] == first["semantic_digest"]
    assert all(value["passed"] for value in run_query_smoke(project).values())


def test_query_smoke_exercises_all_read_modes(tmp_path):
    project, _ = _snapshot(tmp_path)
    results = run_query_smoke(project)
    assert set(results) == {
        "stats", "sessions", "lineage", "audit", "diagnostics", "artifacts"
    }
    assert all(result["passed"] for result in results.values()), results


def test_frozen_reference_validation_does_not_require_live_locator(tmp_path):
    project, _ = _snapshot(tmp_path)
    pointer = json.loads((project / ".codess/current.json").read_text())
    snapshot = project / ".codess" / pointer["path"]
    manifest_path = snapshot / "raw-manifest.jsonl"
    lines = manifest_path.read_text().splitlines()
    record = json.loads(lines[1])
    record.update(
        {
            "availability": "reference",
            "source_revision_id": "stat:1:1",
            "source_mtime_ns": 1,
            "source_size": 1,
        }
    )
    for key in (
        "object_id", "stored_sha256", "compression", "uncompressed_size",
        "stored_size", "object_relpath",
    ):
        record.pop(key, None)
    manifest_path.write_text(lines[0] + "\n" + json.dumps(record) + "\n")
    manifest = json.loads((snapshot / "manifest.json").read_text())
    import hashlib
    manifest["raw_manifest_sha256"] = hashlib.sha256(
        manifest_path.read_bytes()
    ).hexdigest()
    snapshot_manifest = snapshot / "manifest.json"
    snapshot_manifest.write_text(json.dumps(manifest))
    current_path = project / ".codess/current.json"
    current = json.loads(current_path.read_text())
    current["manifest_sha256"] = hashlib.sha256(
        snapshot_manifest.read_bytes()
    ).hexdigest()
    current_path.write_text(json.dumps(current))

    strict = validate_project(project)
    assert strict["status"] == "rejected"
    frozen = validate_project(project, verify_reference_current=False)
    assert frozen["status"] == "accepted_with_limitations"
    assert not frozen["errors"]
