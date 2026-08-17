"""Progress reporting: the callable a library takes, and the per-Project view.

These replace the tests for `ProgressTrace`, which was the whole progress
facility and then briefly a shim over `codess.reporting`. The shim is gone; what
remains is a function and a sink accessor, and the properties worth pinning are
different from the class's.

The two the class got wrong, which is why it went:

- it bypassed the level gate, so a quiet profile still printed every per-source
  event; and
- it rendered an unregistered event name anyway, which let 23 of the 38 names
  actually emitted go missing from the code table without anyone noticing.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from codess import reporting
from codess.reporting import emit_named
from codess.reporting.codes import CODE_BY_NAME, FIELD_CLASSES, WARNING
from codess.reporting.sinks import CollectorSink

PACKAGE = Path(reporting.__file__).resolve().parent


@pytest.fixture(autouse=True)
def _clean():
    reporting.reset()
    yield
    reporting.reset()


class TestEmitGoesThroughTheContract:
    """Not around it. The deleted shim constructed its own sink and emitted
    directly, which is how it escaped the gates."""

    def test_an_event_reaches_an_attached_sink(self):
        collector = CollectorSink()
        reporting.configure("debug", sinks=(collector,))
        emit_named("ingest.start", projects=2)
        reporting.flush()
        assert [r["event"] for r in collector.records] == ["ingest.start"]
        assert collector.records[0]["projects"] == 2

    def test_the_level_gate_applies_to_what_an_operator_sees(self):
        """The defect that forced the deletion: a quiet profile must suppress a
        debug-level event, and the shim's own sink never consulted the gate.

        Asserted on a sink that filters at the profile's level. The collector
        deliberately retains more -- see `TestRetentionAndDisplayAreIndependent`.
        """
        collector = CollectorSink(min_level=WARNING)
        reporting.configure("deployment", sinks=(collector,))
        emit_named("source.done", path="/x")
        reporting.flush()
        assert collector.records == []


class TestRetentionAndDisplayAreIndependent:
    """Report R6, and the defect that proved it is not academic.

    One process-wide threshold governed both. Filtering the durable report at the
    profile's level emptied it of every debug event it had always carried, so a
    quiet run produced a report that could not explain what happened. The gate is
    now the minimum across sinks and each sink filters its own.
    """

    def test_a_quiet_profile_still_retains_a_debug_event(self):
        collector = CollectorSink()
        reporting.configure("deployment", sinks=(collector,))
        emit_named("source.done", path="/x")
        reporting.flush()
        assert [r["event"] for r in collector.records] == ["source.done"]

    def test_the_same_run_prints_nothing(self):
        import io

        from codess.reporting.sinks import HumanSink

        stream = io.StringIO()
        collector = CollectorSink()
        reporting.configure("deployment", sinks=(
            collector, HumanSink(stream, min_level=WARNING),
        ))
        emit_named("source.done", path="/x")
        reporting.flush()
        assert stream.getvalue() == "", "a quiet profile must stay quiet"
        assert collector.records, "and the report must still explain the run"

    def test_a_warning_survives_a_quiet_profile(self):
        collector = CollectorSink()
        reporting.configure("deployment", sinks=(collector,))
        emit_named("source.failed", path="/x")
        reporting.flush()
        assert [r["event"] for r in collector.records] == ["source.failed"]

    def test_absent_fields_are_dropped_not_rendered_as_none(self):
        collector = CollectorSink()
        reporting.configure("debug", sinks=(collector,))
        emit_named("vendor.done", vendor="Claude", events=None)
        reporting.flush()
        assert "events" not in collector.records[0]

    def test_an_unknown_event_name_raises_rather_than_degrading(self):
        """The quiet fallback is removed deliberately. Rendering an unregistered
        name anyway is what hid 23 missing codes."""
        reporting.configure("debug", sinks=(CollectorSink(),))
        with pytest.raises(KeyError, match="unknown progress event"):
            emit_named("invented.at.runtime")

    def test_emitting_without_a_configured_sink_is_harmless(self):
        """A library function may be called by a process that never configured
        reporting; that must not raise."""
        emit_named("ingest.start", projects=1)


class TestEveryEmittedEventIsRegistered:
    """The check that would have caught the drift the shim concealed.

    Derived from the call sites rather than maintained by hand: a progress point
    added without a code fails here instead of silently losing its level.
    """

    def _emitted(self) -> tuple[set[str], set[str]]:
        names: set[str] = set()
        fields: set[str] = set()
        for path in sorted(PACKAGE.parent.rglob("*.py")):
            if "egg-info" in str(path):
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                name = (
                    func.id if isinstance(func, ast.Name)
                    else getattr(func, "attr", None)
                )
                if name not in ("progress", "progress_trace", "emit", "_progress"):
                    continue
                if not node.args:
                    continue
                # `_progress(opts, "name", ...)` carries the name second. Missing
                # this is how ten Cursor events stayed unregistered: the scan
                # looked at one argument position and there are two conventions.
                candidate = (
                    node.args[1] if name == "_progress" and len(node.args) > 1
                    else node.args[0]
                )
                if isinstance(candidate, ast.Constant) and isinstance(
                    candidate.value, str
                ):
                    names.add(candidate.value)
                    fields |= {kw.arg for kw in node.keywords if kw.arg}
        return names, fields

    def test_every_emitted_event_name_has_a_code(self):
        names, _ = self._emitted()
        assert names, "the scan found no call sites, so it is not checking anything"
        assert sorted(names - set(CODE_BY_NAME)) == []

    def test_every_emitted_field_name_is_classified(self):
        """An unclassified field renders as `<unregistered>` under a sharing
        profile, so the allowlist has to cover what the call sites pass."""
        _, fields = self._emitted()
        assert sorted(fields - set(FIELD_CLASSES)) == []


class TestPerProjectRetention:
    """What the process-wide ring cannot do, and where it now lives.

    One ingest run touches several Projects and each Project's durable report
    must carry its own events plus the run-level ones. The deleted class solved
    that with a separate deque outside the facility; `CollectorSink` filters
    instead, so there is one bounded store and one drop count.
    """

    def _collected(self) -> CollectorSink:
        collector = CollectorSink()
        reporting.configure("debug", sinks=(collector,))
        emit_named("ingest.start", projects=2)
        emit_named("project.start", project="/w/a")
        emit_named("project.done", project="/w/a")
        emit_named("project.start", project="/w/b")
        reporting.flush()
        return collector

    def test_all_records_are_returned_without_a_project(self):
        assert len(self._collected().records_for()) == 4

    def test_one_project_gets_its_own_events(self):
        selected = self._collected().records_for("/w/a")
        assert [r["event"] for r in selected] == [
            "ingest.start", "project.start", "project.done",
        ]

    def test_a_run_level_event_belongs_to_every_project(self):
        """`ingest.start` is not about one Project, and a report omitting it
        would not explain what the run was doing."""
        for project in ("/w/a", "/w/b"):
            events = [r["event"] for r in self._collected().records_for(project)]
            assert "ingest.start" in events

    def test_another_projects_events_are_excluded(self):
        selected = self._collected().records_for("/w/a")
        assert not any(r.get("project") == "/w/b" for r in selected)

    def test_a_truncated_report_says_it_is_truncated(self):
        """A bound must be visible: otherwise a reader cannot distinguish a quiet
        run from one whose evidence was discarded."""
        collector = CollectorSink(max_records=2)
        reporting.configure("debug", sinks=(collector,))
        for index in range(5):
            emit_named("project.start", project=f"/w/{index}")
        reporting.flush()
        records = collector.records_for()
        assert records[-1]["event"] == "report.events_dropped"
        assert records[-1]["count"] == 3

    def test_the_facility_exposes_its_collector(self):
        """So a durable report reaches it without a parameter threaded down two
        call chains whose only purpose was carrying it."""
        collector = CollectorSink()
        reporting.configure("debug", sinks=(collector,))
        assert reporting.collector() is collector

    def test_a_profile_without_a_collector_reports_none(self):
        """`benchmark` attaches nothing by design, and a report should say it has
        no events rather than fail on the accessor."""
        reporting.configure("benchmark")
        assert reporting.collector() is None


class TestTheShimIsGone:
    """Its removal is the point, so it is asserted rather than assumed."""

    def test_the_module_is_gone_entirely(self):
        """It became one function beside the primitives it wraps. A module
        holding a single three-statement function is a file a reader opens to
        learn nothing."""
        assert not (PACKAGE.parent / "progress.py").exists()

    def test_nothing_imports_the_deleted_module(self):
        """An import statement, not any mention: this file names the module in
        prose, and a substring check would match itself."""
        import ast

        for base in ("src", "tests", "tools"):
            for path in sorted((PACKAGE.parents[2] / base).rglob("*.py")):
                if "egg-info" in str(path):
                    continue
                for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                    if isinstance(node, ast.ImportFrom):
                        assert node.module != "codess.progress", path
                    elif isinstance(node, ast.Import):
                        assert all(
                            alias.name != "codess.progress" for alias in node.names
                        ), path

    def test_no_parallel_emitter_remains_in_the_facility(self):
        """The shim constructed its own `HumanSink`; the replacement emits
        through `event`, so it cannot bypass the gates."""
        text = (PACKAGE / "api.py").read_text(encoding="utf-8")
        assert "class ProgressTrace" not in text
        assert "HumanSink(" not in text
