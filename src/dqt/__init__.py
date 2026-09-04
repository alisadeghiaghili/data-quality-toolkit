"""
dqt
===

Public API for DQT — SQL Data Quality Toolkit.

This module exposes the stable top-level API that DBA-facing consumers should
import directly from ``dqt`` instead of reaching into internal submodules.

Example::

    from dqt import DQTPipeline, from_dsn

    pipeline = from_dsn("sqlite:///example.db")
    result, report_path = pipeline.run()
"""

from __future__ import annotations

from pathlib import Path

from dqt.classification import (
    ClassificationResult,
    SemanticType,
    classify_column,
    classify_column_name,
    classify_value,
    normalize_persian_text,
)
from dqt.common.config_loader import (
    load_connection,
    load_pipeline,
    load_rules,
    load_rules_from_files,
)
from dqt.common.models import (
    # Domain objects
    ColumnResult,
    # Config models
    ConnectionConfig,
    DQIssue,
    DQMetric,
    DQPipelineConfig,
    # Literal types
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
)
from dqt.sql.pipeline import DQTPipeline

__version__ = "0.1.0.dev0"


def from_dsn(
    dsn: str,
    *,
    connection_id: str = "default",
    config: DQPipelineConfig | None = None,
) -> DQTPipeline:
    """Create a :class:`DQTPipeline` from a raw DSN string.

    Args:
        dsn: Database connection string (e.g. ``"sqlite:///dev.db"``).
        connection_id: Logical identifier stored in :class:`ConnectionConfig`.
        config: Optional pipeline config. A default config using
            ``connection_id`` is created when omitted.

    Returns:
        A configured :class:`DQTPipeline` ready to call ``.run()`` on.

    Example::

        pipeline = from_dsn("postgresql+psycopg2://user:pass@host/db")
        result, report = pipeline.run()
    """
    connection = ConnectionConfig(id=connection_id, dsn=dsn)
    pipeline_config = config or DQPipelineConfig(connection_id=connection_id)
    return DQTPipeline(connection, pipeline_config)


def from_yaml_config(path: str | Path) -> DQTPipeline:
    """Create a :class:`DQTPipeline` from a YAML or JSON config file.

    Loads both the connection config and the pipeline config from the same
    file using DQT's typed config loaders.

    Args:
        path: Path to a YAML or JSON configuration file containing at least
            ``connection`` and ``pipeline`` sections.

    Returns:
        A configured :class:`DQTPipeline` ready to call ``.run()`` on.

    Example::

        pipeline = from_yaml_config("dqt.pipeline.yaml")
        result, report = pipeline.run()
    """
    config_path = Path(path)
    connection = load_connection(config_path)
    pipeline_config = load_pipeline(config_path)
    return DQTPipeline(connection, pipeline_config)


__all__ = [
    "__version__",
    # Literal / enum types
    "IssueSeverity",
    "RuleStatus",
    "RunStatus",
    "SemanticType",
    # Domain objects
    "ClassificationResult",
    "ColumnResult",
    "DQIssue",
    "DQMetric",
    "DQTPipeline",
    "PipelineResult",
    "Rule",
    "RuleConfig",
    "RuleResult",
    "RuleRunResult",
    "RuleScope",
    "SamplingConfig",
    "SchemaResult",
    "TableResult",
    # Config models
    "ConnectionConfig",
    "DQPipelineConfig",
    # Classification facet
    "classify_column",
    "classify_column_name",
    "classify_value",
    "normalize_persian_text",
    # Helper constructors
    "from_dsn",
    "from_yaml_config",
    # Config loaders
    "load_connection",
    "load_pipeline",
    "load_rules",
    "load_rules_from_files",
]
