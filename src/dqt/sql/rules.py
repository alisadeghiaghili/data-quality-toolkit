"""
dqt.sql.rules
=============

SQL-based rule evaluation engine for DQT.

This module evaluates declarative data-quality rules (loaded from YAML/JSON
via :mod:`dqt.common.config_loader`) against a live database using SQL queries.
All evaluation is read-only; no data is modified.

Supported expressions
---------------------

+------------------+-----------------------------------------------------------+
| Expression       | Checks                                                    |
+==================+===========================================================+
| ``NOT NULL``     | No NULL values in column (completeness / validity).       |
+------------------+-----------------------------------------------------------+
| ``UNIQUE``       | All values in column are distinct (uniqueness).           |
+------------------+-----------------------------------------------------------+
| ``range``        | Values fall within [min, max] (validity).                 |
|                  | Requires ``params.min`` and/or ``params.max``.            |
+------------------+-----------------------------------------------------------+
| ``regex``        | Values match a regular expression (validity).             |
|                  | Requires ``params.pattern``.                              |
|                  | Each dialect owns how it matches: SQLite registers a       |
|                  | Python ``re``-backed ``REGEXP`` function, PostgreSQL uses  |
|                  | its native ``~``, and SQL Server has no regex operator at  |
|                  | all and says so rather than reporting a false result.      |
+------------------+-----------------------------------------------------------+

Engine architecture
-------------------

:func:`apply_rules` is the single public entry point.  It:

1. Iterates over supplied :class:`~dqt.common.models.RuleConfig` objects.
2. Resolves which (schema, table, column) combinations match each rule's scope
   using glob pattern matching.
3. For each match, calls the appropriate SQL evaluator.
4. Converts failures into :class:`~dqt.common.models.DQIssue` objects and
   wraps per-rule summaries into :class:`~dqt.common.models.RuleRunResult`.

Example::

    from dqt.common.models import ConnectionConfig, DQPipelineConfig
    from dqt.common.config_loader import load_rules
    from dqt.sql.rules import apply_rules
    from dqt.sql.schema_discovery import discover_schema
    from dqt.sql.profiling import SqlProfiler

    conn_cfg = ConnectionConfig(id="dev", dsn="sqlite:///dev.db")
    rules = load_rules("examples/rules/base_rules.yaml")
    tables = discover_schema(conn_cfg)
    issues, summaries = apply_rules(
        run_id="run-001",
        connection_config=conn_cfg,
        rules=rules,
        discovered_tables=tables,
    )
"""

from __future__ import annotations

import fnmatch
import uuid
from typing import Any

from dqt.common.models import (
    ConnectionConfig,
    DQIssue,
    RuleConfig,
    RuleRunResult,
)
from dqt.sql._connect import get_connection, get_dialect_for
from dqt.sql.dialects.base import Dialect
from dqt.sql.schema_discovery import DiscoveredTable

# ---------------------------------------------------------------------------
# Internal: SQLite REGEXP support
# ---------------------------------------------------------------------------

# SQLite ships no REGEXP implementation of its own: the ``REGEXP`` operator
# is only usable if a two-argument function named ``REGEXP`` is registered
# on the connection (https://www.sqlite.org/lang_expr.html#the_like_glob_regexp_and_match_operators).
# Without this registration every ``regex`` rule fails with
# ``sqlite3.OperationalError: no such function: REGEXP`` on every column it
# targets, which is exactly the defect `DQT-04` fixes.

# Upper bound on pattern length accepted for compilation. This is not a
# performance-tuning knob so much as a config-sanity guard: a rule file is
# trusted input in this project (there is no raw-SQL rule type, and rule
# files are not accepted from untrusted users), but a many-kilobyte
# "pattern" is never an intentional regex and is far more likely to be a
# copy-paste accident (e.g. an entire file pasted into params.pattern) that
# is cheaper to reject up front than to hand to ``re.compile``.
_REGEX_PATTERN_MAX_LENGTH = 1000

# Bounds the compiled-pattern cache so a rule file with many distinct (or
# templated/generated) regex patterns cannot grow this process-lifetime
# cache without limit. 256 comfortably covers realistic rule files (DQT's
# own example rule files define a handful of regex rules total) while
# capping worst-case memory to a small, fixed number of compiled patterns.
_REGEX_CACHE_MAXSIZE = 256


# ---------------------------------------------------------------------------
# Internal: DB connection helper
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Internal: scope matching
# ---------------------------------------------------------------------------


