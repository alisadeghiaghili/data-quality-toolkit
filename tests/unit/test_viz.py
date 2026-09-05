"""Charts as strings, not as pictures (`VIZ-1`).

`docs/PLAN-VIZ-UI.md` §2.2 chose inline SVG from pure functions over a
plotting library. The decisive reason is here, in this file: a raster image
can only be smoke-tested — "it did not crash" — and *"the bar for `validity`
is drawn shorter than the bar for `completeness`"* is a claim. The honesty
gate wants a passing test behind a claim, so the output has to be something a
test can read.

So every function in `dqt.viz` takes numbers and returns a
:class:`~dqt.viz.Chart`: an SVG string and the **text equivalent** that says
the same thing. They travel together because `docs/PLAN-VIZ-UI.md` §4 makes
the text equivalent an acceptance criterion rather than a polish pass, and a
value returned beside the thing it describes cannot be forgotten the way a
separate call can.

Three properties are load-bearing and each has its own class below:

* **Geometry is proportional and derivable.** A score of 0.5 draws half the
  track. Every expected pixel below is computed from the module's own
  published constants and the input, never read off a rendering.
* **Nothing is carried by colour alone.** Severity and status carry a word
  and a shape as well.
* **An absence renders as an absence.** "Not measured" must never look like a
  full green score — the failure mode that makes a dashboard worse than no
  dashboard.
"""

from __future__ import annotations

import pytest

from dqt.viz import (
    BAR_CHART_TRACK,
    SCORE_BAR_TRACK,
    TREND_HEIGHT,
    TREND_PADDING,
    TREND_WIDTH,
    Chart,
    bar_chart,
    score_bar,
    scorecard,
    severity_indicator,
    trend_line,
)


class TestEveryChartCarriesItsOwnTextEquivalent:
    """The accessibility requirement, made structural."""

    def test_a_chart_is_svg_and_text_together(self) -> None:
        """Returned as one value so the pair cannot be split by accident."""
        chart = score_bar(0.5, label="completeness")

        assert isinstance(chart, Chart)
        assert chart.svg.startswith("<svg")
        assert chart.text

    def test_the_text_carries_the_numbers_not_a_description_of_a_picture(
        self,
    ) -> None:
        """ "A bar chart of scores" helps nobody who cannot see the bars.

        The equivalent has to contain what the chart encodes, which is the
        values, so a screen reader reaches the same conclusion as an eye.
        """
        chart = bar_chart([("completeness", 0.5), ("validity", 1.0)], title="Scores")

        assert "completeness" in chart.text
        assert "50" in chart.text
        assert "validity" in chart.text
        assert "100" in chart.text


class TestGeometryIsProportional:
    """Every expected pixel is computed from the input, not read off a render."""

    def test_a_full_score_fills_the_track(self) -> None:
        """1.0 draws the whole track, by definition."""
        assert f'width="{SCORE_BAR_TRACK}"' in score_bar(1.0, label="c").svg

    def test_a_half_score_fills_half_the_track(self) -> None:
        """The property the whole module exists to make assertable."""
        assert f'width="{round(SCORE_BAR_TRACK * 0.5)}"' in score_bar(0.5, label="c").svg

    def test_a_zero_score_draws_no_fill(self) -> None:
        """Zero is a real reading and must not round up into a sliver.

        A hairline of green on a column that is entirely NULL is the kind of
        detail a tired reader takes as "nearly fine".
        """
        assert 'width="0"' in score_bar(0.0, label="c").svg

    def test_bars_are_scaled_against_the_largest_value(self) -> None:
        """The longest bar fills the track and the others are relative to it.

        Scaling against the maximum rather than against 1.0 keeps a chart of
        small numbers readable, which is the common case when counting issues.
        """
        chart = bar_chart([("a", 10), ("b", 5)], title="Issues")

        assert f'width="{BAR_CHART_TRACK}"' in chart.svg
        assert f'width="{round(BAR_CHART_TRACK * 0.5)}"' in chart.svg

    def test_a_trend_places_points_across_the_full_width(self) -> None:
        """First point at the left padding, last at the right.

        Two points, so the x coordinates are the two extremes and nothing is
        interpolated.
        """
        chart = trend_line([("2026-09-01", 1.0), ("2026-09-02", 0.0)], title="Score")

        assert f"{TREND_PADDING}," in chart.svg
        assert f"{TREND_WIDTH - TREND_PADDING}," in chart.svg

    def test_a_trend_puts_a_high_score_above_a_low_one(self) -> None:
        """SVG's y axis grows downward, which is the easy thing to get wrong.

        A score of 1.0 belongs at the top of the plot, so its y is the
        *smaller* number. A chart that silently plots quality upside down is
        worse than none.
        """
        chart = trend_line([("a", 1.0), ("b", 0.0)], title="Score")
        points = chart.svg.split('points="')[1].split('"')[0].split()
        high_y = float(points[0].split(",")[1])
        low_y = float(points[1].split(",")[1])

        assert high_y < low_y
        assert high_y == pytest.approx(TREND_PADDING)
        assert low_y == pytest.approx(TREND_HEIGHT - TREND_PADDING)


class TestAScoreOutsideItsRangeIsRefused:
    """A bar wider than its track is a drawing of an impossible number."""

    @pytest.mark.parametrize("score", [-0.1, 1.1, 42.0])
    def test_it_raises_rather_than_clamping(self, score: float) -> None:
        """Clamping would render a wrong number as a plausible one.

        The caller has a bug; silently drawing 100% for a score of 42 hides
        it behind a chart that looks fine.
        """
        with pytest.raises(ValueError, match="between 0 and 1"):
            score_bar(score, label="c")

    def test_a_negative_bar_value_is_refused_too(self) -> None:
        """Counts are never negative, so one means the caller is confused."""
        with pytest.raises(ValueError, match="negative"):
            bar_chart([("a", -1)], title="Issues")


