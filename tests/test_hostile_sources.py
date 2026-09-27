"""No vendor file or directory state may abort a scan or an ingest.

Each case places one hostile artifact beside a healthy Source for the same
Project and runs the real command in a child process. The contract asserted:

- the process reaches its summary: no traceback escapes `console_main`;
- the exit status is 0 when every hostile record was tolerated, and 1 when a
  Source could not be read, with `failed_sources` counted in the durable report;
- the healthy sibling Source is stored in the same run.

A traceback that `log.exception` writes from a per-Source handler is not an
escape: it starts at the handler's frame. An escaped one passes through
`runpy`, which is how `python -m main` starts, and that frame is the marker.

Cases that currently violate the contract are `xfail(strict=True)`, so the
suite stays green while the defect is visible and a fix flips it to a failure
that asks for the marker to be removed.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest
from cursor_fixtures import build_cursor_db

from codess.project import path_to_slug

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SAMPLE = (Path(__file__).parent / "fixtures" / "sample.jsonl").read_text()
SAMPLE_EVENTS = 10
ESCAPED_TRACEBACK = 'File "<frozen runpy>"'
IS_ROOT = hasattr(os, "geteuid") and os.geteuid() == 0
needs_permissions = pytest.mark.skipif(IS_ROOT, reason="root ignores file modes")


def _run(
    args: list[str], env: dict[str, str], timeout: float = 300, **kw,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "main", *args],
        cwd=PROJECT_ROOT, env=env, capture_output=True, text=True, timeout=timeout, **kw,
    )


@dataclass
class Layout:
    root: Path
    project: Path
    cc_source: Path
    codex_day: Path
    cursor_workspace: Path
    env: dict[str, str]

    def ingest(self, source: str, *extra: str) -> subprocess.CompletedProcess:
        return _run([
            "ingest", "--dir", str(self.project), "--source", source,
            "--force", "--min-size", "0", *extra,
        ], self.env)

    def scan(self, *extra: str) -> subprocess.CompletedProcess:
        return _run([
            "scan", "--dir", str(self.root / "work"), "--days", "0", "--out", "-", *extra,
        ], self.env)

    def report(self) -> dict:
        path = self.project / ".codess" / "last-ingest-report.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def stored(self, vendor: str = "cc") -> tuple[int, int]:
        store = self.project / ".codess" / f"sessions_{vendor}.db"
        if not store.exists():
            return 0, 0
        conn = sqlite3.connect(store)
        try:
            return conn.execute(
                "SELECT (SELECT COUNT(*) FROM sessions), (SELECT COUNT(*) FROM events)"
            ).fetchone()
        finally:
            conn.close()


def _restore_modes(root: Path) -> None:
    """Make a tree removable after a test revoked permissions inside it."""
    for path in [root, *root.rglob("*")]:
        with contextlib.suppress(OSError, NotImplementedError):
            path.chmod(0o700, follow_symlinks=False)


@pytest.fixture
def layout(durable_tmp_path):
    """A Project with one healthy Claude Source and empty Codex and Cursor roots.

    Placed under `durable_tmp_path` because ingest refuses OS temp locations as
    durable Projects.
    """
    root = durable_tmp_path
    project = root / "work" / "proj"
    project.mkdir(parents=True)
    cc_projects = root / "cc"
    cc_source = cc_projects / path_to_slug(project.resolve())
    cc_source.mkdir(parents=True)
    (cc_source / "good.jsonl").write_text(SAMPLE)
    codex_day = root / "codex" / "2026" / "09" / "20"
    codex_day.mkdir(parents=True)
    cursor_workspace = root / "cursor" / "User" / "workspaceStorage" / "ws1"
    cursor_workspace.mkdir(parents=True)
    (cursor_workspace / "workspace.json").write_text(
        json.dumps({"folder": project.resolve().as_uri()})
    )
    env = {
        **os.environ,
        "CODESS_CC_PROJECTS": str(cc_projects),
        "CODESS_CODEX_SESSIONS": str(root / "codex"),
        "CODESS_CODEX_ARCHIVED_SESSIONS": str(root / "codex-archived"),
        "CODESS_CURSOR_DATA": str(root / "cursor" / "User"),
        "CODESS_STORE_ROOT": str(root / "registry"),
    }
    yield Layout(root, project, cc_source, codex_day, cursor_workspace, env)
    _restore_modes(root)


def assert_contained(result: subprocess.CompletedProcess, command: str) -> None:
    assert ESCAPED_TRACEBACK not in result.stderr, result.stderr[-3000:]
    if command == "ingest":
        assert "Processed:" in result.stdout, result.stderr[-3000:]
    else:
        assert result.stdout.startswith("path,vendor"), result.stderr[-3000:]


def xfail_defect(reason: str):
    return pytest.mark.xfail(strict=True, reason=reason)


# -- Claude Code --------------------------------------------------------------

def _deep_json(depth: int = 100_000) -> str:
    return "[" * depth + "]" * depth


CLAUDE_TOLERATED: dict[str, Callable[[Path], object]] = {
    "empty_file": lambda d: (d / "h.jsonl").write_text(""),
    "invalid_utf8": lambda d: (d / "h.jsonl").write_bytes(
        b'{"type":"user","message":{"content":"\xff\xfe"}}\n\xc3\x28\n'
    ),
    "nul_bytes": lambda d: (d / "h.jsonl").write_bytes(b"\x00" * 5000 + b"\n"),
    "non_object_records": lambda d: (d / "h.jsonl").write_text(
        '[]\n1\nnull\n"s"\ntrue\n'
    ),
    "truncated_last_line": lambda d: (d / "h.jsonl").write_text(
        SAMPLE + '{"type":"assis'
    ),
    "duplicate_uuids": lambda d: (d / "h.jsonl").write_text("".join(
        json.dumps({"type": "user", "uuid": "u1", "sessionId": "s",
                    "message": {"role": "user", "content": "a"}}) + "\n"
        for _ in range(3)
    )),
    # Past MAX_RECORD_BYTES (2 MiB), which the lineage reader refuses as oversize.
    "oversize_record": lambda d: (d / "h.jsonl").write_text(
        '{"type":"user","message":{"content":"' + "x" * (3 << 20) + '"}}\n'
    ),
    "wrong_field_types": lambda d: (d / "h.jsonl").write_text("".join(
        json.dumps(record) + "\n" for record in [
            {"type": "assistant", "message": "a string, not an object"},
            {"type": "user", "message": {"content": [{"type": "tool_result",
                                                      "tool_use_id": 1}]}},
            {"type": "assistant", "timestamp": {"bad": 1}, "message": {"content": []}},
            {"type": 7, "uuid": ["x"], "parentUuid": {"a": 1}, "cwd": 5},
        ]
    )),
    "index_wrong_shape": lambda d: (d / "sessions-index.json").write_text(
        '{"entries": 5}'
    ),
    "subagent_dir_is_file": lambda d: (d / "good").write_text("x"),
}


@pytest.mark.parametrize("state", sorted(CLAUDE_TOLERATED))
def test_claude_ingest_tolerates_hostile_file(layout, state):
    CLAUDE_TOLERATED[state](layout.cc_source)

    result = layout.ingest("cc")

    assert_contained(result, "ingest")
    assert result.returncode == 0, result.stderr[-2000:]
    sessions, events = layout.stored()
    assert sessions >= 1 and events >= SAMPLE_EVENTS


def _chmod_000(directory: Path) -> None:
    path = directory / "h.jsonl"
    path.write_text(SAMPLE)
    path.chmod(0)


def _symlink_loop(directory: Path) -> None:
    (directory / "a.jsonl").symlink_to(directory / "b.jsonl")
    (directory / "b.jsonl").symlink_to(directory / "a.jsonl")


CLAUDE_UNREADABLE: dict[str, Callable[[Path], object]] = {
    "directory_named_jsonl": lambda d: (d / "h.jsonl").mkdir(),
    "broken_symlink": lambda d: (d / "h.jsonl").symlink_to(d / "nowhere"),
    "symlink_loop": _symlink_loop,
    "permission_denied": _chmod_000,
}


@pytest.mark.parametrize("state", sorted(CLAUDE_UNREADABLE))
def test_claude_ingest_reports_unreadable_source_and_stores_sibling(layout, state):
    if IS_ROOT and state == "permission_denied":
        pytest.skip("root ignores file modes")
    CLAUDE_UNREADABLE[state](layout.cc_source)

    result = layout.ingest("cc")

    assert_contained(result, "ingest")
    assert result.returncode == 1
    assert layout.report()["status"] == "completed_with_errors"
    assert layout.report()["diagnostics"]["failed_sources"] >= 1
    assert layout.stored() == (1, SAMPLE_EVENTS)


@xfail_defect(
    "RecursionError from get_cc_session_lineage (ingest_sources.py:357, outside the "
    "per-Source try; bounded_jsonl.py:55 catches only JSONDecodeError) fails the whole "
    "Project, so the healthy sibling Source is not stored"
)
def test_claude_ingest_deeply_nested_record_fails_only_its_source(layout):
    (layout.cc_source / "h.jsonl").write_text('{"type":"user","message":' + _deep_json() + "}\n")

    result = layout.ingest("cc")

    assert_contained(result, "ingest")
    assert layout.stored() == (1, SAMPLE_EVENTS)


@needs_permissions
@xfail_defect(
    "Path.glob in project.py:154 swallows PermissionError on an unreadable Claude "
    "Source directory; ingest reports status accepted with failed_sources=0"
)
def test_claude_ingest_reports_unreadable_source_directory(layout):
    layout.cc_source.chmod(0)

    result = layout.ingest("cc")

    assert_contained(result, "ingest")
    assert result.returncode == 1


@xfail_defect(
    "--no-progress detaches the HumanSink (ingest_cmd.py:1606), which also carries "
    "warnings: the run exits 1 with no reason on stderr"
)
def test_claude_ingest_absent_source_directory_states_reason_without_progress(layout):
    shutil.rmtree(layout.cc_source)
    layout.cc_source.write_text("not a directory")

    result = layout.ingest("cc", "--no-progress")

    assert_contained(result, "ingest")
    assert result.returncode == 1
    assert "vendor_dir_absent" in result.stderr


@xfail_defect(
    "per-Source handler uses log.exception (ingest_sources.py:453), so an expected "
    "OSError prints a traceback on the operator channel; the failure is also classed "
    "stage=record_mapping rather than source_validation"
)
def test_claude_unreadable_source_is_reported_without_traceback(layout):
    (layout.cc_source / "h.jsonl").mkdir()

    result = layout.ingest("cc")

    assert result.returncode == 1
    assert "Traceback" not in result.stderr


CLAUDE_SCAN_ROOT_KILLERS: dict[str, str | None] = {
    "entries_not_list": '{"entries": 5}',
    "document_is_list": "[]",
    "entry_is_string": '{"entries": ["x"]}',
    "project_path_is_int": '{"entries": [{"projectPath": 5}]}',
    "message_count_is_string": None,
}


def _index_for(layout: Layout, state: str) -> str:
    if state == "message_count_is_string":
        return json.dumps({"entries": [{
            "projectPath": str(layout.project.resolve()), "messageCount": "many",
            "fileMtime": 1, "sessionId": "good",
        }]})
    return CLAUDE_SCAN_ROOT_KILLERS[state] or ""


@pytest.mark.parametrize("state", sorted(CLAUDE_SCAN_ROOT_KILLERS))
@xfail_defect(
    "walk_sessions.py:129 (_session_metrics_cc) iterates sessions-index.json entries "
    "without shape checks and catches only JSONDecodeError/OSError/KeyError; "
    "walk_sessions.py:410 calls data.get on a non-dict. The TypeError/AttributeError "
    "fails the whole work root, dropping every Project under it"
)
def test_claude_scan_malformed_index_fails_only_its_project(layout, state):
    other = layout.root / "work" / "other"
    other.mkdir()
    other_source = Path(layout.env["CODESS_CC_PROJECTS"]) / path_to_slug(other.resolve())
    other_source.mkdir()
    (other_source / "s.jsonl").write_text(SAMPLE)
    (layout.cc_source / "sessions-index.json").write_text(_index_for(layout, state))

    result = layout.scan("--source", "cc")

    assert_contained(result, "scan")
    assert "failed_roots=0" in result.stderr or "failed_roots" not in result.stderr
    assert "other," in result.stdout


@needs_permissions
@xfail_defect(
    "walk_sessions.py:409 idx.exists() raises PermissionError outside the try that "
    "guards the index read; one unreadable Claude Source directory fails the work root"
)
def test_claude_scan_unreadable_source_directory_fails_only_its_project(layout):
    other = layout.root / "work" / "other"
    other.mkdir()
    other_source = Path(layout.env["CODESS_CC_PROJECTS"]) / path_to_slug(other.resolve())
    other_source.mkdir()
    (other_source / "s.jsonl").write_text(SAMPLE)
    layout.cc_source.chmod(0)

    result = layout.scan("--source", "cc")

    assert_contained(result, "scan")
    assert "other," in result.stdout


@pytest.mark.parametrize("state", ["directory_named_jsonl", "broken_symlink", "symlink_loop"])
def test_claude_scan_survives_unreadable_source(layout, state):
    CLAUDE_UNREADABLE[state](layout.cc_source)

    result = layout.scan("--source", "cc")

    assert_contained(result, "scan")
    assert "proj," in result.stdout


# -- Codex --------------------------------------------------------------------

def _codex_meta(session_id: str, cwd: Path) -> str:
    return json.dumps({
        "type": "session_meta", "timestamp": "2026-09-20T00:00:00Z",
        "payload": {"id": session_id, "cwd": str(cwd)},
    })


def _codex_message(text: str) -> str:
    return json.dumps({
        "type": "response_item", "timestamp": "2026-09-20T00:00:01Z",
        "payload": {"type": "message", "role": "user",
                    "content": [{"type": "input_text", "text": text}]},
    })


def _codex_session(session_id: str, cwd: Path) -> str:
    return "\n".join([
        _codex_meta(session_id, cwd), _codex_message("hello"), _codex_message("again"),
    ]) + "\n"


def _with_good_codex(layout: Layout) -> None:
    (layout.codex_day / "rollout-good.jsonl").write_text(
        _codex_session("good", layout.project.resolve())
    )


CODEX_TOLERATED: dict[str, Callable[[Path, Path], object]] = {
    "empty_file": lambda d, p: (d / "rollout-h.jsonl").write_text(""),
    "invalid_utf8": lambda d, p: (d / "rollout-h.jsonl").write_bytes(
        _codex_meta("h", p).encode() + b"\n\xff\xfe\x00\n"
    ),
    "nul_bytes": lambda d, p: (d / "rollout-h.jsonl").write_bytes(b"\x00" * 4096),
    "truncated_last_line": lambda d, p: (d / "rollout-h.jsonl").write_text(
        _codex_session("h", p) + '{"type":"resp'
    ),
    "duplicate_session_id": lambda d, p: (d / "rollout-h.jsonl").write_text(
        _codex_session("good", p)
    ),
    "meta_field_types": lambda d, p: (d / "rollout-h.jsonl").write_text(
        json.dumps({"type": "session_meta", "payload": {"id": 5, "cwd": ["x"]}})
        + "\n" + _codex_message("x") + "\n"
    ),
    "oversize_record": lambda d, p: (d / "rollout-h.jsonl").write_text(
        _codex_meta("h", p) + "\n"
        + '{"type":"event_msg","payload":{"x":"' + "y" * (3 << 20) + '"}}\n'
    ),
}


@pytest.mark.parametrize("state", sorted(CODEX_TOLERATED))
def test_codex_ingest_tolerates_hostile_file(layout, state):
    _with_good_codex(layout)
    CODEX_TOLERATED[state](layout.codex_day, layout.project.resolve())

    result = layout.ingest("codex")

    assert_contained(result, "ingest")
    assert result.returncode == 0, result.stderr[-2000:]
    assert layout.stored("codex")[0] >= 1


def test_codex_ingest_deeply_nested_record_fails_only_its_source(layout):
    _with_good_codex(layout)
    (layout.codex_day / "rollout-h.jsonl").write_text(
        _codex_meta("h", layout.project.resolve()) + "\n"
        + '{"type":"event_msg","payload":' + _deep_json() + "}\n"
    )

    result = layout.ingest("codex")

    assert_contained(result, "ingest")
    assert result.returncode == 1
    assert layout.report()["diagnostics"]["failed_sources"] == 1
    assert layout.stored("codex") == (1, 2)


CODEX_RUN_KILLERS: dict[str, Callable[[Path], str]] = {
    "non_object_first_line": lambda p: "[]\nnull\n5\n",
    "deep_first_line": lambda p: '{"type":"session_meta","payload":' + _deep_json() + "}\n",
    "meta_payload_is_list": lambda p: json.dumps(
        {"type": "session_meta", "payload": [1, 2]}
    ) + "\n",
    "meta_payload_is_string": lambda p: json.dumps(
        {"type": "session_meta", "payload": "str"}
    ) + "\n",
}


@pytest.mark.parametrize("command", ["ingest", "scan"])
@pytest.mark.parametrize("state", sorted(CODEX_RUN_KILLERS))
@xfail_defect(
    "codex_source.build_session_index runs once before the Project loop and is "
    "unguarded: record.get on a non-dict (codex_source.py:199), RecursionError from "
    "json.loads (:196, only JSONDecodeError caught), payload.get on a non-dict "
    "payload (:211). One rollout file aborts scan and ingest for every Project"
)
def test_codex_hostile_rollout_does_not_abort_run(layout, state, command):
    _with_good_codex(layout)
    (layout.codex_day / "rollout-h.jsonl").write_text(
        CODEX_RUN_KILLERS[state](layout.project.resolve())
    )

    result = layout.ingest("codex") if command == "ingest" else layout.scan()

    assert_contained(result, command)


def _codex_unreadable_subdir(day: Path, project: Path) -> None:
    other = day.parent / "21"
    other.mkdir()
    (other / "rollout-h.jsonl").write_text(_codex_session("h", project))
    other.chmod(0)


def _codex_unreadable_file(day: Path, project: Path) -> None:
    path = day / "rollout-h.jsonl"
    path.write_text(_codex_session("h", project))
    path.chmod(0)


CODEX_SILENT: dict[str, Callable[[Path, Path], object]] = {
    "directory_named_jsonl": lambda d, p: (d / "rollout-h.jsonl").mkdir(),
    "broken_symlink": lambda d, p: (d / "rollout-h.jsonl").symlink_to(d / "none"),
    "unreadable_file": _codex_unreadable_file,
    "unreadable_subdirectory": _codex_unreadable_subdir,
}


@pytest.mark.parametrize("state", sorted(CODEX_SILENT))
def test_codex_ingest_survives_unreadable_rollout(layout, state):
    if IS_ROOT and state.startswith("unreadable"):
        pytest.skip("root ignores file modes")
    _with_good_codex(layout)
    CODEX_SILENT[state](layout.codex_day, layout.project.resolve())

    result = layout.ingest("codex")

    assert_contained(result, "ingest")
    assert layout.stored("codex") == (1, 2)


@pytest.mark.parametrize("state", sorted(CODEX_SILENT))
@xfail_defect(
    "codex_source.build_session_index skips unreadable rollouts silently: rglob "
    "(codex_source.py:164) ignores unreadable directories, stat and open failures "
    "`continue` (:167, :203). A Codex Session that cannot be read is invisible; the "
    "run reports accepted with failed_sources=0"
)
def test_codex_ingest_reports_unreadable_rollout(layout, state):
    if IS_ROOT and state.startswith("unreadable"):
        pytest.skip("root ignores file modes")
    _with_good_codex(layout)
    CODEX_SILENT[state](layout.codex_day, layout.project.resolve())

    result = layout.ingest("codex")

    assert result.returncode == 1
    assert layout.report()["diagnostics"].get("failed_sources", 0) >= 1


# -- Cursor -------------------------------------------------------------------

def _good_cursor_db(path: Path) -> None:
    build_cursor_db(path, bubbles=[
        ("c1", "b1", {"type": 1, "text": "hi", "createdAt": "2026-09-20T00:00:00Z"}),
        ("c1", "b2", {"type": 2, "text": "ok"}),
    ])


def _sqlite(path: Path, *statements: tuple) -> None:
    conn = sqlite3.connect(path)
    try:
        for statement in statements:
            conn.execute(*statement)
        conn.commit()
    finally:
        conn.close()


def _corrupt_page(ws: Path) -> None:
    _good_cursor_db(ws / "state.vscdb")
    path = ws / "state.vscdb"
    body = bytearray(path.read_bytes())
    for offset in range(4096, min(len(body), 8192)):
        body[offset] = 0xAB
    path.write_bytes(bytes(body))


def _truncated_db(ws: Path) -> None:
    _good_cursor_db(ws / "state.vscdb")
    path = ws / "state.vscdb"
    body = path.read_bytes()
    path.write_bytes(body[: len(body) // 2 + 100])


def _chmod_db(ws: Path) -> None:
    _good_cursor_db(ws / "state.vscdb")
    (ws / "state.vscdb").chmod(0)


CURSOR_FAILED_SOURCE: dict[str, Callable[[Path], object]] = {
    "not_a_database": lambda ws: (ws / "state.vscdb").write_bytes(b"not sqlite" * 100),
    "empty_file": lambda ws: (ws / "state.vscdb").write_bytes(b""),
    "missing_tables": lambda ws: _sqlite(ws / "state.vscdb", ("CREATE TABLE x(a)",)),
    "wrong_columns": lambda ws: _sqlite(
        ws / "state.vscdb", ("CREATE TABLE cursorDiskKV(k, v, extra)",),
        ("INSERT INTO cursorDiskKV VALUES ('bubbleId:c:b', 1, 2)",),
    ),
    "deeply_nested_value": lambda ws: _sqlite(
        ws / "state.vscdb", ("CREATE TABLE cursorDiskKV(key TEXT PRIMARY KEY, value TEXT)",),
        ("INSERT INTO cursorDiskKV VALUES ('bubbleId:c1:b1', ?)", (_deep_json(),)),
    ),
    "corrupt_page": _corrupt_page,
    "truncated_database": _truncated_db,
    "database_is_directory": lambda ws: (ws / "state.vscdb").mkdir(),
    "permission_denied": _chmod_db,
}


@pytest.mark.parametrize("state", sorted(CURSOR_FAILED_SOURCE))
def test_cursor_ingest_reports_failed_database_and_stores_other_vendors(layout, state):
    if IS_ROOT and state == "permission_denied":
        pytest.skip("root ignores file modes")
    CURSOR_FAILED_SOURCE[state](layout.cursor_workspace)

    result = layout.ingest("all")

    assert_contained(result, "ingest")
    assert result.returncode == 1
    assert layout.report()["diagnostics"]["failed_sources"] >= 1
    assert layout.stored("cc") == (1, SAMPLE_EVENTS)


CURSOR_TOLERATED: dict[str, Callable[[Path], object]] = {
    "non_text_values": lambda ws: _sqlite(
        ws / "state.vscdb", ("CREATE TABLE cursorDiskKV(key TEXT, value BLOB)",),
        ("INSERT INTO cursorDiskKV VALUES ('bubbleId:c1:b1', ?)", (b"\xff\xfe\x00",)),
        ("INSERT INTO cursorDiskKV VALUES ('bubbleId:c1:b2', 5)",),
        ("INSERT INTO cursorDiskKV VALUES (NULL, NULL)",),
    ),
    "wal_without_main": lambda ws: (ws / "state.vscdb-wal").write_bytes(
        b"\x37\x7f\x06\x82" + b"\0" * 100
    ),
}


@pytest.mark.parametrize("state", sorted(CURSOR_TOLERATED))
def test_cursor_ingest_tolerates_hostile_database(layout, state):
    CURSOR_TOLERATED[state](layout.cursor_workspace)

    result = layout.ingest("all")

    assert_contained(result, "ingest")
    assert result.returncode == 0, result.stderr[-2000:]
    assert layout.stored("cc") == (1, SAMPLE_EVENTS)


@pytest.mark.parametrize("state", ["corrupt_page", "missing_tables", "not_a_database"])
def test_cursor_scan_reports_failed_database(layout, state):
    CURSOR_FAILED_SOURCE[state](layout.cursor_workspace)

    result = layout.scan()

    assert_contained(result, "scan")
    assert result.returncode == 1
    assert "failed_sources=1" in result.stderr
    assert "proj," in result.stdout


@pytest.mark.parametrize("body", ["[1,2", '{"folder": 5}'])
@xfail_defect(
    "ingest skips a Cursor workspace whose workspace.json is corrupt or mistyped "
    "with no diagnostic and exit 0; scan counts the corrupt form as malformed=1"
)
def test_cursor_ingest_reports_malformed_workspace_descriptor(layout, body):
    _good_cursor_db(layout.cursor_workspace / "state.vscdb")
    (layout.cursor_workspace / "workspace.json").write_text(body)

    result = layout.ingest("all")

    assert_contained(result, "ingest")
    assert "malformed" in result.stderr or result.returncode == 1


def test_cursor_ingest_survives_exclusively_locked_database(layout):
    """A writer holding an exclusive lock stalls the read; it must not abort it.

    Measured: about 21 s, several 5 s busy timeouts before `connect_readonly`
    falls back to an immutable open (cursor_source.py:68).
    """
    db = layout.cursor_workspace / "state.vscdb"
    _good_cursor_db(db)
    holder = subprocess.Popen(
        [sys.executable, "-c",
         "import sqlite3, sys, time\n"
         "c = sqlite3.connect(sys.argv[1], isolation_level=None)\n"
         "c.execute('BEGIN EXCLUSIVE')\n"
         "print('locked', flush=True)\n"
         "time.sleep(120)\n",
         str(db)],
        stdout=subprocess.PIPE, text=True,
    )
    try:
        assert holder.stdout.readline().strip() == "locked"
        result = layout.ingest("all")
    finally:
        holder.kill()
        holder.wait()

    assert_contained(result, "ingest")
    assert layout.stored("cc") == (1, SAMPLE_EVENTS)


# -- Non-regular files --------------------------------------------------------

HANG_LIMIT_SECONDS = 20


def _bounded(run: Callable[[], subprocess.CompletedProcess]) -> subprocess.CompletedProcess:
    try:
        return run()
    except subprocess.TimeoutExpired:
        pytest.fail(f"run did not finish within {HANG_LIMIT_SECONDS} s")


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="needs named pipes")
@xfail_defect(
    "a FIFO named rollout-*.jsonl blocks forever in open(): build_session_index "
    "(codex_source.py:187) opens every *.jsonl with no regular-file check, and scan "
    "builds that index for the default vendor set"
)
def test_codex_fifo_does_not_hang_scan(layout):
    os.mkfifo(layout.codex_day / "rollout-h.jsonl")

    result = _bounded(lambda: _run(
        ["scan", "--dir", str(layout.root / "work"), "--days", "0", "--out", "-"],
        layout.env, timeout=HANG_LIMIT_SECONDS,
    ))

    assert_contained(result, "scan")


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="needs named pipes")
@xfail_defect(
    "admission (ingest_pipeline.py:41, resources.check_source) tests st_size only; a "
    "FIFO has size 0, so with --min-size 0 it is admitted and open() blocks forever. "
    "The default --min-size skips it by accident"
)
def test_claude_fifo_does_not_hang_ingest(layout):
    os.mkfifo(layout.cc_source / "h.jsonl")

    result = _bounded(lambda: _run([
        "ingest", "--dir", str(layout.project), "--source", "cc", "--force",
        "--min-size", "0",
    ], layout.env, timeout=HANG_LIMIT_SECONDS))

    assert_contained(result, "ingest")
