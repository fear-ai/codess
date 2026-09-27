"""A `tools/` script's default locations come from `config`, not from one machine's tree.

Each tool runs in a subprocess with no location flags, under the isolated
`CODESS_*` locations conftest sets, and the test asserts the tool read the
configured location: a default spelled as a home-directory literal reads the
developer's data here instead, or fails on a machine laid out differently.
"""

from __future__ import annotations

import csv
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from cursor_fixtures import build_cursor_db

TOOLS = Path(__file__).resolve().parent.parent / "tools"


def _run(tool: str, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(TOOLS / f"{tool}.py"), *args],
        env={**os.environ, **env}, capture_output=True, text=True, check=False,
    )


def _session(root: Path, name: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    record = {"type": "session_meta", "payload": {"id": name, "cli_version": "1.0.0"}}
    (root / f"{name}.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")


def test_codex_parentage_reads_the_configured_roots(tmp_path):
    active, archive = tmp_path / "active", tmp_path / "archive"
    _session(active, "a1")
    _session(archive, "b1")
    output = tmp_path / "report.json"
    result = _run(
        "audit_codex_parentage", "--output", str(output),
        CODESS_CODEX_SESSIONS=str(active), CODESS_CODEX_ARCHIVED_SESSIONS=str(archive),
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(output.read_text())["root_counts"] == {"active": 1, "archive": 1}


def test_codex_parentage_reads_no_archive_where_none_is_configured(tmp_path):
    active = tmp_path / "active"
    _session(active, "a1")
    output = tmp_path / "report.json"
    env = {key: value for key, value in os.environ.items() if key != "CODESS_CODEX_ARCHIVED_SESSIONS"}
    env["CODESS_CODEX_SESSIONS"] = str(active)
    result = subprocess.run(
        [sys.executable, str(TOOLS / "audit_codex_parentage.py"), "--output", str(output)],
        env=env, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(output.read_text())["root_counts"] == {"active": 1}


@pytest.fixture
def cursor_global():
    """One bubble in the global database under the configured `CODESS_CURSOR_DATA`."""
    db = Path(os.environ["CODESS_CURSOR_DATA"]) / "globalStorage" / "state.vscdb"
    db.parent.mkdir(parents=True)
    bubble = json.dumps({"type": 1, "text": "hello", "createdAt": "2026-07-10T00:00:01Z"})
    return build_cursor_db(db, bubbles=[("c1", "b1", bubble)], headers=[])


def test_cursor_feature_audit_reads_the_configured_database(cursor_global):
    result = _run("audit_cursor_features")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["bubble_records"] == 1


def test_evidence_inventory_prints_the_report_without_an_output(cursor_global):
    before = sorted(TOOLS.parent.joinpath("catalog").glob("*"))
    result = _run("gather_evidence")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["inventory_format"] == "codess.evidence-inventory/1"
    assert sorted(TOOLS.parent.joinpath("catalog").glob("*")) == before


def test_evidence_inventory_writes_the_named_output(tmp_path, cursor_global):
    output = tmp_path / "inventory.json"
    result = _run("gather_evidence", "--output", str(output))
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["output"] == str(output)
    assert json.loads(output.read_text())["inventory_format"] == "codess.evidence-inventory/1"


def test_review_catalog_anchors_topics_at_the_configured_work_root(tmp_path):
    work = tmp_path / "work"
    project = work / "group" / "project"
    project.mkdir(parents=True)
    candidates = tmp_path / "candidates.csv"
    with candidates.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["title", "directory_path", "repo_url"])
        writer.writeheader()
        writer.writerow({"title": "project", "directory_path": str(project), "repo_url": ""})
    output = tmp_path / "catalog.json"
    result = _run("build_review_catalog", str(candidates), str(output), CODESS_WORK_ROOT=str(work))
    assert result.returncode == 0, result.stderr
    [entry] = json.loads(output.read_text())["projects"]
    assert entry["curation"]["topic"] == "group"


@pytest.fixture
def demo_metrics():
    spec = importlib.util.spec_from_file_location("demo_model_metrics", TOOLS / "demo_model_metrics.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_demo_metrics_zone_follows_tz(demo_metrics, monkeypatch):
    monkeypatch.setenv("TZ", "Etc/GMT-3")
    assert demo_metrics.local_zone_name() == "Etc/GMT-3"


def test_demo_metrics_names_the_zone_from_the_localtime_link(demo_metrics, monkeypatch):
    monkeypatch.delenv("TZ", raising=False)
    monkeypatch.setattr(demo_metrics.os.path, "realpath", lambda _: "/usr/share/zoneinfo/Europe/Oslo")
    assert demo_metrics.local_zone_name() == "Europe/Oslo"


def test_demo_metrics_reads_a_naive_boundary_in_the_named_zone(demo_metrics):
    # Etc/GMT-3 is UTC+3, so local midnight is 21:00 UTC the previous day.
    boundary = demo_metrics._parse_boundary("2026-01-02T00:00:00", "Etc/GMT-3")
    assert boundary == demo_metrics.datetime.fromisoformat("2026-01-01T21:00:00+00:00").timestamp() * 1000


def test_demo_metrics_falls_back_to_process_local_time(demo_metrics):
    naive = "2026-01-02T00:00:00"
    expected = demo_metrics.datetime.fromisoformat(naive).astimezone().timestamp() * 1000
    assert demo_metrics._parse_boundary(naive, None) == expected
