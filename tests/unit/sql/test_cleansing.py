"""
Unit tests for dqt.sql.cleansing.

All tests use a SQLite in-memory database opened via a temp file so that
_get_connection() can find it by DSN.  Tests cover:

- standardize: trim, case, normalize_spaces, no-op rows, NULL skipping
- deduplicate: keep first/last, multi-column key, no duplicates
- lookup_correct: mapping applied, unknown values unchanged, empty mapping
- apply_cleansing: enabled flag, unknown operation, commit/rollback, multi-op
- CleansingResult: log, total_changes, tables_affected, errors
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from dqt.common.models import ConnectionConfig
from dqt.sql.cleansing import (
    CleansingConfig,
    CleansingLog,
    apply_cleansing,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dsn(db_file: Path) -> str:
    return f"sqlite:///{db_file}"


def _conn_cfg(db_file: Path) -> ConnectionConfig:
    return ConnectionConfig(id="test", dsn=_dsn(db_file))


def _read_col(db_file: Path, table: str, col: str) -> list:
    """Read all non-null values of a column from the test DB."""
    conn = sqlite3.connect(str(db_file))
    rows = conn.execute(f'SELECT "{col}" FROM {table}').fetchall()
    conn.close()
    return [r[0] for r in rows]


def _count_rows(db_file: Path, table: str) -> int:
    conn = sqlite3.connect(str(db_file))
    count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    conn.close()
    return count


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def users_db(make_sqlite_db) -> Path:
    """SQLite DB with a 'users' table containing whitespace/case issues."""
    return make_sqlite_db(
        "users.db",
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            email TEXT,
            name  TEXT
        );
        INSERT INTO users VALUES (1, '  Alice@Example.COM  ', '  alice  ');
        INSERT INTO users VALUES (2, 'BOB@EXAMPLE.COM',       'BOB');
        INSERT INTO users VALUES (3, NULL,                    'carol');
        INSERT INTO users VALUES (4, 'dave@example.com',      'Dave');
        """,
    )


@pytest.fixture
def dup_db(make_sqlite_db) -> Path:
    """SQLite DB with duplicate rows on 'email'."""
    return make_sqlite_db(
        "dup.db",
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            email TEXT,
            name  TEXT
        );
        INSERT INTO users VALUES (1, 'alice@example.com', 'Alice 1');
        INSERT INTO users VALUES (2, 'bob@example.com',   'Bob');
        INSERT INTO users VALUES (3, 'alice@example.com', 'Alice 2'); -- duplicate
        INSERT INTO users VALUES (4, 'carol@example.com', 'Carol');
        INSERT INTO users VALUES (5, 'alice@example.com', 'Alice 3'); -- duplicate
        """,
    )


@pytest.fixture
def dup_db_with_nulls(make_sqlite_db) -> Path:
    """SQLite DB with one real duplicate pair plus several distinct NULL-email rows.

    Regression fixture for the confirmed data-loss bug: GROUP BY collapses all
    NULL-keyed rows into a single group, so a naive dedup would delete every
    NULL-email customer except one, even though they are genuinely distinct.
    """
    return make_sqlite_db(
        "dup_nulls.db",
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            email TEXT,
            name  TEXT
        );
        INSERT INTO users VALUES (1, 'alice@example.com', 'Alice 1');
        INSERT INTO users VALUES (2, 'alice@example.com', 'Alice 2'); -- real duplicate
        INSERT INTO users VALUES (3, NULL, 'NoEmail 1');
        INSERT INTO users VALUES (4, NULL, 'NoEmail 2');
        INSERT INTO users VALUES (5, NULL, 'NoEmail 3');
        """,
    )


@pytest.fixture
def lookup_db(make_sqlite_db) -> Path:
    """SQLite DB with a 'orders' table and a 'status_map' lookup table."""
    return make_sqlite_db(
        "lookup.db",
        """
        CREATE TABLE orders (
            id     INTEGER PRIMARY KEY,
            status TEXT
        );
        INSERT INTO orders VALUES (1, 'pend');
        INSERT INTO orders VALUES (2, 'SHIPPED');
        INSERT INTO orders VALUES (3, 'cncl');
        INSERT INTO orders VALUES (4, 'delivered');  -- already canonical

        CREATE TABLE status_map (
            from_value TEXT,
            to_value   TEXT
        );
        INSERT INTO status_map VALUES ('pend',    'pending');
        INSERT INTO status_map VALUES ('cncl',    'cancelled');
        INSERT INTO status_map VALUES ('SHIPPED', 'shipped');
        """,
    )


# ---------------------------------------------------------------------------
# standardize
# ---------------------------------------------------------------------------


