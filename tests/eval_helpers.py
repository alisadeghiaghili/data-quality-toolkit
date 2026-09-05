"""Run a single rule fragment against a cursor, for tests that want a number.

The rule engine compiles a check to aggregate *expressions* so that several
checks over one table can share a scan (``tests/unit/sql/test_rules_grouped.py``
covers why). Some tests are about one check's arithmetic rather than about
batching, and they read better asking for two numbers than for a slice of a
shared row.

These adapters exist here rather than in ``src`` deliberately: the production
engine has no use for a one-check-at-a-time entry point, and a function kept
in the package only because tests import it is exactly the kind of thing the
honesty gate is meant to keep out.

Example:
    total, nulls = eval_not_null(cursor, None, "users", "email", dialect)
"""

from __future__ import annotations

from typing import Any

from dqt.sql.dialects.base import Dialect
from dqt.sql.rules import (
    _fragment_not_null,
    _fragment_range,
    _fragment_regex,
    _fragment_unique,
    _run_aggregate,
)


def _run(
    cursor: Any,
    dialect: Dialect,
    schema_name: str | None,
    table_name: str,
    expressions: tuple[str, ...],
    binds: tuple[Any, ...],
) -> tuple[Any, ...]:
    """Run one fragment's expressions against *table_name*.

    Args:
        cursor: Open DBAPI cursor.
        dialect: Dialect assembling the statement.
        schema_name: Schema name, or None.
        table_name: Table to read.
        expressions: The fragment's aggregates.
        binds: The fragment's bind values.

    Returns:
        The row those expressions produced.

    Example:
        values = _run(cursor, dialect, None, "users", ("COUNT(*)",), ())
    """
    return _run_aggregate(
        cursor,
        dialect,
        dialect.qualified_identifier(schema_name, table_name),
        expressions,
        binds,
    )


def eval_not_null(
    cursor: Any,
    schema_name: str | None,
    table_name: str,
    column_name: str,
    dialect: Dialect,
) -> tuple[int, int]:
    """Count total rows and NULL rows for a column.

    Args:
        cursor: Open DBAPI cursor.
        schema_name: Schema name, or None.
        table_name: Table name.
        column_name: Column to check.
        dialect: Target dialect.

    Returns:
        Tuple of ``(total_rows, null_count)``.

    Example:
        total, nulls = eval_not_null(cursor, None, "users", "email", dialect)
    """
    expressions, binds = _fragment_not_null(dialect.quote_identifier(column_name))
    values = _run(cursor, dialect, schema_name, table_name, expressions, binds)
    return int(values[0]), int(values[1])


def eval_unique(
    cursor: Any,
    schema_name: str | None,
    table_name: str,
    column_name: str,
    dialect: Dialect,
    approximate: bool = False,
) -> tuple[int, int, bool]:
    """Count non-NULL values and duplicates for a column.

    Args:
        cursor: Open DBAPI cursor.
        schema_name: Schema name, or None.
        table_name: Table name.
        column_name: Column to check.
        dialect: Target dialect.
        approximate: Whether to ask for an estimating distinct count.

    Returns:
        Tuple of ``(total_rows, duplicate_extra_rows, used_approximation)``.

    Example:
        total, dupes, estimated = eval_unique(cursor, None, "u", "email", dialect)
    """
    expressions, binds, used_approximation = _fragment_unique(
        dialect.quote_identifier(column_name), dialect, approximate=approximate
    )
    values = _run(cursor, dialect, schema_name, table_name, expressions, binds)
    return int(values[0]), int(values[1] or 0), used_approximation


def eval_range(
    cursor: Any,
    schema_name: str | None,
    table_name: str,
    column_name: str,
    min_val: float | None,
    max_val: float | None,
    dialect: Dialect,
) -> tuple[int, int]:
    """Count rows outside ``[min_val, max_val]``.

    Args:
        cursor: Open DBAPI cursor.
        schema_name: Schema name, or None.
        table_name: Table name.
        column_name: Column to check.
        min_val: Inclusive lower bound, or None.
        max_val: Inclusive upper bound, or None.
        dialect: Target dialect.

    Returns:
        Tuple of ``(total_rows, out_of_range_count)``.

    Raises:
        ValueError: If both bounds are None.

    Example:
        total, bad = eval_range(cursor, None, "p", "price", 0.0, None, dialect)
    """
    expressions, binds = _fragment_range(
        dialect.quote_identifier(column_name), dialect, min_val, max_val
    )
    values = _run(cursor, dialect, schema_name, table_name, expressions, binds)
    return int(values[0]), int(values[1] or 0)


def eval_regex(
    cursor: Any,
    schema_name: str | None,
    table_name: str,
    column_name: str,
    pattern: str,
    dialect: Dialect,
) -> tuple[int, int]:
    """Count rows whose value does not match *pattern*.

    Args:
        cursor: Open DBAPI cursor.
        schema_name: Schema name, or None.
        table_name: Table name.
        column_name: Column to check.
        pattern: Regular expression source.
        dialect: Target dialect.

    Returns:
        Tuple of ``(total_rows, non_matching_count)``.

    Raises:
        ValueError: If the dialect cannot evaluate a regular expression, or
            the pattern is invalid.

    Example:
        total, bad = eval_regex(cursor, None, "u", "email", r"^.+@", dialect)
    """
    expressions, binds = _fragment_regex(dialect.quote_identifier(column_name), dialect, pattern)
    values = _run(cursor, dialect, schema_name, table_name, expressions, binds)
    return int(values[0]), int(values[1] or 0)
