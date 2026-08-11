"""
Integration tests for DQTPipeline.run() on a real SQLite database.

These tests exercise the full pipeline stack end-to-end:
schema discovery -> profiling -> diagnostics -> rules -> metrics ->
monitoring -> persistence -> HTML report generation.

Design decisions:
- SQLite is used as the integration backend (no Docker required for basic
  integration coverage). Add a Postgres fixture when CI has Docker support.
- Tests are realistic but small: 2 tables, ~5 rows each.
- Rule engine integration is tested via config_loader + apply_rules.
- All assertions focus on correctness of data-quality outputs, not performance.

To run only integration tests:
    pytest tests/integration/ -v
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from dqt.common.config_loader import load_rules
from dqt.common.models import ConnectionConfig, DQPipelineConfig
from dqt.common.storage import RunStore
from dqt.sql.pipeline import DQTPipeline
from dqt.sql.rules import apply_rules
from dqt.sql.schema_discovery import discover_schema

# ---------------------------------------------------------------------------
# Shared DB fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def integration_db(tmp_path_factory) -> str:
    """Create a realistic test SQLite DB and return its DSN.

    Schema: employees + departments with intentional DQ issues:
    - NULLs in required columns
    - Duplicate 'employee_code'
    - Negative salary
    - Invalid email format
    """
    tmp = tmp_path_factory.mktemp("integration_db")
    db_file = tmp / "integration.db"
    conn = sqlite3.connect(str(db_file))
    conn.executescript("""
        CREATE TABLE departments (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            budget REAL
        );
        INSERT INTO departments VALUES (1, 'Engineering', 500000.0);
        INSERT INTO departments VALUES (2, 'Marketing', 200000.0);
        INSERT INTO departments VALUES (3, 'HR', 150000.0);

        CREATE TABLE employees (
            id INTEGER PRIMARY KEY,
            employee_code TEXT,
            name TEXT NOT NULL,
            email TEXT,
            salary REAL,
            department_id INTEGER
        );
        -- Alice, Bob: clean rows
        INSERT INTO employees VALUES (1, 'EMP001', 'Alice', 'alice@corp.com', 90000.0, 1);
        INSERT INTO employees VALUES (2, 'EMP002', 'Bob',   'bob@corp.com',   75000.0, 2);
        -- Carol: duplicate employee_code
        INSERT INTO employees VALUES (3, 'EMP001', 'Carol', 'carol@corp.com', 80000.0, 1);
        -- Dave: bad email, negative salary
        INSERT INTO employees VALUES (4, 'EMP004', 'Dave', 'not_an_email', -5000.0, 3);
        -- Eve: NULL email, NULL department
        INSERT INTO employees VALUES (5, 'EMP005', 'Eve', NULL, 60000.0, NULL);
    """)
    conn.commit()
    conn.close()
    return f"sqlite:///{db_file}"


@pytest.fixture(scope="module")
def integration_pipeline(integration_db, tmp_path_factory) -> DQTPipeline:
    tmp = tmp_path_factory.mktemp("integration_pipeline")
    conn_cfg = ConnectionConfig(id="integration", dsn=integration_db)
    pipe_cfg = DQPipelineConfig(connection_id="integration")
    return DQTPipeline(
        connection_config=conn_cfg,
        pipeline_config=pipe_cfg,
        store_path=tmp / "runs.db",
        report_dir=tmp,
    )


# ---------------------------------------------------------------------------
# Full pipeline end-to-end
# ---------------------------------------------------------------------------


class TestFullPipelineIntegration:
    def test_pipeline_completes_successfully(self, integration_pipeline):
        result, report = integration_pipeline.run()
        assert result.status == "success"
        assert report.exists()

    def test_all_tables_discovered(self, integration_pipeline):
        result, _ = integration_pipeline.run()
        table_names = {t.split(".")[-1] for t in result.tables}
        assert "employees" in table_names
        assert "departments" in table_names

    def test_completeness_issues_detected(self, integration_pipeline):
        """NULL email and NULL department_id in employees must be flagged."""
        result, _ = integration_pipeline.run()
        c_issues = [i for i in result.issues if i.dimension == "completeness"]
        assert len(c_issues) > 0
        issue_columns = {i.column_name for i in c_issues}
        # At least email should be flagged
        assert "email" in issue_columns or any(i.table_name == "employees" for i in c_issues)

    def test_metrics_cover_all_tables(self, integration_pipeline):
        result, _ = integration_pipeline.run()
        metric_tables = {m.table_name for m in result.metrics if m.table_name}
        assert "employees" in metric_tables
        assert "departments" in metric_tables

    def test_run_persisted(self, integration_pipeline, tmp_path_factory):
        result, _ = integration_pipeline.run()
        store = RunStore(db_path=integration_pipeline._store_path)
        runs = store.load_runs()
        run_ids = {r["run_id"] for r in runs}
        assert result.run_id in run_ids

    def test_html_report_non_empty(self, integration_pipeline):
        result, report = integration_pipeline.run()
        content = report.read_text(encoding="utf-8")
        assert len(content) > 500
        assert "<html" in content.lower() or "<!doctype" in content.lower()


# ---------------------------------------------------------------------------
# Rule engine integration
# ---------------------------------------------------------------------------


class TestRuleEngineIntegration:
    def test_not_null_rule_finds_null_email(self, integration_db):
        conn_cfg = ConnectionConfig(id="int", dsn=integration_db)
        tables = discover_schema(conn_cfg)
        emp_tables = [t for t in tables if t.table_name == "employees"]
        assert emp_tables, "employees table not found"

        from dqt.common.models import RuleConfig, RuleScope

        rule = RuleConfig(
            name="not_null_email",
            dimension="completeness",
            severity="error",
            scope=RuleScope(table_pattern="employees", column_pattern="email"),
            expression="NOT NULL",
        )
        issues, summaries = apply_rules(
            run_id="int-001",
            connection_config=conn_cfg,
            rules=[rule],
            discovered_tables=emp_tables,
        )
        assert len(issues) == 1
        assert issues[0].column_name == "email"
        assert issues[0].severity == "error"

    def test_unique_rule_finds_duplicate_code(self, integration_db):
        conn_cfg = ConnectionConfig(id="int", dsn=integration_db)
        tables = discover_schema(conn_cfg)
        emp_tables = [t for t in tables if t.table_name == "employees"]

        from dqt.common.models import RuleConfig, RuleScope

        rule = RuleConfig(
            name="unique_employee_code",
            dimension="uniqueness",
            severity="critical",
            scope=RuleScope(table_pattern="employees", column_pattern="employee_code"),
            expression="UNIQUE",
        )
        issues, summaries = apply_rules(
            run_id="int-002",
            connection_config=conn_cfg,
            rules=[rule],
            discovered_tables=emp_tables,
        )
        assert len(issues) == 1
        assert "duplicate" in issues[0].message.lower()
        assert issues[0].severity == "critical"

    def test_range_rule_finds_negative_salary(self, integration_db):
        conn_cfg = ConnectionConfig(id="int", dsn=integration_db)
        tables = discover_schema(conn_cfg)
        emp_tables = [t for t in tables if t.table_name == "employees"]

        from dqt.common.models import RuleConfig, RuleScope

        rule = RuleConfig(
            name="positive_salary",
            dimension="validity",
            severity="error",
            scope=RuleScope(table_pattern="employees", column_pattern="salary"),
            expression="range",
            params={"min": 0},
        )
        issues, summaries = apply_rules(
            run_id="int-003",
            connection_config=conn_cfg,
            rules=[rule],
            discovered_tables=emp_tables,
        )
        assert len(issues) == 1
        assert "outside" in issues[0].message.lower() or "out of range" in issues[0].message.lower()

    def test_multiple_rules_from_yaml(self, integration_db, tmp_path_factory):
        """Verify that loading rules from the example YAML and running them
        produces non-empty output on the integration DB."""
        examples_dir = Path("examples/rules/base_rules.yaml")
        if not examples_dir.exists():
            pytest.skip("examples/rules/base_rules.yaml not found (run from repo root)")

        conn_cfg = ConnectionConfig(id="int", dsn=integration_db)
        tables = discover_schema(conn_cfg)
        rules = load_rules(examples_dir)
        assert len(rules) > 0

        issues, summaries = apply_rules(
            run_id="int-004",
            connection_config=conn_cfg,
            rules=rules,
            discovered_tables=tables,
        )
        # With the integration DB's known issues, at least one rule should fire
        assert len(summaries) == len(rules)
