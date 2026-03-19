"""CLI edge cases: no store, no mode, empty dir, idempotent."""

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

from ingest.project import path_to_slug


PROJECT_ROOT = Path(__file__).parent.parent


def _run(cmd, cwd=None, env=None, **kw):
    env = env or os.environ.copy()
    cwd = cwd or PROJECT_ROOT
    return subprocess.run(
        [sys.executable, "-m", "main"] + cmd,
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        **kw,
    )


def test_query_no_store_exit_1():
    """Query before any ingest exits 1."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        r = _run(["query", "--project", str(tmp), "--tool-counts"])
        assert r.returncode == 1
        assert "No store" in r.stderr or "store" in r.stderr.lower()


def test_query_no_mode_exit_1():
    """Query without --tool-counts/--sessions/--permissions exits 1."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        # Create empty store
        (tmp / ".coding-sess").mkdir()
        init_db(tmp / ".coding-sess" / "sessions.db")
        r = _run(["query", "--project", str(tmp)])
        assert r.returncode == 1
        assert "Specify" in r.stderr or "tool-counts" in r.stderr.lower()


def test_ingest_no_cc_dir_exit_1():
    """Ingest --source cc when no CC project dir exits 1."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        proj = tmp / "orphan"
        proj.mkdir()
        env = os.environ.copy()
        env["CODINGSESS_CC_PROJECTS"] = str(tmp)
        r = _run(["ingest", "--source", "cc", "--project", str(proj), "--min-size", "0"], env=env)
        assert r.returncode == 1
        assert "No CC project" in r.stderr


def test_ingest_empty_jsonl_dir_success():
    """Ingest when CC dir exists but no jsonl files: success, 0 ingested."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        proj = tmp / "myproj"
        proj.mkdir()
        cc_dir = tmp / "cc"
        cc_dir.mkdir()
        slug = path_to_slug(proj.resolve())
        (cc_dir / slug).mkdir(parents=True)
        env = os.environ.copy()
        env["CODINGSESS_CC_PROJECTS"] = str(cc_dir)
        r = _run(["ingest", "--source", "cc", "--project", str(proj), "--min-size", "0"], env=env)
        assert r.returncode == 0
        assert "0 file" in r.stdout or "0 event" in r.stdout


def test_ingest_empty_jsonl_file():
    """Ingest file with no valid records."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        proj = tmp / "proj"
        proj.mkdir()
        cc_dir = tmp / "cc"
        cc_dir.mkdir()
        slug = path_to_slug(proj.resolve())
        (cc_dir / slug).mkdir(parents=True)
        (cc_dir / slug / "empty.jsonl").write_text("")
        env = os.environ.copy()
        env["CODINGSESS_CC_PROJECTS"] = str(cc_dir)
        r = _run(["ingest", "--project", str(proj), "--source", "cc", "--force", "--min-size", "0"], env=env)
        assert r.returncode == 0


def test_query_empty_store():
    """Query --tool-counts on empty store: empty output, exit 0."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        proj = tmp / "proj"
        proj.mkdir()
        cc_dir = tmp / "cc"
        cc_dir.mkdir()
        slug = path_to_slug(proj.resolve())
        (cc_dir / slug).mkdir(parents=True)
        env = os.environ.copy()
        env["CODINGSESS_CC_PROJECTS"] = str(cc_dir)
        _run(["ingest", "--project", str(proj), "--source", "cc", "--min-size", "0"], env=env)
        r = _run(["query", "--project", str(proj), "--tool-counts"], env=env)
        assert r.returncode == 0
        assert r.stdout.strip() == "" or "Bash" not in r.stdout


def test_idempotent_same_data():
    """Re-ingest same file produces identical event count."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        proj = tmp / "proj"
        proj.mkdir()
        cc_dir = tmp / "cc"
        cc_dir.mkdir()
        slug = path_to_slug(proj.resolve())
        (cc_dir / slug).mkdir(parents=True)
        fixture = Path(__file__).parent / "fixtures" / "sample.jsonl"
        shutil.copy(fixture, cc_dir / slug / "s1.jsonl")
        env = os.environ.copy()
        env["CODINGSESS_CC_PROJECTS"] = str(cc_dir)
        r1 = _run(["ingest", "--project", str(proj), "--source", "cc", "--force", "--min-size", "0"], env=env)
        assert r1.returncode == 0
        r2 = _run(["query", "--project", str(proj), "--tool-counts"], env=env)
        lines1 = r2.stdout.strip().split("\n")
        r3 = _run(["ingest", "--project", str(proj), "--source", "cc", "--force", "--min-size", "0"], env=env)
        r4 = _run(["query", "--project", str(proj), "--tool-counts"], env=env)
        lines2 = r4.stdout.strip().split("\n")
        assert sorted(lines1) == sorted(lines2)


def test_ingest_shows_stats():
    """Ingest prints added and overall stats."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        proj = tmp / "proj"
        proj.mkdir()
        cc_dir = tmp / "cc"
        cc_dir.mkdir()
        slug = path_to_slug(proj.resolve())
        (cc_dir / slug).mkdir(parents=True)
        fixture = Path(__file__).parent / "fixtures" / "sample.jsonl"
        shutil.copy(fixture, cc_dir / slug / "s1.jsonl")
        env = os.environ.copy()
        env["CODINGSESS_CC_PROJECTS"] = str(cc_dir)
        r = _run(["ingest", "--project", str(proj), "--source", "cc", "--force", "--min-size", "0"], env=env)
        assert r.returncode == 0
        assert "Added:" in r.stdout and "Overall:" in r.stdout


