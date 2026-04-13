"""Tests for codess scan CLI and run_scan."""

import json

import pytest
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


def _scan_env(base: Path, **extra: str) -> dict:
    """Isolate ``ingested_projects.json`` writes from the developer home."""
    reg = base / "_test_codess_registry"
    reg.mkdir(parents=True, exist_ok=True)
    return {**os.environ.copy(), "CODESS_REGISTRY": str(reg), **extra}


def test_scan_mixed_dir_dirs(tmp_path):
    """Scan with both --dirs file and --dir: dedupe, both used."""
    work = tmp_path / "work"
    work.mkdir()
    proj = work / "proj"
    proj.mkdir()
    cc = tmp_path / "cc"
    cc.mkdir()
    slug = "-" + str(proj.resolve()).lstrip("/").replace("/", "-")
    (cc / slug).mkdir(parents=True)
    (cc / slug / "sessions-index.json").write_text(
        json.dumps({"entries": [{"projectPath": str(proj), "sessionId": "s1", "fileMtime": 1e12, "messageCount": 1, "isSidechain": False}]})
    )
    (tmp_path / "codex").mkdir()
    cursor_base = tmp_path / "cursor" / "User"
    cursor_base.mkdir(parents=True)
    dirs_file = tmp_path / "dirs.txt"
    dirs_file.write_text(str(work) + "\n")
    env = _scan_env(
        tmp_path,
        CODESS_CC_PROJECTS=str(cc),
        CODESS_CODEX_SESSIONS=str(tmp_path / "codex"),
        CODESS_CURSOR_DATA=str(cursor_base),
    )
    r = _run(["scan", "--dirs", str(dirs_file), "--dir", str(work), "--days", "9999", "--out", "-"], env=env)
    assert r.returncode == 0
    lines = r.stdout.strip().split("\n")
    assert len(lines) >= 2  # header + at least one project (deduped)

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
        env = _scan_env(
            tmp,
            CODESS_CC_PROJECTS=str(tmp / "cc"),
            CODESS_CODEX_SESSIONS=str(tmp / "codex"),
            CODESS_CURSOR_DATA=str(cursor_base),
        )
        r = _run(["scan", "--dir", str(work), "--out", "-"], env=env)
        assert r.returncode == 0
        lines = r.stdout.strip().split("\n")
        assert lines[0] == "path,vendor,sess,mb,span_weeks"
        assert len(lines) == 1  # header only, no projects


def test_scan_csv_format(tmp_path):
    """Scan output: header path,vendor,sess,mb,span_weeks; numeric sess and mb."""
    work = tmp_path / "work"
    work.mkdir()
    proj = work / "proj"
    proj.mkdir()
    cc = tmp_path / "cc"
    cc.mkdir()
    slug = "-" + str(proj.resolve()).lstrip("/").replace("/", "-")
    (cc / slug).mkdir(parents=True)
    (cc / slug / "sessions-index.json").write_text(
        json.dumps({"entries": [{"projectPath": str(proj), "sessionId": "s1", "fileMtime": 1e12, "messageCount": 2, "isSidechain": False}]})
    )
    (tmp_path / "codex").mkdir()
    cursor_base = tmp_path / "cursor" / "User"
    cursor_base.mkdir(parents=True)
    env = _scan_env(
        tmp_path,
        CODESS_CC_PROJECTS=str(cc),
        CODESS_CODEX_SESSIONS=str(tmp_path / "codex"),
        CODESS_CURSOR_DATA=str(cursor_base),
    )
    r = _run(["scan", "--dir", str(work), "--days", "9999", "--out", "-"], env=env)
    assert r.returncode == 0
    lines = r.stdout.strip().split("\n")
    assert lines[0] == "path,vendor,sess,mb,span_weeks"
    if len(lines) > 1:
        parts = lines[1].split(",")
        assert len(parts) >= 4
        int(parts[2])  # sess numeric
        float(parts[3])  # mb numeric


