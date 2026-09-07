"""Validity and timeliness diagnostics (`F3`, second half).

The last two of the six dimensions, and they differ from the other four in a
way worth stating rather than papering over: **DQT cannot measure either
without being told what to expect.**

Completeness, uniqueness, consistency and referential integrity are all
answerable from the data alone -- a NULL is a NULL, a duplicate is a
duplicate, a broken reference is broken. Validity and timeliness are not.
Whether `"n/a"` is a valid email depends on what the column is *for*, and
whether a table last written to ninety days ago is stale depends on whether
it is a ledger or an archive.

So neither invents a default:

* **Validity** is measured when classification is enabled. A column the
  validators recognise as email at 96% has 4% that are not emails, and that
  is a validity finding DQT can stand behind. Without classification there is
  no expectation to test against, and `RANGE` and `REGEX` rules remain the
  other way to supply one.
* **Timeliness** reports the age of the newest row as a **measurement**
  always, and scores it as a **judgement** only when a maximum age is
  configured. `DQMetric` carries exactly one of `metric_name` or `dimension`
  precisely so that a number and a verdict cannot be confused, and this is
  the case that distinction was made for.

Inventing a threshold -- "thirty days is stale" -- would produce confident
findings about tables DQT knows nothing about, which is the failure mode this
whole project is organised against.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from dqt.common.models import (
    ClassificationConfig,
    ConnectionConfig,
    DQPipelineConfig,
    TimelinessConfig,
)
from dqt.sql.pipeline import DQTPipeline

# `contact` holds four values: three are addresses, one is not. A validator
# run over them matches 3 of 4, so 25% of the column is invalid -- derived
# from the literal, not from the classifier.
VALIDITY_SEEDED = """
    CREATE TABLE people (id INTEGER PRIMARY KEY, contact TEXT);
    INSERT INTO people (id, contact) VALUES
        (1, 'ali@example.com'),
        (2, 'sara@example.com'),
        (3, 'reza@example.com'),
        (4, 'not-an-address');
