"""Unit tests for :mod:`dqt.classification`.

Every expected value in this file is hand-derived from the published
specification of the identifier under test, written out as arithmetic in a
comment above the fixture, and never obtained by running the code under test.
A reader can therefore check any fixture with a pen and this file alone.

Ground truths used:

* **Iranian national ID (کد ملی)** -- ten digits ``d1..d10``.  ``d10`` is a
  check digit defined by ``s = sum(d_i * (11 - i) for i in 1..9)`` (weights 10,
  9, 8, 7, 6, 5, 4, 3, 2) and ``r = s mod 11``.  The code is valid when
  ``r < 2 and d10 == r``, or when ``r >= 2 and d10 == 11 - r``.
* **IBAN / Sheba** -- ISO 13616 with the ISO 7064 MOD 97-10 check: move the
  first four characters to the end, replace each letter by its position in the
  alphabet plus nine (``A`` = 10 ... ``Z`` = 35), read the result as a decimal
  integer, and require ``value mod 97 == 1``.  An Iranian Sheba is the ``IR``
  case: ``IR`` plus two check digits plus a 22-digit BBAN, 26 characters total.
* **GB82 WEST 1234 5698 7654 32** is the IBAN example published in the ISO
  13616 / ECBS documentation and is used here as an external oracle for the
  generic IBAN path.  Its mod-97 reduction is written out below.

There is no database access anywhere in this file, and
``test_classification_module_performs_no_io`` asserts the module under test
cannot acquire one.
"""

from __future__ import annotations

import itertools
import pathlib
import re
from collections.abc import Iterator

import pytest

from dqt.classification import (
    ClassificationResult,
    classify_column,
    classify_column_name,
    classify_value,
    is_email_address,
    is_iranian_landline_number,
    is_iranian_mobile_number,
    is_shamsi_date,
    is_valid_iban,
    is_valid_iranian_national_id,
    is_valid_sheba,
    normalize_persian_text,
)

# ===========================================================================
# Iranian national ID -- hand-derived fixtures
# ===========================================================================

# Fixture NID-1 (valid, r < 2 branch).
#   first nine digits: 1 2 3 4 5 6 7 8 9
#   weights:          10 9 8 7 6 5 4 3 2
#   products:         10, 18, 24, 28, 30, 30, 28, 24, 18
#   s = 10+18+24+28+30+30+28+24+18 = 210
#   210 = 11 * 19 + 1  ->  r = 1
#   r < 2  ->  check digit must equal r = 1
VALID_NATIONAL_ID_LOW_REMAINDER = "1234567891"

# Fixture NID-2 (valid, r >= 2 branch, and leading zeros).
#   first nine digits: 0 0 1 2 3 4 5 6 7
#   weights:          10 9 8 7 6 5 4 3 2
#   products:          0,  0,  8, 14, 18, 20, 20, 18, 14
#   s = 0+0+8+14+18+20+20+18+14 = 112
#   112 = 11 * 10 + 2  ->  r = 2
#   r >= 2  ->  check digit must equal 11 - 2 = 9
VALID_NATIONAL_ID_HIGH_REMAINDER = "0012345679"

# Fixture NID-3 (published validator test vector, used as an external oracle).
#   digits:   0 4 9 9 3 7 0 8 9 | check 9
#   weights: 10 9 8 7 6 5 4 3 2
#   products: 0, 36, 72, 63, 18, 35, 0, 24, 18
#   s = 0+36+72+63+18+35+0+24+18 = 266
#   266 = 11 * 24 + 2  ->  r = 2
#   r >= 2  ->  check digit must equal 11 - 2 = 9, and d10 is 9.
VALID_NATIONAL_ID_PUBLISHED_SAMPLE = "0499370899"

# Fixture NID-4 (invalid: the check digit of NID-1 off by one).
#   Same s = 210, same r = 1, so the only admissible check digit is 1.
#   This fixture ends in 0, so it must be rejected.
INVALID_NATIONAL_ID_WRONG_CHECK_DIGIT = "1234567890"

