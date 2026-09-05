"""
HTML report generator for DQT SQL pipelines.

This module produces a self-contained HTML report from a PipelineResult.
The report is DBA-oriented and shows:
- Run summary (run_id, status, started/ended, duration).
- Per-table completeness scores and row counts.
- Per-column null counts and completeness scores.
- Detected issues grouped by severity.

The output is a single HTML file with inline CSS; no external dependencies.
"""

from __future__ import annotations

import html
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from dqt._html import Raw, document, element, table
from dqt.common.models import DQMetric, PipelineResult, get_args_of_dq_dimension
from dqt.viz import Chart, bar_chart, scorecard, severity_indicator

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_html_report(result: PipelineResult, output_path: Path | str | None = None) -> Path:
    """Generate a self-contained HTML DQ report from a PipelineResult.

    The report includes a run summary, per-table completeness scores, per-column
    null counts, and a grouped issue list.  It is written to *output_path*; if
    not supplied a file named ``dqt_report_<run_id>.html`` is created in the
    current working directory.

    Args:
        result: Completed PipelineResult from ``DQTPipeline.run()``.
        output_path: Optional destination path for the HTML file.

    Returns:
        The resolved ``Path`` of the written report file.

    Example:
        path = generate_html_report(result, output_path="/tmp/report.html")
        print(f"Report written to {path}")
    """
    if output_path is None:
        output_path = Path.cwd() / f"dqt_report_{result.run_id}.html"
    output_path = Path(output_path)
    # Create the directory rather than raising FileNotFoundError from
    # write_text. RunStore already does this for its own file, and a caller
    # who names a path is asking for the file to be there.
    output_path.parent.mkdir(parents=True, exist_ok=True)

    html_content = _render(result)
    output_path.write_text(html_content, encoding="utf-8")
    return output_path


