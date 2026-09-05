"""
dqt.sql.dialects.postgresql
===========================

The PostgreSQL dialect: ANSI identifier quoting, a read-only session, the
``information_schema.columns`` introspection query, and the native ``~``
regular-expression operator.

Driver. This module uses ``psycopg`` (v3) and nothing else. Before `DQT-08`
the codebase opened PostgreSQL connections with ``psycopg`` in one module and
``psycopg2`` in another — two drivers, two read-only mechanisms, one
codebase. ``psycopg`` v3 is the maintained line and has a first-class
read-only property, so it is the survivor; ``psycopg2-binary`` is gone from
the ``postgres`` extra.

Untested against a real server. There is no PostgreSQL instance in this
repository's CI and no PostgreSQL driver installed in its development
environment, so everything below that requires a live connection is
unexercised. The pure SQL-construction methods are unit-tested; the
connection and introspection paths are not.
"""

from __future__ import annotations

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

# One query returns every user column, already ordered, so discovery costs a
# single round trip regardless of how many tables the database holds.
# The primary-key columns are LEFT JOINed rather than fetched by a subquery so
# that a table without a primary key still returns its columns instead of
# vanishing from discovery. Cleansing needs to know a table has no key
# (NEW-M); it cannot learn that from a table it never sees.
COLUMN_METADATA_SQL = """
                SELECT
                    c.table_schema,
                    c.table_name,
                    c.column_name,
                    c.data_type,
                    c.is_nullable,
                    (k.column_name IS NOT NULL) AS is_primary_key
                FROM information_schema.columns AS c
                LEFT JOIN information_schema.table_constraints AS tc
                    ON tc.table_schema = c.table_schema
                    AND tc.table_name = c.table_name
                    AND tc.constraint_type = 'PRIMARY KEY'
                LEFT JOIN information_schema.key_column_usage AS k
                    ON k.constraint_name = tc.constraint_name
                    AND k.table_schema = c.table_schema
                    AND k.table_name = c.table_name
                    AND k.column_name = c.column_name
                WHERE c.table_schema NOT IN ('information_schema', 'pg_catalog')
                ORDER BY c.table_schema, c.table_name, c.ordinal_position
                """


