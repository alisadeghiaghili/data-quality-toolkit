"""Schema-level `CHECK` constraints on the run store (NEW-A).

Every test here writes **direct SQL**, bypassing :class:`RunStore`'s own
methods. That is the point. Validation living only in Python is validation
that a later code path, a migration script, or a DBA with a sqlite3 prompt can
walk straight past. Putting the enforcement in the schema makes the store's
contents true by construction rather than by convention.

Each test reproduces a defect that exists today: before this unit, every
insert below succeeds in silence.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from dqt.common.storage import RunStore


@pytest.fixture
def store_connection(tmp_path: Path) -> sqlite3.Connection:
    """Create the schema, then hand back a raw connection to it.

    Args:
        tmp_path: pytest temporary directory.

    Returns:
        An open sqlite3 connection to a store with the schema applied.

    Example:
        store_connection.execute("INSERT INTO runs ...")
    """
    db = tmp_path / "runs.db"
    RunStore(db_path=db).init_schema()
    return sqlite3.connect(str(db))


def _seed_run(connection: sqlite3.Connection, status: str = "success") -> None:
    """Insert one parent run so foreign keys resolve.

    Args:
        connection: Open connection to the store.
        status: Run status to write.

    Returns:
        None.

    Example:
        _seed_run(store_connection)
    """
    connection.execute(
        "INSERT INTO runs (run_id, connection_id, started_at, ended_at, status) "
        "VALUES ('run-001', 'conn-a', '2026-09-05T00:00:00', '2026-09-05T00:01:00', ?)",
        (status,),
    )


def test_run_metrics_rejects_a_dimension_outside_the_closed_set(
    store_connection: sqlite3.Connection,
) -> None:
    """``dimension='banana'`` cannot reach the table.

    ``docs/CONVENTIONS-DQT.md`` §0.1 calls the six-value list closed. Until
    the database says so too, "closed" is a sentence in a document.
    """
    _seed_run(store_connection)

    with pytest.raises(sqlite3.IntegrityError):
        store_connection.execute(
            "INSERT INTO run_metrics (run_id, dimension, score) VALUES ('run-001', 'banana', 1.0)"
        )


def test_run_metrics_accepts_a_null_dimension_with_a_metric_name(
    store_connection: sqlite3.Connection,
) -> None:
    """A raw measurement is storable without pretending to be a dimension.

    This is the other half of the constraint. A `CHECK` that only allowed the
    six dimensions would force ``row_count`` back into the field this unit is
    emptying.
    """
    _seed_run(store_connection)

    store_connection.execute(
        "INSERT INTO run_metrics (run_id, dimension, metric_name, score) "
        "VALUES ('run-001', NULL, 'row_count', 1.0)"
    )

    assert store_connection.execute("SELECT COUNT(*) FROM run_metrics").fetchone()[0] == 1


def test_run_metrics_rejects_a_row_that_is_neither(
    store_connection: sqlite3.Connection,
) -> None:
    """A row with no dimension and no metric name is meaningless.

    The model rejects this shape; the schema has to agree, or direct SQL
    becomes a way to store a metric that no consumer can interpret.
    """
    _seed_run(store_connection)

    with pytest.raises(sqlite3.IntegrityError):
        store_connection.execute(
            "INSERT INTO run_metrics (run_id, dimension, metric_name, score) "
            "VALUES ('run-001', NULL, NULL, 1.0)"
        )


def test_run_issues_rejects_an_unknown_dimension(
    store_connection: sqlite3.Connection,
) -> None:
    """Issues carry real dimensions only; there is no measurement case here.

    Unlike a metric, an issue is always a judgement, so ``dimension`` stays
    ``NOT NULL`` on this table.
    """
    _seed_run(store_connection)

    with pytest.raises(sqlite3.IntegrityError):
        store_connection.execute(
            "INSERT INTO run_issues (issue_id, run_id, dimension, severity, message) "
            "VALUES ('i1', 'run-001', 'banana', 'error', 'x')"
        )


def test_run_issues_rejects_an_unknown_severity(
    store_connection: sqlite3.Connection,
) -> None:
    """Severity is a closed four-value ladder.

    A severity outside it silently breaks every filter and ordering built on
    it -- the UI's severity filter, the report's badges, and any future
    exit-code contract that keys on "was anything critical".
    """
    _seed_run(store_connection)

    with pytest.raises(sqlite3.IntegrityError):
        store_connection.execute(
            "INSERT INTO run_issues (issue_id, run_id, dimension, severity, message) "
            "VALUES ('i1', 'run-001', 'completeness', 'catastrophic', 'x')"
        )


def test_runs_rejects_an_unknown_status(store_connection: sqlite3.Connection) -> None:
    """Run status is exactly ``success``, ``failed`` or ``partial``.

    The data model names those three. A fourth value would make "did this run
    succeed" unanswerable by query, which is the one question the runs table
    exists to answer.
    """
    with pytest.raises(sqlite3.IntegrityError):
        _seed_run(store_connection, status="mostly-fine")


def test_the_natural_key_still_prevents_duplicate_metrics(
    store_connection: sqlite3.Connection,
) -> None:
    """Making ``dimension`` nullable must not open a duplicate-row hole.

    The unique index covers the natural key, and SQLite treats NULLs as
    distinct from one another. Without folding ``metric_name`` into the index
    and coalescing the nulls, two identical ``row_count`` metrics for one
    table would both be stored -- reintroducing the idempotency defect Phase 0
    fixed for a different column set.
    """
    _seed_run(store_connection)
    insert = (
        "INSERT INTO run_metrics (run_id, table_name, dimension, metric_name, score) "
        "VALUES ('run-001', 'customers', NULL, 'row_count', 1.0)"
    )
    store_connection.execute(insert)

    with pytest.raises(sqlite3.IntegrityError):
        store_connection.execute(insert)
