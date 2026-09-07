"""Uniqueness and consistency diagnostics (`F3`, first half).

`DQDimension` has six values and `DQDiagnostics` produced one. The dashboard
has rendered the other five as "not measured" since it was built, and
`dqt_competitors.md` has recorded F3 as `NOT MET` throughout.

Two of them fall out of what `F1` already computes, at no extra scan:

**Uniqueness** is a distinct count against a non-NULL count. A column with
1,000 values and 998 distinct ones has duplicates, and nothing about the
null count or the bounds would say so.

**Consistency** needs one more aggregate, and it is the interesting one.
The question is not "are these values valid" -- that is validity -- but
*"is the same thing written more than one way?"* `"Tehran"`, `"tehran"` and
`" Tehran "` are one city recorded three ways, and that is precisely what
`cleansing`'s `standardize` operation exists to fix. Comparing
``COUNT(DISTINCT col)`` against ``COUNT(DISTINCT <normalized col>)`` finds
it in the same pass: when the second is smaller, some values differ only by
case or surrounding whitespace.

**A duplicate is not an inconsistency and the two must not be conflated.**
Two rows both saying `"Tehran"` are duplicates -- a uniqueness observation.
One row saying `"Tehran"` and another `"tehran"` are an inconsistency, and
the distinct count cannot see it because they *are* distinct. The fixture
below contains both, separately, so neither test can pass on the other's
data.

Diagnostics stay pure over profiles: no new query, nothing opened here.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from dqt.common.models import ConnectionConfig
from dqt.sql.diagnostics import DQDiagnostics
from dqt.sql.dialects import get_dialect_by_name
from dqt.sql.profiling import SqlProfiler
from dqt.sql.schema_discovery import discover_schema

# Hand-derived from the values below:
#   city   : 5 non-NULL, values Tehran / tehran / " Tehran " / Shiraz / Shiraz
#            distinct raw = 4  (Tehran, tehran, " Tehran ", Shiraz)
#            distinct normalized = 2  (tehran, shiraz)
#            -> 2 spellings collapse, so it is INCONSISTENT
#            -> raw distinct 4 < non-NULL 5, so it also has a DUPLICATE
#   code   : 5 non-NULL, all different, no case or space variation
#            -> unique and consistent; the control for both tests
SEEDED = """
    CREATE TABLE places (
        id INTEGER PRIMARY KEY,
        city TEXT,
        code TEXT
    );
    INSERT INTO places (id, city, code) VALUES
        (1, 'Tehran',   'A1'),
        (2, 'tehran',   'A2'),
        (3, ' Tehran ', 'A3'),
        (4, 'Shiraz',   'A4'),
        (5, 'Shiraz',   'A5');
