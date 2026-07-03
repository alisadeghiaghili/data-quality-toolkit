"""
DQT command-line interface.

This module exposes a minimal DBA-oriented CLI built with argparse.  It is
intentionally thin; all business logic lives in the pipeline and domain layers.

Commands
--------
profile
    Run the full DQT pipeline against a database and write an HTML report.

Usage examples
--------------
# Minimal — profile all schemas in a SQLite database::

    python -m dqt profile --dsn sqlite:///mydb.db

# Scope to a single schema::

    python -m dqt profile --dsn postgresql://user:pass@host/db --schema public

# Custom output directory and run-store location::

    python -m dqt profile \\
        --dsn sqlite:///mydb.db \\
        --schema main \\
        --report-dir /tmp/reports \\
        --store /tmp/dqt_runs.db

# Load full pipeline config from YAML/JSON::

    python -m dqt profile --dsn sqlite:///mydb.db --config dqt_config.yaml
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_pipeline_config(config_path: str | None, schema: str | None,
                           exclude_tables: list[str]) -> dict:
    """Load pipeline configuration from a YAML/JSON file or build from flags.

    Args:
        config_path: Optional path to a ``.yaml`` or ``.json`` config file.
        schema: Schema filter from the ``--schema`` flag.
        exclude_tables: Tables to exclude from ``--exclude-tables``.

    Returns:
        A dict compatible with ``DQPipelineConfig`` field names.
    """
    if config_path:
        p = Path(config_path)
        if not p.exists():
            print(f"[dqt] ERROR: config file not found: {config_path}", file=sys.stderr)
            sys.exit(1)
        text = p.read_text(encoding="utf-8")
        if p.suffix in (".yaml", ".yml"):
            try:
                import yaml  # type: ignore
                data = yaml.safe_load(text)
            except ImportError:
                print(
                    "[dqt] ERROR: PyYAML is required to load .yaml configs. "
                    "Install it with: pip install pyyaml",
                    file=sys.stderr,
                )
                sys.exit(1)
        else:
            data = json.loads(text)
        return data if isinstance(data, dict) else {}

    cfg: dict = {}
    if schema:
        cfg["include_schemas"] = [schema]
    if exclude_tables:
        cfg["exclude_tables"] = exclude_tables
    return cfg


# ---------------------------------------------------------------------------
# Sub-command: profile
# ---------------------------------------------------------------------------


def _cmd_profile(args: argparse.Namespace) -> None:
    """Execute the profile sub-command."""
    # Late imports keep startup fast and errors local to the command.
    from dqt.common.models import ConnectionConfig, DQPipelineConfig
    from dqt.sql.pipeline import DQTPipeline

    # -- Build connection config
    conn_cfg = ConnectionConfig(
        id=f"cli-{args.dsn.split('/')[-1]}",
        dsn=args.dsn,
        dialect=args.dsn.split("://")[0] if "://" in args.dsn else "sqlite",
    )

    # -- Build pipeline config
    raw_cfg = _load_pipeline_config(
        config_path=args.config,
        schema=args.schema,
        exclude_tables=args.exclude_tables or [],
    )
    pipeline_cfg = DQPipelineConfig(**raw_cfg)

    # -- Resolve paths
    report_dir = Path(args.report_dir) if args.report_dir else Path.cwd()
    report_dir.mkdir(parents=True, exist_ok=True)
    store_path = Path(args.store) if args.store else Path.cwd() / "dqt_runs.db"

    print(f"[dqt] Connecting to: {args.dsn}")
    print(f"[dqt] Report output : {report_dir}")
    print(f"[dqt] Run store     : {store_path}")
    if args.schema:
        print(f"[dqt] Schema filter : {args.schema}")

    # -- Run pipeline
    pipeline = DQTPipeline(
        connection_config=conn_cfg,
        pipeline_config=pipeline_cfg,
        store_path=store_path,
        report_dir=report_dir,
    )

    try:
        result, report_path = pipeline.run()
    except Exception as exc:  # noqa: BLE001
        print(f"[dqt] ERROR: pipeline failed — {exc}", file=sys.stderr)
        sys.exit(1)

    issues_by_sev: dict[str, int] = {}
    for issue in result.issues:
        issues_by_sev[issue.severity] = issues_by_sev.get(issue.severity, 0) + 1

    print()
    print(f"[dqt] Run ID        : {result.run_id}")
    print(f"[dqt] Status        : {result.status}")
    print(f"[dqt] Tables scanned: {len(result.tables)}")
    print(f"[dqt] Metrics       : {len(result.metrics)}")
    print(f"[dqt] Issues        : {sum(issues_by_sev.values())} "
          f"({', '.join(f'{v} {k}' for k, v in sorted(issues_by_sev.items()))})")
    print(f"[dqt] Report        : {report_path}")


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    """Build and return the top-level argument parser."""
    parser = argparse.ArgumentParser(
        prog="dqt",
        description="DQT — SQL Data Quality Toolkit",
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")
    sub.required = True

    # profile subcommand
    profile_p = sub.add_parser(
        "profile",
        help="Run the DQ pipeline and write an HTML report.",
    )
    profile_p.add_argument(
        "--dsn",
        required=True,
        metavar="DSN",
        help="Database connection string, e.g. sqlite:///db.db or postgresql://user:pass@host/db",
    )
    profile_p.add_argument(
        "--schema",
        default=None,
        metavar="SCHEMA",
        help="Restrict profiling to this schema (optional).",
    )
    profile_p.add_argument(
        "--exclude-tables",
        nargs="+",
        default=[],
        metavar="TABLE",
        help="Space-separated list of table names to exclude.",
    )
    profile_p.add_argument(
        "--config",
        default=None,
        metavar="PATH",
        help="Path to a YAML or JSON pipeline config file.",
    )
    profile_p.add_argument(
        "--report-dir",
        default=None,
        metavar="DIR",
        help="Directory where the HTML report is written (default: current directory).",
    )
    profile_p.add_argument(
        "--store",
        default=None,
        metavar="PATH",
        help="SQLite path for the RunStore (default: dqt_runs.db in current directory).",
    )
    profile_p.set_defaults(func=_cmd_profile)

    return parser


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    """DQT CLI entry point.

    Args:
        argv: Argument list; defaults to ``sys.argv[1:]``.

    Example:
        main(["profile", "--dsn", "sqlite:///test.db"])
    """
    parser = _build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
