"""One scan per table, not one per rule (unit 16, performance and scale).

``CLAUDE.md`` §3 asks for this by name: *"Rules on the same table are grouped
so the table is scanned once, not once per rule."* The previous pass got each
rule down to one query and `test_rules_cost.py` gates that, which is a real
improvement over two and **is not the same claim**. A DBA writes the most
rules against the table they care about most, so twenty rules on a hot table
were twenty scans where one would do.

The plan said that unit was closed. It was not, and this file is the other
half.

**How.** Every check compiles to aggregate *expressions* rather than to a
statement: a pair of `SUM(CASE WHEN ... THEN 1 ELSE 0 END)`-style columns and
their binds. Checks against the same table are concatenated into one
``SELECT``, run once, and each check reads back its own slice of the row.
That is why no check may carry a ``WHERE``: a predicate belonging to one rule
would silently filter the rows every other rule in the batch counted.

**What stays alone, and why it is said out loud.** A ``REFERENCE`` rule
pointing at a reference *table* needs a join, and a join changes which rows
the other aggregates see. Those run one query each. The alternative -- making
every other rule's aggregate join-aware -- would trade a clear cost for a
subtle correctness risk.

**One bad rule must not poison the others.** Batching means a single
unparseable expression fails a query that several rules were relying on. When
a batch fails, DQT retries its checks one at a time, so the DBA gets the
verdicts that were computable and an error naming only the rule that was not.
Without that, a typo in one rule would blank a whole table's report.

Counted, not timed, for the reason ``test_profiling_cost.py`` gives.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from dqt.common.models import ConnectionConfig, DQIssue, RuleConfig, RuleScope
from dqt.sql.rules import apply_rules
from dqt.sql.schema_discovery import discover_schema
from tests.counting import CountingConnection

SEEDED = """
    CREATE TABLE ref_cities (name TEXT);
    INSERT INTO ref_cities (name) VALUES ('Tehran'), ('Shiraz');
    CREATE TABLE people (
        id INTEGER PRIMARY KEY,
        email TEXT,
        age INTEGER,
        city TEXT
    );
    INSERT INTO people (id, email, age, city) VALUES
        (1, 'a@b.com', 30, 'Tehran'),
        (2, NULL, 200, 'Tehran'),
        (3, 'a@b.com', 25, 'Atlantis');
    CREATE TABLE orders (id INTEGER PRIMARY KEY, amount INTEGER);
    INSERT INTO orders (id, amount) VALUES (1, 5), (2, NULL);
