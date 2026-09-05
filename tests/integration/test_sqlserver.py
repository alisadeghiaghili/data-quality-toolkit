"""SQL Server exercised against a real server.

`DQT-08` shipped a SQL Server dialect whose every assertion was about SQL
text: whether ``pyodbc`` accepts the generated ODBC connection string, and
whether ``INFORMATION_SCHEMA`` returns what ``fetch_column_metadata``
expects, could only be settled against an instance. That PR said so and left
a skipped placeholder naming the gap. This file closes it.

The most important thing here is not that things work. It is that SQL Server
is the dialect where DQT's read-only promise is **weaker**, and these tests
say so out loud rather than letting the shared vocabulary imply otherwise:
``ReadOnlyEnforcement.ADVISORY`` means the ODBC access-mode hint is a request,
not a guarantee, and a write that reaches the server will land.

Skips when ``DQT_SQLSERVER_TEST_DSN`` is unset, so a developer without an
instance is not blocked. CI sets it, which is what makes the skip honest
rather than a way of never finding out.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from dqt.common.models import ConnectionConfig, RuleConfig, RuleScope
from dqt.common.storage import RunStore
from dqt.exceptions import ReadOnlyViolationError
from dqt.sql._connect import get_connection, get_dialect_for
from dqt.sql.cleansing import (
    CleansingConfig,
    cleanse_apply,
    cleanse_plan,
    revert,
)
from dqt.sql.dialects.base import ReadOnlyEnforcement
from dqt.sql.profiling import SqlProfiler
from dqt.sql.rules import apply_rules
from dqt.sql.schema_discovery import discover_schema

SQLSERVER_DSN = os.environ.get("DQT_SQLSERVER_TEST_DSN")

pytestmark = pytest.mark.skipif(
    not SQLSERVER_DSN,
    reason=(
        "DQT_SQLSERVER_TEST_DSN is not set. CI sets it against a service "
        "container; set it locally to exercise the SQL Server dialect."
    ),
)


class _NullStore:
    """A store for calls that fail before anything is persisted.

    Example:
        cleanse_plan(config, configs, store=_NullStore())
    """

    def __init__(self) -> None:
        """Start with no saved plan.

        Example:
            store = _NullStore()
        """
        self.plan: object | None = None

    def save_cleansing_plan(self, plan: object) -> None:
        """Keep the plan in memory so a test can read its id back.

        Args:
            plan: The plan to keep.

        Returns:
            None.

        Example:
            store.save_cleansing_plan(plan)
        """
        self.plan = plan

    def load_cleansing_plan(self, plan_id: str) -> object:
        """Return the plan saved by :meth:`save_cleansing_plan`.

        Args:
            plan_id: Ignored; only one plan is ever held.

        Returns:
            The saved plan.

        Example:
            plan = store.load_cleansing_plan("anything")
        """
        return self.plan


def _writable() -> ConnectionConfig:
    """Return a writable connection to the test instance.

    Returns:
        A ConnectionConfig with read_only disabled.

    Example:
        connection = get_connection(_writable())
    """
    return ConnectionConfig(id="mssql-setup", dsn=str(SQLSERVER_DSN), read_only=False)


def _execute(*statements: str) -> None:
    """Run statements on a writable connection and commit.

    Args:
        *statements: SQL to execute in order.

    Returns:
        None.

    Example:
        _execute("CREATE TABLE t (id INT)")
    """
    connection = get_connection(_writable())
    try:
        cursor = connection.cursor()
        for statement in statements:
            cursor.execute(statement)
        connection.commit()
    finally:
        connection.close()


def _emails(table: str) -> set[str]:
    """Return the non-NULL email values currently in *table*.

    Args:
        table: Table to read.

    Returns:
        The values as a set, so ordering does not enter the assertion.

    Example:
        assert _emails(seeded_table) == {"a@b.com"}
    """
    connection = get_connection(_writable())
    try:
        cursor = connection.cursor()
        cursor.execute(f"SELECT email FROM {table} WHERE email IS NOT NULL")
        return {row[0] for row in cursor.fetchall()}
    finally:
        connection.close()


@pytest.fixture
def seeded_table() -> Iterator[str]:
    """Create a keyed table with hand-counted contents, then drop it.

    Five rows. ``email`` is NULL on two of them and holds one value that is
    not an email, counted from the literal INSERT below.

    Yields:
        The name of the created table.

    Example:
        def test_something(seeded_table):
            ...
    """
    table = f"dqt_test_{uuid.uuid4().hex[:8]}"
    _execute(
        f"CREATE TABLE {table} (id INT NOT NULL PRIMARY KEY, email NVARCHAR(200) NULL)",
        f"INSERT INTO {table} (id, email) VALUES "
        "(1, 'a@b.com'), (2, NULL), (3, 'c@d.com'), (4, NULL), (5, 'not-an-email')",
    )
    yield table
    _execute(f"DROP TABLE IF EXISTS {table}")


@pytest.fixture
def keyless_table() -> Iterator[str]:
    """Create a table with no primary key, then drop it.

    Yields:
        The name of the created table.

    Example:
        def test_something(keyless_table):
            ...
    """
    table = f"dqt_nokey_{uuid.uuid4().hex[:8]}"
    _execute(f"CREATE TABLE {table} (a NVARCHAR(50) NULL, b NVARCHAR(50) NULL)")
    yield table
    _execute(f"DROP TABLE IF EXISTS {table}")


class TestReadOnlyIsAdvisoryHereAndSaysSo:
    """SQL Server is where DQT's read-only promise is weakest.

    SQLite opens ``mode=ro`` and PostgreSQL sets the session read-only; both
    are refusals the engine makes. SQL Server's ODBC access-mode attribute is
    a hint the driver may pass along, and nothing stops a write that reaches
    the server. `DQT-08` encoded that as ``ReadOnlyEnforcement.ADVISORY``;
    these tests check the encoding is honest rather than decorative.
    """

    def test_the_dialect_reports_advisory_enforcement(self) -> None:
        """The tri-state exists so this case cannot hide behind the other two."""
        config = ConnectionConfig(id="mssql", dsn=str(SQLSERVER_DSN))

        assert get_dialect_for(config).read_only_enforcement is ReadOnlyEnforcement.ADVISORY

    def test_opening_read_only_warns_that_it_is_not_enforced(self) -> None:
        """A caller asking for read_only is told what they did not get.

        Opening it silently would leave someone believing they had the
        guarantee PostgreSQL gives them.
        """
        read_only = ConnectionConfig(id="mssql-ro", dsn=str(SQLSERVER_DSN), read_only=True)

        with pytest.warns(RuntimeWarning, match="not enforced"):
            get_connection(read_only).close()

    def test_the_server_does_not_block_a_write_and_that_is_the_point(
        self, seeded_table: str
    ) -> None:
        """The write succeeds, which is exactly why the warning exists.

        This is the assertion most worth having and the least comfortable.
        The same code against PostgreSQL raises; here it commits. If a future
        change ever made SQL Server enforce read-only at the server, this test
        would fail and the tri-state should be corrected -- which is the point
        of asserting a limitation rather than only documenting it.
        """
        read_only = ConnectionConfig(id="mssql-ro", dsn=str(SQLSERVER_DSN), read_only=True)
        with pytest.warns(RuntimeWarning):
            connection = get_connection(read_only)
        try:
            cursor = connection.cursor()
            cursor.execute(f"UPDATE {seeded_table} SET email = 'written' WHERE id = 1")
            connection.commit()
        finally:
            connection.close()

        verify = get_connection(_writable())
        try:
            cursor = verify.cursor()
            cursor.execute(f"SELECT email FROM {seeded_table} WHERE id = 1")
            assert cursor.fetchone()[0] == "written"
        finally:
            verify.close()

    def test_dqt_still_refuses_to_build_the_mutation(self, seeded_table: str) -> None:
        """DQT's own guard is the only line of defence here, and it holds.

        On the other two dialects this is defence in depth. On SQL Server it
        is the whole defence, which is why `DQT-05`'s application-level check
        matters more here than anywhere else.
        """
        read_only = ConnectionConfig(id="mssql-ro", dsn=str(SQLSERVER_DSN), read_only=True)
        configs = [
            CleansingConfig(
                table_name=seeded_table,
                column_name="email",
                operation="standardize",
                params={"trim": True, "case": "lower"},
            )
        ]
        store = _NullStore()
        with pytest.warns(RuntimeWarning):
            plan = cleanse_plan(read_only, configs, store=store)

        with pytest.raises(ReadOnlyViolationError):
            cleanse_apply(plan.plan_id, read_only, store=store)


class TestTheDialectWorksAgainstTheServer:
    """Everything `DQT-08` could only assert as SQL text."""

    def test_the_odbc_connection_string_is_accepted(self) -> None:
        """``pyodbc`` accepts what ``odbc_connection_string`` generates.

        This was the single largest unknown in `DQT-08`: the string was built
        and unit-tested against hand-written expectations, and never handed to
        a driver.
        """
        connection = get_connection(ConnectionConfig(id="mssql", dsn=str(SQLSERVER_DSN)))
        try:
            cursor = connection.cursor()
            cursor.execute("SELECT 1")
            assert cursor.fetchone()[0] == 1
        finally:
            connection.close()

    def test_discovery_finds_the_seeded_table(self, seeded_table: str) -> None:
        """``INFORMATION_SCHEMA`` introspection returns what was created."""
        config = ConnectionConfig(id="mssql", dsn=str(SQLSERVER_DSN))

        assert seeded_table in {t.table_name for t in discover_schema(config)}

    def test_discovery_reports_the_primary_key(self, seeded_table: str) -> None:
        """`NEW-M` needs the key, and this is where it comes from.

        Ground truth: the fixture declares ``id INT NOT NULL PRIMARY KEY``.
        """
        config = ConnectionConfig(id="mssql", dsn=str(SQLSERVER_DSN))
        table = next(t for t in discover_schema(config) if t.table_name == seeded_table)

        assert [c.column_name for c in table.columns if c.is_primary_key] == ["id"]

    def test_a_keyless_table_is_still_discovered(self, keyless_table: str) -> None:
        """The key join is a LEFT JOIN, verified rather than read.

        An inner join would hide every keyless table, so DQT would profile a
        database and silently omit tables.
        """
        config = ConnectionConfig(id="mssql", dsn=str(SQLSERVER_DSN))

        assert keyless_table in {t.table_name for t in discover_schema(config)}

    def test_profiling_counts_match_the_literal_insert(self, seeded_table: str) -> None:
        """Ground truth: five rows, two NULL emails, read off the INSERT.

        The same assertion the SQLite and PostgreSQL suites make. Three
        engines agreeing is what makes the dialect abstraction worth having;
        one engine agreeing with itself proves nothing.
        """
        config = ConnectionConfig(id="mssql", dsn=str(SQLSERVER_DSN))
        tables = [t for t in discover_schema(config) if t.table_name == seeded_table]

        profiles = SqlProfiler(config).profile_tables(tables)

        assert profiles[0].row_count == 5
        email = next(c for c in profiles[0].columns if c.column_name == "email")
        assert email.null_count == 2

    def test_a_regex_rule_is_refused_rather_than_silently_passing(self, seeded_table: str) -> None:
        """SQL Server has no regex operator, and DQT says so.

        Reporting zero violations would be a false clean bill of health --
        the same defect `DQT-04` fixed on SQLite, where `regex` rules
        evaluated against a function that did not exist.
        """
        config = ConnectionConfig(id="mssql", dsn=str(SQLSERVER_DSN))
        tables = [t for t in discover_schema(config) if t.table_name == seeded_table]
        rule = RuleConfig(
            name="email-shape",
            dimension="validity",
            severity="error",
            scope=RuleScope(table_pattern=seeded_table, column_pattern="email"),
            expression="regex",
            params={"pattern": r"^[^@\s]+@[^@\s]+\.[^@\s]+$"},
        )

        issues, _ = apply_rules(
            run_id="run-mssql",
            connection_config=config,
            rules=[rule],
            discovered_tables=tables,
        )

        assert any("regular-expression" in issue.message.lower() for issue in issues)


class TestCleansingRoundTripsOnSqlServer:
    """`NEW-M` in practice: rows addressed by primary key, on a third engine."""

    def test_plan_apply_and_revert_restore_the_original_values(
        self, seeded_table: str, tmp_path: Path
    ) -> None:
        """The change lands and comes back, addressed by the primary key.

        Ground truth: three of the five seeded rows have a non-NULL email and
        all three are lowercase, so upper-casing changes exactly three. The
        two NULLs are skipped by the ``IS NOT NULL`` guard.

        Before `NEW-M` none of this was reachable on SQL Server -- cleansing
        died at its first query looking for ``rowid``.
        """
        config = _writable()
        store = RunStore(db_path=tmp_path / "runs.db")
        store.init_schema()
        configs = [
            CleansingConfig(
                table_name=seeded_table,
                column_name="email",
                operation="standardize",
                params={"trim": True, "case": "upper"},
            )
        ]

        plan = cleanse_plan(config, configs, store=store)

        assert len(plan.changes) == 3
        # Addressed by the key the database maintains, not a disk position.
        assert all(change.row_key.keys() == {"id"} for change in plan.changes)

        cleanse_apply(plan.plan_id, config, store=store)
        assert _emails(seeded_table) == {"A@B.COM", "C@D.COM", "NOT-AN-EMAIL"}

        revert(plan.plan_id, config, store=store)
        assert _emails(seeded_table) == {"a@b.com", "c@d.com", "not-an-email"}

    def test_cleansing_a_keyless_table_refuses_and_says_why(self, keyless_table: str) -> None:
        """No key and no stable locator, so DQT refuses up front.

        SQL Server's ``%%physloc%%`` is a physical address that moves, so the
        dialect reports no locator at all. The error names the table and the
        fix instead of failing inside a query.
        """
        configs = [
            CleansingConfig(
                table_name=keyless_table,
                column_name="a",
                operation="standardize",
                params={"trim": True},
            )
        ]

        with pytest.raises(ValueError, match="primary key"):
            cleanse_plan(_writable(), configs, store=_NullStore())
