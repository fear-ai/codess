from pathlib import Path

from codess.content_processing import ContentValidationError
from codess.ingest_review import record_ingest_review
from codess.resources import ResourceLimitError


def test_size_review_preserves_safe_evidence_and_candidate_classifications(tmp_path: Path):
    source = tmp_path / "state.vscdb"
    source.write_bytes(b"sqlite bytes")
    opts = {"diagnostics": {}, "content_failure_reviews": []}
    exc = ResourceLimitError(
        "too large", limit_kind="source_bytes", observed=12, maximum=4
    )

    assert record_ingest_review(
        opts, exc, source=source, vendor="Cursor", stage="source_validation"
    )
    review = opts["content_failure_reviews"][0]
    assert review["failure_class"] == "source_size_limit"
    assert review["review_required"] is True
    assert "wrong_source_scope_or_container_selected" in review["candidate_causes"]
    assert review["observations"]["limit_kind"] == "source_bytes"
    assert review["observations"]["source_bytes"] == len(b"sqlite bytes")
    assert "content" not in review
    assert opts["diagnostics"]["reviewable_content_failures"] == 1


def test_charset_review_suggests_rechecking_text_classification(tmp_path: Path):
    exc = ContentValidationError(
        "not utf-8", validation_kind="charset", encoding="utf-8"
    )
    opts = {"diagnostics": {}}

    assert record_ingest_review(
        opts, exc, source=tmp_path / "result.bin", vendor="Claude",
        stage="external_content_extraction", record_type="external.tool_result",
    )
    review = opts["content_failure_reviews"][0]
    assert review["failure_class"] == "character_set_validation"
    assert "binary_content_misclassified_as_text" in review["candidate_causes"]
