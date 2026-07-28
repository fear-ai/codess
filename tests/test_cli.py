"""CLI edge cases: no store, no mode, empty dir, idempotent."""

import csv
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

from codess.project import path_to_slug


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


def test_invalid_integer_config_is_fatal_for_every_command():
    """Malformed integer env values produce a useful error, not an import traceback."""
    with tempfile.TemporaryDirectory() as tmp:
        env = os.environ.copy()
        env["CODESS_DAYS"] = "recent"
        for command in ("scan", "ingest", "query"):
            r = _run([command, "--dir", tmp], env=env)
            assert r.returncode == 1
            assert "CODESS_DAYS='recent' must be an integer" in r.stderr
            assert "Traceback" not in r.stderr


def test_invalid_config_range_is_fatal_for_every_command():
    """All command families enforce the same validated environment contract."""
    with tempfile.TemporaryDirectory() as tmp:
        env = os.environ.copy()
        env["CODESS_MIN_SIZE"] = "-1"
        for command in ("scan", "ingest", "query"):
            r = _run([command, "--dir", tmp], env=env)
            assert r.returncode == 1
            assert "CODESS_MIN_SIZE=-1 must be >= 0" in r.stderr


def test_query_no_store_exit_1():
    """Query before any ingest exits 1."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        r = _run(["query", "--dir", str(tmp), "--tool", "0"])
        assert r.returncode == 1
        assert "No store" in r.stderr or "store" in r.stderr.lower()


def test_query_reports_invalid_snapshot_without_traceback():
    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp)
        state = project / ".codess"
        state.mkdir()
        (state / "current.json").write_text(
            json.dumps({"path": "snapshots/missing", "manifest_sha256": "bad"}),
            encoding="utf-8",
        )
        result = _run(["query", "--dir", str(project), "--stats"])
        assert result.returncode == 1
        assert "cannot open query stores" in result.stderr
        assert "Traceback" not in result.stderr


def test_query_aggregates_multiple_project_roots():
    """Query totals span roots while registry counts remain project-local."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        first = tmp / "first"
        second = tmp / "second"
        first.mkdir()
        second.mkdir()
        for index, project in enumerate((first, second)):
            store = project / ".codess" / "sessions_cc.db"
            init_db(store)
            conn = sqlite3.connect(store)
            conn.execute(
                "INSERT INTO sessions "
                "(id, source, type, started_at, project_path) "
                "VALUES (?, ?, ?, ?, ?)",
                (f"s{index}", "Claude", "Code", index + 1, str(project)),
            )
            conn.commit()
            conn.close()
        registry = tmp / "registry"
        env = {**os.environ, "CODESS_REGISTRY": str(registry)}
        r = _run(
            ["query", "--dir", str(first), "--dir", str(second), "--stats"],
            env=env,
        )
        assert r.returncode == 0
        assert "Sessions: 2" in r.stdout
        data = json.loads((registry / "ingested_projects.json").read_text())
        counts = {entry["path"]: entry["query"]["sessions"] for entry in data["projects"]}
        assert counts == {str(first.resolve()): 1, str(second.resolve()): 1}


def test_query_aggregates_multiple_vendor_stores():
    """Query reports every populated vendor DB in a project."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = Path(tmp)
        stores = [
            proj / ".codess" / "sessions_cc.db",
            proj / ".codess" / "sessions_codex.db",
        ]
        for index, store in enumerate(stores):
            init_db(store)
            conn = sqlite3.connect(store)
            conn.execute(
                "INSERT INTO sessions "
                "(id, source, type, started_at) VALUES (?, ?, ?, ?)",
                (f"s{index}", "test", "Code", 1),
            )
            conn.commit()
            conn.close()
        env = {**os.environ, "CODESS_REGISTRY": str(proj / "registry")}
        r = _run(["query", "--dir", str(proj), "--stats"], env=env)
        assert r.returncode == 0
        assert "Sessions: 2" in r.stdout


def test_query_duplicate_session_ids_route_by_global_number():
    """Duplicate vendor session IDs remain distinct behind global session numbers."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = Path(tmp)
        stores = [
            (proj / ".codess" / "sessions_cc.db", "Claude", 1000, "old"),
            (proj / ".codess" / "sessions_codex.db", "Codex", 2000, "new"),
        ]
        for store, source, timestamp, content in stores:
            init_db(store)
            conn = sqlite3.connect(store)
            conn.execute(
                "INSERT INTO sessions "
                "(id, source, type, started_at, ended_at, project_path) "
                "VALUES ('same', ?, 'Code', ?, ?, ?)",
                (source, timestamp, timestamp, str(proj)),
            )
            conn.execute(
                "INSERT INTO events "
                "(session_id, event_id, event_type, subtype, role, content, timestamp) "
                "VALUES ('same', 'e1', 'user_message', 'prompt', 'user', ?, ?)",
                (content, timestamp),
            )
            conn.execute(
                "INSERT INTO events "
                "(session_id, event_id, event_type, tool_name, timestamp) "
                "VALUES ('same', 'e2', 'tool_call', ?, ?)",
                ("Read" if source == "Codex" else "Bash", timestamp),
            )
            conn.commit()
            conn.close()
        env = {**os.environ, "CODESS_REGISTRY": str(proj / "registry")}

        listed = _run(
            ["query", "--dir", str(proj), "--sessions", "--id"], env=env
        )
        shown = _run(
            ["query", "--dir", str(proj), "-sess", "1", "--show", "prompt"],
            env=env,
        )
        tools = _run(["query", "--dir", str(proj), "--tool", "0"], env=env)

        assert listed.returncode == 0
        rows = listed.stdout.strip().splitlines()
        codex_fields = rows[1].split("\t")
        claude_fields = rows[2].split("\t")
        assert codex_fields[0] == "same"
        assert codex_fields[2:4] == ["1", "Codex"]
        assert claude_fields[0] == "same"
        assert claude_fields[2:4] == ["2", "Claude"]
        assert codex_fields[1].startswith("codess:session:sha256:")
        assert claude_fields[1].startswith("codess:session:sha256:")
        assert codex_fields[1] != claude_fields[1]
        assert shown.returncode == 0
        assert "new" in shown.stdout
        assert "old" not in shown.stdout
        assert tools.returncode == 0
        assert "Read" in tools.stdout
        assert "Bash" in tools.stdout


