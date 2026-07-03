"""
Monitoring stage for DQT SQL pipelines.

This module is intentionally lightweight. In DQT, monitoring means tracking
data-quality metrics over time, not service health or infrastructure
telemetry.
"""

from __future__ import annotations

from dqt.common.models import DQMetric


def monitor(metrics: list[DQMetric]) -> list[DQMetric]:
    """Return metrics unchanged for the initial pipeline shell.

    Args:
        metrics: Data-quality metrics produced by pipeline stages.

    Returns:
        The same list of metrics.

    Example:
        monitored = monitor(metrics)
    """
    return metrics
