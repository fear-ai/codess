"""Content sanitization: control chars, ANSI, redaction."""

import re
from config import REDACT_PATTERNS

# Exclude \t (0x09) and \n (0x0a) - we keep those; \r normalized to \n first
CONTROL_CHARS_RE = re.compile(r'[\x00-\x08\x0b\x0c\x0d-\x1f\x7f]')
ANSI_ESCAPE_RE = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]')


def sanitize_text(s: str) -> str:
    """Remove control chars, ANSI escapes; normalize \\r to \\n."""
    if not s:
        return s
    t = s.replace('\r\n', '\n').replace('\r', '\n')
    t = ANSI_ESCAPE_RE.sub('', t)
    t = CONTROL_CHARS_RE.sub('', t)
    return t


def sanitize_for_display(s: str, max_len: int = 512) -> str:
    """Sanitize + truncate for source_raw display only."""
    if isinstance(s, bytes):
        s = s.decode('utf-8', errors='replace')
    t = sanitize_text(s)
    if len(t) > max_len:
        t = t[: max_len - 1] + '…'
    return t


def redact(s: str, patterns: list[re.Pattern] | None = None) -> str:
    """Replace matches with [REDACTED]."""
    patterns = patterns or REDACT_PATTERNS
    for pat in patterns:
        s = pat.sub('[REDACTED]', s)
    return s


def apply_sanitization(text: str, redact_enabled: bool = False) -> str:
    """Sanitize text; optionally apply redaction."""
    t = sanitize_text(text)
    if redact_enabled:
        t = redact(t)
    return t
