"""The Persian font DQT embeds in its reports (`VIZ-4`).

Persian rendered without proper Arabic-script shaping is not slightly off, it
is unreadable: letters that should join stand apart and the words stop being
words. A report is a file someone emails or attaches to a ticket, so it
cannot assume the machine that opens it has a Persian font installed — the
font travels with the file.

**Vazirmatn**, SIL Open Font License, vendored here with its licence and
inlined as a ``data:`` URI. Never fetched at runtime: a report that fetches
its font renders correctly on the machine that made it and blankly on an
air-gapped one, which is exactly where a DBA opens it.

Only Persian pages carry it. Sixty-odd kilobytes of base64 in every English
report, to render text with no Persian in it, is cost with no reader.

Example:
    from dqt.fonts import embedded_font_face

    css = embedded_font_face("fa")
"""

from __future__ import annotations

import pathlib

from dqt.i18n import Language

__all__ = ["FONT_FILE", "LICENCE_FILE", "embedded_font_face"]

#: The vendored font.
FONT_FILE = pathlib.Path(__file__).with_name("Vazirmatn-Regular.woff2")

#: Its licence. The OFL requires this to accompany the font, and a font
#: vendored without one is a licensing defect that looks like a feature.
LICENCE_FILE = pathlib.Path(__file__).with_name("OFL.txt")

#: The family name the stylesheet asks for.
FONT_FAMILY = "Vazirmatn"


def embedded_font_face(language: Language) -> str:
    """Return the ``@font-face`` rule for *language*, or nothing.

    Args:
        language: The language the page is rendered in.

    Returns:
        CSS inlining the font as a ``data:`` URI for Persian, and the empty
        string for every other language.

    Example:
        assert "@font-face" in embedded_font_face("fa")
    """
    raise NotImplementedError
