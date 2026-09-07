"""Which columns go missing together (`F11`).

Profiling reports how much is missing, per column. This reports what is
missing *with* what, and they answer different questions. Three columns each
20% NULL might be one upstream feed dropping all three from the same fifth
of the rows, or three unrelated gaps -- and the null counts are identical
either way.

**The boundary with `missingly`.** `AGENTS.md` forbids re-implementing that
package's algorithms. The line:

- `missingly` **infers the mechanism**: whether the missingness is random.
  That is a statistical inference over a DataFrame, which is what
  :mod:`dqt.bridges.missingly` samples rows for.
- This module **counts co-occurrence**: a ``GROUP BY`` over a per-row
  null-signature, computed inside the database, materialising nothing.

Describing a pattern is not inferring a mechanism. DQT reports the pattern;
missingly explains it.

Example:
    patterns = missingness_patterns(connection_config, table, config)
"""

from __future__ import annotations

from dataclasses import dataclass

from dqt.common.models import ConnectionConfig, MissingnessConfig
from dqt.sql._connect import get_connection, get_dialect_for
from dqt.sql.schema_discovery import DiscoveredTable

__all__ = ["MissingnessPattern", "missingness_patterns"]


@dataclass(frozen=True, slots=True)
class MissingnessPattern:
    """One combination of columns that are NULL in the same rows.

    Attributes:
        columns: The columns missing together, in table order.
        row_count: How many rows have exactly this combination missing.

    Example:
        pattern = MissingnessPattern(columns=("email", "phone"), row_count=3)
    """

    columns: tuple[str, ...]
    row_count: int


def missingness_patterns(
    connection_config: ConnectionConfig,
    table: DiscoveredTable,
    config: MissingnessConfig,
) -> list[MissingnessPattern]:
    """Return the most common combinations of simultaneously-missing columns.

    Args:
        connection_config: Connection to read through. May be read-only.
        table: The table to examine.
        config: How many patterns to return.

    Returns:
        Patterns, most common first. Rows missing nothing, and patterns of a
        single column, are excluded.

    Example:
        patterns = missingness_patterns(connection_config, table, config)
    """
    nullable = [column for column in table.columns if not column.is_primary_key]
    if len(nullable) < 2:
        # A pattern needs at least two columns to say anything the null count
        # does not already say.
        return []

    dialect = get_dialect_for(connection_config)
    qualified = dialect.qualified_identifier(table.schema_name, table.table_name)

    # A per-row signature: one character per column, '1' where it is NULL.
    # Concatenating rather than grouping by the columns themselves keeps the
    # GROUP BY key one value wide however many columns the table has, and
    # keeps the returned rows small -- the alternative sends every grouped
    # column's value back for every group.
    signature = " || ".join(
        f"(CASE WHEN {dialect.quote_identifier(column.column_name)} IS NULL THEN '1' ELSE '0' END)"
        for column in nullable
    )

    statement = (
        f"SELECT {signature} AS dqt_pattern, COUNT(*) AS dqt_rows "
        f"FROM {qualified} "
        f"GROUP BY {signature} "
        f"ORDER BY COUNT(*) DESC "
        f"LIMIT {int(config.top_patterns)}"
    )

    connection = get_connection(connection_config)
    try:
        rows = connection.execute(statement).fetchall()
    finally:
        connection.close()

    patterns: list[MissingnessPattern] = []
    for row in rows:
        marks = str(row[0])
        columns = tuple(
            column.column_name for column, mark in zip(nullable, marks, strict=False) if mark == "1"
        )
        # Rows missing nothing are the largest group on a healthy table, and
        # a single missing column is what the null count already reports.
        if len(columns) < 2:
            continue
        patterns.append(MissingnessPattern(columns=columns, row_count=int(row[1])))
    return patterns
