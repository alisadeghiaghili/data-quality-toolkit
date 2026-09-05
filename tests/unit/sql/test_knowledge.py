"""Validating a column against reference data (Knowledge/Domain facet).

The last facet in ``docs/CONVENTIONS-DQT.md`` §2 with no code behind it, and
`docs/API-STABILITY.md` names it as a `1.0.0` blocker: freezing an API while
the facet table still reads "not started" would mean either adding to a
frozen surface later or admitting the model overstated what DQT does.

**What the facet is.** A reference set is the authoritative list of values a
column is allowed to hold -- a currency table, a branch code list, the
provinces of a country. Checking a column against one is validity, and it is
the check a DBA reaches for that neither ``regex`` nor ``RANGE`` can express.

Two sources, because two things are genuinely different:

* A **table in the same database**, which is the scalable form. The check is
  an anti-join computed in the database, so a hundred-million-row table is
  matched against a reference table by the query planner rather than by
  Python.
* An **inline list**, for a vocabulary small enough to write in the rule file
  -- status codes, a handful of flags. Bound as parameters, never
  interpolated: ``DQT-02`` established that a rule literal comes from user
  input and a reference value is no different.

**What DQT does not ship.** No reference *data*. A data-quality tool
carrying its own country list is one stale release away from reporting
correct data as invalid, and a false positive on a DBA's clean table costs
more trust than the convenience is worth. DQT provides the mechanism and the
DBA provides the authority.

**Persian folding is opt-in and belongs here.** ``شیراز`` written with an
Arabic yeh is the same city as ``شیراز`` written with a Persian one, and a
reference check that calls them different values reports a data-quality
problem that does not exist. The folding is the one in
``dqt.classification``, pushed into SQL as ``REPLACE`` so the comparison
still happens in the database. It is a parameter of the check, never a
default, for the reason ``classification`` gives: changing values silently
is not a data-quality tool's job.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from dqt.classification import PERSIAN_FOLD_RULES, normalize_persian_text
from dqt.common.models import ConnectionConfig, DQIssue, RuleConfig, RuleScope
from dqt.sql.dialects import get_dialect_by_name
from dqt.sql.knowledge import (
    ReferenceList,
    ReferenceTable,
    persian_fold_expression,
    reference_set_from_params,
    unmatched_count_query,
)
from dqt.sql.rules import apply_rules
from dqt.sql.schema_discovery import discover_schema

SQLITE = get_dialect_by_name("sqlite")


class TestAReferenceSetIsReadFromTheRuleParameters:
    """One of two shapes, and saying neither or both is a config error."""

    def test_a_table_reference_names_its_column(self) -> None:
        """The scalable form: point at a table already in the database."""
        reference = reference_set_from_params(
            {"reference_table": "ref_cities", "reference_column": "name"}
        )

        assert reference == ReferenceTable(
            table_name="ref_cities", column_name="name", schema_name=None
        )

    def test_a_table_reference_may_live_in_another_schema(self) -> None:
        """Reference data usually does not sit beside the data it governs."""
        reference = reference_set_from_params(
            {
                "reference_table": "cities",
                "reference_column": "name",
                "reference_schema": "master",
            }
        )

        assert reference == ReferenceTable(
            table_name="cities", column_name="name", schema_name="master"
        )

    def test_an_inline_list_is_read_as_written(self) -> None:
        """Small vocabularies belong in the rule file, not in a table."""
        reference = reference_set_from_params({"values": ["OPEN", "CLOSED"]})

        assert reference == ReferenceList(values=("OPEN", "CLOSED"))

    def test_naming_neither_is_refused(self) -> None:
        """A reference check with no reference cannot be evaluated.

        Passing everything would be worse than failing: a rule that reports
        a clean column because it was never told what to compare against is
        a false clean bill of health.
        """
        with pytest.raises(ValueError, match="reference_table"):
            reference_set_from_params({})

    def test_naming_both_is_refused(self) -> None:
        """Two answers to one question, and DQT will not pick for the DBA."""
        with pytest.raises(ValueError, match="both"):
            reference_set_from_params(
                {"values": ["A"], "reference_table": "t", "reference_column": "c"}
            )

    def test_an_empty_list_is_refused(self) -> None:
        """An empty reference set makes every value a violation.

        Almost certainly a config that failed to load rather than a DBA who
        meant "nothing is allowed", so it is refused by name.
        """
        with pytest.raises(ValueError, match="empty"):
            reference_set_from_params({"values": []})

    def test_a_table_without_its_column_is_refused(self) -> None:
        """Half a reference is not a reference."""
        with pytest.raises(ValueError, match="reference_column"):
            reference_set_from_params({"reference_table": "ref_cities"})


class TestTheQueryIsSetBasedAndBound:
    """One statement, no correlated subquery, no interpolated value."""

    def test_an_inline_list_binds_every_value(self) -> None:
        """Values are parameters, exactly as rule literals are.

        ``DQT-02`` parameterised rule bounds because they come from a config
        file a person edits. A reference value comes from the same file.
        """
        sql, binds = unmatched_count_query(
            SQLITE, None, "people", "city", ReferenceList(values=("Tehran", "Shiraz"))
        )

        assert binds == ("Tehran", "Shiraz")
        assert "Tehran" not in sql
        assert sql.count("?") == 2

    def test_an_inline_list_counts_what_is_absent_from_it(self) -> None:
        """``NOT IN`` over the bound values, with NULL excluded.

        A NULL is "not applicable", not "invalid" -- the same reading
        ``regex_not_matching_predicate`` takes. Counting NULLs here would
        make every completeness problem a validity problem too.
        """
        sql, _ = unmatched_count_query(
            SQLITE, None, "people", "city", ReferenceList(values=("Tehran",))
        )
        flattened = " ".join(sql.split())

        assert "NOT IN" in flattened
        assert '"city" IS NOT NULL' in flattened

    def test_a_table_reference_is_an_anti_join(self) -> None:
        """A LEFT JOIN, not a value-list subquery.

        ``NOT IN (SELECT ...)`` would also be one statement, but a single
        NULL in the reference column makes the whole predicate UNKNOWN and
        the rule reports nothing wrong at all -- a false clean bill of
        health. The join is also the shape a planner can index.
        """
        sql, binds = unmatched_count_query(
            SQLITE,
            None,
            "people",
            "city",
            ReferenceTable(table_name="ref_cities", column_name="name"),
        )
        flattened = " ".join(sql.split())

        assert binds == ()
        assert "LEFT JOIN" in flattened
        assert flattened.split()[0] == "SELECT"
        assert "NOT IN (SELECT" not in flattened

    def test_the_reference_values_are_de_duplicated_before_joining(self) -> None:
        """A reference column may repeat a value; the denominator must not.

        Without ``SELECT DISTINCT`` a value listed twice matches each data
        row twice, so "how many did we check" grows and the column looks
        cleaner than it is -- the direction of error that hides problems.
        ``test_rules_grouped.py`` exercises the same thing against a
        database.
        """
        sql, _ = unmatched_count_query(
            SQLITE,
            None,
            "people",
            "city",
            ReferenceTable(table_name="ref_cities", column_name="name"),
        )
        flattened = " ".join(sql.split())

        assert "LEFT JOIN (SELECT DISTINCT" in flattened

    def test_the_reference_table_is_quoted(self) -> None:
        """Identifiers are quoted, values are bound -- the standing rule."""
        sql, _ = unmatched_count_query(
            SQLITE,
            None,
            "people",
            "city",
            ReferenceTable(table_name="ref cities", column_name="na me"),
        )

        assert '"ref cities"' in sql
        assert '"na me"' in sql


class TestPersianFoldingHappensInSql:
    """The comparison stays in the database, folded on both sides."""

    def test_the_fold_rules_agree_with_the_python_normalizer(self) -> None:
        """One source of truth, checked rather than assumed.

        ``persian_fold_expression`` builds nested ``REPLACE`` calls from the
        same rules ``normalize_persian_text`` applies. If the two ever
        disagreed, a value would pass in Python and fail in SQL, which is the
        worst kind of bug to find: the report would be right about a table
        DQT itself made look wrong.
        """
        samples = ["شیراز", "شيراز", "كرمان", "۰۹۱۲", "٠٩١٢", "می‌شود", "Tehran", ""]

        for sample in samples:
            folded = sample
            for source, replacement in PERSIAN_FOLD_RULES:
                folded = folded.replace(source, replacement)

            assert folded == normalize_persian_text(sample), sample

    def test_the_expression_replaces_rather_than_reads_rows(self) -> None:
        """``REPLACE`` is in all three dialects, so the fold is portable.

        Doing this in Python would mean reading every value out of the
        database to compare it, which is the thing DQT exists not to do.
        """
        expression = persian_fold_expression('"city"')

        assert expression.startswith("REPLACE(")
        assert '"city"' in expression
        assert expression.count("REPLACE(") == len(PERSIAN_FOLD_RULES)

    def test_folding_applies_to_both_sides_of_the_comparison(self) -> None:
        """Folding only the data would compare a folded value to a raw one.

        The reference table is written by people too, and there is no reason
        to assume it is the canonical side.
        """
        sql, _ = unmatched_count_query(
            SQLITE,
            None,
            "people",
            "city",
            ReferenceTable(table_name="ref_cities", column_name="name"),
            normalize_persian=True,
        )
        flattened = " ".join(sql.split())
        join_condition = flattened.split(" ON ", 1)[1]

        assert join_condition.count("REPLACE(") == 2 * len(PERSIAN_FOLD_RULES)

    def test_an_inline_list_is_folded_in_python_not_in_sql(self) -> None:
        """The allowed values are already known here, so SQL need not fold them.

        Wrapping each placeholder in twenty-odd ``REPLACE`` calls would ask
        the database to compute a constant, once per row. The column still
        folds in SQL, because its values are the ones DQT has not seen.
        """
        sql, binds = unmatched_count_query(
            SQLITE,
            None,
            "people",
            "city",
            ReferenceList(values=("شيراز",)),
            normalize_persian=True,
        )

        assert binds == ("شیراز",)
        assert sql.count("REPLACE(") == len(PERSIAN_FOLD_RULES)

    def test_folding_is_off_unless_asked(self) -> None:
        """Changing values silently is not a data-quality tool's job.

        ``dqt.classification`` makes the same choice for the same reason:
        normalization is a decision about the data, and the DBA makes it.
        """
        sql, _ = unmatched_count_query(
            SQLITE,
            None,
            "people",
            "city",
            ReferenceTable(table_name="ref_cities", column_name="name"),
        )

        assert "REPLACE(" not in sql


SEEDED = """
    CREATE TABLE ref_cities (name TEXT);
    INSERT INTO ref_cities (name) VALUES ('تهران'), ('شیراز'), ('Tehran');
    CREATE TABLE people (id INTEGER PRIMARY KEY, city TEXT);
    INSERT INTO people (id, city) VALUES
        (1, 'تهران'),
        (2, 'شيراز'),
        (3, 'Atlantis'),
        (4, NULL),
        (5, 'Tehran');
