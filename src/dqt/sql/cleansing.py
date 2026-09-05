"""
dqt.sql.cleansing
=================

Reversible, auditable SQL cleansing for DQT.

Reversibility is a property of the ``cleanse_plan`` / ``cleanse_apply`` /
``revert`` triple, not of every function here. ``apply_cleansing`` is the
legacy one-shot path: it writes a log to memory and returns it, so a caller
who drops the return value has lost the before-values permanently. Prefer the
triple. ``CONVENTIONS-DQT.md`` section 1 S4 draws exactly this line -- a log a
human could replay by hand is an audit trail; automated undo is
reversibility -- and this module used to claim the second while providing
only the first.

All operations in this module are **data-quality cleansing only**:

* **Standardization** — trim whitespace, normalize internal spaces,
  apply case transformations (upper / lower / title).
* **Deduplication** — remove duplicate rows by key columns, retaining
  the first or last occurrence.
* **Lookup-based correction** — replace column values using a mapping
  stored in a domain / knowledge table.

Design invariants
-----------------

1. Every change is recorded in a :class:`CleansingLog` entry
   (before value, after value, row identifier, column, operation).
2. A plan applied through :func:`cleanse_apply` is **automatically
   reversible**: its log is persisted against the ``plan_id`` and
   :func:`revert` replays it backwards. Changes made through the legacy
   :func:`apply_cleansing` are reversible only by hand, and only while the
   caller still holds the returned log.
3. No schema changes, no DDL, no masking, no compliance features.
4. All SQL is executed through DBAPI2 connections obtained from
   :func:`~dqt.sql._connect.get_connection`, the single connection
   authority (`DQT-08`). Cleansing no longer reaches into the rules
   engine for it: both call the same module, so the read-only guard
   cannot be enforced on one path and skipped on the other.
5. :func:`apply_cleansing` never writes by accident: it raises
   :class:`~dqt.exceptions.ReadOnlyViolationError` if the connection is
   ``read_only`` (the default), and separately defaults to ``dry_run=True``
   so a caller must opt into both a writable connection and an explicit
   commit before any row changes.

Public API
----------

* :class:`CleansingConfig` — declarative config for one cleansing rule.
* :class:`CleansingLog` — single audit entry.
* :class:`CleansingResult` — summary of a full cleansing run.
* :func:`apply_cleansing` — execute a list of configs against a live DB.
* :func:`cleanse` — pipeline adapter called by :class:`~dqt.sql.pipeline.DQTPipeline`.

Example::

    from dqt.common.models import ConnectionConfig
    from dqt.sql.cleansing import CleansingConfig, apply_cleansing

    # read_only=False: this connection is being deliberately opted into writes.
    conn_cfg = ConnectionConfig(id="dev", dsn="sqlite:///dev.db", read_only=False)
    configs = [
        CleansingConfig(
            table_name="customers",
            column_name="email",
            operation="standardize",
            params={"case": "lower", "trim": True},
        ),
        CleansingConfig(
            table_name="customers",
            column_name=None,
            operation="deduplicate",
            params={"key_columns": ["email"], "keep": "first"},
        ),
    ]
    # dry_run=False: without it, this call only previews the change and
    # commits nothing.
    result = apply_cleansing(
        run_id="run-001", connection_config=conn_cfg, configs=configs, dry_run=False
    )
    print(f"{result.total_changes} change(s) across {result.tables_affected} table(s)")
"""

from __future__ import annotations

import hashlib
import re
import uuid
import warnings
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from dqt.common.models import ConnectionConfig
from dqt.exceptions import ReadOnlyViolationError
from dqt.sql._connect import get_connection, get_dialect_for
from dqt.sql._identifiers import qualified_identifier, quote_identifier
from dqt.sql.dialects.base import Dialect
from dqt.sql.row_identity import RowIdentity, resolve_row_identity
from dqt.sql.schema_discovery import discover_schema

# ---------------------------------------------------------------------------
# Public data classes
# ---------------------------------------------------------------------------


@dataclass
class CleansingConfig:
    """Declarative configuration for one cleansing operation.

    A :class:`CleansingConfig` describes a single cleansing step to apply to
    a specific table (and optionally column).  Multiple configs are combined
    into a list and passed to :func:`apply_cleansing`.

    Attributes:
        table_name: Target table name.
        column_name: Target column name, or ``None`` for table-level operations
            (e.g. deduplication).
        operation: One of ``"standardize"``, ``"deduplicate"``,
            ``"lookup_correct"``.
        params: Operation-specific parameters (see each operation's docstring).
        schema_name: Optional schema qualifier.  Defaults to ``None``.
        enabled: Set to ``False`` to skip this config without removing it.

    Example::

        cfg = CleansingConfig(
            table_name="users",
            column_name="email",
            operation="standardize",
            params={"case": "lower", "trim": True},
        )
    """

    table_name: str
    column_name: str | None
    operation: Literal["standardize", "deduplicate", "lookup_correct"]
    params: dict[str, Any] = field(default_factory=dict)
    schema_name: str | None = None
    enabled: bool = True