class PostgresqlDialect:
    """PostgreSQL's implementation of the ``Dialect`` protocol.

    PostgreSQL is DQT's primary production target. It has real schemas, a
    server-side read-only session mode, and a native regular-expression
    operator, so it needs none of SQLite's compensations.

    Attributes:
        name: Always ``"postgresql"``. The ``postgres://`` DSN alias resolves
            to this same name, so downstream code sees one spelling.
        parameter_placeholder: Always ``"%s"`` — ``psycopg`` uses the
            ``pyformat`` paramstyle.
        read_only_enforcement: ``DRIVER_ENFORCED``. A read-only session
            makes the server reject writes.

    Example:
        dialect = PostgresqlDialect()
        assert dialect.quote_identifier("orders") == '"orders"'
    """

    name = "postgresql"
    #: ctid is a physical address: it moves when a row is updated and under
    #: VACUUM FULL. A stored plan holding ctids could address different rows
    #: when applied, so cleansing requires a primary key here instead.
    physical_row_locator: str | None = None

    parameter_placeholder = "%s"
    read_only_enforcement = ReadOnlyEnforcement.DRIVER_ENFORCED

    def connect(self, connection_config: ConnectionConfig) -> Any:
        """Open a ``psycopg`` (v3) connection, read-only unless opted out.

        When ``connection_config.read_only`` is ``True`` (the default) the
        connection's ``read_only`` property is set before any transaction
        begins, which makes every subsequent transaction on it read-only at
        the server rather than by convention.

        Behaviour note for reviewers. Before `DQT-08` the rule engine reached
        PostgreSQL through ``psycopg2`` and issued ``SET SESSION
        CHARACTERISTICS AS TRANSACTION READ ONLY``. This is the ``psycopg``
        v3 equivalent, not a translation of that statement. Both make the
        session read-only; neither is exercised by a test in this repository.

        Args:
            connection_config: Validated connection configuration whose DSN
                starts with ``postgresql://`` or ``postgres://``. The DSN is
                passed through to the driver unmodified.

        Returns:
            An open ``psycopg.Connection``.

        Raises:
            ImportError: If ``psycopg`` is not installed. DQT reports the
                missing optional dependency rather than degrading to a
                different driver or a wrong answer.

        Example:
            from dqt.common.models import ConnectionConfig

            config = ConnectionConfig(id="prod", dsn="postgresql://u:p@host/db")
            connection = PostgresqlDialect().connect(config)  # requires psycopg
            connection.close()
        """
        try:
            import psycopg
        except ImportError as exc:
            raise ImportError(
                "PostgreSQL support requires the 'psycopg' package. "
                "Install it with: pip install 'dqt[postgres]'"
            ) from exc
        connection = psycopg.connect(connection_config.dsn)
        if connection_config.read_only:
            # psycopg v3: setting this outside a transaction makes every
            # subsequent transaction on the session read-only at the server.
            connection.read_only = True
        return connection

    def quote_identifier(self, name: str) -> str:
        """Quote one identifier using ANSI double quotes.

        Args:
            name: Raw identifier (schema, table, or column name).

        Returns:
            The identifier in double quotes, with embedded double quotes
            doubled.

        Example:
            assert PostgresqlDialect().quote_identifier('a"b') == '"a""b"'
        """
        return quote_with_doubled_delimiter(name, '"')

    def qualified_identifier(self, schema_name: str | None, table_name: str) -> str:
        """Return a quoted, schema-qualified table reference.

        Unlike SQLite, PostgreSQL has no implicit schema name to suppress:
        every schema name it reports, ``main`` included, is a real schema a
        DBA created, and dropping it would silently retarget the query at
        whatever the ``search_path`` resolves to.

        Args:
            schema_name: Schema name, or ``None`` to leave the reference
                unqualified and let ``search_path`` resolve it.
            table_name: Table name.

        Returns:
            ``"schema"."table"`` whenever *schema_name* is given, otherwise
            just ``"table"``.

        Example:
            reference = PostgresqlDialect().qualified_identifier("public", "orders")
            assert reference == '"public"."orders"'
        """
        if schema_name:
            return f"{self.quote_identifier(schema_name)}.{self.quote_identifier(table_name)}"
        return self.quote_identifier(table_name)

    def fetch_column_metadata(self, connection: Any) -> list[ColumnMetadata]:
        """Read every user column from ``information_schema.columns``.

        Costs exactly one round trip regardless of table count.

        Args:
            connection: An open ``psycopg`` connection.

        Returns:
            Column rows ordered by schema, table, and ordinal position, with
            the catalogue schemas ``information_schema`` and ``pg_catalog``
            excluded.

        Example:
            rows = PostgresqlDialect().fetch_column_metadata(connection)
            assert all(row.schema_name != "pg_catalog" for row in rows)
        """
        with connection.cursor() as cursor:
            cursor.execute(COLUMN_METADATA_SQL)
            rows = cursor.fetchall()
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
            sql = PostgresqlDialect().select_aggregates_sql('"t"', ["COUNT(*)"])
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
        """Build a ``SELECT`` bounded by PostgreSQL's trailing ``LIMIT`` clause.

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
            sql = PostgresqlDialect().limited_select_sql('"t"', ["*"], limit=5)
            assert sql == 'SELECT * FROM "t" LIMIT 5'
        """
        validate_row_limit(limit)
        statement = ansi_select_aggregates_sql(qualified_table, expressions, where_clause)
        if order_by:
            statement = f"{statement} ORDER BY {', '.join(order_by)}"
        if limit is None:
            return statement
        return f"{statement} LIMIT {limit}"

    def regex_not_matching_predicate(self, quoted_column: str, pattern: str) -> str:
        """Build a "value does not match" predicate using the native ``~`` operator.

        PostgreSQL evaluates ``~`` inside the server, so no pattern is
        compiled in Python and no row is round-tripped through a callback.
        This is the reason the rule engine asks the dialect for this
        predicate instead of assuming SQLite's ``REGEXP`` everywhere.

        Args:
            quoted_column: An already-quoted column reference.
            pattern: Regular expression source. Not validated here — the
                server is the authority on POSIX regex syntax, and
                pre-validating with Python's :mod:`re` would reject patterns
                PostgreSQL accepts. Bound as a parameter by the caller.

        Returns:
            ``<col> IS NOT NULL AND NOT (<col> ~ %s)`` — one ``pyformat``
            placeholder for the pattern.

        Example:
            predicate = PostgresqlDialect().regex_not_matching_predicate('"e"', "^a")
            assert predicate == '"e" IS NOT NULL AND NOT ("e" ~ %s)'
        """
        return (
            f"{quoted_column} IS NOT NULL AND NOT ({quoted_column} ~ {self.parameter_placeholder})"
        )

    def approximate_distinct_expression(self, quoted_column: str) -> str | None:
        """Report that stock PostgreSQL has no approximate distinct count.

        Args:
            quoted_column: An already-quoted column reference (unused).

        Returns:
            Always ``None``. Approximate distinct counting on PostgreSQL
            requires an extension (``postgresql-hll``, ``datasketches``)
            that DQT cannot assume is installed, and guessing wrong would
            turn a slow query into a failing one. A caller that wants
            approximation on PostgreSQL must configure it explicitly; that
            is a separate decision, deliberately not made here.

        Example:
            assert PostgresqlDialect().approximate_distinct_expression('"c"') is None
        """
        return None


# The single PostgreSQL dialect instance; dialects are stateless.
POSTGRESQL = PostgresqlDialect()

__all__ = [
    "COLUMN_METADATA_SQL",
    "POSTGRESQL",
    "PostgresqlDialect",
]