# Fixture NID-5 (repeated digits -- passes the checksum, is never issued).
#   For a code of ten identical digits d:
#     s = d * (10+9+8+7+6+5+4+3+2) = 54 * d
#     54 mod 11 = 10, so r = (10 * d) mod 11.
#   d = 1: r = 10 -> check = 11 - 10 = 1 = d      (checksum satisfied)
#   d = 0: r = 0  -> check = 0 = d                (checksum satisfied)
#   Both therefore satisfy the arithmetic and both are rejected by policy.
REPEATED_DIGIT_NATIONAL_IDS = ("0000000000", "1111111111", "5555555555")


def test_valid_national_id_low_remainder_branch() -> None:
    """A code whose weighted sum leaves remainder 1 must accept check digit 1."""
    assert is_valid_iranian_national_id(VALID_NATIONAL_ID_LOW_REMAINDER) is True


def test_valid_national_id_high_remainder_branch() -> None:
    """A code whose weighted sum leaves remainder 2 must accept check digit 9."""
    assert is_valid_iranian_national_id(VALID_NATIONAL_ID_HIGH_REMAINDER) is True


def test_valid_national_id_published_sample() -> None:
    """The published validator test vector must be accepted."""
    assert is_valid_iranian_national_id(VALID_NATIONAL_ID_PUBLISHED_SAMPLE) is True


def test_invalid_national_id_wrong_check_digit() -> None:
    """A code differing from a valid one only in its check digit must be rejected."""
    assert is_valid_iranian_national_id(INVALID_NATIONAL_ID_WRONG_CHECK_DIGIT) is False


@pytest.mark.parametrize("code", REPEATED_DIGIT_NATIONAL_IDS)
def test_repeated_digit_national_ids_are_rejected(code: str) -> None:
    """Ten identical digits satisfy the checksum but are rejected as never issued."""
    assert is_valid_iranian_national_id(code) is False


@pytest.mark.parametrize(
    "code",
    ["", "123456789", "12345678912", "123456789a", "1234-56789", "۱۲۳۴۵۶۷۸۹۱"],
)
def test_national_id_rejects_non_ten_ascii_digit_input(code: str) -> None:
    """Anything that is not exactly ten ASCII digits is rejected before arithmetic."""
    assert is_valid_iranian_national_id(code) is False


# ===========================================================================
# Sheba and IBAN -- hand-derived fixtures
# ===========================================================================

# Fixture IBAN-1 (valid Sheba, check digits derived here).
#   BBAN chosen: "0620000000000000000001"  (22 digits: bank code 062 + 19 digits)
#   Check-digit derivation, per ISO 13616:
#     rearranged = BBAN + "IR" + "00" = "0620000000000000000001" + "1827" + "00"
#     as an integer X = B * 10**6 + 182700, where B = 620000000000000000001
#                                                  = 62 * 10**19 + 1
#     powers of ten modulo 97 (each step is the previous times ten, reduced):
#       10**1=10  10**2=3   10**3=30  10**4=9   10**5=90  10**6=27
#       10**7=76  10**8=81  10**9=34  10**10=49 10**11=5  10**12=50
#       10**13=15 10**14=53 10**15=45 10**16=62 10**17=38 10**18=89
#       10**19=17
#     B mod 97 = (62 * 17 + 1) mod 97 = 1055 mod 97 = 1055 - 970 = 85
#     85 * (10**6 mod 97) = 85 * 27 = 2295;  2295 - 97*23 = 2295 - 2231 = 64
#     182700 mod 97: 1827 mod 97 = 1827 - 1746 = 81; 81 * 3 = 243; 243 - 194 = 49
#     X mod 97 = (64 + 49) mod 97 = 113 - 97 = 16
#     check digits = 98 - 16 = 82
#   Verification of the finished IBAN "IR82" + BBAN:
#     rearranged = BBAN + "1827" + "82",  Y = B * 10**6 + 182782
#     182782 mod 97 = (49 + 82) mod 97 = 131 - 97 = 34
#     Y mod 97 = (64 + 34) mod 97 = 98 - 97 = 1   -> valid
VALID_SHEBA = "IR820620000000000000000001"

