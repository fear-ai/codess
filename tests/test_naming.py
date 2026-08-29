"""The naming rules CLAUDE.md states, enforced where no lint rule can.

Ruff's `A` family reports a parameter shadowing a *builtin*; nothing in ruff
reports one shadowing a module-level name in the same file. mypy reports it, but
only as a downstream type error whose message names the type rather than the
collision -- and only if the annotations happen to make the conflict visible.

Four collisions of this class were found in one session, three of them live bugs.
These checks are the mechanical form of the rules that replaced them.
"""

from __future__ import annotations

import ast
from pathlib import Path

import codess

SRC = Path(codess.__file__).resolve().parents[1]


def _modules() -> list[Path]:
    return [
        path for base in ("codess", "cli")
        for path in sorted((SRC / base).rglob("*.py"))
        if "egg-info" not in str(path)
    ]


def test_no_parameter_shadows_a_module_level_function() -> None:
    """CLAUDE.md rule 1.

    `configure(profile=...)` beside a module function `profile()` reads as the
    function to a person and resolves to the parameter to the interpreter -- which
    is how `emit_named(event=...)` came to call a `str`.
    """
    offenders = []
    for path in _modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        module_functions = {
            node.name for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            parameters = {
                argument.arg
                for argument in node.args.args + node.args.kwonlyargs
            }
            offenders.extend(
                f"{path.name}:{node.name}({shadowed})"
                for shadowed in sorted(parameters & module_functions)
            )
    assert offenders == [], (
        "a parameter reuses the name of a module-level function in the same "
        f"file: {offenders}"
    )


def test_a_parameter_rebind_keeps_the_parameters_own_value() -> None:
    """CLAUDE.md rule 2, in the form that can be checked statically.

    `registry = registry.expanduser().resolve()` is the benign idiom -- same type,
    same meaning, and the expression mentions the name it rebinds. A rebind whose
    expression does *not* mention the name is either filling a `None` default or
    changing what the name means, and the second is the hazard.

    Measured when this was written: 52 benign normalizations against 2 rebinds,
    both of which fill a None default with a same-typed value. New entries need
    checking by hand, which is what this list is for.
    """
    allowed = {
        # Fills a `None` default with the value it would have had.
        "baseline_validation.py:run_query_smoke(snapshot_id)",
        "walk_sessions.py:walk_sessions(codex_index)",
    }
    offenders = []
    for path in _modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            parameters = {
                argument.arg
                for argument in node.args.args + node.args.kwonlyargs
            }
            for statement in ast.walk(node):
                if not isinstance(statement, ast.Assign):
                    continue
                for target in statement.targets:
                    if not (
                        isinstance(target, ast.Name) and target.id in parameters
                    ):
                        continue
                    mentioned = {
                        name.id for name in ast.walk(statement.value)
                        if isinstance(name, ast.Name)
                    }
                    if target.id in mentioned:
                        continue
                    entry = f"{path.name}:{node.name}({target.id})"
                    if entry not in allowed:
                        offenders.append(entry)
    assert offenders == [], (
        "a local rebinds a parameter to an unrelated value; give it its own name "
        f"or add it to `allowed` with the reason: {offenders}"
    )


def test_the_naming_rules_are_documented_where_code_is_governed() -> None:
    """A rule enforced by a test and written down nowhere is a rule nobody can
    follow. CLAUDE.md had no code naming section at all, which is why these
    conventions lived only in the reviewer's head."""
    text = (SRC.parent / "AGENTS.md").read_text(encoding="utf-8")
    assert "## Code Naming" in text
    for expected in ("module-level function", "rebinds", "trailing underscore"):
        assert expected in text, expected
