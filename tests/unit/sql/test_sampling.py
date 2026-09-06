"""Honouring `SamplingConfig` (`NEW-Z`).

`1.0.2` corrected a docstring that described sampling SQL DQT never generated.
This generates it.

**Profiling samples. Rules never do.** That is the design decision this file
exists to record, and it is not a limitation — it is the point.

A profile is a *description*: "about 12% of `email` is NULL" is a useful
sentence whether it came from every row or from fifty thousand of them, and
saying it came from a sample makes it honest.

A rule is a *verdict*: "`email` has no duplicates" read off a sample means
"no duplicates **among the rows I looked at**", which is not the same claim
and is far more reassuring than the evidence supports. A rule that passes
because it did not look is the exact failure `DQT-04` fixed for `regex` on
SQLite and `GATE-02` proved against on SQL Server. Sampling a verdict would
reintroduce it by design.

**Every sampled number says so.** `DQMetric.metadata` carries the strategy and
the limit, for the same reason `UNIQUE`'s evidence carries `approximate`: a
sampled figure and a full-scan figure are different claims, and a trend that
renders them identically asserts a precision it does not have.

**`seed` is refused rather than ignored.** None of the three dialects can seed
a random sample inside a single scalar subquery — PostgreSQL needs a separate
`setseed()` call, SQLite has no seedable `RANDOM()`, SQL Server's `NEWID()`
takes no seed. Accepting it and quietly producing an unseeded sample is what
this whole unit exists to stop happening.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable
from pathlib import Path

import pytest

from dqt.common.models import ConnectionConfig, SamplingConfig
from dqt.sql.dialects import get_dialect_by_name
from dqt.sql.profiling import SqlProfiler
from dqt.sql.schema_discovery import discover_schema

SQLITE = get_dialect_by_name("sqlite")

SEEDED = """
    CREATE TABLE people (id INTEGER PRIMARY KEY, email TEXT);
    INSERT INTO people (id, email)
    SELECT value, CASE WHEN value % 4 = 0 THEN NULL ELSE 'a@b.com' END
    FROM (WITH RECURSIVE c(value) AS (
        SELECT 1 UNION ALL SELECT value + 1 FROM c WHERE value < 200
    ) SELECT value FROM c);
"""


class TestTheDialectBuildsTheSampledTable:
    """Each engine samples in its own syntax; the caller asks once."""

    def test_sqlite_takes_the_first_n_rows_with_limit(self) -> None:
        """``first_n`` is the cheap one: no sort, just stop early."""
        expression = SQLITE.sampled_table_expression('"people"', "first_n", 100, None)

        assert "LIMIT 100" in expression
        assert "ORDER BY" not in expression.upper()

    def test_sqlite_randomises_with_order_by_random(self) -> None:
        """A random sample has to sort, which is why it costs more."""
        expression = SQLITE.sampled_table_expression('"people"', "random", 100, None)

        assert "ORDER BY RANDOM()" in expression.upper()
        assert "LIMIT 100" in expression

    def test_sql_server_uses_top_rather_than_limit(self) -> None:
        """T-SQL puts the bound on the projection, as it does everywhere else.

        This is the structural difference the dialect layer exists for -- a
        caller cannot sample by appending a string.
        """
        expression = get_dialect_by_name("sqlserver").sampled_table_expression(
            "[people]", "first_n", 100, None
        )

        assert "TOP (100)" in expression
        assert "LIMIT" not in expression.upper()

    def test_sql_server_randomises_with_newid(self) -> None:
        """``NEWID()`` is T-SQL's random ordering; ``RANDOM()`` does not exist."""
        expression = get_dialect_by_name("sqlserver").sampled_table_expression(
            "[people]", "random", 100, None
        )

        assert "NEWID()" in expression.upper()

    @pytest.mark.parametrize("name", ["sqlite", "postgresql", "sqlserver"])
    def test_the_result_is_a_usable_table_reference(self, name: str) -> None:
        """It is substituted where a table name goes, so it must be aliased.

        An unaliased subquery is a syntax error on every engine here, and the
        failure would appear at the far end of query building rather than
        where the expression was made.
        """
        expression = get_dialect_by_name(name).sampled_table_expression(
            '"people"', "first_n", 10, None
        )

        assert expression.strip().startswith("(")
        assert " AS " in expression.upper()

    @pytest.mark.parametrize("name", ["sqlite", "postgresql", "sqlserver"])
    def test_a_seed_is_refused_by_name(self, name: str) -> None:
        """Refused, not ignored -- which is the whole reason for this unit.

        No dialect here can seed a random sample inside one scalar subquery.
        Accepting the parameter and quietly producing an unseeded sample is
        precisely the failure `1.0.2` documented.
        """
        with pytest.raises(ValueError, match="seed"):
            get_dialect_by_name(name).sampled_table_expression('"t"', "random", 10, 42)

    @pytest.mark.parametrize("name", ["sqlite", "postgresql", "sqlserver"])
    def test_a_seed_is_harmless_when_the_sample_is_not_random(self, name: str) -> None:
        """``first_n`` is already reproducible, so a seed changes nothing.

        Refusing it here would be pedantry rather than protection.
        """
        expression = get_dialect_by_name(name).sampled_table_expression(
            '"t"', "first_n", 10, 42
        )

        assert expression


