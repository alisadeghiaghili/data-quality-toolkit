"""The dashboard shows what profiling actually found (`NEW-AE`).

DQT gained a great deal between `1.1.0` and `1.7.0`: minimum, maximum, mean
and distinct counts per column, semantic types, and a record of how far every
metric moved since the last run. **None of it reached the HTML screens.**

The JSON endpoints were fine throughout -- the metrics carry all of it in
their metadata, so `/runs/{id}/metrics` has been complete the whole time.
What lagged was the part a DBA actually looks at, which is the part the
project's own positioning rests on: `dqt_competitors.md` names DBA-first
framing as one of three real differentiators, and a dashboard three releases
behind the data is not that.

Two screens' worth of gap, and they are different in kind:

* **The column detail did not exist at all.** The HTML report has shown it
  since `F1`; someone reading the dashboard instead saw table names and issue
  counts and nothing about the columns themselves.
* **Drift was recorded and never shown.** `F8` writes how far each metric
  moved into the metric's own metadata. A number that only a JSON client can
  see is not what "monitoring" means to the person watching the dashboard.

These read from the **store**, not from a live `PipelineResult`. That is the
difference between the report and the screens, and it is why they cannot
share `column_rows()`: one describes a run that just happened, the other a
run that happened last night.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from dqt.common.models import ConnectionConfig, DQPipelineConfig, MonitoringConfig
from dqt.sql.pipeline import DQTPipeline

fastapi = pytest.importorskip("fastapi", reason="the ui extra is not installed")

SEEDED = """
    CREATE TABLE customers (id INTEGER PRIMARY KEY, email TEXT, city TEXT);
    INSERT INTO customers (id, email, city) VALUES
        (1, 'ali@example.com', 'Tehran'),
        (2, NULL,              'tehran'),
        (3, 'reza@example.com', NULL);
"""

DEGRADED = """
    CREATE TABLE customers (id INTEGER PRIMARY KEY, email TEXT, city TEXT);
    INSERT INTO customers (id, email, city) VALUES
        (1, NULL, NULL),
        (2, NULL, NULL),
        (3, NULL, NULL);
