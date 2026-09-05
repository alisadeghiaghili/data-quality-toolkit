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
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from dqt.common.models import (
    ConnectionConfig,
    DQIssue,
    IssueSeverity,
    RuleConfig,
    RuleRunResult,
)
from dqt.sql._connect import get_connection, get_dialect_for
from dqt.sql.dialects.base import Dialect
from dqt.sql.knowledge import reference_set_from_params, unmatched_count_fragment
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
# Internal: compiled checks
# ---------------------------------------------------------------------------
#
# A check compiles to aggregate *expressions* rather than to a statement, so
# that checks against the same table can be concatenated into one SELECT and
# read back from one row. `CLAUDE.md` section 3 asks for exactly that: a table
# is scanned once, not once per rule.
#
# The invariant that makes it safe: a fragment never carries a WHERE. A
# predicate belonging to one rule would silently filter the rows every other
# rule in the batch counted, so every per-rule condition lives inside a CASE.


#: Turns one check's slice of a result row into the issues it implies.
_Decoder = Callable[[Sequence[Any]], list[DQIssue]]


@dataclass(frozen=True, slots=True)
class _CompiledCheck:
    """One rule against one column, ready to be run with others.

    Attributes:
        rule_index: Position of the owning rule, so verdicts can be
            attributed back to it after the work is regrouped by table.
        table: The table the check reads, kept so a failed retry can name
            what it was checking.
        column_name: The column the check reads, kept for the same reason.
        from_clause: The already-quoted table reference this check reads,
            including any join it needs. Checks sharing a from_clause share
            a query.
        expressions: The aggregates this check contributes, in order.
        binds: Values for the placeholders in *expressions*.
        decode: Turns the values those expressions produced into issues.

    Example:
        check = _compile_check(run_id, rule, 0, table, "email", dialect)
    """

    rule_index: int
    table: DiscoveredTable
    column_name: str
    from_clause: str
    expressions: tuple[str, ...]
    binds: tuple[Any, ...]
    decode: _Decoder


def _fragment_not_null(quoted_column: str) -> tuple[tuple[str, ...], tuple[Any, ...]]:
    """Return the aggregates counting rows and NULLs for a column.

    Args:
        quoted_column: An already-quoted column reference.

    Returns:
        The expressions and their binds.

    Example:
        expressions, binds = _fragment_not_null('"email"')
    """
    return (("COUNT(*)", f"COUNT(*) - COUNT({quoted_column})"), ())


def _fragment_unique(
    quoted_column: str, dialect: Dialect, *, approximate: bool
) -> tuple[tuple[str, ...], tuple[Any, ...], bool]:
    """Return the aggregates counting non-NULL values and duplicates.

    ``COUNT(col)`` counts non-NULL values and ``COUNT(DISTINCT col)`` counts
    the values that exist, so the difference is how many rows duplicate some
    other row -- what the old ``GROUP BY`` subquery summed, in one pass.

    ``COUNT(DISTINCT ...)`` has to hold every distinct value it has seen, so
    on a high-cardinality column it is the one operation here that can cost
    real memory on the server. A caller may opt into an estimate per rule;
    whether that is acceptable is a property of the check, not of the run.

    Args:
        quoted_column: An already-quoted column reference.
        dialect: Dialect that may offer an estimating distinct count.
        approximate: Whether the rule asked for an estimate.

    Returns:
        The expressions, their binds, and whether an estimate was used --
        an estimate and an exact count are different claims, and a report
        must not render them alike.

    Example:
        expressions, binds, estimated = _fragment_unique(
            '"email"', dialect, approximate=False
        )
    """
    distinct_expression = None
    if approximate:
        distinct_expression = dialect.approximate_distinct_expression(quoted_column)
    used_approximation = distinct_expression is not None
    if distinct_expression is None:
        distinct_expression = f"COUNT(DISTINCT {quoted_column})"

    return (
        (f"COUNT({quoted_column})", f"COUNT({quoted_column}) - {distinct_expression}"),
        (),
        used_approximation,
    )


