"""Foreign-key discovery and orphan-row detection (`F2`).

Profiling reported row counts and nothing about how tables relate. F2 asks
for orphan rows and referential integrity, which is the question a DBA asks
about a database rather than about a column: *are there orders pointing at
customers that no longer exist?*

**A NULL foreign key is not an orphan.** An order with no `customer_id`
references nothing, which is a completeness question and already answered by
the null count. An order whose `customer_id` is `4102` when no customer
`4102` exists is a broken reference. Counting the first as the second would
inflate every orphan count on every nullable foreign key in the database,
and the number would look like a catastrophe rather than a bug in DQT.

**Composite keys are counted properly rather than skipped.** SQLite reports a
two-column foreign key as two `PRAGMA` rows sharing an id; treating each row
as its own single-column key would compare `r_code` against `regions.code`
alone and call a row matched when only half of it matches. That is a false
clean bill of health, so the anti-join carries every column of the key at
once.

**Cost.** One `COUNT(*)` anti-join per foreign key. That is not batchable the
way column statistics are -- each key joins a different parent table -- but
it is proportional to the number of keys, which is small, rather than to rows
or columns. No row is materialised.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from dqt.common.models import ConnectionConfig
from dqt.sql.referential import count_orphans
from dqt.sql.schema_discovery import discover_schema

SEEDED = """
    CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT);
    CREATE TABLE regions (code TEXT, sub TEXT, PRIMARY KEY (code, sub));
    CREATE TABLE orders (
        id INTEGER PRIMARY KEY,
        customer_id INTEGER REFERENCES customers(id),
        r_code TEXT,
        r_sub TEXT,
        FOREIGN KEY (r_code, r_sub) REFERENCES regions(code, sub)
    );
    INSERT INTO customers (id, name) VALUES (1, 'ali'), (2, 'sara');
    INSERT INTO regions (code, sub) VALUES ('IR', 'THR'), ('IR', 'SHZ');
    INSERT INTO orders (id, customer_id, r_code, r_sub) VALUES
        (1, 1,    'IR', 'THR'),
        (2, 2,    'IR', 'SHZ'),
        (3, 99,   'IR', 'THR'),
        (4, NULL, 'IR', 'THR'),
        (5, 1,    'IR', 'XXX');
