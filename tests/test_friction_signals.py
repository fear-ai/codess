"""Preliminary friction signals, and the limits stated on each.

The counting is trivial; the discipline is refusing to call a count a finding.
Every assertion here is about a boundary -- what the pattern must not match,
what a rate may not be compared against, what a low count does not mean.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parent.parent / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from friction_signals import (  # noqa: E402
    CORRECTIVE,
    INTERRUPTED,
    MIN_PROMPTS,
    collect,
)


class TestCorrectivePattern:
    """Anchored to the opening, because a correction that matters is stated first."""

    @pytest.mark.parametrize("text", [
        "no, that is not what I asked",
        "wrong - public documents do not link to internal ones",
        "not done testing, not even close",
        "revert that change",
        "undo changes, I was only kidding",
        "you missed the second file",
    ])
    def test_it_matches_a_correction_at_the_opening(self, text):
        assert CORRECTIVE.match(text)

    @pytest.mark.parametrize("text", [
        "add a check so there is no crash when the file is absent",
        "the parser has no tests yet, please add some",
        "document why we do not follow symlinks",
    ])
    def test_it_does_not_match_a_negation_inside_ordinary_prose(self, text):
        """Unanchored, this would report a rate near 100%."""
        assert not CORRECTIVE.match(text)

    def test_the_interrupt_marker_is_vendor_stated(self):
        """The strongest signal here, because the harness writes it verbatim."""
        assert INTERRUPTED.search("[Request interrupted by user]")
        assert not INTERRUPTED.search("please interrupt the loop on error")


class TestRatesAreGuarded:
    def _store(self, tmp_path, prompts):
        from store_fixtures import insert_event, insert_session

        from codess.store import connect, init_db

        projects = tmp_path / "projects" / "p1"
        snapshot = projects / "snap"
        snapshot.mkdir(parents=True)
        database = snapshot / "sessions_cc.db"
        init_db(database)
        conn = connect(database)
        insert_session(
            conn, "s1", source="Claude", vendor_session_id="v1",
            project_path="/p", started_at=1000.0,
        )
        for index, text in enumerate(prompts, 1):
            insert_event(
                conn, "s1", f"e{index}", sequence_no=index,
                event_kind="message.prompt", actor_kind="human", content=text,
            )
        conn.commit()
        conn.close()
        (projects / "current.json").write_text(
            json.dumps({"path": str(snapshot)}), encoding="utf-8",
        )
        return tmp_path

    def test_a_project_below_the_floor_is_omitted(self, tmp_path):
        """One correction in twenty prompts is 5% and means nothing."""
        root = self._store(tmp_path, ["no, wrong"] + ["do the thing"] * 5)
        assert collect(root) == []

    def test_a_project_above_the_floor_reports_a_rate(self, tmp_path):
        root = self._store(
            tmp_path, ["no, wrong"] * 5 + ["do the thing"] * MIN_PROMPTS,
        )
        rows = collect(root)
        assert len(rows) == 1
        assert rows[0]["corrective"] == 5
        assert 0 < rows[0]["corrective_rate"] < 1

    def test_examples_are_withheld_unless_asked(self, tmp_path):
        """Prompt text is content; a count is not."""
        root = self._store(tmp_path, ["no, wrong"] * MIN_PROMPTS)
        assert collect(root)[0]["examples"] == []
        assert collect(root, keep_examples=True)[0]["examples"]

    def test_an_interrupt_is_not_also_counted_as_corrective(self, tmp_path):
        """One prompt is one observation, under whichever signal fits."""
        root = self._store(
            tmp_path,
            ["[Request interrupted by user]"] * 3 + ["do the thing"] * MIN_PROMPTS,
        )
        row = collect(root)[0]
        assert row["interrupted"] == 3
        assert row["corrective"] == 0
