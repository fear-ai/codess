"""Tests for codess scan CLI and run_scan."""

import json
import sqlite3

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


def _write_codex_session(root: Path, project: Path, session_id: str = "session") -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{session_id}.jsonl").write_text(json.dumps({
        "type": "session_meta", "timestamp": "2026-07-10T00:00:00Z",
        "payload": {"id": session_id, "cwd": str(project)},
    }) + "\n")


def test_scan_rejects_remote_cursor_uri_that_looks_like_project_child(tmp_path):
    work = tmp_path / "work"
    project = work / "project"
    project.mkdir(parents=True)
    codex = tmp_path / "codex"
    _write_codex_session(codex, project)
    cursor = tmp_path / "cursor" / "User"
    ws = cursor / "workspaceStorage" / "remote"
    ws.mkdir(parents=True)
    (ws / "workspace.json").write_text(json.dumps({
        "folder": "vscode-remote://ssh-remote+host/home/user/other"
    }))
    env = _scan_env(
        tmp_path, CODESS_CC_PROJECTS=str(tmp_path / "cc"),
        CODESS_CODEX_SESSIONS=str(codex), CODESS_CURSOR_DATA=str(cursor),
    )
    result = _run(["scan", "--dir", str(work), "--days", "0", "--out", "-"], env=env)
    assert result.returncode == 0
    assert result.stdout.strip().splitlines()[1].split(",")[:2] == ["project", "Codex"]


def test_scan_coalesces_nested_workspace_into_observed_git_project(tmp_path):
    import sqlite3

    work = tmp_path / "work"
    project = work / "project"
    child = project / "src"
    child.mkdir(parents=True)
    (project / ".git").mkdir()
    codex = tmp_path / "codex"
    _write_codex_session(codex, project)
    cursor = tmp_path / "cursor" / "User"
    ws = cursor / "workspaceStorage" / "child"
    ws.mkdir(parents=True)
    (ws / "workspace.json").write_text(json.dumps({"folder": str(child)}))
    conn = sqlite3.connect(ws / "state.vscdb")
    conn.execute("CREATE TABLE cursorDiskKV (key TEXT PRIMARY KEY, value TEXT)")
    conn.commit()
    conn.close()
    env = _scan_env(
        tmp_path, CODESS_CC_PROJECTS=str(tmp_path / "cc"),
        CODESS_CODEX_SESSIONS=str(codex), CODESS_CURSOR_DATA=str(cursor),
    )
    result = _run(["scan", "--dir", str(work), "--days", "0", "--out", "-"], env=env)
    assert result.returncode == 0
    rows = result.stdout.strip().splitlines()
    assert len(rows) == 2
    assert rows[1].split(",")[:2] == ["project", "Codex|Cursor"]


def test_scan_maps_lone_nested_workspace_to_nearest_git_root(tmp_path):
    work = tmp_path / "work"
    project = work / "project"
    child = project / "src"
    child.mkdir(parents=True)
    (project / ".git").mkdir()
    cursor = tmp_path / "cursor" / "User"
    ws = cursor / "workspaceStorage" / "child"
    ws.mkdir(parents=True)
    (ws / "workspace.json").write_text(json.dumps({"folder": str(child)}))
    env = _scan_env(
        tmp_path, CODESS_CC_PROJECTS=str(tmp_path / "cc"),
        CODESS_CODEX_SESSIONS=str(tmp_path / "codex"), CODESS_CURSOR_DATA=str(cursor),
    )
    result = _run(["scan", "--dir", str(work), "--days", "0", "--out", "-"], env=env)
    assert result.returncode == 0
    rows = result.stdout.strip().splitlines()
    assert len(rows) == 2
    assert rows[1].split(",", 1)[0] == "project"


