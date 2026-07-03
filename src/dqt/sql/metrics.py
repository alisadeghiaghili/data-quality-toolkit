"""
Metric aggregation for DQT SQL pipelines.

This module provides small helpers for computing run-level summary metrics from
column and table profiling output. It remains focused on data quality, not
service monitoring.
"""

from __future__ import annotations

from dqt.common.models import DQMetric
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
            dimension="table_count",
            score=1.0,
            value=float(table_count),
            metadata={},
        ),
        DQMetric(
            run_id=run_id,
            dimension="column_count",
            score=1.0,
            value=float(column_count),
            metadata={},
        ),
        DQMetric(
            run_id=run_id,
            dimension="average_completeness",
            score=average_completeness,
            value=average_completeness,
            metadata={},
        ),
    ]
