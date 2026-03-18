"""Integration tests for ingest and query."""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from ingest.project import path_to_slug


def test_path_to_slug_roundtrip():
    """Slug encode/decode round-trip. Note: slug format uses - as separator, so paths with hyphens are lossy."""
    from ingest.project import slug_to_path

    path = Path("/Users/walter/Work/Spank/spankpy")
    slug = path_to_slug(path)
    assert slug == "-Users-walter-Work-Spank-spankpy"
    back = slug_to_path(slug)
    assert back == path


def test_sanitize_control_chars():
    """Sanitization strips control chars and ANSI."""
    from ingest.sanitize import sanitize_text

    assert sanitize_text("hello\x00world") == "helloworld"
    assert sanitize_text("hello\x1b[31mred\x1b[0m") == "hellored"
    assert sanitize_text("a\r\nb") == "a\nb"  # \r\n normalized to \n


def test_truncate_content():
    """Truncation adds ellipsis and returns full len."""
    from ingest.cc_adapter import truncate_content

    short, n = truncate_content("hi", 10)
    assert short == "hi" and n == 2
    long_text = "x" * 100
    truncated, n = truncate_content(long_text, 50)
    assert len(truncated) == 50 and truncated.endswith("…") and n == 100


def test_cc_adapter_iter_and_skip():
    """iter_cc_records and should_skip."""
    from ingest.cc_adapter import iter_cc_records, should_skip

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


