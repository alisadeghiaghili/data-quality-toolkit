"""Grounded unit tests for schema discovery (`DQT-08`'s folded `NEW-C` slice).

``schema_discovery.py`` had no dedicated unit tests before this branch: it was
covered only incidentally by the end-to-end integration test, which asserts
shape rather than any hand-computed value. These tests give it an oracle —
the ``CREATE TABLE`` text each test writes by hand — so that `DQT-08`'s move
of its SQLite and PostgreSQL branches into ``dqt.sql.dialects`` can be shown
not to have changed what it reports.

They are characterization tests: they are expected to pass against the code as
it stood before the move, and to keep passing after it. A failure here during
`DQT-08` means the move changed behaviour, not that a new feature is missing.
"""

from __future__ import annotations

import sqlite3

import pytest

from dqt.common.models import ConnectionConfig
from dqt.sql.schema_discovery import DiscoveredColumn, DiscoveredTable, discover_schema


@pytest.fixture
def two_table_database(tmp_path):
    """A hand-written schema: two base tables, one view, known nullability.

    Ground truth for every assertion below is this DDL, not anything the code
    under test reports. ``id`` and ``created_at`` are declared ``NOT NULL``;
    ``email``, ``order_id``'s table-mate ``amount``, and ``customer_id`` are
    not, so exactly three of the six columns are nullable.
    """
    db_path = tmp_path / "discovery.db"
    connection = sqlite3.connect(db_path)
    connection.executescript("""
        CREATE TABLE customers (
            id INTEGER NOT NULL,
            email TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE orders (
            order_id INTEGER NOT NULL,
            customer_id INTEGER,
            amount REAL
        );
        CREATE VIEW customer_orders AS
            SELECT c.id, o.amount FROM customers c JOIN orders o ON o.customer_id = c.id;
    """)
    connection.commit()
    connection.close()
    return db_path


@pytest.fixture
def config(two_table_database):
    return ConnectionConfig(id="t", dsn=f"sqlite:///{two_table_database}")


class TestDiscoverSqliteSchema:
    def test_returns_both_base_tables_in_name_order(self, config):
        tables = discover_schema(config)
        assert [table.table_name for table in tables] == ["customers", "orders"]

    def test_views_are_not_reported_as_tables(self, config):
        assert "customer_orders" not in {table.table_name for table in discover_schema(config)}

    def test_every_table_reports_sqlites_implicit_schema(self, config):
        assert {table.schema_name for table in discover_schema(config)} == {"main"}

    def test_columns_are_reported_in_declaration_order(self, config):
        tables = {table.table_name: table for table in discover_schema(config)}
        assert [column.column_name for column in tables["customers"].columns] == [
            "id",
            "email",
            "created_at",
        ]
        assert [column.column_name for column in tables["orders"].columns] == [
            "order_id",
            "customer_id",
            "amount",
        ]

    def test_declared_types_are_reported_verbatim(self, config):
        tables = {table.table_name: table for table in discover_schema(config)}
        assert [column.data_type for column in tables["customers"].columns] == [
            "INTEGER",
            "TEXT",
            "TEXT",
        ]

    def test_nullability_matches_the_not_null_constraints_in_the_ddl(self, config):
        tables = {table.table_name: table for table in discover_schema(config)}
        nullability = {
            (table_name, column.column_name): column.nullable
            for table_name, table in tables.items()
            for column in table.columns
        }
        assert nullability == {
            ("customers", "id"): False,
            ("customers", "email"): True,
            ("customers", "created_at"): False,
            ("orders", "order_id"): False,
            ("orders", "customer_id"): True,
            ("orders", "amount"): True,
        }

    def test_columns_carry_their_own_schema_and_table_names(self, config):
        tables = {table.table_name: table for table in discover_schema(config)}
        column = tables["orders"].columns[0]
        assert (column.schema_name, column.table_name) == ("main", "orders")

    def test_returns_domain_objects_not_driver_rows(self, config):
        tables = discover_schema(config)
        assert all(isinstance(table, DiscoveredTable) for table in tables)
        assert all(
            isinstance(column, DiscoveredColumn) for table in tables for column in table.columns
        )

    def test_empty_database_discovers_nothing(self, tmp_path):
        db_path = tmp_path / "empty.db"
        connection = sqlite3.connect(db_path)
        connection.execute("PRAGMA user_version = 1")  # force the file to exist
        connection.commit()
        connection.close()
        assert discover_schema(ConnectionConfig(id="t", dsn=f"sqlite:///{db_path}")) == []

    def test_column_with_no_declared_type_reports_unknown(self, tmp_path):
        # SQLite permits a typeless column; discovery must report a placeholder
        # rather than an empty string that would render as a blank cell.
        db_path = tmp_path / "typeless.db"
        connection = sqlite3.connect(db_path)
        connection.execute("CREATE TABLE t (a)")
        connection.commit()
        connection.close()
        tables = discover_schema(ConnectionConfig(id="t", dsn=f"sqlite:///{db_path}"))
        assert tables[0].columns[0].data_type == "UNKNOWN"


class TestUnsupportedDsn:
    def test_unsupported_dsn_is_rejected(self, tmp_path):
        config = ConnectionConfig(id="t", dsn="mysql://u:p@host/db")
        with pytest.raises(ValueError, match="mysql"):
            discover_schema(config)
