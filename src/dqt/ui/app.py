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
    uvicorn.run(app, host="127.0.0.1", port=8000)

Bind the loopback address, not ``0.0.0.0``
------------------------------------------

Both examples above reach only the machine the server runs on, and that is
deliberate. **This application has no authentication.** Read-only does not
mean harmless: what these endpoints return is schema names, table names,
column names and issue messages read out of whatever database DQT was
pointed at — a map of a production schema together with a list of where its
data is weakest.

Serving that on ``0.0.0.0`` publishes it to every network the host can reach.
If it needs to be reachable from elsewhere, put it behind something that
authenticates — a reverse proxy with access control, or an SSH tunnel — and
make that a deliberate decision rather than a default inherited from an
example.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

try:
    from fastapi import FastAPI, HTTPException, Query
    from fastapi.responses import HTMLResponse

    _FASTAPI_AVAILABLE = True
except ImportError:
    _FASTAPI_AVAILABLE = False

from dqt import __version__
from dqt.ui.api import (
    get_dimension_scores,
    get_issue_counts_by_dimension,
    get_issue_counts_by_severity,
    get_rule_history,
    get_run_issues,
    get_run_metrics,
    get_run_rule_results,
    get_run_summary,
    list_runs,
    list_tables_for_run,
)
from dqt.ui.pages import (
    ISSUE_PAGE_SIZE,
    issues_page,
    overview_page,
    rule_history_page,
    rules_page,
    run_page,
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
    version=__version__,
)


def _store_path() -> Path:
    """Return the active RunStore path from the environment or default."""
    return Path(os.environ.get("DQT_STORE_PATH", str(_DEFAULT_STORE)))


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@app.get("/health", tags=["infra"])
def health() -> dict[str, Any]:
    """Report that the process is up, and which store it is serving.

    The store path is included deliberately. A health check that only says
    "ok" cannot distinguish a server reading the right database from one
    reading an empty file it created itself, and the second failure looks
    exactly like a quiet week of clean data.

    Returns:
        ``status`` and the resolved store path.

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

    Args:
        connection_id: Only runs against this logical connection.
        status: Only runs with this outcome -- ``success``, ``failed`` or
            ``partial``.
        limit: Maximum runs returned, between 1 and 500. Bounded because an
            unbounded list grows with how long DQT has been in use.

    Returns:
        One dict per run, newest first.

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
    """Summarise one run.

    Args:
        run_id: The run to summarise.

    Returns:
        The run's metadata plus aggregated ``metric_count``,
        ``issue_count`` and ``overall_completeness``.

    Raises:
        HTTPException: 404 if no such run. An empty summary would be
            indistinguishable from a run that found nothing, which is the
            more reassuring of the two answers and the wrong one.

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
    """List the tables a run profiled.

    Args:
        run_id: The run to read.

    Returns:
        Qualified table names, sorted and de-duplicated. An unknown run
        yields an empty list rather than an error: "profiled nothing" is a
        true answer about a run that does not exist, and the caller asking
        this question is usually iterating rather than navigating.

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
    """Return the metrics a run recorded.

    Args:
        run_id: The run to read.
        table_name: Only metrics for this table.
        dimension: Only metrics for this dimension, e.g. ``completeness``.

    Returns:
        One dict per metric.

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
    """Return the issues a run found.

    Args:
        run_id: The run to read.
        severity: Only issues at this severity -- ``info``, ``warning``,
            ``error`` or ``critical``.
        table_name: Only issues about this table.

    Returns:
        One dict per issue, each carrying counts as evidence rather than the
        offending rows.

    Example::

        GET /runs/run-abc12345/issues?severity=critical
    """
    return get_run_issues(
        store_path=_store_path(),
        run_id=run_id,
        severity=severity,
        table_name=table_name,
    )


# ---------------------------------------------------------------------------
# Screens (VIZ-3)
# ---------------------------------------------------------------------------
#
# Server-rendered HTML, added beside the JSON rather than instead of it. The
# pages are pure functions in dqt.ui.pages; these routes only fetch and hand
# over, so the part that can go wrong here is routing and nothing else.
#
# Read-only, like everything in this module. docs/PLAN-VIZ-UI.md section 7:
# a button that opens a connection to a production database does not belong
# on an HTTP surface with no authentication.


