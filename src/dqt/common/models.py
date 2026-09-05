"""
dqt.common.models
=================

Core domain objects and configuration models for DQT.

Domain objects (dataclasses):
    PipelineResult, SchemaResult, TableResult, ColumnResult,
    DQMetric, DQIssue, Rule, RuleResult, RuleRunResult

Config models (Pydantic BaseModel):
    SamplingConfig, RuleScope, ConnectionConfig,
    DQPipelineConfig, RuleConfig

This module is intentionally pure data/domain: no DB connections,
no SQL, no I/O, no side effects.  It is the single source of truth
for DQT's type system, consumed by all other modules (pipeline,
storage, CLI, UI, bridges).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, get_args

from pydantic import BaseModel, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Literals (reused across domain objects)
# ---------------------------------------------------------------------------

RunStatus = Literal["success", "failed", "partial"]
IssueSeverity = Literal["info", "warning", "error", "critical"]
RuleStatus = Literal["pass", "fail", "error"]

# The closed set from docs/CONVENTIONS-DQT.md section 0.1. Adding a seventh
# value requires editing that section first; this alias is downstream of the
# document, not the other way round.
DQDimension = Literal[
    "completeness",
    "validity",
    "uniqueness",
    "consistency",
    "referential_integrity",
    "timeliness",
]


def get_args_of_dq_dimension() -> set[str]:
    """Return the closed set of data-quality dimension identifiers.

    Returns:
        Every value :data:`DQDimension` admits, as a set of strings.

    Example:
        assert "completeness" in get_args_of_dq_dimension()
    """
    return set(get_args(DQDimension))


# ===========================================================================
# SECTION 1 — Domain Objects (dataclasses)
# ===========================================================================


@dataclass
class StageError:
    """One pipeline stage that did not complete.

    Attributes:
        stage: Name of the stage, e.g. ``"discover_schema"``.
        message: What went wrong, in terms a DBA can act on.
        exception_type: Class name of the underlying exception, or
            ``"missing_input"`` where nothing was raised.

    Example:
        error = StageError(
            stage="discover_schema",
            message="unable to open database file",
            exception_type="OperationalError",
        )
    """

    stage: str
    message: str
    exception_type: str


@dataclass
class DQMetric:
    """A single data-quality metric measurement.

    A ``DQMetric`` captures a normalized score and optional raw value for one
    data-quality dimension at a specific scope (global, schema, table, or
    column) within a pipeline run.

    Attributes:
        run_id: Unique identifier of the pipeline run that produced this metric.
        dimension: The data-quality dimension being measured, e.g.
            ``"completeness"``, ``"validity"``, ``"uniqueness"``.
        score: Normalized quality score in the range [0.0, 1.0] where 1.0
            represents perfect quality.
        schema_name: Schema scope; ``None`` for global metrics.
        table_name: Table scope; ``None`` for schema- or global-level metrics.
        column_name: Column scope; ``None`` for table- or higher-level metrics.
        value: Raw measured value (e.g. null ratio = 0.07, distinct count = 42).
            ``None`` when no raw value is applicable.
        metadata: Arbitrary key/value pairs for context, such as thresholds
            applied or sample size used.

    Example::

        metric = DQMetric(
            run_id="run-001",
            dimension="completeness",
            score=0.93,
            table_name="customers",
            column_name="email",
            value=0.07,
            metadata={"threshold": 0.95, "sample_rows": 10000},
        )
    """

    run_id: str
    score: float
    dimension: DQDimension | None = None
    metric_name: str | None = None
    schema_name: str | None = None
    table_name: str | None = None
    column_name: str | None = None
    value: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Enforce the dimension/metric-name split.

        Raises:
            ValueError: If both or neither of ``dimension`` and
                ``metric_name`` are set, or if ``dimension`` is outside the
                closed set in ``docs/CONVENTIONS-DQT.md`` section 0.1.

        Example:
            DQMetric(run_id="r", score=1.0, metric_name="row_count")
        """
        if (self.dimension is None) == (self.metric_name is None):
            raise ValueError(
                "a DQMetric carries exactly one of dimension or metric_name: "
                "a quality judgement or a raw measurement, never both and never "
                f"neither. Got dimension={self.dimension!r}, "
                f"metric_name={self.metric_name!r}."
            )
        if self.dimension is not None and self.dimension not in get_args_of_dq_dimension():
            raise ValueError(
                f"dimension {self.dimension!r} is not one of the six in "
                f"CONVENTIONS-DQT.md section 0.1: "
                f"{sorted(get_args_of_dq_dimension())}. Adding a seventh means "
                "editing that section first."
            )


