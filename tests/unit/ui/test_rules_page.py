"""The rules screen (`VIZ-6`).

Screen 4 in `docs/PLAN-VIZ-UI.md` §3, and the one that was blocked until
`NEW-S` gave the store somewhere to keep rule results.

**The reason it exists is the zero.** A rule whose scope no longer matches
anything reports no failures, which on every other screen reads exactly like
a rule that passes — and a silently-matching-nothing rule is the most common
way a rule set rots. `targets_checked == 0` is the only thing that
distinguishes them, so this screen has to put it in front of a reader rather
than leaving it as a number in a column nobody scans.

**And history, because a single run cannot show a direction.** Whether a rule
is getting better or worse is the question a DBA asks about a rule, and one
number cannot answer it.

No apply action, no run action, no editing. The screen is read-only like
every other, for the reason `docs/PLAN-VIZ-UI.md` §7 gives: this is an HTTP
surface with no authentication.
"""

from __future__ import annotations

from typing import Any

from dqt.i18n import translate
from dqt.ui.pages import rule_history_page, rules_page

_RUN: dict[str, Any] = {
    "run_id": "run-1",
    "connection_id": "warehouse",
    "started_at": "2026-09-05T09:00:00+00:00",
    "status": "success",
    "dqt_version": "0.1.0",
}


def _result(name: str, *, checked: int, failed: int, errored: int = 0) -> dict[str, Any]:
    """Build one rule summary as ``dqt.ui.api`` returns it.

    Args:
        name: Rule name.
        checked: Targets evaluated.
        failed: Targets that failed.
        errored: Targets whose evaluation itself failed.

    Returns:
        A plain dict.

    Example:
        row = _result("not-null-email", checked=3, failed=1)
    """
    return {
        "run_id": "run-1",
        "rule_name": name,
        "targets_checked": checked,
        "targets_failed": failed,
        "targets_error": errored,
    }


class TestARuleThatMatchedNothingIsImpossibleToMiss:
    """The defect this screen exists to surface."""

    def test_a_zero_target_rule_is_called_out(self) -> None:
        """ "Matched nothing" is a different statement from "found nothing".

        Reported as words rather than left as a zero in a column, because a
        zero in a column of zeroes is invisible -- and the rules that matched
        nothing sit next to rules that passed, which also show zero failures.
        """
        html = rules_page(
            run=_RUN,
            results=[
                _result("not-null-email", checked=3, failed=1),
                _result("orphan-rule", checked=0, failed=0),
            ],
        )

        assert translate("matched_nothing", "en") in html

    def test_it_is_named(self) -> None:
        """A warning that does not say which rule is a warning nobody can act on."""
        html = rules_page(run=_RUN, results=[_result("orphan-rule", checked=0, failed=0)])

        assert "orphan-rule" in html

    def test_a_run_where_every_rule_matched_something_says_nothing_about_it(
        self,
    ) -> None:
        """No warning when there is nothing to warn about.

        A permanent banner is a banner people stop reading, which would cost
        exactly the attention this screen is trying to buy.
        """
        html = rules_page(run=_RUN, results=[_result("not-null-email", checked=3, failed=1)])

        assert translate("matched_nothing", "en") not in html

    def test_the_warning_is_above_the_table(self) -> None:
        """Asserted as a position, like the run status badge.

        "It is on the page somewhere" is how a warning gets missed, and this
        one competes with a table of every rule in the run.
        """
        html = rules_page(
            run=_RUN,
            results=[
                _result("aaa-passes", checked=3, failed=0),
                _result("zzz-orphan", checked=0, failed=0),
            ],
        )

        assert html.index(translate("matched_nothing", "en")) < html.index("<table>")