def test_query_scales_beyond_sqlite_attach_limit():
    """Independent read-only connections allow aggregation over more than ten stores."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        roots = []
        for project_index in range(4):
            project = tmp / f"project-{project_index}"
            project.mkdir()
            roots.append(project)
            for store_index, filename in enumerate(
                ("sessions_cc.db", "sessions_codex.db", "sessions_cursor.db")
            ):
                store = project / ".codess" / filename
                init_db(store)
                conn = sqlite3.connect(store)
                conn.execute(
                    "INSERT INTO sessions "
                    "(id, source, type, started_at) VALUES (?, 'test', 'Code', ?)",
                    (f"s-{project_index}-{store_index}", project_index * 10 + store_index),
                )
                conn.commit()
                conn.close()
        command = ["query", "--stats"]
        for project in roots:
            command.extend(["--dir", str(project)])
        env = {**os.environ, "CODESS_REGISTRY": str(tmp / "registry")}

        r = _run(command, env=env)

        assert r.returncode == 0
        assert "Sessions: 12" in r.stdout


def test_query_warns_for_root_without_store_and_counts_it_as_zero():
    """Mixed batches remain useful while missing roots are explicit in stderr/registry."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        populated = tmp / "populated"
        empty = tmp / "empty"
        populated.mkdir()
        empty.mkdir()
        store = populated / ".codess" / "sessions_cc.db"
        init_db(store)
        conn = sqlite3.connect(store)
        conn.execute(
            "INSERT INTO sessions "
            "(id, source, type, started_at) VALUES ('s1', 'Claude', 'Code', 1)"
        )
        conn.commit()
        conn.close()
        registry = tmp / "registry"
        env = {**os.environ, "CODESS_REGISTRY": str(registry)}

        r = _run(
            ["query", "--dir", str(populated), "--dir", str(empty), "--stats"],
            env=env,
        )

        assert r.returncode == 0
        assert f"warning: no store found for {empty.resolve()}" in r.stderr
        data = json.loads((registry / "ingested_projects.json").read_text())
        counts = {entry["path"]: entry["query"]["sessions"] for entry in data["projects"]}
        assert counts[str(populated.resolve())] == 1
        assert counts[str(empty.resolve())] == 0