@dataclass
class DQIssue:
    """A single data-quality issue detected during a pipeline run.

    A ``DQIssue`` records one violation or anomaly found in the data, scoped
    to a specific schema/table/column.  It carries enough evidence for a DBA
    to diagnose and act on the problem.

    Attributes:
        issue_id: Unique identifier for this issue (e.g. a UUID).
        run_id: Identifier of the pipeline run that raised this issue.
        dimension: Data-quality dimension violated, e.g. ``"validity"``,
            ``"uniqueness"``, ``"completeness"``.
        severity: One of ``"info"``, ``"warning"``, ``"error"``, ``"critical"``.
        message: Human-readable description of the issue.
        evidence: Structured evidence supporting the issue, e.g.
            ``{"sample_values": ["", None, "N/A"], "null_count": 312}``.
        schema_name: Schema where the issue was found; ``None`` if global.
        table_name: Table where the issue was found; ``None`` if schema-level.
        column_name: Column where the issue was found; ``None`` if table-level.
        rule_name: Name of the rule that triggered this issue, or ``None`` if
            the issue was raised by a diagnostic (not a rule).

    Example::

        issue = DQIssue(
            issue_id="iss-0042",
            run_id="run-001",
            dimension="validity",
            severity="error",
            message="Column 'email' contains 312 values that are not valid e-mail addresses.",
            evidence={"invalid_count": 312, "sample": ["notanemail", "foo@"]},
            table_name="customers",
            column_name="email",
            rule_name="email_format_check",
        )
    """

    issue_id: str
    run_id: str
    dimension: str
    severity: IssueSeverity
    message: str
    evidence: dict[str, Any] = field(default_factory=dict)
    schema_name: str | None = None
    table_name: str | None = None
    column_name: str | None = None
    rule_name: str | None = None


@dataclass
class ColumnResult:
    """Data-quality result for a single column.

    Aggregates all metrics and issues found for one column during a pipeline
    run, together with its database type and optional semantic classification.

    Attributes:
        schema_name: Name of the schema containing the column's table.
        table_name: Name of the table containing the column.
        column_name: Name of the column.
        db_type: Database-reported column type, e.g. ``"VARCHAR(255)"``,
            ``"INT"``, ``"TIMESTAMP"``.

            .. note::
                The design document names this field ``type``.  It is stored
                here as ``db_type`` to avoid shadowing the Python built-in
                ``type``.  All serialization layers MUST map ``db_type``
                back to ``"type"`` in external representations (JSON, reports).

        semantic_type: Optional semantic classification assigned by the
            classification module, e.g. ``"email"``, ``"phone"``, ``"iban"``,
            ``"national_id"``.  ``None`` if classification has not run or
            produced no result for this column.
        metrics: List of :class:`DQMetric` instances scoped to this column.
        issues: List of :class:`DQIssue` instances scoped to this column.

    Example::

        col = ColumnResult(
            schema_name="public",
            table_name="customers",
            column_name="email",
            db_type="VARCHAR(255)",
            semantic_type="email",
            metrics=[DQMetric(run_id="run-001", dimension="completeness", score=0.99)],
            issues=[],
        )
    """

    schema_name: str
    table_name: str
    column_name: str
    db_type: str
    semantic_type: str | None = None
    metrics: list[DQMetric] = field(default_factory=list)
    issues: list[DQIssue] = field(default_factory=list)


@dataclass
class TableResult:
    """Data-quality result for a single database table.

    Aggregates column-level results, table-level metrics (e.g. row count,
    FK integrity), and table-scoped issues.

    Attributes:
        schema_name: Name of the schema containing this table.
        table_name: Name of the table.
        columns: Ordered list of :class:`ColumnResult` for every profiled
            column in this table.
        metrics: Table-level :class:`DQMetric` instances, e.g. row count,
            overall completeness score, FK violation count.
        issues: Table-scoped :class:`DQIssue` instances, e.g. duplicate
            primary-key rows, orphaned FK rows.

    Example::

        tbl = TableResult(
            schema_name="public",
            table_name="orders",
            columns=[],
            metrics=[DQMetric(run_id="run-001", dimension="uniqueness", score=1.0)],
            issues=[],
        )
    """

    schema_name: str
    table_name: str
    columns: list[ColumnResult] = field(default_factory=list)
    metrics: list[DQMetric] = field(default_factory=list)
    issues: list[DQIssue] = field(default_factory=list)


