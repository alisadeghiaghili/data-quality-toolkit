"""The generic missingness bridge contract, B1.

The contract exists so DQT can consume an external missingness analyser
without knowing which one it is. Everything asserted here is about that
independence: the types carry no analyser-specific concept, they need no
DataFrame library to construct, and the one number DQT stores is normalised
to DQT's own unit rather than whatever the analyser happened to use.

If a future analyser cannot be expressed through these types without adding
a field named after it, the abstraction has failed and this file is where it
should show.
"""

from __future__ import annotations

import pytest

from dqt.bridges import ColumnMissingness, MissingnessBridge, MissingnessReport


def _report(**overrides: object) -> MissingnessReport:
    """Build a report with two columns of known missingness.

    Ground truth: 2 missing of 8 sampled rows is a ratio of 0.25, and 0 of 8
    is 0.0. Both are written here rather than computed.

    Args:
        **overrides: Field values replacing the defaults.

    Returns:
        A MissingnessReport for assertions to work against.

    Example:
        report = _report(analyzer="other")
    """
    defaults: dict[str, object] = {
        "analyzer": "missingly",
        "schema_name": "main",
        "table_name": "customers",
        "sampled_rows": 8,
        "columns": (
            ColumnMissingness(column_name="email", missing_count=2, missing_ratio=0.25),
            ColumnMissingness(column_name="id", missing_count=0, missing_ratio=0.0),
        ),
    }
    defaults.update(overrides)
    return MissingnessReport(**defaults)  # type: ignore[arg-type]


def test_the_contract_needs_no_dataframe_library_to_construct() -> None:
    """A report is buildable from plain Python values alone.

    DQT core is SQL-first and does not depend on pandas. If constructing the
    result type required a DataFrame, every consumer of a bridge result would
    inherit that dependency, and the bridge boundary would have leaked the
    thing it exists to contain.
    """
    report = _report()

    assert report.analyzer == "missingly"
    assert report.sampled_rows == 8
    assert [c.column_name for c in report.columns] == ["email", "id"]


def test_missing_ratio_is_a_ratio_not_a_percentage() -> None:
    """The stored ratio is 0..1, whatever unit the analyser reported in.

    ``missingly.miss_var_summary`` reports ``pct_miss`` on a 0..100 scale
    while ``DQMetric.score`` is 0..1. Normalising at the boundary is the whole
    point of having a boundary: a 25 that should have been 0.25 would not
    raise anything, it would silently make a quarter-empty column look a
    hundred times worse.
    """
    email = _report().columns[0]

    assert email.missing_ratio == 0.25
    assert 0.0 <= email.missing_ratio <= 1.0


def test_a_ratio_outside_the_unit_interval_is_rejected() -> None:
    """The type refuses a percentage handed to it by mistake.

    This is the guard that makes the previous test's convention enforceable
    rather than merely documented.
    """
    with pytest.raises(ValueError, match="missing_ratio"):
        ColumnMissingness(column_name="email", missing_count=2, missing_ratio=25.0)


def test_diagnostics_stay_opaque_to_dqt() -> None:
    """Analyser-specific findings pass through uninterpreted.

    Little's MCAR test, MAR/MNAR classification and the rest are `missingly`'s
    domain. DQT's rule is that it never re-implements them, and the honest
    expression of that is a field it stores and does not read. Typing this as
    a mapping rather than a modelled result is deliberate: modelling it would
    be the first step toward re-implementing it.
    """
    report = _report(diagnostics={"mcar_test": {"p_value": 0.03, "statistic": 12.7}})

    assert report.diagnostics["mcar_test"]["p_value"] == 0.03


def test_report_serialises_for_external_analyses_storage() -> None:
    """``to_dict`` produces what ``PipelineResult.external_analyses`` holds.

    That field is typed ``dict[str, dict[str, Any]]``, so a report has to
    reduce to plain data. Round-tripping through it must not lose the columns
    or the analyser's name, since a stored panel with no attribution is
    indistinguishable from a DQT-computed one.
    """
    payload = _report().to_dict()

    assert payload["analyzer"] == "missingly"
    assert payload["sampled_rows"] == 8
    assert payload["columns"][0] == {
        "column_name": "email",
        "missing_count": 2,
        "missing_ratio": 0.25,
    }


def test_qualified_name_matches_the_external_analyses_key() -> None:
    """The report knows its own key, so callers cannot invent a different one.

    ``external_analyses`` is keyed ``schema.table``; a caller composing that
    string separately is a chance for the key and the report to disagree.
    """
    assert _report().qualified_name == "main.customers"
    assert _report(schema_name=None).qualified_name == "customers"


def test_any_object_with_analyze_satisfies_the_protocol() -> None:
    """The protocol is structural, so DQT never imports an analyser to type it.

    A nominal base class would force ``dqt.bridges`` to be importable by every
    analyser adapter and vice versa. Structural typing keeps the dependency
    pointing one way.
    """

    class StubBridge:
        name = "stub"

        def analyze(
            self, frame: object, *, table_name: str, schema_name: str | None = None
        ) -> MissingnessReport:
            return _report(analyzer="stub", table_name=table_name, schema_name=schema_name)

    bridge: MissingnessBridge = StubBridge()
    result = bridge.analyze(object(), table_name="orders", schema_name=None)

    assert isinstance(bridge, MissingnessBridge)
    assert result.analyzer == "stub"
    assert result.qualified_name == "orders"
