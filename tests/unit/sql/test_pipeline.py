"""
Unit tests for dqt.sql.pipeline.DQTPipeline.

All tests use a SQLite in-memory-style file DB (tmp_path) to avoid
external dependencies. Tests cover the full pipeline.run() flow,
stage isolation, and RunStore persistence.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dqt.common.models import ConnectionConfig, DQPipelineConfig
from dqt.common.storage import RunStore
from dqt.sql.pipeline import DQTPipeline

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def small_db(make_sqlite_db) -> str:
    """Create a small SQLite DB with two tables and return its file DSN."""
    db_file = make_sqlite_db(
        "test_pipeline.db",
        """
        CREATE TABLE customers (
            id INTEGER PRIMARY KEY,
            email TEXT,
            name TEXT NOT NULL
        );
        INSERT INTO customers VALUES (1, 'alice@example.com', 'Alice');
        INSERT INTO customers VALUES (2, NULL, 'Bob');  -- NULL email
        INSERT INTO customers VALUES (3, 'carol@example.com', 'Carol');

        CREATE TABLE orders (
            id INTEGER PRIMARY KEY,
            customer_id INTEGER NOT NULL,
            amount REAL
        );
        INSERT INTO orders VALUES (1, 1, 99.9);
        INSERT INTO orders VALUES (2, 2, -5.0);
        INSERT INTO orders VALUES (3, 3, 200.0);
        """,
    )
    return f"sqlite:///{db_file}"


@pytest.fixture
def pipeline(small_db: str, tmp_path: Path) -> DQTPipeline:
    """Return a configured DQTPipeline against the small test DB."""
    conn_cfg = ConnectionConfig(id="test-sqlite", dsn=small_db)
    pipe_cfg = DQPipelineConfig(connection_id="test-sqlite")
    return DQTPipeline(
        connection_config=conn_cfg,
        pipeline_config=pipe_cfg,
        store_path=tmp_path / "runs.db",
        report_dir=tmp_path,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDQTPipelineRun:
    def test_run_returns_result_and_report(self, pipeline, tmp_path):
        result, report_path = pipeline.run()
        assert result.status == "success"
        assert report_path.exists()
        assert report_path.suffix == ".html"

    def test_run_id_is_unique(self, pipeline, tmp_path):
        r1, _ = pipeline.run()
        r2, _ = pipeline.run()
        assert r1.run_id != r2.run_id

    def test_tables_discovered(self, pipeline):
        result, _ = pipeline.run()
        table_names = {t.split(".")[-1] for t in result.tables}
        assert "customers" in table_names
        assert "orders" in table_names

    def test_metrics_populated(self, pipeline):
        result, _ = pipeline.run()
        assert len(result.metrics) > 0
        dimensions = {m.dimension for m in result.metrics}
        assert "completeness" in dimensions

    def test_issues_detected(self, pipeline):
        """Completeness diagnostics should flag the NULL email in customers."""
        result, _ = pipeline.run()
        # NULL email in customers should produce at least one completeness issue
        completeness_issues = [i for i in result.issues if i.dimension == "completeness"]
        assert len(completeness_issues) > 0

    def test_run_persisted_to_store(self, pipeline, tmp_path):
        result, _ = pipeline.run()
        store = RunStore(db_path=tmp_path / "runs.db")
        runs = store.load_runs()
        assert any(r["run_id"] == result.run_id for r in runs)

    def test_metrics_persisted(self, pipeline, tmp_path):
        result, _ = pipeline.run()
        store = RunStore(db_path=tmp_path / "runs.db")
        metrics = store.load_metrics(result.run_id)
        assert len(metrics) == len(result.metrics)

    def test_schema_filter_excludes_tables(self, small_db, tmp_path):
        conn_cfg = ConnectionConfig(id="test", dsn=small_db)
        pipe_cfg = DQPipelineConfig(
            connection_id="test",
            include_tables=["customers"],
        )
        pipeline = DQTPipeline(
            connection_config=conn_cfg,
            pipeline_config=pipe_cfg,
            store_path=tmp_path / "filtered_runs.db",
            report_dir=tmp_path,
        )
        result, _ = pipeline.run()
        table_names = {t.split(".")[-1] for t in result.tables}
        assert "customers" in table_names
        assert "orders" not in table_names

    def test_report_contains_run_id(self, pipeline, tmp_path):
        result, report_path = pipeline.run()
        html = report_path.read_text(encoding="utf-8")
        assert result.run_id in html


class TestDQTPipelineStages:
    def test_discover_schema_returns_tables(self, pipeline):
        tables = pipeline.discover_schema()
        names = [t.table_name for t in tables]
        assert "customers" in names
        assert "orders" in names

    def test_profile_data_returns_profiles(self, pipeline):
        tables = pipeline.discover_schema()
        profiles = pipeline.profile_data(tables)
        assert len(profiles) > 0
        assert all(hasattr(p, "table_name") for p in profiles)

    def test_run_diagnostics_returns_issues_list(self, pipeline):
        tables = pipeline.discover_schema()
        profiles = pipeline.profile_data(tables)
        issues = pipeline.run_diagnostics(profiles, run_id="unit-test")
        assert isinstance(issues, list)


# ---------------------------------------------------------------------------
# NEW-B: run() can report failure
# ---------------------------------------------------------------------------


class TestRunReportsFailure:
    """`run()` hardcoded ``status = "success"`` and wrapped no stage.

    Verified against the unfixed code before writing these: pointing the
    pipeline at an unopenable DSN raises ``sqlite3.OperationalError`` straight
    out of ``run()``. Nothing is persisted, so ``runs.status`` could only ever
    hold ``"success"`` -- the value is not a report, it is a constant.

    `ENGINEERING-STANDARDS.md` §1.6 calls returning a non-failure on failure a
    silent-failure defect. This is the aggravated form: it returns a
    *positive* signal, or nothing at all.

    This has to land before `DQT-06`. An exit code derived from a status that
    is always ``"success"`` is not a contract.
    """

    def test_discovery_failure_is_reported_not_raised(self, tmp_path: Path) -> None:
        """An unopenable database yields ``failed``, not a traceback.

        A caller scripting DQT needs the run to come back so it can read the
        status. An exception escaping ``run()`` forces every caller to
        reimplement the same try/except and invent its own vocabulary for what
        went wrong.
        """
        conn_cfg = ConnectionConfig(id="x", dsn=f"sqlite:///{tmp_path}/missing/nope.db")
        pipeline = DQTPipeline(
            conn_cfg,
            DQPipelineConfig(connection_id="x"),
            store_path=tmp_path / "runs.db",
            report_dir=tmp_path,
        )

        result, _ = pipeline.run()

        assert result.status == "failed"
        assert any("discover_schema" in error.stage for error in result.stage_errors)

    def test_a_failed_run_is_still_persisted(self, tmp_path: Path) -> None:
        """The failure reaches the store, which is the point of recording it.

        Today the exception escapes before persistence, so a failed run leaves
        no trace at all -- monitoring cannot see it, and a trend built on
        ``runs`` silently omits every run that broke.
        """
        store_path = tmp_path / "runs.db"
        conn_cfg = ConnectionConfig(id="x", dsn=f"sqlite:///{tmp_path}/missing/nope.db")
        pipeline = DQTPipeline(
            conn_cfg,
            DQPipelineConfig(connection_id="x"),
            store_path=store_path,
            report_dir=tmp_path,
        )

        result, _ = pipeline.run()

        runs = RunStore(db_path=store_path).load_runs()
        assert [r["status"] for r in runs] == ["failed"]
        assert runs[0]["run_id"] == result.run_id

    def test_a_missing_rule_file_downgrades_to_partial(
        self, tmp_path: Path, make_sqlite_db
    ) -> None:
        """A rule file that is not there makes the run ``partial``, not ``success``.

        Settled 2026-08-19: not ``failed``, because the checks that could run
        did run; not silent, because a run that skipped half its rules and
        reported success is exactly the false clean bill of health `NEW-H`
        was about. Today ``apply_rules`` suppresses ``FileNotFoundError``
        per file and says nothing.
        """
        db_file = make_sqlite_db("d.db", "CREATE TABLE t (id INTEGER); INSERT INTO t VALUES (1);")
        conn_cfg = ConnectionConfig(id="x", dsn=f"sqlite:///{db_file}")
        pipeline = DQTPipeline(
            conn_cfg,
            DQPipelineConfig(connection_id="x", rule_files=[str(tmp_path / "not-there.yaml")]),
            store_path=tmp_path / "runs.db",
            report_dir=tmp_path,
        )

        result, _ = pipeline.run()

        assert result.status == "partial"
        assert any("not-there.yaml" in error.message for error in result.stage_errors)

    def test_a_clean_run_is_still_success(self, tmp_path: Path, make_sqlite_db) -> None:
        """The happy path is unchanged.

        Error capture that also changed the meaning of a good run would be a
        worse defect than the one it fixes.
        """
        db_file = make_sqlite_db("d.db", "CREATE TABLE t (id INTEGER); INSERT INTO t VALUES (1);")
        conn_cfg = ConnectionConfig(id="x", dsn=f"sqlite:///{db_file}")
        pipeline = DQTPipeline(
            conn_cfg,
            DQPipelineConfig(connection_id="x"),
            store_path=tmp_path / "runs.db",
            report_dir=tmp_path,
        )

        result, _ = pipeline.run()

        assert result.status == "success"
        assert result.stage_errors == []
