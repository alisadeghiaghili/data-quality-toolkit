"""Unit tests for the SQLite dialect.

Expected SQL strings below are written by hand from the SQL that
``schema_discovery.py``, ``profiling.py`` and ``rules.py`` emitted before
`DQT-08` moved it here. That is the point of these tests: they pin the moved
SQL to what it was, so a "pure move" that quietly changed a query is caught.
"""

from __future__ import annotations

import sqlite3

import pytest

from dqt.common.models import ConnectionConfig
from dqt.sql.dialects.base import ReadOnlyEnforcement
from dqt.sql.dialects.sqlite import (
    REGEX_CACHE_MAXSIZE,
    REGEX_PATTERN_MAX_LENGTH,
    SQLITE,
    compile_regex_pattern,
    sqlite_regexp,
)


class TestIdentifierQuoting:
    def test_plain_identifier(self):
        assert SQLITE.quote_identifier("orders") == '"orders"'

    def test_embedded_double_quote_is_doubled(self):
        # ANSI escaping: one embedded quote becomes two, so the identifier
        # cannot terminate early. Hand-derived, not measured.
        assert SQLITE.quote_identifier('a"b') == '"a""b"'

    def test_injection_payload_stays_inside_the_identifier(self):
        payload = 'x"; DROP TABLE users; --'
        assert SQLITE.quote_identifier(payload) == '"x""; DROP TABLE users; --"'


class TestQualifiedIdentifier:
    def test_none_schema_is_unqualified(self):
        assert SQLITE.qualified_identifier(None, "orders") == '"orders"'

    def test_implicit_main_schema_is_suppressed(self):
        # "main" is the name SQLite gives its implicit default schema, not a
        # schema a DBA created, so it must not appear in the reference.
        assert SQLITE.qualified_identifier("main", "orders") == '"orders"'

    def test_attached_schema_is_qualified(self):
        assert SQLITE.qualified_identifier("aux", "orders") == '"aux"."orders"'


class TestSelectAggregatesSql:
    def test_single_expression(self):
        assert SQLITE.select_aggregates_sql('"t"', ["COUNT(*)"]) == 'SELECT COUNT(*) FROM "t"'

    def test_where_clause_is_appended(self):
        assert (
            SQLITE.select_aggregates_sql('"t"', ["COUNT(*)"], '"c" IS NULL')
            == 'SELECT COUNT(*) FROM "t" WHERE "c" IS NULL'
        )

    def test_many_expressions_share_one_scan(self):
        # This is the single-pass-profiling seam: N column statistics in one
        # statement, not N statements. Nothing calls it that way yet; the
        # interface must already permit it.
        sql = SQLITE.select_aggregates_sql('"t"', ["COUNT(*)", 'COUNT("a")', 'COUNT("b")'])
        assert sql == 'SELECT COUNT(*), COUNT("a"), COUNT("b") FROM "t"'

    def test_empty_expressions_is_a_programming_error(self):
        with pytest.raises(ValueError, match="at least one expression"):
            SQLITE.select_aggregates_sql('"t"', [])


class TestLimitedSelectSql:
    def test_limit_is_a_trailing_clause(self):
        assert SQLITE.limited_select_sql('"t"', ["*"], limit=5) == 'SELECT * FROM "t" LIMIT 5'

    def test_limit_follows_the_where_clause(self):
        assert (
            SQLITE.limited_select_sql('"t"', ["*"], '"c" IS NULL', 3)
            == 'SELECT * FROM "t" WHERE "c" IS NULL LIMIT 3'
        )

    def test_no_limit_is_a_plain_select(self):
        assert SQLITE.limited_select_sql('"t"', ["*"]) == 'SELECT * FROM "t"'

    @pytest.mark.parametrize("bad_limit", [0, -1])
    def test_non_positive_limit_is_rejected(self, bad_limit):
        with pytest.raises(ValueError, match="positive"):
            SQLITE.limited_select_sql('"t"', ["*"], limit=bad_limit)


class TestRegexPredicate:
    def test_predicate_matches_the_pre_dqt_08_sql(self):
        # Byte-for-byte the WHERE body rules._eval_regex built before the
        # move, so the SQLite regex path is provably unchanged.
        assert (
            SQLITE.regex_not_matching_predicate('"email"', "^a")
            == '"email" IS NOT NULL AND "email" NOT REGEXP ?'
        )

    def test_pattern_is_never_interpolated_into_the_sql(self):
        payload = "'; DROP TABLE users; --"
        predicate = SQLITE.regex_not_matching_predicate('"email"', payload)
        assert "DROP TABLE" not in predicate
        assert predicate.endswith("?")

    def test_malformed_pattern_is_rejected_before_any_query_is_built(self):
        with pytest.raises(ValueError, match="Invalid regex pattern"):
            SQLITE.regex_not_matching_predicate('"email"', "(unbalanced")

    def test_over_long_pattern_is_rejected(self):
        with pytest.raises(ValueError, match="exceeds the maximum"):
            SQLITE.regex_not_matching_predicate('"email"', "a" * (REGEX_PATTERN_MAX_LENGTH + 1))


class TestRegexpCallback:
    """SQLite's REGEXP(X, Y) takes the pattern first and the value second."""

    def test_match(self):
        assert sqlite_regexp("^a", "abc") is True

    def test_non_match(self):
        assert sqlite_regexp("^a", "zzz") is False

    def test_null_value_is_null_not_false(self):
        # A NULL is "not applicable", never "invalid".
        assert sqlite_regexp("^a", None) is None

    def test_non_string_value_is_coerced(self):
        assert sqlite_regexp("^1", 123) is True

    def test_compiled_pattern_cache_is_bounded(self):
        info = compile_regex_pattern.cache_info()
        assert info.maxsize == REGEX_CACHE_MAXSIZE
        assert info.maxsize is not None and info.maxsize > 0


