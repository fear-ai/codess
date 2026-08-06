"""Path-string curation labeling (codess.path_label)."""

from codess.path_label import classify_project_path


def test_path_defaults_separate_active_reference_and_dormant(tmp_path):
    work = tmp_path / "Work"
    assert classify_project_path(work / "Code" / "ours", work_root=work) == {
        "topic": "Code", "ownership": "own", "activity_state": "active", "selection_state": "candidate",
    }
    assert classify_project_path(work / "Github" / "old", work_root=work)["selection_state"] == "needs_review"
    assert classify_project_path(work / "Spank" / "sOSS" / "ref", work_root=work)["ownership"] == "reference"
    assert classify_project_path(work / "Code" / "CodingTools" / "codex" / "codex-rs", work_root=work)["ownership"] == "reference"
    assert classify_project_path(work / "WP" / "site", work_root=work)["selection_state"] == "deferred"