def test_scan_writes_csv(tmp_path):
    """Scan --out writes CSV file."""
    work = tmp_path / "work"
    work.mkdir()
    cc = tmp_path / "cc"
    cc.mkdir()
    codex = tmp_path / "codex"
    codex.mkdir()
    env = _scan_env(
        tmp_path,
        CODESS_CC_PROJECTS=str(cc),
        CODESS_CODEX_SESSIONS=str(codex),
    )
    out_file = tmp_path / "scan_out.csv"
    r = _run(["scan", "--dir", str(work), "--out", str(out_file)], env=env)
    assert r.returncode == 0
    assert out_file.exists()
    assert "path,vendor" in out_file.read_text()


@pytest.mark.parametrize("subagent_flag,env_val,expected_sess", [
    (False, None, 1),
    (True, None, 2),
    (False, "1", 2),
])
def test_scan_cc_subagent(subagent_flag, env_val, expected_sess):
    """CC subagent: default exclude (sess=1), --subagent or CODESS_SUBAGENT include (sess=2)."""
    import time

    mtime_ms = int((time.time() - 1) * 1000)
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
        extra = {
            "CODESS_CC_PROJECTS": str(cc),
            "CODESS_CODEX_SESSIONS": str(tmp / "codex"),
            "CODESS_CURSOR_DATA": str(cursor_base),
        }
        if env_val is not None:
            extra["CODESS_SUBAGENT"] = env_val
        env = _scan_env(tmp, **extra)
        cmd = ["scan", "--dir", str(work)]
        if subagent_flag:
            cmd.append("--subagent")
        cmd.extend(["--out", "-"])
        r = _run(cmd, env=env)
        assert r.returncode == 0
        lines = r.stdout.strip().split("\n")
        assert len(lines) == 2
        parts = lines[1].split(",")
        assert int(parts[2]) == expected_sess


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
        env = _scan_env(
            tmp,
            CODESS_CC_PROJECTS=str(cc),
            CODESS_CODEX_SESSIONS=str(tmp / "codex"),
            CODESS_CURSOR_DATA=str(cursor_base),
        )
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
        env = _scan_env(
            tmp,
            CODESS_CC_PROJECTS=str(tmp / "cc"),
            CODESS_CODEX_SESSIONS=str(tmp / "codex"),
            CODESS_CURSOR_DATA=str(cursor_base),
        )
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
        proj = work / "proj"
        proj.mkdir()
        slug = "-" + str(proj.resolve()).lstrip("/").replace("/", "-")
        slug_dir = cc / slug
        slug_dir.mkdir(parents=True)
        idx = slug_dir / "sessions-index.json"
        idx.write_text(json.dumps({"entries": [{"projectPath": str(proj), "sessionId": "s1", "fileMtime": 1e12, "messageCount": 5, "isSidechain": False}]}))
        env = _scan_env(
            tmp,
            CODESS_CC_PROJECTS=str(cc),
            CODESS_CODEX_SESSIONS=str(tmp / "codex"),
            CODESS_CURSOR_DATA=str(cursor_base),
        )
        r = _run(["scan", "--dir", str(work), "--debug", "--out", "-"], env=env)
        assert r.returncode == 0
        assert "days_ago=" in r.stderr


def test_scan_invalid_source_exit(tmp_path):
    """Unknown scan --source tokens are a global error (stderr + exit 1)."""
    env = _scan_env(tmp_path)
    r = _run(["scan", "--source", "cc,bogus", "--out", "-"], env=env)
    assert r.returncode == 1
    assert "bogus" in r.stderr
    assert "invalid" in r.stderr.lower()


def test_scan_registry_missing_file_exit(tmp_path):
    """--registry with no ingested_projects.json exits 1."""
    reg = tmp_path / "reg"
    reg.mkdir()
    work = tmp_path / "work"
    work.mkdir()
    (tmp_path / "cc").mkdir()
    (tmp_path / "codex").mkdir()
    cursor_base = tmp_path / "cursor" / "User"
    cursor_base.mkdir(parents=True)
    env = _scan_env(
        tmp_path,
        CODESS_CC_PROJECTS=str(tmp_path / "cc"),
        CODESS_CODEX_SESSIONS=str(tmp_path / "codex"),
        CODESS_CURSOR_DATA=str(cursor_base),
    )
    r = _run(
        ["scan", "--dir", str(work), "--registry", str(reg), "--out", "-"],
        env=env,
    )
    assert r.returncode == 1
    assert "not found" in r.stderr.lower()


