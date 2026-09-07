"""
Monitoring for DQT: how each metric moved since the last run.

DQT records the change without being told anything, and calls it a problem
only when told how far is too far. A completeness score that swings ten
points a day is alarming on a customer table and normal on a staging table
that is truncated and reloaded, and nothing in the number distinguishes
them -- the same reasoning :class:`~dqt.common.models.TimelinessConfig`
rests on.

Monitoring here means **data**-quality metrics over time. Service health,
latency and wait statistics are permanent non-goals; see `AGENTS.md`.

Two properties are load-bearing and easy to get wrong:

* **A first observation has no drift, rather than zero drift.** Zero would
  put a flat line on the left edge of every trend and make a column first
  seen today indistinguishable from one stable for a year.
* **Only falls are reported.** A tolerance on the absolute change is the
  natural implementation and alerts whenever the data gets *cleaner*.
"""

from __future__ import annotations

from typing import Any

from dqt.common.models import DQIssue, DQMetric, MonitoringConfig


def monitor(metrics: list[DQMetric], store: Any = None) -> list[DQMetric]:
    """Annotate each metric with how far it moved since the last run.

    Called without a *store* this returns its input unchanged, which is what
    it did before `F8` and keeps every existing caller working.

    Args:
        metrics: The run's metrics, modified in place and returned.
        store: A :class:`~dqt.common.storage.RunStore` to read history from,
            or None to skip the comparison entirely.

    Returns:
        The same metrics, with ``previous_score`` and ``delta`` added to the
        metadata of any that have a prior observation.

    Example:
        annotated = monitor(metrics, store=store)
    """
    if store is None:
        return metrics

    for metric in metrics:
        if metric.score is None:
            continue
        history = store.load_metric_history(
            schema_name=metric.schema_name,
            table_name=metric.table_name,
            column_name=metric.column_name,
            dimension=metric.dimension,
            metric_name=metric.metric_name,
            limit=1,
        )
        # Monitoring runs *before* persistence, so the newest stored row is
        # the previous run rather than this one. That ordering is deliberate:
        # it is what lets the deltas themselves be stored, so the history
        # carries them and a chart does not have to recompute them. A metric
        # seen for the first time has no stored row at all.
        if not history:
            continue

        previous = float(history[0]["score"])
        metric.metadata = dict(metric.metadata or {})
        metric.metadata["previous_score"] = previous
        metric.metadata["delta"] = round(metric.score - previous, 10)

    return metrics


def drift_issues(
    metrics: list[DQMetric], config: MonitoringConfig | None, run_id: str
) -> list[DQIssue]:
    """Report metrics that fell further than the configured tolerance.

    Pure over the annotations :func:`monitor` added, so the judgement is
    testable without a store.

    Args:
        metrics: Metrics already annotated by :func:`monitor`.
        config: The tolerance, or None to judge nothing.
        run_id: The current run.

    Returns:
        One issue per metric that fell too far. Empty when *config* is None.

    Example:
        issues = drift_issues(metrics, config, run_id="run-001")
    """
    if config is None:
        return []

    issues: list[DQIssue] = []
    for metric in metrics:
        # Dimension scores only. The tolerance is a fall in a score, which
        # lives in [0, 1]; a row count falling by 400 is not comparable to
        # that, and pretending it is would make one tolerance govern two
        # incomparable scales. Measurements still carry their delta -- the
        # number is recorded, only the verdict is withheld.
        if metric.dimension is None:
            continue
        delta = (metric.metadata or {}).get("delta")
        # Only falls. Getting better is not a problem to report, and a
        # tolerance on the absolute change would alert on exactly that.
        if not isinstance(delta, int | float) or delta >= 0:
            continue
        if -delta <= config.max_score_drop:
            continue

        subject = metric.dimension or metric.metric_name or "metric"
        where = ".".join(part for part in (metric.table_name, metric.column_name) if part)
        issues.append(
            DQIssue(
                issue_id=f"{run_id}:{where or 'run'}:{subject}:drift",
                run_id=run_id,
                dimension=metric.dimension,
                severity="warning",
                message=(
                    f"Drift: {subject} on '{where or 'this run'}' fell "
                    f"{-delta:.3f} since the previous run, past the "
                    f"{config.max_score_drop} tolerance "
                    f"({metric.metadata['previous_score']:.3f} -> {metric.score:.3f})."
                ),
                evidence={
                    "previous_score": metric.metadata["previous_score"],
                    "score": metric.score,
                    "delta": delta,
                },
                schema_name=metric.schema_name,
                table_name=metric.table_name,
                column_name=metric.column_name,
            )
        )
    return issues
