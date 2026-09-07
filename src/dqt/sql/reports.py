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
import tempfile
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dqt._html import Raw, document, element, table
from dqt._theme import STYLESHEET
from dqt.common.models import DQMetric, PipelineResult, get_args_of_dq_dimension
from dqt.exceptions import ConfigurationError
from dqt.i18n import Language, translate
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


@dataclass(frozen=True, slots=True)
class ColumnReportRow:
    """One profiled column, as both renderers describe it.

    Named rather than positional on purpose. A shared ``list[object]`` is
    the arrangement where inserting a statistic silently shifts every field
    after it in one renderer and not the other -- and both would still
    typecheck, still run, and quietly mislabel every column in the report.

    Attributes:
        schema_name: Schema the column belongs to.
        table_name: Table the column belongs to.
        column_name: The column.
        db_type: Its database type, or ``"n/a"``.
        semantic_type: What classification recognised it as, or ``"n/a"``.
        null_count: NULL values, or ``"n/a"`` when not measured.
        distinct_count: Distinct values, or ``"n/a"``.
        minimum: Smallest value, or ``"n/a"``.
        maximum: Largest value, or ``"n/a"``.
        mean: Arithmetic mean, or ``"n/a"`` for a type with no mean.
        completeness: Score in ``[0, 1]``.

    Example:
        row = ColumnReportRow(
            schema_name="main",
            table_name="customers",
            column_name="email",
            db_type="TEXT",
            semantic_type="email",
            null_count=1,
            distinct_count=3,
            minimum="a@x.com",
            maximum="z@x.com",
            mean="n/a",
            completeness=0.75,
        )
    """

    schema_name: str
    table_name: str
    column_name: str
    db_type: str
    semantic_type: str
    null_count: object
    distinct_count: object
    minimum: object
    maximum: object
    mean: object
    completeness: float


def column_rows(result: PipelineResult) -> list[ColumnReportRow]:
    """Return one row per profiled column, as plain values.

    Shared by both renderers so that *what* a report describes is decided
    once. Values are undecorated -- a score is a float, not a badge -- and
    each renderer applies its own presentation.

    When `F1` added the mean and the distinct count, a second
    hand-maintained column list is exactly where they would have gone
    missing.

    Args:
        result: The completed run.

    Returns:
        One :class:`ColumnReportRow` per column, tables in name order.

    Example:
        rows = column_rows(result)
    """
    rows: list[ColumnReportRow] = []
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
            statistics = metric.metadata if metric and metric.metadata else {}
            rows.append(
                ColumnReportRow(
                    schema_name=column.schema_name,
                    table_name=column.table_name,
                    column_name=column.column_name,
                    db_type=column.db_type or "n/a",
                    semantic_type=column.semantic_type or "n/a",
                    null_count=null_count,
                    distinct_count=_statistic(statistics, "distinct_count"),
                    minimum=_statistic(statistics, "min_value"),
                    maximum=_statistic(statistics, "max_value"),
                    mean=_statistic(statistics, "mean_value"),
                    completeness=(metric.score if metric and metric.score is not None else 1.0),
                )
            )
    return rows


#: Cached across calls so the woff2 is decoded once per process rather than
#: once per report.
_CONVERTED_FONT: Path | None = None


def _import_pdf_backend() -> Any:
    """Import the PDF library, or explain which extra provides it.

    Follows the pattern the SQL Server dialect uses for ``pyodbc``: a bare
    ``ModuleNotFoundError`` tells a DBA nothing about what to install.

    Returns:
        The ``fpdf`` module.

    Raises:
        ConfigurationError: If the extra is not installed.

    Example:
        fpdf = _import_pdf_backend()
    """
    try:
        import fpdf
    except ImportError as error:
        raise ConfigurationError(
            "Writing a PDF needs the 'pdf' extra, which is not installed. "
            "Install it with: pip install 'dqt[pdf]'"
        ) from error
    return fpdf


