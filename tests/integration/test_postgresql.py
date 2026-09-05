"""PostgreSQL exercised against a real server.

`README.md` has listed PostgreSQL as supported since the project began, and
`docs/BACKLOG.md` recorded the gap plainly: the PostgreSQL side of `read_only`
enforcement "is still untested, since there is no PostgreSQL driver or server
available in CI". That is the sharpest version of the problem this repository
exists to avoid — the tool's central safety promise, unexecuted, on the only
production-grade database it claims to support.

`docs/PROPOSAL-v1.0-roadmap.md` makes running PostgreSQL in CI a hard gate for
1.0.0 for that reason. Until these run, "supports PostgreSQL" is a claim with
no evidence behind it.

These tests skip when ``DQT_POSTGRES_TEST_DSN`` is unset, so a developer
without a server is not blocked. CI sets it, which is what makes the skip
honest rather than a way of never finding out.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest

from dqt.common.models import ConnectionConfig, RuleConfig, RuleScope
from dqt.exceptions import ReadOnlyViolationError
from dqt.sql._connect import get_connection, get_dialect_for
from dqt.sql.cleansing import CleansingConfig, cleanse_apply, cleanse_plan
from dqt.sql.profiling import SqlProfiler
from dqt.sql.rules import apply_rules
from dqt.sql.schema_discovery import discover_schema


class _NullStore:
    """A store for calls that fail before anything is persisted.

    Example:
        cleanse_plan(config, configs, store=_NullStore())
    """

    def save_cleansing_plan(self, plan: object) -> None:
        """Discard the plan.

        Args:
            plan: Ignored.

        Returns:
            None.

        Example:
            _NullStore().save_cleansing_plan(plan)
        """


POSTGRES_DSN = os.environ.get("DQT_POSTGRES_TEST_DSN")

pytestmark = pytest.mark.skipif(
    not POSTGRES_DSN,
    reason=(
        "DQT_POSTGRES_TEST_DSN is not set. CI sets it against a service "
        "container; set it locally to exercise the PostgreSQL dialect."
    ),
)


@pytest.fixture
def seeded_table() -> Iterator[str]:
    """Create a table with hand-counted contents, and drop it afterwards.

    Five rows. ``email`` is NULL on two of them and holds one value that does
    not match an email pattern, counted from the literal INSERT below.

    Yields:
        The name of the created table.

    Example:
        def test_something(seeded_table):
            ...
    """
    table = f"dqt_test_{uuid.uuid4().hex[:8]}"
    writable = ConnectionConfig(id="pg-setup", dsn=str(POSTGRES_DSN), read_only=False)
    connection = get_connection(writable)
    try:
        cursor = connection.cursor()
        cursor.execute(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, email TEXT)")
        cursor.execute(
            f"INSERT INTO {table} (id, email) VALUES "
            "(1, 'a@b.com'), (2, NULL), (3, 'c@d.com'), (4, NULL), (5, 'not-an-email')"
        )
        connection.commit()
    finally:
        connection.close()

    yield table

    connection = get_connection(writable)
    try:
        connection.cursor().execute(f"DROP TABLE IF EXISTS {table}")
        connection.commit()
    finally:
        connection.close()


class TestReadOnlyIsActuallyEnforced:
    """The claim that had never been executed.

    `DQT-03` sets ``SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY`` on
    a read-only PostgreSQL connection. Whether the server honours it — and
    whether DQT sends it at all on the path a caller actually takes — was
    never checked against a server.
    """

    def test_the_server_refuses_a_write_on_a_read_only_connection(self, seeded_table: str) -> None:
        """PostgreSQL itself rejects the UPDATE, not just DQT.

        This is the layer that matters. DQT's own guard can be bypassed by any
        code path that forgets to ask; a session the server has put in
        read-only mode cannot be. The assertion is that the write raises at
        the driver, with the connection opened exactly as DQT opens it.
        """
        read_only = ConnectionConfig(id="pg-ro", dsn=str(POSTGRES_DSN), read_only=True)
        connection = get_connection(read_only)
        try:
            with pytest.raises(Exception, match="read-only|read only"):
                cursor = connection.cursor()
                cursor.execute(f"UPDATE {seeded_table} SET email = 'x' WHERE id = 1")
                connection.commit()
        finally:
            connection.close()

    def test_reads_still_work_on_the_same_connection(self, seeded_table: str) -> None:
        """Read-only must not mean useless.

        A guard that also blocked profiling would be trivially safe and
        trivially pointless.
        """
        read_only = ConnectionConfig(id="pg-ro", dsn=str(POSTGRES_DSN), read_only=True)
        connection = get_connection(read_only)
        try:
            cursor = connection.cursor()
            cursor.execute(f"SELECT COUNT(*) FROM {seeded_table}")
            assert cursor.fetchone()[0] == 5
        finally:
            connection.close()

    def test_cleanse_apply_refuses_before_reaching_the_server(self, seeded_table: str) -> None:
        """DQT's own guard fires first, so the server is the second line.

        Defence in depth is the point: the application refuses to build the
        statement, and the session would refuse to run it.
        """
        read_only = ConnectionConfig(id="pg-ro", dsn=str(POSTGRES_DSN), read_only=True)
        configs = [
            CleansingConfig(
                table_name=seeded_table,
                column_name="email",
                operation="standardize",
                params={"trim": True, "case": "lower"},
            )
        ]

        class _Store:
            def save_cleansing_plan(self, plan: object) -> None: ...

            def load_cleansing_plan(self, plan_id: str) -> object:
                return self.plan

        store = _Store()
        store.plan = cleanse_plan(read_only, configs, store=store)  # type: ignore[attr-defined]

        with pytest.raises(ReadOnlyViolationError):
            cleanse_apply(store.plan.plan_id, read_only, store=store)  # type: ignore[attr-defined]


class TestTheDialectWorksAgainstTheServer:
    """Discovery, profiling and regex, against real PostgreSQL rather than SQL text."""

    def test_discovery_finds_the_seeded_table(self, seeded_table: str) -> None:
        """`INFORMATION_SCHEMA` introspection returns what was created."""
        config = ConnectionConfig(id="pg", dsn=str(POSTGRES_DSN))

        tables = {t.table_name for t in discover_schema(config)}

        assert seeded_table in tables

    def test_profiling_counts_match_the_literal_insert(self, seeded_table: str) -> None:
        """Ground truth: five rows, two NULL emails, read off the INSERT.

        The same assertion the SQLite tests make, against a different engine.
        A dialect abstraction is only worth having if both sides agree, and
        this is where that gets checked rather than assumed.
        """
        config = ConnectionConfig(id="pg", dsn=str(POSTGRES_DSN))
        tables = [t for t in discover_schema(config) if t.table_name == seeded_table]

        profiles = SqlProfiler(config).profile_tables(tables)

        assert profiles[0].row_count == 5
        email = next(c for c in profiles[0].columns if c.column_name == "email")
        assert email.null_count == 2

    def test_regex_rules_use_the_native_operator(self, seeded_table: str) -> None:
        """PostgreSQL matches with ``~``, not a Python callback.

        On SQLite `DQT-04` registers a Python function invoked once per row.
        PostgreSQL has a real operator, and the dialect is supposed to use it.
        Ground truth: of the three non-NULL emails, one does not match, and
        NULLs are excluded by the predicate rather than counted as failures.
        """
        config = ConnectionConfig(id="pg", dsn=str(POSTGRES_DSN))
        tables = [t for t in discover_schema(config) if t.table_name == seeded_table]
        rule = RuleConfig(
            name="email-shape",
            dimension="validity",
            severity="error",
            scope=RuleScope(table_pattern=seeded_table, column_pattern="email"),
            expression="regex",
            params={"pattern": r"^[^@\s]+@[^@\s]+\.[^@\s]+$"},
        )

        issues, summaries = apply_rules(
            run_id="run-pg",
            connection_config=config,
            rules=[rule],
            discovered_tables=tables,
        )

        assert summaries[0].targets_failed == 1
        assert issues[0].evidence["non_matching_count"] == 1
        # NULLs are excluded by the predicate, not counted as failures.
        assert issues[0].evidence["total_rows"] == 5

    def test_the_resolved_dialect_is_postgresql(self) -> None:
        """The registry routes a ``postgresql://`` DSN to the right dialect."""
        config = ConnectionConfig(id="pg", dsn=str(POSTGRES_DSN))

        assert get_dialect_for(config).name == "postgresql"


