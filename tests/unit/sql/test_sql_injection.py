"""
Regression tests for the SQL injection defect fixed by DQT-02.

Before this fix, ``dqt.sql.rules._eval_range`` built its WHERE clause by
f-string-interpolating ``params.min`` / ``params.max`` directly into the SQL
text, and ``_qualified_table`` returned a completely unquoted identifier.
``DQT-critical-review.md`` Sec 1.3 demonstrated that a rule file could put an
arbitrary SQL expression in ``params.max`` and have it execute as part of the
range predicate.

This module reproduces the exact payload from that review and a malicious
table-name payload, and asserts both are neutralized by the fix:

* ``params.min`` / ``params.max`` are rejected as non-numeric at the model
  layer (``RuleConfig``) before a rule can ever reach the query builder.
* Even if a caller bypassed model validation and called the SQL-layer
  evaluator directly with a non-numeric bound, DBAPI parameter binding means
  the value is compared as a literal, not executed as SQL text.
* Table and column identifiers are quoted and escaped through
  ``dqt.sql._identifiers``, so an identifier containing a quote character and
  a trailing statement cannot break out of its quoting.
"""

from __future__ import annotations

import sqlite3

import pytest
from pydantic import ValidationError

from dqt.common.models import RuleConfig, RuleScope
from dqt.sql._identifiers import quote_identifier
from dqt.sql.dialects import get_dialect_by_name
from tests.eval_helpers import eval_not_null, eval_range

# The exact payload reproduced in DQT-critical-review.md Sec 1.3: a
# subquery over a `secret` table, arithmetic-adjusted to exercise the
# range predicate's comparison operator.
REVIEW_PAYLOAD = "(SELECT COUNT(*) FROM secret WHERE x LIKE 'sensitive%') - 1"

# A table name carrying an embedded quote and a trailing statement, meant to
# break out of naive `f'"{name}"'` interpolation.
MALICIOUS_TABLE_NAME = 'my table"; DROP TABLE t; --'


