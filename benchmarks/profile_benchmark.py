"""Measure what profiling costs, in time and in queries.

This is a report, not a gate. Wall-clock numbers vary by machine, disk and
what else the box is doing, so asserting on them in CI produces a test that
fails on a noisy runner and passes on a quiet one -- and people learn to
re-run it rather than read it. The deterministic property, one query per
table regardless of width, is gated instead by
``tests/unit/sql/test_profiling_cost.py``.

What this script is for is the other half: knowing the absolute numbers, and
watching them move. A budget with no measurement behind it is a wish.

Run it directly::

    python benchmarks/profile_benchmark.py
    python benchmarks/profile_benchmark.py --rows 200000 --columns 40

Example:
    python benchmarks/profile_benchmark.py --rows 1000
"""

from __future__ import annotations

import argparse
import sqlite3
import statistics
import tempfile
import time
from pathlib import Path
from typing import Any

from dqt.common.models import ConnectionConfig
from dqt.sql.profiling import SqlProfiler
from dqt.sql.schema_discovery import discover_schema


def build_database(path: Path, rows: int, columns: int) -> None:
    """Create a table of *rows* x *columns* with a third of the values NULL.

    Args:
        path: Where to write the SQLite file.
        rows: Number of rows to insert.
        columns: Number of columns to create.

    Returns:
        None.

    Example:
        build_database(Path("bench.db"), rows=1000, columns=20)
    """
    connection = sqlite3.connect(str(path))
    try:
        column_ddl = ", ".join(f"c{n} TEXT" for n in range(columns))
        connection.execute(f"CREATE TABLE bench (id INTEGER PRIMARY KEY, {column_ddl})")
        placeholders = ", ".join("?" for _ in range(columns))
        connection.executemany(
            f"INSERT INTO bench VALUES (NULL, {placeholders})",
            (
                tuple(None if (row + col) % 3 == 0 else f"v{col}" for col in range(columns))
                for row in range(rows)
            ),
        )
        connection.commit()
    finally:
        connection.close()


def measure(path: Path, repeats: int) -> dict[str, Any]:
    """Profile the database *repeats* times and summarise the cost.

    Args:
        path: SQLite file to profile.
        repeats: How many timed runs to take.

    Returns:
        A dict of the median and minimum elapsed seconds and the query count.

    Example:
        result = measure(Path("bench.db"), repeats=5)
    """
    config = ConnectionConfig(id="bench", dsn=f"sqlite:///{path}")
    tables = discover_schema(config)
    profiler = SqlProfiler(config)

    timings: list[float] = []
    for _ in range(repeats):
        started = time.perf_counter()
        profiles = profiler.profile_tables(tables)
        timings.append(time.perf_counter() - started)

    return {
        "median_seconds": statistics.median(timings),
        # The minimum is the cleanest signal available on a shared machine:
        # noise can only ever make a run slower, never faster.
        "min_seconds": min(timings),
        "row_count": profiles[0].row_count,
        "column_count": len(profiles[0].columns),
    }


def main() -> None:
    """Build a synthetic database, profile it, and print the numbers.

    Returns:
        None.

    Example:
        main()
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=100_000)
    parser.add_argument("--columns", type=int, default=20)
    parser.add_argument("--repeats", type=int, default=5)
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "bench.db"
        print(f"Building {args.rows:,} rows x {args.columns} columns ...")
        build_database(path, args.rows, args.columns)
        size_mb = path.stat().st_size / 1_048_576

        result = measure(path, args.repeats)

    cells = result["row_count"] * result["column_count"]
    print()
    print(f"  database        {size_mb:>10.1f} MB")
    print(f"  rows            {result['row_count']:>10,}")
    print(f"  columns         {result['column_count']:>10,}")
    print(f"  median          {result['median_seconds']:>10.3f} s")
    print(f"  fastest         {result['min_seconds']:>10.3f} s")
    print(f"  cells/second    {cells / result['min_seconds']:>10,.0f}")
    print()
    print("  Queries per table: 1, regardless of column count.")
    print("  That property is gated by tests/unit/sql/test_profiling_cost.py;")
    print("  the timings above are a report, not an assertion.")


if __name__ == "__main__":
    main()
