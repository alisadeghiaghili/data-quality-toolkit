"""Grounded unit tests for ``dqt.ui.api`` (NEW-D).

The whole ``dqt.ui`` package had zero tests. `api.py` is the read-only
data-access layer every UI consumer goes through, so an error here is
invisible until it reaches a screen.

Every expectation below is derived by hand from the literal fixture in
``_seed``: four metrics, three of them ``completeness`` with scores 1.0, 0.5
and 0.0, and two issues. Nothing is obtained by calling the code and
asserting it equals itself.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from dqt.common.models import DQIssue, DQMetric, PipelineResult
from dqt.common.storage import RunStore
from dqt.ui.api import (
    get_run_issues,
    get_run_metrics,
    get_run_summary,
    list_runs,
    list_tables_for_run,
)

RUN_ID = "run-001"


def _metric(dimension: str, score: float, table: str, column: str | None = None) -> DQMetric:
    """Build one metric for the fixture.

    Args:
        dimension: Metric dimension, e.g. ``"completeness"``.
        score: Normalised score in [0, 1].
        table: Table the metric belongs to.
        column: Column the metric belongs to, or None for table-level.

    Returns:
        A DQMetric ready to be saved to a RunStore.

    Example:
        metric = _metric("completeness", 1.0, "orders", "id")
    """
    return DQMetric(
        run_id=RUN_ID,
        dimension=dimension,
        score=score,
        schema_name="main",
        table_name=table,
        column_name=column,
        value=score,
        metadata={},
    )


def _issue(severity: str, table: str, column: str) -> DQIssue:
    """Build one issue for the fixture.

    Args:
        severity: One of ``"info"``, ``"warning"``, ``"error"``, ``"critical"``.
        table: Table the issue belongs to.
        column: Column the issue belongs to.

    Returns:
        A DQIssue ready to be saved to a RunStore.

    Example:
        issue = _issue("error", "orders", "email")
    """
    return DQIssue(
        issue_id=f"{RUN_ID}:{table}:{column}",
        run_id=RUN_ID,
        dimension="completeness",
        severity=severity,  # type: ignore[arg-type]
        message=f"Column '{column}' contains NULL values.",
        evidence={"null_count": 1, "row_count": 2},
        schema_name="main",
        table_name=table,
        column_name=column,
        rule_name=None,
    )


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    """Seed a RunStore with one run whose contents are known by hand.

    The fixture holds four metrics -- three ``completeness`` with scores
    1.0, 0.5 and 0.0, plus one ``row_count`` -- and two issues, spread over
    tables ``orders`` and ``customers``.

    Args:
        tmp_path: pytest temporary directory.

    Returns:
        Path to the seeded SQLite store.

    Example:
        runs = list_runs(store_path)
    """
    db = tmp_path / "runs.db"
    store = RunStore(db_path=db)
    store.init_schema()
    store.save_run(
        PipelineResult(
            run_id=RUN_ID,
            connection_id="conn-a",
            started_at=datetime(2026, 9, 4, 10, 0, tzinfo=UTC),
            ended_at=datetime(2026, 9, 4, 10, 1, tzinfo=UTC),
            status="success",
            metrics=[
                _metric("completeness", 1.0, "orders", "id"),
                _metric("completeness", 0.5, "orders", "email"),
                _metric("completeness", 0.0, "customers", "phone"),
                _metric("row_count", 1.0, "orders"),
            ],
            issues=[
                _issue("warning", "orders", "email"),
                _issue("error", "customers", "phone"),
            ],
        )
    )
    return db


def test_list_runs_returns_the_saved_run(store_path: Path) -> None:
    """One run was saved, so exactly one run comes back, with its metadata."""
    runs = list_runs(store_path)

    assert len(runs) == 1
    assert runs[0]["run_id"] == RUN_ID
    assert runs[0]["connection_id"] == "conn-a"
    assert runs[0]["status"] == "success"


def test_list_runs_filters_do_not_match_everything(store_path: Path) -> None:
    """Filters must actually filter, not be accepted and ignored.

    A filter that is silently dropped is the exact defect `NEW-H` was: the
    CLI accepted ``rule_files`` and never forwarded it, so runs reported
    success having checked nothing.
    """
    assert list_runs(store_path, connection_id="conn-a") != []
    assert list_runs(store_path, connection_id="no-such-conn") == []
    assert list_runs(store_path, status="success") != []
    assert list_runs(store_path, status="failed") == []


def test_run_summary_averages_only_completeness_metrics(store_path: Path) -> None:
    """Overall completeness is the mean of completeness metrics alone.

    Ground truth: the fixture's completeness scores are 1.0, 0.5 and 0.0, so
    the mean is 1.5 / 3 = 0.5. The fourth metric has dimension ``row_count``
    and a score of 1.0; if it were wrongly included the mean would be
    2.5 / 4 = 0.625. The two values differ, so this fixture actually
    discriminates between the correct and the naive implementation.
    """
    summary = get_run_summary(store_path, run_id=RUN_ID)

    assert summary["overall_completeness"] == 0.5
    assert summary["metric_count"] == 4
    assert summary["issue_count"] == 2
    assert summary["connection_id"] == "conn-a"


def test_run_summary_reports_a_missing_run_rather_than_raising(store_path: Path) -> None:
    """An unknown run yields an error dict, not an exception or empty summary."""
    summary = get_run_summary(store_path, run_id="does-not-exist")

    assert "error" in summary
    assert "does-not-exist" in summary["error"]
    assert "overall_completeness" not in summary


def test_metrics_and_issues_can_be_filtered(store_path: Path) -> None:
    """Dimension, table and severity filters select the hand-known subsets.

    Ground truth from the fixture: three completeness metrics, one row_count;
    three metrics on ``orders``; one ``error`` issue, on ``customers``.
    """
    assert len(get_run_metrics(store_path, run_id=RUN_ID)) == 4
    assert len(get_run_metrics(store_path, run_id=RUN_ID, dimension="completeness")) == 3
    assert len(get_run_metrics(store_path, run_id=RUN_ID, table_name="orders")) == 3

    assert len(get_run_issues(store_path, run_id=RUN_ID)) == 2
    errors = get_run_issues(store_path, run_id=RUN_ID, severity="error")
    assert [i["table_name"] for i in errors] == ["customers"]


def test_list_tables_is_sorted_and_deduplicated(store_path: Path) -> None:
    """Table names come back sorted and unique.

    Ground truth: metrics reference ``orders`` three times and ``customers``
    once, so the result is exactly ``["customers", "orders"]`` -- sorted, and
    with ``orders`` appearing once rather than three times.
    """
    assert list_tables_for_run(store_path, run_id=RUN_ID) == ["customers", "orders"]
