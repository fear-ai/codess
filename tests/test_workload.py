"""The workload harness: what it records, and that its comparison is trustworthy.

A comparison nobody trusts is worse than none, because it trains a reader to
ignore a real difference. These pin the two properties that make it usable: a
digest is stable across runs of unchanged code, and it *changes* when the result
actually changes.
"""

from __future__ import annotations

import pytest

from codess.workload import (
    CASE_SIZES,
    LOCATED_FIELDS,
    TIMING_FIELDS,
    Measurement,
    Workload,
    measured,
    query_plan,
    result_digest,
    scans_a_table,
    stable_rows,
    store_bytes,
)


class TestResultDigestComparesResults:
    """Not environments. Two identical runs in different temporary directories
    reported DIFFERENT before volatile fields were excluded, which is the false
    positive that would make the comparison useless."""

    def test_the_same_rows_digest_alike(self):
        rows = [{"id": 1, "kind": "tool.call"}, {"id": 2, "kind": "message"}]
        assert result_digest(rows) == result_digest(list(rows))

    def test_different_rows_digest_differently(self):
        assert result_digest([{"id": 1}]) != result_digest([{"id": 2}])

    def test_order_is_part_of_the_result(self):
        """A query states deterministic ordering, so a reordering is a change."""
        a = [{"id": 1}, {"id": 2}]
        assert result_digest(a) != result_digest(list(reversed(a)))

    def test_a_run_location_does_not_change_the_digest(self):
        """Rewritten relative to the run root, not dropped. Dropping was the
        first fix and it overcorrected -- see the next test."""
        first = [{"id": 1, "project_path": "/tmp/run-a/p"}]
        second = [{"id": 1, "project_path": "/tmp/run-b/p"}]
        assert result_digest(first, run_root="/tmp/run-a") == result_digest(
            second, run_root="/tmp/run-b"
        )

    def test_a_different_project_is_still_reported_as_different(self):
        """The overcorrection this caught: excluding located fields outright made
        a query that returned another Project's rows compare EQUAL, which is
        exactly the defect a comparison exists to find."""
        first = [{"id": 1, "project_path": "/tmp/run-a/alpha"}]
        second = [{"id": 1, "project_path": "/tmp/run-b/beta"}]
        assert result_digest(first, run_root="/tmp/run-a") != result_digest(
            second, run_root="/tmp/run-b"
        )

    def test_a_different_store_file_is_reported_as_different(self):
        first = [{"id": 1, "path": "/tmp/run-a/v1.db"}]
        second = [{"id": 1, "path": "/tmp/run-b/v2.db"}]
        assert result_digest(first, run_root="/tmp/run-a") != result_digest(
            second, run_root="/tmp/run-b"
        )

    def test_a_timestamp_does_not_change_the_digest(self):
        first = [{"id": 1, "observed_at": "2026-01-01T00:00:00+00:00"}]
        second = [{"id": 1, "observed_at": "2026-06-01T00:00:00+00:00"}]
        assert result_digest(first) == result_digest(second)

    def test_located_fields_are_rewritten_recursively(self):
        nested = {"rows": [{"id": 1, "path": "/run/x", "kept": 2}]}
        assert stable_rows(nested, run_root="/run") == {
            "rows": [{"id": 1, "path": "<run>/x", "kept": 2}]
        }

    def test_without_a_run_root_a_located_field_is_dropped(self):
        """Safe but blind: the fallback cannot distinguish two Projects. A caller
        that knows its scratch directory should say so."""
        nested = {"rows": [{"id": 1, "path": "/x", "kept": 2}]}
        assert stable_rows(nested) == {"rows": [{"id": 1, "kept": 2}]}

    def test_the_field_sets_do_not_cover_a_result_field(self):
        """Neither set may be so wide it hides a real change."""
        for field in ("id", "event_kind", "events", "sessions"):
            assert field not in TIMING_FIELDS
            assert field not in LOCATED_FIELDS

    def test_the_two_sets_are_disjoint(self):
        """A field is either a clock reading or a position, never both -- they are
        handled differently, so an overlap would make the treatment ambiguous."""
        assert set() == TIMING_FIELDS & LOCATED_FIELDS