class TestApproximateDistinct:
    def test_sqlite_has_no_approximation(self):
        assert SQLITE.approximate_distinct_expression('"c"') is None


class TestConnect:
    def test_memory_database_is_opened_writable_despite_read_only(self, tmp_path):
        # Documented DQT-03 carve-out: a fresh in-memory database is not a
        # persistent asset, and mode=ro would only make it permanently empty.
        config = ConnectionConfig(id="t", dsn="sqlite:///:memory:")
        assert config.read_only is True
        connection = SQLITE.connect(config)
        try:
            connection.execute("CREATE TABLE t (a INTEGER)")
        finally:
            connection.close()

    def test_regexp_function_is_registered_on_every_connection(self):
        config = ConnectionConfig(id="t", dsn="sqlite:///:memory:")
        connection = SQLITE.connect(config)
        try:
            rows = connection.execute("SELECT 1 WHERE 'abc' REGEXP '^a'").fetchall()
            assert len(rows) == 1
            rows = connection.execute("SELECT 1 WHERE 'zzz' REGEXP '^a'").fetchall()
            assert rows == []
        finally:
            connection.close()

    def test_row_factory_is_sqlite_row(self):
        config = ConnectionConfig(id="t", dsn="sqlite:///:memory:")
        connection = SQLITE.connect(config)
        try:
            assert connection.row_factory is sqlite3.Row
        finally:
            connection.close()

    def test_read_only_connection_rejects_writes(self, tmp_path):
        db_path = tmp_path / "seeded.db"
        seed = sqlite3.connect(db_path)
        seed.execute("CREATE TABLE t (a INTEGER)")
        seed.execute("INSERT INTO t VALUES (1)")
        seed.commit()
        seed.close()

        config = ConnectionConfig(id="t", dsn=f"sqlite:///{db_path}")
        connection = SQLITE.connect(config)
        try:
            with pytest.raises(sqlite3.OperationalError, match="readonly database"):
                connection.execute("INSERT INTO t VALUES (2)")
                connection.commit()
        finally:
            connection.close()

    def test_read_only_false_permits_writes(self, tmp_path):
        db_path = tmp_path / "writable.db"
        config = ConnectionConfig(id="t", dsn=f"sqlite:///{db_path}", read_only=False)
        connection = SQLITE.connect(config)
        try:
            connection.execute("CREATE TABLE t (a INTEGER)")
            connection.execute("INSERT INTO t VALUES (1)")
            connection.commit()
            assert connection.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 1
        finally:
            connection.close()

    def test_read_only_open_of_a_missing_file_raises_instead_of_creating_it(self, tmp_path):
        missing = tmp_path / "absent.db"
        config = ConnectionConfig(id="t", dsn=f"sqlite:///{missing}")
        with pytest.raises(sqlite3.OperationalError):
            SQLITE.connect(config)
        assert not missing.exists()

    def test_enforcement_level_is_driver_enforced(self):
        assert SQLITE.read_only_enforcement is ReadOnlyEnforcement.DRIVER_ENFORCED


class TestFetchColumnMetadata:
    def test_reports_hand_written_ddl_exactly(self, tmp_path):
        """Discovery must report the tables and columns the DDL declares.

        Ground truth is the CREATE TABLE text below, written by hand: two
        base tables, one view (which must not appear), and known nullability
        per column.
        """
        db_path = tmp_path / "schema.db"
        seed = sqlite3.connect(db_path)
        seed.executescript("""
            CREATE TABLE customers (
                id INTEGER NOT NULL,
                email TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE orders (
                order_id INTEGER NOT NULL,
                amount REAL
            );
            CREATE VIEW recent_orders AS SELECT * FROM orders;
        """)
        seed.commit()
        seed.close()

        config = ConnectionConfig(id="t", dsn=f"sqlite:///{db_path}")
        connection = SQLITE.connect(config)
        try:
            rows = SQLITE.fetch_column_metadata(connection)
        finally:
            connection.close()

        assert [(r.table_name, r.column_name, r.data_type, r.nullable) for r in rows] == [
            ("customers", "id", "INTEGER", False),
            ("customers", "email", "TEXT", True),
            ("customers", "created_at", "TEXT", False),
            ("orders", "order_id", "INTEGER", False),
            ("orders", "amount", "REAL", True),
        ]
        assert all(row.schema_name == "main" for row in rows)

    def test_views_and_sqlite_internal_tables_are_excluded(self, tmp_path):
        db_path = tmp_path / "views.db"
        seed = sqlite3.connect(db_path)
        seed.executescript("""
            CREATE TABLE t (id INTEGER PRIMARY KEY AUTOINCREMENT);
            CREATE VIEW v AS SELECT * FROM t;
        """)
        seed.commit()
        seed.close()

        config = ConnectionConfig(id="t", dsn=f"sqlite:///{db_path}")
        connection = SQLITE.connect(config)
        try:
            table_names = {row.table_name for row in SQLITE.fetch_column_metadata(connection)}
        finally:
            connection.close()

        # AUTOINCREMENT creates sqlite_sequence; it is not a user table.
        assert table_names == {"t"}
