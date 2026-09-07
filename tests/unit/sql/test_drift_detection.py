"""Metric history and drift detection (`F8`).

`monitor()` returned its input unchanged. It has done so since the pipeline
was built, which made Monitoring a named facet that did nothing --
`ROADMAP-2.0.md` §1.4 called it "either a feature DQT owes or a facet DQT
should cut", and `1.0` shipped without deciding.

**It turned out not to be blocked.** That document said a metric-level trend
needed `run_metrics` queryable by metric identity, and recorded that whether
the schema supported it was *unverified*. It does: the table already carries
schema, table, column, dimension and metric name, and already has a unique
index on exactly that natural key. Nothing about the schema had to change,
so no store is refused and no history is deleted.

That is the second time a `2.0` entry was wrong in the same direction -- the
first was sampling, which shipped as `1.1.0`. Both were "this needs a schema
change", both reasoned from memory of the schema rather than from reading
it.

**What drift is, and what it is not.** A score falling from 0.98 to 0.72 is
a finding; a score falling from 0.980 to 0.979 is noise. DQT reports the
change **always**, as data on the metric, and raises an issue only against a
configured tolerance -- the same split `F3` made for timeliness, and for the
same reason: the size of drop that matters is a property of the table, not
of the number.

**A first run has no drift.** Not zero drift -- no drift. Reporting the
first observation of a metric as "unchanged" would put a flat line on every
trend chart's left edge and make a new column indistinguishable from a
stable one.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from dqt.common.models import ConnectionConfig, DQPipelineConfig, MonitoringConfig
from dqt.sql.pipeline import DQTPipeline

CLEAN = """
    CREATE TABLE people (id INTEGER PRIMARY KEY, email TEXT);
    INSERT INTO people (id, email) VALUES (1, 'a@x.com'), (2, 'b@x.com'),
                                          (3, 'c@x.com'), (4, 'd@x.com');
"""

# The same table with three of the four emails removed. Completeness for
# `email` falls from 1.0 to 0.25 -- hand-derived: one non-NULL of four rows.
DEGRADED = """
    CREATE TABLE people (id INTEGER PRIMARY KEY, email TEXT);
    INSERT INTO people (id, email) VALUES (1, 'a@x.com'), (2, NULL),
                                          (3, NULL), (4, NULL);
