"""Unit tests for dqt.common.models.

Covers all domain objects (dataclasses) and config models (Pydantic).
No DB connections or I/O; pure in-memory construction and validation.
"""

import typing
from datetime import datetime

import pytest
from pydantic import ValidationError

from dqt.common.models import (
    DQDimension,
    get_args_of_dq_dimension,
    ColumnResult,
    ConnectionConfig,
    DQIssue,
    DQMetric,
    DQPipelineConfig,
    PipelineResult,
    Rule,
    RuleConfig,
    RuleResult,
    RuleRunResult,
    RuleScope,
    SamplingConfig,
    SchemaResult,
    TableResult,
)

# ===========================================================================
# Helpers
# ===========================================================================


def make_metric(**kwargs: object) -> DQMetric:
    """Return a minimal valid DQMetric."""
    defaults = {"run_id": "run-001", "dimension": "completeness", "score": 1.0}
    defaults.update(kwargs)  # type: ignore[arg-type]
    return DQMetric(**defaults)  # type: ignore[arg-type]


def make_issue(**kwargs: object) -> DQIssue:
    """Return a minimal valid DQIssue."""
    defaults = {
        "issue_id": "iss-001",
        "run_id": "run-001",
        "dimension": "validity",
        "severity": "error",
        "message": "test issue",
    }
    defaults.update(kwargs)  # type: ignore[arg-type]
    return DQIssue(**defaults)  # type: ignore[arg-type]


# ===========================================================================
# DQMetric
# ===========================================================================


class TestDQMetric:
    def test_minimal_construction(self) -> None:
        m = make_metric()
        assert m.run_id == "run-001"
        assert m.dimension == "completeness"
        assert m.score == 1.0
        assert m.schema_name is None
        assert m.table_name is None
        assert m.column_name is None
        assert m.value is None
        assert m.metadata == {}

    def test_full_construction(self) -> None:
        m = make_metric(
            schema_name="public",
            table_name="customers",
            column_name="email",
            value=0.07,
            metadata={"threshold": 0.95},
        )
        assert m.schema_name == "public"
        assert m.table_name == "customers"
        assert m.column_name == "email"
        assert m.value == 0.07
        assert m.metadata == {"threshold": 0.95}

    def test_metadata_defaults_to_empty_dict(self) -> None:
        m1 = make_metric()
        m2 = make_metric()
        # Each instance must have its own dict (no shared mutable default)
        m1.metadata["key"] = "val"
        assert "key" not in m2.metadata


# ===========================================================================
# DQIssue
# ===========================================================================


class TestDQIssue:
    def test_minimal_construction(self) -> None:
        i = make_issue()
        assert i.issue_id == "iss-001"
        assert i.severity == "error"
        assert i.rule_name is None
        assert i.evidence == {}

    def test_with_rule_name_and_evidence(self) -> None:
        i = make_issue(
            rule_name="email_check",
            evidence={"invalid_count": 5},
            table_name="customers",
            column_name="email",
        )
        assert i.rule_name == "email_check"
        assert i.evidence["invalid_count"] == 5
        assert i.table_name == "customers"

    def test_all_severity_literals(self) -> None:
        for sev in ("info", "warning", "error", "critical"):
            i = make_issue(severity=sev)
            assert i.severity == sev

    def test_evidence_defaults_to_empty_dict(self) -> None:
        i1 = make_issue()
        i2 = make_issue()
        i1.evidence["x"] = 1
        assert "x" not in i2.evidence


# ===========================================================================
# ColumnResult
# ===========================================================================


class TestColumnResult:
    def test_construction(self) -> None:
        col = ColumnResult(
            schema_name="public",
            table_name="customers",
            column_name="email",
            db_type="VARCHAR(255)",
            semantic_type="email",
        )
        assert col.db_type == "VARCHAR(255)"
        assert col.semantic_type == "email"
        assert col.metrics == []
        assert col.issues == []

    def test_semantic_type_defaults_none(self) -> None:
        col = ColumnResult(
            schema_name="public",
            table_name="t",
            column_name="c",
            db_type="INT",
        )
        assert col.semantic_type is None

    def test_lists_are_independent(self) -> None:
        col1 = ColumnResult(schema_name="s", table_name="t", column_name="c", db_type="INT")
        col2 = ColumnResult(schema_name="s", table_name="t", column_name="c", db_type="INT")
        col1.metrics.append(make_metric())
        assert col2.metrics == []


# ===========================================================================
# TableResult
# ===========================================================================


