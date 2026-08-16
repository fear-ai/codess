"""Coverage, shape, and loss reporting over one store.

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

    def test_zero_record_loss_is_distinguished_from_unmeasured(self, store):
        """A zero must not read as evidence when nothing writes the level.

        Only `field` diagnostics are constructed today -- 38,092 rows across
        every real store and none at the other two levels -- so a reported
        zero for record loss means "not recorded", not "did not happen". The report
        says which.
        """
        self._diagnostic(store, level="field", reason="field_absent")
        store.commit()
        assert loss(store)["record_loss_recorded"] is False

        self._diagnostic(store, level="record", reason="unsupported_shape")
        store.commit()
        assert loss(store)["record_loss_recorded"] is True


def test_store_coverage_reports_all_three(store):
    """The three sections travel together: a count, its shapes, and its loss."""
    add_event(store, "e1", event_kind="tool.call", source_record_type="assistant")
    store.commit()
    report = store_coverage(store)
    assert set(report) == {"coverage", "shapes", "loss"}
    assert report["coverage"]["admitted_events"] == 1
    assert report["shapes"]["by_source_record_type"] == {"assistant": 1}
    assert report["loss"]["available"] is True


class TestEventAtBasis:
    """The basis states where an instant came from, so it needs an instant.

    `event_at_basis` defaulted to `vendor` whenever unset, asserting vendor
    provenance for 14,031 real Events that had no vendor timestamp -- the one
    claim this column exists to prevent. The value survey found it because
    the column held one constant across every store and vendor.
    """

    def _upsert(self, store, **event):
        """Through `upsert_event`, which is where the basis is decided.

        `store_fixtures.insert_event` writes the row directly, so it cannot
        exercise this -- the defect lived in the writer, not the schema.
        """
        from codess.store import upsert_event

        upsert_event(store, {
            "session_id": "s1", "source_id": None, "event_type": "user_message",
            **event,
        })
        store.commit()

    def test_vendor_basis_requires_a_vendor_instant(self, store):
        self._upsert(store, event_id="e1", timestamp=1000.0)
        self._upsert(store, event_id="e2")  # no vendor instant
        assert dict(
            store.execute("SELECT event_at_basis, COUNT(*) FROM events GROUP BY 1")
        ) == {"vendor": 1, "unknown": 1}

    def test_an_explicit_basis_is_kept(self, store):
        self._upsert(store, event_id="e1", timestamp=1000.0, event_at_basis="session")
        assert store.execute(
            "SELECT event_at_basis FROM events"
        ).fetchone()[0] == "session"


def test_a_column_the_store_lacks_fails_naming_it(tmp_path):
    """A renamed column fails loudly rather than reporting nothing.

    `_counts_by` interpolates a column name, so a rename that reached the DDL
    but not this report would otherwise produce a query matching no rows --
    an empty coverage section that reads as "no diagnostics" rather than as a
    broken report (CoPlan W52 step 2).
    """
    from codess.coverage_report import _counts_by
    from codess.schema_contract import SchemaContractError

    store = tmp_path / "store.db"
    init_db(store)
    conn = connect(store)
    try:
        with pytest.raises(SchemaContractError, match="no column 'severity_level'"):
            _counts_by(conn, "severity_level")
        assert _counts_by(conn, "level") == {}
    finally:
        conn.close()