class TestStandardize:
    def test_trim_and_lower(self, users_db):
        cfg = CleansingConfig(
            table_name="users",
            column_name="email",
            operation="standardize",
            params={"trim": True, "case": "lower"},
        )
        result = apply_cleansing("run-1", _conn_cfg(users_db), [cfg])
        emails = _read_col(users_db, "users", "email")
        assert "alice@example.com" in emails
        assert "bob@example.com" in emails
        # Unchanged row (already lower, no leading/trailing spaces)
        assert "dave@example.com" in emails
        # NULL row not touched
        assert None in emails
        assert result.total_changes == 2  # rows 1 and 2 changed

    def test_upper_case(self, users_db):
        cfg = CleansingConfig(
            table_name="users",
            column_name="name",
            operation="standardize",
            params={"trim": True, "case": "upper"},
        )
        apply_cleansing("run-2", _conn_cfg(users_db), [cfg])
        names = _read_col(users_db, "users", "name")
        assert "ALICE" in names
        assert "BOB" in names
        assert "CAROL" in names
        assert "DAVE" in names

    def test_normalize_spaces(self, make_sqlite_db):
        db_file = make_sqlite_db(
            "spaces.db",
            """
            CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT);
            INSERT INTO t VALUES (1, 'hello   world');
            INSERT INTO t VALUES (2, 'no  extra');
            INSERT INTO t VALUES (3, 'clean');
            """,
        )
        cfg = CleansingConfig(
            table_name="t",
            column_name="v",
            operation="standardize",
            params={"normalize_spaces": True, "trim": False},
        )
        result = apply_cleansing("run-3", _conn_cfg(db_file), [cfg])
        vals = _read_col(db_file, "t", "v")
        assert "hello world" in vals
        assert "no extra" in vals
        assert "clean" in vals
        assert result.total_changes == 2

    def test_no_change_when_already_clean(self, users_db):
        cfg = CleansingConfig(
            table_name="users",
            column_name="email",
            operation="standardize",
            params={"trim": False},  # no-op
        )
        result = apply_cleansing("run-4", _conn_cfg(users_db), [cfg])
        assert result.total_changes == 0

    def test_log_records_before_after(self, users_db):
        cfg = CleansingConfig(
            table_name="users",
            column_name="email",
            operation="standardize",
            params={"trim": True, "case": "lower"},
        )
        result = apply_cleansing("run-5", _conn_cfg(users_db), [cfg])
        assert len(result.log) > 0
        entry: CleansingLog = result.log[0]
        assert entry.before_value is not None
        assert entry.after_value is not None
        assert entry.before_value != entry.after_value
        assert entry.operation == "standardize"


# ---------------------------------------------------------------------------
# deduplicate
# ---------------------------------------------------------------------------


class TestDeduplicate:
    def test_keep_first_removes_duplicates(self, dup_db):
        cfg = CleansingConfig(
            table_name="users",
            column_name=None,
            operation="deduplicate",
            params={"key_columns": ["email"], "keep": "first"},
        )
        result = apply_cleansing("run-6", _conn_cfg(dup_db), [cfg])
        assert _count_rows(dup_db, "users") == 3  # alice, bob, carol
        assert result.total_changes == 2  # 2 duplicate rows deleted

    def test_keep_last(self, dup_db):
        cfg = CleansingConfig(
            table_name="users",
            column_name=None,
            operation="deduplicate",
            params={"key_columns": ["email"], "keep": "last"},
        )
        result = apply_cleansing("run-7", _conn_cfg(dup_db), [cfg])
        assert _count_rows(dup_db, "users") == 3
        # 'Alice 3' (id=5) should survive
        names = _read_col(dup_db, "users", "name")
        assert "Alice 3" in names
        assert result.total_changes == 2

    def test_null_key_rows_not_treated_as_duplicates(self, dup_db_with_nulls):
        cfg = CleansingConfig(
            table_name="users",
            column_name=None,
            operation="deduplicate",
            params={"key_columns": ["email"], "keep": "first"},
        )
        result = apply_cleansing("run-null-key", _conn_cfg(dup_db_with_nulls), [cfg])
        # Only the one real 'alice@example.com' duplicate should be removed;
        # all three distinct NULL-email rows must survive.
        assert result.total_changes == 1
        assert _count_rows(dup_db_with_nulls, "users") == 4
        names = _read_col(dup_db_with_nulls, "users", "name")
        assert {"NoEmail 1", "NoEmail 2", "NoEmail 3"} <= set(names)

    def test_no_duplicates_no_change(self, users_db):
        cfg = CleansingConfig(
            table_name="users",
            column_name=None,
            operation="deduplicate",
            params={"key_columns": ["id"]},
        )
        result = apply_cleansing("run-8", _conn_cfg(users_db), [cfg])
        assert result.total_changes == 0

    def test_missing_key_columns_raises(self, users_db):
        cfg = CleansingConfig(
            table_name="users",
            column_name=None,
            operation="deduplicate",
            params={},  # no key_columns
        )
        result = apply_cleansing("run-9", _conn_cfg(users_db), [cfg])
        assert len(result.errors) == 1
        assert "key_columns" in result.errors[0]

    def test_log_contains_deleted_row_data(self, dup_db):
        cfg = CleansingConfig(
            table_name="users",
            column_name=None,
            operation="deduplicate",
            params={"key_columns": ["email"], "keep": "first"},
        )
        result = apply_cleansing("run-10", _conn_cfg(dup_db), [cfg])
        assert len(result.log) == 2
        for entry in result.log:
            assert entry.operation == "deduplicate"
            assert isinstance(entry.before_value, dict)
            assert entry.after_value is None


