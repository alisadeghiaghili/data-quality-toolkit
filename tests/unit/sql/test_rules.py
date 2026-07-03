"""
Unit tests for dqt.sql.rules.

All tests use a SQLite in-memory database.
Tests cover: NOT NULL, UNIQUE, range, unknown expression, empty inputs,
scope matching, and the apply_rules() public API.
"""

from __future__ import annotations

import sqlite3

import pytest

from dqt.common.models import ConnectionConfig, RuleConfig, RuleScope
from dqt.sql.rules import (
    _detect_dialect,
    _eval_not_null,
    _eval_range,
    _eval_unique,
    _matches_scope,
    apply_rules,
)
from dqt.sql.schema_discovery import DiscoveredColumn, DiscoveredTable


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sqlite_conn():
    """In-memory SQLite connection with a small test dataset."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE users (
            id INTEGER,
            email TEXT,
            age INTEGER
        );
        INSERT INTO users VALUES (1, 'alice@example.com', 25);
        INSERT INTO users VALUES (2, 'bob@example.com', 30);
        INSERT INTO users VALUES (3, NULL, 17);        -- NULL email, minor age
        INSERT INTO users VALUES (4, 'alice@example.com', -1); -- duplicate email, negative age
        INSERT INTO users VALUES (NULL, 'carol@example.com', 22); -- NULL id
    """)
    return conn


@pytest.fixture
def discovered_users_table():
    """Minimal DiscoveredTable for the 'users' table."""
    return DiscoveredTable(
        schema_name=None,
        table_name="users",
        columns=[
            DiscoveredColumn(schema_name=None, table_name="users", column_name="id", data_type="INTEGER", is_nullable=True, ordinal_position=1),
            DiscoveredColumn(schema_name=None, table_name="users", column_name="email", data_type="TEXT", is_nullable=True, ordinal_position=2),
            DiscoveredColumn(schema_name=None, table_name="users", column_name="age", data_type="INTEGER", is_nullable=True, ordinal_position=3),
        ],
    )


@pytest.fixture
def sqlite_dsn_file(tmp_path):
    """SQLite file-based DSN with a populated test DB."""
    db_file = tmp_path / "test_rules.db"
    conn = sqlite3.connect(str(db_file))
    conn.executescript("""
        CREATE TABLE orders (
            id INTEGER,
            amount REAL,
            customer_id INTEGER
        );
        INSERT INTO orders VALUES (1, 100.0, 10);
        INSERT INTO orders VALUES (2, -5.0, 20);    -- negative amount
        INSERT INTO orders VALUES (3, 200.0, NULL); -- NULL customer_id
        INSERT INTO orders VALUES (1, 50.0, 30);    -- duplicate id
    """)
    conn.commit()
    conn.close()
    return f"sqlite:///{db_file}"


# ---------------------------------------------------------------------------
# _detect_dialect
# ---------------------------------------------------------------------------

class TestDetectDialect:
    def test_sqlite(self):
        assert _detect_dialect("sqlite:///dev.db") == "sqlite"

    def test_postgresql(self):
        assert _detect_dialect("postgresql://u:p@h/db") == "postgresql"

    def test_postgres_alias(self):
        assert _detect_dialect("postgres://u:p@h/db") == "postgresql"

    def test_unsupported_raises(self):
        with pytest.raises(ValueError, match="Cannot detect dialect"):
            _detect_dialect("mysql://u:p@h/db")


# ---------------------------------------------------------------------------
# Low-level SQL evaluators
# ---------------------------------------------------------------------------

class TestEvalNotNull:
    def test_detects_nulls(self, sqlite_conn):
        cursor = sqlite_conn.cursor()
        total, null_count = _eval_not_null(cursor, None, "users", "email")
        assert total == 5
        assert null_count == 1

    def test_no_nulls(self, sqlite_conn):
        cursor = sqlite_conn.cursor()
        # 'age' column has no NULLs in fixture
        total, null_count = _eval_not_null(cursor, None, "users", "age")
        assert total == 5
        assert null_count == 0


class TestEvalUnique:
    def test_detects_duplicates(self, sqlite_conn):
        cursor = sqlite_conn.cursor()
        total, dup_extra = _eval_unique(cursor, None, "users", "email")
        # alice@example.com appears twice -> 1 extra row
        assert dup_extra == 1

    def test_no_duplicates_when_unique(self, sqlite_conn):
        cursor = sqlite_conn.cursor()
        # age values: 25, 30, 17, -1, 22 -> all unique
        _, dup_extra = _eval_unique(cursor, None, "users", "age")
        assert dup_extra == 0