@dataclass
class SchemaResult:
    """Data-quality summary for a database schema.

    Holds references to all tables profiled within the schema and any
    schema-level metrics or issues (e.g. cross-table consistency checks).

    Attributes:
        schema_name: Name of the schema (e.g. ``"public"``, ``"dbo"``).
        tables: Names of all tables discovered and profiled within this schema.
        metrics: Schema-level :class:`DQMetric` instances.
        issues: Schema-level :class:`DQIssue` instances.

    Example::

        schema = SchemaResult(
            schema_name="public",
            tables=["customers", "orders", "products"],
            metrics=[],
            issues=[],
        )
    """

    schema_name: str
    tables: list[str] = field(default_factory=list)
    metrics: list[DQMetric] = field(default_factory=list)
    issues: list[DQIssue] = field(default_factory=list)


@dataclass
class RuleResult:
    """Outcome of evaluating one rule against one specific target.

    A ``RuleResult`` is produced per (rule, table) or per (rule, column)
    combination.  Use :class:`RuleRunResult` for the aggregated summary
    across all targets of a rule.

    Attributes:
        run_id: Pipeline run that evaluated this rule.
        rule_name: Name of the rule that was evaluated.
        status: ``"pass"`` if the rule passed, ``"fail"`` if it found
            violations, ``"error"`` if evaluation itself failed.
        schema_name: Schema of the evaluated target; ``None`` if not applicable.
        table_name: Table of the evaluated target; ``None`` if not applicable.
        column_name: Column of the evaluated target; ``None`` if table-level.
        details: Optional explanation of the result (e.g. count of failing
            rows, error message on ``"error"`` status).

    Example::

        result = RuleResult(
            run_id="run-001",
            rule_name="email_format_check",
            status="fail",
            table_name="customers",
            column_name="email",
            details="312 rows failed the regex pattern check.",
        )
    """

    run_id: str
    rule_name: str
    status: RuleStatus
    schema_name: str | None = None
    table_name: str | None = None
    column_name: str | None = None
    details: str | None = None


@dataclass
class RuleRunResult:
    """Aggregated summary of one rule's evaluation across all its targets.

    After evaluating a rule against all matching tables/columns, the pipeline
    produces one ``RuleRunResult`` summarizing how many targets passed, failed,
    or errored.

    Attributes:
        run_id: Pipeline run that evaluated this rule.
        rule_name: Name of the rule.
        targets_checked: Total number of table/column targets evaluated.
        targets_failed: Number of targets where the rule reported ``"fail"``.
        targets_error: Number of targets where evaluation itself failed.

    Example::

        summary = RuleRunResult(
            run_id="run-001",
            rule_name="not_null_email",
            targets_checked=3,
            targets_failed=1,
            targets_error=0,
        )
    """

    run_id: str
    rule_name: str
    targets_checked: int
    targets_failed: int
    targets_error: int


@dataclass
class PipelineResult:
    """Complete outcome of one DQT data-quality pipeline run.

    ``PipelineResult`` is the top-level container produced by
    :class:`dqt.pipeline.DQTPipeline`.  All downstream consumers — storage,
    reports, UI, and bridges — work from this single object.

    Attributes:
        run_id: Unique identifier for this run (e.g. a UUID or timestamp slug).
        connection_id: Identifier of the :class:`ConnectionConfig` used.
        started_at: UTC datetime when the run began.
        ended_at: UTC datetime when the run completed (success or failure).
        status: Overall run outcome: ``"success"``, ``"failed"``, or
            ``"partial"`` (some stages completed, some failed).
        schemas: One :class:`SchemaResult` per schema discovered and profiled.
        tables: All :class:`TableResult` objects keyed by
            ``"<schema_name>.<table_name>"``.
        metrics: Global cross-table metrics for this run.
        issues: Global list of all issues across every schema/table/column.
        rules_run: One :class:`RuleRunResult` per rule evaluated during the run.
        stage_errors: Stages that did not complete. Empty on a clean run;
            non-empty is what makes ``status`` other than ``"success"``
            explainable rather than merely reported.
        external_analyses: Results from optional external analyzers, keyed by
            tool name (e.g. ``{"missingly": {"public.customers": <report>}}``).
            DQT core never populates this; only bridge modules write here.

    Example::

        result = PipelineResult(
            run_id="run-20260703-001",
            connection_id="pg-prod",
            started_at=datetime(2026, 7, 3, 10, 0, 0),
            ended_at=datetime(2026, 7, 3, 10, 4, 23),
            status="success",
        )
    """

    run_id: str
    connection_id: str
    started_at: datetime
    ended_at: datetime
    status: RunStatus
    schemas: list[SchemaResult] = field(default_factory=list)
    tables: dict[str, TableResult] = field(default_factory=dict)
    metrics: list[DQMetric] = field(default_factory=list)
    issues: list[DQIssue] = field(default_factory=list)
    rules_run: list[RuleRunResult] = field(default_factory=list)
    dqt_version: str = ""
    external_analyses: dict[str, dict[str, Any]] = field(default_factory=dict)
    stage_errors: list[StageError] = field(default_factory=list)


