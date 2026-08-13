"""Coverage, shape, and loss reporting over one store (W12).

The report answers what an ingest *missed*, which the run-time diagnostic
counters could not: they printed to stderr and were discarded, so nothing
could be queried later or compared between runs. These cover the properties
that make the report usable as evidence -- that classified and unclassified
partition the admitted Events, that record-level loss is not conflated with
field-level incompleteness, and that a store with nothing in it reports
nothing rather than dividing by zero.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from store_fixtures import insert_event, insert_session

from codess.config import get_store_path
from codess.coverage_report import (
    loss,
    mapped_coverage,
    source_record_shapes,
    store_coverage,
)
from codess.store import connect, init_db


def make_store(tmp_path: Path, name: str = "Claude") -> Path:
    store_path = get_store_path(tmp_path, name)
    init_db(store_path)
    return store_path


def add_session(conn, session_id="s1"):
    return insert_session(
        conn, session_id, source="Claude", vendor_session_id=f"v-{session_id}",
        project_path="/projects/p", started_at=1000.0,
    )


def add_event(conn, event_id, **columns):
    return insert_event(conn, "s1", event_id, **columns)


@pytest.fixture
def store(tmp_path):
    conn = connect(make_store(tmp_path))
    add_session(conn)
    conn.commit()
    yield conn
    conn.close()


class TestMappedCoverage:
    def test_empty_store(self, store):
        """No Events, so no ratio -- reported as unknown, not as zero or one."""
        assert mapped_coverage(store) == {
            "admitted_events": 0,
            "unclassified_events": 0,
            "classified_events": 0,
            "classified_ratio": None,
        }

    def test_fully_classified(self, store):
        for index in range(4):
            add_event(
                store, f"e{index}", event_kind="tool.call", actor_kind="model",
                content_role="tool_request", origin_kind="model_generated",
            )
        store.commit()
        coverage = mapped_coverage(store)
        assert coverage["admitted_events"] == 4
        assert coverage["classified_events"] == 4
        assert coverage["classified_ratio"] == 1.0

    def test_partial_classification(self, store):
        """An Event missing any one dimension counts as unclassified.

        Not "missing all four": a record Codess stored while unable to say
        what it is has not been mapped, and reporting it as covered because
        three of four dimensions resolved would overstate coverage.
        """
        add_event(
            store, "e1", event_kind="tool.call", actor_kind="model",
            content_role="tool_request", origin_kind="model_generated",
        )
        add_event(
            store, "e2", event_kind="tool.call", actor_kind="model",
            content_role="tool_request",  # origin_kind absent
        )
        store.commit()
        coverage = mapped_coverage(store)
        assert coverage["classified_events"] == 1
        assert coverage["unclassified_events"] == 1
        assert coverage["classified_ratio"] == 0.5

    def test_counts_partition_the_admitted(self, store):
        """classified + unclassified == admitted, so a ratio is recomputable."""
        for index in range(3):
            add_event(store, f"e{index}", event_kind="tool.call")
        store.commit()
        coverage = mapped_coverage(store)
        assert (
            coverage["classified_events"] + coverage["unclassified_events"]
            == coverage["admitted_events"]
        )


class TestSourceRecordShapes:
    def test_counts_by_record_type_and_rule(self, store):
        add_event(store, "e1", source_record_type="assistant", mapping_rule="claude.message")
        add_event(store, "e2", source_record_type="assistant", mapping_rule="claude.message")
        add_event(store, "e3", source_record_type="attachment", mapping_rule="claude.product-state")
        store.commit()
        shapes = source_record_shapes(store)
        assert shapes["by_source_record_type"] == {"assistant": 2, "attachment": 1}
        assert shapes["by_mapping_rule"]["claude.message"] == 2

    def test_absent_type_is_named_not_dropped(self, store):
        """A record whose type Codess could not name is the finding."""
        add_event(store, "e1", source_record_type=None)
        store.commit()
        assert source_record_shapes(store)["by_source_record_type"] == {"[none]": 1}


class TestLoss:
    def _diagnostic(self, conn, *, level, reason):
        conn.execute(
            "INSERT INTO mapping_diagnostics"
            "(session_id, event_id, level, reason_code, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("s1", None, level, reason, "2026-01-01T00:00:00Z"),
        )

    def test_field_and_record_loss_are_not_summed(self, store):
        """A missing field is not a missing record.

        Adding them would report a Project as lossier than it is: a field
        diagnostic means an Event exists with a value absent, while a record
        diagnostic means no Event exists at all.
        """
        self._diagnostic(store, level="field", reason="field_absent")
        self._diagnostic(store, level="field", reason="field_absent")
        self._diagnostic(store, level="record", reason="unsupported_shape")
        store.commit()
        report = loss(store)
        assert report["unmapped_records"] == {"source": 0, "record": 1}
        assert report["by_level"]["field"] == 2
        assert report["record_level_reasons"] == {"unsupported_shape": 1}

    def test_reasons_are_reported_for_both_levels(self, store):
        self._diagnostic(store, level="source", reason="source_unreadable")
        store.commit()
        report = loss(store)
        assert report["by_reason"]["source_unreadable"] == 1
        assert report["unmapped_records"]["source"] == 1

    def test_no_diagnostics(self, store):
        assert loss(store)["by_level"] == {}


def test_store_coverage_reports_all_three(store):
    """The three sections travel together: a count, its shapes, and its loss."""
    add_event(store, "e1", event_kind="tool.call", source_record_type="assistant")
    store.commit()
    report = store_coverage(store)
    assert set(report) == {"coverage", "shapes", "loss"}
    assert report["coverage"]["admitted_events"] == 1
    assert report["shapes"]["by_source_record_type"] == {"assistant": 1}
    assert report["loss"]["available"] is True
