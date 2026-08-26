"""Reading refresh receipts as Project observations.

This module had no test naming it, and it is the one the corpus baseline reads
its ingest-rate evidence from -- so a wrong reading here becomes a figure
quoted in planning. The decisions worth pinning are which receipt wins when a
Project appears in several, which stage wins within one receipt, and what is
refused rather than read.
"""

from __future__ import annotations

import json
import os

import pytest

from codess.refresh_receipts import (
    REFRESH_RECEIPT_FORMAT,
    latest_refresh_observations,
)


def write_receipt(store_root, name, receipt, *, mtime=None):
    """Write one receipt under the refresh receipts directory, optionally aged."""
    receipts = store_root / "receipts" / "refresh"
    receipts.mkdir(parents=True, exist_ok=True)
    path = receipts / name
    path.write_text(json.dumps(receipt), encoding="utf-8")
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def receipt(project_id, *, stage="apply", status="passed", completed_at=None,
            snapshot_id=None, source="cc"):
    """A minimal receipt in the released format."""
    return {
        "receipt_format": REFRESH_RECEIPT_FORMAT,
        "status": "completed",
        "requested_stage": stage,
        "plan": {"projects": [{"project_id": project_id, "source": source,
                               "raw_mode": "reference"}]},
        stage: [{
            "project_id": project_id,
            "status": status,
            "completed_at": completed_at,
            "returncode": 0 if status == "passed" else 1,
            "ingest_summary": {"snapshot_id": snapshot_id} if snapshot_id else {},
        }],
    }


class TestWhatIsRead:
    """A receipt is admitted only when it states the released format."""

    def test_absent_receipts_directory(self, tmp_path):
        """A store that has never refreshed is not an error."""
        assert latest_refresh_observations(tmp_path) == {}

    def test_foreign_format_refused(self, tmp_path):
        """`receipt_format` is the gate, so an unrelated JSON file is skipped."""
        body = receipt("p1")
        body["receipt_format"] = "something.else/9"
        write_receipt(tmp_path, "a.json", body)
        assert latest_refresh_observations(tmp_path) == {}

    def test_unreadable_json_skipped(self, tmp_path):
        """One corrupt receipt must not hide every other Project's result."""
        receipts = tmp_path / "receipts" / "refresh"
        receipts.mkdir(parents=True)
        (receipts / "bad.json").write_text("{not json", encoding="utf-8")
        write_receipt(tmp_path, "good.json", receipt("p1"))
        assert set(latest_refresh_observations(tmp_path)) == {"p1"}

    def test_status_outside_vocabulary(self, tmp_path):
        """Only `passed` and `failed` map; anything else is not an outcome."""
        write_receipt(tmp_path, "a.json",
                      receipt("p1", status="cancelled"))
        assert latest_refresh_observations(tmp_path) == {}

    def test_nonpositive_limit_rejected(self, tmp_path):
        """Reading zero receipts would report "never refreshed" for everything."""
        with pytest.raises(ValueError):
            latest_refresh_observations(tmp_path, receipt_limit=0)


class TestWhichObservationWins:
    """Several receipts can describe one Project; one of them is current."""

    def test_later_completion_wins(self, tmp_path):
        """Recency is decided by the stated completion, not by file order."""
        write_receipt(tmp_path, "old.json",
                      receipt("p1", completed_at="2026-01-01T00:00:00+00:00",
                              snapshot_id="old"))
        write_receipt(tmp_path, "new.json",
                      receipt("p1", completed_at="2026-06-01T00:00:00+00:00",
                              snapshot_id="new"))
        observed = latest_refresh_observations(tmp_path)
        assert observed["p1"]["snapshot_id"] == "new"

    def test_apply_outranks_preflight(self, tmp_path):
        """Both stages can complete together; apply is the one that changed a store.

        Without the stage rank the winner would depend on iteration order, and
        a Project that was applied would sometimes report only its preflight.
        """
        body = receipt("p1", stage="preflight",
                       completed_at="2026-06-01T00:00:00+00:00")
        body["apply"] = [{
            "project_id": "p1", "status": "passed",
            "completed_at": "2026-06-01T00:00:00+00:00",
            "returncode": 0, "ingest_summary": {"snapshot_id": "applied"},
        }]
        write_receipt(tmp_path, "a.json", body)
        observed = latest_refresh_observations(tmp_path)
        assert observed["p1"]["stage"] == "apply"
        assert observed["p1"]["status"] == "refresh_applied"

    def test_failure_is_observed(self, tmp_path):
        """A failed refresh is what a reader most needs to see."""
        write_receipt(tmp_path, "a.json",
                      receipt("p1", status="failed",
                              completed_at="2026-06-01T00:00:00+00:00"))
        observed = latest_refresh_observations(tmp_path)
        assert observed["p1"]["status"] == "refresh_failed"
        assert observed["p1"]["result_status"] == "failed"

    def test_file_time_fallback(self, tmp_path):
        """A receipt with no stated time still orders, by when it was written."""
        write_receipt(tmp_path, "old.json",
                      receipt("p1", snapshot_id="old"), mtime=1_000_000)
        write_receipt(tmp_path, "new.json",
                      receipt("p1", snapshot_id="new"), mtime=2_000_000)
        observed = latest_refresh_observations(tmp_path)
        assert observed["p1"]["snapshot_id"] == "new"

    def test_projects_observed_independently(self, tmp_path):
        """One receipt covering several Projects yields one row each."""
        body = receipt("p1", completed_at="2026-06-01T00:00:00+00:00")
        body["plan"]["projects"].append({"project_id": "p2", "source": "codex",
                                         "raw_mode": "reference"})
        body["apply"].append({
            "project_id": "p2", "status": "failed",
            "completed_at": "2026-06-01T00:00:00+00:00", "returncode": 1,
            "ingest_summary": {},
        })
        write_receipt(tmp_path, "a.json", body)
        observed = latest_refresh_observations(tmp_path)
        assert observed["p1"]["status"] == "refresh_applied"
        assert observed["p2"]["status"] == "refresh_failed"
        assert observed["p2"]["source"] == "codex"
