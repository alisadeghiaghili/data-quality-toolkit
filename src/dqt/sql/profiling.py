"""
Basic SQL profiling for DQT.

This module provides minimal SQL-first profiling focused on row counts and
column null counts. It is intentionally small and DBA-oriented, forming the
first usable slice of the larger profiling roadmap.

Current implementation:
- Table row counts.
- Column null counts.
- Column completeness scores derived from null counts.

Query cost, stated plainly. Profiling currently issues one row-count query per
table plus one null-count query per column, so a table with N columns costs
N + 1 round trips and N + 1 scans. That is unchanged by `DQT-08`, which only
moved where the SQL is built: every statement now comes from
``dialect.select_aggregates_sql``, which takes a *sequence* of expressions.
Folding the N + 1 statements into one aggregate query per table is therefore a
change to this module alone, needing nothing from the dialect layer. That work
belongs to the performance unit, not here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from dqt.common.models import ConnectionConfig, DQMetric
from dqt.sql._connect import get_connection, get_dialect_for
from dqt.sql.dialects import Dialect
from dqt.sql.schema_discovery import DiscoveredTable


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
        self._dialect: Dialect = get_dialect_for(connection_config)

    def profile_tables(self, tables: list[DiscoveredTable]) -> list[TableProfile]:
        """Profile discovered tables with simple aggregate queries.

        Args:
            tables: Tables discovered by schema discovery.

        Returns:
            A list of table profiles.

        Example:
            profiles = profiler.profile_tables(tables)
        """
        conn = get_connection(self._connection_config)
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
                    metric_name="row_count",
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
        """Profile one table with a single aggregate query.

        The row count and every column's NULL count come back from one scan.
        This used to be one query per column plus a row count, so a
        hundred-column table cost a hundred and one full scans to produce what
        one pass can.

        ``COUNT(*)`` counts rows and ``COUNT(col)`` counts non-NULL values, so
        the NULL count is their difference -- no per-column predicate, and no
        second look at the table.

        Args:
            conn: Open connection to the profiled database.
            table: The table to profile.

        Returns:
            Its :class:`TableProfile`.

        Example:
            profile = profiler._profile_table(conn, table)
        """
        table_ref = self._dialect.qualified_identifier(table.schema_name, table.table_name)
        expressions = ["COUNT(*)"] + [
            f"COUNT({self._dialect.quote_identifier(column.column_name)})"
            for column in table.columns
        ]
        statement = self._dialect.select_aggregates_sql(table_ref, expressions)
        row = conn.execute(statement).fetchone()

        # An aggregate over an empty table returns one row of zeros rather
        # than no rows; reading it as "no result" would make row_count wrong.
        row_count = int(row[0])
        columns = [
            ColumnProfile(
                schema_name=column.schema_name,
                table_name=column.table_name,
                column_name=column.column_name,
                null_count=row_count - int(row[position]),
                row_count=row_count,
            )
            for position, column in enumerate(table.columns, start=1)
        ]
        return TableProfile(
            schema_name=table.schema_name,
            table_name=table.table_name,
            row_count=row_count,
            columns=columns,
        )
