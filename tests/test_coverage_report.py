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

from codess import coverage_report
from codess.config import get_store_path
from codess.coverage_report import (
    loss,
    mapped_coverage,
    source_record_shapes,
    store_coverage,
)
from codess.store import connect, init_db


def _store_with_rules(tmp_path, source_system_id, rules):
    """A store whose Events carry exactly `rules`, for conformance checks."""
    path = get_store_path(tmp_path, "cc")
    init_db(path)
    conn = connect(path)
    if source_system_id is not None:
        insert_session(conn, "s1", source_system_id=source_system_id)
        for index, rule in enumerate(rules):
            insert_event(conn, "s1", str(index), mapping_rule=rule)
    return conn


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
            "(session_id, event_id, granularity, reason_code, created_at) "
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
        assert report["by_granularity"]["field"] == 2
        assert report["record_level_reasons"] == {"unsupported_shape": 1}

    def test_reasons_are_reported_for_both_levels(self, store):
        self._diagnostic(store, level="source", reason="source_unreadable")
        store.commit()
        report = loss(store)
        assert report["by_reason"]["source_unreadable"] == 1
        assert report["unmapped_records"]["source"] == 1

    def test_no_diagnostics(self, store):
        assert loss(store)["by_granularity"] == {}

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


def test_store_coverage_reports_every_section(store):
    """Every section of the report travels with the others.

    A count, its shapes, whether those shapes match the released profile, its
    loss, and the evidence no decoder admits at all.
    """
    add_event(store, "e1", event_kind="tool.call", source_record_type="assistant")
    store.commit()
    report = store_coverage(store)
    assert set(report) == {
        "coverage", "shapes", "conformance", "loss", "undecoded",
    }
    assert report["coverage"]["admitted_events"] == 1
    assert report["shapes"]["by_source_record_type"] == {"assistant": 1}
    assert report["loss"]["available"] is True


class TestUndecodedEvidence:
    """Loss has two shapes and the report used to carry one.

    `loss()` measures what a decoder read and could not fully map. This measures
    evidence a vendor retained that no adapter admits -- which a store cannot
    report, because nothing was written, so a store-derived report states zero by
    construction.
    """

    def test_a_vendor_with_no_measured_container_says_so(self):
        from codess.coverage_report import undecoded_evidence

        result = undecoded_evidence("anthropic.claude-code")
        assert result["available"] is False
        assert result["reason"]

    def test_an_unknown_vendor_is_not_silently_reported_as_clean(self):
        """`available: False` with a reason, never an absent key: a reader must
        be able to tell "measured, none" from "not measured"."""
        from codess.coverage_report import undecoded_evidence

        assert undecoded_evidence(None)["available"] is False

    def test_codex_history_is_reported_not_admitted(self, tmp_path, monkeypatch):
        """A history-only Session is counted, never turned into a Session.

        Admitting one would mean a Session with prompts and no Model Turns,
        which changes what a Session is and is a mapping decision under 6.5.
        """
        import codess.coverage_report as coverage_module

        measured = {
            "available": True, "history_path": "/h/history.jsonl",
            "history_sessions": 19, "with_rollout": 18, "without_rollout": 1,
            "unrolled_prompt_counts": {"0000bbbbbbbbbbbb": 2},
        }
        monkeypatch.setattr(
            "codess.codex_source.unrolled_history_sessions", lambda **_: measured,
        )
        result = coverage_module.undecoded_evidence("openai.codex")
        assert result["available"] is True
        assert result["sessions"] == 19
        assert result["with_rollout"] == 18
        assert result["undecodable_sessions"] == 1
        assert result["undecodable_prompts"] == 2
        assert result["disposition"] == "reported, not admitted"

    def test_an_absent_history_container_is_not_an_error(self, monkeypatch):
        monkeypatch.setattr(
            "codess.codex_source.unrolled_history_sessions",
            lambda **_: {"available": False, "history_path": "/nope"},
        )
        import codess.coverage_report as coverage_module

        assert coverage_module.undecoded_evidence("openai.codex")["available"] is False

    def test_the_measurement_carries_no_prompt_text(self):
        """A coverage figure must be publishable beside a store."""
        from codess.codex_source import unrolled_history_sessions

        measured = unrolled_history_sessions()
        serialized = repr(measured)
        assert "unrolled_prompt_counts" in measured or not measured["available"]
        # Only identifiers and counts; no free text field exists to leak.
        assert set(measured) <= {
            "available", "history_path", "history_sessions", "with_rollout",
            "without_rollout", "unrolled_prompt_counts",
        }, serialized


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
    broken report.
    """
    from codess.coverage_report import _counts_by
    from codess.schema_contract import SchemaContractError

    store = tmp_path / "store.db"
    init_db(store)
    conn = connect(store)
    try:
        with pytest.raises(SchemaContractError, match="no column 'severity_level'"):
            _counts_by(conn, "severity_level")
        assert _counts_by(conn, "granularity") == {}
    finally:
        conn.close()


class TestProfileConformance:
    """The store's rules against the profile's, in both directions.

    `source_record_shapes` reports which rules a store used and the released
    profile declares which exist, but nothing compared them: a rule an adapter
    invented and a rule a contract declares are indistinguishable once stored.
    """

    def test_a_rule_the_profile_does_not_name(self, tmp_path):
        """An adapter emitting an undeclared id is what this exists to find."""
        conn = _store_with_rules(tmp_path, "anthropic.claude-code",
                                 ["claude.message", "claude.invented"])
        result = coverage_report.profile_conformance(conn, "anthropic.claude-code")
        assert result["available"] is True
        assert result["undeclared"] == ["claude.invented"]

    def test_a_declared_rule_no_event_carries(self, tmp_path):
        """Unused is reported, not silently equated with conformance."""
        conn = _store_with_rules(tmp_path, "anthropic.claude-code", ["claude.message"])
        result = coverage_report.profile_conformance(conn, "anthropic.claude-code")
        assert "claude.lineage" in result["unused"]
        assert result["used"] == 1

    def test_an_empty_store_is_not_a_missing_profile(self, tmp_path):
        """Two unavailabilities, distinguishable by their reason.

        A store with no Sessions names no source system. Reporting that as
        "no released profile" would read as a contract gap rather than as an
        empty store, and the two need different responses.
        """
        conn = _store_with_rules(tmp_path, None, [])
        result = coverage_report.profile_conformance(conn, None)
        assert result["available"] is False
        assert "no Sessions" in result["reason"]

    def test_a_superseded_store_is_not_compared(self, tmp_path):
        """A store written under an older contract cannot be judged by today's.

        Its rule ids were declared when it was written and are not now, so
        every one reads as undeclared -- a statement about the store's age
        rather than about any decoder. A store predating the digest column
        records none at all, so an absent digest is superseded rather than
        matching: treating absence as agreement is what let stale stores be
        compared against profiles they never saw.
        """
        conn = _store_with_rules(tmp_path, "anthropic.claude-code", ["claude.message"])
        conn.execute("DELETE FROM store_meta WHERE key='contract_digest'")
        result = coverage_report.profile_conformance(conn, "anthropic.claude-code")
        assert result["available"] is False
        assert "superseded" in result["reason"]
