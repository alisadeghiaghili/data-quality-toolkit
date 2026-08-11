"""
Basic SQL profiling for DQT.

This module provides minimal SQL-first profiling focused on row counts and
column null counts. It is intentionally small and DBA-oriented, forming the
first usable slice of the larger profiling roadmap.

Current implementation:
- Table row counts.
- Column null counts.
- Column completeness scores derived from null counts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from dqt.common.models import ConnectionConfig, DQMetric
from dqt.sql.schema_discovery import DiscoveredColumn, DiscoveredTable, connect_sql


@dataclass(slots=True)
class ColumnProfile:
    """Minimal profile for one column.

    Attributes:
        schema_name: Schema name.
        table_name: Table name.
        column_name: Column name.
        null_count: Number of NULL values in the column.
        row_count: Number of rows in the table.

    Example:
        profile = ColumnProfile(
            schema_name="main",
            table_name="customers",
            column_name="email",
            null_count=10,
            row_count=100,
        )
    """

    schema_name: str
    table_name: str
    column_name: str
    null_count: int
    row_count: int


@dataclass(slots=True)
class TableProfile:
    """Minimal profile for one table.

    Attributes:
        schema_name: Schema name.
        table_name: Table name.
        row_count: Number of rows in the table.
        columns: Column-level profiles for the table.

    Example:
        profile = TableProfile(
            schema_name="main",
            table_name="customers",
            row_count=100,
            columns=[],
        )
    """

    schema_name: str
    table_name: str
    row_count: int
    columns: list[ColumnProfile]


class SqlProfiler:
    """Minimal SQL profiler for DQT.

    This profiler computes a basic profiling slice that is enough to feed the
    first pipeline shell: row counts, null counts, and completeness-oriented
    metrics.

    Args:
        connection_config: Validated connection settings.

    Example:
        profiler = SqlProfiler(connection_config)
        profiles = profiler.profile_tables(discovered_tables)
    """

    def __init__(self, connection_config: ConnectionConfig) -> None:
        self._connection_config = connection_config

    def profile_tables(self, tables: list[DiscoveredTable]) -> list[TableProfile]:
        """Profile discovered tables with simple aggregate queries.

        Args:
            tables: Tables discovered by schema discovery.

        Returns:
            A list of table profiles.

        Example:
            profiles = profiler.profile_tables(tables)
        """
        conn = connect_sql(self._connection_config)
        try:
            return [self._profile_table(conn, table) for table in tables]
        finally:
            conn.close()

    def build_metrics(self, profiles: list[TableProfile], run_id: str) -> list[DQMetric]:
        """Convert profiling results into DQMetric objects.

        Args:
            profiles: Table profiles from profiling.
            run_id: Pipeline run identifier.

        Returns:
            A flat list of DQMetric instances.

        Example:
            metrics = profiler.build_metrics(profiles, run_id="run-001")
        """
        metrics: list[DQMetric] = []
        for profile in profiles:
            metrics.append(
                DQMetric(
                    run_id=run_id,
                    dimension="row_count",
                    score=1.0,
                    schema_name=profile.schema_name,
                    table_name=profile.table_name,
                    value=float(profile.row_count),
                    metadata={},
                )
            )
            for column in profile.columns:
                completeness = 1.0
                if column.row_count > 0:
                    completeness = 1.0 - (column.null_count / column.row_count)

                metrics.append(
                    DQMetric(
                        run_id=run_id,
                        dimension="completeness",
                        score=completeness,
                        schema_name=column.schema_name,
                        table_name=column.table_name,
                        column_name=column.column_name,
                        value=float(column.null_count),
                        metadata={
                            "null_count": column.null_count,
                            "row_count": column.row_count,
                        },
                    )
                )
        return metrics

    def _profile_table(self, conn: Any, table: DiscoveredTable) -> TableProfile:
        row_count = self._fetch_row_count(conn, table)
        column_profiles = [
            self._profile_column(conn, table, column, row_count) for column in table.columns
        ]
        return TableProfile(
            schema_name=table.schema_name,
            table_name=table.table_name,
            row_count=row_count,
            columns=column_profiles,
        )

    def _fetch_row_count(self, conn: Any, table: DiscoveredTable) -> int:
        table_ref = _table_ref(table.schema_name, table.table_name)
        cursor = conn.execute(f"SELECT COUNT(*) FROM {table_ref}")
        return int(cursor.fetchone()[0])

    def _profile_column(
        self,
        conn: Any,
        table: DiscoveredTable,
        column: DiscoveredColumn,
        row_count: int,
    ) -> ColumnProfile:
        table_ref = _table_ref(table.schema_name, table.table_name)
        col_ref = _ident(column.column_name)
        cursor = conn.execute(f"SELECT COUNT(*) FROM {table_ref} WHERE {col_ref} IS NULL")
        null_count = int(cursor.fetchone()[0])
        return ColumnProfile(
            schema_name=column.schema_name,
            table_name=column.table_name,
            column_name=column.column_name,
            null_count=null_count,
            row_count=row_count,
        )


def _ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _table_ref(schema_name: str, table_name: str) -> str:
    if schema_name in {"main", ""}:
        return _ident(table_name)
    return f"{_ident(schema_name)}.{_ident(table_name)}"
