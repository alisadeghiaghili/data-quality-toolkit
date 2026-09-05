"""The screens, as strings (`VIZ-3`).

`docs/PLAN-VIZ-UI.md` §3 lists the screens. This is the first three of them —
Overview, Explorer, Column & Issue detail — and they are built the same way
the report is: `dqt._html` for markup, `dqt.viz` for charts, one renderer for
both delivery modes.

**The pages are pure functions.** They take the plain dicts `dqt.ui.api`
returns and give back a string. No request, no framework, no database, so
almost everything worth asserting about a screen can be asserted without
starting a server — which is what keeps a UI suite fast enough that people
run it.

Two properties matter more than the rest and each has its own class:

* **A degraded run cannot look healthy.** `docs/PLAN-VIZ-UI.md` §3: a dashboard
  that renders a failed run green is worse than no dashboard, and it is the
  same defect Phase 0 removed, wearing a nicer font.
* **The page works without colour and without JavaScript.** Plain
  server-rendered pages were chosen partly because they are keyboard
  accessible and back-button correct by construction; that stops being true
  the moment something on the page needs script to be usable.
"""

from __future__ import annotations

from typing import Any

from dqt.i18n import translate
from dqt.ui.pages import issues_page, overview_page, run_page

_RUN: dict[str, Any] = {
    "run_id": "run-1",
    "connection_id": "warehouse",
    "started_at": "2026-09-05T09:00:00+00:00",
    "ended_at": "2026-09-05T09:01:00+00:00",
    "status": "success",
    "dqt_version": "0.1.0",
}

#: Hand-built. ``completeness`` scored 0.5; nothing measured the other five.
_SCORES: dict[str, float | None] = {
    "completeness": 0.5,
    "consistency": None,
    "referential_integrity": None,
    "timeliness": None,
    "uniqueness": None,
    "validity": None,
}

_SEVERITIES: dict[str, int] = {"error": 2, "warning": 1}
_DIMENSIONS: dict[str, int] = {"completeness": 2, "validity": 1}


def _run(**overrides: Any) -> dict[str, Any]:
    """Return the fixture run, optionally overridden.

    Args:
        **overrides: Fields to replace.

    Returns:
        A run dict as ``dqt.ui.api`` returns it.

    Example:
        failed = _run(status="failed")
    """
    return {**_RUN, **overrides}


def _overview(**overrides: Any) -> str:
    """Render the overview for the fixture run.

    Args:
        **overrides: Fields to replace on the run.

    Returns:
        The page HTML.

    Example:
        html = _overview(status="failed")
    """
    return overview_page(
        runs=[_run(**overrides)],
        run=_run(**overrides),
        dimension_scores=_SCORES,
        issues_by_severity=_SEVERITIES,
        issues_by_dimension=_DIMENSIONS,
    )


class TestADegradedRunCannotLookHealthy:
    """The failure that makes a dashboard worse than no dashboard."""

    def test_the_status_word_is_on_the_page(self) -> None:
        """Not a colour, not an icon alone -- the word the run itself used."""
        assert "failed" in _overview(status="failed")

    def test_a_failed_run_does_not_render_like_a_successful_one(self) -> None:
        """The floor. If one assertion in this file survives, it is this one."""
        assert _overview(status="failed") != _overview(status="success")

    def test_a_partial_run_is_distinct_from_a_failed_one(self) -> None:
        """ "Some of it worked" and "none of it did" lead to different actions."""
        assert _overview(status="partial") != _overview(status="failed")

    def test_the_status_is_near_the_top_rather_than_buried(self) -> None:
        """A badge below three tables is a badge nobody reads.

        Asserted as a position rather than only as presence, because "it is
        on the page somewhere" is exactly how a warning gets missed.
        """
        html = _overview(status="failed")

        assert html.index("failed") < html.index("Quality by dimension")


class TestTheOverviewAnswersItsQuestion:
    """One question per screen: how is this run, and where do I look first."""

    def test_every_dimension_has_a_card(self) -> None:
        """Six, including the five nothing measured.

        Showing only what was measured invites the reader to assume the rest
        was fine -- the same reasoning as the report's scorecards.

        Compared against the glossary rather than the raw key: `VIZ-4` gave
        English a row of its own, so ``referential_integrity`` renders as
        "referential integrity". Asserting the underscored key would be
        asserting that the page leaks an internal identifier.
        """
        html = _overview()

        for dimension in _SCORES:
            assert translate(dimension, "en") in html

    def test_an_unmeasured_dimension_says_so_and_draws_no_bar(self) -> None:
        """ "Not measured" and "perfect" are the two readings most easily confused."""
        html = _overview()

        assert "not measured" in html.lower()
        assert "dqt-unmeasured" in html

    def test_the_issue_counts_are_charted(self) -> None:
        """Two completeness and one validity, from the fixture literal."""
        html = _overview()

        assert "completeness 2" in html
        assert "validity 1" in html

    def test_the_connection_is_named(self) -> None:
        """A DBA with several connections needs to know which one this is."""
        assert "warehouse" in _overview()

    def test_the_dqt_version_is_shown(self) -> None:
        """Scores are only comparable within a version line (`NEW-S`).

        Recording it and then not showing it would waste the column.
        """
        assert "0.1.0" in _overview()


