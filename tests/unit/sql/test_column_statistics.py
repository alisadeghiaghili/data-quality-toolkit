"""Column statistics: min, max, mean and distinct (`F1`).

`dqt_competitors.md` §1 F1 asks for column statistics and `1.1.0` produced
two: a NULL count and a row count. This adds the rest.

**It is one scan, and that is the constraint the design answers to.**
`AGENTS.md` "Performance rules" requires many column statistics in one
aggregate query per table, not one query per statistic per column. Four
statistics across a hundred-column table is four hundred aggregate
expressions in a single `SELECT`, not four hundred scans. There is a test
below that counts the queries, because this is the row where a plausible
implementation is a hundredfold slower and nothing about the returned
numbers would say so.

**Type gating is correctness, not tidiness.** `AVG` over a text column is
not a harmless no-op: PostgreSQL raises, and SQLite silently returns `0.0`,
which is worse -- a profile that reports the mean of a name column as zero
is a wrong answer rather than a missing one. So the profiler asks the
dialect what a type supports before it asks the database for it.

**Which types support what is genuinely per-engine.** ``TEXT`` is SQLite's
ordinary string type and is fine under `MIN`; on SQL Server ``text`` is the
deprecated LOB type and `MIN` over it is an error. The same spelling means
different things, which is why this lives behind the dialect rather than in
a shared table of type names.

**Distinct counting is the expensive one.** ``COUNT(DISTINCT ...)`` must
hold every distinct value it has seen, so on a wide table it is the one
statistic here that can cost real memory on the server. It stays on by
default -- a profile without cardinality is not much of a profile, and this
is already a deliberate full scan -- but it can be turned off, and it can be
estimated where the dialect offers an estimator. An estimate and an exact
count are different claims, so the profile records which one it is.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from dqt.common.models import ConnectionConfig, ProfilingConfig
from dqt.sql.dialects import get_dialect_by_name
from dqt.sql.profiling import SqlProfiler
from dqt.sql.schema_discovery import discover_schema

# Four rows, one of them all-NULL. Every expected value below is derived from
# this literal by hand, never by running the profiler.
SEEDED = """
    CREATE TABLE people (
        id INTEGER,
        score REAL,
        name TEXT,
        joined TEXT
    );
    INSERT INTO people (id, score, name, joined) VALUES
        (1, 10.0, 'ali',  '2026-01-01'),
        (2, 20.0, 'sara', '2026-02-01'),
        (3, 30.0, 'ali',  '2026-03-01'),
        (4, NULL, NULL,   NULL);
