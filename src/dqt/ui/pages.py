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
    raise NotImplementedError


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
    raise NotImplementedError


def issues_page(
    *,
    run: Mapping[str, Any],
    issues: Sequence[Mapping[str, Any]],
    total: int,
) -> str:
    """Render the issue list: what is wrong, and enough context to act.

    Args:
        run: The run the issues belong to.
        issues: The page of issues to show.
        total: How many issues the run has in all.

    Returns:
        The page HTML.

    Example:
        html = issues_page(run=run, issues=[], total=0)
    """
    raise NotImplementedError
