"""Reversible, audited cleansing: plan / apply / revert (DQT-05).

`cleansing.py`'s module docstring has called its primitives "Reversible,
auditable" since they were written, and `pipeline.py` repeated the claim
verbatim. Neither was true: `CleansingLog` objects existed only in memory,
`grep -c cleansing src/dqt/common/storage.py` returned 0, and there was no
`revert` anywhere. Drop the return value of `apply_cleansing()` and the
before-values needed to undo anything were gone permanently.

`docs/CONVENTIONS-DQT.md` §1 S4 is explicit that a log a human could use to
reconstruct a change by hand is an **audit trail**, not reversibility, and
that the two must not be conflated -- which is exactly what that docstring
did.

The round-trip proof below is a **checksum**, not a row count.
`docs/HONESTY-GATE.md` says why in as many words: row counts can match while
values changed.
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Callable
from pathlib import Path

import pytest

from dqt.common.models import ConnectionConfig
from dqt.common.storage import RunStore
from dqt.exceptions import ReadOnlyViolationError
from dqt.sql.cleansing import (
    CleansingConfig,
    cleanse_apply,
    cleanse_plan,
    revert,
)

# Emails with inconsistent whitespace and case. Hand-counted: four rows, three
# of which change under a trim+lowercase standardisation; row 3 is already
# canonical and must be left alone.
CUSTOMERS = """
    CREATE TABLE customers (id INTEGER PRIMARY KEY, email TEXT);
    INSERT INTO customers (id, email) VALUES (1, '  Alice@Example.COM ');
    INSERT INTO customers (id, email) VALUES (2, 'BOB@example.com');
    INSERT INTO customers (id, email) VALUES (3, 'carol@example.com');
    INSERT INTO customers (id, email) VALUES (4, ' Dave@Example.com');
