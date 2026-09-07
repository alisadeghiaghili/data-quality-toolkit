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
from typing import Any

from dqt.common.storage import RunStore


def _store(store_path: str | Path) -> RunStore:
    """Return a RunStore instance for the given path."""
    return RunStore(db_path=store_path)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def list_runs(
    store_path: str | Path,
    connection_id: str | None = None,
    status: str | None = None,
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

    completeness_scores = [m["score"] for m in metrics if m["dimension"] == "completeness"]
    overall_completeness: float | None = (
        sum(completeness_scores) / len(completeness_scores) if completeness_scores else None
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
    table_name: str | None = None,
    dimension: str | None = None,
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
    severity: str | None = None,
    table_name: str | None = None,
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


def get_run_rule_results(store_path: str | Path, run_id: str) -> list[dict[str, Any]]:
    """Return the rule summaries for one run.

    Args:
        store_path: Path to the RunStore SQLite file.
        run_id: The run to read.

    Returns:
        One plain dict per rule evaluated, in rule-name order.

    Example:
        results = get_run_rule_results("dqt_runs.db", run_id="run-001")
    """
    return _store(store_path).load_rule_results(run_id)


def get_rule_history(
    store_path: str | Path, rule_name: str, limit: int = 50
) -> list[dict[str, Any]]:
    """Return one rule's results across runs, newest first.

    Args:
        store_path: Path to the RunStore SQLite file.
        rule_name: The rule to follow.
        limit: Maximum entries returned.

    Returns:
        Plain dicts carrying the rule's counts and the run's timestamp.

    Example:
        history = get_rule_history("dqt_runs.db", rule_name="not-null-email")
    """
    return _store(store_path).load_rule_history(rule_name, limit=limit)


def get_column_details(store_path: str | Path, run_id: str) -> list[dict[str, Any]]:
    """Return one entry per profiled column, read back from a stored run.

    The HTML report builds the same view from a live ``PipelineResult``;
    the screens cannot, because they serve a run that finished last night.
    The statistics survive that gap because `F1` writes them into the
    completeness metric's metadata rather than only into the profile object.

    Args:
        store_path: Path to the RunStore SQLite file.
        run_id: The run to read.

    Returns:
        Dicts with ``schema_name``, ``table_name``, ``column_name``,
        ``semantic_type``, ``null_count``, ``distinct_count``, ``min_value``,
        ``max_value``, ``mean_value`` and ``score``. Sorted by table then
        column, so the screen is stable between refreshes.

    Example:
        columns = get_column_details("dqt_runs.db", run_id="run-001")
    """
    # The semantic type rides on the *validity* metric, not the completeness
    # one -- classification is what produces it, and validity is what
    # classification scores. Reading it off the completeness metric returned
    # "n/a" for every column even when classification had run, which is the
    # kind of wrong that looks like a disabled feature.
    semantic_types = {
        (metric.get("table_name"), metric.get("column_name")): (metric.get("metadata") or {}).get(
            "semantic_type"
        )
        for metric in get_run_metrics(store_path, run_id, dimension="validity")
    }

    rows: list[dict[str, Any]] = []
    for metric in get_run_metrics(store_path, run_id, dimension="completeness"):
        if not metric.get("column_name"):
            continue
        metadata = metric.get("metadata") or {}
        rows.append(
            {
                "schema_name": metric.get("schema_name"),
                "table_name": metric.get("table_name"),
                "column_name": metric.get("column_name"),
                "semantic_type": semantic_types.get(
                    (metric.get("table_name"), metric.get("column_name"))
                ),
                "null_count": metric.get("value"),
                "distinct_count": metadata.get("distinct_count"),
                "min_value": metadata.get("min_value"),
                "max_value": metadata.get("max_value"),
                "mean_value": metadata.get("mean_value"),
                "score": metric.get("score"),
            }
        )
    return sorted(rows, key=lambda row: (str(row["table_name"]), str(row["column_name"])))


def get_score_changes(store_path: str | Path, run_id: str) -> list[dict[str, Any]]:
    """Return the dimension scores that fell since the previous run.

    Reads the deltas `F8` writes onto each metric, so this asks the store a
    question rather than recomputing a comparison the pipeline already made.

    Only falls, and only where a previous observation exists. A run with no
    predecessor returns nothing rather than a list of zeroes -- the same
    distinction `F8` makes between no drift and zero drift, kept at the
    point it would otherwise be lost.

    Args:
        store_path: Path to the RunStore SQLite file.
        run_id: The run to read.

    Returns:
        Dicts with ``table_name``, ``column_name``, ``dimension``,
        ``previous_score``, ``score`` and ``delta``, worst fall first.

    Example:
        changes = get_score_changes("dqt_runs.db", run_id="run-001")
    """
    changes: list[dict[str, Any]] = []
    for metric in get_run_metrics(store_path, run_id):
        metadata = metric.get("metadata") or {}
        delta = metadata.get("delta")
        if not isinstance(delta, int | float) or delta >= 0 or not metric.get("dimension"):
            continue
        changes.append(
            {
                "table_name": metric.get("table_name"),
                "column_name": metric.get("column_name"),
                "dimension": metric.get("dimension"),
                "previous_score": metadata.get("previous_score"),
                "score": metric.get("score"),
                "delta": delta,
            }
        )
    return sorted(changes, key=lambda row: float(row["delta"]))


def get_issue_counts_by_severity(store_path: str | Path, run_id: str) -> dict[str, int]:
    """Return how many issues of each severity a run produced.

    Grouped in the database rather than by counting a loaded list: the size
    of that list is exactly how bad the data is, which is the wrong thing for
    a page's cost to depend on.

    Args:
        store_path: Path to the RunStore SQLite file.
        run_id: The run to count.

    Returns:
        Severity to count, absent where there are none.

    Example:
        counts = get_issue_counts_by_severity("dqt_runs.db", run_id="run-001")
    """
    return _store(store_path).count_issues_by_severity(run_id)


def get_issue_counts_by_dimension(store_path: str | Path, run_id: str) -> dict[str, int]:
    """Return how many issues of each dimension a run produced.

    Args:
        store_path: Path to the RunStore SQLite file.
        run_id: The run to count.

    Returns:
        Dimension to count, absent where there are none.

    Example:
        counts = get_issue_counts_by_dimension("dqt_runs.db", run_id="run-001")
    """
    return _store(store_path).count_issues_by_dimension(run_id)


def get_dimension_scores(store_path: str | Path, run_id: str) -> dict[str, float]:
    """Return a run's mean score per dimension.

    A dimension nothing measured is absent rather than zero. The screens rely
    on that distinction: absent renders as "not measured" and zero renders as
    a measured failure, and they are different claims.

    Args:
        store_path: Path to the RunStore SQLite file.
        run_id: The run to read.

    Returns:
        Dimension to mean score.

    Example:
        scores = get_dimension_scores("dqt_runs.db", run_id="run-001")
    """
    return _store(store_path).average_score_by_dimension(run_id)
