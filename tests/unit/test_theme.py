"""Contrast, measured rather than intended (`VIZ-5`).

`docs/PLAN-VIZ-UI.md` §4 commits DQT to WCAG 2.1 AA: 4.5:1 for body text,
3:1 for large text and graphical objects. A commitment nothing measures is a
wish, and "these colours look fine to me" is exactly the judgement that fails
the readers the requirement exists for.

So the ratios are computed here, from the palette DQT actually paints with,
using the formula from WCAG 2.1 rather than an eyeball. Writing this found
two colours that did not clear the bar. The conventional amber and teal used
for `warning` and `info` are tuned to look right on screen, and against a
near-white page they measure **1.51:1** and **2.81:1** — the amber is barely
distinguishable from the paper it is drawn on.

**The severity word carries the meaning either way**, which is why those
marks were not a blocker before this file existed. But a mark nobody can see
is not worth drawing, and claiming AA while shipping one is the kind of
unbacked claim the honesty gate exists to stop.
"""

from __future__ import annotations

import pytest

from dqt._theme import CONTRAST_REQUIREMENTS, PALETTE, STYLESHEET


def _channel(value: int) -> float:
    """Linearise one sRGB channel, per WCAG 2.1.

    Args:
        value: The channel byte, 0-255.

    Returns:
        The linearised value in [0, 1].

    Example:
        assert _channel(0) == 0.0
    """
    proportion = value / 255
    if proportion <= 0.03928:
        return proportion / 12.92
    return ((proportion + 0.055) / 1.055) ** 2.4


def _luminance(colour: str) -> float:
    """Return the relative luminance of a ``#rrggbb`` colour.

    Args:
        colour: A six-digit hex colour.

    Returns:
        Relative luminance in [0, 1].

    Example:
        assert _luminance("#000000") == 0.0
    """
    red, green, blue = (int(colour[index : index + 2], 16) for index in (1, 3, 5))
    return 0.2126 * _channel(red) + 0.7152 * _channel(green) + 0.0722 * _channel(blue)


def _contrast(foreground: str, background: str) -> float:
    """Return the WCAG contrast ratio between two colours.

    Args:
        foreground: A six-digit hex colour.
        background: A six-digit hex colour.

    Returns:
        The ratio, between 1.0 and 21.0.

    Example:
        assert round(_contrast("#000000", "#ffffff")) == 21
    """
    first, second = _luminance(foreground), _luminance(background)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


class TestTheFormulaItself:
    """The measure has to be right before the measurements mean anything."""

    def test_black_on_white_is_the_maximum(self) -> None:
        """21:1 is the ceiling WCAG defines, and a check on the arithmetic."""
        assert round(_contrast("#000000", "#ffffff")) == 21

    def test_a_colour_against_itself_is_the_minimum(self) -> None:
        """1:1, invisible -- the other end of the scale."""
        assert _contrast("#0f3460", "#0f3460") == pytest.approx(1.0)

    def test_the_order_of_the_arguments_does_not_matter(self) -> None:
        """Contrast is symmetric; a test that depended on order would be
        measuring the caller rather than the colours.
        """
        assert _contrast("#0f3460", "#f4f6f9") == pytest.approx(_contrast("#f4f6f9", "#0f3460"))


class TestEveryPairDqtPutsOnScreenClearsTheBar:
    """The gate. One parametrised case per commitment in the palette."""

    @pytest.mark.parametrize(
        ("foreground", "background", "minimum"),
        CONTRAST_REQUIREMENTS,
        ids=[f"{pair[0]}-on-{pair[1]}" for pair in CONTRAST_REQUIREMENTS],
    )
    def test_the_pair_meets_its_requirement(
        self, foreground: str, background: str, minimum: float
    ) -> None:
        """4.5:1 for text, 3:1 for graphical objects.

        The failure message names the ratio, so a designer changing a colour
        learns how far short it fell rather than only that it did.
        """
        ratio = _contrast(PALETTE[foreground], PALETTE[background])

        assert ratio >= minimum, f"{foreground} on {background} is {ratio:.2f}:1, needs {minimum}:1"

    def test_every_palette_colour_is_a_six_digit_hex(self) -> None:
        """The formula above assumes it, so the assumption is checked."""
        for name, colour in PALETTE.items():
            assert len(colour) == 7 and colour.startswith("#"), name

    def test_every_severity_has_a_requirement(self) -> None:
        """A colour with no row here is a colour nobody measured.

        The palette is the easy place to add one and forget, which is why
        this asks the question from the other side.
        """
        required = {pair[0] for pair in CONTRAST_REQUIREMENTS}

        for name in PALETTE:
            if name.startswith("sev_"):
                assert name in required, name


class TestTheStylesheetIsBuiltFromThePalette:
    """A measured palette proves nothing if the CSS hardcodes something else."""

    def test_every_palette_colour_appears_in_the_stylesheet(self) -> None:
        """Otherwise a colour could be measured and never used, or worse."""
        for name, colour in PALETTE.items():
            assert colour in STYLESHEET, name

    def test_no_other_colour_is_hardcoded(self) -> None:
        """The one that matters: an unmeasured colour on a page.

        Scans the stylesheet for hex literals and checks each against the
        palette, so a hand-added ``#ff0000`` fails here rather than reaching
        a reader.
        """
        import re

        found = set(re.findall(r"#[0-9a-fA-F]{6}", STYLESHEET))

        assert found <= set(PALETTE.values()), found - set(PALETTE.values())


class TestTheStylesheetSupportsTheOtherAccessRules:
    """Things `docs/PLAN-VIZ-UI.md` §4 asks for that are CSS decisions."""

    def test_focus_is_visible(self) -> None:
        """Keyboard users need to see where they are.

        Browsers give a default outline and stylesheets routinely remove it;
        stating one means a later reset cannot silently take it away.
        """
        assert ":focus-visible" in STYLESHEET
        assert "outline" in STYLESHEET

    def test_alignment_follows_the_reading_direction(self) -> None:
        """``text-align: left`` would strand every header in a Persian page.

        ``start`` follows ``dir``, which is what makes one stylesheet serve
        both languages instead of two that drift.
        """
        assert "text-align: start" in STYLESHEET
        assert "text-align: left" not in STYLESHEET

    def test_spacing_follows_the_reading_direction_too(self) -> None:
        """The same reasoning for the gap beside a severity mark."""
        assert "margin-inline-end" in STYLESHEET
        assert "margin-right" not in STYLESHEET

    def test_it_prints(self) -> None:
        """A report is printed and attached to tickets at least as often as
        it is read on screen, and a dark header bar costs a whole cartridge.
        """
        assert "@media print" in STYLESHEET
