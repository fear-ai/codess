"""Integration tests for ingest and query."""

import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

from cursor_fixtures import create_bubble_table, create_header_table, put_headers
from codess.project import path_to_slug, slug_to_path
from codess.snapshot import current_raw_records


def test_path_to_slug_roundtrip():
    """Slug encode/decode round-trip. Note: slug format uses - as separator, so paths with hyphens are lossy."""

    path = Path("/Users/walter/Work/Spank/spankpy")
    slug = path_to_slug(path)
    assert slug == "-Users-walter-Work-Spank-spankpy"
    back = slug_to_path(slug)
    assert back == path


def test_ingest_invalid_source_is_global_error(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "main",
            "ingest",
            "--dir",
            str(project),
            "--source",
            "bogus",
        ],
        cwd=str(Path(__file__).parent.parent),
        env={**os.environ, "CODESS_REGISTRY": str(tmp_path / "registry")},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "invalid ingest --source" in result.stderr
    assert not (project / ".codess").exists()


def test_sanitize_control_chars():
    """Sanitization strips control chars and ANSI."""
    from codess.sanitize import sanitize_text

    assert sanitize_text("hello\x00world") == "helloworld"
    assert sanitize_text("hello\x1b[31mred\x1b[0m") == "hellored"
    assert sanitize_text("a\r\nb") == "a\nb"  # \r\n normalized to \n


def test_truncate_content():
    """Truncation adds ellipsis and returns full len."""
    from codess.adapters.cc import truncate_content

    short, n = truncate_content("hi", 10)
    assert short == "hi" and n == 2
    long_text = "x" * 100
    truncated, n = truncate_content(long_text, 50)
    assert len(truncated) == 50 and truncated.endswith("…") and n == 100


def test_cc_adapter_iter_and_skip():
    """iter_cc_records and should_skip."""
    from codess.adapters.cc import iter_cc_records, should_skip

    fixtures = Path(__file__).parent / "fixtures" / "sample.jsonl"
    records = list(iter_cc_records(fixtures))
    assert len(records) >= 9  # 9 data lines, progress skipped in processing
    for line_num, record, raw in records:
        assert line_num >= 1
        assert "type" in record
        if record["type"] == "progress":
            assert should_skip(record)
        if record["type"] == "user":
            assert not should_skip(record)