"""


def _reference_rule(**params: Any) -> RuleConfig:
    """Build a REFERENCE rule on ``people.city``.

    Args:
        **params: Rule parameters naming the reference set.

    Returns:
        A RuleConfig.

    Example:
        rule = _reference_rule(values=["Tehran"])
    """
    return RuleConfig(
        name="city-in-reference",
        dimension="validity",
        severity="error",
        scope=RuleScope(table_pattern="people", column_pattern="city"),
        expression="REFERENCE",
        params=params,
    )


@pytest.fixture
def run_rule(make_sqlite_db: Callable[[str, str], Path]) -> Callable[[RuleConfig], list[DQIssue]]:
    """Evaluate one rule against the seeded database.

    Args:
        make_sqlite_db: Factory fixture building a SQLite file.

    Returns:
        A callable taking a rule and returning the issues it raised.

    Example:
        issues = run_rule(_reference_rule(values=["Tehran"]))
    """
    counter = itertools.count()

    def _run(rule: RuleConfig) -> list[DQIssue]:
        db_file = make_sqlite_db(f"knowledge{next(counter)}.db", SEEDED)
        config = ConnectionConfig(id="knowledge", dsn=f"sqlite:///{db_file}")
        tables = [t for t in discover_schema(config) if t.table_name == "people"]
        issues, _ = apply_rules(
            run_id="run-knowledge",
            connection_config=config,
            rules=[rule],
            discovered_tables=tables,
        )
        return issues

    return _run


class TestTheRuleRunsAgainstADatabase:
    """Ground truth is hand-counted from the seeded literal above."""

    def test_values_absent_from_the_reference_table_are_reported(
        self, run_rule: Callable[[RuleConfig], list[DQIssue]]
    ) -> None:
        """Two of the four non-NULL cities are not in ``ref_cities``.

        ``تهران`` and ``Tehran`` are listed. ``شيراز`` is written with an
        Arabic yeh and the reference has the Persian one, so without folding
        it does not match. ``Atlantis`` is not there at all. Row 4 is NULL
        and is not checked.
        """
        issues = run_rule(_reference_rule(reference_table="ref_cities", reference_column="name"))

        assert issues[0].evidence["unmatched_count"] == 2
        assert issues[0].evidence["checked_rows"] == 4

    def test_folding_makes_the_arabic_spelling_match(
        self, run_rule: Callable[[RuleConfig], list[DQIssue]]
    ) -> None:
        """The same table, one parameter, one fewer false positive.

        ``شيراز`` and ``شیراز`` differ by one code point that carries no
        meaning. Reporting them as different values is a data-quality
        problem DQT would have invented.
        """
        issues = run_rule(
            _reference_rule(
                reference_table="ref_cities",
                reference_column="name",
                normalize_persian=True,
            )
        )

        assert issues[0].evidence["unmatched_count"] == 1
        assert issues[0].evidence["normalized"] is True

    def test_a_column_fully_covered_raises_nothing(
        self, run_rule: Callable[[RuleConfig], list[DQIssue]]
    ) -> None:
        """All five distinct non-NULL values listed, so no issue.

        The NULL row must not turn a clean column into a finding.
        """
        issues = run_rule(
            _reference_rule(values=["تهران", "شيراز", "Atlantis", "Tehran"]),
        )

        assert issues == []

    def test_an_inline_list_reports_what_is_missing_from_it(
        self, run_rule: Callable[[RuleConfig], list[DQIssue]]
    ) -> None:
        """Only ``Tehran`` allowed, so the other three non-NULL rows fail."""
        issues = run_rule(_reference_rule(values=["Tehran"]))

        assert issues[0].evidence["unmatched_count"] == 3
        assert issues[0].evidence["checked_rows"] == 4

    def test_an_inline_list_folds_too(
        self, run_rule: Callable[[RuleConfig], list[DQIssue]]
    ) -> None:
        """The seeded ``شيراز`` has an Arabic yeh; the rule writes a Persian one.

        Ground truth: four non-NULL cities, one of them Shiraz. With folding
        the rule's single allowed value matches it, so the other three fail.
        """
        issues = run_rule(_reference_rule(values=["شیراز"], normalize_persian=True))

        assert issues[0].evidence["unmatched_count"] == 3
        assert issues[0].evidence["checked_rows"] == 4

    def test_the_evidence_carries_counts_and_not_the_values(
        self, run_rule: Callable[[RuleConfig], list[DQIssue]]
    ) -> None:
        """A DQIssue must never materialise the violating set.

        The standing rule from ``test_rules_cost.py``: on a table where half
        the rows fail, evidence holding the offending values would put the
        report's size at the mercy of how bad the data is.
        """
        issues = run_rule(_reference_rule(values=["Tehran"]))

        assert set(issues[0].evidence) == {"unmatched_count", "checked_rows", "normalized"}
        assert isinstance(issues[0].evidence["unmatched_count"], int)

    def test_a_missing_reference_becomes_an_error_issue_not_a_crash(
        self, run_rule: Callable[[RuleConfig], list[DQIssue]]
    ) -> None:
        """A bad rule must not take the run down with it.

        The engine's standing contract: one unusable rule is reported as an
        error-severity issue naming it, and every other rule still runs.
        """
        issues = run_rule(_reference_rule())

        assert issues[0].severity == "error"
        assert "reference_table" in issues[0].message
