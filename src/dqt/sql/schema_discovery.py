"""
Schema discovery for DQT SQL pipelines.

This module discovers user tables and columns and returns pure domain
objects, without coupling to any ORM.

It contains no dialect-specific SQL of its own. Which catalogue to query, and
how, is the dialect's business (:mod:`dqt.sql.dialects`); this module's job is
to open one connection through the single connection authority
(:func:`dqt.sql._connect.get_connection`), ask the dialect for column rows,
and group them into :class:`DiscoveredTable` objects. Before `DQT-08` it did
all three itself and branched on the DSN inline, and its own connection helper
ignored ``ConnectionConfig.read_only`` entirely.
"""

from __future__ import annotations

from dataclasses import dataclass

from dqt.common.models import ConnectionConfig
from dqt.sql._connect import get_connection, get_dialect_for
from dqt.sql.dialects import ColumnMetadata


@dataclass(slots=True)
class DiscoveredColumn:
    """Metadata for one discovered database column.

    Attributes:
        schema_name: Database schema name.
        table_name: Table name.
        column_name: Column name.
        data_type: Database-reported type name.
        nullable: Whether the column accepts NULL values.

    Example:
        column = DiscoveredColumn(
            schema_name="main",
            table_name="customers",
            column_name="email",
            data_type="TEXT",
            nullable=True,
        )
    """

    schema_name: str
    table_name: str
    column_name: str
    data_type: str
    nullable: bool


@dataclass(slots=True)
class DiscoveredTable:
    """Metadata for one discovered database table.

    Attributes:
        schema_name: Database schema name.
        table_name: Table name.
        columns: Ordered list of discovered columns.

    Example:
        table = DiscoveredTable(
            schema_name="main",
            table_name="customers",
            columns=[],
        )
    """

    schema_name: str
    table_name: str
    columns: list[DiscoveredColumn]


def discover_schema(connection_config: ConnectionConfig) -> list[DiscoveredTable]:
    """Discover user tables and columns from a relational database.

    Works on every dialect :mod:`dqt.sql.dialects` supports, because the
    catalogue query is the dialect's, not this function's. Views and system
    schemas are excluded on all of them.

    A table with no columns at all is not reported, because a column-row
    catalogue query returns nothing for it. That is unchanged from the
    pre-`DQT-08` behaviour and is unreachable on SQLite, which cannot create
    such a table.

    Args:
        connection_config: Validated DQT connection configuration. Its
            ``read_only`` flag is honoured — unlike before `DQT-08`, when this
            function's private connection helper never read it.

    Returns:
        A list of discovered tables with their columns, in the order the
        dialect's catalogue query returns them.

    Raises:
        ValueError: If the DSN names no supported dialect.
        ImportError: If the dialect's driver is not installed.

    Example:
        tables = discover_schema(connection_config)
    """
    dialect = get_dialect_for(connection_config)
    connection = get_connection(connection_config)
    try:
        column_rows = dialect.fetch_column_metadata(connection)
    finally:
        connection.close()
    return _group_columns_into_tables(column_rows)


def _group_columns_into_tables(column_rows: list[ColumnMetadata]) -> list[DiscoveredTable]:
    """Group adapter-layer column rows into domain tables, preserving order.

    Args:
        column_rows: Rows as returned by a dialect's
            ``fetch_column_metadata``, already ordered by schema, table, and
            the table's own column order.

    Returns:
        One :class:`DiscoveredTable` per distinct (schema, table) pair, in
        first-appearance order, each carrying its columns in row order.
    """
    tables: dict[tuple[str, str], DiscoveredTable] = {}
    for row in column_rows:
        key = (row.schema_name, row.table_name)
        table = tables.get(key)
        if table is None:
            table = DiscoveredTable(
                schema_name=row.schema_name,
                table_name=row.table_name,
                columns=[],
            )
            tables[key] = table
        table.columns.append(
            DiscoveredColumn(
                schema_name=row.schema_name,
                table_name=row.table_name,
                column_name=row.column_name,
                data_type=row.data_type,
                nullable=row.nullable,
            )
        )
    return list(tables.values())