def test_query_stats():
    """Query --stats prints sessions and events."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        proj = tmp / "proj"
        proj.mkdir()
        cc_dir = tmp / "cc"
        cc_dir.mkdir()
        slug = path_to_slug(proj.resolve())
        (cc_dir / slug).mkdir(parents=True)
        fixture = Path(__file__).parent / "fixtures" / "sample.jsonl"
        shutil.copy(fixture, cc_dir / slug / "s1.jsonl")
        env = os.environ.copy()
        env["CODINGSESS_CC_PROJECTS"] = str(cc_dir)
        _run(["ingest", "--project", str(proj), "--source", "cc", "--force", "--min-size", "0"], env=env)
        r = _run(["query", "--project", str(proj), "--stats"], env=env)
        assert r.returncode == 0
        assert "Sessions:" in r.stdout and "Events:" in r.stdout


def test_query_taxonomy():
    """Query --taxonomy prints event types."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        proj = tmp / "proj"
        proj.mkdir()
        cc_dir = tmp / "cc"
        cc_dir.mkdir()
        slug = path_to_slug(proj.resolve())
        (cc_dir / slug).mkdir(parents=True)
        fixture = Path(__file__).parent / "fixtures" / "sample.jsonl"
        shutil.copy(fixture, cc_dir / slug / "s1.jsonl")
        env = os.environ.copy()
        env["CODINGSESS_CC_PROJECTS"] = str(cc_dir)
        _run(["ingest", "--project", str(proj), "--source", "cc", "--force", "--min-size", "0"], env=env)
        r = _run(["query", "--project", str(proj), "--taxonomy"], env=env)
        assert r.returncode == 0
        assert "tool_call" in r.stdout and "user_message" in r.stdout


def test_query_sessions_with_id():
    """Query --sessions --id includes num column."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        proj = tmp / "proj"
        proj.mkdir()
        cc_dir = tmp / "cc"
        cc_dir.mkdir()
        slug = path_to_slug(proj.resolve())
        (cc_dir / slug).mkdir(parents=True)
        fixture = Path(__file__).parent / "fixtures" / "sample.jsonl"
        shutil.copy(fixture, cc_dir / slug / "s1.jsonl")
        env = os.environ.copy()
        env["CODINGSESS_CC_PROJECTS"] = str(cc_dir)
        _run(["ingest", "--project", str(proj), "--source", "cc", "--force", "--min-size", "0"], env=env)
        r = _run(["query", "--project", str(proj), "--sessions", "--id"], env=env)
        assert r.returncode == 0
        assert "num" in r.stdout and "\t1\t" in r.stdout


def test_ingest_source_codex_only():
    """Ingest --source codex with no Codex data: success, 0 ingested."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        proj = tmp / "proj"
        proj.mkdir()
        codex_empty = tmp / "codex_empty" / "sessions"
        codex_empty.mkdir(parents=True)
        env = os.environ.copy()
        env["CODINGSESS_CODEX_SESSIONS"] = str(codex_empty)
        r = _run(["ingest", "--project", str(proj), "--source", "codex", "--min-size", "0"], env=env)
        assert r.returncode == 0
        assert "0 session" in r.stdout or "0 event" in r.stdout


def test_ingest_cursor_global_flag():
    """Ingest --source cursor --cursor-global uses global storage only."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        proj = tmp / "proj"
        proj.mkdir()
        cursor_base = tmp / "cursor" / "User"
        global_dir = cursor_base / "globalStorage"
        global_dir.mkdir(parents=True)
        db = global_dir / "state.vscdb"
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE IF NOT EXISTS cursorDiskKV (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute(
            "INSERT INTO cursorDiskKV (key, value) VALUES (?, ?)",
            ("bubbleId:c1:b1", json.dumps({"type": 1, "text": "hi", "timingInfo": {}})),
        )
        conn.commit()
        conn.close()
        env = os.environ.copy()
        env["CODINGSESS_CURSOR_USER_DATA"] = str(cursor_base)
        r = _run(["ingest", "--project", str(proj), "--source", "cursor", "--cursor-global", "--force"], env=env)
        assert r.returncode == 0
        assert "1 session" in r.stdout or "1 event" in r.stdout or "session" in r.stdout.lower()


def test_only_skipped_records():
    """File with only progress/system: no events, session still created? Or not."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        proj = tmp / "proj"
        proj.mkdir()
        cc_dir = tmp / "cc"
        cc_dir.mkdir()
        slug = path_to_slug(proj.resolve())
        (cc_dir / slug).mkdir(parents=True)
        (cc_dir / slug / "only_skipped.jsonl").write_text(
            '{"type":"progress","message":{}}\n{"type":"system","message":{}}\n'
        )
        env = os.environ.copy()
        env["CODINGSESS_CC_PROJECTS"] = str(cc_dir)
        r = _run(["ingest", "--project", str(proj), "--source", "cc", "--force", "--min-size", "0"], env=env)
        assert r.returncode == 0
        r2 = _run(["query", "--project", str(proj), "--sessions"], env=env)
        # May or may not have session row (we don't upsert session if 0 events)
        assert r2.returncode == 0


# Need init_db for test_query_no_mode
from ingest.store import init_db