class TestTableResult:
    def test_construction(self) -> None:
        tbl = TableResult(schema_name="public", table_name="orders")
        assert tbl.columns == []
        assert tbl.metrics == []
        assert tbl.issues == []

    def test_with_columns(self) -> None:
        col = ColumnResult(
            schema_name="public", table_name="orders", column_name="id", db_type="INT"
        )
        tbl = TableResult(schema_name="public", table_name="orders", columns=[col])
        assert len(tbl.columns) == 1
        assert tbl.columns[0].column_name == "id"


# ===========================================================================
# SchemaResult
# ===========================================================================


class TestSchemaResult:
    def test_construction(self) -> None:
        s = SchemaResult(schema_name="public", tables=["customers", "orders"])
        assert s.schema_name == "public"
        assert "customers" in s.tables
        assert s.metrics == []
        assert s.issues == []


# ===========================================================================
# RuleResult
# ===========================================================================


class TestRuleResult:
    def test_pass(self) -> None:
        r = RuleResult(run_id="run-001", rule_name="not_null", status="pass")
        assert r.status == "pass"
        assert r.details is None

    def test_fail_with_details(self) -> None:
        r = RuleResult(
            run_id="run-001",
            rule_name="email_check",
            status="fail",
            table_name="customers",
            column_name="email",
            details="312 rows failed.",
        )
        assert r.status == "fail"
        assert r.details == "312 rows failed."

    def test_all_status_literals(self) -> None:
        for status in ("pass", "fail", "error"):
            r = RuleResult(run_id="r", rule_name="rule", status=status)  # type: ignore[arg-type]
            assert r.status == status


# ===========================================================================
# RuleRunResult
# ===========================================================================


class TestRuleRunResult:
    def test_construction(self) -> None:
        rr = RuleRunResult(
            run_id="run-001",
            rule_name="not_null_email",
            targets_checked=5,
            targets_failed=2,
            targets_error=0,
        )
        assert rr.targets_checked == 5
        assert rr.targets_failed == 2
        assert rr.targets_error == 0


# ===========================================================================
# PipelineResult
# ===========================================================================


class TestPipelineResult:
    def _make(self, **kwargs: object) -> PipelineResult:
        defaults: dict[str, object] = {
            "run_id": "run-001",
            "connection_id": "pg-prod",
            "started_at": datetime(2026, 7, 3, 10, 0, 0),
            "ended_at": datetime(2026, 7, 3, 10, 4, 0),
            "status": "success",
        }
        defaults.update(kwargs)
        return PipelineResult(**defaults)  # type: ignore[arg-type]

    def test_minimal_construction(self) -> None:
        r = self._make()
        assert r.run_id == "run-001"
        assert r.status == "success"
        assert r.schemas == []
        assert r.tables == {}
        assert r.metrics == []
        assert r.issues == []
        assert r.rules_run == []
        assert r.external_analyses == {}

    def test_all_status_literals(self) -> None:
        for status in ("success", "failed", "partial"):
            r = self._make(status=status)
            assert r.status == status

    def test_external_analyses_not_shared(self) -> None:
        r1 = self._make()
        r2 = self._make()
        r1.external_analyses["missingly"] = {}
        assert "missingly" not in r2.external_analyses

    def test_tables_keyed_by_schema_dot_table(self) -> None:
        tbl = TableResult(schema_name="public", table_name="customers")
        r = self._make(tables={"public.customers": tbl})
        assert "public.customers" in r.tables


# ===========================================================================
# SamplingConfig (Pydantic)
# ===========================================================================


class TestSamplingConfig:
    def test_defaults(self) -> None:
        cfg = SamplingConfig()
        assert cfg.strategy == "random"
        assert cfg.limit == 10_000
        assert cfg.seed is None

    def test_custom(self) -> None:
        cfg = SamplingConfig(strategy="first_n", limit=500, seed=42)
        assert cfg.strategy == "first_n"
        assert cfg.limit == 500
        assert cfg.seed == 42

    def test_limit_must_be_positive(self) -> None:
        with pytest.raises(ValidationError, match="greater than 0"):
            SamplingConfig(limit=0)

    def test_invalid_strategy(self) -> None:
        with pytest.raises(ValidationError):
            SamplingConfig(strategy="invalid")  # type: ignore[arg-type]


# ===========================================================================
# RuleScope (Pydantic)
# ===========================================================================


class TestRuleScope:
    def test_all_none_by_default(self) -> None:
        s = RuleScope()
        assert s.schema_pattern is None
        assert s.table_pattern is None
        assert s.column_pattern is None

    def test_partial(self) -> None:
        s = RuleScope(table_pattern="customers", column_pattern="email")
        assert s.table_pattern == "customers"
        assert s.schema_pattern is None


