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

Dry run vs. commit
------------------

``profile`` defaults to ``--dry-run``: the connection to the profiled
database is opened read-only (:attr:`~dqt.common.models.ConnectionConfig.read_only`,
enforced by :func:`dqt.sql.rules._get_connection`), so no mutating
operation can commit. Pass ``--commit`` to open the connection read-write.
As of this version, ``profile`` itself never invokes cleansing (stage 5 of
:meth:`~dqt.sql.pipeline.DQTPipeline.run` is a documented pass-through — see
``dqt.sql.cleansing.cleanse``), so ``--commit`` currently only affects how
the connection is opened; it becomes load-bearing once a future task wires
cleansing configs into the pipeline.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import UTC, datetime
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

from dqt.common.config_loader import load_rules
from dqt.common.models import ConnectionConfig, DQPipelineConfig, PipelineResult
from dqt.exceptions import ConfigurationError
from dqt.exit_codes import FAIL_ON_CHOICES, ExitCode, decide_exit_code
from dqt.sql.pipeline import DQTPipeline
from dqt.sql.rules import apply_rules
from dqt.sql.schema_discovery import discover_schema

_err = Console(stderr=True)
_out = Console()


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


#: Shared by ``profile`` and ``check`` so the contract is described once.
#: `tests/unit/test_documented_surface.py` requires a choice-bounded flag to
#: name its choices in its own help, and two copies of that prose would drift.
_FAIL_ON_HELP = (
    "Severity at which findings make the process exit non-zero. "
    "'error' (default) fails on error and critical; 'warning' also "
    "fails on warnings; 'none' never gates on findings. A broken run "
    "still exits non-zero whatever this is set to."
)


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
    # --commit is deliberately absent. It used to open the connection
    # read-write, which mattered while run() had a cleansing stage; Q1 removed
    # that stage, so the flag's only remaining effect would be to drop a guard
    # in exchange for nothing. --dry-run is kept as an accepted no-op because
    # scripts pass it and its intent is now simply unconditional.
    profile.add_argument(
        "--fail-on",
        choices=list(FAIL_ON_CHOICES),
        default="error",
        help=_FAIL_ON_HELP,
    )
    profile.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Accepted for compatibility and has no effect: profiling always "
            "opens the connection read-only and never mutates."
        ),
    )

    # -- serve subcommand
    serve = sub.add_parser(
        "serve",
        help="Serve the read-only dashboard over HTTP.",
    )
    serve.add_argument(
        "--store",
        default="dqt_runs.db",
        help="Path to the RunStore SQLite file the dashboard reads.",
    )
    serve.add_argument(
        "--host",
        default=LOOPBACK_HOST,
        help=(
            "Address to bind. Defaults to 127.0.0.1, which is reachable only "
            "from this machine. Any other address is refused unless "
            "--allow-unauthenticated-remote-access is also given."
        ),
    )
    serve.add_argument("--port", type=int, default=8000, help="Port to bind (default 8000).")
    serve.add_argument(
        "--allow-unauthenticated-remote-access",
        action="store_true",
        help=(
            "Permit binding an address other machines can reach. The dashboard "
            "has no login, so only use this behind a reverse proxy or tunnel "
            "that authenticates."
        ),
    )

    # -- check subcommand
    check = sub.add_parser(
        "check",
        help="Evaluate rules only, without profiling. A CI gate.",
    )
    check.add_argument("--dsn", required=True, help="SQLAlchemy-style DSN.")
    check.add_argument(
        "--rules",
        action="append",
        default=None,
        help="Path to a YAML or JSON rule file. Repeatable.",
    )
    check.add_argument("--config", default=None, help="Config file supplying rule_files.")
    check.add_argument("--connection-id", default="cli", help="Logical connection identifier.")
    check.add_argument(
        "--fail-on",
        choices=list(FAIL_ON_CHOICES),
        default="error",
        help=_FAIL_ON_HELP,
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
        # 3, not 1. A missing file means DQT never reached a database, and a
        # pipeline branching on the contract must not read that as "your data
        # has errors" -- the two failures demand opposite responses.
        sys.exit(int(ExitCode.CONFIGURATION_ERROR))
    raw = p.read_text(encoding="utf-8")
    if p.suffix in (".yaml", ".yml"):
        if not _YAML_AVAILABLE:
            _err.print("[red]PyYAML is not installed.[/red] Run: pip install pyyaml")
            sys.exit(int(ExitCode.CONFIGURATION_ERROR))
        yaml_cfg: dict[str, Any] = yaml.safe_load(raw) or {}
        return yaml_cfg
    try:
        json_cfg: dict[str, Any] = json.loads(raw)
        return json_cfg
    except json.JSONDecodeError as exc:
        _err.print(f"[red]Failed to parse config JSON:[/red] {exc}")
        sys.exit(int(ExitCode.CONFIGURATION_ERROR))


def _build_connection_config(args: argparse.Namespace) -> ConnectionConfig:
    """Build a ConnectionConfig from CLI args, honoring --dry-run/--commit.

    ``args.commit`` defaults to ``False`` (i.e. ``--dry-run``, the default
    unless ``--commit`` was passed).  This function maps that directly onto
    :attr:`~dqt.common.models.ConnectionConfig.read_only`: without
    ``--commit``, the connection used for this run is opened read-only
    (enforced at the connection layer by
    :func:`dqt.sql.rules._get_connection`), regardless of what a future
    mutating stage might otherwise attempt. ``--commit`` is required to open
    a writable connection.

    Args:
        args: Parsed CLI namespace for the ``profile`` subcommand.

    Returns:
        A validated :class:`~dqt.common.models.ConnectionConfig`.

    Example::

        cfg = _build_connection_config(args)
        assert cfg.read_only is True  # always
    """
    return ConnectionConfig(
        id=args.connection_id,
        dsn=args.dsn,
        # Unconditional: see _build_parser on why --commit no longer exists.
        read_only=True,
    )


def _build_pipeline_config(
    args: argparse.Namespace,
    file_cfg: dict[str, Any],
) -> DQPipelineConfig:
    """Merge CLI args + config file into a DQPipelineConfig.

    CLI args take precedence over file values. ``rule_files`` has no CLI-level
    flag today, so a ``rule_files`` list in *file_cfg* is forwarded as-is;
    without it, the pipeline evaluates no declarative rules regardless of
    what the config file names.

    Args:
        args: Parsed CLI namespace.
        file_cfg: Dict loaded from an optional config file.

    Returns:
        A populated DQPipelineConfig.

    Example::

        cfg = _build_pipeline_config(args, {"rule_files": ["rules/base.yaml"]})
        assert cfg.rule_files == ["rules/base.yaml"]
    """
    include_schemas = None
    if args.schema:
        include_schemas = [args.schema]
    elif "include_schemas" in file_cfg:
        include_schemas = file_cfg["include_schemas"]

    # The file is handed to the model rather than copied key by key. Every
    # key added to DQPipelineConfig after this function was written had been
    # silently dropped -- sampling, profiling, classification -- and an
    # enumeration is a list somebody has to remember to extend. The model
    # already knows its own fields, and `extra="forbid"` now sees a
    # misspelled key instead of ignoring it.
    settings: dict[str, Any] = dict(file_cfg)
    settings["connection_id"] = args.connection_id
    if include_schemas is not None:
        settings["include_schemas"] = include_schemas
    settings.setdefault("rule_files", [])

    return DQPipelineConfig(**settings)


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

    connection_config = _build_connection_config(args)
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
                    # NEW-B means run() reports rather than raises, so reaching
                    # here is DQT breaking, not the data being bad.
                    _err.print(f"[red]Internal error:[/red] {exc}")
                    return int(ExitCode.INTERNAL_ERROR)
            progress.advance(task)

    if result is None or report_path is None:
        _err.print("[red]Pipeline did not complete.[/red]")
        return int(ExitCode.INTERNAL_ERROR)

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

    for stage_error in result.stage_errors:
        _err.print(f"[yellow]{stage_error.stage}:[/yellow] {stage_error.message}")

    # Only the report path goes to stdout for shell capture
    _out.print(str(report_path))
    return int(decide_exit_code(result, fail_on=args.fail_on))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


#: The address the dashboard binds unless told otherwise. Reachable only from
#: the machine running it.
LOOPBACK_HOST = "127.0.0.1"

#: Addresses that reach no further than this machine. ``localhost`` is
#: included by name because that is what people type; the two IPs are its
#: IPv4 and IPv6 forms.
_LOOPBACK_ADDRESSES = frozenset({LOOPBACK_HOST, "localhost", "::1"})


def resolve_bind_host(host: str, *, allow_remote: bool) -> str:
    """Return *host* if it is safe to bind, or refuse.

    The dashboard has **no authentication**, and what it serves is not the
    stored numbers so much as the shape of the database behind them: schema
    names, table names, column names, and a ranked list of where the data is
    weakest. That is reconnaissance, and binding it to a reachable address
    publishes it to everyone who can open the port.

    ``dqt.ui.app`` has always said so in its docstring, and `VIZ-0` tests
    that it does. But a docstring is read by people editing DQT, not by the
    person starting a server -- and until this command existed, DQT never
    called ``uvicorn.run``, so there was no moment at which to refuse. This
    is that moment.

    Args:
        host: The address the operator asked to bind.
        allow_remote: Whether the operator explicitly accepted the risk.

    Returns:
        *host*, unchanged, when binding it is permitted.

    Raises:
        ConfigurationError: When *host* is reachable from other machines and
            *allow_remote* is False.

    Example:
        assert resolve_bind_host("127.0.0.1", allow_remote=False) == "127.0.0.1"
    """
    if allow_remote or host in _LOOPBACK_ADDRESSES:
        return host

    raise ConfigurationError(
        f"Refusing to bind {host!r}: the dashboard has no authentication, and "
        "that address is reachable from other machines. What it would publish "
        "is your schema -- table names, column names, and a list of exactly "
        "where the data is weakest -- to anyone who can open the port. "
        "Bind 127.0.0.1 and reach it through an SSH tunnel, or put a reverse "
        "proxy that authenticates in front of it. If something already "
        "authenticates in front of DQT, pass "
        "--allow-unauthenticated-remote-access to say so."
    )


def _run_server(host: str, port: int, store: str) -> None:
    """Start the dashboard. Separated so the refusal can be tested without binding a port.

    Args:
        host: Already-validated bind address.
        port: Port to bind.
        store: Path to the RunStore the dashboard reads.

    Returns:
        None. Blocks until the server stops.

    Example:
        _run_server("127.0.0.1", 8000, "dqt_runs.db")
    """
    import os

    os.environ["DQT_STORE_PATH"] = store
    try:
        import uvicorn
    except ImportError as error:  # pragma: no cover - exercised by the message test
        raise ConfigurationError(
            "The dashboard needs the 'ui' extra, which is not installed. "
            "Install it with: pip install 'dqt[ui]'"
        ) from error

    from dqt.ui.app import app

    uvicorn.run(app, host=host, port=port)


def _cmd_serve(args: argparse.Namespace) -> int:
    """Validate the bind address, then serve.

    Validation happens **before** anything binds. A guard that fired after
    the port was open would already have failed.

    Args:
        args: Parsed ``serve`` arguments.

    Returns:
        The process exit code.

    Example:
        code = _cmd_serve(args)
    """
    host = resolve_bind_host(args.host, allow_remote=args.allow_unauthenticated_remote_access)
    if host not in _LOOPBACK_ADDRESSES:
        _err.print(
            f"[yellow]Warning:[/yellow] serving on {host} with no authentication. "
            "Anyone who can reach this port can read your schema."
        )
    _err.print(f"[bold]Dashboard:[/bold] http://{host}:{args.port}/ui  (store: {args.store})")
    _run_server(host, args.port, args.store)
    return int(ExitCode.SUCCESS)


def _cmd_check(args: argparse.Namespace) -> int:
    """Evaluate rules against the database, without profiling.

    Rules need discovered tables, not profiles, so this is genuinely cheaper
    than a profile run -- which is the only reason it is worth having as a
    separate CI step.

    Args:
        args: Parsed ``check`` arguments.

    Returns:
        The process exit code, from the same contract ``profile`` uses.

    Raises:
        ConfigurationError: When no rules were supplied. A gate that checks
            nothing must not report success.

    Example:
        code = _cmd_check(args)
    """
    rule_paths = list(args.rules or [])
    if args.config:
        rule_paths.extend(_load_config_file(args.config).get("rule_files", []))

    rules: list[Any] = []
    for path in rule_paths:
        rules.extend(load_rules(path))

    if not rules:
        raise ConfigurationError(
            "No rules to check. `dqt check` gates a build on rules, so running "
            "it with none would report a clean bill of health for a check that "
            "never happened. Pass --rules PATH, or a --config naming rule_files."
        )

    connection_config = ConnectionConfig(id=args.connection_id, dsn=args.dsn)
    tables = discover_schema(connection_config)
    run_id = f"check-{uuid.uuid4().hex[:12]}"
    issues, rule_runs = apply_rules(run_id, connection_config, rules, tables)

    moment = datetime.now(UTC)
    result = PipelineResult(
        run_id=run_id,
        connection_id=connection_config.id,
        started_at=moment,
        ended_at=moment,
        status="success",
        issues=issues,
        rules_run=rule_runs,
    )

    _err.rule("[bold]Rule check[/bold]")
    for rule_run in rule_runs:
        _err.print(
            f"  {rule_run.rule_name}: {rule_run.targets_checked} target(s), "
            f"{rule_run.targets_failed} failed, {rule_run.targets_error} error(s)"
        )
    _print_issues_table(result)

    return int(decide_exit_code(result, fail_on=args.fail_on))


def main() -> None:
    """CLI entry point — parse args and dispatch to the appropriate command.

    Example::

        # In pyproject.toml:
        # [project.scripts]
        # dqt = "dqt.cli:main"
    """
    parser = _build_parser()
    args = parser.parse_args()

    handlers = {
        "profile": _cmd_profile,
        "serve": _cmd_serve,
        "check": _cmd_check,
    }
    handler = handlers.get(args.command)
    if handler is None:
        parser.print_help()
        sys.exit(1)

    try:
        sys.exit(handler(args))
    except ConfigurationError as error:
        # Exit 3, never 1. `NEW-V` was config errors exiting 1, which tells a
        # CI job the data has problems when the run never happened.
        _err.print(f"[red]Configuration error:[/red] {error}")
        sys.exit(int(ExitCode.CONFIGURATION_ERROR))


if __name__ == "__main__":
    main()
