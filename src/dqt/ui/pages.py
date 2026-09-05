"""The DBA-facing screens, rendered server-side (`VIZ-3`).

`docs/PLAN-VIZ-UI.md` §3 lists the screens; this module is the first three.
They are built the same way the HTML report is — :mod:`dqt._html` for markup,
:mod:`dqt.viz` for charts — which is the plan's central idea: one renderer,
two delivery modes, so a severity colour or a score badge is decided in one
place.

**Every function here is pure.** It takes the plain dicts :mod:`dqt.ui.api`
returns and gives back a string. No request, no framework, no database — so
almost everything worth asserting about a screen can be asserted without
starting a server.

No JavaScript, deliberately. `docs/PLAN-VIZ-UI.md` §2.1 chose plain
server-rendered pages partly because they are keyboard accessible and
back-button correct *by construction*, and that stops being true the moment
something on the page needs script to be usable.

Example:
    from dqt.ui.pages import overview_page

    html = overview_page(
        runs=runs, run=runs[0], dimension_scores=scores,
        issues_by_severity=severities, issues_by_dimension=dimensions,
    )
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from dqt._html import Raw, document, element, table
from dqt.common.models import get_args_of_dq_dimension
from dqt.viz import Chart, bar_chart, scorecard, severity_indicator

__all__ = ["issues_page", "overview_page", "run_page"]

#: How many issues a page shows. The size of a response must not depend on
#: how bad the data is -- the rule DQIssue evidence already follows.
ISSUE_PAGE_SIZE = 50

#: How each run status is rendered. The word is the part that always works.
_STATUS_CLASSES = {"success": "ok", "partial": "warn", "failed": "err"}

_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: 'Segoe UI', Arial, sans-serif;
    background: #f4f6f9; color: #1a1a2e; padding: 24px;
}
h1 { font-size: 1.5rem; color: #0f3460; margin-bottom: 4px; }
h2 { font-size: 1.05rem; color: #0f3460; margin: 20px 0 8px; }
a { color: #0f3460; }
nav { font-size: 0.85rem; margin-bottom: 12px; }
table { width: 100%; border-collapse: collapse; margin-bottom: 16px; font-size: 0.88rem; }
th { background: #0f3460; color: #fff; padding: 8px 12px; text-align: left; }
td { padding: 7px 12px; border-bottom: 1px solid #e4e4e4; }
tr:nth-child(even) td { background: #f9f9f9; }
.badge {
    display: inline-block; padding: 2px 8px; border-radius: 12px;
    font-size: 0.78rem; font-weight: 600;
}
.ok { background: #d4edda; color: #155724; }
.warn { background: #fff3cd; color: #856404; }
.err { background: #f8d7da; color: #721c24; }
.meta { font-size: 0.82rem; color: #4a4a5e; margin-bottom: 8px; }
.empty { font-size: 0.9rem; color: #4a4a5e; padding: 8px 0; }
.dqt-track { fill: #e0e0e0; }
.dqt-fill, .dqt-bar { fill: #0f3460; }
.dqt-unmeasured { display: none; }
.dqt-bar-label, .dqt-bar-value { font-size: 11px; fill: #1a1a2e; }
.dqt-figure { margin: 0 0 12px 0; }
.dqt-chart-text { font-size: 0.78rem; color: #4a4a5e; margin-top: 2px; }
.dqt-cards { display: flex; flex-wrap: wrap; gap: 16px; margin-bottom: 16px; }
.dqt-severity { vertical-align: middle; margin-right: 4px; }
.dqt-severity-info { fill: #17a2b8; }
.dqt-severity-warning { fill: #ffc107; }
.dqt-severity-error { fill: #dc3545; }
.dqt-severity-critical { fill: #721c24; }
"""


def _status_badge(status: str) -> Raw:
    """Render a run status as a labelled badge.

    Args:
        status: The run's status. An unrecognised one renders as an error
            rather than being styled as healthy.

    Returns:
        The badge markup.

    Example:
        assert "failed" in _status_badge("failed")
    """
    return element("span", status, attrs={"class": f"badge {_STATUS_CLASSES.get(status, 'err')}"})


