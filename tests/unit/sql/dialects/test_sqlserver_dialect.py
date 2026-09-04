"""Unit tests for the SQL Server dialect's pure SQL construction and decisions.

**No SQL Server instance and no ``pyodbc`` installation exist here.** Nothing
in this file opens a connection, and nothing in it should be read as evidence
that DQT works against a real SQL Server. What it does prove is that every
decision the dialect makes without a server — bracket quoting, ``TOP (n)``
placement, DSN translation, the read-only attribute set, the refusal to fake
regular expressions, and the introspection query text — is what it claims to
be.

Expected values are hand-derived from Microsoft's T-SQL and ODBC
documentation (bracket delimiters escape only ``]``; ``TOP`` precedes the
select list; ODBC connection strings are ``KEY=value`` pairs separated by
``;``; ``SQL_ATTR_ACCESS_MODE`` is 101 and ``SQL_MODE_READ_ONLY`` is 1), not
by running this code.
"""

from __future__ import annotations

import pytest

from dqt.sql.dialects.base import ReadOnlyEnforcement
from dqt.sql.dialects.sqlserver import (
    COLUMN_METADATA_SQL,
    DEFAULT_ODBC_DRIVER,
    ODBC_SQL_ATTR_ACCESS_MODE,
    ODBC_SQL_MODE_READ_ONLY,
    SQLSERVER,
    odbc_connection_string,
    read_only_connect_attributes,
)


class TestIdentifierQuoting:
    def test_plain_identifier_uses_brackets(self):
        # Brackets, not ANSI double quotes: a double-quoted identifier
        # becomes a string literal when QUOTED_IDENTIFIER is OFF.
        assert SQLSERVER.quote_identifier("orders") == "[orders]"

    def test_only_the_closing_bracket_is_doubled(self):
        # Asymmetric delimiters: only "]" can terminate the identifier.
        assert SQLSERVER.quote_identifier("a]b") == "[a]]b]"

    def test_opening_bracket_is_an_ordinary_character(self):
        assert SQLSERVER.quote_identifier("a[b") == "[a[b]"

    def test_double_quote_is_not_special(self):
        # The ANSI escaping rule the other two dialects use would double
        # this; SQL Server's bracket form must not.
        assert SQLSERVER.quote_identifier('a"b') == '[a"b]'

    def test_injection_payload_stays_inside_the_identifier(self):
        payload = "x]; DROP TABLE users; --"
        assert SQLSERVER.quote_identifier(payload) == "[x]]; DROP TABLE users; --]"


class TestQualifiedIdentifier:
    def test_schema_is_qualified(self):
        assert SQLSERVER.qualified_identifier("dbo", "orders") == "[dbo].[orders]"

    def test_none_schema_is_unqualified(self):
        assert SQLSERVER.qualified_identifier(None, "orders") == "[orders]"

    def test_a_schema_named_main_is_not_suppressed(self):
        # "main" is SQLite's implicit schema, not SQL Server's; SQL Server's
        # default is dbo, and a schema named main would be a real one.
        assert SQLSERVER.qualified_identifier("main", "orders") == "[main].[orders]"


class TestSelectAggregatesSql:
    def test_single_expression(self):
        assert SQLSERVER.select_aggregates_sql("[t]", ["COUNT(*)"]) == "SELECT COUNT(*) FROM [t]"

    def test_where_clause_is_appended(self):
        assert (
            SQLSERVER.select_aggregates_sql("[t]", ["COUNT(*)"], "[c] IS NULL")
            == "SELECT COUNT(*) FROM [t] WHERE [c] IS NULL"
        )

    def test_empty_expressions_is_a_programming_error(self):
        with pytest.raises(ValueError, match="at least one expression"):
            SQLSERVER.select_aggregates_sql("[t]", [])


class TestLimitedSelectSql:
    def test_limit_is_a_prefix_not_a_suffix(self):
        """TOP (n) goes before the select list — the structural difference.

        This is the assertion that justifies a dialect layer rather than a
        table of substituted strings: no amount of suffix substitution turns
        ``LIMIT 5`` into ``TOP (5)`` in the right position.
        """
        assert SQLSERVER.limited_select_sql("[t]", ["*"], limit=5) == "SELECT TOP (5) * FROM [t]"

    def test_limit_with_a_where_clause(self):
        assert (
            SQLSERVER.limited_select_sql("[t]", ["[a]", "[b]"], "[c] IS NULL", 3)
            == "SELECT TOP (3) [a], [b] FROM [t] WHERE [c] IS NULL"
        )

    def test_no_limit_emits_no_top(self):
        assert SQLSERVER.limited_select_sql("[t]", ["*"]) == "SELECT * FROM [t]"

    @pytest.mark.parametrize("bad_limit", [0, -1])
    def test_non_positive_limit_is_rejected(self, bad_limit):
        with pytest.raises(ValueError, match="positive"):
            SQLSERVER.limited_select_sql("[t]", ["*"], limit=bad_limit)


class TestRegexIsRefusedRatherThanFaked:
    def test_regex_predicate_raises(self):
        """SQL Server has no regex operator, and LIKE is not one.

        Mapping a regular expression onto ``LIKE`` would answer a different
        question while looking like it answered this one — the exact
        silent-wrong-answer failure mode DQT exists to avoid. The refusal is
        the specified behaviour, not a gap.
        """
        with pytest.raises(ValueError, match="no regular-expression"):
            SQLSERVER.regex_not_matching_predicate("[email]", "^a")

    def test_refusal_message_names_the_dialect(self):
        with pytest.raises(ValueError) as excinfo:
            SQLSERVER.regex_not_matching_predicate("[email]", "^a")
        assert "SQL Server" in str(excinfo.value)


