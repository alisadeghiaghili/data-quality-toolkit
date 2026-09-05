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

import html
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


def _validate_score(score: float) -> None:
    """Refuse a score that is not a proportion.

    Clamping would draw a wrong number as a plausible one and hide the
    caller's bug behind a chart that looks fine.

    Args:
        score: The value to check.

    Returns:
        None.

    Raises:
        ValueError: If *score* is outside ``[0, 1]``.

    Example:
        _validate_score(0.5)
    """
    if not 0.0 <= score <= 1.0:
        raise ValueError(f"A score must be between 0 and 1 to be drawn as a bar; got {score!r}.")


def _percent(score: float) -> str:
    """Format a proportion as a percentage for the text equivalent.

    Args:
        score: A value in ``[0, 1]``.

    Returns:
        The percentage, without a trailing ``.0`` on whole numbers.

    Example:
        assert _percent(0.5) == "50%"
    """
    pct = round(score * 100, 1)
    return f"{pct:g}%"


def score_bar(score: float, *, label: str) -> Chart:
    """Draw one proportion as a bar against a full-width track.

    Args:
        score: A value in ``[0, 1]``.
        label: What the score describes. Escaped; it is usually a dimension
            or a column name.

    Returns:
        The :class:`Chart`.

    Raises:
        ValueError: If *score* is outside ``[0, 1]``.

    Example:
        assert 'width="60"' in score_bar(0.5, label="completeness").svg
    """
    _validate_score(score)
    safe_label = html.escape(label)
    filled = round(SCORE_BAR_TRACK * score)
    text = f"{safe_label}: {_percent(score)}"
    svg = (
        f'<svg class="dqt-score-bar" width="{SCORE_BAR_TRACK}" height="10" '
        f'role="img" aria-label="{text}">'
        f'<rect class="dqt-track" x="0" y="0" width="{SCORE_BAR_TRACK}" height="10"></rect>'
        f'<rect class="dqt-fill" x="0" y="0" width="{filled}" height="10"></rect>'
        "</svg>"
    )
    return Chart(svg=svg, text=text)


def bar_chart(series: Sequence[tuple[str, float]], *, title: str) -> Chart:
    """Draw labelled values as horizontal bars, largest first.

    Bars are scaled against the largest value rather than against a fixed
    ceiling, so a chart of small counts is still readable. At most
    :data:`MAX_BAR_CATEGORIES` bars are drawn and the text equivalent says
    how many were left out.

    Args:
        series: ``(label, value)`` pairs. Labels are escaped.
        title: Heading for the chart. Escaped.

    Returns:
        The :class:`Chart`. An empty *series* returns one that says there is
        nothing to show, rather than an empty frame that reads as a
        rendering failure.

    Raises:
        ValueError: If any value is negative, which a count never is.

    Example:
        chart = bar_chart([("completeness", 3), ("validity", 1)], title="Issues")
    """
    safe_title = html.escape(title)
    for label, value in series:
        if value < 0:
            raise ValueError(f"A bar cannot be negative; {label!r} has value {value!r}.")

    if not series:
        return Chart(
            svg=f'<svg class="dqt-bar-chart" role="img" aria-label="{safe_title}: no data"></svg>',
            text=f"{safe_title}: no data",
        )

    ranked = sorted(series, key=lambda pair: (-pair[1], pair[0]))
    shown = ranked[:MAX_BAR_CATEGORIES]
    hidden = len(ranked) - len(shown)
    largest = max(value for _, value in shown) or 1.0

    rows = []
    described = []
    for index, (label, value) in enumerate(shown):
        safe_label = html.escape(label)
        width = round(BAR_CHART_TRACK * (value / largest))
        y = index * BAR_ROW_PITCH
        rows.append(
            f'<text class="dqt-bar-label" x="0" y="{y + 13}">{safe_label}</text>'
            f'<rect class="dqt-bar" x="{BAR_LABEL_GUTTER}" y="{y}" '
            f'width="{width}" height="18"></rect>'
            f'<text class="dqt-bar-value" x="{BAR_LABEL_GUTTER + width + 4}" '
            f'y="{y + 13}">{value:g}</text>'
        )
        described.append(f"{safe_label} {value:g}")

    if hidden:
        described.append(f"and {hidden} more")

    text = f"{safe_title}: " + ", ".join(described)
    height = len(shown) * BAR_ROW_PITCH
    svg = (
        f'<svg class="dqt-bar-chart" width="{BAR_LABEL_GUTTER + BAR_CHART_TRACK + 40}" '
        f'height="{height}" role="img" aria-label="{text}">' + "".join(rows) + "</svg>"
    )
    return Chart(svg=svg, text=text)


