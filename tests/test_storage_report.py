"""Storage observation, utilization, skew, and history deltas."""

import json
import sqlite3

from codess.storage_report import build_storage_report, inspect_sqlite


def _store(path, sessions=1, events=3):
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE sessions(id TEXT PRIMARY KEY, session_entity_id TEXT, source TEXT);
        CREATE TABLE interactions(id TEXT);
        CREATE TABLE events(
          id INTEGER PRIMARY KEY, session_id TEXT, event_kind TEXT,
          event_type TEXT, subtype TEXT, content TEXT, content_len INTEGER,
          tool_input TEXT, tool_output TEXT
        );
    """)
    for index in range(sessions):
        conn.execute(
            "INSERT INTO sessions VALUES (?, ?, 'Claude')",
            (f"s{index}", f"global-{index}"),
        )
    for index in range(events):
        kind = "message.prompt" if index % 2 == 0 else "message.response"
        event_type = "user_message" if index % 2 == 0 else "assistant_message"
        conn.execute(
            "INSERT INTO events(session_id,event_kind,event_type,subtype,content,content_len) "
            "VALUES ('s0',?,?,?,?,?)",
            (kind, event_type, "prompt" if index % 2 == 0 else "response", "text", 4),
        )
    conn.commit()
    conn.close()


def test_inspect_sqlite_reports_text_and_skew(tmp_path):
    db = tmp_path / "sessions_cc.db"
    _store(db, sessions=2, events=5)
    report = inspect_sqlite(db)
    assert report["counts"]["sessions"] == 2
    assert report["counts"]["events"] == 5
    assert report["text"]["prompts"]["records"] == 3
    assert report["text"]["responses"]["records"] == 2
    assert report["session_skew"]["sessions_with_at_most_two_events"] == 1
    assert report["tokens"]["availability"] == "not_normalized"
    assert 0 < report["pages"]["utilization_ratio"] <= 1


def test_report_records_observations_and_deltas(tmp_path):
    registry = tmp_path / "registry"
    snapshot = registry / "projects" / "project" / "snapshots" / "one"
    snapshot.mkdir(parents=True)
    _store(snapshot / "sessions_cc.db")
    pointer = snapshot.parents[1] / "current.json"
    pointer.write_text(json.dumps({"path": str(snapshot)}))
    history = registry / "history"

    first = build_storage_report(registry, history_dir=history)
    assert first["totals"]["events"] == 3
    assert len(list(history.glob("*.json"))) == 1

    conn = sqlite3.connect(snapshot / "sessions_cc.db")
    conn.execute(
        "INSERT INTO events(session_id,event_kind,event_type,subtype,content,content_len) "
        "VALUES ('s0','message.response','assistant_message','response','more',4)"
    )
    conn.commit()
    conn.close()
    second = build_storage_report(registry, history_dir=history)
    assert second["delta"]["events"] == 1
    assert second["previous_observed_at"] == first["observed_at"]


def test_size_threshold_warnings(tmp_path):
    registry = tmp_path / "registry"
    snapshot = registry / "projects" / "project" / "snapshots" / "one"
    snapshot.mkdir(parents=True)
    db = snapshot / "sessions_cc.db"
    _store(db)
    (snapshot.parents[1] / "current.json").write_text(json.dumps({"path": str(snapshot)}))
    report = build_storage_report(
        registry, history_dir=registry / "history", codess_limit=1,
    )
    assert report["warnings"][0]["kind"] == "codess_db_size"