@dataclass
class CleansingLog:
    """Audit record for a single value change produced by a cleansing operation.

    A :class:`CleansingLog` entry is created for every row affected by a
    cleansing step.  The log contains enough information to reproduce or undo
    the change manually.

    Attributes:
        run_id: Pipeline run identifier.
        operation: Cleansing operation that produced this entry.
        schema_name: Schema of the affected table (may be ``None``).
        table_name: Table where the change occurred.
        column_name: Column where the change occurred (``None`` for
            row-level operations such as deduplication).
        row_key: Dict representing the identifying column(s) and their values
            for the affected row (e.g. ``{"id": 42}``).
        before_value: Value before the change (``None`` for deleted rows).
        after_value: Value after the change (``None`` for deleted rows).

    Example::

        entry = CleansingLog(
            run_id="run-001",
            operation="standardize",
            table_name="users",
            column_name="email",
            row_key={"id": 7},
            before_value="  Alice@Example.COM  ",
            after_value="alice@example.com",
        )
    """

    run_id: str
    operation: str
    table_name: str
    schema_name: str | None = None
    column_name: str | None = None
    row_key: dict[str, Any] = field(default_factory=dict)
    before_value: Any = None
    after_value: Any = None


@dataclass
class CleansingResult:
    """Summary of all changes applied during one cleansing run.

    Attributes:
        run_id: Pipeline run identifier.
        log: Ordered list of all :class:`CleansingLog` entries produced
            during this run. When ``dry_run`` is ``True``, these entries
            describe changes that *would* be made — the database was not
            touched.
        total_changes: Total number of value-level changes (UPDATE + DELETE).
            When ``dry_run`` is ``True``, this counts planned changes, not
            changes actually applied.
        tables_affected: Number of distinct tables that were modified (or,
            in dry-run mode, that would have been modified).
        errors: List of error messages for operations that could not be
            applied (non-fatal; the run continues).
        dry_run: ``True`` if this result came from a preview run that
            executed no mutating SQL and committed nothing (the default for
            :func:`apply_cleansing`); ``False`` if the changes described by
            ``log`` were actually written and committed.

    Example::

        result = apply_cleansing(run_id="run-001", ..., dry_run=False)
        print(result.total_changes, result.tables_affected)
    """

    run_id: str
    log: list[CleansingLog] = field(default_factory=list)
    total_changes: int = 0
    tables_affected: int = 0
    errors: list[str] = field(default_factory=list)
    dry_run: bool = True


