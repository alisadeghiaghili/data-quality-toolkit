"""
dqt.sql.dialects.base
=====================

The :class:`Dialect` protocol — DQT's single declaration of everything that
varies between one relational database and another — plus the small set of
ANSI-common SQL builders that concrete dialects share rather than each
re-implementing.

Why a protocol rather than a base class. A protocol lets the modules that
*use* a dialect (``rules.py``, ``schema_discovery.py``, ``profiling.py``)
depend on the shape of a dialect without importing any concrete dialect and
therefore without importing any database driver. Concrete dialects are
adapters; they may import drivers, and they do so lazily, inside the method
that needs one, so that ``import dqt`` never requires ``psycopg`` or
``pyodbc`` to be installed.

What deliberately is *not* here. This protocol describes single-statement
SQL construction and connection opening. It does not describe query
*planning* — how many statements a caller issues, or whether several column
statistics are folded into one scan — because that is the calling module's
decision, not the database's. :meth:`Dialect.select_aggregates_sql` takes a
*sequence* of expressions precisely so a future single-pass profiler can pass
one expression per column per statistic and get one query per table, without
this protocol changing at all.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any, NoReturn, Protocol, runtime_checkable

from dqt.common.models import ConnectionConfig


def _unimplemented(symbol: str) -> NoReturn:
    """Fail loudly for a symbol whose interface exists but whose body does not.

    This exists so that `DQT-08`'s tests-first commit can ship the complete
    ``dialects`` interface — signatures, types, and docstrings — while every
    behavioural test still fails by *executing* the code under test rather
    than by failing to import it. The implementing commit replaces each of
    these calls with a real body; none may survive into a merged branch.

    Args:
        symbol: Dotted name of the unimplemented symbol, used in the message.

    Returns:
        Never returns.

    Raises:
        NotImplementedError: Always.
    """
    raise NotImplementedError(f"{symbol} is declared but not yet implemented (DQT-08).")


class ReadOnlyEnforcement(Enum):
    """How strongly a dialect can hold a connection to ``read_only=True``.

    DQT's read-only guarantee (`DQT-03`) is layered: an application-level
    refusal in :func:`dqt.sql.cleansing.apply_cleansing`, plus a
    connection-level control applied when the connection is opened. This
    enum records how strong the *second* layer actually is on a given
    database, so that a weaker one is stated rather than assumed.

    Attributes:
        DRIVER_ENFORCED: A write through the connection fails at the driver
            or the server, not merely by DQT's own convention. SQLite
            (``file:...?mode=ro``) and PostgreSQL (a read-only session)
            are both in this class.
        ADVISORY: The dialect offers no mechanism that makes a write fail.
            The connection is opened with whatever read-only *hint* the
            driver accepts, but the guarantee rests on DQT's own refusal
            plus the privileges of the login the operator supplies.

    Example:
        from dqt.sql.dialects import SQLITE, SQLSERVER
        from dqt.sql.dialects.base import ReadOnlyEnforcement

        assert SQLITE.read_only_enforcement is ReadOnlyEnforcement.DRIVER_ENFORCED
        assert SQLSERVER.read_only_enforcement is ReadOnlyEnforcement.ADVISORY
    """

    DRIVER_ENFORCED = "driver_enforced"
    ADVISORY = "advisory"


@dataclass(frozen=True, slots=True)
class ColumnMetadata:
    """One column as reported by a dialect's introspection query.

    This is the adapter-layer row shape returned by
    :meth:`Dialect.fetch_column_metadata`. It deliberately is *not*
    :class:`~dqt.sql.schema_discovery.DiscoveredColumn`: that type belongs to
    the domain layer, and having an adapter build it would point the
    dependency outward. :func:`~dqt.sql.schema_discovery.discover_schema`
    maps these rows into the domain objects.

    Attributes:
        schema_name: Schema the column's table lives in. Dialects that have
            no real schema concept report their conventional stand-in
            (SQLite reports ``"main"``).
        table_name: Table the column belongs to.
        column_name: Column name, exactly as the database reports it.
        is_primary_key: Whether the column is part of the primary key.
        data_type: Database-reported type name, uppercased or lowercased
            exactly as the database returns it — DQT does not normalise it.
        nullable: ``True`` when the column accepts ``NULL``.

    Example:
        column = ColumnMetadata(
            schema_name="main",
            table_name="customers",
            column_name="email",
            data_type="TEXT",
            nullable=True,
        )
        assert column.nullable is True
    """

    schema_name: str
    table_name: str
    column_name: str
    data_type: str
    nullable: bool
    is_primary_key: bool = False


@runtime_checkable
class Dialect(Protocol):
    """Everything DQT needs to know about one relational database.

    A dialect is the single authority for its database: identifier quoting,
    the read-only connection incantation, bind-parameter style, catalogue
    introspection, aggregate and row-limited query construction, regular
    expression matching, and approximate-distinct support. No module outside
    ``dqt.sql.dialects`` may branch on the database in use; it asks a
    dialect instead.

    Attributes:
        name: Canonical dialect name (``"sqlite"``, ``"postgresql"``,
            ``"sqlserver"``). This is the key used by
            :func:`dqt.sql.dialects.get_dialect_by_name`.
        physical_row_locator: Row-address expression for keyless tables,
            or None where the dialect has none that is stable.
        parameter_placeholder: The DBAPI bind-parameter placeholder this
            database's driver expects — ``"?"`` for ``qmark`` drivers,
            ``"%s"`` for ``pyformat``/``format`` drivers. Literal values
            must always reach SQL through a placeholder, never through
            string interpolation.
        read_only_enforcement: How strongly :meth:`connect` can hold a
            ``read_only=True`` connection — see :class:`ReadOnlyEnforcement`.

    Example:
        from dqt.sql.dialects import get_dialect

        dialect = get_dialect("sqlite:///dev.db")
        assert dialect.name == "sqlite"
        assert dialect.parameter_placeholder == "?"
    """

    name: str
    parameter_placeholder: str
    read_only_enforcement: ReadOnlyEnforcement

    def connect(self, connection_config: ConnectionConfig) -> Any:
        """Open a DBAPI connection to the user database described by *config*.

        Implementations import their driver inside this method, never at
        module import time, so that installing DQT does not require every
        supported database's driver.

        Args:
            connection_config: Validated DQT connection configuration. Its
                ``read_only`` flag (default ``True``) selects the read-only
                connection form where the dialect has one.

        Returns:
            An open DBAPI 2.0 connection. The caller owns it and must close
            it.

        Raises:
            ImportError: If the dialect's driver is not installed.
            ValueError: If the DSN is malformed for this dialect.

        Example:
            from dqt.common.models import ConnectionConfig

            config = ConnectionConfig(id="dev", dsn="sqlite:///dev.db")
            connection = dialect.connect(config)
            connection.close()
        """
        ...

    def quote_identifier(self, name: str) -> str:
        """Quote and escape one SQL identifier for this dialect.

        Args:
            name: Raw identifier (schema, table, or column name), exactly as
                it appears in the database catalogue.

        Returns:
            The identifier wrapped in this dialect's delimiters, with any
            embedded delimiter escaped so the identifier cannot terminate
            early.

        Example:
            assert dialect.quote_identifier("orders").endswith("orders" + dialect_close)
        """
        ...

    def qualified_identifier(self, schema_name: str | None, table_name: str) -> str:
        """Return a quoted, possibly schema-qualified table reference.

        Args:
            schema_name: Schema name, or ``None`` for an unqualified
                reference. A dialect may additionally treat its own implicit
                default schema as "unqualified" — SQLite does this for
                ``"main"``.
            table_name: Table name.

        Returns:
            ``schema.table``, both quoted, when a schema qualifier applies;
            otherwise just the quoted table name.

        Example:
            reference = dialect.qualified_identifier(None, "orders")
            assert "orders" in reference
        """
        ...

    #: Expression naming a row's physical address, for tables with no primary
    #: key, or None where the dialect has none stable enough to substitute for
    #: one. SQLite's ``rowid`` is stable for a row's lifetime; PostgreSQL's
    #: ``ctid`` is not -- it moves on UPDATE and under VACUUM FULL -- so
    #: PostgreSQL reports None and cleansing refuses rather than addressing
    #: whatever now sits at a recorded position (`NEW-M`).
    physical_row_locator: str | None

    def fetch_column_metadata(self, connection: Any) -> list[ColumnMetadata]:
        """Read every user column from the database's catalogue.

        System and catalogue schemas are excluded by the implementation;
        views are excluded, so only base tables are reported.

        Args:
            connection: An open connection to this dialect's database,
                normally one returned by :meth:`connect`.

        Returns:
            Column rows ordered by schema, then table, then the table's own
            column order. A table with no columns produces no rows and so
            does not appear at all.

        Example:
            rows = dialect.fetch_column_metadata(connection)
            assert all(row.table_name for row in rows)
        """
        ...

    def select_aggregates_sql(
        self,
        qualified_table: str,
        expressions: Sequence[str],
        where_clause: str | None = None,
    ) -> str:
        """Build one set-based aggregate query over *qualified_table*.

        This is the seam that keeps profiling and rule evaluation set-based.
        Passing many expressions in one call is what makes a single-pass,
        one-query-per-table profiler possible without changing this
        protocol; passing one is the degenerate case used today.

        Args:
            qualified_table: An already-quoted table reference, as returned
                by :meth:`qualified_identifier`.
            expressions: Aggregate SQL expressions to project, already
                built from quoted identifiers. Must not be empty.
            where_clause: Optional predicate body, without the ``WHERE``
                keyword. Literal values inside it must be bind-parameter
                placeholders, never interpolated text.

        Returns:
            A ``SELECT <expressions> FROM <table>`` statement, with
            ``WHERE <where_clause>`` appended when one is given.

        Raises:
            ValueError: If *expressions* is empty.

        Example:
            sql = dialect.select_aggregates_sql("t", ["COUNT(*)"])
            assert sql.startswith("SELECT COUNT(*) FROM t")
        """
        ...

    def limited_select_sql(
        self,
        qualified_table: str,
        expressions: Sequence[str],
        where_clause: str | None = None,
        limit: int | None = None,
        order_by: Sequence[str] | None = None,
    ) -> str:
        """Build a row-limited ``SELECT``, using this dialect's limit syntax.

        The syntax differs structurally, not just lexically: PostgreSQL and
        SQLite append ``LIMIT n`` after the ``WHERE`` clause, while SQL
        Server puts ``TOP (n)`` between ``SELECT`` and the projection. That
        is why this is a dialect method rather than a shared string suffix.
        DQT needs it wherever evidence must be bounded rather than
        materialised in full.

        Args:
            qualified_table: An already-quoted table reference.
            expressions: SQL expressions to project. Must not be empty.
            where_clause: Optional predicate body, without ``WHERE``.
            limit: Maximum rows to return. ``None`` means no limit, in which
                case the result is identical to
                :meth:`select_aggregates_sql`. Must be positive when given.

        Returns:
            A ``SELECT`` statement carrying this dialect's row limit.

        Raises:
            ValueError: If *expressions* is empty, or *limit* is not
                positive.

        Example:
            sql = dialect.limited_select_sql("t", ["a"], limit=5)
            assert "5" in sql
        """
        ...

    def regex_not_matching_predicate(self, quoted_column: str, pattern: str) -> str:
        """Build a predicate selecting rows whose value fails *pattern*.

        The returned predicate always excludes ``NULL`` explicitly: a
        ``NULL`` value is "not applicable", not "invalid", and must not be
        counted as a violation.

        Args:
            quoted_column: An already-quoted column reference.
            pattern: The regular expression source, as written in a rule
                file's ``params.pattern``. It is *validated* here where the
                dialect needs validation up front, but it is never
                interpolated into the returned SQL — the caller binds it as
                a parameter.

        Returns:
            A predicate body, without the ``WHERE`` keyword, containing one
            bind-parameter placeholder for *pattern*.

        Raises:
            ValueError: If this dialect has no regular-expression support at
                all, or if *pattern* is not a valid, length-bounded regular
                expression on a dialect that must compile it in Python.

        Example:
            predicate = dialect.regex_not_matching_predicate('"email"', "^a")
            assert "IS NOT NULL" in predicate
        """
        ...

    def approximate_distinct_expression(self, quoted_column: str) -> str | None:
        """Return an approximate distinct-count expression, if one exists.

        ``COUNT(DISTINCT ...)`` is expensive at scale, and some databases
        offer a sketch-based approximation instead. This method reports
        whether that is available so a caller can offer it as an option
        rather than assuming it exists everywhere.

        Args:
            quoted_column: An already-quoted column reference.

        Returns:
            An SQL expression approximating the distinct count of the
            column, or ``None`` when this dialect has no built-in
            approximation and the caller must fall back to an exact
            ``COUNT(DISTINCT ...)``.

        Example:
            expression = dialect.approximate_distinct_expression('"customer_id"')
            assert expression is None or "customer_id" in expression
        """
        ...


def quote_with_doubled_delimiter(name: str, quote_char: str) -> str:
    """Quote *name* with a symmetric delimiter, doubling embedded occurrences.

    This is the ANSI identifier-quoting algorithm, shared by every dialect
    whose opening and closing delimiter are the same character. SQL Server's
    bracket form is asymmetric and does not use this function — which is
    exactly why the algorithm lives here as a shared helper rather than as a
    single hard-coded rule.

    Args:
        name: Raw identifier.
        quote_char: The delimiter character, e.g. ``'"'``.

    Returns:
        The quoted identifier, with every embedded *quote_char* doubled.

    Example:
        assert quote_with_doubled_delimiter("orders", '"') == '"orders"'
        assert quote_with_doubled_delimiter('a"b', '"') == '"a""b"'
    """
    escaped = name.replace(quote_char, quote_char * 2)
    return f"{quote_char}{escaped}{quote_char}"


def ansi_select_aggregates_sql(
    qualified_table: str,
    expressions: Sequence[str],
    where_clause: str | None = None,
) -> str:
    """Build a ``SELECT ... FROM ... [WHERE ...]`` statement in ANSI form.

    Every dialect DQT supports shares this shape, so it is implemented once
    here and delegated to, rather than written out in each dialect module.

    Args:
        qualified_table: An already-quoted table reference.
        expressions: SQL expressions to project. Must not be empty.
        where_clause: Optional predicate body, without the ``WHERE`` keyword.

    Returns:
        The assembled statement, with expressions comma-separated.

    Raises:
        ValueError: If *expressions* is empty — a ``SELECT`` with no
            projection is a programming error, not a query.

    Example:
        sql = ansi_select_aggregates_sql("t", ["COUNT(*)"], '"c" IS NULL')
        assert sql == 'SELECT COUNT(*) FROM t WHERE "c" IS NULL'
    """
    if not expressions:
        raise ValueError("A SELECT needs at least one expression to project.")
    statement = f"SELECT {', '.join(expressions)} FROM {qualified_table}"
    if where_clause:
        statement = f"{statement} WHERE {where_clause}"
    return statement


def validate_row_limit(limit: int | None) -> None:
    """Reject a non-positive row limit before it reaches any SQL text.

    Args:
        limit: The candidate limit, or ``None`` for "no limit".

    Returns:
        ``None``. This function exists for its exception.

    Raises:
        ValueError: If *limit* is given and is not strictly positive. A
            zero or negative limit is always a caller mistake, and letting
            it through would produce SQL whose meaning differs per database.

    Example:
        validate_row_limit(10)
        validate_row_limit(None)
    """
    if limit is not None and limit <= 0:
        raise ValueError(f"Row limit must be a positive integer, got {limit!r}.")