def _chart_block(chart: Chart) -> Raw:
    """Place a chart beside the words that say the same thing.

    The equivalent is shown rather than hidden: a sighted reader gets the
    numbers without hovering, and nothing is maintained twice.

    Args:
        chart: The chart to place.

    Returns:
        The figure markup.

    Example:
        block = _chart_block(bar_chart([("a", 1)], title="t"))
    """
    return element(
        "figure",
        Raw(chart.svg),
        element("figcaption", chart.text, attrs={"class": "dqt-chart-text"}),
        attrs={"class": "dqt-figure"},
    )


def _run_header(run: Mapping[str, Any]) -> Raw:
    """Render the run's identity and status, above everything else.

    Position is part of the contract. A status badge below three tables is a
    badge nobody reads, and `docs/PLAN-VIZ-UI.md` §3 asks for a degraded run
    to be impossible to mistake for a healthy one.

    Args:
        run: A run dict from :mod:`dqt.ui.api`.

    Returns:
        The header markup.

    Example:
        header = _run_header(run)
    """
    version = run.get("dqt_version") or "unknown"
    return element(
        "div",
        element("h1", f"Run {run['run_id']}"),
        element(
            "p",
            _status_badge(str(run.get("status", ""))),
            Raw(" &middot; "),
            f"connection {run.get('connection_id', '')}",
            Raw(" &middot; "),
            f"started {run.get('started_at', '')}",
            Raw(" &middot; "),
            f"DQT {version}",
            attrs={"class": "meta"},
        ),
    )


def _dimension_cards(scores: Mapping[str, float | None]) -> Raw:
    """Render one scorecard per dimension, measured or not.

    Every dimension in the vocabulary appears, including the ones nothing
    measured. Showing only what was measured invites a reader to assume the
    rest was fine.

    Args:
        scores: Score per dimension; a missing or None entry means nothing
            measured it.

    Returns:
        The section markup.

    Example:
        cards = _dimension_cards({"completeness": 0.5})
    """
    cards = [
        _chart_block(scorecard(dimension, score=scores.get(dimension)))
        for dimension in sorted(get_args_of_dq_dimension())
    ]
    return element(
        "section",
        element("h2", "Quality by dimension"),
        element("div", *cards, attrs={"class": "dqt-cards"}),
    )


def _counts_chart(counts: Mapping[str, int], *, title: str) -> Raw:
    """Chart a mapping of counts.

    Args:
        counts: Label to count.
        title: Heading for the chart.

    Returns:
        The section markup.

    Example:
        section = _counts_chart({"error": 2}, title="Issues by severity")
    """
    chart = bar_chart(
        [(label, float(count)) for label, count in sorted(counts.items())], title=title
    )
    return element("section", element("h2", title), _chart_block(chart))


def _breadcrumbs(*trail: tuple[str, str | None]) -> Raw:
    """Render a breadcrumb trail.

    No dead ends: every view links onward and back.

    Args:
        *trail: ``(label, href)`` pairs. A None href renders as plain text,
            which is what the current page should be.

    Returns:
        The navigation markup.

    Example:
        nav = _breadcrumbs(("Overview", "/ui"), ("Run", None))
    """
    parts: list[object] = []
    for index, (label, href) in enumerate(trail):
        if index:
            parts.append(Raw(" / "))
        parts.append(element("a", label, attrs={"href": href}) if href else label)
    return element("nav", *parts)


def _page(title: str, *sections: object) -> str:
    """Wrap sections in a complete, self-contained document.

    Args:
        title: Document title.
        *sections: Body content.

    Returns:
        The page HTML.

    Example:
        html = _page("Overview", element("h1", "hi"))
    """
    return document(title=f"DQT - {title}", body=element("div", *sections), css=_CSS)


