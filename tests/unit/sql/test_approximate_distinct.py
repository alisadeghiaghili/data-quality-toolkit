"""Opting into an approximate distinct count (unit 16, performance and scale).

`UNIQUE` rules count duplicates with ``COUNT(col) - COUNT(DISTINCT col)``.
``COUNT(DISTINCT ...)`` is the expensive half: it has to hold every distinct
value it has seen, so on a high-cardinality column of a large table it is the
one operation in DQT that can cost real memory on the server.

Some databases offer a cheap estimate instead. SQL Server has
``APPROX_COUNT_DISTINCT``; SQLite has nothing, and PostgreSQL's HyperLogLog
lives in an extension rather than core, so both report none.

Two things matter more than the speed.

**Asking is per rule, not per run.** Whether an estimate is acceptable is a
property of the check, not of the machine. A DBA may accept it on a
500-million-row table's uniqueness check and refuse it on a small critical
one, in the same run.

**An estimate must announce itself.** A duplicate count that came from
``APPROX_COUNT_DISTINCT`` is not the same claim as one that came from
``COUNT(DISTINCT)``, and a report that presents them identically is asserting
a precision it does not have. That is the honesty gate applied to a number
rather than to a sentence.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from dqt.common.models import ConnectionConfig, RuleConfig, RuleScope
from dqt.sql.dialects import get_dialect_by_name
from dqt.sql.rules import apply_rules
from dqt.sql.schema_discovery import discover_schema

# Four non-NULL emails, two of them the same, so one row is a duplicate of
# another. Counted from the literal below.
SEEDED = """
    CREATE TABLE people (id INTEGER PRIMARY KEY, email TEXT);
    INSERT INTO people VALUES (1, 'a@b.com');
    INSERT INTO people VALUES (2, 'a@b.com');
    INSERT INTO people VALUES (3, 'c@d.com');
    INSERT INTO people VALUES (4, 'e@f.com');
"""


def _unique_rule(*, approximate: bool | None = None) -> RuleConfig:
    """Build a UNIQUE rule on ``email``.

    Args:
        approximate: Value for the ``approximate`` parameter, or None to omit
            it entirely.

    Returns:
        A RuleConfig.

    Example:
        rule = _unique_rule(approximate=True)
    """
    params: dict[str, Any] = {} if approximate is None else {"approximate": approximate}
    return RuleConfig(
        name="unique-email",
        dimension="uniqueness",
        severity="error",
        scope=RuleScope(table_pattern="people", column_pattern="email"),
        expression="UNIQUE",
        params=params,
    )


@pytest.fixture
def run_rule(
    make_sqlite_db: Callable[[str, str], Path],
) -> Callable[[RuleConfig], Any]:
    """Evaluate one rule against the seeded table.

    Args:
        make_sqlite_db: Factory fixture building a SQLite file.

    Returns:
        A callable taking a rule and returning the issues it raised.

    Example:
        issues = run_rule(_unique_rule())
    """

    counter = itertools.count()

    def _run(rule: RuleConfig) -> Any:
        # A fresh file per call: this fixture is used more than once in a
        # single test, and re-running CREATE TABLE against the first database
        # would fail for a reason that has nothing to do with the assertion.
        db_file = make_sqlite_db(f"approx{next(counter)}.db", SEEDED)
        config = ConnectionConfig(id="approx", dsn=f"sqlite:///{db_file}")
        issues, _ = apply_rules(
            run_id="run-approx",
            connection_config=config,
            rules=[rule],
            discovered_tables=discover_schema(config),
        )
        return issues

    return _run


class TestTheDialectDecidesWhatIsPossible:
    """Only SQL Server has a native estimate; the others say so."""

    def test_sql_server_offers_an_expression(self) -> None:
        """``APPROX_COUNT_DISTINCT`` has been in SQL Server since 2019."""
        expression = get_dialect_by_name("sqlserver").approximate_distinct_expression('"c"')

        assert expression == 'APPROX_COUNT_DISTINCT("c")'

    @pytest.mark.parametrize("name", ["sqlite", "postgresql"])
    def test_the_others_report_none_rather_than_faking_one(self, name: str) -> None:
        """SQLite has nothing, and PostgreSQL's HyperLogLog is an extension.

        Returning an exact expression here and calling it approximate would be
        the worst option: the caller would pay full cost while believing they
        had opted out of it.
        """
        assert get_dialect_by_name(name).approximate_distinct_expression('"c"') is None


class TestAskingIsOptionalAndPerRule:
    """The default is exact, and asking is a per-rule decision."""

    def test_the_default_is_exact(self, run_rule: Callable[[RuleConfig], Any]) -> None:
        """A rule that says nothing gets the precise answer.

        Ground truth: four non-NULL emails, ``a@b.com`` twice, so exactly one
        row duplicates another.
        """
        issues = run_rule(_unique_rule())

        assert issues[0].evidence["duplicate_extra_rows"] == 1
        assert issues[0].evidence["approximate"] is False

    def test_asking_on_a_dialect_without_one_still_answers_exactly(
        self, run_rule: Callable[[RuleConfig], Any]
    ) -> None:
        """SQLite cannot estimate, so it counts -- and says the count is exact.

        Refusing the rule would punish a portable config for naming an
        optimisation one database happens to lack. Silently reporting
        ``approximate: true`` would be worse: the number is exact, and saying
        otherwise understates a result DQT is entitled to stand behind.
        """
        issues = run_rule(_unique_rule(approximate=True))

        assert issues[0].evidence["duplicate_extra_rows"] == 1
        assert issues[0].evidence["approximate"] is False

    def test_the_evidence_always_says_which_it_was(
        self, run_rule: Callable[[RuleConfig], Any]
    ) -> None:
        """Present whether or not the caller asked, so a reader never guesses.

        An estimate and an exact count are different claims. A report that
        renders them identically asserts a precision it does not have --
        the honesty gate applied to a number rather than to a sentence.
        """
        for rule in (
            _unique_rule(),
            _unique_rule(approximate=False),
            _unique_rule(approximate=True),
        ):
            issues = run_rule(rule)

            assert "approximate" in issues[0].evidence


class TestTheSqlSaysWhatWasAsked:
    """Checked as generated SQL, since no SQL Server runs in the unit suite."""

    def test_an_approximate_request_reaches_the_dialect(self) -> None:
        """The SQL Server dialect builds the estimating form.

        The unit suite has no SQL Server, so this asserts the expression the
        dialect hands back rather than a query result. The live-server suite
        in ``tests/integration/test_sqlserver.py`` covers the rest.
        """
        dialect = get_dialect_by_name("sqlserver")

        approximate = dialect.approximate_distinct_expression('"email"')
        exact = f"COUNT(DISTINCT {'email'!r})"

        assert approximate is not None
        assert approximate != exact
        assert "APPROX" in approximate