def _fragment_range(
    quoted_column: str,
    dialect: Dialect,
    min_val: float | None,
    max_val: float | None,
) -> tuple[tuple[str, ...], tuple[Any, ...]]:
    """Return the aggregates counting rows outside ``[min_val, max_val]``.

    The bounds are always bound as DBAPI parameters, never interpolated:
    ``DQT-02`` established that a rule literal comes from a file a person
    edits.

    Args:
        quoted_column: An already-quoted column reference.
        dialect: Dialect supplying the bind placeholder.
        min_val: Inclusive lower bound, or None.
        max_val: Inclusive upper bound, or None.

    Returns:
        The expressions and their binds.

    Raises:
        ValueError: If both bounds are None, which would describe no range
            at all.

    Example:
        expressions, binds = _fragment_range('"age"', dialect, 0, 120)
    """
    if min_val is None and max_val is None:
        raise ValueError("range rule requires at least one of params.min or params.max.")

    placeholder = dialect.parameter_placeholder
    bind_params: tuple[Any, ...]
    if min_val is not None and max_val is not None:
        condition = (
            f"{quoted_column} IS NOT NULL AND "
            f"({quoted_column} < {placeholder} OR {quoted_column} > {placeholder})"
        )
        bind_params = (min_val, max_val)
    elif min_val is not None:
        condition = f"{quoted_column} IS NOT NULL AND {quoted_column} < {placeholder}"
        bind_params = (min_val,)
    else:
        condition = f"{quoted_column} IS NOT NULL AND {quoted_column} > {placeholder}"
        bind_params = (max_val,)

    # SUM(CASE ...) is the portable filtered count: FILTER (WHERE ...) is
    # standard, and SQL Server does not have it.
    return (("COUNT(*)", f"SUM(CASE WHEN {condition} THEN 1 ELSE 0 END)"), bind_params)


def _fragment_regex(
    quoted_column: str, dialect: Dialect, pattern: str
) -> tuple[tuple[str, ...], tuple[Any, ...]]:
    """Return the aggregates counting values that fail *pattern*.

    The dialect validates *pattern* before any query is built. Without that,
    a malformed pattern would surface as a driver error mid-scan, and -- far
    worse -- a caller could receive a row count computed against a pattern
    that failed to compile.

    Args:
        quoted_column: An already-quoted column reference.
        dialect: Dialect owning the match predicate.
        pattern: Regular expression source, bound as a parameter.

    Returns:
        The expressions and their binds.

    Raises:
        ValueError: If the dialect cannot evaluate a regular expression at
            all, or if *pattern* is not a valid, length-bounded one.

    Example:
        expressions, binds = _fragment_regex('"email"', dialect, r"^[^@]+@")
    """
    # The predicate carries its own IS NOT NULL guard: whether a NULL can
    # reach the match operator is the dialect's business, and a second guard
    # here would duplicate it and invite the two to drift.
    predicate = dialect.regex_not_matching_predicate(quoted_column, pattern)
    return (("COUNT(*)", f"SUM(CASE WHEN {predicate} THEN 1 ELSE 0 END)"), (pattern,))


def _run_aggregate(
    cursor: Any,
    dialect: Dialect,
    from_clause: str,
    expressions: Sequence[str],
    binds: Sequence[Any],
) -> tuple[Any, ...]:
    """Run one aggregate query and return its single row.

    Args:
        cursor: Open DBAPI cursor.
        dialect: Dialect assembling the statement.
        from_clause: An already-quoted table reference, joins included.
        expressions: The aggregates to project. Must not be empty.
        binds: Values for the placeholders, in order.

    Returns:
        The row, one value per expression.

    Example:
        values = _run_aggregate(cursor, dialect, '"t"', ["COUNT(*)"], ())
    """
    cursor.execute(dialect.select_aggregates_sql(from_clause, list(expressions)), tuple(binds))
    row = cursor.fetchone()
    return tuple(row)


def _issue(
    run_id: str,
    rule: RuleConfig,
    table: DiscoveredTable,
    column_name: str,
    *,
    message: str,
    evidence: dict[str, Any],
    severity: IssueSeverity | None = None,
) -> DQIssue:
    """Build a DQIssue for *rule* against one column.

    Every issue this module raises names the same (run, rule, table, column),
    so assembling them in one place keeps that from drifting between the six
    call sites that used to repeat it.

    Args:
        run_id: Pipeline run identifier.
        rule: The rule that produced the finding.
        table: The table it ran against.
        column_name: The column it ran against.
        message: Human-readable finding.
        evidence: Counts backing the finding. Never the offending rows.
        severity: Overrides the rule's severity, for findings about the rule
            itself rather than about the data.

    Returns:
        The issue.

    Example:
        issue = _issue(run_id, rule, table, "email", message="...", evidence={})
    """
    return DQIssue(
        issue_id=str(uuid.uuid4()),
        run_id=run_id,
        dimension=rule.dimension,
        severity=severity or rule.severity,
        message=message,
        evidence=evidence,
        schema_name=table.schema_name,
        table_name=table.table_name,
        column_name=column_name,
        rule_name=rule.name,
    )


