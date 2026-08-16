"""Every CoSchema identifier named in code exists in the released DDL.

A renamed column must fail a test rather than a query. SQLite resolves a
column name at execution, so a statement naming a column the DDL no longer
declares raises `OperationalError` only on the path that runs it -- and a
report nobody exercises returns nothing instead of failing. Renaming
`global_id` to three table-qualified names broke 34 tests, each found by
running them; this check is the mechanical form of that search (CoPlan W52).

The check reads SQL text out of the source rather than executing it, so a
statement in a rarely-taken branch is covered exactly like a common one.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from codess.schema_contract import load_ddl

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"

# Identifiers that appear in SQL text but are not CoSchema columns: SQLite
# keywords and functions, PRAGMA names, and the vendor tables Codess reads
# read-only from Claude, Codex, and Cursor storage.
_SQL_WORDS = {
    "select", "from", "where", "insert", "into", "values", "update", "set",
    "delete", "join", "left", "inner", "outer", "on", "as", "and", "or",
    "not", "null", "is", "in", "like", "glob", "between", "order", "by",
    "group", "having", "limit", "offset", "asc", "desc", "distinct", "count",
    "sum", "min", "max", "avg", "coalesce", "cast", "case", "when", "then",
    "else", "end", "exists", "union", "all", "conflict", "do", "nothing",
    "excluded", "primary", "key", "unique", "index", "table", "create",
    "drop", "if", "replace", "pragma", "begin", "commit", "rollback",
    "transaction", "with", "recursive", "json_extract", "json_valid",
    "json_each", "length", "lower", "upper", "substr", "trim", "abs",
    "round", "total", "group_concat", "ifnull", "nullif", "instr", "hex",
    "quote", "random", "typeof", "collate", "binary", "nocase", "integer",
    "text", "real", "blob", "numeric", "default", "references", "cascade",
    "foreign", "check", "constraint", "using", "natural", "cross", "attach",
    "detach", "database", "vacuum", "analyze", "explain", "query", "plan",
    "temp", "temporary", "view", "trigger", "for", "each", "row", "of",
    "add", "column", "rename", "to", "without", "rowid", "autoincrement",
    "asc_nulls_last", "first", "last", "nulls", "true", "false", "escape",
    "intersect", "except", "over", "partition", "window", "filter", "cte",
}

_PRAGMA_WORDS = {
    "table_info", "foreign_key_check", "integrity_check", "quick_check",
    "user_version", "application_id", "foreign_keys", "journal_mode",
    "synchronous", "busy_timeout", "query_only", "wal", "wal_checkpoint",
    "cache_size", "temp_store", "mmap_size", "page_count", "page_size",
    "freelist_count", "optimize", "case_sensitive_like", "encoding",
    "locking_mode", "read_uncommitted", "secure_delete", "index_list",
    "index_info", "database_list", "schema_version", "truncate", "normal",
    "full", "off", "memory", "delete", "persist", "exclusive",
}

# Vendor storage: Cursor's shared SQLite database and the sqlite_* catalog.
_VENDOR_TABLES = {
    "cursordiskkv", "itemtable", "sqlite_master", "sqlite_schema",
    "sqlite_sequence", "sqlite_stat1", "composerdata", "bubbleid",
    "messagerequestcontext", "composerheaders", "value", "rowid",
    "workbench", "history", "entries", "editor",
}

_IGNORED = _SQL_WORDS | _PRAGMA_WORDS | _VENDOR_TABLES


def _ddl_tables() -> dict[str, set[str]]:
    """Each table the released DDL declares, with its column names."""
    ddl = load_ddl()
    tables: dict[str, set[str]] = {}
    for body in re.finditer(r"CREATE TABLE (\w+)\s*\((.*?)\n\)", ddl, re.DOTALL):
        columns: set[str] = set()
        for line in body.group(2).splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("--"):
                continue
            word = re.match(r"(\w+)", stripped)
            if word and word.group(1).lower() not in _SQL_WORDS:
                columns.add(word.group(1).lower())
        tables[body.group(1).lower()] = columns
    return tables


def _ddl_identifiers() -> set[str]:
    """Every table and column name the released DDL declares."""
    tables = _ddl_tables()
    names = set(tables)
    for columns in tables.values():
        names |= columns
    for match in re.finditer(r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(\w+)", load_ddl()):
        names.add(match.group(1).lower())
    return names


def _alias_tables(sql: str, tables: dict[str, set[str]]) -> dict[str, str]:
    """Map each alias in `sql` to the CoSchema table it stands for.

    Both `FROM sessions s` and `JOIN events AS e` bind an alias, and a table
    used without one binds its own name. Only bindings naming a real CoSchema
    table are returned, so a CTE alias resolves to nothing and its columns are
    left unchecked rather than checked against the wrong table.
    """
    bound: dict[str, str] = {}
    rebound: set[str] = set()
    for match in re.finditer(
        r"\b(?:FROM|JOIN|INSERT\s+INTO|UPDATE)\s+(\w+)(?:\s+(?:AS\s+)?(\w+))?",
        sql,
        re.IGNORECASE,
    ):
        table = match.group(1).lower()
        alias = (match.group(2) or "").lower()
        if table not in tables:
            # A CTE or subquery source. Any alias it binds shadows a table of
            # the same name later in the statement, so record it as unusable
            # rather than resolving its columns against the wrong table.
            if alias and alias not in _IGNORED:
                rebound.add(alias)
            continue
        bound[table] = table
        if alias and alias not in _IGNORED:
            bound[alias] = table
    for alias in rebound:
        bound.pop(alias, None)
    return bound


def _insert_columns(sql: str) -> list[tuple[str, list[str]]]:
    """Every table-plus-bare-column-list position in `sql`.

    Two shapes name columns bare against a known table, and both fail only
    when the statement runs: an `INSERT INTO table(col, ...)` list, and an
    `UPDATE table SET col=?` assignment. A projection-only check misses each.
    """
    found: list[tuple[str, list[str]]] = []
    for match in re.finditer(
        r"INSERT(?:\s+OR\s+\w+)?\s+INTO\s+(\w+)\s*\(([^)]*)\)", sql, re.IGNORECASE
    ):
        columns = [
            c.strip().lower()
            for c in match.group(2).split(",")
            if re.fullmatch(r"\s*\w+\s*", c)
        ]
        found.append((match.group(1).lower(), columns))
    for match in re.finditer(
        r"UPDATE\s+(\w+)\s+SET\s+(.*?)(?=\s+WHERE\b|$)", sql, re.IGNORECASE | re.DOTALL
    ):
        columns = [
            assignment.group(1).lower()
            for assignment in re.finditer(r"(\w+)\s*=", match.group(2))
        ]
        found.append((match.group(1).lower(), columns))
    return found


def _sql_strings(tree: ast.AST) -> list[str]:
    """Every string constant that looks like a SQL statement."""
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            text = node.value
            if re.search(
                r"\b(SELECT|INSERT INTO|UPDATE|DELETE FROM|CREATE TABLE)\b",
                text,
            ):
                found.append(text)
        elif isinstance(node, ast.JoinedStr):
            # An f-string SQL skeleton: keep the literal fragments, which is
            # where a column name is written even when placeholders are not.
            parts = [
                v.value for v in node.values
                if isinstance(v, ast.Constant) and isinstance(v.value, str)
            ]
            joined = " ".join(parts)
            if re.search(r"\b(SELECT|INSERT INTO|UPDATE|DELETE FROM)\b", joined):
                found.append(joined)
    return found


def _candidate_identifiers(sql: str) -> set[str]:
    """Names in `sql` that SQLite resolves against the CoSchema tables.

    Only two positions are checked, because only these two are unambiguous
    without binding aliases and CTEs: a table named after `FROM`, `JOIN`,
    `INSERT INTO`, or `UPDATE`, and a column written as `alias.column`. A bare
    column in a projection is skipped -- it may be an alias defined in the
    same statement (`COUNT(*) AS cnt`), a CTE column, or a name introduced by
    a window function, and distinguishing those needs a SQL parser rather than
    a check. The qualified form is where a rename actually breaks, since that
    is how every cross-table statement in this codebase names its columns.
    """
    sql = re.sub(r"'[^']*'", " ", sql)
    sql = re.sub(r"--[^\n]*", " ", sql)
    sql = re.sub(r":\w+", " ", sql)

    # CTE and subquery aliases are defined inside the statement, so a
    # reference to one is not a CoSchema table.
    local = {m.group(1).lower() for m in re.finditer(r"\b(\w+)\s+AS\s*\(", sql, re.IGNORECASE)}
    local |= {m.group(1).lower() for m in re.finditer(r"\bAS\s+(\w+)\b", sql, re.IGNORECASE)}

    names: set[str] = set()
    for token in re.finditer(
        r"\b(?:FROM|JOIN|INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+(\w+)", sql, re.IGNORECASE
    ):
        names.add(token.group(1).lower())
    for token in re.finditer(r"\b(\w+)\.(\w+)\b", sql):
        names.add(token.group(2).lower())
    return {
        n for n in names
        if n not in _IGNORED and n not in local and not n.isdigit()
    }


# Vendor storage access, not CoSchema. `cursor_source` owns every query
# against Cursor's shared database (CoPlan 6.4), whose columns are the
# vendor's own camelCase names and are deliberately outside the DDL.
_VENDOR_STORAGE_MODULES = {"cursor_source.py"}


def _python_files() -> list[Path]:
    return sorted(
        p for p in SRC_ROOT.rglob("*.py")
        if "__pycache__" not in p.parts and p.name not in _VENDOR_STORAGE_MODULES
    )


def _local_names(sql_texts: list[str]) -> set[str]:
    """Aliases and CTE names a module defines for itself.

    Collected across the whole module because one statement is often built
    from several adjacent string fragments, so a CTE can be declared in one
    constant and referenced in the next.
    """
    local: set[str] = set()
    for sql in sql_texts:
        local |= {m.group(1).lower() for m in re.finditer(r"\b(\w+)\s+AS\s*\(", sql, re.IGNORECASE)}
        local |= {m.group(1).lower() for m in re.finditer(r"\bAS\s+(\w+)\b", sql, re.IGNORECASE)}
    return local


@pytest.mark.parametrize("path", _python_files(), ids=lambda p: p.name)
def test_sql_identifiers_declared(path: Path) -> None:
    """No SQL statement names a CoSchema identifier the DDL does not declare.

    Failure means a rename reached the code but not the DDL, or the reverse.
    """
    declared = _ddl_identifiers()
    tables = _ddl_tables()
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    sql_texts = _sql_strings(tree)
    local = _local_names(sql_texts)
    undeclared: dict[str, set[str]] = {}

    def note(sql: str, names: set[str]) -> None:
        if names:
            undeclared.setdefault(sql.strip()[:80], set()).update(names)

    for sql in sql_texts:
        note(sql, {
            name for name in _candidate_identifiers(sql)
            if name not in declared
            and name not in local
            and not name.startswith("idx_")
        })
        # A qualified reference resolves against exactly one table, so a
        # column that exists on some other table is still wrong here.
        bound = _alias_tables(sql, tables)
        misplaced = set()
        for match in re.finditer(r"\b(\w+)\.(\w+)\b", re.sub(r"'[^']*'", " ", sql)):
            alias, column = match.group(1).lower(), match.group(2).lower()
            table = bound.get(alias)
            if table and column not in tables[table] and column not in _IGNORED:
                misplaced.add(f"{alias}.{column} (not a column of {table})")
        note(sql, misplaced)
        # An INSERT column list names its columns bare against a known table.
        for table, columns in _insert_columns(sql):
            if table not in tables:
                continue
            note(sql, {
                f"{table}.{c} (not a column of {table})"
                for c in columns
                if c not in tables[table] and c not in _IGNORED
            })

    assert not undeclared, (
        f"{path.relative_to(SRC_ROOT)} names identifiers absent from the "
        f"released DDL: { {k: sorted(v) for k, v in undeclared.items()} }"
    )


class TestTheCheckActuallyDetects:
    """The guard must fail on a rename, not merely pass on a clean tree.

    A check that silently stops matching is worse than no check: it reports
    success over exactly the drift it was built to catch. Each case below is
    a rename this codebase has actually made or is scheduled to make.
    """

    def _undeclared(self, sql: str) -> set[str]:
        """Names in `sql` that the released DDL does not declare."""
        declared = _ddl_identifiers()
        tables = _ddl_tables()
        found = {
            name for name in _candidate_identifiers(sql)
            if name not in declared and not name.startswith("idx_")
        }
        bound = _alias_tables(sql, tables)
        for match in re.finditer(r"\b(\w+)\.(\w+)\b", sql):
            alias, column = match.group(1).lower(), match.group(2).lower()
            table = bound.get(alias)
            if table and column not in tables[table] and column not in _IGNORED:
                found.add(column)
        for table, columns in _insert_columns(sql):
            if table in tables:
                found |= {
                    c for c in columns
                    if c not in tables[table] and c not in _IGNORED
                }
        return found

    def test_a_qualified_column_that_moved_tables_is_caught(self):
        """`started_at` exists on `sessions`, so only the table resolves it.

        This is the W25 case: the column was renamed on `tool_invocations`
        alone, so a check that merely asked "does this name exist anywhere"
        would have passed.
        """
        assert "started_at" in self._undeclared(
            "SELECT ti.started_at FROM tool_invocations ti"
        )
        assert self._undeclared("SELECT s.started_at FROM sessions s") == set()

    def test_a_renamed_column_in_an_insert_list_is_caught(self):
        assert "content_sha256" in self._undeclared(
            "INSERT INTO sources(source_entity_id, content_sha256) VALUES (?, ?)"
        )

    def test_a_renamed_column_in_an_update_clause_is_caught(self):
        """The position a projection-only check misses.

        `ingest_sources` held exactly this shape, and no test reached it.
        """
        assert "content_sha256" in self._undeclared(
            "UPDATE sources SET availability=?, content_sha256=? WHERE id=?"
        )

    def test_a_removed_column_is_caught(self):
        assert "timestamp" in self._undeclared("SELECT e.timestamp FROM events e")

    def test_current_columns_pass(self):
        assert self._undeclared(
            "SELECT e.event_at, e.event_kind FROM events e "
            "JOIN sessions s ON s.id=e.session_id"
        ) == set()

    def test_a_cte_alias_is_not_resolved_against_a_table(self):
        """A CTE rebinds an alias, and its columns are not CoSchema columns.

        `configuration_audit` binds `e` to `ranked_events` after using it for
        `events`, so resolving the later reference against `events` would
        report a false positive on correct SQL.
        """
        assert self._undeclared(
            "WITH ranked AS (SELECT id, ROW_NUMBER() OVER () AS rank FROM events) "
            "SELECT e.rank FROM ranked e"
        ) == set()

    def test_vendor_storage_modules_are_excluded_deliberately(self):
        """Cursor's own tables are outside the DDL by design (CoPlan 6.4)."""
        assert "cursor_source.py" in _VENDOR_STORAGE_MODULES
        assert all(
            path.name not in _VENDOR_STORAGE_MODULES for path in _python_files()
        )

    def test_the_check_reads_every_sql_holding_module(self):
        """A guard that scanned nothing would pass vacuously."""
        names = {path.name for path in _python_files()}
        assert {"store.py", "query_api.py", "query_reports.py"} <= names