# ===========================================================================
# SECTION 2 — Domain Object: Rule (references RuleScope from config section)
# ===========================================================================


@dataclass
class Rule:
    r"""A declarative data-quality rule.

    A ``Rule`` defines a check to be evaluated against one or more
    table/column targets.  Rules are loaded from YAML/JSON via
    :class:`RuleConfig` and converted to ``Rule`` instances by the rules
    engine.

    Attributes:
        name: Unique rule identifier (e.g. ``"not_null_email"``).
        dimension: Data-quality dimension this rule tests, e.g.
            ``"validity"``, ``"completeness"``, ``"uniqueness"``.
        severity: Default severity of issues raised when this rule fails.
            One of ``"info"``, ``"warning"``, ``"error"``, ``"critical"``.
        scope: A :class:`RuleScope` defining which tables/columns the rule
            applies to.
        expression: A DSL keyword or SQL fragment defining the check, e.g.
            ``"NOT NULL"`` or ``"value ~ '^[^@]+@[^@]+$'"``.
        params: Arbitrary additional parameters passed to the rule evaluator,
            e.g. ``{"pattern": "^[^@]+@[^@]+$", "min": 0}``.

    Example::

        rule = Rule(
            name="email_format_check",
            dimension="validity",
            severity="error",
            scope=RuleScope(table_pattern="customers", column_pattern="email"),
            expression="regex",
            params={"pattern": r"^[^@\s]+@[^@\s]+\.[^@\s]+$"},
        )
    """

    name: str
    dimension: str
    severity: IssueSeverity
    scope: RuleScope
    expression: str
    params: dict[str, Any] = field(default_factory=dict)


# ===========================================================================
# SECTION 3 — Config Models (Pydantic)
# ===========================================================================


class SamplingConfig(BaseModel):
    """Configuration for table sampling used during profiling and bridges.

    When profiling large tables or when calling external analyzers (e.g.
    ``missingly``), DQT can sample rows instead of scanning full tables.
    This model defines the sampling strategy and limits.

    Attributes:
        strategy: Sampling method.  ``"random"`` uses ``TABLESAMPLE`` or
            ``ORDER BY RANDOM()``; ``"first_n"`` takes the first ``limit``
            rows via ``LIMIT``.  Defaults to ``"random"``.
        limit: Maximum number of rows to sample.  Must be a positive integer.
            Defaults to ``10_000``.
        seed: Optional random seed for reproducible sampling.  Only used
            when ``strategy`` is ``"random"``.

    Example::

        cfg = SamplingConfig(strategy="random", limit=5000, seed=42)
    """

    strategy: Literal["random", "first_n"] = "random"
    limit: int = Field(default=10_000, gt=0, description="Maximum rows to sample.")
    seed: int | None = Field(default=None, description="Random seed for reproducibility.")


class RuleScope(BaseModel):
    """Defines the target scope for a data-quality rule.

    A ``RuleScope`` specifies which schemas, tables, and columns a rule
    applies to, using exact names or glob-style patterns.  All fields are
    optional; omitting a field means "match all".

    Attributes:
        schema_pattern: Glob pattern for schema names, e.g. ``"public"``
            or ``"dbo_*"``.  ``None`` matches all schemas.
        table_pattern: Glob pattern for table names, e.g. ``"customer*"``.
            ``None`` matches all tables.
        column_pattern: Glob pattern for column names, e.g. ``"*_email"``.
            ``None`` matches all columns.

    Example::

        scope = RuleScope(table_pattern="customers", column_pattern="email")
    """

    schema_pattern: str | None = None
    table_pattern: str | None = None
    column_pattern: str | None = None