def test_query_aggregates_permissions_and_task_review():
    """Permission and task reports merge events from every selected store."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        roots = [tmp / "first", tmp / "second"]
        for index, project in enumerate(roots):
            project.mkdir()
            store = project / ".codess" / "sessions_cc.db"
            init_db(store)
            conn = sqlite3.connect(store)
            conn.execute(
                "INSERT INTO sessions "
                "(id, source, type, started_at) VALUES (?, 'Claude', 'Code', ?)",
                (f"s{index}", index + 1),
            )
            conn.execute(
                "INSERT INTO events "
                "(session_id, event_id, event_type, subtype, tool_name, timestamp) "
                "VALUES (?, 'permission', 'user_message', 'permission_denied', 'Bash', ?)",
                (f"s{index}", index + 1),
            )
            conn.execute(
                "INSERT INTO events "
                "(session_id, event_id, event_type, subtype, tool_name, timestamp) "
                "VALUES (?, 'failure', 'user_message', 'tool_failure', 'Read', ?)",
                (f"s{index}", index + 1.5),
            )
            conn.execute(
                "INSERT INTO events "
                "(session_id, event_id, event_type, tool_name, tool_input, timestamp) "
                "VALUES (?, 'task', 'tool_call', 'Task', ?, ?)",
                (f"s{index}", json.dumps({"description": f"task {index}"}), index + 1),
            )
            if index == 0:
                conn.execute(
                    "INSERT INTO events "
                    "(session_id, event_id, event_type, subtype, content_len, "
                    "timestamp, metadata) VALUES (?, 'compact-summary', "
                    "'system_event', 'context_compaction_summary', 123, 10, ?)",
                    (
                        f"s{index}",
                        json.dumps({"content_truncated": True}),
                    ),
                )
            conn.commit()
            conn.close()
        root_args = ["--dir", str(roots[0]), "--dir", str(roots[1])]

        permissions = _run(["query", *root_args, "--permissions"])
        audit = _run(["query", *root_args, "--audit", "--limit", "3"])
        audit_all = _run(["query", *root_args, "--audit"])
        tasks = _run(["query", *root_args, "--task-review"])

        assert permissions.returncode == 0
        assert str(roots[0].resolve()) in permissions.stdout
        assert str(roots[1].resolve()) in permissions.stdout
        assert audit.returncode == 0
        audit_rows = audit.stdout.strip().splitlines()
        assert len(audit_rows) == 4  # header plus one global three-row window
        assert "permission_denied" in audit.stdout
        assert "tool_failure" in audit.stdout
        assert "context_compaction_summary" in audit_all.stdout
        assert "characters=123,truncated=true" in audit_all.stdout
        assert tasks.returncode == 0
        assert "Task\t2" in tasks.stdout
        assert "task 0" in tasks.stdout and "task 1" in tasks.stdout


def test_query_lineage_and_session_metadata_report():
    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp)
        store = project / ".codess" / "sessions_codex.db"
        init_db(store)
        conn = sqlite3.connect(store)
        conn.execute(
            "INSERT INTO sessions "
            "(id, source, type, release, started_at, metadata) "
            "VALUES ('s1', 'Codex', 'Code', '1.2.3', 1, ?)",
            (json.dumps({"originator": "codex_cli_rs", "source": "cli"}),),
        )
        conn.executemany(
            "INSERT INTO events "
            "(session_id, event_id, event_type, subtype, tool_name, "
            "content_len, timestamp, metadata) "
            "VALUES ('s1', ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    "call-1", "tool_call", None, "shell", None, 1,
                    json.dumps({"call_id": "lineage-1", "status": "completed"}),
                ),
                (
                    "result-1", "user_message", "tool_result", "shell", 12, 2,
                    json.dumps({"call_id": "lineage-1"}),
                ),
                (
                    "call-2", "tool_call", None, "apply_patch", None, 3,
                    json.dumps({"call_id": "lineage-2"}),
                ),
                (
                    "orphan", "user_message", "tool_result", "Read", 5, 4,
                    json.dumps({"tool_use_id": "orphan-id"}),
                ),
                (
                    "call-3", "tool_call", None, "shell", None, 5,
                    json.dumps({"call_id": "lineage-3"}),
                ),
                (
                    "result-3", "user_message", "tool_failure", "shell", 9, 6,
                    json.dumps({"call_id": "lineage-3"}),
                ),
            ],
        )
        conn.commit()
        conn.close()

        lineage = _run(["query", "--dir", str(project), "--lineage"])
        sessions = _run(["query", "--dir", str(project), "--sessions"])
        limited_lineage = _run(
            ["query", "--dir", str(project), "--lineage", "--limit", "1"]
        )
        zero_sessions = _run(
            ["query", "--dir", str(project), "--sessions", "--limit", "0"]
        )

        assert lineage.returncode == 0
        assert "lineage-1\tcompleted\tresult\t12" in lineage.stdout
        assert "lineage-2\t\tmissing_result" in lineage.stdout
        assert "orphan-id\t\tunlinked_result\t5" in lineage.stdout
        assert "lineage-3\t\ttool_failure\t9" in lineage.stdout
        assert sessions.returncode == 0
        assert "1.2.3" in sessions.stdout
        assert "originator=codex_cli_rs,source=cli" in sessions.stdout
        assert len(limited_lineage.stdout.strip().splitlines()) == 2
        assert zero_sessions.stdout == ""


def test_query_rejects_negative_limit():
    r = _run(["query", "--limit", "-1", "--sessions"])
    assert r.returncode == 1
    assert "--limit must be >= 0" in r.stderr


def test_query_v2_diagnostics_and_cross_vendor_artifacts():
    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp)
        fixture = json.loads(
            (Path(__file__).parents[1] / "schema/coschema/fixtures/golden/"
             "cross-vendor-artifact.json").read_text()
        )
        suffixes = {"Claude": "cc", "Codex": "codex"}
        for source in fixture["sources"]:
            suffix = suffixes[source]
            store = project / ".codess" / f"sessions_{suffix}.db"
            init_db(store)
            conn = connect(store)
            replace_session_events(
                conn,
                {"id": f"s-{suffix}", "source": source, "type": "Code", "project_path": str(project)},
                [{
                    "session_id": f"s-{suffix}", "event_id": "1",
                    "event_type": "tool_call", "role": "assistant",
                    "tool_name": "Read",
                    "tool_input": json.dumps({"path": fixture["artifact_path"]}),
                }],
                session_id=f"s-{suffix}",
            )
            conn.commit()
            conn.close()

        artifacts = _run(["query", "--dir", str(project), "--artifacts"])
        diagnostics = _run(["query", "--dir", str(project), "--diagnostics"])
        assert artifacts.returncode == 0
        assert (
            f"{fixture['artifact_path']}\t{','.join(fixture['sources'])}\t"
            f"{fixture['expected']['source_count']}\t{fixture['operation']}\t"
            f"{fixture['expected']['event_count']}\t"
            f"{fixture['expected']['artifact_rows_across_stores']}"
        ) in artifacts.stdout
        assert diagnostics.returncode == 0
        assert diagnostics.stdout.count("missing_tool_call_id") == 2


def test_query_can_select_an_exact_retained_snapshot_without_registry_update():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        project = root / "project"
        project.mkdir()
        working = root / "sessions_codex.db"
        init_db(working)
        conn = connect(working)
        replace_session_events(
            conn,
            {"id": "historical", "source": "Codex", "type": "Code"},
            [{
                "session_id": "historical", "event_id": "prompt",
                "event_type": "user_message", "subtype": "prompt",
                "role": "user", "content": "history",
            }],
            session_id="historical",
        )
        conn.commit()
        conn.close()
        snapshot = create_snapshot(
            project, [working], [], raw_store=RawStore(root / "raw")
        )
        registry = root / "registry"
        result = _run([
            "query", "--dir", str(project), "--snapshot-id", snapshot.name,
            "--registry", str(registry), "--stats",
        ])
        assert result.returncode == 0
        assert "Sessions: 1" in result.stdout and "Events: 1" in result.stdout
        assert not (registry / "ingested_projects.json").exists()


def test_query_no_mode_exit_1():
    """Query without a mode flag exits 1."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        # Create empty store
        (tmp / ".codess").mkdir()
        init_db(tmp / ".codess" / "sessions.db")
        r = _run(["query", "--dir", str(tmp)])
        assert r.returncode == 1
        assert "Specify" in r.stderr