@pytest.fixture
def injection_db():
    """In-memory SQLite database with a `products` table and a `secret` table.

    Mirrors the fixture used to reproduce the original exploit: `secret`
    holds two rows matching 'sensitive%', so a successfully executed
    subquery payload would evaluate to `2 - 1 == 1`, making
    `"price" > 1` true for all three `products` rows (out_of_range == 3).
    """
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE products (id INTEGER, price REAL);
        INSERT INTO products VALUES (1, 10.0);
        INSERT INTO products VALUES (2, 20.0);
        INSERT INTO products VALUES (3, 30.0);

        CREATE TABLE secret (x TEXT);
        INSERT INTO secret VALUES ('sensitive-row-1');
        INSERT INTO secret VALUES ('sensitive-row-2');
        """
    )
    return conn


class TestModelLayerRejectsNonNumericBounds:
    """Defence layer 1: a malicious payload cannot even build a RuleConfig."""

    def _rule_kwargs(self, params: dict[str, object]) -> dict[str, object]:
        return {
            "name": "max_price",
            "dimension": "validity",
            "severity": "error",
            "scope": RuleScope(column_pattern="price"),
            "expression": "range",
            "params": params,
        }

    def test_rejects_review_payload_as_max(self):
        with pytest.raises(ValidationError, match="must be an int or float"):
            RuleConfig(**self._rule_kwargs({"max": REVIEW_PAYLOAD}))

    def test_rejects_review_payload_as_min(self):
        with pytest.raises(ValidationError, match="must be an int or float"):
            RuleConfig(**self._rule_kwargs({"min": REVIEW_PAYLOAD}))

    def test_accepts_numeric_bounds(self):
        # Numeric bounds are unaffected by the new validator.
        rule = RuleConfig(**self._rule_kwargs({"min": 0, "max": 100.5}))
        assert rule.params == {"min": 0, "max": 100.5}

    def test_rejects_bool_bound(self):
        # bool is a subclass of int in Python; explicitly excluded so a
        # stray `true`/`false` in a YAML rule file cannot silently become
        # a range bound of 1 or 0.
        with pytest.raises(ValidationError, match="must be an int or float"):
            RuleConfig(**self._rule_kwargs({"max": True}))


class TestParameterizationPreventsExecution:
    """Defence layer 2: even a raw string reaching the evaluator cannot run."""

    def test_review_payload_does_not_execute_as_max(self, injection_db):
        cursor = injection_db.cursor()
        total, out_of_range = eval_range(
            cursor,
            None,
            "products",
            "price",
            None,
            REVIEW_PAYLOAD,
            dialect=get_dialect_by_name("sqlite"),
        )
        assert total == 3
        # Pre-fix, the interpolated payload evaluated to `2 - 1 == 1`,
        # so `"price" > 1` matched all three rows (out_of_range == 3).
        # Bound as a DBAPI parameter, the payload is compared as a literal
        # string value against a REAL column and matches nothing.
        assert out_of_range != 3
        assert out_of_range == 0
        # The attacker's subquery, if it had executed, would not itself
        # mutate `secret` -- but confirm the table is untouched and still
        # readable, i.e. no side channel occurred during evaluation.
        secret_count = cursor.execute("SELECT COUNT(*) FROM secret").fetchone()[0]
        assert secret_count == 2

    def test_review_payload_does_not_execute_as_min(self, injection_db):
        cursor = injection_db.cursor()
        total, out_of_range = eval_range(
            cursor,
            None,
            "products",
            "price",
            REVIEW_PAYLOAD,
            None,
            dialect=get_dialect_by_name("sqlite"),
        )
        assert total == 3
        # If the payload had executed as SQL text, "price" < 1 would match
        # zero rows (all prices are >= 10). SQLite instead compares the
        # bound TEXT literal against the REAL column using its storage-class
        # ordering rules (numeric sorts before text), which is unrelated to
        # -- and does not require -- ever parsing the payload as SQL.
        assert out_of_range != 0
        # No data was read out of `secret` as a side effect of evaluation.
        secret_count = cursor.execute("SELECT COUNT(*) FROM secret").fetchone()[0]
        assert secret_count == 2


class TestMaliciousTableIdentifierIsSafelyQuoted:
    """A table name carrying a quote and a trailing statement is inert."""

    def test_quote_identifier_escapes_embedded_quotes(self):
        quoted = quote_identifier(MALICIOUS_TABLE_NAME)
        # The identifier is wrapped in doubled-quote-escaped double quotes;
        # it must not contain an unescaped closing quote followed by
        # attacker SQL that a naive f-string would have let through.
        assert quoted.startswith('"')
        assert quoted.endswith('"')
        assert '""' in quoted  # the embedded `"` was doubled, not left bare

    def test_malicious_table_name_does_not_drop_other_table(self):
        """A table name carrying a quote and statement terminator stays inert.

        What this proves: routing the identifier through
        :func:`quote_identifier` keeps the generated query well-formed and
        returning correct counts. Against the unquoted pre-fix code the same
        call raised ``sqlite3.OperationalError: near "table": syntax error``.

        What it does not prove: that quoting is what stopped a second
        statement from running. Python's :mod:`sqlite3` permits only one
        statement per ``execute()`` regardless of quoting, so the embedded
        ``DROP TABLE`` could not have executed through this path either way.
        The multi-statement vector is real on the ``psycopg2`` path, which
        this test does not exercise.
        """
        conn = sqlite3.connect(":memory:")
        quoted = quote_identifier(MALICIOUS_TABLE_NAME)
        conn.execute(f"CREATE TABLE {quoted} (id INTEGER)")
        conn.execute("CREATE TABLE t (id INTEGER)")
        conn.execute(f"INSERT INTO {quoted} VALUES (1), (NULL)")
        conn.commit()

        cursor = conn.cursor()
        total, null_count = eval_not_null(
            cursor, None, MALICIOUS_TABLE_NAME, "id", dialect=get_dialect_by_name("sqlite")
        )
        assert total == 2
        assert null_count == 1

        remaining_tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        # Both tables survive. See this test's docstring for why that is
        # weaker evidence than it looks on SQLite.
        assert "t" in remaining_tables
        assert MALICIOUS_TABLE_NAME in remaining_tables
