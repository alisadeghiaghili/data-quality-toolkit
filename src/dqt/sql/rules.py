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
|                  | Only supported on databases with a REGEXP operator or     |
|                  | equivalent (SQLite REGEXP requires a registered function).|
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
from dqt.sql.schema_discovery import DiscoveredTable


# ---------------------------------------------------------------------------
# Internal: DB connection helper
# ---------------------------------------------------------------------------

def _get_connection(config: ConnectionConfig) -> Any:
    """Return a DBAPI connection for *config*.

    Supports SQLite (``sqlite://...``) and PostgreSQL (``postgresql://...``).
    The connection is always opened in read-only mode where the driver supports
    it.

    Args:
        config: Validated connection configuration.

    Returns:
        An open DBAPI connection.

    Raises:
        ImportError: If the required driver (``psycopg2``) is not installed.
        ValueError: If the DSN scheme is not supported.

    Example::

        conn = _get_connection(ConnectionConfig(id="dev", dsn="sqlite:///dev.db"))
        conn.close()
    """
    dsn = config.dsn
    if dsn.startswith("sqlite://"):
        import sqlite3
        db_path = dsn[len("sqlite:///"):] if dsn.startswith("sqlite:///") else dsn[len("sqlite://"):]
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn
    if dsn.startswith("postgresql://") or dsn.startswith("postgres://"):
        try:
            import psycopg2  # type: ignore
        except ImportError as exc:
            raise ImportError(
                "psycopg2 is required for PostgreSQL connections. "
                "Install with: pip install psycopg2-binary"
            ) from exc
        return psycopg2.connect(dsn)
    raise ValueError(
        f"Unsupported DSN scheme in '{dsn}'. "
        "Supported: sqlite://, postgresql://, postgres://"
    )


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
    if column_name is not None and scope.column_pattern and not fnmatch.fnmatch(
        column_name.lower(), scope.column_pattern.lower()
    ):
        return False
    return True


# ---------------------------------------------------------------------------
# Internal: SQL evaluators
# ---------------------------------------------------------------------------

def _qualified_table(schema_name: str | None, table_name: str) -> str:
    """Return a schema-qualified table identifier.

    Args:
        schema_name: Schema name, or ``None`` for unqualified.
        table_name: Table name.

    Returns:
        ``schema.table`` or just ``table`` if schema is ``None``.

    Example::

        assert _qualified_table("public", "orders") == "public.orders"
        assert _qualified_table(None, "orders") == "orders"
    """
    if schema_name and schema_name != "main":  # SQLite uses 'main' internally
        return f"{schema_name}.{table_name}"
    return table_name


def _eval_not_null(
    cursor: Any,
    schema_name: str | None,
    table_name: str,
    column_name: str,
) -> tuple[int, int]:
    """Count total rows and NULL rows for a column.

    Args:
        cursor: Open DBAPI cursor.
        schema_name: Schema name (may be ``None``).
        table_name: Table name.
        column_name: Column name to check.

    Returns:
        Tuple of ``(total_rows, null_count)``.

    Example::

        total, nulls = _eval_not_null(cursor, "public", "orders", "customer_id")
    """
    tbl = _qualified_table(schema_name, table_name)
    cursor.execute(
        f'SELECT COUNT(*), COUNT(*) - COUNT("{column_name}") FROM {tbl}'
    )
    row = cursor.fetchone()
    return int(row[0]), int(row[1])