def test_ingest_no_cc_dir_exit_1():
    """Ingest --source cc when no CC project dir exits 1."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        proj = tmp / "orphan"
        proj.mkdir()
        env = os.environ.copy()
        env["CODESS_CC_PROJECTS"] = str(tmp)
        r = _run(["ingest", "--source", "cc", "--dir", str(proj), "--min-size", "0"], env=env)
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
        env["CODESS_CC_PROJECTS"] = str(cc_dir)
        r = _run(["ingest", "--source", "cc", "--dir", str(proj), "--min-size", "0"], env=env)
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
        env["CODESS_CC_PROJECTS"] = str(cc_dir)
        r = _run(["ingest", "--dir", str(proj), "--source", "cc", "--force", "--min-size", "0"], env=env)
        assert r.returncode == 0


def test_query_empty_store():
    """Query --tool 0 on empty store: empty output, exit 0."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        proj = tmp / "proj"
        proj.mkdir()
        cc_dir = tmp / "cc"
        cc_dir.mkdir()
        slug = path_to_slug(proj.resolve())
        (cc_dir / slug).mkdir(parents=True)
        env = os.environ.copy()
        env["CODESS_CC_PROJECTS"] = str(cc_dir)
        _run(["ingest", "--dir", str(proj), "--source", "cc", "--min-size", "0"], env=env)
        r = _run(["query", "--dir", str(proj), "--tool", "0"], env=env)
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
        env["CODESS_CC_PROJECTS"] = str(cc_dir)
        r1 = _run(["ingest", "--dir", str(proj), "--source", "cc", "--force", "--min-size", "0"], env=env)
        assert r1.returncode == 0
        r2 = _run(["query", "--dir", str(proj), "--tool", "0"], env=env)
        lines1 = r2.stdout.strip().split("\n")
        r3 = _run(["ingest", "--dir", str(proj), "--source", "cc", "--force", "--min-size", "0"], env=env)
        r4 = _run(["query", "--dir", str(proj), "--tool", "0"], env=env)
        lines2 = r4.stdout.strip().split("\n")
        assert sorted(lines1) == sorted(lines2)


def test_ingest_shows_stats():
    """Ingest distinguishes processed work from stored totals."""
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
        env["CODESS_CC_PROJECTS"] = str(cc_dir)
        r = _run(["ingest", "--dir", str(proj), "--source", "cc", "--force", "--min-size", "0"], env=env)
        assert r.returncode == 0
        assert "Processed:" in r.stdout and "Stored:" in r.stdout


def test_query_stats():
    """Query --stats prints sessions and events; merges query counts into registry."""
    import json

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        proj = tmp / "proj"
        proj.mkdir()
        cc_dir = tmp / "cc"
        cc_dir.mkdir()
        reg = tmp / "central_reg"
        reg.mkdir()
        slug = path_to_slug(proj.resolve())
        (cc_dir / slug).mkdir(parents=True)
        fixture = Path(__file__).parent / "fixtures" / "sample.jsonl"
        shutil.copy(fixture, cc_dir / slug / "s1.jsonl")
        env = os.environ.copy()
        env["CODESS_CC_PROJECTS"] = str(cc_dir)
        env["CODESS_REGISTRY"] = str(reg)
        _run(["ingest", "--dir", str(proj), "--source", "cc", "--force", "--min-size", "0"], env=env)
        r = _run(["query", "--dir", str(proj), "--stats"], env=env)
        assert r.returncode == 0
        assert "Sessions:" in r.stdout and "Events:" in r.stdout
        data = json.loads((reg / "ingested_projects.json").read_text())
        ent = next(p for p in data["projects"] if p["path"] == str(proj.resolve()))
        assert "query" in ent
        assert "sessions" in ent["query"]


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
        env["CODESS_CC_PROJECTS"] = str(cc_dir)
        _run(["ingest", "--dir", str(proj), "--source", "cc", "--force", "--min-size", "0"], env=env)
        r = _run(["query", "--dir", str(proj), "--taxonomy"], env=env)
        assert r.returncode == 0
        assert "tool_call" in r.stdout and "user_message" in r.stdout


def test_query_sessions_with_id():
    """Query --sessions --id includes global and display identities."""
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
        env["CODESS_CC_PROJECTS"] = str(cc_dir)
        _run(["ingest", "--dir", str(proj), "--source", "cc", "--force", "--min-size", "0"], env=env)
        r = _run(["query", "--dir", str(proj), "--sessions", "--id"], env=env)
        assert r.returncode == 0
        assert "global_id" in r.stdout and "num" in r.stdout and "\t1\t" in r.stdout