def test_scan_does_not_count_explicitly_missing_claude_source(tmp_path):
    work = tmp_path / "work"
    project = work / "project"
    project.mkdir(parents=True)
    cc = tmp_path / "cc"
    slug = "-" + str(project.resolve()).lstrip("/").replace("/", "-")
    source = cc / slug
    source.mkdir(parents=True)
    (source / "sessions-index.json").write_text(json.dumps({"entries": [{
        "projectPath": str(project), "sessionId": "gone", "fileMtime": 1e12,
        "messageCount": 5, "isSidechain": False,
        "fullPath": str(source / "gone.jsonl"),
    }]}))
    codex = tmp_path / "codex"
    _write_codex_session(codex, project)
    cursor = tmp_path / "cursor" / "User"
    cursor.mkdir(parents=True)
    env = _scan_env(
        tmp_path, CODESS_CC_PROJECTS=str(cc),
        CODESS_CODEX_SESSIONS=str(codex), CODESS_CURSOR_DATA=str(cursor),
    )
    result = _run(["scan", "--dir", str(work), "--days", "0", "--out", "-"], env=env)
    assert result.returncode == 0
    assert result.stdout.strip().splitlines()[1].split(",")[:2] == ["project", "Codex"]
    assert "stale_index_entries=1" in result.stderr


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


def test_scan_dirs_accepts_candidate_csv_directory_path_column(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    dirs_file = tmp_path / "candidates.csv"
    dirs_file.write_text(
        "title,directory_path,repo_url,notes\n"
        f'example,{work},https://example.invalid/repo,"contains, comma"\n'
    )
    result = _run(
        ["scan", "--dirs", str(dirs_file), "--days", "0", "--out", "-"],
        env=_scan_env(tmp_path),
    )
    assert result.returncode == 0
    assert "directory root does not exist" not in result.stderr


def test_multi_root_scan_does_not_register_cursor_global_as_project(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    cursor = tmp_path / "cursor" / "User"
    (cursor / "globalStorage").mkdir(parents=True)
    db = cursor / "globalStorage" / "state.vscdb"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE cursorDiskKV (key TEXT PRIMARY KEY, value BLOB)")
    conn.execute("INSERT INTO cursorDiskKV VALUES (?, ?)", ("composerData:c1", b'{}'))
    conn.commit()
    conn.close()
    reg = tmp_path / "registry"
    env = _scan_env(tmp_path, CODESS_CURSOR_DATA=str(cursor), CODESS_REGISTRY=str(reg))
    result = _run(
        ["scan", "--dir", str(first), "--dir", str(second), "--days", "0", "--out", "-"],
        env=env,
    )
    assert result.returncode == 0
    registry_path = reg / "ingested_projects.json"
    if registry_path.exists():
        registry = json.loads(registry_path.read_text())
        assert not any("(global)" in row["path"] for row in registry["projects"])


def test_scan_prunes_legacy_cursor_global_pseudo_project(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    reg = tmp_path / "registry"
    reg.mkdir()
    (reg / "ingested_projects.json").write_text(json.dumps({"projects": [{
        "path": str(work / "(global)"),
        "scan": {"by_vendor": {"Cursor": {"sess": 5}}},
    }]}))
    result = _run(
        ["scan", "--dir", str(work), "--days", "0", "--out", "-"],
        env=_scan_env(tmp_path, CODESS_REGISTRY=str(reg)),
    )
    assert result.returncode == 0
    registry = json.loads((reg / "ingested_projects.json").read_text())
    assert registry["projects"] == []


def test_scan_help():
    """Scan subcommand shows help."""
    r = _run(["scan", "--help"])
    assert r.returncode == 0
    assert "scan" in r.stdout
    assert "--dir" in r.stdout or "dirs" in r.stdout
    assert "--norec" not in r.stdout


def test_scan_rejects_removed_norec_option():
    result = _run(["scan", "--norec"])
    assert result.returncode == 2
    assert "unrecognized arguments" in result.stderr


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


def test_scan_missing_root_is_error(tmp_path):
    env = _scan_env(tmp_path)
    missing = tmp_path / "missing"
    r = _run(["scan", "--dir", str(missing), "--out", "-"], env=env)
    assert r.returncode == 1
    assert "does not exist" in r.stderr


def test_scan_days_zero_means_all_time(tmp_path):
    work = tmp_path / "work"
    proj = work / "proj"
    proj.mkdir(parents=True)
    cc = tmp_path / "cc"
    slug = "-" + str(proj.resolve()).lstrip("/").replace("/", "-")
    (cc / slug).mkdir(parents=True)
    (cc / slug / "sessions-index.json").write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "projectPath": str(proj),
                        "sessionId": "old",
                        "fileMtime": 1_000_000_000_000,
                        "messageCount": 1,
                        "isSidechain": False,
                    }
                ]
            }
        )
    )
    codex = tmp_path / "codex"
    codex.mkdir()
    cursor = tmp_path / "cursor" / "User"
    cursor.mkdir(parents=True)
    env = _scan_env(
        tmp_path,
        CODESS_CC_PROJECTS=str(cc),
        CODESS_CODEX_SESSIONS=str(codex),
        CODESS_CURSOR_DATA=str(cursor),
    )
    result = _run(
        ["scan", "--dir", str(work), "--days", "0", "--out", "-"],
        env=env,
    )
    assert result.returncode == 0
    assert len(result.stdout.strip().splitlines()) == 2


