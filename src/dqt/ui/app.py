"""
dqt.ui.app
==========

Minimal FastAPI application skeleton for DQT.

Exposes **read-only** data-quality endpoints backed by the RunStore via
``dqt.ui.api``.  No service performance metrics, no masking, no MDM.

Endpoints
---------

* ``GET /runs``                         — list recent pipeline runs.
* ``GET /runs/{run_id}``                — summary for a single run.
* ``GET /runs/{run_id}/tables``         — tables profiled in a run.
* ``GET /runs/{run_id}/metrics``        — metrics for a run (filterable).
* ``GET /runs/{run_id}/issues``         — issues for a run (filterable).
* ``GET /health``                       — liveness probe.

Running the server::

    pip install fastapi uvicorn
    export DQT_STORE_PATH=dqt_runs.db
    uvicorn dqt.ui.app:app --reload

Or from Python::

    import uvicorn
    from dqt.ui.app import app
    uvicorn.run(app, host="0.0.0.0", port=8000)
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

try:
    from fastapi import FastAPI, HTTPException, Query

    _FASTAPI_AVAILABLE = True
except ImportError:
    _FASTAPI_AVAILABLE = False

from dqt.ui.api import (
    get_run_issues,
    get_run_metrics,
    get_run_summary,
    list_runs,
    list_tables_for_run,
)

_DEFAULT_STORE = Path(os.environ.get("DQT_STORE_PATH", "dqt_runs.db"))

if not _FASTAPI_AVAILABLE:
    raise ImportError(
        "FastAPI is required to run the DQT web UI. Install it with: pip install fastapi uvicorn"
    )

app = FastAPI(
    title="DQT — SQL Data Quality Toolkit",
    description=(
        "Read-only REST API for exploring DQT pipeline run results. "
        "Data-quality focused: profiling, diagnostics, metrics, issues."
    ),
    version="0.1.0",
)


def _store_path() -> Path:
    """Return the active RunStore path from the environment or default."""
    return Path(os.environ.get("DQT_STORE_PATH", str(_DEFAULT_STORE)))


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@app.get("/health", tags=["infra"])
def health() -> dict[str, Any]:
    """Liveness probe. Returns ``{\"status\": \"ok\"}``.

    Example::

        GET /health
        → {"status": "ok", "store": "dqt_runs.db"}
    """
    return {"status": "ok", "store": str(_store_path())}


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


@app.get("/runs", tags=["runs"])
def get_runs(
    connection_id: str | None = Query(None, description="Filter by connection ID"),
    status: str | None = Query(None, description="Filter by status: success|failed|partial"),
    limit: int = Query(50, ge=1, le=500, description="Max rows returned"),
) -> list[dict[str, Any]]:
    """List recent pipeline runs, newest first.

    Example::

        GET /runs?status=success&limit=10
    """
    return list_runs(
        store_path=_store_path(),
        connection_id=connection_id,
        status=status,
        limit=limit,
    )


@app.get("/runs/{run_id}", tags=["runs"])
def get_run(
    run_id: str,
) -> dict[str, Any]:
    """Get summary for a single run.

    Returns run metadata plus aggregated ``metric_count``, ``issue_count``,
    and ``overall_completeness``.

    Example::

        GET /runs/run-abc12345
    """
    summary = get_run_summary(store_path=_store_path(), run_id=run_id)
    if "error" in summary:
        raise HTTPException(status_code=404, detail=summary["error"])
    return summary


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------


@app.get("/runs/{run_id}/tables", tags=["schema"])
def get_tables(
    run_id: str,
) -> list[str]:
    """List tables that were profiled in a run.

    Example::

        GET /runs/run-abc12345/tables
        → ["public.orders", "public.customers"]
    """
    return list_tables_for_run(store_path=_store_path(), run_id=run_id)


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


@app.get("/runs/{run_id}/metrics", tags=["metrics"])
def get_metrics(
    run_id: str,
    table_name: str | None = Query(None, description="Filter by table name"),
    dimension: str | None = Query(None, description="Filter by DQ dimension, e.g. completeness"),
) -> list[dict[str, Any]]:
    """Get data-quality metrics for a run.

    Example::

        GET /runs/run-abc12345/metrics?dimension=completeness
    """
    return get_run_metrics(
        store_path=_store_path(),
        run_id=run_id,
        table_name=table_name,
        dimension=dimension,
    )


# ---------------------------------------------------------------------------
# Issues
# ---------------------------------------------------------------------------


@app.get("/runs/{run_id}/issues", tags=["issues"])
def get_issues(
    run_id: str,
    severity: str | None = Query(
        None, description="Filter by severity: info|warning|error|critical"
    ),
    table_name: str | None = Query(None, description="Filter by table name"),
) -> list[dict[str, Any]]:
    """Get data-quality issues detected in a run.

    Example::

        GET /runs/run-abc12345/issues?severity=critical
    """
    return get_run_issues(
        store_path=_store_path(),
        run_id=run_id,
        severity=severity,
        table_name=table_name,
    )