"""


@pytest.fixture
def profiled(make_sqlite_db: Callable[[str, str], Path]) -> Callable[..., object]:
    """Profile a seeded table and return its columns by name.

    Args:
        make_sqlite_db: Factory fixture building a SQLite file.

    Returns:
        A callable taking optional SQL and returning a name-to-profile dict.

    Example:
        columns = profiled()
    """
    counter = {"n": 0}

    def _run(sql: str = SEEDED) -> object:
        counter["n"] += 1
        db_file = make_sqlite_db(f"consistency{counter['n']}.db", sql)
        config = ConnectionConfig(id="s", dsn=f"sqlite:///{db_file}")
        profile = SqlProfiler(config).profile_tables(discover_schema(config))[0]
        return {column.column_name: column for column in profile.columns}

    return _run


class TestTheNormalizedDistinctCountIsProfiled:
    """The one new number, computed in the pass that was already happening."""

    def test_case_and_space_variants_collapse(self, profiled: Callable[..., object]) -> None:
        """Four spellings, two cities. Counted from the INSERT, not the code."""
        city = profiled()["city"]  # type: ignore[index]

        assert city.distinct_count == 4
        assert city.normalized_distinct_count == 2

    def test_a_tidy_column_collapses_to_nothing(self, profiled: Callable[..., object]) -> None:
        """``code`` has no variants, so both counts agree.

        The control. Without it, a normalizer that collapsed everything to
        one value would satisfy the test above.
        """
        code = profiled()["code"]  # type: ignore[index]

        assert code.distinct_count == 5
        assert code.normalized_distinct_count == 5

    def test_numeric_columns_are_left_alone(self, profiled: Callable[..., object]) -> None:
        """Case-folding a number is meaningless work in the hot query.

        ``None``, not a repeated distinct count: the question was never
        asked of this column, and answering it with the raw count would say
        "checked, and consistent".
        """
        assert profiled()["id"].normalized_distinct_count is None  # type: ignore[index]

    @pytest.mark.parametrize("name", ["sqlite", "postgresql", "sqlserver"])
    def test_every_dialect_spells_the_normalizer(self, name: str) -> None:
        """Trimming and case-folding, asked of the dialect rather than assumed.

        ``TRIM`` arrived in SQL Server only in 2017; asking the dialect
        leaves room for an engine that needs ``LTRIM(RTRIM(...))`` without
        the caller knowing.
        """
        expression = get_dialect_by_name(name).normalized_text_expression('"city"')

        assert "city" in expression
        assert "LOWER" in expression.upper()


class TestUniquenessIsDiagnosed:
    """A distinct count nobody compares to anything is a number, not a finding."""

    def test_duplicates_raise_an_issue(self, profiled: Callable[..., object]) -> None:
        """``city`` has 5 non-NULL values and 4 distinct: one duplicate."""
        issues = _diagnose(profiled())

        uniqueness = [i for i in issues if i.dimension == "uniqueness"]

        assert [i.column_name for i in uniqueness] == ["city"]
        assert "1" in uniqueness[0].message

    def test_a_unique_column_raises_nothing(self, profiled: Callable[..., object]) -> None:
        """``code`` is all distinct. The control."""
        issues = _diagnose(profiled())

        assert "code" not in [i.column_name for i in issues if i.dimension == "uniqueness"]

    def test_nulls_are_not_counted_as_duplicates(self, profiled: Callable[..., object]) -> None:
        """Two NULLs are not two copies of a value.

        ``COUNT(DISTINCT)`` already excludes NULL, so comparing it against
        the *row* count rather than the non-NULL count reports every
        nullable column in the database as having duplicates. That is the
        arithmetic slip this pins.
        """
        sql = """
            CREATE TABLE places (id INTEGER PRIMARY KEY, city TEXT, code TEXT);
            INSERT INTO places (id, city, code) VALUES
                (1, 'Tehran', 'A1'), (2, NULL, 'A2'), (3, NULL, 'A3');
        """
        issues = _diagnose(profiled(sql))  # type: ignore[call-arg]

        assert not [i for i in issues if i.dimension == "uniqueness"]


class TestConsistencyIsDiagnosed:
    """The dimension whose name means "written the same way every time"."""

    def test_spelling_variants_raise_an_issue(self, profiled: Callable[..., object]) -> None:
        """Four spellings collapsing to two is two values written more than one way."""
        issues = _diagnose(profiled())

        consistency = [i for i in issues if i.dimension == "consistency"]

        assert [i.column_name for i in consistency] == ["city"]

    def test_a_consistent_column_raises_nothing(self, profiled: Callable[..., object]) -> None:
        """``code`` varies in neither case nor whitespace."""
        issues = _diagnose(profiled())

        assert "code" not in [i.column_name for i in issues if i.dimension == "consistency"]

    def test_duplicates_alone_are_not_an_inconsistency(
        self, profiled: Callable[..., object]
    ) -> None:
        """The distinction the whole dimension rests on.

        Two rows both saying ``'Shiraz'`` are duplicates. They are *not*
        inconsistent -- the same thing is written the same way. A check that
        conflated the two would flag every column that has any repeated
        value, which is nearly all of them.
        """
        sql = """
            CREATE TABLE places (id INTEGER PRIMARY KEY, city TEXT, code TEXT);
            INSERT INTO places (id, city, code) VALUES
                (1, 'Shiraz', 'A1'), (2, 'Shiraz', 'A2'), (3, 'Tabriz', 'A3');
        """
        issues = _diagnose(profiled(sql))  # type: ignore[call-arg]

        assert not [i for i in issues if i.dimension == "consistency"]
        assert [i.dimension for i in issues if i.dimension == "uniqueness"] == ["uniqueness"]


class TestDiagnosticsStayPure:
    """`DQDiagnostics` reads profiles. It must not learn to query."""

    def test_the_module_opens_no_connection(self) -> None:
        """Its testability rests on this, and so does the layering.

        A diagnostic that queried would need a live database to test, and
        every one of the assertions above would become an integration test.
        """
        source = (
            Path(__file__).resolve().parents[3] / "src" / "dqt" / "sql" / "diagnostics.py"
        ).read_text(encoding="utf-8")

        for forbidden in ("get_connection", "sqlite3", "psycopg", "pyodbc", "execute("):
            assert forbidden not in source, f"diagnostics.py must not use {forbidden!r}"


def _diagnose(columns: object) -> list[object]:
    """Run diagnostics over one table's profiled columns.

    Args:
        columns: Column name to profile, as the fixture returns.

    Returns:
        The issues raised.

    Example:
        issues = _diagnose(profiled())
    """
    from dqt.sql.profiling import TableProfile

    profiles = list(columns.values())  # type: ignore[attr-defined]
    table = TableProfile(
        schema_name=profiles[0].schema_name,
        table_name=profiles[0].table_name,
        row_count=profiles[0].row_count,
        columns=profiles,
    )
    return DQDiagnostics().run([table], run_id="run-1")


class TestBothDimensionsAreScored:
    """ "Not measured" and "measured, and fine" are different answers."""

    def test_a_clean_column_still_produces_both_metrics(
        self, make_sqlite_db: Callable[[str, str], Path], tmp_path: Path
    ) -> None:
        """Silence is indistinguishable from not having looked.

        The dashboard renders a dimension with no metric as "not measured".
        A database that is genuinely unique and consistent has to be able to
        say so, which means a metric even when there is no issue -- the same
        argument `F2` made for referential integrity.
        """
        sql = """
            CREATE TABLE places (id INTEGER PRIMARY KEY, code TEXT);
            INSERT INTO places (id, code) VALUES (1, 'A1'), (2, 'A2');
        """
        metrics = _run_metrics(make_sqlite_db, tmp_path, "scored-clean.db", sql)
        dimensions = {m.dimension for m in metrics}  # type: ignore[attr-defined]

        assert "uniqueness" in dimensions
        assert "consistency" in dimensions

    def test_a_dirty_column_scores_below_one(
        self, make_sqlite_db: Callable[[str, str], Path], tmp_path: Path
    ) -> None:
        """A score that never moves is a label, not a measurement."""
        metrics = _run_metrics(make_sqlite_db, tmp_path, "scored-dirty.db", SEEDED)

        for dimension in ("uniqueness", "consistency"):
            scores = [
                m.score
                for m in metrics  # type: ignore[attr-defined]
                if m.dimension == dimension and m.column_name == "city"
            ]

            assert scores and scores[0] < 1.0, f"{dimension} did not score the dirty column"


def _run_metrics(
    make_sqlite_db: Callable[[str, str], Path], tmp_path: Path, name: str, sql: str
) -> object:
    """Run the pipeline and return its metrics.

    Args:
        make_sqlite_db: Factory fixture building a SQLite file.
        tmp_path: pytest's per-test directory.
        name: Distinct database filename.
        sql: Schema and data to seed.

    Returns:
        The run's metrics.

    Example:
        metrics = _run_metrics(make_sqlite_db, tmp_path, "a.db", SEEDED)
    """
    from dqt.common.models import DQPipelineConfig
    from dqt.sql.pipeline import DQTPipeline

    db_file = make_sqlite_db(name, sql)
    result, _ = DQTPipeline(
        ConnectionConfig(id="s", dsn=f"sqlite:///{db_file}"),
        DQPipelineConfig(connection_id="s"),
        store_path=tmp_path / "runs.db",
        report_dir=tmp_path,
    ).run()
    return result.metrics
