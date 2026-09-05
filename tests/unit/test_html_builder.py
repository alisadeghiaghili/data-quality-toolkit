"""Escaping as a default rather than a discipline (`VIZ-2`).

`reports.py` escapes correctly today, and it does so through twenty-odd
separate ``html.escape`` calls. That is correctness by per-line discipline:
every one of them has to be right, and the one that is forgotten fails
silently — the report renders, and a table named ``<b>`` quietly becomes
bold instead of being shown.

`docs/PLAN-VIZ-UI.md` §2.2 proposed Jinja2 for its autoescaping. This module
is the same property without the dependency, and the reason for the change is
recorded in that document: `docs/BACKLOG.md` §4 rules out new *hard*
dependencies, and the report facet has to work with no extras installed. A
sixty-line builder that escapes by default costs about as much code as the
``html.escape`` calls it replaces and makes forgetting one impossible.

The design is one rule: **text is escaped, markup is explicit.** Anything
passed as content is escaped unless it is wrapped in :class:`~dqt.\\_html.Raw`,
and wrapping is the visible act that says "I built this myself".
"""

from __future__ import annotations

import pytest

from dqt._html import Raw, attributes, document, element, table


class TestContentIsEscapedUnlessItIsDeclaredMarkup:
    """The default has to be the safe one, or it is not a default."""

    def test_text_content_is_escaped(self) -> None:
        """A table name that looks like a tag stays a table name."""
        assert element("td", "<b>x</b>") == "<td>&lt;b&gt;x&lt;/b&gt;</td>"

    def test_declared_markup_passes_through(self) -> None:
        """SVG built by ``dqt.viz`` is markup and must not be escaped twice.

        Double-escaping is the failure that follows over-correcting for the
        first one: the chart renders as its own source code.
        """
        assert element("td", Raw("<svg/>")) == "<td><svg/></td>"

    def test_several_children_are_joined_in_order(self) -> None:
        """Order matters in a document; a set or a dict would not preserve it."""
        assert element("tr", element("td", "a"), element("td", "b")) == (
            "<tr><td>a</td><td>b</td></tr>"
        )

    def test_a_number_is_rendered_without_the_caller_converting_it(self) -> None:
        """Counts are the most common content; ``str()`` at every call site
        is noise that invites a forgotten escape when a name goes through the
        same path.
        """
        assert element("td", 42) == "<td>42</td>"

    def test_an_empty_element_is_still_closed(self) -> None:
        """Unclosed tags cascade: one swallows the rest of the document."""
        assert element("td") == "<td></td>"


class TestAttributesAreEscapedToo:
    """A quote in an attribute value escapes the attribute."""

    def test_a_value_containing_a_quote_cannot_break_out(self) -> None:
        """The classic injection point, and the one hand-written HTML misses.

        ``html.escape`` with its default ``quote=True`` is what makes this
        safe; the builder must not be the thing that turns it off.
        """
        rendered = attributes({"title": 'a" onclick="evil()'})

        assert 'onclick="evil()"' not in rendered
        assert "&quot;" in rendered

    def test_attributes_render_in_the_order_given(self) -> None:
        """Deterministic output is what makes report tests assertable."""
        assert attributes({"class": "b", "id": "a"}) == ' class="b" id="a"'

    def test_no_attributes_render_as_nothing(self) -> None:
        """An empty mapping must not leave a stray space in the tag."""
        assert attributes({}) == ""

    def test_an_element_carries_its_attributes(self) -> None:
        """The two halves compose."""
        assert element("td", "x", attrs={"class": "c"}) == '<td class="c">x</td>'


class TestTablesAreBuiltFromRowsRatherThanStrings:
    """Every section of the report is a table; building them once is the point."""

    def test_a_table_renders_a_header_and_its_rows(self) -> None:
        """The shape every section shares."""
        rendered = table(["Name", "Count"], [["orders", 3]])

        assert "<th>Name</th><th>Count</th>" in rendered
        assert "<td>orders</td><td>3</td>" in rendered

    def test_cell_content_is_escaped(self) -> None:
        """The whole reason this is not string concatenation."""
        assert "&lt;script&gt;" in table(["A"], [["<script>"]])

    def test_a_cell_may_hold_declared_markup(self) -> None:
        """Score bars and severity indicators are cells."""
        assert "<svg/>" in table(["A"], [[Raw("<svg/>")]])

    def test_a_table_with_no_rows_still_renders_its_header(self) -> None:
        """An empty table is a statement; a missing one is a bug.

        The caller decides whether to show it at all -- that judgement lives
        in the report, which knows whether "no rows" means "nothing to
        report" or "nothing ran".
        """
        rendered = table(["Name"], [])

        assert "<th>Name</th>" in rendered
        assert "<td>" not in rendered

    def test_a_ragged_row_is_refused(self) -> None:
        """A row shorter than the header silently shifts every cell after it.

        The result still renders, which is what makes it worth refusing here
        rather than leaving it to be noticed in a browser.
        """
        with pytest.raises(ValueError, match="header"):
            table(["A", "B"], [["only-one"]])


class TestTheDocumentIsSelfContained:
    """`VIZ-0` pinned this on the report; here it is at the source."""

    def test_the_stylesheet_is_inlined(self) -> None:
        """The file has to keep working after it is emailed."""
        assert "<style>body{}</style>" in document(title="t", body=Raw(""), css="body{}")

    def test_the_title_is_escaped(self) -> None:
        """Titles carry run ids, which carry whatever the caller passed."""
        assert "&lt;b&gt;" in document(title="<b>", body=Raw(""), css="")

    def test_it_declares_utf8_and_a_language(self) -> None:
        """Persian arrives in `VIZ-4`; the encoding cannot be guessed then."""
        rendered = document(title="t", body=Raw(""), css="")

        assert 'charset="UTF-8"' in rendered
        assert "<html" in rendered

    def test_the_body_is_declared_markup(self) -> None:
        """The body is assembled from elements, so escaping it would break it."""
        assert "<h1>x</h1>" in document(title="t", body=Raw("<h1>x</h1>"), css="")
