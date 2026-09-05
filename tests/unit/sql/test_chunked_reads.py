"""Reading rows without holding the table in memory (unit 16, performance).

Cleansing is the one facet that genuinely has to read rows: it records a
before-value for every change so ``revert()`` can put it back. Everything
else in DQT aggregates in the database.

It read them all at once. ``_standardize`` and ``_lookup_correct`` each ran
``SELECT <identity>, <column> FROM <table> WHERE <column> IS NOT NULL`` and
called ``fetchall()``, so planning a cleanse of a fifty-million-row table
built a fifty-million-element Python list before deciding that four rows
needed changing. ``CLAUDE.md`` names the requirement -- *"chunk reads or use
a server-side cursor so memory stays flat"* -- and this is the path it was
written for.

**Why paging by key rather than a streaming cursor.** The obvious fix is to
keep one cursor open and ``fetchmany()`` from it. That would be wrong here,
because these functions write while they read: ``_standardize`` issues an
``UPDATE`` for each row that changes. SQLite documents that a query running
while its own connection modifies the table "might return a changed row more
than once, or ... a row that was previously deleted", and the other engines
answer according to their isolation level. Streaming would buy flat memory
by making the result depend on which engine is underneath.

Paging by the row identity avoids the question: each page's ``SELECT``
finishes before that page's writes are issued, and the next page starts
after the last key seen. The identity is the primary key, which an
``UPDATE`` to some other column does not move, so no row is skipped or
repeated. Memory is bounded by the page size, not by the table.

**And a per-row round trip goes away.** ``_deduplicate`` ran one extra
``SELECT *`` per duplicate found, to capture the row before deleting it --
per-row work over a table, which ``CLAUDE.md`` calls a design smell by name.
The ranked query already visits those rows; it can bring the values back
with it.

Counted, not timed, for the reason ``test_profiling_cost.py`` gives.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from dqt.common.models import ConnectionConfig
from dqt.sql.cleansing import CleansingConfig, cleanse_plan
from dqt.sql.dialects import get_dialect_by_name
from dqt.sql.row_identity import RowIdentity

SQLITE = get_dialect_by_name("sqlite")

SEEDED_ROWS = 25
PAGE_SIZE = 10


class TestAnIdentityCanExpressWhereAPageLeftOff:
    """Keyset paging needs an ordering and an "after this row" predicate.

    Both belong on :class:`RowIdentity`: it already knows which columns name
    a row, and building the predicate anywhere else would mean a second
    place that has to agree with it about key order.
    """

    def test_a_single_key_orders_by_itself(self) -> None:
        """One column, one ordering term."""
        identity = RowIdentity(columns=("id",), locator=None)

        assert identity.order_by_expressions(SQLITE) == ['"id"']

    def test_a_composite_key_orders_by_every_part_in_key_order(self) -> None:
        """Key order is what makes the paging predicate below correct.

        Ordering by ``b, a`` while comparing ``a`` first would skip rows.
        """
        identity = RowIdentity(columns=("tenant_id", "id"), locator=None)

        assert identity.order_by_expressions(SQLITE) == ['"tenant_id"', '"id"']

    def test_a_single_key_compares_directly(self) -> None:
        """``("id" > ?)`` -- the whole predicate for the common case."""
        identity = RowIdentity(columns=("id",), locator=None)

        assert identity.after_clause(SQLITE) == '("id" > ?)'

    def test_a_composite_key_is_compared_lexicographically(self) -> None:
        """Expanded by hand rather than written as a row-value comparison.

        SQLite and PostgreSQL accept ``(a, b) > (?, ?)``; SQL Server does
        not. The expansion below means one form for all three, which is the
        whole point of having a dialect layer rather than three code paths.

        Read it as: a later tenant, or the same tenant and a later id.
        """
        identity = RowIdentity(columns=("tenant_id", "id"), locator=None)

        assert identity.after_clause(SQLITE) == (
            '("tenant_id" > ?) OR ("tenant_id" = ? AND "id" > ?)'
        )

    def test_the_binds_repeat_the_prefix_the_predicate_repeats(self) -> None:
        """Three placeholders above, so three values, in that order.

        Hand-derived from the clause: ``tenant_id`` appears in both branches
        and ``id`` only in the second.
        """
        identity = RowIdentity(columns=("tenant_id", "id"), locator=None)

        assert identity.after_bind_values({"tenant_id": 7, "id": 42}) == (7, 7, 42)

    def test_a_locator_compares_as_a_single_term(self) -> None:
        """A keyless table on SQLite pages by ``rowid``, which is ordered."""
        identity = RowIdentity(columns=(), locator="rowid")

        assert identity.after_clause(SQLITE) == "(rowid > ?)"
        assert identity.after_bind_values({"rowid": 3}) == (3,)


class TestTheDialectCanOrderABoundedSelect:
    """A bounded read without an ordering returns an arbitrary page.

    ``limited_select_sql`` bounded the row count but said nothing about
    which rows, which is fine for issue evidence and useless for paging:
    "any twenty rows" cannot be resumed from.
    """

    @pytest.mark.parametrize("name", ["sqlite", "postgresql", "sqlserver"])
    def test_every_dialect_accepts_an_ordering(self, name: str) -> None:
        """The ordering reaches the SQL on all three."""
        sql = get_dialect_by_name(name).limited_select_sql(
            '"t"', ['"a"'], limit=10, order_by=['"a"']
        )

        assert "ORDER BY" in sql.upper()
        assert '"a"' in sql

    def test_the_order_follows_the_predicate_on_sqlite(self) -> None:
        """``WHERE`` then ``ORDER BY`` then ``LIMIT`` -- SQLite's grammar."""
        sql = " ".join(
            SQLITE.limited_select_sql(
                '"t"', ['"a"'], where_clause='"a" > 1', limit=10, order_by=['"a"']
            ).split()
        )

        assert sql.index("WHERE") < sql.index("ORDER BY") < sql.index("LIMIT")

    def test_sql_server_keeps_top_in_front_and_the_order_behind(self) -> None:
        """T-SQL puts the bound on the projection and the ordering last.

        This is the structural difference the dialect layer exists for: a
        caller cannot bound a result set by appending a string.
        """
        sql = " ".join(
            get_dialect_by_name("sqlserver")
            .limited_select_sql('"t"', ['"a"'], limit=10, order_by=['"a"'])
            .split()
        )

        assert sql.startswith("SELECT TOP (10)")
        assert sql.index("ORDER BY") > sql.index("FROM")


