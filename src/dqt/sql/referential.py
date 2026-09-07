"""Referential integrity: counting rows whose foreign key points nowhere (`F2`).

The question this answers is about a database rather than a column: *are
there orders pointing at customers that no longer exist?* Nothing else in
DQT asks across two tables.

**A NULL foreign key is not an orphan.** A row with no reference references
nothing, which is a completeness question the null count already answers. A
row whose reference names a parent that does not exist is broken. Counting
the first as the second would inflate every orphan count on every nullable
foreign key in the database.

**Composite keys are compared whole.** Matching one column of a two-column
key and calling the row satisfied is a false clean bill of health, so every
column of the key joins at once.

**Cost.** One ``COUNT(*)`` over an anti-join per foreign key. Not batchable
the way column statistics are -- each key joins a different parent -- but
proportional to the number of keys, which is small, and no row is
materialised. The naive implementation of this check reads the parent keys
into a Python set and compares row by row; that is correct and unusable at
size, which is what `AGENTS.md` "Performance rules" forbids by name.

Example:
    orphans = count_orphans(connection_config, foreign_key)
"""

from __future__ import annotations

from dqt.common.models import ConnectionConfig
from dqt.sql._connect import get_connection, get_dialect_for
from dqt.sql.dialects import Dialect
from dqt.sql.schema_discovery import DiscoveredForeignKey

__all__ = ["count_orphans", "orphan_count_sql"]


def orphan_count_sql(dialect: Dialect, key: DiscoveredForeignKey) -> str:
    """Build the anti-join that counts rows whose reference is unmatched.

    A ``LEFT JOIN`` on the whole key, keeping the rows where the parent side
    came back NULL. The join carries **every** column of the key, so a
    composite key matches only when all of it matches.

    Rows whose own key is NULL are excluded before the join is considered.
    They would satisfy the ``IS NULL`` test on the parent side -- nothing
    joins to NULL -- and be counted as orphans, which they are not: a row
    with no reference references nothing.

    Args:
        dialect: The dialect to quote identifiers with.
        key: The foreign key to check.

    Returns:
        A ``SELECT COUNT(*)`` statement.

    Example:
        sql = orphan_count_sql(dialect, key)
    """
    child = dialect.qualified_identifier(key.schema_name, key.table_name)
    parent = dialect.qualified_identifier(key.referenced_schema, key.referenced_table)

    on_terms = " AND ".join(
        f"c.{dialect.quote_identifier(child_column)} = p.{dialect.quote_identifier(parent_column)}"
        for child_column, parent_column in zip(key.columns, key.referenced_columns, strict=True)
    )
    # Every column of the child's key must be present for the row to be
    # claiming a reference at all. A partially-NULL composite key references
    # nothing, the same as a wholly-NULL one.
    present = " AND ".join(
        f"c.{dialect.quote_identifier(column)} IS NOT NULL" for column in key.columns
    )
    # Any parent column serves as the "did it match" probe; the first is
    # arbitrary but stable.
    probe = f"p.{dialect.quote_identifier(key.referenced_columns[0])}"

    return (
        f"SELECT COUNT(*) FROM {child} AS c "
        f"LEFT JOIN {parent} AS p ON {on_terms} "
        f"WHERE {present} AND {probe} IS NULL"
    )


def count_orphans(connection_config: ConnectionConfig, key: DiscoveredForeignKey) -> int:
    """Count rows whose foreign key names a parent row that does not exist.

    One query, no rows materialised.

    Args:
        connection_config: Connection to read through. May be read-only.
        key: The foreign key to check.

    Returns:
        The number of orphaned rows. Rows whose key is NULL are excluded.

    Example:
        orphans = count_orphans(connection_config, key)
    """
    dialect = get_dialect_for(connection_config)
    statement = orphan_count_sql(dialect, key)
    connection = get_connection(connection_config)
    try:
        row = connection.execute(statement).fetchone()
    finally:
        connection.close()
    return int(row[0])
