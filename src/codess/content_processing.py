"""Scoped, auditable content pre/post-processing prototypes.

The normalized store remains policy-neutral.  Callers may attach a processor to
an ingest run and record the returned actions in mapping metadata/diagnostics.
Rules are layered like web request filters or database predicates: global rules
apply first, followed by every matching scope in declaration order.
"""

from __future__ import annotations

import fnmatch
import re
import unicodedata
from dataclasses import dataclass, field, replace
from typing import Any

from codess.sanitize import apply_sanitization, sanitize_text


class ContentValidationError(ValueError):
    """Typed validation error retained as possible mapping/ingest evidence."""

    def __init__(
        self,
        message: str,
        *,
        validation_kind: str,
        expected_type: str | None = None,
        observed_type: str | None = None,
        encoding: str | None = None,
    ) -> None:
        super().__init__(message)
        self.validation_kind = validation_kind
        self.expected_type = expected_type
        self.observed_type = observed_type
        self.encoding = encoding


@dataclass(frozen=True)
class ContentContext:
    vendor: str | None = None
    record_type: str | None = None
    event_kind: str | None = None
    project_path: str | None = None
    repo_path: str | None = None
    phase: str | None = None


@dataclass(frozen=True)
class ContentResult:
    content: str
    accepted: bool
    original_length: int
    actions: tuple[str, ...] = ()
    reason: str | None = None


@dataclass(frozen=True)
class ContentPolicy:
    rules: dict[str, Any] = field(default_factory=dict)
    scopes: tuple[dict[str, Any], ...] = ()

    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None) -> ContentPolicy:
        value = dict(value or {})
        scopes = tuple(value.pop("scopes", ()) or ())
        return cls(rules=value, scopes=scopes)


def _condition_matches(actual: str | None, expected: Any) -> bool:
    choices = expected if isinstance(expected, list) else [expected]
    value = actual or ""
    return any(fnmatch.fnmatchcase(value, str(choice)) for choice in choices)


def _scope_matches(scope: dict[str, Any], context: ContentContext) -> bool:
    conditions = scope.get("when") or {}
    return all(
        _condition_matches(getattr(context, key, None), expected)
        for key, expected in conditions.items()
    )


def _merged_rules(policy: ContentPolicy, context: ContentContext) -> dict[str, Any]:
    merged = dict(policy.rules)
    list_fields = {
        "privacy_patterns", "suppress_patterns", "vocabulary_blank",
    }
    for scope in policy.scopes:
        if not _scope_matches(scope, context):
            continue
        for key, value in scope.items():
            if key == "when":
                continue
            if key in list_fields:
                merged[key] = list(merged.get(key) or []) + list(value or [])
            elif key == "topics" or key == "charset":
                merged[key] = {**(merged.get(key) or {}), **(value or {})}
            else:
                merged[key] = value
    return merged