@pytest.fixture
def profile(make_sqlite_db: Callable[[str, str], Path]) -> Callable[..., object]:
    """Profile the seeded 200-row table, optionally sampled.

    Args:
        make_sqlite_db: Factory fixture building a SQLite file.

    Returns:
        A callable taking an optional SamplingConfig and returning the profile.

    Example:
        result = profile(SamplingConfig(strategy="first_n", limit=50))
    """
    counter = itertools.count()

    def _run(sampling: SamplingConfig | None = None) -> object:
        db_file = make_sqlite_db(f"sample{next(counter)}.db", SEEDED)
        config = ConnectionConfig(id="s", dsn=f"sqlite:///{db_file}")
        tables = discover_schema(config)
        return SqlProfiler(config, sampling=sampling).profile_tables(tables)[0]

    return _run


class TestProfilingHonoursTheSetting:
    """The behaviour `1.0.2` had to admit was missing."""

    def test_an_unsampled_profile_sees_every_row(self, profile: Callable[..., object]) -> None:
        """The control. 200 rows seeded, counted from the literal.

        Without this, a sampled profile reporting 50 could mean sampling
        works or could mean the fixture is smaller than intended.
        """
        assert profile().row_count == 200  # type: ignore[attr-defined]

    def test_a_sampled_profile_reads_only_the_sample(
        self, profile: Callable[..., object]
    ) -> None:
        """50 of 200, so the count is 50 rather than 200.

        ``first_n`` is used because its result is deterministic; a random
        sample of 50 also returns 50, but asserting on it would be asserting
        on the engine's shuffle.
        """
        sampled = profile(SamplingConfig(strategy="first_n", limit=50))

        assert sampled.row_count == 50  # type: ignore[attr-defined]

    def test_a_limit_above_the_table_size_reads_everything(
        self, profile: Callable[..., object]
    ) -> None:
        """A sample larger than the table is the table, not an error."""
        sampled = profile(SamplingConfig(strategy="first_n", limit=10_000))

        assert sampled.row_count == 200  # type: ignore[attr-defined]

    def test_the_null_counts_come_from_the_sample_too(
        self, profile: Callable[..., object]
    ) -> None:
        """Every column statistic, not only the row count.

        The fixture nulls every fourth row, so the first 40 rows hold 10
        NULLs -- counted from the seeding expression, not from the profiler.
        """
        sampled = profile(SamplingConfig(strategy="first_n", limit=40))
        email = next(c for c in sampled.columns if c.column_name == "email")  # type: ignore[attr-defined]

        assert email.null_count == 10


class TestASampledNumberSaysSo:
    """A sampled figure and a full-scan figure are different claims."""

    def test_a_sampled_profile_records_how_it_was_taken(
        self, profile: Callable[..., object]
    ) -> None:
        """Strategy and limit, so a reader can judge the number.

        "12% NULL" means something different from a 50-row sample than from
        two hundred, and only the sample size distinguishes them.
        """
        sampled = profile(SamplingConfig(strategy="first_n", limit=50))

        assert sampled.sampling == {"strategy": "first_n", "limit": 50}  # type: ignore[attr-defined]

    def test_an_unsampled_profile_says_nothing(
        self, profile: Callable[..., object]
    ) -> None:
        """Absent rather than a falsy placeholder.

        Every profile stored before this feature existed has no sampling
        information, and "unsampled" is the correct reading of that -- so the
        new field has to agree with the old rows rather than contradict them.
        """
        assert profile().sampling is None  # type: ignore[attr-defined]
