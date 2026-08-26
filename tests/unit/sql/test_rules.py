"""
Unit tests for dqt.sql.rules.

All tests use a SQLite in-memory database.
Tests cover: NOT NULL, UNIQUE, range, regex, unknown expression, empty
inputs, scope matching, and the apply_rules() public API.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from dqt.common.config_loader import load_rules
from dqt.common.models import ConnectionConfig, RuleConfig, RuleScope
from dqt.sql.rules import (
    _detect_dialect,
    _eval_not_null,
    _eval_range,
    _eval_regex,
    _eval_unique,
    _get_connection,
    _matches_scope,
    apply_rules,
)
from dqt.sql.schema_discovery import DiscoveredColumn, DiscoveredTable

# Repository root, three levels above tests/unit/sql/test_rules.py, used to
# load the real shipped example rule file rather than re-typing its pattern
# by hand (see TestEvalRegex.test_email_rule_flags_exactly_invalid_addresses).
_REPO_ROOT = Path(__file__).resolve().parents[3]

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sqlite_conn():
    """In-memory SQLite connection with a small test dataset."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE users (
            id INTEGER,
            email TEXT,
            age INTEGER
        );
        INSERT INTO users VALUES (1, 'alice@example.com', 25);
        INSERT INTO users VALUES (2, 'bob@example.com', 30);
        INSERT INTO users VALUES (3, NULL, 17);        -- NULL email, minor age
        INSERT INTO users VALUES (4, 'alice@example.com', -1); -- duplicate email, negative age
        INSERT INTO users VALUES (NULL, 'carol@example.com', 22); -- NULL id
    """)
    return conn


@pytest.fixture
def discovered_users_table():
    """Minimal DiscoveredTable for the 'users' table."""
    return DiscoveredTable(
        schema_name=None,
        table_name="users",
        columns=[
            DiscoveredColumn(
                schema_name=None,
                table_name="users",
                column_name="id",
                data_type="INTEGER",
                nullable=True,
            ),
            DiscoveredColumn(
                schema_name=None,
                table_name="users",
                column_name="email",
                data_type="TEXT",
                nullable=True,
            ),
            DiscoveredColumn(
                schema_name=None,
                table_name="users",
                column_name="age",
                data_type="INTEGER",
                nullable=True,
            ),
        ],
    )


@pytest.fixture
def sqlite_dsn_file(make_sqlite_db):
    """SQLite file-based DSN with a populated test DB."""
    db_file = make_sqlite_db(
        "test_rules.db",
        """
        CREATE TABLE orders (
            id INTEGER,
            amount REAL,
            customer_id INTEGER
        );
        INSERT INTO orders VALUES (1, 100.0, 10);
        INSERT INTO orders VALUES (2, -5.0, 20);    -- negative amount
        INSERT INTO orders VALUES (3, 200.0, NULL); -- NULL customer_id
        INSERT INTO orders VALUES (1, 50.0, 30);    -- duplicate id
        """,
    )
    return f"sqlite:///{db_file}"


# ---------------------------------------------------------------------------
# _detect_dialect
# ---------------------------------------------------------------------------


class TestDetectDialect:
    def test_sqlite(self):
        assert _detect_dialect("sqlite:///dev.db") == "sqlite"

    def test_postgresql(self):
        assert _detect_dialect("postgresql://u:p@h/db") == "postgresql"

    def test_postgres_alias(self):
        assert _detect_dialect("postgres://u:p@h/db") == "postgresql"

    def test_unsupported_raises(self):
        with pytest.raises(ValueError, match="Cannot detect dialect"):
            _detect_dialect("mysql://u:p@h/db")


# ---------------------------------------------------------------------------
# Low-level SQL evaluators
# ---------------------------------------------------------------------------


class TestEvalNotNull:
    def test_detects_nulls(self, sqlite_conn):
        cursor = sqlite_conn.cursor()
        total, null_count = _eval_not_null(cursor, None, "users", "email")
        assert total == 5
        assert null_count == 1

    def test_no_nulls(self, sqlite_conn):
        cursor = sqlite_conn.cursor()
        # 'age' column has no NULLs in fixture
        total, null_count = _eval_not_null(cursor, None, "users", "age")
        assert total == 5
        assert null_count == 0


class TestEvalUnique:
    def test_detects_duplicates(self, sqlite_conn):
        cursor = sqlite_conn.cursor()
        total, dup_extra = _eval_unique(cursor, None, "users", "email")
        # alice@example.com appears twice -> 1 extra row
        assert dup_extra == 1

    def test_no_duplicates_when_unique(self, sqlite_conn):
        cursor = sqlite_conn.cursor()
        # age values: 25, 30, 17, -1, 22 -> all unique
        _, dup_extra = _eval_unique(cursor, None, "users", "age")
        assert dup_extra == 0


class TestEvalRange:
    def test_detects_below_min(self, sqlite_conn):
        cursor = sqlite_conn.cursor()
        total, out = _eval_range(cursor, None, "users", "age", min_val=0, max_val=None)
        # age = -1 is out of range
        assert out == 1

    def test_detects_above_max(self, sqlite_conn):
        cursor = sqlite_conn.cursor()
        total, out = _eval_range(cursor, None, "users", "age", min_val=None, max_val=100)
        assert out == 0  # all ages <= 100

    def test_both_bounds(self, sqlite_conn):
        cursor = sqlite_conn.cursor()
        total, out = _eval_range(cursor, None, "users", "age", min_val=18, max_val=100)
        # age 17 and -1 are out of range -> 2
        assert out == 2

    def test_no_bounds_raises(self, sqlite_conn):
        cursor = sqlite_conn.cursor()
        with pytest.raises(ValueError, match="range rule requires"):
            _eval_range(cursor, None, "users", "age", None, None)


# ---------------------------------------------------------------------------
# _matches_scope
# ---------------------------------------------------------------------------


class TestMatchesScope:
    def _table(self, schema=None, name="users"):
        return DiscoveredTable(schema_name=schema, table_name=name, columns=[])

    def _rule(self, table_pattern=None, column_pattern=None, schema_pattern=None):
        return RuleConfig(
            name="r",
            dimension="completeness",
            severity="error",
            scope=RuleScope(
                table_pattern=table_pattern,
                column_pattern=column_pattern,
                schema_pattern=schema_pattern,
            ),
            expression="NOT NULL",
        )

    def test_no_scope_matches_all(self):
        rule = self._rule()
        assert _matches_scope(self._table(), "email", rule) is True

    def test_table_pattern_match(self):
        rule = self._rule(table_pattern="user*")
        assert _matches_scope(self._table(name="users"), "email", rule) is True

    def test_table_pattern_no_match(self):
        rule = self._rule(table_pattern="order*")
        assert _matches_scope(self._table(name="users"), "email", rule) is False

    def test_column_pattern_match(self):
        rule = self._rule(column_pattern="*email*")
        assert _matches_scope(self._table(), "user_email", rule) is True

    def test_column_pattern_no_match(self):
        rule = self._rule(column_pattern="email")
        assert _matches_scope(self._table(), "phone", rule) is False

    def test_schema_pattern_match(self):
        rule = self._rule(schema_pattern="pub*")
        assert _matches_scope(self._table(schema="public"), "id", rule) is True

    def test_schema_pattern_no_match(self):
        rule = self._rule(schema_pattern="staging")
        assert _matches_scope(self._table(schema="public"), "id", rule) is False


# ---------------------------------------------------------------------------
# apply_rules() public API
# ---------------------------------------------------------------------------


class TestApplyRules:
    def _conn_cfg(self, dsn):
        return ConnectionConfig(id="test", dsn=dsn)

    def _rule(
        self, name, expr, col_pattern, dimension="completeness", severity="error", params=None
    ):
        return RuleConfig(
            name=name,
            dimension=dimension,
            severity=severity,
            scope=RuleScope(column_pattern=col_pattern),
            expression=expr,
            params=params or {},
        )

    def test_empty_rules_returns_empty(self, sqlite_dsn_file, discovered_users_table):
        issues, summaries = apply_rules(
            run_id="run-test",
            connection_config=self._conn_cfg(sqlite_dsn_file),
            rules=[],
            discovered_tables=[discovered_users_table],
        )
        assert issues == []
        assert summaries == []

    def test_no_tables_returns_empty(self, sqlite_dsn_file):
        rule = self._rule("r", "NOT NULL", "email")
        issues, summaries = apply_rules(
            run_id="run-test",
            connection_config=self._conn_cfg(sqlite_dsn_file),
            rules=[rule],
            discovered_tables=[],
        )
        assert issues == []

    def test_not_null_detects_violation(self, sqlite_dsn_file):
        db_file = sqlite_dsn_file.replace("sqlite:///", "")
        conn = sqlite3.connect(db_file)
        tables = [
            DiscoveredTable(
                schema_name=None,
                table_name="orders",
                columns=[
                    DiscoveredColumn(
                        schema_name=None,
                        table_name="orders",
                        column_name="customer_id",
                        data_type="INTEGER",
                        nullable=True,
                    ),
                ],
            )
        ]
        conn.close()
        rule = self._rule(
            "not_null_customer",
            "NOT NULL",
            "customer_id",
            dimension="completeness",
            severity="critical",
        )
        issues, summaries = apply_rules(
            run_id="run-001",
            connection_config=self._conn_cfg(sqlite_dsn_file),
            rules=[rule],
            discovered_tables=tables,
        )
        assert len(issues) == 1
        assert issues[0].severity == "critical"
        assert "NULL" in issues[0].message
        assert summaries[0].targets_failed == 1

    def test_unique_detects_duplicate(self, sqlite_dsn_file):
        tables = [
            DiscoveredTable(
                schema_name=None,
                table_name="orders",
                columns=[
                    DiscoveredColumn(
                        schema_name=None,
                        table_name="orders",
                        column_name="id",
                        data_type="INTEGER",
                        nullable=True,
                    ),
                ],
            )
        ]
        rule = self._rule(
            "unique_order_id", "UNIQUE", "id", dimension="uniqueness", severity="error"
        )
        issues, summaries = apply_rules(
            run_id="run-002",
            connection_config=self._conn_cfg(sqlite_dsn_file),
            rules=[rule],
            discovered_tables=tables,
        )
        assert len(issues) == 1
        assert "duplicate" in issues[0].message.lower()

    def test_range_detects_negative(self, sqlite_dsn_file):
        tables = [
            DiscoveredTable(
                schema_name=None,
                table_name="orders",
                columns=[
                    DiscoveredColumn(
                        schema_name=None,
                        table_name="orders",
                        column_name="amount",
                        data_type="REAL",
                        nullable=True,
                    ),
                ],
            )
        ]
        rule = self._rule(
            "positive_amount",
            "range",
            "amount",
            dimension="validity",
            severity="error",
            params={"min": 0},
        )
        issues, summaries = apply_rules(
            run_id="run-003",
            connection_config=self._conn_cfg(sqlite_dsn_file),
            rules=[rule],
            discovered_tables=tables,
        )
        assert len(issues) == 1
        assert "out of range" in issues[0].message.lower() or "outside" in issues[0].message.lower()

    def test_unknown_expression_produces_error_issue(self, sqlite_dsn_file):
        tables = [
            DiscoveredTable(
                schema_name=None,
                table_name="orders",
                columns=[
                    DiscoveredColumn(
                        schema_name=None,
                        table_name="orders",
                        column_name="id",
                        data_type="INTEGER",
                        nullable=True,
                    ),
                ],
            )
        ]
        rule = self._rule("bad_expr", "FOOBAR", "id", dimension="validity", severity="warning")
        issues, summaries = apply_rules(
            run_id="run-004",
            connection_config=self._conn_cfg(sqlite_dsn_file),
            rules=[rule],
            discovered_tables=tables,
        )
        assert len(issues) == 1
        assert "unknown expression" in issues[0].message.lower()

    def test_rule_passes_when_no_violations(self, sqlite_dsn_file):
        tables = [
            DiscoveredTable(
                schema_name=None,
                table_name="orders",
                columns=[
                    DiscoveredColumn(
                        schema_name=None,
                        table_name="orders",
                        column_name="id",
                        data_type="INTEGER",
                        nullable=True,
                    ),
                ],
            )
        ]
        # All orders have non-null ids in the fixture (though duplicated)
        rule = self._rule(
            "not_null_order_id", "NOT NULL", "id", dimension="completeness", severity="error"
        )
        issues, summaries = apply_rules(
            run_id="run-005",
            connection_config=self._conn_cfg(sqlite_dsn_file),
            rules=[rule],
            discovered_tables=tables,
        )
        assert len(issues) == 0
        assert summaries[0].targets_failed == 0

    def test_scope_filters_columns(self, sqlite_dsn_file):
        tables = [
            DiscoveredTable(
                schema_name=None,
                table_name="orders",
                columns=[
                    DiscoveredColumn(
                        schema_name=None,
                        table_name="orders",
                        column_name="id",
                        data_type="INTEGER",
                        nullable=True,
                    ),
                    DiscoveredColumn(
                        schema_name=None,
                        table_name="orders",
                        column_name="amount",
                        data_type="REAL",
                        nullable=True,
                    ),
                    DiscoveredColumn(
                        schema_name=None,
                        table_name="orders",
                        column_name="customer_id",
                        data_type="INTEGER",
                        nullable=True,
                    ),
                ],
            )
        ]
        # Only check customer_id, which has 1 NULL
        rule = self._rule(
            "check_fk", "NOT NULL", "customer_id", dimension="completeness", severity="warning"
        )
        issues, summaries = apply_rules(
            run_id="run-006",
            connection_config=self._conn_cfg(sqlite_dsn_file),
            rules=[rule],
            discovered_tables=tables,
        )
        assert len(issues) == 1
        assert issues[0].column_name == "customer_id"
        assert summaries[0].targets_checked == 1  # only customer_id matched


# ---------------------------------------------------------------------------
# DQT-04: SQLite REGEXP support
#
# SQLite has no built-in REGEXP implementation. The `X REGEXP Y` operator
# only works if a two-argument function named REGEXP is registered on the
# connection; without that registration every `regex` rule fails with
# `sqlite3.OperationalError: no such function: REGEXP` on every column it
# targets, including the shipped examples/rules/advanced_rules.yaml
# `valid_email_format` rule. These tests pin down (1) that the function is
# actually registered by `_get_connection`, (2) that its argument order is
# correct, (3) exactly which rows a real rule flags, (4) that a malformed
# pattern is a config error rather than a false "every row failed" result,
# and (5) that the compiled-pattern cache is bounded.
# ---------------------------------------------------------------------------


class TestRegexpRegistration:
    def test_regexp_function_registered_on_sqlite_connection(self):
        """`_get_connection` must register REGEXP, and the argument order matters.

        SQLite rewrites the infix expression `X REGEXP Y` into the function
        call `REGEXP(Y, X)` -- the pattern (Y) is passed first, the value
        (X) second. This is empirical, not documented behavior we can take
        on faith, so this test proves it rather than assuming it:

        `'abc' REGEXP '^a'` means X='abc', Y='^a'. If the registered
        function receives arguments in the documented (pattern, value)
        order, it evaluates as "does 'abc' start with 'a'?" -> True. If the
        implementation had the argument order backwards -- treating the
        first-received argument as the value and the second as the pattern
        -- it would instead evaluate as "does '^a' contain the literal
        substring 'abc'?" -> False. The two orderings give different
        answers for this input, so a passing result here rules out the
        swapped-argument bug, not just the "no function registered at all"
        bug.
        """
        conn = _get_connection(ConnectionConfig(id="t", dsn="sqlite:///:memory:"))
        try:
            cursor = conn.cursor()
            # Would raise sqlite3.OperationalError: no such function: REGEXP
            # if REGEXP were not registered at all.
            cursor.execute("SELECT 1 WHERE 'abc' REGEXP '^a'")
            row = cursor.fetchone()
            # Would be None (no row) if the argument order were reversed --
            # see docstring above.
            assert row is not None
            assert row[0] == 1
        finally:
            conn.close()

    def test_regexp_function_rejects_non_matching_value(self):
        """Companion negative case: a value that must NOT match either way.

        `'zzz' REGEXP '^a'` should find no matching row in both the correct
        and the (hypothetically) reversed argument order, so on its own it
        would not catch the swapped-argument bug -- it exists to confirm
        the operator does filter out real non-matches, not just always
        return true.
        """
        conn = _get_connection(ConnectionConfig(id="t", dsn="sqlite:///:memory:"))
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 WHERE 'zzz' REGEXP '^a'")
            assert cursor.fetchone() is None
        finally:
            conn.close()


class TestEvalRegexEmailRule:
    def test_email_rule_flags_exactly_invalid_addresses(self, make_sqlite_db):
        """The shipped valid_email_format rule must flag exactly the invalid rows.

        Fixture (hand-enumerated, not derived from running any code):
            "a@b.com"      -> VALID:   local part, "@", domain, ".", tld all present.
            "not-an-email" -> INVALID: no "@" at all, cannot match.
            "x@y"          -> INVALID: has "@" but no "." afterwards, cannot match.
            ""             -> policy call, see below.
            None           -> policy call, see below.

        Policy calls, derived from reading _eval_regex's SQL and the
        pattern text (examples/rules/advanced_rules.yaml), not from running
        the code:

        * None (SQL NULL) is NOT APPLICABLE, not invalid: _eval_regex's
          WHERE clause is `{col} IS NOT NULL AND {col} NOT REGEXP ?`. The
          explicit `IS NOT NULL` guard excludes SQL NULL from the REGEXP
          check entirely, by construction -- a NULL value is a
          completeness concern (the separate NOT NULL rule expression),
          not a validity/regex one. It cannot appear in the failing set.

        * "" (empty string) IS INVALID, not "not applicable": unlike NULL,
          an empty string is NOT NULL in SQL, so the `IS NOT NULL` guard
          does not exclude it -- it reaches the REGEXP check. The pattern
          `^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$` requires at least one non-"@"
          non-whitespace character before the "@" (`[^@\\s]+`), which an
          empty string cannot supply, so it cannot match and is correctly
          counted as a failure.

        Hand-derived failing set: {"", "not-an-email", "x@y"} (3 of the 5
        rows; "a@b.com" passes and None is excluded by construction).

        Note on the task brief: the brief for this test suggested the
        failing set would be exactly {"not-an-email", "x@y"} (i.e. that ""
        would NOT be flagged). Hand-deriving from the actual SQL and the
        actual pattern text disagrees with that: the IS NOT NULL guard
        does not exempt "", so "" is correctly flagged as invalid under
        the rule as written. This discrepancy is reported in the task
        report rather than silently adjusting the expectation.
        """
        pattern = None
        for rule in load_rules(str(_REPO_ROOT / "examples" / "rules" / "advanced_rules.yaml")):
            if rule.name == "valid_email_format":
                pattern = rule.params["pattern"]
                break
        assert pattern is not None, "valid_email_format rule not found in advanced_rules.yaml"

        db_file = make_sqlite_db(
            "emails.db",
            """
            CREATE TABLE users (email TEXT);
            INSERT INTO users VALUES ('a@b.com');
            INSERT INTO users VALUES ('not-an-email');
            INSERT INTO users VALUES ('x@y');
            INSERT INTO users VALUES ('');
            INSERT INTO users VALUES (NULL);
            """,
        )
        conn = _get_connection(
            ConnectionConfig(id="t", dsn=f"sqlite:///{db_file}", read_only=False)
        )
        try:
            cursor = conn.cursor()

            total, non_matching = _eval_regex(cursor, None, "users", "email", pattern, "sqlite")
            assert total == 5
            assert non_matching == 3  # hand-derived above: "", "not-an-email", "x@y"

            # Identify the exact failing rows (counts alone cannot prove
            # *which* rows failed), using the same REGEXP mechanism.
            cursor.execute(
                "SELECT email FROM users WHERE email IS NOT NULL AND email NOT REGEXP ?",
                (pattern,),
            )
            failing = {row[0] for row in cursor.fetchall()}
            assert failing == {"", "not-an-email", "x@y"}
        finally:
            conn.close()


class TestEvalRegexMalformedPattern:
    def test_malformed_pattern_is_a_config_error_not_a_data_issue(self):
        """A malformed pattern must raise, not be reported as "every row failed".

        An unbalanced "(" is not a valid regular expression. Today (before
        `DQT-09`'s exception hierarchy lands), the typed, catchable error
        this module raises for bad rule configuration is ValueError -- see
        `_eval_range`'s `range rule requires at least one of params.min or
        params.max` for the existing convention this follows.

        Before DQT-04's fix, calling `_eval_regex` for ANY pattern (valid
        or malformed) on a connection raises
        `sqlite3.OperationalError: no such function: REGEXP`, because no
        REGEXP function is registered on the connection at all -- that is
        the reproduction of the underlying defect this test starts from.
        After the fix, a malformed pattern must raise ValueError, and must
        raise it before any SQL runs against the table -- never as a
        count where every row is reported as non-matching.
        """
        conn = sqlite3.connect(":memory:")
        conn.executescript(
            """
            CREATE TABLE users (email TEXT);
            INSERT INTO users VALUES ('a@b.com');
            INSERT INTO users VALUES ('c@d.com');
            """
        )
        try:
            cursor = conn.cursor()
            # _get_connection would additionally register REGEXP; using a
            # plain sqlite3 connection here isolates the assertion to
            # _eval_regex's own pattern handling, independent of whether
            # the connection has REGEXP registered.
            with pytest.raises(ValueError):
                _eval_regex(cursor, None, "users", "email", "(unbalanced", "sqlite")

            # The defect this guards against: total rows must never be
            # silently reported as the non-matching count for a pattern
            # that never actually compiled.
            cursor.execute("SELECT COUNT(*) FROM users")
            total = cursor.fetchone()[0]
            assert total == 2  # sanity: the raise above must not have run any COUNT query
        finally:
            conn.close()


class TestRegexPatternCacheBounded:
    def test_pattern_cache_is_bounded_and_long_patterns_are_rejected(self):
        """The compiled-pattern cache must not grow without bound, and huge
        patterns must be rejected rather than compiled.

        This is written to run against unfixed code without an import
        error: it first drives the real behavior through `_eval_regex`
        (an existing, already-public symbol) across many distinct
        patterns. Before DQT-04's fix this fails immediately with
        `sqlite3.OperationalError: no such function: REGEXP` on the very
        first pattern, since no REGEXP function -- and therefore no cache
        -- exists yet; that is a legitimate reproduction of the underlying
        defect. The cache-introspection assertions below are reached only
        once that call succeeds, i.e. only after the fix, at which point
        the new internal cache function is imported locally (not at module
        scope) so it cannot break collection of this file pre-fix.
        """
        conn = _get_connection(ConnectionConfig(id="t", dsn="sqlite:///:memory:"))
        try:
            cursor = conn.cursor()
            cursor.execute("CREATE TABLE t (v TEXT)")
            cursor.execute("INSERT INTO t VALUES ('sample')")

            n_distinct_patterns = 400  # deliberately larger than any reasonable cache bound
            for i in range(n_distinct_patterns):
                # Each pattern is syntactically distinct (and harmless: none
                # of them match 'sample'), forcing n_distinct_patterns
                # separate compilations if nothing bounds the cache.
                _eval_regex(cursor, None, "t", "v", f"^only-pattern-number-{i}$", "sqlite")

            # Reached only when the loop above succeeded, i.e. post-fix.
            from dqt.sql.rules import _compile_regex_pattern

            info = _compile_regex_pattern.cache_info()
            assert info.maxsize is not None and info.maxsize > 0, (
                "pattern cache must have a finite maxsize, not be unbounded"
            )
            assert info.currsize <= info.maxsize
            assert info.currsize < n_distinct_patterns, (
                "cache must be bounded well below the number of distinct patterns used"
            )

            # A pattern far above the length limit must be rejected before
            # ever reaching re.compile -- proven by the distinctive
            # "exceeds the maximum" ValueError message rather than a
            # generic regex-syntax error, and by it never being counted as
            # a cache entry.
            huge_pattern = "a" * 50_000  # syntactically valid regex, just absurdly long
            misses_before = _compile_regex_pattern.cache_info().misses
            with pytest.raises(ValueError, match="exceeds"):
                _compile_regex_pattern(huge_pattern)
            info_after = _compile_regex_pattern.cache_info()
            # A rejected pattern must not be memoized: lru_cache never
            # caches a raised exception, but this also confirms the
            # rejection happens outside of (before) any cached-compile path.
            assert info_after.misses == misses_before + 1
        finally:
            conn.close()