#: How many rows a cleansing read pulls back at a time.
#:
#: Cleansing is the one facet that genuinely reads rows, because it records a
#: before-value for every change so ``revert()`` can put it back. Reading them
#: all at once puts the planner's memory at the mercy of the table's size, so
#: reads are paged by the row identity instead.
#:
#: Internal and unstable: it is a tuning knob, not part of the promise in
#: ``docs/API-STABILITY.md``.
_READ_PAGE_SIZE = 1000


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _fetch_all_dicts(cursor: Any, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    """Execute *sql* and return all rows as plain dicts.

    Args:
        cursor: Open DBAPI cursor.
        sql: SQL query string.
        params: Positional parameters for the query.

    Returns:
        List of row dicts (column name → value).

    Example::

        rows = _fetch_all_dicts(cursor, "SELECT id, email FROM users")
    """
    cursor.execute(sql, params)
    cols = [d[0] for d in cursor.description]
    return [dict(zip(cols, row, strict=True)) for row in cursor.fetchall()]


# ---------------------------------------------------------------------------
# Cleansing operations
# ---------------------------------------------------------------------------


def _identity_from_row_key(row_key: dict[str, Any], dialect: Dialect) -> RowIdentity:
    """Reconstruct how a logged row was addressed, from the log entry itself.

    Storing the identity on every log row would repeat it thousands of times
    for one plan; the key names already carry it.

    Args:
        row_key: The identity recorded when the change was planned.
        dialect: Dialect whose locator name to recognise.

    Returns:
        The :class:`~dqt.sql.row_identity.RowIdentity` that produced *row_key*.

    Raises:
        ValueError: If *row_key* is empty, which would address every row.

    Example:
        identity = _identity_from_row_key({"id": 42}, dialect)
    """
    names = tuple(row_key)
    if not names:
        raise ValueError(
            "A cleansing log entry has no row key. Replaying it would match "
            "every row in the table rather than the one that changed."
        )
    if len(names) == 1 and names[0] == dialect.physical_row_locator:
        return RowIdentity(columns=(), locator=names[0])
    return RowIdentity(columns=names, locator=None)


def _identity_projection(identity: RowIdentity, dialect: Dialect) -> str:
    """Return the SELECT list that reads a row's identity.

    Args:
        identity: How rows of this table are addressed.
        dialect: Dialect used for quoting.

    Returns:
        A comma-separated projection, aliased so the values can be read back
        by name whatever the dialect called them.

    Example:
        projection = _identity_projection(identity, dialect)
    """
    return ", ".join(_identity_projection_list(identity, dialect))


def _identity_projection_list(identity: RowIdentity, dialect: Dialect) -> list[str]:
    """Return the identity projection as separate expressions.

    ``limited_select_sql`` takes a sequence rather than a joined string, so
    the paged reader needs the parts. Joining them is
    :func:`_identity_projection`'s job and is not repeated here.

    Args:
        identity: How rows of this table are addressed.
        dialect: Dialect used for quoting.

    Returns:
        One aliased expression per identity component.

    Example:
        expressions = _identity_projection_list(identity, dialect)
    """
    return [
        f"{expression} AS {dialect.quote_identifier(name)}"
        for expression, name in zip(
            identity.select_expressions(dialect), identity.key_names(), strict=True
        )
    ]


def _iter_pages(
    cursor: Any,
    dialect: Dialect,
    qualified_table: str,
    identity: RowIdentity,
    expressions: list[str],
    where_clause: str | None,
    page_size: int,
) -> Iterator[list[dict[str, Any]]]:
    """Read a table in identity-ordered pages, one bounded query at a time.

    Each page's query completes before the caller sees it, so a caller that
    writes while it reads never has an open result set over the table it is
    modifying. The next page resumes after the last identity seen rather
    than by offset, so a page is neither skipped nor repeated when rows in
    front of the cursor change.

    Args:
        cursor: Open DBAPI cursor. Reused between pages; the caller may
            issue writes on it between them.
        dialect: Dialect supplying the row limit, ordering and placeholders.
        qualified_table: An already-quoted table reference.
        identity: How rows of this table are addressed and ordered.
        expressions: The projection. Must include the identity.
        where_clause: Predicate body without ``WHERE``, or None.
        page_size: Maximum rows per page, which is also the memory bound.

    Yields:
        One non-empty page of rows, each a name-keyed dict.

    Example:
        for page in _iter_pages(cursor, dialect, tbl, identity, cols, None, 1000):
            for row in page:
                ...
    """
    order_by = identity.order_by_expressions(dialect)
    after: dict[str, Any] | None = None

    while True:
        predicate = where_clause
        binds: tuple[Any, ...] = ()
        if after is not None:
            resume = identity.after_clause(dialect)
            predicate = f"({where_clause}) AND ({resume})" if where_clause else resume
            binds = identity.after_bind_values(after)

        cursor.execute(
            dialect.limited_select_sql(
                qualified_table,
                expressions,
                predicate,
                limit=page_size,
                order_by=order_by,
            ),
            binds,
        )
        names = [description[0] for description in cursor.description]
        rows = [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]
        if not rows:
            return

        yield rows

        # A short page is the last one. A full page might be, so the loop
        # asks once more and stops on the empty answer -- one extra bounded
        # query in exchange for never truncating a table whose size happens
        # to be a multiple of the page size.
        if len(rows) < page_size:
            return
        after = _read_row_key(rows[-1], identity)


def _read_row_key(row: dict[str, Any], identity: RowIdentity) -> dict[str, Any]:
    """Extract a row's identity from a fetched row.

    Args:
        row: One row as a name-keyed dict.
        identity: How rows of this table are addressed.

    Returns:
        The identity, ready to store in a CleansingLog and replay later.

    Example:
        row_key = _read_row_key(row, identity)
    """
    return {name: row[name] for name in identity.key_names()}


def _standardize(
    cursor: Any,
    run_id: str,
    identity: RowIdentity,
    dialect: Dialect,
    schema_name: str | None,
    table_name: str,
    column_name: str,
    params: dict[str, Any],
    dry_run: bool = False,
) -> list[CleansingLog]:
    """Standardize string values in *column_name*.

    Supported params
    ----------------
    trim : bool
        Strip leading and trailing whitespace.  Default ``True``.
    normalize_spaces : bool
        Collapse multiple consecutive spaces into a single space.
        Default ``False``.
    case : str or None
        ``"upper"``, ``"lower"``, or ``"title"``.  ``None`` = no case change.
        Default ``None``.

    Only rows whose value would actually change are logged; when
    *dry_run* is ``False`` they are also updated.  NULL values are skipped.

    Args:
        cursor: Open DBAPI cursor.
        run_id: Pipeline run identifier.
        schema_name: Schema name or ``None``.
        table_name: Target table name.
        column_name: Target column name.
        params: Standardization parameters (see above).
        dry_run: When ``True``, compute and log the rows that would change
            without executing the ``UPDATE`` statement.

    Returns:
        List of :class:`CleansingLog` entries, one per (would-be) changed row.

    Example::

        logs = _standardize(cursor, "run-1", None, "users", "email",
                            {"case": "lower", "trim": True}, dry_run=False)
    """
    trim = params.get("trim", True)
    normalize_spaces = params.get("normalize_spaces", False)
    case = params.get("case")  # "upper" | "lower" | "title" | None
    tbl = qualified_identifier(schema_name, table_name)
    col = quote_identifier(column_name)
    placeholder = dialect.parameter_placeholder

    logs: list[CleansingLog] = []
    pages = _iter_pages(
        cursor,
        dialect,
        tbl,
        identity,
        [*_identity_projection_list(identity, dialect), col],
        f"{col} IS NOT NULL",
        _READ_PAGE_SIZE,
    )
    for page in pages:
        for row in page:
            original: str = str(row[column_name])
            value = original

            if trim:
                value = value.strip()
            if normalize_spaces:
                value = re.sub(r" +", " ", value)
            if case == "upper":
                value = value.upper()
            elif case == "lower":
                value = value.lower()
            elif case == "title":
                value = value.title()

            if value != original:
                if not dry_run:
                    row_key = _read_row_key(row, identity)
                    cursor.execute(
                        f"UPDATE {tbl} SET {col} = {placeholder} "
                        f"WHERE {identity.where_clause(dialect)}",
                        (value, *identity.bind_values(row_key)),
                    )
                logs.append(
                    CleansingLog(
                        run_id=run_id,
                        operation="standardize",
                        schema_name=schema_name,
                        table_name=table_name,
                        column_name=column_name,
                        row_key=_read_row_key(row, identity),
                        before_value=original,
                        after_value=value,
                    )
                )
    return logs


def _deduplicate(
    cursor: Any,
    run_id: str,
    identity: RowIdentity,
    dialect: Dialect,
    schema_name: str | None,
    table_name: str,
    params: dict[str, Any],
    dry_run: bool = False,
) -> list[CleansingLog]:
    """Remove duplicate rows based on key columns.

    Supported params
    ----------------
    key_columns : list[str]
        Column(s) that define a duplicate.  **Required.**
    keep : str
        ``"first"`` (keep the earliest row by identity order) or ``"last"``
        (keep the latest).
        Default ``"first"``.

    For every set of duplicates, all rows except the one to keep are
    (would be, when *dry_run* is ``True``) deleted, and a
    :class:`CleansingLog` entry is written for each such row.

    Args:
        cursor: Open DBAPI cursor.
        run_id: Pipeline run identifier.
        schema_name: Schema name or ``None``.
        table_name: Target table name.
        params: Deduplication parameters (see above).
        dry_run: When ``True``, identify the rows that would be deleted
            without executing the ``DELETE`` statement.

    Returns:
        List of :class:`CleansingLog` entries, one per (would-be) deleted row.

    Raises:
        ValueError: If *key_columns* is missing or empty.

    Example::

        logs = _deduplicate(cursor, "run-1", None, "users",
                            {"key_columns": ["email"], "keep": "first"}, dry_run=False)
    """
    key_columns: list[str] = params.get("key_columns", [])
    if not key_columns:
        raise ValueError("deduplicate operation requires params.key_columns (non-empty list).")
    keep: str = params.get("keep", "first")
    tbl = qualified_identifier(schema_name, table_name)

    quoted_keys = [quote_identifier(c) for c in key_columns]
    key_expr = ", ".join(quoted_keys)
    # A NULL-valued key column is not equal to another NULL for duplicate purposes —
    # GROUP BY would otherwise collapse all NULL-keyed rows into one "duplicate" group
    # and delete genuinely distinct rows. Exclude any row with a NULL key column.
    not_null_guard = " AND ".join(f"{qk} IS NOT NULL" for qk in quoted_keys)

    # Rank each row within its duplicate group and delete everything after the
    # first. This used to be `rowid NOT IN (SELECT MIN(rowid) ... GROUP BY ...)`,
    # which is SQLite-only twice over: rowid does not exist elsewhere, and
    # PostgreSQL has no aggregate over its ctid equivalent either. A window
    # function is portable across SQLite 3.25+, PostgreSQL and SQL Server, and
    # it handles a composite key without needing an aggregate at all (NEW-M).
    order_expr = ", ".join(identity.select_expressions(dialect))
    direction = "ASC" if keep == "first" else "DESC"
    # Every column comes back with the ranking, not one SELECT * per duplicate
    # afterwards. A DELETE has no after-value, so revert() needs the whole row,
    # and the ranked query already visits exactly those rows -- asking again,
    # once per row, was per-row work over a table.
    #
    # The identity is projected separately only where it is not already among
    # the columns: a primary key is, a physical locator is not.
    ranked_projection = f"{tbl}.*"
    if identity.locator is not None:
        ranked_projection = f"{_identity_projection(identity, dialect)}, {ranked_projection}"
    dup_sql = f"""
        SELECT *
        FROM (
            SELECT
                {ranked_projection},
                ROW_NUMBER() OVER (
                    PARTITION BY {key_expr}
                    ORDER BY {order_expr} {direction}
                ) AS dqt_rank
            FROM {tbl}
            WHERE {not_null_guard}
        ) AS dqt_ranked
        WHERE dqt_rank > 1
    """
    rows_to_delete = _fetch_all_dicts(cursor, dup_sql)

    where_clause = identity.where_clause(dialect)
    logs: list[CleansingLog] = []
    for row in rows_to_delete:
        row_key = _read_row_key(row, identity)
        binds = identity.bind_values(row_key)
        before = {name: value for name, value in row.items() if name != "dqt_rank"}
        if not dry_run:
            cursor.execute(f"DELETE FROM {tbl} WHERE {where_clause}", binds)
        logs.append(
            CleansingLog(
                run_id=run_id,
                operation="deduplicate",
                schema_name=schema_name,
                table_name=table_name,
                column_name=None,
                row_key=row_key,
                before_value=before,
                after_value=None,
            )
        )
    return logs


def _lookup_correct(
    cursor: Any,
    run_id: str,
    identity: RowIdentity,
    dialect: Dialect,
    schema_name: str | None,
    table_name: str,
    column_name: str,
    params: dict[str, Any],
    dry_run: bool = False,
) -> list[CleansingLog]:
    """Replace column values using a domain lookup table.

    The lookup table must have exactly two relevant columns:
    a ``from_column`` (raw / incorrect value) and a ``to_column``
    (correct / canonical value).  Any row in *table_name* whose
    *column_name* value matches a ``from_column`` entry is updated to
    the corresponding ``to_column`` value.

    Supported params
    ----------------
    lookup_table : str
        Name of the lookup / domain table.  **Required.**
    from_column : str
        Column in the lookup table containing raw values.  Default ``"from_value"``.
    to_column : str
        Column in the lookup table containing canonical values.  Default ``"to_value"``.
    lookup_schema : str or None
        Schema of the lookup table.  Defaults to the same schema as *table_name*.

    Args:
        cursor: Open DBAPI cursor.
        run_id: Pipeline run identifier.
        schema_name: Schema name of the target table, or ``None``.
        table_name: Target table name.
        column_name: Target column name.
        params: Lookup correction parameters (see above).
        dry_run: When ``True``, identify the rows that would be corrected
            without executing the ``UPDATE`` statement.

    Returns:
        List of :class:`CleansingLog` entries, one per (would-be) corrected row.

    Raises:
        ValueError: If *lookup_table* param is missing.

    Example::

        logs = _lookup_correct(
            cursor, "run-1", None, "orders", "status",
            {"lookup_table": "status_map",
             "from_column": "raw_status",
             "to_column": "canonical_status"},
            dry_run=False,
        )
    """
    lookup_table: str = params.get("lookup_table", "")
    if not lookup_table:
        raise ValueError("lookup_correct operation requires params.lookup_table.")
    from_col: str = params.get("from_column", "from_value")
    to_col: str = params.get("to_column", "to_value")
    lookup_schema: str | None = params.get("lookup_schema", schema_name)

    tbl = qualified_identifier(schema_name, table_name)
    lookup_tbl = qualified_identifier(lookup_schema, lookup_table)
    col = quote_identifier(column_name)
    placeholder = dialect.parameter_placeholder
    from_col_q = quote_identifier(from_col)
    to_col_q = quote_identifier(to_col)

    # The mapping is read whole and deliberately: it is a dictionary the
    # operation looks every row up in, so paging it would only move the
    # same rows into memory more slowly. It is bounded by the number of
    # corrections a DBA has written down, not by the table being cleansed.
    mapping_rows = _fetch_all_dicts(
        cursor,
        f"SELECT {from_col_q}, {to_col_q} FROM {lookup_tbl}",
    )
    mapping: dict[Any, Any] = {r[from_col]: r[to_col] for r in mapping_rows}
    if not mapping:
        return []

    logs: list[CleansingLog] = []
    pages = _iter_pages(
        cursor,
        dialect,
        tbl,
        identity,
        [*_identity_projection_list(identity, dialect), col],
        f"{col} IS NOT NULL",
        _READ_PAGE_SIZE,
    )
    for page in pages:
        for row in page:
            old_val = row[column_name]
            if old_val not in mapping:
                continue
            new_val = mapping[old_val]
            if not dry_run:
                cursor.execute(
                    f"UPDATE {tbl} SET {col} = {placeholder} "
                    f"WHERE {identity.where_clause(dialect)}",
                    (new_val, *identity.bind_values(_read_row_key(row, identity))),
                )
            logs.append(
                CleansingLog(
                    run_id=run_id,
                    operation="lookup_correct",
                    schema_name=schema_name,
                    table_name=table_name,
                    column_name=column_name,
                    row_key=_read_row_key(row, identity),
                    before_value=old_val,
                    after_value=new_val,
                )
            )
    return logs


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def apply_cleansing(
    run_id: str,
    connection_config: ConnectionConfig,
    configs: list[CleansingConfig],
    dry_run: bool = True,
) -> CleansingResult:
    """Execute a list of cleansing configs against a live database.

    Two independent safety checks gate every call, corresponding to the two
    ways a caller can fail to opt into a write:

    1. **`read_only`.** If ``connection_config.read_only`` is ``True`` (the
       default), this function raises
       :class:`~dqt.exceptions.ReadOnlyViolationError` immediately, before
       opening a connection or building any SQL statement. This check is
       independent of, and in addition to, the connection-layer enforcement
       in :func:`dqt.sql.rules._get_connection` (SQLite ``mode=ro``,
       PostgreSQL ``TRANSACTION READ ONLY``): even if that layer were ever
       bypassed or ported to a driver this check does not know about, this
       one still stands.
    2. **`dry_run`.** Independently of ``read_only``, if *dry_run* is
       ``True`` (the default), this function computes and logs exactly the
       same :class:`CleansingLog` entries it would produce for a real run,
       but never executes an ``UPDATE``/``DELETE`` statement and never
       commits. Pass ``dry_run=False`` — the equivalent of a CLI caller
       passing ``--commit`` — to actually apply the changes.

    Both defaults are safe: calling this function with only *run_id*,
    *connection_config*, and *configs* neither raises nor writes; it returns
    a preview. Actually writing requires an explicitly writable connection
    (``read_only=False``) *and* an explicit ``dry_run=False``.

    Applies each :class:`CleansingConfig` in order.  Each operation is
    wrapped in a try/except so a single failing config does not abort the
    entire run; errors are collected in :attr:`CleansingResult.errors`.

    When *dry_run* is ``False``, all changes are committed together at the
    end; if an unrecoverable error occurs before commit, the connection is
    rolled back. When *dry_run* is ``True``, the connection is always rolled
    back (nothing was executed that could commit in the first place).

    Args:
        run_id: Unique identifier for the current pipeline run.
        connection_config: Database connection configuration.  Must have
            ``read_only=False`` or this call raises immediately.
        configs: Ordered list of :class:`CleansingConfig` objects to apply.
        dry_run: When ``True`` (the default), compute and log planned
            changes without writing them. When ``False``, execute and
            commit them.

    Returns:
        :class:`CleansingResult` summarising all (planned or applied)
        changes and any errors.

    Raises:
        ReadOnlyViolationError: If ``connection_config.read_only`` is
            ``True``.

    Example::

        from dqt.common.models import ConnectionConfig
        from dqt.sql.cleansing import CleansingConfig, apply_cleansing

        conn_cfg = ConnectionConfig(id="dev", dsn="sqlite:///dev.db", read_only=False)
        result = apply_cleansing(
            run_id="run-001",
            connection_config=conn_cfg,
            configs=[
                CleansingConfig(
                    table_name="users",
                    column_name="email",
                    operation="standardize",
                    params={"case": "lower", "trim": True},
                )
            ],
            dry_run=False,
        )
        print(result.total_changes)
    """
    warnings.warn(
        "apply_cleansing() is superseded by cleanse_plan() / cleanse_apply() / "
        "revert(). It writes a log to memory and returns it, so a caller who "
        "drops the return value loses the before-values permanently and the "
        "change cannot be undone -- the defect DQT-05 exists to fix. The "
        "replacement persists the log against a plan_id and can undo "
        "automatically. See docs/API-STABILITY.md for the removal schedule.",
        DeprecationWarning,
        stacklevel=2,
    )
    if connection_config.read_only:
        raise ReadOnlyViolationError(
            f"Connection '{connection_config.id}' has read_only=True; "
            "apply_cleansing() refuses to build any mutating statement against "
            "it. Set read_only=False on the ConnectionConfig to permit "
            "cleansing writes (dry_run=False is separately required to commit)."
        )

    cleansing_result = CleansingResult(run_id=run_id, dry_run=dry_run)
    tables_modified: set[str] = set()

    dialect = get_dialect_for(connection_config)
    identities = _resolve_identities(connection_config, configs, dialect)

    db_conn = get_connection(connection_config)
    try:
        cursor = db_conn.cursor()

        for cfg in configs:
            if not cfg.enabled:
                continue
            try:
                if cfg.operation == "standardize":
                    if not cfg.column_name:
                        raise ValueError("standardize requires column_name.")
                    logs = _standardize(
                        cursor,
                        run_id,
                        identities[cfg.table_name],
                        dialect,
                        cfg.schema_name,
                        cfg.table_name,
                        cfg.column_name,
                        cfg.params,
                        dry_run,
                    )
                elif cfg.operation == "deduplicate":
                    logs = _deduplicate(
                        cursor,
                        run_id,
                        identities[cfg.table_name],
                        dialect,
                        cfg.schema_name,
                        cfg.table_name,
                        cfg.params,
                        dry_run,
                    )
                elif cfg.operation == "lookup_correct":
                    if not cfg.column_name:
                        raise ValueError("lookup_correct requires column_name.")
                    logs = _lookup_correct(
                        cursor,
                        run_id,
                        identities[cfg.table_name],
                        dialect,
                        cfg.schema_name,
                        cfg.table_name,
                        cfg.column_name,
                        cfg.params,
                        dry_run,
                    )
                else:
                    cleansing_result.errors.append(
                        f"Unknown cleansing operation '{cfg.operation}' "
                        f"on {cfg.table_name}.{cfg.column_name}; skipped."
                    )
                    continue

                cleansing_result.log.extend(logs)
                cleansing_result.total_changes += len(logs)
                if logs:
                    tables_modified.add(cfg.table_name)

            except Exception as exc:  # noqa: BLE001
                cleansing_result.errors.append(
                    f"Error in '{cfg.operation}' on {cfg.table_name}.{cfg.column_name}: {exc}"
                )

        if dry_run:
            db_conn.rollback()
        else:
            db_conn.commit()

    except Exception:
        db_conn.rollback()
        raise
    finally:
        db_conn.close()

    cleansing_result.tables_affected = len(tables_modified)
    return cleansing_result


def _resolve_identities(
    connection_config: ConnectionConfig,
    configs: list[CleansingConfig],
    dialect: Dialect,
) -> dict[str, RowIdentity]:
    """Work out how to address rows of every table the configs touch.

    Discovery runs once per plan rather than once per operation, so several
    configs against one table cost one introspection between them.

    Args:
        connection_config: Connection to introspect.
        configs: Cleansing operations about to run.
        dialect: Dialect that may offer a physical locator.

    Returns:
        A RowIdentity per table name named by *configs*.

    Raises:
        ValueError: If a named table does not exist, or has no primary key on
            a dialect with no stable locator.

    Example:
        identities = _resolve_identities(config, configs, dialect)
    """
    wanted = {cfg.table_name for cfg in configs if cfg.enabled}
    discovered = {
        table.table_name: table
        for table in discover_schema(connection_config)
        if table.table_name in wanted
    }
    missing = wanted - set(discovered)
    if missing:
        raise ValueError(
            f"Cleansing was asked to change {sorted(missing)}, which discovery "
            "did not find. Check the table name and the schema the connection "
            "points at."
        )
    return {name: resolve_row_identity(table, dialect) for name, table in discovered.items()}


def _compute_changes(
    cursor: Any,
    run_id: str,
    configs: list[CleansingConfig],
    dry_run: bool,
    dialect: Dialect,
    identities: dict[str, RowIdentity],
) -> list[CleansingLog]:
    """Run every enabled config and collect the rows it would change.

    Args:
        cursor: Open DBAPI cursor.
        run_id: Run the logs are attributed to.
        configs: Cleansing operations to evaluate.
        dry_run: When True, compute without issuing any mutation.
        dialect: Dialect owning quoting, placeholders and row identity.
        identities: How to address rows, keyed by table name.

    Returns:
        One :class:`CleansingLog` per row that changed or would change.

    Raises:
        ValueError: If a config omits a column the operation requires.

    Example:
        logs = _compute_changes(cursor, "run-1", configs, dry_run=True)
    """
    collected: list[CleansingLog] = []
    for cfg in configs:
        if not cfg.enabled:
            continue
        identity = identities[cfg.table_name]
        if cfg.operation == "standardize":
            if not cfg.column_name:
                raise ValueError("standardize requires column_name.")
            collected += _standardize(
                cursor,
                run_id,
                identity,
                dialect,
                cfg.schema_name,
                cfg.table_name,
                cfg.column_name,
                cfg.params,
                dry_run,
            )
        elif cfg.operation == "deduplicate":
            collected += _deduplicate(
                cursor,
                run_id,
                identity,
                dialect,
                cfg.schema_name,
                cfg.table_name,
                cfg.params,
                dry_run,
            )
        elif cfg.operation == "lookup_correct":
            if not cfg.column_name:
                raise ValueError("lookup_correct requires column_name.")
            collected += _lookup_correct(
                cursor,
                run_id,
                identity,
                dialect,
                cfg.schema_name,
                cfg.table_name,
                cfg.column_name,
                cfg.params,
                dry_run,
            )
        else:
            raise ValueError(f"Unknown cleansing operation: {cfg.operation!r}")
    return collected


def _fingerprint(changes: list[CleansingLog]) -> str:
    """Digest the rows a plan targets, as they were when it was computed.

    Covers the row identity and the value found there, so the check catches
    both a row that moved and a value edited underneath the plan.

    Args:
        changes: The planned changes.

    Returns:
        A hex digest.

    Example:
        fingerprint = _fingerprint(plan.changes)
    """
    digest = hashlib.sha256()
    for change in sorted(
        changes, key=lambda c: (c.table_name, str(c.column_name), repr(c.row_key))
    ):
        digest.update(
            repr(
                (change.table_name, change.column_name, change.row_key, change.before_value)
            ).encode("utf-8")
        )
    return digest.hexdigest()


@dataclass
class CleansingPlan:
    """What a cleansing run would change, computed and stored before it runs.

    A plan is the addressable unit `Q2` chose over a discarded ``--dry-run``
    preview: what a reviewer approved and what is later executed are the same
    object, retrieved by ``plan_id`` rather than reconstructed.

    Attributes:
        plan_id: Identifier assigned at planning time.
        connection_id: Connection the plan was computed against.
        configs: The cleansing configs it covers.
        created_at: When planning ran.
        changes: One entry per row that would change, with its before-value.
        fingerprint: Digest of the affected rows as they were at planning
            time, used to refuse a stale plan.
        run_id: Pipeline run that produced it, or None for an ad hoc call.
        applied_at: When it was executed, or None if it has not been.

    Example:
        plan = cleanse_plan(connection_config, configs, store=store)
    """

    plan_id: str
    connection_id: str
    configs: list[CleansingConfig]
    created_at: datetime
    changes: list[CleansingLog] = field(default_factory=list)
    fingerprint: str = ""
    run_id: str | None = None
    applied_at: datetime | None = None


def cleanse_plan(
    connection_config: ConnectionConfig,
    configs: list[CleansingConfig],
    *,
    store: Any,
    run_id: str | None = None,
) -> CleansingPlan:
    """Compute and persist what cleansing would change, mutating nothing.

    Args:
        connection_config: Connection to read from. May be read-only.
        configs: Cleansing operations to plan.
        store: RunStore that persists the plan.
        run_id: Owning pipeline run, or None for an ad hoc call.

    Returns:
        The persisted :class:`CleansingPlan`.

    Example:
        plan = cleanse_plan(config, configs, store=store)
    """
    dialect = get_dialect_for(connection_config)
    identities = _resolve_identities(connection_config, configs, dialect)

    connection = get_connection(connection_config)
    try:
        cursor = connection.cursor()
        # dry_run=True: planning is a read, which is why it works against a
        # read-only connection and why producing a plan from production needs
        # no write authority.
        changes = _compute_changes(cursor, run_id or "", configs, True, dialect, identities)
    finally:
        connection.close()

    plan = CleansingPlan(
        plan_id=f"plan-{uuid.uuid4().hex[:12]}",
        connection_id=connection_config.id,
        configs=configs,
        created_at=datetime.now(UTC),
        changes=changes,
        fingerprint=_fingerprint(changes),
        run_id=run_id,
    )
    store.save_cleansing_plan(plan)
    return plan


def cleanse_apply(
    plan_id: str,
    connection_config: ConnectionConfig,
    *,
    store: Any,
) -> CleansingResult:
    """Execute a previously planned change set.

    Args:
        plan_id: Plan to execute.
        connection_config: Connection to write through. Must not be read-only.
        store: RunStore holding the plan.

    Returns:
        A :class:`CleansingResult` describing what changed.

    Raises:
        ValueError: If the plan is unknown, already applied, or the data has
            drifted since it was planned.
        ReadOnlyViolationError: If the connection is read-only.

    Example:
        result = cleanse_apply(plan.plan_id, config, store=store)
    """
    plan = store.load_cleansing_plan(plan_id)
    if plan is None:
        raise ValueError(f"No cleansing plan with id {plan_id!r}.")
    if plan.applied_at is not None:
        raise ValueError(
            f"Plan {plan_id!r} was already applied at {plan.applied_at.isoformat()}. "
            "A plan is a one-shot authorisation: re-running it would write a second "
            "log for the same intent, and the two would disagree about the original "
            "values, making the revert chain ambiguous."
        )
    if connection_config.read_only:
        raise ReadOnlyViolationError(
            f"Connection {connection_config.id!r} has read_only=True; cleanse_apply "
            "refuses to build a mutating statement. Planning is a read and needs no "
            "write authority; applying does."
        )

    dialect = get_dialect_for(connection_config)
    connection = get_connection(connection_config)
    result = CleansingResult(run_id=plan.run_id or "", dry_run=False)
    try:
        cursor = connection.cursor()
        current = _compute_changes(
            cursor,
            plan.run_id or "",
            plan.configs,
            True,
            dialect,
            _resolve_identities(connection_config, plan.configs, dialect),
        )
        if _fingerprint(current) != plan.fingerprint:
            raise ValueError(
                f"The data changed since plan {plan_id!r} was computed. Applying it "
                "would record before-values that no longer describe what is there, so "
                "the log would lie and a revert built on it would corrupt rather than "
                "restore. Re-plan against the current state."
            )

        # Replay the reviewed plan rather than recomputing: what was approved
        # is what executes.
        for change in plan.changes:
            table = qualified_identifier(change.schema_name, change.table_name)
            column = quote_identifier(str(change.column_name))
            identity = _identity_from_row_key(change.row_key, dialect)
            cursor.execute(
                f"UPDATE {table} SET {column} = {dialect.parameter_placeholder} "
                f"WHERE {identity.where_clause(dialect)}",
                (change.after_value, *identity.bind_values(change.row_key)),
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    applied_at = datetime.now(UTC)
    store.save_cleansing_log(plan_id, plan.changes, applied_at)
    store.mark_cleansing_plan_applied(plan_id, applied_at)

    result.log = list(plan.changes)
    result.total_changes = len(plan.changes)
    result.tables_affected = len({c.table_name for c in plan.changes})
    return result


def revert(
    plan_id: str,
    connection_config: ConnectionConfig,
    *,
    store: Any,
) -> CleansingResult:
    """Replay a plan's log backwards, restoring the prior values.

    Args:
        plan_id: Plan to undo.
        connection_config: Connection to write through.
        store: RunStore holding the plan and its log.

    Returns:
        A :class:`CleansingResult` describing what was restored.

    Raises:
        ValueError: If the plan is unknown or was never applied.
        ReadOnlyViolationError: If the connection is read-only.

    Example:
        revert(plan.plan_id, config, store=store)
    """
    plan = store.load_cleansing_plan(plan_id)
    if plan is None:
        raise ValueError(f"No cleansing plan with id {plan_id!r}.")
    if plan.applied_at is None:
        raise ValueError(f"Plan {plan_id!r} has not been applied, so there is nothing to undo.")
    if connection_config.read_only:
        raise ReadOnlyViolationError(
            f"Connection {connection_config.id!r} has read_only=True; revert writes."
        )

    entries = store.load_cleansing_log(plan_id)
    dialect = get_dialect_for(connection_config)
    connection = get_connection(connection_config)
    result = CleansingResult(run_id=plan.run_id or "", dry_run=False)
    try:
        cursor = connection.cursor()
        # Backwards: the last change made is the first undone, so overlapping
        # edits to one row unwind in the order they were applied.
        for entry in reversed(entries):
            table = qualified_identifier(entry["schema_name"], entry["table_name"])
            column = quote_identifier(str(entry["column_name"]))
            identity = _identity_from_row_key(entry["row_key"], dialect)
            cursor.execute(
                f"UPDATE {table} SET {column} = {dialect.parameter_placeholder} "
                f"WHERE {identity.where_clause(dialect)}",
                (entry["before_value"], *identity.bind_values(entry["row_key"])),
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    result.total_changes = len(entries)
    result.tables_affected = len({e["table_name"] for e in entries})
    return result


__all__ = [
    "CleansingConfig",
    "CleansingLog",
    "CleansingPlan",
    "CleansingResult",
    "apply_cleansing",
    "cleanse_apply",
    "cleanse_plan",
    "revert",
]
