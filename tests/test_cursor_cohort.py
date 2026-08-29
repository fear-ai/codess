"""Cursor cohort change detection and metadata-only cache behavior."""

from __future__ import annotations

import json
import sqlite3

from codess.cursor_cohort import (
    cohort_needed,
    combine_selection_markers,
    load_selection_marker_cache,
    prepare_cursor_cohort,
    resolve_selection_markers,
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

    legacy_cache = json.loads(cache.read_text(encoding="utf-8"))
    legacy_cache["cache_format"] = "codess.cursor-selection-cache/1"
    cache.write_text(json.dumps(legacy_cache), encoding="utf-8")
    assert load_selection_marker_cache(
        cache, source=source, container_marker=container,
        selections=selections,
    ) is None


def test_combined_selection_marker_states_its_derivation():
    marker = combine_selection_markers({
        "/one": {"source_revision": "digest-fingerprint:one"},
        "/two": {"source_revision": "digest-fingerprint:two"},
    })
    assert marker["source_revision"].startswith(
        "cursor-cohort-selection-digest-fingerprint:"
    )
    assert marker["fingerprint_method"].endswith(
        "selection-digest-fingerprint"
    )


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
        working_path=first_target,
        source_system_key="cursor.composer",
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
        working_path=second_target,
        source_system_key="cursor.composer",
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
    assert progress[-1][1]["working_bytes"] == second["uncompressed_size"]
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
        working_path=tmp_path / "first.db",
        source_system_key="cursor.composer",
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
        working_path=tmp_path / "second.db",
        source_system_key="cursor.composer",
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
        working_path=tmp_path / "cap.db",
        source_system_key="cursor.composer",
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
        working_path=tmp_path / "cap.db",
        source_system_key="cursor.composer",
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


class TestResolveSelectionMarkers:
    """The cache decision, now testable without a live Cursor store.

    It ran inside a 247-line ingest phase, so its three outcomes could only be
    exercised by running an ingest against a real Cursor database. The
    unstable branch in particular could not be reached deliberately at all.
    """

    def _selections(self):
        return {"/p": ["ws-1"]}

    def _markers(self, *_args, **_kwargs):
        return {"/p": {"source_mtime": 10, "source_size": 20}}

    def test_a_stable_read_is_cached_and_reported_as_scanned(self, tmp_path):
        cache = tmp_path / "selection.json"
        source = tmp_path / "state.vscdb"
        source.write_bytes(b"x")
        resolved = resolve_selection_markers(
            cache, source=source, selections=self._selections(),
            supplemental_headers=None,
            observe_containers=lambda: {"main": 1},
            read_markers=self._markers,
        )
        assert resolved.status == "scanned"
        assert resolved.per_project == self._markers()
        assert cache.exists(), "a stable read must be cached"

    def test_a_second_call_reuses_the_cache(self, tmp_path):
        cache = tmp_path / "selection.json"
        source = tmp_path / "state.vscdb"
        source.write_bytes(b"x")
        common = {
            "source": source,
            "selections": self._selections(),
            "supplemental_headers": None,
            "observe_containers": lambda: {"main": 1},
        }
        resolve_selection_markers(cache, read_markers=self._markers, **common)

        def refuse(*_args, **_kwargs):
            raise AssertionError("a reused marker set must not read the store")

        resolved = resolve_selection_markers(cache, read_markers=refuse, **common)
        assert resolved.status == "reused"

    def test_force_bypasses_the_cache(self, tmp_path):
        cache = tmp_path / "selection.json"
        source = tmp_path / "state.vscdb"
        source.write_bytes(b"x")
        common = {
            "source": source,
            "selections": self._selections(),
            "supplemental_headers": None,
            "observe_containers": lambda: {"main": 1},
            "read_markers": self._markers,
        }
        resolve_selection_markers(cache, **common)
        resolved = resolve_selection_markers(cache, force=True, **common)
        assert resolved.status == "scanned"

    def test_a_write_landing_across_the_read_is_not_cached(self, tmp_path):
        """The correctness case the container bracket exists for.

        Cursor writes to its own store while Codess reads. Caching a
        fingerprint taken across a write would describe a state not on disk,
        and a later run would skip a Project whose evidence had changed.
        """
        cache = tmp_path / "selection.json"
        source = tmp_path / "state.vscdb"
        source.write_bytes(b"x")
        observations = iter(range(100))

        resolved = resolve_selection_markers(
            cache, source=source, selections=self._selections(),
            supplemental_headers=None,
            # Never twice the same: every read looks like a concurrent write.
            observe_containers=lambda: {"main": next(observations)},
            read_markers=self._markers,
        )
        assert resolved.status == "scanned-unstable"
        assert not cache.exists(), "an unstable read must not be cached"
        assert resolved.per_project == self._markers(), (
            "the markers are still used for this run; only caching is refused"
        )

    def test_the_combined_marker_is_derived_from_the_per_project_set(self, tmp_path):
        cache = tmp_path / "selection.json"
        source = tmp_path / "state.vscdb"
        source.write_bytes(b"x")
        resolved = resolve_selection_markers(
            cache, source=source, selections=self._selections(),
            supplemental_headers=None,
            observe_containers=lambda: {"main": 1},
            read_markers=self._markers,
        )
        assert resolved.combined == combine_selection_markers(resolved.per_project)
        assert resolved.combined["project_count"] == 1
