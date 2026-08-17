"""Field rendering under a privacy profile: allowlist, type check, bound.

Report 15.4's three mechanisms, in the order they are applied, each catching
what the next cannot:

1. **An allowlist.** A field name absent from `codes.FIELD_CLASSES` renders as
   `<unregistered>` under any non-local profile. A denylist fails open, and the
   field nobody classified is the one that leaks.
2. **A type restriction.** A value must be a scalar. A dict or list is where a
   transcript body enters an operational field by accident, and rejecting the
   type is cheaper and more certain than inspecting the value.
3. **A bound.** A long scalar is truncated with a marker, so an unexpectedly
   large value is visible as truncated rather than emitted whole.

**Path redaction is structural, not textual.** A regular expression over
`/Users/[^/]+` would miss `/home`, `C:\\Users`, a mounted volume, and a custom
`CODESS_CC_PROJECTS`. The known roots are registered instead, and a `located`
field is rendered relative to whichever root contains it.
"""

from __future__ import annotations

from pathlib import Path

from codess.hashing import codess_text_hash
from codess.reporting.codes import (
    FIELD_CLASSES,
    LINKING,
    LOCATED,
    UNREGISTERED,
)
from codess.reporting.levels import MAX_FIELD_BYTES

_SCALARS = (str, int, float, bool, type(None))

REJECTED = "<non-scalar>"
"""Rendered in place of a dict, list, or object value.

Named for what happened rather than showing a repr: a repr of the rejected
value is exactly the content the type check exists to keep out.
"""

TRUNCATED_MARKER = "...<truncated>"

_LINKING_DIGEST_CHARS = 8
"""Enough to correlate lines within one report, short enough not to reverse.

The same reasoning as `identity`'s bounded forms: a truncated digest is a join
key, not an identifier, so it needs to distinguish the values present in one
report rather than to be globally unique.
"""


class Roots:
    """Registered filesystem roots, longest-first, for structural redaction.

    Longest-first because roots nest: the registry may live under home, and a
    path under both should be reported against the more specific one, or the
    token says less than it could.
    """

    __slots__ = ("_ordered",)

    def __init__(self, roots: dict[str, Path] | None = None) -> None:
        self._ordered: list[tuple[str, str]] = []
        for token, path in (roots or {}).items():
            self.register(token, path)

    def register(self, token: str, path: Path | str) -> None:
        resolved = str(Path(path).expanduser().resolve())
        self._ordered = sorted(
            [*[item for item in self._ordered if item[1] != resolved],
             (token, resolved)],
            key=lambda item: len(item[1]),
            reverse=True,
        )

    def relative(self, value: str) -> str:
        """Render one path against its containing root, or leave it alone."""
        for token, root in self._ordered:
            if value == root:
                return f"<{token}>"
            if value.startswith(root + "/"):
                return f"<{token}>/{value[len(root) + 1:]}"
        return value

    def token_only(self, value: str) -> str:
        """Render only which root contained a path, discarding the remainder."""
        for token, root in self._ordered:
            if value == root or value.startswith(root + "/"):
                return f"<{token}>"
        return "<unrooted>"


def _bounded(text: str) -> str:
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= MAX_FIELD_BYTES:
        return text
    keep = MAX_FIELD_BYTES - len(TRUNCATED_MARKER)
    return encoded[:keep].decode("utf-8", errors="ignore") + TRUNCATED_MARKER


def _tail(value: str, segments: int = 2) -> str:
    """Keep a path's final segments.

    Under `shared`, a root-relative path can still encode the original location,
    because Claude's project directory naming embeds the absolute path in a slug
    -- so making the path root-relative is not enough on its own. Keeping the
    final two segments is `identity.source_key`'s existing rule (Report 15.4).

    **This bounds the leak; it does not close it.** Measured on a real ingest,
    `shared` renders a Claude source as
    `-Users-<user>-Work-<group>-<project>/<uuid>.jsonl`: the slug *is* one
    segment, so keeping two keeps it whole, and the account name survives. The
    rule works for an ordinary path and fails for a vendor that encodes a path
    into a filename.

    Two segments is still the right rule here, because the alternative -- pattern
    matching a slug -- is the textual redaction 15.4 rejects for missing every
    naming convention it was not written against. `strict` is the profile that
    closes it, reducing the value to its root token, and that is what a log
    leaving the organisation should use. A reader choosing `shared` for an issue
    report is told this by the profile table rather than discovering it.
    """
    parts = [part for part in value.split("/") if part]
    return "/".join(parts[-segments:]) if parts else value


def render(
    name: str, value: object, *, privacy: str = "local", roots: Roots | None = None,
) -> tuple[str, object] | None:
    """Render one field for a sink, or None if it must not be emitted.

    Returns the pair to emit, so a caller does not have to know which of the
    three mechanisms rejected or transformed a value.
    """
    if privacy == "local":
        # The operator's own machine and their own data: verbatim, including the
        # unregistered field, because the allowlist exists to protect a value
        # leaving the machine and here nothing is.
        if not isinstance(value, _SCALARS):
            return (name, REJECTED)
        return (name, _bounded(value) if isinstance(value, str) else value)

    field_class = FIELD_CLASSES.get(name)
    if field_class is None:
        return (name, UNREGISTERED)
    if not isinstance(value, _SCALARS):
        return (name, REJECTED)
    if value is None:
        return (name, None)

    if field_class == LOCATED:
        text = str(value)
        if privacy == "strict":
            return (name, (roots or Roots()).token_only(text))
        return (name, _bounded(_tail((roots or Roots()).relative(text))))
    if field_class == LINKING:
        if privacy == "strict":
            return None
        digest = codess_text_hash(256, 256, str(value))
        return (name, digest[:_LINKING_DIGEST_CHARS])
    return (name, _bounded(value) if isinstance(value, str) else value)


def render_fields(
    fields: tuple, *, privacy: str = "local", roots: Roots | None = None,
) -> dict[str, object]:
    """Render a flat (key, value, key, value, ...) tuple into a mapping.

    The flat tuple is the call site's cheap form (Report 5); materializing a
    mapping happens here, once, for a sink that is actually emitting.
    """
    rendered: dict[str, object] = {}
    for index in range(0, len(fields) - 1, 2):
        name = fields[index]
        pair = render(
            str(name), fields[index + 1], privacy=privacy, roots=roots,
        )
        if pair is not None:
            rendered[pair[0]] = pair[1]
    return rendered
