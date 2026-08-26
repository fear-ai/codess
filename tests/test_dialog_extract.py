"""Extraction of human/model exchanges, and the exclusions it must state.

The SQL is easy; deciding what is a human prompt is the work. A Claude `user`
record can carry a tool result, a context injection, or a task notification, and
a scripted run looks like a Session until `surface_kind` says otherwise.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parent.parent / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from dialog_extract import (  # noqa: E402
    DEFAULT_BOUT_GAP_MS,
    MIN_TASK_CHARS,
    _is_status_only,
    parse_since,
)


class TestStatusOnlyPrompts:
    """A resume word is input without a request.

    `continue` is excluded from the default dataset and counted, because "the
    operator said continue" differs from "no prompt".
    """

    @pytest.mark.parametrize("text", ["continue", "go", "  Continue.  ", "ok", "ls"])
    def test_a_resume_word_is_status_only(self, text):
        assert _is_status_only(text)

    def test_a_stated_task_is_not(self):
        assert not _is_status_only("read the parser and fix the off-by-one")

    def test_the_minimum_is_short_enough_to_keep_real_work(self):
        """The floor keeps ordinary work.

        40 characters was tried and is the 25th percentile of real prompts, so
        it removed real requests.
        """
        assert MIN_TASK_CHARS < 20
        assert not _is_status_only("fix the failing test")


class TestSinceWindow:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [("1h", 3_600_000), ("2d", 172_800_000), ("1w", 604_800_000)],
    )
    def test_it_parses_a_relative_window(self, value, expected):
        assert parse_since(value) == expected

    def test_no_window_means_all_time(self):
        assert parse_since(None) is None

    def test_a_calendar_date_is_refused(self):
        """A date in a saved command goes stale silently."""
        with pytest.raises(ValueError, match="30d"):
            parse_since("2026-01-01")


class TestExtraction:
    def _store(self, tmp_path, events, surface="cli"):
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
            project_path="/p", started_at=1000.0, surface_kind=surface,
        )
        for index, event in enumerate(events, 1):
            insert_event(conn, "s1", f"e{index}", sequence_no=index, **event)
        conn.commit()
        conn.close()
        (projects / "current.json").write_text(
            json.dumps({"path": str(snapshot)}), encoding="utf-8",
        )
        return tmp_path

    def test_a_prompt_pairs_with_the_replies_that_follow(self, tmp_path):
        from dialog_extract import extract

        root = self._store(tmp_path, [
            {"event_kind": "message.prompt", "actor_kind": "human",
             "content": "explain the parser", "event_at": 1000.0},
            {"event_kind": "message.response", "actor_kind": "model",
             "content": "first", "event_at": 2000.0},
            {"event_kind": "message.response", "actor_kind": "model",
             "content": "second", "event_at": 3000.0},
        ])
        rows, counts = extract(root)
        assert len(rows) == 1
        assert rows[0]["replies"] == 2
        assert counts["excluded_status_only"] == 0

    def test_harness_traffic_in_a_user_envelope_is_excluded(self, tmp_path):
        """Classification decides this, not a guess about the content."""
        from dialog_extract import extract

        root = self._store(tmp_path, [
            {"event_kind": "message.prompt", "actor_kind": "harness",
             "content": "<injected context>", "event_at": 1000.0},
        ])
        rows, counts = extract(root)
        assert rows == []
        assert counts["excluded_not_human"] == 1

    def test_a_scripted_surface_is_excluded_by_default(self, tmp_path):
        """`api` on Claude is `entrypoint: sdk-cli`, a programmatic run."""
        from dialog_extract import extract

        root = self._store(tmp_path, [
            {"event_kind": "message.prompt", "actor_kind": "human",
             "content": "score this transcript", "event_at": 1000.0},
        ], surface="api")
        assert extract(root)[0] == []
        assert len(extract(root, surface="any")[0]) == 1

    def test_a_long_gap_starts_a_new_bout(self, tmp_path):
        """A Session spans days; a bout is a sitting."""
        from dialog_extract import extract

        root = self._store(tmp_path, [
            {"event_kind": "message.prompt", "actor_kind": "human",
             "content": "first real task here", "event_at": 1000.0},
            {"event_kind": "message.prompt", "actor_kind": "human",
             "content": "second real task here",
             "event_at": 1000.0 + DEFAULT_BOUT_GAP_MS * 2},
        ])
        rows, _counts = extract(root)
        assert [row["bout"] for row in rows] == [0, 1]

    def test_a_close_gap_stays_in_one_bout(self, tmp_path):
        from dialog_extract import extract

        root = self._store(tmp_path, [
            {"event_kind": "message.prompt", "actor_kind": "human",
             "content": "first real task here", "event_at": 1000.0},
            {"event_kind": "message.prompt", "actor_kind": "human",
             "content": "second real task here", "event_at": 60_000.0},
        ])
        rows, _counts = extract(root)
        assert [row["bout"] for row in rows] == [0, 0]

    def test_every_row_states_that_the_pairing_is_derived(self, tmp_path):
        """Sequence is evidence of order; adjacency is not proof of causality."""
        from dialog_extract import extract

        root = self._store(tmp_path, [
            {"event_kind": "message.prompt", "actor_kind": "human",
             "content": "a real stated task", "event_at": 1000.0},
        ])
        assert extract(root)[0][0]["pairing"] == "derived_from_sequence"


class TestReport:
    def _rows(self, count=6):
        return [
            {
                "record": "exchange", "project_id": "p", "vendor": "anthropic.claude-code",
                "surface": "cli", "session_id": "s1", "bout": index // 3,
                "sequence_no": index, "prompt_at": 1000 * index,
                "prompt": "task", "prompt_chars": 50 * (index + 1),
                "replies": index % 4, "reply_chars": 900, "reply": "ok",
                "pairing": "derived_from_sequence",
            }
            for index in range(count)
        ]

    def test_it_analyzes_without_opening_a_store(self, tmp_path):
        """The split is the point: step two reads a file, never SQL."""
        from dialog_report import analyze, load

        path = tmp_path / "d.jsonl"
        path.write_text(
            json.dumps({"record": "header", "surface": "cli"}) + "\n"
            + "\n".join(json.dumps(row) for row in self._rows()) + "\n",
            encoding="utf-8",
        )
        rows, header = load(path)
        report = analyze(rows)
        assert header["surface"] == "cli"
        assert report["exchanges"] == 6
        assert report["bouts"] == 2

    def test_it_reports_percentiles_not_means(self, tmp_path):
        """Each of these is heavy-tailed; a mean resembles no exchange."""
        from dialog_report import analyze

        report = analyze(self._rows(20))
        assert {"p25", "p50", "p75", "p95", "max"} <= set(report["prompt_chars"])
        assert "mean" not in report["prompt_chars"]

    def test_the_page_states_the_population_it_measured(self, tmp_path):
        from dialog_report import analyze, render

        header = {
            "surface": "cli", "since": "30d", "excluded_status_only": 7,
            "excluded_not_human": 3, "bout_gap_minutes": 60,
        }
        page = render(analyze(self._rows()), header)
        assert "30d" in page
        assert "7 status-only" in page
        assert "http" not in page