# ---------------------------------------------------------------------------
# lookup_correct
# ---------------------------------------------------------------------------


class TestLookupCorrect:
    def test_applies_mapping(self, lookup_db):
        cfg = CleansingConfig(
            table_name="orders",
            column_name="status",
            operation="lookup_correct",
            params={
                "lookup_table": "status_map",
                "from_column": "from_value",
                "to_column": "to_value",
            },
        )
        result = apply_cleansing("run-11", _conn_cfg(lookup_db), [cfg])
        statuses = _read_col(lookup_db, "orders", "status")
        assert "pending" in statuses
        assert "cancelled" in statuses
        assert "shipped" in statuses
        assert "delivered" in statuses  # unchanged
        assert result.total_changes == 3

    def test_unknown_values_unchanged(self, lookup_db):
        cfg = CleansingConfig(
            table_name="orders",
            column_name="status",
            operation="lookup_correct",
            params={
                "lookup_table": "status_map",
                "from_column": "from_value",
                "to_column": "to_value",
            },
        )
        apply_cleansing("run-12", _conn_cfg(lookup_db), [cfg])
        statuses = _read_col(lookup_db, "orders", "status")
        assert "delivered" in statuses  # was not in map, must remain

    def test_missing_lookup_table_param_raises(self, lookup_db):
        cfg = CleansingConfig(
            table_name="orders",
            column_name="status",
            operation="lookup_correct",
            params={},
        )
        result = apply_cleansing("run-13", _conn_cfg(lookup_db), [cfg])
        assert len(result.errors) == 1
        assert "lookup_table" in result.errors[0]


# ---------------------------------------------------------------------------
# apply_cleansing: meta-behaviour
# ---------------------------------------------------------------------------


class TestApplyCleansing:
    def test_disabled_config_skipped(self, users_db):
        cfg = CleansingConfig(
            table_name="users",
            column_name="email",
            operation="standardize",
            params={"case": "lower", "trim": True},
            enabled=False,
        )
        result = apply_cleansing("run-14", _conn_cfg(users_db), [cfg])
        assert result.total_changes == 0

    def test_unknown_operation_recorded_as_error(self, users_db):
        cfg = CleansingConfig(
            table_name="users",
            column_name="email",
            operation="standardize",  # valid type; we'll monkeypatch below
            params={},
        )
        # Force an invalid operation by direct attribute set after construction
        cfg.operation = "foobar"  # type: ignore[assignment]
        result = apply_cleansing("run-15", _conn_cfg(users_db), [cfg])
        assert len(result.errors) == 1
        assert "foobar" in result.errors[0]

    def test_multiple_operations_applied_in_order(self, users_db):
        cfgs = [
            CleansingConfig(
                table_name="users",
                column_name="email",
                operation="standardize",
                params={"trim": True, "case": "lower"},
            ),
            CleansingConfig(
                table_name="users",
                column_name="name",
                operation="standardize",
                params={"trim": True, "case": "title"},
            ),
        ]
        result = apply_cleansing("run-16", _conn_cfg(users_db), cfgs)
        assert result.total_changes >= 2
        assert result.tables_affected == 1  # both ops on same table

    def test_tables_affected_counts_distinct_tables(self, make_sqlite_db):
        db_file = make_sqlite_db(
            "multi.db",
            """
            CREATE TABLE t1 (id INTEGER PRIMARY KEY, v TEXT);
            CREATE TABLE t2 (id INTEGER PRIMARY KEY, v TEXT);
            INSERT INTO t1 VALUES (1, '  hello  ');
            INSERT INTO t2 VALUES (1, '  world  ');
            """,
        )
        cfgs = [
            CleansingConfig(
                table_name="t1", column_name="v", operation="standardize", params={"trim": True}
            ),
            CleansingConfig(
                table_name="t2", column_name="v", operation="standardize", params={"trim": True}
            ),
        ]
        result = apply_cleansing("run-17", _conn_cfg(db_file), cfgs)
        assert result.tables_affected == 2
        assert result.total_changes == 2

    def test_result_has_correct_run_id(self, users_db):
        cfg = CleansingConfig(
            table_name="users",
            column_name="email",
            operation="standardize",
            params={"trim": True},
        )
        result = apply_cleansing("my-run-id", _conn_cfg(users_db), [cfg])
        assert result.run_id == "my-run-id"
