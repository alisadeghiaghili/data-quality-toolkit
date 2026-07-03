"""
dqt.ui.api
==========

Thin data-access layer for DQT UI consumers.

All functions read from a ``RunStore`` SQLite file and return plain Python
dicts or lists — no DQT domain models leak through this boundary.  This
ensures that web frontends, desktop UIs, and CLI renderers all share the
same data-access path without coupling to internal dataclasses.

This module is **read-only** and never modifies stored data.

Example::

    from dqt.ui.api import list_runs, get_run_summary, get_run_metrics, get_run_issues

    runs = list_runs("dqt_runs.db")
    summary = get_run_summary("dqt_runs.db", run_id=runs[0]["run_id"])
    metrics = get_run_metrics("dqt_runs.db", run_id=runs[0]["run_id"])
    issues  = get_run_issues("dqt_runs.db", run_id=runs[0]["run_id"])
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from dqt.common.storage import RunStore


def _store(store_path: str | Path) -> RunStore:
    """Return a RunStore instance for the given path."""
    return RunStore(db_path=store_path)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def list_runs(
    store_path: str | Path,
    connection_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return recent pipeline runs from the store.

    Each dict contains the keys: ``run_id``, ``connection_id``,
    ``started_at``, ``ended_at``, ``status``.

    Args:
        store_path: Path to the RunStore SQLite file.
        connection_id: Optional filter by logical connection identifier.
        status: Optional filter by run status
            (``"success"``, ``"failed"``, ``"partial"``).  ``None`` = all.
        limit: Maximum number of rows returned (newest first).

    Returns:
        List of run metadata dicts, ordered by ``started_at`` descending.

    Example::

        runs = list_runs("dqt_runs.db", status="success", limit=10)
    """
    return _store(store_path).load_runs(
        connection_id=connection_id,
        status=status,
        limit=limit,
    )


def get_run_summary(
    store_path: str | Path,
    run_id: str,
) -> dict[str, Any]:
    """Return a summary dict for a single run.

    The summary includes the run metadata plus aggregated counts and an
    overall completeness score computed from stored metrics.

    Args:
        store_path: Path to the RunStore SQLite file.
        run_id: Identifier of the run to summarise.

    Returns:
        Dict with keys: ``run_id``, ``connection_id``, ``started_at``,
        ``ended_at``, ``status``, ``metric_count``, ``issue_count``,
        ``overall_completeness`` (float 0–1, or ``None`` if no metrics).

    Example::

        summary = get_run_summary("dqt_runs.db", run_id="run-abc123")
        print(summary["overall_completeness"])
    """
    store = _store(store_path)
    runs = store.load_runs(limit=1000)
    run_meta = next((r for r in runs if r["run_id"] == run_id), None)
    if run_meta is None:
        return {"error": f"Run '{run_id}' not found."}

    metrics = store.load_metrics(run_id)
    issues = store.load_issues(run_id)

    completeness_scores = [
        m["score"] for m in metrics if m["dimension"] == "completeness"
    ]
    overall_completeness: Optional[float] = (
        sum(completeness_scores) / len(completeness_scores)
        if completeness_scores
        else None
    )

    return {
        **run_meta,
        "metric_count": len(metrics),
        "issue_count": len(issues),
        "overall_completeness": overall_completeness,
    }


def get_run_metrics(
    store_path: str | Path,
    run_id: str,
    table_name: Optional[str] = None,
    dimension: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Return metric rows for a run, optionally filtered.

    Args:
        store_path: Path to the RunStore SQLite file.
        run_id: Identifier of the run whose metrics to fetch.
        table_name: Optional filter to a specific table.
        dimension: Optional filter to a specific DQ dimension
            (e.g. ``"completeness"``).

    Returns:
        List of metric dicts with keys: ``run_id``, ``schema_name``,
        ``table_name``, ``column_name``, ``dimension``, ``score``,
        ``value``, ``metadata``.

    Example::

        completeness = get_run_metrics(
            "dqt_runs.db",
            run_id="run-abc123",
            dimension="completeness",
        )
    """
    return _store(store_path).load_metrics(
        run_id=run_id,
        table_name=table_name,
        dimension=dimension,
    )


def get_run_issues(
    store_path: str | Path,
    run_id: str,
    severity: Optional[str] = None,
    table_name: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Return issue rows for a run, optionally filtered.

    Args:
        store_path: Path to the RunStore SQLite file.
        run_id: Identifier of the run whose issues to fetch.
        severity: Optional filter
            (``"info"``, ``"warning"``, ``"error"``, ``"critical"``).
        table_name: Optional filter to a specific table.

    Returns:
        List of issue dicts with keys: ``issue_id``, ``run_id``,
        ``schema_name``, ``table_name``, ``column_name``, ``dimension``,
        ``severity``, ``message``, ``evidence``, ``rule_name``.

    Example::

        critical = get_run_issues(
            "dqt_runs.db",
            run_id="run-abc123",
            severity="critical",
        )
    """
    return _store(store_path).load_issues(
        run_id=run_id,
        severity=severity,
        table_name=table_name,
    )


def list_tables_for_run(
    store_path: str | Path,
    run_id: str,
) -> list[str]:
    """Return a sorted list of unique table names that have metrics for a run.

    Args:
        store_path: Path to the RunStore SQLite file.
        run_id: The pipeline run to inspect.

    Returns:
        Sorted list of table name strings.

    Example::

        tables = list_tables_for_run("dqt_runs.db", run_id="run-abc123")
    """
    metrics = _store(store_path).load_metrics(run_id)
    seen: set[str] = set()
    for m in metrics:
        if m["table_name"]:
            seen.add(m["table_name"])
    return sorted(seen)


__all__ = [
    "list_runs",
    "get_run_summary",
    "get_run_metrics",
    "get_run_issues",
    "list_tables_for_run",
]
