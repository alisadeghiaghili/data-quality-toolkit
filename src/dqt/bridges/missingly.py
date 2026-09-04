"""Adapter for the `missingly` sibling package (B2).

This is the only module in DQT permitted to know `missingly` exists, and it
imports it lazily so that ``import dqt`` keeps working on a machine that does
not have it. `missingly` operates on DataFrames; DQT operates on databases,
so the adapter's real job is to read a *bounded sample* out of SQL and to
translate what comes back into DQT's units.

Example:
    from dqt.bridges.missingly import run_missingly, sample_table

    frame = sample_table(connection_config, table_name="customers", limit=5000)
    report = run_missingly(frame, table_name="customers")
"""

from __future__ import annotations

import importlib
from typing import Any

from dqt.bridges.base import ColumnMissingness, MissingnessReport
from dqt.common.models import ConnectionConfig, PipelineResult
from dqt.sql._connect import get_connection, get_dialect_for

DEFAULT_SAMPLE_LIMIT = 10_000


def _import_optional(module_name: str) -> Any:
    """Import an optional dependency, or explain how to install it.

    Args:
        module_name: Module to import, e.g. ``"missingly"``.

    Returns:
        The imported module.

    Raises:
        ImportError: If it is not installed, naming the extra that provides it.

    Example:
        pandas = _import_optional("pandas")
    """
    try:
        return importlib.import_module(module_name)
    except ImportError as exc:
        raise ImportError(
            f"{module_name} is required for the missingly bridge but is not installed. "
            f"Install it with: pip install 'dqt[bridges]'. DQT core does not need it -- "
            "only this bridge does, and only when called."
        ) from exc


def _collect_diagnostics(missingly: Any, frame: Any) -> tuple[dict[str, Any], tuple[str, ...]]:
    """Gather missingly's analyser-specific findings without interpreting them.

    A diagnostic that cannot be computed is recorded as a note rather than
    raised: the per-column figures are the bridge's primary output and are
    still valid when, say, Little's test has too few complete cases to run.

    Args:
        missingly: The imported missingly module.
        frame: Sampled rows.

    Returns:
        The diagnostics mapping and any notes explaining what was skipped.

    Example:
        diagnostics, notes = _collect_diagnostics(missingly, frame)
    """
    diagnostics: dict[str, Any] = {}
    notes: list[str] = []
    mcar_test = getattr(missingly, "mcar_test", None)
    if mcar_test is not None:
        try:
            diagnostics["mcar_test"] = mcar_test(frame)
        except Exception as exc:  # noqa: BLE001 - the analyser's failure, not ours
            notes.append(f"mcar_test could not be computed on this sample: {exc}")
    return diagnostics, tuple(notes)


def sample_table(
    connection_config: ConnectionConfig,
    table_name: str,
    *,
    schema_name: str | None = None,
    limit: int = DEFAULT_SAMPLE_LIMIT,
) -> Any:
    """Read at most *limit* rows of a table into a DataFrame.

    Args:
        connection_config: Connection to read from.
        table_name: Table to sample.
        schema_name: Schema of *table_name*, or None.
        limit: Maximum rows to read.

    Returns:
        A pandas DataFrame holding the sample.

    Raises:
        ImportError: If pandas is not installed.

    Example:
        frame = sample_table(config, table_name="customers", limit=1000)
    """
    pandas = _import_optional("pandas")
    dialect = get_dialect_for(connection_config)
    qualified = dialect.qualified_identifier(schema_name, table_name)
    sql = dialect.limited_select_sql(qualified, ["*"], limit=limit)

    connection = get_connection(connection_config)
    try:
        cursor = connection.execute(sql) if hasattr(connection, "execute") else None
        if cursor is None:
            cursor = connection.cursor()
            cursor.execute(sql)
        columns = [description[0] for description in cursor.description]
        rows = cursor.fetchall()
    finally:
        connection.close()

    # Rows arrive as driver-specific row objects; list(row) normalises them.
    return pandas.DataFrame([list(row) for row in rows], columns=columns)


def run_missingly(
    frame: Any,
    *,
    table_name: str,
    schema_name: str | None = None,
) -> MissingnessReport:
    """Analyse *frame* with `missingly` and translate the result.

    Args:
        frame: Sampled rows as a pandas DataFrame.
        table_name: Table the sample came from.
        schema_name: Schema of *table_name*, or None.

    Returns:
        A :class:`~dqt.bridges.base.MissingnessReport`.

    Raises:
        ImportError: If `missingly` is not installed.

    Example:
        report = run_missingly(frame, table_name="customers")
    """
    missingly = _import_optional("missingly")

    summary = missingly.miss_var_summary(frame)
    sampled_rows = len(frame)
    columns = tuple(
        ColumnMissingness(
            column_name=str(row["variable"]),
            missing_count=int(row["n_miss"]),
            # miss_var_summary reports pct_miss on a 0..100 scale; DQT stores a
            # ratio. Converting here is the entire reason this adapter exists.
            missing_ratio=float(row["pct_miss"]) / 100.0,
        )
        for _, row in summary.iterrows()
    )

    diagnostics, notes = _collect_diagnostics(missingly, frame)

    return MissingnessReport(
        analyzer="missingly",
        schema_name=schema_name,
        table_name=table_name,
        sampled_rows=sampled_rows,
        columns=columns,
        diagnostics=diagnostics,
        notes=notes,
    )


def attach_missingly_result(result: PipelineResult, report: MissingnessReport) -> None:
    """Store *report* on *result* under its analyser and table key.

    Args:
        result: Pipeline result to attach to.
        report: Report to store.

    Returns:
        None. *result* is modified in place.

    Example:
        attach_missingly_result(result, report)
    """
    result.external_analyses.setdefault(report.analyzer, {})[report.qualified_name] = (
        report.to_dict()
    )


class MissinglyBridge:
    """`missingly` behind the generic :class:`MissingnessBridge` protocol.

    Attributes:
        name: Always ``"missingly"``.

    Example:
        report = MissinglyBridge().analyze(frame, table_name="customers")
    """

    name = "missingly"

    def analyze(
        self,
        frame: Any,
        *,
        table_name: str,
        schema_name: str | None = None,
    ) -> MissingnessReport:
        """Analyse a sample and return DQT-shaped findings.

        Args:
            frame: Sampled rows as a pandas DataFrame.
            table_name: Table the sample came from.
            schema_name: Schema of *table_name*, or None.

        Returns:
            A :class:`~dqt.bridges.base.MissingnessReport`.

        Example:
            report = MissinglyBridge().analyze(frame, table_name="t")
        """
        return run_missingly(frame, table_name=table_name, schema_name=schema_name)


__all__ = [
    "DEFAULT_SAMPLE_LIMIT",
    "MissinglyBridge",
    "attach_missingly_result",
    "run_missingly",
    "sample_table",
]