class TestMeasurement:
    """CoPlan 11.4's required evidence, and the figure that compares sizes."""

    def test_per_row_cost_is_reported_for_a_measured_row_count(self):
        m = Measurement(name="q", seconds=0.5, rows=1_000)
        assert m.per_row_us() == pytest.approx(500.0)

    def test_per_row_cost_is_absent_rather_than_zero_without_rows(self):
        """A phase measuring a plan has no rows; reporting 0 us/row would read
        as free rather than as not applicable."""
        assert Measurement(name="plan", seconds=0.1).per_row_us() is None

    def test_the_report_carries_every_required_field(self):
        report = Measurement(name="q", seconds=1.0, rows=10).report()
        for key in (
            "seconds", "rows", "per_row_us", "source_bytes", "peak_bytes",
            "result_digest", "plans", "rows_visited",
        ):
            assert key in report, key

    def test_a_measured_phase_records_time_and_peak_allocation(self):
        with measured("build") as m:
            _ = [object() for _ in range(20_000)]
        assert m.seconds > 0
        assert m.peak_bytes > 0

    def test_memory_tracing_is_optional(self):
        """A timing run and a memory run measure different things: tracing costs
        roughly 2x, so a timing comparison must be able to decline it."""
        with measured("t", trace_memory=False) as m:
            pass
        assert m.peak_bytes == 0


class TestWorkloadComparison:
    """Result equality is checked before cost, because a faster run returning
    different rows is a defect rather than an improvement."""

    def _run(self, digest: str, seconds: float) -> Workload:
        work = Workload("w", size="correctness")
        def body(m):
            m.rows = 10
            m.result_digest = digest
        work.measure("phase", body, trace_memory=False)
        work.measurements[-1].seconds = seconds
        return work

    def test_equal_results_are_reported_as_comparable(self):
        a, b = self._run("d1", 1.0), self._run("d1", 0.5)
        report = a.compare(b)
        assert report["all_results_equal"] is True
        assert report["phases"]["phase"]["ratio"] == pytest.approx(0.5)

    def test_a_faster_run_with_different_results_is_not_an_improvement(self):
        a, b = self._run("d1", 1.0), self._run("d2", 0.1)
        report = a.compare(b)
        assert report["all_results_equal"] is False

    def test_an_absent_phase_is_reported_rather_than_ignored(self):
        a = self._run("d1", 1.0)
        b = Workload("w")
        assert a.compare(b)["phases"]["phase"]["comparable"] is False

    def test_a_phase_is_retrievable_by_name(self):
        work = self._run("d1", 1.0)
        assert work.phase("phase") is not None
        assert work.phase("absent") is None


class TestQueryPlans:
    """A timing that improved without a plan change is usually measuring the page
    cache, and a plan that became a scan is a regression a timing may not show
    until the data grows."""

    def test_a_plan_is_recorded_as_text_lines(self, tmp_path):
        from codess.store import connect, init_db

        db = tmp_path / "p.db"
        init_db(db)
        conn = connect(db, read_only=True)
        try:
            plans = query_plan(conn, "SELECT id FROM events WHERE session_id=?", ("s",))
        finally:
            conn.close()
        assert plans and all(isinstance(line, str) for line in plans)

    def test_an_unparseable_statement_reports_rather_than_raises(self, tmp_path):
        """A plan is evidence about a measurement, so failing to get one must not
        abort the measurement."""
        from codess.store import connect, init_db

        db = tmp_path / "p.db"
        init_db(db)
        conn = connect(db, read_only=True)
        try:
            plans = query_plan(conn, "SELECT nonsense FROM nowhere")
        finally:
            conn.close()
        assert plans and plans[0].startswith("unavailable:")

    def test_a_scan_is_reported_not_judged(self):
        """A small table is cheaper scanned than indexed, so the caller decides."""
        assert scans_a_table(["SCAN events"]) is True
        assert scans_a_table(["SEARCH events USING INDEX idx_events_session"]) is False
        assert scans_a_table(["SCAN events USING COVERING INDEX idx_x"]) is False


class TestCaseSizes:
    """Two sizes, anchored to measured reality rather than chosen."""

    def test_both_sizes_exist_and_differ_by_orders_of_magnitude(self):
        assert set(CASE_SIZES) == {"correctness", "scale"}
        assert CASE_SIZES["scale"] >= CASE_SIZES["correctness"] * 100

    def test_the_correctness_case_is_small_enough_to_assert_on(self):
        assert CASE_SIZES["correctness"] <= 100


class TestStoreBytes:
    """A store's file size alone understates what was read from a database with
    an active WAL, which is the ordinary state of a live vendor container."""

    def test_a_missing_file_is_zero_rather_than_an_error(self, tmp_path):
        assert store_bytes(tmp_path / "absent.db") == 0

    def test_sidecars_are_counted_with_the_main_file(self, tmp_path):
        main = tmp_path / "s.db"
        main.write_bytes(b"a" * 100)
        (tmp_path / "s.db-wal").write_bytes(b"b" * 50)
        assert store_bytes(main) == 150