def _eval_unique(
    cursor: Any,
    schema_name: str | None,
    table_name: str,
    column_name: str,
) -> tuple[int, int]:
    """Count total non-null rows and duplicate rows for a column.

    Args:
        cursor: Open DBAPI cursor.
        schema_name: Schema name.
        table_name: Table name.
        column_name: Column name to check.

    Returns:
        Tuple of ``(total_rows, duplicate_count)`` where ``duplicate_count``
        is the number of rows that share a value with at least one other row.

    Example::

        total, dupes = _eval_unique(cursor, "public", "users", "email")
    """
    tbl = _qualified_table(schema_name, table_name)
    cursor.execute(f'SELECT COUNT("{column_name}") FROM {tbl}')
    total = int(cursor.fetchone()[0])
    cursor.execute(
        f"""
        SELECT COALESCE(SUM(cnt - 1), 0)
        FROM (
            SELECT COUNT("{column_name}") AS cnt
            FROM {tbl}
            WHERE "{column_name}" IS NOT NULL
            GROUP BY "{column_name}"
            HAVING COUNT("{column_name}") > 1
        ) AS dupes
        """
    )
    duplicate_extra = int(cursor.fetchone()[0])
    return total, duplicate_extra


def _eval_range(
    cursor: Any,
    schema_name: str | None,
    table_name: str,
    column_name: str,
    min_val: float | None,
    max_val: float | None,
) -> tuple[int, int]:
    """Count rows outside the specified [min, max] range.

    Args:
        cursor: Open DBAPI cursor.
        schema_name: Schema name.
        table_name: Table name.
        column_name: Column name.
        min_val: Minimum acceptable value (inclusive).  ``None`` = no lower bound.
        max_val: Maximum acceptable value (inclusive).  ``None`` = no upper bound.

    Returns:
        Tuple of ``(total_rows, out_of_range_count)``.

    Raises:
        ValueError: If both *min_val* and *max_val* are ``None``.

    Example::

        total, bad = _eval_range(cursor, None, "products", "price", 0.0, None)
    """
    if min_val is None and max_val is None:
        raise ValueError("range rule requires at least one of params.min or params.max.")
    tbl = _qualified_table(schema_name, table_name)
    cursor.execute(f'SELECT COUNT(*) FROM {tbl}')
    total = int(cursor.fetchone()[0])

    conditions: list[str] = [f'"{column_name}" IS NOT NULL']
    if min_val is not None:
        conditions.append(f'"{column_name}" < {min_val}')
    if max_val is not None:
        conditions.append(f'"{column_name}" > {max_val}')
    # Only first condition is always present; wrap min/max in OR if both given
    if min_val is not None and max_val is not None:
        where = f'"{column_name}" IS NOT NULL AND ("{column_name}" < {min_val} OR "{column_name}" > {max_val})'
    elif min_val is not None:
        where = f'"{column_name}" IS NOT NULL AND "{column_name}" < {min_val}'
    else:
        where = f'"{column_name}" IS NOT NULL AND "{column_name}" > {max_val}'

    cursor.execute(f'SELECT COUNT(*) FROM {tbl} WHERE {where}')
    out_of_range = int(cursor.fetchone()[0])
    return total, out_of_range


def _eval_regex(
    cursor: Any,
    schema_name: str | None,
    table_name: str,
    column_name: str,
    pattern: str,
    dialect: str,
) -> tuple[int, int]:
    """Count rows whose column value does not match *pattern*.

    SQLite support requires the REGEXP function to be registered on the
    connection.  PostgreSQL uses the native ``~`` operator.

    Args:
        cursor: Open DBAPI cursor.
        schema_name: Schema name.
        table_name: Table name.
        column_name: Column name.
        pattern: Regular expression pattern.
        dialect: ``"sqlite"`` or ``"postgresql"``.

    Returns:
        Tuple of ``(total_rows, non_matching_count)``.

    Raises:
        ValueError: If *dialect* is not supported.

    Example::

        total, bad = _eval_regex(cursor, None, "users", "email",
                                  r"^[^@]+@[^@]+$", "sqlite")
    """
    tbl = _qualified_table(schema_name, table_name)
    cursor.execute(f'SELECT COUNT(*) FROM {tbl}')
    total = int(cursor.fetchone()[0])

    if dialect == "sqlite":
        not_match_sql = (
            f'SELECT COUNT(*) FROM {tbl} '
            f'WHERE "{column_name}" IS NOT NULL '
            f'AND "{column_name}" NOT REGEXP ?'
        )
        cursor.execute(not_match_sql, (pattern,))
    elif dialect in ("postgresql", "postgres"):
        not_match_sql = (
            f'SELECT COUNT(*) FROM {tbl} '
            f'WHERE "{column_name}" IS NOT NULL '
            f'AND NOT ("{column_name}" ~ %s)'
        )
        cursor.execute(not_match_sql, (pattern,))
    else:
        raise ValueError(f"Unsupported dialect for regex evaluation: {dialect!r}")

    non_matching = int(cursor.fetchone()[0])
    return total, non_matching


