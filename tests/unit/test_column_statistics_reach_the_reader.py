"""Computed statistics reach the person reading the report (`F1`).

Computing a statistic and surfacing it are two different pieces of work, and
this repository has a live example of stopping after the first:
`classification.py` is real, locale-aware and publicly exported, and nothing
calls it during a run -- so `dqt_competitors.md` records F10 as `PARTIAL`
rather than met, on the rule that a module existing is not a floor item met.

`F1` would fail the same way if `min`, `max`, `mean` and the distinct count
lived only in a `ColumnProfile` that never left the profiler. These tests
follow them out: into the metric metadata that the store, the JSON API and
the trend history all read, and into the HTML report a DBA is actually sent.

The report is the artifact that matters most here. It is one self-contained
file, which is why it survives being emailed to someone who will never run
DQT themselves -- and for that person it is not one view of the data, it is
the only one.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path

from dqt.common.models import ConnectionConfig, DQPipelineConfig
from dqt.common.storage import RunStore
from dqt.sql.pipeline import DQTPipeline

SEEDED = """
    CREATE TABLE people (id INTEGER, score REAL, name TEXT);
    INSERT INTO people (id, score, name) VALUES
        (1, 10.0, 'ali'),
        (2, 20.0, 'sara'),
        (3, 30.0, 'ali'),
        (4, NULL, NULL);