"""


def _recorded_selects(db_file: Path) -> list[str]:
    """Profile *db_file* and return every SELECT the profiler issued.

    The count is taken from SQLite itself, through
    ``Connection.set_trace_callback``, which reports every statement the
    engine actually runs. That keeps the measurement outside the code under
    test twice over: DQT cannot satisfy it by reporting a number it chose,
    and the test cannot miss a query issued by a route it did not think to
    patch.

    ``sqlite3.Connection`` is immutable from Python 3.13, so replacing its
    ``execute`` method -- the obvious approach, and the first one tried --
    raises ``TypeError``. The trace callback is the supported seam and is a
    better measurement regardless.

    Args:
        db_file: The SQLite file to profile.

    Returns:
        The SELECT statements, in the order they were executed.

    Example:
        assert len(_recorded_selects(path)) == 1
    """
    from dqt.sql import profiling as profiling_module

    config = ConnectionConfig(id="s", dsn=f"sqlite:///{db_file}")
    tables = discover_schema(config)

    statements: list[str] = []
    real_get_connection = profiling_module.get_connection

    def traced(*args: object, **kwargs: object) -> object:
        connection = real_get_connection(*args, **kwargs)  # type: ignore[arg-type]
        connection.set_trace_callback(statements.append)
        return connection

    profiling_module.get_connection = traced  # type: ignore[assignment]
    try:
        SqlProfiler(config).profile_tables(tables)
    finally:
        profiling_module.get_connection = real_get_connection  # type: ignore[assignment]

    return [s for s in statements if s.strip().upper().startswith("SELECT")]


@pytest.fixture
def profile_columns(make_sqlite_db: Callable[[str, str], Path]) -> Callable[..., object]:
    """Profile the seeded table and return its columns by name.

    Args:
        make_sqlite_db: Factory fixture building a SQLite file.

    Returns:
        A callable taking an optional ProfilingConfig and returning a dict of
        column name to :class:`~dqt.sql.profiling.ColumnProfile`.

    Example:
        columns = profile_columns()
        assert columns["id"].min_value == 1
    """
    counter = {"n": 0}

    def _run(profiling: ProfilingConfig | None = None, sql: str = SEEDED) -> object:
        counter["n"] += 1
        db_file = make_sqlite_db(f"stats{counter['n']}.db", sql)
        config = ConnectionConfig(id="s", dsn=f"sqlite:///{db_file}")
        tables = discover_schema(config)
        profile = SqlProfiler(config, profiling=profiling).profile_tables(tables)[0]
        return {column.column_name: column for column in profile.columns}

    return _run


class TestNumericColumnsGetEveryStatistic:
    """The case the word "profiling" is usually taken to mean."""

    def test_min_and_max_come_from_the_values_present(
        self, profile_columns: Callable[..., object]
    ) -> None:
        """``id`` holds 1, 2, 3, 4 -- read off the INSERT, not the code."""
        column = profile_columns()["id"]  # type: ignore[index]

        assert column.min_value == 1
        assert column.max_value == 4

    def test_the_mean_ignores_nulls_rather_than_counting_them_as_zero(
        self, profile_columns: Callable[..., object]
    ) -> None:
        """``score`` is 10, 20, 30 and one NULL, so the mean is 20, not 15.

        This is the assertion that distinguishes a mean from a sum over the
        row count, and it is the mistake a hand-rolled implementation makes.
        SQL's ``AVG`` already excludes NULLs; the test pins that DQT does not
        undo it by dividing by ``row_count``.
        """
        column = profile_columns()["score"]  # type: ignore[index]

        assert column.mean_value == pytest.approx(20.0)

    def test_the_distinct_count_excludes_nulls(
        self, profile_columns: Callable[..., object]
    ) -> None:
        """``score`` has three values and one NULL, so three distinct.

        NULL is not a value, and counting it would make "distinct" disagree
        with the null count already reported beside it.
        """
        column = profile_columns()["score"]  # type: ignore[index]

        assert column.distinct_count == 3

    def test_repeated_values_count_once(self, profile_columns: Callable[..., object]) -> None:
        """``name`` is 'ali', 'sara', 'ali', NULL -- two distinct.

        The duplicate is what makes this test say something the null count
        does not already say.
        """
        column = profile_columns()["name"]  # type: ignore[index]

        assert column.distinct_count == 2


class TestNonNumericColumnsGetWhatTheirTypeSupports:
    """A statistic that cannot mean anything must be absent, not wrong."""

    def test_text_columns_are_ordered_lexicographically(
        self, profile_columns: Callable[..., object]
    ) -> None:
        """'ali' < 'sara', and both are useful to a DBA eyeballing a column."""
        column = profile_columns()["name"]  # type: ignore[index]

        assert column.min_value == "ali"
        assert column.max_value == "sara"

    def test_a_text_column_has_no_mean(self, profile_columns: Callable[..., object]) -> None:
        """The point of the type gate.

        SQLite answers ``AVG(name)`` with ``0.0`` rather than refusing. A
        profile reporting the mean of a name column as zero is a wrong
        answer, and wrong is worse than absent -- a reader has no way to tell
        it from a column that genuinely averages zero.
        """
        column = profile_columns()["name"]  # type: ignore[index]

        assert column.mean_value is None

    def test_dates_stored_as_text_still_get_bounds(
        self, profile_columns: Callable[..., object]
    ) -> None:
        """ "When does this table start and end" is a real DBA question.

        ISO-8601 sorts correctly as text, which is why the fixture stores it
        that way -- the answer is useful even though SQLite has no date type.
        """
        column = profile_columns()["joined"]  # type: ignore[index]

        assert column.min_value == "2026-01-01"
        assert column.max_value == "2026-03-01"


class TestColumnsWithNothingInThem:
    """Empty and all-NULL are different, and neither may crash."""

    def test_an_all_null_column_reports_absent_bounds_and_zero_distinct(
        self,
        profile_columns: Callable[..., object],
    ) -> None:
        """Absent bounds, but a *known* distinct count of zero.

        ``MIN`` over no values is NULL, which is honestly "unknown". The
        distinct count is not unknown -- it is zero, and saying so is more
        useful than saying nothing.
        """
        sql = """
            CREATE TABLE people (id INTEGER, name TEXT);
            INSERT INTO people (id, name) VALUES (1, NULL), (2, NULL);
        """
        column = profile_columns(sql=sql)["name"]  # type: ignore[index,call-arg]

        assert column.min_value is None
        assert column.max_value is None
        assert column.distinct_count == 0

    def test_an_empty_table_profiles_without_error(
        self, profile_columns: Callable[..., object]
    ) -> None:
        """An aggregate over zero rows returns one row of NULLs, not no rows.

        Reading that as "no result" is how this crashes, and an empty table
        is the normal state of a table nobody has loaded yet.
        """
        sql = "CREATE TABLE people (id INTEGER, name TEXT);"
        columns = profile_columns(sql=sql)  # type: ignore[call-arg]

        assert columns["id"].min_value is None  # type: ignore[index]
        assert columns["id"].distinct_count == 0  # type: ignore[index]


class TestDistinctCountingCanBeDeclined:
    """The one statistic here that can cost real memory on the server."""

    def test_turning_it_off_leaves_the_count_absent_rather_than_zero(
        self, profile_columns: Callable[..., object]
    ) -> None:
        """``None`` means "not asked for"; ``0`` means "asked, and none".

        Reporting an un-run count as zero would be indistinguishable from an
        all-NULL column, which the test above asserts is genuinely zero.
        """
        columns = profile_columns(ProfilingConfig(distinct_counts=False))  # type: ignore[call-arg]

        assert columns["name"].distinct_count is None  # type: ignore[index]

    def test_the_other_statistics_survive_it(self, profile_columns: Callable[..., object]) -> None:
        """Declining the expensive one must not decline the cheap ones."""
        columns = profile_columns(ProfilingConfig(distinct_counts=False))  # type: ignore[call-arg]

        assert columns["id"].min_value == 1  # type: ignore[index]
        assert columns["id"].max_value == 4  # type: ignore[index]

    def test_it_is_on_by_default(self, profile_columns: Callable[..., object]) -> None:
        """A profile without cardinality is not much of a profile.

        Pinned as a decision rather than left to the default of whatever the
        field happens to be, because the argument for `False` (it is the
        expensive one) is a real argument that lost.
        """
        assert profile_columns()["name"].distinct_count == 2  # type: ignore[index]


class TestAnEstimateSaysThatItIsOne:
    """An estimate and an exact count are different claims."""

    def test_an_exact_count_is_not_flagged_as_approximate(
        self, profile_columns: Callable[..., object]
    ) -> None:
        """The default, and the control for the test below."""
        assert profile_columns()["name"].distinct_is_approximate is False  # type: ignore[index]

    def test_sqlite_gives_an_exact_count_even_when_asked_to_estimate(
        self, profile_columns: Callable[..., object]
    ) -> None:
        """Asking for an estimate an engine cannot give must not lie.

        SQLite ships no sketch-based distinct count, so
        ``approximate_distinct_expression`` returns None there and the exact
        count is used. The flag must then read ``False`` -- reporting an
        exact number as approximate is as wrong as the reverse, and it is the
        direction a careless implementation gets wrong, because it sets the
        flag from what was *requested* rather than from what was *done*.
        """
        columns = profile_columns(  # type: ignore[call-arg]
            ProfilingConfig(approximate_distinct=True)
        )

        assert columns["name"].distinct_count == 2  # type: ignore[index]
        assert columns["name"].distinct_is_approximate is False  # type: ignore[index]


class TestTheDialectDecidesWhatATypeSupports:
    """`TEXT` means different things on different engines."""

    def test_sqlite_text_supports_bounds(self) -> None:
        """SQLite's ordinary string type. ``MIN`` over it is fine."""
        assert get_dialect_by_name("sqlite").supports_min_max("TEXT") is True

    def test_sql_server_legacy_text_does_not(self) -> None:
        """``text`` is the deprecated LOB type there; ``MIN`` over it errors.

        The same four letters, the opposite answer. This pair is the whole
        argument for putting the question behind the dialect.
        """
        assert get_dialect_by_name("sqlserver").supports_min_max("text") is False

    @pytest.mark.parametrize("name", ["sqlite", "postgresql", "sqlserver"])
    def test_no_dialect_averages_a_string(self, name: str) -> None:
        """The gate that stops SQLite answering 0.0 for the mean of a name."""
        dialect = get_dialect_by_name(name)

        assert dialect.supports_mean("varchar") is False
        assert dialect.supports_mean("TEXT") is False

    @pytest.mark.parametrize("name", ["sqlite", "postgresql", "sqlserver"])
    def test_every_dialect_averages_its_numbers(self, name: str) -> None:
        """Spellings differ by engine; the answer must not."""
        dialect = get_dialect_by_name(name)

        assert dialect.supports_mean("integer") is True
        assert dialect.supports_mean("REAL") is True

    @pytest.mark.parametrize("name", ["sqlite", "postgresql", "sqlserver"])
    def test_binary_columns_are_left_alone(self, name: str) -> None:
        """Ordering a blob is meaningless where it is not an outright error."""
        dialect = get_dialect_by_name(name)

        assert dialect.supports_min_max("blob") is False
        assert dialect.supports_mean("blob") is False


