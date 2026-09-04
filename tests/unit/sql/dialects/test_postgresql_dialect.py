"""Unit tests for the PostgreSQL dialect's pure SQL construction.

No PostgreSQL server or driver exists in this repository's CI or development
environment, so nothing here opens a connection. Every expected string is
hand-written from the SQL ``schema_discovery.py`` and ``rules.py`` emitted for
PostgreSQL before `DQT-08` moved it into this dialect; the connection and
introspection paths remain unexercised and are named as such in
``postgresql.py``'s own module docstring.
"""

from __future__ import annotations

import pytest

from dqt.sql.dialects.base import ReadOnlyEnforcement
from dqt.sql.dialects.postgresql import COLUMN_METADATA_SQL, POSTGRESQL


class TestIdentifierQuoting:
    def test_plain_identifier(self):
        assert POSTGRESQL.quote_identifier("orders") == '"orders"'

    def test_embedded_double_quote_is_doubled(self):
        assert POSTGRESQL.quote_identifier('a"b') == '"a""b"'


class TestQualifiedIdentifier:
    def test_schema_is_always_qualified(self):
        assert POSTGRESQL.qualified_identifier("public", "orders") == '"public"."orders"'

    def test_none_schema_is_unqualified(self):
        assert POSTGRESQL.qualified_identifier(None, "orders") == '"orders"'

    def test_a_schema_literally_named_main_is_not_suppressed(self):
        """PostgreSQL has no implicit "main"; a schema so named is real.

        Before `DQT-08`, the shared ``qualified_identifier`` applied SQLite's
        "main is implicit" rule to every dialect, so a PostgreSQL table in a
        schema named ``main`` was addressed unqualified and silently resolved
        through ``search_path`` to whatever table that found. Ground truth is
        PostgreSQL's own naming rules, not DQT's code: ``main`` there is an
        ordinary schema name.
        """
        assert POSTGRESQL.qualified_identifier("main", "orders") == '"main"."orders"'


class TestSelectAggregatesSql:
    def test_single_expression(self):
        assert POSTGRESQL.select_aggregates_sql('"t"', ["COUNT(*)"]) == 'SELECT COUNT(*) FROM "t"'

    def test_where_clause_is_appended(self):
        assert (
            POSTGRESQL.select_aggregates_sql('"t"', ["COUNT(*)"], '"c" IS NULL')
            == 'SELECT COUNT(*) FROM "t" WHERE "c" IS NULL'
        )

    def test_empty_expressions_is_a_programming_error(self):
        with pytest.raises(ValueError, match="at least one expression"):
            POSTGRESQL.select_aggregates_sql('"t"', [])


class TestLimitedSelectSql:
    def test_limit_is_a_trailing_clause(self):
        assert POSTGRESQL.limited_select_sql('"t"', ["*"], limit=5) == 'SELECT * FROM "t" LIMIT 5'

    @pytest.mark.parametrize("bad_limit", [0, -1])
    def test_non_positive_limit_is_rejected(self, bad_limit):
        with pytest.raises(ValueError, match="positive"):
            POSTGRESQL.limited_select_sql('"t"', ["*"], limit=bad_limit)


class TestRegexPredicate:
    def test_predicate_uses_the_native_operator(self):
        # Byte-for-byte the WHERE body rules._eval_regex built for
        # PostgreSQL before the move, placeholder included.
        assert (
            POSTGRESQL.regex_not_matching_predicate('"email"', "^a")
            == '"email" IS NOT NULL AND NOT ("email" ~ %s)'
        )

    def test_pattern_is_never_interpolated_into_the_sql(self):
        predicate = POSTGRESQL.regex_not_matching_predicate('"email"', "'; DROP TABLE users; --")
        assert "DROP TABLE" not in predicate
        assert predicate.count("%s") == 1

    def test_pattern_is_not_pre_compiled_by_python(self):
        """A pattern Python rejects must still reach the server.

        PostgreSQL uses POSIX regular expressions, not Python's dialect, so
        pre-validating with :mod:`re` would reject patterns the server
        accepts. This asserts the dialect does not do that.
        """
        predicate = POSTGRESQL.regex_not_matching_predicate('"e"', "(unbalanced")

        # Reaching this line is most of the assertion: a dialect that ran the
        # pattern through re.compile would have raised on "(unbalanced".
        assert "%s" in predicate
        # And the pattern travels as a bind parameter, never interpolated --
        # which is both why the server gets to judge it and why a pattern can
        # never carry SQL into the statement.
        assert "unbalanced" not in predicate


class TestApproximateDistinct:
    def test_stock_postgresql_has_no_builtin_approximation(self):
        assert POSTGRESQL.approximate_distinct_expression('"c"') is None


class TestIntrospectionSql:
    def test_column_metadata_sql_is_unchanged_from_the_pre_move_query(self):
        # Hand-compared against schema_discovery._discover_postgres as it
        # stood on main before DQT-08.
        normalised = " ".join(COLUMN_METADATA_SQL.split())
        assert normalised == (
            "SELECT table_schema, table_name, column_name, data_type, is_nullable "
            "FROM information_schema.columns "
            "WHERE table_schema NOT IN ('information_schema', 'pg_catalog') "
            "ORDER BY table_schema, table_name, ordinal_position"
        )


class TestReadOnlyEnforcementLevel:
    def test_postgresql_read_only_is_driver_enforced(self):
        assert POSTGRESQL.read_only_enforcement is ReadOnlyEnforcement.DRIVER_ENFORCED
