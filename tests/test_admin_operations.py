"""Administrative workflow operations and grouped command dispatch."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from codess.baseline_catalog import freeze_reviewed_catalogs, verify_reviewed_catalog
from codess.baseline_operations import reset_rebuildable_working_stores
from codess.baseline_validation import validate_project
from codess.candidate_review import (
    discover_git_roots, recommend, record_decision, refresh_candidates, validate_policy,
)
from codess.catalog_operations import onboard_catalog, relocate_project
from codess.fileio import hash_file, read_json, write_json_atomic
from codess.project import parse_and_run
from codess.project_catalog import (
    add_project_location, ensure_project_binding, get_project_entry,
    retire_project_location,
)
from codess.raw_store import RawStore
from codess.schema_evolution import compare, required
from codess.snapshot import create_snapshot
from codess.store import connect, init_db, replace_session_events, sync_project_catalog
from codess.vendor_audits.claude_features import audit_claude_features


def _git_project(path: Path) -> None:
    path.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    (path / "README.md").write_text("test\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "initial"], cwd=path, check=True)


def _captured_project(tmp_path: Path) -> tuple[Path, Path, str]:
    registry = tmp_path / "registry"
    project = tmp_path / "project"
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
            {"id": "s1", "source": "Codex", "type": "Code",
             "project_path": str(project), "project_id": binding["project_id"]},
            [{"session_id": "s1", "event_id": "e1",
              "event_type": "user_message", "role": "user",
              "content": "hello", "source_file": str(source)}],
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


def test_fileio_hash_and_atomic_json(tmp_path):
    path = tmp_path / "value.json"
    write_json_atomic(path, {"b": 2, "a": 1})
    assert read_json(path) == {"a": 1, "b": 2}
    assert len(hash_file(path)) == 64


def test_candidate_refresh_uses_scan_and_preserves_review(tmp_path, monkeypatch):
    project = tmp_path / "project"
    _git_project(project)
    catalog = tmp_path / "catalog.json"
    write_json_atomic(catalog, {
        "catalog_format": "codess.catalog/1",
        "projects": [{
            "project_id": "p1", "path": str(project), "logical_name": "project",
            "curation": {"topic": "test", "ownership": "own", "activity_state": "active", "selection_state": "candidate"},
            "observations": {},
            "review": {"decision": "approved", "reviewed_at": "before"},
        }],
    })
    monkeypatch.setattr(
        "codess.candidate_review.run_scan",
        lambda *args, **kwargs: [{
            "path": "project", "dir_path": str(project), "vendor": "Claude|Codex",
            "sess": 3, "mb": 2.5, "span_weeks": 1.0,
        }],
    )
    report = refresh_candidates([tmp_path], catalog_path=catalog, since="2020-01-01")
    item = report["projects"][0]
    assert item["review"]["decision"] == "approved"
    assert item["recommendation"]["outcome"] == "consider"
    assert item["observations"]["git"]["is_repository"] is True
    assert item["observations"]["git"]["commits_since"] == 1


def test_git_discovery_stops_at_first_repository_boundary(tmp_path):
    parent = tmp_path / "parent"
    nested = parent / "vendor" / "nested"
    parent.mkdir()
    (parent / ".git").mkdir()
    nested.mkdir(parents=True)
    (nested / ".git").mkdir()
    sibling = tmp_path / "sibling"
    sibling.mkdir()
    (sibling / ".git").mkdir()
    assert discover_git_roots([tmp_path], max_depth=5) == [parent, sibling]


def test_git_discovery_prunes_generated_dependency_and_cache_trees(tmp_path):
    kept = tmp_path / "project"
    kept.mkdir()
    (kept / ".git").mkdir()
    for name in (
        "build", "Debug", "node_modules", ".cache", ".ccache", ".pyenv",
        ".venv", "target", "cmake-build-release",
    ):
        nested = tmp_path / name / "accidental-repo"
        nested.mkdir(parents=True)
        (nested / ".git").mkdir()

    assert discover_git_roots([tmp_path], max_depth=5) == [kept]


def test_explicit_artifact_named_git_root_can_still_be_inspected(tmp_path):
    explicit = tmp_path / "build"
    explicit.mkdir()
    (explicit / ".git").mkdir()
    assert discover_git_roots([explicit], max_depth=1) == [explicit]


def test_git_discovery_never_walks_a_broad_system_root():
    assert discover_git_roots([Path("/")], max_depth=20) == []


def test_candidate_policy_rejects_unknown_or_mistyped_fields():
    with pytest.raises(ValueError, match="unknown"):
        validate_policy({"policy_format": "codess.candidate-policy/1", "worthy": True})
    with pytest.raises(ValueError, match="nonnegative integer"):
        validate_policy({"policy_format": "codess.candidate-policy/1", "min_sessions": True})


def test_empty_workspace_trace_is_not_cross_vendor_session_evidence(tmp_path):
    result = recommend({
        "path": str(tmp_path), "curation": {},
        "observations": {
            "session_count": 1,
            "vendors": {
                "Codex": {"sessions": 1},
                "Cursor": {"sessions": 0, "workspace_trace": True},
            },
        },
    })
    assert result["outcome"] == "consider"
    assert "cross_vendor_evidence" not in result["reasons"]


def test_decision_and_plan_only_onboarding_do_not_ingest(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    catalog = tmp_path / "catalog.json"
    write_json_atomic(catalog, {
        "catalog_format": "codess.catalog/1",
        "projects": [{
            "project_id": "p1", "path": str(project),
            "review": {"decision": None},
        }],
    })
    record_decision(
        catalog, project_ref="p1", decision="approved", reviewer="tester", notes="ok"
    )
    receipt = onboard_catalog(
        catalog, registry=tmp_path / "registry", repo_root=Path(__file__).parents[1],
        stop_after="plan", source="cursor", raw_mode="capture",
    )
    assert receipt["status"] == "planned"
    assert receipt["plan"]["projects"][0]["project_id"] == "p1"
    assert receipt["plan"]["projects"][0]["source"] == "cursor"
    assert receipt["plan"]["raw_mode"] == "capture"
    assert len(receipt["plan"]["package_digest"]) == 64
    assert not (project / ".codess").exists()


def test_location_add_retire_and_conflict(tmp_path):
    registry = tmp_path / "registry"
    first = tmp_path / "first"
    first.mkdir()
    binding = ensure_project_binding(registry, first)
    second = tmp_path / "second"
    second.mkdir()
    added = add_project_location(registry, binding["project_id"], second)
    assert added["state"] == "active"
    retired = retire_project_location(registry, binding["project_id"], first)
    assert retired["state"] == "retired"
    states = {item["path"]: item["state"] for item in get_project_entry(registry, binding["project_id"])["locations"]}
    assert states[str(first.resolve())] == "retired"
    other = tmp_path / "other"
    other.mkdir()
    other_binding = ensure_project_binding(registry, other)
    with pytest.raises(ValueError, match="another Project"):
        add_project_location(registry, other_binding["project_id"], second)


def test_schema_evolution_package_and_admin_dispatch(tmp_path, capsys):
    old = {"format_id": "x", "application_id": 1, "entities": {}, "vocabularies": {}}
    new = {**old, "entities": {"new": {"fields": {}}}}
    findings = list(compare(old, new))
    assert required(findings) == "compatible"
    old_path, new_path = tmp_path / "old.json", tmp_path / "new.json"
    write_json_atomic(old_path, old)
    write_json_atomic(new_path, new)
    assert parse_and_run(["schema", "compare", str(old_path), str(new_path), "--declared", "compatible"]) == 0
    assert json.loads(capsys.readouterr().out)["required"] == "compatible"


def test_claude_feature_audit_is_structure_only(tmp_path):
    source = tmp_path / "project" / "session.jsonl"
    source.parent.mkdir()
    source.write_text(
        json.dumps({
            "type": "assistant", "parentUuid": "p", "isSidechain": True,
            "version": "1.2.3", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "text": "secret body"}
            ]},
        }) + "\n",
        encoding="utf-8",
    )
    report = audit_claude_features(tmp_path)
    assert report["content_block_types"] == {"tool_use": 1}
    assert report["parent_links"] == 1
    assert "secret body" not in json.dumps(report)


def test_freeze_revalidates_verifies_and_rolls_back_reviewed_baseline(
    tmp_path, monkeypatch,
):
    project, registry, project_id = _captured_project(tmp_path)
    policy_path = tmp_path / "policy.json"
    write_json_atomic(policy_path, {"policy_format": "codess.validation-policy/1"})
    validation = validate_project(
        project, policy={"policy_format": "codess.validation-policy/1"},
        raw_store_root=registry / "raw",
    )
    assert validation["status"] == "accepted", validation["errors"]
    write_json_atomic(project / ".codess/validation-report.json", {
        "status": "accepted", "final_validation": validation,
        "fixed_point": {"passed": True},
    })
    approved, reviewed = tmp_path / "approved.json", tmp_path / "reviewed.json"
    result = freeze_reviewed_catalogs(
        {"projects": [{"path": str(project), "policy": str(policy_path)}]},
        approved_path=approved, reviewed_path=reviewed,
        repo_root=Path(__file__).parents[1],
    )
    assert result["verification"]["status"] == "verified"
    assert read_json(approved)["projects"][0]["project_id"] == project_id
    assert verify_reviewed_catalog(
        reviewed, repo_root=Path(__file__).parents[1]
    )["status"] == "verified"
    prior_approved, prior_reviewed = approved.read_bytes(), reviewed.read_bytes()
    monkeypatch.setattr(
        "codess.baseline_catalog.verify_reviewed_catalog",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("post-write failure")),
    )
    with pytest.raises(RuntimeError, match="post-write failure"):
        freeze_reviewed_catalogs(
            {"projects": [{"path": str(project), "policy": str(policy_path)}]},
            approved_path=approved, reviewed_path=reviewed,
            repo_root=Path(__file__).parents[1],
        )
    assert approved.read_bytes() == prior_approved
    assert reviewed.read_bytes() == prior_reviewed


def test_relocation_rolls_back_catalog_and_pointer_on_verification_failure(
    tmp_path, monkeypatch,
):
    project, registry, project_id = _captured_project(tmp_path)
    before = (registry / "projects.json").read_bytes()
    replacement = tmp_path / "replacement"
    monkeypatch.setattr("codess.catalog_operations.current_store_paths", lambda path: [])
    with pytest.raises(RuntimeError, match="cannot read"):
        relocate_project(registry, project_id, project, replacement)
    assert (registry / "projects.json").read_bytes() == before
    assert not (replacement / ".codess/current.json").exists()


def test_fixed_point_reset_discards_only_rebuildable_working_stores(tmp_path):
    project, _, _ = _captured_project(tmp_path)
    working = project / ".codess/sessions_codex.db"
    assert working.exists()
    (Path(str(working) + "-journal")).write_bytes(b"derived")
    removed = reset_rebuildable_working_stores(project)
    assert removed == ["sessions_codex.db"]
    assert not working.exists()
    assert not Path(str(working) + "-journal").exists()
    assert (project / ".codess/current.json").exists()