def test_scan_merges_registry_without_registry_flag(tmp_path):
    """Every scan upserts index metrics into CODESS_REGISTRY (isolated in test)."""
    work = tmp_path / "work"
    work.mkdir()
    proj = work / "proj"
    proj.mkdir()
    cc = tmp_path / "cc"
    cc.mkdir()
    slug = "-" + str(proj.resolve()).lstrip("/").replace("/", "-")
    (cc / slug).mkdir(parents=True)
    (cc / slug / "sessions-index.json").write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "projectPath": str(proj),
                        "sessionId": "s1",
                        "fileMtime": 1e12,
                        "messageCount": 2,
                        "isSidechain": False,
                    }
                ]
            }
        )
    )
    (tmp_path / "codex").mkdir()
    cursor_base = tmp_path / "cursor" / "User"
    cursor_base.mkdir(parents=True)
    env = _scan_env(
        tmp_path,
        CODESS_CC_PROJECTS=str(cc),
        CODESS_CODEX_SESSIONS=str(tmp_path / "codex"),
        CODESS_CURSOR_DATA=str(cursor_base),
    )
    reg_home = tmp_path / "_test_codess_registry"
    r = _run(
        ["scan", "--dir", str(work), "--days", "9999", "--out", "-"],
        env=env,
    )
    assert r.returncode == 0
    stats_path = reg_home / "ingested_projects.json"
    assert stats_path.exists()
    data = json.loads(stats_path.read_text())
    byp = {p["path"]: p for p in data.get("projects", [])}
    pkey = str(proj.resolve())
    assert pkey in byp
    assert "scan" in byp[pkey]
    assert "last_scan" in byp[pkey]


def test_scan_registry_filter_and_ref_columns(tmp_path):
    """--registry keeps only ingested paths and appends ref columns (no sidecar)."""
    work = tmp_path / "work"
    work.mkdir()
    proj = work / "proj"
    proj.mkdir()
    cc = tmp_path / "cc"
    cc.mkdir()
    slug = "-" + str(proj.resolve()).lstrip("/").replace("/", "-")
    (cc / slug).mkdir(parents=True)
    (cc / slug / "sessions-index.json").write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "projectPath": str(proj),
                        "sessionId": "s1",
                        "fileMtime": 1e12,
                        "messageCount": 2,
                        "isSidechain": False,
                    }
                ]
            }
        )
    )
    (tmp_path / "codex").mkdir()
    cursor_base = tmp_path / "cursor" / "User"
    cursor_base.mkdir(parents=True)
    reg = tmp_path / "reg"
    reg.mkdir()
    stats = {
        "projects": [
            {
                "path": str(proj.resolve()),
                "last_ingestion": "2025-01-01T00:00:00+00:00",
                "sources": {"Claude": {"sessions": 1, "events": 2}},
            }
        ]
    }
    (reg / "ingested_projects.json").write_text(json.dumps(stats))
    env = _scan_env(
        tmp_path,
        CODESS_CC_PROJECTS=str(cc),
        CODESS_CODEX_SESSIONS=str(tmp_path / "codex"),
        CODESS_CURSOR_DATA=str(cursor_base),
    )
    r = _run(
        [
            "scan",
            "--dir",
            str(work),
            "--days",
            "9999",
            "--registry",
            str(reg),
            "--out",
            "-",
        ],
        env=env,
    )
    assert r.returncode == 0
    lines = r.stdout.strip().split("\n")
    assert lines[0] == (
        "path,vendor,sess,mb,span_weeks,reg_path,reg_updated,reg_sources"
    )
    assert len(lines) == 2
    assert "Claude" in lines[1]
    assert str(proj.resolve()) in lines[1]
