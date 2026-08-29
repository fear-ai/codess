"""Daily activity timeline, and the encoding decisions it rests on."""

from __future__ import annotations

import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from timeline_report import FALLBACK_RAMP, _step, render  # noqa: E402


class TestStep:
    """Magnitude within a row, scaled to that row's peak.

    Proportional rather than absolute so a quiet Project stays legible; the
    tooltip carries the count, so a step is never read as a value.
    """

    def test_no_activity_has_no_colour(self):
        """An empty day must read as absence, not as a small value."""
        assert _step(0, 100, FALLBACK_RAMP) == ""

    def test_the_peak_lands_on_the_darkest_step(self):
        assert _step(100, 100, FALLBACK_RAMP) == FALLBACK_RAMP[-1]

    def test_a_small_count_lands_on_the_lightest_step(self):
        assert _step(1, 1000, FALLBACK_RAMP) == FALLBACK_RAMP[0]

    def test_steps_are_monotonic_in_count(self):
        ramp_positions = [
            FALLBACK_RAMP.index(_step(count, 100, FALLBACK_RAMP))
            for count in (2, 15, 40, 60, 95)
        ]
        assert ramp_positions == sorted(ramp_positions)


class TestRender:
    def _days(self):
        return {
            "2026-07-13": {"openai.codex": {"events": 900, "sessions": 1}},
            "2026-07-14": {"openai.codex": {"events": 300, "sessions": 1}},
            "2026-07-20": {"anthropic.claude-code": {"events": 400, "sessions": 1}},
            "2026-07-21": {
                "anthropic.claude-code": {"events": 100, "sessions": 1},
                "openai.codex": {"events": 50, "sessions": 1},
            },
        }

    def test_it_counts_shared_days(self):
        """The question the timeline exists to answer."""
        page = render("P", self._days(), {})
        assert "Shared days" in page
        assert ">1<" in page

    def test_separation_is_reported_as_a_share_of_active_days(self):
        page = render("P", self._days(), {})
        # Three of four active days had a single vendor.
        assert "75%" in page

    def test_a_gap_day_renders_as_empty_not_as_zero(self):
        """A line chart would slope across the gap and imply a decline."""
        page = render("P", self._days(), {})
        assert "no activity" in page
        assert "cell empty" in page

    def test_commits_appear_as_their_own_row(self):
        page = render("P", self._days(), {"2026-07-13": 3})
        assert "Commits" in page
        assert "3 commits" in page

    def test_no_activity_renders_a_page_rather_than_failing(self):
        assert "No dated activity" in render("P", {}, {})

    def test_the_page_is_self_contained(self):
        page = render("P", self._days(), {})
        assert page.startswith("<!DOCTYPE html>")
        assert "http://" not in page and "https://" not in page

    def test_dark_mode_is_declared_under_both_scopes(self):
        page = render("P", self._days(), {})
        assert "prefers-color-scheme: dark" in page
        assert '[data-theme="dark"]' in page

    def test_every_cell_carries_an_accessible_label(self):
        """Colour alone never carries the value."""
        page = render("P", self._days(), {})
        assert 'role="img"' in page
        assert "aria-label=" in page
