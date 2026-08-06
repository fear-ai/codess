"""Bounded scale checks for vendor paths that previously grew linearly."""

import json
import sqlite3
import time

from codess.adapters.cursor import _iter_bubbles
from codess.cursor_source import get_db_metrics
from codess.codex_source import get_session_files as get_codex_session_files
from codess.query_api import (
    execute, make_request, selected_project_ids, selected_project_snapshots,
)
from codess.store import connect, init_db, replace_session_events


def test_cursor_large_header_metrics_and_selected_read(tmp_path):
    db = tmp_path / "state.vscdb"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE cursorDiskKV (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute(
        "CREATE TABLE composerHeaders ("
        "composerId TEXT PRIMARY KEY, workspaceId TEXT, createdAt INTEGER, "
        "lastUpdatedAt INTEGER, isArchived INTEGER, isSubagent INTEGER)"
    )
    count = 1_200
    conn.executemany(
        "INSERT INTO cursorDiskKV VALUES (?, ?)",
        (
            (
                f"bubbleId:composer-{index:04d}:bubble",
                json.dumps({"type": 1, "text": f"message-{index}"}),
            )
            for index in range(count)
        ),
    )
    conn.executemany(
        "INSERT INTO composerHeaders VALUES (?, 'workspace', ?, ?, 0, 0)",
        (
            (
                f"composer-{index:04d}",
                1_700_000_000_000 + index,
                1_700_000_001_000 + index,
            )
            for index in range(count)
        ),
    )
    conn.commit()
    conn.close()

    started = time.perf_counter()
    metrics = get_db_metrics(db)
    stats = {}
    selected = list(
        _iter_bubbles(db, stats, composer_ids={"composer-1199"})
    )
    elapsed = time.perf_counter() - started

    assert metrics["count"] == count
    assert metrics["header_count"] == count
    assert metrics["timed_header_count"] == count
    assert selected[0][0] == "composer-1199"
    assert stats["rows"] == 1
    assert elapsed < 5


def test_codex_active_archive_dedup_scales(tmp_path, monkeypatch):
    active = tmp_path / "sessions"
    archived = tmp_path / "archived_sessions"
    project = tmp_path / "project"
    active.mkdir()
    archived.mkdir()
    project.mkdir()
    count = 300
    for index in range(count):
        record = json.dumps({
            "type": "session_meta",
            "payload": {
                "id": f"session-{index:04d}",
                "cwd": str(project),
            },
        }) + "\n"
        (active / f"active-{index:04d}.jsonl").write_text(record)
        (archived / f"archived-{index:04d}.jsonl").write_text(record)

    monkeypatch.setattr("codess.codex_source.CODEX_SESSIONS", active)
    monkeypatch.setattr(
        "codess.codex_source.CODEX_ARCHIVED_SESSIONS", archived
    )
    started = time.perf_counter()
    files = get_codex_session_files(project)
    elapsed = time.perf_counter() - started

    assert len(files) == count
    assert all(path.parent == active for path in files)
    assert elapsed < 5


def test_typed_query_streams_and_orders_beyond_sqlite_attach_limit(tmp_path):
    stores = []
    count = 60
    for index in range(count):
        project = tmp_path / f"project-{index:03d}"
        store = project / ".codess" / "sessions_codex.db"
        init_db(store)
        conn = connect(store)
        replace_session_events(
            conn,
            {
                "id": f"session-{index:03d}",
                "source": "Codex",
                "type": "Code",
                "project_path": str(project),
            },
            [{
                "session_id": f"session-{index:03d}",
                "event_id": f"event-{index:03d}",
                "event_type": "assistant_message",
                "subtype": "response",
                "role": "assistant",
                "content": "bounded",
                "timestamp": (count - index) * 1000,
            }],
            session_id=f"session-{index:03d}",
        )
        conn.execute(
            "INSERT OR REPLACE INTO store_meta(key,value) "
            "VALUES('snapshot_id',?)",
            (f"snapshot-{index:03d}",),
        )
        conn.commit()
        conn.close()
        stores.append({
            "conn": connect(store, read_only=True),
            "path": store,
            "project_path": project,
            "snapshot_id": f"snapshot-{index:03d}",
        })
    try:
        started = time.perf_counter()
        result = execute(
            list(reversed(stores)),
            make_request(
                "events",
                project_ids=selected_project_ids(stores),
                project_snapshots=selected_project_snapshots(stores),
                limit=7,
                byte_limit=1024,
            ),
        )
        elapsed = time.perf_counter() - started
        assert [row["event_at"] for row in result["rows"]] == [
            1000, 2000, 3000, 4000, 5000, 6000, 7000
        ]
        assert result["summary"]["matched_rows_read"] == 7
        assert result["summary"]["returned_content_bytes"] == 49
        assert elapsed < 5
    finally:
        for store in stores:
            store["conn"].close()
