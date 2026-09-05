"""The English↔Persian vocabulary DQT renders reports and screens in (`VIZ-4`).

`docs/PLAN-VIZ-UI.md` §5: report and screen text are bilingual. **CLI output
and code stay English-only**, which this module does not change.

**A fixed glossary, not a translator.** A dimension name rendered two ways in
one report is a correctness bug rather than a style issue: a reader comparing
two sections cannot tell whether they describe the same dimension. The table
below is closed, and ``tests/unit/test_i18n.py`` proves it complete — so
nothing here needs a runtime fallback, and a missing translation fails a test
instead of quietly shipping an English word into a Persian page.

**Mirror the layout, not the data.** :func:`is_rtl` decides direction in one
place, and :func:`ltr_span` keeps identifiers, SQL and numbers left-to-right
inside it. ``orders.customer_id`` reordered by a bidirectional algorithm is
not a translation of anything — it is a different table name, and printing
one is worse than printing the English.

Charts do not mirror at all. A bar chart is a measurement, and reflecting it
would put the largest value where a Persian reader's eye starts while the
axis still said otherwise.

Example:
    from dqt.i18n import translate

    heading = translate("completeness", "fa")
"""

from __future__ import annotations

import html
from typing import Literal

__all__ = [
    "LANGUAGES",
    "TRANSLATIONS",
    "Language",
    "is_rtl",
    "ltr_span",
    "translate",
]

#: The languages DQT renders. Closed: adding one means adding every row
#: below, which is the point -- a language half-translated is worse than one
#: not offered.
Language = Literal["en", "fa"]

#: The same set, checkable at runtime.
LANGUAGES: tuple[Language, ...] = ("en", "fa")

#: Every word DQT puts on a page, in both languages.
#:
#: English is a row here rather than "the key itself". Treating the key as
#: the English text would make the two languages behave differently, and
#: would ship an internal identifier at a reader the day a key stopped being
#: a real word -- ``referential_integrity`` is exactly that day.
TRANSLATIONS: dict[str, dict[Language, str]] = {
    # Dimensions
    "completeness": {"en": "completeness", "fa": "کامل بودن"},
    "validity": {"en": "validity", "fa": "اعتبار"},
    "uniqueness": {"en": "uniqueness", "fa": "یکتایی"},
    "consistency": {"en": "consistency", "fa": "سازگاری"},
    "referential_integrity": {"en": "referential integrity", "fa": "یکپارچگی ارجاعی"},
    "timeliness": {"en": "timeliness", "fa": "به‌هنگام بودن"},
    # Severities
    "info": {"en": "info", "fa": "اطلاع"},
    "warning": {"en": "warning", "fa": "هشدار"},
    "error": {"en": "error", "fa": "خطا"},
    "critical": {"en": "critical", "fa": "بحرانی"},
    # Run statuses
    "success": {"en": "success", "fa": "موفق"},
    "partial": {"en": "partial", "fa": "ناقص"},
    "failed": {"en": "failed", "fa": "ناموفق"},
    # Screen and report labels
    "overview": {"en": "Overview", "fa": "نمای کلی"},
    "run": {"en": "Run", "fa": "اجرا"},
    "runs": {"en": "Runs", "fa": "اجراها"},
    "recent_runs": {"en": "Recent runs", "fa": "اجراهای اخیر"},
    "issues": {"en": "Issues", "fa": "مسائل"},
    "tables": {"en": "Tables", "fa": "جدول‌ها"},
    "schema": {"en": "Schema", "fa": "اسکیما"},
    "table": {"en": "Table", "fa": "جدول"},
    "column": {"en": "Column", "fa": "ستون"},
    "message": {"en": "Message", "fa": "پیام"},
    "severity": {"en": "Severity", "fa": "شدت"},
    "dimension": {"en": "Dimension", "fa": "بُعد"},
    "status": {"en": "Status", "fa": "وضعیت"},
    "connection": {"en": "connection", "fa": "اتصال"},
    "started": {"en": "started", "fa": "شروع"},
    "quality_by_dimension": {"en": "Quality by dimension", "fa": "کیفیت بر حسب بُعد"},
    "issues_by_dimension": {"en": "Issues by dimension", "fa": "مسائل بر حسب بُعد"},
    "issues_by_severity": {"en": "Issues by severity", "fa": "مسائل بر حسب شدت"},
    "not_measured": {"en": "not measured", "fa": "اندازه‌گیری نشده"},
    "no_runs": {"en": "No runs recorded yet.", "fa": "هنوز اجرایی ثبت نشده است."},
    "no_tables": {
        "en": "No tables were profiled in this run.",
        "fa": "در این اجرا جدولی پروفایل نشد.",
    },
    "no_issues": {
        "en": "No issues were found in this run.",
        "fa": "در این اجرا مسئله‌ای یافت نشد.",
    },
    "view_issues": {"en": "View issues", "fa": "مشاهدهٔ مسائل"},
    "stage_errors": {"en": "Stage Errors", "fa": "خطاهای مرحله"},
}


def translate(key: str, language: Language) -> str:
    """Return *key*'s word in *language*.

    Args:
        key: A key of :data:`TRANSLATIONS`.
        language: One of :data:`LANGUAGES`.

    Returns:
        The translated word.

    Raises:
        KeyError: If *key* is not in the glossary. Falling back to the key
            would print an internal identifier at a reader.
        ValueError: If *language* is not one DQT renders. The set is closed,
            and guessing would pick a language on someone's behalf.

    Example:
        assert translate("error", "en") == "error"
    """
    if language not in LANGUAGES:
        raise ValueError(f"Unknown language {language!r}; DQT renders {', '.join(LANGUAGES)}.")
    if key not in TRANSLATIONS:
        raise KeyError(f"No translation for {key!r}.")
    return TRANSLATIONS[key][language]


def is_rtl(language: Language) -> bool:
    """Report whether *language* reads right to left.

    Decided in one place so a report and a screen cannot disagree about it.

    Args:
        language: One of :data:`LANGUAGES`.

    Returns:
        True for Persian.

    Example:
        assert is_rtl("fa") is True
    """
    return language == "fa"


def ltr_span(value: object) -> str:
    """Wrap *value* so it stays left-to-right inside right-to-left text.

    Identifiers, SQL and numbers are data, not prose. Inside an RTL block a
    browser's bidirectional algorithm reorders bare Latin text, so this is
    what keeps ``orders.customer_id`` readable rather than merely present.

    The value is escaped, because identifiers come from the database like
    everything else.

    Args:
        value: Text or a number to keep in reading order.

    Returns:
        The wrapped, escaped markup.

    Example:
        assert ltr_span("orders") == '<span dir="ltr">orders</span>'
    """
    return f'<span dir="ltr">{html.escape(str(value))}</span>'
