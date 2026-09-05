"""The one stylesheet the report and the screens share (`VIZ-5`).

Private: this is how DQT paints its own pages.

Two reasons it exists. The first is duplication — `VIZ-2` and `VIZ-3` grew
near-identical CSS blocks in `reports.py` and `ui/pages.py`, and a severity
colour defined twice is a severity colour that will eventually mean two
different things.

The second is that **contrast has to be checkable**. `docs/PLAN-VIZ-UI.md` §4
commits DQT to WCAG 2.1 AA, and a commitment nothing measures is a wish. The
palette is named here and :data:`CONTRAST_REQUIREMENTS` says which pairs the
design puts in front of a reader and what each one owes them, so
``tests/unit/test_theme.py`` can compute every ratio and fail the build on a
colour that does not clear it.

Example:
    from dqt._theme import STYLESHEET

    page = document(title="t", body=body, css=STYLESHEET)
"""

from __future__ import annotations

__all__ = ["CONTRAST_REQUIREMENTS", "PALETTE", "STYLESHEET"]

#: Every colour DQT paints with, named once.
PALETTE: dict[str, str] = {
    "page": "#f4f6f9",
    "ink": "#1a1a2e",
    "muted": "#4a4a5e",
    "brand": "#0f3460",
    "on_brand": "#ffffff",
    "rule": "#e4e4e4",
    "stripe": "#f9f9f9",
    "track": "#e0e0e0",
    # Badge backgrounds and the text that sits on them.
    "ok_bg": "#d4edda",
    "ok_ink": "#155724",
    "warn_bg": "#fff3cd",
    "warn_ink": "#856404",
    "err_bg": "#f8d7da",
    "err_ink": "#721c24",
    # Severity marks, as VIZ-2 and VIZ-3 wrote them.
    "sev_info": "#17a2b8",
    "sev_warning": "#ffc107",
    "sev_error": "#dc3545",
    "sev_critical": "#721c24",
}

#: What the design owes a reader, as ``(foreground, background, minimum)``.
#:
#: 4.5:1 for body text and 3:1 for large text and graphical objects, per
#: WCAG 2.1 AA. Listing the pairs rather than deriving them is deliberate:
#: the question "which colours actually meet on screen" is answered by the
#: design, and a test that guessed would either miss a pair or invent one.
CONTRAST_REQUIREMENTS: tuple[tuple[str, str, float], ...] = (
    # Body text on the page.
    ("ink", "page", 4.5),
    ("muted", "page", 4.5),
    ("brand", "page", 4.5),
    ("ink", "stripe", 4.5),
    # Table headers.
    ("on_brand", "brand", 4.5),
    # Badges: text on its own background.
    ("ok_ink", "ok_bg", 4.5),
    ("warn_ink", "warn_bg", 4.5),
    ("err_ink", "err_bg", 4.5),
    # Graphical objects: bars against their track, marks against the page.
    ("brand", "track", 3.0),
    ("sev_info", "page", 3.0),
    ("sev_warning", "page", 3.0),
    ("sev_error", "page", 3.0),
    ("sev_critical", "page", 3.0),
)


def _stylesheet() -> str:
    """Build the shared stylesheet from :data:`PALETTE`.

    Returns:
        The CSS text, with every colour taken from the palette so the
        contrast tests measure what a reader actually sees.

    Example:
        assert "@media print" in _stylesheet()
    """
    colour = PALETTE
    return f"""
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
    font-family: 'Segoe UI', Arial, sans-serif;
    background: {colour["page"]}; color: {colour["ink"]}; padding: 24px;
}}
h1 {{ font-size: 1.5rem; color: {colour["brand"]}; margin-bottom: 4px; }}
h2 {{ font-size: 1.05rem; color: {colour["brand"]}; margin: 20px 0 8px; }}
a {{ color: {colour["brand"]}; }}
a:focus-visible, [tabindex]:focus-visible {{
    outline: 3px solid {colour["brand"]}; outline-offset: 2px;
}}
nav {{ font-size: 0.85rem; margin-bottom: 12px; }}
table {{ width: 100%; border-collapse: collapse; margin-bottom: 16px; font-size: 0.88rem; }}
th {{ background: {colour["brand"]}; color: {colour["on_brand"]}; padding: 8px 12px; text-align: start; }}
td {{ padding: 7px 12px; border-bottom: 1px solid {colour["rule"]}; }}
tr:nth-child(even) td {{ background: {colour["stripe"]}; }}
.badge {{
    display: inline-block; padding: 2px 8px; border-radius: 12px;
    font-size: 0.78rem; font-weight: 600;
}}
.ok {{ background: {colour["ok_bg"]}; color: {colour["ok_ink"]}; }}
.warn {{ background: {colour["warn_bg"]}; color: {colour["warn_ink"]}; }}
.err {{ background: {colour["err_bg"]}; color: {colour["err_ink"]}; }}
.meta {{ font-size: 0.82rem; color: {colour["muted"]}; margin-bottom: 8px; }}
.empty {{ font-size: 0.9rem; color: {colour["muted"]}; padding: 8px 0; }}
/* Charts from dqt.viz carry no colour of their own, so the page decides how
   one looks -- which is what lets a single set of primitives serve the report
   and the screens. */
.dqt-track {{ fill: {colour["track"]}; }}
.dqt-fill, .dqt-bar {{ fill: {colour["brand"]}; }}
.dqt-scorecard, .dqt-score-bar {{ vertical-align: middle; }}
.dqt-unmeasured {{ display: none; }}
.dqt-bar-label, .dqt-bar-value {{ font-size: 11px; fill: {colour["ink"]}; }}
.dqt-figure {{ margin: 0 0 12px 0; }}
/* The text equivalent is shown, not hidden. A sighted reader gets the numbers
   without hovering, and nothing has to be maintained twice. */
.dqt-chart-text {{ font-size: 0.78rem; color: {colour["muted"]}; margin-top: 2px; }}
.dqt-cards {{ display: flex; flex-wrap: wrap; gap: 16px; margin-bottom: 16px; }}
.dqt-severity {{ vertical-align: middle; margin-inline-end: 4px; }}
.dqt-severity-info {{ fill: {colour["sev_info"]}; }}
.dqt-severity-warning {{ fill: {colour["sev_warning"]}; }}
.dqt-severity-error {{ fill: {colour["sev_error"]}; }}
.dqt-severity-critical {{ fill: {colour["sev_critical"]}; }}
@media print {{
    body {{ background: {colour["on_brand"]}; padding: 0; }}
    th {{ background: {colour["on_brand"]}; color: {colour["ink"]}; border-bottom: 2px solid {colour["ink"]}; }}
}}
"""


#: The stylesheet both delivery modes use.
STYLESHEET = _stylesheet()