"""


def _rule(name: str, table: str, column: str, expression: str, **params: Any) -> RuleConfig:
    """Build a rule against one column.

    Args:
        name: Rule name, unique within a run.
        table: Table pattern.
        column: Column pattern.
        expression: One of the closed DSL keywords.
        **params: Rule parameters.

    Returns:
        A RuleConfig.

    Example:
        rule = _rule("r1", "people", "email", "NOT NULL")
    """
    return RuleConfig(
        name=name,
        dimension="completeness" if expression == "NOT NULL" else "validity",
        severity="error",
        scope=RuleScope(table_pattern=table, column_pattern=column),
        expression=expression,
        params=params,
    )


RunRules = Callable[[list[RuleConfig]], tuple[list[str], list[DQIssue], list[Any]]]


@pytest.fixture
def run_rules(
    make_sqlite_db: Callable[[str, str], Path], monkeypatch: pytest.MonkeyPatch
) -> RunRules:
    """Evaluate rules and return the statements, issues and summaries.

    Args:
        make_sqlite_db: Factory fixture building a SQLite file.
        monkeypatch: Used to hand the engine a counting connection.

    Returns:
        A callable taking rules and returning (statements, issues, summaries).

    Example:
        statements, issues, summaries = run_rules([rule])
    """
    import dqt.sql.rules as rules_module

    counter = itertools.count()
    real_connect = rules_module.get_connection

    def _run(rules: list[RuleConfig]) -> tuple[list[str], list[DQIssue], list[Any]]:
        db_file = make_sqlite_db(f"grouped{next(counter)}.db", SEEDED)
        config = ConnectionConfig(id="grouped", dsn=f"sqlite:///{db_file}")
        tables = discover_schema(config)

        seen: list[str] = []

        def counting_connect(connection_config: ConnectionConfig) -> Any:
            wrapper = CountingConnection(real_connect(connection_config))
            wrapper.statements = seen
            return wrapper

        monkeypatch.setattr(rules_module, "get_connection", counting_connect)
        issues, summaries = apply_rules(
            run_id="run-grouped",
            connection_config=config,
            rules=rules,
            discovered_tables=tables,
        )
        return seen, issues, summaries

    return _run


class TestATableIsScannedOncePerRun:
    """The cost is the number of tables, not the number of rules."""

    def test_four_rules_on_one_table_cost_one_query(self, run_rules: RunRules) -> None:
        """The claim ``CLAUDE.md`` §3 makes, stated as a count.

        Four different checks over the same rows. Each needs a denominator
        and a violation count, and one pass over the table produces all
        eight numbers.
        """
        rules = [
            _rule("r1", "people", "email", "NOT NULL"),
            _rule("r2", "people", "city", "NOT NULL"),
            _rule("r3", "people", "age", "RANGE", min=0, max=120),
            _rule("r4", "people", "email", "UNIQUE"),
        ]

        statements, _, _ = run_rules(rules)

        assert len(statements) == 1, f"one scan expected, ran {len(statements)}: {statements}"

    def test_the_cost_does_not_grow_with_the_rule_count(self, run_rules: RunRules) -> None:
        """Two rules and eight rules cost the same.

        Stated as a comparison so it cannot be satisfied by a constant that
        happens to be large. This is the property; the count above is one
        instance of it.
        """
        few, _, _ = run_rules(
            [
                _rule("r1", "people", "email", "NOT NULL"),
                _rule("r2", "people", "city", "NOT NULL"),
            ]
        )
        many, _, _ = run_rules(
            [
                _rule(f"r{n}", "people", column, expression, **params)
                for n, (column, expression, params) in enumerate(
                    [
                        ("email", "NOT NULL", {}),
                        ("city", "NOT NULL", {}),
                        ("age", "NOT NULL", {}),
                        ("id", "NOT NULL", {}),
                        ("email", "UNIQUE", {}),
                        ("city", "UNIQUE", {}),
                        ("age", "RANGE", {"min": 0, "max": 120}),
                        ("id", "RANGE", {"min": 0}),
                    ]
                )
            ]
        )

        assert len(few) == len(many) == 1

    def test_the_cost_grows_with_the_table_count(self, run_rules: RunRules) -> None:
        """Two tables, two scans. Per-table cost is the irreducible part."""
        statements, _, _ = run_rules(
            [
                _rule("r1", "people", "email", "NOT NULL"),
                _rule("r2", "orders", "amount", "NOT NULL"),
            ]
        )

        assert len(statements) == 2

    def test_a_regex_rule_joins_the_batch(self, run_rules: RunRules) -> None:
        """``regex`` used to cost two queries, and nothing noticed.

        The budget test never parametrised it, so a bare row count followed
        by the match survived the pass that removed exactly that shape from
        ``RANGE`` and ``UNIQUE``.
        """
        statements, _, _ = run_rules(
            [
                _rule("r1", "people", "email", "regex", pattern=r"^[^@]+@[^@]+$"),
                _rule("r2", "people", "city", "NOT NULL"),
            ]
        )

        assert len(statements) == 1

    def test_no_statement_carries_a_where_clause(self, run_rules: RunRules) -> None:
        """A predicate in a batch would filter the other rules' rows.

        This is the invariant that makes batching safe, so it is asserted
        directly rather than inferred from the counts: every per-rule
        condition has to live inside a ``CASE``, never in a ``WHERE``.
        """
        statements, _, _ = run_rules(
            [
                _rule("r1", "people", "age", "RANGE", min=0, max=120),
                _rule("r2", "people", "email", "regex", pattern=r"^[^@]+@[^@]+$"),
                _rule("r3", "people", "city", "REFERENCE", values=["Tehran"]),
            ]
        )

        batched = [s for s in statements if "ref_cities" not in s]
        assert all(" WHERE " not in " ".join(s.split()).upper() for s in batched), batched


class TestWhatCannotBeBatchedSaysSo:
    """A joined reference check runs alone, and does not drag the rest with it."""

    def test_a_reference_table_rule_runs_on_its_own(self, run_rules: RunRules) -> None:
        """A join changes which rows the other aggregates would see.

        Making every other rule's aggregate join-aware would trade a clear
        cost for a subtle correctness risk, so this one pays a query.
        Three rules, two statements: one batch plus the joined check.
        """
        statements, _, _ = run_rules(
            [
                _rule("r1", "people", "email", "NOT NULL"),
                _rule("r2", "people", "age", "RANGE", min=0, max=120),
                _rule(
                    "r3",
                    "people",
                    "city",
                    "REFERENCE",
                    reference_table="ref_cities",
                    reference_column="name",
                ),
            ]
        )

        assert len(statements) == 2

    def test_an_inline_reference_list_does_batch(self, run_rules: RunRules) -> None:
        """No join, so nothing stops it joining the batch."""
        statements, _, _ = run_rules(
            [
                _rule("r1", "people", "email", "NOT NULL"),
                _rule("r2", "people", "city", "REFERENCE", values=["Tehran"]),
            ]
        )

        assert len(statements) == 1


class TestTheVerdictsSurviveBatching:
    """A cheaper engine that reports the wrong issues is worse than a slow one."""

    def test_the_same_issues_are_raised(self, run_rules: RunRules) -> None:
        """Ground truth, hand-counted from the seeded literal.

        ``email`` is NULL on row 2, so NOT NULL fails. ``age`` is 200 on row
        2, outside 0-120, so RANGE fails. ``email`` repeats ``a@b.com``, so
        UNIQUE fails. ``city`` holds ``Atlantis``, absent from the reference
        list, so REFERENCE fails. ``id`` is the primary key, so its NOT NULL
        passes.
        """
        _, issues, _ = run_rules(
            [
                _rule("r1", "people", "email", "NOT NULL"),
                _rule("r2", "people", "age", "RANGE", min=0, max=120),
                _rule("r3", "people", "email", "UNIQUE"),
                _rule("r4", "people", "city", "REFERENCE", values=["Tehran"]),
                _rule("r5", "people", "id", "NOT NULL"),
            ]
        )

        assert {issue.rule_name for issue in issues} == {"r1", "r2", "r3", "r4"}

    def test_each_check_reads_back_its_own_numbers(self, run_rules: RunRules) -> None:
        """Slicing one row into several verdicts is where an off-by-one hides.

        Every count below is hand-derived from the seeded literal: three
        rows, one NULL email, one age out of range, one duplicated email.
        """
        _, issues, _ = run_rules(
            [
                _rule("r1", "people", "email", "NOT NULL"),
                _rule("r2", "people", "age", "RANGE", min=0, max=120),
                _rule("r3", "people", "email", "UNIQUE"),
            ]
        )
        by_rule = {issue.rule_name: issue.evidence for issue in issues}

        assert by_rule["r1"] == {"null_count": 1, "total_rows": 3}
        assert by_rule["r2"]["out_of_range_count"] == 1
        assert by_rule["r3"]["duplicate_extra_rows"] == 1

    def test_every_rule_still_gets_a_summary(self, run_rules: RunRules) -> None:
        """One RuleRunResult per rule, passing or failing, as before.

        Batching changes the order work happens in, and the summaries are
        keyed by rule rather than by query -- so this pins that they did not
        become one summary per batch.
        """
        _, _, summaries = run_rules(
            [
                _rule("r1", "people", "email", "NOT NULL"),
                _rule("r2", "people", "id", "NOT NULL"),
                _rule("r3", "orders", "amount", "NOT NULL"),
            ]
        )

        assert [summary.rule_name for summary in summaries] == ["r1", "r2", "r3"]
        assert [summary.targets_checked for summary in summaries] == [1, 1, 1]
        assert [summary.targets_failed for summary in summaries] == [1, 0, 1]


class TestOneBadRuleDoesNotBlankTheTable:
    """The risk batching introduces, and the answer to it."""

    def test_a_failing_check_leaves_the_others_reporting(self, run_rules: RunRules) -> None:
        """A rule the database rejects must cost only its own verdict.

        Before batching, each rule ran alone and a bad one hurt only itself.
        Sharing a query means one unparseable expression fails a statement
        several rules were relying on, so DQT retries the batch one check at
        a time. Without that, a typo in one rule would blank a table's whole
        report -- a far worse regression than the scans it saved.

        A ``RANGE`` over a text column is the vehicle: SQLite compares it
        without complaint, so the rule that must fail here is the one whose
        parameters cannot be compiled at all.
        """
        _, issues, summaries = run_rules(
            [
                _rule("r1", "people", "email", "NOT NULL"),
                _rule("r2", "people", "age", "RANGE"),
                _rule("r3", "people", "email", "UNIQUE"),
            ]
        )
        by_rule = {issue.rule_name: issue for issue in issues}

        assert by_rule["r1"].evidence == {"null_count": 1, "total_rows": 3}
        assert by_rule["r3"].evidence["duplicate_extra_rows"] == 1
        assert "params.min" in by_rule["r2"].message
        assert [s.targets_error for s in summaries] == [0, 1, 0]

class TestAReferenceTableWithRepeatsDoesNotInflateTheCounts:
    """Found while compiling the join into a fragment.

    A ``LEFT JOIN`` against a reference column holding the same value twice
    matches each data row twice, so the "how many did we check" denominator
    counts it twice. The number is then wrong in the direction that hides
    problems: a column can appear cleaner than it is because its denominator
    grew.
    """

    def test_duplicate_reference_rows_are_counted_once(
        self, make_sqlite_db: Callable[[str, str], Path]
    ) -> None:
        """Three rows checked, whatever the reference table repeats.

        ``Tehran`` is listed twice below. Without a de-duplicating join the
        two Tehran rows in ``people`` each match twice, and the denominator
        reads five instead of three.
        """
        script = """
            CREATE TABLE ref_cities (name TEXT);
            INSERT INTO ref_cities (name) VALUES ('Tehran'), ('Tehran'), ('Shiraz');
            CREATE TABLE people (id INTEGER PRIMARY KEY, city TEXT);
            INSERT INTO people (id, city) VALUES (1, 'Tehran'), (2, 'Tehran'), (3, 'Atlantis');
        """
        db_file = make_sqlite_db("refdupes.db", script)
        config = ConnectionConfig(id="refdupes", dsn=f"sqlite:///{db_file}")
        tables = [t for t in discover_schema(config) if t.table_name == "people"]

        issues, _ = apply_rules(
            run_id="run-refdupes",
            connection_config=config,
            rules=[
                _rule(
                    "r1",
                    "people",
                    "city",
                    "REFERENCE",
                    reference_table="ref_cities",
                    reference_column="name",
                )
            ],
            discovered_tables=tables,
        )

        assert issues[0].evidence["checked_rows"] == 3
        assert issues[0].evidence["unmatched_count"] == 1
