"""A dimension with no column scores still reports one (`NEW-AD`).

`F7` made ``average_score_by_dimension`` read the run-level rollup instead
of averaging, with a fallback for runs stored before rollups existed. The
docstring described that fallback as being *for old stores*, and it is not
only that.

`referential_integrity` is scored **per table** -- it is a property of a
relationship, not of a column -- so it has no column-level scores to roll
up, and therefore no run-level rollup row either. Its score reaches the
dashboard entirely through the fallback.

That makes the fallback load-bearing for a dimension in every current run,
not a compatibility shim for historical ones. Recorded as a test because the
next person to read "fallback for pre-F7 runs" could reasonably decide it is
dead code once no old stores remain, and deleting it would silently blank
referential integrity on every dashboard.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from dqt.common.models import ConnectionConfig, DQPipelineConfig
from dqt.common.storage import RunStore
from dqt.sql.pipeline import DQTPipeline

SEEDED = """
    CREATE TABLE customers (id INTEGER PRIMARY KEY);
    CREATE TABLE orders (id INTEGER PRIMARY KEY,
                         customer_id INTEGER REFERENCES customers(id));
    INSERT INTO customers (id) VALUES (1);
    INSERT INTO orders (id, customer_id) VALUES (1, 1), (2, 404);
"""


def test_a_table_scoped_dimension_still_reaches_the_dashboard(
    make_sqlite_db: Callable[[str, str], Path], tmp_path: Path
) -> None:
    """One orphan, so referential integrity scores 0.0 rather than vanishing.

    Absent would render as "not measured", which is the opposite of what
    happened: it was measured, and it failed.
    """
    db_file = make_sqlite_db("fallback.db", SEEDED)
    store_path = tmp_path / "runs.db"
    result, _ = DQTPipeline(
        ConnectionConfig(id="s", dsn=f"sqlite:///{db_file}"),
        DQPipelineConfig(connection_id="s"),
        store_path=store_path,
        report_dir=tmp_path,
    ).run()

    scores = RunStore(db_path=store_path).average_score_by_dimension(result.run_id)

    assert "referential_integrity" in scores, "a measured dimension disappeared"
    assert scores["referential_integrity"] == 0.0


def test_it_has_no_run_level_rollup_of_its_own(
    make_sqlite_db: Callable[[str, str], Path], tmp_path: Path
) -> None:
    """The reason the test above is not redundant.

    If a rollup row existed for this dimension, the fallback would never run
    and the assertion above would pass for the wrong reason.
    """
    db_file = make_sqlite_db("fallback-why.db", SEEDED)
    result, _ = DQTPipeline(
        ConnectionConfig(id="s", dsn=f"sqlite:///{db_file}"),
        DQPipelineConfig(connection_id="s"),
        store_path=tmp_path / "runs.db",
        report_dir=tmp_path,
    ).run()

    rolled = [
        metric
        for metric in result.metrics
        if metric.dimension == "referential_integrity"
        and (metric.metadata or {}).get("scope") == "run"
    ]

    assert rolled == []
