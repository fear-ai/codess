"""Administrative workflow operations and grouped command dispatch."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from codess.baseline_catalog import freeze_reviewed_catalogs, verify_reviewed_catalog
from codess.baseline_operations import (
    apply_project,
    reset_rebuildable_working_stores,
    run_ingest,
)
from codess.baseline_validation import validate_project
from codess.catalog_operations import (
    _run_ingest_stage,
    onboard_catalog,
    relocate_project,
    retire_location,
)
from codess.fileio import hash_file, read_json, write_json_atomic
from codess.project import parse_and_run
from codess.project_catalog import (
    add_project_location,
    durable_project_root,
    ensure_project_binding,
    get_project_entry,
    retire_project_location,
    set_project_selection_state,
)
from codess.raw_store import RawStore
from codess.review_project import (
    discover_git_roots,
    observe_git,
    recommend,
    record_decision,
    refresh_candidates,
    validate_policy,
)
from codess.schema_evolution import compare, required
from codess.session_names import (
    alias_index,
    remove_session_name,
    set_session_name,
)
from codess.snapshot import create_snapshot, current_raw_records, publish_snapshot
from codess.store import connect, init_db, replace_session_events, sync_project_catalog
from codess.vendor_audits.claude_features import audit_claude_features
from codess.vendor_audits.codex_features import audit_codex_features


def _git_project(path: Path) -> None:
    path.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    (path / "README.md").write_text("test\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "initial"], cwd=path, check=True)


def test_admin_ingest_paths_forward_resource_policy(tmp_path, monkeypatch):
    calls = []

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(command, **kwargs):
        calls.append(command)
        return Result()

    monkeypatch.setattr(
        "codess.baseline_operations.subprocess.run", fake_run
    )
    policy = tmp_path / "resources.json"
    run_ingest(
        tmp_path / "project",
        source="all",
        raw_mode="reference",
        registry=tmp_path / "registry",
        min_size=0,
        repo_root=tmp_path,
        resource_policy=policy,
    )
    assert calls[0][-2:] == ["--resource-policy", str(policy)]

    calls.clear()
    monkeypatch.setattr(
        "codess.catalog_operations.subprocess.run", fake_run
    )
    _run_ingest_stage(
        {"projects": [{"path": str(tmp_path / "project")}]},
        validate=True,
        source="all",
        raw_mode="reference",
        registry=tmp_path / "registry",
        repo_root=tmp_path,
        resource_policy=policy,
    )
    assert ["--resource-policy", str(policy)] == calls[0][-3:-1]
    assert calls[0][-1] == "--validate"


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


def test_session_names_resolve_prefix_without_replacing_identity(tmp_path):
    _project, registry, project_id = _captured_project(tmp_path)

    named = set_session_name(registry, project_id, "s1", "slash_model")
    assert named["name"] == "slash_model"
    assert named["session_entity_id"].startswith("codess:session:")
    assert alias_index(registry)[
        (project_id, named["session_entity_id"])
    ] == "slash_model"

    removed = remove_session_name(registry, project_id, "s1")
    assert removed["session_entity_id"] == named["session_entity_id"]
    assert alias_index(registry) == {}


def test_session_name_registry_rejects_session_id_as_the_mapping_field(
    tmp_path,
):
    write_json_atomic(tmp_path / "session-names.json", {
        "format": "codess.session-names/1",
        "names": [{
            "project_id": "codess:project:p",
            "session_id": "codess:session:s",
            "name": "old-shape",
            "source": "user_alias",
        }],
    })
    with pytest.raises(ValueError, match="session_entity_id"):
        alias_index(tmp_path)


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
        "codess.review_project.walk_sessions",
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
    assert item["observations"]["git"]["worktree"]["is_linked"] is False
    assert item["observations"]["git"]["commits_since"] == 1


def test_git_observation_identifies_linked_worktree_and_common_repository(tmp_path):
    primary = tmp_path / "primary"
    linked = tmp_path / "linked"
    _git_project(primary)
    subprocess.run(
        ["git", "worktree", "add", "-qb", "performance", str(linked)],
        cwd=primary,
        check=True,
    )
    primary_observation = observe_git(primary)
    linked_observation = observe_git(linked)
    assert primary_observation["worktree"]["is_linked"] is False
    assert linked_observation["worktree"]["is_linked"] is True
    assert linked_observation["worktree"]["branch"] == "performance"
    assert (
        linked_observation["worktree"]["common_git_dir"]
        == primary_observation["worktree"]["common_git_dir"]
    )
    assert (
        linked_observation["worktree"]["git_dir"]
        != primary_observation["worktree"]["git_dir"]
    )


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


def test_excluded_project_can_retire_its_last_location(tmp_path):
    registry = tmp_path / "registry"
    project = tmp_path / "deleted-later"
    project.mkdir()
    binding = ensure_project_binding(registry, project)
    set_project_selection_state(
        registry, binding["project_id"], "excluded", note="temporary test path"
    )

    result = retire_location(registry, binding["project_id"], project)

    assert result["state"] == "retired"
    location = get_project_entry(registry, binding["project_id"])["locations"][0]
    assert location["state"] == "retired"
    assert location["path_obsolete"] is True


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
        "\n".join((json.dumps({
            "type": "assistant", "parentUuid": "p", "isSidechain": True,
            "version": "1.2.3", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "text": "secret body"}
            ]},
        }), json.dumps({
            "type": "system", "subtype": "compact_boundary", "uuid": "b",
            "compactMetadata": {"trigger": "auto", "preTokens": 100},
        }), json.dumps({
            "type": "user", "isCompactSummary": True, "parentUuid": "b",
            "message": {"role": "user", "content": "private compact body"},
        }))) + "\n",
        encoding="utf-8",
    )
    report = audit_claude_features(tmp_path)
    assert report["content_block_types"] == {"tool_use": 1}
    assert report["parent_links"] == 2
    assert report["compaction_evidence"] == {
        "compact_boundaries": 1,
        "compact_summaries": 1,
        "summaries_with_parent_uuid": 1,
        "summary_characters": 20,
        "maximum_summary_characters": 20,
        "triggers": {"auto": 1},
        "compact_metadata_fields": {"trigger": 1, "preTokens": 1},
    }
    assert "secret body" not in json.dumps(report)
    assert "private compact body" not in json.dumps(report)


def test_codex_feature_audit_is_bounded_and_tracks_setting_provenance(tmp_path):
    root = tmp_path / "sessions"
    root.mkdir()
    source = root / "session.jsonl"
    source.write_text("\n".join((
        json.dumps({
            "type": "turn_context",
            "payload": {"model": "gpt-test", "effort": "high",
                        "user_instructions": "secret body"},
        }),
        json.dumps({
            "type": "event_msg",
            "payload": {"type": "thread_settings_applied", "thread_settings": {
                "model": "gpt-test", "reasoning_effort": "medium",
                "service_tier": "priority",
                "collaboration_mode": {"mode": "default"},
            }},
        }),
        json.dumps({"type": "response_item", "payload": {
            "type": "message", "content": "x" * 4096,
        }}),
    )) + "\n", encoding="utf-8")
    report = audit_codex_features(
        [("active", root)], max_record_bytes=1024
    )
    assert report["diagnostics"] == {"oversize": 1}
    assert report["model_settings"]["service_tier"] == {"priority": 1}
    assert report["model_settings"]["reasoning_effort"] == {
        "high": 1, "medium": 1,
    }
    assert any("thread_settings_applied" in key for key in report["setting_provenance"])
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


def test_freeze_preserves_explicit_accepted_with_limitations_state(
    tmp_path, monkeypatch,
):
    project, registry, _ = _captured_project(tmp_path)
    policy_path = tmp_path / "policy.json"
    write_json_atomic(
        policy_path, {"policy_format": "codess.validation-policy/1"}
    )
    validation = validate_project(
        project,
        policy={"policy_format": "codess.validation-policy/1"},
        raw_store_root=registry / "raw",
    )
    validation["status"] = "accepted_with_limitations"
    validation["limitations"] = ["reference-only fixture"]
    write_json_atomic(project / ".codess/validation-report.json", {
        "status": "accepted_with_limitations",
        "final_validation": validation,
        "fixed_point": {"passed": True},
    })
    monkeypatch.setattr(
        "codess.baseline_catalog.validate_project",
        lambda *args, **kwargs: dict(validation),
    )
    approved, reviewed = tmp_path / "approved.json", tmp_path / "reviewed.json"
    result = freeze_reviewed_catalogs(
        {"projects": [{"path": str(project), "policy": str(policy_path)}]},
        approved_path=approved,
        reviewed_path=reviewed,
        repo_root=Path(__file__).parents[1],
    )
    assert result["verification"]["status"] == "verified"
    assert read_json(approved)["projects"][0]["validation_state"] == (
        "accepted_with_limitations"
    )
    assert read_json(reviewed)["projects"][0]["validation_state"] == (
        "accepted_with_limitations"
    )


def test_reviewed_baseline_verifies_its_exact_retained_snapshot_after_current_advances(
    tmp_path,
):
    project, registry, project_id = _captured_project(tmp_path)
    policy_path = tmp_path / "policy.json"
    policy = {"policy_format": "codess.validation-policy/1"}
    write_json_atomic(policy_path, policy)
    validation = validate_project(
        project, policy=policy, raw_store_root=registry / "raw",
    )
    write_json_atomic(project / ".codess/validation-report.json", {
        "status": "accepted", "final_validation": validation,
        "fixed_point": {"passed": True},
    })
    approved, reviewed = tmp_path / "approved.json", tmp_path / "reviewed.json"
    freeze_reviewed_catalogs(
        {"projects": [{"path": str(project), "policy": str(policy_path)}]},
        approved_path=approved, reviewed_path=reviewed,
        repo_root=Path(__file__).parents[1],
    )
    reviewed_snapshot = read_json(reviewed)["projects"][0]["snapshot_id"]

    store = project / ".codess/sessions_codex.db"
    conn = connect(store)
    try:
        conn.execute("UPDATE events SET content='later' WHERE event_id='e1'")
        conn.commit()
    finally:
        conn.close()
    create_snapshot(
        project, [store], current_raw_records(project),
        raw_store=RawStore(registry / "raw"),
        build_policy={"raw_mode": "capture"},
        registry_root=registry, project_id=project_id,
    )
    assert read_json(project / ".codess/current.json")["snapshot_id"] != (
        reviewed_snapshot
    )

    result = verify_reviewed_catalog(
        reviewed, repo_root=Path(__file__).parents[1]
    )
    assert result["projects"][0]["snapshot_id"] == reviewed_snapshot
    assert result["projects"][0]["project_id"] == project_id


def test_relocation_rolls_back_catalog_and_pointer_on_verification_failure(
    tmp_path, monkeypatch,
):
    project, registry, project_id = _captured_project(tmp_path)
    before = (registry / "projects.json").read_bytes()
    replacement = tmp_path / "replacement"
    monkeypatch.setattr("codess.catalog_operations.current_stores", lambda path: [])
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


def test_candidate_snapshot_does_not_publish_before_validation(tmp_path, monkeypatch):
    project, registry, project_id = _captured_project(tmp_path)
    local_pointer = project / ".codess/current.json"
    central_pointer = durable_project_root(registry, project_id) / "current.json"
    prior_local = local_pointer.read_bytes()
    prior_central = central_pointer.read_bytes()
    store = project / ".codess/sessions_codex.db"
    candidate = create_snapshot(
        project,
        [store],
        current_raw_records(project),
        raw_store=RawStore(registry / "raw"),
        registry_root=registry,
        project_id=project_id,
        publish=False,
    )
    monkeypatch.setattr(
        "codess.baseline_operations.archive_stale_working_stores",
        lambda *args: None,
    )
    monkeypatch.setattr(
        "codess.baseline_operations.reset_rebuildable_working_stores",
        lambda *args: [],
    )
    monkeypatch.setattr(
        "codess.baseline_operations.run_ingest",
        lambda *args, **kwargs: {
            "returncode": 0,
            "stdout": "",
            "stderr": "",
            "candidate_snapshot_path": str(candidate),
        },
    )
    monkeypatch.setattr(
        "codess.baseline_operations.validate_project",
        lambda *args, **kwargs: {
            "status": "rejected",
            "errors": ["injected policy failure"],
        },
    )

    with pytest.raises(RuntimeError, match="first validation rejected"):
        apply_project(
            project,
            source="all",
            raw_mode="capture",
            registry=registry,
            policy_path=None,
            repeat=False,
            approve_catalog=None,
            min_size=0,
            query_smoke=False,
            repo_root=Path(__file__).parents[1],
        )

    assert local_pointer.read_bytes() == prior_local
    assert central_pointer.read_bytes() == prior_central
    assert candidate.is_dir()


def test_pointer_pair_publication_rolls_back_on_second_replace(
    tmp_path, monkeypatch,
):
    project, registry, project_id = _captured_project(tmp_path)
    local_pointer = project / ".codess/current.json"
    central_pointer = durable_project_root(registry, project_id) / "current.json"
    prior_local = local_pointer.read_bytes()
    prior_central = central_pointer.read_bytes()
    candidate = create_snapshot(
        project,
        [project / ".codess/sessions_codex.db"],
        current_raw_records(project),
        raw_store=RawStore(registry / "raw"),
        registry_root=registry,
        project_id=project_id,
        publish=False,
    )
    calls = 0

    def fail_second(source, target):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected second-pointer failure")
        source.replace(target)

    monkeypatch.setattr("codess.snapshot._replace_pointer", fail_second)
    with pytest.raises(Exception, match="prior pointers restored"):
        publish_snapshot(
            project,
            candidate,
            registry_root=registry,
            project_id=project_id,
        )

    assert local_pointer.read_bytes() == prior_local
    assert central_pointer.read_bytes() == prior_central
    assert candidate.is_dir()


def test_repeat_build_failure_leaves_prior_pointers_current(
    tmp_path, monkeypatch,
):
    project, registry, project_id = _captured_project(tmp_path)
    local_pointer = project / ".codess/current.json"
    central_pointer = durable_project_root(registry, project_id) / "current.json"
    prior_local = local_pointer.read_bytes()
    prior_central = central_pointer.read_bytes()
    candidate = create_snapshot(
        project,
        [project / ".codess/sessions_codex.db"],
        current_raw_records(project),
        raw_store=RawStore(registry / "raw"),
        registry_root=registry,
        project_id=project_id,
        publish=False,
    )
    ingests = iter((
        {
            "returncode": 0,
            "stdout": "",
            "stderr": "",
            "candidate_snapshot_path": str(candidate),
        },
        {
            "returncode": 1,
            "stdout": "",
            "stderr": "injected repeat failure",
            "candidate_snapshot_path": None,
        },
    ))
    monkeypatch.setattr(
        "codess.baseline_operations.archive_stale_working_stores",
        lambda *args: None,
    )
    monkeypatch.setattr(
        "codess.baseline_operations.reset_rebuildable_working_stores",
        lambda *args: [],
    )
    monkeypatch.setattr(
        "codess.baseline_operations.run_ingest",
        lambda *args, **kwargs: next(ingests),
    )
    monkeypatch.setattr(
        "codess.baseline_operations.validate_project",
        lambda *args, **kwargs: {
            "status": "accepted",
            "snapshot_id": candidate.name,
            "project_id": project_id,
            "source_revisions": [],
            "semantic_digest": "one",
            "normalization_digest": "one",
        },
    )

    with pytest.raises(RuntimeError, match="repeat ingest failed"):
        apply_project(
            project,
            source="all",
            raw_mode="capture",
            registry=registry,
            policy_path=None,
            repeat=True,
            approve_catalog=None,
            min_size=0,
            query_smoke=False,
            repo_root=Path(__file__).parents[1],
        )

    assert local_pointer.read_bytes() == prior_local
    assert central_pointer.read_bytes() == prior_central
    assert candidate.is_dir()


def test_fixed_point_with_allowed_source_drift_does_not_recheck_live_reference(
    tmp_path, monkeypatch,
):
    project = tmp_path / "project"
    (project / ".codess").mkdir(parents=True)
    validations = iter((
        {
            "status": "accepted_with_limitations",
            "snapshot_id": "snapshot-one",
            "source_revisions": ["revision-one"],
            "semantic_digest": "semantic-one",
            "normalization_digest": "normalized",
        },
        {
            "status": "accepted_with_limitations",
            "snapshot_id": "snapshot-two",
            "source_revisions": ["revision-two"],
            "semantic_digest": "semantic-two",
            "normalization_digest": "normalized",
        },
    ))
    reference_checks = []

    monkeypatch.setattr(
        "codess.baseline_operations.load_policy",
        lambda _path: {
            "allow_source_revision_drift": True,
            "require_fixed_point": True,
        },
    )
    candidates = iter((
        tmp_path / "registry/projects/p/snapshots/snapshot-one",
        tmp_path / "registry/projects/p/snapshots/snapshot-two",
    ))
    monkeypatch.setattr(
        "codess.baseline_operations.run_ingest",
        lambda *args, **kwargs: {
            "returncode": 0, "stdout": "", "stderr": "",
            "candidate_snapshot_path": str(next(candidates)),
        },
    )
    monkeypatch.setattr(
        "codess.baseline_operations.reset_rebuildable_working_stores",
        lambda _project: [],
    )
    value_acceptance = {
        "accepted": True, "fatal": [], "fatal_count": 0,
        "advisory": [], "advisory_count": 0, "match_count": 10,
        "examples_truncated": False,
    }
    monkeypatch.setattr(
        "codess.baseline_operations.snapshot_store_paths_from_base",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        "codess.baseline_operations.compare_snapshots",
        lambda *args, **kwargs: value_acceptance,
    )

    def fake_validate(*args, **kwargs):
        reference_checks.append(kwargs["verify_reference_current"])
        return next(validations)

    monkeypatch.setattr(
        "codess.baseline_operations.validate_project", fake_validate
    )
    monkeypatch.setattr(
        "codess.baseline_operations.publish_snapshot",
        lambda *args, **kwargs: {"snapshot_id": "snapshot-two"},
    )
    result = apply_project(
        project,
        source="all",
        raw_mode="reference",
        registry=tmp_path / "registry",
        policy_path=tmp_path / "policy.json",
        repeat=True,
        approve_catalog=None,
        min_size=0,
        query_smoke=False,
        repo_root=Path(__file__).parents[1],
    )
    assert reference_checks == [False, False]
    assert result["fixed_point"] == {
        "source_revisions_match": False,
        "semantic_digest_match": False,
        "normalization_digest_match": True,
        "value_acceptance": value_acceptance,
        "passed": True,
    }


def test_a_working_archive_is_named_the_instant_its_manifest_reports(tmp_path):
    """One archival event, one instant.

    The archive directory name and the manifest's `archived_at` render the
    same moment. They were separate clock reads, so the directory an operator
    sorts by could claim a different second than the manifest inside it.
    """
    import json
    from datetime import datetime

    from codess.baseline_operations import archive_stale_working_stores
    from codess.config import CURRENT_POINTER_FILE, STORE_DIR, WORKING_ARCHIVES_DIR
    from codess.raw_store import RawStore
    from codess.snapshot import create_snapshot
    from codess.store import connect, init_db

    project = tmp_path / "project"
    base = project / STORE_DIR
    store = base / "sessions_cc.db"
    init_db(store)

    raw = RawStore(tmp_path / "raw")
    source = tmp_path / "session.jsonl"
    source.write_text('{"type":"user"}\n', encoding="utf-8")
    record = raw.observe(
        source, source_system_id="anthropic.claude-code",
        storage_format="claude-jsonl", mode="capture",
    )
    snapshot = create_snapshot(project, [store], [record], raw_store=raw)
    assert (base / CURRENT_POINTER_FILE).exists(), snapshot

    # Make the working store claim a package the release no longer matches,
    # which is the condition the archival exists for.
    conn = connect(store)
    try:
        conn.execute(
            "UPDATE store_meta SET value=? WHERE key='package_digest'", ("f" * 64,),
        )
        conn.commit()
    finally:
        conn.close()

    destination = archive_stale_working_stores(project)
    assert destination is not None
    assert destination.parent.name == WORKING_ARCHIVES_DIR
    manifest = json.loads((destination / "archive.json").read_text(encoding="utf-8"))
    archived_at = datetime.fromisoformat(manifest["archived_at"])
    assert destination.name.endswith(archived_at.strftime("%Y%m%dT%H%M%SZ"))


def test_package_verify_reports_both_digests_and_what_each_covers():
    """Exact package verification has a named consumer now that the gate does not.

    The fixtures are not in the write gate; the guarantee lives here instead, where its
    question -- "is this working tree the reviewed one" -- is the right one to ask.
    """
    import io
    import json
    from contextlib import redirect_stdout

    from cli.admin_cmd import run
    from codess.schema_contract import CONTRACT_ROLES, contract_digest, verify_package

    captured = io.StringIO()
    with redirect_stdout(captured):
        assert run(["package", "verify"]) == 0
    report = json.loads(captured.getvalue())

    assert report["format"] == "codess.package-verification/1"
    assert report["contract_digest"] == contract_digest()
    assert report["package_digest"] == verify_package()
    assert report["contract_digest"] != report["package_digest"]
    assert set(report["contract_files"]) == CONTRACT_ROLES
    assert report["other_files"], "the fixtures outside the gate must be named"
    assert not set(report["other_files"]) & CONTRACT_ROLES