@app.get("/ui", tags=["screens"], response_class=HTMLResponse)
def screen_overview() -> str:
    """Render the overview screen.

    Returns:
        The page HTML.

    Example::

        GET /ui
    """
    store = _store_path()
    runs = list_runs(store_path=store, limit=20)
    latest = runs[0] if runs else None
    if latest is None:
        return overview_page(
            runs=[],
            run=None,
            dimension_scores={},
            issues_by_severity={},
            issues_by_dimension={},
        )
    run_id = str(latest["run_id"])
    return overview_page(
        runs=runs,
        run=latest,
        dimension_scores=dict(get_dimension_scores(store, run_id)),
        issues_by_severity=get_issue_counts_by_severity(store, run_id),
        issues_by_dimension=get_issue_counts_by_dimension(store, run_id),
    )


@app.get("/ui/runs/{run_id}", tags=["screens"], response_class=HTMLResponse)
def screen_run(run_id: str) -> str:
    """Render one run's explorer screen.

    Args:
        run_id: The run to show.

    Returns:
        The page HTML.

    Raises:
        HTTPException: 404 if the run is unknown. An empty run page reads as
            a run that went perfectly, so "nothing here" must not render as
            "nothing wrong".

    Example::

        GET /ui/runs/run-001
    """
    store = _store_path()
    run = _require_run(store, run_id)
    tables = [
        {"schema_name": None, "table_name": name, "issue_count": 0}
        for name in list_tables_for_run(store_path=store, run_id=run_id)
    ]
    for issue in get_run_issues(store_path=store, run_id=run_id):
        for entry in tables:
            if entry["table_name"] == issue.get("table_name"):
                entry["issue_count"] = int(entry["issue_count"] or 0) + 1
    return run_page(
        run=run,
        tables=tables,
        dimension_scores=dict(get_dimension_scores(store, run_id)),
        issues_by_severity=get_issue_counts_by_severity(store, run_id),
    )


@app.get("/ui/runs/{run_id}/issues", tags=["screens"], response_class=HTMLResponse)
def screen_issues(run_id: str) -> str:
    """Render one run's issue list.

    Args:
        run_id: The run to show.

    Returns:
        The page HTML.

    Raises:
        HTTPException: 404 if the run is unknown.

    Example::

        GET /ui/runs/run-001/issues
    """
    store = _store_path()
    run = _require_run(store, run_id)
    issues = get_run_issues(store_path=store, run_id=run_id)
    return issues_page(run=run, issues=issues[:ISSUE_PAGE_SIZE], total=len(issues))


def _require_run(store: Path, run_id: str) -> dict[str, Any]:
    """Return a run, or refuse with a 404.

    Args:
        store: Path to the RunStore file.
        run_id: The run to look for.

    Returns:
        The run summary.

    Raises:
        HTTPException: 404 if no such run exists.

    Example::

        run = _require_run(store, "run-001")
    """
    summary = get_run_summary(store_path=store, run_id=run_id)
    if not summary or summary.get("run_id") is None:
        raise HTTPException(status_code=404, detail=f"Unknown run: {run_id}")
    return summary


@app.get("/ui/runs/{run_id}/rules", tags=["screens"], response_class=HTMLResponse)
def screen_rules(run_id: str) -> str:
    """Render what each rule did in one run.

    Args:
        run_id: The run to show.

    Returns:
        The page HTML.

    Raises:
        HTTPException: 404 if the run is unknown, consistent with the other
            run-scoped screens.

    Example::

        GET /ui/runs/run-001/rules
    """
    store = _store_path()
    return rules_page(
        run=_require_run(store, run_id),
        results=get_run_rule_results(store, run_id),
    )


@app.get("/ui/rules/{rule_name}", tags=["screens"], response_class=HTMLResponse)
def screen_rule_history(rule_name: str) -> str:
    """Render one rule's results across runs.

    Not scoped to a run: history is the question that spans them.

    A rule with no history is a page rather than a 404. "Never ran" is an
    answer, and a different one from "does not exist" -- a 404 would tell a
    DBA their rule name was wrong when the truth may be that the rule has
    never matched anything, which is exactly what this screen exists to
    surface.

    Args:
        rule_name: The rule to follow.

    Returns:
        The page HTML.

    Example::

        GET /ui/rules/not-null-email
    """
    return rule_history_page(
        rule_name=rule_name,
        history=get_rule_history(_store_path(), rule_name),
    )