# Fixture IBAN-2 (invalid Sheba: check digits 82 -> 83).
#   Raising the check digits by one raises Y by one, so Y mod 97 = 2, not 1.
INVALID_SHEBA_WRONG_CHECK_DIGITS = "IR830620000000000000000001"

# Fixture IBAN-3 (published ISO 13616 / ECBS example, external oracle).
#   IBAN "GB82WEST12345698765432" (22 characters, the GB length).
#   rearranged = "WEST12345698765432" + "GB" + "82"
#   letters:  W=32  E=14  S=28  T=29  G=16  B=11
#   numeric  = "3214282912345698765432" + "1611" + "82"
#   Left-to-right reduction r = (r*10 + digit) mod 97, digit by digit:
#     3->3  2->32  1->30  4->13  2->35  8->67  2->90  9->36  1->70  2->23
#     3->39 4->6   5->65  6->74  9->70  8->29  7->6   6->66  5->83  4->58
#     3->1  2->12  1->24  6->52  1->36  1->70  8->29  2->1
#   final remainder 1  -> valid
VALID_GENERIC_IBAN = "GB82WEST12345698765432"

# Fixture IBAN-4 (invalid generic IBAN: last digit 2 -> 1).
#   The reduction is identical until the final step, where 29*10 + 1 = 291
#   and 291 = 97 * 3, so the remainder is 0, not 1.
INVALID_GENERIC_IBAN = "GB82WEST12345698765431"


def test_valid_sheba_is_accepted() -> None:
    """A Sheba whose check digits were derived from the BBAN must be accepted."""
    assert is_valid_sheba(VALID_SHEBA) is True


def test_sheba_with_wrong_check_digits_is_rejected() -> None:
    """Raising the check digits by one breaks the mod-97 identity."""
    assert is_valid_sheba(INVALID_SHEBA_WRONG_CHECK_DIGITS) is False


def test_sheba_tolerates_the_conventional_four_digit_grouping() -> None:
    """Sheba is conventionally printed in groups of four; spaces are matching noise."""
    assert is_valid_sheba("IR82 0620 0000 0000 0000 0000 01") is True


@pytest.mark.parametrize(
    "value",
    [
        "",
        "IR8206200000000000000001",  # 24 characters, not 26
        "IR82062000000000000000000123",  # 28 characters, not 26
        "GB82WEST12345698765432",  # valid IBAN, but not an Iranian one
        "IR8206200000000000000000A1",  # non-digit inside the BBAN
    ],
)
def test_sheba_rejects_wrong_shape(value: str) -> None:
    """Only ``IR`` plus 24 digits can be a Sheba, whatever its checksum says."""
    assert is_valid_sheba(value) is False


def test_valid_generic_iban_is_accepted() -> None:
    """The published ISO 13616 example must pass the mod-97 check."""
    assert is_valid_iban(VALID_GENERIC_IBAN) is True


def test_generic_iban_with_altered_final_digit_is_rejected() -> None:
    """Altering the published example's final digit must break the check."""
    assert is_valid_iban(INVALID_GENERIC_IBAN) is False


def test_a_valid_sheba_is_also_a_valid_iban() -> None:
    """Sheba is the Iranian case of IBAN, so the generic check must accept it too."""
    assert is_valid_iban(VALID_SHEBA) is True


# ===========================================================================
# Iranian telephone numbers -- recognised by shape, not validated
# ===========================================================================


