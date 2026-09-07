"""
Metric aggregation for DQT SQL pipelines.

This module provides small helpers for computing run-level summary metrics from
column and table profiling output. It remains focused on data quality, not
service monitoring.
"""

from __future__ import annotations

from dqt.common.models import DQDimension, DQMetric
from dqt.sql.profiling import TableProfile


def compute_run_metrics(profiles: list[TableProfile], run_id: str) -> list[DQMetric]:
    """Compute simple run-level summary metrics.

    Current metrics:
    - table_count
    - column_count
    - average_completeness

    Args:
        profiles: Table profiles from profiling.
        run_id: Pipeline run identifier.

    Returns:
        Run-level DQMetric records.

    Example:
        metrics = compute_run_metrics(profiles, run_id="run-001")
    """
    table_count = len(profiles)
    column_profiles = [column for table in profiles for column in table.columns]
    column_count = len(column_profiles)

    if column_count == 0:
        average_completeness = 1.0
    else:
        scores = []
        for column in column_profiles:
            if column.row_count == 0:
                scores.append(1.0)
            else:
                scores.append(1.0 - (column.null_count / column.row_count))
        average_completeness = sum(scores) / len(scores)

    return [
        DQMetric(
            run_id=run_id,
            metric_name="table_count",
            score=1.0,
            value=float(table_count),
            metadata={},
        ),
        DQMetric(
            run_id=run_id,
            metric_name="column_count",
            score=1.0,
            value=float(column_count),
            metadata={},
        ),
        DQMetric(
            run_id=run_id,
            metric_name="average_completeness",
            score=average_completeness,
            value=average_completeness,
            metadata={},
        ),
    ]


#: Marks a metric as a rollup rather than a directly measured score, and says
#: over what. Without it a table rollup is indistinguishable from a column
#: score -- both carry a dimension, a table name and a score -- and every
#: consumer would have to reimplement the distinction from the absent column
#: name.
ROLLUP_SCOPES = ("table", "run")


def roll_up_dimension_scores(metrics: list[DQMetric], run_id: str) -> list[DQMetric]:
    """Summarise per-column dimension scores at table and run level.

    **The run-level number is a mean over the columns, not a mean of the
    table means.** Those differ whenever tables have different widths, and
    the column mean is what ``RunStore.average_score_by_dimension`` has
    always returned -- so reproducing it here keeps every chart already drawn
    where it was. A mean of table means would weigh a one-column lookup table
    equally with a forty-column fact table.

    A dimension already scored at table scope -- referential integrity, which
    `F2` measures per table because it is a property of a relationship rather
    than of a column -- is left alone. There are no columns to average, and
    inventing a second score for the same (table, dimension) pair would make
    the answer depend on which row a reader happened to select.

    Args:
        metrics: Every metric the run produced, including the per-column
            dimension scores this summarises.
        run_id: The current run.

    Returns:
        The new rollup metrics. The input is not modified.

    Example:
        rollups = roll_up_dimension_scores(metrics, run_id="run-001")
    """
    column_scores: dict[tuple[DQDimension, str, str], list[float]] = {}
    scored_at_table_scope: set[tuple[DQDimension, str, str]] = set()

    for metric in metrics:
        if metric.dimension is None or metric.score is None:
            continue
        schema = metric.schema_name or ""
        table = metric.table_name or ""
        if metric.column_name is None:
            scored_at_table_scope.add((metric.dimension, schema, table))
            continue
        column_scores.setdefault((metric.dimension, schema, table), []).append(metric.score)

    rollups: list[DQMetric] = []
    per_dimension: dict[DQDimension, list[float]] = {}

    for (dimension, schema, table), scores in column_scores.items():
        per_dimension.setdefault(dimension, []).extend(scores)
        if (dimension, schema, table) in scored_at_table_scope:
            continue
        rollups.append(
            DQMetric(
                run_id=run_id,
                dimension=dimension,
                score=sum(scores) / len(scores),
                schema_name=schema or None,
                table_name=table or None,
                metadata={"scope": "table", "rolled_up_from": len(scores)},
            )
        )

    for dimension, scores in per_dimension.items():
        rollups.append(
            DQMetric(
                run_id=run_id,
                dimension=dimension,
                score=sum(scores) / len(scores),
                metadata={"scope": "run", "rolled_up_from": len(scores)},
            )
        )

    return rollups