def trend_line(points: Sequence[tuple[str, float]], *, title: str) -> Chart:
    """Draw scores over time, oldest on the left.

    Args:
        points: ``(when, score)`` pairs in chronological order. Each score is
            a value in ``[0, 1]``.
        title: Heading for the chart. Escaped.

    Returns:
        The :class:`Chart`. Fewer than two points cannot make a line, so the
        text says so rather than drawing a single dot as a trend.

    Raises:
        ValueError: If any score is outside ``[0, 1]``.

    Example:
        chart = trend_line([("2026-09-01", 0.9), ("2026-09-02", 1.0)], title="Score")
    """
    safe_title = html.escape(title)
    for _, score in points:
        _validate_score(score)

    if len(points) < 2:
        return Chart(
            svg=f'<svg class="dqt-trend" role="img" aria-label="{safe_title}: no data"></svg>',
            text=f"{safe_title}: no data",
        )

    span = TREND_WIDTH - 2 * TREND_PADDING
    plot = TREND_HEIGHT - 2 * TREND_PADDING
    step = span / (len(points) - 1)

    coordinates = []
    described = []
    for index, (when, score) in enumerate(points):
        x = round(TREND_PADDING + index * step, 2)
        # SVG's y axis grows downward, so a high score is a small y. Getting
        # this backwards would plot quality upside down and still look like a
        # chart.
        y = round(TREND_PADDING + (1.0 - score) * plot, 2)
        coordinates.append(f"{x:g},{y:g}")
        described.append(f"{html.escape(when)} {_percent(score)}")

    text = f"{safe_title}: " + ", ".join(described)
    svg = (
        f'<svg class="dqt-trend" width="{TREND_WIDTH}" height="{TREND_HEIGHT}" '
        f'role="img" aria-label="{text}">'
        f'<polyline class="dqt-trend-line" fill="none" points="{" ".join(coordinates)}"></polyline>'
        "</svg>"
    )
    return Chart(svg=svg, text=text)


def severity_indicator(severity: str) -> Chart:
    """Draw a severity as a shape, with its word beside it.

    Args:
        severity: One of ``"info"``, ``"warning"``, ``"error"``,
            ``"critical"``.

    Returns:
        The :class:`Chart`, whose ``shape`` names the mark used.

    Raises:
        ValueError: If *severity* is not one of the four. Guessing would
            invent a severity the vocabulary does not have.

    Example:
        assert severity_indicator("error").shape == "square"
    """
    shape = _SEVERITY_SHAPES.get(severity)
    if shape is None:
        raise ValueError(
            f"Unknown severity {severity!r}; expected one of {', '.join(sorted(_SEVERITY_SHAPES))}."
        )

    marks = {
        "circle": '<circle cx="7" cy="7" r="5"></circle>',
        "triangle": '<polygon points="7,2 12,12 2,12"></polygon>',
        "square": '<rect x="2" y="2" width="10" height="10"></rect>',
        "diamond": '<polygon points="7,1 13,7 7,13 1,7"></polygon>',
    }
    svg = (
        f'<svg class="dqt-severity dqt-severity-{severity}" width="14" height="14" '
        f'role="img" aria-label="{severity}">{marks[shape]}</svg>'
    )
    return Chart(svg=svg, text=severity, shape=shape)


def scorecard(
    dimension: str,
    *,
    score: float | None,
    approximate: bool = False,
) -> Chart:
    """Draw one dimension's score, or state that it was not measured.

    ``score=None`` is the case this function exists for. "Not measured" and
    "perfect" are the two readings most easily confused, and confusing them
    is how a gap becomes a green tick — so an unmeasured dimension draws no
    bar at all, because an empty track still reads as zero to a glancing eye.

    Args:
        dimension: The dimension being scored. Escaped.
        score: A value in ``[0, 1]``, or None when nothing measured it.
        approximate: Whether the score came from an estimate. An estimate and
            an exact figure are different claims, and rendering them
            identically asserts a precision the number does not have.

    Returns:
        The :class:`Chart`.

    Raises:
        ValueError: If *score* is outside ``[0, 1]``.

    Example:
        assert "not measured" in scorecard("timeliness", score=None).text
    """
    safe_dimension = html.escape(dimension)

    if score is None:
        text = f"{safe_dimension}: not measured"
        return Chart(
            svg=(
                f'<svg class="dqt-scorecard dqt-unmeasured" width="{SCORE_BAR_TRACK}" '
                f'height="10" role="img" aria-label="{text}"></svg>'
            ),
            text=text,
        )

    bar = score_bar(score, label=dimension)
    text = f"{safe_dimension}: {_percent(score)}"
    if approximate:
        text = f"{text} (approximate)"
    return Chart(svg=bar.svg.replace("dqt-score-bar", "dqt-scorecard", 1), text=text)
