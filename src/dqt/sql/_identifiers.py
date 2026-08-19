"""
dqt.sql._identifiers
=====================

Single quoting authority for every SQL identifier (schema, table, or column
name) used anywhere in :mod:`dqt.sql`. Nothing else in this package should
build a quoted identifier by hand; call :func:`quote_identifier` (or
:func:`qualified_identifier` for a schema-qualified table reference)
instead.

This module intentionally does not touch literal values. Literal values
(rule thresholds, cleansing replacement values, lookup values, ...) must
always reach SQL as DBAPI bind parameters, never through this module or
through string interpolation.
"""

from __future__ import annotations

# Quote character per supported dialect. Both dialects DQT currently
# supports use ANSI double-quoted identifiers; the table exists so a future
# dialect with a different quote character (e.g. MySQL's backtick) is a
# one-line addition here rather than a second quoting function elsewhere.
_QUOTE_CHARS: dict[str, str] = {
    "sqlite": '"',
    "postgresql": '"',
}


def quote_identifier(name: str, dialect: str = "sqlite") -> str:
    """Quote and escape a single SQL identifier for *dialect*.

    Wraps *name* in the dialect's identifier quote character, doubling any
    embedded occurrence of that character so the identifier cannot break out
    of its quoting.

    Args:
        name: Raw identifier (schema, table, or column name).
        dialect: One of the keys registered in this module's dialect table
            (currently ``"sqlite"`` or ``"postgresql"``).

    Returns:
        The quoted identifier, e.g. ``'"orders"'``.

    Raises:
        ValueError: If *dialect* is not a supported dialect.

    Example::

        assert quote_identifier("orders") == '"orders"'
        quoted = quote_identifier('a"b')
        assert quoted.count('"') == 4  # opening, doubled embedded, closing
    """
    try:
        quote_char = _QUOTE_CHARS[dialect]
    except KeyError as exc:
        raise ValueError(f"Unsupported dialect for identifier quoting: {dialect!r}") from exc
    escaped = name.replace(quote_char, quote_char * 2)
    return f"{quote_char}{escaped}{quote_char}"


def qualified_identifier(schema_name: str | None, table_name: str, dialect: str = "sqlite") -> str:
    """Return a quoted, possibly schema-qualified table identifier.

    Args:
        schema_name: Schema name, or ``None``/``"main"`` for SQLite's
            implicit default schema (an unqualified reference is used in
            that case).
        table_name: Table name.
        dialect: Target SQL dialect, forwarded to :func:`quote_identifier`.

    Returns:
        ``"schema"."table"`` when *schema_name* is given and is not
        SQLite's implicit ``"main"``; otherwise just ``"table"``, quoted.

    Example::

        assert qualified_identifier("public", "orders", "postgresql") == '"public"."orders"'
        assert qualified_identifier(None, "orders") == '"orders"'
        assert qualified_identifier("main", "orders") == '"orders"'
    """
    if schema_name and schema_name != "main":
        return f"{quote_identifier(schema_name, dialect)}.{quote_identifier(table_name, dialect)}"
    return quote_identifier(table_name, dialect)
