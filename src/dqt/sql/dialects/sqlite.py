"""
dqt.sql.dialects.sqlite
=======================

The SQLite dialect: identifier quoting, the ``file:...?mode=ro`` read-only
connection form, catalogue introspection via ``sqlite_master`` plus
``PRAGMA table_info``, and the Python-backed ``REGEXP`` function SQLite does
not ship (`DQT-04`).

This module also owns the compiled-pattern cache that ``REGEXP`` needs. That
cache lives here rather than in ``rules.py`` because it is SQLite's problem,
not the rule engine's: PostgreSQL evaluates ``~`` inside the server and never
compiles a pattern in Python at all.

Known scaling limit, restated where the code lives. SQLite's ``REGEXP`` is a
Python callback invoked once per row, so a ``regex`` rule on SQLite is a full
scan with per-row Python overhead. That is a property of SQLite, not a defect
in DQT, and it is why the PostgreSQL dialect uses the native operator instead.
"""

from __future__ import annotations

import functools
import re
import sqlite3
from collections.abc import Sequence
from typing import Any

from dqt.common.models import ConnectionConfig
from dqt.sql.dialects.base import (
    ColumnMetadata,
    ReadOnlyEnforcement,
    ansi_select_aggregates_sql,
    quote_with_doubled_delimiter,
    validate_row_limit,
)

# Upper bound on pattern length accepted for compilation. This is not a
# performance-tuning knob so much as a config-sanity guard: a rule file is
# trusted input in this project (there is no raw-SQL rule type, and rule
# files are not accepted from untrusted users), but a many-kilobyte
# "pattern" is never an intentional regex and is far more likely to be a
# copy-paste accident that is cheaper to reject up front than to hand to
# ``re.compile``.
REGEX_PATTERN_MAX_LENGTH = 1000

# Bounds the compiled-pattern cache so a rule file with many distinct (or
# templated/generated) regex patterns cannot grow this process-lifetime
# cache without limit.
REGEX_CACHE_MAXSIZE = 256

# SQLite has no schema concept; every user table lives in the connection's
# implicit default schema, which SQLite itself names "main". DQT reports that
# name so a discovered table always carries a schema, but suppresses it when
# building a table reference, because ``"main"."t"`` is not what a DBA writes.
IMPLICIT_SCHEMA_NAME = "main"

# Base tables only, catalogue tables excluded, ordered so discovery output is
# deterministic across runs (ENGINEERING-STANDARDS.md §1.8).
TABLE_LIST_SQL = """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """


@functools.lru_cache(maxsize=REGEX_CACHE_MAXSIZE)
def compile_regex_pattern(pattern: str) -> re.Pattern[str]:
    """Compile *pattern* into a :class:`re.Pattern`, cached and length-bounded.

    This is the single place a ``regex`` rule's pattern is turned into a
    compiled expression, so that the ``REGEXP`` callback and the up-front
    validation performed when the query is built share one cache, and the
    length guard and error message are written once.

    Args:
        pattern: Regular expression source, as written in ``params.pattern``
            of a rule file.

    Returns:
        The compiled pattern, memoized by :func:`functools.lru_cache` (see
        ``REGEX_CACHE_MAXSIZE`` for the bound).

    Raises:
        ValueError: If *pattern* is longer than ``REGEX_PATTERN_MAX_LENGTH``,
            or is not a syntactically valid Python regular expression. This
            is deliberately :class:`ValueError`: a malformed pattern is a
            rule-configuration error, not a data issue, and must not be
            reported as if every row failed the check. (Once `DQT-09` lands a
            shared exception hierarchy this should become that hierarchy's
            ``RuleEvaluationError``; tracked there, not here.)

    Example::

        compiled = compile_regex_pattern(r"^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$")
        assert compiled.search("a@b.com") is not None
    """
    if len(pattern) > REGEX_PATTERN_MAX_LENGTH:
        raise ValueError(
            f"regex rule pattern is {len(pattern)} characters, which exceeds the "
            f"maximum of {REGEX_PATTERN_MAX_LENGTH}. Refusing to compile it."
        )
    try:
        return re.compile(pattern)
    except re.error as exc:
        raise ValueError(f"Invalid regex pattern {pattern!r}: {exc}") from exc