def _pdf_font_path() -> Path:
    """Return a TrueType copy of the report font, converting once per process.

    The package ships Vazirmatn as ``woff2`` because that is what the HTML
    report embeds. No PDF library accepts a web font, so it is converted
    here -- by ``fonttools``, which the PDF backend already depends on, so
    the conversion costs no extra dependency and no second font asset ships.
    Reusing the same font is what keeps the two reports from disagreeing
    about which typeface they are.

    Written to a temporary directory rather than beside the packaged font.
    The first version wrote into the installed package, which works in a
    development checkout and fails wherever ``site-packages`` is read-only
    -- a container image, a system install, a locked-down server. It also
    left an untracked file in the source tree.

    Returns:
        Path to a ``.ttf``, created on first use and reused thereafter.

    Raises:
        ConfigurationError: If the conversion fails.

    Example:
        path = _pdf_font_path()
    """
    global _CONVERTED_FONT
    if _CONVERTED_FONT is not None and _CONVERTED_FONT.exists():
        return _CONVERTED_FONT

    source = Path(__file__).resolve().parents[1] / "fonts" / "Vazirmatn-Regular.woff2"
    target = Path(tempfile.gettempdir()) / "dqt-Vazirmatn-Regular.ttf"

    if not target.exists():
        try:
            from fontTools.ttLib import TTFont

            font = TTFont(str(source))
            # Clearing the flavor turns a web font back into a plain
            # TrueType one; the glyph data itself is untouched.
            font.flavor = None
            font.save(str(target))
        except Exception as error:  # noqa: BLE001 - the cause is what matters
            raise ConfigurationError(
                f"Could not prepare the report font for PDF output: {error}"
            ) from error

    _CONVERTED_FONT = target
    return target