def overview_page(
    *,
    runs: Sequence[Mapping[str, Any]],
    run: Mapping[str, Any] | None,
    dimension_scores: Mapping[str, float | None],
    issues_by_severity: Mapping[str, int],
    issues_by_dimension: Mapping[str, int],
) -> str:
    """Render the overview: how is this run, and where do I look first.

    Args:
        runs: Recent runs, newest first.
        run: The run being summarised, or None when there are none.
        dimension_scores: Score per dimension; absent means not measured.
        issues_by_severity: Issue counts by severity.
        issues_by_dimension: Issue counts by dimension.

    Returns:
        The page HTML.

    Example:
        html = overview_page(
            runs=[], run=None, dimension_scores={},
            issues_by_severity={}, issues_by_dimension={},
        )
    """
    if run is None:
        return _page(
            "Overview",
            _breadcrumbs(("Overview", None)),
            element("h1", "DQT"),
            element("p", "No runs recorded yet.", attrs={"class": "empty"}),
        )

    recent = table(
        ["Run", "Status", "Started", "Connection"],
        [
            [
                element("a", str(entry["run_id"]), attrs={"href": f"/ui/runs/{entry['run_id']}"}),
                _status_badge(str(entry.get("status", ""))),
                entry.get("started_at", ""),
                entry.get("connection_id", ""),
            ]
            for entry in runs
        ],
    )

    return _page(
        "Overview",
        _breadcrumbs(("Overview", None)),
        _run_header(run),
        _dimension_cards(dimension_scores),
        _counts_chart(issues_by_dimension, title="Issues by dimension"),
        _counts_chart(issues_by_severity, title="Issues by severity"),
        element("h2", "Recent runs"),
        recent,
    )


def run_page(
    *,
    run: Mapping[str, Any],
    tables: Sequence[Mapping[str, Any]],
    dimension_scores: Mapping[str, float | None],
    issues_by_severity: Mapping[str, int],
) -> str:
    """Render the explorer: which table is worst.

    Args:
        run: The run being explored.
        tables: Table summaries, each with at least ``table_name``.
        dimension_scores: Score per dimension; absent means not measured.
        issues_by_severity: Issue counts by severity.

    Returns:
        The page HTML.

    Example:
        html = run_page(
            run=run, tables=[], dimension_scores={}, issues_by_severity={}
        )
    """
    rows = [
        [
            entry.get("schema_name") or "",
            entry.get("table_name") or "",
            entry.get("issue_count", 0),
        ]
        for entry in tables
    ]
    body = (
        table(["Schema", "Table", "Issues"], rows)
        if rows
        else element("p", "No tables were profiled in this run.", attrs={"class": "empty"})
    )

    return _page(
        f"Run {run['run_id']}",
        _breadcrumbs(("Overview", "/ui"), (f"Run {run['run_id']}", None)),
        _run_header(run),
        _dimension_cards(dimension_scores),
        _counts_chart(issues_by_severity, title="Issues by severity"),
        element("h2", "Tables"),
        body,
        element(
            "p",
            element("a", "View issues", attrs={"href": f"/ui/runs/{run['run_id']}/issues"}),
        ),
    )


def issues_page(
    *,
    run: Mapping[str, Any],
    issues: Sequence[Mapping[str, Any]],
    total: int,
) -> str:
    """Render the issue list: what is wrong, and enough context to act.

    The list is bounded. Showing fifty of four thousand without saying so
    would be a lie by omission, so the count of what the bound hid is on the
    page.

    Args:
        run: The run the issues belong to.
        issues: The page of issues to show.
        total: How many issues the run has in all.

    Returns:
        The page HTML.

    Example:
        html = issues_page(run=run, issues=[], total=0)
    """
    rows = [
        [
            _severity_cell(str(issue.get("severity", ""))),
            issue.get("dimension", ""),
            issue.get("table_name") or "",
            issue.get("column_name") or "",
            issue.get("message", ""),
        ]
        for issue in issues
    ]
    body = (
        table(["Severity", "Dimension", "Table", "Column", "Message"], rows)
        if rows
        else element("p", "No issues were found in this run.", attrs={"class": "empty"})
    )

    shown = element(
        "p",
        f"Showing {len(issues)} of {total} issue(s).",
        attrs={"class": "meta"},
    )

    return _page(
        f"Issues - {run['run_id']}",
        _breadcrumbs(
            ("Overview", "/ui"),
            (f"Run {run['run_id']}", f"/ui/runs/{run['run_id']}"),
            ("Issues", None),
        ),
        _run_header(run),
        element("h2", "Issues"),
        shown,
        body,
    )


def _severity_cell(severity: str) -> Raw:
    """Render a severity as a shape and its word.

    Args:
        severity: The issue's severity.

    Returns:
        The cell markup. An unfamiliar severity renders as a plain label
        rather than raising: a page is rendered after the fact, and refusing
        to draw one would lose the whole screen.

    Example:
        cell = _severity_cell("error")
    """
    try:
        indicator = severity_indicator(severity)
    except ValueError:
        return element("span", severity, attrs={"class": "badge"})
    return Raw(indicator.svg + element("span", severity, attrs={"class": "badge"}))
