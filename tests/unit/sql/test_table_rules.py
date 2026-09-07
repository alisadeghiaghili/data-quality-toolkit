"""Table-level rules (`F5`).

Every rule DQT could express was about one column. `RuleScope` has always
had a `column_pattern` that may be omitted, and the matcher has always
handled a `None` column, but nothing ever compiled a check at table scope --
so `dqt_competitors.md` recorded F5 as `NOT MET` with the note "column scope
only".

The three added here are the three F5 names, in the safe form of each:

* **`UNIQUE_TOGETHER`** -- duplication. A composite key that the schema does
  not declare. `(order_id, line_no)` being unique is a constraint a DBA
  knows and the database often does not.
* **`FOREIGN_KEY`** -- referential integrity, *declared* rather than
  discovered. `F2` finds orphans behind constraints the database enforces;
  this finds them behind the relationships it does not, which is where they
  actually accumulate.
* **`CONDITIONAL_NOT_NULL`** -- a conditional constraint. "When `status` is
  `shipped`, `shipped_at` must be set" is the shape of most real ones.

**None of them takes SQL from the user.** Column and table names go through
the dialect's quoting path and values are bound parameters, which is
`AGENTS.md`'s SQL-safety rule with no exceptions. A rule carrying a raw
predicate would be more expressive and would hand a config file the ability
to write arbitrary SQL; that remains undecided in `docs/BACKLOG.md` §3 and is
not settled here by implementing it.

**Cost.** Table-level checks ride in the *same* aggregate statement as the
column-level ones, as scalar subqueries. One round trip per table either
way. The subqueries do group internally, so the engine reads more than the
single pass a plain aggregate needs -- but no extra statement, and no rule
gets a scan of its own.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from dqt.common.models import ConnectionConfig, RuleConfig, RuleScope
from dqt.sql.rules import apply_rules
from dqt.sql.schema_discovery import discover_schema

# Hand-derived from the rows below:
#   (order_id, line_no) : (1,1) appears twice -> ONE duplicated combination,
#                         even though neither column alone is unique.
#   customer_id         : 77 has no customer -> ONE orphan. NULL is not one.
#   status/shipped_at   : row 4 is 'shipped' with no shipped_at -> ONE breach.
#                         Row 5 is 'pending' with no shipped_at, which is fine.
SEEDED = """
    CREATE TABLE customers (id INTEGER PRIMARY KEY);
    CREATE TABLE order_lines (
        id INTEGER PRIMARY KEY,
        order_id INTEGER,
        line_no INTEGER,
        customer_id INTEGER,
        status TEXT,
        shipped_at TEXT
    );
    INSERT INTO customers (id) VALUES (1), (2);
    INSERT INTO order_lines (id, order_id, line_no, customer_id, status, shipped_at) VALUES
        (1, 1, 1, 1,    'shipped', '2026-01-01'),
        (2, 1, 2, 2,    'shipped', '2026-01-02'),
        (3, 2, 1, 77,   'pending', NULL),
        (4, 1, 1, NULL, 'shipped', NULL),
        (5, 3, 1, 1,    'pending', NULL);
