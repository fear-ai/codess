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
    loss, the evidence no decoder admits at all, what the projection dropped
    before an Event existed, and the composers no index binds.

    The last two are loss a store cannot report on itself: a field never
    projected leaves no row, and an unattributed composer is excluded from
    ingest by design, so both read as absent-from-the-vendor unless stated.
    """
    add_event(store, "e1", event_kind="tool.call", source_record_type="assistant")
    store.commit()
    report = store_coverage(store)
    assert set(report) == {
        "coverage", "shapes", "conformance", "loss", "undecoded",
        "projection", "unbound", "repeated_prompts",
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


class TestProjectionAndUnboundCoverage:
    """Two shapes of loss a store cannot report on itself.

    `loss()` measures what a decoder read and could not fully map. These
    measure what never reached the decoder: a bubble field the projection drops
    before an Event is built, and a composer no index binds to a Project. Both
    leave no row, so a report derived only from the store states zero by
    construction -- the unfalsifiable zero recorded elsewhere.
    """

    def test_projection_names_the_dropped_field_count(self):
        from codess.coverage_report import projection_coverage

        report = projection_coverage("cursor.composer")
        assert report["available"] is True
        assert report["observed_fields"] > report["projected_fields"]
        assert report["unprojected_fields"] == (
            report["observed_fields"] - report["projected_fields"]
        )

    def test_the_projected_set_is_derived_from_the_decoder(self):
        """Restating it here would let the report drift from what is read."""
        from codess.adapters.cursor import _MAPPED_BUBBLE_FIELDS
        from codess.coverage_report import projection_coverage

        report = projection_coverage("cursor.composer")
        assert set(report["projected"]) == set(_MAPPED_BUBBLE_FIELDS)

    def test_another_vendor_reports_unavailable_rather_than_omitting(self):
        """Unavailable is stated rather than the key being omitted.

        A reader must be able to tell "measured, none" from "not measured".
        """
        from codess.coverage_report import projection_coverage, unbound_composers

        for report in (
            projection_coverage("anthropic.claude-code"),
            unbound_composers("openai.codex"),
        ):
            assert report["available"] is False
            assert report["reason"]

    def test_an_unreadable_container_does_not_fail_the_report(self, tmp_path):
        """A coverage report never fails the query it describes."""
        import sqlite3

        import codess.cursor_source as cursor_source
        from codess import coverage_report

        def _raise(_path):
            raise sqlite3.DatabaseError("unreadable")

        saved = cursor_source.unbound_composer_count
        cursor_source.unbound_composer_count = _raise
        try:
            report = coverage_report.unbound_composers("cursor.composer")
        finally:
            cursor_source.unbound_composer_count = saved
        assert report["available"] is False


class TestRepeatedPrompts:
    """Repetition is the signal, not brevity.

    An earlier version filtered to prompts of 40 characters or fewer. That is
    wrong twice: 40 characters is the 25th percentile of human prompts in this
    corpus, so it is not short; and the most repeated text measured is 8,670
    characters repeated 13 times -- a scripted evaluation run, which a length
    filter hides entirely.
    """

    def _prompt(self, store, event_id, sequence_no, text, event_at,
                session_id="s1"):
        insert_event(
            store, session_id, event_id, event_kind="message.prompt",
            actor_kind="human", content=text, sequence_no=sequence_no,
            event_at=event_at,
        )

    def test_a_consecutive_identical_prompt_is_reported(self, store):
        from codess.coverage_report import repeated_prompts

        self._prompt(store, "e1", 1, "continue", 1_000)
        self._prompt(store, "e2", 2, "continue", 21_000)
        store.commit()
        report = repeated_prompts(store)
        assert report["consecutive"] == 1
        assert report["examples"][0]["gap_ms"] == 20_000

    def test_a_long_repeated_prompt_is_not_filtered_out(self, store):
        """The case a length filter hid: 8,670 characters, repeated."""
        from codess.coverage_report import repeated_prompts

        text = "You are an impartial judge reviewing a conversation. " * 160
        self._prompt(store, "e1", 1, text, 1_000)
        self._prompt(store, "e2", 2, text, 5_000)
        store.commit()
        report = repeated_prompts(store)
        assert report["consecutive"] == 1
        assert report["examples"][0]["chars"] > 8_000

    def test_the_reported_text_is_bounded(self, store):
        """The report states what repeated rather than reproducing it."""
        from codess.coverage_report import repeated_prompts

        text = "x" * 5_000
        self._prompt(store, "e1", 1, text, 1_000)
        self._prompt(store, "e2", 2, text, 2_000)
        store.commit()
        assert len(repeated_prompts(store)["examples"][0]["text"]) <= 80

    def test_a_text_recurring_across_sessions_is_reported_separately(self, store):
        """A scripted run and an operator's `continue` are both worth seeing."""
        from codess.coverage_report import repeated_prompts

        add_session(store, session_id="s2")
        self._prompt(store, "e1", 1, "continue", 1_000, session_id="s1")
        self._prompt(store, "e2", 1, "continue", 2_000, session_id="s2")
        store.commit()
        report = repeated_prompts(store)
        # Different Sessions, so not consecutive; recurring is the right shape.
        assert report["consecutive"] == 0
        assert report["recurring"][0]["sessions"] == 2

    def test_a_distant_repeat_is_outside_the_window(self, store):
        from codess.coverage_report import repeated_prompts

        self._prompt(store, "e1", 1, "continue", 1_000)
        self._prompt(store, "e2", 2, "continue", 6_000_000)
        store.commit()
        report = repeated_prompts(store)
        assert report["consecutive"] == 1
        assert report["within_window"] == 0

    def test_different_prompts_are_not_a_repeat(self, store):
        from codess.coverage_report import repeated_prompts

        self._prompt(store, "e1", 1, "continue", 1_000)
        self._prompt(store, "e2", 2, "go", 2_000)
        store.commit()
        assert repeated_prompts(store)["consecutive"] == 0

    def test_it_does_not_classify_the_cause(self, store):
        from codess.coverage_report import repeated_prompts

        store.commit()
        assert "not classified" in repeated_prompts(store)["disposition"]