def _matches_scope(
    table: DiscoveredTable,
    column_name: str | None,
    rule: RuleConfig,
) -> bool:
    """Return True if (table, column) falls within *rule*'s scope.

    Glob patterns are applied case-insensitively.  An absent (``None``) pattern
    means "match all".

    Args:
        table: Discovered table candidate.
        column_name: Column name candidate, or ``None`` for table-level rules.
        rule: The rule whose scope to check.

    Returns:
        ``True`` if the candidate matches the scope; ``False`` otherwise.

    Example::

        rule = RuleConfig(
            name="r", dimension="completeness", severity="error",
            scope=RuleScope(table_pattern="order*", column_pattern="id"),
            expression="NOT NULL",
        )
        assert _matches_scope(table, "id", rule) is True
    """
    scope = rule.scope
    if scope.schema_pattern and not fnmatch.fnmatch(
        (table.schema_name or "").lower(), scope.schema_pattern.lower()
    ):
        return False
    if scope.table_pattern and not fnmatch.fnmatch(
        table.table_name.lower(), scope.table_pattern.lower()
    ):
        return False
    return not (
        column_name is not None
        and scope.column_pattern
        and not fnmatch.fnmatch(column_name.lower(), scope.column_pattern.lower())
    )


# ---------------------------------------------------------------------------
# Internal: SQL evaluators
# ---------------------------------------------------------------------------


def _eval_not_null(
    cursor: Any,
    schema_name: str | None,
    table_name: str,
    column_name: str,
    dialect: Dialect,
) -> tuple[int, int]:
    """Count total rows and NULL rows for a column.

    Args:
        cursor: Open DBAPI cursor.
        schema_name: Schema name (may be ``None``).
        table_name: Table name.
        column_name: Column name to check.
        dialect: Target SQL dialect, used for identifier quoting.

    Returns:
        Tuple of ``(total_rows, null_count)``.

    Example::

        total, nulls = _eval_not_null(cursor, "public", "orders", "customer_id")
    """
    tbl = dialect.qualified_identifier(schema_name, table_name)
    col = dialect.quote_identifier(column_name)
    cursor.execute(f"SELECT COUNT(*), COUNT(*) - COUNT({col}) FROM {tbl}")
    row = cursor.fetchone()
    return int(row[0]), int(row[1])


def _eval_unique(
    cursor: Any,
    schema_name: str | None,
    table_name: str,
    column_name: str,
    dialect: Dialect,
) -> tuple[int, int]:
    """Count total non-null rows and duplicate rows for a column.

    Args:
        cursor: Open DBAPI cursor.
        schema_name: Schema name.
        table_name: Table name.
        column_name: Column name to check.
        dialect: Target SQL dialect, used for identifier quoting.

    Returns:
        Tuple of ``(total_rows, duplicate_count)`` where ``duplicate_count``
        is the number of rows that share a value with at least one other row.

    Example::

        total, dupes = _eval_unique(cursor, "public", "users", "email")
    """
    tbl = dialect.qualified_identifier(schema_name, table_name)
    col = dialect.quote_identifier(column_name)
    # COUNT(col) counts non-NULL values and COUNT(DISTINCT col) counts the
    # values that exist, so the difference is how many rows are duplicates of
    # some other row -- exactly what the old GROUP BY subquery summed, in one
    # pass instead of a grouped scan plus a separate count.
    #
    # COUNT(DISTINCT ...) is expensive at scale; an approximate-distinct path
    # is a separate scope item of this unit, and the dialect protocol already
    # carries approximate_distinct_expression() for it.
    statement = dialect.select_aggregates_sql(
        tbl, [f"COUNT({col})", f"COUNT({col}) - COUNT(DISTINCT {col})"]
    )
    cursor.execute(statement)
    row = cursor.fetchone()
    return int(row[0]), int(row[1] or 0)


