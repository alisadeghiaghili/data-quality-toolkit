"""Measure what a run costs, in seconds, against published budgets (`GATE-04`).

The `v0.4` rung asks for profiling, rule evaluation and cleanse planning to
each report a timing under a published budget for a stated fixture size.

**The timing happens here, not in CI.** Wall-clock numbers vary by machine,
disk and what else the box is doing, so asserting on them in a shared runner
produces a test that fails on a noisy agent and passes on a quiet one — and
people learn to re-run it rather than read it. The deterministic properties
are gated instead, by ``tests/unit/sql/test_profiling_cost.py`` and
``tests/unit/sql/test_rules_grouped.py``, which count queries.

So this script measures, checks each phase against
:data:`~benchmarks.budgets.BUDGETS`, and writes the result to
``benchmarks/results/latest.json``. That file is committed, and
``tests/unit/test_benchmark_evidence.py`` checks it covers every phase at the
stated size and came in under budget. The evidence is a file rather than a
clock, so the check is deterministic — and stale or missing evidence fails
just as loudly as slow evidence.

Run it::

    python benchmarks/benchmark.py
    python benchmarks/benchmark.py --rows 200000 --write

Example:
    python benchmarks/benchmark.py --rows 1000
"""

from __future__ import annotations

import argparse
import json
import platform
import sqlite3
import statistics
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from budgets import BUDGETS, FIXTURE_COLUMNS, FIXTURE_ROWS  # noqa: E402

from dqt.common.models import (  # noqa: E402
    ConnectionConfig,
    RuleConfig,
    RuleScope,
)
from dqt.sql.cleansing import CleansingConfig, cleanse_plan  # noqa: E402
from dqt.sql.profiling import SqlProfiler  # noqa: E402
from dqt.sql.rules import apply_rules  # noqa: E402
from dqt.sql.schema_discovery import discover_schema  # noqa: E402

#: Where the committed evidence lives.
RESULTS_FILE = Path(__file__).resolve().parent / "results" / "latest.json"


class _MemoryStore:
    """The one store method cleanse_plan calls.

    Example:
        store = _MemoryStore()
    """

    def save_cleansing_plan(self, plan: object) -> None:
        """Discard the plan; only the timing matters here.

        Args:
            plan: Ignored.

        Returns:
            None.

        Example:
            _MemoryStore().save_cleansing_plan(plan)
        """


def build_database(path: Path, rows: int, columns: int) -> None:
    """Create a fixture table with a third of its values NULL.

    Args:
        path: Where to create the SQLite file.
        rows: How many rows to insert.
        columns: How many text columns beside the key.

    Returns:
        None.

    Example:
        build_database(Path("bench.db"), 1000, 20)
    """
    names = [f"c{index}" for index in range(columns)]
    with sqlite3.connect(path) as connection:
        connection.execute(
            f"CREATE TABLE wide (id INTEGER PRIMARY KEY, "
            f"{', '.join(f'{name} TEXT' for name in names)})"
        )
        placeholders = ", ".join("?" * (columns + 1))
        connection.executemany(
            f"INSERT INTO wide VALUES ({placeholders})",
            [
                (
                    row,
                    *[
                        None if (row + index) % 3 == 0 else f"v{row % 97}"
                        for index in range(columns)
                    ],
                )
                for row in range(rows)
            ],
        )


def _time(work: Any, repeats: int) -> float:
    """Return the median wall-clock seconds of *repeats* runs.

    The median rather than the minimum: the minimum reports the luckiest run
    on an otherwise busy machine, which is not what anyone will experience.

    Args:
        work: A zero-argument callable.
        repeats: How many times to run it.

    Returns:
        Median seconds.

    Example:
        seconds = _time(lambda: None, 3)
    """
    timings = []
    for _ in range(repeats):
        started = time.perf_counter()
        work()
        timings.append(time.perf_counter() - started)
    return statistics.median(timings)


def measure(path: Path, repeats: int) -> dict[str, float]:
    """Time each phase against the fixture at *path*.

    Args:
        path: The SQLite fixture.
        repeats: Runs per phase.

    Returns:
        Phase name to median seconds.

    Example:
        timings = measure(Path("bench.db"), 3)
    """
    config = ConnectionConfig(id="bench", dsn=f"sqlite:///{path}", read_only=False)
    tables = discover_schema(config)

    rules = [
        RuleConfig(
            name=f"not-null-c{index}",
            dimension="completeness",
            severity="warning",
            scope=RuleScope(table_pattern="wide", column_pattern=f"c{index}"),
            expression="NOT NULL",
        )
        for index in range(10)
    ]
    cleansing = [
        CleansingConfig(
            table_name="wide",
            column_name="c0",
            operation="standardize",
            params={"trim": True},
        )
    ]

    return {
        "profiling": _time(lambda: SqlProfiler(config).profile_tables(tables), repeats),
        "rules": _time(
            lambda: apply_rules(
                run_id="bench",
                connection_config=config,
                rules=rules,
                discovered_tables=tables,
            ),
            repeats,
        ),
        "cleanse_plan": _time(
            lambda: cleanse_plan(config, cleansing, store=_MemoryStore()), repeats
        ),
    }


def main() -> int:
    """Measure, compare against the budgets, and optionally record.

    Returns:
        0 when every phase is within budget, 1 otherwise.

    Example:
        raise SystemExit(main())
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=FIXTURE_ROWS)
    parser.add_argument("--columns", type=int, default=FIXTURE_COLUMNS)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument(
        "--write",
        action="store_true",
        help="Record the run to benchmarks/results/latest.json.",
    )
    arguments = parser.parse_args()

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "bench.db"
        build_database(path, arguments.rows, arguments.columns)
        timings = measure(path, arguments.repeats)

    over_budget = []
    print(f"{arguments.rows} rows x {arguments.columns} columns, median of {arguments.repeats}\n")
    for phase, seconds in timings.items():
        budget = BUDGETS[phase]
        verdict = "ok" if seconds <= budget else "OVER"
        if seconds > budget:
            over_budget.append(phase)
        print(f"  {phase:<14} {seconds:7.3f}s   budget {budget:5.2f}s   {verdict}")

    if arguments.write:
        record = {
            "recorded_at": datetime.now(UTC).isoformat(),
            "rows": arguments.rows,
            "columns": arguments.columns,
            "repeats": arguments.repeats,
            "timings": timings,
            "machine": {
                "python": platform.python_version(),
                "platform": platform.platform(),
                "processor": platform.processor() or "unknown",
            },
        }
        RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        RESULTS_FILE.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        print(f"\nRecorded to {RESULTS_FILE}")

    if over_budget:
        print(f"\nOver budget: {', '.join(over_budget)}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