"""


def _run(make_sqlite_db: Callable[[str, str], Path], tmp_path: Path, name: str) -> object:
    """Run the pipeline over the seeded table.

    Args:
        make_sqlite_db: Factory fixture building a SQLite file.
        tmp_path: pytest's per-test directory.
        name: Distinct database filename for this run.

    Returns:
        A ``(result, report_path)`` tuple.

    Example:
        result, report = _run(make_sqlite_db, tmp_path, "a.db")
    """
    db_file = make_sqlite_db(name, SEEDED)
    return DQTPipeline(
        ConnectionConfig(id="s", dsn=f"sqlite:///{db_file}"),
        DQPipelineConfig(connection_id="s"),
        store_path=tmp_path / "runs.db",
        report_dir=tmp_path,
    ).run()


class TestTheMetricCarriesTheStatistics:
    """`DQMetric.metadata` is what the store and the JSON API read."""

    def test_a_numeric_column_reports_its_bounds_and_mean(
        self, make_sqlite_db: Callable[[str, str], Path], tmp_path: Path
    ) -> None:
        """``score`` is 10, 20, 30 and a NULL -- hand-derived from the INSERT.

        The mean is 20 rather than 15, which is the assertion that says the
        NULL was excluded rather than counted as zero on the way through.
        """
        result, _ = _run(make_sqlite_db, tmp_path, "metric-numeric.db")  # type: ignore[misc]

        metric = next(
            m
            for m in result.metrics  # type: ignore[attr-defined]
            if m.column_name == "score" and m.dimension == "completeness"
        )

        assert metric.metadata["min_value"] == 10.0
        assert metric.metadata["max_value"] == 30.0
        assert metric.metadata["mean_value"] == 20.0
        assert metric.metadata["distinct_count"] == 3

    def test_a_text_column_reports_bounds_but_no_mean(
        self, make_sqlite_db: Callable[[str, str], Path], tmp_path: Path
    ) -> None:
        """Absent, not zero. The type gate has to survive the trip out.

        A serialiser that turns ``None`` into ``0`` on the way into metadata
        would undo the whole point of gating ``AVG`` in the first place.
        """
        result, _ = _run(make_sqlite_db, tmp_path, "metric-text.db")  # type: ignore[misc]

        metric = next(
            m
            for m in result.metrics  # type: ignore[attr-defined]
            if m.column_name == "name" and m.dimension == "completeness"
        )

        assert metric.metadata["min_value"] == "ali"
        assert metric.metadata["max_value"] == "sara"
        assert metric.metadata["mean_value"] is None
        assert metric.metadata["distinct_count"] == 2

    def test_the_existing_keys_survive(
        self, make_sqlite_db: Callable[[str, str], Path], tmp_path: Path
    ) -> None:
        """Additive, not a replacement.

        ``null_count`` and ``row_count`` were in this metadata before, and
        anything already reading them must keep working -- the metadata keys
        are what a stored run is read back through.
        """
        result, _ = _run(make_sqlite_db, tmp_path, "metric-keys.db")  # type: ignore[misc]

        metric = next(
            m
            for m in result.metrics  # type: ignore[attr-defined]
            if m.column_name == "id" and m.dimension == "completeness"
        )

        assert metric.metadata["null_count"] == 0
        assert metric.metadata["row_count"] == 4


class TestBinaryColumnMinMaxDoesNotCrashPersistence:
    """`NEW-AF`: a raw driver value in metric metadata used to crash `_persist`.

    ``SqlProfiler.build_metrics`` copied ``column.min_value``/``max_value``
    into ``DQMetric.metadata`` unchanged, and
    ``RunStore._metric_row`` called ``json.dumps(metric.metadata)`` with no
    ``default``. SQLite's ``_UNORDERED_TYPES`` holds only ``"blob"`` (matched
    by whole name), so a column declared ``VARBINARY(16)`` -- a spelling
    that does not match ``"blob"`` -- passes ``supports_min_max`` and
    ``MIN``/``MAX`` run over it, returning raw ``bytes``. ``json.dumps``
    cannot serialize ``bytes``, and that ``TypeError`` was raised inside
    ``_persist``, which is outside ``run()``'s stage-error guards: nothing
    was stored, no report was written, and the CLI exited non-zero even
    though profiling itself had already completed successfully.
    """

    def test_a_varbinary_column_run_succeeds_and_reports_a_hex_bound(self, tmp_path: Path) -> None:
        """Ground truth: the single seeded row holds the two bytes ``0x00``, ``0xff``.

        ``MIN``/``MAX`` over one row both equal that row's own value, so the
        completeness metric's ``min_value`` must be the hex preview of
        exactly those two bytes: ``"0x00ff"`` -- no truncation marker, since
        two bytes is far under the 32-byte preview bound.
        """
        db_file = tmp_path / "binary.db"
        connection = sqlite3.connect(db_file)
        try:
            connection.execute("CREATE TABLE blobs (id INTEGER PRIMARY KEY, payload VARBINARY(16))")
            connection.execute("INSERT INTO blobs (id, payload) VALUES (1, ?)", (b"\x00\xff",))
            connection.commit()
        finally:
            connection.close()

        store_path = tmp_path / "runs.db"
        result, report_path = DQTPipeline(
            ConnectionConfig(id="s", dsn=f"sqlite:///{db_file}"),
            DQPipelineConfig(connection_id="s"),
            store_path=store_path,
            report_dir=tmp_path,
        ).run()

        assert result.status == "success"
        assert report_path.exists()

        store = RunStore(db_path=store_path)
        assert any(row["run_id"] == result.run_id for row in store.load_runs())

        metric = next(
            m
            for m in result.metrics  # type: ignore[attr-defined]
            if m.column_name == "payload" and m.dimension == "completeness"
        )
        assert metric.metadata["min_value"] == "0x00ff"
        assert metric.metadata["max_value"] == "0x00ff"


class TestTheReportShowsThem:
    """The one artifact that reaches someone who will never run DQT."""

    def test_the_column_table_carries_the_new_statistics(
        self, make_sqlite_db: Callable[[str, str], Path], tmp_path: Path
    ) -> None:
        """Headers and values both, because either alone is a broken column.

        Asserting on the rendered values rather than only the headings is
        what stops this passing against a table of empty cells.
        """
        _, report_path = _run(make_sqlite_db, tmp_path, "report.db")  # type: ignore[misc]
        html = Path(str(report_path)).read_text(encoding="utf-8")

        for heading in ("Distinct", "Min", "Max", "Mean"):
            assert heading in html, f"report has no {heading} column"

        assert ">sara<" in html, "the text column's maximum is not rendered"
        assert ">20.0<" in html or ">20<" in html, "the numeric mean is not rendered"

    def test_an_absent_statistic_renders_as_absent(
        self, make_sqlite_db: Callable[[str, str], Path], tmp_path: Path
    ) -> None:
        """A text column has no mean, and the cell must not claim one.

        The report already renders an unknown null count as ``n/a``; a blank
        or a ``0`` here would be the report inventing a number the profiler
        deliberately declined to produce.
        """
        _, report_path = _run(make_sqlite_db, tmp_path, "report-absent.db")  # type: ignore[misc]
        html = Path(str(report_path)).read_text(encoding="utf-8")

        assert "n/a" in html
