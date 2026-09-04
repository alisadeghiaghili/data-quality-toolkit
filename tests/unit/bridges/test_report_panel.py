"""Rendering external analyses into the HTML report, B3.

This also closes `NEW-E` in ``docs/BACKLOG.md``: ``external_analyses`` existed
as a field that nothing read. A field nothing reads is a promise nothing
keeps, and it had been carrying that status since the data model was written.

The panel is conditional by design. DQT must be fully usable without any
sibling analyser, so a report for a run that never called a bridge must not
mention one -- an empty "Missing Data" heading would suggest the analysis ran
and found nothing, which is a different claim from its not having run.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from dqt.bridges import ColumnMissingness, MissingnessReport
from dqt.bridges.missingly import attach_missingly_result
from dqt.common.models import PipelineResult
from dqt.sql.reports import generate_html_report


def _render(result: PipelineResult, tmp_path: Path) -> str:
    """Render *result* to HTML and return the file's contents.

    Args:
        result: Pipeline result to render.
        tmp_path: pytest temporary directory.

    Returns:
        The rendered HTML as text.

    Example:
        html = _render(_result(), tmp_path)
    """
    return generate_html_report(result, tmp_path / "report.html").read_text(encoding="utf-8")


def _result() -> PipelineResult:
    """Build an otherwise-empty successful run.

    Returns:
        A PipelineResult with no metrics, issues, or external analyses.

    Example:
        html = _render(_result(), tmp_path)
    """
    return PipelineResult(
        run_id="run-001",
        connection_id="conn-a",
        started_at=datetime(2026, 9, 4, 10, 0, tzinfo=UTC),
        ended_at=datetime(2026, 9, 4, 10, 1, tzinfo=UTC),
        status="success",
    )


def test_no_panel_when_no_bridge_ran(tmp_path: Path) -> None:
    """A report without external analyses says nothing about them.

    Silence and "we looked and found nothing" are different claims, and only
    one of them is true here.
    """
    html = _render(_result(), tmp_path)

    assert "Missing Data" not in html
    assert "missingly" not in html


def test_panel_appears_and_attributes_the_analyser(tmp_path: Path) -> None:
    """When a bridge ran, its findings render and are credited to it.

    Attribution is not decoration. A completeness figure DQT computed and one
    a sibling package computed carry different warranties, and a reader who
    cannot tell them apart will attribute both to DQT.

    Ground truth: 2 missing of 8 sampled rows renders as 25%.
    """
    result = _result()
    attach_missingly_result(
        result,
        MissingnessReport(
            analyzer="missingly",
            schema_name="main",
            table_name="customers",
            sampled_rows=8,
            columns=(ColumnMissingness(column_name="email", missing_count=2, missing_ratio=0.25),),
        ),
    )

    html = _render(result, tmp_path)

    assert "Missing Data" in html
    assert "missingly" in html
    assert "main.customers" in html
    assert "email" in html
    assert "25" in html


def test_panel_states_that_the_figures_come_from_a_sample(tmp_path: Path) -> None:
    """The sampled row count is shown, because it bounds every claim above it.

    A 25% missing rate measured on 8 sampled rows of a 40-million-row table is
    an estimate. Rendering the ratio without the sample size would present an
    estimate as a census.
    """
    result = _result()
    attach_missingly_result(
        result,
        MissingnessReport(
            analyzer="missingly",
            schema_name=None,
            table_name="orders",
            sampled_rows=1000,
            columns=(ColumnMissingness(column_name="ref", missing_count=10, missing_ratio=0.01),),
        ),
    )

    html = _render(result, tmp_path)

    assert "1000" in html or "1,000" in html


def test_panel_escapes_values_from_the_analyser(tmp_path: Path) -> None:
    """External data is escaped before it reaches the page.

    Everything in this panel originates outside DQT -- column names come from
    the user's database and the payload passes through a third-party package.
    The report is an HTML file a DBA opens in a browser, so an unescaped
    column name is a script-injection vector reaching a human.
    """
    result = _result()
    attach_missingly_result(
        result,
        MissingnessReport(
            analyzer="missingly",
            schema_name=None,
            table_name="t",
            sampled_rows=1,
            columns=(
                ColumnMissingness(
                    column_name="<script>alert(1)</script>",
                    missing_count=1,
                    missing_ratio=1.0,
                ),
            ),
        ),
    )

    html = _render(result, tmp_path)

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
