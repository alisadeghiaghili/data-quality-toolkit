"""Rendered profiler SQL, per production dialect, with no live database (`NEW-AF`).

`SqlProfiler._plan_column` is the one place per-column profiling SQL is
assembled, and it is a pure function of a discovered column plus the
dialect it was built with -- it never opens a connection itself. That is
what makes it possible to check exactly what SQL DQT would send to a real
PostgreSQL or SQL Server server without either one installed: build a
:class:`~dqt.sql.profiling.SqlProfiler` whose dialect resolves from a
``postgresql://`` or ``mssql://`` DSN (dialect resolution is a pure string
match -- see ``dqt.sql.dialects.get_dialect`` -- so this never attempts a
connection), and inspect the expression list it appends to.

Before `NEW-AF` this could not have been asserted at all: the profiler
asked ``SqlProfiler._is_text_like`` (orderable-but-not-numeric) rather than
the dialect what counted as text, so PostgreSQL's ``date``, ``timestamp``,
``boolean`` and ``uuid`` were folded with ``LOWER(TRIM(...))`` -- a query
that fails outright on a real server, because PostgreSQL has no implicit
cast from any of them to ``text``. These tests pin the fixed SQL text by
hand, against the PostgreSQL and SQL Server documentation and the live
SQL Server 2022 verification recorded in ``sqlserver.py``.
"""

from __future__ import annotations

from dqt.common.models import ConnectionConfig
from dqt.sql.profiling import SqlProfiler
from dqt.sql.schema_discovery import DiscoveredColumn

POSTGRES_CONFIG = ConnectionConfig(id="pg", dsn="postgresql://user:pw@host/db")
SQLSERVER_CONFIG = ConnectionConfig(id="mssql", dsn="mssql://user:pw@host/db")


def _column(data_type: str, column_name: str = "c") -> DiscoveredColumn:
    """Build a single discovered column with the rest of the fields inert.

    Args:
        data_type: The declared type to plan for.
        column_name: The column's name, quoted verbatim by the dialect.

    Returns:
        A DiscoveredColumn usable with ``SqlProfiler._plan_column``.

    Example:
        column = _column("boolean")
    """
    return DiscoveredColumn(
        schema_name="public",
        table_name="t",
        column_name=column_name,
        data_type=data_type,
        nullable=True,
    )


def _expressions_for(connection_config: ConnectionConfig, data_type: str) -> list[str]:
    """Plan one column and return the aggregate expressions built for it.

    Args:
        connection_config: Names the dialect to plan with, never connected to.
        data_type: The column's declared type.

    Returns:
        The expression list ``_plan_column`` appended to, in order. Index 0
        is always ``COUNT(col)``; anything after it is conditional on the
        type.

    Example:
        expressions = _expressions_for(POSTGRES_CONFIG, "boolean")
    """
    profiler = SqlProfiler(connection_config)
    expressions: list[str] = []
    profiler._plan_column(_column(data_type), expressions)
    return expressions


class TestPostgresqlOrderableNonNumericTypesGetNoTextFolding:
    """The exact defect `NEW-AF` fixes: PostgreSQL has no implicit cast to text."""

    def test_timestamp_gets_no_lower_or_trim(self):
        expressions = " ".join(_expressions_for(POSTGRES_CONFIG, "timestamp")).upper()
        assert "LOWER" not in expressions
        assert "TRIM" not in expressions

    def test_date_gets_no_lower_or_trim(self):
        expressions = " ".join(_expressions_for(POSTGRES_CONFIG, "date")).upper()
        assert "LOWER" not in expressions
        assert "TRIM" not in expressions

    def test_boolean_gets_no_lower_or_trim(self):
        expressions = " ".join(_expressions_for(POSTGRES_CONFIG, "boolean")).upper()
        assert "LOWER" not in expressions
        assert "TRIM" not in expressions

    def test_uuid_gets_no_lower_or_trim(self):
        expressions = " ".join(_expressions_for(POSTGRES_CONFIG, "uuid")).upper()
        assert "LOWER" not in expressions
        assert "TRIM" not in expressions


class TestPostgresqlBooleanAndUuidGetNoBounds:
    """PostgreSQL has no ``min``/``max`` for either.

    ``ERROR: function min(boolean) does not exist``.
    """

    def test_boolean_gets_no_min_or_max(self):
        expressions = " ".join(_expressions_for(POSTGRES_CONFIG, "boolean")).upper()
        assert "MIN(" not in expressions
        assert "MAX(" not in expressions

    def test_uuid_gets_no_min_or_max(self):
        expressions = " ".join(_expressions_for(POSTGRES_CONFIG, "uuid")).upper()
        assert "MIN(" not in expressions
        assert "MAX(" not in expressions


