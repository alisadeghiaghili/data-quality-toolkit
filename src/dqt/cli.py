"""
dqt.cli
=======

Command-line interface for DQT.

Exposes a ``profile`` subcommand that runs the full DQT pipeline against a
SQL database and prints a rich summary to the terminal.

Usage examples::

    python -m dqt profile --dsn sqlite:///mydb.db
    python -m dqt profile --dsn postgresql://user:pass@host/db --schema public
    python -m dqt profile --dsn sqlite:///mydb.db --config dqt_config.yaml
    python -m dqt profile --dsn sqlite:///mydb.db --report-dir /tmp/reports

All log/progress output is written to stderr; only the final report path is
printed to stdout so the caller can capture it via shell substitution.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:
    import yaml

    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False

from rich import box
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from dqt.common.models import ConnectionConfig, DQPipelineConfig, PipelineResult
from dqt.sql.pipeline import DQTPipeline

_err = Console(stderr=True)
_out = Console()


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    """Build and return the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="dqt",
        description="DQT — SQL Data Quality Toolkit",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # -- profile subcommand
    profile = sub.add_parser(
        "profile",
        help="Run the DQT pipeline and generate a data-quality report.",
    )
    profile.add_argument(
        "--dsn",
        required=True,
        metavar="DSN",
        help="SQLAlchemy-style DSN, e.g. sqlite:///mydb.db or postgresql://user:pass@host/db",
    )
    profile.add_argument(
        "--schema",
        dest="schema",
        default=None,
        metavar="SCHEMA",
        help="Restrict profiling to this schema (optional).",
    )
    profile.add_argument(
        "--report-dir",
        dest="report_dir",
        default=None,
        metavar="DIR",
        help="Directory for the HTML report (default: current directory).",
    )
    profile.add_argument(
        "--store",
        dest="store",
        default=None,
        metavar="PATH",
        help="Path to the RunStore SQLite file (default: dqt_runs.db).",
    )
    profile.add_argument(
        "--config",
        dest="config",
        default=None,
        metavar="FILE",
        help="Optional YAML or JSON config file with pipeline options.",
    )
    profile.add_argument(
        "--connection-id",
        dest="connection_id",
        default="cli",
        metavar="ID",
        help="Logical connection identifier stored in run history (default: cli).",
    )
    return parser


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------


def _load_config_file(path: str) -> dict[str, Any]:
    """Load a YAML or JSON config file and return it as a dict.

    Args:
        path: Path to a YAML (``.yaml``/``.yml``) or JSON (``.json``) file.

    Returns:
        Parsed configuration dict.

    Raises:
        SystemExit: If the file cannot be parsed or YAML is not installed.

    Example::

        cfg = _load_config_file("dqt_config.yaml")
    """
    p = Path(path)
    if not p.exists():
        _err.print(f"[red]Config file not found:[/red] {path}")
        sys.exit(1)
    raw = p.read_text(encoding="utf-8")
    if p.suffix in (".yaml", ".yml"):
        if not _YAML_AVAILABLE:
            _err.print("[red]PyYAML is not installed.[/red] Run: pip install pyyaml")
            sys.exit(1)
        yaml_cfg: dict[str, Any] = yaml.safe_load(raw) or {}
        return yaml_cfg
    try:
        json_cfg: dict[str, Any] = json.loads(raw)
        return json_cfg
    except json.JSONDecodeError as exc:
        _err.print(f"[red]Failed to parse config JSON:[/red] {exc}")
        sys.exit(1)


def _build_pipeline_config(
    args: argparse.Namespace,
    file_cfg: dict[str, Any],
) -> DQPipelineConfig:
    """Merge CLI args + config file into a DQPipelineConfig.

    CLI args take precedence over file values.

    Args:
        args: Parsed CLI namespace.
        file_cfg: Dict loaded from an optional config file.

    Returns:
        A populated DQPipelineConfig.

    Example::

        cfg = _build_pipeline_config(args, {})
    """
    include_schemas = None
    if args.schema:
        include_schemas = [args.schema]
    elif file_cfg.get("include_schemas"):
        include_schemas = file_cfg["include_schemas"]

    return DQPipelineConfig(
        connection_id=args.connection_id,
        include_schemas=include_schemas,
        exclude_schemas=file_cfg.get("exclude_schemas"),
        include_tables=file_cfg.get("include_tables"),
        exclude_tables=file_cfg.get("exclude_tables"),
    )


# ---------------------------------------------------------------------------
# Rich output helpers
# ---------------------------------------------------------------------------

_SEVERITY_STYLE = {
    "critical": "bold red",
    "error": "red",
    "warning": "yellow",
    "info": "dim",
}


