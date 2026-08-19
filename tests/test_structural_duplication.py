"""Functions that differ only in their names, found by shape rather than text.

The defect this catches is a body consolidated once and then reintroduced under
a different name. `context_content.truncate_content` was extracted from three
adapters, documented as one definition, and a private `_truncate` reappeared in
the Codex adapter with a different signature and docstring. Every reviewer who
read either site saw a small, reasonable local helper.

**Why text comparison does not find it.** The reintroduced copy shared no line
with the original: different name, different parameter annotations, different
docstring. Comparing the *shape* -- the sequence of AST node types, with every
name and constant erased -- makes the two identical, because what was
duplicated is the logic rather than the wording.

Cheap enough to keep: the whole tree parses in well under a second, so this runs
with the ordinary suite rather than as a separate audit somebody remembers to
invoke.
"""

from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"

# Below this, a shared shape is coincidence rather than duplication: a guard
# clause plus a return matches hundreds of unrelated functions. Six statements
# is where the shapes observed here stopped colliding by accident -- the one
# real cluster found had 95 nodes.
MIN_BODY_STATEMENTS = 6

# A function may legitimately share a shape with another: the two hash helpers
# differ only in the width they pass, and separating them is what makes each
# readable. Record the pair rather than raising, so an accepted duplicate is a
# decision someone wrote down instead of a check somebody disabled.
ACCEPTED_SHARED_SHAPES: set[frozenset[str]] = set()


def _shape(function: ast.FunctionDef) -> tuple[str, ...]:
    """The node types of a function body, in order, with names discarded.

    Names and constants are what a reintroduced copy changes; control flow and
    call structure are what it keeps.
    """
    return tuple(type(node).__name__ for node in ast.walk(function))


def _functions() -> list[tuple[str, ast.FunctionDef]]:
    found = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        found.extend(
            (f"{path.name}::{node.name}", node)
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
            and len(node.body) >= MIN_BODY_STATEMENTS
        )
    return found


def test_no_two_functions_share_a_body_shape():
    """One logic, one definition -- checked by structure, not by reading."""
    by_shape: dict[tuple[str, ...], list[str]] = defaultdict(list)
    for label, function in _functions():
        by_shape[_shape(function)].append(label)

    clusters = [
        sorted(labels) for labels in by_shape.values()
        if len(labels) > 1 and frozenset(labels) not in ACCEPTED_SHARED_SHAPES
    ]
    assert clusters == [], (
        "these functions have identical structure and differ only in naming; "
        "extract one definition, or add the pair to ACCEPTED_SHARED_SHAPES "
        "with the reason:\n"
        + "\n".join("  " + " <-> ".join(c) for c in clusters)
    )


def test_the_check_detects_a_reintroduced_copy():
    """The check earns its place only if it fails on the case it exists for.

    Asserts against the real detector on a synthetic pair rather than trusting
    that a passing run means the logic works -- a shape comparison that always
    returned "no duplicates" would pass the test above forever.
    """
    original = ast.parse(
        "def bound(text, limit):\n"
        "    if text is None:\n        return '', 0\n"
        "    body = str(text)\n    size = len(body)\n"
        "    if limit <= 0:\n        return '', size\n"
        "    return body[:limit], size\n"
    ).body[0]
    reintroduced = ast.parse(
        "def _clip(value, cap):\n"
        "    if value is None:\n        return '', 0\n"
        "    text = str(value)\n    length = len(text)\n"
        "    if cap <= 0:\n        return '', length\n"
        "    return text[:cap], length\n"
    ).body[0]

    assert _shape(original) == _shape(reintroduced), (
        "renaming every local must not change the shape, or the check cannot "
        "find a copy that was renamed"
    )