class TestNothingIsCarriedByColourAlone:
    """Roughly 8% of men have some colour-vision deficiency."""

    @pytest.mark.parametrize("severity", ["info", "warning", "error", "critical"])
    def test_a_severity_carries_its_word(self, severity: str) -> None:
        """The label is the part that always works."""
        assert severity in severity_indicator(severity).text

    @pytest.mark.parametrize("severity", ["info", "warning", "error", "critical"])
    def test_a_severity_carries_a_shape_as_well(self, severity: str) -> None:
        """Distinguishable at a glance without reading, and without colour.

        A row of identical circles in four colours is a legend lookup for
        everyone and unusable for some; four different marks are neither.
        """
        assert severity_indicator(severity).shape

    def test_the_four_severities_use_four_different_shapes(self) -> None:
        """Two severities sharing a mark would put the burden back on colour."""
        shapes = {
            severity_indicator(name).shape for name in ("info", "warning", "error", "critical")
        }

        assert len(shapes) == 4

    def test_an_unknown_severity_is_refused(self) -> None:
        """The set is closed, and guessing would invent a severity."""
        with pytest.raises(ValueError, match="severity"):
            severity_indicator("catastrophic")


class TestAnAbsenceRendersAsAnAbsence:
    """The failure that makes a dashboard worse than no dashboard."""

    def test_an_unmeasured_dimension_is_not_drawn_as_a_full_score(self) -> None:
        """ "Not measured" and "perfect" are the two readings most easily
        confused, and confusing them is how a gap becomes a green tick.
        """
        card = scorecard("timeliness", score=None)

        assert "not measured" in card.text.lower()
        assert "100" not in card.text

    def test_an_unmeasured_dimension_draws_no_bar_at_all(self) -> None:
        """An empty track still reads as a score of zero to a glancing eye."""
        assert "<rect" not in scorecard("timeliness", score=None).svg

    def test_a_measured_zero_is_different_from_not_measured(self) -> None:
        """A column that is entirely NULL scored 0. That is a measurement."""
        measured = scorecard("completeness", score=0.0)
        unmeasured = scorecard("completeness", score=None)

        assert measured.svg != unmeasured.svg
        assert "not measured" not in measured.text.lower()

    def test_an_approximate_score_says_so(self) -> None:
        """An estimate and an exact count are different claims.

        The same rule the `UNIQUE` rule's evidence follows: a report that
        renders them identically asserts a precision it does not have.
        """
        card = scorecard("uniqueness", score=0.9, approximate=True)

        assert "approximate" in card.text.lower()


class TestTheOutputIsSafeToEmbed:
    """Labels are table and column names, which come from the database."""

    def test_a_label_is_escaped(self) -> None:
        """A column can be named almost anything, including markup."""
        chart = bar_chart([("<script>x</script>", 1)], title="Issues")

        assert "<script>" not in chart.svg
        assert "&lt;script&gt;" in chart.svg

    def test_a_title_is_escaped(self) -> None:
        """Titles are built from identifiers too."""
        assert "<b>" not in bar_chart([("a", 1)], title="<b>t</b>").svg

    def test_the_text_equivalent_is_escaped(self) -> None:
        """It is rendered into the same page, so it is markup too."""
        assert "<script>" not in bar_chart([("<script>x</script>", 1)], title="t").text

    def test_nothing_is_fetched_from_outside(self) -> None:
        """The report must stay self-contained when this is embedded in it."""
        svg = bar_chart([("a", 1)], title="t").svg

        assert "http" not in svg
        assert "<image" not in svg


class TestTheSameInputAlwaysDrawsTheSameThing:
    """Determinism is what makes any of the above assertable at all."""

    def test_two_calls_produce_identical_output(self) -> None:
        """No timestamps, no random ids, no dict ordering leaking through."""
        first = bar_chart([("a", 1), ("b", 2)], title="t")
        second = bar_chart([("a", 1), ("b", 2)], title="t")

        assert first == second


class TestManyCategoriesStayReadable:
    """`docs/PLAN-VIZ-UI.md` §5: 5-7 categories per chart, not forty."""

    def test_a_long_series_is_truncated_and_says_so(self) -> None:
        """Silently dropping rows would make the chart a lie by omission.

        Truncation is the right behaviour -- forty labels in four hundred
        pixels is unreadable -- but only if the chart admits it.
        """
        series = [(f"c{n}", float(40 - n)) for n in range(40)]

        chart = bar_chart(series, title="Worst columns")

        assert "33 more" in chart.text

    def test_the_largest_values_are_the_ones_kept(self) -> None:
        """ "Worst N" is the question these charts answer.

        Keeping the first N in input order would answer a different one, and
        would depend on how the caller happened to sort.
        """
        chart = bar_chart([(f"c{n}", float(n)) for n in range(40)], title="t")

        assert "c39" in chart.text
        assert "c0," not in chart.text

    def test_a_short_series_is_left_alone(self) -> None:
        """No truncation note when nothing was truncated."""
        assert "more" not in bar_chart([("a", 1), ("b", 2)], title="t").text

    def test_an_empty_series_says_there_is_nothing_to_show(self) -> None:
        """An empty chart frame implies a rendering failure."""
        chart = bar_chart([], title="Issues by dimension")

        assert "no data" in chart.text.lower()
        assert "<rect" not in chart.svg
