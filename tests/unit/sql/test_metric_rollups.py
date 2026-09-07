"""Dimension scores rolled up to table and run (`F7`).

F7 asks for scores "per table/column/dimension". Per-column arrived with
`F1`, `F2` and `F3`: uniqueness, consistency, validity, timeliness and
completeness all produce a `DQMetric` per column now. **Per table did not.**

The run-level number did exist, but not as data -- `RunStore` averaged the
column rows on the way out, inside a method the HTML screens call. Three
things follow from a rollup that lives in a read query rather than in the
metrics:

* **A JSON consumer that is not the dashboard has to redo it.** The six
  frozen endpoints hand out metrics; every reader has to know that a
  dimension's score means averaging the column rows, and has to agree on
  how.
* **There is no table-level score at all.** "Which of my forty tables is
  worst on completeness" is the question a DBA opens a data-quality tool
  to ask, and DQT could not answer it.
* **Nothing can be trended.** `run_metrics` is what the history reads, so a
  score that is only ever computed on the way out has no history. `F8`
  needs exactly this.

**The run-level number must not move.** It is on the dashboard today. The
rollup reproduces it -- a mean over the same rows -- rather than taking the
mean of table means, which would weigh a one-column table equally with a
forty-column one and quietly change every existing chart.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from dqt.common.models import ConnectionConfig, DQPipelineConfig
from dqt.sql.pipeline import DQTPipeline

# Two tables of deliberately different width, so a mean-of-means and a mean
# over all columns give different answers and the tests can tell them apart.
SEEDED = """
    CREATE TABLE wide (a TEXT, b TEXT, c TEXT, d TEXT);
    CREATE TABLE narrow (only_one TEXT);
    INSERT INTO wide (a, b, c, d) VALUES
        ('x', 'x', NULL, NULL),
        ('y', 'y', 'y',  NULL);
    INSERT INTO narrow (only_one) VALUES ('p'), ('q');
