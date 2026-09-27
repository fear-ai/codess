"""No Project, store, snapshot, or registry state may abort an ingest.

Two Projects are ingested together. After a healthy first run, each receives a
new Source, one Project's derived state is damaged, and the pair is ingested
again. The contract asserted:

- no traceback escapes `console_main`, and the run reaches its summary;
- the healthy Project is updated in the same run;
- the damaged Project's previously stored Sessions survive the failure;
- the exit status is 1 whenever a Project could not be ingested.

The same contract is checked for Source reads that race a writer, for a write
that hits the file-size limit, and for Project paths whose names are awkward
for a slug, a CSV, or a command line.
"""

from __future__ import annotations

import contextlib
import json
import os
import resource
import shutil
import sqlite3
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from codess.project import path_to_slug

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SAMPLE = (Path(__file__).parent / "fixtures" / "sample.jsonl").read_text()
ESCAPED_TRACEBACK = 'File "<frozen runpy>"'
IS_ROOT = hasattr(os, "geteuid") and os.geteuid() == 0


def _run(args: list[str], env: dict[str, str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "main", *args],
        cwd=PROJECT_ROOT, env=env, capture_output=True, text=True, timeout=300, **kw,
    )


def stored_sessions(project: Path) -> int | None:
    """Session count read without writing; None when the store cannot be opened."""
    store = project / ".codess" / "sessions_cc.db"
    try:
        conn = sqlite3.connect(f"{store.resolve().as_uri()}?mode=ro", uri=True)
        try:
            return conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        finally:
            conn.close()
    except sqlite3.Error:
        return None


def _restore_modes(root: Path) -> None:
    for path in [root, *root.rglob("*")]:
        with contextlib.suppress(OSError, NotImplementedError):
            path.chmod(0o700, follow_symlinks=False)


@dataclass
class Pair:
    root: Path
    damaged: Path
    healthy: Path
    damaged_source: Path
    healthy_source: Path
    registry: Path
    env: dict[str, str]

    def args(self) -> list[str]:
        return [
            "ingest", "--dir", str(self.damaged), "--dir", str(self.healthy),
            "--source", "cc", "--min-size", "0", "--no-progress",
        ]

    def ingest(self, **kw) -> subprocess.CompletedProcess:
        return _run(self.args(), self.env, **kw)

    def add_sources(self) -> None:
        (self.damaged_source / "new.jsonl").write_text(SAMPLE)
        (self.healthy_source / "new.jsonl").write_text(SAMPLE)


@pytest.fixture
def pair(durable_tmp_path):
    root = durable_tmp_path
    cc_projects = root / "cc"
    projects, sources = [], []
    for name in ("damaged", "healthy"):
        project = root / name
        project.mkdir()
        source = cc_projects / path_to_slug(project.resolve())
        source.mkdir(parents=True)
        (source / "good.jsonl").write_text(SAMPLE)
        projects.append(project)
        sources.append(source)
    env = {
        **os.environ,
        "CODESS_CC_PROJECTS": str(cc_projects),
        "CODESS_CODEX_SESSIONS": str(root / "codex"),
        "CODESS_CODEX_ARCHIVED_SESSIONS": str(root / "codex-archived"),
        "CODESS_CURSOR_DATA": str(root / "cursor" / "User"),
        "CODESS_STORE_ROOT": str(root / "registry"),
    }
    built = Pair(root, projects[0], projects[1], sources[0], sources[1], root / "registry", env)
    first = built.ingest()
    assert first.returncode == 0, first.stderr[-2000:]
    assert stored_sessions(built.damaged) == stored_sessions(built.healthy) == 1
    built.add_sources()
    yield built
    _restore_modes(root)


def assert_contained(result: subprocess.CompletedProcess) -> None:
    assert ESCAPED_TRACEBACK not in result.stderr, result.stderr[-3000:]
    assert "Processed:" in result.stdout, result.stderr[-3000:]


def _codess(pair: Pair) -> Path:
    return pair.damaged / ".codess"


def _overwrite_store(body: bytes) -> Callable[[Pair], object]:
    return lambda p: (_codess(p) / "sessions_cc.db").write_bytes(body)


def _corrupt_store_page(p: Pair) -> None:
    path = _codess(p) / "sessions_cc.db"
    body = bytearray(path.read_bytes())
    for offset in range(8192, min(len(body), 20000)):
        body[offset] = 0xAB
    path.write_bytes(bytes(body))


def _drop_sessions_table(p: Pair) -> None:
    conn = sqlite3.connect(_codess(p) / "sessions_cc.db")
    conn.execute("DROP TABLE sessions")
    conn.commit()
    conn.close()


