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
from datetime import UTC, datetime
from pathlib import Path

from dqt.common.models import DQMetric, PipelineResult

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
.score-bar-wrap {
    background: #e0e0e0; border-radius: 6px; height: 10px; width: 120px;
    display: inline-block; vertical-align: middle;
}
.score-bar { height: 10px; border-radius: 6px; }
.score-good { background: #28a745; }
.score-warn { background: #ffc107; }
.score-bad { background: #dc3545; }
"""


def _score_badge(score: float) -> str:
    pct = round(score * 100, 1)
    if score >= 0.95:
        cls = "ok"
    elif score >= 0.80:
        cls = "warn"
    else:
        cls = "err"
    bar_cls = "score-good" if score >= 0.95 else ("score-warn" if score >= 0.80 else "score-bad")
    bar_w = round(score * 120)
    return (
        f'<span class="score-bar-wrap"><span class="score-bar {bar_cls}" '
        f'style="width:{bar_w}px"></span></span> '
        f'<span class="badge {cls}">{pct}%</span>'
    )


def _severity_badge(severity: str) -> str:
    cls = {"error": "err", "warning": "warn", "info": "ok"}.get(severity, "ok")
    return f'<span class="badge {cls}">{html.escape(severity)}</span>'


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


def _render(result: PipelineResult) -> str:
    started_str = (
        result.started_at.strftime("%Y-%m-%d %H:%M:%S UTC") if result.started_at else "n/a"
    )
    ended_str = result.ended_at.strftime("%Y-%m-%d %H:%M:%S UTC") if result.ended_at else "n/a"
    duration = _duration(result.started_at, result.ended_at)
    status_badge = (
        _severity_badge("info") if result.status == "success" else _severity_badge("warning")
    )

    # ---- run summary -------------------------------------------------------
    summary_rows = [
        ("Run ID", html.escape(result.run_id)),
        ("Status", status_badge),
        ("Started", html.escape(started_str)),
        ("Ended", html.escape(ended_str)),
        ("Duration", html.escape(duration)),
        ("Tables scanned", str(len(result.tables))),
        ("Total issues", str(len(result.issues))),
        ("Total metrics", str(len(result.metrics))),
    ]
    summary_html = (
        "<table><tr><th>Field</th><th>Value</th></tr>"
        + "".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in summary_rows)
        + "</table>"
    )

    # ---- table-level metrics -----------------------------------------------
    table_rows_html = ""
    for _key, table_result in sorted(result.tables.items()):
        schema = table_result.schema_name
        table = table_result.table_name
        row_count_m = _metric_lookup(result.metrics, "row_count", schema=schema, table=table)
        row_count = (
            int(row_count_m.value) if row_count_m and row_count_m.value is not None else "n/a"
        )

        col_completeness_scores = [
            m.score
            for m in result.metrics
            if m.dimension == "completeness"
            and m.schema_name == schema
            and m.table_name == table
            and m.column_name is not None
            and m.score is not None
        ]
        avg_completeness = (
            sum(col_completeness_scores) / len(col_completeness_scores)
            if col_completeness_scores
            else 1.0
        )
        issue_count = sum(
            1 for i in result.issues if i.schema_name == schema and i.table_name == table
        )
        table_rows_html += (
            f"<tr>"
            f"<td>{html.escape(schema)}</td>"
            f"<td>{html.escape(table)}</td>"
            f"<td>{row_count}</td>"
            f"<td>{_score_badge(avg_completeness)}</td>"
            f"<td>{issue_count}</td>"
            f"</tr>"
        )

    table_header = (
        "<tr><th>Schema</th><th>Table</th><th>Rows</th>"
        "<th>Avg Completeness</th><th>Issues</th></tr>"
    )
    table_section = "<h2>Table Summary</h2><table>" + table_header + table_rows_html + "</table>"

    # ---- column-level metrics ----------------------------------------------
    col_rows_html = ""
    for _key, table_result in sorted(result.tables.items()):
        for col in table_result.columns:
            null_m = _metric_lookup(
                result.metrics,
                "completeness",
                schema=col.schema_name,
                table=col.table_name,
                column=col.column_name,
            )
            null_count = int(null_m.value) if null_m and null_m.value is not None else "n/a"
            score = null_m.score if null_m and null_m.score is not None else 1.0
            col_rows_html += (
                f"<tr>"
                f"<td>{html.escape(col.schema_name)}</td>"
                f"<td>{html.escape(col.table_name)}</td>"
                f"<td>{html.escape(col.column_name)}</td>"
                f"<td>{null_count}</td>"
                f"<td>{_score_badge(score)}</td>"
                f"</tr>"
            )

    col_header = (
        "<tr><th>Schema</th><th>Table</th><th>Column</th>"
        "<th>Null Count</th><th>Completeness</th></tr>"
    )
    col_section = (
        ("<h2>Column Completeness</h2><table>" + col_header + col_rows_html + "</table>")
        if col_rows_html
        else ""
    )

    # ---- issues ------------------------------------------------------------
    issue_rows_html = ""
    for issue in sorted(
        result.issues, key=lambda i: (i.severity, i.table_name or "", i.column_name or "")
    ):
        issue_rows_html += (
            f"<tr>"
            f"<td>{_severity_badge(issue.severity)}</td>"
            f"<td>{html.escape(issue.schema_name or '')}</td>"
            f"<td>{html.escape(issue.table_name or '')}</td>"
            f"<td>{html.escape(issue.column_name or '')}</td>"
            f"<td>{html.escape(issue.message)}</td>"
            f"</tr>"
        )

    issue_section = (
        (
            "<h2>Issues</h2>"
            "<table>"
            "<tr><th>Severity</th><th>Schema</th><th>Table</th>"
            "<th>Column</th><th>Message</th></tr>" + issue_rows_html + "</table>"
        )
        if issue_rows_html
        else "<h2>Issues</h2><p>No issues detected.</p>"
    )

    external_section = _external_section(result)

    generated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    run_id_escaped = html.escape(result.run_id)
    meta_line = f"Generated {generated_at} &nbsp;|&nbsp; Run: {run_id_escaped}"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>DQT Report — {run_id_escaped}</title>
<style>{_CSS}</style>
</head>
<body>
<h1>DQT Data Quality Report</h1>
<p class="meta">{meta_line}</p>
<h2>Run Summary</h2>
{summary_html}
{table_section}
{col_section}
{issue_section}
{external_section}
</body>
</html>
"""