# ---------------------------------------------------------------------------
# Internal: dialect detection
# ---------------------------------------------------------------------------

def _detect_dialect(dsn: str) -> str:
    """Derive a dialect string from a DSN.

    Args:
        dsn: Database DSN string.

    Returns:
        ``"sqlite"``, ``"postgresql"``, or raises ``ValueError``.

    Example::

        assert _detect_dialect("sqlite:///dev.db") == "sqlite"
        assert _detect_dialect("postgresql://u:p@host/db") == "postgresql"
    """
    if dsn.startswith("sqlite"):
        return "sqlite"
    if dsn.startswith("postgresql") or dsn.startswith("postgres"):
        return "postgresql"
    raise ValueError(f"Cannot detect dialect from DSN: {dsn!r}")


# ---------------------------------------------------------------------------
# Internal: single-rule evaluator
# ---------------------------------------------------------------------------

def _evaluate_rule(
    run_id: str,
    rule: RuleConfig,
    table: DiscoveredTable,
    column_name: str,
    cursor: Any,
    dialect: str,
) -> list[DQIssue]:
    """Evaluate one rule against one (table, column) and return any issues.

    Args:
        run_id: Pipeline run identifier.
        rule: The rule configuration to evaluate.
        table: The target table.
        column_name: The target column.
        cursor: Open DBAPI cursor.
        dialect: Database dialect (``"sqlite"`` or ``"postgresql"``)..

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
            total, null_count = _eval_not_null(cursor, schema, tname, column_name)
            if null_count > 0:
                issues.append(DQIssue(
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
                ))

        elif expr == "UNIQUE":
            total, duplicate_extra = _eval_unique(cursor, schema, tname, column_name)
            if duplicate_extra > 0:
                issues.append(DQIssue(
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
                ))

        elif expr == "RANGE":
            min_val = rule.params.get("min")
            max_val = rule.params.get("max")
            total, out_of_range = _eval_range(
                cursor, schema, tname, column_name, min_val, max_val
            )
            if out_of_range > 0:
                issues.append(DQIssue(
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
                ))

        elif expr == "REGEX":
            pattern = rule.params.get("pattern", "")
            if not pattern:
                raise ValueError(f"Rule '{rule.name}' uses 'regex' but params.pattern is missing.")
            total, non_matching = _eval_regex(
                cursor, schema, tname, column_name, pattern, dialect
            )
            if non_matching > 0:
                issues.append(DQIssue(
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
                ))

        else:
            # Unknown expression: produce an error-severity issue so the DBA
            # knows a rule was skipped, rather than silently passing.
            issues.append(DQIssue(
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
            ))
    except Exception as exc:  # noqa: BLE001
        issues.append(DQIssue(
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
        ))

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

    dialect = _detect_dialect(connection_config.dsn)
    all_issues: list[DQIssue] = []
    summaries: list[RuleRunResult] = []

    db_conn = _get_connection(connection_config)
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
                        error_issues = [i for i in col_issues if i.severity == "error" and "evaluation error" in i.message]
                        if error_issues:
                            targets_error += 1
                        else:
                            targets_failed += 1

            all_issues.extend(rule_issues)
            summaries.append(RuleRunResult(
                run_id=run_id,
                rule_name=rule.name,
                targets_checked=targets_checked,
                targets_failed=targets_failed,
                targets_error=targets_error,
            ))
    finally:
        db_conn.close()

    return all_issues, summaries