"""


def _run(
    make_sqlite_db: Callable[[str, str], Path],
    tmp_path: Path,
    name: str,
    sql: str,
    config: DQPipelineConfig | None = None,
) -> object:
    """Run the pipeline over a seeded database.

    Args:
        make_sqlite_db: Factory fixture building a SQLite file.
        tmp_path: pytest's per-test directory.
        name: Distinct database filename.
        sql: Schema and data to seed.
        config: Pipeline settings, or None for the defaults.

    Returns:
        The :class:`~dqt.common.models.PipelineResult`.

    Example:
        result = _run(make_sqlite_db, tmp_path, "a.db", SQL)
    """
    db_file = make_sqlite_db(name, sql)
    result, _ = DQTPipeline(
        ConnectionConfig(id="s", dsn=f"sqlite:///{db_file}"),
        config or DQPipelineConfig(connection_id="s"),
        store_path=tmp_path / "runs.db",
        report_dir=tmp_path,
    ).run()
    return result


class TestValidityComesFromClassification:
    """An expectation has to exist before conformity to it can be measured."""

    def test_values_that_do_not_fit_the_detected_type_are_reported(
        self, make_sqlite_db: Callable[[str, str], Path], tmp_path: Path
    ) -> None:
        """Three of four are addresses, so one value is invalid.

        This is the finding a generic profiler cannot produce: the column is
        not empty, not duplicated and not inconsistent. It simply contains
        something that is not the thing the column is for.
        """
        result = _run(
            make_sqlite_db,
            tmp_path,
            "validity.db",
            VALIDITY_SEEDED,
            DQPipelineConfig(
                connection_id="s",
                classification=ClassificationConfig(enabled=True, minimum_match_ratio=0.5),
            ),
        )
        issues = [i for i in result.issues if i.dimension == "validity"]  # type: ignore[attr-defined]

        assert [i.column_name for i in issues] == ["contact"]
        assert "1" in issues[0].message

    def test_a_column_that_fits_perfectly_raises_nothing(
        self, make_sqlite_db: Callable[[str, str], Path], tmp_path: Path
    ) -> None:
        """The control. A check that always fires says nothing."""
        sql = """
            CREATE TABLE people (id INTEGER PRIMARY KEY, contact TEXT);
            INSERT INTO people (id, contact) VALUES (1, 'a@b.com'), (2, 'c@d.com');
        """
        result = _run(
            make_sqlite_db,
            tmp_path,
            "validity-clean.db",
            sql,
            DQPipelineConfig(connection_id="s", classification=ClassificationConfig(enabled=True)),
        )

        assert not [i for i in result.issues if i.dimension == "validity"]  # type: ignore[attr-defined]

    def test_an_unrecognised_column_is_not_called_invalid(
        self, make_sqlite_db: Callable[[str, str], Path], tmp_path: Path
    ) -> None:
        """Prose matches no validator, and that is not a quality problem.

        A column classified ``unknown`` has no expectation attached, so
        every value in it would count as a mismatch. Reporting that as 100%
        invalid would make free-text columns the worst-scoring thing in
        every database DQT is pointed at.
        """
        sql = """
            CREATE TABLE people (id INTEGER PRIMARY KEY, note TEXT);
            INSERT INTO people (id, note) VALUES (1, 'called them back'), (2, 'no answer');
        """
        result = _run(
            make_sqlite_db,
            tmp_path,
            "validity-prose.db",
            sql,
            DQPipelineConfig(connection_id="s", classification=ClassificationConfig(enabled=True)),
        )

        assert not [i for i in result.issues if i.dimension == "validity"]  # type: ignore[attr-defined]

    def test_without_classification_validity_is_not_measured(
        self, make_sqlite_db: Callable[[str, str], Path], tmp_path: Path
    ) -> None:
        """Absent, not 1.0.

        Scoring an unmeasured dimension as perfect is the one outcome worse
        than leaving it blank: it is a clean bill of health for a check that
        never ran.
        """
        result = _run(make_sqlite_db, tmp_path, "validity-off.db", VALIDITY_SEEDED)
        dimensions = {m.dimension for m in result.metrics}  # type: ignore[attr-defined]

        assert "validity" not in dimensions


class TestTimelinessMeasuresBeforeItJudges:
    """A number needs no threshold. A verdict does."""

    def test_the_age_of_the_newest_row_is_always_reported(
        self, make_sqlite_db: Callable[[str, str], Path], tmp_path: Path
    ) -> None:
        """A measurement, so it carries ``metric_name`` and no dimension.

        DQT can say "the newest row is 40 days old" without being told
        anything. It cannot say whether that is bad.
        """
        result = _run(make_sqlite_db, tmp_path, "timeliness-measure.db", _dated_sql(40))
        ages = [
            m
            for m in result.metrics  # type: ignore[attr-defined]
            if m.metric_name == "max_age_days" and m.column_name == "updated_at"
        ]

        assert ages, "no age measurement was produced"
        assert 39 <= float(ages[0].value or 0) <= 41

    def test_it_is_not_scored_without_a_threshold(
        self, make_sqlite_db: Callable[[str, str], Path], tmp_path: Path
    ) -> None:
        """Whether 40 days is stale depends on whether this is a ledger or an archive.

        Inventing a default would produce confident findings about tables DQT
        knows nothing about.
        """
        result = _run(make_sqlite_db, tmp_path, "timeliness-unjudged.db", _dated_sql(40))
        dimensions = {m.dimension for m in result.metrics}  # type: ignore[attr-defined]

        assert "timeliness" not in dimensions

    def test_a_configured_maximum_age_turns_it_into_a_verdict(
        self, make_sqlite_db: Callable[[str, str], Path], tmp_path: Path
    ) -> None:
        """40 days old against a 7-day maximum is stale."""
        result = _run(
            make_sqlite_db,
            tmp_path,
            "timeliness-stale.db",
            _dated_sql(40),
            DQPipelineConfig(connection_id="s", timeliness=TimelinessConfig(max_age_days=7)),
        )
        issues = [i for i in result.issues if i.dimension == "timeliness"]  # type: ignore[attr-defined]

        assert [i.column_name for i in issues] == ["updated_at"]

    def test_fresh_data_passes_the_same_threshold(
        self, make_sqlite_db: Callable[[str, str], Path], tmp_path: Path
    ) -> None:
        """The control, and the case that proves the threshold is read."""
        result = _run(
            make_sqlite_db,
            tmp_path,
            "timeliness-fresh.db",
            _dated_sql(1),
            DQPipelineConfig(connection_id="s", timeliness=TimelinessConfig(max_age_days=7)),
        )

        assert not [i for i in result.issues if i.dimension == "timeliness"]  # type: ignore[attr-defined]
        assert "timeliness" in {m.dimension for m in result.metrics}  # type: ignore[attr-defined]

    def test_a_column_that_holds_no_dates_is_left_alone(
        self, make_sqlite_db: Callable[[str, str], Path], tmp_path: Path
    ) -> None:
        """``name`` is text that is not a date, and has no age.

        Reading a name as a timestamp would produce an age for every text
        column in the database, most of them nonsense.
        """
        result = _run(
            make_sqlite_db,
            tmp_path,
            "timeliness-text.db",
            _dated_sql(3),
            DQPipelineConfig(connection_id="s", timeliness=TimelinessConfig(max_age_days=7)),
        )
        aged = {
            m.column_name
            for m in result.metrics  # type: ignore[attr-defined]
            if m.metric_name == "max_age_days"
        }

        assert "name" not in aged


def _dated_sql(days_old: int) -> str:
    """Seed a table whose newest row is *days_old* days in the past.

    Computed from the clock at call time rather than hard-coded, because a
    fixed date would silently become "very stale" and stop testing the
    threshold at all.

    Args:
        days_old: Age of the newest row, in days.

    Returns:
        The seeding SQL.

    Example:
        sql = _dated_sql(40)
    """
    newest = (datetime.now(UTC) - timedelta(days=days_old)).strftime("%Y-%m-%d %H:%M:%S")
    older = (datetime.now(UTC) - timedelta(days=days_old + 30)).strftime("%Y-%m-%d %H:%M:%S")
    return f"""
        CREATE TABLE events (id INTEGER PRIMARY KEY, name TEXT, updated_at TIMESTAMP);
        INSERT INTO events (id, name, updated_at) VALUES
            (1, 'alpha', '{older}'),
            (2, 'beta',  '{newest}');
    """