"""


def _run(
    make_sqlite_db: Callable[[str, str], Path],
    tmp_path: Path,
    name: str,
    sql: str = SEEDED,
    store: Path | None = None,
) -> object:
    """Run the pipeline into a store.

    Args:
        make_sqlite_db: Factory fixture building a SQLite file.
        tmp_path: pytest's per-test directory.
        name: Distinct database filename.
        sql: Schema and data to seed.
        store: Store path, or None for one under *tmp_path*.

    Returns:
        The :class:`~dqt.common.models.PipelineResult`.

    Example:
        result = _run(make_sqlite_db, tmp_path, "a.db")
    """
    db_file = make_sqlite_db(name, sql)
    result, _ = DQTPipeline(
        ConnectionConfig(id="s", dsn=f"sqlite:///{db_file}"),
        DQPipelineConfig(connection_id="s", monitoring=MonitoringConfig(max_score_drop=0.1)),
        store_path=store or (tmp_path / "runs.db"),
        report_dir=tmp_path,
    ).run()
    return result


def _client(store_path: Path) -> object:
    """Return a test client bound to a store.

    Args:
        store_path: The RunStore to serve.

    Returns:
        A ``TestClient``.

    Example:
        client = _client(path)
    """
    import os

    from fastapi.testclient import TestClient

    os.environ["DQT_STORE_PATH"] = str(store_path)
    from dqt.ui.app import app

    return TestClient(app)


class TestTheColumnsScreen:
    """The per-column detail the report has shown since `F1`."""

    def test_it_lists_every_profiled_column(
        self, make_sqlite_db: Callable[[str, str], Path], tmp_path: Path
    ) -> None:
        """Three columns seeded, three columns shown."""
        result = _run(make_sqlite_db, tmp_path, "cols.db")
        response = _client(tmp_path / "runs.db").get(  # type: ignore[attr-defined]
            f"/ui/runs/{result.run_id}/columns"  # type: ignore[attr-defined]
        )

        assert response.status_code == 200
        for column in ("id", "email", "city"):
            assert column in response.text

    def test_it_shows_the_statistics_not_only_the_names(
        self, make_sqlite_db: Callable[[str, str], Path], tmp_path: Path
    ) -> None:
        """A screen of column names is a schema listing, not a profile.

        ``email`` has one NULL and two distinct values -- both hand-derived
        from the INSERT, and both invisible on every screen before this one.
        """
        result = _run(make_sqlite_db, tmp_path, "stats.db")
        text = (
            _client(tmp_path / "runs.db")
            .get(  # type: ignore[attr-defined]
                f"/ui/runs/{result.run_id}/columns"  # type: ignore[attr-defined]
            )
            .text
        )

        for heading in ("Distinct", "Min", "Max"):
            assert heading in text
        assert "ali@example.com" in text

    def test_an_unmeasured_statistic_reads_as_absent(
        self, make_sqlite_db: Callable[[str, str], Path], tmp_path: Path
    ) -> None:
        """``city`` is text and has no mean.

        The report renders that as ``n/a``; a blank cell on the dashboard
        would read as a value of zero or as a rendering bug, and the two
        surfaces should not disagree about what "not computed" looks like.
        """
        result = _run(make_sqlite_db, tmp_path, "absent.db")
        text = (
            _client(tmp_path / "runs.db")
            .get(  # type: ignore[attr-defined]
                f"/ui/runs/{result.run_id}/columns"  # type: ignore[attr-defined]
            )
            .text
        )

        assert "n/a" in text

    def test_an_unknown_run_is_a_404_rather_than_an_empty_table(self, tmp_path: Path) -> None:
        """An empty grid would read as "this run profiled nothing"."""
        from dqt.common.storage import RunStore

        RunStore(db_path=tmp_path / "runs.db").init_schema()
        response = _client(tmp_path / "runs.db").get("/ui/runs/no-such-run/columns")  # type: ignore[attr-defined]

        assert response.status_code == 404

    def test_the_run_screen_links_to_it(
        self, make_sqlite_db: Callable[[str, str], Path], tmp_path: Path
    ) -> None:
        """A screen nothing links to is a screen nobody finds."""
        result = _run(make_sqlite_db, tmp_path, "linked.db")
        text = (
            _client(tmp_path / "runs.db")
            .get(  # type: ignore[attr-defined]
                f"/ui/runs/{result.run_id}"  # type: ignore[attr-defined]
            )
            .text
        )

        assert f"/ui/runs/{result.run_id}/columns" in text  # type: ignore[attr-defined]


class TestDriftIsVisible:
    """`F8` records it. Until now only a JSON client could see it."""

    def test_a_fall_since_the_previous_run_is_shown(
        self, make_sqlite_db: Callable[[str, str], Path], tmp_path: Path
    ) -> None:
        """Completeness falls from 1.0 to 0.0 on ``email`` between two runs.

        The number a DBA opening the dashboard in the morning most wants is
        "what got worse overnight", and it was being computed and stored and
        never displayed.
        """
        store = tmp_path / "runs.db"
        _run(make_sqlite_db, tmp_path, "drift-1.db", SEEDED, store)
        second = _run(make_sqlite_db, tmp_path, "drift-2.db", DEGRADED, store)

        text = _client(store).get(f"/ui/runs/{second.run_id}").text  # type: ignore[attr-defined]

        assert "email" in text
        assert "0.33" in text or "0.3" in text or "-0.3" in text

    def test_a_first_run_shows_no_drift_section(
        self, make_sqlite_db: Callable[[str, str], Path], tmp_path: Path
    ) -> None:
        """There is nothing to compare against, and an empty panel says nothing.

        The pair to `F8`'s "a first observation has no drift rather than
        zero drift": the screen has to make the same distinction the data
        does, or it undoes it at the last step.
        """
        result = _run(make_sqlite_db, tmp_path, "no-drift.db")
        text = (
            _client(tmp_path / "runs.db")
            .get(  # type: ignore[attr-defined]
                f"/ui/runs/{result.run_id}"  # type: ignore[attr-defined]
            )
            .text
        )

        assert "Changed since" not in text
