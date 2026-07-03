"""
Core SQL pipeline orchestrator for DQT.

This module defines DQTPipeline, the SQL-first pipeline shell required by the
DQT conventions. The current implementation provides a minimal but working
slice:
- connect to SQLite or PostgreSQL,
- discover tables and columns,
- compute simple profiling,
- produce completeness diagnostics,
- assemble a PipelineResult from DQT domain models.

It intentionally does not implement full rules, cleansing, monitoring
persistence, knowledge tables, semantic classification, or report rendering
yet.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from dqt.common.models import (
    ColumnResult,
    ConnectionConfig,
    DQIssue,
    DQMetric,
    DQPipelineConfig,
    PipelineResult,
    SchemaResult,
    TableResult,
)
from dqt.sql.cleansing import cleanse
from dqt.sql.diagnostics import DQDiagnostics
from dqt.sql.metrics import compute_run_metrics
from dqt.sql.monitoring import monitor
from dqt.sql.profiling import SqlProfiler, TableProfile
from dqt.sql.reports import generate_report
from dqt.sql.rules import apply_rules
from dqt.sql.schema_discovery import DiscoveredTable, discover_schema


class DQTPipeline:
    """Minimal SQL-first DQT pipeline orchestrator.

    Args:
        connection_config: Database connection configuration.
        pipeline_config: Per-run pipeline settings.

    Example:
        pipeline = DQTPipeline(connection_config, pipeline_config)
        result = pipeline.run()
    """

    def __init__(
        self,
        connection_config: ConnectionConfig,
        pipeline_config: DQPipelineConfig,
    ) -> None:
        self._connection_config = connection_config
        self._pipeline_config = pipeline_config

    def run(self) -> PipelineResult:
        """Execute the current DQT pipeline stages.

        Stages:
        1. discover_schema
        2. profile_data
        3. run_diagnostics
        4. apply_rules
        5. cleanse
        6. compute_metrics
        7. monitor
        8. generate_report

        Returns:
            A PipelineResult populated with discovered schema, table/column
            results, metrics, and basic completeness issues.

        Example:
            result = pipeline.run()
        """
        run_id = f"run-{uuid4().hex[:8]}"
        started_at = datetime.now(timezone.utc)

        discovered_tables = self.discover_schema()
        profiled_tables = self.profile_data(discovered_tables)
        issues = self.run_diagnostics(profiled_tables, run_id=run_id)
        rule_runs = self.apply_rules(run_id=run_id)

        result = self._build_result(
            run_id=run_id,
            started_at=started_at,
            profiled_tables=profiled_tables,
            issues=issues,
            rule_runs=rule_runs,
        )

        result = self.cleanse(result)
        run_metrics = self.compute_metrics(profiled_tables, run_id=run_id)
        monitored_metrics = self.monitor(result.metrics + run_metrics)
        result.metrics = monitored_metrics
        _ = self.generate_report(result)

        result.ended_at = datetime.now(timezone.utc)
        result.status = "success"
        return result

    def discover_schema(self) -> list[DiscoveredTable]:
        """Discover database tables and columns.

        Returns:
            Discovered table metadata.

        Example:
            tables = pipeline.discover_schema()
        """
        tables = discover_schema(self._connection_config)
        return self._filter_tables(tables)

    def profile_data(self, tables: list[DiscoveredTable]) -> list[TableProfile]:
        """Profile discovered tables.

        Args:
            tables: Discovered tables.

        Returns:
            Profiled tables.

        Example:
            profiles = pipeline.profile_data(tables)
        """
        profiler = SqlProfiler(self._connection_config)
        return profiler.profile_tables(tables)

    def run_diagnostics(self, profiles: list[TableProfile], run_id: str) -> list[DQIssue]:
        """Run basic DQ diagnostics.

        Args:
            profiles: Profiled tables.
            run_id: Pipeline run identifier.

        Returns:
            Detected issues.

        Example:
            issues = pipeline.run_diagnostics(profiles, run_id="run-001")
        """
        diagnostics = DQDiagnostics()
        return diagnostics.run(profiles, run_id)

    def apply_rules(self, run_id: str) -> list:
        """Run the rules stage.

        Args:
            run_id: Pipeline run identifier.

        Returns:
            Rule execution summaries.

        Example:
            rules = pipeline.apply_rules(run_id="run-001")
        """
        return apply_rules(run_id)

    def cleanse(self, result: PipelineResult) -> PipelineResult:
        """Run the cleansing stage.

        Args:
            result: Pipeline result built from earlier stages.

        Returns:
            PipelineResult after the cleansing stage.

        Example:
            result = pipeline.cleanse(result)
        """
        return cleanse(result)

    def compute_metrics(self, profiles: list[TableProfile], run_id: str) -> list[DQMetric]:
        """Compute run-level summary metrics.

        Args:
            profiles: Profiled tables.
            run_id: Pipeline run identifier.

        Returns:
            Run-level metrics.

        Example:
            metrics = pipeline.compute_metrics(profiles, run_id="run-001")
        """
        return compute_run_metrics(profiles, run_id)

    def monitor(self, metrics: list[DQMetric]) -> list[DQMetric]:
        """Run the monitoring stage.

        Args:
            metrics: Data-quality metrics.

        Returns:
            Metrics prepared for monitoring/history use.

        Example:
            metrics = pipeline.monitor(metrics)
        """
        return monitor(metrics)

    def generate_report(self, result: PipelineResult) -> dict[str, str]:
        """Run the report generation stage.

        Args:
            result: Final pipeline result.

        Returns:
            Minimal report descriptor.

        Example:
            report = pipeline.generate_report(result)
        """
        return generate_report(result)

    def _filter_tables(self, tables: list[DiscoveredTable]) -> list[DiscoveredTable]:
        include_schemas = set(self._pipeline_config.include_schemas or [])
        exclude_schemas = set(self._pipeline_config.exclude_schemas or [])
        include_tables = set(self._pipeline_config.include_tables or [])
        exclude_tables = set(self._pipeline_config.exclude_tables or [])

        filtered: list[DiscoveredTable] = []
        for table in tables:
            if include_schemas and table.schema_name not in include_schemas:
                continue
            if table.schema_name in exclude_schemas:
                continue
            if include_tables and table.table_name not in include_tables:
                continue
            if table.table_name in exclude_tables:
                continue
            filtered.append(table)
        return filtered

    def _build_result(
        self,
        run_id: str,
        started_at: datetime,
        profiled_tables: list[TableProfile],
        issues: list[DQIssue],
        rule_runs: list,
    ) -> PipelineResult:
        profiler = SqlProfiler(self._connection_config)
        profile_metrics = profiler.build_metrics(profiled_tables, run_id=run_id)

        table_results: dict[str, TableResult] = {}
        schema_tables: dict[str, list[str]] = {}

        for table_profile in profiled_tables:
            key = f"{table_profile.schema_name}.{table_profile.table_name}"
            schema_tables.setdefault(table_profile.schema_name, []).append(
                table_profile.table_name
            )

            column_results: list[ColumnResult] = []
            for column_profile in table_profile.columns:
                column_metrics = [
                    metric
                    for metric in profile_metrics
                    if metric.schema_name == column_profile.schema_name
                    and metric.table_name == column_profile.table_name
                    and metric.column_name == column_profile.column_name
                ]
                column_issues = [
                    issue
                    for issue in issues
                    if issue.schema_name == column_profile.schema_name
                    and issue.table_name == column_profile.table_name
                    and issue.column_name == column_profile.column_name
                ]
                column_results.append(
                    ColumnResult(
                        schema_name=column_profile.schema_name,
                        table_name=column_profile.table_name,
                        column_name=column_profile.column_name,
                        db_type=column_profile.__class__.__name__,
                        semantic_type=None,
                        metrics=column_metrics,
                        issues=column_issues,
                    )
                )

            table_metrics = [
                metric
                for metric in profile_metrics
                if metric.schema_name == table_profile.schema_name
                and metric.table_name == table_profile.table_name
                and metric.column_name is None
            ]
            table_issues = [
                issue
                for issue in issues
                if issue.schema_name == table_profile.schema_name
                and issue.table_name == table_profile.table_name
                and issue.column_name is None
            ]

            table_results[key] = TableResult(
                schema_name=table_profile.schema_name,
                table_name=table_profile.table_name,
                columns=column_results,
                metrics=table_metrics,
                issues=table_issues,
            )

        schema_results = [
            SchemaResult(
                schema_name=schema_name,
                tables=sorted(table_names),
                metrics=[],
                issues=[],
            )
            for schema_name, table_names in sorted(schema_tables.items())
        ]

        return PipelineResult(
            run_id=run_id,
            connection_id=self._connection_config.id,
            started_at=started_at,
            ended_at=started_at,
            status="partial",
            schemas=schema_results,
            tables=table_results,
            metrics=profile_metrics,
            issues=issues,
            rules_run=rule_runs,
            external_analyses={},
        )