"""


def _run_twice(
    make_sqlite_db: Callable[[str, str], Path],
    tmp_path: Path,
    name: str,
    second_sql: str = DEGRADED,
    config: DQPipelineConfig | None = None,
) -> tuple[object, object]:
    """Run the pipeline twice against the same store, degrading in between.

    Two *different* database files sharing one store, because the point is a
    metric's history rather than a table's contents.

    Args:
        make_sqlite_db: Factory fixture building a SQLite file.
        tmp_path: pytest's per-test directory.
        name: Distinct database filename stem.
        second_sql: What the second run sees.
        config: Pipeline settings, or None for the defaults.

    Returns:
        The two :class:`~dqt.common.models.PipelineResult` objects, in order.

    Example:
        first, second = _run_twice(make_sqlite_db, tmp_path, "a")
    """
    store = tmp_path / "runs.db"
    settings = config or DQPipelineConfig(connection_id="s")

    first_db = make_sqlite_db(f"{name}-1.db", CLEAN)
    first, _ = DQTPipeline(
        ConnectionConfig(id="s", dsn=f"sqlite:///{first_db}"),
        settings,
        store_path=store,
        report_dir=tmp_path,
    ).run()

    second_db = make_sqlite_db(f"{name}-2.db", second_sql)
    second, _ = DQTPipeline(
        ConnectionConfig(id="s", dsn=f"sqlite:///{second_db}"),
        settings,
        store_path=store,
        report_dir=tmp_path,
    ).run()
    return first, second


def _email_completeness(result: object) -> object:
    """Find the ``email`` completeness metric in a result.

    Args:
        result: A PipelineResult.

    Returns:
        The metric.

    Example:
        metric = _email_completeness(result)
    """
    return next(
        metric
        for metric in result.metrics  # type: ignore[attr-defined]
        if metric.dimension == "completeness" and metric.column_name == "email"
    )


class TestTheStoreCanFollowOneMetric:
    """A trend needs a metric's own history, not a run's."""

    def test_a_metric_is_findable_across_runs(
        self, make_sqlite_db: Callable[[str, str], Path], tmp_path: Path
    ) -> None:
        """Identified by scope and dimension, which is what the unique index already keys on.

        `ROADMAP-2.0.md` recorded this as unverified and possibly needing a
        schema change. It needed none.
        """
        from dqt.common.storage import RunStore

        _run_twice(make_sqlite_db, tmp_path, "history")
        history = RunStore(db_path=tmp_path / "runs.db").load_metric_history(
            schema_name="main",
            table_name="people",
            column_name="email",
            dimension="completeness",
            metric_name=None,
        )

        assert [round(float(entry["score"]), 2) for entry in history] == [0.25, 1.0]

    def test_the_newest_observation_comes_first(
        self, make_sqlite_db: Callable[[str, str], Path], tmp_path: Path
    ) -> None:
        """Matches ``load_rule_history``, so a caller reading both is not surprised."""
        from dqt.common.storage import RunStore

        _run_twice(make_sqlite_db, tmp_path, "history-order")
        history = RunStore(db_path=tmp_path / "runs.db").load_metric_history(
            schema_name="main",
            table_name="people",
            column_name="email",
            dimension="completeness",
            metric_name=None,
        )

        assert float(history[0]["score"]) < float(history[1]["score"])


class TestDriftIsMeasuredAlways:
    """The number needs no threshold. Only the verdict does."""

    def test_a_metric_carries_its_previous_score(
        self, make_sqlite_db: Callable[[str, str], Path], tmp_path: Path
    ) -> None:
        """1.0 then 0.25, so the second run knows what the first said."""
        _, second = _run_twice(make_sqlite_db, tmp_path, "delta")
        metric = _email_completeness(second)

        assert metric.metadata["previous_score"] == 1.0  # type: ignore[attr-defined]
        assert metric.metadata["delta"] == -0.75  # type: ignore[attr-defined]

    def test_a_first_run_has_no_drift_rather_than_zero_drift(
        self, make_sqlite_db: Callable[[str, str], Path], tmp_path: Path
    ) -> None:
        """Absent, not 0.0.

        Zero would put a flat line on the left edge of every trend and make
        a column first seen today indistinguishable from one that has been
        stable for a year.
        """
        first, _ = _run_twice(make_sqlite_db, tmp_path, "first-run")
        metric = _email_completeness(first)

        assert "delta" not in (metric.metadata or {})  # type: ignore[attr-defined]

    def test_a_steady_metric_reports_no_change(
        self, make_sqlite_db: Callable[[str, str], Path], tmp_path: Path
    ) -> None:
        """Zero drift *is* the right answer once there is something to compare to.

        The pair to the test above: absent means no baseline, and 0.0 means
        measured and unchanged.
        """
        _, second = _run_twice(make_sqlite_db, tmp_path, "steady", second_sql=CLEAN)
        metric = _email_completeness(second)

        assert metric.metadata["delta"] == 0.0  # type: ignore[attr-defined]


class TestDriftIsJudgedOnlyWhenAsked:
    """How big a drop matters is a property of the table, not of the number."""

    def test_no_issue_without_a_configured_tolerance(
        self, make_sqlite_db: Callable[[str, str], Path], tmp_path: Path
    ) -> None:
        """A 0.75 drop, and still no finding.

        A default tolerance would produce confident alerts about tables DQT
        knows nothing about -- the same argument timeliness made, and the
        same answer.
        """
        _, second = _run_twice(make_sqlite_db, tmp_path, "undecided")

        assert not [i for i in second.issues if i.dimension and "drift" in i.message.lower()]  # type: ignore[attr-defined]

    def test_a_drop_past_the_tolerance_raises_an_issue(
        self, make_sqlite_db: Callable[[str, str], Path], tmp_path: Path
    ) -> None:
        """0.75 against a 0.1 tolerance."""
        _, second = _run_twice(
            make_sqlite_db,
            tmp_path,
            "alerting",
            config=DQPipelineConfig(
                connection_id="s", monitoring=MonitoringConfig(max_score_drop=0.1)
            ),
        )
        drift = [i for i in second.issues if "drift" in i.message.lower()]  # type: ignore[attr-defined]

        assert drift
        assert any(i.column_name == "email" for i in drift)

    def test_an_improvement_is_never_an_issue(
        self, make_sqlite_db: Callable[[str, str], Path], tmp_path: Path
    ) -> None:
        """Getting better by 0.75 is not a problem to report.

        A tolerance on the absolute change would fire here, which is the
        obvious implementation and the wrong one: nobody wants an alert
        because their data got cleaner.
        """
        store = tmp_path / "runs.db"
        settings = DQPipelineConfig(
            connection_id="s", monitoring=MonitoringConfig(max_score_drop=0.1)
        )
        bad = make_sqlite_db("improve-1.db", DEGRADED)
        DQTPipeline(
            ConnectionConfig(id="s", dsn=f"sqlite:///{bad}"),
            settings,
            store_path=store,
            report_dir=tmp_path,
        ).run()
        good = make_sqlite_db("improve-2.db", CLEAN)
        second, _ = DQTPipeline(
            ConnectionConfig(id="s", dsn=f"sqlite:///{good}"),
            settings,
            store_path=store,
            report_dir=tmp_path,
        ).run()

        assert not [i for i in second.issues if "drift" in i.message.lower()]
        assert _email_completeness(second).metadata["delta"] == 0.75  # type: ignore[attr-defined]

    def test_a_first_run_cannot_alert(
        self, make_sqlite_db: Callable[[str, str], Path], tmp_path: Path
    ) -> None:
        """There is nothing to have drifted from.

        Worth its own test because the natural implementation treats a
        missing baseline as 0.0 and alerts on every metric of every first
        run -- which is the run where a user is deciding whether to trust
        the tool.
        """
        first, _ = _run_twice(
            make_sqlite_db,
            tmp_path,
            "first-alert",
            config=DQPipelineConfig(
                connection_id="s", monitoring=MonitoringConfig(max_score_drop=0.1)
            ),
        )

        assert not [i for i in first.issues if "drift" in i.message.lower()]  # type: ignore[attr-defined]