def _print_metrics_table(result: PipelineResult) -> None:
    """Render run-level metrics as a Rich table on stderr.

    Args:
        result: Completed pipeline result.

    Example::

        _print_metrics_table(result)
    """
    table = Table(
        title="[bold]DQT Run Metrics[/bold]",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Schema", style="dim")
    table.add_column("Table")
    table.add_column("Column")
    table.add_column("Dimension")
    table.add_column("Score", justify="right")
    table.add_column("Value", justify="right")

    run_level = [m for m in result.metrics if m.table_name is None]
    table_level = [m for m in result.metrics if m.table_name is not None and m.column_name is None]
    col_level = [m for m in result.metrics if m.column_name is not None]

    for m in run_level + table_level + col_level:
        score = m.score
        if score >= 0.9:
            score_str = f"[green]{score:.2%}[/green]"
        elif score >= 0.7:
            score_str = f"[yellow]{score:.2%}[/yellow]"
        else:
            score_str = f"[red]{score:.2%}[/red]"
        table.add_row(
            m.schema_name or "",
            m.table_name or "(run)",
            m.column_name or "",
            m.dimension,
            score_str,
            f"{m.value:.2f}" if m.value is not None else "",
        )

    _err.print(table)


def _print_issues_table(result: PipelineResult) -> None:
    """Render detected DQ issues as a Rich table on stderr.

    Args:
        result: Completed pipeline result.

    Example::

        _print_issues_table(result)
    """
    if not result.issues:
        _err.print("[green]No data-quality issues detected.[/green]")
        return

    table = Table(
        title="[bold]Data-Quality Issues[/bold]",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold red",
    )
    table.add_column("Severity")
    table.add_column("Schema", style="dim")
    table.add_column("Table")
    table.add_column("Column")
    table.add_column("Dimension")
    table.add_column("Message")

    for issue in sorted(result.issues, key=lambda i: i.severity, reverse=True):
        sev_style = _SEVERITY_STYLE.get(issue.severity, "")
        table.add_row(
            f"[{sev_style}]{issue.severity.upper()}[/{sev_style}]",
            issue.schema_name or "",
            issue.table_name or "",
            issue.column_name or "",
            issue.dimension,
            issue.message,
        )

    _err.print(table)


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------


def _cmd_profile(args: argparse.Namespace) -> int:
    """Execute the profile command.

    Builds ConnectionConfig + DQPipelineConfig from CLI args and an optional
    config file, runs DQTPipeline with Rich progress display, and prints
    a metrics + issues summary.

    Args:
        args: Parsed CLI namespace.

    Returns:
        Exit code (0 = success, 1 = error).

    Example::

        sys.exit(_cmd_profile(args))
    """
    file_cfg: dict[str, Any] = {}
    if args.config:
        file_cfg = _load_config_file(args.config)

    connection_config = ConnectionConfig(
        id=args.connection_id,
        dsn=args.dsn,
    )
    pipeline_config = _build_pipeline_config(args, file_cfg)
    report_dir = Path(args.report_dir) if args.report_dir else Path.cwd()
    store_path = Path(args.store) if args.store else Path.cwd() / "dqt_runs.db"

    pipeline = DQTPipeline(
        connection_config=connection_config,
        pipeline_config=pipeline_config,
        store_path=store_path,
        report_dir=report_dir,
    )

    _err.rule("[bold cyan]DQT Pipeline[/bold cyan]")

    stages = [
        "Discovering schema",
        "Profiling tables",
        "Running diagnostics",
        "Applying rules",
        "Computing metrics",
        "Monitoring",
        "Persisting results",
        "Generating HTML report",
    ]

    result: PipelineResult | None = None
    report_path: Path | None = None

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        TimeElapsedColumn(),
        console=_err,
        transient=True,
    ) as progress:
        task = progress.add_task("Initializing...", total=len(stages))
        for stage in stages:
            progress.update(task, description=stage)
            if stage == "Generating HTML report":
                # Run the full pipeline on the last meaningful stage label
                try:
                    result, report_path = pipeline.run()
                except Exception as exc:  # noqa: BLE001
                    _err.print(f"[red]Pipeline error:[/red] {exc}")
                    return 1
            progress.advance(task)

    if result is None or report_path is None:
        _err.print("[red]Pipeline did not complete.[/red]")
        return 1

    status_style = "green" if result.status == "success" else "red"
    status_text = f"[{status_style}]{result.status}[/{status_style}]"
    _err.rule("[bold]Results[/bold]")
    _err.print(
        f"[bold]Run ID:[/bold] {result.run_id}  "
        f"[bold]Status:[/bold] {status_text}  "
        f"[bold]Tables:[/bold] {len(result.tables)}  "
        f"[bold]Metrics:[/bold] {len(result.metrics)}  "
        f"[bold]Issues:[/bold] {len(result.issues)}"
    )

    _print_metrics_table(result)
    _print_issues_table(result)

    _err.rule()
    _err.print(f"[bold]Report:[/bold] {report_path}")

    # Only the report path goes to stdout for shell capture
    _out.print(str(report_path))
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI entry point — parse args and dispatch to the appropriate command.

    Example::

        # In pyproject.toml:
        # [project.scripts]
        # dqt = "dqt.cli:main"
    """
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "profile":
        sys.exit(_cmd_profile(args))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
