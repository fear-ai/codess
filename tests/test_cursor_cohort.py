"""Cursor cohort change detection and metadata-only cache behavior."""

from __future__ import annotations

import sqlite3

from codess.cursor_cohort import cohort_needed, prepare_cursor_cohort
from codess.raw_store import RawStore
from codess.store import ingest_state_marker, save_ingest_state


def _cursor_db(path) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE values_for_test(value TEXT)")
        conn.execute("INSERT INTO values_for_test VALUES ('captured')")


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
    second, second_marker, status = prepare_cursor_cohort(
        source,
        raw_store=raw_store,
        cache_path=cache,
        materialized_path=second_target,
        source_system_id="cursor.composer",
        storage_format="cursor-sqlite",
        marker=marker,
        force=False,
    )
    assert status == "reused"
    assert second_marker == marker
    assert second["object_id"] == first["object_id"]
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
