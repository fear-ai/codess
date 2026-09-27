"""Path-string curation labeling (codess.path_label)."""

import json
import os
import subprocess
import sys

import pytest

import codess.path_label as path_label
from codess.path_label import classify_project_path

ACTIVE = {"ownership": "own", "activity_state": "active", "selection_state": "candidate"}
REFERENCE_TOPIC = {"ownership": "reference", "activity_state": "dormant", "selection_state": "needs_review"}
REFERENCE_SEGMENT = {"ownership": "reference", "activity_state": "dormant", "selection_state": "deferred"}
DORMANT_TOPIC = {"ownership": "own", "activity_state": "dormant", "selection_state": "deferred"}


def _curation(path, work):
    label = classify_project_path(path, work_root=work)
    return label.pop("topic"), label


@pytest.fixture
def configured(monkeypatch):
    """Configure the three name sets explicitly, as an operator would."""
    monkeypatch.setattr(path_label, "REFERENCE_TOPICS", frozenset({"shelf"}))
    monkeypatch.setattr(path_label, "DORMANT_TOPICS", frozenset({"archive"}))
    monkeypatch.setattr(path_label, "REFERENCE_SEGMENTS", frozenset({"vendored"}))


def test_nothing_is_reference_or_dormant_until_configured(tmp_path):
    """Topic names describe one machine's grouping, so the shipped sets are empty."""
    work = tmp_path / "root"
    for first in ("shelf", "archive", "vendored", "anything"):
        topic, label = _curation(work / first / "project", work)
        assert (topic, label) == (first, ACTIVE)


def test_the_sets_are_read_from_the_environment_and_ship_empty():
    code = (
        "import json, codess.path_label as p;"
        "print(json.dumps([sorted(p.REFERENCE_TOPICS), sorted(p.DORMANT_TOPICS), sorted(p.REFERENCE_SEGMENTS)]))"
    )
    names = ("CODESS_REFERENCE_TOPICS", "CODESS_DORMANT_TOPICS", "CODESS_REFERENCE_SEGMENTS")
    unset = {key: value for key, value in os.environ.items() if key not in names}
    shipped = subprocess.run([sys.executable, "-c", code], env=unset, capture_output=True, text=True, check=True)
    assert json.loads(shipped.stdout) == [[], [], []]

    supplied = dict(unset, CODESS_REFERENCE_TOPICS="shelf, forks", CODESS_DORMANT_TOPICS="archive",
                    CODESS_REFERENCE_SEGMENTS="vendored")
    loaded = subprocess.run([sys.executable, "-c", code], env=supplied, capture_output=True, text=True, check=True)
    assert json.loads(loaded.stdout) == [["forks", "shelf"], ["archive"], ["vendored"]]


def test_a_reference_topic_matches_only_the_first_segment(tmp_path, configured):
    work = tmp_path / "root"
    assert _curation(work / "shelf" / "project", work) == ("shelf", REFERENCE_TOPIC)
    assert _curation(work / "group" / "shelf" / "project", work) == ("group", ACTIVE)


def test_a_dormant_topic_matches_only_the_first_segment(tmp_path, configured):
    work = tmp_path / "root"
    assert _curation(work / "archive" / "project", work) == ("archive", DORMANT_TOPIC)
    assert _curation(work / "group" / "archive" / "project", work) == ("group", ACTIVE)


def test_a_reference_segment_matches_at_any_depth(tmp_path, configured):
    work = tmp_path / "root"
    assert _curation(work / "vendored" / "project", work) == ("vendored", REFERENCE_SEGMENT)
    assert _curation(work / "group" / "vendored" / "project", work) == ("group", REFERENCE_SEGMENT)


def test_reference_outranks_dormant(tmp_path, configured, monkeypatch):
    work = tmp_path / "root"
    assert _curation(work / "archive" / "vendored" / "project", work) == ("archive", REFERENCE_SEGMENT)
    monkeypatch.setattr(path_label, "DORMANT_TOPICS", frozenset({"shelf"}))
    assert _curation(work / "shelf" / "project", work) == ("shelf", REFERENCE_TOPIC)


def test_matching_is_by_whole_segment_and_case_sensitive(tmp_path, configured):
    work = tmp_path / "root"
    assert _curation(work / "Shelf" / "project", work) == ("Shelf", ACTIVE)
    assert _curation(work / "shelves" / "project", work) == ("shelves", ACTIVE)


def test_the_topic_is_taken_below_the_root_the_caller_names(tmp_path, monkeypatch, configured):
    """An explicit root is honoured even inside the default one.

    HOME points at the temporary tree so that a classifier anchored to a
    home-relative default root would take `inner` as the topic.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(path_label, "DEFAULT_WORK", tmp_path / "Work")
    inner = tmp_path / "Work" / "inner"
    assert _curation(inner / "shelf" / "project", inner) == ("shelf", REFERENCE_TOPIC)


def test_the_default_root_comes_from_configuration(tmp_path, monkeypatch):
    work = tmp_path / "configured"
    monkeypatch.setattr(path_label, "DEFAULT_WORK", work)
    assert classify_project_path(work / "group" / "project")["topic"] == "group"


def test_a_path_outside_the_root_is_unknown(tmp_path, monkeypatch):
    monkeypatch.setattr(path_label, "REFERENCE_TOPICS", frozenset({"unknown"}))
    label = classify_project_path(tmp_path / "elsewhere" / "project", work_root=tmp_path / "root")
    assert label == {"topic": "unknown", "ownership": "unknown", "activity_state": "active", "selection_state": "candidate"}
