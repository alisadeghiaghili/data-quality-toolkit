"""
dqt.ui
======

Thin UI layer for DQT.

This package provides:

* ``api`` — data-access functions that read from ``RunStore`` and return
  plain Python dicts/lists suitable for any UI consumer (web, desktop, CLI).
* ``app`` — a minimal FastAPI application skeleton exposing read-only
  endpoints for run overview, table explorer, issues, and metrics.

The UI layer is strictly data-quality focused.  It never exposes service
performance metrics (latency, CPU, uptime) and never duplicates data-access
logic from ``dqt.common.storage``.

Example::

    from dqt.ui.api import list_runs, get_run_issues
    runs = list_runs(store_path="dqt_runs.db")
"""

from dqt.ui.api import (
    get_run_issues,
    get_run_metrics,
    get_run_summary,
    list_runs,
)

__all__ = [
    "list_runs",
    "get_run_summary",
    "get_run_metrics",
    "get_run_issues",
]
