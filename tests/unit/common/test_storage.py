"""
Unit tests for dqt.common.storage.RunStore.

Tests use an in-memory SQLite database (:memory:) so they are fast,
isolated, and leave no files on disk.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from dqt.common.models import (
    DQIssue,
    DQMetric,
    PipelineResult,
)
from dqt.common.storage import RunStore

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def store(tmp_path: Path) -> RunStore:
    """Return an initialised RunStore backed by a temp SQLite file."""
    s = RunStore(tmp_path / "test.db")
    s.init_schema()
    return s


@pytest.fixture()
def simple_result() -> PipelineResult:
    """Return a minimal PipelineResult with one metric and one issue."""
    metric = DQMetric(
        run_id="run-001",
        dimension="completeness",
        score=0.95,
        table_name="customers",
        column_name="email",
        value=0.05,
        metadata={"threshold": 0.95},
    )
    issue = DQIssue(
        issue_id="iss-001",
        run_id="run-001",
        dimension="validity",
        severity="error",
        message="Invalid email addresses found.",
        evidence={"count": 42},
        table_name="customers",
        column_name="email",
        rule_name="email_format_check",
    )
    return PipelineResult(
        run_id="run-001",
        connection_id="pg-test",
        started_at=datetime(2026, 7, 3, 10, 0, 0, tzinfo=UTC),
        ended_at=datetime(2026, 7, 3, 10, 5, 0, tzinfo=UTC),
        status="success",
        metrics=[metric],
        issues=[issue],
    )


# ---------------------------------------------------------------------------
# init_schema
# ---------------------------------------------------------------------------


class TestInitSchema:
    def test_idempotent(self, store: RunStore) -> None:
        """Calling init_schema twice must not raise."""
        store.init_schema()  # second call

    def test_tables_exist(self, store: RunStore) -> None:
        """All three managed tables must exist after init_schema."""
        import sqlite3

        with sqlite3.connect(str(store._db_path)) as conn:
            tables = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        assert {"runs", "run_metrics", "run_issues"}.issubset(tables)


# ---------------------------------------------------------------------------
# save_run
# ---------------------------------------------------------------------------


class TestSaveRun:
    def test_saves_run_row(self, store: RunStore, simple_result: PipelineResult) -> None:
        store.save_run(simple_result)
        runs = store.load_runs()
        assert len(runs) == 1
        assert runs[0]["run_id"] == "run-001"
        assert runs[0]["connection_id"] == "pg-test"
        assert runs[0]["status"] == "success"

    def test_saves_metric_row(self, store: RunStore, simple_result: PipelineResult) -> None:
        store.save_run(simple_result)
        metrics = store.load_metrics("run-001")
        assert len(metrics) == 1
        m = metrics[0]
        assert m["dimension"] == "completeness"
        assert m["score"] == pytest.approx(0.95)
        assert m["table_name"] == "customers"
        assert m["metadata"] == {"threshold": 0.95}

    def test_saves_issue_row(self, store: RunStore, simple_result: PipelineResult) -> None:
        store.save_run(simple_result)
        issues = store.load_issues("run-001")
        assert len(issues) == 1
        i = issues[0]
        assert i["issue_id"] == "iss-001"
        assert i["severity"] == "error"
        assert i["evidence"] == {"count": 42}
        assert i["rule_name"] == "email_format_check"

    def test_idempotent_on_duplicate_run_id(
        self, store: RunStore, simple_result: PipelineResult
    ) -> None:
        """Saving the same run twice must not raise or duplicate rows."""
        store.save_run(simple_result)
        store.save_run(simple_result)  # second call
        assert len(store.load_runs()) == 1
        assert len(store.load_metrics("run-001")) == 1
        assert len(store.load_issues("run-001")) == 1

    def test_metadata_holding_a_decimal_and_a_date_does_not_crash_the_save(
        self, store: RunStore
    ) -> None:
        """`NEW-AF`: defence in depth for a metadata producer that forgot to sanitise.

        ``dqt.sql.profiling`` now turns a raw driver value into a JSON-safe
        one before it ever reaches a ``DQMetric``, but ``_metric_row`` also
        serializes with ``default=str`` so that a *future* producer which
        skips that step degrades to a readable string instead of raising
        ``TypeError`` inside the one transaction that persists a completed
        run. This metadata is built directly, bypassing the profiler
        entirely, to prove the store's own defence rather than the
        profiler's.

        Hand-derived: ``str(Decimal("12.50")) == "12.50"`` and
        ``str(date(2024, 1, 2)) == "2024-01-02"`` -- both are what
        ``json.dumps(..., default=str)`` calls on a value it does not
        otherwise know how to encode.
        """
        metric = DQMetric(
            run_id="run-002",
            dimension="completeness",
            score=1.0,
            table_name="orders",
            column_name="amount",
            metadata={"min_value": Decimal("12.50"), "max_value": date(2024, 1, 2)},
        )
        result = PipelineResult(
            run_id="run-002",
            connection_id="pg-test",
            started_at=datetime(2026, 7, 3, 10, 0, 0, tzinfo=UTC),
            ended_at=datetime(2026, 7, 3, 10, 5, 0, tzinfo=UTC),
            status="success",
            metrics=[metric],
            issues=[],
        )

        store.save_run(result)

        metrics = store.load_metrics("run-002")
        assert metrics[0]["metadata"] == {"min_value": "12.50", "max_value": "2024-01-02"}

    def test_no_dsn_stored(self, store: RunStore, simple_result: PipelineResult) -> None:
        """Verify DSN is never written into the runs table."""
        store.save_run(simple_result)
        runs = store.load_runs()
        assert "dsn" not in runs[0]
        for v in runs[0].values():
            assert "://" not in str(v), "DSN-like string found in runs row"


# ---------------------------------------------------------------------------
# load_runs
# ---------------------------------------------------------------------------


class TestLoadRuns:
    def _make_result(self, run_id: str, conn_id: str, status: str) -> PipelineResult:
        return PipelineResult(
            run_id=run_id,
            connection_id=conn_id,
            started_at=datetime(2026, 1, 1, tzinfo=UTC),
            ended_at=datetime(2026, 1, 1, 0, 1, tzinfo=UTC),
            status=status,  # type: ignore[arg-type]
        )

    def test_filter_by_connection_id(self, store: RunStore) -> None:
        store.save_run(self._make_result("r1", "pg-prod", "success"))
        store.save_run(self._make_result("r2", "pg-dev", "success"))
        runs = store.load_runs(connection_id="pg-prod")
        assert len(runs) == 1
        assert runs[0]["run_id"] == "r1"

    def test_filter_by_status(self, store: RunStore) -> None:
        store.save_run(self._make_result("r1", "pg-prod", "success"))
        store.save_run(self._make_result("r2", "pg-prod", "failed"))
        failed = store.load_runs(status="failed")
        assert len(failed) == 1
        assert failed[0]["run_id"] == "r2"

    def test_limit(self, store: RunStore) -> None:
        for i in range(5):
            store.save_run(self._make_result(f"r{i}", "pg-prod", "success"))
        runs = store.load_runs(limit=3)
        assert len(runs) == 3

    def test_empty_store_returns_empty_list(self, store: RunStore) -> None:
        assert store.load_runs() == []


# ---------------------------------------------------------------------------
# load_metrics
# ---------------------------------------------------------------------------


class TestLoadMetrics:
    def test_filter_by_table(self, store: RunStore, simple_result: PipelineResult) -> None:
        store.save_run(simple_result)
        metrics = store.load_metrics("run-001", table_name="customers")
        assert all(m["table_name"] == "customers" for m in metrics)

    def test_filter_by_dimension(self, store: RunStore, simple_result: PipelineResult) -> None:
        store.save_run(simple_result)
        metrics = store.load_metrics("run-001", dimension="completeness")
        assert all(m["dimension"] == "completeness" for m in metrics)

    def test_metadata_is_deserialized(self, store: RunStore, simple_result: PipelineResult) -> None:
        store.save_run(simple_result)
        m = store.load_metrics("run-001")[0]
        assert isinstance(m["metadata"], dict)

    def test_unknown_run_id_returns_empty(self, store: RunStore) -> None:
        assert store.load_metrics("nonexistent") == []


# ---------------------------------------------------------------------------
# load_issues
# ---------------------------------------------------------------------------


class TestLoadIssues:
    def test_filter_by_severity(self, store: RunStore, simple_result: PipelineResult) -> None:
        store.save_run(simple_result)
        errors = store.load_issues("run-001", severity="error")
        assert len(errors) == 1
        assert errors[0]["severity"] == "error"

    def test_filter_by_table(self, store: RunStore, simple_result: PipelineResult) -> None:
        store.save_run(simple_result)
        issues = store.load_issues("run-001", table_name="customers")
        assert len(issues) == 1

    def test_evidence_is_deserialized(self, store: RunStore, simple_result: PipelineResult) -> None:
        store.save_run(simple_result)
        i = store.load_issues("run-001")[0]
        assert isinstance(i["evidence"], dict)
        assert i["evidence"]["count"] == 42

    def test_unknown_run_id_returns_empty(self, store: RunStore) -> None:
        assert store.load_issues("nonexistent") == []