def test_full_ingest_and_query():
    """Full ingest and query cycle with temp CC dir."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        project_root = tmp / "myproj"
        project_root.mkdir()
        (project_root / "main.py").write_text("print('hi')")

        # CC layout: projects_dir / <slug> / *.jsonl
        projects_dir = tmp / "cc_projects"
        projects_dir.mkdir()
        slug = path_to_slug(project_root.resolve())
        session_dir = projects_dir / slug
        session_dir.mkdir(parents=True)
        fixture = Path(__file__).parent / "fixtures" / "sample.jsonl"
        shutil.copy(fixture, session_dir / "test-session.jsonl")

        env = os.environ.copy()
        env["CODINGSESS_CC_PROJECTS_DIR"] = str(projects_dir)

        # Run ingest
        import subprocess
        result = subprocess.run(
            [sys.executable, "-m", "main", "ingest", "--project", str(project_root), "--force", "--min-size", "0"],
            cwd=str(Path(__file__).parent.parent),
            env=env,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"ingest failed: {result.stderr}"

        # Run query --tool-counts
        result = subprocess.run(
            [sys.executable, "-m", "main", "query", "--project", str(project_root), "--tool-counts"],
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
            [sys.executable, "-m", "main", "query", "--project", str(project_root), "--sessions"],
            cwd=str(Path(__file__).parent.parent),
            env=env,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "test-session" in result.stdout or "Claude" in result.stdout


def test_malformed_json_skipped():
    """Malformed JSON lines are skipped; ingest continues."""
    from ingest.cc_adapter import iter_cc_records

    fixtures = Path(__file__).parent / "fixtures" / "malformed.jsonl"
    records = list(iter_cc_records(fixtures))
    assert len(records) == 2  # Line 2 is invalid, skipped
    assert records[0][1]["type"] == "user"
    assert records[1][1]["type"] == "assistant"


def test_codex_ingest_and_query():
    """Codex ingest → query cycle with temp Codex dir."""
    import json
    import sqlite3

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        proj = tmp / "myproj"
        proj.mkdir()
        codex_dir = tmp / "codex" / "sessions" / "2024" / "01"
        codex_dir.mkdir(parents=True)
        sess_file = codex_dir / "rollout-abc.jsonl"
        proj_str = str(proj.resolve())
        sess_file.write_text(
            f'{{"type":"session_meta","payload":{{"id":"s1","cwd":"{proj_str}"}}}}\n'
            '{"type":"response_item","payload":{"type":"message","role":"user","content":[{"type":"input_text","text":"Hi"}]}}\n'
            '{"type":"response_item","payload":{"type":"message","role":"developer","content":[{"type":"input_text","text":"Hello"}]}}\n'
        )
        env = os.environ.copy()
        env["CODINGSESS_CODEX_SESSIONS_DIR"] = str(tmp / "codex" / "sessions")

        r = subprocess.run(
            [sys.executable, "-m", "main", "ingest", "--project", str(proj), "--source", "codex", "--force", "--min-size", "0"],
            cwd=str(Path(__file__).parent.parent),
            env=env,
            capture_output=True,
            text=True,
        )
        assert r.returncode == 0, f"ingest: {r.stderr}"
        assert "2 event" in r.stdout or "2 session" in r.stdout or "1 session" in r.stdout

        r = subprocess.run(
            [sys.executable, "-m", "main", "query", "--project", str(proj), "--stats"],
            cwd=str(Path(__file__).parent.parent),
            env=env,
            capture_output=True,
            text=True,
        )
        assert r.returncode == 0
        assert "Sessions:" in r.stdout and "Events:" in r.stdout


def test_cursor_ingest_and_query():
    """Cursor ingest from workspace DB → query cycle."""
    import json
    import sqlite3

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        proj = tmp / "myproj"
        proj.mkdir()
        cursor_base = tmp / "cursor" / "User"
        ws = cursor_base / "workspaceStorage" / "abc123"
        ws.mkdir(parents=True)
        (ws / "workspace.json").write_text(f'{{"folder":{{"path":"{proj}"}}}}')
        db = ws / "state.vscdb"
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE IF NOT EXISTS cursorDiskKV (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute(
            "INSERT INTO cursorDiskKV (key, value) VALUES (?, ?)",
            ("bubbleId:c1:b1", json.dumps({"type": 1, "text": "hi", "timingInfo": {"clientStartTime": 1}})),
        )
        conn.execute(
            "INSERT INTO cursorDiskKV (key, value) VALUES (?, ?)",
            ("bubbleId:c1:b2", json.dumps({"type": 2, "text": "ok", "timingInfo": {"clientStartTime": 2}})),
        )
        conn.commit()
        conn.close()

        env = os.environ.copy()
        env["CODINGSESS_CURSOR_USER_DATA"] = str(cursor_base)

        r = subprocess.run(
            [sys.executable, "-m", "main", "ingest", "--project", str(proj), "--source", "cursor", "--force"],
            cwd=str(Path(__file__).parent.parent),
            env=env,
            capture_output=True,
            text=True,
        )
        assert r.returncode == 0, f"ingest: {r.stderr}"
        assert "1 session" in r.stdout or "2 event" in r.stdout or "session" in r.stdout.lower()

        r = subprocess.run(
            [sys.executable, "-m", "main", "query", "--project", str(proj), "--stats"],
            cwd=str(Path(__file__).parent.parent),
            env=env,
            capture_output=True,
            text=True,
        )
        assert r.returncode == 0
        assert "Sessions:" in r.stdout and "Events:" in r.stdout


def test_incremental_skip_unchanged():
    """Re-ingest of unchanged file adds no new rows."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        project_root = tmp / "proj"
        project_root.mkdir()
        projects_dir = tmp / "cc"
        projects_dir.mkdir()
        slug = path_to_slug(project_root.resolve())
        (projects_dir / slug).mkdir(parents=True)
        fixture = Path(__file__).parent / "fixtures" / "sample.jsonl"
        shutil.copy(fixture, projects_dir / slug / "s1.jsonl")

        env = os.environ.copy()
        env["CODINGSESS_CC_PROJECTS_DIR"] = str(projects_dir)

        # First ingest
        r1 = subprocess.run(
            [sys.executable, "-m", "main", "ingest", "--project", str(project_root), "--min-size", "0"],
            cwd=str(Path(__file__).parent.parent),
            env=env,
            capture_output=True,
            text=True,
        )
        assert r1.returncode == 0

        # Query count
        r2 = subprocess.run(
            [sys.executable, "-m", "main", "query", "--project", str(project_root), "--tool-counts"],
            cwd=str(Path(__file__).parent.parent),
            env=env,
            capture_output=True,
            text=True,
        )
        count1 = len(r2.stdout.strip().split("\n"))

        # Second ingest (unchanged)
        r3 = subprocess.run(
            [sys.executable, "-m", "main", "ingest", "--project", str(project_root), "--min-size", "0"],
            cwd=str(Path(__file__).parent.parent),
            env=env,
            capture_output=True,
            text=True,
        )
        assert r3.returncode == 0
        assert "0 file(s)" in r3.stdout or "Ingested 0" in r3.stdout


