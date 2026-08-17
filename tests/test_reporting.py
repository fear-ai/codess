"""The reporting facility: gates, event structure, sinks, and privacy.

Gates G1 and G2 from Report 13.3. G1 requires the package to exist with no
Codess import in its leaves and to reproduce R1-R5 against the real
implementation rather than the prototypes measured in Report 2. G2 requires the
sinks to round-trip an event, including the encoding fallback and R10.
"""

from __future__ import annotations

import ast
import io
import json
from pathlib import Path

import pytest

from codess import reporting
from codess.reporting import buffer as buffer_module
from codess.reporting import clock, codes, privacy
from codess.reporting.levels import MAX_FIELDS, REPORT_TRACE, resolve
from codess.reporting.sinks import (
    CODE,
    FIELDS,
    LEVEL,
    TICK,
    CollectorSink,
    HumanSink,
    JsonlSink,
    NullSink,
)

REPORTING_ROOT = Path(reporting.__file__).resolve().parent


@pytest.fixture(autouse=True)
def _clean_facility():
    """Every test starts with nothing attached and no counts."""
    reporting.reset()
    yield
    reporting.reset()


class TestTheLeavesHaveNoCodessDependency:
    """Report 4: `clock`, `buffer`, and `codes` must be importable by `fileio`
    and the adapters without a cycle, which only holds if they import nothing
    from Codess."""

    LEAVES = ("clock.py", "buffer.py", "codes.py")

    def _imports(self, name: str) -> set[str]:
        tree = ast.parse((REPORTING_ROOT / name).read_text(encoding="utf-8"))
        found = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                found.add(node.module)
        return found

    def test_no_leaf_imports_codess_outside_the_package(self):
        for name in self.LEAVES:
            outside = {
                module for module in self._imports(name)
                if module.startswith("codess.")
                and not module.startswith("codess.reporting")
            }
            assert outside == set(), f"{name} imports {outside}"

    def test_the_package_does_not_import_the_store_or_the_cli(self):
        """A facility the store imports must not import the store."""
        for path in sorted(REPORTING_ROOT.rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            for forbidden in ("codess.store", "codess.query_api", "cli."):
                assert f"import {forbidden}" not in text, f"{path.name}: {forbidden}"


class TestGatesInCostOrder:
    """Report 6. The cheapest rejection happens first, and the run-time sink
    check precedes all construction."""

    def test_no_sink_attached_emits_nothing(self):
        reporting.event(reporting.code("ingest.start"), projects=1)
        assert reporting.counters() == {}

    def test_an_event_below_a_sinks_threshold_is_dropped(self):
        """Per sink, not process-wide. The gate constructs an event if any sink
        accepts it, so suppression is asserted on a sink that filters (R6)."""
        collector = CollectorSink(min_level=codes.WARNING)
        # deployment starts at warning; `source.done` is debug.
        reporting.configure("deployment", sinks=(collector,))
        reporting.event(reporting.code("source.done"), path="/x")
        reporting.flush()
        assert collector.records == []

    def test_a_durable_sink_retains_what_a_quiet_profile_does_not_print(self):
        """Report R6: immediacy and permanence are selected independently."""
        collector = CollectorSink()
        reporting.configure("deployment", sinks=(collector,))
        reporting.event(reporting.code("source.done"), path="/x")
        reporting.flush()
        assert [r["event"] for r in collector.records] == ["source.done"]

    def test_an_event_at_the_threshold_is_emitted(self):
        collector = CollectorSink()
        reporting.configure("deployment", sinks=(collector,))
        reporting.event(reporting.code("project.failed"), error_type="OSError")
        reporting.flush()
        assert [r["event"] for r in collector.records] == ["project.failed"]

    def test_the_compile_gate_is_a_module_constant(self):
        """R2 needs a literal-bound constant, or the branch is not folded."""
        assert isinstance(REPORT_TRACE, bool)

    def test_a_disabled_site_costs_less_than_the_facility_it_replaces(self):
        """R1's intent, not its exact figure.

        `**fields` packs a dict before any gate in the body runs (~43 ns for two
        fields), so the measured 76 ns cannot reach Report 3's ~16 ns estimate.
        The claim that holds is the one that matters: far cheaper than the
        1,245 ns of the facility being replaced.
        """
        import timeit

        code = reporting.code("source.done")
        per_call = timeit.timeit(
            lambda: reporting.event(code, path="/x", events=1), number=20_000,
        ) / 20_000
        assert per_call < 400e-9, f"{per_call * 1e9:.0f} ns per disabled call"


class TestEventStructure:
    """Report 5. A tuple with fixed positions, an integer code, a monotonic
    tick, and a flat field tuple."""

    def test_an_event_is_a_five_tuple_with_a_flat_field_pair_list(self):
        seen: list[tuple] = []

        class Capture:
            def emit(self, events): seen.extend(events)
            def close(self): pass

        reporting.configure("debug", sinks=(Capture(),))
        reporting.event(reporting.code("vendor.start"), vendor="Claude", events=3)
        reporting.flush()
        assert len(seen) == 1
        record = seen[0]
        assert len(record) == 5
        assert record[CODE] == reporting.code("vendor.start")
        assert record[LEVEL] == codes.INFO
        assert record[FIELDS] == ("vendor", "Claude", "events", 3)

    def test_the_tick_is_monotonic_and_never_a_formatted_string(self):
        """R4: no timestamp is formatted unless it is rendered."""
        seen: list[tuple] = []

        class Capture:
            def emit(self, events): seen.extend(events)
            def close(self): pass

        reporting.configure("debug", sinks=(Capture(),))
        before = clock.tick()
        reporting.event(reporting.code("scan.start"))
        reporting.flush()
        assert isinstance(seen[0][TICK], int)
        assert seen[0][TICK] >= before

    def test_a_code_is_an_integer_resolved_from_a_closed_set(self):
        assert isinstance(reporting.code("ingest.done"), int)
        with pytest.raises(KeyError, match="unknown event name"):
            reporting.code("invented.at.runtime")

    def test_a_code_is_never_reused_for_a_second_name(self):
        """A retained report holds integers, so renumbering relabels history."""
        assert len(set(codes.EVENT_NAMES)) == len(codes.EVENT_NAMES)
        assert len(codes.CODE_BY_NAME) == len(codes.EVENT_NAMES)

    def test_fields_beyond_the_bound_are_counted_not_raised(self):
        """R10: a reporting call never raises into the operation."""
        collector = CollectorSink()
        reporting.configure("debug", sinks=(collector,))
        fields = {f"f{i}": i for i in range(MAX_FIELDS + 5)}
        reporting.event(reporting.code("scan.done"), **fields)
        reporting.flush()
        assert reporting.counters().get("fields_rejected") == 1
        # The bound is on the caller's fields, not on the envelope, so count the
        # `f*` keys rather than the whole record: the envelope's own keys are
        # fixed and asserting a total conflates the two.
        caller_fields = [k for k in collector.records[0] if k.startswith("f")]
        assert len(caller_fields) == MAX_FIELDS


class TestCounters:
    """Report 2.3. A per-record fact is an index into a preallocated list."""

    def test_a_counter_needs_no_sink(self):
        """An ingest summary reports counters from a run that emitted nothing."""
        reporting.count(reporting.slot("malformed"))
        assert reporting.counters() == {"malformed": 1}

    def test_only_non_zero_counters_are_reported(self):
        """Nineteen counters of which two fired would bury the two."""
        reporting.count(reporting.slot("ignored"), 3)
        assert reporting.counters() == {"ignored": 3}

    def test_an_unknown_counter_is_refused(self):
        with pytest.raises(KeyError, match="unknown counter"):
            reporting.slot("not_a_counter")

    def test_every_slot_has_a_distinct_index(self):
        assert len(codes.SLOT_BY_NAME) == codes.COUNTER_COUNT


class TestSpans:
    """Report 5. Two ticks and a subtraction, and a failure still reports."""

    def test_a_span_reports_its_duration(self):
        collector = CollectorSink()
        reporting.configure("debug", sinks=(collector,))
        with reporting.span(reporting.code("vendor.done"), vendor="Codex"):
            pass
        reporting.flush()
        assert collector.records[0]["vendor"] == "Codex"
        assert collector.records[0]["phase_seconds"] >= 0

    def test_a_span_carries_fields_discovered_during_the_phase(self):
        collector = CollectorSink()
        reporting.configure("debug", sinks=(collector,))
        with reporting.span(reporting.code("vendor.done")) as extra:
            extra["events"] = 412
        reporting.flush()
        assert collector.records[0]["events"] == 412

    def test_a_failing_phase_reports_and_re_raises(self):
        """A phase that failed after 40 seconds is more informative than
        silence, and swallowing would change the observed code's behaviour."""
        collector = CollectorSink()
        reporting.configure("debug", sinks=(collector,))
        with pytest.raises(ValueError), reporting.span(
            reporting.code("project.failed")
        ):
            raise ValueError("boom")
        reporting.flush()
        assert collector.records[0]["error_type"] == "ValueError"


class TestSinksRoundTripAnEvent:
    """Gate G2. Each sink renders the envelope, and none raises (R10)."""

    def test_the_human_sink_renders_one_line_per_event(self):
        stream = io.StringIO()
        reporting.configure("debug", sinks=(HumanSink(stream),))
        reporting.event(reporting.code("ingest.start"), projects=2)
        reporting.flush()
        line = stream.getvalue().strip()
        assert "ingest.start" in line
        assert "projects=2" in line

    def test_the_jsonl_sink_emits_one_object_per_line(self):
        stream = io.StringIO()
        reporting.configure("debug", sinks=(JsonlSink(stream),))
        reporting.event(reporting.code("ingest.done"), events=5, status="accepted")
        reporting.flush()
        record = json.loads(stream.getvalue().strip())
        assert record["event"] == "ingest.done"
        assert record["events"] == 5
        assert record["level"] == "info"
        assert record["scope"] == "ingest"

    def test_a_value_that_cannot_be_serialized_degrades_rather_than_raising(self):
        """Report 12.1's encoding fallback."""
        stream = io.StringIO()
        reporting.configure("debug", sinks=(JsonlSink(stream),))
        reporting.event(reporting.code("scan.done"), count=object())
        reporting.flush()
        record = json.loads(stream.getvalue().strip())
        assert isinstance(record["count"], str)

    def test_a_failing_stream_does_not_reach_the_caller(self):
        class Broken(io.StringIO):
            def write(self, _text):
                raise OSError("closed pipe")

        reporting.configure("debug", sinks=(HumanSink(Broken()),))
        reporting.event(reporting.code("ingest.start"))
        reporting.flush()  # must not raise

    def test_a_failing_sink_does_not_stop_the_others(self):
        class Explodes:
            def emit(self, events): raise RuntimeError("nope")
            def close(self): pass

        collector = CollectorSink()
        reporting.configure("debug", sinks=(Explodes(), collector))
        reporting.event(reporting.code("ingest.start"))
        reporting.flush()
        assert [r["event"] for r in collector.records] == ["ingest.start"]

    def test_the_null_sink_discards(self):
        reporting.configure("benchmark", sinks=(NullSink(),))
        reporting.event(reporting.code("command.failed"), error_type="X")
        reporting.flush()

    def test_stdout_is_never_a_sink(self):
        """R9. stdout carries the requested result and nothing else."""
        for path in sorted(REPORTING_ROOT.rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            assert "sys.stdout" not in text, path.name


class TestDurableAndBridgeSinks:
    """The two sinks Report 10 specifies and step 7 added.

    `file` is durable where `jsonl` is immediate: stderr disappears with the
    terminal, and a scale workload or an overnight refresh needs its evidence
    afterwards. `bridge` is for a library call site whose caller configured
    stdlib logging and never called `configure`.
    """

    def test_the_file_sink_writes_one_object_per_line(self, tmp_path):
        from codess.reporting.sinks import FileSink

        out = tmp_path / "events.jsonl"
        reporting.configure("debug", sinks=(FileSink(out),))
        reporting.event(reporting.code("ingest.start"), projects=3)
        reporting.flush()
        reporting.reset()
        record = json.loads(out.read_text(encoding="utf-8").strip())
        assert record["event"] == "ingest.start"
        assert record["projects"] == 3

    def test_the_file_sink_creates_its_parent_directory(self, tmp_path):
        from codess.reporting.sinks import FileSink

        out = tmp_path / "nested" / "deeper" / "events.jsonl"
        reporting.configure("debug", sinks=(FileSink(out),))
        reporting.event(reporting.code("ingest.start"))
        reporting.flush()
        reporting.reset()
        assert out.exists()

    def test_the_file_sink_appends_rather_than_erasing(self, tmp_path):
        """A second run must not silently erase the first run's evidence."""
        from codess.reporting.sinks import FileSink

        out = tmp_path / "events.jsonl"
        for code in ("ingest.start", "ingest.done"):
            reporting.configure("debug", sinks=(FileSink(out),))
            reporting.event(reporting.code(code))
            reporting.flush()
            reporting.reset()
        assert len(out.read_text(encoding="utf-8").strip().splitlines()) == 2

    def test_the_file_sink_leaves_no_file_when_nothing_is_emitted(self, tmp_path):
        """Opened lazily: a profile that attaches it and emits nothing should not
        leave an empty file to be mistaken for a run that produced none."""
        from codess.reporting.sinks import FileSink

        out = tmp_path / "events.jsonl"
        reporting.configure("debug", sinks=(FileSink(out),))
        reporting.flush()
        reporting.reset()
        assert not out.exists()

    def test_an_unwritable_file_does_not_abort_the_operation(self, tmp_path):
        """R10. A reporting sink that cannot open its destination loses the
        events; it must not fail the ingest it was reporting on."""
        from codess.reporting.sinks import FileSink

        blocked = tmp_path / "file"
        blocked.write_text("not a directory", encoding="utf-8")
        reporting.configure("debug", sinks=(FileSink(blocked / "events.jsonl"),))
        reporting.event(reporting.code("ingest.start"))
        reporting.flush()  # must not raise
        reporting.reset()

    def test_the_bridge_sink_maps_the_event_level_onto_logging(self):
        """A handler filtering at WARNING must see warnings and nothing else,
        which is what the caller who configured it asked for."""
        import logging

        captured: list[logging.LogRecord] = []

        class Capture(logging.Handler):
            def emit(self, record):
                captured.append(record)

        from codess.reporting.sinks import BridgeSink

        logger = logging.getLogger("codess.reporting.test")
        logger.setLevel(logging.DEBUG)
        handler = Capture()
        logger.addHandler(handler)
        try:
            reporting.configure(
                "debug", sinks=(BridgeSink("codess.reporting.test"),),
            )
            reporting.event(reporting.code("project.failed"), error_type="OSError")
            reporting.flush()
        finally:
            logger.removeHandler(handler)
            reporting.reset()
        assert len(captured) == 1
        assert captured[0].levelno == logging.ERROR
        assert captured[0].codess_event == "project.failed"
        assert captured[0].codess_fields == {"error_type": "OSError"}

    def test_both_machine_readable_sinks_share_one_envelope(self, tmp_path):
        """A reader parsing either must not have to handle two shapes."""
        import io

        from codess.reporting.sinks import FileSink, JsonlSink

        out = tmp_path / "events.jsonl"
        stream = io.StringIO()
        reporting.configure(
            "debug", sinks=(FileSink(out), JsonlSink(stream)),
        )
        reporting.event(reporting.code("vendor.done"), vendor="Codex", events=7)
        reporting.flush()
        reporting.reset()
        from_file = json.loads(out.read_text(encoding="utf-8").strip())
        from_stderr = json.loads(stream.getvalue().strip())
        assert set(from_file) == set(from_stderr)
        assert from_file["event"] == from_stderr["event"]


class TestBufferingAndFlush:
    """Report 8. Batched, bounded, and immediate on a warning."""

    def test_events_batch_until_the_threshold(self):
        collector = CollectorSink()
        reporting.configure("debug", sinks=(collector,))
        # debug flushes at 32.
        for _ in range(5):
            reporting.event(reporting.code("source.done"), path="/x")
        assert collector.records == [], "a partial batch must not have flushed"
        reporting.flush()
        assert len(collector.records) == 5

    def test_a_warning_flushes_immediately(self):
        """Deferring a failure behind 255 routine events would show the
        operator the problem after the run that caused it."""
        collector = CollectorSink()
        reporting.configure("debug", sinks=(collector,))
        reporting.event(reporting.code("source.failed"), path="/x")
        assert [r["event"] for r in collector.records] == ["source.failed"]

    def test_the_ring_never_grows_and_reports_what_it_dropped(self):
        ring = buffer_module.EventRing(4, flush_events=100)
        for index in range(10):
            ring.append((0, index, codes.INFO, 0, ()))
        assert len(ring) == 4
        assert ring.dropped == 6
        assert [event[1] for event in ring.retained()] == [6, 7, 8, 9]

    def test_a_drain_returns_oldest_first(self):
        ring = buffer_module.EventRing(8, flush_events=100)
        for index in range(3):
            ring.append((0, index, codes.INFO, 0, ()))
        assert [event[1] for event in ring.drain()] == [0, 1, 2]
        assert ring.drain() == [], "a second drain has nothing pending"


class TestProfiles:
    """Report 11 and 15.5. Volume and privacy are chosen once per run."""

    def test_every_named_profile_resolves(self):
        for name in ("debug", "validation", "deployment", "benchmark"):
            assert resolve(name).name == name

    def test_an_unknown_profile_raises_rather_than_defaulting(self):
        """A mistyped profile silently falling back would mean a run intended
        to redact does not."""
        with pytest.raises(ValueError, match="unknown reporting profile"):
            resolve("depoyment")

    def test_an_unknown_privacy_profile_raises(self):
        with pytest.raises(ValueError, match="unknown privacy profile"):
            resolve("debug", "anonymous")

    def test_benchmark_attaches_no_sink(self):
        """Report 11: reporting must contribute zero to a timing run."""
        assert resolve("benchmark").sinks == ()

    def test_local_is_the_default_privacy(self):
        assert resolve("debug").privacy == "local"


class TestPrivacyRendering:
    """Report 15.4. Allowlist, type restriction, bound, structural redaction."""

    def test_local_renders_verbatim(self):
        assert privacy.render("project", "/w/p", privacy="local") == (
            "project", "/w/p",
        )

    def test_an_unregistered_field_is_marked_under_a_shared_profile(self):
        """An allowlist fails closed; a denylist would leak the field nobody
        thought to classify."""
        assert privacy.render("mystery", "x", privacy="shared") == (
            "mystery", codes.UNREGISTERED,
        )

    def test_a_non_scalar_is_rejected_by_type_not_inspected(self):
        """A dict is where a transcript body enters an operational field."""
        _name, value = privacy.render("events", {"body": "secret"}, privacy="shared")
        assert value == privacy.REJECTED
        assert "secret" not in str(value)

    def test_a_located_field_is_rendered_against_its_root(self, tmp_path):
        roots = privacy.Roots({"work": tmp_path})
        _name, value = privacy.render(
            "project", str(tmp_path / "deep" / "inner"),
            privacy="shared", roots=roots,
        )
        assert "deep/inner" in str(value)

    def test_the_longest_matching_root_wins(self, tmp_path):
        """Roots nest: the registry may live under home."""
        nested = tmp_path / "reg"
        nested.mkdir()
        roots = privacy.Roots()
        roots.register("home", tmp_path)
        roots.register("registry", nested)
        assert roots.relative(str(nested / "x")) == "<registry>/x"

    def test_strict_keeps_only_the_root_token(self, tmp_path):
        roots = privacy.Roots({"store": tmp_path})
        _name, value = privacy.render(
            "path", str(tmp_path / "a" / "b" / "c"),
            privacy="strict", roots=roots,
        )
        assert value == "<store>"

    def test_a_path_under_no_registered_root_is_marked_unrooted(self):
        """Never verbatim under `strict`: an unrecognized path is the one most
        likely to name something the profile exists to withhold."""
        _name, value = privacy.render(
            "path", "/elsewhere/x", privacy="strict", roots=privacy.Roots(),
        )
        assert value == "<unrooted>"

    def test_strict_omits_a_linking_identifier_entirely(self):
        assert privacy.render("session_id", "s1", privacy="strict") is None

    def test_shared_truncates_a_linking_identifier(self):
        _name, value = privacy.render("session_id", "s1", privacy="shared")
        assert value != "s1"
        assert len(str(value)) == 8

    def test_the_same_identifier_renders_alike_so_lines_still_correlate(self):
        first = privacy.render("session_id", "s1", privacy="shared")
        second = privacy.render("session_id", "s1", privacy="shared")
        assert first == second

    def test_shared_does_not_close_a_vendor_encoded_path(self, tmp_path):
        """Measured, and recorded because the profile table promises less than a
        reader might assume.

        Claude names a project directory by encoding the absolute path into a
        slug, so the slug is one path segment: keeping the final two keeps it
        whole and the account name survives `shared`. `strict` is what closes it.
        """
        cc = tmp_path / ".claude" / "projects"
        slug = cc / "-Users-someone-Work-Group-Project"
        slug.mkdir(parents=True)
        roots = privacy.Roots({"cc-projects": cc})
        source = str(slug / "abc.jsonl")

        _name, shared = privacy.render(
            "source", source, privacy="shared", roots=roots,
        )
        assert "someone" in str(shared), "the slug survives, which is the point"

        _name, strict = privacy.render(
            "source", source, privacy="strict", roots=roots,
        )
        assert strict == "<cc-projects>"
        assert "someone" not in str(strict)

    def test_a_long_scalar_is_truncated_visibly(self):
        _name, value = privacy.render("reason", "x" * 9000, privacy="shared")
        assert value.endswith(privacy.TRUNCATED_MARKER)

    def test_every_registered_field_has_a_known_class(self):
        assert set(codes.FIELD_CLASSES.values()) <= {
            codes.OPEN, codes.LOCATED, codes.LINKING,
        }

    def test_a_flat_field_tuple_becomes_a_mapping(self):
        assert privacy.render_fields(("events", 3, "vendor", "Codex")) == {
            "events": 3, "vendor": "Codex",
        }


class TestClock:
    """Report 7. One anchor, ticks thereafter, resolution only at flush."""

    def test_a_tick_resolves_to_a_wall_instant(self):
        now = clock.tick()
        resolved = clock.wall_ns(now)
        assert abs(resolved - clock.ANCHOR_WALL_NS) < 60 * 1_000_000_000

    def test_a_duration_never_involves_the_anchor(self):
        """A duration derived from resolved wall instants would reintroduce the
        backward-step hazard the monotonic tick avoids."""
        start = clock.tick()
        end = start + 1_500_000_000
        assert clock.duration_seconds(start, end) == pytest.approx(1.5)

    def test_the_anchor_is_taken_once_at_import(self):
        first = clock.ANCHOR_TICK_NS
        clock.tick()
        assert first == clock.ANCHOR_TICK_NS
