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

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

__all__ = ["Raw", "attributes", "document", "element", "table"]


@dataclass(frozen=True, slots=True)
class Raw:
    """Markup the caller built and vouches for.

    Attributes:
        markup: HTML or SVG to emit unchanged.

    Example:
        cell = element("td", Raw("<svg/>"))
    """

    markup: str


#: Anything that can be the content of an element.
Content = "Raw | str | int | float"


def attributes(attrs: Mapping[str, str]) -> str:
    """Render attributes, escaping every value.

    Args:
        attrs: Attribute names and values, in the order given.

    Returns:
        A string starting with a space, or empty when *attrs* is empty.

    Example:
        assert attributes({"class": "c"}) == ' class="c"'
    """
    raise NotImplementedError


def element(
    tag: str,
    *children: object,
    attrs: Mapping[str, str] | None = None,
) -> str:
    """Render one element and its children.

    Args:
        tag: Element name.
        *children: Content, escaped unless wrapped in :class:`Raw`.
        attrs: Optional attributes.

    Returns:
        The element, always explicitly closed.

    Example:
        assert element("td", "x") == "<td>x</td>"
    """
    raise NotImplementedError


def table(headers: Sequence[str], rows: Iterable[Sequence[object]]) -> str:
    """Render a table from headers and rows.

    Args:
        headers: Column headings, escaped.
        rows: Row values, escaped unless wrapped in :class:`Raw`.

    Returns:
        The table.

    Raises:
        ValueError: If a row is not the same width as *headers*.

    Example:
        assert "<th>A</th>" in table(["A"], [["x"]])
    """
    raise NotImplementedError


def document(*, title: str, body: Raw, css: str) -> str:
    """Wrap a body in a self-contained HTML document.

    Args:
        title: Document title, escaped.
        body: The assembled page content.
        css: Stylesheet text, inlined.

    Returns:
        The complete document.

    Example:
        page = document(title="Report", body=Raw("<h1>hi</h1>"), css="")
    """
    raise NotImplementedError
