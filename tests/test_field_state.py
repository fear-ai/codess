"""A16 / D18: universal field-state classification prototype."""

from __future__ import annotations

from codess import field_state as fs


def test_specific_states():
    assert fs.classify(fs._MISSING) == fs.ABSENT
    assert fs.classify(None) == fs.NULL
    assert fs.classify("") == fs.EMPTY
    assert fs.classify("   ") == fs.EMPTY
    assert fs.classify([]) == fs.EMPTY
    assert fs.classify({}) == fs.EMPTY
    assert fs.classify("N/A") == fs.SENTINEL
    assert fs.classify("  unknown ") == fs.SENTINEL
    assert fs.classify("real value") == fs.PRESENT
    assert fs.classify(0) == fs.PRESENT          # zero is a value, not vacant
    assert fs.classify(False) == fs.PRESENT      # false is a value
    assert fs.classify(["x"]) == fs.PRESENT


def test_get_state_distinguishes_absent_from_null():
    assert fs.get_state({}, "k") == (None, fs.ABSENT)
    assert fs.get_state({"k": None}, "k") == (None, fs.NULL)
    assert fs.get_state({"k": "v"}, "k") == ("v", fs.PRESENT)


def test_vacant_umbrella_covers_absent_family_but_not_malformed():
    for state in (fs.ABSENT, fs.EMPTY, fs.NULL, fs.SENTINEL):
        assert fs.is_vacant(state)
    assert not fs.is_vacant(fs.PRESENT)
    assert not fs.is_vacant(fs.MALFORMED)  # malformed is a warning, not absence


def test_diagnostic_levels():
    assert fs.diagnostic_level(fs.PRESENT) is None
    assert fs.diagnostic_level(fs.ABSENT) == "info"
    assert fs.diagnostic_level(fs.SENTINEL) == "info"
    assert fs.diagnostic_level(fs.MALFORMED) == "warn"


def test_diagnose_records_and_never_raises():
    opts = {"diagnostics": {}, "field_diagnostics": []}
    fs.diagnose(opts, field="model", state=fs.ABSENT,
                source_field="message.model")
    fs.diagnose(opts, field="ts", state=fs.MALFORMED,
                source_field="timestamp", value="not-a-date")
    fs.diagnose(opts, field="ok", state=fs.PRESENT, source_field="x")  # no-op

    assert opts["diagnostics"] == {"field_absent": 1, "field_malformed": 1}
    rows = opts["field_diagnostics"]
    assert len(rows) == 2
    assert rows[0]["level"] == "info" and rows[0]["reason_code"] == "field_absent"
    assert rows[1]["level"] == "warn" and rows[1]["detail"] is None  # malformed value not echoed


def test_coarse_collapses_to_present_vacant_but_keeps_malformed():
    assert fs.coarse(fs.PRESENT) == fs.PRESENT
    for state in (fs.ABSENT, fs.EMPTY, fs.NULL, fs.SENTINEL):
        assert fs.coarse(state) == fs.VACANT
    assert fs.coarse(fs.MALFORMED) == fs.MALFORMED  # neither present nor vacant


def test_criticality_is_the_shared_a14_a16_partition():
    # present: nothing to weigh.
    assert fs.criticality(fs.PRESENT, is_critical_field=True) is None
    # vacant/malformed on a critical (identity/order/lineage) field blocks.
    assert fs.criticality(fs.VACANT, is_critical_field=True) == fs.FATAL
    assert fs.criticality(fs.MALFORMED, is_critical_field=True) == fs.FATAL
    assert fs.criticality(fs.ABSENT, is_critical_field=True) == fs.FATAL
    # the same states on a non-critical field are advisory, never fatal.
    assert fs.criticality(fs.VACANT, is_critical_field=False) == fs.ADVISORY
    assert fs.criticality(fs.MALFORMED, is_critical_field=False) == fs.ADVISORY


def test_compare_two_present_values():
    assert fs.compare("x", "x") == fs.MATCH        # both present, equal
    assert fs.compare("x", "y") == fs.MISMATCH     # both present, differ
    assert fs.compare(1, 1) == fs.MATCH
    assert fs.compare(1, 2) == fs.MISMATCH


def test_compare_vacant_takes_precedence_over_mismatch():
    # A side that is not a real value -> vacant, NEVER mismatch, even though the
    # two values technically differ.
    assert fs.compare(None, "y") == fs.VACANT      # would-be-mismatch, but vacant
    assert fs.compare("x", None) == fs.VACANT
    assert fs.compare("", "y") == fs.VACANT        # empty side
    assert fs.compare("N/A", "y") == fs.VACANT     # sentinel side
    assert fs.compare(None, None) == fs.VACANT     # both vacant
    # Only two real, differing values is a mismatch.
    assert fs.compare("real1", "real2") == fs.MISMATCH


def test_never_crashes_on_hostile_inputs():
    # The contract: classify anything without raising.
    for bad in [object(), b"bytes", 3.14, {"nested": {"x": 1}}, [None], ("a",)]:
        assert fs.classify(bad) in {
            fs.PRESENT, fs.EMPTY, fs.NULL, fs.SENTINEL, fs.ABSENT, fs.MALFORMED
        }
    # Missing diagnostics sink must be tolerated, not crash.
    fs.diagnose({}, field="f", state=fs.ABSENT, source_field="s")
