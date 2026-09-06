"""
SQL profiling for DQT.

Computes, per table:

- The row count.
- Per column: NULL count, minimum, maximum, mean, and distinct count.

Query cost, stated plainly. **One aggregate query per table**, whatever the
column count and whatever the statistics asked for. A hundred-column table
producing five statistics each is one ``SELECT`` carrying roughly five
hundred aggregate expressions over a single scan -- not five hundred scans,
which is what the arithmetic looks like if each statistic fetches itself.
`AGENTS.md` "Performance rules" requires this, and
``tests/unit/sql/test_column_statistics.py`` counts the statements SQLite
actually executes, because a per-column implementation returns identical
numbers and only the clock would tell.

Two statistics are conditional, for different reasons:

- ``MIN``/``MAX``/``AVG`` are asked for only where the column's type
  supports them, and the **dialect** decides that. ``AVG`` over text is not
  a harmless no-op -- PostgreSQL raises, SQLite silently answers ``0.0`` --
  and a reported mean of zero cannot be told from a column that genuinely
  averages zero.
- ``COUNT(DISTINCT ...)`` holds every distinct value it sees, so it is the
  one statistic that can cost real memory server-side. It is on by default
  and can be declined through :class:`~dqt.common.models.ProfilingConfig`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from dqt.common.models import ConnectionConfig, DQMetric, ProfilingConfig, SamplingConfig
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
        data_type: The column's declared database type, carried through from
            schema discovery. Consumers report this as the column's type; the
            profiler's own class name is not it.
        min_value: Smallest value present, or ``None`` when the column holds
            no values or its type does not order.
        max_value: Largest value present, on the same terms.
        mean_value: Arithmetic mean of the non-NULL values, or ``None`` for
            any type the engine cannot genuinely average. Absent rather than
            zero: SQLite answers ``AVG`` over text with ``0.0``, and a
            reported zero cannot be told from a column that averages zero.
        distinct_count: Number of distinct non-NULL values, or ``None`` when
            distinct counting was declined. ``None`` and ``0`` are different
            answers -- the second is what an all-NULL column genuinely has.
        distinct_is_approximate: Whether *distinct_count* is an estimate.
            Set from what the engine actually did, not from what was asked
            for, so a request an engine cannot honour reads as exact.

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
    data_type: str = ""
    min_value: Any = None
    max_value: Any = None
    mean_value: float | None = None
    distinct_count: int | None = None
    distinct_is_approximate: bool = False


@dataclass(slots=True)
class TableProfile:
    """Minimal profile for one table.

    Attributes:
        schema_name: Schema name.
        table_name: Table name.
        row_count: Number of rows read. **The sample's size when *sampling*
            is set**, not the table's -- which is why the next attribute is
            not optional decoration.
        columns: Column-level profiles for the table.
        sampling: How the sample was taken, or None when every row was read.
            Absent rather than a falsy placeholder, so that a profile stored
            before sampling existed reads correctly as unsampled.

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
    sampling: dict[str, object] | None = None


