import json

from codess.codex_parent_audit import audit_parentage


def _write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"type": "session_meta", "payload": payload}) + "\n")


def test_parent_audit_resolves_only_explicit_parent_fields(tmp_path):
    root = tmp_path / "sessions"
    _write(root / "parent.jsonl", {"id": "parent", "cli_version": "1"})
    _write(root / "child.jsonl", {
        "id": "child", "cli_version": "2",
        "source": {"subagent": {"thread_spawn": {"parent_thread_id": "parent"}}},
    })
    report = audit_parentage([("active", root)])
    assert report["support_status"] == "supported"
    assert report["resolved_parent_references"] == 1


def test_parent_audit_does_not_infer_from_other_metadata(tmp_path):
    root = tmp_path / "sessions"
    _write(root / "one.jsonl", {
        "id": "one", "cli_version": "1", "cwd": "/repo", "originator": "codex",
    })
    report = audit_parentage([("active", root)])
    assert report["support_status"] == "not_observed"
    assert report["parent_candidate_fields"] == []