# ===========================================================================
# ConnectionConfig (Pydantic)
# ===========================================================================


class TestConnectionConfig:
    def test_valid(self) -> None:
        cfg = ConnectionConfig(id="pg-prod", dsn="postgresql://localhost/mydb")
        assert cfg.id == "pg-prod"
        assert cfg.read_only is True  # default
        assert cfg.ssl is None

    def test_read_only_false(self) -> None:
        cfg = ConnectionConfig(id="pg-dev", dsn="postgresql://localhost/dev", read_only=False)
        assert cfg.read_only is False

    def test_dsn_blank_raises(self) -> None:
        with pytest.raises(ValidationError, match="dsn must not be blank"):
            ConnectionConfig(id="x", dsn="   ")

    def test_dsn_empty_string_raises(self) -> None:
        with pytest.raises(ValidationError):
            ConnectionConfig(id="x", dsn="")

    def test_ssl_options(self) -> None:
        cfg = ConnectionConfig(
            id="pg-prod", dsn="postgresql://localhost/db", ssl={"sslmode": "require"}
        )
        assert cfg.ssl == {"sslmode": "require"}

    def test_id_empty_raises(self) -> None:
        with pytest.raises(ValidationError):
            ConnectionConfig(id="", dsn="postgresql://localhost/db")


# ===========================================================================
# DQPipelineConfig (Pydantic)
# ===========================================================================


class TestDQPipelineConfig:
    def test_minimal(self) -> None:
        cfg = DQPipelineConfig(connection_id="pg-prod")
        assert cfg.connection_id == "pg-prod"
        assert cfg.include_schemas is None
        assert cfg.rule_files == []

    def test_include_exclude_overlap_schemas_raises(self) -> None:
        with pytest.raises(ValidationError, match="include_schemas and exclude_schemas"):
            DQPipelineConfig(
                connection_id="pg",
                include_schemas=["public", "staging"],
                exclude_schemas=["staging"],
            )

    def test_include_exclude_overlap_tables_raises(self) -> None:
        with pytest.raises(ValidationError, match="include_tables and exclude_tables"):
            DQPipelineConfig(
                connection_id="pg",
                include_tables=["orders"],
                exclude_tables=["orders"],
            )

    def test_no_overlap_passes(self) -> None:
        cfg = DQPipelineConfig(
            connection_id="pg",
            include_schemas=["public"],
            exclude_schemas=["internal"],
        )
        assert cfg.include_schemas == ["public"]

    def test_threshold_out_of_range_raises(self) -> None:
        with pytest.raises(ValidationError, match="\\[0.0, 1.0\\]"):
            DQPipelineConfig(
                connection_id="pg",
                metric_thresholds={"completeness": 1.5},
            )

    def test_threshold_valid(self) -> None:
        cfg = DQPipelineConfig(
            connection_id="pg",
            metric_thresholds={"completeness": 0.95, "validity": 1.0},
        )
        assert cfg.metric_thresholds == {"completeness": 0.95, "validity": 1.0}

    def test_sampling_nested(self) -> None:
        cfg = DQPipelineConfig(
            connection_id="pg",
            sampling=SamplingConfig(limit=5000, seed=7),
        )
        assert cfg.sampling is not None
        assert cfg.sampling.limit == 5000


# ===========================================================================
# RuleConfig (Pydantic)
# ===========================================================================


class TestRuleConfig:
    def test_valid(self) -> None:
        cfg = RuleConfig(
            name="not_null_email",
            dimension="completeness",
            severity="critical",
            scope=RuleScope(table_pattern="customers", column_pattern="email"),
            expression="NOT NULL",
        )
        assert cfg.name == "not_null_email"
        assert cfg.params == {}

    def test_name_with_space_raises(self) -> None:
        with pytest.raises(ValidationError, match="must not contain spaces"):
            RuleConfig(
                name="bad name",
                dimension="validity",
                severity="error",
                scope=RuleScope(),
                expression="NOT NULL",
            )

    def test_invalid_severity_raises(self) -> None:
        with pytest.raises(ValidationError):
            RuleConfig(
                name="rule1",
                dimension="validity",
                severity="blocker",  # type: ignore[arg-type]
                scope=RuleScope(),
                expression="NOT NULL",
            )

    def test_params_passed_through(self) -> None:
        cfg = RuleConfig(
            name="email_regex",
            dimension="validity",
            severity="error",
            scope=RuleScope(column_pattern="*email*"),
            expression="regex",
            params={"pattern": r"^[^@]+@[^@]+$"},
        )
        assert cfg.params["pattern"] == r"^[^@]+@[^@]+$"