def _eval_range(
    cursor: Any,
    schema_name: str | None,
    table_name: str,
    column_name: str,
    min_val: float | None,
    max_val: float | None,
    dialect: Dialect,
) -> tuple[int, int]:
    """Count rows outside the specified [min, max] range.

    *min_val* and *max_val* are always passed to the database as DBAPI bind
    parameters, never interpolated into the SQL text.

    Args:
        cursor: Open DBAPI cursor.
        schema_name: Schema name.
        table_name: Table name.
        column_name: Column name.
        min_val: Minimum acceptable value (inclusive).  ``None`` = no lower bound.
        max_val: Maximum acceptable value (inclusive).  ``None`` = no upper bound.
        dialect: Target SQL dialect, used for identifier quoting and the
            bind-parameter placeholder style.

    Returns:
        Tuple of ``(total_rows, out_of_range_count)``.

    Raises:
        ValueError: If both *min_val* and *max_val* are ``None``.

    Example::

        total, bad = _eval_range(cursor, None, "products", "price", 0.0, None)
    """
    if min_val is None and max_val is None:
        raise ValueError("range rule requires at least one of params.min or params.max.")
    tbl = dialect.qualified_identifier(schema_name, table_name)
    col = dialect.quote_identifier(column_name)
    ph = dialect.parameter_placeholder
    bind_params: list[float]
    if min_val is not None and max_val is not None:
        where = f"{col} IS NOT NULL AND ({col} < {ph} OR {col} > {ph})"
        bind_params = [min_val, max_val]
    elif min_val is not None:
        where = f"{col} IS NOT NULL AND {col} < {ph}"
        bind_params = [min_val]
    else:
        assert max_val is not None  # narrowed by the branch above
        where = f"{col} IS NOT NULL AND {col} > {ph}"
        bind_params = [max_val]

    # One scan for both numbers. The denominator and the violation count come
    # from the same rows, so asking separately reads the table twice to learn
    # one thing. SUM(CASE ...) is the portable form of a filtered count --
    # FILTER (WHERE ...) is standard but SQL Server does not have it.
    statement = dialect.select_aggregates_sql(
        tbl, ["COUNT(*)", f"SUM(CASE WHEN {where} THEN 1 ELSE 0 END)"]
    )
    cursor.execute(statement, bind_params)
    row = cursor.fetchone()
    # SUM over no rows is NULL, not 0.
    return int(row[0]), int(row[1] or 0)


def _eval_regex(
    cursor: Any,
    schema_name: str | None,
    table_name: str,
    column_name: str,
    pattern: str,
    dialect: Dialect,
) -> tuple[int, int]:
    """Count rows whose column value does not match *pattern*.

    How the match is expressed is the dialect's business, not this
    function's: it asks
    :meth:`~dqt.sql.dialects.base.Dialect.regex_not_matching_predicate` for a
    predicate and binds *pattern* as a parameter. SQLite answers with its
    registered ``REGEXP`` function (`DQT-04`), PostgreSQL with the native
    ``~`` operator, and SQL Server refuses outright because it has no regex
    operator to answer with.

    *cursor* must come from a connection opened by
    :func:`~dqt.sql._connect.get_connection`, which is what installs SQLite's
    ``REGEXP`` function; a connection opened any other way raises
    ``sqlite3.OperationalError: no such function: REGEXP``.

    The dialect validates *pattern* up front, before any query runs. This is
    deliberate: without it, a malformed pattern would only be discovered
    when SQLite invokes the registered function mid-query, which surfaces
    as ``sqlite3.OperationalError: user-defined function raised
    exception`` rather than the ``ValueError`` this module otherwise uses
    for bad rule configuration (see :func:`_eval_range`) — and, more
    importantly, callers must never receive a row count computed against a
    pattern that failed to compile, which is why validation happens before
    the counting query rather than being left for the per-row callback to
    discover.

    Args:
        cursor: Open DBAPI cursor.
        schema_name: Schema name.
        table_name: Table name.
        column_name: Column name.
        pattern: Regular expression pattern.
        dialect: Resolved :class:`~dqt.sql.dialects.base.Dialect`. It owns
            the identifier quoting and the bind placeholder used below.

    Returns:
        Tuple of ``(total_rows, non_matching_count)``.

    Raises:
        ValueError: If the dialect cannot evaluate a regular expression at
            all, or if *pattern* is not a valid, length-bounded regular
            expression. Which of the two applies is the dialect's decision;
            see
            :meth:`~dqt.sql.dialects.base.Dialect.regex_not_matching_predicate`.

    Example::

        total, bad = _eval_regex(cursor, None, "users", "email",
                                  r"^[^@]+@[^@]+$", "sqlite")
    """
    tbl = dialect.qualified_identifier(schema_name, table_name)
    col = dialect.quote_identifier(column_name)
    cursor.execute(f"SELECT COUNT(*) FROM {tbl}")
    total = int(cursor.fetchone()[0])

    predicate = dialect.regex_not_matching_predicate(col, pattern)
    # The predicate carries its own IS NOT NULL guard: whether a NULL can
    # even reach the match operator is the dialect's business, so adding a
    # second guard here would duplicate it and invite the two to drift.
    cursor.execute(f"SELECT COUNT(*) FROM {tbl} WHERE {predicate}", (pattern,))

    non_matching = int(cursor.fetchone()[0])
    return total, non_matching