def generate_pdf_report(
    result: PipelineResult,
    output_path: Path | str | None = None,
    language: Language = "en",
) -> Path:
    """Write a printable PDF of a completed run.

    A companion to :func:`generate_html_report` rather than a copy of it:
    the HTML report is the interactive artifact, this is the one that goes
    in an email to somebody who will never run DQT. Both describe the same
    columns, because :func:`column_rows` decides that once.

    Text shaping is enabled, which is what makes Persian render as joined
    letters in the right order rather than as disconnected forms.

    Args:
        result: Completed PipelineResult from ``DQTPipeline.run()``.
        output_path: Destination file, or a directory to name a file in.
            Defaults to ``dqt_report_<run_id>.pdf`` in the working
            directory.
        language: ``"en"`` or ``"fa"``. Only affects the headings; the data
            is the data.

    Returns:
        The resolved path of the written file.

    Raises:
        ConfigurationError: If the ``pdf`` extra is not installed.

    Example:
        path = generate_pdf_report(result, "report.pdf")
    """
    fpdf = _import_pdf_backend()

    destination = Path(output_path) if output_path else Path.cwd()
    if destination.is_dir():
        destination = destination / f"dqt_report_{result.run_id}.pdf"

    document = fpdf.FPDF(orientation="L", unit="mm", format="A4")
    document.set_auto_page_break(auto=True, margin=12)
    document.add_font("vazirmatn", "", str(_pdf_font_path()))
    document.set_font("vazirmatn", size=9)
    # HarfBuzz shaping. Without it Persian renders as isolated letter forms
    # in visual order, which is legible to nobody.
    document.set_text_shaping(True)
    document.add_page()

    title = translate("report_title", language)
    document.set_font_size(16)
    document.cell(text=title, new_x="LMARGIN", new_y="NEXT")
    document.set_font_size(9)
    document.cell(
        text=(
            f"Run {result.run_id}  |  status: {result.status}  |  "
            f"{len(result.tables)} table(s), {len(result.issues)} issue(s)"
        ),
        new_x="LMARGIN",
        new_y="NEXT",
    )
    document.ln(4)

    _pdf_table(
        document,
        ["Schema", "Table", "Column", "Type", "Semantic", "Nulls", "Distinct", "Score"],
        [
            [
                row.schema_name,
                row.table_name,
                row.column_name,
                row.db_type,
                row.semantic_type,
                row.null_count,
                row.distinct_count,
                f"{row.completeness:.2f}",
            ]
            for row in column_rows(result)
        ],
    )

    if result.issues:
        document.ln(4)
        document.set_font_size(12)
        document.cell(text="Issues", new_x="LMARGIN", new_y="NEXT")
        document.set_font_size(9)
        _pdf_table(
            document,
            ["Severity", "Table", "Column", "Dimension", "Message"],
            [
                [
                    issue.severity,
                    issue.table_name or "",
                    issue.column_name or "",
                    issue.dimension or "",
                    issue.message,
                ]
                for issue in result.issues
            ],
            widths=(22, 34, 30, 38, 150),
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    document.output(str(destination))
    return destination


def _pdf_table(
    document: Any,
    headers: list[str],
    rows: list[list[object]],
    widths: tuple[float, ...] | None = None,
) -> None:
    """Draw one table into a PDF document.

    Cells are truncated rather than wrapped. A profile report is a wide,
    scannable grid; a wrapped message turns every row into three and makes
    the page unreadable, and the HTML report remains the place to read a
    long message in full.

    Args:
        document: The open ``FPDF`` document.
        headers: Column headings.
        rows: Rows of values.
        widths: Column widths in millimetres, or None to divide evenly.

    Returns:
        None.

    Example:
        _pdf_table(document, ["A"], [["1"]])
    """
    available = document.w - 2 * document.l_margin
    if widths is None:
        widths = tuple(available / len(headers) for _ in headers)

    document.set_font_size(8)
    for header, width in zip(headers, widths, strict=True):
        document.cell(width, 6, header, border=1)
    document.ln()

    for row in rows:
        for value, width in zip(row, widths, strict=True):
            text = "" if value is None else str(value)
            # Roughly two characters per millimetre at this size. Measuring
            # each string would be exact and would cost a text-shaping pass
            # per cell, which is the wrong trade for a printable summary.
            limit = max(3, int(width / 1.7))
            if len(text) > limit:
                text = text[: limit - 1] + "\u2026"
            document.cell(width, 5, text, border=1)
        document.ln()


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


def _statistic(metadata: dict[str, Any], key: str) -> object:
    """Render one column statistic, or ``n/a`` when it was not produced.

    A missing statistic is not a zero. A text column has no mean and a
    declined distinct count has no value, and rendering either as ``0``
    would state a number the profiler deliberately did not compute --
    indistinguishable, to a reader, from a column that genuinely averages
    zero or holds no distinct values.

    ``n/a`` is reused rather than invented here: the null-count cell already
    uses it for the same "not known" meaning.

    Args:
        metadata: The completeness metric's metadata mapping.
        key: Which statistic to read.

    Returns:
        The value, or the string ``"n/a"``.

    Example:
        assert _statistic({}, "mean_value") == "n/a"
    """
    value = metadata.get(key)
    return "n/a" if value is None else value


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
        # Keyed on the rendered string, because an issue may carry no
        # dimension -- a drift finding about a raw measurement does not --
        # and sorting None against str raises rather than ordering.
        [
            (str(dimension or "unspecified"), float(count))
            for dimension, count in sorted(counts.items(), key=lambda item: str(item[0] or ""))
        ],
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

    # Built from the shared rows, decorated here. The renderer owns the
    # badge; what a report describes is decided once, in column_rows.
    rendered_column_rows: list[list[object]] = [
        [
            row.schema_name,
            row.table_name,
            row.column_name,
            row.db_type,
            row.semantic_type,
            row.null_count,
            row.distinct_count,
            row.minimum,
            row.maximum,
            row.mean,
            _score_badge(row.completeness),
        ]
        for row in column_rows(result)
    ]

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
        table(
            [
                "Schema",
                "Table",
                "Column",
                "Type",
                "Semantic",
                "Null Count",
                "Distinct",
                "Min",
                "Max",
                "Mean",
                "Completeness",
            ],
            rendered_column_rows,
        ),
        issue_section,
        Raw(_external_section(result)),
    )

    return document(title=f"DQT Report - {result.run_id}", body=body, css=STYLESHEET)