class ConnectionConfig(BaseModel):
    """Configuration for a database connection.

    ``ConnectionConfig`` is validated before any pipeline run.  Credentials
    MUST NOT appear in reports, logs, or UI artifacts.  DQT should operate
    with a read-only database role wherever possible.

    Attributes:
        id: Unique identifier for this connection (e.g. ``"pg-prod"``).
            Used to cross-reference runs.
        dsn: Database connection string.  May reference environment variables
            using ``${VAR_NAME}`` notation; expansion is handled by the
            connection layer, not this model.
        read_only: Whether DQT should enforce a read-only session.  Strongly
            recommended to be ``True`` in production.  Defaults to ``True``.
        ssl: Optional SSL/TLS parameters passed to the DB driver, e.g.
            ``{"sslmode": "require", "sslrootcert": "/path/to/ca.pem"}``.

    Example::

        conn = ConnectionConfig(
            id="pg-prod",
            dsn="${PROD_DB_DSN}",
            read_only=True,
            ssl={"sslmode": "require"},
        )
    """

    id: str = Field(..., min_length=1, description="Unique connection identifier.")
    dsn: str = Field(..., min_length=1, description="Database DSN; may use ${ENV_VAR} expansion.")
    read_only: bool = Field(default=True, description="Enforce read-only session.")
    ssl: dict[str, Any] | None = Field(default=None, description="SSL/TLS driver options.")

    @field_validator("dsn")
    @classmethod
    def dsn_must_not_be_empty(cls, v: str) -> str:
        """Reject blank or whitespace-only DSNs.

        A blank DSN fails later, inside a driver, with a message about the
        driver rather than about the config -- so it is refused here, where
        the field it came from can be named.

        Args:
            v: The DSN as written in the config.

        Returns:
            The DSN unchanged.

        Raises:
            ValueError: If the DSN is empty or only whitespace.

        Example:
            ConnectionConfig(id="c", dsn="sqlite:///dev.db")
        """
        if not v.strip():
            raise ValueError("dsn must not be blank; use a valid connection string or ${ENV_VAR}.")
        return v


class DQPipelineConfig(BaseModel):
    """Configuration for a DQT pipeline run.

    Defines which schemas/tables to include or exclude, optional sampling,
    metric thresholds, and rule file paths.  Validated by Pydantic before the
    pipeline starts.

    Attributes:
        connection_id: Must match the ``id`` of a :class:`ConnectionConfig`.
        include_schemas: If set, only these schema names are profiled.
        exclude_schemas: Schema names to skip.  Applied after ``include_schemas``.
        include_tables: If set, only these table names (unqualified) are profiled.
        exclude_tables: Table names to skip.
        sampling: Optional :class:`SamplingConfig` for large-table sampling.
        metric_thresholds: Minimum acceptable score per dimension, e.g.
            ``{"completeness": 0.95, "validity": 0.99}``.  Scores below
            threshold will raise issues.
        rule_files: Paths to YAML or JSON files containing rule definitions.
            Processed in order; later files can override earlier ones.

    Example::

        cfg = DQPipelineConfig(
            connection_id="pg-prod",
            include_schemas=["public"],
            exclude_tables=["audit_log"],
            metric_thresholds={"completeness": 0.95},
            rule_files=["rules/base.yaml", "rules/project_specific.yaml"],
        )
    """

    connection_id: str = Field(..., min_length=1)
    include_schemas: list[str] | None = None
    exclude_schemas: list[str] | None = None
    include_tables: list[str] | None = None
    exclude_tables: list[str] | None = None
    sampling: SamplingConfig | None = None
    metric_thresholds: dict[str, float] | None = None
    rule_files: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_no_overlap_in_include_exclude(self) -> DQPipelineConfig:
        """Refuse a config that both includes and excludes the same name.

        Whichever way DQT resolved the contradiction, half the readers of the
        config would be surprised -- and a table silently skipped is the
        expensive half of that guess.

        Returns:
            The validated config.

        Raises:
            ValueError: If any schema or table name appears in both lists.

        Example:
            DQPipelineConfig(connection_id="c", include_tables=["orders"])
        """
        for attr in ("schemas", "tables"):
            inc: list[str] | None = getattr(self, f"include_{attr}")
            exc: list[str] | None = getattr(self, f"exclude_{attr}")
            if inc and exc:
                overlap = set(inc) & set(exc)
                if overlap:
                    raise ValueError(
                        f"The same {attr} name(s) appear in both "
                        f"include_{attr} and exclude_{attr}: {sorted(overlap)}."
                    )
        return self

    @field_validator("metric_thresholds")
    @classmethod
    def thresholds_must_be_in_range(cls, v: dict[str, float] | None) -> dict[str, float] | None:
        """Refuse thresholds outside the range scores can take.

        Metric scores are normalised to ``[0, 1]``, so a threshold of ``95``
        can never be met and one of ``-1`` can never be missed. Both are
        almost always a percentage written where a fraction was meant.

        Args:
            v: The threshold mapping, or None when none was given.

        Returns:
            The mapping unchanged, or None.

        Raises:
            ValueError: If any threshold falls outside ``[0.0, 1.0]``.

        Example:
            DQPipelineConfig(connection_id="c", metric_thresholds={"completeness": 0.95})
        """
        if v is None:
            return v
        out_of_range = {k: val for k, val in v.items() if not (0.0 <= val <= 1.0)}
        if out_of_range:
            raise ValueError(
                f"metric_thresholds values must be in [0.0, 1.0]. "
                f"Out-of-range entries: {out_of_range}."
            )
        return v


