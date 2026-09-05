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
from dqt._theme import STYLESHEET
from dqt.common.models import get_args_of_dq_dimension
from dqt.fonts import embedded_font_face
from dqt.i18n import Language, ltr_span, translate
from dqt.viz import Chart, bar_chart, scorecard, severity_indicator, trend_line

__all__ = [
    "issues_page",
    "overview_page",
    "rule_history_page",
    "rules_page",
    "run_page",
]

#: How many issues a page shows. The size of a response must not depend on
#: how bad the data is -- the rule DQIssue evidence already follows.
ISSUE_PAGE_SIZE = 50

#: Keys the glossary can translate when they appear as chart labels.
#:
#: Severities and dimensions are vocabulary; a table name is not, and passing
#: one to the glossary would raise on data rather than on a programming
#: mistake.
TRANSLATABLE = frozenset(
    {
        "completeness",
        "validity",
        "uniqueness",
        "consistency",
        "referential_integrity",
        "timeliness",
        "info",
        "warning",
        "error",
        "critical",
    }
)

#: How each run status is rendered. The word is the part that always works.
_STATUS_CLASSES = {"success": "ok", "partial": "warn", "failed": "err"}


def _status_badge(status: str, language: Language) -> Raw:
    """Render a run status as a labelled badge.

    Args:
        status: The run's status. An unrecognised one renders as an error
            rather than being styled as healthy.

    Returns:
        The badge markup.

    Example:
        assert "failed" in _status_badge("failed")
    """
    label = translate(status, language) if status in _STATUS_CLASSES else status
    return element("span", label, attrs={"class": f"badge {_STATUS_CLASSES.get(status, 'err')}"})


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


def _run_header(run: Mapping[str, Any], language: Language) -> Raw:
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
        element(
            "h1",
            f"{translate('run', language)} ",
            Raw(ltr_span(run["run_id"])),
        ),
        element(
            "p",
            _status_badge(str(run.get("status", "")), language),
            Raw(" &middot; "),
            f"{translate('connection', language)} ",
            Raw(ltr_span(run.get("connection_id", ""))),
            Raw(" &middot; "),
            f"{translate('started', language)} ",
            Raw(ltr_span(run.get("started_at", ""))),
            Raw(" &middot; DQT "),
            Raw(ltr_span(version)),
            attrs={"class": "meta"},
        ),
    )


def _dimension_cards(scores: Mapping[str, float | None], language: Language) -> Raw:
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
        _chart_block(scorecard(translate(dimension, language), score=scores.get(dimension)))
        for dimension in sorted(get_args_of_dq_dimension())
    ]
    return element(
        "section",
        element("h2", translate("quality_by_dimension", language)),
        element("div", *cards, attrs={"class": "dqt-cards"}),
    )


def _counts_chart(counts: Mapping[str, int], *, title: str, language: Language) -> Raw:
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
        [
            (translate(label, language) if label in TRANSLATABLE else label, float(count))
            for label, count in sorted(counts.items())
        ],
        title=title,
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


def _page(title: str, language: Language, *sections: object) -> str:
    """Wrap sections in a complete, self-contained document.

    Args:
        title: Document title.
        *sections: Body content.

    Returns:
        The page HTML.

    Example:
        html = _page("Overview", element("h1", "hi"))
    """
    # The font is prepended rather than appended so a reader's own stylesheet
    # overrides can still win, and so an English page pays nothing for it.
    return document(
        title=f"DQT - {title}",
        body=element("div", *sections),
        css=embedded_font_face(language) + STYLESHEET,
        language=language,
    )


