"""
Rules stage for DQT SQL pipelines.

This module is intentionally stubbed in the current phase. The project
conventions require a dedicated rules module, but full rule execution is part
of a later milestone.
"""

from __future__ import annotations

from dqt.common.models import RuleRunResult


def apply_rules(run_id: str) -> list[RuleRunResult]:
    """Return rule execution results for the current run.

    The current implementation is a stub and returns an empty list.

    Args:
        run_id: Pipeline run identifier.

    Returns:
        An empty list of rule execution summaries.

    Example:
        results = apply_rules(run_id="run-001")
    """
    return []