def _evaluation_error_issue(
    run_id: str,
    rule: RuleConfig,
    table: DiscoveredTable,
    column_name: str,
    error: Exception,
) -> DQIssue:
    """Report that a rule could not be evaluated.

    A rule DQT cannot run must say so rather than pass quietly: reporting a
    clean column that was never checked is a false clean bill of health.

    Args:
        run_id: Pipeline run identifier.
        rule: The rule that could not run.
        table: The table it targeted.
        column_name: The column it targeted.
        error: What went wrong.

    Returns:
        An error-severity issue naming the rule and the failure.

    Example:
        issue = _evaluation_error_issue(run_id, rule, table, "email", exc)
    """
    return _issue(
        run_id,
        rule,
        table,
        column_name,
        message=(
            f"Rule '{rule.name}' evaluation error on '{table.table_name}.{column_name}': {error}"
        ),
        evidence={"error": str(error)},
        severity="error",
    )


def _compile_check(
    run_id: str,
    rule: RuleConfig,
    rule_index: int,
    table: DiscoveredTable,
    column_name: str,
    dialect: Dialect,
) -> _CompiledCheck:
    """Compile one rule against one column into shareable aggregates.

    Args:
        run_id: Pipeline run identifier.
        rule: The rule to compile.
        rule_index: Position of *rule* in the run, kept so its verdicts can
            be attributed back after the work is regrouped by table.
        table: The target table.
        column_name: The target column.
        dialect: Resolved :class:`~dqt.sql.dialects.base.Dialect`.

    Returns:
        The compiled check.

    Raises:
        ValueError: If the rule's parameters do not describe a runnable
            check. Raised here, before any query, so a misconfigured rule is
            reported as itself rather than as a driver error.

    Example:
        check = _compile_check(run_id, rule, 0, table, "email", dialect)
    """
    qualified_table = dialect.qualified_identifier(table.schema_name, table.table_name)
    quoted_column = dialect.quote_identifier(column_name)
    expression = rule.expression.strip().upper()

    if expression == "NOT NULL":
        expressions, binds = _fragment_not_null(quoted_column)

        def decode_not_null(values: Sequence[Any]) -> list[DQIssue]:
            total, null_count = int(values[0]), int(values[1])
            if null_count == 0:
                return []
            return [
                _issue(
                    run_id,
                    rule,
                    table,
                    column_name,
                    message=(
                        f"Column '{column_name}' in '{table.table_name}' has "
                        f"{null_count} NULL value(s) out of {total} total rows."
                    ),
                    evidence={"null_count": null_count, "total_rows": total},
                )
            ]

        return _CompiledCheck(
            rule_index, table, column_name, qualified_table, expressions, binds, decode_not_null
        )

    if expression == "UNIQUE":
        expressions, binds, used_approximation = _fragment_unique(
            quoted_column,
            dialect,
            approximate=bool(rule.params.get("approximate", False)),
        )

        def decode_unique(values: Sequence[Any]) -> list[DQIssue]:
            total, duplicate_extra = int(values[0]), int(values[1] or 0)
            if duplicate_extra == 0:
                return []
            return [
                _issue(
                    run_id,
                    rule,
                    table,
                    column_name,
                    message=(
                        f"Column '{column_name}' in '{table.table_name}' has "
                        f"{duplicate_extra} extra duplicate value(s) "
                        "(violates uniqueness)."
                    ),
                    evidence={
                        "duplicate_extra_rows": duplicate_extra,
                        "total_rows": total,
                        # Present whether or not the caller asked, so a reader
                        # never has to guess which kind of number this is.
                        "approximate": used_approximation,
                    },
                )
            ]

        return _CompiledCheck(
            rule_index, table, column_name, qualified_table, expressions, binds, decode_unique
        )

    if expression == "RANGE":
        min_val = rule.params.get("min")
        max_val = rule.params.get("max")
        expressions, binds = _fragment_range(quoted_column, dialect, min_val, max_val)

        def decode_range(values: Sequence[Any]) -> list[DQIssue]:
            total, out_of_range = int(values[0]), int(values[1] or 0)
            if out_of_range == 0:
                return []
            return [
                _issue(
                    run_id,
                    rule,
                    table,
                    column_name,
                    message=(
                        f"Column '{column_name}' in '{table.table_name}' has "
                        f"{out_of_range} value(s) outside range "
                        f"[{min_val}, {max_val}] out of {total} total rows."
                    ),
                    evidence={
                        "out_of_range_count": out_of_range,
                        "total_rows": total,
                        "min": min_val,
                        "max": max_val,
                    },
                )
            ]

        return _CompiledCheck(
            rule_index, table, column_name, qualified_table, expressions, binds, decode_range
        )

    if expression == "REGEX":
        pattern = rule.params.get("pattern")
        if not pattern:
            raise ValueError("regex rule requires params.pattern.")
        expressions, binds = _fragment_regex(quoted_column, dialect, str(pattern))

        def decode_regex(values: Sequence[Any]) -> list[DQIssue]:
            total, non_matching = int(values[0]), int(values[1] or 0)
            if non_matching == 0:
                return []
            return [
                _issue(
                    run_id,
                    rule,
                    table,
                    column_name,
                    message=(
                        f"Column '{column_name}' in '{table.table_name}' has "
                        f"{non_matching} value(s) not matching pattern "
                        f"'{pattern}' out of {total} total rows."
                    ),
                    evidence={
                        "non_matching_count": non_matching,
                        "total_rows": total,
                        "pattern": pattern,
                    },
                )
            ]

        return _CompiledCheck(
            rule_index, table, column_name, qualified_table, expressions, binds, decode_regex
        )

    if expression == "REFERENCE":
        reference = reference_set_from_params(rule.params)
        normalized = bool(rule.params.get("normalize_persian", False))
        fragment = unmatched_count_fragment(
            dialect,
            table.schema_name,
            table.table_name,
            column_name,
            reference,
            normalize_persian=normalized,
        )

        def decode_reference(values: Sequence[Any]) -> list[DQIssue]:
            checked_rows, unmatched = int(values[0]), int(values[1] or 0)
            if unmatched == 0:
                return []
            return [
                _issue(
                    run_id,
                    rule,
                    table,
                    column_name,
                    message=(
                        f"Column '{column_name}' in '{table.table_name}' has "
                        f"{unmatched} value(s) absent from its reference set, "
                        f"out of {checked_rows} non-NULL value(s) checked."
                    ),
                    evidence={
                        "unmatched_count": unmatched,
                        "checked_rows": checked_rows,
                        # Present whether or not folding was asked for, so a
                        # reader never has to guess whether two spellings of
                        # one word were treated as one value.
                        "normalized": normalized,
                    },
                )
            ]

        # A joined check cannot share a query: the join changes which rows the
        # other aggregates would see. It pays its own scan, and says so.
        return _CompiledCheck(
            rule_index,
            table,
            column_name,
            f"{qualified_table}{fragment.join_clause or ''}",
            fragment.expressions,
            fragment.binds,
            decode_reference,
        )

    def decode_unknown(_: Sequence[Any]) -> list[DQIssue]:
        return [
            _issue(
                run_id,
                rule,
                table,
                column_name,
                message=(
                    f"Rule '{rule.name}' uses unknown expression "
                    f"'{rule.expression}'. No evaluation was performed."
                ),
                evidence={"expression": rule.expression},
                severity="error",
            )
        ]

    # No expressions, so an unknown rule costs nothing and still reports
    # itself. Passing quietly would be the one unacceptable outcome.
    return _CompiledCheck(rule_index, table, column_name, qualified_table, (), (), decode_unknown)


