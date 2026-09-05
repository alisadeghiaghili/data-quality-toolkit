"""What profiling costs the database (unit 16, performance and scale).

DQT is SQL-first so that computation happens in the database and rows are not
dragged into Python. That buys nothing if the tool then asks the database the
same question once per column.

`_profile_column` issued one query per column, so profiling a table cost
**N+1 round trips**: one row count plus one `COUNT(*) WHERE col IS NULL` per
column. On a hundred-column warehouse table that is a hundred and one full
scans to compute statistics one scan could produce.

**These tests count queries, not seconds.** A wall-clock budget in CI is a
flaky test wearing a performance costume -- it fails on a noisy runner and
passes on a quiet one, and people learn to re-run it. A query count is
deterministic, and it is also the thing that actually scales badly: the cost
that matters here grows with the number of columns, and counting round trips
measures exactly that.

Timings are reported separately by ``benchmarks/profile_benchmark.py``, which
is not a gate. Numbers that vary by machine belong in a report, not an
assertion.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from dqt.common.models import ConnectionConfig
from dqt.sql.profiling import SqlProfiler
from dqt.sql.schema_discovery import discover_schema


class CountingCursor:
    """A cursor that records every statement executed through it.

    Attributes:
        statements: Every statement seen, in order.

    Example:
        cursor = CountingCursor(real_cursor, statements)
    """

    def __init__(self, inner: Any, statements: list[str]) -> None:
        """Wrap *inner*, appending each statement to *statements*.

        Args:
            inner: The real DBAPI cursor.
            statements: Shared list to append to.

        Example:
            CountingCursor(connection.cursor(), [])
        """
        self._inner = inner
        self.statements = statements

    def execute(self, statement: str, *args: Any, **kwargs: Any) -> Any:
        """Record and forward a statement.

        Args:
            statement: SQL to run.
            *args: Passed through.
            **kwargs: Passed through.

        Returns:
            Whatever the wrapped cursor returns.

        Example:
            cursor.execute("SELECT 1")
        """
        self.statements.append(statement)
        return self._inner.execute(statement, *args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        """Forward everything else to the wrapped cursor.

        Args:
            name: Attribute being looked up.

        Returns:
            The wrapped cursor's attribute.

        Example:
            rows = cursor.fetchall()
        """
        return getattr(self._inner, name)


class CountingConnection:
    """A connection that records every statement run against it.

    Attributes:
        statements: Every statement seen, in order.

    Example:
        connection = CountingConnection(real_connection)
    """

    def __init__(self, inner: Any) -> None:
        """Wrap *inner* and start an empty statement log.

        Args:
            inner: The real DBAPI connection.

        Example:
            CountingConnection(sqlite3.connect(":memory:"))
        """
        self._inner = inner
        self.statements: list[str] = []

    def execute(self, statement: str, *args: Any, **kwargs: Any) -> Any:
        """Record and forward a statement.

        Args:
            statement: SQL to run.
            *args: Passed through.
            **kwargs: Passed through.

        Returns:
            Whatever the wrapped connection returns.

        Example:
            connection.execute("SELECT 1")
        """
        self.statements.append(statement)
        return self._inner.execute(statement, *args, **kwargs)

    def cursor(self) -> CountingCursor:
        """Return a cursor that shares this connection's statement log.

        Returns:
            A CountingCursor.

        Example:
            cursor = connection.cursor()
        """
        return CountingCursor(self._inner.cursor(), self.statements)

    def __getattr__(self, name: str) -> Any:
        """Forward everything else to the wrapped connection.

        Args:
            name: Attribute being looked up.

        Returns:
            The wrapped connection's attribute.

        Example:
            connection.close()
        """
        return getattr(self._inner, name)


def _wide_table(column_count: int) -> str:
    """Return DDL and one INSERT for a table with *column_count* columns.

    Args:
        column_count: How many nullable columns to create.

    Returns:
        A SQL script.

    Example:
        script = _wide_table(20)
    """
    columns = ", ".join(f"c{n} TEXT" for n in range(column_count))
    values = ", ".join("NULL" if n % 2 else f"'v{n}'" for n in range(column_count))
    return f"CREATE TABLE wide ({columns}); INSERT INTO wide VALUES ({values});"


@pytest.fixture
def profile_and_count(
    make_sqlite_db: Callable[[str, str], Path], monkeypatch: pytest.MonkeyPatch
) -> Callable[[str], tuple[list[str], Any]]:
    """Profile a seeded database and return the statements it ran.

    Args:
        make_sqlite_db: Factory fixture building a SQLite file.
        monkeypatch: Used to hand the profiler a counting connection.

    Returns:
        A callable taking a DDL script and returning (statements, profiles).

    Example:
        statements, profiles = profile_and_count(script)
    """

    def _run(script: str) -> tuple[list[str], Any]:
        db_file = make_sqlite_db("perf.db", script)
        config = ConnectionConfig(id="perf", dsn=f"sqlite:///{db_file}")
        tables = discover_schema(config)

        seen: list[str] = []
        import dqt.sql.profiling as profiling_module

        real_connect = profiling_module.get_connection

        def counting_connect(connection_config: ConnectionConfig) -> Any:
            wrapper = CountingConnection(real_connect(connection_config))
            wrapper.statements = seen
            return wrapper

        monkeypatch.setattr(profiling_module, "get_connection", counting_connect)
        profiles = SqlProfiler(config).profile_tables(tables)
        return seen, profiles

    return _run


class TestProfilingIsSinglePass:
    """One aggregate query per table, whatever its width."""

    def test_a_twenty_column_table_costs_one_query(
        self, profile_and_count: Callable[[str], tuple[list[str], Any]]
    ) -> None:
        """Twenty columns must not mean twenty-one scans.

        The old shape issued a row count plus one ``COUNT(*) WHERE col IS
        NULL`` per column. Every one of those is a full scan on a table with
        no index on the column, so profiling a wide table re-read it once per
        column to compute what a single pass can produce.
        """
        statements, _ = profile_and_count(_wide_table(20))

        assert len(statements) == 1, (
            f"profiling one table should cost one query, ran {len(statements)}: "
            f"{statements}"
        )

    def test_the_cost_does_not_grow_with_column_count(
        self, profile_and_count: Callable[[str], tuple[list[str], Any]]
    ) -> None:
        """Five columns and fifty columns cost the same.

        This is the property, stated as a comparison so it cannot be
        satisfied by a constant that happens to be large. A tool that scales
        with schema width is unusable on the warehouse tables its own README
        describes.
        """
        narrow, _ = profile_and_count(_wide_table(5))
        wide, _ = profile_and_count(_wide_table(50))

        assert len(narrow) == len(wide)

    def test_the_cost_grows_only_with_table_count(
        self, profile_and_count: Callable[[str], tuple[list[str], Any]]
    ) -> None:
        """Three tables cost three queries, not three times their width.

        Per-table cost is irreducible without cross-table SQL that would be
        far harder to read than it is worth. Per-column cost is not.
        """
        script = "".join(
            f"CREATE TABLE t{n} (a TEXT, b TEXT, c TEXT, d TEXT);"
            f"INSERT INTO t{n} VALUES ('x', NULL, 'y', NULL);"
            for n in range(3)
        )
        statements, _ = profile_and_count(script)

        assert len(statements) == 3


class TestTheNumbersAreStillRight:
    """A faster profiler that reports the wrong counts is worse than a slow one."""

    def test_null_counts_survive_the_single_pass(
        self, profile_and_count: Callable[[str], tuple[list[str], Any]]
    ) -> None:
        """Ground truth: the fixture nulls every odd-numbered column.

        With ten columns, c1/c3/c5/c7/c9 are NULL and the rest hold a value,
        on the single seeded row. Counted from ``_wide_table``'s literal, not
        from the profiler.
        """
        _, profiles = profile_and_count(_wide_table(10))

        by_name = {c.column_name: c for c in profiles[0].columns}
        assert profiles[0].row_count == 1
        assert [n for n in range(10) if by_name[f"c{n}"].null_count == 1] == [1, 3, 5, 7, 9]
        assert [n for n in range(10) if by_name[f"c{n}"].null_count == 0] == [0, 2, 4, 6, 8]

    def test_an_empty_table_still_reports_zero_rows(
        self, profile_and_count: Callable[[str], tuple[list[str], Any]]
    ) -> None:
        """The boundary that `NEW-C` slice 1 pinned must survive this change.

        A single-pass query over an empty table returns one row of zeros, not
        no rows, and reading it as "no result" would make row_count wrong.
        """
        statements, profiles = profile_and_count("CREATE TABLE wide (a TEXT, b TEXT);")

        assert len(statements) == 1
        assert profiles[0].row_count == 0
        assert all(column.null_count == 0 for column in profiles[0].columns)
