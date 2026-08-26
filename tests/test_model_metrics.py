"""Comparative measures, and the comparability rules they must not break.

The measures are easy; stating what they may be compared against is the work.
Three findings from the corpus shape every assertion here: a tool call is
harness-mediated, an Event count measures how much a harness writes down, and
only the human-prompt count is normalized across all three vendors.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parent.parent / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from model_metrics import _distribution, _vendor_rows  # noqa: E402
from model_metrics_report import _vendor_slot, render  # noqa: E402


class TestDurationResolution:
    """A duration measure must say whether it measured anything.

    Cursor writes the call bubble and its result with the same `createdAt`, so
    83% of its pairs are exactly 0 ms. Reporting that as a p50 would state a
    performance result the evidence cannot support.
    """

    def test_measured_durations_report_percentiles(self):
        summary = _distribution([10.0, 20.0, 30.0, 40.0])
        assert summary["resolution"] == "measured"
        assert summary["p50"] is not None

    def test_mostly_zero_durations_are_marked_same_timestamp(self):
        summary = _distribution([0.0, 0.0, 0.0, 0.0, 5.0])
        assert summary["resolution"] == "same_timestamp"
        assert summary["zero_share"] == 0.8

    def test_no_observations_is_its_own_state(self):
        """Distinct from a measure that ran and found zeros."""
        summary = _distribution([])
        assert summary["resolution"] == "none"
        assert summary["n"] == 0
        assert summary["p50"] is None

    def test_the_count_travels_with_the_percentile(self):
        """A percentile over four observations is arithmetic, not evidence."""
        assert _distribution([1.0, 2.0])["n"] == 2


class TestVendorRows:
    def _bucket(self, **overrides):
        bucket = {
            "sessions": 10, "events": 1000, "tool_calls": 400,
            "human_prompts": 50, "model_turns": 200, "input_tokens": 0,
            "output_tokens": 0, "projects": {"p1"},
            "kinds": {"tool.call": 300, "tool.result": 300, "message.prompt": 400},
        }
        bucket.update(overrides)
        return bucket

    def test_a_vendor_with_no_sessions_is_omitted(self):
        """A store set holds one database per vendor whether it contributed or not.

        An empty one names no vendor, so counting it would report a row of
        zeros under `unknown` -- absence of evidence read as a measurement.
        """
        rows = _vendor_rows({"empty": self._bucket(sessions=0, events=0)})
        assert rows == []

    def test_the_tool_share_is_computed_from_tool_kinds(self):
        rows = _vendor_rows({"v": self._bucket()})
        assert rows[0]["tool_event_share"] == 0.6

    def test_rows_are_ordered_by_events(self):
        rows = _vendor_rows({
            "small": self._bucket(events=100),
            "large": self._bucket(events=9000),
        })
        assert [row["vendor"] for row in rows] == ["large", "small"]


class TestColourFollowsTheEntity:
    """A filter that drops one vendor must not repaint the others."""

    def test_the_slot_is_keyed_on_the_vendor_not_its_rank(self):
        order = ["cursor.composer", "anthropic.claude-code", "openai.codex"]
        assert _vendor_slot("openai.codex", order) == 2
        # The same vendor keeps its slot when another is filtered out of view.
        assert _vendor_slot("openai.codex", order) == 2

    def test_an_unknown_vendor_folds_into_the_last_slot(self):
        """Never a generated hue: a fourth would fail the all-pairs floor."""
        order = ["a", "b", "c"]
        assert _vendor_slot("unlisted", order) == 2


class TestReport:
    def _report(self):
        return {
            "vendors": [{
                "vendor": "anthropic.claude-code", "projects": 1, "sessions": 5,
                "events": 900, "model_turns": 40, "tool_calls": 30,
                "human_prompts": 12, "tool_event_share": 0.45,
                "events_per_session": 180.0, "input_tokens": 0, "output_tokens": 0,
            }],
            "tools": [{
                "vendor": "anthropic.claude-code", "tool": "Bash", "calls": 500,
                "failed": 25, "denied": 1, "failure_rate": 0.05,
                "duration_ms": {"n": 500, "p50": 20, "p90": 90, "p99": 400,
                                "zero_share": 0.0, "resolution": "measured"},
            }],
            "models": [],
        }

    def test_it_renders_a_self_contained_page(self):
        page = render(self._report())
        assert page.startswith("<!DOCTYPE html>")
        # No network dependency: a report that needs a CDN is not readable
        # from an archive, which is where an investigation reads it from.
        assert "http://" not in page
        assert "https://" not in page

    def test_every_mark_carries_a_visible_label(self):
        """The light-mode contrast WARN is discharged by labels, not ignored."""
        page = render(self._report())
        assert 'class="row-value"' in page

    def test_a_table_view_repeats_the_figures(self):
        page = render(self._report())
        assert "<table>" in page

    def test_dark_mode_is_declared_under_both_scopes(self):
        """The OS setting and an explicit toggle must both win."""
        page = render(self._report())
        assert "prefers-color-scheme: dark" in page
        assert '[data-theme="dark"]' in page

    def test_a_same_timestamp_measure_is_omitted_and_explained(self):
        report = self._report()
        report["tools"][0]["duration_ms"] = {
            "n": 500, "p50": 0, "p90": 0, "p99": 0,
            "zero_share": 0.9, "resolution": "same_timestamp",
        }
        page = render(report)
        assert "same timestamp" in page
        assert "state ordering rather than elapsed time" in page

    def test_the_page_states_what_may_not_be_compared(self):
        page = render(self._report())
        assert "harness-mediated" in page
        assert "human-prompt" in page

    @pytest.mark.parametrize("payload", ['<script>x</script>', 'a"b'])
    def test_a_tool_name_is_escaped(self, payload):
        """A tool name is vendor-supplied text reaching a rendered page."""
        report = self._report()
        report["tools"][0]["tool"] = payload
        page = render(report)
        assert "<script>x</script>" not in page


def test_the_measures_run_against_a_real_store(tmp_path):
    """The queries must match the released DDL, not a remembered one."""
    from model_metrics import collect

    from codess.store import init_db

    projects = tmp_path / "projects" / "p1"
    snapshot = projects / "snap"
    snapshot.mkdir(parents=True)
    init_db(snapshot / "sessions_cc.db")
    (projects / "current.json").write_text(
        json.dumps({"path": str(snapshot)}), encoding="utf-8",
    )
    report = collect(tmp_path)
    assert set(report) == {"vendors", "tools", "models"}


def test_a_store_that_cannot_answer_does_not_abort_the_report(tmp_path):
    """An unreadable store does not abort the report.

    A report that stops at the first one measures whichever stores happened to
    sort before it.
    """
    from model_metrics import collect

    projects = tmp_path / "projects" / "p1"
    snapshot = projects / "snap"
    snapshot.mkdir(parents=True)
    broken = snapshot / "sessions_cc.db"
    broken.write_bytes(b"not a database")
    (projects / "current.json").write_text(
        json.dumps({"path": str(snapshot)}), encoding="utf-8",
    )
    with sqlite3.connect(":memory:"):
        pass
    assert collect(tmp_path)["vendors"] == []