class TestApproximateDistinct:
    def test_sql_server_offers_approx_count_distinct(self):
        # SQL Server 2019+ ships a HyperLogLog-backed APPROX_COUNT_DISTINCT.
        # This is the only dialect of the three that returns an expression,
        # which is why the protocol returns an optional.
        assert SQLSERVER.approximate_distinct_expression("[c]") == "APPROX_COUNT_DISTINCT([c])"


class TestOdbcConnectionString:
    def test_full_dsn_with_credentials_and_port(self):
        assert odbc_connection_string("mssql://sa:pw@localhost:1433/dqt") == (
            f"DRIVER={{{DEFAULT_ODBC_DRIVER}}};"
            "SERVER=localhost,1433;"
            "DATABASE=dqt;"
            "UID=sa;"
            "PWD=pw;"
            "Encrypt=yes;"
            "TrustServerCertificate=no"
        )

    def test_dsn_without_port_omits_the_comma_form(self):
        assert "SERVER=localhost;" in odbc_connection_string("mssql://sa:pw@localhost/dqt")

    def test_dsn_without_credentials_uses_integrated_authentication(self):
        connection_string = odbc_connection_string("mssql://localhost/dqt")
        assert "Trusted_Connection=yes" in connection_string
        assert "UID=" not in connection_string
        assert "PWD=" not in connection_string

    def test_sqlserver_scheme_alias_is_accepted(self):
        assert odbc_connection_string("sqlserver://localhost/dqt").startswith("DRIVER=")

    def test_driver_query_parameter_overrides_the_default(self):
        connection_string = odbc_connection_string(
            "mssql://localhost/dqt?driver=ODBC+Driver+17+for+SQL+Server"
        )
        assert connection_string.startswith("DRIVER={ODBC Driver 17 for SQL Server};")

    def test_encrypt_and_trust_parameters_are_forwarded(self):
        connection_string = odbc_connection_string(
            "mssql://localhost/dqt?encrypt=no&trust_server_certificate=yes"
        )
        assert "Encrypt=no" in connection_string
        assert "TrustServerCertificate=yes" in connection_string

    def test_password_containing_a_url_escape_is_decoded(self):
        # %40 is "@"; the URL parser must decode it rather than splitting on it.
        assert "PWD=p@ss" in odbc_connection_string("mssql://sa:p%40ss@localhost/dqt")

    def test_unknown_query_parameter_is_rejected(self):
        with pytest.raises(ValueError, match="application_intent"):
            odbc_connection_string("mssql://localhost/dqt?application_intent=ReadOnly")

    def test_semicolon_in_a_value_is_rejected(self):
        # A ";" would break out of its ODBC key/value pair.
        with pytest.raises(ValueError, match="must not contain"):
            odbc_connection_string("mssql://sa:a%3Bb@localhost/dqt")

    def test_brace_in_a_value_is_rejected(self):
        with pytest.raises(ValueError, match="must not contain"):
            odbc_connection_string("mssql://localhost/dqt?driver=a%7Bb")

    def test_wrong_scheme_is_rejected(self):
        with pytest.raises(ValueError, match="mssql"):
            odbc_connection_string("postgresql://localhost/dqt")

    def test_missing_database_is_rejected(self):
        with pytest.raises(ValueError, match="database"):
            odbc_connection_string("mssql://localhost")

    def test_missing_host_is_rejected(self):
        with pytest.raises(ValueError, match="host"):
            odbc_connection_string("mssql:///dqt")


class TestReadOnlyAttributes:
    def test_read_only_requests_the_odbc_access_mode_attribute(self):
        assert read_only_connect_attributes(True) == {
            ODBC_SQL_ATTR_ACCESS_MODE: ODBC_SQL_MODE_READ_ONLY
        }

    def test_odbc_constants_match_the_specification(self):
        # ODBC 3.x sqlext.h: SQL_ATTR_ACCESS_MODE = 101, SQL_MODE_READ_ONLY = 1.
        assert (ODBC_SQL_ATTR_ACCESS_MODE, ODBC_SQL_MODE_READ_ONLY) == (101, 1)

    def test_writable_connection_requests_nothing(self):
        assert read_only_connect_attributes(False) == {}

    def test_enforcement_is_advisory_not_driver_enforced(self):
        """SQL Server cannot hold a connection read-only, and DQT says so.

        The ODBC access-mode attribute is a hint the specification permits a
        driver to ignore, and ``ApplicationIntent=ReadOnly`` routes rather
        than forbids. Recording this as ADVISORY is what lets
        ``get_connection`` warn instead of silently implying a guarantee DQT
        does not have on this database.
        """
        assert SQLSERVER.read_only_enforcement is ReadOnlyEnforcement.ADVISORY


class TestIntrospectionSql:
    def test_column_metadata_sql_selects_base_tables_only(self):
        normalised = " ".join(COLUMN_METADATA_SQL.split())
        assert normalised == (
            "SELECT c.TABLE_SCHEMA, c.TABLE_NAME, c.COLUMN_NAME, c.DATA_TYPE, c.IS_NULLABLE "
            "FROM INFORMATION_SCHEMA.COLUMNS AS c "
            "JOIN INFORMATION_SCHEMA.TABLES AS t "
            "ON t.TABLE_CATALOG = c.TABLE_CATALOG "
            "AND t.TABLE_SCHEMA = c.TABLE_SCHEMA "
            "AND t.TABLE_NAME = c.TABLE_NAME "
            "WHERE t.TABLE_TYPE = 'BASE TABLE' "
            "AND c.TABLE_SCHEMA NOT IN ('sys', 'INFORMATION_SCHEMA') "
            "ORDER BY c.TABLE_SCHEMA, c.TABLE_NAME, c.ORDINAL_POSITION"
        )
