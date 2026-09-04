"""Unit tests for the single user-database connection authority (`DQT-08`).

Two things are proven here.

1. **The bypass is closed.** Before `DQT-08` there were two connection-opening
   paths, and only ``rules._get_connection`` honoured
   ``ConnectionConfig.read_only``. ``schema_discovery.connect_sql`` never even
   read the flag, so schema discovery and profiling opened writable
   connections regardless of configuration. The tests in
   :class:`TestReadOnlyIsEnforcedOnEveryPath` reproduce that through the
   public API and fail against the unfixed code.
2. **There is only one path left.** :class:`TestSingleConnectionAuthority`
   asserts the second opener is gone rather than merely fixed, because two
   correct openers still reproduce the single-authority violation the task
   exists to close.

The read-only reproduction uses a *missing* database file. That is the
sharpest observable difference between the two pre-`DQT-08` paths and needs no
access to the connection object: a ``mode=ro`` open of a missing file raises,
while a plain ``sqlite3.connect`` silently creates it. So "did this call
create a database file?" answers "was read-only honoured?" from outside.
"""

from __future__ import annotations

import sqlite3

import pytest

from dqt.common.models import ConnectionConfig
from dqt.sql import schema_discovery
from dqt.sql._connect import get_connection, get_dialect_for
from dqt.sql.dialects import SQLITE
from dqt.sql.profiling import SqlProfiler
from dqt.sql.schema_discovery import discover_schema


@pytest.fixture
def seeded_database(tmp_path):
    """A real SQLite file with one table and one row, for read-only probing."""
    db_path = tmp_path / "seeded.db"
    connection = sqlite3.connect(db_path)
    connection.execute("CREATE TABLE t (a INTEGER, b TEXT)")
    connection.execute("INSERT INTO t VALUES (1, 'x')")
    connection.commit()
    connection.close()
    return db_path


class TestReadOnlyIsEnforcedOnEveryPath:
    """`read_only=True` must hold whichever facet opened the connection."""

    def test_discovery_does_not_create_a_missing_database_when_read_only(self, tmp_path):
        missing = tmp_path / "absent_discovery.db"
        config = ConnectionConfig(id="t", dsn=f"sqlite:///{missing}")
        assert config.read_only is True

        with pytest.raises(sqlite3.OperationalError):
            discover_schema(config)
        assert not missing.exists(), (
            "read_only=True must not create the database file; "
            "the pre-DQT-08 connect_sql() created it and returned an empty schema"
        )

    def test_profiling_does_not_create_a_missing_database_when_read_only(self, tmp_path):
        missing = tmp_path / "absent_profiling.db"
        config = ConnectionConfig(id="t", dsn=f"sqlite:///{missing}")

        with pytest.raises(sqlite3.OperationalError):
            SqlProfiler(config).profile_tables([])
        assert not missing.exists()

    def test_connection_from_the_authority_rejects_writes_when_read_only(self, seeded_database):
        config = ConnectionConfig(id="t", dsn=f"sqlite:///{seeded_database}")
        connection = get_connection(config)
        try:
            with pytest.raises(sqlite3.OperationalError, match="readonly database"):
                connection.execute("INSERT INTO t VALUES (2, 'y')")
                connection.commit()
        finally:
            connection.close()

    def test_connection_from_the_authority_permits_writes_when_opted_out(self, seeded_database):
        config = ConnectionConfig(id="t", dsn=f"sqlite:///{seeded_database}", read_only=False)
        connection = get_connection(config)
        try:
            connection.execute("INSERT INTO t VALUES (2, 'y')")
            connection.commit()
            assert connection.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 2
        finally:
            connection.close()

    def test_discovery_still_reads_a_read_only_database(self, seeded_database):
        """Enforcing read-only must not break the read path it guards."""
        config = ConnectionConfig(id="t", dsn=f"sqlite:///{seeded_database}")
        tables = discover_schema(config)
        assert [table.table_name for table in tables] == ["t"]


class TestSingleConnectionAuthority:
    """Exactly one function opens a user-database connection."""

    def test_schema_discovery_no_longer_exposes_its_own_connection_opener(self):
        assert not hasattr(schema_discovery, "connect_sql"), (
            "schema_discovery.connect_sql was DQT-08's second connection path; "
            "it must be deleted, not merely corrected"
        )

    def test_rules_no_longer_exposes_its_own_connection_opener(self):
        from dqt.sql import rules

        assert not hasattr(rules, "_get_connection")

    def test_authority_resolves_the_dialect_from_the_connection_config(self):
        config = ConnectionConfig(id="t", dsn="sqlite:///:memory:")
        assert get_dialect_for(config) is SQLITE

    def test_unsupported_dsn_is_rejected_by_the_authority(self):
        config = ConnectionConfig(id="t", dsn="mysql://u:p@h/db")
        with pytest.raises(ValueError, match="mysql"):
            get_connection(config)


class TestAdvisoryReadOnlyIsAnnounced:
    """A dialect that cannot enforce read-only must not imply that it can."""

    def test_no_warning_for_a_driver_enforced_dialect(self, seeded_database, recwarn):
        config = ConnectionConfig(id="t", dsn=f"sqlite:///{seeded_database}")
        connection = get_connection(config)
        connection.close()
        assert [w for w in recwarn if issubclass(w.category, RuntimeWarning)] == []

    def test_sqlserver_read_only_warns_before_the_driver_is_even_needed(self):
        """The warning is a property of the dialect, not of a live server.

        The connection attempt always fails here -- with ``ImportError`` where
        ``pyodbc`` is absent, as in CI, and with a driver error where it is
        installed but no SQL Server is listening. Which one it is does not
        matter and the test deliberately does not care: what matters is that
        the warning was already emitted by the time either happened, since
        that is what proves it does not depend on reaching a server.

        Asserting the specific exception would make this test pass or fail on
        whether the developer happens to have pyodbc installed, which is not
        a property of DQT.
        """
        config = ConnectionConfig(id="wh", dsn="mssql://sa:pw@localhost/dqt")
        with (
            pytest.warns(RuntimeWarning, match="not enforced"),
            pytest.raises(Exception),  # noqa: B017,PT011
        ):
            get_connection(config)


@pytest.mark.skip(
    reason=(
        "Requires a live SQL Server and pyodbc; neither exists in this "
        "repository's CI or development environment. Un-skip and point "
        "DQT_SQLSERVER_TEST_DSN at a throwaway database to exercise it."
    )
)
def test_sqlserver_discovery_against_a_live_server():
    """Placeholder for the one SQL Server claim no unit test can support.

    Every other SQL Server assertion in this branch is about SQL text or a
    decision made without a server. Whether ``pyodbc`` accepts the generated
    ODBC connection string, and whether ``INFORMATION_SCHEMA`` returns what
    :meth:`SqlServerDialect.fetch_column_metadata` expects, can only be
    settled against a real instance. Naming that here keeps the gap visible
    in the test suite rather than only in a pull-request description.
    """
    raise AssertionError("unreachable: this test is skipped")