class RuleConfig(BaseModel):
    """Declarative configuration for a single data-quality rule.

    ``RuleConfig`` is the serializable form of a :class:`Rule` as it appears
    in YAML/JSON rule files.  The rules engine converts ``RuleConfig``
    instances into ``Rule`` domain objects before evaluation.

    Attributes:
        name: Unique rule name.  Must be a non-empty slug (no spaces).
        dimension: Data-quality dimension this rule tests.
        severity: Default issue severity when this rule fails.
        scope: :class:`RuleScope` specifying target schemas/tables/columns.
        expression: DSL keyword or SQL fragment for the check logic.
        params: Additional parameters forwarded to the rule evaluator.

    Example::

        cfg = RuleConfig(
            name="not_null_order_id",
            dimension="completeness",
            severity="critical",
            scope=RuleScope(table_pattern="orders", column_pattern="order_id"),
            expression="NOT NULL",
            params={},
        )
    """

    name: str = Field(..., min_length=1, description="Unique rule identifier.")
    dimension: str = Field(..., min_length=1)
    severity: IssueSeverity
    scope: RuleScope
    expression: str = Field(..., min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def name_must_be_slug(cls, v: str) -> str:
        """Refuse rule names containing spaces.

        A rule name is an identifier: it appears in issue records, in the
        rules screen's URLs, and in CLI output. A space survives none of
        those cleanly.

        Args:
            v: The rule name as written in the config.

        Returns:
            The name unchanged.

        Raises:
            ValueError: If the name contains a space.

        Example:
            RuleConfig(name="not-null-email", ...)
        """
        if " " in v:
            raise ValueError(
                f"Rule name '{v}' must not contain spaces. Use underscores or hyphens instead."
            )
        return v

    @field_validator("params")
    @classmethod
    def range_bounds_must_be_numeric(cls, v: dict[str, Any]) -> dict[str, Any]:
        """Reject non-numeric ``params.min`` / ``params.max`` values.

        The ``range`` rule expression (:mod:`dqt.sql.rules`) binds these
        values as DBAPI query parameters. Rejecting a non-numeric value here,
        before the config ever reaches the query builder, is defense in
        depth alongside parameterization: a string payload cannot reach the
        SQL layer through this field even if a call site were to bind it
        incorrectly.

        Args:
            v: The rule's params mapping.

        Returns:
            The mapping unchanged.

        Raises:
            ValueError: If ``params.min`` or ``params.max`` is present and
                is not a number.

        Example:
            RuleConfig(name="age", expression="RANGE", params={"min": 0, "max": 120}, ...)
        """
        for key in ("min", "max"):
            if key not in v:
                continue
            bound = v[key]
            if isinstance(bound, bool) or not isinstance(bound, int | float):
                raise ValueError(
                    f"RuleConfig.params[{key!r}] must be an int or float, "
                    f"got {type(bound).__name__}."
                )
        return v


# ---------------------------------------------------------------------------
# Public re-exports  (consumed by dqt/__init__.py)
# ---------------------------------------------------------------------------

__all__ = [
    # Literals
    "RunStatus",
    "IssueSeverity",
    "RuleStatus",
    # Domain objects
    "DQMetric",
    "DQIssue",
    "ColumnResult",
    "TableResult",
    "SchemaResult",
    "Rule",
    "RuleResult",
    "RuleRunResult",
    "PipelineResult",
    # Config models
    "SamplingConfig",
    "RuleScope",
    "ConnectionConfig",
    "DQPipelineConfig",
    "RuleConfig",
]