def _store_is_directory(p: Pair) -> None:
    store = _codess(p) / "sessions_cc.db"
    store.unlink()
    store.mkdir()


def _codess_is_file(p: Pair) -> None:
    shutil.rmtree(_codess(p))
    _codess(p).write_text("not a directory")


def _pointer_to_nowhere(p: Pair) -> None:
    pointer = _codess(p) / "current.json"
    document = json.loads(pointer.read_text())
    document.update(path=str(p.registry / "nowhere"), snapshot_id="nope")
    pointer.write_text(json.dumps(document))


def _halve_snapshot_files(p: Pair) -> None:
    snapshot = Path(json.loads((_codess(p) / "current.json").read_text())["path"])
    for path in snapshot.iterdir():
        if path.is_file():
            body = path.read_bytes()
            path.write_bytes(body[: len(body) // 2])


def _write_text(relative: str, body: str) -> Callable[[Pair], object]:
    return lambda p: (_codess(p) / relative).write_text(body)


PROJECT_FAILS: dict[str, Callable[[Pair], object]] = {
    "codess_is_file": _codess_is_file,
    "store_not_a_database": _overwrite_store(b"garbage" * 1000),
    "store_corrupt_page": _corrupt_store_page,
    "store_missing_table": _drop_sessions_table,
    "store_is_directory": _store_is_directory,
    "pointer_malformed": _write_text("current.json", "{not json"),
    "pointer_wrong_type": _write_text("current.json", "[1, 2]"),
    "pointer_to_missing_snapshot": _pointer_to_nowhere,
    "binding_wrong_type": _write_text("project.json", '{"project_id": 5}'),
    # The manifest hash no longer matches, so the snapshot's raw records are refused.
    "half_written_snapshot": _halve_snapshot_files,
}


@pytest.mark.parametrize("state", sorted(PROJECT_FAILS))
def test_damaged_project_fails_alone(pair, state):
    PROJECT_FAILS[state](pair)
    before = stored_sessions(pair.damaged)

    result = pair.ingest()

    assert_contained(result)
    assert result.returncode == 1
    assert stored_sessions(pair.healthy) == 2
    # Whatever of the damaged store was readable before is still readable.
    assert stored_sessions(pair.damaged) == before


@pytest.mark.skipif(IS_ROOT, reason="root ignores file modes")
def test_unwritable_codess_directory_fails_alone(pair):
    _codess(pair).chmod(0o555)

    result = pair.ingest()

    assert_contained(result)
    assert result.returncode == 1
    assert stored_sessions(pair.healthy) == 2
    assert stored_sessions(pair.damaged) == 1


def test_locked_store_fails_alone(pair):
    """A second writer holding the store's exclusive lock fails only that Project.

    The failure arrives after the 5 s busy timeout (fileio.py:111); it must not
    stall or abort the run.
    """
    holder = subprocess.Popen(
        [sys.executable, "-c",
         "import sqlite3, sys, time\n"
         "c = sqlite3.connect(sys.argv[1], isolation_level=None)\n"
         "c.execute('BEGIN EXCLUSIVE')\n"
         "print('locked', flush=True)\n"
         "time.sleep(120)\n",
         str(_codess(pair) / "sessions_cc.db")],
        stdout=subprocess.PIPE, text=True,
    )
    try:
        assert holder.stdout.readline().strip() == "locked"
        result = pair.ingest()
    finally:
        holder.kill()
        holder.wait()

    assert_contained(result)
    assert result.returncode == 1
    assert stored_sessions(pair.healthy) == 2
    assert stored_sessions(pair.damaged) == 1


def _corrupt_registry_pointers(p: Pair) -> None:
    for path in p.registry.glob("projects/*/current.json"):
        path.write_text("nope")


def _leave_rebuild_directory(p: Pair) -> None:
    leftover = _codess(p) / ".rebuild-x"
    leftover.mkdir()
    (leftover / "sessions_cc.db").write_bytes(b"junk")


PROJECT_RECOVERS: dict[str, Callable[[Pair], object]] = {
    "ingest_state_corrupt": _write_text("ingest_state.json", "\x00\x01"),
    "registry_pointer_corrupt": _corrupt_registry_pointers,
    "rebuild_leftover": _leave_rebuild_directory,
    "orphan_wal": lambda p: (_codess(p) / "sessions_cc.db-wal").write_bytes(
        b"\x37\x7f\x06\x82" + b"\0" * 200
    ),
}


@pytest.mark.parametrize("state", sorted(PROJECT_RECOVERS))
def test_damaged_derived_state_is_rebuilt(pair, state):
    PROJECT_RECOVERS[state](pair)

    result = pair.ingest()

    assert_contained(result)
    assert result.returncode == 0, result.stderr[-2000:]
    assert stored_sessions(pair.healthy) == 2
    assert stored_sessions(pair.damaged) == 2


@pytest.mark.parametrize("body", ["{broken", "[]"])
def test_corrupt_registry_fails_run_without_touching_stores(pair, body):
    """A corrupt registry fails every Project, and must still leave each store intact.

    The registry is shared by every Project, so failing them all is correct; the
    run must still end in a summary.
    """
    for name in ("projects.json", "projects_state.json", "project-bindings.json"):
        (pair.registry / name).write_text(body)

    result = pair.ingest()

    assert_contained(result)
    assert result.returncode == 1
    assert stored_sessions(pair.healthy) == 1
    assert stored_sessions(pair.damaged) == 1


@pytest.mark.xfail(strict=True, reason=(
    "ingest_state.json marks good.jsonl current (ingest_pipeline.py:49 should_ingest) "
    "without checking the store it describes; a store truncated to 0 bytes is rebuilt "
    "empty, the Session is never restored, and the run exits 0"
))
def test_emptied_store_is_repopulated(pair):
    (_codess(pair) / "sessions_cc.db").write_bytes(b"")

    result = pair.ingest()

    assert_contained(result)
    assert stored_sessions(pair.damaged) == 2


def test_file_size_limit_fails_cleanly_and_next_run_recovers(pair):
    """A write past the file-size limit fails the run; the next run recovers.

    Disk-full stand-in: RLIMIT_FSIZE turns writes past the limit into EFBIG
    (Python ignores SIGXFSZ). The failed run leaves a hot rollback journal; the
    next read-write open rolls it back.
    """
    def limit_file_size():
        resource.setrlimit(resource.RLIMIT_FSIZE, (300_000, 300_000))

    result = pair.ingest(preexec_fn=limit_file_size)

    assert_contained(result)
    assert result.returncode == 1

    recovered = pair.ingest()

    assert recovered.returncode == 0, recovered.stderr[-2000:]
    assert stored_sessions(pair.damaged) == stored_sessions(pair.healthy) == 2
    conn = sqlite3.connect(_codess(pair) / "sessions_cc.db")
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        conn.close()


# -- Stored Sessions after a Source turns hostile -----------------------------

def _replace_with_directory(source: Path) -> None:
    (source / "good.jsonl").unlink()
    (source / "good.jsonl").mkdir()


def _replace_with_broken_symlink(source: Path) -> None:
    (source / "good.jsonl").unlink()
    (source / "good.jsonl").symlink_to(source / "none")


SOURCE_TURNS_HOSTILE: dict[str, Callable[[Path], object]] = {
    "file_deleted": lambda d: (d / "good.jsonl").unlink(),
    "directory_removed": lambda d: shutil.rmtree(d),
    "replaced_by_directory": _replace_with_directory,
    "broken_symlink": _replace_with_broken_symlink,
    "deeply_nested": lambda d: (d / "good.jsonl").write_text(
        '{"a":' + "[" * 100_000 + "]" * 100_000 + "}\n"
    ),
}


@pytest.mark.parametrize("state", sorted(SOURCE_TURNS_HOSTILE))
def test_stored_session_survives_source_turning_hostile(pair, state):
    SOURCE_TURNS_HOSTILE[state](pair.damaged_source)

    result = pair.ingest()

    assert_contained(result)
    assert stored_sessions(pair.healthy) == 2
    assert stored_sessions(pair.damaged) >= 1


@pytest.mark.parametrize("body", [b"", b"\xff\x00garbage\n"])
@pytest.mark.xfail(strict=True, reason=(
    "a Source rewritten to zero decodable records commits session=None "
    "(ingest_sources.py:428-446 via commit_source_replacement), deleting the stored "
    "Session with exit 0; only empty_sources/malformed_records count it"
))
def test_stored_session_survives_source_losing_every_record(pair, body):
    (pair.damaged_source / "good.jsonl").write_bytes(body)

    result = pair.ingest()

    assert_contained(result)
    assert stored_sessions(pair.damaged) == 2


# -- Reads that race a writer -------------------------------------------------

RACE_DRIVER = r'''
import os, sys
from pathlib import Path
sys.path.insert(0, "src")
import codess.ingest_sources as ingest

mode, target = os.environ["RACE_MODE"], os.environ["RACE_TARGET"]
lineage, process = ingest.get_cc_session_lineage, ingest.process_cc_file

def racing_lineage(path, *args, **kwargs):
    if mode == "deleted_before_lineage" and Path(path).name == target:
        Path(path).unlink()
    return lineage(path, *args, **kwargs)

def racing_process(path, *args, **kwargs):
    if Path(path).name == target:
        text = Path(path).read_text() if Path(path).exists() else ""
        if mode == "deleted_before_decode":
            Path(path).unlink()
        elif mode == "appended_during_read":
            with open(path, "a") as stream:
                stream.write(text * 3)
        elif mode == "shrunk_during_read":
            Path(path).write_text(text[: len(text) // 3])
    return process(path, *args, **kwargs)

ingest.get_cc_session_lineage = racing_lineage
ingest.process_cc_file = racing_process
sys.argv = ["codess", *sys.argv[1:]]
from codess.project import console_main
sys.exit(console_main())
'''


@pytest.mark.parametrize("mode, code", [
    ("deleted_before_lineage", 1),
    ("deleted_before_decode", 1),
    ("appended_during_read", 0),
    ("shrunk_during_read", 0),
])
def test_source_changing_during_read_is_contained(pair, mode, code):
    """Listing, lineage, and decode each open the file; it may change between them."""
    (pair.damaged_source / "racy.jsonl").write_text(SAMPLE)
    env = {**pair.env, "RACE_MODE": mode, "RACE_TARGET": "racy.jsonl"}

    result = subprocess.run(
        [sys.executable, "-c", RACE_DRIVER, *pair.args()[0:]],
        cwd=PROJECT_ROOT, env=env, capture_output=True, text=True, timeout=300,
    )

    assert "Traceback (most recent call last):\n  File \"<string>\"" not in result.stderr
    assert "Processed:" in result.stdout, result.stderr[-3000:]
    assert result.returncode == code
    assert stored_sessions(pair.healthy) == 2
    assert stored_sessions(pair.damaged) >= 2


# -- Awkward Project names ----------------------------------------------------

def _claude_session(cwd: Path, session_id: str) -> str:
    return "".join(json.dumps({
        "type": kind, "cwd": str(cwd), "sessionId": session_id,
        "uuid": f"{session_id}-{index}", "timestamp": f"2026-09-20T00:00:0{index}Z",
        "message": {"role": kind, "content": [{"type": "text", "text": "x"}]},
    }) + "\n" for index, kind in enumerate(["user", "assistant"]))


def _named_layout(root: Path, names: list[str]) -> tuple[list[Path], dict[str, str]]:
    work, cc_projects = root / "work", root / "cc"
    projects = []
    for name in names:
        project = work / name
        project.mkdir(parents=True)
        projects.append(project)
    source = cc_projects / path_to_slug(projects[0].resolve())
    source.mkdir(parents=True)
    (source / "s1.jsonl").write_text(_claude_session(projects[0].resolve(), "s1"))
    env = {
        **os.environ,
        "CODESS_CC_PROJECTS": str(cc_projects),
        "CODESS_CODEX_SESSIONS": str(root / "codex"),
        "CODESS_CURSOR_DATA": str(root / "cursor" / "User"),
        "CODESS_STORE_ROOT": str(root / "registry"),
    }
    return projects, env


@pytest.mark.parametrize("name", ["my proj", "pröj-日本", "a\nb", "-rf", "a.b_c", "--dir"])
def test_awkward_project_name_scans_and_ingests(durable_tmp_path, name):
    (project,), env = _named_layout(durable_tmp_path, [name])

    scan = _run(["scan", "--dir", str(durable_tmp_path / "work"), "--days", "0",
                 "--out", "-", "--source", "cc"], env)
    ingest = _run(["ingest", "--dir", str(project), "--source", "cc", "--force",
                   "--min-size", "0", "--no-progress"], env)

    assert ESCAPED_TRACEBACK not in scan.stderr + ingest.stderr
    assert scan.returncode == 0 and ingest.returncode == 0, ingest.stderr[-2000:]
    assert len(scan.stdout.strip().splitlines()) >= 2
    assert stored_sessions(project) == 1


@pytest.mark.xfail(strict=True, reason=(
    "path_to_slug maps '/' to '-', so work/a/b and work/a-b share one Claude slug; "
    "ingest of work/a/b stores a-b's Session although every record's cwd names a-b"
))
def test_slug_separator_collision_does_not_misattribute_sessions(durable_tmp_path):
    (_owner, other), env = _named_layout(durable_tmp_path, ["a-b", "a/b"])

    result = _run(["ingest", "--dir", str(other), "--source", "cc", "--force",
                   "--min-size", "0", "--no-progress"], env)

    assert ESCAPED_TRACEBACK not in result.stderr
    assert not stored_sessions(other)
