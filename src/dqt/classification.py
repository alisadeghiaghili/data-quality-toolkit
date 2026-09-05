"""
dqt.classification
==================

Semantic typing of columns -- the Classification facet.

Given a column name and a **bounded sample** of that column's values, this
module reports which semantic type the evidence supports: an e-mail address, an
IBAN, an Iranian Sheba, an Iranian national ID, an Iranian mobile or landline
number, or a Shamsi (Jalali) date. The answer is written into
``ColumnResult.semantic_type`` by whichever caller wires this facet into a run;
this module itself does no such wiring.

Validated versus recognised
---------------------------

The two prefixes in this module's function names are a deliberate distinction,
not a naming accident:

``is_valid_*``
    The value carries a check digit and that check digit was recomputed from
    the published algorithm. ``is_valid_iranian_national_id``,
    ``is_valid_iban`` and ``is_valid_sheba`` are in this group. A false answer
    is proof the value is wrong.
``is_*``
    The value has the right *shape* and its parts fall in plausible ranges.
    ``is_iranian_mobile_number``, ``is_iranian_landline_number``,
    ``is_shamsi_date`` and ``is_email_address`` are in this group. There is no
    check digit to verify, so a true answer means "well formed", never
    "allocated", "deliverable", or "a real calendar date".

Deliberately not implemented: Shamsi-to-Gregorian conversion. ``is_shamsi_date``
recognises the shape and range of a Shamsi date and does not check whether the
year is a leap year, so 30 Esfand is accepted in every year. Recognising
without converting is an admitted gap; converting without a verified algorithm
would be a silent one.

Normalization is never silent
-----------------------------

:func:`normalize_persian_text` changes values -- it folds Arabic letter and
digit variants to their Persian or ASCII forms and drops zero-width joiners.
That is a cleansing-shaped operation, so it never happens implicitly on a
read-only path. Callers opt in per call with ``apply_persian_normalization``,
the folded text is used for matching only, and
``ClassificationResult.normalization_applied`` records that it happened.

Cost per value
--------------

One ``str.translate`` when normalization is requested, then at most seven
``re.fullmatch`` calls, plus O(26) integer arithmetic for the two checksum
detectors. Every pattern is compiled once at import; nothing is compiled or
allocated per value. Classifying a column therefore costs
``O(min(sample size, max_sample_values) * 7)`` and does not grow with the size
of the table behind the sample.

This module is pure domain logic. It holds no connection, issues no query, and
touches no file: it can be exercised end to end without a database.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Literal

SemanticType = Literal[
    "email",
    "iban",
    "sheba",
    "iranian_national_id",
    "iranian_mobile_number",
    "iranian_landline_number",
    "shamsi_date",
    "unknown",
]

# ---------------------------------------------------------------------------
# Persian text normalization
# ---------------------------------------------------------------------------

# Built once and reused: str.translate takes a mapping of code point to
# replacement, where None means "delete this code point".
_PERSIAN_TRANSLATION_TABLE: dict[int, str | None] = {
    # Persian (extended Arabic-Indic) digits U+06F0..U+06F9.
    **{0x06F0 + offset: str(offset) for offset in range(10)},
    # Arabic-Indic digits U+0660..U+0669.
    **{0x0660 + offset: str(offset) for offset in range(10)},
    0x064A: "ی",  # Arabic yeh      -> Persian yeh
    0x0649: "ی",  # Arabic alef maksura -> Persian yeh
    0x0643: "ک",  # Arabic kaf      -> Persian kaf
    0x200C: None,  # zero-width non-joiner: orthographic, carries no data
    0x200D: None,  # zero-width joiner: same reasoning
}

#: The same fold, as ordered (source, replacement) pairs.
#:
#: ``str.translate`` applies every rule at once; SQL has no such operation,
#: so the knowledge facet's fold expression nests ``REPLACE`` calls instead
#: and applies them one after another. (Named in prose rather than as a
#: dotted path: this module must not reach into the SQL layer, and
#: ``test_classification_module_performs_no_io`` enforces that by reading the
#: source text, which cannot tell a comment from an import.) They agree only
#: because no replacement here is itself the source of another rule -- the
#: outputs are ASCII digits, Persian yeh and Persian kaf, none of which is
#: rewritten. ``tests/unit/sql/test_knowledge.py`` checks that rather than
#: trusting it: if the two ever disagreed, a value would pass in Python and
#: fail in SQL.
PERSIAN_FOLD_RULES: tuple[tuple[str, str], ...] = tuple(
    (chr(code_point), replacement if replacement is not None else "")
    for code_point, replacement in _PERSIAN_TRANSLATION_TABLE.items()
)

# ---------------------------------------------------------------------------
# Detector patterns -- compiled once, at module scope, never per value
# ---------------------------------------------------------------------------

# [0-9] rather than \d throughout: Python's \d also matches Persian and
# Arabic-Indic digits, which would make the "normalization is opt-in" contract
# a lie -- a Persian-digit national ID would match without anyone asking.
_TEN_ASCII_DIGITS = re.compile(r"[0-9]{10}")
_SHEBA_SHAPE = re.compile(r"IR[0-9]{24}")
_IBAN_SHAPE = re.compile(r"[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}")
_IRANIAN_MOBILE_SHAPE = re.compile(r"09[0-9]{9}")
_IRANIAN_LANDLINE_SHAPE = re.compile(r"0[1-8][0-9]{9}")
_SHAMSI_DATE_SHAPE = re.compile(r"([0-9]{4})([/-])([0-9]{2})\2([0-9]{2})")
_EMAIL_SHAPE = re.compile(
    r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+"
    r"(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*"
    r"@(?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\.)+"
    r"[A-Za-z]{2,}"
)
_WHITESPACE = re.compile(r"\s+")
_TELEPHONE_SEPARATORS = re.compile(r"[\s\-().]+")
_NON_ALPHANUMERIC = re.compile(r"[^a-z0-9]+")

# Shamsi month lengths: Farvardin..Shahrivar have 31 days, Mehr..Bahman have
# 30, and Esfand has 29 or 30 depending on the year. The leap rule is not
# implemented (see the module docstring), so 30 is the accepted maximum for
# Esfand in every year.
_SHAMSI_LONG_MONTH_COUNT = 6
_SHAMSI_MINIMUM_PLAUSIBLE_YEAR = 1200
_SHAMSI_MAXIMUM_PLAUSIBLE_YEAR = 1500


@dataclass
class ClassificationResult:
    """The outcome of classifying one column from a bounded sample of its values.

    Attributes:
        column_name: Name of the column that was classified.
        semantic_type: The type the sampled values support, or ``"unknown"``
            when no detector reached ``minimum_match_ratio``.
        confidence: Fraction of usable sampled values matching
            ``semantic_type``, in ``[0.0, 1.0]``. Exactly ``0.0`` whenever
            ``semantic_type`` is ``"unknown"``.
        considered_count: How many sampled values were usable -- ``None``,
            empty and whitespace-only values are excluded.
        matched_count: How many usable values matched ``semantic_type``.
            ``0`` when the type is ``"unknown"``.
        name_hint: The type suggested by the column name alone, or ``None``.
            Advisory metadata only: it never changes ``semantic_type``.
        normalization_applied: Whether Persian normalization was applied to the
            sampled values before matching. The stored values are never
            modified; this records only what the matcher saw.
        match_ratios: Match ratio of every detector, including the losing ones.
            This is the evidence behind the decision.

    Example::

        result = ClassificationResult(
            column_name="contact_email",
            semantic_type="email",
            confidence=1.0,
            considered_count=3,
            matched_count=3,
            name_hint="email",
        )
    """

    column_name: str
    semantic_type: SemanticType
    confidence: float
    considered_count: int
    matched_count: int
    name_hint: SemanticType | None = None
    normalization_applied: bool = False
    match_ratios: dict[str, float] = field(default_factory=dict)


def normalize_persian_text(value: str) -> str:
    """Fold Persian and Arabic letter and digit variants to canonical forms.

    Four rewrites are applied, each of which loses no information a data-quality
    check depends on: Persian (U+06F0..U+06F9) and Arabic-Indic
    (U+0660..U+0669) digits become ASCII digits; Arabic yeh (U+064A) and alef
    maksura (U+0649) become Persian yeh (U+06CC); Arabic kaf (U+0643) becomes
    Persian kaf (U+06A9); and the zero-width non-joiner and joiner (U+200C,
    U+200D) are removed. Nothing else is touched, so ASCII text is returned
    byte for byte and the operation is idempotent.

    This function changes values. Nothing in this module calls it implicitly --
    see the module docstring.

    Args:
        value: The text to normalize. May be empty.

    Returns:
        The folded text. Never ``None``, never longer than *value*.

    Example::

        normalize_persian_text("۰۹۱۲")   # -> "0912"
        normalize_persian_text("كي")     # -> "کی"
    """
    return value.translate(_PERSIAN_TRANSLATION_TABLE)


# ---------------------------------------------------------------------------
# Checksum-backed detectors
# ---------------------------------------------------------------------------


def is_valid_iranian_national_id(value: str) -> bool:
    """Report whether *value* is a checksum-valid Iranian national ID.

    The code is ten ASCII digits ``d1..d10``. Let
    ``s = sum(d_i * (11 - i) for i in 1..9)`` -- weights 10, 9, 8, 7, 6, 5, 4,
    3, 2 -- and ``r = s mod 11``. The code is valid when ``r < 2`` and
    ``d10 == r``, or when ``r >= 2`` and ``d10 == 11 - r``.

    Codes made of ten identical digits satisfy that arithmetic for every digit,
    because the weights sum to 54 and ``54 mod 11 = 10``. They are not issued,
    and this function rejects them. That is a policy decision layered on top of
    the checksum, and it is the only one.

    No normalization and no separator stripping: the input must already be ten
    ASCII digits. A national ID written in Persian digits is rejected until the
    caller folds it explicitly with :func:`normalize_persian_text`.

    Args:
        value: The candidate national ID. Anything that is not exactly ten
            ASCII digits is rejected before any arithmetic runs.

    Returns:
        ``True`` only when the check digit matches and the code is not a
        repeated-digit sequence.

    Example::

        is_valid_iranian_national_id("0499370899")   # -> True
        is_valid_iranian_national_id("1111111111")   # -> False, never issued
    """
    if not _TEN_ASCII_DIGITS.fullmatch(value):
        return False
    if value == value[0] * 10:
        return False
    weighted_sum = sum(int(value[position]) * (10 - position) for position in range(9))
    remainder = weighted_sum % 11
    check_digit = int(value[9])
    if remainder < 2:
        return check_digit == remainder
    return check_digit == 11 - remainder


def _iban_check_remainder(compact: str) -> int:
    """Return the ISO 7064 MOD 97-10 remainder of an already-compacted IBAN.

    The first four characters move to the end, each letter becomes its
    zero-based alphabet position plus ten (``A`` -> 10 ... ``Z`` -> 35), and
    the resulting decimal string is reduced modulo 97.

    Args:
        compact: An upper-case IBAN with no whitespace, already known to match
            :data:`_IBAN_SHAPE`.

    Returns:
        The remainder modulo 97. A well-formed IBAN yields ``1``.
    """
    rearranged = compact[4:] + compact[:4]
    digits = "".join(
        str(ord(character) - 55) if character.isalpha() else character for character in rearranged
    )
    return int(digits) % 97


def is_valid_iban(value: str) -> bool:
    """Report whether *value* is a checksum-valid IBAN under ISO 13616.

    The value is compacted (whitespace removed, upper-cased) and must then be
    two letters, two check digits and 11 to 30 further alphanumerics -- 15 to
    34 characters in total. The ISO 7064 MOD 97-10 reduction must yield 1.

    Country-specific length rules are **not** enforced, because that would mean
    owning and maintaining the IBAN registry. A string of the right general
    shape whose checksum happens to hold is therefore accepted even if its
    length is wrong for its country code.

    Args:
        value: The candidate IBAN. Conventional four-character grouping is
            tolerated; any other punctuation is not.

    Returns:
        ``True`` when the shape matches and the mod-97 check yields 1.

    Example::

        is_valid_iban("GB82WEST12345698765432")   # -> True
    """
    compact = _WHITESPACE.sub("", value).upper()
    if not _IBAN_SHAPE.fullmatch(compact):
        return False
    return _iban_check_remainder(compact) == 1


def is_valid_sheba(value: str) -> bool:
    """Report whether *value* is a checksum-valid Iranian Sheba.

    A Sheba is the Iranian case of IBAN: the literal ``IR``, two check digits
    and a 22-digit BBAN, 26 characters in total, verified with the same ISO
    7064 MOD 97-10 reduction as :func:`is_valid_iban`.

    A bare 24-digit string is **not** accepted. Deriving the ``IR`` prefix from
    a column's context would be a guess, and a guess inside a validator is
    indistinguishable from a bug.

    Args:
        value: The candidate Sheba. Conventional four-digit grouping is
            tolerated; any other punctuation is not.

    Returns:
        ``True`` when the value is ``IR`` plus 24 digits and the mod-97 check
        yields 1.

    Example::

        is_valid_sheba("IR820620000000000000000001")   # -> True
    """
    compact = _WHITESPACE.sub("", value).upper()
    if not _SHEBA_SHAPE.fullmatch(compact):
        return False
    return _iban_check_remainder(compact) == 1


# ---------------------------------------------------------------------------
# Shape-recognising detectors
# ---------------------------------------------------------------------------


def _iranian_national_telephone_form(value: str) -> str:
    """Rewrite an Iranian telephone number into its national ``0``-prefixed form.

    Separators conventionally used in printed numbers -- spaces, hyphens,
    parentheses and dots -- are removed, and the ``+98`` and ``0098``
    international prefixes are replaced by the national trunk prefix ``0``.
    A bare ``98`` prefix is deliberately not handled: it is indistinguishable
    from a subscriber number that happens to start with 98.

    Args:
        value: The candidate telephone number as written.

    Returns:
        The same number in national form, or the separator-stripped input
        unchanged when no international prefix was present.
    """
    compact = _TELEPHONE_SEPARATORS.sub("", value)
    if compact.startswith("+98"):
        return "0" + compact[3:]
    if compact.startswith("0098"):
        return "0" + compact[4:]
    return compact


def is_iranian_mobile_number(value: str) -> bool:
    """Report whether *value* has the shape of an Iranian mobile number.

    An Iranian mobile number is eleven digits beginning ``09`` in national
    form. The ``+98`` and ``0098`` international prefixes are accepted and
    rewritten before matching, as are the spaces, hyphens, parentheses and dots
    numbers are conventionally printed with.

    This is shape recognition, not validation. Operator prefix allocations are
    reference data that changes, and this module owns no reference data, so a
    true answer means the number is well formed -- never that it is allocated
    or in service.

    Args:
        value: The candidate telephone number as written.

    Returns:
        ``True`` when the number reduces to eleven digits beginning ``09``.

    Example::

        is_iranian_mobile_number("+98 912 123 4567")   # -> True
    """
    return bool(_IRANIAN_MOBILE_SHAPE.fullmatch(_iranian_national_telephone_form(value)))


def is_iranian_landline_number(value: str) -> bool:
    """Report whether *value* has the shape of an Iranian landline number.

    An Iranian landline is eleven digits in national form: the trunk prefix
    ``0``, an area code whose first digit is 1 to 8, and eight further digits.
    The second digit is what separates a landline from a mobile, which uses 9.

    The published area-code list is **not** enforced. That list is reference
    data belonging to the Knowledge/Domain facet, which does not exist yet, so
    this detector recognises the shape and says so rather than pretending to a
    completeness it cannot back.

    Args:
        value: The candidate telephone number as written.

    Returns:
        ``True`` when the number reduces to eleven digits beginning ``0``
        followed by a digit in 1..8.

    Example::

        is_iranian_landline_number("021 1234 5678")   # -> True
    """
    return bool(_IRANIAN_LANDLINE_SHAPE.fullmatch(_iranian_national_telephone_form(value)))


def is_shamsi_date(value: str) -> bool:
    """Report whether *value* has the shape of a plausible Shamsi (Jalali) date.

    The accepted form is ``YYYY/MM/DD`` or ``YYYY-MM-DD``, zero-padded, with a
    single separator used consistently. The year must fall in 1200..1500, which
    is what distinguishes a Shamsi date from a Gregorian one written the same
    way. Months 1 to 6 carry 31 days, months 7 to 11 carry 30, and Esfand
    carries at most 30.

    No calendar conversion happens here and none is planned in this module: the
    Esfand leap rule is not applied, so 30 Esfand is accepted in every year,
    including years in which it does not exist. A value accepted here is
    Shamsi-*shaped*, not a proven date.

    Args:
        value: The candidate date string. Unpadded parts and missing separators
            are rejected.

    Returns:
        ``True`` when the shape matches and every part is in range.

    Example::

        is_shamsi_date("1403/06/14")   # -> True
        is_shamsi_date("1403/07/31")   # -> False, Mehr has 30 days
    """
    match = _SHAMSI_DATE_SHAPE.fullmatch(value)
    if match is None:
        return False
    year = int(match.group(1))
    month = int(match.group(3))
    day = int(match.group(4))
    if not _SHAMSI_MINIMUM_PLAUSIBLE_YEAR <= year <= _SHAMSI_MAXIMUM_PLAUSIBLE_YEAR:
        return False
    if not 1 <= month <= 12:
        return False
    longest_day = 31 if month <= _SHAMSI_LONG_MONTH_COUNT else 30
    return 1 <= day <= longest_day


def is_email_address(value: str) -> bool:
    """Report whether *value* has the shape of an e-mail address.

    The pattern is the pragmatic one: a dot-separated local part, an ``@``, a
    dot-separated domain whose labels start and end alphanumerically, and an
    alphabetic top-level label of at least two characters. It is deliberately
    not RFC 5322 -- quoted local parts, comments and bracketed address literals
    are rejected, because a column holding them is far more likely to hold
    corrupt data than exotic valid data.

    Internationalised addresses are out of scope: a non-ASCII local part or
    domain is rejected rather than half-supported.

    Args:
        value: The candidate address.

    Returns:
        ``True`` when the value matches the pattern in full. This says nothing
        about whether the address exists or is deliverable.

    Example::

        is_email_address("a.b+tag@sub.example.co.uk")   # -> True
    """
    return bool(_EMAIL_SHAPE.fullmatch(value))


# ---------------------------------------------------------------------------
# Detector registry and column-name hints
# ---------------------------------------------------------------------------

# Declaration order is precedence order: the first entry wins a tie. It runs
# most specific to least, which is why a valid Iranian IBAN classifies as
# "sheba" even though `is_valid_iban` also accepts it.
_DETECTORS: tuple[tuple[SemanticType, Callable[[str], bool]], ...] = (
    ("iranian_national_id", is_valid_iranian_national_id),
    ("sheba", is_valid_sheba),
    ("iban", is_valid_iban),
    ("iranian_mobile_number", is_iranian_mobile_number),
    ("iranian_landline_number", is_iranian_landline_number),
    ("email", is_email_address),
    ("shamsi_date", is_shamsi_date),
)

# Substring hints checked in order against the squashed column name, so the
# more specific keyword must come first: "cell_phone" must reach the mobile
# entry before the "phone" entry claims it.
_COLUMN_NAME_HINTS: tuple[tuple[str, SemanticType], ...] = (
    ("nationalid", "iranian_national_id"),
    ("nationalcode", "iranian_national_id"),
    ("codemelli", "iranian_national_id"),
    ("kodemelli", "iranian_national_id"),
    ("melli", "iranian_national_id"),
    ("sheba", "sheba"),
    ("shaba", "sheba"),
    ("iban", "iban"),
    ("email", "email"),
    ("mail", "email"),
    ("mobile", "iranian_mobile_number"),
    ("cellphone", "iranian_mobile_number"),
    ("cell", "iranian_mobile_number"),
    ("hamrah", "iranian_mobile_number"),
    ("landline", "iranian_landline_number"),
    ("telephone", "iranian_landline_number"),
    ("phone", "iranian_landline_number"),
    ("shamsi", "shamsi_date"),
    ("jalali", "shamsi_date"),
)


def classify_column_name(column_name: str) -> SemanticType | None:
    """Suggest a semantic type from a column name alone.

    The name is lower-cased and stripped of everything that is not an ASCII
    letter or digit, so ``"Customer_EMail"``, ``"e-mail address"`` and
    ``"customeremail"`` all reduce to the same key. The first matching hint in
    the module's ordered table wins.

    The result is **advisory only**. :func:`classify_column` records it and
    never lets it decide, override, or break a tie between detectors: a column
    named ``national_id`` holding rubbish is an ``unknown`` column, not a
    national-ID column.

    Args:
        column_name: The column name as reported by schema discovery. May be
            empty.

    Returns:
        The suggested :data:`SemanticType`, or ``None`` when the name suggests
        nothing. ``None`` is never a guess.

    Example::

        classify_column_name("code_melli")   # -> "iranian_national_id"
        classify_column_name("created_at")   # -> None
    """
    squashed = _NON_ALPHANUMERIC.sub("", column_name.lower())
    if not squashed:
        return None
    for keyword, semantic_type in _COLUMN_NAME_HINTS:
        if keyword in squashed:
            return semantic_type
    return None


def classify_value(value: str, *, apply_persian_normalization: bool = False) -> SemanticType:
    """Classify a single value into exactly one semantic type.

    Detectors run in the module's fixed precedence order -- most specific
    first -- and the first one to accept the value wins. A valid Iranian IBAN
    therefore classifies as ``"sheba"`` rather than ``"iban"``, even though
    both detectors accept it.

    Args:
        value: The value to classify. Surrounding whitespace is ignored; an
            empty or whitespace-only value classifies as ``"unknown"``.
        apply_persian_normalization: When ``True``, :func:`normalize_persian_text`
            is applied to a copy of the value before matching. Defaults to
            ``False``, so a value written in Persian digits classifies as
            ``"unknown"`` until the caller asks for the fold.

    Returns:
        The matching :data:`SemanticType`, or ``"unknown"`` when no detector
        accepts the value.

    Example::

        classify_value("IR820620000000000000000001")   # -> "sheba"
        classify_value("just some free text")          # -> "unknown"
    """
    candidate = normalize_persian_text(value) if apply_persian_normalization else value
    candidate = candidate.strip()
    if not candidate:
        return "unknown"
    for semantic_type, detector in _DETECTORS:
        if detector(candidate):
            return semantic_type
    return "unknown"


def classify_column(
    column_name: str,
    sample_values: Iterable[str | None],
    *,
    minimum_match_ratio: float = 0.8,
    max_sample_values: int = 1000,
    apply_persian_normalization: bool = False,
) -> ClassificationResult:
    """Classify one column from a bounded sample of its values.

    Every detector is run against every usable value, producing a match ratio
    per detector. The highest ratio wins, ties break by the module's fixed
    precedence order, and the winner is reported only if it reaches
    *minimum_match_ratio*. Otherwise the column is ``"unknown"`` -- a column
    that is 60% e-mail addresses is a data-quality problem, not an e-mail
    column.

    The sample is consumed lazily and never more than *max_sample_values*
    items are pulled from it, so an unbounded iterator is safe and the whole
    column is never required. Nothing here reads the database; the caller
    supplies the sample.

    Args:
        column_name: Name of the column being classified. Used for the
            advisory ``name_hint`` and echoed in the result.
        sample_values: A bounded sample of the column's values. ``None``,
            empty and whitespace-only entries are skipped and excluded from
            ``considered_count``. Any iterable is accepted, including a
            generator over a server-side cursor.
        minimum_match_ratio: Fraction of usable values a detector must match to
            be reported, in ``[0.0, 1.0]``. Defaults to ``0.8``. At ``0.0``
            every non-zero ratio is accepted; at ``1.0`` a single stray value
            forces ``"unknown"``.
        max_sample_values: Hard ceiling on how many items are pulled from
            *sample_values*. Must be positive. Defaults to ``1000``.
        apply_persian_normalization: When ``True``, each sampled value is
            folded with :func:`normalize_persian_text` before matching. The
            stored values are never modified. Defaults to ``False``.

    Returns:
        A :class:`ClassificationResult` carrying the decision, its confidence,
        the counts behind it, the advisory name hint, whether normalization was
        applied, and the match ratio of every detector including the losers.

    Raises:
        ValueError: If *minimum_match_ratio* is outside ``[0.0, 1.0]``, or
            *max_sample_values* is not positive.

    Example::

        classify_column("contact_email", ["a@b.com", "c@d.org"]).semantic_type
        # -> "email"

    """
    if not 0.0 <= minimum_match_ratio <= 1.0:
        raise ValueError(f"minimum_match_ratio must be in [0.0, 1.0], got {minimum_match_ratio!r}.")
    if max_sample_values <= 0:
        raise ValueError(f"max_sample_values must be positive, got {max_sample_values!r}.")

    match_counts: dict[str, int] = {semantic_type: 0 for semantic_type, _ in _DETECTORS}
    considered_count = 0
    iterator = iter(sample_values)
    for _ in range(max_sample_values):
        try:
            raw_value = next(iterator)
        except StopIteration:
            break
        if raw_value is None:
            continue
        candidate = normalize_persian_text(raw_value) if apply_persian_normalization else raw_value
        candidate = candidate.strip()
        if not candidate:
            continue
        considered_count += 1
        for semantic_type, detector in _DETECTORS:
            if detector(candidate):
                match_counts[semantic_type] += 1

    match_ratios: dict[str, float] = {
        semantic_type: (match_counts[semantic_type] / considered_count if considered_count else 0.0)
        for semantic_type, _ in _DETECTORS
    }

    best_type: SemanticType = "unknown"
    best_ratio = 0.0
    for semantic_type, _ in _DETECTORS:
        if match_ratios[semantic_type] > best_ratio:
            best_ratio = match_ratios[semantic_type]
            best_type = semantic_type

    name_hint = classify_column_name(column_name)
    if best_type == "unknown" or best_ratio < minimum_match_ratio:
        return ClassificationResult(
            column_name=column_name,
            semantic_type="unknown",
            confidence=0.0,
            considered_count=considered_count,
            matched_count=0,
            name_hint=name_hint,
            normalization_applied=apply_persian_normalization,
            match_ratios=match_ratios,
        )
    return ClassificationResult(
        column_name=column_name,
        semantic_type=best_type,
        confidence=best_ratio,
        considered_count=considered_count,
        matched_count=match_counts[best_type],
        name_hint=name_hint,
        normalization_applied=apply_persian_normalization,
        match_ratios=match_ratios,
    )


__all__ = [
    "ClassificationResult",
    "SemanticType",
    "classify_column",
    "classify_column_name",
    "classify_value",
    "is_email_address",
    "is_iranian_landline_number",
    "is_iranian_mobile_number",
    "is_shamsi_date",
    "is_valid_iban",
    "is_valid_iranian_national_id",
    "is_valid_sheba",
    "normalize_persian_text",
]
