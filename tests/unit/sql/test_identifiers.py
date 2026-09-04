"""Unit tests for the identifier-quoting entry point.

``dqt.sql._identifiers`` remains the single entry point every module calls to
quote an identifier; after `DQT-08` it resolves the *rules* for doing so from
the dialect rather than from a private quote-character table of its own. These
tests fix that behaviour at the entry point, including the one case where the
old shared implementation was wrong for a non-SQLite dialect.
"""

from __future__ import annotations

import pytest

from dqt.sql._identifiers import qualified_identifier, quote_identifier


class TestQuoteIdentifier:
    def test_default_dialect_is_sqlite(self):
        assert quote_identifier("orders") == '"orders"'

    def test_postgresql_uses_ansi_double_quotes(self):
        assert quote_identifier("orders", "postgresql") == '"orders"'

    def test_sqlserver_uses_brackets(self):
        assert quote_identifier("orders", "sqlserver") == "[orders]"

    def test_embedded_delimiter_is_escaped_per_dialect(self):
        assert quote_identifier('a"b', "sqlite") == '"a""b"'
        assert quote_identifier("a]b", "sqlserver") == "[a]]b]"

    def test_unsupported_dialect_is_rejected(self):
        with pytest.raises(ValueError, match="mysql"):
            quote_identifier("orders", "mysql")


class TestQualifiedIdentifier:
    def test_sqlite_suppresses_its_implicit_main_schema(self):
        assert qualified_identifier("main", "orders") == '"orders"'

    def test_sqlite_qualifies_an_attached_schema(self):
        assert qualified_identifier("aux", "orders") == '"aux"."orders"'

    def test_none_schema_is_unqualified_in_every_dialect(self):
        assert qualified_identifier(None, "orders", "sqlite") == '"orders"'
        assert qualified_identifier(None, "orders", "postgresql") == '"orders"'
        assert qualified_identifier(None, "orders", "sqlserver") == "[orders]"

    def test_postgresql_schema(self):
        assert qualified_identifier("public", "orders", "postgresql") == '"public"."orders"'

    def test_sqlserver_schema(self):
        assert qualified_identifier("dbo", "orders", "sqlserver") == "[dbo].[orders]"

    def test_main_is_only_implicit_for_sqlite(self):
        """A schema named ``main`` is real everywhere except SQLite.

        The pre-`DQT-08` implementation applied SQLite's rule to every
        dialect, so a PostgreSQL or SQL Server table in a schema named
        ``main`` was addressed unqualified and left to ``search_path`` (or the
        login's default schema) to resolve — a different table, silently.
        Ground truth is each database's own naming rules, not DQT's code.
        """
        assert qualified_identifier("main", "orders", "postgresql") == '"main"."orders"'
        assert qualified_identifier("main", "orders", "sqlserver") == "[main].[orders]"