def test_ingest_source_codex_only():
    """Ingest --source codex with no Codex data: success, 0 ingested."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        proj = tmp / "proj"
        proj.mkdir()
        codex_empty = tmp / "codex_empty" / "sessions"
        codex_empty.mkdir(parents=True)
        env = os.environ.copy()
        env["CODESS_CODEX_SESSIONS"] = str(codex_empty)
        r = _run(["ingest", "--dir", str(proj), "--source", "codex", "--min-size", "0"], env=env)
        assert r.returncode == 0
        assert "0 session" in r.stdout or "0 event" in r.stdout


def test_ingest_cursor_global():
    """Ingest --source cursor uses global storage when present."""
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
        env["CODESS_CURSOR_DATA"] = str(cursor_base)
        r = _run(["ingest", "--dir", str(proj), "--source", "cursor", "--force"], env=env)
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
        env["CODESS_CC_PROJECTS"] = str(cc_dir)
        r = _run(["ingest", "--dir", str(proj), "--source", "cc", "--force", "--min-size", "0"], env=env)
        assert r.returncode == 0
        assert "ignored=2" in r.stderr
        r2 = _run(["query", "--dir", str(proj), "--sessions"], env=env)
        # May or may not have session row (we don't upsert session if 0 events)
        assert r2.returncode == 0


def test_ingest_malformed_record_reports_aggregate_and_continues():
    """Malformed JSON is tolerated but represented in the final diagnostics."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        proj = tmp / "proj"
        proj.mkdir()
        cc_projects = tmp / "cc"
        slug_dir = cc_projects / path_to_slug(proj.resolve())
        slug_dir.mkdir(parents=True)
        shutil.copy(
            Path(__file__).parent / "fixtures" / "malformed.jsonl",
            slug_dir / "mixed.jsonl",
        )
        env = {**os.environ, "CODESS_CC_PROJECTS": str(cc_projects)}

        r = _run(
            ["ingest", "--dir", str(proj), "--source", "cc", "--force", "--min-size", "0"],
            env=env,
        )

        assert r.returncode == 0
        assert "malformed=1" in r.stderr
        assert "failed_sources=0" in r.stderr


def test_ingest_partial_source_failure_continues_and_exits_1():
    """A failed source is counted while later valid sources still commit."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        proj = tmp / "proj"
        proj.mkdir()
        cc_projects = tmp / "cc"
        slug_dir = cc_projects / path_to_slug(proj.resolve())
        slug_dir.mkdir(parents=True)
        (slug_dir / "broken.jsonl").mkdir()
        shutil.copy(
            Path(__file__).parent / "fixtures" / "sample.jsonl",
            slug_dir / "good.jsonl",
        )
        env = {**os.environ, "CODESS_CC_PROJECTS": str(cc_projects)}

        r = _run(
            ["ingest", "--dir", str(proj), "--source", "cc", "--force", "--min-size", "0"],
            env=env,
        )

        assert r.returncode == 1
        assert "Processed: 1 session" in r.stdout
        assert "failed_sources=1" in r.stderr
        report = json.loads(
            (proj / ".codess/last-ingest-report.json").read_text(encoding="utf-8")
        )
        assert report["status"] == "completed_with_errors"
        assert report["diagnostics"]["failed_sources"] == 1


def test_multi_project_reports_isolate_status_and_diagnostics():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        failed_project = root / "failed"
        accepted_project = root / "accepted"
        failed_project.mkdir()
        accepted_project.mkdir()
        cc_projects = root / "cc"
        failed_sources = cc_projects / path_to_slug(failed_project.resolve())
        accepted_sources = cc_projects / path_to_slug(accepted_project.resolve())
        failed_sources.mkdir(parents=True)
        accepted_sources.mkdir(parents=True)
        (failed_sources / "broken.jsonl").mkdir()
        shutil.copy(
            Path(__file__).parent / "fixtures" / "sample.jsonl",
            accepted_sources / "good.jsonl",
        )

        result = _run(
            [
                "ingest", "--dir", str(failed_project),
                "--dir", str(accepted_project), "--source", "cc",
                "--force", "--min-size", "0",
            ],
            env={
                **os.environ,
                "CODESS_CC_PROJECTS": str(cc_projects),
                "CODESS_REGISTRY": str(root / "registry"),
            },
        )

        assert result.returncode == 1
        failed_report = json.loads(
            (failed_project / ".codess/last-ingest-report.json").read_text()
        )
        accepted_report = json.loads(
            (accepted_project / ".codess/last-ingest-report.json").read_text()
        )
        assert failed_report["status"] == "completed_with_errors"
        assert failed_report["diagnostics"]["failed_sources"] == 1
        assert accepted_report["status"] == "accepted"
        assert "failed_sources" not in accepted_report["diagnostics"]


def test_ingest_stop_aborts_before_later_sources():
    """--stop aborts at the first failed source instead of committing siblings."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        proj = tmp / "proj"
        proj.mkdir()
        cc_projects = tmp / "cc"
        slug_dir = cc_projects / path_to_slug(proj.resolve())
        slug_dir.mkdir(parents=True)
        (slug_dir / "a-broken.jsonl").mkdir()
        shutil.copy(
            Path(__file__).parent / "fixtures" / "sample.jsonl",
            slug_dir / "z-good.jsonl",
        )
        env = {**os.environ, "CODESS_CC_PROJECTS": str(cc_projects)}

        r = _run(
            [
                "ingest",
                "--dir",
                str(proj),
                "--source",
                "cc",
                "--force",
                "--min-size",
                "0",
                "--stop",
            ],
            env=env,
        )

        assert r.returncode == 1
        assert "Ingested" not in r.stdout
        conn = sqlite3.connect(proj / ".codess" / "sessions_cc.db")
        try:
            assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
        finally:
            conn.close()