class TestPromptFamilies:
    """An exact-keyed group count is a floor, not a family size.

    A templated prompt embeds varying content into a fixed preamble, so one
    scripted run splits into as many exact groups as it has variants. Measured:
    327 prompts of an LLM-judge harness share one opening, hold 6 preambles and
    24 generated transcripts, and reduce to 34 exact texts -- the largest
    holding 13. Reading 13 as the family understates the run 25-fold.
    """

    def _prompt(self, store, event_id, sequence_no, text, session_id="s1"):
        insert_event(
            store, session_id, event_id, event_kind="message.prompt",
            actor_kind="human", content=text, sequence_no=sequence_no,
            event_at=1_000 * sequence_no,
        )

    def _templated(self, store, count):
        """One preamble, a different body per Session -- the observed shape."""
        preamble = "You are an impartial judge reviewing a conversation. " * 6
        for index in range(count):
            # `s1` is the fixture's own Session, so the run starts there and
            # adds the rest rather than recreating it.
            session_id = "s1" if index == 0 else f"fam{index}"
            if index:
                add_session(store, session_id=session_id)
            self._prompt(
                store, f"e{index}", 1,
                preamble + f"[BEGIN TRANSCRIPT] variant {'x' * index}",
                session_id=session_id,
            )
        store.commit()

    def test_a_templated_family_is_reported_at_its_true_size(self, store):
        from codess.coverage_report import repeated_prompts

        self._templated(store, 8)
        report = repeated_prompts(store)
        family = report["families"][0]
        assert family["sessions"] == 8
        assert family["exact_texts"] == 8

    def test_the_exact_grouping_would_have_reported_nothing(self, store):
        """Every text is distinct, so exact keying sees no repetition at all.

        This is the failure the roll-up exists for: the family is invisible to
        the grouping that reports honestly on each of its fragments.
        """
        from codess.coverage_report import repeated_prompts

        self._templated(store, 8)
        report = repeated_prompts(store)
        assert report["recurring"] == []
        assert report["families"][0]["sessions"] == 8

    def test_a_length_span_proves_the_family_is_larger(self, store):
        """Identical texts cannot have different lengths.

        `varies_by_length` is a check rather than a heuristic: a span inside
        one opening means the exact grouping split a family.
        """
        from codess.coverage_report import repeated_prompts

        self._templated(store, 5)
        family = repeated_prompts(store)["families"][0]
        assert family["varies_by_length"] is True
        assert family["chars_min"] < family["chars_max"]

    def test_one_repeated_text_does_not_vary_by_length(self, store):
        """The negative case, which is what makes the flag falsifiable."""
        from codess.coverage_report import repeated_prompts

        add_session(store, session_id="s2")
        self._prompt(store, "e1", 1, "continue", session_id="s1")
        self._prompt(store, "e2", 1, "continue", session_id="s2")
        store.commit()
        family = repeated_prompts(store)["families"][0]
        assert family["varies_by_length"] is False
        assert family["chars_min"] == family["chars_max"]

    def test_unrelated_prompts_form_no_family(self, store):
        from codess.coverage_report import repeated_prompts

        add_session(store, session_id="s2")
        self._prompt(store, "e1", 1, "review the parser changes", session_id="s1")
        self._prompt(store, "e2", 1, "write the migration guide", session_id="s2")
        store.commit()
        assert repeated_prompts(store)["families"] == []

    def test_the_prefix_length_is_not_configurable(self):
        """One corpus and one observed family cannot inform a setting.

        W84's precedent: a vocabulary guessed from a single value is worse than
        none.
        """
        from codess import coverage_report
        from codess.settings import BY_NAME

        assert coverage_report.FAMILY_PREFIX_CHARS == 200
        assert not any("prefix" in name for name in BY_NAME)
