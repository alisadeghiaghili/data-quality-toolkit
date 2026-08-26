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
|                  | SQLite has no native REGEXP; this module registers a      |
|                  | Python ``re``-backed implementation on every connection    |
|                  | it opens (see :func:`_get_connection`). PostgreSQL uses    |
|                  | its native ``~`` operator.                                 |
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
import functools
import re
import uuid
from typing import Any

from dqt.common.models import (
    ConnectionConfig,
    DQIssue,
    RuleConfig,
    RuleRunResult,
)
from dqt.sql._identifiers import qualified_identifier, quote_identifier
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


@functools.lru_cache(maxsize=_REGEX_CACHE_MAXSIZE)
def _compile_regex_pattern(pattern: str) -> re.Pattern[str]:
    """Compile *pattern* into a :class:`re.Pattern`, cached and length-bounded.

    This is the single place a ``regex`` rule's pattern is turned into a
    compiled expression, for two reasons: it lets the SQLite ``REGEXP``
    callback (:func:`_sqlite_regexp`) and :func:`_eval_regex`'s own
    up-front validation share one cache, and it means the length guard and
    the "invalid pattern" error message only need to be written once.

    Args:
        pattern: Regular expression source, as written in ``params.pattern``
            of a rule file.

    Returns:
        The compiled pattern, memoized by :func:`functools.lru_cache` (see
        module-level ``_REGEX_CACHE_MAXSIZE`` for the bound).

    Raises:
        ValueError: If *pattern* is longer than ``_REGEX_PATTERN_MAX_LENGTH``,
            or is not a syntactically valid Python regular expression. This
            is deliberately :class:`ValueError`, matching the convention
            already used by :func:`_eval_range` for bad rule parameters —
            a malformed pattern is a rule-configuration error, not a data
            issue, and must not be reported as if every row failed the
            check. (Once `DQT-09` lands a shared exception hierarchy, this
            should become that hierarchy's ``RuleEvaluationError`` instead;
            tracked there, not here.)

    Example::

        compiled = _compile_regex_pattern(r"^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$")
        assert compiled.search("a@b.com") is not None
    """
    if len(pattern) > _REGEX_PATTERN_MAX_LENGTH:
        raise ValueError(
            f"regex rule pattern is {len(pattern)} characters, which exceeds the "
            f"maximum of {_REGEX_PATTERN_MAX_LENGTH}. Refusing to compile it."
        )
    try:
        return re.compile(pattern)
    except re.error as exc:
        raise ValueError(f"Invalid regex pattern {pattern!r}: {exc}") from exc


def _sqlite_regexp(pattern: str, value: object) -> bool | None:
    """Implement SQLite's ``REGEXP`` operator via Python's :mod:`re`.

    Registered as the connection-wide ``REGEXP(X, Y)`` function by
    :func:`_get_connection`. SQLite rewrites the infix expression
    ``value REGEXP pattern`` into the function call ``REGEXP(pattern,
    value)`` — the pattern comes first, the value second — so this
    function's parameter order mirrors that call exactly. Getting this
    backwards would not raise; it would silently invert every match
    (verified empirically in
    ``tests/unit/sql/test_rules.py::test_regexp_function_registered_on_sqlite_connection``).

    Args:
        pattern: The regex pattern (SQLite's first argument, ``X`` in
            ``REGEXP(X, Y)``).
        value: The column value being tested (SQLite's second argument).
            May be any SQLite-native Python type, or ``None``.

    Returns:
        ``True`` if *value* (coerced to ``str``) matches *pattern* anywhere
        (via :func:`re.search`); ``False`` if it does not; ``None`` if
        *value* is SQL ``NULL`` (SQLite treats a ``NULL`` function result as
        ``NULL``, which is falsy in a ``WHERE`` clause — callers in this
        module additionally guard with an explicit ``IS NOT NULL``, so this
        is defense in depth rather than the only NULL handling).

    Raises:
        ValueError: If *pattern* is invalid or too long — see
            :func:`_compile_regex_pattern`. SQLite reports this to the
            caller as ``sqlite3.OperationalError: user-defined function
            raised exception``; :func:`_eval_regex` avoids that by
            validating the pattern itself before ever issuing the query.

    Example::

        assert _sqlite_regexp("^a", "abc") is True
        assert _sqlite_regexp("^a", "zzz") is False
        assert _sqlite_regexp("^a", None) is None
    """
    if value is None:
        return None
    compiled = _compile_regex_pattern(pattern)
    return compiled.search(str(value)) is not None


