"""
dqt.sql.dialects.sqlserver
==========================

The Microsoft SQL Server dialect: bracket-delimited identifiers, ``TOP (n)``
row limiting, ``INFORMATION_SCHEMA`` introspection restricted to base tables,
``APPROX_COUNT_DISTINCT``, and an explicit refusal to pretend it has regular
expressions.

Driver. ``pyodbc``, installed via the ``sqlserver`` extra. It is imported
inside :meth:`SqlServerDialect.connect`, never at module import time, so that
``import dqt`` works on a machine that has never heard of ODBC.

Three ways SQL Server differs structurally, not cosmetically, from the two
dialects DQT already supported — these are the reasons this dialect exists as
a third implementation rather than a configuration of an existing one:

1. **Identifier delimiters are asymmetric.** ``[name]``, with ``]`` doubled.
   The shared "double the quote character" algorithm the other two dialects
   use does not apply.
2. **The row limit is a prefix, not a suffix.** ``SELECT TOP (n) ...``, not
   ``... LIMIT n``. A dialect layer that only varied strings could not
   express this.
3. **There is no regular-expression operator at all.** Not a different
   spelling of one — none. See
   :meth:`SqlServerDialect.regex_not_matching_predicate`.

Unexercised against a real server. No SQL Server instance and no ``pyodbc``
installation exist in this repository's CI or development environment.
Everything here that constructs SQL or makes a decision is unit-tested as a
pure function against hand-written expected strings; everything that requires
a live connection — :meth:`SqlServerDialect.connect` and
:meth:`SqlServerDialect.fetch_column_metadata` — has never been run against
SQL Server. That gap is stated here, in the module that carries it, and not
only in a pull-request description that a future reader will not have.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from urllib.parse import parse_qsl, unquote, urlsplit

from dqt.common.models import ConnectionConfig
from dqt.sql.dialects.base import (
    ColumnMetadata,
    ReadOnlyEnforcement,
    ansi_select_aggregates_sql,
    validate_row_limit,
)

# ODBC 3.x connection attributes, by their numeric values from the ODBC
# specification's sqlext.h. They are spelled out numerically rather than taken
# from `pyodbc`'s namespace deliberately: the numbers are fixed by the ODBC
# standard and verifiable against it, whereas which SQL_* constants a given
# pyodbc build re-exports is a property of that build. Getting an attribute
# name wrong would surface as an AttributeError on a code path this repository
# cannot execute.
ODBC_SQL_ATTR_ACCESS_MODE = 101
ODBC_SQL_MODE_READ_ONLY = 1

# The ODBC driver assumed when a DSN does not name one. Driver 18 is the
# current Microsoft release; naming a default keeps the common DSN short
# without hiding which driver was chosen -- it appears in the generated
# connection string.
DEFAULT_ODBC_DRIVER = "ODBC Driver 18 for SQL Server"

# Query parameters this dialect understands in an ``mssql://`` DSN. Anything
# else is rejected rather than forwarded: ODBC connection strings are
# semicolon-delimited key/value pairs, so silently passing arbitrary
# user-supplied text into one would be a connection-string injection.
SUPPORTED_DSN_QUERY_KEYS = ("driver", "encrypt", "trust_server_certificate")

# Base tables only (views excluded, matching the other two dialects), system
# schemas excluded, ordered so discovery output is deterministic.
# Primary-key columns are LEFT JOINed so a table without a key still returns
# its columns rather than vanishing from discovery (NEW-M).
COLUMN_METADATA_SQL = """
                SELECT
                    c.TABLE_SCHEMA,
                    c.TABLE_NAME,
                    c.COLUMN_NAME,
                    c.DATA_TYPE,
                    c.IS_NULLABLE,
                    CASE WHEN k.COLUMN_NAME IS NULL THEN 0 ELSE 1 END
                        AS IS_PRIMARY_KEY
                FROM INFORMATION_SCHEMA.COLUMNS AS c
                LEFT JOIN INFORMATION_SCHEMA.TABLE_CONSTRAINTS AS tc
                  ON tc.TABLE_SCHEMA = c.TABLE_SCHEMA
                 AND tc.TABLE_NAME = c.TABLE_NAME
                 AND tc.CONSTRAINT_TYPE = 'PRIMARY KEY'
                LEFT JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE AS k
                  ON k.CONSTRAINT_NAME = tc.CONSTRAINT_NAME
                 AND k.TABLE_SCHEMA = c.TABLE_SCHEMA
                 AND k.TABLE_NAME = c.TABLE_NAME
                 AND k.COLUMN_NAME = c.COLUMN_NAME
                JOIN INFORMATION_SCHEMA.TABLES AS t
                  ON t.TABLE_CATALOG = c.TABLE_CATALOG
                 AND t.TABLE_SCHEMA = c.TABLE_SCHEMA
                 AND t.TABLE_NAME = c.TABLE_NAME
                WHERE t.TABLE_TYPE = 'BASE TABLE'
                  AND c.TABLE_SCHEMA NOT IN ('sys', 'INFORMATION_SCHEMA')
                ORDER BY c.TABLE_SCHEMA, c.TABLE_NAME, c.ORDINAL_POSITION
                """


def odbc_connection_string(dsn: str) -> str:
    """Translate an ``mssql://`` DSN into an ODBC connection string.

    DQT's DSNs are URLs; ``pyodbc`` wants semicolon-delimited ODBC key/value
    pairs. This is the whole of that translation, kept as a pure function so
    it can be tested against hand-written expected strings without a driver
    or a server.

    The accepted form is::

        mssql://[user[:password]@]host[:port]/database[?key=value&...]

    with ``sqlserver://`` accepted as an alias. When no user is given,
    ``Trusted_Connection=yes`` is emitted so the connection uses Windows
    integrated authentication. Recognised query keys are listed in
    ``SUPPORTED_DSN_QUERY_KEYS``.

    Args:
        dsn: The DSN to translate.

    Returns:
        An ODBC connection string, with keys emitted in a fixed order
        (``DRIVER``, ``SERVER``, ``DATABASE``, credentials, then options) so
        the output is deterministic and testable.

    Raises:
        ValueError: If the DSN does not use an ``mssql``/``sqlserver``
            scheme, names no host or no database, carries a query key that is
            not in ``SUPPORTED_DSN_QUERY_KEYS``, or carries a value
            containing ``;``, ``{`` or ``}`` — those characters would let a
            value break out of its ODBC key/value pair.

    Example:
        connection_string = odbc_connection_string("mssql://sa:pw@localhost:1433/dqt")
        assert "SERVER=localhost,1433" in connection_string
        assert "DATABASE=dqt" in connection_string
    """
    parts = urlsplit(dsn)
    if parts.scheme not in ("mssql", "sqlserver"):
        raise ValueError(f"SQL Server DSN must use the 'mssql' or 'sqlserver' scheme, got {dsn!r}.")
    if not parts.hostname:
        raise ValueError(f"SQL Server DSN names no host: {dsn!r}.")
    database = parts.path.lstrip("/")
    if not database:
        raise ValueError(f"SQL Server DSN names no database: {dsn!r}.")

    options = {key.lower(): value for key, value in parse_qsl(parts.query, keep_blank_values=True)}
    unsupported = sorted(set(options) - set(SUPPORTED_DSN_QUERY_KEYS))
    if unsupported:
        raise ValueError(
            f"Unsupported SQL Server DSN query parameter(s): {', '.join(unsupported)}. "
            f"Supported: {', '.join(SUPPORTED_DSN_QUERY_KEYS)}."
        )

    username = unquote(parts.username) if parts.username else None
    password = unquote(parts.password) if parts.password else None
    server = parts.hostname if parts.port is None else f"{parts.hostname},{parts.port}"

    pairs: list[tuple[str, str]] = [
        ("DRIVER", options.get("driver", DEFAULT_ODBC_DRIVER)),
        ("SERVER", server),
        ("DATABASE", database),
    ]
    if username is None:
        pairs.append(("Trusted_Connection", "yes"))
    else:
        pairs.append(("UID", username))
        pairs.append(("PWD", password or ""))
    pairs.append(("Encrypt", options.get("encrypt", "yes")))
    pairs.append(("TrustServerCertificate", options.get("trust_server_certificate", "no")))

    for key, value in pairs:
        if any(character in value for character in ";{}"):
            raise ValueError(
                f"SQL Server DSN value for {key} must not contain ';', '{{' or '}}'; "
                "those characters would break out of the ODBC connection string."
            )
    return ";".join(
        f"{key}={{{value}}}" if key == "DRIVER" else f"{key}={value}" for key, value in pairs
    )


def read_only_connect_attributes(read_only: bool) -> dict[int, int]:
    """Return the ODBC pre-connection attributes for a read-only request.

    Kept separate from :meth:`SqlServerDialect.connect` so the decision can
    be tested without ``pyodbc`` installed — which matters here more than
    elsewhere, because this is the one dialect whose read-only story is
    weaker than DQT's other two and therefore the one most worth pinning
    down in a test.

    Args:
        read_only: Whether the caller asked for a read-only connection.

    Returns:
        ``{ODBC_SQL_ATTR_ACCESS_MODE: ODBC_SQL_MODE_READ_ONLY}`` when
        *read_only* is true, otherwise an empty mapping. The attribute is a
        **hint**: the ODBC specification permits a driver to accept it and
        still allow writes, and the SQL Server driver does not enforce it at
        the server. It is set because it costs nothing and some tools honour
        it, not because it constitutes enforcement — see
        :attr:`SqlServerDialect.read_only_enforcement`.

    Example:
        assert read_only_connect_attributes(False) == {}
        assert read_only_connect_attributes(True) == {101: 1}
    """
    if not read_only:
        return {}
    return {ODBC_SQL_ATTR_ACCESS_MODE: ODBC_SQL_MODE_READ_ONLY}


class SqlServerDialect:
    """SQL Server's implementation of the ``Dialect`` protocol.

    Attributes:
        name: Always ``"sqlserver"``. Both the ``mssql://`` and
            ``sqlserver://`` DSN schemes resolve to it.
        parameter_placeholder: Always ``"?"`` — ``pyodbc`` uses the ``qmark``
            paramstyle, the same as ``sqlite3``.
        read_only_enforcement: ``ADVISORY``, and this is the one place in
            DQT where that value is used. SQL Server has no equivalent of
            SQLite's ``mode=ro`` or PostgreSQL's read-only session: the ODBC
            access-mode attribute is a hint the driver may ignore, and
            ``ApplicationIntent=ReadOnly`` only routes to an availability
            group's readable secondary rather than forbidding writes. On this
            dialect, ``read_only=True`` therefore rests on DQT's own refusal
            to build mutating SQL plus the privileges of the login the
            operator supplies. Grant that login ``db_datareader`` and nothing
            more.

    Example:
        dialect = SqlServerDialect()
        assert dialect.quote_identifier("orders") == "[orders]"
    """

    name = "sqlserver"
    #: %%physloc%% is likewise physical and moves. A primary key is required.
    physical_row_locator: str | None = None

    parameter_placeholder = "?"
    read_only_enforcement = ReadOnlyEnforcement.ADVISORY

    def connect(self, connection_config: ConnectionConfig) -> Any:
        """Open a ``pyodbc`` connection to SQL Server.

        Autocommit is left off so that nothing reaches the server implicitly,
        and the ODBC read-only access-mode hint is applied when
        ``connection_config.read_only`` is true. Read
        :attr:`read_only_enforcement` before relying on that hint: unlike
        DQT's other two dialects, it is not enforcement.

        Args:
            connection_config: Validated connection configuration whose DSN
                starts with ``mssql://`` or ``sqlserver://``.

        Returns:
            An open ``pyodbc.Connection`` with ``autocommit`` disabled.

        Raises:
            ImportError: If ``pyodbc`` is not installed. Install it with
                ``pip install 'dqt[sqlserver]'``.
            ValueError: If the DSN cannot be translated — see
                :func:`odbc_connection_string`.

        Example:
            from dqt.common.models import ConnectionConfig

            config = ConnectionConfig(id="wh", dsn="mssql://sa:pw@host/db")
            connection = SqlServerDialect().connect(config)  # requires pyodbc
            connection.close()
        """
        connection_string = odbc_connection_string(connection_config.dsn)
        try:
            import pyodbc
        except ImportError as exc:
            raise ImportError(
                "SQL Server support requires the 'pyodbc' package. "
                "Install it with: pip install 'dqt[sqlserver]'"
            ) from exc
        return pyodbc.connect(
            connection_string,
            autocommit=False,
            attrs_before=read_only_connect_attributes(connection_config.read_only),
        )

    def quote_identifier(self, name: str) -> str:
        """Quote one identifier using T-SQL's bracket delimiters.

        Brackets are used rather than ANSI double quotes because they are
        correct regardless of the session's ``QUOTED_IDENTIFIER`` setting,
        whereas a double-quoted identifier becomes a string literal when that
        setting is ``OFF``.

        The escaping is asymmetric: only the closing bracket can terminate
        the identifier, so only ``]`` is doubled. A ``[`` inside the name is
        an ordinary character.

        Args:
            name: Raw identifier (schema, table, or column name).

        Returns:
            The identifier in brackets, with every embedded ``]`` doubled.

        Example:
            assert SqlServerDialect().quote_identifier("a]b") == "[a]]b]"
        """
        # Asymmetric delimiters: only "]" can terminate the identifier, so
        # only "]" is doubled. This is why the shared, symmetric
        # quote_with_doubled_delimiter helper does not apply to this dialect.
        return "[" + name.replace("]", "]]") + "]"

    def qualified_identifier(self, schema_name: str | None, table_name: str) -> str:
        """Return a bracketed, schema-qualified table reference.

        SQL Server schemas are real, and its default schema is ``dbo``, not
        SQLite's ``main``; no schema name is suppressed here.

        Args:
            schema_name: Schema name, or ``None`` to leave the reference
                unqualified and let the login's default schema resolve it.
            table_name: Table name.

        Returns:
            ``[schema].[table]`` whenever *schema_name* is given, otherwise
            just ``[table]``.

        Example:
            assert SqlServerDialect().qualified_identifier("dbo", "orders") == "[dbo].[orders]"
        """
        if schema_name:
            return f"{self.quote_identifier(schema_name)}.{self.quote_identifier(table_name)}"
        return self.quote_identifier(table_name)

    def fetch_column_metadata(self, connection: Any) -> list[ColumnMetadata]:
        """Read every user column from ``INFORMATION_SCHEMA``.

        Costs exactly one round trip. Views are excluded by the join on
        ``TABLE_TYPE = 'BASE TABLE'``, matching what the SQLite and
        PostgreSQL dialects report.

        Args:
            connection: An open ``pyodbc`` connection.

        Returns:
            Column rows ordered by schema, table, and ordinal position.

        Example:
            rows = SqlServerDialect().fetch_column_metadata(connection)
            assert all(row.schema_name != "sys" for row in rows)
        """
        cursor = connection.cursor()
        try:
            cursor.execute(COLUMN_METADATA_SQL)
            rows = cursor.fetchall()
        finally:
            cursor.close()
        return [
            ColumnMetadata(
                schema_name=schema_name,
                table_name=table_name,
                column_name=column_name,
                data_type=data_type,
                nullable=(is_nullable == "YES"),
                is_primary_key=bool(is_primary_key),
            )
            for (
                schema_name,
                table_name,
                column_name,
                data_type,
                is_nullable,
                is_primary_key,
            ) in rows
        ]

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
            sql = SqlServerDialect().select_aggregates_sql("[t]", ["COUNT(*)"])
            assert sql == "SELECT COUNT(*) FROM [t]"
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
        """Build a ``SELECT`` bounded by T-SQL's ``TOP (n)`` prefix.

        This is where the dialect abstraction earns its place: the limit is a
        prefix on the projection here and a suffix on the statement in both
        other dialects, so a caller cannot bound its result set by appending
        a string.

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
            ``SELECT TOP (<n>) <expressions> FROM <table> [WHERE ...]`` when
            *limit* is given, otherwise the unbounded statement.

        Raises:
            ValueError: If *expressions* is empty, or *limit* is not positive.

        Example:
            sql = SqlServerDialect().limited_select_sql("[t]", ["*"], limit=5)
            assert sql == "SELECT TOP (5) * FROM [t]"
        """
        validate_row_limit(limit)
        if limit is None:
            statement = ansi_select_aggregates_sql(qualified_table, expressions, where_clause)
        else:
            if not expressions:
                raise ValueError("A SELECT needs at least one expression to project.")
            statement = f"SELECT TOP ({limit}) {', '.join(expressions)} FROM {qualified_table}"
            if where_clause:
                statement = f"{statement} WHERE {where_clause}"
        if order_by:
            statement = f"{statement} ORDER BY {', '.join(order_by)}"
        return statement

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
        if limit <= 0:
            raise ValueError(f"A sample needs a positive limit; got {limit}.")
        if strategy not in ("random", "first_n"):
            raise ValueError(f"Unknown sampling strategy {strategy!r}. Use 'random' or 'first_n'.")
        if seed is not None and strategy == "random":
            raise ValueError(
                "A random sample cannot take a seed on this dialect. PostgreSQL "
                "needs a separate setseed() call, SQLite has no seedable "
                "RANDOM(), and SQL Server's NEWID() takes none -- so honouring "
                "the seed is impossible here and ignoring it would produce an "
                "unseeded sample while the config said otherwise. Remove the "
                "seed, or use strategy='first_n', which is already reproducible."
            )
        # TOP on the projection and NEWID() for the shuffle: T-SQL has
        # neither LIMIT nor RANDOM(), which is the whole reason this is a
        # dialect method rather than a shared string.
        order = " ORDER BY NEWID()" if strategy == "random" else ""
        return f"(SELECT TOP ({limit}) * FROM {qualified_table}{order}) AS dqt_sample"

    def regex_not_matching_predicate(self, quoted_column: str, pattern: str) -> str:
        """Refuse: SQL Server has no regular-expression operator.

        T-SQL's ``LIKE`` is a wildcard matcher, not a regular-expression
        engine, and mapping a regex onto it would silently change what a
        ``regex`` rule means — a data-quality tool reporting a
        different-but-plausible answer is worse than one reporting none.
        SQL Server 2025 adds ``REGEXP_LIKE``; when DQT gains a way to know a
        server's version, this method is where that support belongs.

        Because :func:`dqt.sql.rules._evaluate_rule` converts an evaluation
        exception into an ``error``-severity ``DQIssue``, the visible effect
        of this refusal is that a ``regex`` rule targeting SQL Server reports
        an explicit error naming the limitation, per target. It never reports
        zero violations, and it never reports every row as violating.

        Args:
            quoted_column: An already-quoted column reference (unused).
            pattern: Regular expression source (unused).

        Returns:
            Never returns.

        Raises:
            ValueError: Always. (``ValueError`` matches what the rule engine
                already raises for unsupported rule configuration; `DQT-09`
                should re-home this on the package exception hierarchy.)

        Example:
            import pytest

            with pytest.raises(ValueError, match="no regular-expression"):
                SqlServerDialect().regex_not_matching_predicate("[e]", "^a")
        """
        raise ValueError(
            "SQL Server has no regular-expression operator, so DQT cannot evaluate a "
            "'regex' rule against it. T-SQL's LIKE is a wildcard matcher, not a regular "
            "expression, and mapping one onto the other would answer a different "
            "question while looking like it answered this one. Use a 'range', "
            "'NOT NULL' or 'UNIQUE' rule here instead."
        )

    def approximate_distinct_expression(self, quoted_column: str) -> str | None:
        """Return SQL Server's built-in approximate distinct count.

        ``APPROX_COUNT_DISTINCT`` (SQL Server 2019 and later) is a
        HyperLogLog-backed estimate with a documented error bound, intended
        for exactly the case DQT cares about: a distinct count over a large
        column where an exact ``COUNT(DISTINCT ...)`` is too expensive.

        Args:
            quoted_column: An already-quoted column reference.

        Returns:
            ``APPROX_COUNT_DISTINCT(<column>)``. This is the only dialect of
            the three that returns an expression rather than ``None``, which
            is why the protocol returns an optional rather than assuming the
            capability is universal.

        Example:
            expression = SqlServerDialect().approximate_distinct_expression("[c]")
            assert expression == "APPROX_COUNT_DISTINCT([c])"
        """
        return f"APPROX_COUNT_DISTINCT({quoted_column})"


# The single SQL Server dialect instance; dialects are stateless.
SQLSERVER = SqlServerDialect()

__all__ = [
    "COLUMN_METADATA_SQL",
    "DEFAULT_ODBC_DRIVER",
    "ODBC_SQL_ATTR_ACCESS_MODE",
    "ODBC_SQL_MODE_READ_ONLY",
    "SQLSERVER",
    "SUPPORTED_DSN_QUERY_KEYS",
    "SqlServerDialect",
    "odbc_connection_string",
    "read_only_connect_attributes",
]