@pytest.mark.parametrize(
    "value",
    [
        "09121234567",  # national form: 0 9 then nine digits
        "0912 123 4567",  # same number, conventional spacing
        "0912-123-4567",  # same number, hyphenated
        "+989121234567",  # international form
        "00989121234567",  # international form with the 00 prefix
        "09361234567",
        "09051234567",
    ],
)
def test_iranian_mobile_shapes_are_recognised(value: str) -> None:
    """An eleven-digit ``09`` number, in any of its written prefixes, is a mobile."""
    assert is_iranian_mobile_number(value) is True


@pytest.mark.parametrize(
    "value",
    [
        "",
        "0812345678",  # a landline, not a mobile
        "091212345678",  # twelve digits
        "0912123456",  # ten digits
        "9121234567",  # missing the national trunk prefix; deliberately not guessed
        "+9891212345678",  # one digit too many after +98
    ],
)
def test_non_mobile_shapes_are_rejected(value: str) -> None:
    """Anything that is not an eleven-digit ``09`` number is not a mobile."""
    assert is_iranian_mobile_number(value) is False


@pytest.mark.parametrize(
    "value",
    [
        "02112345678",  # Tehran
        "03112345678",  # Isfahan
        "021 1234 5678",
        "+982112345678",
        "00982112345678",
    ],
)
def test_iranian_landline_shapes_are_recognised(value: str) -> None:
    """An eleven-digit number starting ``0`` and not ``09`` is a landline shape."""
    assert is_iranian_landline_number(value) is True


@pytest.mark.parametrize(
    "value",
    [
        "",
        "09121234567",  # a mobile, not a landline
        "0211234567",  # ten digits
        "021123456789",  # twelve digits
        "2112345678",  # missing the national trunk prefix
    ],
)
def test_non_landline_shapes_are_rejected(value: str) -> None:
    """Wrong length, or a mobile prefix, is not a landline shape."""
    assert is_iranian_landline_number(value) is False


# ===========================================================================
# Shamsi (Jalali) dates -- recognised, never converted
# ===========================================================================


@pytest.mark.parametrize(
    "value",
    [
        "1403/06/14",  # month 6 has 31 days
        "1403-06-14",  # the hyphenated separator
        "1403/01/31",  # Farvardin, 31 days
        "1403/06/31",  # Shahrivar, the last 31-day month
        "1403/07/30",  # Mehr, 30 days
        "1403/11/30",  # Bahman, 30 days
        "1399/12/30",  # Esfand 30: accepted without a leap-year check
        "1200/01/01",  # lower bound of the plausible range
        "1500/12/29",  # upper bound of the plausible range
    ],
)
def test_shamsi_date_shapes_are_recognised(value: str) -> None:
    """Months 1-6 carry 31 days, 7-11 carry 30, and Esfand carries at most 30."""
    assert is_shamsi_date(value) is True


@pytest.mark.parametrize(
    "value",
    [
        "",
        "1403/13/01",  # month 13
        "1403/00/10",  # month 0
        "1403/07/31",  # Mehr has only 30 days
        "1403/12/31",  # Esfand never has 31 days
        "1403/06/00",  # day 0
        "1403/06/32",  # day 32
        "1199/01/01",  # below the plausible Shamsi year range
        "1501/01/01",  # above the plausible Shamsi year range
        "2024/01/15",  # a Gregorian year, which is what the range test excludes
        "1403/6/14",  # unpadded month
        "14030614",  # no separator
    ],
)
def test_non_shamsi_shapes_are_rejected(value: str) -> None:
    """Out-of-range parts, unpadded parts, and Gregorian years are all rejected."""
    assert is_shamsi_date(value) is False


# ===========================================================================
# Email
# ===========================================================================


@pytest.mark.parametrize(
    "value",
    [
        "ali@example.com",
        "a.b+tag@sub.example.co.uk",
        "user_name@example-domain.org",
    ],
)
def test_email_shapes_are_recognised(value: str) -> None:
    """A local part, an ``@``, a dotted domain and an alphabetic suffix."""
    assert is_email_address(value) is True