# ---------------------------------------------------------------------------
# Internal: DB connection helper
# ---------------------------------------------------------------------------


def _get_connection(config: ConnectionConfig) -> Any:
    """Return a DBAPI connection for *config*.

    Supports SQLite (``sqlite://...``) and PostgreSQL (``postgresql://...``).

    When ``config.read_only`` is ``True`` (the default — see
    :class:`~dqt.common.models.ConnectionConfig`), the returned connection
    cannot write, enforced by the driver/database itself rather than by
    caller discipline:

    * **SQLite** — opened via the ``file:<path>?mode=ro`` URI form, so any
      ``INSERT``/``UPDATE``/``DELETE`` raises ``sqlite3.OperationalError:
      attempt to write a readonly database``. A path of ``":memory:"`` is a
      documented exception: a fresh in-memory database created by this call
      is never a persistent asset, so ``mode=ro`` would only make it
      permanently empty and unusable. It is opened normally in that case.
      A consequence of the URI form: unlike a plain
      ``sqlite3.connect(path)``, this does **not** create the database file
      if it does not already exist — it raises ``sqlite3.OperationalError``
      instead. That is a deliberate behavior change from the pre-`DQT-03`
      code (which always auto-created the file); it is treated here as
      correct, since silently creating a database file you were told to
      treat as read-only is itself a surprise.
    * **PostgreSQL** — the session is set to
      ``SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY`` immediately
      after connecting, so every subsequent transaction on this connection
      is read-only at the server, not just by convention. (Untested in this
      repository: there is no PostgreSQL driver or server available in CI —
      see the task report's ``UNTESTED CODE PATHS``.)

    This is one of two independent enforcement layers for `DQT-03`; the
    second is :class:`~dqt.exceptions.ReadOnlyViolationError`, raised by
    :func:`dqt.sql.cleansing.apply_cleansing` before this function is even
    called.

    Every SQLite connection returned here (regardless of *config.read_only*)
    also has :func:`_sqlite_regexp` registered as the ``REGEXP`` function
    (`DQT-04`), since SQLite dispatches its ``REGEXP`` operator to a
    user-defined function rather than implementing one itself. This is the
    single place that registration happens; nothing in this module opens a
    second, non-conforming SQLite connection. (Note:
    :func:`dqt.sql.schema_discovery.connect_sql` is a separate,
    non-conforming connection-opening path elsewhere in this package — out
    of scope for `DQT-04`, but its ``regex`` rules would not get REGEXP
    support from this change.)

    Args:
        config: Validated connection configuration.

    Returns:
        An open DBAPI connection.

    Raises:
        ImportError: If the required driver (``psycopg2``) is not installed.
        ValueError: If the DSN scheme is not supported.

    Example::

        # read_only=False because the example path need not already exist;
        # the default (read_only=True) requires the file to exist first.
        conn = _get_connection(
            ConnectionConfig(id="dev", dsn="sqlite:///dev.db", read_only=False)
        )
        conn.close()
    """
    dsn = config.dsn
    if dsn.startswith("sqlite://"):
        import sqlite3

        db_path = (
            dsn[len("sqlite:///") :] if dsn.startswith("sqlite:///") else dsn[len("sqlite://") :]
        )
        if config.read_only and db_path != ":memory:":
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        else:
            conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        # See _sqlite_regexp: SQLite has no built-in REGEXP, only the
        # ability to dispatch it to a registered function. Registering it
        # here, on every connection this function returns (read-only or
        # not, file-backed or :memory:), is what makes the `regex` rule
        # expression actually work on SQLite (`DQT-04`). Registering a
        # function is not a write and is unaffected by mode=ro.
        conn.create_function("REGEXP", 2, _sqlite_regexp)
        return conn
    if dsn.startswith("postgresql://") or dsn.startswith("postgres://"):
        try:
            import psycopg2
        except ImportError as exc:
            raise ImportError(
                "psycopg2 is required for PostgreSQL connections. "
                "Install with: pip install psycopg2-binary"
            ) from exc
        pg_conn = psycopg2.connect(dsn)
        if config.read_only:
            pg_cursor = pg_conn.cursor()
            pg_cursor.execute("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY")
            pg_cursor.close()
            pg_conn.commit()
        return pg_conn
    raise ValueError(
        f"Unsupported DSN scheme in '{dsn}'. Supported: sqlite://, postgresql://, postgres://"
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
    return not (
        column_name is not None
        and scope.column_pattern
        and not fnmatch.fnmatch(column_name.lower(), scope.column_pattern.lower())
    )


# ---------------------------------------------------------------------------
# Internal: SQL evaluators
# ---------------------------------------------------------------------------


def _placeholder(dialect: str) -> str:
    """Return the DBAPI bind-parameter placeholder for *dialect*.

    Args:
        dialect: ``"sqlite"``, ``"postgresql"``, or ``"postgres"``.

    Returns:
        ``"?"`` for SQLite (paramstyle ``qmark``), ``"%s"`` for PostgreSQL
        (paramstyle ``pyformat``/``format``, as used by ``psycopg2``).

    Raises:
        ValueError: If *dialect* is not supported.

    Example::

        assert _placeholder("sqlite") == "?"
        assert _placeholder("postgresql") == "%s"
    """
    if dialect == "sqlite":
        return "?"
    if dialect in ("postgresql", "postgres"):
        return "%s"
    raise ValueError(f"Unsupported dialect for parameter placeholders: {dialect!r}")


def _eval_not_null(
    cursor: Any,
    schema_name: str | None,
    table_name: str,
    column_name: str,
    dialect: str = "sqlite",
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
    tbl = qualified_identifier(schema_name, table_name, dialect)
    col = quote_identifier(column_name, dialect)
    cursor.execute(f"SELECT COUNT(*), COUNT(*) - COUNT({col}) FROM {tbl}")
    row = cursor.fetchone()
    return int(row[0]), int(row[1])


def _eval_unique(
    cursor: Any,
    schema_name: str | None,
    table_name: str,
    column_name: str,
    dialect: str = "sqlite",
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
    tbl = qualified_identifier(schema_name, table_name, dialect)
    col = quote_identifier(column_name, dialect)
    cursor.execute(f"SELECT COUNT({col}) FROM {tbl}")
    total = int(cursor.fetchone()[0])
    cursor.execute(
        f"""
        SELECT COALESCE(SUM(cnt - 1), 0)
        FROM (
            SELECT COUNT({col}) AS cnt
            FROM {tbl}
            WHERE {col} IS NOT NULL
            GROUP BY {col}
            HAVING COUNT({col}) > 1
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
    dialect: str = "sqlite",
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
    tbl = qualified_identifier(schema_name, table_name, dialect)
    col = quote_identifier(column_name, dialect)
    cursor.execute(f"SELECT COUNT(*) FROM {tbl}")
    total = int(cursor.fetchone()[0])

    ph = _placeholder(dialect)
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

    cursor.execute(f"SELECT COUNT(*) FROM {tbl} WHERE {where}", bind_params)
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

    On SQLite this relies on the ``REGEXP`` function registered by
    :func:`_get_connection` (`DQT-04`); *cursor* must come from a
    connection opened through that function, or the query below raises
    ``sqlite3.OperationalError: no such function: REGEXP``. PostgreSQL uses
    the native ``~`` operator instead and needs no such registration.

    For SQLite, *pattern* is validated (compiled) up front via
    :func:`_compile_regex_pattern` before any query runs. This is
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
        dialect: ``"sqlite"`` or ``"postgresql"``.

    Returns:
        Tuple of ``(total_rows, non_matching_count)``.

    Raises:
        ValueError: If *dialect* is not supported, or (SQLite only) if
            *pattern* is not a valid, length-bounded regular expression —
            see :func:`_compile_regex_pattern`.

    Example::

        total, bad = _eval_regex(cursor, None, "users", "email",
                                  r"^[^@]+@[^@]+$", "sqlite")
    """
    tbl = qualified_identifier(schema_name, table_name, dialect)
    col = quote_identifier(column_name, dialect)
    cursor.execute(f"SELECT COUNT(*) FROM {tbl}")
    total = int(cursor.fetchone()[0])

    if dialect == "sqlite":
        _compile_regex_pattern(pattern)  # raise ValueError before querying, not during
        not_match_sql = f"SELECT COUNT(*) FROM {tbl} WHERE {col} IS NOT NULL AND {col} NOT REGEXP ?"
        cursor.execute(not_match_sql, (pattern,))
    elif dialect in ("postgresql", "postgres"):
        not_match_sql = f"SELECT COUNT(*) FROM {tbl} WHERE {col} IS NOT NULL AND NOT ({col} ~ %s)"
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
