"""
Core SQL pipeline orchestrator for DQT.

This module defines DQTPipeline, the SQL-first pipeline shell required by the
DQT conventions. The current implementation provides a minimal but working
slice:
- connect to SQLite or PostgreSQL,
- discover tables and columns,
- compute simple profiling,
- produce completeness diagnostics,
- assemble a PipelineResult from DQT domain models,
- persist run + metrics + issues via RunStore,
- generate a self-contained HTML report.

Stubbed stages: rules, cleansing, monitoring trend analysis, rich reports.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
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
from dqt.common.storage import RunStore
from dqt.sql.cleansing import cleanse
from dqt.sql.diagnostics import DQDiagnostics
from dqt.sql.metrics import compute_run_metrics
from dqt.sql.monitoring import monitor
from dqt.sql.profiling import SqlProfiler, TableProfile
from dqt.sql.reports import generate_html_report, generate_report
from dqt.sql.rules import apply_rules
from dqt.sql.schema_discovery import DiscoveredTable, discover_schema


class DQTPipeline:
    """SQL-first DQT pipeline orchestrator.

    Orchestrates schema discovery, profiling, diagnostics, rules (stub),
    cleansing (stub), metric aggregation, monitoring store write, and HTML
    report generation in a single ``run()`` call.

    Args:
        connection_config: Database connection configuration.
        pipeline_config: Per-run pipeline settings.
        store_path: Optional SQLite path for RunStore persistence.
            Defaults to ``dqt_runs.db`` in the current working directory.
        report_dir: Optional directory where HTML reports are written.
            Defaults to the current working directory.

    Example:
        pipeline = DQTPipeline(connection_config, pipeline_config)
        result, report_path = pipeline.run()
    """

    def __init__(
        self,
        connection_config: ConnectionConfig,
        pipeline_config: DQPipelineConfig,
        store_path: Path | str | None = None,
        report_dir: Path | str | None = None,
    ) -> None:
        self._connection_config = connection_config
        self._pipeline_config = pipeline_config
        self._store_path = Path(store_path) if store_path else Path.cwd() / "dqt_runs.db"
        self._report_dir = Path(report_dir) if report_dir else Path.cwd()

    def run(self) -> tuple[PipelineResult, Path]:
        """Execute the full DQT pipeline and return the result + report path.

        Stages executed in order:
        1. discover_schema
        2. profile_data
        3. run_diagnostics
        4. apply_rules  (stub)
        5. cleanse      (stub)
        6. compute_metrics
        7. monitor
        8. persist via RunStore
        9. generate HTML report

        Returns:
            Tuple of (PipelineResult, Path) where Path points to the HTML report.

        Example:
            result, report_path = pipeline.run()
        """
        run_id = f"run-{uuid4().hex[:8]}"
        started_at = datetime.now(timezone.utc)

        # -- Stage 1: schema discovery
        discovered_tables = self.discover_schema()

        # -- Stage 2: profiling
        profiled_tables = self.profile_data(discovered_tables)

        # -- Stage 3: diagnostics
        issues = self.run_diagnostics(profiled_tables, run_id=run_id)

        # -- Stage 4: rules (stub)
        rule_runs = self.apply_rules(run_id=run_id)

        # -- Assemble intermediate result
        result = self._build_result(
            run_id=run_id,
            started_at=started_at,
            profiled_tables=profiled_tables,
            issues=issues,
            rule_runs=rule_runs,
        )

        # -- Stage 5: cleansing (stub)
        result = self.cleanse(result)

        # -- Stage 6: compute run-level metrics
        run_metrics = self.compute_metrics(profiled_tables, run_id=run_id)

        # -- Stage 7: monitoring
        monitored_metrics = self.monitor(result.metrics + run_metrics)
        result.metrics = monitored_metrics

        result.ended_at = datetime.now(timezone.utc)
        result.status = "success"

        # -- Stage 8: persist to RunStore
        self._persist(result)

        # -- Stage 9: generate HTML report
        report_path = self._report_dir / f"dqt_report_{result.run_id}.html"
        generate_html_report(result, output_path=report_path)

        return result, report_path

    # ------------------------------------------------------------------
    # Individual stage methods (also callable independently)
    # ------------------------------------------------------------------

    def discover_schema(self) -> list[DiscoveredTable]:
        """Discover database tables and columns.

        Returns:
            Filtered list of discovered tables.

        Example:
            tables = pipeline.discover_schema()
        """
        tables = discover_schema(self._connection_config)
        return self._filter_tables(tables)

    def profile_data(self, tables: list[DiscoveredTable]) -> list[TableProfile]:
        """Profile discovered tables.

        Args:
            tables: Tables returned by discover_schema.

        Returns:
            List of table profiles.

        Example:
            profiles = pipeline.profile_data(tables)
        """
        profiler = SqlProfiler(self._connection_config)
        return profiler.profile_tables(tables)

    def run_diagnostics(self, profiles: list[TableProfile], run_id: str) -> list[DQIssue]:
        """Run completeness diagnostics over profiled tables.

        Args:
            profiles: Table profiles from profile_data.
            run_id: Current run identifier.

        Returns:
            List of DQIssue objects.

        Example:
            issues = pipeline.run_diagnostics(profiles, run_id)
        """
        return DQDiagnostics().run(profiles, run_id)

    def apply_rules(self, run_id: str) -> list:
        """Apply configured rules (stub).

        Args:
            run_id: Current run identifier.

        Returns:
            Empty list in the current implementation.

        Example:
            rule_runs = pipeline.apply_rules(run_id)
        """
        return apply_rules(run_id)

    def cleanse(self, result: PipelineResult) -> PipelineResult:
        """Run the cleansing stage (stub).

        Args:
            result: PipelineResult from earlier stages.

        Returns:
            Unchanged PipelineResult.

        Example:
            result = pipeline.cleanse(result)
        """
        return cleanse(result)

    def compute_metrics(self, profiles: list[TableProfile], run_id: str) -> list[DQMetric]:
        """Compute run-level summary metrics.

        Args:
            profiles: Table profiles.
            run_id: Current run identifier.

        Returns:
            List of run-level DQMetric objects.

        Example:
            metrics = pipeline.compute_metrics(profiles, run_id)
        """
        return compute_run_metrics(profiles, run_id)

    def monitor(self, metrics: list[DQMetric]) -> list[DQMetric]:
        """Pass metrics through the monitoring stage (stub).

        Args:
            metrics: Combined column and run-level metrics.

        Returns:
            Same metrics list.

        Example:
            metrics = pipeline.monitor(metrics)
        """
        return monitor(metrics)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _persist(self, result: PipelineResult) -> None:
        """Write run, metrics, and issues to the RunStore."""
        store = RunStore(db_path=str(self._store_path))
        store.init_schema()
        store.save_run(result)

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
                    m for m in profile_metrics
                    if m.schema_name == column_profile.schema_name
                    and m.table_name == column_profile.table_name
                    and m.column_name == column_profile.column_name
                ]
                column_issues = [
                    i for i in issues
                    if i.schema_name == column_profile.schema_name
                    and i.table_name == column_profile.table_name
                    and i.column_name == column_profile.column_name
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
                m for m in profile_metrics
                if m.schema_name == table_profile.schema_name
                and m.table_name == table_profile.table_name
                and m.column_name is None
            ]
            table_issues = [
                i for i in issues
                if i.schema_name == table_profile.schema_name
                and i.table_name == table_profile.table_name
                and i.column_name is None
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
