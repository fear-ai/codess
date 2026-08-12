"""Candidate Project review: CSV seeding and decision recording (codess.review_project)."""

import pytest

from codess.path_label import local_path_key
from codess.review_project import CandidateReviewError, load_candidate_csv


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
    assert item["path_key"] == local_path_key(local)
    # The prefix names a machine-local location rather than a candidate,
    # which is what the value has always been (W20).
    assert item["path_key"].startswith("local:path-key:")
    assert "project_id" not in item


def test_candidate_csv_rejects_duplicate_paths(tmp_path):
    csv_path = tmp_path / "bad.csv"
    csv_path.write_text(
        "title,directory_path,repo_url\nA,/tmp/a,x\nAgain,/tmp/a,y\n",
        encoding="utf-8",
    )
    with pytest.raises(CandidateReviewError, match="repeats"):
        load_candidate_csv(csv_path)
