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

from typing import Any

from dqt.bridges.base import MissingnessReport
from dqt.common.models import ConnectionConfig, PipelineResult

DEFAULT_SAMPLE_LIMIT = 10_000


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
    raise NotImplementedError("sample_table is specified but not implemented")


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
    raise NotImplementedError("run_missingly is specified but not implemented")


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
    raise NotImplementedError("attach_missingly_result is specified but not implemented")


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
        raise NotImplementedError("MissinglyBridge.analyze is specified but not implemented")


__all__ = [
    "DEFAULT_SAMPLE_LIMIT",
    "MissinglyBridge",
    "attach_missingly_result",
    "run_missingly",
    "sample_table",
]
