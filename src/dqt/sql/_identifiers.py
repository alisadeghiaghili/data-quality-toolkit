"""
dqt.sql._identifiers
=====================

Single quoting *entry point* for every SQL identifier (schema, table, or
column name) used anywhere in :mod:`dqt.sql`. Nothing else in this package
should build a quoted identifier by hand; call :func:`quote_identifier` (or
:func:`qualified_identifier` for a schema-qualified table reference)
instead.

Where the rules live, after `DQT-08`. This module no longer holds a
quote-character table of its own. It resolves the dialect by name and asks it,
because quoting is not the same shape in every database: SQLite and PostgreSQL
use a symmetric ANSI delimiter with the embedded character doubled, while SQL
Server uses asymmetric brackets in which only the closing one is escaped. A
single lookup table could express the first rule and not the second. Keeping
this module as the entry point while the dialect owns the rule means every
call site is unchanged and there is still exactly one implementation per
database.

Prefer the dialect directly where you already hold one. A caller that has a
:class:`~dqt.sql.dialects.base.Dialect` — everything downstream of
:func:`dqt.sql._connect.get_connection` does — should call
``dialect.quote_identifier(...)`` rather than routing a dialect *name* string
through this module. This module exists for the callers that only have a name.

This module intentionally does not touch literal values. Literal values
(rule thresholds, cleansing replacement values, lookup values, ...) must
always reach SQL as DBAPI bind parameters, never through this module or
through string interpolation.
"""

from __future__ import annotations

from dqt.sql.dialects import get_dialect_by_name


def quote_identifier(name: str, dialect: str = "sqlite") -> str:
    """Quote and escape a single SQL identifier for *dialect*.

    Wraps *name* in the dialect's identifier delimiters, escaping any
    embedded delimiter so the identifier cannot break out of its quoting.
    The escaping rule is the dialect's, not this function's.

    Args:
        name: Raw identifier (schema, table, or column name).
        dialect: One of the names registered in :mod:`dqt.sql.dialects`
            (``"sqlite"``, ``"postgresql"``, ``"sqlserver"``; ``"postgres"``
            is accepted as an alias).

    Returns:
        The quoted identifier, e.g. ``'"orders"'`` on SQLite and PostgreSQL
        or ``"[orders]"`` on SQL Server.

    Raises:
        ValueError: If *dialect* is not a supported dialect name.

    Example::

        assert quote_identifier("orders") == '"orders"'
        assert quote_identifier("orders", "sqlserver") == "[orders]"
        quoted = quote_identifier('a"b')
        assert quoted.count('"') == 4  # opening, doubled embedded, closing
    """
    return get_dialect_by_name(dialect).quote_identifier(name)


def qualified_identifier(schema_name: str | None, table_name: str, dialect: str = "sqlite") -> str:
    """Return a quoted, possibly schema-qualified table identifier.

    Whether a schema qualifier is dropped is the dialect's decision, not this
    function's. SQLite suppresses its implicit ``"main"``, because that is a
    name SQLite gave itself rather than one a DBA chose; PostgreSQL and SQL
    Server suppress nothing, because a schema named ``main`` there is real and
    dropping it would silently retarget the query.

    Args:
        schema_name: Schema name, or ``None`` for an unqualified reference.
        table_name: Table name.
        dialect: Target SQL dialect name, forwarded to
            :func:`~dqt.sql.dialects.get_dialect_by_name`.

    Returns:
        A quoted ``schema.table`` reference where the dialect qualifies, and
        a quoted bare table name where it does not.

    Raises:
        ValueError: If *dialect* is not a supported dialect name.

    Example::

        assert qualified_identifier("public", "orders", "postgresql") == '"public"."orders"'
        assert qualified_identifier(None, "orders") == '"orders"'
        assert qualified_identifier("main", "orders") == '"orders"'
        assert qualified_identifier("dbo", "orders", "sqlserver") == "[dbo].[orders]"
    """
    return get_dialect_by_name(dialect).qualified_identifier(schema_name, table_name)
