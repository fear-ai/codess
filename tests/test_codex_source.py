"""Codex transcript inventory, cache invalidation, and Project selection."""

import json
import os

from codess.codex_source import build_session_index, get_session_files


def test_empty_when_no_root(tmp_path, monkeypatch):
    monkeypatch.setattr("codess.codex_source.CODEX_SESSIONS", tmp_path / "missing")
    monkeypatch.setattr("codess.codex_source.CODEX_ARCHIVED_SESSIONS", None)
    project = tmp_path / "project"
    project.mkdir()
    assert get_session_files(project) == []


def test_matches_project_cwd(tmp_path, monkeypatch):
    sessions = tmp_path / "codex"
    transcript_dir = sessions / "2024" / "01"
    transcript_dir.mkdir(parents=True)
    project = tmp_path / "project"
    project.mkdir()
    transcript = transcript_dir / "rollout.jsonl"
    transcript.write_text(
        json.dumps({"type": "session_meta", "payload": {"cwd": str(project)}}) + "\n"
    )
    monkeypatch.setattr("codess.codex_source.CODEX_SESSIONS", sessions)
    monkeypatch.setattr("codess.codex_source.CODEX_ARCHIVED_SESSIONS", None)
    assert get_session_files(project) == [transcript]


def test_active_wins_over_archived_duplicate(tmp_path, monkeypatch):
    active = tmp_path / "sessions"
    archived = tmp_path / "archived_sessions"
    active.mkdir()
    archived.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    record = json.dumps({
        "type": "session_meta",
        "payload": {"id": "same-id", "cwd": str(project)},
    }) + "\n"
    active_file = active / "active.jsonl"
    archived_file = archived / "archived.jsonl"
    active_file.write_text(record)
    archived_file.write_text("not json\n" + record)
    monkeypatch.setattr("codess.codex_source.CODEX_SESSIONS", active)
    monkeypatch.setattr("codess.codex_source.CODEX_ARCHIVED_SESSIONS", archived)
    assert get_session_files(project) == [active_file]


def test_archived_session_is_selected_when_not_active(tmp_path, monkeypatch):
    active = tmp_path / "sessions"
    archived = tmp_path / "archived_sessions"
    active.mkdir()
    archived.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    transcript = archived / "archived.jsonl"
    transcript.write_text(
        "not json\n" + json.dumps({
            "type": "session_meta",
            "payload": {"id": "archived", "cwd": str(project)},
        }) + "\n"
    )
    monkeypatch.setattr("codess.codex_source.CODEX_SESSIONS", active)
    monkeypatch.setattr("codess.codex_source.CODEX_ARCHIVED_SESSIONS", archived)
    assert get_session_files(project) == [transcript]


def test_index_updates_changed_and_drops_removed(tmp_path, monkeypatch):
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    first_project = tmp_path / "project-a"
    second_project = tmp_path / "project-b"
    first_project.mkdir()
    second_project.mkdir()
    transcript = sessions / "rollout.jsonl"
    transcript.write_text(
        json.dumps({
            "type": "session_meta",
            "payload": {"id": "one", "cwd": str(first_project)},
        }) + "\n" + json.dumps({"type": "event_msg"}) + "\n"
    )
    monkeypatch.setattr("codess.codex_source.CODEX_SESSIONS", sessions)
    monkeypatch.setattr("codess.codex_source.CODEX_ARCHIVED_SESSIONS", None)
    cache = tmp_path / "registry" / "cache.json"

    first = build_session_index(cache_path=cache, include_record_counts=True)
    assert first[0]["cwd"] == str(first_project)
    assert first[0]["record_count"] == 2

    before = transcript.stat()
    transcript.write_text(
        json.dumps({
            "type": "session_meta",
            "payload": {"id": "one", "cwd": str(second_project)},
        }) + "\n"
    )
    os.utime(
        transcript,
        ns=(transcript.stat().st_atime_ns, before.st_mtime_ns + 1_000_000),
    )
    second = build_session_index(cache_path=cache, include_record_counts=True)
    assert second[0]["cwd"] == str(second_project)
    assert second[0]["record_count"] == 1

    transcript.unlink()
    assert build_session_index(cache_path=cache) == []
    assert json.loads(cache.read_text())["files"] == []
