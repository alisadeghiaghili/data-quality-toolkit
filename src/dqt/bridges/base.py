"""Generic missingness-bridge contract (B1).

DQT computes its own completeness statistics -- null counts and ratios -- and
stops there. Missing-data *analysis* proper (MCAR/MAR/MNAR classification,
co-occurrence structure, imputation) belongs to sibling packages such as
``missingly``, and DQT's standing rule is that it never re-implements them.

This module is how the two meet without coupling. It defines what DQT will
accept back from any external analyser, in DQT's own vocabulary and units. No
name in here refers to a specific package, and nothing in here imports one --
including any DataFrame library, since DQT core is SQL-first and must stay
installable without pandas.

Example:
    from dqt.bridges import ColumnMissingness, MissingnessReport

    report = MissingnessReport(
        analyzer="missingly",
        schema_name="main",
        table_name="customers",
        sampled_rows=1000,
        columns=(
            ColumnMissingness("email", missing_count=120, missing_ratio=0.12),
        ),
    )
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class ColumnMissingness:
    """Missingness of one column, in DQT's units.

    Args:
        column_name: Column the figures describe.
        missing_count: Number of missing values among the analysed rows.
        missing_ratio: Missing values as a fraction in ``[0, 1]``. Analysers
            reporting percentages must convert before constructing this.

    Raises:
        ValueError: If *missing_ratio* falls outside ``[0, 1]``.

    Example:
        column = ColumnMissingness("email", missing_count=2, missing_ratio=0.25)
    """

    column_name: str
    missing_count: int
    missing_ratio: float

    def __post_init__(self) -> None:
        """Reject a ratio that is really a percentage.

        Raises:
            ValueError: If *missing_ratio* is outside ``[0, 1]``.

        Example:
            ColumnMissingness("a", missing_count=0, missing_ratio=0.0)
        """
        raise NotImplementedError("ColumnMissingness validation is specified but not implemented")


@dataclass(frozen=True, slots=True)
class MissingnessReport:
    """One external analyser's findings for one table.

    Args:
        analyzer: Name of the package that produced this, e.g. ``"missingly"``.
        table_name: Table analysed.
        sampled_rows: Rows the analyser actually saw. Every figure above is
            bounded by this; it is not the table's row count.
        columns: Per-column missingness.
        schema_name: Schema of *table_name*, or None.
        diagnostics: Analyser-specific findings, stored verbatim and never
            interpreted by DQT.
        notes: Free-text caveats worth surfacing to a reader.

    Example:
        report = MissingnessReport(
            analyzer="missingly",
            table_name="customers",
            sampled_rows=1000,
            columns=(),
        )
    """

    analyzer: str
    table_name: str
    sampled_rows: int
    columns: tuple[ColumnMissingness, ...]
    schema_name: str | None = None
    diagnostics: Mapping[str, Any] = field(default_factory=dict)
    notes: tuple[str, ...] = ()

    @property
    def qualified_name(self) -> str:
        """Return the ``schema.table`` key this report is stored under.

        Returns:
            ``"schema.table"``, or just the table name when there is no schema.

        Example:
            assert report.qualified_name == "main.customers"
        """
        raise NotImplementedError("qualified_name is specified but not implemented")

    def to_dict(self) -> dict[str, Any]:
        """Reduce the report to the plain data ``external_analyses`` holds.

        Returns:
            A JSON-compatible dict carrying the analyser, the sample size,
            the per-column figures, and any diagnostics and notes.

        Example:
            payload = report.to_dict()
        """
        raise NotImplementedError("to_dict is specified but not implemented")


@runtime_checkable
class MissingnessBridge(Protocol):
    """What DQT requires of any external missingness analyser.

    Structural rather than nominal on purpose: an adapter satisfies this by
    shape alone, so no analyser package needs to import DQT and DQT needs to
    import no analyser.

    Attributes:
        name: Analyser name, recorded as :attr:`MissingnessReport.analyzer`.

    Example:
        class StubBridge:
            name = "stub"

            def analyze(self, frame, *, table_name, schema_name=None):
                ...
    """

    name: str

    def analyze(
        self,
        frame: Any,
        *,
        table_name: str,
        schema_name: str | None = None,
    ) -> MissingnessReport:
        """Analyse a sampled table and return findings in DQT's vocabulary.

        Args:
            frame: Tabular sample, in whatever form the analyser accepts. DQT
                does not constrain the type, which is what keeps this module
                free of a DataFrame dependency.
            table_name: Table the sample came from.
            schema_name: Schema of *table_name*, or None.

        Returns:
            A :class:`MissingnessReport`.

        Example:
            report = bridge.analyze(frame, table_name="customers")
        """
        ...


__all__ = ["ColumnMissingness", "MissingnessBridge", "MissingnessReport"]
