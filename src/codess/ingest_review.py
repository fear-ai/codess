"""Content-validation failures retained for classification and ingest review.

The records deliberately contain observations rather than source content.  They
help distinguish a genuinely malformed/large value from selecting the wrong
source, boundary, decoder, or vendor mapping.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from codess.resources import ResourceLimitError


def _failure_details(exc: BaseException) -> tuple[str, list[str], list[str]] | None:
    kind = getattr(exc, "validation_kind", None)
    if isinstance(exc, ResourceLimitError):
        limit_kind = exc.limit_kind or "resource_limit"
        if limit_kind == "source_bytes":
            return (
                "source_size_limit",
                [
                    "wrong_source_scope_or_container_selected",
                    "database_or_archive_misclassified_as_content",
                    "legitimate_oversize_source",
                ],
                [
                    "verify the source is the intended project/session projection",
                    "inspect the container format before raising the configured limit",
                    "raise the limit explicitly only after confirming classification",
                ],
            )
        boundary = "session" if limit_kind == "session_events" else "source"
        return (
            f"{boundary}_event_limit",
            [
                f"wrong_{boundary}_boundary",
                "aggregate_misclassified_as_one_logical_unit",
                f"legitimate_large_{boundary}",
            ],
            [
                f"verify the {boundary} identity and record grouping",
                "compare parsed counts with raw vendor structure",
                "raise the limit explicitly only after confirming classification",
            ],
        )
    if kind == "charset" or isinstance(exc, (UnicodeError, LookupError)):
        return (
            "character_set_validation",
            [
                "binary_content_misclassified_as_text",
                "wrong_declared_or_default_charset",
                "encoded_or_compressed_content_not_decoded",
                "corrupt_content",
            ],
            [
                "inspect media type and encoding metadata",
                "compare byte structure with the vendor field definition",
                "configure a scoped charset mapping only after identification",
            ],
        )
    message = str(exc).lower()
    if (
        kind == "type"
        or isinstance(exc, TypeError)
        or ("unsupported" in message and "type" in message)
    ):
        return (
            "content_type_validation",
            [
                "vendor_record_variant_unmapped",
                "wrapper_or_harness_content_misclassified",
                "external_content_misclassified_as_inline",
                "malformed_content",
            ],
            [
                "inspect the vendor record envelope and discriminator",
                "compare the observed shape with adjacent records and fixtures",
                "add a vendor mapping only when the semantic role is established",
            ],
        )
    return None


def record_ingest_review(
    opts: dict[str, Any],
    exc: BaseException,
    *,
    source: str | Path,
    vendor: str,
    stage: str,
    record_type: str | None = None,
) -> bool:
    """Record a reviewable size/type/charset failure; return whether classified."""
    details = _failure_details(exc)
    if details is None:
        return False
    failure_class, candidates, checks = details
    source_text = str(source)
    path = Path(source_text).expanduser()
    observation: dict[str, Any] = {
        "source_suffix": path.suffix.lower() or None,
        "source_locator_sha256": hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
    }
    try:
        stat = path.stat()
    except OSError:
        pass
    else:
        observation["source_bytes"] = stat.st_size
    for name in ("limit_kind", "observed", "maximum", "expected_type", "observed_type", "encoding"):
        value = getattr(exc, name, None)
        if value is not None:
            observation[name] = value
    review = {
        "review_format": "codess.ingest-content-review/1",
        "review_required": True,
        "failure_class": failure_class,
        "vendor": vendor,
        "stage": stage,
        "record_type": record_type,
        "source": source_text,
        "exception_type": type(exc).__name__,
        "message": str(exc),
        "observations": observation,
        "candidate_causes": candidates,
        "recommended_checks": checks,
    }
    opts.setdefault("content_failure_reviews", []).append(review)
    diagnostics = opts.get("diagnostics")
    if diagnostics is not None:
        diagnostics["reviewable_content_failures"] = (
            diagnostics.get("reviewable_content_failures", 0) + 1
        )
    return True
