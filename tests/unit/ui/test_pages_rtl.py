"""The screens in Persian (`VIZ-4`).

`docs/PLAN-VIZ-UI.md` §5. Three things have to be true at once, and the third
is the one that is usually missed.

* The document declares its language and direction, so a browser lays it out
  rather than guessing from the characters it happens to see first.
* The words are the glossary's, not English left in place.
* **Identifiers, SQL and numbers stay left-to-right.** Inside an RTL block a
  browser's bidirectional algorithm reorders bare Latin text, so a table name
  is still *present* but no longer *correct* — and a report that prints
  ``di_remotsuc.sredro`` is worse than one in the wrong language, because it
  looks like data.

And charts do not mirror. A bar chart is a measurement; reflecting it would
put the largest value where a Persian reader's eye starts while the axis
still said otherwise.
"""

from __future__ import annotations

from typing import Any

from dqt.i18n import translate
from dqt.ui.pages import issues_page, overview_page

_RUN: dict[str, Any] = {
    "run_id": "run-1",
    "connection_id": "warehouse",
    "started_at": "2026-09-05T09:00:00+00:00",
    "status": "partial",
    "dqt_version": "0.1.0",
}

_SCORES: dict[str, float | None] = {"completeness": 0.5}


def _overview(language: str) -> str:
    """Render the overview in *language*.

    Args:
        language: ``"en"`` or ``"fa"``.

    Returns:
        The page HTML.

    Example:
        html = _overview("fa")
    """
    return overview_page(
        runs=[_RUN],
        run=_RUN,
        dimension_scores=_SCORES,
        issues_by_severity={"error": 2},
        issues_by_dimension={"completeness": 2},
        language=language,  # type: ignore[arg-type]
    )


class TestTheDocumentDeclaresItsDirection:
    """A browser should not have to guess from the first characters it sees."""

    def test_persian_is_marked_rtl(self) -> None:
        """The attribute that flips the whole layout."""
        assert 'dir="rtl"' in _overview("fa")

    def test_persian_is_marked_as_persian(self) -> None:
        """``lang`` drives hyphenation, font selection and screen readers."""
        assert 'lang="fa"' in _overview("fa")

    def test_english_stays_left_to_right(self) -> None:
        """The default, asserted so it cannot drift when RTL is added."""
        html = _overview("en")

        assert 'dir="rtl"' not in html
        assert 'lang="en"' in html


class TestTheWordsAreTranslated:
    """The glossary is used, not merely present."""

    def test_a_heading_is_in_persian(self) -> None:
        """Taken from the glossary rather than retyped here.

        Comparing against ``translate`` means this test cannot drift from the
        table it is checking -- and it fails if the page stops going through
        the glossary at all.
        """
        assert translate("quality_by_dimension", "fa") in _overview("fa")

    def test_a_run_status_is_in_persian(self) -> None:
        """The word a reader scans for first has to be legible."""
        assert translate("partial", "fa") in _overview("fa")

    def test_a_dimension_is_in_persian(self) -> None:
        """Including inside a chart's text equivalent."""
        assert translate("completeness", "fa") in _overview("fa")

    def test_english_is_unchanged(self) -> None:
        """Adding a language must not alter the one that already worked."""
        assert "Quality by dimension" in _overview("en")


class TestDataDoesNotFlip:
    """Mirror the layout, not the data."""

    def test_an_identifier_carries_its_own_direction(self) -> None:
        """A reordered table name is wrong while still looking like data."""
        html = issues_page(
            run=_RUN,
            issues=[
                {
                    "severity": "error",
                    "dimension": "completeness",
                    "table_name": "orders",
                    "column_name": "customer_id",
                    "message": "m",
                }
            ],
            total=1,
            language="fa",
        )

        assert '<span dir="ltr">orders</span>' in html
        assert '<span dir="ltr">customer_id</span>' in html

    def test_the_run_id_carries_its_own_direction(self) -> None:
        """It is an identifier too, and it is in every heading."""
        assert '<span dir="ltr">run-1</span>' in _overview("fa")

    def test_a_chart_is_drawn_the_same_way_in_both_languages(self) -> None:
        """Only the words change; the geometry is a measurement.

        Asserted by pulling the polyline-free bar markup out of both pages:
        if a future change mirrored the chart for RTL, the two would differ.
        """
        english = _overview("en")
        persian = _overview("fa")

        def bars(html: str) -> list[str]:
            return [part.split(">")[0] for part in html.split("<rect class=")[1:]]

        assert bars(english) == bars(persian)


class TestAPersianPageCarriesItsFont:
    """`docs/PLAN-VIZ-UI.md` §5: shaping is not optional for Persian.

    A page that renders Persian in whatever the machine happens to have is
    often rendering it in a font with no Arabic-script shaping — letters that
    should join stand apart, and the words stop being words. That is not a
    degraded rendering, it is an unreadable one.
    """

    def test_persian_inlines_the_font(self) -> None:
        """Inlined, so the page still works on a machine without it."""
        html = _overview("fa")

        assert "@font-face" in html
        assert "data:font/woff2;base64," in html

    def test_english_does_not_pay_for_it(self) -> None:
        """Sixty-odd kilobytes to render text with no Persian in it."""
        assert "@font-face" not in _overview("en")

    def test_the_font_is_not_fetched_from_anywhere(self) -> None:
        """Self-contained is the property the whole delivery mode rests on."""
        html = _overview("fa")

        assert "fonts.googleapis.com" not in html
        assert "src: url(data:" in html