def generate_report(
    result: PipelineResult, output_path: Path | str | None = None
) -> dict[str, str]:
    """Compatibility wrapper used by the pipeline orchestrator.

    Writes the HTML report and returns a small descriptor dictionary so the
    pipeline stage interface remains uniform.

    Args:
        result: Completed PipelineResult.
        output_path: Optional destination path.

    Returns:
        Dict with keys ``status``, ``run_id``, and ``report_path``.

    Example:
        descriptor = generate_report(result)
    """
    path = generate_html_report(result, output_path=output_path)
    return {
        "status": result.status,
        "run_id": result.run_id,
        "report_path": str(path),
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: 'Segoe UI', Arial, sans-serif;
    background: #f4f6f9; color: #1a1a2e; padding: 24px;
}
h1 { font-size: 1.6rem; margin-bottom: 4px; color: #0f3460; }
h2 {
    font-size: 1.1rem; margin: 24px 0 8px; color: #16213e;
    border-bottom: 2px solid #e0e0e0; padding-bottom: 4px;
}
.meta { font-size: 0.85rem; color: #555; margin-bottom: 16px; }
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

/* Charts from dqt.viz. The SVG carries no colour of its own so that the page
   decides how a chart looks -- which is what lets one set of primitives serve
   both the report and the pages that read from the same store. */
.dqt-track { fill: #e0e0e0; }
.dqt-fill, .dqt-bar { fill: #0f3460; }
.dqt-scorecard, .dqt-score-bar { vertical-align: middle; }
.dqt-unmeasured { display: none; }
.dqt-bar-label, .dqt-bar-value { font-size: 11px; fill: #1a1a2e; }
.dqt-figure { margin: 0 0 12px 0; }
/* The text equivalent is shown, not hidden. A sighted reader gets the numbers
   without hovering, and nothing has to be maintained twice. */
.dqt-chart-text { font-size: 0.78rem; color: #4a4a5e; margin-top: 2px; }
.dqt-cards {
    display: flex; flex-wrap: wrap; gap: 16px; margin-bottom: 16px;
}
.dqt-severity { vertical-align: middle; margin-right: 4px; }
.dqt-severity-info { fill: #17a2b8; }
.dqt-severity-warning { fill: #ffc107; }
.dqt-severity-error { fill: #dc3545; }
.dqt-severity-critical { fill: #721c24; }
"""


def _score_badge(score: float) -> Raw:
    """Render a score as a bar and a percentage.

    Drawn by :func:`dqt.viz.scorecard` rather than by hand, so the report and
    the pages that come later cannot drift apart. The text equivalent rides
    beside the bar, which is where the accessibility requirement is actually
    met.

    Args:
        score: A value in ``[0, 1]``.

    Returns:
        The badge markup.

    Example:
        assert "50%" in _score_badge(0.5)
    """
    card = scorecard("score", score=score)
    return Raw(
        card.svg + element("span", card.text.removeprefix("score: "), attrs={"class": "badge"})
    )


#: How each run status is rendered: CSS class, and the word the reader sees.
#:
#: The word matters more than the colour. A report that renders a failed run
#: as a healthy one is worse than no report, and the three statuses have to
#: stay three -- "something went wrong" and "everything went wrong" lead to
#: different decisions.
_STATUS_CLASSES: dict[str, str] = {"success": "ok", "partial": "warn", "failed": "err"}


def _status_badge(status: str) -> str:
    """Render a run's status as a labelled badge.

    Args:
        status: One of ``"success"``, ``"partial"`` or ``"failed"``. An
            unrecognised value is rendered as an error rather than silently
            styled as healthy.

    Returns:
        An HTML span carrying the status word as text, so the meaning does
        not depend on the colour.

    Example:
        assert "failed" in _status_badge("failed")
    """
    return f'<span class="badge {_STATUS_CLASSES.get(status, "err")}">{html.escape(status)}</span>'


def _severity_badge(severity: str) -> Raw:
    """Render a severity as a shape and its word.

    Colour alone is unreadable to roughly 8% of men, and DBAs are exactly the
    audience that stares at these tables all day, so the mark and the label
    both carry the meaning. Unknown severities fall back to a plain label
    rather than raising: a report is rendered after the run, and refusing to
    draw one because a severity was unfamiliar would lose the whole page.

    Args:
        severity: The issue's severity.

    Returns:
        The badge markup.

    Example:
        assert "error" in _severity_badge("error")
    """
    try:
        indicator = severity_indicator(severity)
    except ValueError:
        return element("span", severity, attrs={"class": "badge"})
    return Raw(indicator.svg + element("span", severity, attrs={"class": "badge"}))


def _duration(started: datetime | None, ended: datetime | None) -> str:
    if started is None or ended is None:
        return "n/a"
    delta = ended - started
    secs = delta.total_seconds()
    if secs < 60:
        return f"{secs:.1f}s"
    return f"{int(secs // 60)}m {int(secs % 60)}s"


def _metric_lookup(
    metrics: list[DQMetric],
    dimension: str,
    schema: str | None = None,
    table: str | None = None,
    column: str | None = None,
) -> DQMetric | None:
    for m in metrics:
        if m.dimension != dimension:
            continue
        if schema is not None and m.schema_name != schema:
            continue
        if table is not None and m.table_name != table:
            continue
        if column is not None and m.column_name != column:
            continue
        return m
    return None


def _external_section(result: PipelineResult) -> str:
    """Render findings contributed by sibling analysers, or nothing.

    ``PipelineResult.external_analyses`` is written only by
    :mod:`dqt.bridges`; DQT core never populates it. When no bridge ran the
    section is omitted entirely rather than rendered empty, because an empty
    "Missing Data" heading would read as "we looked and found nothing", which
    is a different claim from not having looked.

    Every value here originates outside DQT -- column names come from the
    user's database and the payload has passed through a third-party package
    -- and the output is a file a DBA opens in a browser, so all of it is
    escaped.

    Args:
        result: Pipeline result whose external analyses to render.

    Returns:
        An HTML section, or an empty string when there are none.

    Example:
        section = _external_section(result)
    """
    if not result.external_analyses:
        return ""

    blocks: list[str] = []
    for analyzer, tables in sorted(result.external_analyses.items()):
        rows = ""
        for qualified_name, payload in sorted(tables.items()):
            sampled = payload.get("sampled_rows", "n/a")
            for column in payload.get("columns", []):
                ratio = column.get("missing_ratio")
                pct = f"{ratio * 100:.0f}%" if isinstance(ratio, int | float) else "n/a"
                rows += (
                    "<tr>"
                    f"<td>{html.escape(str(qualified_name))}</td>"
                    f"<td>{html.escape(str(column.get('column_name', '')))}</td>"
                    f"<td>{html.escape(str(column.get('missing_count', 'n/a')))}</td>"
                    f"<td>{html.escape(pct)}</td>"
                    f"<td>{html.escape(str(sampled))}</td>"
                    "</tr>"
                )
            for note in payload.get("notes", []):
                rows += f'<tr><td colspan="5">{html.escape(str(note))}</td></tr>'

        if not rows:
            continue
        header = (
            "<tr><th>Table</th><th>Column</th><th>Missing</th>"
            "<th>Missing %</th><th>Rows sampled</th></tr>"
        )
        blocks.append(
            f"<h3>{html.escape(analyzer)}</h3>"
            '<p class="meta">Computed by an external analyser, not by DQT. '
            "Figures describe the sampled rows only.</p>"
            f"<table>{header}{rows}</table>"
        )

    if not blocks:
        return ""
    return "<h2>Missing Data (sibling package)</h2>" + "".join(blocks)


def _stage_error_section(result: PipelineResult) -> str:
    """Render the stages that failed, or nothing at all.

    ``NEW-B`` gave a run the ability to report failure; this is where it
    reaches a person. A ``partial`` status with no explanation tells a DBA
    that something is wrong and nothing about what, and ``StageError.message``
    is written to be actionable, so dropping it wastes the part of a failure
    designed to be read.

    Returns nothing when there is nothing to say. An empty panel implies
    something is missing or broken -- the same rule the missingness panel
    follows.

    Args:
        result: The completed run.

    Returns:
        An HTML section, or the empty string when no stage failed.

    Example:
        assert _stage_error_section(clean_result) == ""
    """
    if not result.stage_errors:
        return ""

    rows = "".join(
        f"<tr><td>{html.escape(error.stage)}</td>"
        f"<td>{html.escape(error.exception_type)}</td>"
        f"<td>{html.escape(error.message)}</td></tr>"
        for error in result.stage_errors
    )
    return (
        "<h2>Stage Errors</h2>"
        "<p>These stages did not complete. Numbers below are computed from "
        "whatever did.</p>"
        "<table><tr><th>Stage</th><th>Error</th><th>Message</th></tr>"
        f"{rows}</table>"
    )


def _chart_block(chart: Chart) -> Raw:
    """Place a chart and its text equivalent on the page together.

    :class:`~dqt.viz.Chart` returns them as one value so the pair cannot be
    split; this is the other half of that -- putting the equivalent into the
    document rather than keeping it.

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


def _dimension_scores(result: PipelineResult) -> dict[str, float | None]:
    """Average each dimension's metrics, or report that none exist.

    Derived from ``PipelineResult.metrics`` -- the flat canonical list --
    rather than from the nested per-table views, which are navigation and
    would double-count.

    Every dimension in the vocabulary gets an entry, including the ones
    nothing measured. A report that lists only what it measured lets a reader
    assume the rest was fine, and DQT measures completeness today and little
    else.

    Args:
        result: The completed run.

    Returns:
        A score in ``[0, 1]`` per dimension, or None where nothing measured
        it.

    Example:
        scores = _dimension_scores(result)
    """
    scores: dict[str, float | None] = {}
    for dimension in sorted(get_args_of_dq_dimension()):
        measured = [
            metric.score
            for metric in result.metrics
            if metric.dimension == dimension and metric.score is not None
        ]
        scores[dimension] = sum(measured) / len(measured) if measured else None
    return scores


def _dimension_section(result: PipelineResult) -> Raw:
    """Render one scorecard per dimension.

    Args:
        result: The completed run.

    Returns:
        The section markup.

    Example:
        section = _dimension_section(result)
    """
    cards = [
        _chart_block(scorecard(dimension, score=score))
        for dimension, score in _dimension_scores(result).items()
    ]
    return element(
        "section",
        element("h2", "Quality by dimension"),
        element("div", *cards, attrs={"class": "dqt-cards"}),
    )


def _issue_chart_section(result: PipelineResult) -> Raw:
    """Chart how many issues each dimension produced.

    Answers "where do I look first", which is the question an overview exists
    for. Counted from the canonical issue list.

    Args:
        result: The completed run.

    Returns:
        The section markup.

    Example:
        section = _issue_chart_section(result)
    """
    counts = Counter(issue.dimension for issue in result.issues)
    chart = bar_chart(
        [(dimension, float(count)) for dimension, count in sorted(counts.items())],
        title="Issues by dimension",
    )
    return element("section", element("h2", "Issues by dimension"), _chart_block(chart))


def _render(result: PipelineResult) -> str:
    """Assemble the whole report.

    Every fragment is built through :mod:`dqt._html`, which escapes content
    unless it is declared markup -- so a table named ``<b>`` stays a table
    name without anyone remembering to say so.

    Args:
        result: The completed run.

    Returns:
        The document text.

    Example:
        html = _render(result)
    """
    started_str = (
        result.started_at.strftime("%Y-%m-%d %H:%M:%S UTC") if result.started_at else "n/a"
    )
    ended_str = result.ended_at.strftime("%Y-%m-%d %H:%M:%S UTC") if result.ended_at else "n/a"

    summary = table(
        ["Field", "Value"],
        [
            ["Run ID", result.run_id],
            ["Status", _status_badge(result.status)],
            ["Started", started_str],
            ["Ended", ended_str],
            ["Duration", _duration(result.started_at, result.ended_at)],
            ["Tables scanned", len(result.tables)],
            ["Total issues", len(result.issues)],
            ["Total metrics", len(result.metrics)],
        ],
    )

    table_rows: list[list[object]] = []
    for _key, table_result in sorted(result.tables.items()):
        schema = table_result.schema_name
        name = table_result.table_name
        row_count_metric = _metric_lookup(result.metrics, "row_count", schema=schema, table=name)
        row_count = (
            int(row_count_metric.value)
            if row_count_metric and row_count_metric.value is not None
            else "n/a"
        )
        column_scores = [
            metric.score
            for metric in result.metrics
            if metric.dimension == "completeness"
            and metric.schema_name == schema
            and metric.table_name == name
            and metric.column_name is not None
            and metric.score is not None
        ]
        average = sum(column_scores) / len(column_scores) if column_scores else 1.0
        issue_count = sum(
            1 for issue in result.issues if issue.schema_name == schema and issue.table_name == name
        )
        table_rows.append([schema, name, row_count, _score_badge(average), issue_count])

    column_rows: list[list[object]] = []
    for _key, table_result in sorted(result.tables.items()):
        for column in table_result.columns:
            metric = _metric_lookup(
                result.metrics,
                "completeness",
                schema=column.schema_name,
                table=column.table_name,
                column=column.column_name,
            )
            null_count = int(metric.value) if metric and metric.value is not None else "n/a"
            score = metric.score if metric and metric.score is not None else 1.0
            column_rows.append(
                [
                    column.schema_name,
                    column.table_name,
                    column.column_name,
                    null_count,
                    _score_badge(score),
                ]
            )

    issue_rows: list[list[object]] = [
        [
            _severity_badge(issue.severity),
            issue.schema_name or "",
            issue.table_name or "",
            issue.column_name or "",
            issue.message,
        ]
        for issue in result.issues
    ]
    issue_section = (
        element(
            "section",
            element("h2", "Issues"),
            table(["Severity", "Schema", "Table", "Column", "Message"], issue_rows),
        )
        if issue_rows
        else element("section", element("h2", "Issues"), element("p", "No issues detected."))
    )

    generated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    body = element(
        "div",
        element("h1", "DQT Data Quality Report"),
        element(
            "p",
            f"Generated {generated_at} | Run: {result.run_id}",
            attrs={"class": "meta"},
        ),
        element("h2", "Run Summary"),
        summary,
        Raw(_stage_error_section(result)),
        _dimension_section(result),
        _issue_chart_section(result),
        element("h2", "Table Summary"),
        table(["Schema", "Table", "Rows", "Avg Completeness", "Issues"], table_rows),
        element("h2", "Column Metrics"),
        table(["Schema", "Table", "Column", "Null Count", "Completeness"], column_rows),
        issue_section,
        Raw(_external_section(result)),
    )

    return document(title=f"DQT Report - {result.run_id}", body=body, css=_CSS)