def _seed(rows: int) -> str:
    """Return a script creating ``people`` with *rows* untrimmed emails.

    Every value has a trailing space, so a ``trim`` standardization changes
    every row -- which is what makes the write path run on every page rather
    than only on the first.

    Args:
        rows: How many rows to insert.

    Returns:
        A SQL script.

    Example:
        script = _seed(25)
    """
    values = ", ".join(f"({n}, 'user{n}@example.com ')" for n in range(1, rows + 1))
    return (
        "CREATE TABLE people (id INTEGER PRIMARY KEY, email TEXT);"
        f"INSERT INTO people (id, email) VALUES {values};"
    )


class _RecordingCursor:
    """A cursor logging statements and the size of every result it hands back.

    Example:
        cursor = _RecordingCursor(real_cursor, [])
    """

    def __init__(self, inner: Any, log: list[tuple[str, int]]) -> None:
        """Wrap *inner* and append to *log*.

        Args:
            inner: The real DBAPI cursor.
            log: Shared list of (statement, rows returned) pairs.

        Example:
            cursor = _RecordingCursor(inner, [])
        """
        self._inner = inner
        self._log = log
        self._last = ""

    def execute(self, sql: str, params: Any = ()) -> Any:
        """Record *sql*, then run it.

        Args:
            sql: Statement to execute.
            params: Bind values.

        Returns:
            Whatever the wrapped cursor returns.

        Example:
            cursor.execute("SELECT 1")
        """
        self._last = " ".join(sql.split())
        self._log.append((self._last, 0))
        return self._inner.execute(sql, params)

    def fetchall(self) -> Any:
        """Record how many rows this statement materialised at once.

        Returns:
            The rows.

        Example:
            rows = cursor.fetchall()
        """
        rows = self._inner.fetchall()
        self._log.append((f"FETCH {self._last}", len(rows)))
        return rows

    def fetchone(self) -> Any:
        """Delegate, without recording a single row as a materialisation.

        Returns:
            The row.

        Example:
            row = cursor.fetchone()
        """
        return self._inner.fetchone()

    def __getattr__(self, name: str) -> Any:
        """Delegate everything else to the wrapped cursor.

        Args:
            name: Attribute name.

        Returns:
            The wrapped cursor's attribute.

        Example:
            description = cursor.description
        """
        return getattr(self._inner, name)