@pytest.mark.parametrize(
    "value",
    ["", "not-an-email", "foo@", "@bar.com", "a b@c.com", "a@b", "a@@b.com", "a@b..com"],
)
def test_non_email_shapes_are_rejected(value: str) -> None:
    """A missing part, an internal space, or a bare domain is not an address."""
    assert is_email_address(value) is False


# ===========================================================================
# Persian text normalization -- an explicit, opt-in, value-changing operation
# ===========================================================================

PERSIAN_DIGIT_NATIONAL_ID = "۱۲۳۴۵۶۷۸۹۱"
ARABIC_INDIC_DIGIT_NATIONAL_ID = "١٢٣٤٥٦٧٨٩١"


def test_persian_digits_fold_to_ascii() -> None:
    """U+06F0..U+06F9 are the Persian digit forms of ASCII 0-9."""
    assert normalize_persian_text(PERSIAN_DIGIT_NATIONAL_ID) == "1234567891"


def test_arabic_indic_digits_fold_to_ascii() -> None:
    """U+0660..U+0669 are the Arabic-Indic digit forms of ASCII 0-9."""
    assert normalize_persian_text(ARABIC_INDIC_DIGIT_NATIONAL_ID) == "1234567891"


def test_arabic_yeh_and_kaf_fold_to_their_persian_forms() -> None:
    """Arabic yeh U+064A and kaf U+0643 must become Persian U+06CC and U+06A9."""
    arabic_form = "كيان"
    persian_form = "کیان"
    assert normalize_persian_text(arabic_form) == persian_form


def test_alef_maksura_folds_to_persian_yeh() -> None:
    """Arabic alef maksura U+0649 is a third spelling of the same letter."""
    assert normalize_persian_text("ى") == "ی"


def test_zero_width_non_joiner_is_removed() -> None:
    """ZWNJ is orthographic, carries no identifier information, and is dropped."""
    assert normalize_persian_text("می‌رود") == "میرود"


def test_normalization_leaves_ascii_untouched() -> None:
    """ASCII text must survive normalization byte for byte."""
    ascii_text = "Ali-2026/06/14 a@b.com IR82"
    assert normalize_persian_text(ascii_text) == ascii_text


def test_normalization_is_idempotent() -> None:
    """Normalizing an already-normalized value must change nothing further."""
    once = normalize_persian_text("كي‌۱۲")
    assert normalize_persian_text(once) == once


def test_national_id_written_in_persian_digits_is_not_silently_normalized() -> None:
    """The validator itself never normalizes; that is the caller's explicit choice."""
    assert is_valid_iranian_national_id(PERSIAN_DIGIT_NATIONAL_ID) is False
    assert is_valid_iranian_national_id(normalize_persian_text(PERSIAN_DIGIT_NATIONAL_ID)) is True


# ===========================================================================
# classify_value
# ===========================================================================


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (VALID_NATIONAL_ID_LOW_REMAINDER, "iranian_national_id"),
        (VALID_SHEBA, "sheba"),
        (VALID_GENERIC_IBAN, "iban"),
        ("09121234567", "iranian_mobile_number"),
        ("02112345678", "iranian_landline_number"),
        ("ali@example.com", "email"),
        ("1403/06/14", "shamsi_date"),
        ("just some free text", "unknown"),
        ("", "unknown"),
    ],
)
def test_classify_value_assigns_the_expected_semantic_type(value: str, expected: str) -> None:
    """One value maps to exactly one semantic type under the documented precedence."""
    assert classify_value(value) == expected


def test_classify_value_prefers_sheba_over_the_generic_iban() -> None:
    """An Iranian IBAN satisfies both checks; the more specific type must win."""
    assert is_valid_iban(VALID_SHEBA) is True
    assert classify_value(VALID_SHEBA) == "sheba"


