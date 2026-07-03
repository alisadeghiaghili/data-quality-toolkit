"""DQT — SQL Data Quality Toolkit.

Public API surface for DQT.  Import core classes from here.

Example::

    from dqt import (
        DQTPipeline,
        PipelineResult,
        DQMetric,
        DQIssue,
        ConnectionConfig,
        DQPipelineConfig,
    )
"""

from dqt.common.models import (
    # Literals
    IssueSeverity,
    RuleStatus,
    RunStatus,
    # Domain objects
    ColumnResult,
    DQIssue,
    DQMetric,
    PipelineResult,
    Rule,
    RuleResult,
    RuleRunResult,
    SchemaResult,
    TableResult,
    # Config models
    ConnectionConfig,
    DQPipelineConfig,
    RuleConfig,
    RuleScope,
    SamplingConfig,
)
from dqt.sql.pipeline import DQTPipeline

__all__ = [
    "RunStatus",
    "IssueSeverity",
    "RuleStatus",
    "DQMetric",
    "DQIssue",
    "ColumnResult",
    "TableResult",
    "SchemaResult",
    "Rule",
    "RuleResult",
    "RuleRunResult",
    "PipelineResult",
    "SamplingConfig",
    "RuleScope",
    "ConnectionConfig",
    "DQPipelineConfig",
    "RuleConfig",
    "DQTPipeline",
]
