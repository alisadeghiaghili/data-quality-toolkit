"""Grounded unit tests for ``dqt.sql.profiling`` (NEW-C slice 1).

Every expected value in this module is derived by hand from the literal
``INSERT`` statements in the fixture, or from closed-form arithmetic on those
literals. No expectation is obtained by running the profiler and asserting it
equals itself -- that would prove only self-consistency.

Before this module, ``profiling.py`` had no dedicated unit tests: it was
covered incidentally by the end-to-end pipeline integration test, which
asserts that profiling produced *something*, not that it produced the *right*
something. Unit 6 (``DQT-05``) takes a checksum of a table "before mutation"
and compares it after ``revert``; that proof is only worth anything if the
counts profiling reports are themselves known to be correct.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from dqt.common.models import ConnectionConfig
from dqt.sql.profiling import SqlProfiler
from dqt.sql.schema_discovery import discover_schema

# Five rows. Column ``x`` is NULL on id 2 and id 4, populated on 1, 3 and 5.
# Counted by hand from the statements below: row_count = 5, null_count = 2.
FIVE_ROWS_TWO_NULLS = """
    CREATE TABLE measurements (id INTEGER PRIMARY KEY, x INTEGER);
    INSERT INTO measurements (id, x) VALUES (1, 10);
    INSERT INTO measurements (id, x) VALUES (2, NULL);
    INSERT INTO measurements (id, x) VALUES (3, 30);
    INSERT INTO measurements (id, x) VALUES (4, NULL);
    INSERT INTO measurements (id, x) VALUES (5, 50);
"""

# A table that is created and never populated: zero rows, zero NULLs.
EMPTY_TABLE = """
    CREATE TABLE measurements (id INTEGER PRIMARY KEY, x INTEGER);
"""


def _profile(db_file: Path) -> list:
    """Discover and profile every table in *db_file*.

    Args:
        db_file: Path to a SQLite database file.

    Returns:
        The list of TableProfile objects the profiler produced.

    Example:
        profiles = _profile(Path("measurements.db"))
    """
    conn_cfg = ConnectionConfig(id="test", dsn=f"sqlite:///{db_file}")
    tables = discover_schema(conn_cfg)
    return SqlProfiler(conn_cfg).profile_tables(tables)


def test_row_and_null_counts_match_hand_seeded_fixture(
    make_sqlite_db: Callable[[str, str], Path],
) -> None:
    """Counts must match the literal INSERT list, not merely be self-consistent.

    Ground truth: the fixture contains five INSERT statements, so the table has
    five rows. Column ``x`` receives the literal NULL on ids 2 and 4, so it has
    exactly two NULLs. Both numbers are read off the SQL text above, not
    produced by the code under test.
    """
    profiles = _profile(make_sqlite_db("measurements.db", FIVE_ROWS_TWO_NULLS))

    assert len(profiles) == 1
    table = profiles[0]
    assert table.table_name == "measurements"
    assert table.row_count == 5

    column_x = next(c for c in table.columns if c.column_name == "x")
    assert column_x.null_count == 2
    assert column_x.row_count == 5

    # The primary key can never be NULL, so its count is a control: it proves
    # the NULL count is per-column and not a table-wide constant.
    column_id = next(c for c in table.columns if c.column_name == "id")
    assert column_id.null_count == 0


def test_completeness_score_formula(make_sqlite_db: Callable[[str, str], Path]) -> None:
    """Completeness is 1 - null_count/row_count, computed on the same fixture.

    Ground truth: 1.0 - 2/5 = 0.6, arithmetic on the hand-counted literals.
    The raw ``value`` carries the null count, and the metadata carries both
    operands, so a reader can re-derive the score without rerunning anything.
    """
    db_file = make_sqlite_db("measurements.db", FIVE_ROWS_TWO_NULLS)
    conn_cfg = ConnectionConfig(id="test", dsn=f"sqlite:///{db_file}")
    profiler = SqlProfiler(conn_cfg)
    profiles = profiler.profile_tables(discover_schema(conn_cfg))

    metrics = profiler.build_metrics(profiles, run_id="run-001")

    completeness_x = next(
        m for m in metrics if m.dimension == "completeness" and m.column_name == "x"
    )
    assert completeness_x.score == 0.6
    assert completeness_x.value == 2.0
    assert completeness_x.metadata["null_count"] == 2
    assert completeness_x.metadata["row_count"] == 5

    # The table-level row_count metric reports the count as its value and does
    # not pretend to be a quality score.
    row_count_metric = next(m for m in metrics if m.dimension == "row_count")
    assert row_count_metric.value == 5.0


def test_zero_row_table_is_not_a_division_by_zero(
    make_sqlite_db: Callable[[str, str], Path],
) -> None:
    """An empty table reports completeness 1.0 rather than raising or NaN.

    This is a boundary invariant, not a discovered behaviour: "how complete is
    nothing" is *defined* here to be vacuously complete, matching the explicit
    ``if row_count > 0`` guard in ``build_metrics``. The test exists to lock
    that choice so a later refactor cannot silently turn it into a
    ZeroDivisionError or a NaN score that would poison every aggregate built
    on top of it.
    """
    db_file = make_sqlite_db("empty.db", EMPTY_TABLE)
    conn_cfg = ConnectionConfig(id="test", dsn=f"sqlite:///{db_file}")
    profiler = SqlProfiler(conn_cfg)
    profiles = profiler.profile_tables(discover_schema(conn_cfg))

    assert profiles[0].row_count == 0

    metrics = profiler.build_metrics(profiles, run_id="run-001")
    completeness = [m for m in metrics if m.dimension == "completeness"]

    assert completeness, "an empty table must still yield per-column metrics"
    for metric in completeness:
        assert metric.score == 1.0
        assert metric.value == 0.0