def test_full_ingest_and_query(durable_tmp_path):
    """Full ingest and query cycle with temp CC dir."""
    tmp = durable_tmp_path
    project_path = tmp / "myproj"
    project_path.mkdir()
    (project_path / "main.py").write_text("print('hi')")

    # CC layout: projects_dir / <slug> / *.jsonl
    projects_dir = tmp / "cc_projects"
    projects_dir.mkdir()
    slug = path_to_slug(project_path.resolve())
    session_dir = projects_dir / slug
    session_dir.mkdir(parents=True)
    fixture = Path(__file__).parent / "fixtures" / "sample.jsonl"
    shutil.copy(fixture, session_dir / "test-session.jsonl")

    reg = tmp / "_central_reg"
    reg.mkdir()
    env = os.environ.copy()
    env["CODESS_REGISTRY"] = str(reg)
    env["CODESS_CC_PROJECTS"] = str(projects_dir)

    # Run ingest
    import subprocess
    result = subprocess.run(
        [sys.executable, "-m", "main", "ingest", "--dir", str(project_path), "--force", "--min-size", "0"],
        cwd=str(Path(__file__).parent.parent),
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"ingest failed: {result.stderr}"

    # Run query --tool 0
    result = subprocess.run(
        [sys.executable, "-m", "main", "query", "--dir", str(project_path), "--tool", "0"],
        cwd=str(Path(__file__).parent.parent),
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"query failed: {result.stderr}"
    lines = result.stdout.strip().split("\n")
    assert any("Bash" in line for line in lines)
    assert any("Read" in line for line in lines)

    # Run query --sessions
    result = subprocess.run(
        [sys.executable, "-m", "main", "query", "--dir", str(project_path), "--sessions"],
        cwd=str(Path(__file__).parent.parent),
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "test-session" in result.stdout or "Claude" in result.stdout


def test_cc_ingest_includes_nested_subagent_with_parent_metadata(durable_tmp_path):
    """Nested subagent transcripts become sessions linked to their main session."""
    tmp = durable_tmp_path
    project_path = tmp / "myproj"
    project_path.mkdir()
    projects_dir = tmp / "cc_projects"
    slug_dir = projects_dir / path_to_slug(project_path.resolve())
    nested_dir = slug_dir / "parent-session" / "subagents"
    nested_dir.mkdir(parents=True)
    fixture = Path(__file__).parent / "fixtures" / "sample.jsonl"
    shutil.copy(fixture, slug_dir / "parent-session.jsonl")
    shutil.copy(fixture, nested_dir / "child-session.jsonl")

    env = os.environ.copy()
    env["CODESS_CC_PROJECTS"] = str(projects_dir)
    env["CODESS_REGISTRY"] = str(tmp / "registry")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "main",
            "ingest",
            "--dir",
            str(project_path),
            "--source",
            "cc",
            "--force",
            "--min-size",
            "0",
        ],
        cwd=str(Path(__file__).parent.parent),
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    conn = sqlite3.connect(project_path / ".codess" / "sessions_cc.db")
    try:
        sessions = {
            row[0]: row[1]
            for row in conn.execute("SELECT id, metadata FROM sessions")
        }
        assert set(sessions) == {"parent-session", "child-session"}
        assert sessions["parent-session"] is None
        child_metadata = json.loads(sessions["child-session"])
        assert child_metadata == {
            "is_sidechain": True,
            "parent_session_id": "parent-session",
            "source_relpath": "parent-session/subagents/child-session.jsonl",
        }
        assert conn.execute(
            "SELECT COUNT(*) FROM events WHERE session_id = 'child-session'"
        ).fetchone()[0] > 0
    finally:
        conn.close()


def test_cc_force_reingest_replaces_shortened_transcript(durable_tmp_path):
    tmp_path = durable_tmp_path
    project = tmp_path / "project"
    project.mkdir()
    projects = tmp_path / "claude"
    session_dir = projects / path_to_slug(project.resolve())
    session_dir.mkdir(parents=True)
    transcript = session_dir / "replace-me.jsonl"
    records = [
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": [{"type": "text", "text": "one"}],
            },
        },
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "two"}],
            },
        },
    ]
    env = {
        **os.environ,
        "CODESS_CC_PROJECTS": str(projects),
        "CODESS_REGISTRY": str(tmp_path / "registry"),
    }
    command = [
        sys.executable, "-m", "main", "ingest",
        "--dir", str(project), "--source", "cc",
        "--force", "--min-size", "0",
    ]
    transcript.write_text(
        "".join(json.dumps(record) + "\n" for record in records)
    )
    assert subprocess.run(
        command, cwd=str(Path(__file__).parent.parent), env=env,
        capture_output=True, text=True,
    ).returncode == 0
    transcript.write_text(json.dumps(records[0]) + "\n")
    assert subprocess.run(
        command, cwd=str(Path(__file__).parent.parent), env=env,
        capture_output=True, text=True,
    ).returncode == 0
    with sqlite3.connect(
        project / ".codess" / "sessions_cc.db"
    ) as store:
        assert store.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
        assert store.execute("SELECT content FROM events").fetchone()[0] == "one"


def test_malformed_json_skipped():
    """Malformed JSON lines are skipped; ingest continues."""
    from codess.adapters.cc import iter_cc_records

    fixtures = Path(__file__).parent / "fixtures" / "malformed.jsonl"
    records = list(iter_cc_records(fixtures))
    assert len(records) == 2  # Line 2 is invalid, skipped
    assert records[0][1]["type"] == "user"
    assert records[1][1]["type"] == "assistant"