def test_scan_negative_days_is_error(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    result = _run(
        ["scan", "--dir", str(work), "--days", "-1", "--out", "-"],
        env=_scan_env(tmp_path),
    )
    assert result.returncode == 1
    assert "must be >= 0" in result.stderr


def test_scan_non_numeric_days_is_argparse_error(tmp_path):
    result = _run(
        ["scan", "--days", "recent", "--out", "-"],
        env=_scan_env(tmp_path),
    )
    assert result.returncode == 2
    assert "--days" in result.stderr
    assert "invalid int value" in result.stderr


def test_scan_reports_malformed_index_as_nonfatal(tmp_path):
    """A malformed CC index is visible without crashing the scan."""
    work = tmp_path / "work"
    proj = work / "proj"
    proj.mkdir(parents=True)
    cc = tmp_path / "cc"
    slug = "-" + str(proj.resolve()).lstrip("/").replace("/", "-")
    source = cc / slug
    source.mkdir(parents=True)
    (source / "sessions-index.json").write_text("not json")
    (source / "s1.jsonl").write_text('{"type":"user"}\n')
    env = _scan_env(
        tmp_path,
        CODESS_CC_PROJECTS=str(cc),
        CODESS_CODEX_SESSIONS=str(tmp_path / "codex"),
        CODESS_CURSOR_DATA=str(tmp_path / "cursor" / "User"),
    )

    result = _run(
        ["scan", "--dir", str(work), "--source", "cc", "--days", "0", "--out", "-"],
        env=env,
    )

    assert result.returncode == 0
    assert "malformed=1" in result.stderr
    assert result.stdout.startswith("path,vendor")


def test_scan_source_filter_ignores_other_vendor_corruption(tmp_path):
    """Diagnostics cover only vendors selected by --source."""
    work = tmp_path / "work"
    work.mkdir()
    codex = tmp_path / "codex"
    codex.mkdir()
    (codex / "bad.jsonl").write_text("not json")
    cc = tmp_path / "cc"
    cc.mkdir()
    env = _scan_env(
        tmp_path,
        CODESS_CC_PROJECTS=str(cc),
        CODESS_CODEX_SESSIONS=str(codex),
        CODESS_CURSOR_DATA=str(tmp_path / "cursor" / "User"),
    )

    result = _run(
        ["scan", "--dir", str(work), "--source", "cc", "--out", "-"],
        env=env,
    )

    assert result.returncode == 0
    assert "scan diagnostics" not in result.stderr


def test_scan_cursor_metric_failure_exits_1_and_stop_suppresses_csv(tmp_path):
    """Missing Cursor tables are source failures; --stop aborts before output."""
    import sqlite3

    work = tmp_path / "work"
    proj = work / "proj"
    proj.mkdir(parents=True)
    cursor_base = tmp_path / "cursor" / "User"
    ws = cursor_base / "workspaceStorage" / "ws1"
    ws.mkdir(parents=True)
    (ws / "workspace.json").write_text(json.dumps({"folder": str(proj)}))
    conn = sqlite3.connect(ws / "state.vscdb")
    conn.execute("CREATE TABLE unrelated (value TEXT)")
    conn.commit()
    conn.close()
    env = _scan_env(tmp_path, CODESS_CURSOR_DATA=str(cursor_base))

    continued = _run(
        ["scan", "--dir", str(work), "--source", "cursor", "--out", "-"],
        env=env,
    )
    stopped = _run(
        [
            "scan",
            "--dir",
            str(work),
            "--source",
            "cursor",
            "--stop",
            "--out",
            "-",
        ],
        env=env,
    )

    assert continued.returncode == 1
    assert "failed_sources=1" in continued.stderr
    assert continued.stdout.startswith("path,vendor")
    assert stopped.returncode == 1
    assert "failed_sources=1" in stopped.stderr
    assert stopped.stdout == ""


def test_scan_cursor_invalid_key_is_reported_but_nonfatal(tmp_path):
    """Malformed Cursor keys affect diagnostics, not command success."""
    import sqlite3

    work = tmp_path / "work"
    proj = work / "proj"
    proj.mkdir(parents=True)
    cursor_base = tmp_path / "cursor" / "User"
    ws = cursor_base / "workspaceStorage" / "ws1"
    ws.mkdir(parents=True)
    (ws / "workspace.json").write_text(json.dumps({"folder": str(proj)}))
    conn = sqlite3.connect(ws / "state.vscdb")
    conn.execute("CREATE TABLE cursorDiskKV (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO cursorDiskKV VALUES ('bubbleId:broken', '{}')")
    conn.commit()
    conn.close()
    env = _scan_env(tmp_path, CODESS_CURSOR_DATA=str(cursor_base))

    result = _run(
        ["scan", "--dir", str(work), "--source", "cursor", "--out", "-"],
        env=env,
    )

    assert result.returncode == 0
    assert "invalid_keys=1" in result.stderr


def test_scan_path_filter_uses_component_boundary(tmp_path):
    """A sibling such as work-other is not considered inside work."""
    work = tmp_path / "work"
    sibling_project = tmp_path / "work-other" / "proj"
    work.mkdir()
    sibling_project.mkdir(parents=True)
    cc = tmp_path / "cc"
    source = cc / "project-index"
    source.mkdir(parents=True)
    (source / "sessions-index.json").write_text(
        json.dumps({"entries": [{"projectPath": str(sibling_project)}]})
    )
    env = _scan_env(tmp_path, CODESS_CC_PROJECTS=str(cc))

    result = _run(
        ["scan", "--dir", str(work), "--source", "cc", "--out", "-"],
        env=env,
    )

    assert result.returncode == 0
    assert result.stdout.strip().splitlines() == ["path,vendor,sess,mb,span_weeks"]


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


def test_scan_rejects_vendor_project_mapping_inside_pruned_tree(tmp_path):
    work = tmp_path / "work"
    noisy_project = work / "node_modules" / "dependency"
    noisy_project.mkdir(parents=True)
    cc = tmp_path / "cc"
    slug_dir = cc / ("-" + str(noisy_project.resolve()).lstrip("/").replace("/", "-"))
    slug_dir.mkdir(parents=True)
    (slug_dir / "sessions-index.json").write_text(json.dumps({
        "entries": [{
            "projectPath": str(noisy_project), "sessionId": "s1",
            "fileMtime": 1e12, "messageCount": 2, "isSidechain": False,
        }]
    }))
    codex = tmp_path / "codex"
    codex.mkdir()
    cursor = tmp_path / "cursor" / "User"
    cursor.mkdir(parents=True)
    env = _scan_env(
        tmp_path,
        CODESS_CC_PROJECTS=str(cc),
        CODESS_CODEX_SESSIONS=str(codex),
        CODESS_CURSOR_DATA=str(cursor),
    )

    result = _run(["scan", "--dir", str(work), "--days", "9999", "--out", "-"], env=env)

    assert result.returncode == 0
    assert result.stdout.strip().splitlines() == ["path,vendor,sess,mb,span_weeks"]


def test_scan_rejects_broad_system_root_before_source_discovery(tmp_path):
    result = _run(
        ["scan", "--dir", "/", "--out", "-"],
        env=_scan_env(tmp_path),
    )
    assert result.returncode == 1
    assert "broad system traversal root" in result.stderr


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


def test_scan_days_filters_cursor_global_with_header_timestamps(tmp_path):
    """Cursor global rows with a known old header range respect --days."""
    import sqlite3

    work = tmp_path / "work"
    work.mkdir()
    cursor_base = tmp_path / "cursor" / "User"
    global_dir = cursor_base / "globalStorage"
    global_dir.mkdir(parents=True)
    db = global_dir / "state.vscdb"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE cursorDiskKV (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute(
        "CREATE TABLE composerHeaders ("
        "composerId TEXT PRIMARY KEY, workspaceId TEXT, createdAt INTEGER, "
        "lastUpdatedAt INTEGER, isArchived INTEGER, isSubagent INTEGER)"
    )
    conn.execute(
        "INSERT INTO cursorDiskKV VALUES (?, ?)",
        ("bubbleId:c1:b1", json.dumps({"type": 1, "text": "old"})),
    )
    conn.execute(
        "INSERT INTO composerHeaders VALUES (?, ?, ?, ?, ?, ?)",
        ("c1", "ws", 1_000_000_000_000, 1_000_000_001_000, 0, 0),
    )
    conn.commit()
    conn.close()
    cc = tmp_path / "cc"
    codex = tmp_path / "codex"
    cc.mkdir()
    codex.mkdir()
    env = _scan_env(
        tmp_path,
        CODESS_CC_PROJECTS=str(cc),
        CODESS_CODEX_SESSIONS=str(codex),
        CODESS_CURSOR_DATA=str(cursor_base),
    )
    result = _run(
        ["scan", "--dir", str(work), "--days", "1", "--out", "-"],
        env=env,
    )
    assert result.returncode == 0
    assert result.stdout.strip().splitlines() == [
        "path,vendor,sess,mb,span_weeks"
    ]


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


def test_scan_registry_corrupt_json_exit(tmp_path):
    reg = tmp_path / "reg"
    reg.mkdir()
    (reg / "ingested_projects.json").write_text("{broken")
    work = tmp_path / "work"
    work.mkdir()
    r = _run(
        ["scan", "--dir", str(work), "--registry", str(reg), "--out", "-"],
        env=_scan_env(tmp_path),
    )
    assert r.returncode == 1
    assert "cannot read registry" in r.stderr.lower()


def test_scan_empty_registry_warns_and_outputs_only_header(tmp_path):
    reg = tmp_path / "reg"
    reg.mkdir()
    (reg / "ingested_projects.json").write_text('{"projects":[]}')
    work = tmp_path / "work"
    work.mkdir()
    r = _run(
        ["scan", "--dir", str(work), "--registry", str(reg), "--out", "-"],
        env=_scan_env(tmp_path),
    )
    assert r.returncode == 0
    assert "registry has no projects" in r.stderr.lower()
    assert len(r.stdout.strip().splitlines()) == 1


@pytest.mark.parametrize("contents", ["", "# comments only\n", "../outside\n"])
def test_scan_dirs_file_without_usable_roots_is_error(tmp_path, contents):
    dirs = tmp_path / "dirs.txt"
    dirs.write_text(contents)
    result = _run(
        ["scan", "--dirs", str(dirs), "--out", "-"],
        env=_scan_env(tmp_path),
    )
    assert result.returncode == 1
    assert "codess:" in result.stderr.lower()


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