class TestItIsStillOneQueryPerTable:
    """The constraint the whole design answers to."""

    def test_four_statistics_over_four_columns_cost_one_scan(
        self, make_sqlite_db: Callable[[str, str], Path]
    ) -> None:
        """`AGENTS.md` "Performance rules" asks for this by name.

        The failure this catches does not change a single returned number,
        which is why it needs its own test: an implementation issuing one
        query per statistic per column returns exactly these values, a
        hundredfold slower on a hundred-column table.

        One statement. Not one per column, not one per statistic.
        """
        db_file = make_sqlite_db("stats-cost.db", SEEDED)
        selects = _recorded_selects(db_file)

        assert len(selects) == 1, f"expected one aggregate query, got {len(selects)}: {selects}"

    def test_that_one_query_carries_every_statistic(
        self, make_sqlite_db: Callable[[str, str], Path]
    ) -> None:
        """Guards the cheap way to pass the test above: compute less.

        A single query that omits MIN, MAX, AVG and the distinct count is
        also a single query.
        """
        db_file = make_sqlite_db("stats-shape.db", SEEDED)
        upper = _recorded_selects(db_file)[0].upper()

        assert "MIN(" in upper
        assert "MAX(" in upper
        assert "AVG(" in upper
        assert "COUNT(DISTINCT" in upper
