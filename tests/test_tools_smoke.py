"""Every `tools/` script holding store SQL runs against a real store.

SQL in a string is opaque to ruff and mypy, and a column name exists only in
the DDL, so a rename reaches a tool only if something executes it. Nothing did:
`decode_audit.py` queried `mapping_diagnostics.level` for a whole format
version after that column became `granularity`, and the failure was invisible
because the audit runs when a developer types it. These tests execute each
SQL-bearing tool over an ingested store so a rename fails here instead.

They assert the run succeeds and produces its report, not what the report says
-- the numbers depend on the fixture and would make this a change-detector.
What is being checked is that every statement still parses against the current
schema.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from codess.project import path_to_slug

REPO = Path(__file__).resolve().parent.parent

# Every tool that issues SQL against a Project store. Derived by reading the
# scripts rather than by pattern, because a query built from a constant would
# not match a grep for `SELECT`.
SQL_BEARING_TOOLS = ("decode_audit", "field_coverage", "value_survey")


@pytest.fixture
def ingested_project(durable_tmp_path):
    """One Project ingested from the Claude fixture, with its registry."""
    tmp = durable_tmp_path
    project_path = tmp / "toolproj"
    project_path.mkdir()
    (project_path / "main.py").write_text("print('hi')")

    projects_dir = tmp / "cc_projects"
    session_dir = projects_dir / path_to_slug(project_path.resolve())
    session_dir.mkdir(parents=True)
    shutil.copy(
        Path(__file__).parent / "fixtures" / "sample.jsonl",
        session_dir / "test-session.jsonl",
    )

    registry = tmp / "_registry"
    registry.mkdir()
    env = os.environ.copy()
    env["CODESS_STORE_ROOT"] = str(registry)
    env["CODESS_CC_PROJECTS"] = str(projects_dir)

    result = subprocess.run(
        [
            sys.executable, "-m", "main", "ingest", "--dir", str(project_path),
            "--force", "--min-size", "0",
        ],
        cwd=str(REPO), env=env, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, f"ingest failed: {result.stderr}"
    return project_path, env


@pytest.mark.parametrize("tool", SQL_BEARING_TOOLS)
def test_sql_bearing_tool_runs(tool, ingested_project):
    """The tool's statements parse against the schema this version writes."""
    project_path, env = ingested_project
    result = subprocess.run(
        [sys.executable, f"tools/{tool}.py", "--dir", str(project_path)],
        cwd=str(REPO), env=env, capture_output=True, text=True, check=False,
    )
    # A tool may exit nonzero to report a finding; an unhandled exception is
    # the failure this guards, and it names the missing column in the traceback.
    assert "Traceback" not in result.stderr, (
        f"tools/{tool}.py raised against a current store:\n{result.stderr}"
    )


def test_decode_audit_report_sections(ingested_project):
    """The audit produces its structured report, not merely a zero exit.

    A tool that fails to read a store can still exit zero with empty counts, so
    the check is that the report names the store and carries the sections a
    reader acts on.
    """
    project_path, env = ingested_project
    out = project_path / "audit.json"
    result = subprocess.run(
        [
            sys.executable, "tools/decode_audit.py",
            "--dir", str(project_path), "--out", str(out),
        ],
        cwd=str(REPO), env=env, capture_output=True, text=True, check=False,
    )
    assert "Traceback" not in result.stderr, result.stderr
    report = json.loads(out.read_text(encoding="utf-8"))
    stores = report["projects"][0]["stores"]
    claude = stores["Claude"]
    assert claude["counts"]["events"] > 0, "the fixture Session produced no Events"
    # `diagnostics` is the section that carried the renamed column. An empty
    # dict is a valid answer; a missing key means the query never ran.
    for section in ("counts", "vocabularies", "inconsistencies", "linkage"):
        assert section in claude, f"decode audit omitted {section}"
