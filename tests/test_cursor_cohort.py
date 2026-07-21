"""Cursor cohort change detection and metadata-only cache behavior."""

from __future__ import annotations

import sqlite3

from codess.cursor_cohort import (
    cohort_needed,
    load_selection_marker_cache,
    prepare_cursor_cohort,
    save_selection_marker_cache,
)
from codess.raw_store import RawStore
from codess.store import ingest_state_marker, save_ingest_state


def _cursor_db(path) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE values_for_test(value TEXT)")
        conn.execute("INSERT INTO values_for_test VALUES ('captured')")


def test_selection_marker_cache_requires_exact_container_and_scope(tmp_path):
    source = tmp_path / "state.vscdb"
    _cursor_db(source)
    cache = tmp_path / "selection-cache.json"
    container = {"method": "stat", "files": [{"role": "main", "size": 1}]}
    selections = {"/project": {"workspace"}}
    markers = {"/project": {"source_revision": "marker"}}

    save_selection_marker_cache(
        cache, source=source, container_marker=container,
        selections=selections, project_markers=markers,
    )

    assert load_selection_marker_cache(
        cache, source=source, container_marker=container,
        selections=selections,
    ) == markers
    assert load_selection_marker_cache(
        cache, source=source,
        container_marker={"method": "stat", "files": []},
        selections=selections,
    ) is None
    assert load_selection_marker_cache(
        cache, source=source, container_marker=container,
        selections={"/other": {"workspace"}},
    ) is None


def test_cursor_cohort_cache_restores_without_recapturing(tmp_path, monkeypatch):
    source = tmp_path / "state.vscdb"
    _cursor_db(source)
    raw_store = RawStore(tmp_path / "raw")
    cache = tmp_path / "cache.json"
    marker = ingest_state_marker(source)

    first_target = tmp_path / "first.db"
    first, saved_marker, status = prepare_cursor_cohort(
        source,
        raw_store=raw_store,
        cache_path=cache,
        materialized_path=first_target,
        source_system_id="cursor.composer",
        storage_format="cursor-sqlite",
        marker=marker,
        force=False,
    )
    assert status == "captured"
    assert saved_marker == marker
    assert cache.is_file()
    with sqlite3.connect(first_target.resolve().as_uri() + "?mode=ro", uri=True) as conn:
        assert conn.execute("SELECT value FROM values_for_test").fetchone()[0] == "captured"

    def reject_recapture(*_args, **_kwargs):
        raise AssertionError("an unchanged cohort must reuse its raw object")

    monkeypatch.setattr(raw_store, "observe", reject_recapture)
    second_target = tmp_path / "second.db"
    progress = []
    second, second_marker, status = prepare_cursor_cohort(
        source,
        raw_store=raw_store,
        cache_path=cache,
        materialized_path=second_target,
        source_system_id="cursor.composer",
        storage_format="cursor-sqlite",
        marker=marker,
        force=False,
        progress=lambda event, **fields: progress.append((event, fields)),
    )
    assert status == "reused"
    assert second_marker == marker
    assert second["object_id"] == first["object_id"]
    assert [event for event, _fields in progress] == [
        "cursor.cohort.restore.start", "cursor.cohort.restore.done",
    ]
    assert progress[-1][1]["materialized_bytes"] == second["uncompressed_size"]
    assert progress[-1][1]["phase_seconds"] >= 0
    with sqlite3.connect(second_target.resolve().as_uri() + "?mode=ro", uri=True) as conn:
        assert conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"


def test_cohort_needed_checks_every_selected_project_state(tmp_path):
    source = tmp_path / "state.vscdb"
    _cursor_db(source)
    marker = ingest_state_marker(source)
    states = [tmp_path / "first.json", tmp_path / "second.json"]
    key = f"cursor:global:{source.resolve()}"

    assert cohort_needed(source, states, marker, force=False)
    for state_path in states:
        save_ingest_state(state_path, {key: marker})
    assert not cohort_needed(source, states, marker, force=False)
    assert cohort_needed(source, states, marker, force=True)


def test_cursor_cohort_source_change_creates_a_new_cached_revision(tmp_path):
    source = tmp_path / "state.vscdb"
    _cursor_db(source)
    raw_store = RawStore(tmp_path / "raw")
    cache = tmp_path / "cache.json"
    first_marker = ingest_state_marker(source)
    first, _, _ = prepare_cursor_cohort(
        source,
        raw_store=raw_store,
        cache_path=cache,
        materialized_path=tmp_path / "first.db",
        source_system_id="cursor.composer",
        storage_format="cursor-sqlite",
        marker=first_marker,
        force=False,
    )

    with sqlite3.connect(source) as conn:
        conn.execute("INSERT INTO values_for_test VALUES ('changed')")
    second_marker = ingest_state_marker(source)
    assert second_marker != first_marker
    second, _, status = prepare_cursor_cohort(
        source,
        raw_store=raw_store,
        cache_path=cache,
        materialized_path=tmp_path / "second.db",
        source_system_id="cursor.composer",
        storage_format="cursor-sqlite",
        marker=second_marker,
        force=False,
    )
    assert status == "captured"
    assert second["object_id"] != first["object_id"]


def test_capture_records_stable_when_source_quiescent(tmp_path):
    """A15/D16: a capture over an unchanging source is marked stable."""
    source = tmp_path / "state.vscdb"
    _cursor_db(source)
    raw_store = RawStore(tmp_path / "raw")
    marker = ingest_state_marker(source)
    record, _, status = prepare_cursor_cohort(
        source,
        raw_store=raw_store,
        cache_path=tmp_path / "cache.json",
        materialized_path=tmp_path / "cap.db",
        source_system_id="cursor.composer",
        storage_format="cursor-sqlite",
        marker=marker,
        force=False,
    )
    assert status == "captured"
    assert record["change_detection"]["capture_stability"] == "stable_during_capture"
    assert (
        record["change_detection"]["post_capture_revision"]
        == marker["source_revision"]
    )


def test_capture_records_source_advanced_when_revision_moves(tmp_path):
    """A15/D16: if the source revision moves across the backup window, the
    capture is annotated `source_advanced` instead of being treated as if the
    source were quiescent. We simulate the window by advancing the source after
    computing the pre-capture marker but before the capture reads it."""
    source = tmp_path / "state.vscdb"
    _cursor_db(source)
    raw_store = RawStore(tmp_path / "raw")

    stale_marker = ingest_state_marker(source)
    # The source changes between marker read and capture — the exact hazard the
    # stability loop exists to detect.
    with sqlite3.connect(source) as conn:
        conn.execute("INSERT INTO values_for_test VALUES ('mid-capture write')")

    progress_events = []
    record, _, status = prepare_cursor_cohort(
        source,
        raw_store=raw_store,
        cache_path=tmp_path / "cache.json",
        materialized_path=tmp_path / "cap.db",
        source_system_id="cursor.composer",
        storage_format="cursor-sqlite",
        marker=stale_marker,
        force=False,
        progress=lambda event, **fields: progress_events.append((event, fields)),
    )
    assert status == "captured"
    cd = record["change_detection"]
    assert cd["capture_stability"] == "source_advanced"
    assert cd["post_capture_revision"] != stale_marker["source_revision"]
    assert any(e == "cursor.cohort.source_advanced" for e, _ in progress_events)
