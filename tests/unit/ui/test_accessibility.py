"""What a rendered page owes a reader who is not looking at it (`VIZ-5`).

`tests/unit/test_theme.py` measures colour. This measures structure, on the
actual output of every surface DQT renders — the two screens and the report —
so a page cannot pass by being built from accessible parts and assembled
carelessly.

The rules are `docs/PLAN-VIZ-UI.md` §4, and each is here because skipping it
breaks a specific reader rather than because a checklist lists it: an
unlabelled chart is silence to a screen reader, a table without header cells
is a grid of unattributed numbers, and a heading level skipped is a document
whose outline no longer matches what it looks like.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from dqt.common.models import DQIssue, PipelineResult
from dqt.sql.reports import generate_html_report
from dqt.ui.pages import issues_page, overview_page, run_page

_RUN: dict[str, Any] = {
    "run_id": "run-1",
    "connection_id": "warehouse",
    "started_at": "2026-09-05T09:00:00+00:00",
    "status": "partial",
    "dqt_version": "0.1.0",
}


@pytest.fixture
def surfaces(tmp_path: Path) -> dict[str, str]:
    """Render every surface DQT produces.

    Args:
        tmp_path: Directory for the report file.

    Returns:
        Surface name to HTML, so a failure names which page broke.

    Example:
        for name, html in surfaces.items(): ...
    """
    moment = datetime(2026, 9, 5, 9, 0, tzinfo=UTC)
    report = generate_html_report(
        PipelineResult(
            run_id="run-1",
            connection_id="c",
            started_at=moment,
            ended_at=moment,
            status="partial",
            issues=[
                DQIssue(
                    issue_id="i-1",
                    run_id="run-1",
                    dimension="completeness",
                    severity="error",
                    message="m",
                    schema_name="main",
                    table_name="orders",
                    column_name="email",
                )
            ],
        ),
        output_path=tmp_path / "r.html",
    ).read_text(encoding="utf-8")

    issue = {
        "severity": "error",
        "dimension": "completeness",
        "table_name": "orders",
        "column_name": "email",
        "message": "m",
    }
    return {
        "report": report,
        "overview": overview_page(
            runs=[_RUN],
            run=_RUN,
            dimension_scores={"completeness": 0.5},
            issues_by_severity={"error": 1},
            issues_by_dimension={"completeness": 1},
        ),
        "explorer": run_page(
            run=_RUN,
            tables=[{"schema_name": "main", "table_name": "orders", "issue_count": 1}],
            dimension_scores={"completeness": 0.5},
            issues_by_severity={"error": 1},
        ),
        "issues": issues_page(run=_RUN, issues=[issue], total=1),
    }


class TestEveryChartSaysWhatItShows:
    """An unlabelled chart is silence to a screen reader."""

    def test_every_svg_carries_an_accessible_name(self, surfaces: dict[str, str]) -> None:
        """``role="img"`` plus ``aria-label``, on every one.

        ``dqt.viz`` puts them there, so this is checking that nothing between
        the primitive and the page strips them -- which is exactly the kind
        of thing a refactor does silently.
        """
        for name, html in surfaces.items():
            for svg in re.findall(r"<svg[^>]*>", html):
                assert 'role="img"' in svg, f"{name}: {svg}"
                assert "aria-label=" in svg, f"{name}: {svg}"

    def test_no_chart_relies_on_a_title_attribute(self, surfaces: dict[str, str]) -> None:
        """``title`` is a tooltip, and a tooltip needs a pointer.

        Keyboard and touch users never see one, so a chart whose only
        explanation lives there has no explanation for them.
        """
        for name, html in surfaces.items():
            for svg in re.findall(r"<svg[^>]*>", html):
                assert "title=" not in svg, f"{name}: {svg}"


class TestTablesAreTables:
    """A table without header cells is a grid of unattributed numbers."""

    def test_every_table_has_header_cells(self, surfaces: dict[str, str]) -> None:
        """``<th>``, so a screen reader can announce which column a cell is in."""
        for name, html in surfaces.items():
            for table in re.findall(r"<table>.*?</table>", html, re.DOTALL):
                assert "<th>" in table, name

    def test_no_layout_is_done_with_a_table(self, surfaces: dict[str, str]) -> None:
        """Every table here holds data, and none is used for arrangement.

        A layout table is announced as data and read cell by cell, which is
        how a page becomes unusable while looking fine. The scorecards use a
        flex container instead, and this pins that they keep doing so.
        """
        for name, html in surfaces.items():
            for table in re.findall(r"<table>.*?</table>", html, re.DOTALL):
                assert "dqt-cards" not in table, name


class TestTheDocumentOutlineMatchesThePage:
    """A heading structure is how a screen reader user skims."""

    def test_there_is_exactly_one_h1(self, surfaces: dict[str, str]) -> None:
        """The document's subject, stated once.

        Two competing h1s is a page with two subjects; none is a page with
        no entry point.
        """
        for name, html in surfaces.items():
            assert html.count("<h1>") == 1, name

    def test_no_heading_level_is_skipped(self, surfaces: dict[str, str]) -> None:
        """h1 then h3 tells a reader a level was lost.

        They cannot tell whether the section is missing or merely styled
        differently, so the outline stops being navigable.
        """
        for name, html in surfaces.items():
            levels = [int(match) for match in re.findall(r"<h([1-6])>", html)]
            for previous, current in zip(levels, levels[1:], strict=False):
                assert current <= previous + 1, f"{name}: h{previous} then h{current}"


class TestNavigationWorksWithoutAPointer:
    """Plain pages were chosen so this is true by construction; pin it."""

    def test_every_link_is_a_real_link(self, surfaces: dict[str, str]) -> None:
        """An ``<a>`` with an ``href`` is focusable and follows Enter.

        A clickable ``<span>`` is neither, and the difference is invisible
        until someone puts the mouse down.
        """
        for name, html in surfaces.items():
            for anchor in re.findall(r"<a[^>]*>", html):
                assert "href=" in anchor, f"{name}: {anchor}"

    def test_nothing_is_removed_from_the_tab_order(self, surfaces: dict[str, str]) -> None:
        """``tabindex="-1"`` on a link takes it away from keyboard users."""
        for name, html in surfaces.items():
            assert 'tabindex="-1"' not in html, name

    def test_the_page_declares_its_language(self, surfaces: dict[str, str]) -> None:
        """A screen reader picks its voice from this.

        Without it, Persian is read with an English pronunciation model,
        which is not an accent -- it is noise.
        """
        for name, html in surfaces.items():
            assert "<html lang=" in html, name
