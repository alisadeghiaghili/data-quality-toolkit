"""The English↔Persian vocabulary, and what RTL does not flip (`VIZ-4`).

`docs/PLAN-VIZ-UI.md` §5: report and screen text are bilingual; CLI output and
code stay English-only, which is unchanged.

**A fixed glossary, not a translator.** A dimension name rendered two ways in
one report is a correctness bug, not a style issue — a DBA comparing two
sections cannot tell whether ``اعتبار`` and ``درستی`` are the same dimension.
So the table is closed and complete by construction, and a test proves the
completeness rather than a fallback hiding a gap at runtime.

**Mirror the layout, not the data.** Navigation and reading order flip;
identifiers, SQL and numbers do not. ``orders.customer_id`` reversed is not a
translation of anything — it is a different table, and a report that prints
one is worse than a report in the wrong language.

**Charts do not mirror either.** A bar chart is a measurement, and reflecting
it would put the largest value where a Persian reader's eye starts while the
axis still says otherwise.
"""

from __future__ import annotations

import pytest

from dqt.common.models import get_args_of_dq_dimension
from dqt.i18n import LANGUAGES, TRANSLATIONS, is_rtl, ltr_span, translate


class TestTheGlossaryIsClosedAndComplete:
    """Completeness is proved here so nothing needs a runtime fallback."""

    def test_every_key_has_every_language(self) -> None:
        """A gap would surface as English inside a Persian report.

        Silently, and in the one place a reader cannot check it: they do not
        know whether the English word is a missing translation or a
        deliberate technical term.
        """
        for key, translations in TRANSLATIONS.items():
            assert set(translations) == set(LANGUAGES), key

    def test_every_dimension_is_translated(self) -> None:
        """The six dimensions are the vocabulary a report is built on.

        Derived from the canonical set rather than listed again, so adding a
        dimension fails here instead of quietly rendering in English.
        """
        for dimension in get_args_of_dq_dimension():
            assert dimension in TRANSLATIONS

    @pytest.mark.parametrize("severity", ["info", "warning", "error", "critical"])
    def test_every_severity_is_translated(self, severity: str) -> None:
        """Severity is the word a reader scans for first."""
        assert severity in TRANSLATIONS

    @pytest.mark.parametrize("status", ["success", "partial", "failed"])
    def test_every_run_status_is_translated(self, status: str) -> None:
        """A degraded run has to be legible in both languages."""
        assert status in TRANSLATIONS

    def test_no_two_keys_share_a_persian_word(self) -> None:
        """Two dimensions rendered identically would be indistinguishable.

        A reader comparing sections could not tell which one a number
        belonged to, which is worse than leaving one untranslated.
        """
        persian = [translations["fa"] for translations in TRANSLATIONS.values()]

        assert len(persian) == len(set(persian))


class TestTranslationRefusesToGuess:
    """An unknown key is a programming mistake, not a display decision."""

    def test_a_known_key_translates(self) -> None:
        """The ordinary case."""
        assert translate("completeness", "fa") == TRANSLATIONS["completeness"]["fa"]

    def test_english_returns_the_key_s_english_word(self) -> None:
        """English is a row in the table, not the absence of a translation.

        Treating the key itself as the English text would make the two
        languages behave differently -- and would silently ship an internal
        identifier to a reader the day a key stopped being a real word.
        """
        assert translate("referential_integrity", "en") == "referential integrity"

    def test_an_unknown_key_raises(self) -> None:
        """Falling back to the key would print ``run_status`` at a reader."""
        with pytest.raises(KeyError, match="no_such_key"):
            translate("no_such_key", "en")

    def test_an_unknown_language_raises(self) -> None:
        """The set is closed; guessing would pick a language for someone."""
        with pytest.raises(ValueError, match="language"):
            translate("completeness", "de")  # type: ignore[arg-type]


class TestDirectionIsAPropertyOfTheLanguage:
    """One place decides, so a page and a report cannot disagree."""

    def test_persian_is_right_to_left(self) -> None:
        """The reason the whole layout flips."""
        assert is_rtl("fa") is True

    def test_english_is_not(self) -> None:
        """Stated rather than assumed, since it is the default everywhere."""
        assert is_rtl("en") is False


class TestIdentifiersStayLeftToRight:
    """Mirror the layout, not the data."""

    def test_an_identifier_is_wrapped_with_its_own_direction(self) -> None:
        """``orders.customer_id`` reversed is a different table.

        Inside an RTL block a bare Latin identifier is reordered by the
        browser's bidirectional algorithm, so the wrapper is what keeps a
        name readable rather than merely present.
        """
        assert ltr_span("orders.customer_id") == ('<span dir="ltr">orders.customer_id</span>')

    def test_the_wrapped_text_is_escaped(self) -> None:
        """Identifiers come from the database like everything else."""
        assert "&lt;b&gt;" in ltr_span("<b>")

    def test_a_number_is_wrapped_too(self) -> None:
        """A count beside Persian text is reordered by the same algorithm."""
        assert 'dir="ltr"' in ltr_span("1,234")