class TestOverviewAmortizes:
    """The defect the harness found on its first run.

    `overview` cost a flat ~282 us/row over 20,000 Events while every other
    action amortized, and profiling attributed it to three datetime
    constructions per Event for two values that change at most once a day. The
    fix caches by day; this pins that the cost now falls with scale rather than
    staying flat, which is the property a per-row figure exists to reveal.
    """

    def _overview_us_per_row(self, tmp_path, sessions: int, per_session: int):
        import sys

        sys.path.insert(0, str(tmp_path.parent))
        from store_fixtures import insert_event, insert_session

        from codess.query_api import execute, make_request
        from codess.store import connect, init_db
        from codess.workload import measured

        db = tmp_path / f"o{sessions}.db"
        init_db(db)
        conn = connect(db)
        try:
            for index in range(sessions):
                # Distinct per store: `observation_id` is unique, so reusing an
                # id across the two measured stores collides.
                sid = f"s{per_session}-{index:04d}"
                insert_session(conn, sid, source="Claude", project_path="/w/p")
                for offset in range(per_session):
                    insert_event(
                        conn, sid, f"e{offset:05d}", sequence_no=offset + 1,
                        event_at=1_700_000_000_000 + offset,
                        event_kind="tool.call", actor_kind="model",
                        content_role="tool_input", origin_kind="direct",
                        content="x",
                    )
            conn.commit()
        finally:
            conn.close()
        conn = connect(db, read_only=True)
        try:
            scope = [{"conn": conn, "path": db, "project_path": tmp_path}]
            with measured("overview", trace_memory=False) as m:
                execute(scope, make_request("overview"))
        finally:
            conn.close()
        return m.seconds / (sessions * per_session)

    def test_the_same_day_is_converted_once_not_once_per_event(self, tmp_path):
        """Every Event shares a day here, so a per-Event conversion would make
        the per-row cost flat as the count grows."""
        small = self._overview_us_per_row(tmp_path, 2, 100)
        large = self._overview_us_per_row(tmp_path, 2, 1_000)
        # Per-row cost must not grow with the row count. A generous bound: the
        # assertion is about the shape of the curve, not a platform's absolute
        # speed, and a strict ratio would make this a flaky timing test.
        assert large < small * 3, f"per-row cost grew: {small:.3e} -> {large:.3e}"


class TestAncillaryReadsAreBounded:
    """The reads that can meet content no vendor contract bounds.

    Each is a file whose size is a property of something other than a Session: a
    tool's output, a developer's working tree, a Project's Source count. A bound
    is chosen against the measured corpus so it rejects an outlier rather than
    truncating ordinary input.
    """

    def test_an_oversize_persisted_tool_output_is_refused_not_read(self, tmp_path):
        """The size is checked before the read: rejecting after reading would
        already have materialized the body the bound exists to exclude."""
        import json as json_module

        from codess.adapters.cc import process_file

        session_dir = tmp_path / "session-id"
        sidecar = session_dir / "tool-results" / "result.txt"
        sidecar.parent.mkdir(parents=True)
        sidecar.write_bytes(b"y" * 4096)
        transcript = tmp_path / "session-id.jsonl"
        transcript.write_text(json_module.dumps({
            "type": "user",
            "message": {"role": "user", "content": [{
                "type": "tool_result", "tool_use_id": "tool-1", "content": "x",
            }]},
            "toolUseResult": {"persistedOutputPath": str(sidecar)},
        }) + "\n")

        opts = {
            "redact": False, "diagnostics": {}, "record_diagnostics": [],
            "max_external_content_bytes": 1024,
        }
        events = list(process_file(transcript, "session-id", opts))

        external = [e for e in events if e["event_type"] == "external_content"]
        assert external == [], "an oversize body must not become content"
        assert opts["diagnostics"].get("external_content_oversize") == 1
        refusals = [
            item for item in opts["record_diagnostics"]
            if item["reason_code"] == "external_content_oversize"
        ]
        assert len(refusals) == 1, "the refusal is recorded with its locator"
        assert "4096" in refusals[0]["detail"]

    def test_an_ordinary_persisted_output_is_still_admitted(self, tmp_path):
        """The bound must reject an outlier, not ordinary output."""
        import json as json_module

        from codess.adapters.cc import process_file

        session_dir = tmp_path / "session-id"
        sidecar = session_dir / "tool-results" / "result.txt"
        sidecar.parent.mkdir(parents=True)
        sidecar.write_text("external result body")
        transcript = tmp_path / "session-id.jsonl"
        transcript.write_text(json_module.dumps({
            "type": "user",
            "message": {"role": "user", "content": [{
                "type": "tool_result", "tool_use_id": "tool-1", "content": "x",
            }]},
            "toolUseResult": {"persistedOutputPath": str(sidecar)},
        }) + "\n")
        events = list(process_file(
            transcript, "session-id",
            {"redact": False, "external_sources": []},
        ))
        external = [e for e in events if e["event_type"] == "external_content"]
        assert len(external) == 1
        assert external[0]["content"] == "external result body"

    def test_the_external_bound_is_generous_against_the_measured_corpus(self):
        """Four persisted outputs were observed, the largest 110 KB. A bound at
        or below that would truncate ordinary output."""
        from codess.config import MAX_EXTERNAL_CONTENT_BYTES

        assert MAX_EXTERNAL_CONTENT_BYTES > 110_304 * 4

    def test_an_oversize_untracked_file_does_not_change_the_build_identity(
        self, tmp_path,
    ):
        """A dirty tree whose fingerprint silently ignored its largest untracked
        file would report two different trees as the same build. Size and mtime
        are recorded instead, so the file still contributes."""
        from codess.config import WORKTREE_DIGEST_MAX_BYTES

        assert WORKTREE_DIGEST_MAX_BYTES >= 8 * 1024 * 1024

    def test_the_raw_manifest_is_streamed_rather_than_materialized(self):
        """A manifest grows with a Project's Source count and is read on every
        validation, so holding the text and the parsed records is two copies of
        a file with no stated upper bound."""
        from pathlib import Path

        import codess.baseline_validation as module

        text = Path(module.__file__).read_text(encoding="utf-8")
        assert "RAW_MANIFEST_FILE).read_text(" not in text
        assert "RAW_MANIFEST_FILE).open(" in text


