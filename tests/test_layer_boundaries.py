"""The dependency rules, enforced against the import graph rather than described.

CoPlan states which layer may depend on which. Until these checks existed the
rules held by review alone, so a violation reached a call site before anyone
read for it -- which is how vendor SQL spread into two modules and a probe
statement ended up in a command module.

The checks read imports statically. A module that never imports another cannot
depend on it, which is the property the layering is about; what a function does
at run time is a separate question these do not answer.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"


def _module_imports(path: Path) -> set[str]:
    """Every module name `path` imports, including inside a function body."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names.add(node.module)
        elif isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
    return names


def _library_modules() -> list[Path]:
    return sorted(p for p in (SRC / "codess").rglob("*.py"))


def _adapters() -> list[Path]:
    return sorted((SRC / "codess" / "adapters").glob("*.py"))


@pytest.mark.parametrize("path", _library_modules(), ids=lambda p: p.name)
def test_library_does_not_import_the_command_layer(path):
    """`codess.*` may not depend on `cli.*`.

    `project` is the exception and the reason is structural: it is the console
    entry point, so dispatching to a command adapter is its job. It defers each
    import into the branch that needs it, which is why the package still
    imports without `cli` present.
    """
    if path.name == "project.py":
        return
    offenders = {name for name in _module_imports(path) if name.split(".")[0] == "cli"}
    assert not offenders, f"{path.name} imports {sorted(offenders)}"


@pytest.mark.parametrize("path", _adapters(), ids=lambda p: p.name)
def test_an_adapter_reaches_no_further_than_mapping(path):
    """A vendor decoder owns interpretation, not storage, query, or catalog.

    An adapter that could reach the store would be able to write what it
    decoded, which is the boundary that keeps decode testable from records
    alone: every adapter test supplies bounded input and reads candidates back,
    with no database in between.
    """
    forbidden = {"codess.store", "codess.query_api", "codess.project_catalog",
                 "codess.catalog_operations", "codess.snapshot"}
    offenders = _module_imports(path) & forbidden
    assert not offenders, f"{path.name} imports {sorted(offenders)}"


def test_the_query_engine_does_not_invoke_a_decoder():
    """Query reads normalized stores; re-decoding there would be a second path.

    Two decode paths disagree eventually, and the one reached through a query
    would disagree invisibly -- a caller sees rows, not which code produced
    them.
    """
    for name in ("query_api.py", "query_reports.py", "investigation.py"):
        path = SRC / "codess" / name
        if not path.is_file():
            continue
        offenders = {i for i in _module_imports(path) if "adapters" in i}
        assert not offenders, f"{name} imports {sorted(offenders)}"


def test_vendor_sql_stays_in_its_source_access_module():
    """Cursor's tables are named in `cursor_source` and nowhere else.

    The adapter previously opened SQLite itself, which spread vendor table
    knowledge across two modules and made decode untestable without a database.
    `cursorDiskKV` appearing anywhere else is that regression returning.
    """
    owners = {"cursor_source.py"}
    offenders = []
    for path in _library_modules():
        if path.name in owners:
            continue
        text = path.read_text(encoding="utf-8")
        if "cursorDiskKV" in text and "FROM cursorDiskKV" in text:
            offenders.append(path.name)
    assert not offenders, f"vendor SQL outside {owners}: {offenders}"
