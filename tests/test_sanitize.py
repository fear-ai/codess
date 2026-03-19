"""Sanitization corner cases and edge cases."""

import pytest

from codess.sanitize import (
    apply_sanitization,
    redact,
    sanitize_for_display,
    sanitize_text,
)


class TestSanitizeText:
    """sanitize_text edge cases."""

    def test_empty_and_none(self):
        assert sanitize_text("") == ""
        assert sanitize_text(None) is None

    def test_control_chars(self):
        assert sanitize_text("a\x00b") == "ab"
        assert sanitize_text("\x01\x02\x1f\x7f") == ""
        assert sanitize_text("keep\t\n") == "keep\t\n"  # tab and newline preserved

    def test_ansi_sequences(self):
        assert sanitize_text("hello\x1b[31mred\x1b[0m") == "hellored"
        assert sanitize_text("\x1b[0m") == ""
        assert sanitize_text("\x1b[1;32mbold green\x1b[0m") == "bold green"

    def test_line_endings(self):
        assert sanitize_text("a\r\nb") == "a\nb"
        assert sanitize_text("a\rb") == "a\nb"
        assert sanitize_text("a\nb") == "a\nb"
        assert sanitize_text("a\n\rb") == "a\n\nb"  # \n\r -> \n then \r->\n

    def test_combined(self):
        assert sanitize_text("a\x00\x1b[31mb\r\nc") == "ab\nc"

    def test_unicode(self):
        assert sanitize_text("café 日本語") == "café 日本語"
        assert sanitize_text("emoji 🎉") == "emoji 🎉"


class TestSanitizeForDisplay:
    """sanitize_for_display edge cases."""

    def test_bytes_input(self):
        assert sanitize_for_display(b"hello", 10) == "hello"
        assert sanitize_for_display(b"x" * 20, 10).endswith("…")

    def test_invalid_utf8_bytes(self):
        # Replacement char for invalid bytes
        out = sanitize_for_display(b"hello\xff\xfe world", 20)
        assert "hello" in out and "world" in out

    def test_truncation(self):
        assert len(sanitize_for_display("x" * 1000, 100)) == 100
        assert sanitize_for_display("x" * 100, 50).endswith("…")


class TestRedact:
    """Redaction patterns."""

    def test_sk_key(self):
        assert "sk-" in "sk-abc123" * 5
        assert "[REDACTED]" in redact("key is sk-abcdefghij1234567890xyz")

    def test_api_key_pattern(self):
        assert "[REDACTED]" in redact('API_KEY="secret12345678901234567890"')

    def test_no_false_positive_short_hex(self):
        # Short hex strings should not match
        s = "id: a1b2c3d4"
        assert redact(s) == s  # No 20+ char match

    def test_empty_patterns(self):
        assert redact("sk-xxx", []) == "sk-xxx"


class TestApplySanitization:
    """apply_sanitization combinations."""

    def test_no_redact(self):
        assert apply_sanitization("hello\x00world", False) == "helloworld"

    def test_with_redact(self):
        out = apply_sanitization("key sk-abcdefghij1234567890xyz", True)
        assert "[REDACTED]" in out