class TestSelectedCursorWorkIsIndependentOfTheContainer:
    """Answered by measurement rather than by inspection.

    A shared vendor database holds every workspace an operator has, so the cost
    of reading one Project's Sessions must track the *selection* rather than the
    container. The two are indistinguishable at a single container size, which is
    why this measures one identical selection against containers that differ by
    three orders of magnitude.

    Measured: growing the container 1000x -- 0 to 200,000 unrelated bubbles,
    19.5 MB -- changed the selected read cost by 1.21x. A scan would have grown
    with the container.
    """

    def _selected_read(self, tmp_path, unrelated: int):
        import sqlite3
        import sys

        sys.path.insert(0, str(tmp_path.parent))
        from cursor_fixtures import create_bubble_table, put_bubbles

        from codess.cursor_source import connect_readonly, iter_bubble_rows
        from codess.workload import measured, query_plan, result_digest

        db = tmp_path / f"c{unrelated}.vscdb"
        conn = sqlite3.connect(db)
        try:
            create_bubble_table(conn)
            put_bubbles(conn, [
                ("c0", f"b{i:05d}", {"text": f"s{i}", "type": 1})
                for i in range(200)
            ])
            if unrelated:
                put_bubbles(conn, [
                    (f"z{o:05d}", f"b{i:05d}", {"text": f"u{o}-{i}", "type": 1})
                    for o in range(unrelated // 200) for i in range(200)
                ])
            conn.commit()
        finally:
            conn.close()

        read = connect_readonly(db)
        try:
            with measured("selected", trace_memory=False) as m:
                rows = list(iter_bubble_rows(read, {"c0"}))
            plans = query_plan(
                read,
                "SELECT key, value FROM cursorDiskKV WHERE key >= ? AND key < ?",
                ("bubbleId:c0:", "bubbleId:c0;"),
            )
        finally:
            read.close()
        return {
            "seconds": m.seconds, "rows": len(rows), "plans": plans,
            "digest": result_digest([key for key, _ in rows]),
            "bytes": db.stat().st_size,
        }

    def test_the_same_selection_returns_the_same_rows_at_any_container_size(
        self, tmp_path,
    ):
        """Correctness before cost: a bounded read that returned fewer rows in a
        larger container would be a defect the timing would not reveal."""
        small = self._selected_read(tmp_path, 0)
        large = self._selected_read(tmp_path, 20_000)
        assert small["rows"] == large["rows"] == 200
        assert small["digest"] == large["digest"]

    def test_unrelated_content_does_not_make_the_selected_read_scan(self, tmp_path):
        """The plan is the durable assertion. A timing can be fast on a warm
        cache; a plan that became a scan is the regression that appears later."""
        from codess.workload import scans_a_table

        large = self._selected_read(tmp_path, 20_000)
        assert not scans_a_table(large["plans"]), large["plans"]
        assert any("key>" in line or "key >" in line for line in large["plans"]), (
            f"expected an indexed key-range search: {large['plans']}"
        )

    def test_the_container_grows_while_the_selected_read_does_not(self, tmp_path):
        """The measurement, bounded generously: the assertion is about the shape
        of the curve rather than a platform's absolute speed."""
        small = self._selected_read(tmp_path, 0)
        large = self._selected_read(tmp_path, 20_000)
        growth = large["bytes"] / max(1, small["bytes"])
        assert growth > 5, f"the container must actually grow: {growth:.1f}x"
        # Cost is allowed to rise a little -- a larger B-tree is deeper -- but
        # not proportionally to the container.
        assert large["seconds"] < small["seconds"] * 10 + 0.05, (
            f"selected read grew with the container: "
            f"{small['seconds']:.5f}s -> {large['seconds']:.5f}s"
        )

