"""Path-string curation labeling (codess.path_label)."""

from codess.path_label import classify_project_path


def test_path_defaults_separate_active_reference_and_dormant(tmp_path):
    work = tmp_path / "Work"
    assert classify_project_path(work / "Code" / "ours", work_root=work) == {
        "topic": "Code", "ownership": "own", "activity_state": "active", "selection_state": "candidate",
    }
    assert classify_project_path(work / "Github" / "old", work_root=work)["selection_state"] == "needs_review"
    assert classify_project_path(work / "WP" / "site", work_root=work)["selection_state"] == "deferred"


def test_reference_segments_are_configured_not_assumed(tmp_path, monkeypatch):
    """A vendored-code directory is named differently on every machine.

    Shipping one developer's names would label unrelated directories as
    reference work, so the set is empty until an operator supplies it.
    """
    import codess.path_label as path_label

    work = tmp_path / "Work"
    plain = classify_project_path(work / "Group" / "vendored" / "ref", work_root=work)
    assert plain["ownership"] == "own"

    monkeypatch.setattr(path_label, "REFERENCE_SEGMENTS", frozenset({"vendored"}))
    labelled = classify_project_path(work / "Group" / "vendored" / "ref", work_root=work)
    assert labelled["ownership"] == "reference"
    assert labelled["selection_state"] == "deferred"
