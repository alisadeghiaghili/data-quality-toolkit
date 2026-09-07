"""The database half of the Classification facet.

Named for the job rather than the facet, deliberately. ``sql/classification.py``
would share a basename with :mod:`dqt.classification`, which sits in a
different architectural layer -- and ``tools/arch_audit.py`` matches layers by
module name, so the collision made an adapter read as domain code and fail the
inward-dependency rule. Two modules in different layers should not share a
name even where the import system tolerates it.

:mod:`dqt.classification` holds the validators -- pure functions over values,
with no I/O, which is what makes them cheap to test against published
checksum rules. This module is the part that has to touch a database, and it
exists so that the pure half can stay pure.

**This is the only stage in DQT that reads real values.** Profiling, rules,
diagnostics and metrics all compute inside the database and bring back
numbers. A checksum cannot be evaluated that way: recognising an Iranian
national ID means seeing the ten digits. So this module genuinely pulls rows
into Python, and two constraints follow from that rather than decorating it.

**One bounded query per table.** Every candidate column is read in a single
``SELECT`` with a row limit, not one query per column. `AGENTS.md`
"Performance rules" permits genuinely reading rows only when the read is
chunked or bounded, and a sample is what keeps memory flat no matter how
large the table is.

**Off unless asked for.** See
:class:`~dqt.common.models.ClassificationConfig`. The reason is what it
reads, not what it costs.

Example:
    results = classify_table(connection, dialect, table, config)
"""

from __future__ import annotations

from typing import Any

from dqt.classification import ClassificationResult, classify_column
from dqt.common.models import ClassificationConfig
from dqt.sql.dialects import Dialect
from dqt.sql.schema_discovery import DiscoveredTable

__all__ = ["classifiable_columns", "classify_table"]


def classifiable_columns(table: DiscoveredTable, dialect: Dialect) -> list[Any]:
    """Return the columns worth reading values from.

    Binary and large-object columns are excluded. Their contents are not
    text, so no validator here can match one, and reading them is the
    expensive way to learn nothing -- a blob column would drag its payload
    into memory for a sample that cannot classify it.

    The question is asked of the dialect rather than answered from a shared
    list, for the same reason profiling asks it: ``TEXT`` is SQLite's
    ordinary string type and SQL Server's deprecated LOB type.

    Args:
        table: The discovered table.
        dialect: Dialect that knows which of its types are orderable text.

    Returns:
        The discovered columns to sample, in their table order.

    Example:
        columns = classifiable_columns(table, dialect)
    """
    return [column for column in table.columns if dialect.supports_min_max(column.data_type)]


def classify_table(
    connection: Any,
    dialect: Dialect,
    table: DiscoveredTable,
    config: ClassificationConfig,
) -> dict[str, ClassificationResult]:
    """Infer a semantic type for each of a table's classifiable columns.

    Issues **one** bounded ``SELECT`` covering every candidate column, then
    classifies each column from its slice of the returned rows. Reading the
    columns together is what keeps this one scan rather than one per column,
    and the two produce identical answers -- so nothing but a statement count
    would reveal the difference.

    Values are stringified before matching. A national ID stored as an
    integer column is still a national ID, and the validators work on
    characters.

    Args:
        connection: An open connection to the profiled database.
        dialect: Dialect for quoting and for the row-limit syntax.
        table: The table to classify.
        config: Which rows to read and how to match.

    Returns:
        Column name to its :class:`~dqt.classification.ClassificationResult`.
        Empty when the table has no classifiable column, in which case no
        query is issued at all.

    Example:
        results = classify_table(connection, dialect, table, config)
    """
    columns = classifiable_columns(table, dialect)
    if not columns:
        return {}

    table_ref = dialect.qualified_identifier(table.schema_name, table.table_name)
    projection = [dialect.quote_identifier(column.column_name) for column in columns]
    statement = dialect.limited_select_sql(table_ref, projection, limit=config.sample_size)
    rows = connection.execute(statement).fetchall()

    results: dict[str, ClassificationResult] = {}
    for position, column in enumerate(columns):
        # None stays None rather than becoming the string "None", which would
        # be four characters no validator matches and every validator counts
        # against the match ratio.
        values = [None if row[position] is None else str(row[position]) for row in rows]
        results[column.column_name] = classify_column(
            column.column_name,
            values,
            minimum_match_ratio=config.minimum_match_ratio,
            max_sample_values=config.sample_size,
            apply_persian_normalization=config.persian_normalization,
        )
    return results