"""


def _checksum(db_file: Path) -> str:
    """Hash every value in ``customers``, ordered, so any change shows.

    A row count would not: `HONESTY-GATE.md` notes that counts can match
    while values changed, which is precisely the failure a revert test must
    be able to see.

    Args:
        db_file: Path to the SQLite database.

    Returns:
        A hex digest over the table's contents.

    Example:
        before = _checksum(db_file)
    """
    connection = sqlite3.connect(str(db_file))
    try:
        rows = connection.execute("SELECT id, email FROM customers ORDER BY id").fetchall()
    finally:
        connection.close()
    digest = hashlib.sha256()
    for row in rows:
        digest.update(repr(row).encode("utf-8"))
    return digest.hexdigest()


@pytest.fixture
def scenario(
    make_sqlite_db: Callable[[str, str], Path], tmp_path: Path
) -> tuple[ConnectionConfig, RunStore, list[CleansingConfig], Path]:
    """Seed a database, a store, and a standardisation config.

    Args:
        make_sqlite_db: Factory fixture building a SQLite file.
        tmp_path: pytest temporary directory.

    Returns:
        The writable connection config, the run store, the cleansing configs,
        and the path to the seeded database.

    Example:
        config, store, configs, db_file = scenario
    """
    db_file = make_sqlite_db("customers.db", CUSTOMERS)
    store = RunStore(db_path=tmp_path / "runs.db")
    store.init_schema()
    config = ConnectionConfig(id="t", dsn=f"sqlite:///{db_file}", read_only=False)
    configs = [
        CleansingConfig(
            table_name="customers",
            column_name="email",
            operation="standardize",
            params={"trim": True, "case": "lower"},
        )
    ]
    return config, store, configs, db_file


def test_planning_mutates_nothing(
    scenario: tuple[ConnectionConfig, RunStore, list[CleansingConfig], Path],
) -> None:
    """``cleanse_plan`` computes what would change and changes nothing.

    This is the property that lets a plan be produced against production data
    without a decision having been made yet. If planning mutated, the
    plan/apply split would be theatre.
    """
    config, store, configs, db_file = scenario
    before = _checksum(db_file)

    plan = cleanse_plan(config, configs, store=store)

    assert _checksum(db_file) == before
    assert plan.plan_id
    assert plan.applied_at is None


def test_a_plan_is_durable_and_addressable(
    scenario: tuple[ConnectionConfig, RunStore, list[CleansingConfig], Path],
) -> None:
    """The plan outlives the process that made it.

    This is what Q2 bought over ``--dry-run``: the old preview was terminal
    output discarded on exit, so what a reviewer approved and what was later
    executed were connected only by hope. A stored, addressable plan makes
    them the same object.
    """
    config, store, configs, _ = scenario
    plan = cleanse_plan(config, configs, store=store)

    reloaded = store.load_cleansing_plan(plan.plan_id)

    assert reloaded is not None
    assert reloaded.plan_id == plan.plan_id
    assert reloaded.applied_at is None


def test_apply_then_revert_restores_the_exact_bytes(
    scenario: tuple[ConnectionConfig, RunStore, list[CleansingConfig], Path],
) -> None:
    """The round trip is byte-identical, which is what "reversible" has to mean.

    Ground truth: three of the four seeded emails change under trim+lowercase
    and one is already canonical, so applying must alter the checksum and
    reverting must restore it exactly. Comparing checksums rather than counts
    is deliberate -- a revert that wrote back the right number of rows with
    the wrong values would pass a count assertion.
    """
    config, store, configs, db_file = scenario
    before = _checksum(db_file)

    plan = cleanse_plan(config, configs, store=store)
    applied = cleanse_apply(plan.plan_id, config, store=store)

    assert applied.total_changes == 3
    assert _checksum(db_file) != before

    revert(plan.plan_id, config, store=store)

    assert _checksum(db_file) == before


def test_applying_a_plan_twice_is_refused(
    scenario: tuple[ConnectionConfig, RunStore, list[CleansingConfig], Path],
) -> None:
    """A plan is a one-shot authorisation, not a reusable command.

    Re-running it would write a second log for the same intent, and the two
    logs would then disagree about what the original values were -- making
    the revert chain ambiguous, which is worse than not having one.
    """
    config, store, configs, _ = scenario
    plan = cleanse_plan(config, configs, store=store)
    cleanse_apply(plan.plan_id, config, store=store)

    with pytest.raises(ValueError, match="already applied"):
        cleanse_apply(plan.plan_id, config, store=store)


def test_apply_refuses_when_the_data_moved_under_the_plan(
    scenario: tuple[ConnectionConfig, RunStore, list[CleansingConfig], Path],
) -> None:
    """A plan approved against one state must not execute against another.

    This is the risk the plan/apply split introduces and has to answer for:
    time passes between the two calls. Applying a stale plan would write
    before-values that no longer describe what was there, so the log would
    lie and the revert built on it would corrupt rather than restore.
    """
    config, store, configs, db_file = scenario
    plan = cleanse_plan(config, configs, store=store)

    connection = sqlite3.connect(str(db_file))
    try:
        connection.execute("UPDATE customers SET email = 'changed@example.com' WHERE id = 1")
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(ValueError, match="changed since|drift"):
        cleanse_apply(plan.plan_id, config, store=store)


def test_reverting_an_unapplied_plan_is_refused(
    scenario: tuple[ConnectionConfig, RunStore, list[CleansingConfig], Path],
) -> None:
    """There is nothing to undo, and pretending otherwise hides a mistake."""
    config, store, configs, _ = scenario
    plan = cleanse_plan(config, configs, store=store)

    with pytest.raises(ValueError, match="not been applied"):
        revert(plan.plan_id, config, store=store)


def test_read_only_still_blocks_the_mutating_step(
    scenario: tuple[ConnectionConfig, RunStore, list[CleansingConfig], Path],
) -> None:
    """``read_only`` gates apply, not plan.

    Planning is a read, so it must work against a read-only connection --
    that is the normal case for producing a plan from production. Applying is
    the write, and `DQT-03`'s guard has to survive the split intact.
    """
    config, store, configs, db_file = scenario
    read_only = ConnectionConfig(id="t", dsn=f"sqlite:///{db_file}", read_only=True)

    plan = cleanse_plan(read_only, configs, store=store)

    with pytest.raises(ReadOnlyViolationError):
        cleanse_apply(plan.plan_id, read_only, store=store)


def test_the_log_records_before_and_after_for_every_change(
    scenario: tuple[ConnectionConfig, RunStore, list[CleansingConfig], Path],
) -> None:
    """The audit trail is per row, and it is what revert replays.

    Ground truth: three rows change, so three log entries exist, and each
    holds the value that was there before. Without the before-value the log
    is an audit trail only -- the distinction §1 S4 insists on.
    """
    config, store, configs, _ = scenario
    plan = cleanse_plan(config, configs, store=store)
    cleanse_apply(plan.plan_id, config, store=store)

    entries = store.load_cleansing_log(plan.plan_id)

    assert len(entries) == 3
    before_values = {entry["before_value"] for entry in entries}
    assert "  Alice@Example.COM " in before_values
    assert all(entry["after_value"] is not None for entry in entries)