class _RecordingConnection:
    """A connection handing out :class:`_RecordingCursor` objects.

    Example:
        connection = _RecordingConnection(real, [])
    """

    def __init__(self, inner: Any, log: list[tuple[str, int]]) -> None:
        """Wrap *inner*, sharing *log* with every cursor it makes.

        Args:
            inner: The real DBAPI connection.
            log: Shared statement log.

        Example:
            connection = _RecordingConnection(inner, [])
        """
        self._inner = inner
        self._log = log

    def cursor(self) -> _RecordingCursor:
        """Return a recording cursor.

        Returns:
            The wrapper.

        Example:
            cursor = connection.cursor()
        """
        return _RecordingCursor(self._inner.cursor(), self._log)

    def __getattr__(self, name: str) -> Any:
        """Delegate everything else to the wrapped connection.

        Args:
            name: Attribute name.

        Returns:
            The wrapped connection's attribute.

        Example:
            connection.commit()
        """
        return getattr(self._inner, name)


class _NullStore:
    """A store that keeps the plan in memory.

    Example:
        store = _NullStore()
    """

    def __init__(self) -> None:
        """Start empty.

        Example:
            store = _NullStore()
        """
        self.plan: Any = None

    def save_cleansing_plan(self, plan: Any) -> None:
        """Keep *plan*.

        Args:
            plan: The plan to keep.

        Returns:
            None.

        Example:
            store.save_cleansing_plan(plan)
        """
        self.plan = plan


PlanAndLog = Callable[[str, list[CleansingConfig]], tuple[list[tuple[str, int]], Any]]


@pytest.fixture
def plan_and_log(
    make_sqlite_db: Callable[[str, str], Path], monkeypatch: pytest.MonkeyPatch
) -> PlanAndLog:
    """Plan a cleanse against a seeded database, returning what it ran.

    Args:
        make_sqlite_db: Factory fixture building a SQLite file.
        monkeypatch: Used to shrink the page size and record statements.

    Returns:
        A callable taking a seed script and configs, returning (log, plan).

    Example:
        log, plan = plan_and_log(_seed(25), [config])
    """
    import dqt.sql.cleansing as cleansing_module

    counter = itertools.count()
    real_connect = cleansing_module.get_connection
    monkeypatch.setattr(cleansing_module, "_READ_PAGE_SIZE", PAGE_SIZE)

    def _run(script: str, configs: list[CleansingConfig]) -> tuple[list[tuple[str, int]], Any]:
        db_file = make_sqlite_db(f"chunk{next(counter)}.db", script)
        config = ConnectionConfig(id="chunk", dsn=f"sqlite:///{db_file}", read_only=False)

        log: list[tuple[str, int]] = []

        def recording_connect(connection_config: ConnectionConfig) -> Any:
            return _RecordingConnection(real_connect(connection_config), log)

        monkeypatch.setattr(cleansing_module, "get_connection", recording_connect)
        plan = cleanse_plan(config, configs, store=_NullStore(), run_id="run-chunk")
        return log, plan

    return _run


def _standardize_config() -> CleansingConfig:
    """Return a trim standardization over ``people.email``.

    Returns:
        A CleansingConfig.

    Example:
        config = _standardize_config()
    """
    return CleansingConfig(
        table_name="people",
        column_name="email",
        operation="standardize",
        params={"trim": True},
    )