def test_classify_value_can_be_asked_to_normalize_first() -> None:
    """Normalization is opt-in and off by default, even inside classification."""
    assert classify_value(PERSIAN_DIGIT_NATIONAL_ID) == "unknown"
    assert (
        classify_value(PERSIAN_DIGIT_NATIONAL_ID, apply_persian_normalization=True)
        == "iranian_national_id"
    )


# ===========================================================================
# classify_column_name -- advisory hints only
# ===========================================================================


@pytest.mark.parametrize(
    ("column_name", "expected"),
    [
        ("email", "email"),
        ("Customer_EMail", "email"),
        ("e-mail address", "email"),
        ("sheba", "sheba"),
        ("shaba_number", "sheba"),
        ("iban", "iban"),
        ("national_id", "iranian_national_id"),
        ("code_melli", "iranian_national_id"),
        ("nationalCode", "iranian_national_id"),
        ("mobile", "iranian_mobile_number"),
        ("cell_phone", "iranian_mobile_number"),
        ("telephone", "iranian_landline_number"),
        ("shamsi_date", "shamsi_date"),
        ("jalali_birth_date", "shamsi_date"),
    ],
)
def test_column_name_hints_are_recognised(column_name: str, expected: str) -> None:
    """A column name suggests a type; separators and case must not matter."""
    assert classify_column_name(column_name) == expected


@pytest.mark.parametrize("column_name", ["", "created_at", "amount", "notes", "id"])
def test_column_names_without_a_hint_return_none(column_name: str) -> None:
    """A name that suggests nothing must return ``None``, never a guess."""
    assert classify_column_name(column_name) is None


# ===========================================================================
# classify_column
# ===========================================================================


def test_classify_column_reports_a_full_match() -> None:
    """A column whose sampled values all match reports that type at confidence 1.0."""
    result = classify_column("contact_email", ["a@b.com", "c@d.org", "e@f.net"])
    assert isinstance(result, ClassificationResult)
    assert result.column_name == "contact_email"
    assert result.semantic_type == "email"
    assert result.confidence == 1.0
    assert result.considered_count == 3
    assert result.matched_count == 3
    assert result.name_hint == "email"
    assert result.normalization_applied is False


def test_classify_column_ignores_nulls_and_blanks() -> None:
    """``None``, empty strings and whitespace are not evidence either way."""
    result = classify_column("contact_email", [None, "", "   ", "a@b.com"])
    assert result.semantic_type == "email"
    assert result.considered_count == 1
    assert result.matched_count == 1
    assert result.confidence == 1.0


def test_classify_column_returns_unknown_below_the_threshold() -> None:
    """Three matches in five values is 0.6, which fails the default 0.8 threshold."""
    values = ["a@b.com", "c@d.org", "e@f.net", "garbage", "more garbage"]
    result = classify_column("contact_email", values)
    assert result.semantic_type == "unknown"
    assert result.confidence == 0.0
    assert result.considered_count == 5
    assert result.match_ratios["email"] == 0.6


def test_classify_column_threshold_is_caller_controlled() -> None:
    """The same 0.6 ratio passes once the caller lowers the threshold to 0.6."""
    values = ["a@b.com", "c@d.org", "e@f.net", "garbage", "more garbage"]
    result = classify_column("contact_email", values, minimum_match_ratio=0.6)
    assert result.semantic_type == "email"
    assert result.confidence == 0.6
    assert result.matched_count == 3


def test_classify_column_with_no_usable_values_is_unknown() -> None:
    """An all-null sample yields no evidence, so no type may be asserted."""
    result = classify_column("national_id", [None, None, ""])
    assert result.semantic_type == "unknown"
    assert result.confidence == 0.0
    assert result.considered_count == 0
    assert result.matched_count == 0


def test_a_column_name_hint_never_overrides_the_values() -> None:
    """A promising name with unusable data must still classify as unknown."""
    result = classify_column("national_id", ["garbage", "junk", "not an id"])
    assert result.semantic_type == "unknown"
    assert result.name_hint == "iranian_national_id"


