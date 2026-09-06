"""
dqt.sql.pipeline
================

Core SQL pipeline orchestrator for DQT.

This module defines :class:`DQTPipeline`, the SQL-first pipeline that wires
together all DQT stages into a single ``run()`` call:

1. **discover_schema** — enumerate tables and columns from the database.
2. **profile_data** — compute per-column statistics (min/max, nulls, distinct counts).
3. **run_diagnostics** — derive :class:`~dqt.common.models.DQIssue` objects from profiles.
4. **apply_rules** — evaluate declarative YAML/JSON rules via SQL and collect additional issues.
5. **compute_metrics** — aggregate run-level :class:`~dqt.common.models.DQMetric` objects.
6. **monitor** — pass metrics through the monitoring stage (stub; drift detection in future).

There is deliberately no cleansing stage. Q1, settled 2026-08-26, requires a
profiling run to be structurally incapable of mutating what it profiles, so
``run()``'s call graph contains no path to cleansing at all -- not behind a
flag, not behind a config toggle, not as a no-op method a later edit could
fill in. Cleansing is invoked deliberately through
:func:`~dqt.sql.cleansing.cleanse_plan` and
:func:`~dqt.sql.cleansing.cleanse_apply`, and
``tests/unit/test_architecture.py`` fails if this module imports either.
8. **persist** — write run, metrics, and issues to :class:`~dqt.common.storage.RunStore`.
9. **generate_report** — produce a self-contained HTML report.

All stages are also exposed as individual public methods so they can be called
in isolation for testing, scripting, or incremental pipelines.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from dqt._version import __version__
from dqt.common.config_loader import load_rules
from dqt.common.models import (
    ColumnResult,
    ConnectionConfig,
    DQIssue,
    DQMetric,
    DQPipelineConfig,
    PipelineResult,
    RuleRunResult,
    SchemaResult,
    StageError,
    TableResult,
)
from dqt.common.storage import RunStore
from dqt.sql.diagnostics import DQDiagnostics
from dqt.sql.metrics import compute_run_metrics
from dqt.sql.monitoring import monitor
from dqt.sql.profiling import SqlProfiler, TableProfile
from dqt.sql.reports import generate_html_report
from dqt.sql.rules import apply_rules as _apply_rules_engine
from dqt.sql.schema_discovery import DiscoveredTable, discover_schema


class DQTPipeline:
    """SQL-first DQT pipeline orchestrator.

    Orchestrates all data-quality stages — schema discovery, profiling,
    diagnostics, declarative rule evaluation, cleansing (stub), metric
    aggregation, monitoring, persistence, and HTML report generation ---
    in a single :meth:`run` call.

    Each stage is also callable independently via its public method, which
    is useful for incremental pipelines, scripting, and unit testing.

    Args:
        connection_config: Validated database connection settings.
        pipeline_config: Per-run pipeline settings (filters, rule files,
            metric thresholds, etc.).
        store_path: Path for the SQLite :class:`~dqt.common.storage.RunStore`
            file.  Defaults to ``dqt_runs.db`` in the current working directory.
        report_dir: Directory where HTML reports are written.
            Defaults to the current working directory.

    Example::

        from dqt.common.models import ConnectionConfig, DQPipelineConfig
        from dqt.sql.pipeline import DQTPipeline

        conn = ConnectionConfig(id="dev", dsn="sqlite:///dev.db")
        cfg  = DQPipelineConfig(
            connection_id="dev",
            rule_files=["examples/rules/base_rules.yaml"],
        )
        pipeline = DQTPipeline(conn, cfg)
        result, report_path = pipeline.run()
        print(result.status, report_path)
    """

    def __init__(
        self,
        connection_config: ConnectionConfig,
        pipeline_config: DQPipelineConfig,
        store_path: Path | str | None = None,
        report_dir: Path | str | None = None,
    ) -> None:
        """Assemble a pipeline, without connecting to anything.

        Both paths default to the working directory, which is the right
        default for a CLI run and the wrong one for a library caller -- so
        both are parameters rather than constants.

        Args:
            connection_config: The database to read.
            pipeline_config: What to include, exclude and sample.
            store_path: Where to persist runs. Defaults to
                ``dqt_runs.db`` beside the working directory.
            report_dir: Where to write reports. Defaults to the working
                directory.

        Example:
            pipeline = DQTPipeline(connection_config, pipeline_config)
        """
        self._connection_config = connection_config
        self._pipeline_config = pipeline_config
        self._store_path = Path(store_path) if store_path else Path.cwd() / "dqt_runs.db"
        self._report_dir = Path(report_dir) if report_dir else Path.cwd()
        self._rule_file_errors: list[StageError] = []

    # ------------------------------------------------------------------
    # Primary entry point
    # ------------------------------------------------------------------

    def run(self) -> tuple[PipelineResult, Path]:
        """Execute the full DQT pipeline and return the result and report path.

        Stages are executed in order:

        1. :meth:`discover_schema`
        2. :meth:`profile_data`
        3. :meth:`run_diagnostics`
        4. :meth:`apply_rules` — loads rule files from
           :attr:`~dqt.common.models.DQPipelineConfig.rule_files` and runs SQL
           evaluation; issues are merged into the global issue list.
        5. :meth:`compute_metrics`
        6. :meth:`monitor` (stub)
        7. Persist to :class:`~dqt.common.storage.RunStore`.
        8. Write HTML report.

        No stage mutates the profiled database. See the module docstring for
        why that is structural rather than a default.

        Returns:
            A ``(PipelineResult, Path)`` tuple.  ``Path`` points to the
            generated HTML report file.

        Example::

            result, report_path = pipeline.run()
            print(f"{result.status}: {len(result.issues)} issue(s)")
        """
        run_id = f"run-{uuid4().hex[:8]}"
        started_at = datetime.now(UTC)
        stage_errors: list[StageError] = []
        self._rule_file_errors = []

        # Stages 1-3 depend on one another, so a failure here ends the run:
        # profiling nothing is not a smaller answer, it is a different and
        # misleading one. Each is caught separately so stage_errors names the
        # one that actually broke rather than the first in the chain.
        discovered_tables: list[DiscoveredTable] = []
        profiled_tables: list[TableProfile] = []
        diagnostic_issues: list[DQIssue] = []
        fatal = False

        def _record(stage: str, exc: Exception) -> None:
            stage_errors.append(
                StageError(stage=stage, message=str(exc), exception_type=type(exc).__name__)
            )

        try:
            discovered_tables = self.discover_schema()
        except Exception as exc:  # noqa: BLE001 - the failure is the report
            _record("discover_schema", exc)
            fatal = True

        if not fatal:
            try:
                profiled_tables = self.profile_data(discovered_tables)
            except Exception as exc:  # noqa: BLE001
                _record("profile_data", exc)
                fatal = True

        if not fatal:
            try:
                diagnostic_issues = self.run_diagnostics(profiled_tables, run_id=run_id)
            except Exception as exc:  # noqa: BLE001
                _record("run_diagnostics", exc)
                fatal = True

        # Stage 4: rule evaluation
        rule_issues, rule_runs = self.apply_rules(
            run_id=run_id,
            discovered_tables=discovered_tables,
        )

        # Merge all issues
        all_issues = diagnostic_issues + rule_issues

        # Assemble intermediate result
        result = self._build_result(
            run_id=run_id,
            started_at=started_at,
            profiled_tables=profiled_tables,
            issues=all_issues,
            rule_runs=rule_runs,
        )

        # Stage 5: cleansing (stub)

        # Stage 6: compute run-level metrics
        run_metrics = self.compute_metrics(profiled_tables, run_id=run_id)

        # Stage 7: monitoring
        result.metrics = self.monitor(result.metrics + run_metrics)

        result.ended_at = datetime.now(UTC)
        stage_errors.extend(self._rule_file_errors)
        result.stage_errors = stage_errors
        # A stage that could not run at all fails the run; a stage that ran
        # but skipped part of its input degrades it. Reporting both as
        # "success" is what NEW-B exists to stop.
        if fatal:
            result.status = "failed"
        elif stage_errors:
            result.status = "partial"
        else:
            result.status = "success"

        # Stage 8: persist
        self._persist(result)

        # Stage 9: HTML report
        self._report_dir.mkdir(parents=True, exist_ok=True)
        report_path = self._report_dir / f"dqt_report_{result.run_id}.html"
        generate_html_report(result, output_path=report_path)

        return result, report_path

    # ------------------------------------------------------------------
    # Individual stages (callable independently)
    # ------------------------------------------------------------------

    def discover_schema(self) -> list[DiscoveredTable]:
        """Discover and filter database tables and columns.

        Applies schema/table include/exclude filters from
        :attr:`~dqt.common.models.DQPipelineConfig`.

        Returns:
            Filtered list of :class:`~dqt.sql.schema_discovery.DiscoveredTable`
            objects.

        Example::

            tables = pipeline.discover_schema()
            print([t.table_name for t in tables])
        """
        tables = discover_schema(self._connection_config)
        return self._filter_tables(tables)

    def profile_data(self, tables: list[DiscoveredTable]) -> list[TableProfile]:
        """Profile a list of discovered tables.

        Args:
            tables: Tables returned by :meth:`discover_schema`.

        Returns:
            List of :class:`~dqt.sql.profiling.TableProfile` objects.

        Example::

            tables   = pipeline.discover_schema()
            profiles = pipeline.profile_data(tables)
        """
        # The config key is the promise, not the profiler's parameter: a
        # profiler that samples correctly while nothing asks it to leaves
        # `sampling` as ignored as it was before it was implemented.
        profiler = SqlProfiler(self._connection_config, sampling=self._pipeline_config.sampling)
        return profiler.profile_tables(tables)

    def run_diagnostics(
        self,
        profiles: list[TableProfile],
        run_id: str,
    ) -> list[DQIssue]:
        """Run completeness and validity diagnostics over profiled tables.

        Args:
            profiles: Table profiles from :meth:`profile_data`.
            run_id: Unique identifier for the current pipeline run.

        Returns:
            List of :class:`~dqt.common.models.DQIssue` objects.

        Example::

            issues = pipeline.run_diagnostics(profiles, run_id="run-001")
        """
        return DQDiagnostics().run(profiles, run_id)

    def apply_rules(
        self,
        run_id: str,
        discovered_tables: list[DiscoveredTable] | None = None,
    ) -> tuple[list[DQIssue], list[RuleRunResult]]:
        """Load rule files and evaluate all rules against discovered tables.

        Rule files are read from
        :attr:`~dqt.common.models.DQPipelineConfig.rule_files`.  Each file is
        loaded via :func:`~dqt.common.config_loader.load_rules` and the
        combined rule set is evaluated by
        :func:`~dqt.sql.rules.apply_rules`.

        If no rule files are configured, or *discovered_tables* is empty,
        returns two empty lists immediately.

        Args:
            run_id: Unique identifier for the current pipeline run.
            discovered_tables: Tables returned by :meth:`discover_schema`.
                Defaults to ``None`` (treated as empty).

        Returns:
            A ``(issues, summaries)`` tuple:

            * *issues* — flat list of :class:`~dqt.common.models.DQIssue`
              produced by failing rules.
            * *summaries* — one :class:`~dqt.common.models.RuleRunResult`
              per rule, recording how many targets were checked / failed / errored.

        Example::

            tables = pipeline.discover_schema()
            issues, summaries = pipeline.apply_rules(run_id="run-001",
                                                     discovered_tables=tables)
        """
        rule_files = self._pipeline_config.rule_files or []
        if not rule_files or not discovered_tables:
            return [], []

        # Load and merge rules from all configured files
        all_rules = []
        for rule_file in rule_files:
            # A missing rule file is not fatal -- the DBA may be running from a
            # different working directory -- but it is not nothing either. It
            # used to be suppressed in silence, so a run that checked none of
            # its rules still reported success, which is the false clean bill
            # of health NEW-H was about. Settled 2026-08-19: report it, and let
            # run() downgrade the status to "partial".
            try:
                all_rules.extend(load_rules(rule_file))
            except FileNotFoundError:
                self._rule_file_errors.append(
                    StageError(
                        stage="apply_rules",
                        message=f"rule file not found: {rule_file}",
                        exception_type="missing_input",
                    )
                )

        if not all_rules:
            return [], []

        return _apply_rules_engine(
            run_id=run_id,
            connection_config=self._connection_config,
            rules=all_rules,
            discovered_tables=discovered_tables,
        )

    def compute_metrics(
        self,
        profiles: list[TableProfile],
        run_id: str,
    ) -> list[DQMetric]:
        """Compute run-level summary metrics.

        Args:
            profiles: Table profiles from :meth:`profile_data`.
            run_id: Unique identifier for the current pipeline run.

        Returns:
            List of run-level :class:`~dqt.common.models.DQMetric` objects.

        Example::

            metrics = pipeline.compute_metrics(profiles, run_id="run-001")
        """
        return compute_run_metrics(profiles, run_id)

    def monitor(self, metrics: list[DQMetric]) -> list[DQMetric]:
        """Pass metrics through the monitoring stage (stub).

        The monitoring stage currently returns metrics unchanged.  Drift
        detection and threshold alerting will be added in a future milestone.

        Args:
            metrics: Combined column-level and run-level metrics.

        Returns:
            Same metrics list (pass-through).

        Example::

            metrics = pipeline.monitor(all_metrics)
        """
        return monitor(metrics)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _persist(self, result: PipelineResult) -> None:
        """Write the run, its metrics, and its issues to the RunStore.

        Args:
            result: Completed :class:`~dqt.common.models.PipelineResult`.
        """
        store = RunStore(db_path=str(self._store_path))
        store.init_schema()
        store.save_run(result)

    def _filter_tables(self, tables: list[DiscoveredTable]) -> list[DiscoveredTable]:
        """Apply include/exclude schema and table filters from pipeline config.

        Args:
            tables: Full list of discovered tables.

        Returns:
            Filtered list based on
            :attr:`~dqt.common.models.DQPipelineConfig.include_schemas`,
            :attr:`~dqt.common.models.DQPipelineConfig.exclude_schemas`,
            :attr:`~dqt.common.models.DQPipelineConfig.include_tables`,
            and :attr:`~dqt.common.models.DQPipelineConfig.exclude_tables`.
        """
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
        rule_runs: list[RuleRunResult],
    ) -> PipelineResult:
        """Assemble a :class:`~dqt.common.models.PipelineResult` from stage outputs.

        Builds :class:`~dqt.common.models.ColumnResult` and
        :class:`~dqt.common.models.TableResult` trees, groups tables by schema,
        and attaches per-scope metrics and issues.

        Args:
            run_id: Pipeline run identifier.
            started_at: Run start timestamp.
            profiled_tables: Table profiles from :meth:`profile_data`.
            issues: Merged issues from diagnostics + rules.
            rule_runs: Rule summaries from :meth:`apply_rules`.

        Returns:
            Partially-complete :class:`~dqt.common.models.PipelineResult`
            (``status`` set to ``"partial"``; caller updates to ``"success"``
            after remaining stages).
        """
        profiler = SqlProfiler(self._connection_config, sampling=self._pipeline_config.sampling)
        profile_metrics = profiler.build_metrics(profiled_tables, run_id=run_id)

        table_results: dict[str, TableResult] = {}
        schema_tables: dict[str, list[str]] = {}

        for table_profile in profiled_tables:
            key = f"{table_profile.schema_name}.{table_profile.table_name}"
            schema_tables.setdefault(table_profile.schema_name, []).append(table_profile.table_name)

            column_results: list[ColumnResult] = []
            for column_profile in table_profile.columns:
                column_metrics = [
                    m
                    for m in profile_metrics
                    if m.schema_name == column_profile.schema_name
                    and m.table_name == column_profile.table_name
                    and m.column_name == column_profile.column_name
                ]
                column_issues = [
                    i
                    for i in issues
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
                m
                for m in profile_metrics
                if m.schema_name == table_profile.schema_name
                and m.table_name == table_profile.table_name
                and m.column_name is None
            ]
            table_issues = [
                i
                for i in issues
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
            dqt_version=__version__,
        )
