"""What the rule engine costs the database (unit 16, performance and scale).

Measured before writing these, because guessing would have been wrong:
``NOT NULL`` already costs one query, combining the denominator and the
violation count into a single aggregate. ``RANGE`` and ``UNIQUE`` each cost
two -- a bare ``SELECT COUNT(*)`` for the denominator, then a second scan for
the violations.

So the target is not a new idea, it is the one ``NOT NULL`` already
demonstrates: **one query per rule**. Conditional aggregation gets ``RANGE``
there, and ``COUNT(col) - COUNT(DISTINCT col)`` gets ``UNIQUE`` there while
also replacing a ``GROUP BY`` subquery with a single pass.

A DBA writes the most rules against the tables they care about most, so the
rule count on a hot table is exactly where a per-rule extra scan hurts.

Counts, not seconds, for the same reason as ``test_profiling_cost.py``: a
clock budget in CI is a flaky test wearing a performance costume, and a query
count is both deterministic and the thing that actually scales.

Two other scope items of this unit are pinned here rather than assumed,
because both turned out to be already true and a property nothing checks is
one that quietly stops being true:

* **Evidence is bounded.** ``DQIssue.evidence`` carries counts, never the
  violating rows.
* **The connection is reused.** One connection for the whole rule run, not
  one per rule.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from dqt.common.models import ConnectionConfig, RuleConfig, RuleScope
from dqt.sql.rules import apply_rules
from dqt.sql.schema_discovery import discover_schema
from tests.counting import CountingConnection

SEEDED = """
    CREATE TABLE people (
        id INTEGER PRIMARY KEY,
        email TEXT,
        age INTEGER,
        city TEXT
    );
    INSERT INTO people VALUES (1, 'a@b.com', 30, 'Tehran');
    INSERT INTO people VALUES (2, NULL, 200, 'Tehran');
    INSERT INTO people VALUES (3, 'a@b.com', 25, NULL);
