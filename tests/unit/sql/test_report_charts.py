"""The report draws what it reports (`VIZ-2`).

`VIZ-0` pinned what the HTML report already promised. This adds the two
things `docs/PLAN-VIZ-UI.md` §3 asks the Overview to show, using the
primitives `VIZ-1` built — so the static artifact and the pages that come
later render the same charts from the same code.

**Scorecards for every dimension, including the ones nothing measured.** This
is the honesty requirement, not a decoration. DQT computes `completeness`
today and little else; a report that shows only what it measured lets a
reader assume the rest was fine. Six cards, and the five nobody scored say
"not measured" — which `dqt.viz.scorecard` renders as no bar at all, because
an empty track still reads as zero.

**Issues by dimension.** The one chart that answers "where do I look first",
which is the question the Overview exists for.

Everything `VIZ-0` pinned still has to hold, unchanged, and that suite is the
guard for this change rather than anything written here.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from dqt.common.models import DQIssue, DQMetric, PipelineResult
from dqt.sql.reports import generate_html_report

#: Hand-built so the expected numbers below are read off this literal.
#:
#: ``completeness`` is measured on two columns, scoring 1.0 and 0.0, so its
#: dimension score is 0.5. Nothing measures the other five. Three issues:
#: two ``completeness``, one ``validity``.
_RUN_ID = "run-charts"


def _result() -> PipelineResult:
    """Build the run the assertions below are derived from.

    Returns:
        A PipelineResult with two completeness metrics and three issues.

    Example:
        html = generate_html_report(_result())
    """
    moment = datetime(2026, 9, 5, 9, 0, tzinfo=UTC)
    return PipelineResult(
        run_id=_RUN_ID,
        connection_id="conn-1",
        started_at=moment,
        ended_at=moment,
        status="success",
        metrics=[
            DQMetric(
                run_id=_RUN_ID,
                dimension="completeness",
                score=1.0,
                schema_name="main",
                table_name="orders",
                column_name="id",
            ),
            DQMetric(
                run_id=_RUN_ID,
                dimension="completeness",
                score=0.0,
                schema_name="main",
                table_name="orders",
                column_name="email",
            ),
        ],
        issues=[
            DQIssue(
                issue_id=f"i-{index}",
                run_id=_RUN_ID,
                dimension=dimension,
                severity="error",
                message="something",
                schema_name="main",
                table_name="orders",
                column_name="email",
            )
            for index, dimension in enumerate(("completeness", "completeness", "validity"))
        ],
    )


def _render(tmp_path: Path) -> str:
    """Render the fixture run.

    Args:
        tmp_path: Directory to write into.

    Returns:
        The report's text.

    Example:
        html = _render(tmp_path)
    """
    return generate_html_report(_result(), output_path=tmp_path / "r.html").read_text(
        encoding="utf-8"
    )


class TestEveryDimensionGetsACard:
    """Six dimensions, whether or not anything measured them."""

    def test_all_six_dimensions_appear(self, tmp_path: Path) -> None:
        """Showing only what was measured invites the reader to assume the rest.

        The canonical set is closed and small, so there is no excuse for a
        report that quietly answers a narrower question than the one a DBA
        thinks they asked.
        """
        html = _render(tmp_path)

        for dimension in (
            "completeness",
            "validity",
            "uniqueness",
            "consistency",
            "referential_integrity",
            "timeliness",
        ):
            assert dimension in html

    def test_an_unmeasured_dimension_says_so(self, tmp_path: Path) -> None:
        """Five of the six are unmeasured in the fixture, and must say it."""
        assert "not measured" in _render(tmp_path).lower()

    def test_the_measured_dimension_shows_its_score(self, tmp_path: Path) -> None:
        """Two completeness metrics scoring 1.0 and 0.0 average to 50%.

        Derived from the fixture literal, not from the renderer.
        """
        assert "50%" in _render(tmp_path)

    def test_an_unmeasured_dimension_is_not_drawn_as_a_full_bar(self, tmp_path: Path) -> None:
        """The failure this whole section exists to prevent.

        ``dqt.viz.scorecard`` already refuses to draw a bar for a missing
        score; this checks the report actually goes through it rather than
        defaulting a missing score to 1.0 somewhere on the way.
        """
        html = _render(tmp_path)

        assert "dqt-unmeasured" in html


class TestIssuesAreCharted:
    """ "Where do I look first" is the question the overview answers."""

    def test_the_chart_is_drawn_from_the_canonical_issue_list(self, tmp_path: Path) -> None:
        """Two completeness issues and one validity, counted from the fixture.

        Counts come from ``PipelineResult.issues`` -- the flat canonical list
        -- never from summing the nested per-table views, which are
        navigation and double-count.
        """
        html = _render(tmp_path)

        assert "completeness 2" in html
        assert "validity 1" in html

    def test_the_chart_carries_its_text_equivalent(self, tmp_path: Path) -> None:
        """The accessibility rule follows the chart into the report.

        ``dqt.viz`` returns the equivalent beside the SVG so it cannot be
        dropped; this checks the report puts it on the page rather than
        keeping it.
        """
        html = _render(tmp_path)

        assert "dqt-chart-text" in html

    def test_a_clean_run_says_there_is_nothing_to_chart(self, tmp_path: Path) -> None:
        """An empty chart frame reads as a rendering failure."""
        clean = _result()
        clean.issues.clear()

        html = generate_html_report(clean, output_path=tmp_path / "c.html").read_text(
            encoding="utf-8"
        )

        assert "no data" in html.lower()


class TestTheChartsComeFromTheSharedPrimitives:
    """One renderer, two delivery modes -- the plan's central idea.

    If the report drew its own bars, the dashboard would drift from it the
    first time either changed. These assert the report is emitting `VIZ-1`'s
    markup rather than something that merely looks similar.
    """

    def test_score_bars_are_viz_score_bars(self, tmp_path: Path) -> None:
        """The class name is the seam, and a seam nobody checks moves."""
        assert "dqt-scorecard" in _render(tmp_path)

    def test_the_bar_chart_is_a_viz_bar_chart(self, tmp_path: Path) -> None:
        """Same reasoning for the issue chart."""
        assert "dqt-bar-chart" in _render(tmp_path)
