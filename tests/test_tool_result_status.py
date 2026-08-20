"""Recognizing an application failure inside a transport that succeeded.

A tool call can return HTTP 200 carrying a JSON error body, so the transport
status alone understates failure. The hazard runs the other way too: a result
that merely *mentions* an error is not a failed result, and a detector that
searches prose would mark successful work as failed. These pin both edges --
what counts as explicit evidence, and what is deliberately not searched.

The returned string is a path into the value, so a reader can see which field
decided it rather than trusting a boolean.
"""

from __future__ import annotations

import json

import pytest

from codess.tool_result_status import application_failure_evidence


class TestExplicitStatusFields:
    """A vendor stating failure in a named field is the strongest evidence."""

    def test_is_error_flag(self):
        assert application_failure_evidence({"isError": True}) == "$.isError=true"

    def test_is_error_false(self):
        """The field being present is not the finding; its value is."""
        assert application_failure_evidence({"isError": False}) is None

    @pytest.mark.parametrize("status", ["error", "failed", "failure", "fatal",
                                        "unavailable"])
    def test_failed_status_words(self, status):
        assert application_failure_evidence({"status": status}) == f"$.status={status}"

    def test_status_case_and_padding(self):
        """Vendors are inconsistent about both, and neither changes the meaning."""
        assert application_failure_evidence({"status": "  FAILED "}) == "$.status=failed"

    def test_succeeded_status(self):
        assert application_failure_evidence({"status": "ok"}) is None

    def test_server_status_field(self):
        assert application_failure_evidence(
            {"serverStatus": "error"}) == "$.serverStatus=error"

    def test_populated_error_field(self):
        assert application_failure_evidence({"error": "boom"}) == "$.error"

    @pytest.mark.parametrize("empty", [None, "", [], {}])
    def test_empty_error_field(self, empty):
        """An `error` key present and empty says no error occurred."""
        assert application_failure_evidence({"error": empty}) is None


class TestWhatIsNotSearched:
    """The detector is deliberately narrow, and that is the design."""

    def test_prose_mentioning_error(self):
        """Otherwise every result discussing errors would be marked failed."""
        assert application_failure_evidence(
            "The build succeeded after fixing an error in main.py") is None

    def test_error_prefix(self):
        """A result *starting* with the word is a stated outcome, not prose."""
        evidence = application_failure_evidence("Error: cannot open file")
        assert evidence == "$: Error: cannot open file"

    def test_evidence_bounded_to_one_line(self):
        """A stack trace must not become the diagnostic body."""
        evidence = application_failure_evidence("failed to run\n" + "x" * 500)
        assert evidence is not None
        assert len(evidence) < 120

    def test_unrelated_type(self):
        assert application_failure_evidence(42) is None
        assert application_failure_evidence(None) is None

    def test_empty_text(self):
        assert application_failure_evidence("   ") is None


class TestNestedAndEncodedResults:
    """Failure is commonly wrapped, so the search follows named wrappers."""

    @pytest.mark.parametrize("wrapper", ["result", "content", "output",
                                         "message", "text"])
    def test_wrapper_fields_followed(self, wrapper):
        evidence = application_failure_evidence({wrapper: {"isError": True}})
        assert evidence == f"$.{wrapper}.isError=true"

    def test_unnamed_wrapper(self):
        """Following every key would search arbitrary prose by another route."""
        assert application_failure_evidence({"notes": {"isError": True}}) is None

    def test_list_searched_by_position(self):
        evidence = application_failure_evidence([{"ok": 1}, {"status": "error"}])
        assert evidence == "$[1].status=error"

    def test_json_encoded_text(self):
        """Tool output frequently arrives as a JSON string, not an object."""
        evidence = application_failure_evidence(json.dumps({"isError": True}))
        assert evidence == "$.json.isError=true"

    def test_json_after_output_marker(self):
        """A command echo precedes the payload; the payload is the result."""
        body = 'ran the tool\nOutput:\n{"status": "failed"}'
        assert application_failure_evidence(body) == "$.json.status=failed"

    def test_recursion_depth_bound(self):
        """A deeply nested body must not cost unbounded work."""
        nested: dict = {"isError": True}
        for _ in range(12):
            nested = {"result": nested}
        assert application_failure_evidence(nested) is None
        assert application_failure_evidence(nested, max_depth=40) is not None

    def test_first_failure_reported(self):
        """One piece of evidence is enough; the path says which one."""
        evidence = application_failure_evidence(
            {"status": "error", "result": {"isError": True}})
        assert evidence == "$.status=error"
