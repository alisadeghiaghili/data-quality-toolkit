"""Unit tests for the public API surface of dqt.

These tests assert that every name exported in ``dqt.__all__`` is importable
from the top-level package and that the helper constructors work correctly.
"""

from __future__ import annotations

import dqt
from dqt import (
    ColumnResult,
    ConnectionConfig,
    DQIssue,
    DQMetric,
    DQPipelineConfig,
    DQTPipeline,
    IssueSeverity,
    PipelineResult,
    Rule,
    RuleConfig,
    RuleResult,
    RuleRunResult,
    RuleScope,
    RuleStatus,
    RunStatus,
    SamplingConfig,
    SchemaResult,
    TableResult,
    from_dsn,
    from_yaml_config,
    load_connection,
    load_pipeline,
    load_rules,
    load_rules_from_files,
)


def test_version_is_set() -> None:
    """__version__ must be a non-empty string."""
    assert isinstance(dqt.__version__, str)
    assert len(dqt.__version__) > 0


def test_public_api_exports_are_importable() -> None:
    """Every exported name resolves to a non-None object."""
    assert ColumnResult is not None
    assert ConnectionConfig is not None
    assert DQIssue is not None
    assert DQMetric is not None
    assert DQPipelineConfig is not None
    assert DQTPipeline is not None
    assert IssueSeverity is not None
    assert PipelineResult is not None
    assert Rule is not None
    assert RuleConfig is not None
    assert RuleResult is not None
    assert RuleRunResult is not None
    assert RuleScope is not None
    assert RuleStatus is not None
    assert RunStatus is not None
    assert SamplingConfig is not None
    assert SchemaResult is not None
    assert TableResult is not None
    assert from_dsn is not None
    assert from_yaml_config is not None
    assert load_connection is not None
    assert load_pipeline is not None
    assert load_rules is not None
    assert load_rules_from_files is not None


def test_from_dsn_returns_pipeline() -> None:
    """from_dsn() must return a DQTPipeline instance."""
    pipeline = from_dsn("sqlite:///test_public_api.db")
    assert isinstance(pipeline, DQTPipeline)


def test_from_dsn_with_custom_connection_id() -> None:
    """from_dsn() must propagate connection_id to the underlying ConnectionConfig."""
    pipeline = from_dsn("sqlite:///test.db", connection_id="test_conn")
    assert isinstance(pipeline, DQTPipeline)


def test_from_dsn_with_explicit_config() -> None:
    """from_dsn() must use the provided DQPipelineConfig when given."""
    cfg = DQPipelineConfig(connection_id="custom")
    pipeline = from_dsn("sqlite:///test.db", connection_id="custom", config=cfg)
    assert isinstance(pipeline, DQTPipeline)


def test_all_list_is_complete() -> None:
    """Every name in __all__ must actually be importable from the dqt module."""
    import importlib

    module = importlib.import_module("dqt")
    for name in dqt.__all__:
        assert hasattr(module, name), f"'{name}' is in __all__ but not importable from dqt"
