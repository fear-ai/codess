"""Catalog candidates preserve observations and require human curation."""

from pathlib import Path

import pytest

from codess.catalog import (
    CatalogError,
    candidate_key_for_path,
    classify_project_path,
    load_candidate_csv,
)


def test_path_defaults_separate_active_reference_and_dormant(tmp_path):
    work = tmp_path / "Work"
    assert classify_project_path(work / "Code" / "ours", work_root=work) == {
        "topic": "Code", "ownership": "own", "activity_state": "active", "selection_state": "candidate",
    }
    assert classify_project_path(work / "Github" / "old", work_root=work)["selection_state"] == "needs_review"
    assert classify_project_path(work / "Spank" / "sOSS" / "ref", work_root=work)["ownership"] == "reference"
    assert classify_project_path(work / "Code" / "CodingTools" / "codex" / "codex-rs", work_root=work)["ownership"] == "reference"
    assert classify_project_path(work / "WP" / "site", work_root=work)["selection_state"] == "deferred"


def test_candidate_csv_does_not_assume_remote_availability(tmp_path):
    work = tmp_path / "Work"
    local = work / "Code" / "ours"
    local.mkdir(parents=True)
    csv_path = tmp_path / "active.csv"
    csv_path.write_text(
        "title,directory_path,repo_url,last_commit_date,doc_and_code_file_count,notes\n"
        f"Ours,{local},https://github.com/gone/repo,2026-07-01,12,reported fact\n",
        encoding="utf-8",
    )
    catalog = load_candidate_csv(csv_path, work_root=work)
    item = catalog["projects"][0]
    assert item["curation"]["selection_state"] == "candidate"
    assert item["observations"]["remote"]["status"] == "unchecked"
    assert item["observations"]["local_availability"] == "present"
    assert item["review"]["decision"] is None
    assert item["candidate_key"] == candidate_key_for_path(local)
    assert item["candidate_key"].startswith("candidate:path:")
    assert "project_id" not in item


def test_candidate_csv_rejects_duplicate_paths(tmp_path):
    csv_path = tmp_path / "bad.csv"
    csv_path.write_text(
        "title,directory_path,repo_url\nA,/tmp/a,x\nAgain,/tmp/a,y\n",
        encoding="utf-8",
    )
    with pytest.raises(CatalogError, match="repeats"):
        load_candidate_csv(csv_path)