"""


def _run(
    make_sqlite_db: Callable[[str, str], Path], name: str, rule: RuleConfig
) -> tuple[list[object], list[object]]:
    """Evaluate one rule against the seeded database.

    Args:
        make_sqlite_db: Factory fixture building a SQLite file.
        name: Distinct database filename.
        rule: The rule to evaluate.

    Returns:
        The issues and the per-rule summaries.

    Example:
        issues, runs = _run(make_sqlite_db, "a.db", rule)
    """
    db_file = make_sqlite_db(name, SEEDED)
    config = ConnectionConfig(id="s", dsn=f"sqlite:///{db_file}")
    return apply_rules("run-1", config, [rule], discover_schema(config))


def _rule(expression: str, params: dict[str, object]) -> RuleConfig:
    """Build a table-scoped rule against ``order_lines``.

    Args:
        expression: The rule expression.
        params: Its parameters.

    Returns:
        The rule.

    Example:
        rule = _rule("UNIQUE_TOGETHER", {"columns": ["order_id"]})
    """
    return RuleConfig(
        name=expression.lower(),
        dimension="uniqueness",
        severity="error",
        scope=RuleScope(table_pattern="order_lines"),
        expression=expression,
        params=params,
    )


class TestUniqueTogether:
    """A composite key the database does not declare."""

    def test_a_duplicated_combination_is_reported(
        self, make_sqlite_db: Callable[[str, str], Path]
    ) -> None:
        """``(1, 1)`` appears twice. Neither column alone is unique.

        That is the whole reason this cannot be expressed as two column
        rules: ``order_id`` repeats legitimately, ``line_no`` repeats
        legitimately, and only the pair is a constraint.
        """
        issues, _ = _run(
            make_sqlite_db,
            "unique-together.db",
            _rule("UNIQUE_TOGETHER", {"columns": ["order_id", "line_no"]}),
        )

        assert len(issues) == 1
        assert "1" in issues[0].message  # type: ignore[attr-defined]

    def test_a_genuinely_unique_combination_passes(
        self, make_sqlite_db: Callable[[str, str], Path]
    ) -> None:
        """``(id, order_id)`` is unique because ``id`` is a primary key."""
        issues, _ = _run(
            make_sqlite_db,
            "unique-together-clean.db",
            _rule("UNIQUE_TOGETHER", {"columns": ["id", "order_id"]}),
        )

        assert issues == []

    def test_it_runs_once_for_the_table_not_once_per_column(
        self, make_sqlite_db: Callable[[str, str], Path]
    ) -> None:
        """A table-scoped rule has one target, whatever the column count.

        ``order_lines`` has six columns. A rule compiled per column would
        report six targets and evaluate the same check six times.
        """
        _, runs = _run(
            make_sqlite_db,
            "unique-together-targets.db",
            _rule("UNIQUE_TOGETHER", {"columns": ["order_id", "line_no"]}),
        )

        assert runs[0].targets_checked == 1  # type: ignore[attr-defined]

    def test_a_missing_column_list_is_refused(
        self, make_sqlite_db: Callable[[str, str], Path]
    ) -> None:
        """A rule that cannot describe a check must not pass silently.

        Reported as an error issue rather than raised, matching how every
        other malformed rule behaves -- one bad rule does not abort a run.
        """
        issues, runs = _run(
            make_sqlite_db, "unique-together-empty.db", _rule("UNIQUE_TOGETHER", {})
        )

        assert runs[0].targets_error == 1  # type: ignore[attr-defined]
        assert issues


class TestForeignKeyRule:
    """Referential integrity for relationships the database does not enforce."""

    def test_an_orphan_is_reported(self, make_sqlite_db: Callable[[str, str], Path]) -> None:
        """``customer_id`` 77 has no customer, and no constraint says so.

        `F2` finds orphans behind declared constraints. This finds them
        behind the ones nobody declared, which is where they accumulate --
        an undeclared relationship is exactly the one nothing was protecting.
        """
        issues, _ = _run(
            make_sqlite_db,
            "fk-rule.db",
            _rule(
                "FOREIGN_KEY",
                {
                    "columns": ["customer_id"],
                    "references_table": "customers",
                    "references_columns": ["id"],
                },
            ),
        )

        assert len(issues) == 1
        assert "1" in issues[0].message  # type: ignore[attr-defined]

    def test_a_null_reference_is_not_an_orphan(
        self, make_sqlite_db: Callable[[str, str], Path]
    ) -> None:
        """Row 4 has no ``customer_id``. The count is 1, not 2.

        The same rule `F2` had to get right, restated here because this is a
        different code path and would fail the same way.
        """
        issues, _ = _run(
            make_sqlite_db,
            "fk-rule-null.db",
            _rule(
                "FOREIGN_KEY",
                {
                    "columns": ["customer_id"],
                    "references_table": "customers",
                    "references_columns": ["id"],
                },
            ),
        )

        assert "2" not in issues[0].message  # type: ignore[attr-defined]


class TestConditionalNotNull:
    """The shape most real conditional constraints take."""

    def test_a_breach_is_reported(self, make_sqlite_db: Callable[[str, str], Path]) -> None:
        """Row 4 is ``shipped`` with no ``shipped_at``. One breach.

        Rows 3 and 5 are ``pending`` with no ``shipped_at``, which is
        correct and must not be counted -- the condition is what makes this
        different from a plain NOT NULL rule.
        """
        issues, _ = _run(
            make_sqlite_db,
            "conditional.db",
            _rule(
                "CONDITIONAL_NOT_NULL",
                {"when_column": "status", "when_equals": "shipped", "then_column": "shipped_at"},
            ),
        )

        assert len(issues) == 1
        assert "1" in issues[0].message  # type: ignore[attr-defined]

    def test_rows_failing_the_condition_are_ignored(
        self, make_sqlite_db: Callable[[str, str], Path]
    ) -> None:
        """Nothing is ``cancelled``, so nothing is required and nothing fails."""
        issues, _ = _run(
            make_sqlite_db,
            "conditional-none.db",
            _rule(
                "CONDITIONAL_NOT_NULL",
                {
                    "when_column": "status",
                    "when_equals": "cancelled",
                    "then_column": "shipped_at",
                },
            ),
        )

        assert issues == []


class TestNoRuleTakesRawSql:
    """`AGENTS.md`'s SQL-safety rule, applied to the surface that most invites breaking it."""

    def test_the_value_is_bound_and_not_interpolated(
        self, make_sqlite_db: Callable[[str, str], Path]
    ) -> None:
        """A value that would break out of a quoted literal must not.

        If ``when_equals`` were interpolated, this value would close the
        string and comment out the rest of the statement. It is a bound
        parameter, so it is simply a value that matches nothing.
        """
        issues, runs = _run(
            make_sqlite_db,
            "conditional-injection.db",
            _rule(
                "CONDITIONAL_NOT_NULL",
                {
                    "when_column": "status",
                    "when_equals": "shipped' OR '1'='1",
                    "then_column": "shipped_at",
                },
            ),
        )

        assert runs[0].targets_error == 0  # type: ignore[attr-defined]
        assert issues == []

    def test_a_column_name_that_is_not_a_column_is_refused(
        self, make_sqlite_db: Callable[[str, str], Path]
    ) -> None:
        """Identifiers cannot be bound, so they are validated against the table.

        Quoting alone would turn ``x"; DROP TABLE`` into a harmless quoted
        name, but it would also let a rule name a column that does not exist
        and fail as a driver error mid-scan. Checking membership first
        reports it as the configuration mistake it is.
        """
        _, runs = _run(
            make_sqlite_db,
            "unique-together-bad-column.db",
            _rule("UNIQUE_TOGETHER", {"columns": ["order_id", 'x"; DROP TABLE customers; --']}),
        )

        assert runs[0].targets_error == 1  # type: ignore[attr-defined]