def test_a_column_name_hint_never_contradicts_the_values() -> None:
    """Values win outright: a column named ``notes`` holding Shebas is a Sheba column."""
    result = classify_column("notes", [VALID_SHEBA, VALID_SHEBA])
    assert result.semantic_type == "sheba"
    assert result.name_hint is None


def test_classify_column_records_every_detector_ratio() -> None:
    """``match_ratios`` is the evidence for the decision, including the rejects."""
    result = classify_column("shomare_sheba", [VALID_SHEBA, VALID_SHEBA])
    assert result.semantic_type == "sheba"
    assert result.match_ratios["sheba"] == 1.0
    assert result.match_ratios["iban"] == 1.0
    assert result.match_ratios["email"] == 0.0
    assert result.match_ratios["iranian_national_id"] == 0.0


def test_classify_column_normalization_is_opt_in_and_recorded() -> None:
    """Persian-digit values need normalization, and the result must say it happened."""
    values = [PERSIAN_DIGIT_NATIONAL_ID, PERSIAN_DIGIT_NATIONAL_ID]

    without = classify_column("code_melli", values)
    assert without.semantic_type == "unknown"
    assert without.normalization_applied is False

    with_normalization = classify_column("code_melli", values, apply_persian_normalization=True)
    assert with_normalization.semantic_type == "iranian_national_id"
    assert with_normalization.normalization_applied is True


def test_classify_column_rejects_an_out_of_range_threshold() -> None:
    """A threshold outside [0.0, 1.0] is a programming error, not a soft default."""
    with pytest.raises(ValueError):
        classify_column("x", ["a@b.com"], minimum_match_ratio=1.5)


def test_classify_column_rejects_a_non_positive_sample_cap() -> None:
    """A cap of zero would silently classify nothing; reject it loudly."""
    with pytest.raises(ValueError):
        classify_column("x", ["a@b.com"], max_sample_values=0)


# ===========================================================================
# Bounded sampling and layering
# ===========================================================================


def _endless_valid_national_ids() -> Iterator[str]:
    """Yield the same valid national ID forever."""
    return itertools.repeat(VALID_NATIONAL_ID_LOW_REMAINDER)


def test_classify_column_consumes_at_most_the_sample_cap() -> None:
    """The API must never require the whole column; the cap bounds consumption."""
    source = _endless_valid_national_ids()
    result = classify_column("code_melli", source, max_sample_values=50)
    assert result.semantic_type == "iranian_national_id"
    assert result.considered_count == 50
    # The generator must still be alive, proving the cap stopped consumption.
    assert next(source) == VALID_NATIONAL_ID_LOW_REMAINDER


def test_classify_column_default_sample_cap_is_bounded() -> None:
    """Even with no explicit cap, an unbounded source must terminate."""
    result = classify_column("code_melli", _endless_valid_national_ids())
    assert result.semantic_type == "iranian_national_id"
    assert result.considered_count == 1000


def test_classification_module_performs_no_io() -> None:
    """The classification facet is pure domain logic and must import no driver."""
    module_path = pathlib.Path(__file__).resolve().parents[2] / "src" / "dqt" / "classification.py"
    source = module_path.read_text(encoding="utf-8")
    forbidden = ["sqlite3", "psycopg", "import os", "open(", "requests", "dqt.sql"]
    for token in forbidden:
        assert token not in source, f"classification.py must not reference {token!r}"


def test_detector_patterns_are_compiled_once_at_module_scope() -> None:
    """Per-value ``re.compile`` would make classification cost grow with row count."""
    module_path = pathlib.Path(__file__).resolve().parents[2] / "src" / "dqt" / "classification.py"
    source = module_path.read_text(encoding="utf-8")
    for match in re.finditer(r"^(\s*).*re\.compile\(", source, re.M):
        assert match.group(1) == "", "re.compile must appear only at module scope"