"""


def _rule(name: str, column: str, expression: str, **params: Any) -> RuleConfig:
    """Build a rule against ``people``.

    Args:
        name: Rule name, which must be unique within a run.
        column: Column the rule targets.
        expression: One of the closed DSL keywords.
        **params: Rule parameters.

    Returns:
        A RuleConfig.

    Example:
        rule = _rule("r1", "email", "NOT NULL")
    """
    return RuleConfig(
        name=name,
        dimension="completeness" if expression == "NOT NULL" else "validity",
        severity="error",
        scope=RuleScope(table_pattern="people", column_pattern=column),
        expression=expression,
        params=params,
    )


@pytest.fixture
def run_rules_and_count(
    make_sqlite_db: Callable[[str, str], Path], monkeypatch: pytest.MonkeyPatch
) -> Callable[[list[RuleConfig]], tuple[list[str], Any]]:
    """Evaluate rules and return the statements the engine ran.

    Args:
        make_sqlite_db: Factory fixture building a SQLite file.
        monkeypatch: Used to hand the engine a counting connection.

    Returns:
        A callable taking rules and returning (statements, issues).

    Example:
        statements, issues = run_rules_and_count([rule])
    """
    import dqt.sql.rules as rules_module

    counter = itertools.count()
    real_connect = rules_module.get_connection

    def _run(rules: list[RuleConfig]) -> tuple[list[str], Any]:
        db_file = make_sqlite_db(f"rules{next(counter)}.db", SEEDED)
        config = ConnectionConfig(id="cost", dsn=f"sqlite:///{db_file}")
        tables = discover_schema(config)

        seen: list[str] = []

        def counting_connect(connection_config: ConnectionConfig) -> Any:
            wrapper = CountingConnection(real_connect(connection_config))
            wrapper.statements = seen
            return wrapper

        monkeypatch.setattr(rules_module, "get_connection", counting_connect)
        issues, _ = apply_rules(
            run_id="run-cost",
            connection_config=config,
            rules=rules,
            discovered_tables=tables,
        )
        return seen, issues

    return _run


class TestTheTableIsReadOncePerRuleAtMost:
    """The denominator is a property of the table, not of each rule."""

    @pytest.mark.parametrize(
        ("column", "expression", "params"),
        [
            ("email", "NOT NULL", {}),
            ("age", "RANGE", {"min": 0, "max": 120}),
            ("email", "UNIQUE", {}),
        ],
    )
    def test_every_rule_type_costs_one_query(
        self,
        run_rules_and_count: Callable[[list[RuleConfig]], tuple[list[str], Any]],
        column: str,
        expression: str,
        params: dict[str, Any],
    ) -> None:
        """One rule, one scan -- the shape ``NOT NULL`` already had.

        A rule needs a denominator and a violation count, and both come from
        the same rows. Asking for them separately reads the table twice to
        learn one thing.
        """
        statements, _ = run_rules_and_count([_rule("r1", column, expression, **params)])

        assert len(statements) == 1, f"ran {len(statements)}: {statements}"

    def test_four_rules_cost_four_queries(
        self, run_rules_and_count: Callable[[list[RuleConfig]], tuple[list[str], Any]]
    ) -> None:
        """The cost is the rule count, and nothing else.

        One query per rule is the honest floor: each rule tests something
        different and has to look at the data. What is not the floor is a
        second scan per rule to count rows the first scan already saw.
        """
        rules = [
            _rule("r1", "email", "NOT NULL"),
            _rule("r2", "city", "NOT NULL"),
            _rule("r3", "age", "RANGE", min=0, max=120),
            _rule("r4", "email", "UNIQUE"),
        ]

        statements, _ = run_rules_and_count(rules)

        assert len(statements) == len(rules), (
            f"budget is one query per rule ({len(rules)}), ran {len(statements)}: {statements}"
        )

    def test_no_rule_issues_a_bare_row_count(
        self, run_rules_and_count: Callable[[list[RuleConfig]], tuple[list[str], Any]]
    ) -> None:
        """Names the specific waste, so the budget cannot be met by luck.

        A total could be satisfied by a saving somewhere else. This asserts
        that the particular thing being removed -- a scan whose only purpose
        is a denominator the other scan already had -- is gone.
        """
        rules = [
            _rule("r1", "email", "NOT NULL"),
            _rule("r2", "city", "NOT NULL"),
            _rule("r3", "age", "RANGE", min=0, max=120),
        ]

        statements, _ = run_rules_and_count(rules)

        bare = [s for s in statements if " ".join(s.split()) == 'SELECT COUNT(*) FROM "people"']
        assert bare == [], f"a denominator-only scan survived: {bare}"


class TestTheVerdictsAreStillRight:
    """A cheaper engine that reports the wrong issues is worse than a slow one."""

    def test_the_same_issues_are_raised(
        self, run_rules_and_count: Callable[[list[RuleConfig]], tuple[list[str], Any]]
    ) -> None:
        """Ground truth, hand-counted from the seeded literal.

        ``email`` is NULL on row 2, so NOT NULL fails once. ``city`` is NULL
        on row 3, so it fails once. ``age`` is 200 on row 2, outside 0-120, so
        RANGE fails once. ``email`` repeats ``a@b.com``, so UNIQUE fails once.
        Four rules, four issues.
        """
        rules = [
            _rule("r1", "email", "NOT NULL"),
            _rule("r2", "city", "NOT NULL"),
            _rule("r3", "age", "RANGE", min=0, max=120),
            _rule("r4", "email", "UNIQUE"),
        ]

        _, issues = run_rules_and_count(rules)

        assert {issue.rule_name for issue in issues} == {"r1", "r2", "r3", "r4"}

    def test_a_passing_rule_raises_nothing(
        self, run_rules_and_count: Callable[[list[RuleConfig]], tuple[list[str], Any]]
    ) -> None:
        """``id`` is the primary key, so it is neither NULL nor duplicated."""
        _, issues = run_rules_and_count([_rule("ok", "id", "NOT NULL")])

        assert issues == []


class TestPropertiesThatAreAlreadyTrue:
    """Pinned rather than assumed, so they cannot quietly stop being true."""

    def test_evidence_carries_counts_not_rows(
        self, run_rules_and_count: Callable[[list[RuleConfig]], tuple[list[str], Any]]
    ) -> None:
        """A ``DQIssue`` must never materialise the violating set.

        On a table where half the rows fail, evidence holding the rows would
        put the report's size at the mercy of how bad the data is -- worst
        exactly when a DBA most needs to read it.
        """
        _, issues = run_rules_and_count([_rule("r1", "email", "NOT NULL")])

        evidence = issues[0].evidence
        assert set(evidence) == {"null_count", "total_rows"}
        assert all(isinstance(value, int) for value in evidence.values())

    def test_one_connection_serves_every_rule(
        self, make_sqlite_db: Callable[[str, str], Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Reopening per rule would pay the handshake once per rule.

        On SQLite that is cheap; on PostgreSQL or SQL Server over a network it
        is the dominant cost of a small query, and DQT's read-only setup runs
        on every connect -- ``SET SESSION CHARACTERISTICS`` on PostgreSQL, and
        a warning on SQL Server that would repeat once per rule.

        This counts connections opened, not statements, because it is a
        different property from the query budget above and a total could hide
        it.
        """
        import dqt.sql.rules as rules_module

        db_file = make_sqlite_db("reuse.db", SEEDED)
        config = ConnectionConfig(id="reuse", dsn=f"sqlite:///{db_file}")
        tables = discover_schema(config)

        opened = 0
        real_connect = rules_module.get_connection

        def counting_open(connection_config: ConnectionConfig) -> Any:
            nonlocal opened
            opened += 1
            return real_connect(connection_config)

        monkeypatch.setattr(rules_module, "get_connection", counting_open)
        apply_rules(
            run_id="run-reuse",
            connection_config=config,
            rules=[
                _rule("r1", "email", "NOT NULL"),
                _rule("r2", "city", "NOT NULL"),
                _rule("r3", "age", "RANGE", min=0, max=120),
            ],
            discovered_tables=tables,
        )

        assert opened == 1, f"three rules opened {opened} connections"