def test_ingest_stop_environment_is_fail_fast():
    """CODESS_STOP has the same fail-fast behavior as --stop."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        proj = tmp / "proj"
        proj.mkdir()
        cc_projects = tmp / "cc"
        slug_dir = cc_projects / path_to_slug(proj.resolve())
        slug_dir.mkdir(parents=True)
        (slug_dir / "broken.jsonl").mkdir()
        env = {
            **os.environ,
            "CODESS_CC_PROJECTS": str(cc_projects),
            "CODESS_STOP": "1",
        }

        r = _run(
            ["ingest", "--dir", str(proj), "--source", "cc", "--force", "--min-size", "0"],
            env=env,
        )

        assert r.returncode == 1
        assert "Ingested" not in r.stdout


# Need init_db for test_query_no_mode
from codess.raw_store import RawStore
from codess.snapshot import create_snapshot
from codess.store import connect, init_db, replace_session_events


def test_ingest_validate_uses_real_adapter_without_mutation():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        project = root / "project"
        project.mkdir()
        cc = root / "cc"
        source_dir = cc / path_to_slug(project.resolve())
        source_dir.mkdir(parents=True)
        shutil.copy(Path(__file__).parent / "fixtures/sample.jsonl", source_dir / "s1.jsonl")
        registry = root / "registry"
        env = {**os.environ, "CODESS_CC_PROJECTS": str(cc), "CODESS_REGISTRY": str(registry)}
        result = _run(["ingest", "--validate", "--dir", str(project), "--source", "cc", "--min-size", "0"], env=env)
        assert result.returncode == 0, result.stderr
        report = json.loads(result.stdout.strip())
        assert report["report_format"] == "codess.ingest-preflight/1"
        assert report["progress_format"] == "codess.progress/1"
        assert "project.done" in {
            event["event"] for event in report["progress_events"]
        }
        assert report["progress_events"][-1]["event"] == "ingest.done"
        assert report["events"] > 0
        assert report["session_kinds"] == {
            "Claude": {"main": 1, "subagent": 0}
        }
        assert not (project / ".codess").exists()
        assert not registry.exists()


def test_ingest_validate_enforces_source_limit_without_mutation():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        project = root / "project"
        project.mkdir()
        cc = root / "cc"
        source_dir = cc / path_to_slug(project.resolve())
        source_dir.mkdir(parents=True)
        shutil.copy(Path(__file__).parent / "fixtures/sample.jsonl", source_dir / "s1.jsonl")
        env = {**os.environ, "CODESS_CC_PROJECTS": str(cc), "CODESS_REGISTRY": str(root / "registry")}
        result = _run(["ingest", "--validate", "--stop", "--dir", str(project), "--source", "cc", "--min-size", "0", "--max-source-bytes", "1"], env=env)
        assert result.returncode == 1
        assert "exceeds maximum" in result.stderr
        assert not (project / ".codess").exists()


def test_ingest_validate_reports_size_failure_as_possible_misclassification():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        project = root / "project"
        project.mkdir()
        cc = root / "cc"
        source_dir = cc / path_to_slug(project.resolve())
        source_dir.mkdir(parents=True)
        shutil.copy(Path(__file__).parent / "fixtures/sample.jsonl", source_dir / "s1.jsonl")
        env = {
            **os.environ,
            "CODESS_CC_PROJECTS": str(cc),
            "CODESS_REGISTRY": str(root / "registry"),
        }
        result = _run([
            "ingest", "--validate", "--dir", str(project), "--source", "cc",
            "--min-size", "0", "--max-source-bytes", "1",
        ], env=env)
        assert result.returncode == 1
        report = json.loads(result.stdout.strip())
        assert report["status"] == "rejected"
        assert report["diagnostics"]["reviewable_content_failures"] == 1
        review = report["content_failure_reviews"][0]
        assert review["failure_class"] == "source_size_limit"
        assert "wrong_source_scope_or_container_selected" in review["candidate_causes"]


def test_ingest_validate_enforces_event_limit_during_collection():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        project = root / "project"
        project.mkdir()
        cc = root / "cc"
        source_dir = cc / path_to_slug(project.resolve())
        source_dir.mkdir(parents=True)
        shutil.copy(Path(__file__).parent / "fixtures/sample.jsonl", source_dir / "s1.jsonl")
        env = {**os.environ, "CODESS_CC_PROJECTS": str(cc), "CODESS_REGISTRY": str(root / "registry")}
        result = _run([
            "ingest", "--validate", "--stop", "--dir", str(project),
            "--source", "cc", "--min-size", "0", "--max-events-per-source", "1",
        ], env=env)
        assert result.returncode == 1
        assert "maximum is 1" in result.stderr
        assert not (project / ".codess").exists()


def test_ingest_validate_content_policy_does_not_touch_live_store():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        project = root / "project"
        project.mkdir()
        live_store = project / ".codess/sessions_cc.db"
        init_db(live_store)
        cc = root / "cc"
        source_dir = cc / path_to_slug(project.resolve())
        source_dir.mkdir(parents=True)
        shutil.copy(Path(__file__).parent / "fixtures/sample.jsonl", source_dir / "s1.jsonl")
        env = {**os.environ, "CODESS_CC_PROJECTS": str(cc), "CODESS_REGISTRY": str(root / "registry")}
        before = live_store.stat().st_mtime_ns
        result = _run([
            "ingest", "--validate", "--dir", str(project), "--source", "cc",
            "--min-size", "0", "--content-policy", str(Path("schema/content-policy.example.json").resolve()),
        ], env=env)
        assert result.returncode == 0, result.stderr
        assert live_store.stat().st_mtime_ns == before
        conn = sqlite3.connect(live_store)
        try:
            assert conn.execute("SELECT COUNT(*) FROM processing_runs").fetchone()[0] == 0
        finally:
            conn.close()


def test_routine_ingest_writes_resource_and_evidence_report():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        project = root / "project"
        project.mkdir()
        cc = root / "cc"
        source_dir = cc / path_to_slug(project.resolve())
        source_dir.mkdir(parents=True)
        source = source_dir / "s1.jsonl"
        shutil.copy(Path(__file__).parent / "fixtures/sample.jsonl", source)
        env = {
            **os.environ,
            "CODESS_CC_PROJECTS": str(cc),
            "CODESS_REGISTRY": str(root / "registry"),
        }
        result = _run(
            ["ingest", "--dir", str(project), "--source", "cc", "--min-size", "0"],
            env=env,
        )
        assert result.returncode == 0, result.stderr
        report = json.loads(
            (project / ".codess/last-ingest-report.json").read_text(encoding="utf-8")
        )
        assert report["report_format"] == "codess.ingest-runtime/1"
        assert report["progress_format"] == "codess.progress/1"
        assert report["progress_live"] is True
        assert report["resource_observations"][0]["source_bytes"] == source.stat().st_size
        assert report["resource_observations"][0]["events"] > 0
        assert report["evidence_summary"]["tool_invocations"] >= 0
        assert report["limits"]["max_source_bytes"] > 0
        assert "codess: progress " in result.stderr
        assert [event["event"] for event in report["progress_events"]] == [
            "ingest.start", "project.start", "vendor.start", "source.start",
            "source.done", "vendor.done", "artifact_correlation.start",
            "artifact_correlation.done", "snapshot.start", "snapshot.done",
            "evidence_summary.start", "evidence_summary.done", "project.done",
        ]


def test_unchanged_ingest_reuses_snapshot_evidence_summary():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        project = root / "project"
        project.mkdir()
        cc = root / "cc"
        source_dir = cc / path_to_slug(project.resolve())
        source_dir.mkdir(parents=True)
        shutil.copy(
            Path(__file__).parent / "fixtures/sample.jsonl",
            source_dir / "s1.jsonl",
        )
        command = [
            "ingest", "--dir", str(project), "--source", "cc", "--min-size", "0",
        ]
        env = {
            **os.environ,
            "CODESS_CC_PROJECTS": str(cc),
            "CODESS_REGISTRY": str(root / "registry"),
        }
        first = _run(command, env=env)
        assert first.returncode == 0, first.stderr
        pointer_before = (project / ".codess/current.json").read_bytes()
        first_report = json.loads(
            (project / ".codess/last-ingest-report.json").read_text()
        )

        second = _run(command, env=env)

        assert second.returncode == 0, second.stderr
        assert "evidence_summary.reused" in second.stderr
        assert (project / ".codess/current.json").read_bytes() == pointer_before
        second_report = json.loads(
            (project / ".codess/last-ingest-report.json").read_text()
        )
        assert second_report["snapshot_id"] == first_report["snapshot_id"]
        assert second_report["evidence_summary_reused"] is True
        assert second_report["evidence_summary"] == first_report["evidence_summary"]


def test_no_progress_suppresses_live_lines_but_retains_trace():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        project = root / "project"
        project.mkdir()
        cc = root / "cc"
        source_dir = cc / path_to_slug(project.resolve())
        source_dir.mkdir(parents=True)
        shutil.copy(
            Path(__file__).parent / "fixtures/sample.jsonl",
            source_dir / "s1.jsonl",
        )
        result = _run(
            [
                "ingest", "--dir", str(project), "--source", "cc",
                "--min-size", "0", "--no-progress",
            ],
            env={
                **os.environ,
                "CODESS_CC_PROJECTS": str(cc),
                "CODESS_REGISTRY": str(root / "registry"),
            },
        )

        assert result.returncode == 0
        assert "codess: progress " not in result.stderr
        report = json.loads(
            (project / ".codess/last-ingest-report.json").read_text(
                encoding="utf-8"
            )
        )
        assert report["progress_live"] is False
        assert report["progress_events"][0]["event"] == "ingest.start"
        assert report["progress_events"][-1]["event"] == "project.done"


def test_query_jsonl_sessions_and_stats_are_typed():
    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp)
        store = project / ".codess/sessions_cc.db"
        init_db(store)
        conn = sqlite3.connect(store)
        conn.execute("INSERT INTO sessions(id,source,type,started_at,project_path) VALUES('s1','Claude','Code',12.5,?)", (str(project),))
        conn.commit()
        conn.close()
        sessions = _run(["query", "--dir", str(project), "--sessions", "--output-format", "jsonl"])
        row = json.loads(sessions.stdout)
        assert row["schema"] == "codess.query-row/1"
        assert row["data"]["started_at"] == 12.5
        stats = _run(["query", "--dir", str(project), "--stats", "--output-format", "jsonl"])
        rows = [json.loads(line) for line in stats.stdout.splitlines()]
        assert rows[0]["report"] == "stats.project"
        assert rows[0]["data"]["sessions"] == 1
        assert rows[-1]["report"] == "stats.total"
        assert rows[-1]["data"] == {"events": 0, "projects": 1, "sessions": 1}


def test_query_vendor_filter_stable_session_id_sequence_and_csv():
    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp)
        store = project / ".codess/sessions_cc.db"
        init_db(store)
        conn = sqlite3.connect(store)
        conn.executemany(
            "INSERT INTO sessions(id,global_id,source_system_id,source,type,started_at,project_path) "
            "VALUES(?,?,?,?,?,?,?)",
            [
                ("claude-1", "global-claude", "anthropic.claude-code", "Claude", "Code", 1, str(project)),
                ("cursor-1", "global-cursor", "cursor.composer", "Cursor", "Code", 2, str(project)),
            ],
        )
        conn.executemany(
            "INSERT INTO events(session_id,event_id,sequence_no,event_type,subtype,content,timestamp) "
            "VALUES(?,?,?,?,?,?,?)",
            [
                ("claude-1", "c1", 1, "user_message", "prompt", "claude", 1),
                ("cursor-1", "u2", 2, "user_message", "prompt", "SECOND", 1),
                ("cursor-1", "u1", 1, "user_message", "prompt", "FIRST", 2),
            ],
        )
        conn.commit()
        conn.close()
        registry = project / "registry"
        env = {**os.environ, "CODESS_REGISTRY": str(registry)}

        sessions = _run([
            "query", "--dir", str(project), "--source", "cursor",
            "--sessions", "--output-format", "jsonl",
        ], env=env)
        rows = [json.loads(line) for line in sessions.stdout.splitlines()]
        assert sessions.returncode == 0
        assert [row["data"]["session_id"] for row in rows] == ["cursor-1"]

        stats = _run([
            "query", "--dir", str(project), "--source", "cursor",
            "--stats", "--output-format", "csv",
        ], env=env)
        csv_rows = list(csv.DictReader(stats.stdout.splitlines()))
        assert stats.returncode == 0
        assert csv_rows[-1]["report"] == "stats.total"
        assert csv_rows[-1]["sessions"] == "1"
        assert csv_rows[-1]["events"] == "2"
        assert not (registry / "ingested_projects.json").exists()

        detail = _run([
            "query", "--dir", str(project), "--source", "cursor",
            "--session-id", "global-cursor", "--show", "prompt",
        ], env=env)
        assert detail.returncode == 0
        assert detail.stdout.index("FIRST") < detail.stdout.index("SECOND")


def test_query_rejects_invalid_source_and_ambiguous_modes():
    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp)
        init_db(project / ".codess/sessions_cc.db")
        invalid = _run([
            "query", "--dir", str(project), "--source", "windsurf", "--sessions",
        ])
        assert invalid.returncode == 1
        assert "invalid --source" in invalid.stderr
        ambiguous = _run([
            "query", "--dir", str(project), "--sessions", "--stats",
        ])
        assert ambiguous.returncode == 1
        assert "exactly one query report mode" in ambiguous.stderr


def test_query_ambiguous_vendor_session_id_requests_global_id():
    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp)
        for index, name in enumerate(("sessions_cc.db", "sessions_cursor.db")):
            store = project / ".codess" / name
            init_db(store)
            conn = sqlite3.connect(store)
            conn.execute(
                "INSERT INTO sessions(id,global_id,source_system_id,source,type) "
                "VALUES('same',?,?,?, 'Code')",
                (
                    f"global-{index}",
                    "anthropic.claude-code" if index == 0 else "cursor.composer",
                    "Claude" if index == 0 else "Cursor",
                ),
            )
            conn.commit()
            conn.close()
        result = _run([
            "query", "--dir", str(project), "--session-id", "same",
        ])
        assert result.returncode == 1
        assert "ambiguous" in result.stderr
        assert "global session ID" in result.stderr
        assert "Traceback" not in result.stderr


def test_query_pipeline_close_has_no_broken_pipe_traceback():
    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp)
        store = project / ".codess/sessions_cc.db"
        init_db(store)
        conn = sqlite3.connect(store)
        conn.execute(
            "INSERT INTO sessions(id,global_id,source_system_id,source,type,started_at) "
            "VALUES('s1','global-s1','anthropic.claude-code','Claude','Code',1)"
        )
        conn.executemany(
            "INSERT INTO events(session_id,event_id,sequence_no,event_type,subtype,content,timestamp) "
            "VALUES('s1',?,?, 'assistant_message','response',?,?)",
            [(f"e{i}", i, "x" * 2000, i) for i in range(1, 300)],
        )
        conn.commit()
        conn.close()
        proc = subprocess.Popen(
            [
                sys.executable, "-m", "main", "query", "--dir", str(project),
                "--session-id", "global-s1", "--show", "pr",
            ],
            cwd=PROJECT_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        assert proc.stdout is not None and proc.stderr is not None
        proc.stdout.readline()
        proc.stdout.close()
        stderr = proc.stderr.read()
        proc.wait(timeout=10)
        assert "BrokenPipeError" not in stderr
        assert "Traceback" not in stderr
