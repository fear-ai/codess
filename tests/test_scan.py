"""Tests for codess scan CLI and run_scan."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

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


def test_scan_help():
    """Scan subcommand shows help."""
    r = _run(["scan", "--help"])
    assert r.returncode == 0
    assert "scan" in r.stdout
    assert "--dir" in r.stdout or "dirs" in r.stdout


def test_scan_stdout_empty_work():
    """Scan with empty work dir outputs header only."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        work = tmp / "work"
        work.mkdir()
        (tmp / "cc").mkdir()
        (tmp / "codex").mkdir()
        cursor_base = tmp / "cursor" / "User"
        cursor_base.mkdir(parents=True)
        env = os.environ.copy()
        env["CODESS_CC_PROJECTS"] = str(tmp / "cc")
        env["CODESS_CODEX_SESSIONS"] = str(tmp / "codex")
        env["CODESS_CURSOR_DATA"] = str(cursor_base)
        r = _run(["scan", "--dir", str(work), "--out", "-"], env=env)
        assert r.returncode == 0
        lines = r.stdout.strip().split("\n")
        assert lines[0] == "path,vendor,sess,mb,span_weeks"
        assert len(lines) == 1  # header only, no projects


def test_scan_writes_csv(tmp_path):
    """Scan --out writes CSV file."""
    work = tmp_path / "work"
    work.mkdir()
    cc = tmp_path / "cc"
    cc.mkdir()
    codex = tmp_path / "codex"
    codex.mkdir()
    env = os.environ.copy()
    env["CODESS_CC_PROJECTS"] = str(cc)
    env["CODESS_CODEX_SESSIONS"] = str(codex)
    out_file = tmp_path / "scan_out.csv"
    r = _run(["scan", "--dir", str(work), "--out", str(out_file)], env=env)
    assert r.returncode == 0
    assert out_file.exists()
    assert "path,vendor" in out_file.read_text()


def test_scan_cc_excludes_subagent():
    """CC sessions exclude isSidechain entries."""
    import time

    mtime_ms = int((time.time() - 1) * 1000)  # recent, passes --days filter
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        work = tmp / "work"
        work.mkdir()
        proj = work / "proj"
        proj.mkdir()
        cc = tmp / "cc"
        cc.mkdir()
        slug = "-" + str(proj.resolve()).lstrip("/").replace("/", "-")
        (cc / slug).mkdir(parents=True)
        idx_data = {
            "entries": [
                {"projectPath": str(proj), "sessionId": "s1", "fileMtime": mtime_ms, "messageCount": 3, "isSidechain": False},
                {"projectPath": str(proj), "sessionId": "s2", "fileMtime": mtime_ms, "messageCount": 5, "isSidechain": True},
            ]
        }
        (cc / slug / "sessions-index.json").write_text(json.dumps(idx_data))
        (tmp / "codex").mkdir()
        cursor_base = tmp / "cursor" / "User"
        cursor_base.mkdir(parents=True)
        env = os.environ.copy()
        env["CODESS_CC_PROJECTS"] = str(cc)
        env["CODESS_CODEX_SESSIONS"] = str(tmp / "codex")
        env["CODESS_CURSOR_DATA"] = str(cursor_base)
        r = _run(["scan", "--dir", str(work), "--out", "-"], env=env)
        assert r.returncode == 0
        lines = r.stdout.strip().split("\n")
        # sess=1 (only main), events=3 (from s1 only)
        assert len(lines) == 2
        row = lines[1]
        parts = row.split(",")
        assert int(parts[2]) == 1  # sess


def test_scan_debug_dir_label():
    """Scan --debug prints [dir] for directory visits when projects found."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        work = tmp / "work"
        work.mkdir()
        proj = work / "proj"
        proj.mkdir()
        cc = tmp / "cc"
        cc.mkdir()
        slug = "-" + str(proj.resolve()).lstrip("/").replace("/", "-")
        (cc / slug).mkdir(parents=True)
        (cc / slug / "sessions-index.json").write_text(json.dumps({"entries": [{"projectPath": str(proj), "sessionId": "s1", "fileMtime": 1e12, "messageCount": 2, "isSidechain": False}]}))
        (tmp / "codex").mkdir()
        cursor_base = tmp / "cursor" / "User"
        cursor_base.mkdir(parents=True)
        env = os.environ.copy()
        env["CODESS_CC_PROJECTS"] = str(cc)
        env["CODESS_CODEX_SESSIONS"] = str(tmp / "codex")
        env["CODESS_CURSOR_DATA"] = str(cursor_base)
        r = _run(["scan", "--dir", str(work), "--debug", "--out", "-"], env=env)
        assert r.returncode == 0
        assert "[dir]" in r.stderr
        assert "[scan]" in r.stderr


def test_scan_cursor_central_db():
    """Scan includes (global) row when central DB has data."""
    import sqlite3

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        work = tmp / "work"
        work.mkdir()
        cursor_base = tmp / "cursor" / "User"
        gs = cursor_base / "globalStorage"
        gs.mkdir(parents=True)
        db = gs / "state.vscdb"
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE cursorDiskKV (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute(
            "INSERT INTO cursorDiskKV (key, value) VALUES (?, ?)",
            ("bubbleId:c1:b1", json.dumps({"type": 1, "text": "hi", "timingInfo": {}})),
        )
        conn.commit()
        conn.close()
        (tmp / "cc").mkdir()
        (tmp / "codex").mkdir()
        env = os.environ.copy()
        env["CODESS_CC_PROJECTS"] = str(tmp / "cc")
        env["CODESS_CODEX_SESSIONS"] = str(tmp / "codex")
        env["CODESS_CURSOR_DATA"] = str(cursor_base)
        r = _run(["scan", "--dir", str(work), "--out", "-"], env=env)
        assert r.returncode == 0
        lines = r.stdout.strip().split("\n")
        assert lines[0] == "path,vendor,sess,mb,span_weeks"
        assert any("(global)" in ln for ln in lines)
        row = [ln for ln in lines if "(global)" in ln][0]
        assert "1," in row or ",1," in row  # sess=1


def test_scan_days_ago_in_debug():
    """Scan --debug includes days_ago in CC/Codex output."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        work = tmp / "work"
        work.mkdir()
        cc = tmp / "cc"
        cc.mkdir()
        (tmp / "codex").mkdir()
        cursor_base = tmp / "cursor" / "User"
        cursor_base.mkdir(parents=True)
        env = os.environ.copy()
        env["CODESS_CC_PROJECTS"] = str(cc)
        env["CODESS_CODEX_SESSIONS"] = str(tmp / "codex")
        env["CODESS_CURSOR_DATA"] = str(cursor_base)
        proj = work / "proj"
        proj.mkdir()
        slug = "-" + str(proj.resolve()).lstrip("/").replace("/", "-")
        slug_dir = cc / slug
        slug_dir.mkdir(parents=True)
        idx = slug_dir / "sessions-index.json"
        idx.write_text(json.dumps({"entries": [{"projectPath": str(proj), "sessionId": "s1", "fileMtime": 1e12, "messageCount": 5, "isSidechain": False}]}))
        r = _run(["scan", "--dir", str(work), "--debug", "--out", "-"], env=env)
        assert r.returncode == 0
        assert "days_ago=" in r.stderr
