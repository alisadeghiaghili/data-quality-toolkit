"""
dqt.common.storage
==================

Lightweight storage backend for DQT pipeline runs, data-quality metrics,
and data-quality issues.

This module stores only DQT run metadata plus data-quality metrics/issues
used by monitoring, UI exploration, and report generation. It is strictly
about data quality; it does not store service/performance monitoring data
such as latency, CPU, wait stats, or uptime.

Security notes:
    - This store never persists database credentials or DSNs.
    - Only ``connection_id`` (an opaque identifier) and data-quality results
      are stored.  The actual DSN lives solely in ``ConnectionConfig`` at
      runtime and is never written here.
    - All write operations are safe for concurrent readers; destructive
      operations (DROP, DELETE without filter) are intentionally absent.

Default backend: SQLite (via the standard-library ``sqlite3`` module).
The three managed tables are::

    runs(run_id, connection_id, started_at, ended_at, status)
    run_metrics(run_id, schema_name, table_name, column_name,
                dimension, score, value, metadata)
    run_issues(issue_id, run_id, schema_name, table_name, column_name,
               dimension, severity, message, evidence, rule_name)
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from dqt.common.models import DQIssue, DQMetric, PipelineResult

# ---------------------------------------------------------------------------
# Default database path (can be overridden via RunStore constructor)
# ---------------------------------------------------------------------------

_DEFAULT_DB_PATH: Path = Path("dqt_runs.db")


#: Schema version written to ``PRAGMA user_version`` and required on open.
#:
#: One integer, rather than a growing chain of "does this column exist yet"
#: probes: each of those only ever detects the specific past it was taught
#: about. Bump it whenever the DDL below changes -- the store is a local
#: artifact meant to be recreated rather than migrated.
SCHEMA_VERSION = 2


class RunStore:
    """SQLite-backed store for DQT pipeline run results.

    ``RunStore`` manages three tables that record the outcome of every DQT
    pipeline run:

    * **runs** – one row per pipeline run (metadata only; no credentials).
    * **run_metrics** – one row per :class:`~dqt.common.models.DQMetric`
      produced during a run.
    * **run_issues** – one row per :class:`~dqt.common.models.DQIssue`
      detected during a run.

    The store is intentionally lightweight: it uses the standard-library
    ``sqlite3`` module with no external ORM dependencies.  It is suitable for
    local development, CI, and single-server deployments.  For larger
    deployments substitute a proper database backend behind the same interface.

    Security contract:
        This class NEVER stores DSNs, passwords, or any connection credentials.
        Only ``connection_id`` (an opaque string) is written to ``runs``.

    Args:
        db_path: Path to the SQLite database file.  Created automatically if
            it does not exist.  Defaults to ``dqt_runs.db`` in the current
            working directory.

    Example::

        store = RunStore("~/.dqt/history.db")
        store.init_schema()
        store.save_run(pipeline_result)
        runs = store.load_runs()
    """

    def __init__(self, db_path: str | Path = _DEFAULT_DB_PATH) -> None:
        self._db_path: Path = Path(db_path).expanduser().resolve()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        """Open and return a new SQLite connection with sensible defaults."""
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        return conn

    # ------------------------------------------------------------------
    # Schema management
    # ------------------------------------------------------------------

    def _assert_store_is_current(self) -> None:
        """Refuse a store written by an older DQT rather than half-using it.

        The DDL is ``CREATE TABLE IF NOT EXISTS``, so an existing file is left
        exactly as it was and columns added since never appear. The store is a
        local artifact meant to be recreated rather than migrated
        (``CONVENTIONS-DQT.md``), and this is what makes that decision
        survivable: without it the first symptom is an OperationalError thrown
        from the middle of a run that has already done its work.

        Raises:
            RuntimeError: If the file exists with a pre-``NEW-A`` schema.

        Example:
            store._assert_store_is_current()
        """
        if not self._db_path.exists():
            return
        with self._connect() as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            if "run_metrics" not in tables:
                return
            columns = {row[1] for row in conn.execute("PRAGMA table_info(run_metrics)")}

        if "metric_name" not in columns:
            raise RuntimeError(
                f"The run store at {self._db_path} is out of date: run_metrics has no "
                "metric_name column, so it predates NEW-A. DQT recreates this store "
                "rather than migrating it, because it holds run history rather than "
                "source data. Delete the file and re-run; past runs in it are lost, "
                "which is why it is not the place to keep anything you need."
            )

    def init_schema(self) -> None:
        """Create the DQT storage tables if they do not already exist.

        Safe to call multiple times (uses ``CREATE TABLE IF NOT EXISTS``).
        The database file and any missing parent directories are created
        automatically.

        Tables created:

        * ``runs`` – pipeline run metadata.
        * ``run_metrics`` – per-dimension quality scores.
        * ``run_issues`` – per-issue diagnostics.

        Example::

            store = RunStore()
            store.init_schema()  # idempotent
        """
        self._assert_store_is_current()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        ddl = [
            """
            CREATE TABLE IF NOT EXISTS runs (
                run_id        TEXT PRIMARY KEY,
                connection_id TEXT NOT NULL,
                started_at    TEXT NOT NULL,
                ended_at      TEXT NOT NULL,
                status        TEXT NOT NULL
                              CHECK (status IN ('success', 'failed', 'partial'))
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS run_metrics (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id      TEXT    NOT NULL REFERENCES runs(run_id),
                schema_name TEXT,
                table_name  TEXT,
                column_name TEXT,
                -- Nullable: a raw measurement such as row_count is not a
                -- quality dimension, and forcing it into this column is the
                -- defect NEW-A removes. The CHECK keeps section 0.1's closed
                -- set true in the database, not only in Python.
                dimension   TEXT
                            CHECK (dimension IS NULL OR dimension IN (
                                'completeness', 'validity', 'uniqueness',
                                'consistency', 'referential_integrity', 'timeliness'
                            )),
                metric_name TEXT,
                score       REAL    NOT NULL,
                value       REAL,
                metadata    TEXT    DEFAULT '{}',
                -- Table-level: exactly one of the two, mirroring
                -- DQMetric.__post_init__ so direct SQL cannot store a row the
                -- model would refuse to construct.
                CHECK ((dimension IS NULL) <> (metric_name IS NULL))
            );
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_run_metrics_run_id
                ON run_metrics(run_id);
            """,
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_run_metrics_natural_key
                ON run_metrics(
                    run_id,
                    COALESCE(schema_name, ''),
                    COALESCE(table_name, ''),
                    COALESCE(column_name, ''),
                    -- Both, coalesced: SQLite treats NULLs as distinct, so
                    -- indexing the nullable dimension alone would let two
                    -- identical row_count metrics both be stored.
                    COALESCE(dimension, ''),
                    COALESCE(metric_name, '')
                );
            """,
            """
            CREATE TABLE IF NOT EXISTS run_issues (
                issue_id    TEXT PRIMARY KEY,
                run_id      TEXT NOT NULL REFERENCES runs(run_id),
                schema_name TEXT,
                table_name  TEXT,
                column_name TEXT,
                -- An issue is always a judgement, so unlike a metric this
                -- stays NOT NULL: there is no measurement case here.
                dimension   TEXT NOT NULL
                            CHECK (dimension IN (
                                'completeness', 'validity', 'uniqueness',
                                'consistency', 'referential_integrity', 'timeliness'
                            )),
                severity    TEXT NOT NULL
                            CHECK (severity IN ('info', 'warning', 'error', 'critical')),
                message     TEXT NOT NULL,
                evidence    TEXT DEFAULT '{}',
                rule_name   TEXT
            );
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_run_issues_run_id
                ON run_issues(run_id);
            """,
            """
            CREATE TABLE IF NOT EXISTS cleansing_plans (
                plan_id       TEXT PRIMARY KEY,
                -- Nullable and ON DELETE SET NULL: a plan's audit value has
                -- to outlive the run's retention window. A plan is typically
                -- produced during a run but applied and reverted independently
                -- of it, which is why it has its own identity (DQT-05, Q2).
                run_id        TEXT REFERENCES runs(run_id) ON DELETE SET NULL,
                connection_id TEXT NOT NULL,
                configs       TEXT NOT NULL,
                changes       TEXT NOT NULL,
                fingerprint   TEXT NOT NULL,
                created_at    TEXT NOT NULL,
                applied_at    TEXT
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS cleansing_log (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                plan_id      TEXT NOT NULL REFERENCES cleansing_plans(plan_id),
                operation    TEXT NOT NULL,
                schema_name  TEXT,
                table_name   TEXT NOT NULL,
                column_name  TEXT,
                row_key      TEXT NOT NULL,
                before_value TEXT,
                after_value  TEXT,
                logged_at    TEXT NOT NULL
            );
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_cleansing_log_plan_id
                ON cleansing_log(plan_id);
            """,
        ]
        with self._connect() as conn:
            for stmt in ddl:
                conn.execute(stmt)

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def save_run(self, result: PipelineResult) -> None:
        """Persist a complete pipeline run result to the store.

        Writes one row to ``runs``, N rows to ``run_metrics`` (one per
        :class:`~dqt.common.models.DQMetric` in *result*), and M rows to
        ``run_issues`` (one per :class:`~dqt.common.models.DQIssue`).

        If a run with the same ``run_id`` already exists, the entire save is
        skipped (idempotent insert via ``INSERT OR IGNORE``).

        Args:
            result: A fully populated :class:`~dqt.common.models.PipelineResult`
                produced by ``DQTPipeline.run()``.

        Example::

            store.save_run(pipeline_result)
        """
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO runs
                    (run_id, connection_id, started_at, ended_at, status)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    result.run_id,
                    result.connection_id,
                    result.started_at.isoformat(),
                    result.ended_at.isoformat(),
                    result.status,
                ),
            )
            conn.executemany(
                """
                INSERT OR IGNORE INTO run_metrics
                    (run_id, schema_name, table_name, column_name,
                     dimension, metric_name, score, value, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [self._metric_row(result.run_id, m) for m in result.metrics],
            )
            conn.executemany(
                """
                INSERT OR IGNORE INTO run_issues
                    (issue_id, run_id, schema_name, table_name, column_name,
                     dimension, severity, message, evidence, rule_name)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [self._issue_row(i) for i in result.issues],
            )

    def load_rule_results(self, run_id: str) -> list[dict[str, Any]]:
        """Return one summary per rule evaluated in *run_id*.

        Args:
            run_id: The run to read.

        Returns:
            Plain dicts in rule-name order, each carrying ``run_id``,
            ``rule_name``, ``targets_checked``, ``targets_failed`` and
            ``targets_error``.

        Example:
            summaries = store.load_rule_results("run-001")
        """
        raise NotImplementedError

    def load_rule_history(self, rule_name: str, limit: int = 50) -> list[dict[str, Any]]:
        """Return one rule's results across runs, newest first.

        Args:
            rule_name: The rule to follow.
            limit: Maximum entries returned.

        Returns:
            Plain dicts carrying the rule's counts plus the run's
            ``started_at``, newest first.

        Example:
            history = store.load_rule_history("not-null-email")
        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def load_runs(
        self,
        connection_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Load run metadata rows, optionally filtered.

        Args:
            connection_id: Filter to runs for a specific connection.  ``None``
                returns runs for all connections.
            status: Filter by run status (``"success"``, ``"failed"``,
                ``"partial"``).  ``None`` returns all statuses.
            limit: Maximum number of rows to return.  Defaults to ``100``.
                Rows are ordered by ``started_at`` descending (newest first).

        Returns:
            A list of plain ``dict`` objects (column name → value).

        Example::

            recent = store.load_runs(connection_id="pg-prod", limit=10)
        """
        clauses: list[str] = []
        params: list[Any] = []
        if connection_id is not None:
            clauses.append("connection_id = ?")
            params.append(connection_id)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"""
            SELECT run_id, connection_id, started_at, ended_at, status
            FROM runs
            {where}
            ORDER BY started_at DESC
            LIMIT ?
        """
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def load_metrics(
        self,
        run_id: str,
        table_name: str | None = None,
        dimension: str | None = None,
    ) -> list[dict[str, Any]]:
        """Load metric rows for a specific run, optionally filtered.

        Args:
            run_id: The pipeline run whose metrics to retrieve.
            table_name: Filter to metrics for a specific table.  ``None``
                returns metrics for all tables.
            dimension: Filter to a specific DQ dimension (e.g.
                ``"completeness"``).  ``None`` returns all dimensions.

        Returns:
            A list of plain ``dict`` objects (column name → value), with
            ``metadata`` deserialized from JSON to a ``dict``.

        Example::

            metrics = store.load_metrics("run-001", dimension="completeness")
        """
        clauses: list[str] = ["run_id = ?"]
        params: list[Any] = [run_id]
        if table_name is not None:
            clauses.append("table_name = ?")
            params.append(table_name)
        if dimension is not None:
            clauses.append("dimension = ?")
            params.append(dimension)
        where = "WHERE " + " AND ".join(clauses)
        sql = f"""
            SELECT run_id, schema_name, table_name, column_name, metric_name,
                   dimension, score, value, metadata
            FROM run_metrics
            {where}
            ORDER BY schema_name, table_name, column_name, dimension
        """
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        result = []
        for r in rows:
            row = dict(r)
            row["metadata"] = json.loads(row["metadata"] or "{}")
            result.append(row)
        return result

    def load_issues(
        self,
        run_id: str,
        severity: str | None = None,
        table_name: str | None = None,
    ) -> list[dict[str, Any]]:
        """Load issue rows for a specific run, optionally filtered.

        Args:
            run_id: The pipeline run whose issues to retrieve.
            severity: Filter to a specific severity level
                (``"info"``, ``"warning"``, ``"error"``, ``"critical"``).
                ``None`` returns all severities.
            table_name: Filter to issues for a specific table.  ``None``
                returns issues for all tables.

        Returns:
            A list of plain ``dict`` objects (column name → value), with
            ``evidence`` deserialized from JSON to a ``dict``.

        Example::

            critical = store.load_issues("run-001", severity="critical")
        """
        clauses: list[str] = ["run_id = ?"]
        params: list[Any] = [run_id]
        if severity is not None:
            clauses.append("severity = ?")
            params.append(severity)
        if table_name is not None:
            clauses.append("table_name = ?")
            params.append(table_name)
        where = "WHERE " + " AND ".join(clauses)
        sql = f"""
            SELECT issue_id, run_id, schema_name, table_name, column_name,
                   dimension, severity, message, evidence, rule_name
            FROM run_issues
            {where}
            ORDER BY severity DESC, table_name, column_name
        """
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        result = []
        for r in rows:
            row = dict(r)
            row["evidence"] = json.loads(row["evidence"] or "{}")
            result.append(row)
        return result

    # ------------------------------------------------------------------
    # Private mapping helpers
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Cleansing plans and their logs (DQT-05)
    # ------------------------------------------------------------------

    def save_cleansing_plan(self, plan: Any) -> None:
        """Persist a cleansing plan and the change set it computed.

        Args:
            plan: The CleansingPlan to store.

        Returns:
            None.

        Example:
            store.save_cleansing_plan(plan)
        """
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO cleansing_plans
                    (plan_id, run_id, connection_id, configs, changes,
                     fingerprint, created_at, applied_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    plan.plan_id,
                    plan.run_id,
                    plan.connection_id,
                    json.dumps([asdict(c) for c in plan.configs]),
                    json.dumps([asdict(c) for c in plan.changes], default=str),
                    plan.fingerprint,
                    plan.created_at.isoformat(),
                    plan.applied_at.isoformat() if plan.applied_at else None,
                ),
            )

    def load_cleansing_plan(self, plan_id: str) -> Any:
        """Load a cleansing plan by its identifier.

        Args:
            plan_id: Plan to load.

        Returns:
            The CleansingPlan, or None if no such plan exists.

        Example:
            plan = store.load_cleansing_plan("plan-abc")
        """
        from dqt.sql.cleansing import CleansingConfig, CleansingLog, CleansingPlan

        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM cleansing_plans WHERE plan_id = ?", (plan_id,)
            ).fetchone()
        if row is None:
            return None
        return CleansingPlan(
            plan_id=row["plan_id"],
            run_id=row["run_id"],
            connection_id=row["connection_id"],
            configs=[CleansingConfig(**c) for c in json.loads(row["configs"])],
            changes=[CleansingLog(**c) for c in json.loads(row["changes"])],
            fingerprint=row["fingerprint"],
            created_at=datetime.fromisoformat(row["created_at"]),
            applied_at=(datetime.fromisoformat(row["applied_at"]) if row["applied_at"] else None),
        )

    def save_cleansing_log(self, plan_id: str, changes: Any, applied_at: Any) -> None:
        """Persist the per-row log written when a plan was applied.

        The before-values stored here are what :func:`~dqt.sql.cleansing.revert`
        replays. Without them the log would be an audit trail only -- the
        distinction ``CONVENTIONS-DQT.md`` section 1 S4 insists on.

        Args:
            plan_id: Plan the log belongs to.
            changes: CleansingLog entries that were applied.
            applied_at: When they were applied.

        Returns:
            None.

        Example:
            store.save_cleansing_log(plan.plan_id, plan.changes, applied_at)
        """
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO cleansing_log
                    (plan_id, operation, schema_name, table_name, column_name,
                     row_key, before_value, after_value, logged_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        plan_id,
                        change.operation,
                        change.schema_name,
                        change.table_name,
                        change.column_name,
                        json.dumps(change.row_key),
                        change.before_value,
                        change.after_value,
                        applied_at.isoformat(),
                    )
                    for change in changes
                ],
            )

    def load_cleansing_log(self, plan_id: str) -> list[dict[str, Any]]:
        """Load the per-row log written when a plan was applied.

        Args:
            plan_id: Plan whose log to read.

        Returns:
            One dict per changed row, oldest first.

        Example:
            entries = store.load_cleansing_log("plan-abc")
        """
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM cleansing_log WHERE plan_id = ? ORDER BY id", (plan_id,)
            ).fetchall()
        return [dict(r) | {"row_key": json.loads(r["row_key"])} for r in rows]

    def mark_cleansing_plan_applied(self, plan_id: str, applied_at: Any) -> None:
        """Record that a plan has been executed.

        Args:
            plan_id: Plan that ran.
            applied_at: When it ran.

        Returns:
            None.

        Example:
            store.mark_cleansing_plan_applied(plan.plan_id, applied_at)
        """
        with self._connect() as conn:
            conn.execute(
                "UPDATE cleansing_plans SET applied_at = ? WHERE plan_id = ?",
                (applied_at.isoformat(), plan_id),
            )

    @staticmethod
    def _metric_row(run_id: str, metric: DQMetric) -> tuple[Any, ...]:
        """Map a DQMetric dataclass to a parameter tuple for run_metrics INSERT."""
        return (
            run_id,
            metric.schema_name,
            metric.table_name,
            metric.column_name,
            metric.dimension,
            metric.metric_name,
            metric.score,
            metric.value,
            json.dumps(metric.metadata),
        )

    @staticmethod
    def _issue_row(issue: DQIssue) -> tuple[Any, ...]:
        """Map a DQIssue dataclass to a parameter tuple for run_issues INSERT."""
        return (
            issue.issue_id,
            issue.run_id,
            issue.schema_name,
            issue.table_name,
            issue.column_name,
            issue.dimension,
            issue.severity,
            issue.message,
            json.dumps(issue.evidence),
            issue.rule_name,
        )


# ---------------------------------------------------------------------------
# Public re-exports
# ---------------------------------------------------------------------------

__all__ = ["RunStore"]