class TestTheExplorerListsTables:
    """Screen 2: which table is worst, and when was it last looked at."""

    def test_each_table_is_listed_with_its_counts(self) -> None:
        """Numbers come from the caller, already aggregated by the database."""
        html = run_page(
            run=_run(),
            tables=[
                {"table_name": "orders", "schema_name": "main", "issue_count": 3},
                {"table_name": "customers", "schema_name": "main", "issue_count": 0},
            ],
            dimension_scores=_SCORES,
            issues_by_severity=_SEVERITIES,
        )

        assert "orders" in html
        assert "customers" in html
        assert ">3<" in html

    def test_a_run_with_no_tables_says_so(self) -> None:
        """An empty table body reads as a rendering failure."""
        html = run_page(
            run=_run(),
            tables=[],
            dimension_scores=_SCORES,
            issues_by_severity={},
        )

        assert "no tables" in html.lower()


class TestTheIssueListIsReadableAndBounded:
    """Screen 3: what is wrong, and enough context to act."""

    def _issues(self, count: int = 3) -> list[dict[str, Any]]:
        """Build *count* issue dicts.

        Args:
            count: How many to build.

        Returns:
            Issue dicts as ``dqt.ui.api`` returns them.

        Example:
            issues = self._issues(2)
        """
        return [
            {
                "issue_id": f"i-{index}",
                "severity": "error",
                "dimension": "completeness",
                "schema_name": "main",
                "table_name": "orders",
                "column_name": "email",
                "message": f"problem {index}",
                "rule_name": "not-null-email",
            }
            for index in range(count)
        ]

    def test_every_issue_is_shown_with_its_message(self) -> None:
        """The message is the part a DBA acts on."""
        html = issues_page(run=_run(), issues=self._issues(2), total=2)

        assert "problem 0" in html
        assert "problem 1" in html

    def test_severity_is_carried_by_a_word_and_a_shape(self) -> None:
        """Colour alone is unreadable to roughly 8% of men."""
        html = issues_page(run=_run(), issues=self._issues(1), total=1)

        assert "error" in html
        assert "dqt-severity" in html

    def test_a_truncated_list_says_how_many_there_were(self) -> None:
        """Showing 50 of 4000 without saying so is a lie by omission.

        The list has to be bounded -- the size of a page must not depend on
        how bad the data is -- so the only honest option is to say what the
        bound hid.
        """
        html = issues_page(run=_run(), issues=self._issues(50), total=4000)

        assert "4000" in html

    def test_a_clean_run_says_there_is_nothing_wrong(self) -> None:
        """A blank table is ambiguous between clean and broken."""
        html = issues_page(run=_run(), issues=[], total=0)

        assert "no issues" in html.lower()


class TestEveryPageIsNavigableAndSafe:
    """Shared layout properties, asserted once per page."""

    def _pages(self) -> list[str]:
        """Render one of each page.

        Returns:
            The three pages' HTML.

        Example:
            for html in self._pages(): ...
        """
        return [
            _overview(),
            run_page(run=_run(), tables=[], dimension_scores=_SCORES, issues_by_severity={}),
            issues_page(run=_run(), issues=[], total=0),
        ]

    def test_every_page_is_a_complete_document(self) -> None:
        """A fragment served as a page renders in quirks mode."""
        for html in self._pages():
            assert html.startswith("<!DOCTYPE html>")
            assert 'charset="UTF-8"' in html

    def test_every_page_carries_breadcrumbs_back_to_the_overview(self) -> None:
        """No dead ends: every view links onward and back."""
        for html in self._pages()[1:]:
            assert 'href="/ui"' in html

    def test_no_page_needs_javascript(self) -> None:
        """Plain pages were chosen because accessibility comes for free.

        That stops being true the moment something needs script to be usable,
        so the absence is asserted rather than assumed.
        """
        for html in self._pages():
            assert "<script" not in html.lower()
            assert "onclick" not in html.lower()

    def test_user_data_cannot_become_markup(self) -> None:
        """Connection ids, table names and messages all come from outside."""
        html = issues_page(run=_run(connection_id="<script>alert(1)</script>"), issues=[], total=0)

        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html


class TestTheFirstUseAndTheUnexpected:
    """Two states a screen has to handle without looking broken."""

    def test_an_empty_store_says_there_are_no_runs_yet(self) -> None:
        """The first thing a new user sees, and the easiest to get wrong.

        A dashboard with empty charts and blank tables reads as a failure.
        Saying "no runs recorded yet" says the tool is fine and there is
        simply nothing to show.
        """
        html = overview_page(
            runs=[],
            run=None,
            dimension_scores={},
            issues_by_severity={},
            issues_by_dimension={},
        )

        assert "no runs" in html.lower()
        assert "<!DOCTYPE html>" in html

    def test_an_unfamiliar_severity_still_renders(self) -> None:
        """A page is drawn after the fact, so it cannot refuse to draw.

        ``dqt.viz.severity_indicator`` raises on an unknown severity, which
        is right for a caller building a chart. A screen has to degrade
        instead: losing the whole page because one row carried an unexpected
        word would be a far worse outcome than losing the icon.
        """
        issue = {
            "severity": "catastrophic",
            "dimension": "validity",
            "table_name": "orders",
            "column_name": "email",
            "message": "m",
        }

        html = issues_page(run=_run(), issues=[issue], total=1)

        assert "catastrophic" in html
