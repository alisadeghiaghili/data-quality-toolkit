"""Charts as SVG strings, produced by pure functions (Viz/UI facet).

`docs/PLAN-VIZ-UI.md` §2.2 chose this over a plotting library, and the
decisive reason was testability rather than weight: a raster image can only
be smoke-tested, and *"the bar for `validity` is drawn shorter than the bar
for `completeness`"* is a claim the honesty gate wants a test behind. An SVG
string is something a test can read.

It earns its place three more times over. It inherits the page's CSS, so a
chart follows the report into dark mode and RTL without being redrawn. It
survives being emailed inside a single self-contained file, which is what
`docs/DQT-UI-Ecosystem.md` says a DBA values most. And it adds no dependency.

Every function returns a :class:`Chart` — the SVG **and** the text equivalent
that says the same thing. They travel together because a value returned
beside the thing it describes cannot be forgotten the way a separate call
can, and `docs/PLAN-VIZ-UI.md` §4 makes the text equivalent an acceptance
criterion rather than a polish pass.

This module is pure: no I/O, no database, no dialect, no dependencies. It
takes numbers and returns strings.

Example:
    from dqt.viz import score_bar

    chart = score_bar(0.62, label="completeness")
    page = f"<figure>{chart.svg}<figcaption>{chart.text}</figcaption></figure>"
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

__all__ = [
    "BAR_CHART_TRACK",
    "MAX_BAR_CATEGORIES",
    "SCORE_BAR_TRACK",
    "TREND_HEIGHT",
    "TREND_PADDING",
    "TREND_WIDTH",
    "Chart",
    "bar_chart",
    "score_bar",
    "scorecard",
    "severity_indicator",
    "trend_line",
]

#: Width in pixels of a score bar's full track. A score of 1.0 fills it, and
#: every other width is this times the score -- which is what makes the
#: geometry assertable rather than eyeballed.
SCORE_BAR_TRACK = 120

#: Width in pixels of the longest bar in a bar chart. Bars are scaled against
#: the largest value rather than against 1.0, so a chart of small counts stays
#: readable.
BAR_CHART_TRACK = 260

#: Left gutter reserved for category labels.
BAR_LABEL_GUTTER = 130

#: Vertical pitch of one bar: its height plus the gap below it.
BAR_ROW_PITCH = 24

#: How many categories a bar chart draws before truncating.
#:
#: `docs/PLAN-VIZ-UI.md` §5 asks for five to seven. Forty labels in four
#: hundred pixels is not a chart. Truncation is the right behaviour, but only
#: because the chart says it truncated -- silently dropping rows would make it
#: a lie by omission.
MAX_BAR_CATEGORIES = 7

#: Plot area of a trend line, in pixels.
TREND_WIDTH = 400
TREND_HEIGHT = 100

#: Inset from every edge of the trend plot, so the first and last points are
#: drawn inside the frame rather than on it.
TREND_PADDING = 10

#: Marks that distinguish a severity without colour.
#:
#: A row of identical circles in four colours is a legend lookup for everyone
#: and unusable for the roughly 8% of men with some colour-vision deficiency.
#: Four different marks are neither.
_SEVERITY_SHAPES: dict[str, str] = {
    "info": "circle",
    "warning": "triangle",
    "error": "square",
    "critical": "diamond",
}


@dataclass(frozen=True, slots=True)
class Chart:
    """A drawing and the words that say the same thing.

    Attributes:
        svg: The chart, as an inline ``<svg>`` element. Self-contained: it
            references no font, image or stylesheet of its own.
        text: The accessible equivalent, carrying the values the chart
            encodes rather than describing the picture. Already escaped, so
            it can be placed in a page as-is.
        shape: For a severity indicator, the mark used — the non-colour half
            of its encoding. Empty for charts that do not have one.

    Example:
        chart = Chart(svg="<svg/>", text="completeness 50%", shape="")
    """

    svg: str
    text: str
    shape: str = ""


def score_bar(score: float, *, label: str) -> Chart:
    """Draw one proportion as a bar against a full-width track.

    Args:
        score: A value in ``[0, 1]``.
        label: What the score describes.

    Returns:
        The :class:`Chart`.

    Raises:
        ValueError: If *score* is outside ``[0, 1]``.

    Example:
        assert 'width="60"' in score_bar(0.5, label="completeness").svg
    """
    raise NotImplementedError


def bar_chart(series: Sequence[tuple[str, float]], *, title: str) -> Chart:
    """Draw labelled values as horizontal bars, largest first.

    Args:
        series: ``(label, value)`` pairs.
        title: Heading for the chart.

    Returns:
        The :class:`Chart`.

    Raises:
        ValueError: If any value is negative.

    Example:
        chart = bar_chart([("completeness", 3)], title="Issues")
    """
    raise NotImplementedError


def trend_line(points: Sequence[tuple[str, float]], *, title: str) -> Chart:
    """Draw scores over time, oldest on the left.

    Args:
        points: ``(when, score)`` pairs in chronological order.
        title: Heading for the chart.

    Returns:
        The :class:`Chart`.

    Raises:
        ValueError: If any score is outside ``[0, 1]``.

    Example:
        chart = trend_line([("a", 0.9), ("b", 1.0)], title="Score")
    """
    raise NotImplementedError


def severity_indicator(severity: str) -> Chart:
    """Draw a severity as a shape, with its word beside it.

    Args:
        severity: One of the four severities.

    Returns:
        The :class:`Chart`, whose ``shape`` names the mark used.

    Raises:
        ValueError: If *severity* is not one of the four.

    Example:
        assert severity_indicator("error").shape == "square"
    """
    raise NotImplementedError


def scorecard(
    dimension: str,
    *,
    score: float | None,
    approximate: bool = False,
) -> Chart:
    """Draw one dimension's score, or state that it was not measured.

    Args:
        dimension: The dimension being scored.
        score: A value in ``[0, 1]``, or None when nothing measured it.
        approximate: Whether the score came from an estimate.

    Returns:
        The :class:`Chart`.

    Raises:
        ValueError: If *score* is outside ``[0, 1]``.

    Example:
        assert "not measured" in scorecard("timeliness", score=None).text
    """
    raise NotImplementedError
