"""What the HTML report promises its reader (`VIZ-0`).

`reports.py` is 389 lines with 93% line coverage — and almost none of that
coverage is an assertion. It is executed as a side effect of pipeline tests,
so the module is known not to *crash*; what it actually puts on the page is
checked in one place, for one section, in `tests/unit/bridges/test_report_panel.py`.

`docs/PLAN-VIZ-UI.md` moves this module onto shared templates in `VIZ-2`. A
refactor is only safe if the thing being preserved is written down first, so
this file writes it down.

Writing it down found two defects, which is why this is a red commit and not
a set of characterization tests:

**The report never says what the run's status was.** The Status row renders
``_severity_badge("info")`` for a success and ``_severity_badge("warning")``
for anything else — so the badge reads "warning", and the words ``success``,
``partial`` and ``failed`` appear nowhere. A partial run and a failed run
render identically. The module docstring claims it reports "run summary
(run_id, status, ...)"; it reports a severity word standing in for a status.

**`stage_errors` are never rendered.** `NEW-B` added them so a run could
report failure at all. The report drops them, so a degraded run shows an
unexplained "warning" and nothing a DBA can act on. That is the exact defect
the honesty gate exists to catch, one layer further out: the run knows it
went wrong and the artifact a person actually reads does not say so.

The rest of this file is the contract that must survive `VIZ-2` unchanged.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from dqt.common.models import (
    DQIssue,
    DQMetric,
    PipelineResult,
    RunStatus,
    StageError,
)
from dqt.sql.reports import generate_html_report


def _result(
    *,
    status: RunStatus = "success",
    stage_errors: list[StageError] | None = None,
    table_name: str = "orders",
) -> PipelineResult:
    """Build a small run result to render.

    Args:
        status: Run status to record.
        stage_errors: Stage failures to attach, or None for none.
        table_name: Table the metric and issue belong to, so a test can put
            something hostile in it.

    Returns:
        A PipelineResult ready for :func:`generate_html_report`.

    Example:
        html = generate_html_report(_result(status="failed"))
    """
    moment = datetime(2026, 9, 5, 9, 0, tzinfo=UTC)
    return PipelineResult(
        run_id="run-report-1",
        connection_id="conn-1",
        started_at=moment,
        ended_at=moment,
        status=status,
        metrics=[
            DQMetric(
                run_id="run-report-1",
                dimension="completeness",
                score=0.5,
                schema_name="main",
                table_name=table_name,
                column_name="email",
                value=2.0,
            )
        ],
        issues=[
            DQIssue(
                issue_id="i-1",
                run_id="run-report-1",
                dimension="completeness",
                severity="error",
                message="Column 'email' has 2 NULL value(s).",
                schema_name="main",
                table_name=table_name,
                column_name="email",
            )
        ],
        stage_errors=stage_errors or [],
    )


def _render(result: PipelineResult, tmp_path: Path) -> str:
    """Render *result* to a file and return the HTML.

    Args:
        result: The run to render.
        tmp_path: Directory to write into.

    Returns:
        The report's text.

    Example:
        html = _render(_result(), tmp_path)
    """
    written = generate_html_report(result, output_path=tmp_path / "report.html")
    return written.read_text(encoding="utf-8")


class TestTheReportIsSelfContained:
    """The property that makes it worth more to a DBA than a dashboard.

    ``docs/DQT-UI-Ecosystem.md`` borrows this from Great Expectations Data
    Docs: a single file can be emailed, attached to a ticket and archived. It
    stops being that the moment it needs to fetch anything.
    """

    def test_nothing_is_fetched_over_the_network(self, tmp_path: Path) -> None:
        """No stylesheet link, no script tag, no remote image.

        A report that renders correctly on the machine that made it and
        blankly somewhere else is worse than one that never looked
        self-contained.
        """
        html = _render(_result(), tmp_path)

        assert "<script" not in html.lower()
        assert 'rel="stylesheet"' not in html.lower()
        assert not re.search(r'src\s*=\s*["\']https?://', html, re.IGNORECASE)

    def test_the_styles_are_inline(self, tmp_path: Path) -> None:
        """The CSS travels with the file or the file is not self-contained."""
        html = _render(_result(), tmp_path)

        assert "<style>" in html
        assert "</style>" in html

    def test_it_declares_its_encoding(self, tmp_path: Path) -> None:
        """Persian content is coming in `VIZ-4`; UTF-8 has to be stated.

        A browser guessing an encoding is how Persian text becomes mojibake
        in exactly the case the reader cannot check it against the database.
        """
        html = _render(_result(), tmp_path)

        assert 'charset="UTF-8"' in html


class TestUserDataCannotBecomeMarkup:
    """Identifiers and messages come from the database, not from DQT."""

    def test_a_hostile_table_name_is_escaped(self, tmp_path: Path) -> None:
        """A table can legally be named almost anything.

        The report is opened in a browser, often by someone other than the
        person who ran it. A table name that closes a tag and opens a script
        is a real, if unusual, schema — and quoting it is not optional
        because the odds are low.
        """
        html = _render(_result(table_name="<script>alert(1)</script>"), tmp_path)

        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html

    def test_the_escaping_survives_into_the_issue_rows(self, tmp_path: Path) -> None:
        """Every section that prints a name has to escape it, not just one."""
        html = _render(_result(table_name="a<b"), tmp_path)

        assert "a<b</td>" not in html
        assert "a&lt;b" in html


class TestSeverityIsReadableWithoutColour:
    """Roughly 8% of men have some colour-vision deficiency.

    ``docs/PLAN-VIZ-UI.md`` §4 makes this an acceptance criterion rather than
    a polish pass, and the existing report already satisfies it — the badge
    carries the word. Pinned so the `VIZ-2` refactor cannot quietly reduce it
    to a coloured square.
    """

    def test_the_severity_word_is_in_the_text(self, tmp_path: Path) -> None:
        """A red badge with no label is unreadable to part of the audience."""
        html = _render(_result(), tmp_path)

        assert ">error<" in html


class TestTheRunStatusIsStated:
    """A report that renders a failed run as a healthy one is worse than none."""

    @pytest.mark.parametrize("status", ["success", "partial", "failed"])
    def test_the_status_word_itself_appears(self, tmp_path: Path, status: str) -> None:
        """The reader needs the run's status, not a severity standing in for it.

        Today a success renders a badge reading "info" and everything else
        renders one reading "warning", so the three statuses become two and
        neither of the interesting ones is named.
        """
        html = _render(_result(status=status), tmp_path)  # type: ignore[arg-type]

        assert status in html

    def test_a_failed_run_does_not_render_like_a_partial_one(self, tmp_path: Path) -> None:
        """ "Something went wrong" and "everything went wrong" are different.

        A partial run produced numbers a DBA can partly trust; a failed run
        did not. Rendering them identically invites the wrong conclusion from
        the one that matters more.
        """
        failed = _render(_result(status="failed"), tmp_path / "a")
        partial = _render(_result(status="partial"), tmp_path / "b")

        assert failed != partial

    def test_a_failed_run_does_not_render_like_a_successful_one(self, tmp_path: Path) -> None:
        """The floor. If only one of these tests survives, it is this one."""
        failed = _render(_result(status="failed"), tmp_path / "a")
        succeeded = _render(_result(status="success"), tmp_path / "b")

        assert failed != succeeded


class TestStageErrorsReachTheReader:
    """`NEW-B` gave a run the ability to report failure; this is where it lands."""

    def test_a_stage_failure_is_shown_with_its_stage_and_message(self, tmp_path: Path) -> None:
        """An unexplained "warning" is not something a DBA can act on.

        The message is written to be actionable — that is what `StageError`'s
        contract asks for — so dropping it wastes the one part of a failure
        that was designed to be read.
        """
        html = _render(
            _result(
                status="partial",
                stage_errors=[
                    StageError(
                        stage="discover_schema",
                        message="unable to open database file",
                        exception_type="OperationalError",
                    )
                ],
            ),
            tmp_path,
        )

        assert "discover_schema" in html
        assert "unable to open database file" in html

    def test_a_stage_error_message_is_escaped_too(self, tmp_path: Path) -> None:
        """Driver messages quote user input, so they are not trusted markup."""
        html = _render(
            _result(
                status="partial",
                stage_errors=[
                    StageError(
                        stage="apply_rules",
                        message="no such column: <b>oops</b>",
                        exception_type="OperationalError",
                    )
                ],
            ),
            tmp_path,
        )

        assert "<b>oops</b>" not in html
        assert "&lt;b&gt;oops&lt;/b&gt;" in html

    def test_a_clean_run_shows_no_errors_section_at_all(self, tmp_path: Path) -> None:
        """An empty panel implies something is missing or broken.

        The same rule the missingness panel follows: when there is nothing to
        say, say nothing rather than rendering a placeholder.
        """
        html = _render(_result(status="success"), tmp_path)

        assert "Stage Errors" not in html


class TestTheReportNamesItself:
    """Basic identification, pinned because a refactor can drop a title."""

    def test_the_run_id_is_in_the_title_and_the_body(self, tmp_path: Path) -> None:
        """A report found in a ticket a year later has to say what it is."""
        html = _render(_result(), tmp_path)

        assert "<title>" in html
        assert html.count("run-report-1") >= 2

    def test_the_file_is_written_where_it_was_asked_for(self, tmp_path: Path) -> None:
        """The return value is the path, and it is the path that was given."""
        target = tmp_path / "nested" / "report.html"

        written = generate_html_report(_result(), output_path=target)

        assert written == target
        assert written.exists()