def _decode_group(
    cursor: Any,
    dialect: Dialect,
    from_clause: str,
    checks: Sequence[_CompiledCheck],
) -> list[list[DQIssue]]:
    """Run one batch of checks and hand each its own slice of the row.

    Args:
        cursor: Open DBAPI cursor.
        dialect: Dialect assembling the statement.
        from_clause: The table reference every check in *checks* reads.
        checks: Checks sharing that table reference.

    Returns:
        The issues each check produced, in the order the checks were given.

    Example:
        per_check = _decode_group(cursor, dialect, '"t"', checks)
    """
    expressions = [expression for check in checks for expression in check.expressions]
    binds = [bind for check in checks for bind in check.binds]

    values: tuple[Any, ...] = ()
    if expressions:
        values = _run_aggregate(cursor, dialect, from_clause, expressions, binds)

    produced: list[list[DQIssue]] = []
    offset = 0
    for check in checks:
        width = len(check.expressions)
        produced.append(check.decode(values[offset : offset + width]))
        offset += width
    return produced


def _run_group(
    run_id: str,
    rules: Sequence[RuleConfig],
    cursor: Any,
    dialect: Dialect,
    from_clause: str,
    checks: Sequence[_CompiledCheck],
) -> list[tuple[_CompiledCheck, list[DQIssue], bool]]:
    """Run a batch, falling back to one check at a time if it fails.

    Sharing a query is what makes a table cost one scan; it is also what
    makes a single unusable expression able to fail a statement several
    rules were relying on. When that happens each check is retried alone, so
    the DBA gets every verdict that was computable and an error naming only
    the rule that was not. Without the retry, one typo would blank a whole
    table's report -- a far worse regression than the scans it saved.

    Args:
        run_id: Pipeline run identifier.
        rules: Every rule in the run, indexed by ``rule_index``.
        cursor: Open DBAPI cursor.
        dialect: Dialect assembling the statements.
        from_clause: The table reference every check in *checks* reads.
        checks: Checks sharing that table reference.

    Returns:
        One ``(check, issues, errored)`` triple per check.

    Example:
        outcomes = _run_group(run_id, rules, cursor, dialect, '"t"', checks)
    """
    try:
        return [
            (check, produced, False)
            for check, produced in zip(
                checks, _decode_group(cursor, dialect, from_clause, checks), strict=True
            )
        ]
    except Exception:  # noqa: BLE001
        return [_run_alone(run_id, rules, cursor, dialect, from_clause, check) for check in checks]