def sqlite_regexp(pattern: str, value: object) -> bool | None:
    """Implement SQLite's ``REGEXP`` operator via Python's :mod:`re`.

    Registered as the connection-wide ``REGEXP(X, Y)`` function by
    :meth:`SqliteDialect.connect`. SQLite rewrites the infix expression
    ``value REGEXP pattern`` into the function call ``REGEXP(pattern,
    value)`` — the pattern comes first, the value second — so this
    function's parameter order mirrors that call exactly. Getting this
    backwards would not raise; it would silently invert every match.

    Args:
        pattern: The regex pattern (SQLite's first argument, ``X`` in
            ``REGEXP(X, Y)``).
        value: The column value being tested (SQLite's second argument).
            May be any SQLite-native Python type, or ``None``.

    Returns:
        ``True`` if *value* (coerced to ``str``) matches *pattern* anywhere
        (via :func:`re.search`); ``False`` if it does not; ``None`` if
        *value* is SQL ``NULL``.

    Raises:
        ValueError: If *pattern* is invalid or too long — see
            :func:`compile_regex_pattern`. SQLite reports this to the caller
            as ``sqlite3.OperationalError: user-defined function raised
            exception``; :meth:`SqliteDialect.regex_not_matching_predicate`
            avoids that by validating the pattern before the query is issued.

    Example::

        assert sqlite_regexp("^a", "abc") is True
        assert sqlite_regexp("^a", "zzz") is False
        assert sqlite_regexp("^a", None) is None
    """
    if value is None:
        return None
    compiled = compile_regex_pattern(pattern)
    return compiled.search(str(value)) is not None


