"""Build HTML with escaping as the default (`VIZ-2`).

Private on purpose: this is how DQT assembles its own pages, not a template
engine for callers.

`reports.py` escaped correctly, through twenty-odd separate ``html.escape``
calls. That is correctness by per-line discipline — every one has to be
right, and the forgotten one fails *silently*, because the report still
renders and a table named ``<b>`` merely turns bold.

`docs/PLAN-VIZ-UI.md` §2.2 proposed Jinja2 for its autoescaping. This is the
same property without the dependency: `docs/BACKLOG.md` §4 rules out new hard
dependencies, and the Reports facet has to work with no extras installed, so
a builder that costs about as much code as the calls it replaces is the
better trade. The reversal is recorded in the plan.

One rule: **text is escaped, markup is explicit.** Content is escaped unless
wrapped in :class:`Raw`, and wrapping is the visible act that says "I built
this myself" — which is exactly what an SVG from :mod:`dqt.viz` is.

Example:
    from dqt._html import Raw, element, table

    row = element("td", "<not a tag>")
    chart_cell = element("td", Raw(chart.svg))
"""

from __future__ import annotations

import html
from collections.abc import Iterable, Mapping, Sequence

__all__ = ["Raw", "attributes", "document", "element", "table"]


class Raw(str):
    """Markup the caller built and vouches for.

    A ``str`` subclass rather than a wrapper, so that a built element is
    itself declared markup and nesting one inside another needs no ceremony.
    The alternative -- returning plain strings and asking callers to write
    ``Raw(element(...))`` at every nesting site -- puts the burden in the one
    place where forgetting it is invisible: the inner element renders as its
    own source text, which looks like a template bug rather than an escaping
    one.

    Example:
        cell = element("td", Raw("<svg/>"))
        row = element("tr", cell)  # cell is Raw, so it is not escaped again
    """

    __slots__ = ()


def _render(value: object) -> str:
    """Render one piece of content, escaping it unless it is :class:`Raw`.

    Args:
        value: Text, a number, or declared markup.

    Returns:
        The rendered fragment.

    Example:
        assert _render("<b>") == "&lt;b&gt;"
    """
    if isinstance(value, Raw):
        return str(value)
    return html.escape(str(value))


def attributes(attrs: Mapping[str, str]) -> str:
    """Render attributes, escaping every value.

    Values are escaped with quoting on. A quote inside an attribute closes
    it, which is the injection point hand-written HTML misses most often.

    Args:
        attrs: Attribute names and values, rendered in the order given so the
            output is deterministic.

    Returns:
        A string starting with a space, or empty when *attrs* is empty.

    Example:
        assert attributes({"class": "c"}) == ' class="c"'
    """
    if not attrs:
        return ""
    return "".join(f' {name}="{html.escape(str(value))}"' for name, value in attrs.items())


def element(
    tag: str,
    *children: object,
    attrs: Mapping[str, str] | None = None,
) -> Raw:
    """Render one element and its children.

    Args:
        tag: Element name.
        *children: Content, escaped unless wrapped in :class:`Raw`.
        attrs: Optional attributes.

    Returns:
        The element as :class:`Raw`, always explicitly closed — an unclosed
        tag swallows the rest of the document. Returning ``Raw`` is what lets
        one element be the child of another without being escaped again.

    Example:
        assert element("td", "x") == "<td>x</td>"
    """
    body = "".join(_render(child) for child in children)
    return Raw(f"<{tag}{attributes(attrs or {})}>{body}</{tag}>")


def table(headers: Sequence[str], rows: Iterable[Sequence[object]]) -> Raw:
    """Render a table from headers and rows.

    Every section of the report is a table, so this is where the shape is
    decided once.

    Args:
        headers: Column headings, escaped.
        rows: Row values, each escaped unless wrapped in :class:`Raw`.

    Returns:
        The table as :class:`Raw`. A table with no rows still renders its header: whether an
        empty section should appear at all is the report's judgement, since
        only it knows whether "no rows" means "nothing to report" or
        "nothing ran".

    Raises:
        ValueError: If a row is not the same width as *headers*. A short row
            silently shifts every cell after it and still renders, which is
            what makes it worth refusing here rather than in a browser.

    Example:
        assert "<th>A</th>" in table(["A"], [["x"]])
    """
    header_row = element("tr", *(element("th", name) for name in headers))
    body: list[Raw] = []
    for row in rows:
        if len(row) != len(headers):
            raise ValueError(
                f"A table row must match its header width: header has {len(headers)} "
                f"column(s), row has {len(row)}."
            )
        body.append(element("tr", *(element("td", cell) for cell in row)))
    return element("table", header_row, *body)


def document(*, title: str, body: Raw, css: str) -> Raw:
    """Wrap a body in a self-contained HTML document.

    Self-contained is the property that makes the report worth more to a DBA
    than a dashboard — it can be emailed, attached to a ticket and archived —
    and it stops being true the moment the page has to fetch anything, so the
    stylesheet is inlined rather than linked.

    Args:
        title: Document title, escaped.
        body: The assembled page content.
        css: Stylesheet text, inlined.

    Returns:
        The complete document.

    Example:
        page = document(title="Report", body=Raw("<h1>hi</h1>"), css="")
    """
    return Raw(
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="UTF-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        f"{element('title', title)}\n"
        f"{element('style', Raw(css))}\n"
        "</head>\n"
        f"{element('body', body)}\n"
        "</html>\n"
    )
