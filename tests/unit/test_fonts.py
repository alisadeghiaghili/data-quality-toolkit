"""The embedded Persian font (`VIZ-4`).

`docs/PLAN-VIZ-UI.md` §5: Persian rendered without proper Arabic-script
shaping is not slightly off, it is unreadable — letters that should join stand
apart, and the words stop being words. A report is a file someone emails to a
colleague or attaches to a ticket, so it cannot assume the machine that opens
it has a Persian font installed.

So the font travels with the file. Vazirmatn, SIL OFL, vendored into the
package and inlined as a `data:` URI.

Two things that follow from that, and both are tested here rather than
trusted:

* **The licence ships with it.** The OFL requires the licence to accompany
  the font, and a font vendored without one is a licensing defect that looks
  exactly like a working feature.
* **English reports do not carry it.** Sixty-seven kilobytes of base64 in
  every English report, to render text that has no Persian in it, is a cost
  with no reader.
"""

from __future__ import annotations

import pathlib

from dqt.fonts import FONT_FILE, LICENCE_FILE, embedded_font_face

#: Read off the file as downloaded from
#: ``https://cdn.jsdelivr.net/npm/vazirmatn@33.0.3/fonts/webfonts/``.
_EXPECTED_BYTES = 50684


class TestTheFontAndItsLicenceAreBothPresent:
    """A font vendored without its licence is a defect that looks like a feature."""

    def test_the_font_file_ships_with_the_package(self) -> None:
        """Not fetched at runtime: the report must work offline."""
        assert FONT_FILE.exists()

    def test_it_is_the_file_that_was_reviewed(self) -> None:
        """Pinned by size, so a silent replacement fails here.

        A font is opaque -- nobody reads a diff of one -- so the only place a
        swapped file can be caught is a test that knows what was approved.
        """
        assert FONT_FILE.stat().st_size == _EXPECTED_BYTES

    def test_it_is_actually_a_woff2(self) -> None:
        """The magic bytes, so a truncated download cannot pass as a font."""
        assert FONT_FILE.read_bytes()[:4] == b"wOF2"

    def test_the_open_font_licence_ships_beside_it(self) -> None:
        """The OFL requires the licence to accompany the font."""
        licence = LICENCE_FILE.read_text(encoding="utf-8")

        assert LICENCE_FILE.exists()
        assert "SIL Open Font License" in licence
        assert "Vazirmatn" in licence

    def test_both_files_live_inside_the_package(self) -> None:
        """Beside the code, so an installed wheel has them too.

        A file that only exists in a source checkout works in every test and
        fails for every user.
        """
        package = pathlib.Path(__file__).resolve().parents[2] / "src" / "dqt"

        for path in (FONT_FILE, LICENCE_FILE):
            assert package in path.parents


class TestTheFontIsEmbeddedOnlyWhereItIsRead:
    """Cost with no reader is still cost."""

    def test_persian_gets_an_inline_font_face(self) -> None:
        """Self-contained: a ``data:`` URI, never a URL.

        A report that fetches its font renders correctly on the machine that
        made it and blankly on an air-gapped one -- which is exactly where a
        DBA opens it.
        """
        css = embedded_font_face("fa")

        assert "@font-face" in css
        assert "Vazirmatn" in css
        assert "data:font/woff2;base64," in css
        assert "http" not in css

    def test_english_gets_nothing(self) -> None:
        """Sixty-odd kilobytes to render text with no Persian in it."""
        assert embedded_font_face("en") == ""

    def test_the_declaration_names_a_fallback(self) -> None:
        """If the face ever fails to load, the page must still be readable.

        A ``font-family`` with one name and no fallback renders in whatever
        the browser picks, which for Persian is often a font with no shaping
        at all.
        """
        assert "sans-serif" in embedded_font_face("fa")

    def test_the_inlined_font_is_the_vendored_one(self) -> None:
        """Decoded and compared, rather than assumed from a length.

        The point of inlining is that the reviewed file is the one that
        ships; a test that only checked "there is some base64 here" would not
        notice if it were something else.
        """
        import base64

        payload = embedded_font_face("fa").split("base64,")[1].split(")")[0]

        assert base64.b64decode(payload) == FONT_FILE.read_bytes()
