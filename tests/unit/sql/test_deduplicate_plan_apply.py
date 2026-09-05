"""Deduplicate through the supported API (`NEW-U`).

`DQT-05` replaced `apply_cleansing` with `cleanse_plan` / `cleanse_apply` /
`revert`, and deprecated the old one. `GATE-03` asked for a round trip on a
real server and found that this path has **never worked for
`deduplicate`** — on any dialect, including SQLite. Three separate breaks,
each of which alone is fatal:

1. **The log cannot be stored.** `deduplicate` records the whole deleted row
   as `before_value`, which is a dict, and `RunStore.save_cleansing_log`
   hands it straight to `sqlite3`. A dict is not a storable type.
2. **Apply issues the wrong statement.** `cleanse_apply` replays every change
   as ``UPDATE <table> SET <column_name> = <after_value>``. For a deletion
   `column_name` is `None`, so it builds ``SET "None" = ?``.
3. **Revert issues the wrong statement.** Undoing a deletion means putting
   the row back; `revert` also issues an `UPDATE`, against a row that is no
   longer there.

Only the deprecated `apply_cleansing` ever handled `deduplicate`, because it
performs the delete inline and returns the log in memory — so nothing had to
survive a round trip through storage.

That is why this went unnoticed: `docs/API-STABILITY.md` says the replacement
must be "at least as capable" *before* the old one is deprecated, and for
this operation it was not. The deprecation was written against an intention.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path

import pytest

from dqt.common.models import ConnectionConfig
from dqt.common.storage import RunStore
from dqt.sql.cleansing import CleansingConfig, cleanse_apply, cleanse_plan, revert

SEEDED = """
    CREATE TABLE people (id INTEGER PRIMARY KEY, email TEXT, city TEXT);
    INSERT INTO people (id, email, city) VALUES
        (1, 'a@b.com', 'Tehran'),
        (2, 'c@d.com', 'Tehran'),
        (3, 'e@f.com', 'Shiraz'),
        (4, NULL,      'Shiraz');
"""


@pytest.fixture
def cleansing(
    make_sqlite_db: Callable[[str, str], Path], tmp_path: Path
) -> tuple[ConnectionConfig, RunStore, Path]:
    """Seed a database and a store.

    Args:
        make_sqlite_db: Factory fixture building a SQLite file.
        tmp_path: Directory for the run store.

    Returns:
        ``(connection_config, store, database_path)``.

    Example:
        config, store, path = cleansing
    """
    database = make_sqlite_db("dedupe.db", SEEDED)
    store = RunStore(db_path=tmp_path / "runs.db")
    store.init_schema()
    return ConnectionConfig(id="d", dsn=f"sqlite:///{database}", read_only=False), store, database


def _rows(database: Path) -> list[tuple[object, ...]]:
    """Read the table back, in key order.

    Args:
        database: The SQLite file.

    Returns:
        Every row as a tuple.

    Example:
        assert len(_rows(database)) == 4
    """
    with sqlite3.connect(database) as connection:
        return [
            tuple(row)
            for row in connection.execute("SELECT id, email, city FROM people ORDER BY id")
        ]


def _config() -> CleansingConfig:
    """Return a deduplicate config keyed on ``city``.

    Returns:
        A CleansingConfig.

    Example:
        config = _config()
    """
    return CleansingConfig(
        table_name="people",
        column_name=None,
        operation="deduplicate",
        params={"key_columns": ["city"], "keep": "first"},
    )


class TestDeduplicateSurvivesThePlanApplyPath:
    """The supported API has to do what the deprecated one already did."""

    def test_a_plan_can_be_applied(
        self, cleansing: tuple[ConnectionConfig, RunStore, Path]
    ) -> None:
        """Two cities repeat, so rows 2 and 4 go, leaving 1 and 3.

        Hand-counted from the seeded literal.
        """
        config, store, database = cleansing

        plan = cleanse_plan(config, [_config()], store=store)
        cleanse_apply(plan.plan_id, config, store=store)

        assert [row[0] for row in _rows(database)] == [1, 3]

    def test_the_deleted_rows_come_back_exactly(
        self, cleansing: tuple[ConnectionConfig, RunStore, Path]
    ) -> None:
        """Every column, including the NULL that a naive restore drops.

        Row 4's ``email`` is NULL. A revert that reinserts only the columns
        it found values for would silently restore three columns out of
        three and leave the fourth row's NULL as a default -- which on a
        column with a default is a different value, not a missing one.
        """
        config, store, database = cleansing
        before = _rows(database)

        plan = cleanse_plan(config, [_config()], store=store)
        cleanse_apply(plan.plan_id, config, store=store)
        revert(plan.plan_id, config, store=store)

        assert _rows(database) == before

    def test_the_log_survives_storage(
        self, cleansing: tuple[ConnectionConfig, RunStore, Path]
    ) -> None:
        """The whole deleted row is a dict, and has to come back as one.

        ``revert`` reads the log rather than the plan, so a log that
        round-trips as a string is a log that cannot restore anything -- and
        it fails at undo time, long after the rows are gone.
        """
        config, store, _ = cleansing

        plan = cleanse_plan(config, [_config()], store=store)
        cleanse_apply(plan.plan_id, config, store=store)
        entries = store.load_cleansing_log(plan.plan_id)

        assert len(entries) == 2
        assert isinstance(entries[0]["before_value"], dict)
        assert entries[0]["before_value"]["city"] in {"Tehran", "Shiraz"}


class TestStandardizeStillWorks:
    """The fix must not trade one operation for another."""

    def test_a_value_change_still_round_trips(
        self, cleansing: tuple[ConnectionConfig, RunStore, Path]
    ) -> None:
        """A string before_value has to keep behaving like a string.

        Encoding the log to survive a dict is exactly the change that would
        turn every other before_value into a quoted string on the way back.
        """
        config, store, database = cleansing
        before = _rows(database)

        plan = cleanse_plan(
            config,
            [
                CleansingConfig(
                    table_name="people",
                    column_name="email",
                    operation="standardize",
                    params={"case": "upper"},
                )
            ],
            store=store,
        )
        cleanse_apply(plan.plan_id, config, store=store)
        applied = _rows(database)
        revert(plan.plan_id, config, store=store)

        assert applied != before, "the cleanse changed nothing, so the revert proved nothing"
        assert _rows(database) == before