# ===========================================================================
# Rule (dataclass — uses RuleScope from Pydantic)
# ===========================================================================


class TestRule:
    def test_construction(self) -> None:
        scope = RuleScope(table_pattern="customers", column_pattern="email")
        rule = Rule(
            name="email_format",
            dimension="validity",
            severity="error",
            scope=scope,
            expression="regex",
            params={"pattern": r"^[^@]+@[^@]+$"},
        )
        assert rule.name == "email_format"
        assert rule.scope.table_pattern == "customers"
        assert rule.params["pattern"] == r"^[^@]+@[^@]+$"

    def test_params_defaults_to_empty_dict(self) -> None:
        r1 = Rule(
            name="r1",
            dimension="completeness",
            severity="info",
            scope=RuleScope(),
            expression="NOT NULL",
        )
        r2 = Rule(
            name="r2",
            dimension="completeness",
            severity="info",
            scope=RuleScope(),
            expression="NOT NULL",
        )
        r1.params["x"] = 1
        assert "x" not in r2.params


# ---------------------------------------------------------------------------
# NEW-A: the dimension / metric-name split
# ---------------------------------------------------------------------------

CONVENTION_DIMENSIONS = {
    "completeness",
    "validity",
    "uniqueness",
    "consistency",
    "referential_integrity",
    "timeliness",
}


def test_dq_dimension_is_a_closed_literal() -> None:
    """The type admits exactly the six documented dimensions.

    Equality, not containment: a seventh value added to the code without
    editing the convention doc must fail here, and so must a sixth quietly
    dropped. A subset assertion would catch only half of that.
    """
    assert get_args_of_dq_dimension() == CONVENTION_DIMENSIONS


def test_a_quality_score_carries_a_dimension_and_no_metric_name() -> None:
    """Completeness is a dimension, so it goes in ``dimension``."""
    metric = DQMetric(
        run_id="run-001",
        dimension="completeness",
        score=0.6,
        table_name="customers",
        column_name="email",
        value=2.0,
    )

    assert metric.dimension == "completeness"
    assert metric.metric_name is None


def test_a_raw_measurement_carries_a_metric_name_and_no_dimension() -> None:
    """A row count is a measurement, not a judgement about quality.

    ``row_count`` has no meaningful score: 1.0 is written for it today purely
    because the field is required. Putting it in ``metric_name`` and leaving
    ``dimension`` empty is what stops it being averaged into a completeness
    figure by anything that groups on dimension.
    """
    metric = DQMetric(
        run_id="run-001",
        metric_name="row_count",
        score=1.0,
        table_name="customers",
        value=5.0,
    )

    assert metric.metric_name == "row_count"
    assert metric.dimension is None


def test_setting_both_is_rejected() -> None:
    """A metric is a dimension score or a measurement, never both.

    Allowing both would recreate the ambiguity this split exists to remove:
    a consumer would have to decide which field wins, and different consumers
    would decide differently.
    """
    with pytest.raises(ValueError, match="exactly one"):
        DQMetric(
            run_id="run-001",
            dimension="completeness",
            metric_name="row_count",
            score=1.0,
        )


def test_setting_neither_is_rejected() -> None:
    """A metric that is neither a dimension nor a named measurement is nothing.

    Without this guard the mutual-exclusivity rule would be satisfied by an
    empty metric, which is the degenerate case that makes such rules useless.
    """
    with pytest.raises(ValueError, match="exactly one"):
        DQMetric(run_id="run-001", score=1.0)


def test_an_unknown_dimension_is_rejected() -> None:
    """A value outside the closed set cannot be constructed.

    This is what makes §0.1 a specification rather than a description. Today
    ``dimension`` is a free-form ``str`` and ``"banana"`` is accepted in
    silence.
    """
    with pytest.raises(ValueError, match="banana|dimension"):
        DQMetric(run_id="run-001", dimension="banana", score=1.0)  # type: ignore[arg-type]


def test_the_literal_is_usable_for_static_checking() -> None:
    """``DQDimension`` is a real type, not a runtime-only tuple of strings.

    ``mypy --strict`` is a gate here, so the point of a Literal is that a bad
    dimension is caught before the code runs. If it were a plain ``str`` alias
    the runtime guard above would be the only line of defence.
    """
    assert typing.get_origin(DQDimension) is typing.Literal