class TestTheTableAnswersWhatEachRuleDid:
    """Checked, failed and errored are three different outcomes."""

    def test_every_rule_is_listed_with_its_counts(self) -> None:
        """Read off the fixture, not off the renderer."""
        html = rules_page(
            run=_RUN, results=[_result("not-null-email", checked=3, failed=1, errored=2)]
        )

        assert "not-null-email" in html
        for count in ("3", "1", "2"):
            assert f">{count}<" in html

    def test_a_failure_and_an_error_are_not_merged(self) -> None:
        """A rule that failed found a problem; one that errored found nothing.

        Merging them would report a data-quality finding where there was a
        broken rule, which is the more damaging direction of the two.
        """
        html = rules_page(run=_RUN, results=[_result("r", checked=1, failed=0, errored=1)])

        assert translate("targets_failed", "en") in html
        assert translate("targets_error", "en") in html

    def test_a_run_with_no_rules_says_so(self) -> None:
        """An empty table reads as a rendering failure."""
        assert translate("no_rules", "en") in rules_page(run=_RUN, results=[])

    def test_each_rule_links_to_its_history(self) -> None:
        """One run cannot show a direction; the link is where that lives."""
        html = rules_page(run=_RUN, results=[_result("not-null-email", checked=1, failed=0)])

        assert 'href="/ui/rules/not-null-email"' in html


class TestHistoryShowsADirection:
    """Whether a rule is getting better or worse is the question about a rule."""

    def _history(self, *failures: int) -> list[dict[str, Any]]:
        """Build a history, newest first.

        Args:
            *failures: Failure counts, newest first.

        Returns:
            History entries as ``dqt.ui.api`` returns them.

        Example:
            entries = self._history(0, 2, 3)
        """
        return [
            {
                "run_id": f"run-{index}",
                "rule_name": "not-null-email",
                "targets_checked": 3,
                "targets_failed": failed,
                "targets_error": 0,
                "started_at": f"2026-09-0{index + 1}T09:00:00+00:00",
            }
            for index, failed in enumerate(failures)
        ]

    def test_every_run_is_listed(self) -> None:
        """Three runs in, three rows back."""
        html = rule_history_page(rule_name="not-null-email", history=self._history(0, 2, 3))

        for run_id in ("run-0", "run-1", "run-2"):
            assert run_id in html

    def test_the_trend_is_charted_oldest_first(self) -> None:
        """The store returns newest first; a time axis reads the other way.

        Charting the list as given would draw every improving rule as though
        it were getting worse -- a wrong conclusion, drawn confidently, from
        correct data.
        """
        html = rule_history_page(rule_name="not-null-email", history=self._history(0, 2, 3))
        equivalent = html.split('class="dqt-chart-text"')[1]

        assert equivalent.index("2026-09-03") < equivalent.index("2026-09-01")

    def test_a_rule_with_one_run_is_not_drawn_as_a_trend(self) -> None:
        """One reading is not a direction.

        ``dqt.viz.trend_line`` already refuses; this checks the page goes
        through it rather than drawing a flat, reassuring line of its own.
        """
        html = rule_history_page(rule_name="not-null-email", history=self._history(1))

        assert "no data" in html.lower()

    def test_a_rule_with_no_history_says_so_rather_than_404(self) -> None:
        """A renamed or deleted rule has no history, and that is an answer.

        Distinct from "this rule is fine": the page has to say which.
        """
        html = rule_history_page(rule_name="never-ran", history=[])

        assert translate("no_history", "en") in html
        assert "never-ran" in html


class TestTheScreenIsNavigableAndReadOnly:
    """Shared properties, and the safety one."""

    def test_both_pages_link_back(self) -> None:
        """No dead ends."""
        for html in (
            rules_page(run=_RUN, results=[]),
            rule_history_page(rule_name="r", history=[]),
        ):
            assert 'href="/ui"' in html

    def test_neither_page_offers_to_change_anything(self) -> None:
        """Read-only, on an HTTP surface with no authentication.

        A form is the shape a write takes, so the absence of one is the thing
        worth asserting -- more durable than checking for particular words.
        """
        for html in (
            rules_page(run=_RUN, results=[_result("r", checked=1, failed=1)]),
            rule_history_page(rule_name="r", history=[]),
        ):
            assert "<form" not in html.lower()
            assert "<button" not in html.lower()

    def test_a_rule_name_cannot_become_markup(self) -> None:
        """Rule names come from a config file a person edits."""
        html = rules_page(
            run=_RUN, results=[_result("<script>alert(1)</script>", checked=1, failed=0)]
        )

        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html