class ContentProcessor:
    """Apply explicit, scoped transformations at pre/post-normalization hooks."""

    def __init__(self, policy: ContentPolicy):
        self.policy = policy

    def decode(self, value: bytes, context: ContentContext) -> ContentResult:
        rules = _merged_rules(self.policy, context)
        charset = rules.get("charset") or {}
        encoding = str(charset.get("encoding") or "utf-8")
        errors = str(charset.get("errors") or "strict")
        if not isinstance(value, bytes):
            raise ContentValidationError(
                f"content decoder expected bytes, got {type(value).__name__}",
                validation_kind="type", expected_type="bytes",
                observed_type=type(value).__name__, encoding=encoding,
            )
        try:
            text = value.decode(encoding, errors=errors)
        except (UnicodeError, LookupError) as exc:
            raise ContentValidationError(
                f"cannot decode content as {encoding} with errors={errors}: {exc}",
                validation_kind="charset", expected_type="bytes",
                observed_type="bytes", encoding=encoding,
            ) from exc
        result = self._process(text, context, rules)
        actions = (f"decoded:{encoding}:{errors}", *result.actions)
        return replace(result, actions=actions)

    def preprocess(self, value: str, context: ContentContext) -> ContentResult:
        context = replace(context, phase="pre")
        self._require_text(value)
        return self._process(value, context, _merged_rules(self.policy, context))

    def postprocess(self, value: str, context: ContentContext) -> ContentResult:
        context = replace(context, phase="post")
        self._require_text(value)
        return self._process(value, context, _merged_rules(self.policy, context))

    @staticmethod
    def _require_text(value: Any) -> None:
        if not isinstance(value, str):
            raise ContentValidationError(
                f"content processor expected str, got {type(value).__name__}",
                validation_kind="type", expected_type="str",
                observed_type=type(value).__name__,
            )

    @staticmethod
    def _process(
        value: str, context: ContentContext, rules: dict[str, Any]
    ) -> ContentResult:
        original_length = len(value)
        text = sanitize_text(value)
        actions: list[str] = []
        if text != value:
            actions.append("control_sanitized")

        charset = rules.get("charset") or {}
        normalization = charset.get("normalization")
        if normalization:
            normalized = unicodedata.normalize(str(normalization), text)
            if normalized != text:
                actions.append("unicode_normalized")
            text = normalized

        for pattern in rules.get("suppress_patterns") or []:
            if re.search(str(pattern), text, flags=re.IGNORECASE | re.MULTILINE):
                return ContentResult(
                    "", False, original_length, (*actions, "suppressed"),
                    "suppressed_pattern",
                )

        for item in rules.get("privacy_patterns") or []:
            if isinstance(item, str):
                pattern, replacement = item, "[MASKED]"
            else:
                pattern = str(item.get("pattern") or "")
                replacement = str(item.get("replacement") or "[MASKED]")
            updated, count = re.subn(pattern, replacement, text, flags=re.IGNORECASE)
            if count:
                actions.append("privacy_masked")
            text = updated

        for term in rules.get("vocabulary_blank") or []:
            updated, count = re.subn(
                re.escape(str(term)), "[BLANKED]", text, flags=re.IGNORECASE
            )
            if count:
                actions.append("vocabulary_blanked")
            text = updated

        topics = rules.get("topics") or {}
        if any(
            re.search(str(pattern), text, flags=re.IGNORECASE)
            for pattern in topics.get("exclude") or []
        ):
            return ContentResult(
                "", False, original_length, (*actions, "topic_excluded"),
                "topic_excluded",
            )
        include = topics.get("include") or []
        if include and not any(
            re.search(str(pattern), text, flags=re.IGNORECASE)
            for pattern in include
        ):
            return ContentResult(
                "", False, original_length, (*actions, "topic_not_included"),
                "topic_not_included",
            )

        minimum = rules.get("min_chars")
        if minimum is not None and len(text) < int(minimum):
            return ContentResult(
                "", False, original_length, (*actions, "min_chars"),
                "below_min_chars",
            )
        maximum = rules.get("max_chars")
        if maximum is not None and len(text) > int(maximum):
            limit = int(maximum)
            text = (text[: limit - 1] + "…") if limit > 0 else ""
            actions.append("max_chars")

        return ContentResult(text, True, original_length, tuple(actions))


def apply_processing(
    value: str,
    opts: dict[str, Any],
    *,
    vendor: str,
    record_type: str,
    event_kind: str | None = None,
    phase: str = "pre",
) -> str | None:
    """Adapter entry point with shared diagnostics, scope, and redaction."""
    processor = opts.get("content_processor")
    if processor is None:
        return apply_sanitization(str(value), opts.get("redact", False))
    context = ContentContext(
        vendor=vendor, record_type=record_type, event_kind=event_kind,
        project_path=opts.get("project_path"), repo_path=opts.get("repo_path"),
        phase=phase,
    )
    method = processor.preprocess if phase == "pre" else processor.postprocess
    result = method(value, context)
    actions = opts.get("content_actions")
    if actions is not None:
        output_text = result.content
        actions.append({
            "phase": phase,
            "vendor": vendor,
            "record_type": record_type,
            "event_kind": event_kind,
            "accepted": result.accepted,
            "reason": result.reason,
            "actions": list(result.actions),
            "original_length": result.original_length,
            "output_length": len(output_text),
        })
    if not result.accepted:
        diagnostics = opts.get("diagnostics")
        if diagnostics is not None:
            diagnostics["filtered_records"] = diagnostics.get("filtered_records", 0) + 1
        return None
    return apply_sanitization(result.content, opts.get("redact", False))