class TestPostgresqlIncomparableTypesGetNoDistinctCount:
    """``json`` and the geometric types have no equality operator at all."""

    def test_json_gets_no_count_distinct(self):
        expressions = " ".join(_expressions_for(POSTGRES_CONFIG, "json")).upper()
        assert "COUNT(DISTINCT" not in expressions

    def test_xml_gets_no_count_distinct(self):
        expressions = " ".join(_expressions_for(POSTGRES_CONFIG, "xml")).upper()
        assert "COUNT(DISTINCT" not in expressions

    def test_point_gets_no_count_distinct(self):
        expressions = " ".join(_expressions_for(POSTGRES_CONFIG, "point")).upper()
        assert "COUNT(DISTINCT" not in expressions

    def test_jsonb_still_gets_a_distinct_count(self):
        # The deliberately different case: jsonb IS comparable.
        expressions = " ".join(_expressions_for(POSTGRES_CONFIG, "jsonb")).upper()
        assert "COUNT(DISTINCT" in expressions


class TestPostgresqlMoneyMean:
    def test_money_mean_casts_through_numeric(self):
        expressions = _expressions_for(POSTGRES_CONFIG, "money")
        assert 'AVG(CAST("c" AS NUMERIC))' in expressions

    def test_plain_numeric_mean_is_uncast(self):
        expressions = _expressions_for(POSTGRES_CONFIG, "integer")
        assert 'AVG("c")' in expressions


class TestPostgresqlTextDistinctIsByteExact:
    def test_text_distinct_uses_cast_and_c_collation(self):
        expressions = _expressions_for(POSTGRES_CONFIG, "text")
        joined = " ".join(expressions)
        assert 'CAST("c" AS TEXT) COLLATE "C"' in joined

    def test_text_still_gets_a_folded_distinct_count_too(self):
        expressions = _expressions_for(POSTGRES_CONFIG, "text")
        joined = " ".join(expressions).upper()
        assert "LOWER(TRIM(" in joined


class TestSqlServerBitGetsNoBounds:
    def test_bit_gets_no_min_or_max(self):
        expressions = " ".join(_expressions_for(SQLSERVER_CONFIG, "bit")).upper()
        assert "MIN(" not in expressions
        assert "MAX(" not in expressions


class TestSqlServerIntegerMeanAvoidsTruncationAndOverflow:
    def test_int_mean_casts_through_float(self):
        expressions = _expressions_for(SQLSERVER_CONFIG, "int")
        assert "AVG(CAST([c] AS FLOAT))" in expressions


class TestSqlServerIncomparableTypesGetNoDistinctCount:
    """The deprecated LOB types and the spatial types raise ``Msg 8117`` there."""

    def test_text_gets_no_count_distinct(self):
        expressions = " ".join(_expressions_for(SQLSERVER_CONFIG, "text")).upper()
        assert "COUNT(DISTINCT" not in expressions

    def test_ntext_gets_no_count_distinct(self):
        expressions = " ".join(_expressions_for(SQLSERVER_CONFIG, "ntext")).upper()
        assert "COUNT(DISTINCT" not in expressions

    def test_image_gets_no_count_distinct(self):
        expressions = " ".join(_expressions_for(SQLSERVER_CONFIG, "image")).upper()
        assert "COUNT(DISTINCT" not in expressions

    def test_xml_gets_no_count_distinct(self):
        expressions = " ".join(_expressions_for(SQLSERVER_CONFIG, "xml")).upper()
        assert "COUNT(DISTINCT" not in expressions

    def test_geography_gets_no_count_distinct(self):
        expressions = " ".join(_expressions_for(SQLSERVER_CONFIG, "geography")).upper()
        assert "COUNT(DISTINCT" not in expressions


class TestSqlServerNvarcharDistinctIsByteExact:
    def test_nvarchar_distinct_uses_the_varbinary_cast(self):
        expressions = _expressions_for(SQLSERVER_CONFIG, "nvarchar")
        joined = " ".join(expressions)
        assert "CAST([c] AS VARBINARY(MAX))" in joined

    def test_nvarchar_still_gets_a_folded_distinct_count_too(self):
        expressions = _expressions_for(SQLSERVER_CONFIG, "nvarchar")
        joined = " ".join(expressions).upper()
        assert "LOWER(TRIM(" in joined