class TestEvalRange:
    def test_detects_below_min(self, sqlite_conn):
        cursor = sqlite_conn.cursor()
        total, out = _eval_range(cursor, None, "users", "age", min_val=0, max_val=None)
        # age = -1 is out of range
        assert out == 1

    def test_detects_above_max(self, sqlite_conn):
        cursor = sqlite_conn.cursor()
        total, out = _eval_range(cursor, None, "users", "age", min_val=None, max_val=100)
        assert out == 0  # all ages <= 100

    def test_both_bounds(self, sqlite_conn):
        cursor = sqlite_conn.cursor()
        total, out = _eval_range(cursor, None, "users", "age", min_val=18, max_val=100)
        # age 17 and -1 are out of range -> 2
        assert out == 2

    def test_no_bounds_raises(self, sqlite_conn):
        cursor = sqlite_conn.cursor()
        with pytest.raises(ValueError, match="range rule requires"):
            _eval_range(cursor, None, "users", "age", None, None)


# ---------------------------------------------------------------------------
# _matches_scope
# ---------------------------------------------------------------------------

class TestMatchesScope:
    def _table(self, schema=None, name="users"):
        return DiscoveredTable(schema_name=schema, table_name=name, columns=[])

    def _rule(self, table_pattern=None, column_pattern=None, schema_pattern=None):
        return RuleConfig(
            name="r", dimension="completeness", severity="error",
            scope=RuleScope(
                table_pattern=table_pattern,
                column_pattern=column_pattern,
                schema_pattern=schema_pattern,
            ),
            expression="NOT NULL",
        )

    def test_no_scope_matches_all(self):
        rule = self._rule()
        assert _matches_scope(self._table(), "email", rule) is True

    def test_table_pattern_match(self):
        rule = self._rule(table_pattern="user*")
        assert _matches_scope(self._table(name="users"), "email", rule) is True

    def test_table_pattern_no_match(self):
        rule = self._rule(table_pattern="order*")
        assert _matches_scope(self._table(name="users"), "email", rule) is False

    def test_column_pattern_match(self):
        rule = self._rule(column_pattern="*email*")
        assert _matches_scope(self._table(), "user_email", rule) is True

    def test_column_pattern_no_match(self):
        rule = self._rule(column_pattern="email")
        assert _matches_scope(self._table(), "phone", rule) is False

    def test_schema_pattern_match(self):
        rule = self._rule(schema_pattern="pub*")
        assert _matches_scope(self._table(schema="public"), "id", rule) is True

    def test_schema_pattern_no_match(self):
        rule = self._rule(schema_pattern="staging")
        assert _matches_scope(self._table(schema="public"), "id", rule) is False


# ---------------------------------------------------------------------------
# apply_rules() public API
# ---------------------------------------------------------------------------