"""


def _metrics(make_sqlite_db: Callable[[str, str], Path], tmp_path: Path, name: str) -> list:
    """Run the pipeline and return its metrics.

    Args:
        make_sqlite_db: Factory fixture building a SQLite file.
        tmp_path: pytest's per-test directory.
        name: Distinct database filename.

    Returns:
        The run's metrics.

    Example:
        metrics = _metrics(make_sqlite_db, tmp_path, "a.db")
    """
    db_file = make_sqlite_db(name, SEEDED)
    result, _ = DQTPipeline(
        ConnectionConfig(id="s", dsn=f"sqlite:///{db_file}"),
        DQPipelineConfig(connection_id="s"),
        store_path=tmp_path / "runs.db",
        report_dir=tmp_path,
    ).run()
    return list(result.metrics)


def _scoped(metrics: list, dimension: str, scope: str) -> list:
    """Select rolled-up metrics of one dimension at one scope.

    Args:
        metrics: A run's metrics.
        dimension: Which dimension.
        scope: ``"table"`` or ``"run"``.

    Returns:
        The matching metrics.

    Example:
        rows = _scoped(metrics, "completeness", "table")
    """
    return [
        metric
        for metric in metrics
        if metric.dimension == dimension and (metric.metadata or {}).get("scope") == scope
    ]


class TestEveryTableIsScoredPerDimension:
    """ "Which of my forty tables is worst" is why a DBA opens the tool."""

    def test_each_table_gets_a_completeness_score(
        self, make_sqlite_db: Callable[[str, str], Path], tmp_path: Path
    ) -> None:
        """Both tables, not just the one with a problem.

        A table that scores 1.0 has to appear, or "best" and "not measured"
        become the same rendering.
        """
        rolled = _scoped(
            _metrics(make_sqlite_db, tmp_path, "rollup-tables.db"), "completeness", "table"
        )

        assert {metric.table_name for metric in rolled} == {"wide", "narrow"}

    def test_the_table_score_is_the_mean_of_its_own_columns(
        self, make_sqlite_db: Callable[[str, str], Path], tmp_path: Path
    ) -> None:
        """``wide`` holds 2 rows; a=0 nulls, b=0, c=1, d=2.

        Column completeness is 1.0, 1.0, 0.5, 0.0 -- hand-derived from the
        INSERT -- so the table's mean is 0.625. ``narrow`` has no NULLs and
        scores 1.0, which is what makes the two distinguishable.
        """
        metrics = _metrics(make_sqlite_db, tmp_path, "rollup-mean.db")
        by_table = {m.table_name: m.score for m in _scoped(metrics, "completeness", "table")}

        assert by_table["wide"] == 0.625
        assert by_table["narrow"] == 1.0

    def test_a_table_level_dimension_is_not_overwritten(
        self, make_sqlite_db: Callable[[str, str], Path], tmp_path: Path
    ) -> None:
        """Referential integrity is already scored per table by `F2`.

        Rolling columns up must not invent a second, different score for a
        dimension that was measured at table scope in the first place --
        there are no columns to average, and averaging none would produce
        either nothing or a divide by zero.
        """
        metrics = _metrics(make_sqlite_db, tmp_path, "rollup-existing.db")
        referential = [m for m in metrics if m.dimension == "referential_integrity"]

        assert len(referential) == len({(m.table_name, m.column_name) for m in referential})


class TestTheRunScoreDoesNotMove:
    """It is on the dashboard today, and a silent change to it is the worst outcome."""

    def test_it_is_the_mean_over_columns_not_the_mean_of_table_means(
        self, make_sqlite_db: Callable[[str, str], Path], tmp_path: Path
    ) -> None:
        """The two differ here, deliberately.

        Five columns score 1.0, 1.0, 0.5, 0.0, 1.0 -- mean 0.7. The mean of
        the table means is (0.625 + 1.0) / 2 = 0.8125, which would weigh a
        one-column table equally with a four-column one and quietly change
        every chart already drawn.
        """
        metrics = _metrics(make_sqlite_db, tmp_path, "rollup-run.db")
        run_level = _scoped(metrics, "completeness", "run")

        assert len(run_level) == 1
        assert run_level[0].score == 0.7

    def test_the_stored_rollup_matches_what_the_store_used_to_compute(
        self, make_sqlite_db: Callable[[str, str], Path], tmp_path: Path
    ) -> None:
        """The guarantee that nothing on the dashboard shifts.

        ``average_score_by_dimension`` is what the screens read. Its answer
        for a dimension must equal the stored run-level rollup, or the number
        depends on which of the two a caller happens to use.
        """
        from dqt.common.storage import RunStore

        db_file = make_sqlite_db("rollup-agree.db", SEEDED)
        store_path = tmp_path / "runs.db"
        result, _ = DQTPipeline(
            ConnectionConfig(id="s", dsn=f"sqlite:///{db_file}"),
            DQPipelineConfig(connection_id="s"),
            store_path=store_path,
            report_dir=tmp_path,
        ).run()

        computed = RunStore(db_path=store_path).average_score_by_dimension(result.run_id)
        stored = {
            m.dimension: m.score for m in _scoped(list(result.metrics), "completeness", "run")
        }

        assert computed["completeness"] == stored["completeness"]


class TestTheRollupIsFindable:
    """A metric nobody can select is a metric nobody has."""

    def test_rolled_up_rows_declare_their_scope(
        self, make_sqlite_db: Callable[[str, str], Path], tmp_path: Path
    ) -> None:
        """Without it, a table rollup is indistinguishable from a column score.

        Both carry a dimension, a table name and a score; only the absent
        column name would separate them, and relying on that means every
        consumer reimplements the distinction.
        """
        metrics = _metrics(make_sqlite_db, tmp_path, "rollup-scope.db")
        scopes = {(m.metadata or {}).get("scope") for m in metrics if m.dimension}

        assert "table" in scopes
        assert "run" in scopes

    def test_a_rollup_records_how_many_scores_it_averaged(
        self, make_sqlite_db: Callable[[str, str], Path], tmp_path: Path
    ) -> None:
        """A mean over one column and a mean over forty read identically.

        The count is what lets a reader tell a firm number from a thin one.
        """
        metrics = _metrics(make_sqlite_db, tmp_path, "rollup-count.db")
        wide = next(m for m in _scoped(metrics, "completeness", "table") if m.table_name == "wide")

        assert (wide.metadata or {}).get("rolled_up_from") == 4
