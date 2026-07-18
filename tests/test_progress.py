"""Live and persisted processing progress."""

from __future__ import annotations

import io

from codess.progress import ProgressTrace


def test_progress_trace_emits_and_filters_without_content() -> None:
    stream = io.StringIO()
    trace = ProgressTrace(stream=stream, max_events=4)

    trace("cohort.start", projects=2)
    trace("project.start", project="/work/one", project_index=1)
    trace("project.start", project="/work/two", project_index=2)

    assert "codess: progress " in stream.getvalue()
    assert "cohort.start projects=2" in stream.getvalue()
    records = trace.records_for("/work/one")
    assert [record["event"] for record in records] == [
        "cohort.start", "project.start",
    ]
    assert records[1]["project"] == "/work/one"
    assert records[0]["at"].endswith("+00:00")
    assert len(trace.records_for()) == 3


def test_progress_trace_bounds_persisted_events() -> None:
    trace = ProgressTrace(enabled=False, max_events=1)
    trace("first")
    trace("second")

    records = trace.records_for()
    assert [record["event"] for record in records] == [
        "first", "progress.events_dropped",
    ]
    assert records[-1]["count"] == 1