def test_codex_ingest_and_query(durable_tmp_path):
    """Codex ingest → query cycle with temp Codex dir."""
    tmp = durable_tmp_path
    proj = tmp / "myproj"
    proj.mkdir()
    codex_dir = tmp / "codex" / "sessions" / "2024" / "01"
    codex_dir.mkdir(parents=True)
    sess_file = codex_dir / "rollout-abc.jsonl"
    proj_str = str(proj.resolve())
    sess_file.write_text(
        f'{{"type":"session_meta","payload":{{"id":"s1","cwd":"{proj_str}"}}}}\n'
        '{"type":"response_item","payload":{"type":"message","role":"user","content":[{"type":"input_text","text":"Hi"}]}}\n'
        '{"type":"response_item","payload":{"type":"message","role":"assistant","content":[{"type":"output_text","text":"Hello"}]}}\n'
    )
    reg = tmp / "_central_reg"
    reg.mkdir()
    env = os.environ.copy()
    env["CODESS_REGISTRY"] = str(reg)
    env["CODESS_CODEX_SESSIONS"] = str(tmp / "codex" / "sessions")

    r = subprocess.run(
        [sys.executable, "-m", "main", "ingest", "--dir", str(proj), "--source", "codex", "--force", "--min-size", "0"],
        cwd=str(Path(__file__).parent.parent),
        env=env,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, f"ingest: {r.stderr}"
    assert "2 event" in r.stdout or "2 session" in r.stdout or "1 session" in r.stdout

    r = subprocess.run(
        [sys.executable, "-m", "main", "query", "--dir", str(proj), "--stats"],
        cwd=str(Path(__file__).parent.parent),
        env=env,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0
    assert "Sessions:" in r.stdout and "Events:" in r.stdout


def test_codex_force_reingest_replaces_and_empty_removes_session(durable_tmp_path):
    tmp_path = durable_tmp_path
    project = tmp_path / "project"
    project.mkdir()
    sessions = tmp_path / "codex" / "sessions"
    sessions.mkdir(parents=True)
    transcript = sessions / "rollout.jsonl"
    meta = {
        "type": "session_meta",
        "payload": {"id": "replace-me", "cwd": str(project)},
    }
    user = {
        "type": "response_item",
        "payload": {
            "type": "message", "role": "user",
            "content": [{"type": "input_text", "text": "one"}],
        },
    }
    assistant = {
        "type": "response_item",
        "payload": {
            "type": "message", "role": "assistant",
            "content": [{"type": "output_text", "text": "two"}],
        },
    }
    env = {
        **os.environ,
        "CODESS_CODEX_SESSIONS": str(sessions),
        "CODESS_REGISTRY": str(tmp_path / "registry"),
    }

    def ingest():
        return subprocess.run(
            [
                sys.executable, "-m", "main", "ingest",
                "--dir", str(project), "--source", "codex",
                "--force", "--min-size", "0",
            ],
            cwd=str(Path(__file__).parent.parent),
            env=env,
            capture_output=True,
            text=True,
        )

    transcript.write_text(
        "".join(json.dumps(record) + "\n" for record in (meta, user, assistant))
    )
    assert ingest().returncode == 0
    store = project / ".codess" / "sessions_codex.db"
    with sqlite3.connect(store) as conn:
        assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 2

    transcript.write_text(
        "".join(json.dumps(record) + "\n" for record in (meta, user))
    )
    assert ingest().returncode == 0
    with sqlite3.connect(store) as conn:
        assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
        assert conn.execute("SELECT content FROM events").fetchone()[0] == "one"

    transcript.write_text(json.dumps(meta) + "\n")
    result = ingest()
    assert result.returncode == 0
    assert "empty_sources=1" in result.stderr
    with sqlite3.connect(store) as conn:
        assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0


def test_cursor_ingest_and_query(durable_tmp_path):
    """Cursor ingest from workspace DB → query cycle."""
    import json
    import sqlite3

    tmp = durable_tmp_path
    proj = tmp / "myproj"
    proj.mkdir()
    cursor_base = tmp / "cursor" / "User"
    ws = cursor_base / "workspaceStorage" / "abc123"
    ws.mkdir(parents=True)
    (ws / "workspace.json").write_text(f'{{"folder":{{"path":"{proj}"}}}}')
    db = ws / "state.vscdb"
    conn = sqlite3.connect(db)
    create_bubble_table(conn)
    conn.execute(
        "INSERT INTO cursorDiskKV (key, value) VALUES (?, ?)",
        ("bubbleId:c1:b1", json.dumps({"type": 1, "text": "hi", "createdAt": "2026-07-10T00:00:01Z"})),
    )
    conn.execute(
        "INSERT INTO cursorDiskKV (key, value) VALUES (?, ?)",
        ("bubbleId:c1:b2", json.dumps({"type": 2, "text": "ok", "createdAt": "2026-07-10T00:00:02Z"})),
    )
    conn.commit()
    conn.close()

    reg = tmp / "_central_reg"
    reg.mkdir()
    env = os.environ.copy()
    env["CODESS_REGISTRY"] = str(reg)
    env["CODESS_CURSOR_DATA"] = str(cursor_base)

    r = subprocess.run(
        [sys.executable, "-m", "main", "ingest", "--dir", str(proj), "--source", "cursor", "--force"],
        cwd=str(Path(__file__).parent.parent),
        env=env,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, f"ingest: {r.stderr}"
    assert "1 session" in r.stdout or "2 event" in r.stdout or "session" in r.stdout.lower()

    r = subprocess.run(
        [sys.executable, "-m", "main", "query", "--dir", str(proj), "--stats"],
        cwd=str(Path(__file__).parent.parent),
        env=env,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0
    assert "Sessions:" in r.stdout and "Events:" in r.stdout


def test_cursor_force_reingest_removes_sessions_deleted_from_source(durable_tmp_path):
    tmp_path = durable_tmp_path
    project = tmp_path / "project"
    project.mkdir()
    cursor_base = tmp_path / "cursor" / "User"
    workspace = cursor_base / "workspaceStorage" / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "workspace.json").write_text(
        json.dumps({"folder": {"path": str(project)}})
    )
    db = workspace / "state.vscdb"
    conn = sqlite3.connect(db)
    create_bubble_table(conn)
    conn.executemany(
        "INSERT INTO cursorDiskKV VALUES (?, ?)",
        [
            ("bubbleId:keep:b1", json.dumps({"type": 1, "text": "keep"})),
            ("bubbleId:remove:b1", json.dumps({"type": 1, "text": "remove"})),
        ],
    )
    conn.commit()
    conn.close()
    env = {
        **os.environ,
        "CODESS_CURSOR_DATA": str(cursor_base),
        "CODESS_REGISTRY": str(tmp_path / "registry"),
    }
    command = [
        sys.executable, "-m", "main", "ingest",
        "--dir", str(project), "--source", "cursor", "--force",
    ]
    first = subprocess.run(
        command,
        cwd=str(Path(__file__).parent.parent),
        env=env,
        capture_output=True,
        text=True,
    )
    assert first.returncode == 0

    conn = sqlite3.connect(db)
    conn.execute("DELETE FROM cursorDiskKV WHERE key LIKE 'bubbleId:remove:%'")
    conn.commit()
    conn.close()
    second = subprocess.run(
        command,
        cwd=str(Path(__file__).parent.parent),
        env=env,
        capture_output=True,
        text=True,
    )
    assert second.returncode == 0

    with sqlite3.connect(
        project / ".codess" / "sessions_cursor.db"
    ) as store:
        assert [
            row[0] for row in store.execute("SELECT id FROM sessions")
        ] == ["keep"]


def test_cursor_global_ingest_is_scoped_by_composer_headers(durable_tmp_path):
    """Global Cursor bubbles are ingested only when their header maps to the project."""
    import json
    import sqlite3

    tmp = durable_tmp_path
    proj = tmp / "myproj"
    proj.mkdir()
    cursor_base = tmp / "cursor" / "User"
    ws = cursor_base / "workspaceStorage" / "ws-project"
    ws.mkdir(parents=True)
    (ws / "workspace.json").write_text(f'{{"folder":"file://{proj}"}}')

    global_dir = cursor_base / "globalStorage"
    global_dir.mkdir(parents=True)
    global_db = global_dir / "state.vscdb"
    conn = sqlite3.connect(global_db)
    create_bubble_table(conn)
    create_header_table(conn)
    put_headers(
            conn,
        [
            ("mapped", "ws-project", 1, 2, 0, 0),
            ("other", "ws-other", 1, 2, 0, 0),
        ],
    )
    conn.executemany(
        "INSERT INTO cursorDiskKV VALUES (?, ?)",
        [
            (
                "bubbleId:mapped:b1",
                json.dumps(
                    {
                        "type": 1,
                        "text": "keep",
                        "createdAt": "2026-07-10T00:00:01Z",
                    }
                ),
            ),
            (
                "bubbleId:mapped:b2",
                json.dumps(
                    {
                        "type": 2,
                        "text": "second mapped event",
                        "createdAt": "2026-07-10T00:00:02Z",
                    }
                ),
            ),
            (
                "bubbleId:other:b1",
                json.dumps(
                    {
                        "type": 1,
                        "text": "drop",
                        "createdAt": "2026-07-10T00:00:01Z",
                    }
                ),
            ),
        ],
    )
    conn.commit()
    conn.close()

    reg = tmp / "registry"
    reg.mkdir()
    env = {
        **os.environ,
        "CODESS_REGISTRY": str(reg),
        "CODESS_CURSOR_DATA": str(cursor_base),
    }
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "main",
            "ingest",
            "--dir",
            str(proj),
            "--source",
            "cursor",
            "--force",
        ],
        cwd=str(Path(__file__).parent.parent),
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    store = proj / ".codess" / "sessions_cursor.db"
    conn = sqlite3.connect(store)
    sessions = conn.execute(
        "SELECT id, project_path, metadata FROM sessions ORDER BY id"
    ).fetchall()
    events = conn.execute("SELECT session_id FROM events ORDER BY session_id").fetchall()
    conn.close()
    assert [row[0] for row in sessions] == ["mapped"]
    assert sessions[0][1] == str(proj.resolve())
    assert json.loads(sessions[0][2])["workspace_id"] == "ws-project"
    assert events == [("mapped",), ("mapped",)]


def test_cursor_multi_project_capture_reuses_one_consistent_cohort(durable_tmp_path):
    tmp_path = durable_tmp_path
    projects = [tmp_path / "first", tmp_path / "second"]
    for project in projects:
        project.mkdir()
    cursor_base = tmp_path / "cursor" / "User"
    workspace_root = cursor_base / "workspaceStorage"
    for index, project in enumerate(projects, 1):
        workspace = workspace_root / f"ws-{index}"
        workspace.mkdir(parents=True)
        (workspace / "workspace.json").write_text(
            json.dumps({"folder": project.resolve().as_uri()}), encoding="utf-8"
        )
        if index == 1:
            workspace_db = workspace / "state.vscdb"
            with sqlite3.connect(workspace_db) as conn:
                conn.execute("PRAGMA journal_mode=WAL")
                create_bubble_table(conn)
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            Path(str(workspace_db) + "-wal").unlink(missing_ok=True)
            Path(str(workspace_db) + "-shm").unlink(missing_ok=True)
    global_dir = cursor_base / "globalStorage"
    global_dir.mkdir(parents=True)
    global_db = global_dir / "state.vscdb"
    with sqlite3.connect(global_db) as conn:
        create_bubble_table(conn)
        create_header_table(conn)
        for index in (1, 2):
            put_headers(conn, [(f"composer-{index}", f"ws-{index}", 1, 2, 0, 0)])
            conn.execute(
                "INSERT INTO cursorDiskKV VALUES (?, ?)",
                (
                    f"bubbleId:composer-{index}:prompt",
                    json.dumps({"type": 1, "text": f"prompt {index}"}),
                ),
            )
    registry = tmp_path / "registry"
    command = [sys.executable, "-m", "main", "ingest"]
    for project in projects:
        command.extend(["--dir", str(project)])
    command.extend([
        "--source", "cursor", "--raw-mode", "capture",
    ])
    result = subprocess.run(
        command,
        cwd=str(Path(__file__).parent.parent),
        env={
            **os.environ,
            "CODESS_REGISTRY": str(registry),
            "CODESS_CURSOR_DATA": str(cursor_base),
        },
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "cursor.marker.start" in result.stderr
    assert "raw.sqlite_backup.start" in result.stderr
    assert "cursor.composer.read.done" in result.stderr
    assert "cursor.composer.write.done" in result.stderr
    assert "snapshot.done" in result.stderr

    records = []
    source_rows = []
    for project in projects:
        pointer = json.loads(
            (project / ".codess" / "current.json").read_text(encoding="utf-8")
        )
        snapshot = Path(pointer["path"])
        with (snapshot / "raw-manifest.jsonl").open(encoding="utf-8") as stream:
            records.append([
                json.loads(line) for line in stream
                if '"record_type":"header"' not in line
                and '"record_type": "header"' not in line
            ])
        with sqlite3.connect(project / ".codess" / "sessions_cursor.db") as conn:
            source_rows.append(conn.execute(
                "SELECT source_uri, source_revision, capture_method, consistency "
                "FROM sources WHERE source_uri=?",
                (str(global_db.resolve()),),
            ).fetchone())
    global_records = [
        next(record for record in project_records
             if record.get("source_locator") == str(global_db.resolve()))
        for project_records in records
    ]
    assert global_records[0]["object_id"] == global_records[1]["object_id"]
    assert global_records[0]["object_relpath"] == global_records[1]["object_relpath"]
    assert source_rows[0] == source_rows[1]
    assert source_rows[0][0] == str(global_db.resolve())
    assert source_rows[0][2:] == ("sqlite-backup", "transactional-snapshot")

    pointers_before = [
        (project / ".codess" / "current.json").read_bytes()
        for project in projects
    ]
    # Cursor routinely mutates unrelated global/workbench state. Such a change
    # must not invalidate selected workspace/composer ingestion.
    with sqlite3.connect(global_db) as conn:
        conn.execute("CREATE TABLE unrelatedCursorState(value TEXT)")
        conn.execute("INSERT INTO unrelatedCursorState VALUES ('changed')")
    unchanged = subprocess.run(
        command,
        cwd=str(Path(__file__).parent.parent),
        env={
            **os.environ,
            "CODESS_REGISTRY": str(registry),
            "CODESS_CURSOR_DATA": str(cursor_base),
        },
        capture_output=True,
        text=True,
    )
    assert unchanged.returncode == 0, unchanged.stderr
    assert "Cursor cohort: unchanged" in unchanged.stdout
    assert "cursor.cohort.unchanged" in unchanged.stderr
    assert "cursor.project.unchanged" in unchanged.stderr
    assert "artifact_correlation.start" not in unchanged.stderr
    assert [
        (project / ".codess" / "current.json").read_bytes()
        for project in projects
    ] == pointers_before

    cached = subprocess.run(
        command,
        cwd=str(Path(__file__).parent.parent),
        env={
            **os.environ,
            "CODESS_REGISTRY": str(registry),
            "CODESS_CURSOR_DATA": str(cursor_base),
        },
        capture_output=True,
        text=True,
    )
    assert cached.returncode == 0, cached.stderr
    marker_line = next(
        line for line in cached.stderr.splitlines()
        if "cursor.marker.done" in line
    )
    assert "status=reused" in marker_line
    assert [
        (project / ".codess" / "current.json").read_bytes()
        for project in projects
    ] == pointers_before


def test_cursor_capture_upgrades_an_unchanged_reference_snapshot(durable_tmp_path):
    tmp_path = durable_tmp_path
    project = tmp_path / "project"
    project.mkdir()
    cursor_base = tmp_path / "cursor" / "User"
    workspace = cursor_base / "workspaceStorage" / "ws-project"
    workspace.mkdir(parents=True)
    (workspace / "workspace.json").write_text(
        json.dumps({"folder": project.resolve().as_uri()}), encoding="utf-8"
    )
    global_dir = cursor_base / "globalStorage"
    global_dir.mkdir(parents=True)
    global_db = global_dir / "state.vscdb"
    with sqlite3.connect(global_db) as conn:
        create_bubble_table(conn)
        create_header_table(conn)
        conn.execute(
            "INSERT INTO composerHeaders VALUES ('composer', 'ws-project', 1, 2, 0, 0)"
        )
        conn.execute(
            "INSERT INTO cursorDiskKV VALUES (?, ?)",
            ("bubbleId:composer:prompt", json.dumps({"type": 1, "text": "prompt"})),
        )
    registry = tmp_path / "registry"
    base_command = [
        sys.executable, "-m", "main", "ingest", "--dir", str(project),
        "--source", "cursor",
    ]
    env = {
        **os.environ,
        "CODESS_REGISTRY": str(registry),
        "CODESS_CURSOR_DATA": str(cursor_base),
    }
    reference = subprocess.run(
        [*base_command, "--raw-mode", "reference"],
        cwd=str(Path(__file__).parent.parent), env=env,
        capture_output=True, text=True,
    )
    assert reference.returncode == 0, reference.stderr
    pointer_before = (project / ".codess" / "current.json").read_bytes()

    capture = subprocess.run(
        [*base_command, "--raw-mode", "capture"],
        cwd=str(Path(__file__).parent.parent), env=env,
        capture_output=True, text=True,
    )
    assert capture.returncode == 0, capture.stderr
    assert "Cursor cohort: captured" in capture.stdout
    assert (project / ".codess" / "current.json").read_bytes() != pointer_before
    records = current_raw_records(project)
    global_record = next(
        record for record in records
        if record.get("source_locator") == str(global_db.resolve())
    )
    assert global_record["availability"] == "captured"


def test_incremental_skip_unchanged(durable_tmp_path):
    """Re-ingest of unchanged file adds no new rows."""
    tmp = durable_tmp_path
    project_path = tmp / "proj"
    project_path.mkdir()
    projects_dir = tmp / "cc"
    projects_dir.mkdir()
    slug = path_to_slug(project_path.resolve())
    (projects_dir / slug).mkdir(parents=True)
    fixture = Path(__file__).parent / "fixtures" / "sample.jsonl"
    shutil.copy(fixture, projects_dir / slug / "s1.jsonl")

    reg = tmp / "_central_reg"
    reg.mkdir()
    env = os.environ.copy()
    env["CODESS_REGISTRY"] = str(reg)
    env["CODESS_CC_PROJECTS"] = str(projects_dir)

    # First ingest
    r1 = subprocess.run(
        [sys.executable, "-m", "main", "ingest", "--dir", str(project_path), "--min-size", "0"],
        cwd=str(Path(__file__).parent.parent),
        env=env,
        capture_output=True,
        text=True,
    )
    assert r1.returncode == 0

    # Query count
    r2 = subprocess.run(
        [sys.executable, "-m", "main", "query", "--dir", str(project_path), "--tool", "0"],
        cwd=str(Path(__file__).parent.parent),
        env=env,
        capture_output=True,
        text=True,
    )
    assert r2.returncode == 0
    # Second ingest (unchanged)
    r3 = subprocess.run(
        [sys.executable, "-m", "main", "ingest", "--dir", str(project_path), "--min-size", "0"],
        cwd=str(Path(__file__).parent.parent),
        env=env,
        capture_output=True,
        text=True,
    )
    assert r3.returncode == 0
    assert "0 file(s)" in r3.stdout or "Processed: 0" in r3.stdout