# ---------------------------------------------------------------------------
# Internal: dialect detection
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Internal: single-rule evaluator
# ---------------------------------------------------------------------------


def _evaluate_rule(
    run_id: str,
    rule: RuleConfig,
    table: DiscoveredTable,
    column_name: str,
    cursor: Any,
    dialect: Dialect,
) -> list[DQIssue]:
    """Evaluate one rule against one (table, column) and return any issues.

    Args:
        run_id: Pipeline run identifier.
        rule: The rule configuration to evaluate.
        table: The target table.
        column_name: The target column.
        cursor: Open DBAPI cursor.
        dialect: Resolved :class:`~dqt.sql.dialects.base.Dialect`.

    Returns:
        List of :class:`~dqt.common.models.DQIssue` (empty if rule passes).

    Example::

        issues = _evaluate_rule("run-001", rule, table, "email", cursor, "sqlite")
    """
    schema = table.schema_name
    tname = table.table_name
    expr = rule.expression.strip().upper()
    issues: list[DQIssue] = []

    try:
        if expr == "NOT NULL":
            total, null_count = _eval_not_null(cursor, schema, tname, column_name, dialect)
            if null_count > 0:
                issues.append(
                    DQIssue(
                        issue_id=str(uuid.uuid4()),
                        run_id=run_id,
                        dimension=rule.dimension,
                        severity=rule.severity,
                        message=(
                            f"Column '{column_name}' in '{tname}' has {null_count} "
                            f"NULL value(s) out of {total} total rows."
                        ),
                        evidence={"null_count": null_count, "total_rows": total},
                        schema_name=schema,
                        table_name=tname,
                        column_name=column_name,
                        rule_name=rule.name,
                    )
                )

        elif expr == "UNIQUE":
            total, duplicate_extra = _eval_unique(cursor, schema, tname, column_name, dialect)
            if duplicate_extra > 0:
                issues.append(
                    DQIssue(
                        issue_id=str(uuid.uuid4()),
                        run_id=run_id,
                        dimension=rule.dimension,
                        severity=rule.severity,
                        message=(
                            f"Column '{column_name}' in '{tname}' has {duplicate_extra} "
                            f"extra duplicate value(s) (violates uniqueness)."
                        ),
                        evidence={"duplicate_extra_rows": duplicate_extra, "total_rows": total},
                        schema_name=schema,
                        table_name=tname,
                        column_name=column_name,
                        rule_name=rule.name,
                    )
                )

        elif expr == "RANGE":
            min_val = rule.params.get("min")
            max_val = rule.params.get("max")
            total, out_of_range = _eval_range(
                cursor, schema, tname, column_name, min_val, max_val, dialect
            )
            if out_of_range > 0:
                issues.append(
                    DQIssue(
                        issue_id=str(uuid.uuid4()),
                        run_id=run_id,
                        dimension=rule.dimension,
                        severity=rule.severity,
                        message=(
                            f"Column '{column_name}' in '{tname}' has {out_of_range} "
                            f"value(s) outside the range "
                            f"[{min_val if min_val is not None else '-inf'}, "
                            f"{max_val if max_val is not None else '+inf'}]."
                        ),
                        evidence={
                            "out_of_range_count": out_of_range,
                            "total_rows": total,
                            "min": min_val,
                            "max": max_val,
                        },
                        schema_name=schema,
                        table_name=tname,
                        column_name=column_name,
                        rule_name=rule.name,
                    )
                )

        elif expr == "REGEX":
            pattern = rule.params.get("pattern", "")
            if not pattern:
                raise ValueError(f"Rule '{rule.name}' uses 'regex' but params.pattern is missing.")
            total, non_matching = _eval_regex(cursor, schema, tname, column_name, pattern, dialect)
            if non_matching > 0:
                issues.append(
                    DQIssue(
                        issue_id=str(uuid.uuid4()),
                        run_id=run_id,
                        dimension=rule.dimension,
                        severity=rule.severity,
                        message=(
                            f"Column '{column_name}' in '{tname}' has {non_matching} "
                            f"value(s) not matching pattern '{pattern}'."
                        ),
                        evidence={
                            "non_matching_count": non_matching,
                            "total_rows": total,
                            "pattern": pattern,
                        },
                        schema_name=schema,
                        table_name=tname,
                        column_name=column_name,
                        rule_name=rule.name,
                    )
                )

        else:
            # Unknown expression: produce an error-severity issue so the DBA
            # knows a rule was skipped, rather than silently passing.
            issues.append(
                DQIssue(
                    issue_id=str(uuid.uuid4()),
                    run_id=run_id,
                    dimension=rule.dimension,
                    severity="error",
                    message=(
                        f"Rule '{rule.name}' uses unknown expression '{rule.expression}'. "
                        "No evaluation was performed."
                    ),
                    evidence={"expression": rule.expression},
                    schema_name=schema,
                    table_name=tname,
                    column_name=column_name,
                    rule_name=rule.name,
                )
            )
    except Exception as exc:  # noqa: BLE001
        issues.append(
            DQIssue(
                issue_id=str(uuid.uuid4()),
                run_id=run_id,
                dimension=rule.dimension,
                severity="error",
                message=f"Rule '{rule.name}' evaluation error on '{tname}.{column_name}': {exc}",
                evidence={"error": str(exc)},
                schema_name=schema,
                table_name=tname,
                column_name=column_name,
                rule_name=rule.name,
            )
        )

    return issues


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def apply_rules(
    run_id: str,
    connection_config: ConnectionConfig | None = None,
    rules: list[RuleConfig] | None = None,
    discovered_tables: list[DiscoveredTable] | None = None,
) -> tuple[list[DQIssue], list[RuleRunResult]]:
    """Evaluate all rules against the discovered tables and return issues and summaries.

    Iterates over *rules*, resolves matching (table, column) combinations via
    scope glob patterns, evaluates each combination with the appropriate SQL
    query, and returns all :class:`~dqt.common.models.DQIssue` objects plus
    a :class:`~dqt.common.models.RuleRunResult` summary per rule.

    When called with no rules or no tables (e.g. from the legacy stub call
    site ``apply_rules(run_id)``), the function returns empty lists
    immediately.

    Args:
        run_id: Unique identifier for the current pipeline run.
        connection_config: Database connection configuration.  Required unless
            *rules* or *discovered_tables* is empty.
        rules: List of validated :class:`~dqt.common.models.RuleConfig`
            objects.  If ``None`` or empty, returns ``([], [])``.
        discovered_tables: Tables returned by
            :func:`~dqt.sql.schema_discovery.discover_schema`.  If ``None``
            or empty, returns ``([], [])``.

    Returns:
        A ``(issues, summaries)`` tuple where:

        * *issues* is a flat list of all :class:`~dqt.common.models.DQIssue`
          objects produced by failing rules.
        * *summaries* is one :class:`~dqt.common.models.RuleRunResult` per
          rule, even if the rule produced no failures.

    Example::

        issues, summaries = apply_rules(
            run_id="run-001",
            connection_config=conn_cfg,
            rules=rules,
            discovered_tables=tables,
        )
        print(f"{len(issues)} issue(s) from {len(summaries)} rule(s)")
    """
    if not rules or not discovered_tables or connection_config is None:
        return [], []

    dialect = get_dialect_for(connection_config)
    all_issues: list[DQIssue] = []
    summaries: list[RuleRunResult] = []

    db_conn = get_connection(connection_config)
    try:
        cursor = db_conn.cursor()
        for rule in rules:
            rule_issues: list[DQIssue] = []
            targets_checked = 0
            targets_failed = 0
            targets_error = 0

            for table in discovered_tables:
                for col in table.columns:
                    if not _matches_scope(table, col.column_name, rule):
                        continue
                    targets_checked += 1
                    col_issues = _evaluate_rule(
                        run_id=run_id,
                        rule=rule,
                        table=table,
                        column_name=col.column_name,
                        cursor=cursor,
                        dialect=dialect,
                    )
                    rule_issues.extend(col_issues)
                    if col_issues:
                        error_issues = [
                            i
                            for i in col_issues
                            if i.severity == "error" and "evaluation error" in i.message
                        ]
                        if error_issues:
                            targets_error += 1
                        else:
                            targets_failed += 1

            all_issues.extend(rule_issues)
            summaries.append(
                RuleRunResult(
                    run_id=run_id,
                    rule_name=rule.name,
                    targets_checked=targets_checked,
                    targets_failed=targets_failed,
                    targets_error=targets_error,
                )
            )
    finally:
        db_conn.close()

    return all_issues, summaries
