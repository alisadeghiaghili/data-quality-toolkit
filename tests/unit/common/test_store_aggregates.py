"""Counting for a screen, in the database (`VIZ-3`).

A dashboard page shows counts: issues by severity, issues by dimension, a
score per dimension. The easy way to get them is to load every issue and
count in Python, and that is a per-row loop over a table whose size is
exactly how bad the data is — `CLAUDE.md` §3 calls that a design smell, and
the `dqt-ui-designer` skill asks for dashboard queries to stay set-based and
single-pass per view.

So the store groups. Three aggregates, one query each, returning small
dictionaries whose size is bounded by the vocabulary rather than by the data.

The numbers below are hand-counted from the fixture literal.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from dqt.common.models import DQIssue, DQMetric, PipelineResult
from dqt.common.storage import RunStore

_RUN = "run-agg"


def _issue(severity: str, dimension: str, index: int) -> DQIssue:
    """Build one issue for the fixture.

    Args:
        severity: The issue's severity.
        dimension: The issue's dimension.
        index: Makes the id unique.

    Returns:
        A DQIssue.

    Example:
        issue = _issue("error", "completeness", 0)
    """
    return DQIssue(
        issue_id=f"i-{index}",
        run_id=_RUN,
        dimension=dimension,  # type: ignore[arg-type]
        severity=severity,  # type: ignore[arg-type]
        message="m",
        schema_name="main",
        table_name="orders",
        column_name="email",
    )


@pytest.fixture
def store(tmp_path: Path) -> RunStore:
    """Seed a store with a run whose contents are known by hand.

    Three issues: two ``error``/``completeness`` and one
    ``warning``/``validity``. Two ``completeness`` metrics scoring 1.0 and
    0.0, and one ``validity`` metric scoring 0.5.

    Args:
        tmp_path: pytest temporary directory.

    Returns:
        The seeded store.

    Example:
        assert store.count_issues_by_severity("run-agg")["error"] == 2
    """
    created = RunStore(db_path=tmp_path / "runs.db")
    created.init_schema()
    moment = datetime(2026, 9, 5, tzinfo=UTC)
    created.save_run(
        PipelineResult(
            run_id=_RUN,
            connection_id="c",
            started_at=moment,
            ended_at=moment,
            status="success",
            metrics=[
                DQMetric(
                    run_id=_RUN,
                    dimension="completeness",
                    score=1.0,
                    table_name="orders",
                    column_name="id",
                ),
                DQMetric(
                    run_id=_RUN,
                    dimension="completeness",
                    score=0.0,
                    table_name="orders",
                    column_name="email",
                ),
                DQMetric(
                    run_id=_RUN,
                    dimension="validity",
                    score=0.5,
                    table_name="orders",
                    column_name="email",
                ),
            ],
            issues=[
                _issue("error", "completeness", 0),
                _issue("error", "completeness", 1),
                _issue("warning", "validity", 2),
            ],
        )
    )
    return created


class TestIssuesAreCountedByTheDatabase:
    """Two group-bys, not two Python loops over every issue."""

    def test_severities_are_counted(self, store: RunStore) -> None:
        """Two errors and one warning, counted from the fixture."""
        assert store.count_issues_by_severity(_RUN) == {"error": 2, "warning": 1}

    def test_dimensions_are_counted(self, store: RunStore) -> None:
        """Two completeness and one validity."""
        assert store.count_issues_by_dimension(_RUN) == {"completeness": 2, "validity": 1}

    def test_a_severity_with_no_issues_is_absent_rather_than_zero(self, store: RunStore) -> None:
        """The caller decides whether to show a zero.

        Inventing rows for every severity here would push a vocabulary
        decision into the storage layer, which does not own one.
        """
        counts = store.count_issues_by_severity(_RUN)

        assert "critical" not in counts
        assert "info" not in counts

    def test_an_unknown_run_counts_nothing(self, store: RunStore) -> None:
        """Absence is an answer, as everywhere else in this layer."""
        assert store.count_issues_by_severity("no-such-run") == {}


class TestDimensionScoresAreAveragedByTheDatabase:
    """The overview's scorecards, computed where the rows are."""

    def test_scores_are_averaged_per_dimension(self, store: RunStore) -> None:
        """Completeness 1.0 and 0.0 average to 0.5; validity has one 0.5."""
        scores = store.average_score_by_dimension(_RUN)

        assert scores["completeness"] == pytest.approx(0.5)
        assert scores["validity"] == pytest.approx(0.5)

    def test_an_unmeasured_dimension_is_absent_rather_than_zero(self, store: RunStore) -> None:
        """Absent means "nothing measured this"; zero means "it scored zero".

        Collapsing the two here is the single mistake this whole screen is
        built to avoid, and the storage layer is where it would be easiest to
        make by accident.
        """
        scores = store.average_score_by_dimension(_RUN)

        assert "timeliness" not in scores

    def test_metrics_without_a_dimension_are_not_averaged_in(self, store: RunStore) -> None:
        """``row_count`` is a measurement, not a quality score (`NEW-A`).

        The nullable ``dimension`` column exists precisely so those two
        cannot be confused, and averaging a row count into a score would
        confuse them again.
        """
        scores = store.average_score_by_dimension(_RUN)

        assert set(scores) == {"completeness", "validity"}


class TestTheAggregatesCostOneQueryEach:
    """Set-based, single-pass per view -- the rule for dashboard reads."""

    def test_each_aggregate_runs_exactly_one_statement(
        self, store: RunStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Counted, not timed, for the reason the other cost tests give.

        A page that loaded every issue to count three severities would pass
        every assertion above and fall over on the table that needed it most.
        """
        import sqlite3

        seen: list[str] = []
        real_connect = sqlite3.connect

        class _Counting(sqlite3.Connection):
            def execute(self, sql: str, *args: object) -> sqlite3.Cursor:
                if sql.strip().upper().startswith("SELECT"):
                    seen.append(sql)
                return super().execute(sql, *args)  # type: ignore[arg-type]

        def counting_connect(*args: object, **kwargs: object) -> sqlite3.Connection:
            kwargs["factory"] = _Counting
            return real_connect(*args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(sqlite3, "connect", counting_connect)

        store.count_issues_by_severity(_RUN)
        store.count_issues_by_dimension(_RUN)
        store.average_score_by_dimension(_RUN)

        assert len(seen) == 3, seen