def _run_alone(
    run_id: str,
    rules: Sequence[RuleConfig],
    cursor: Any,
    dialect: Dialect,
    from_clause: str,
    check: _CompiledCheck,
) -> tuple[_CompiledCheck, list[DQIssue], bool]:
    """Run one check by itself and report what it produced.

    Args:
        run_id: Pipeline run identifier.
        rules: Every rule in the run, indexed by ``rule_index``.
        cursor: Open DBAPI cursor.
        dialect: Dialect assembling the statement.
        from_clause: The table reference the check reads.
        check: The check to run.

    Returns:
        A ``(check, issues, errored)`` triple.

    Example:
        outcome = _run_alone(run_id, rules, cursor, dialect, '"t"', check)
    """
    try:
        return (check, _decode_group(cursor, dialect, from_clause, [check])[0], False)
    except Exception as error:  # noqa: BLE001
        rule = rules[check.rule_index]
        return (
            check,
            [_evaluation_error_issue(run_id, rule, check.table, check.column_name, error)],
            True,
        )


# ---------------------------------------------------------------------------
# Internal: dialect detection
# ---------------------------------------------------------------------------


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
    compiled: list[_CompiledCheck] = []
    issues_by_rule: dict[int, list[DQIssue]] = {index: [] for index in range(len(rules))}
    targets_checked = [0] * len(rules)
    targets_error = [0] * len(rules)

    # Compile first, connect second. A rule whose parameters cannot describe a
    # check is a configuration mistake, and finding it costs no database work.
    for rule_index, rule in enumerate(rules):
        for table in discovered_tables:
            for column in table.columns:
                if not _matches_scope(table, column.column_name, rule):
                    continue
                targets_checked[rule_index] += 1
                try:
                    compiled.append(
                        _compile_check(run_id, rule, rule_index, table, column.column_name, dialect)
                    )
                except Exception as error:  # noqa: BLE001
                    issues_by_rule[rule_index].append(
                        _evaluation_error_issue(run_id, rule, table, column.column_name, error)
                    )
                    targets_error[rule_index] += 1

    # Checks reading the same table reference share one scan. That is the
    # whole point: `CLAUDE.md` section 3 asks for a table to be read once, not
    # once per rule, and a DBA writes the most rules against the table they
    # care about most.
    groups: dict[str, list[_CompiledCheck]] = {}
    for check in compiled:
        groups.setdefault(check.from_clause, []).append(check)

    db_conn = get_connection(connection_config)
    try:
        cursor = db_conn.cursor()
        for from_clause, checks in groups.items():
            for check, produced, errored in _run_group(
                run_id, rules, cursor, dialect, from_clause, checks
            ):
                issues_by_rule[check.rule_index].extend(produced)
                targets_error[check.rule_index] += int(errored)
    finally:
        db_conn.close()

    all_issues: list[DQIssue] = []
    summaries: list[RuleRunResult] = []
    for rule_index, rule in enumerate(rules):
        rule_issues = issues_by_rule[rule_index]
        all_issues.extend(rule_issues)
        summaries.append(
            RuleRunResult(
                run_id=run_id,
                rule_name=rule.name,
                targets_checked=targets_checked[rule_index],
                targets_failed=len(rule_issues) - targets_error[rule_index],
                targets_error=targets_error[rule_index],
            )
        )

    return all_issues, summaries
