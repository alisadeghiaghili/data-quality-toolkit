"""
Schema discovery for DQT SQL pipelines.

This module provides lightweight schema and column discovery helpers for
SQLite and PostgreSQL connections. It returns pure domain objects and simple
metadata structures without coupling to any ORM.

The current implementation is intentionally minimal:
- SQLite: fully supported using sqlite_master and PRAGMA table_info.
- PostgreSQL: supported through information_schema queries.
- Other engines are not implemented yet.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from dqt.common.models import ConnectionConfig


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


def connect_sql(connection_config: ConnectionConfig) -> Any:
    """Create a minimal DB connection for SQLite or PostgreSQL.

    Args:
        connection_config: Validated DQT connection configuration.

    Returns:
        A database connection object.

    Raises:
        ValueError: If the DSN is unsupported.
        ImportError: If PostgreSQL DSN is used without psycopg installed.

    Example:
        conn = connect_sql(connection_config)
    """
    dsn = connection_config.dsn.strip()

    if dsn.startswith("sqlite:///"):
        db_path = dsn.removeprefix("sqlite:///")
        return sqlite3.connect(db_path)

    if dsn.startswith("postgresql://") or dsn.startswith("postgres://"):
        try:
            import psycopg
        except ImportError as exc:
            raise ImportError(
                "PostgreSQL support requires the 'psycopg' package to be installed."
            ) from exc
        return psycopg.connect(dsn)

    raise ValueError("Unsupported DSN. Expected sqlite:///..., postgresql://..., or postgres://...")


def discover_schema(connection_config: ConnectionConfig) -> list[DiscoveredTable]:
    """Discover user tables and columns from a relational database.

    This function currently supports SQLite and PostgreSQL. It returns a
    normalized in-memory representation that later pipeline stages can use.

    Args:
        connection_config: Validated DQT connection configuration.

    Returns:
        A list of discovered tables with their columns.

    Example:
        tables = discover_schema(connection_config)
    """
    dsn = connection_config.dsn.strip()

    if dsn.startswith("sqlite:///"):
        return _discover_sqlite(connection_config)

    if dsn.startswith("postgresql://") or dsn.startswith("postgres://"):
        return _discover_postgres(connection_config)

    raise ValueError("Unsupported DSN. Expected sqlite:///..., postgresql://..., or postgres://...")


def _discover_sqlite(connection_config: ConnectionConfig) -> list[DiscoveredTable]:
    conn = connect_sql(connection_config)
    try:
        cursor = conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        )
        table_names = [row[0] for row in cursor.fetchall()]
        tables: list[DiscoveredTable] = []

        for table_name in table_names:
            pragma_rows = conn.execute(f"PRAGMA table_info('{table_name}')").fetchall()
            columns = [
                DiscoveredColumn(
                    schema_name="main",
                    table_name=table_name,
                    column_name=row[1],
                    data_type=row[2] or "UNKNOWN",
                    nullable=(row[3] == 0),
                )
                for row in pragma_rows
            ]
            tables.append(
                DiscoveredTable(
                    schema_name="main",
                    table_name=table_name,
                    columns=columns,
                )
            )
        return tables
    finally:
        conn.close()


def _discover_postgres(connection_config: ConnectionConfig) -> list[DiscoveredTable]:
    conn = connect_sql(connection_config)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT table_schema, table_name, column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_schema NOT IN ('information_schema', 'pg_catalog')
                ORDER BY table_schema, table_name, ordinal_position
                """
            )
            rows = cur.fetchall()

        table_map: dict[tuple[str, str], list[DiscoveredColumn]] = {}
        for schema_name, table_name, column_name, data_type, is_nullable in rows:
            key = (schema_name, table_name)
            table_map.setdefault(key, []).append(
                DiscoveredColumn(
                    schema_name=schema_name,
                    table_name=table_name,
                    column_name=column_name,
                    data_type=data_type,
                    nullable=(is_nullable == "YES"),
                )
            )

        return [
            DiscoveredTable(schema_name=s, table_name=t, columns=cols)
            for (s, t), cols in table_map.items()
        ]
    finally:
        conn.close()