class SqliteDialect:
    """SQLite's implementation of the :class:`~dqt.sql.dialects.base.Dialect` protocol.

    SQLite is DQT's development and test target. Two of its properties shape
    this class: it has no schema namespace (so ``qualified_identifier``
    suppresses the implicit ``main``), and it has no built-in ``REGEXP``
    (so ``connect`` registers one).

    Attributes:
        name: Always ``"sqlite"``.
        parameter_placeholder: Always ``"?"`` — the stdlib ``sqlite3``
            driver uses the ``qmark`` paramstyle.
        read_only_enforcement: ``DRIVER_ENFORCED``. A write through a
            ``mode=ro`` connection raises ``sqlite3.OperationalError``.

    Example:
        dialect = SqliteDialect()
        assert dialect.quote_identifier("orders") == '"orders"'
    """

    name = "sqlite"
    #: Stable for the row's lifetime, and every table has one unless it was
    #: created WITHOUT ROWID.
    physical_row_locator: str | None = "rowid"

    parameter_placeholder = "?"
    read_only_enforcement = ReadOnlyEnforcement.DRIVER_ENFORCED

    def connect(self, connection_config: ConnectionConfig) -> Any:
        """Open a SQLite connection, read-only unless explicitly opted out.

        When ``connection_config.read_only`` is ``True`` (the default) the
        database is opened through the ``file:<path>?mode=ro`` URI form, so
        any ``INSERT``/``UPDATE``/``DELETE`` raises
        ``sqlite3.OperationalError: attempt to write a readonly database``.
        A path of ``":memory:"`` is a documented exception: a fresh
        in-memory database created by this call is never a persistent asset,
        so ``mode=ro`` would only make it permanently empty and unusable.

        A consequence of the URI form: unlike a plain
        ``sqlite3.connect(path)``, this does **not** create the database file
        if it does not already exist — it raises ``sqlite3.OperationalError``
        instead. That is deliberate (`DQT-03`): silently creating a database
        file you were told to treat as read-only is itself a surprise.

        Every connection returned here, read-only or not, has
        :func:`sqlite_regexp` registered as the ``REGEXP`` function
        (`DQT-04`), because SQLite dispatches its ``REGEXP`` operator to a
        user-defined function rather than implementing one. Registering a
        function is not a write and is unaffected by ``mode=ro``.

        Args:
            connection_config: Validated connection configuration whose DSN
                starts with ``sqlite://`` or ``sqlite:///``.

        Returns:
            An open :class:`sqlite3.Connection` with
            :class:`sqlite3.Row` as its row factory and ``REGEXP``
            registered.

        Raises:
            sqlite3.OperationalError: If a read-only open names a file that
                does not exist.

        Example:
            from dqt.common.models import ConnectionConfig

            config = ConnectionConfig(id="t", dsn="sqlite:///:memory:")
            connection = SqliteDialect().connect(config)
            connection.close()
        """
        dsn = connection_config.dsn
        database_path = (
            dsn[len("sqlite:///") :] if dsn.startswith("sqlite:///") else dsn[len("sqlite://") :]
        )
        if connection_config.read_only and database_path != ":memory:":
            connection = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
        else:
            connection = sqlite3.connect(database_path)
        connection.row_factory = sqlite3.Row
        connection.create_function("REGEXP", 2, sqlite_regexp)
        return connection

    def quote_identifier(self, name: str) -> str:
        """Quote one identifier using ANSI double quotes.

        Args:
            name: Raw identifier (schema, table, or column name).

        Returns:
            The identifier in double quotes, with embedded double quotes
            doubled.

        Example:
            assert SqliteDialect().quote_identifier('a"b') == '"a""b"'
        """
        return quote_with_doubled_delimiter(name, '"')

    def qualified_identifier(self, schema_name: str | None, table_name: str) -> str:
        """Return a quoted table reference, suppressing SQLite's implicit schema.

        Args:
            schema_name: Schema name. ``None`` and ``"main"`` both produce an
                unqualified reference, because ``main`` is the name SQLite
                gives its implicit default schema rather than a schema a DBA
                chose.
            table_name: Table name.

        Returns:
            ``"schema"."table"`` when a real schema qualifier applies,
            otherwise just ``"table"``.

        Example:
            assert SqliteDialect().qualified_identifier("main", "orders") == '"orders"'
        """
        if schema_name and schema_name != IMPLICIT_SCHEMA_NAME:
            return f"{self.quote_identifier(schema_name)}.{self.quote_identifier(table_name)}"
        return self.quote_identifier(table_name)

    def fetch_column_metadata(self, connection: Any) -> list[ColumnMetadata]:
        """Read every user table's columns from ``sqlite_master`` and ``PRAGMA``.

        This costs one query to list tables plus one ``PRAGMA table_info``
        per table. SQLite exposes no single catalogue view that would let it
        be one query, so the round-trip count is a property of SQLite rather
        than a choice made here.

        Args:
            connection: An open SQLite connection.

        Returns:
            Column rows, tables in name order and columns in the order the
            table declares them. Every row reports ``schema_name="main"``.

        Example:
            rows = SqliteDialect().fetch_column_metadata(connection)
            assert all(row.schema_name == "main" for row in rows)
        """
        table_names = [row[0] for row in connection.execute(TABLE_LIST_SQL).fetchall()]
        columns: list[ColumnMetadata] = []
        for table_name in table_names:
            # PRAGMA does not accept a bound parameter in place of the table
            # name -- verified empirically: sqlite3 raises OperationalError:
            # near "?": syntax error. The name is quoted instead, through the
            # single quoting authority.
            pragma_rows = connection.execute(
                f"PRAGMA table_info({self.quote_identifier(table_name)})"
            ).fetchall()
            columns.extend(
                ColumnMetadata(
                    schema_name=IMPLICIT_SCHEMA_NAME,
                    table_name=table_name,
                    column_name=row[1],
                    data_type=row[2] or "UNKNOWN",
                    nullable=(row[3] == 0),
                    # PRAGMA table_info's `pk` column: 0 when the column is
                    # not part of the key, otherwise its 1-based position.
                    is_primary_key=bool(row[5]),
                )
                for row in pragma_rows
            )
        return columns

    def select_aggregates_sql(
        self,
        qualified_table: str,
        expressions: Sequence[str],
        where_clause: str | None = None,
    ) -> str:
        """Build a set-based aggregate query in ANSI form.

        Args:
            qualified_table: An already-quoted table reference.
            expressions: Aggregate expressions to project. Must not be empty.
            where_clause: Optional predicate body, without ``WHERE``.

        Returns:
            The assembled ``SELECT`` statement.

        Raises:
            ValueError: If *expressions* is empty.

        Example:
            sql = SqliteDialect().select_aggregates_sql('"t"', ["COUNT(*)"])
            assert sql == 'SELECT COUNT(*) FROM "t"'
        """
        return ansi_select_aggregates_sql(qualified_table, expressions, where_clause)

    def limited_select_sql(
        self,
        qualified_table: str,
        expressions: Sequence[str],
        where_clause: str | None = None,
        limit: int | None = None,
        order_by: Sequence[str] | None = None,
    ) -> str:
        """Build a ``SELECT`` bounded by SQLite's trailing ``LIMIT`` clause.

        Args:
            qualified_table: An already-quoted table reference.
            expressions: Expressions to project. Must not be empty.
            where_clause: Optional predicate body, without ``WHERE``.
            limit: Maximum rows, or ``None`` for no limit.
            order_by: Already-quoted ordering terms, or None for no
                ordering. A bounded read with no ordering returns an
                arbitrary page, which is fine for issue evidence and
                useless for paging: "any twenty rows" cannot be
                resumed from.

        Returns:
            The assembled statement with ``LIMIT <n>`` appended when *limit*
            is given.

        Raises:
            ValueError: If *expressions* is empty, or *limit* is not positive.

        Example:
            sql = SqliteDialect().limited_select_sql('"t"', ["*"], limit=5)
            assert sql == 'SELECT * FROM "t" LIMIT 5'
        """
        validate_row_limit(limit)
        statement = ansi_select_aggregates_sql(qualified_table, expressions, where_clause)
        if order_by:
            statement = f"{statement} ORDER BY {', '.join(order_by)}"
        if limit is None:
            return statement
        return f"{statement} LIMIT {limit}"

    def sampled_table_expression(
        self,
        qualified_table: str,
        strategy: str,
        limit: int,
        seed: int | None,
    ) -> str:
        """Return a table reference yielding at most *limit* rows.

        Args:
            qualified_table: An already-quoted table reference.
            strategy: ``"random"`` or ``"first_n"``.
            limit: Maximum rows. Must be positive.
            seed: Requested random seed, or None.

        Returns:
            An aliased subquery usable as a table reference.

        Raises:
            ValueError: If the strategy is unknown, the limit is not
                positive, or a seed is given for a random sample.

        Example:
            expression = dialect.sampled_table_expression('"t"', "first_n", 10, None)
        """
        raise NotImplementedError

    def regex_not_matching_predicate(self, quoted_column: str, pattern: str) -> str:
        """Build a "value does not match" predicate using SQLite's ``REGEXP``.

        *pattern* is compiled here, before any query runs, so that a
        malformed pattern surfaces as a configuration error rather than as
        ``sqlite3.OperationalError: user-defined function raised exception``
        mid-scan — and, more importantly, so no caller ever receives a row
        count computed against a pattern that failed to compile.

        Args:
            quoted_column: An already-quoted column reference.
            pattern: Regular expression source. Validated here; bound as a
                parameter by the caller, never interpolated.

        Returns:
            ``<col> IS NOT NULL AND <col> NOT REGEXP ?`` — one ``qmark``
            placeholder for the pattern.

        Raises:
            ValueError: If *pattern* is not a valid, length-bounded regular
                expression — see :func:`compile_regex_pattern`.

        Example:
            predicate = SqliteDialect().regex_not_matching_predicate('"e"', "^a")
            assert predicate == '"e" IS NOT NULL AND "e" NOT REGEXP ?'
        """
        compile_regex_pattern(pattern)  # raise ValueError before querying, not during
        return (
            f"{quoted_column} IS NOT NULL AND {quoted_column} NOT REGEXP "
            f"{self.parameter_placeholder}"
        )

    def approximate_distinct_expression(self, quoted_column: str) -> str | None:
        """Report that SQLite has no approximate distinct count.

        Args:
            quoted_column: An already-quoted column reference (unused).

        Returns:
            Always ``None``. SQLite ships no sketch-based distinct
            approximation, so a caller wanting a distinct count must use an
            exact ``COUNT(DISTINCT ...)`` and accept its cost.

        Example:
            assert SqliteDialect().approximate_distinct_expression('"c"') is None
        """
        return None


# The single SQLite dialect instance. Dialects are stateless, so one shared
# instance is correct and avoids handing out objects that could drift apart.
SQLITE = SqliteDialect()

__all__ = [
    "IMPLICIT_SCHEMA_NAME",
    "REGEX_CACHE_MAXSIZE",
    "REGEX_PATTERN_MAX_LENGTH",
    "SQLITE",
    "TABLE_LIST_SQL",
    "SqliteDialect",
    "compile_regex_pattern",
    "sqlite_regexp",
]
