"""Policy-driven baseline validation and semantic reproducibility tests."""

import json
from pathlib import Path

import pytest

from codess.baseline_validation import (
    _validate_raw,
    load_policy,
    run_query_smoke,
    semantic_digest,
    validate_project,
)
from codess.fileio import read_source_revision
from codess.raw_store import RawStore
from codess.snapshot import create_snapshot, current_stores
from codess.store import connect, init_db, replace_session_events


def test_living_project_policies_do_not_freeze_transient_corpus_counts():
    policy_dir = Path(__file__).resolve().parents[1] / "catalog" / "policies"
    forbidden = {"minimum_sessions", "minimum_events", "expected_raw_records"}
    for path in policy_dir.glob("*.json"):
        if path.name == "ci-fixture.json":
            continue
        policy = json.loads(path.read_text(encoding="utf-8"))
        assert forbidden.isdisjoint(policy), path


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

    before = semantic_digest(current_stores(project))
    pointer = json.loads((project / ".codess/current.json").read_text())
    snapshot = project / ".codess" / pointer["path"]
    raw_record = json.loads((snapshot / "raw-manifest.jsonl").read_text().splitlines()[1])
    create_snapshot(
        project,
        current_stores(project),
        [raw_record],
        raw_store=RawStore(raw_root),
        build_policy={"raw_mode": "capture"},
    )
    assert semantic_digest(current_stores(project)) == before


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


def test_policy_dates_decoder_and_validator_independently(tmp_path):
    project, raw_root = _snapshot(tmp_path)
    report = validate_project(
        project,
        policy={
            "policy_format": "codess.validation-policy/1",
            "required_decoder_version": "0.1",
            "required_validator_version": "0.1",
        },
        raw_store_root=raw_root,
    )
    assert report["status"] == "rejected"
    failed = {
        check["name"] for check in report["checks"] if not check["passed"]
    }
    assert {"decoder_version", "validator_version"} <= failed


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
    """Every acceptance policy present parses and requires a fixed point.

    The set is not enumerated. It was, naming one machine's Projects, which
    tied the suite to that machine and disclosed it -- and asserted the wrong
    thing besides: what matters is that each policy is loadable and demands a
    fixed point, not which Projects an operator happens to have accepted.
    `ci-fixture.json` is the one policy the repository ships, because it
    validates a fixture the repository contains and is therefore true on
    every machine (W58).
    """
    root = Path(__file__).resolve().parents[1]
    policies = sorted((root / "catalog/policies").glob("*.json"))
    names = {path.name for path in policies}
    assert "ci-fixture.json" in names, "the shipped template policy is missing"
    assert policies, "no acceptance policies found"
    for path in policies:
        policy = load_policy(path)
        assert policy["require_fixed_point"], f"{path.name} does not require a fixed point"


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
        project, current_stores(project), raw_records, raw_store=raw_store,
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


def test_query_smoke_targets_unpublished_candidate_snapshot(tmp_path):
    project, raw_root = _snapshot(tmp_path)
    pointer_path = project / ".codess/current.json"
    prior_pointer = pointer_path.read_bytes()
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    current_snapshot = project / ".codess" / pointer["path"]
    raw_record = json.loads(
        (current_snapshot / "raw-manifest.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()[1]
    )
    candidate = create_snapshot(
        project,
        current_stores(project),
        [raw_record],
        raw_store=RawStore(raw_root),
        build_policy={"raw_mode": "capture"},
        publish=False,
    )

    results = run_query_smoke(
        project, snapshot_id=candidate.name, snapshot_path=candidate
    )

    assert all(result["passed"] for result in results.values()), results
    assert pointer_path.read_bytes() == prior_pointer


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


def test_reference_validation_rejects_legacy_md5_revision(tmp_path):
    source = tmp_path / "legacy.jsonl"
    source.write_text('{"legacy":true}\n', encoding="utf-8")
    legacy_revision = "unsupported-fingerprint:" + ("0" * 32)
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    (snapshot / "raw-manifest.jsonl").write_text(
        json.dumps({"raw_format": "codess.raw/1"}) + "\n"
        + json.dumps({
            "availability": "reference",
            "source_system_id": "openai.codex",
            "source_locator": str(source),
            "source_revision_id": legacy_revision,
        }) + "\n",
        encoding="utf-8",
    )
    report = {"checks": [], "errors": [], "limitations": []}
    records, revisions = _validate_raw(
        snapshot, {}, None, report, verify_reference_current=True
    )

    assert len(records) == 1
    assert legacy_revision in revisions[0]
    check = next(
        check for check in report["checks"]
        if check["name"] == "raw.record[0].current_reference"
    )
    assert not check["passed"]
    assert check["detail"]["expected"] == legacy_revision
    assert check["detail"]["observed"].startswith("digest-fingerprint:")
    assert any("current_reference" in error for error in report["errors"])


def test_reference_validation_keeps_sha256_mismatch_fatal(tmp_path):
    source = tmp_path / "current.jsonl"
    source.write_text('{"current":true}\n', encoding="utf-8")
    current_revision = read_source_revision(source)[0]
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    (snapshot / "raw-manifest.jsonl").write_text(
        json.dumps({"raw_format": "codess.raw/1"}) + "\n"
        + json.dumps({
            "availability": "reference",
            "source_system_id": "openai.codex",
            "source_locator": str(source),
            "source_revision_id": current_revision,
        }) + "\n",
        encoding="utf-8",
    )
    source.write_text('{"current":"changed"}\n', encoding="utf-8")
    report = {"checks": [], "errors": [], "limitations": []}
    _validate_raw(
        snapshot, {}, None, report, verify_reference_current=True
    )

    assert any("current_reference" in error for error in report["errors"])