class TestNoReadHoldsTheWholeTable:
    """The property, stated as a bound on what any one fetch returned."""

    def test_no_single_fetch_exceeds_the_page_size(self, plan_and_log: PlanAndLog) -> None:
        """Twenty-five rows, pages of ten, so nothing over ten at once.

        This is the memory bound restated as something observable. A
        ``fetchall`` over the whole table would show up here as a fetch of
        twenty-five.
        """
        log, _ = plan_and_log(_seed(SEEDED_ROWS), [_standardize_config()])

        oversized = [entry for entry in log if entry[1] > PAGE_SIZE]

        assert oversized == [], f"a read materialised more than {PAGE_SIZE} rows: {oversized}"

    def test_the_read_is_paged_rather_than_taken_once(self, plan_and_log: PlanAndLog) -> None:
        """Twenty-five rows in pages of ten is three reads: 10, 10, 5.

        Hand-derived from the counts, and asserted as a sequence rather than
        a total so that a single unbounded read cannot satisfy it.
        """
        log, _ = plan_and_log(_seed(SEEDED_ROWS), [_standardize_config()])

        page_sizes = [rows for statement, rows in log if statement.startswith("FETCH")]

        assert page_sizes == [10, 10, 5]

    def test_every_paged_read_is_bounded_in_the_sql(self, plan_and_log: PlanAndLog) -> None:
        """The bound is the database's job, not Python's.

        Slicing a full result set in Python would satisfy a count assertion
        while still dragging the table across the wire.
        """
        log, _ = plan_and_log(_seed(SEEDED_ROWS), [_standardize_config()])

        reads = [s for s, _ in log if s.startswith("SELECT") and "people" in s]

        assert reads, "no read reached the table"
        assert all("LIMIT" in s.upper() for s in reads), reads

    def test_the_rows_are_all_still_found(self, plan_and_log: PlanAndLog) -> None:
        """Paging that loses the last page is worse than no paging.

        Every seeded value has a trailing space, so all twenty-five change.
        Counted from ``_seed``, not from the planner.
        """
        _, plan = plan_and_log(_seed(SEEDED_ROWS), [_standardize_config()])

        assert len(plan.changes) == SEEDED_ROWS
        assert {change.row_key["id"] for change in plan.changes} == set(range(1, SEEDED_ROWS + 1))

    def test_a_page_boundary_landing_exactly_on_the_end_stops(
        self, plan_and_log: PlanAndLog
    ) -> None:
        """Twenty rows in pages of ten: two full pages and then nothing.

        The off-by-one worth pinning. A loop that stops only on a short page
        never stops here, so it must issue a third read that returns none --
        the counts are 10, 10, 0.
        """
        log, plan = plan_and_log(_seed(20), [_standardize_config()])

        page_sizes = [rows for statement, rows in log if statement.startswith("FETCH")]

        assert page_sizes == [10, 10, 0]
        assert len(plan.changes) == 20


class TestDeduplicationDoesNotWorkRowByRow:
    """One query for the duplicates, not one query per duplicate."""

    def test_capturing_before_values_costs_no_extra_round_trip(
        self, plan_and_log: PlanAndLog
    ) -> None:
        """Twelve duplicate rows used to mean twelve extra ``SELECT *``.

        The ranked query already visits those rows, so it can return their
        values. Per-row Python work over a table is the design smell
        ``CLAUDE.md`` names; this is the last one in cleansing.

        Seeded so that ``city`` repeats: fifteen rows over three cities, so
        twelve rows duplicate an earlier one.
        """
        script = (
            "CREATE TABLE people (id INTEGER PRIMARY KEY, city TEXT);"
            "INSERT INTO people (id, city) VALUES "
            + ", ".join(f"({n}, 'city{n % 3}')" for n in range(1, 16))
            + ";"
        )
        config = CleansingConfig(
            table_name="people",
            column_name=None,
            operation="deduplicate",
            params={"key_columns": ["city"], "keep": "first"},
        )

        log, plan = plan_and_log(script, [config])

        selects = [s for s, _ in log if s.startswith("SELECT") and "people" in s]
        assert len(plan.changes) == 12
        assert len(selects) == 1, f"one query should find them all, ran {len(selects)}"

    def test_the_before_values_are_still_the_whole_row(self, plan_and_log: PlanAndLog) -> None:
        """A DELETE has no after-value, so revert() needs every column.

        Dropping a column here would make the plan look cheaper and the
        revert incomplete -- the failure would surface only when someone
        tried to undo.
        """
        script = (
            "CREATE TABLE people (id INTEGER PRIMARY KEY, city TEXT, note TEXT);"
            "INSERT INTO people (id, city, note) VALUES "
            "(1, 'Tehran', 'first'), (2, 'Tehran', 'second');"
        )
        config = CleansingConfig(
            table_name="people",
            column_name=None,
            operation="deduplicate",
            params={"key_columns": ["city"], "keep": "first"},
        )

        _, plan = plan_and_log(script, [config])

        assert len(plan.changes) == 1
        before = plan.changes[0].before_value
        assert before == {"id": 2, "city": "Tehran", "note": "second"}