class TestApplyRules:
    def _conn_cfg(self, dsn):
        return ConnectionConfig(id="test", dsn=dsn)

    def _rule(self, name, expr, col_pattern, dimension="completeness", severity="error", params=None):
        return RuleConfig(
            name=name,
            dimension=dimension,
            severity=severity,
            scope=RuleScope(column_pattern=col_pattern),
            expression=expr,
            params=params or {},
        )

    def test_empty_rules_returns_empty(self, sqlite_dsn_file, discovered_users_table):
        issues, summaries = apply_rules(
            run_id="run-test",
            connection_config=self._conn_cfg(sqlite_dsn_file),
            rules=[],
            discovered_tables=[discovered_users_table],
        )
        assert issues == []
        assert summaries == []

    def test_no_tables_returns_empty(self, sqlite_dsn_file):
        rule = self._rule("r", "NOT NULL", "email")
        issues, summaries = apply_rules(
            run_id="run-test",
            connection_config=self._conn_cfg(sqlite_dsn_file),
            rules=[rule],
            discovered_tables=[],
        )
        assert issues == []

    def test_not_null_detects_violation(self, sqlite_dsn_file):
        db_file = sqlite_dsn_file.replace("sqlite:///", "")
        conn = sqlite3.connect(db_file)
        tables = [
            DiscoveredTable(
                schema_name=None,
                table_name="orders",
                columns=[
                    DiscoveredColumn(schema_name=None, table_name="orders", column_name="customer_id", data_type="INTEGER", is_nullable=True, ordinal_position=3),
                ],
            )
        ]
        conn.close()
        rule = self._rule("not_null_customer", "NOT NULL", "customer_id", dimension="completeness", severity="critical")
        issues, summaries = apply_rules(
            run_id="run-001",
            connection_config=self._conn_cfg(sqlite_dsn_file),
            rules=[rule],
            discovered_tables=tables,
        )
        assert len(issues) == 1
        assert issues[0].severity == "critical"
        assert "NULL" in issues[0].message
        assert summaries[0].targets_failed == 1

    def test_unique_detects_duplicate(self, sqlite_dsn_file):
        tables = [
            DiscoveredTable(
                schema_name=None,
                table_name="orders",
                columns=[
                    DiscoveredColumn(schema_name=None, table_name="orders", column_name="id", data_type="INTEGER", is_nullable=True, ordinal_position=1),
                ],
            )
        ]
        rule = self._rule("unique_order_id", "UNIQUE", "id", dimension="uniqueness", severity="error")
        issues, summaries = apply_rules(
            run_id="run-002",
            connection_config=self._conn_cfg(sqlite_dsn_file),
            rules=[rule],
            discovered_tables=tables,
        )
        assert len(issues) == 1
        assert "duplicate" in issues[0].message.lower()

    def test_range_detects_negative(self, sqlite_dsn_file):
        tables = [
            DiscoveredTable(
                schema_name=None,
                table_name="orders",
                columns=[
                    DiscoveredColumn(schema_name=None, table_name="orders", column_name="amount", data_type="REAL", is_nullable=True, ordinal_position=2),
                ],
            )
        ]
        rule = self._rule("positive_amount", "range", "amount", dimension="validity", severity="error", params={"min": 0})
        issues, summaries = apply_rules(
            run_id="run-003",
            connection_config=self._conn_cfg(sqlite_dsn_file),
            rules=[rule],
            discovered_tables=tables,
        )
        assert len(issues) == 1
        assert "out of range" in issues[0].message.lower() or "outside" in issues[0].message.lower()

    def test_unknown_expression_produces_error_issue(self, sqlite_dsn_file):
        tables = [
            DiscoveredTable(
                schema_name=None,
                table_name="orders",
                columns=[
                    DiscoveredColumn(schema_name=None, table_name="orders", column_name="id", data_type="INTEGER", is_nullable=True, ordinal_position=1),
                ],
            )
        ]
        rule = self._rule("bad_expr", "FOOBAR", "id", dimension="validity", severity="warning")
        issues, summaries = apply_rules(
            run_id="run-004",
            connection_config=self._conn_cfg(sqlite_dsn_file),
            rules=[rule],
            discovered_tables=tables,
        )
        assert len(issues) == 1
        assert "unknown expression" in issues[0].message.lower()

    def test_rule_passes_when_no_violations(self, sqlite_dsn_file):
        tables = [
            DiscoveredTable(
                schema_name=None,
                table_name="orders",
                columns=[
                    DiscoveredColumn(schema_name=None, table_name="orders", column_name="id", data_type="INTEGER", is_nullable=True, ordinal_position=1),
                ],
            )
        ]
        # All orders have non-null ids in the fixture (though duplicated)
        rule = self._rule("not_null_order_id", "NOT NULL", "id", dimension="completeness", severity="error")
        issues, summaries = apply_rules(
            run_id="run-005",
            connection_config=self._conn_cfg(sqlite_dsn_file),
            rules=[rule],
            discovered_tables=tables,
        )
        assert len(issues) == 0
        assert summaries[0].targets_failed == 0

    def test_scope_filters_columns(self, sqlite_dsn_file):
        tables = [
            DiscoveredTable(
                schema_name=None,
                table_name="orders",
                columns=[
                    DiscoveredColumn(schema_name=None, table_name="orders", column_name="id", data_type="INTEGER", is_nullable=True, ordinal_position=1),
                    DiscoveredColumn(schema_name=None, table_name="orders", column_name="amount", data_type="REAL", is_nullable=True, ordinal_position=2),
                    DiscoveredColumn(schema_name=None, table_name="orders", column_name="customer_id", data_type="INTEGER", is_nullable=True, ordinal_position=3),
                ],
            )
        ]
        # Only check customer_id, which has 1 NULL
        rule = self._rule("check_fk", "NOT NULL", "customer_id", dimension="completeness", severity="warning")
        issues, summaries = apply_rules(
            run_id="run-006",
            connection_config=self._conn_cfg(sqlite_dsn_file),
            rules=[rule],
            discovered_tables=tables,
        )
        assert len(issues) == 1
        assert issues[0].column_name == "customer_id"
        assert summaries[0].targets_checked == 1  # only customer_id matched