def overview_page(
    *,
    runs: Sequence[Mapping[str, Any]],
    run: Mapping[str, Any] | None,
    dimension_scores: Mapping[str, float | None],
    issues_by_severity: Mapping[str, int],
    issues_by_dimension: Mapping[str, int],
    language: Language = "en",
) -> str:
    """Render the overview: how is this run, and where do I look first.

    Args:
        runs: Recent runs, newest first.
        run: The run being summarised, or None when there are none.
        dimension_scores: Score per dimension; absent means not measured.
        issues_by_severity: Issue counts by severity.
        issues_by_dimension: Issue counts by dimension.
        language: Which language to render in. Persian lays the page out
            right-to-left, but identifiers and numbers keep their own
            direction -- a reordered table name is wrong while still looking
            like data.

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
            translate("overview", language),
            language,
            _breadcrumbs((translate("overview", language), None)),
            element("h1", "DQT"),
            element("p", translate("no_runs", language), attrs={"class": "empty"}),
        )

    recent = table(
        [
            translate("run", language),
            translate("status", language),
            translate("started", language),
            translate("connection", language),
        ],
        [
            [
                element(
                    "a",
                    Raw(ltr_span(entry["run_id"])),
                    attrs={"href": f"/ui/runs/{entry['run_id']}"},
                ),
                _status_badge(str(entry.get("status", "")), language),
                Raw(ltr_span(entry.get("started_at", ""))),
                Raw(ltr_span(entry.get("connection_id", ""))),
            ]
            for entry in runs
        ],
    )

    return _page(
        translate("overview", language),
        language,
        _breadcrumbs((translate("overview", language), None)),
        _run_header(run, language),
        _dimension_cards(dimension_scores, language),
        _counts_chart(
            issues_by_dimension,
            title=translate("issues_by_dimension", language),
            language=language,
        ),
        _counts_chart(
            issues_by_severity,
            title=translate("issues_by_severity", language),
            language=language,
        ),
        element("h2", translate("recent_runs", language)),
        recent,
    )


def run_page(
    *,
    run: Mapping[str, Any],
    tables: Sequence[Mapping[str, Any]],
    dimension_scores: Mapping[str, float | None],
    issues_by_severity: Mapping[str, int],
    language: Language = "en",
) -> str:
    """Render the explorer: which table is worst.

    Args:
        run: The run being explored.
        tables: Table summaries, each with at least ``table_name``.
        dimension_scores: Score per dimension; absent means not measured.
        issues_by_severity: Issue counts by severity.
        language: Which language to render in.

    Returns:
        The page HTML.

    Example:
        html = run_page(
            run=run, tables=[], dimension_scores={}, issues_by_severity={}
        )
    """
    rows: list[list[object]] = [
        [
            Raw(ltr_span(entry.get("schema_name") or "")),
            Raw(ltr_span(entry.get("table_name") or "")),
            entry.get("issue_count", 0),
        ]
        for entry in tables
    ]
    body = (
        table(
            [
                translate("schema", language),
                translate("table", language),
                translate("issues", language),
            ],
            rows,
        )
        if rows
        else element("p", translate("no_tables", language), attrs={"class": "empty"})
    )
    heading = f"{translate('run', language)} {run['run_id']}"

    return _page(
        heading,
        language,
        _breadcrumbs((translate("overview", language), "/ui"), (heading, None)),
        _run_header(run, language),
        _dimension_cards(dimension_scores, language),
        _counts_chart(
            issues_by_severity,
            title=translate("issues_by_severity", language),
            language=language,
        ),
        element("h2", translate("tables", language)),
        body,
        element(
            "p",
            element(
                "a",
                translate("view_issues", language),
                attrs={"href": f"/ui/runs/{run['run_id']}/issues"},
            ),
        ),
    )


def issues_page(
    *,
    run: Mapping[str, Any],
    issues: Sequence[Mapping[str, Any]],
    total: int,
    language: Language = "en",
) -> str:
    """Render the issue list: what is wrong, and enough context to act.

    The list is bounded. Showing fifty of four thousand without saying so
    would be a lie by omission, so the count of what the bound hid is on the
    page.

    Args:
        run: The run the issues belong to.
        issues: The page of issues to show.
        total: How many issues the run has in all.
        language: Which language to render in.

    Returns:
        The page HTML.

    Example:
        html = issues_page(run=run, issues=[], total=0)
    """
    rows: list[list[object]] = [
        [
            _severity_cell(str(issue.get("severity", "")), language),
            _translated_or_raw(str(issue.get("dimension", "")), language),
            Raw(ltr_span(issue.get("table_name") or "")),
            Raw(ltr_span(issue.get("column_name") or "")),
            issue.get("message", ""),
        ]
        for issue in issues
    ]
    body = (
        table(
            [
                translate("severity", language),
                translate("dimension", language),
                translate("table", language),
                translate("column", language),
                translate("message", language),
            ],
            rows,
        )
        if rows
        else element("p", translate("no_issues", language), attrs={"class": "empty"})
    )

    shown = element(
        "p",
        Raw(ltr_span(len(issues))),
        " / ",
        Raw(ltr_span(total)),
        attrs={"class": "meta"},
    )
    heading = f"{translate('issues', language)} - {run['run_id']}"

    return _page(
        heading,
        language,
        _breadcrumbs(
            (translate("overview", language), "/ui"),
            (
                f"{translate('run', language)} {run['run_id']}",
                f"/ui/runs/{run['run_id']}",
            ),
            (translate("issues", language), None),
        ),
        _run_header(run, language),
        element("h2", translate("issues", language)),
        shown,
        body,
    )


def _translated_or_raw(value: str, language: Language) -> str:
    """Translate *value* when it is vocabulary, and leave it alone otherwise.

    A dimension is vocabulary; a value that arrived from an older store, or
    from a future DQT, is data. Passing data to the glossary would raise on
    a row rather than on a programming mistake, and lose the page.

    Args:
        value: The word to render.
        language: Which language to render in.

    Returns:
        The translated word, or *value* unchanged.

    Example:
        assert _translated_or_raw("completeness", "en") == "completeness"
    """
    return translate(value, language) if value in TRANSLATABLE else value


def _severity_cell(severity: str, language: Language) -> Raw:
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
    label = _translated_or_raw(severity, language)
    try:
        indicator = severity_indicator(severity)
    except ValueError:
        return element("span", label, attrs={"class": "badge"})
    return Raw(indicator.svg + element("span", label, attrs={"class": "badge"}))


def rules_page(
    *,
    run: Mapping[str, Any],
    results: Sequence[Mapping[str, Any]],
    language: Language = "en",
) -> str:
    """Render what each rule did in one run.

    The rules that matched nothing are called out above the table, in words.
    A rule whose scope no longer matches anything reports no failures, which
    reads exactly like a rule that passes -- and it sits in the same table,
    next to real passes, showing the same zero. A zero in a column of zeroes
    is invisible, so the warning has to be a sentence and it has to be first.

    Args:
        run: The run the results belong to.
        results: One summary per rule evaluated.
        language: Which language to render in.

    Returns:
        The page HTML.

    Example:
        html = rules_page(run=run, results=[])
    """
    orphans = [
        str(entry["rule_name"]) for entry in results if int(entry.get("targets_checked", 0)) == 0
    ]
    # Only when there is something to say. A permanent banner is a banner
    # people stop reading, which costs the attention this screen exists to buy.
    warning: list[object] = []
    if orphans:
        warning = [
            element(
                "p",
                translate("matched_nothing", language),
                " ",
                Raw(", ".join(ltr_span(name) for name in sorted(orphans))),
                attrs={"class": "badge warn"},
            )
        ]

    rows: list[list[object]] = [
        [
            element(
                "a",
                Raw(ltr_span(entry["rule_name"])),
                attrs={"href": f"/ui/rules/{entry['rule_name']}"},
            ),
            entry.get("targets_checked", 0),
            entry.get("targets_failed", 0),
            entry.get("targets_error", 0),
        ]
        for entry in results
    ]
    body = (
        table(
            [
                translate("rule", language),
                translate("targets_checked", language),
                translate("targets_failed", language),
                translate("targets_error", language),
            ],
            rows,
        )
        if rows
        else element("p", translate("no_rules", language), attrs={"class": "empty"})
    )

    heading = translate("rules", language)
    return _page(
        heading,
        language,
        _breadcrumbs(
            (translate("overview", language), "/ui"),
            (
                f"{translate('run', language)} {run['run_id']}",
                f"/ui/runs/{run['run_id']}",
            ),
            (heading, None),
        ),
        _run_header(run, language),
        element("h2", heading),
        *warning,
        body,
    )


def rule_history_page(
    *,
    rule_name: str,
    history: Sequence[Mapping[str, Any]],
    language: Language = "en",
) -> str:
    """Render one rule's results across runs.

    Charted oldest-first. The store returns history newest-first, which is
    right for a list and wrong for a time axis: plotting it as given would
    draw every improving rule as though it were getting worse.

    Args:
        rule_name: The rule being followed.
        history: Its results, newest first.
        language: Which language to render in.

    Returns:
        The page HTML.

    Example:
        html = rule_history_page(rule_name="r", history=[])
    """
    oldest_first = list(reversed(list(history)))
    chart = trend_line(
        [
            (
                str(entry.get("started_at", ""))[:10],
                _pass_rate(entry),
            )
            for entry in oldest_first
        ],
        title=f"{translate('rule', language)} {rule_name}",
    )

    rows: list[list[object]] = [
        [
            Raw(ltr_span(entry.get("run_id", ""))),
            Raw(ltr_span(entry.get("started_at", ""))),
            entry.get("targets_checked", 0),
            entry.get("targets_failed", 0),
            entry.get("targets_error", 0),
        ]
        for entry in history
    ]
    body = (
        table(
            [
                translate("run", language),
                translate("started", language),
                translate("targets_checked", language),
                translate("targets_failed", language),
                translate("targets_error", language),
            ],
            rows,
        )
        if rows
        else element("p", translate("no_history", language), attrs={"class": "empty"})
    )

    heading = f"{translate('rule', language)} {rule_name}"
    return _page(
        heading,
        language,
        _breadcrumbs(
            (translate("overview", language), "/ui"),
            (translate("history", language), None),
        ),
        element("h1", Raw(ltr_span(rule_name))),
        element("h2", translate("history", language)),
        _chart_block(chart),
        body,
    )


def _pass_rate(entry: Mapping[str, Any]) -> float:
    """Return the share of a rule's targets that passed in one run.

    Args:
        entry: One history entry.

    Returns:
        A value in ``[0, 1]``. A rule that matched nothing scores 0.0 rather
        than 1.0: it did not pass, it did not run, and drawing it at the top
        of the chart would say the opposite.

    Example:
        assert _pass_rate({"targets_checked": 2, "targets_failed": 1}) == 0.5
    """
    checked = int(entry.get("targets_checked", 0))
    if checked <= 0:
        return 0.0
    bad = int(entry.get("targets_failed", 0)) + int(entry.get("targets_error", 0))
    return max(0.0, (checked - bad) / checked)
