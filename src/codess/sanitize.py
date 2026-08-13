"""Content sanitization: control chars, ANSI, redaction."""

import re

from codess.config import REDACT_PATTERNS

# Exclude tab/newline; carriage returns are normalized first. C1 controls are
# removed because terminals may interpret them as single-byte escape controls.
CONTROL_CHARS_RE = re.compile(r'[\x00-\x08\x0b\x0c\x0d-\x1f\x7f-\x9f]')
ANSI_ESCAPE_RE = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]')
CSV_FORMULA_PREFIXES = frozenset(("=", "+", "-", "@", "＝", "＋", "－", "＠"))


def sanitize_text(s: str) -> str:
    """Remove control chars, ANSI escapes; normalize \\r to \\n."""
    if not s:
        return s
    t = s.replace('\r\n', '\n').replace('\r', '\n')
    t = ANSI_ESCAPE_RE.sub('', t)
    return CONTROL_CHARS_RE.sub('', t)


def sanitize_for_display(s: str, max_len: int = 512) -> str:
    """Sanitize + truncate for source_raw display only."""
    if isinstance(s, bytes):
        s = s.decode('utf-8', errors='replace')
    elif not isinstance(s, str):
        s = str(s)
    t = sanitize_text(s)
    if len(t) > max_len:
        t = t[: max_len - 1] + '…'
    return t


def sanitize_tabular(value) -> str:
    """Sanitize a scalar for one-line/tabular terminal output."""
    if value is None:
        return ""
    return sanitize_text(str(value)).replace("\t", " ").replace("\n", " ")


def sanitize_value(value, redact_enabled: bool = False):
    """Recursively sanitize strings in JSON-like tool input structures."""
    if isinstance(value, str):
        return apply_sanitization(value, redact_enabled)
    if isinstance(value, dict):
        return {
            apply_sanitization(str(key), redact_enabled): sanitize_value(
                item, redact_enabled
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize_value(item, redact_enabled) for item in value]
    if isinstance(value, tuple):
        return tuple(sanitize_value(item, redact_enabled) for item in value)
    return value


def protect_csv_cell(value):
    """Prevent spreadsheet formula interpretation for string CSV cells."""
    if not isinstance(value, str) or not value:
        return value
    if value[0] in CSV_FORMULA_PREFIXES or value[0] in ("\t", "\r", "\n"):
        return "\t" + value
    return value


def protect_csv_row(row) -> list:
    return [protect_csv_cell(value) for value in row]


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