class TestRowIdentityOnPostgresql:
    """`NEW-M`: cleansing addresses rows by primary key here, not by ``ctid``.

    These are the assertions that could not exist before. Cleansing failed on
    PostgreSQL outright with ``UndefinedColumn: column "rowid" does not
    exist``, so nothing downstream of a connection was reachable.
    """

    def test_the_dialect_offers_no_physical_locator(self) -> None:
        """PostgreSQL reports None, and that refusal is the design.

        ``ctid`` exists and would have made the code run. It also moves on
        UPDATE and under VACUUM FULL, so a plan applied in a later process
        could address whatever now sits at the recorded position. Reporting
        None makes cleansing demand a primary key instead of silently
        corrupting a keyless table.
        """
        config = ConnectionConfig(id="pg", dsn=str(POSTGRES_DSN))

        assert get_dialect_for(config).physical_row_locator is None

    def test_discovery_reports_the_primary_key(self, seeded_table: str) -> None:
        """The key has to come from the database, and here it does.

        Ground truth: the fixture declares ``id INTEGER PRIMARY KEY``.
        """
        config = ConnectionConfig(id="pg", dsn=str(POSTGRES_DSN))
        table = next(t for t in discover_schema(config) if t.table_name == seeded_table)

        assert [c.column_name for c in table.columns if c.is_primary_key] == ["id"]

    def test_a_keyless_table_is_still_discovered(self) -> None:
        """The primary-key join is a LEFT JOIN, checked against a real server.

        An inner join would hide keyless tables from discovery entirely, so
        DQT would profile a database and silently omit them -- worse than the
        defect it is here to avoid.
        """
        table_name = f"dqt_nokey_{uuid.uuid4().hex[:8]}"
        writable = ConnectionConfig(id="pg-setup", dsn=str(POSTGRES_DSN), read_only=False)
        connection = get_connection(writable)
        try:
            connection.cursor().execute(f"CREATE TABLE {table_name} (a TEXT, b TEXT)")
            connection.commit()
        finally:
            connection.close()

        try:
            config = ConnectionConfig(id="pg", dsn=str(POSTGRES_DSN))
            tables = {t.table_name for t in discover_schema(config)}

            assert table_name in tables
        finally:
            connection = get_connection(writable)
            try:
                connection.cursor().execute(f"DROP TABLE IF EXISTS {table_name}")
                connection.commit()
            finally:
                connection.close()

    def test_cleansing_a_keyless_table_refuses_and_says_why(self) -> None:
        """The error names the table and the fix, rather than failing in SQL.

        Before `NEW-M` this failed with UndefinedColumn from inside a query,
        which told a DBA nothing. Now it refuses up front and says to add a
        primary key.
        """
        table_name = f"dqt_nokey_{uuid.uuid4().hex[:8]}"
        writable = ConnectionConfig(id="pg-setup", dsn=str(POSTGRES_DSN), read_only=False)
        connection = get_connection(writable)
        try:
            connection.cursor().execute(f"CREATE TABLE {table_name} (a TEXT, b TEXT)")
            connection.commit()
        finally:
            connection.close()

        try:
            configs = [
                CleansingConfig(
                    table_name=table_name,
                    column_name="a",
                    operation="standardize",
                    params={"trim": True},
                )
            ]

            with pytest.raises(ValueError, match="primary key"):
                cleanse_plan(writable, configs, store=_NullStore())
        finally:
            connection = get_connection(writable)
            try:
                connection.cursor().execute(f"DROP TABLE IF EXISTS {table_name}")
                connection.commit()
            finally:
                connection.close()