"""
# Hand-derived from the INSERT above:
#   customer_id -> customers.id : row 3 points at 99, which does not exist.
#                                 Row 4 is NULL, which references nothing.
#                                 So ONE orphan, not two.
#   (r_code, r_sub) -> regions  : row 5 is ('IR','XXX'). 'IR' matches on its
#                                 own, which is exactly why the key must be
#                                 compared whole. ONE orphan.


def _tables(make_sqlite_db: Callable[[str, str], Path], name: str) -> tuple[object, object]:
    """Discover the seeded schema.

    Args:
        make_sqlite_db: Factory fixture building a SQLite file.
        name: Distinct database filename.

    Returns:
        A ``(connection_config, tables)`` tuple.

    Example:
        config, tables = _tables(make_sqlite_db, "a.db")
    """
    db_file = make_sqlite_db(name, SEEDED)
    config = ConnectionConfig(id="s", dsn=f"sqlite:///{db_file}")
    return config, discover_schema(config)


def _by_name(tables: object) -> dict[str, object]:
    """Index discovered tables by name.

    Args:
        tables: Discovered tables.

    Returns:
        Table name to :class:`~dqt.sql.schema_discovery.DiscoveredTable`.

    Example:
        assert "orders" in _by_name(tables)
    """
    return {table.table_name: table for table in tables}  # type: ignore[attr-defined]


class TestForeignKeysAreDiscovered:
    """The relationships have to be known before they can be checked."""

    def test_a_single_column_key_is_found(self, make_sqlite_db: Callable[[str, str], Path]) -> None:
        """``orders.customer_id`` references ``customers.id``."""
        _, tables = _tables(make_sqlite_db, "fk-single.db")
        orders = _by_name(tables)["orders"]

        simple = [fk for fk in orders.foreign_keys if fk.columns == ("customer_id",)]  # type: ignore[attr-defined]

        assert len(simple) == 1
        assert simple[0].referenced_table == "customers"
        assert simple[0].referenced_columns == ("id",)

    def test_a_composite_key_is_one_key_not_two(
        self, make_sqlite_db: Callable[[str, str], Path]
    ) -> None:
        """SQLite reports it as two rows sharing an id.

        Reading them as two independent keys is the bug this pins: each half
        would be checked against one parent column, and a row matching only
        one half would be counted as matched.
        """
        _, tables = _tables(make_sqlite_db, "fk-composite.db")
        orders = _by_name(tables)["orders"]

        composite = [fk for fk in orders.foreign_keys if len(fk.columns) == 2]  # type: ignore[attr-defined]

        assert len(composite) == 1
        assert composite[0].columns == ("r_code", "r_sub")
        assert composite[0].referenced_columns == ("code", "sub")
        assert len(orders.foreign_keys) == 2  # type: ignore[attr-defined]

    def test_a_table_without_relationships_reports_none(
        self, make_sqlite_db: Callable[[str, str], Path]
    ) -> None:
        """An empty list, not a missing attribute.

        Every consumer iterates this, and a table with no keys is the common
        case rather than an edge one.
        """
        _, tables = _tables(make_sqlite_db, "fk-none.db")

        assert _by_name(tables)["customers"].foreign_keys == []  # type: ignore[attr-defined]


class TestOrphansAreCounted:
    """The number a DBA actually wants."""

    def test_a_broken_reference_is_counted(
        self, make_sqlite_db: Callable[[str, str], Path]
    ) -> None:
        """Order 3 points at customer 99, which does not exist. One orphan."""
        config, tables = _tables(make_sqlite_db, "orphan-one.db")
        orders = _by_name(tables)["orders"]
        key = next(fk for fk in orders.foreign_keys if fk.columns == ("customer_id",))  # type: ignore[attr-defined]

        assert count_orphans(config, key) == 1

    def test_a_null_reference_is_not_an_orphan(
        self, make_sqlite_db: Callable[[str, str], Path]
    ) -> None:
        """Order 4 has no ``customer_id``, which references nothing.

        Asserted by the count above being 1 rather than 2 -- stated here as
        its own test because it is the assumption most likely to be broken
        by a later change, and the resulting number would look like a
        catastrophe rather than a bug.
        """
        config, tables = _tables(make_sqlite_db, "orphan-null.db")
        orders = _by_name(tables)["orders"]
        key = next(fk for fk in orders.foreign_keys if fk.columns == ("customer_id",))  # type: ignore[attr-defined]

        assert count_orphans(config, key) != 2

    def test_a_composite_key_is_matched_whole(
        self, make_sqlite_db: Callable[[str, str], Path]
    ) -> None:
        """Order 5 is ``('IR', 'XXX')``. ``'IR'`` alone matches; the pair does not.

        This is the test the composite handling exists for. A per-column
        implementation returns 0 here and reports a clean database.
        """
        config, tables = _tables(make_sqlite_db, "orphan-composite.db")
        orders = _by_name(tables)["orders"]
        key = next(fk for fk in orders.foreign_keys if len(fk.columns) == 2)  # type: ignore[attr-defined]

        assert count_orphans(config, key) == 1

    def test_an_intact_relationship_counts_zero(
        self, make_sqlite_db: Callable[[str, str], Path]
    ) -> None:
        """The control. Without it, every count above could be spurious."""
        sql = """
            CREATE TABLE parents (id INTEGER PRIMARY KEY);
            CREATE TABLE children (id INTEGER PRIMARY KEY,
                                   parent_id INTEGER REFERENCES parents(id));
            INSERT INTO parents (id) VALUES (1), (2);
            INSERT INTO children (id, parent_id) VALUES (1, 1), (2, 2), (3, NULL);
        """
        db_file = make_sqlite_db("orphan-clean.db", sql)
        config = ConnectionConfig(id="s", dsn=f"sqlite:///{db_file}")
        children = _by_name(discover_schema(config))["children"]
        key = children.foreign_keys[0]  # type: ignore[attr-defined]

        assert count_orphans(config, key) == 0


class TestTheCountIsCheap:
    """A referential check must not drag the child table into Python."""

    def test_it_materialises_no_rows(self, make_sqlite_db: Callable[[str, str], Path]) -> None:
        """``COUNT(*)`` over an anti-join, not a fetch-and-compare.

        `AGENTS.md` "Performance rules" forbids per-row Python work over a
        table, and a referential check is exactly where a naive
        implementation reaches for it: read the parent keys into a set, read
        the child rows, compare. That is correct and unusable at size.
        """
        db_file = make_sqlite_db("orphan-cost.db", SEEDED)
        config = ConnectionConfig(id="s", dsn=f"sqlite:///{db_file}")
        orders = _by_name(discover_schema(config))["orders"]
        key = next(fk for fk in orders.foreign_keys if fk.columns == ("customer_id",))  # type: ignore[attr-defined]

        import dqt.sql.referential as referential_module
        from dqt.sql._connect import get_connection as real_connect

        statements: list[str] = []

        def traced(*args: object, **kwargs: object) -> object:
            connection = real_connect(*args, **kwargs)  # type: ignore[arg-type]
            connection.set_trace_callback(statements.append)
            return connection

        original = referential_module.get_connection
        referential_module.get_connection = traced  # type: ignore[assignment]
        try:
            count_orphans(config, key)
        finally:
            referential_module.get_connection = original  # type: ignore[assignment]

        assert statements, "nothing was traced, so this proves nothing"
        selects = [s for s in statements if s.strip().upper().startswith("SELECT")]

        assert len(selects) == 1, f"expected one query, got {selects}"
        assert "COUNT(" in selects[0].upper()


class TestOrphansReachTheRun:
    """A count that stops in a helper is the `F10` failure again."""

    def test_a_broken_reference_becomes_a_referential_integrity_issue(
        self, make_sqlite_db: Callable[[str, str], Path], tmp_path: Path
    ) -> None:
        """The dimension the dashboard has always rendered as "not measured".

        There are two orphans in the fixture -- one per key -- and they are
        the whole point of the facet: a column-by-column profiler cannot see
        either of them, because each individual value looks fine.
        """
        result = _run_pipeline(make_sqlite_db, tmp_path, "pipeline-orphans.db")
        issues = [
            issue
            for issue in result.issues  # type: ignore[attr-defined]
            if issue.dimension == "referential_integrity"
        ]

        assert len(issues) == 2
        assert all(issue.table_name == "orders" for issue in issues)

    def test_an_intact_database_raises_nothing(
        self, make_sqlite_db: Callable[[str, str], Path], tmp_path: Path
    ) -> None:
        """The control. A check that always fires says nothing."""
        sql = """
            CREATE TABLE parents (id INTEGER PRIMARY KEY);
            CREATE TABLE children (id INTEGER PRIMARY KEY,
                                   parent_id INTEGER REFERENCES parents(id));
            INSERT INTO parents (id) VALUES (1);
            INSERT INTO children (id, parent_id) VALUES (1, 1), (2, NULL);
        """
        result = _run_pipeline(make_sqlite_db, tmp_path, "pipeline-clean.db", sql)

        assert not [
            issue
            for issue in result.issues  # type: ignore[attr-defined]
            if issue.dimension == "referential_integrity"
        ]

    def test_the_dimension_is_scored_rather_than_unmeasured(
        self, make_sqlite_db: Callable[[str, str], Path], tmp_path: Path
    ) -> None:
        """ "Not measured" and "measured, and fine" are different answers.

        The dashboard has rendered referential integrity as unmeasured since
        it was built. A metric has to exist for it to say anything else, and
        an intact database is exactly the case where the distinction matters
        -- silence there is indistinguishable from not having looked.
        """
        sql = """
            CREATE TABLE parents (id INTEGER PRIMARY KEY);
            CREATE TABLE children (id INTEGER PRIMARY KEY,
                                   parent_id INTEGER REFERENCES parents(id));
            INSERT INTO parents (id) VALUES (1);
            INSERT INTO children (id, parent_id) VALUES (1, 1);
        """
        result = _run_pipeline(make_sqlite_db, tmp_path, "pipeline-scored.db", sql)
        metrics = [
            metric
            for metric in result.metrics  # type: ignore[attr-defined]
            if metric.dimension == "referential_integrity"
        ]

        assert metrics, "referential integrity produced no metric"
        assert metrics[0].score == 1.0


def _run_pipeline(
    make_sqlite_db: Callable[[str, str], Path],
    tmp_path: Path,
    name: str,
    sql: str = SEEDED,
) -> object:
    """Run the whole pipeline over a seeded database.

    Args:
        make_sqlite_db: Factory fixture building a SQLite file.
        tmp_path: pytest's per-test directory.
        name: Distinct database filename.
        sql: Schema and data to seed.

    Returns:
        The :class:`~dqt.common.models.PipelineResult`.

    Example:
        result = _run_pipeline(make_sqlite_db, tmp_path, "a.db")
    """
    from dqt.common.models import DQPipelineConfig
    from dqt.sql.pipeline import DQTPipeline

    db_file = make_sqlite_db(name, sql)
    result, _ = DQTPipeline(
        ConnectionConfig(id="s", dsn=f"sqlite:///{db_file}"),
        DQPipelineConfig(connection_id="s"),
        store_path=tmp_path / "runs.db",
        report_dir=tmp_path,
    ).run()
    return result
