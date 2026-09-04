"""Unit tests for the dialect registry: DSN and name resolution.

Ground truth for every expected value here is the DSN scheme itself, read
from `docs/CONVENTIONS-DQT.md` §3 and from the DSN forms the pre-DQT-08
`_detect_dialect` already accepted. Nothing here is derived by running the
code under test.
"""

from __future__ import annotations

import pytest

from dqt.sql.dialects import (
    POSTGRESQL,
    SQLITE,
    SQLSERVER,
    SUPPORTED_DIALECT_NAMES,
    Dialect,
    get_dialect,
    get_dialect_by_name,
)


class TestGetDialectFromDsn:
    """A DSN must resolve to exactly one dialect, aliases included."""

    def test_sqlite_dsn(self):
        assert get_dialect("sqlite:///dev.db") is SQLITE

    def test_sqlite_dsn_without_third_slash(self):
        # The pre-DQT-08 rules._get_connection accepted "sqlite://path" as
        # well as "sqlite:///path"; that leniency is preserved.
        assert get_dialect("sqlite://dev.db") is SQLITE

    def test_postgresql_dsn(self):
        assert get_dialect("postgresql://u:p@h/db") is POSTGRESQL

    def test_postgres_alias_dsn(self):
        assert get_dialect("postgres://u:p@h/db") is POSTGRESQL

    def test_mssql_dsn(self):
        assert get_dialect("mssql://sa:pw@host/db") is SQLSERVER

    def test_sqlserver_alias_dsn(self):
        assert get_dialect("sqlserver://sa:pw@host/db") is SQLSERVER

    def test_unsupported_dsn_raises_naming_the_dsn(self):
        with pytest.raises(ValueError, match="mysql://u:p@h/db"):
            get_dialect("mysql://u:p@h/db")


class TestGetDialectByName:
    """Canonical dialect names, plus the one historical alias."""

    def test_each_supported_name_resolves(self):
        for name in SUPPORTED_DIALECT_NAMES:
            assert get_dialect_by_name(name).name == name

    def test_supported_names_are_exactly_the_three_dialects(self):
        # Hand-derived from CONVENTIONS-DQT.md §3's dialect table, as amended
        # by this task: SQLite, PostgreSQL, SQL Server. MySQL stays out.
        assert set(SUPPORTED_DIALECT_NAMES) == {"sqlite", "postgresql", "sqlserver"}

    def test_postgres_alias_name_resolves_to_postgresql(self):
        assert get_dialect_by_name("postgres") is POSTGRESQL

    def test_unknown_name_raises(self):
        with pytest.raises(ValueError, match="mysql"):
            get_dialect_by_name("mysql")


class TestProtocolConformance:
    """Every registered dialect must satisfy the Dialect protocol."""

    @pytest.mark.parametrize("dialect", [SQLITE, POSTGRESQL, SQLSERVER])
    def test_dialect_satisfies_protocol(self, dialect):
        assert isinstance(dialect, Dialect)

    @pytest.mark.parametrize("dialect", [SQLITE, POSTGRESQL, SQLSERVER])
    def test_dialect_is_a_shared_singleton(self, dialect):
        # Dialects are stateless; resolving one twice must give the same
        # object, so no caller can mutate a private copy.
        assert get_dialect_by_name(dialect.name) is dialect

    def test_parameter_placeholders_match_each_drivers_paramstyle(self):
        # Hand-derived from each driver's declared DBAPI paramstyle:
        # sqlite3 -> qmark, psycopg -> pyformat, pyodbc -> qmark.
        assert SQLITE.parameter_placeholder == "?"
        assert POSTGRESQL.parameter_placeholder == "%s"
        assert SQLSERVER.parameter_placeholder == "?"
