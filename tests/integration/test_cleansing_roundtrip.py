"""Apply and undo, against real servers (`GATE-03`).

The `v0.3` rung: a round-trip in which the data after `revert()` is identical
to the data before `cleanse_apply()`, for **both** cleansing operations that
change data, against **SQL Server first**, then PostgreSQL.

`tests/integration/test_cleansing_revert.py` already proves this on SQLite by
hashing the database file. That is the easy engine: one process, one file, no
network, and `rowid` available if all else fails. The claim DQT actually
makes is that cleansing is reversible on a *production* database, and until
this file existed nothing tested that.

**`deduplicate` is the operation worth the trouble.** `standardize` changes a
value and undoing it means writing the old one back. `deduplicate` *deletes
rows*, so undoing it means putting rows back that no longer exist — every
column of them, from a log written before they were gone. `NEW-M` already
showed how this breaks when row identity is wrong; this shows it working when
identity is a primary key, on engines where `rowid` does not exist at all.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from collections.abc import Iterator
from typing import Any

import pytest

from dqt.common.models import ConnectionConfig
from dqt.sql._connect import get_connection
from dqt.sql.cleansing import CleansingConfig, cleanse_apply, cleanse_plan, revert

#: SQL Server leads, per the reordered ladder in the roadmap.
ENGINES: tuple[tuple[str, str], ...] = (
    ("sqlserver", "DQT_SQLSERVER_TEST_DSN"),
    ("postgresql", "DQT_POSTGRES_TEST_DSN"),
)


class _MemoryStore:
    """The parts of a store cleansing needs, kept in memory.

    A real :class:`~dqt.common.storage.RunStore` would work, and would also
    put a second database between the test and what it is measuring. The
    round trip under test is the server's, so the store stays out of it.

    Example:
        store = _MemoryStore()
    """

    def __init__(self) -> None:
        """Start with no plan and no log.

        Example:
            store = _MemoryStore()
        """
        self.plans: dict[str, Any] = {}
        self.logs: dict[str, list[Any]] = {}

    def save_cleansing_plan(self, plan: Any) -> None:
        """Keep a plan under its id.

        Args:
            plan: The plan to keep.

        Returns:
            None.

        Example:
            store.save_cleansing_plan(plan)
        """
        self.plans[plan.plan_id] = plan

    def load_cleansing_plan(self, plan_id: str) -> Any:
        """Return a kept plan, or None.

        Args:
            plan_id: The plan to find.

        Returns:
            The plan, or None when there is none.

        Example:
            plan = store.load_cleansing_plan("plan-1")
        """
        return self.plans.get(plan_id)

    def mark_cleansing_plan_applied(self, plan_id: str, applied_at: Any) -> None:
        """Record that a plan was applied.

        Args:
            plan_id: The plan.
            applied_at: When it was applied.

        Returns:
            None.

        Example:
            store.mark_cleansing_plan_applied("plan-1", moment)
        """
        self.plans[plan_id].applied_at = applied_at

    def save_cleansing_log(self, plan_id: str, changes: Any, applied_at: Any) -> None:
        """Record what a plan changed, in the shape a real store returns.

        ``RunStore`` persists to SQLite and reads back plain dicts, so a
        stand-in that kept the ``CleansingLog`` objects would let ``revert``
        pass here and fail against the real thing -- a test that makes the
        code under test easier than production is worse than no test.

        Args:
            plan_id: The plan.
            changes: The log entries.
            applied_at: When it was applied.

        Returns:
            None.

        Example:
            store.save_cleansing_log("plan-1", changes, moment)
        """
        self.logs[plan_id] = [
            {
                "operation": change.operation,
                "schema_name": change.schema_name,
                "table_name": change.table_name,
                "column_name": change.column_name,
                "row_key": change.row_key,
                "before_value": change.before_value,
                "after_value": change.after_value,
            }
            for change in changes
        ]

    def load_cleansing_log(self, plan_id: str) -> list[Any]:
        """Return a plan's log.

        Args:
            plan_id: The plan.

        Returns:
            Its log entries.

        Example:
            entries = store.load_cleansing_log("plan-1")
        """
        return self.logs.get(plan_id, [])


def _dsn(engine: str) -> str:
    """Return the DSN for *engine*, or skip.

    Args:
        engine: Dialect name.

    Returns:
        The DSN.

    Example:
        dsn = _dsn("sqlserver")
    """
    variable = dict(ENGINES)[engine]
    dsn = os.environ.get(variable)
    if not dsn:
        pytest.skip(f"{variable} is not set; CI sets it against a service container.")
    return dsn


def _writable(engine: str) -> ConnectionConfig:
    """Return a writable config for *engine*.

    Args:
        engine: Dialect name.

    Returns:
        A ConnectionConfig with read_only disabled.

    Example:
        config = _writable("sqlserver")
    """
    return ConnectionConfig(id=engine, dsn=_dsn(engine), read_only=False)


def _execute(engine: str, *statements: str) -> None:
    """Run statements and commit.

    Args:
        engine: Dialect name.
        *statements: SQL to run in order.

    Returns:
        None.

    Example:
        _execute("sqlserver", "DROP TABLE t")
    """
    connection = get_connection(_writable(engine))
    try:
        cursor = connection.cursor()
        for statement in statements:
            cursor.execute(statement)
        connection.commit()
    finally:
        connection.close()


def _fingerprint(engine: str, table: str) -> str:
    """Hash every column of every row, in key order.

    ``deduplicate`` removes whole rows, so a fingerprint over one column
    could not tell a restored row from a missing one. Ordered by the key,
    because an unordered read makes the hash depend on the planner.

    Args:
        engine: Dialect name.
        table: Table to fingerprint.

    Returns:
        A hex digest.

    Example:
        digest = _fingerprint("sqlserver", "dqt_rt_ab12")
    """
    connection = get_connection(_writable(engine))
    try:
        cursor = connection.cursor()
        cursor.execute(f"SELECT id, email, city FROM {table} ORDER BY id")
        rows = [tuple(row) for row in cursor.fetchall()]
    finally:
        connection.close()
    return hashlib.sha256(repr(rows).encode("utf-8")).hexdigest()


@pytest.fixture(params=[engine for engine, _ in ENGINES])
def round_trip_table(request: pytest.FixtureRequest) -> Iterator[tuple[str, str]]:
    """Create a seeded table on each engine in turn, then drop it.

    Four rows. ``email`` has a trailing space on one row, so ``standardize``
    has something to change; ``city`` repeats, so ``deduplicate`` has
    something to delete.

    Args:
        request: Supplies the engine name.

    Yields:
        ``(engine, table_name)``.

    Example:
        def test_something(round_trip_table):
            engine, table = round_trip_table
    """
    engine = str(request.param)
    _dsn(engine)

    table = f"dqt_rt_{uuid.uuid4().hex[:8]}"
    text_type = "NVARCHAR(200)" if engine == "sqlserver" else "VARCHAR(200)"
    _execute(
        engine,
        f"CREATE TABLE {table} ("
        f"  id INT NOT NULL PRIMARY KEY,"
        f"  email {text_type} NULL,"
        f"  city {text_type} NULL"
        f")",
        f"INSERT INTO {table} (id, email, city) VALUES "
        "(1, 'a@b.com ', 'Tehran'), "
        "(2, 'c@d.com', 'Tehran'), "
        "(3, 'e@f.com', 'Shiraz'), "
        "(4, NULL, 'Shiraz')",
    )
    yield engine, table
    _execute(engine, f"DROP TABLE {table}")


def _round_trip(engine: str, table: str, config: CleansingConfig) -> tuple[str, str, str]:
    """Fingerprint before, after apply, and after revert.

    Args:
        engine: Dialect name.
        table: Table to cleanse.
        config: The operation to run.

    Returns:
        The three digests, in order.

    Example:
        before, applied, reverted = _round_trip(engine, table, config)
    """
    connection_config = _writable(engine)
    store = _MemoryStore()

    before = _fingerprint(engine, table)
    plan = cleanse_plan(connection_config, [config], store=store)
    cleanse_apply(plan.plan_id, connection_config, store=store)
    applied = _fingerprint(engine, table)
    revert(plan.plan_id, connection_config, store=store)
    reverted = _fingerprint(engine, table)
    return before, applied, reverted


class TestStandardizeRoundTrips:
    """Change a value, put the old one back."""

    def test_the_data_is_identical_before_and_after(
        self, round_trip_table: tuple[str, str]
    ) -> None:
        """And it actually changed in between.

        The middle fingerprint is what stops this passing vacuously. A plan
        that found nothing to do would leave all three identical and satisfy
        a naive before-equals-after assertion.
        """
        engine, table = round_trip_table

        before, applied, reverted = _round_trip(
            engine,
            table,
            CleansingConfig(
                table_name=table,
                column_name="email",
                operation="standardize",
                params={"trim": True},
            ),
        )

        assert applied != before, "the cleanse changed nothing, so the revert proved nothing"
        assert reverted == before


class TestDeduplicateRoundTrips:
    """Delete rows, put them back -- every column of them."""

    def test_the_data_is_identical_before_and_after(
        self, round_trip_table: tuple[str, str]
    ) -> None:
        """The operation that makes this rung worth a gate.

        ``standardize`` undoes by writing an old value back into a row that
        still exists. ``deduplicate`` has to reinsert rows that are gone,
        with every column reconstructed from a log written before they were
        deleted -- and on engines where ``rowid`` does not exist, addressed
        by a primary key that `NEW-M` had to introduce for exactly this.
        """
        engine, table = round_trip_table

        before, applied, reverted = _round_trip(
            engine,
            table,
            CleansingConfig(
                table_name=table,
                column_name=None,
                operation="deduplicate",
                params={"key_columns": ["city"], "keep": "first"},
            ),
        )

        assert applied != before, "nothing was deleted, so the revert proved nothing"
        assert reverted == before

    def test_the_rows_come_back_and_not_just_the_count(
        self, round_trip_table: tuple[str, str]
    ) -> None:
        """A row count restored with the wrong values is not a restore.

        The fingerprint above already covers this, but only implicitly. This
        says it in the terms a reader would check by hand: two cities were
        duplicated, two rows were deleted, and the four original rows are
        back with their original emails.
        """
        engine, table = round_trip_table
        connection_config = _writable(engine)
        store = _MemoryStore()

        plan = cleanse_plan(
            connection_config,
            [
                CleansingConfig(
                    table_name=table,
                    column_name=None,
                    operation="deduplicate",
                    params={"key_columns": ["city"], "keep": "first"},
                )
            ],
            store=store,
        )
        cleanse_apply(plan.plan_id, connection_config, store=store)

        connection = get_connection(connection_config)
        try:
            cursor = connection.cursor()
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            after_apply = int(cursor.fetchone()[0])
        finally:
            connection.close()

        revert(plan.plan_id, connection_config, store=store)

        connection = get_connection(connection_config)
        try:
            cursor = connection.cursor()
            cursor.execute(f"SELECT id, email, city FROM {table} ORDER BY id")
            restored = [tuple(row) for row in cursor.fetchall()]
        finally:
            connection.close()

        assert after_apply == 2, "two duplicate rows should have been deleted"
        assert restored == [
            (1, "a@b.com ", "Tehran"),
            (2, "c@d.com", "Tehran"),
            (3, "e@f.com", "Shiraz"),
            (4, None, "Shiraz"),
        ]