@dataclass(slots=True)
class _ColumnPlan:
    """Where one column's statistics sit in the shared aggregate row.

    Every column contributes a variable number of expressions to a single
    ``SELECT`` -- a text column has no mean, a declined distinct count has no
    slot -- so the mapping from column to result position cannot be computed
    from the column's index. It is recorded while the query is built and read
    back afterwards.

    Attributes:
        column: The discovered column this plan describes.
        non_null: Position of its ``COUNT(col)``.
        minimum: Position of its ``MIN``, or None when the type does not order.
        maximum: Position of its ``MAX``, or None on the same terms.
        mean: Position of its ``AVG``, or None when the type is not numeric.
        distinct: Position of its distinct count, or None when declined.
        distinct_is_approximate: Whether the distinct expression was the
            dialect's estimator. Recorded from what was *built*, not what was
            asked for.

    Example:
        plan = _ColumnPlan(column, non_null=1)
    """

    column: Any
    non_null: int
    minimum: int | None = None
    maximum: int | None = None
    mean: int | None = None
    distinct: int | None = None
    distinct_is_approximate: bool = False

    def read(self, row: Any, row_count: int) -> ColumnProfile:
        """Build this column's profile from the shared aggregate row.

        Args:
            row: The single row the aggregate query returned.
            row_count: ``COUNT(*)`` for the table or sample.

        Returns:
            The column's :class:`ColumnProfile`.

        Example:
            profile = plan.read(row, row_count)
        """
        mean = None if self.mean is None or row[self.mean] is None else float(row[self.mean])
        distinct = None if self.distinct is None else int(row[self.distinct])
        return ColumnProfile(
            schema_name=self.column.schema_name,
            table_name=self.column.table_name,
            column_name=self.column.column_name,
            null_count=row_count - int(row[self.non_null]),
            row_count=row_count,
            data_type=self.column.data_type,
            min_value=None if self.minimum is None else row[self.minimum],
            max_value=None if self.maximum is None else row[self.maximum],
            mean_value=mean,
            distinct_count=distinct,
            distinct_is_approximate=self.distinct_is_approximate,
        )


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

    def __init__(
        self,
        connection_config: ConnectionConfig,
        sampling: SamplingConfig | None = None,
        profiling: ProfilingConfig | None = None,
    ) -> None:
        """Resolve the dialect once, for every table this profiler reads.

        The dialect is chosen from the DSN here rather than per query, so a
        profiler cannot end up quoting one table one way and the next
        another.

        Args:
            connection_config: Connection to profile through. May be
                read-only; profiling never writes.
            sampling: How to sample, or None to read every row.
            profiling: Which column statistics to compute, or None for the
                defaults.

        Example:
            profiler = SqlProfiler(ConnectionConfig(id="c", dsn="sqlite:///dev.db"))
        """
        self._connection_config = connection_config
        self._dialect: Dialect = get_dialect_for(connection_config)
        self._sampling = sampling
        self._profiling = profiling or ProfilingConfig()

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
                            # None is carried through rather than defaulted.
                            # A text column has no mean, and a zero here
                            # could not be told from one that averages zero.
                            "min_value": column.min_value,
                            "max_value": column.max_value,
                            "mean_value": column.mean_value,
                            "distinct_count": column.distinct_count,
                            "distinct_is_approximate": column.distinct_is_approximate,
                        },
                    )
                )
        return metrics

    def _plan_column(self, column: Any, expressions: list[str]) -> _ColumnPlan:
        """Append one column's aggregate expressions and record where they land.

        Appending into the caller's list is what keeps this a single query:
        every column's statistics join the same ``SELECT`` rather than
        earning one of their own.

        Which statistics are asked for depends on the column's type, and the
        dialect decides that. ``AVG`` over text is not a harmless no-op --
        PostgreSQL raises and SQLite answers ``0.0`` -- so an ungated
        profiler either crashes or reports a wrong mean.

        Args:
            column: The discovered column to profile.
            expressions: The aggregate list being built, appended to in place.

        Returns:
            The :class:`_ColumnPlan` recording each statistic's position.

        Example:
            plan = profiler._plan_column(column, expressions)
        """
        quoted = self._dialect.quote_identifier(column.column_name)
        plan = _ColumnPlan(column=column, non_null=len(expressions))
        expressions.append(f"COUNT({quoted})")

        if self._dialect.supports_min_max(column.data_type):
            plan.minimum = len(expressions)
            expressions.append(f"MIN({quoted})")
            plan.maximum = len(expressions)
            expressions.append(f"MAX({quoted})")

        if self._dialect.supports_mean(column.data_type):
            plan.mean = len(expressions)
            expressions.append(f"AVG({quoted})")

        if self._profiling.distinct_counts:
            estimated = None
            if self._profiling.approximate_distinct:
                estimated = self._dialect.approximate_distinct_expression(quoted)
            # Set from the expression that was actually built. Setting it from
            # the request would report an exact count as an estimate on every
            # engine that has no estimator to offer.
            plan.distinct_is_approximate = estimated is not None
            plan.distinct = len(expressions)
            expressions.append(estimated or f"COUNT(DISTINCT {quoted})")

        return plan

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
        expressions = ["COUNT(*)"]
        plans = [self._plan_column(column, expressions) for column in table.columns]
        # The sample is substituted where the table name goes, so the same
        # single aggregate query runs over it. One pass either way -- what
        # changes is how many rows that pass reads.
        read_from = table_ref
        sampling: dict[str, object] | None = None
        if self._sampling is not None:
            read_from = self._dialect.sampled_table_expression(
                table_ref,
                self._sampling.strategy,
                self._sampling.limit,
                self._sampling.seed,
            )
            sampling = {
                "strategy": self._sampling.strategy,
                "limit": self._sampling.limit,
            }

        statement = self._dialect.select_aggregates_sql(read_from, expressions)
        row = conn.execute(statement).fetchone()

        # An aggregate over an empty table returns one row of zeros rather
        # than no rows; reading it as "no result" would make row_count wrong.
        row_count = int(row[0])
        columns = [plan.read(row, row_count) for plan in plans]
        return TableProfile(
            schema_name=table.schema_name,
            table_name=table.table_name,
            row_count=row_count,
            columns=columns,
            sampling=sampling,
        )
