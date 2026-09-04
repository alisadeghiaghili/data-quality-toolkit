"""
dqt.classification
==================

Semantic typing of columns -- the Classification facet.

**This module is a placeholder.** It declares the public surface that
``tests/unit/test_classification.py`` exercises so that the test suite fails on
behavioural assertions rather than on an import error. Every detector below is
planned; none is implemented yet, and each one currently returns the
"no evidence" answer.

The module is pure domain logic: it takes values and column names, and returns
types. It opens nothing, reads nothing, and holds no connection.
"""

from __future__ import annotations

from collections.abc import Iterable
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


@dataclass
class ClassificationResult:
    """The outcome of classifying one column from a bounded sample of its values.

    Attributes:
        column_name: Name of the column that was classified.
        semantic_type: Planned -- the type the sampled values support, or
            ``"unknown"``.
        confidence: Planned -- the fraction of considered values matching
            ``semantic_type``.
        considered_count: Planned -- how many sampled values were usable.
        matched_count: Planned -- how many of those matched ``semantic_type``.
        name_hint: Planned -- the type suggested by the column name alone.
        normalization_applied: Planned -- whether Persian normalization was
            applied for matching purposes.
        match_ratios: Planned -- the match ratio of every detector.

    Example::

        result = ClassificationResult(
            column_name="contact_email",
            semantic_type="unknown",
            confidence=0.0,
            considered_count=0,
            matched_count=0,
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

    Planned. This placeholder returns *value* unchanged.

    Args:
        value: The text to normalize.

    Returns:
        The value unchanged, until the real mapping lands.

    Example::

        normalize_persian_text("۱۲")
    """
    return value


def is_valid_iranian_national_id(value: str) -> bool:
    """Report whether *value* is a checksum-valid Iranian national ID.

    Planned. This placeholder always answers ``False``.

    Args:
        value: The candidate national ID.

    Returns:
        ``False``, until the check-digit arithmetic lands.

    Example::

        is_valid_iranian_national_id("0499370899")
    """
    del value
    return False


def is_valid_iban(value: str) -> bool:
    """Report whether *value* is a checksum-valid IBAN.

    Planned. This placeholder always answers ``False``.

    Args:
        value: The candidate IBAN.

    Returns:
        ``False``, until the mod-97 check lands.

    Example::

        is_valid_iban("GB82WEST12345698765432")
    """
    del value
    return False


def is_valid_sheba(value: str) -> bool:
    """Report whether *value* is a checksum-valid Iranian Sheba.

    Planned. This placeholder always answers ``False``.

    Args:
        value: The candidate Sheba.

    Returns:
        ``False``, until the mod-97 check lands.

    Example::

        is_valid_sheba("IR820620000000000000000001")
    """
    del value
    return False


def is_iranian_mobile_number(value: str) -> bool:
    """Report whether *value* has the shape of an Iranian mobile number.

    Planned. This placeholder always answers ``False``.

    Args:
        value: The candidate telephone number.

    Returns:
        ``False``, until the shape patterns land.

    Example::

        is_iranian_mobile_number("09121234567")
    """
    del value
    return False


def is_iranian_landline_number(value: str) -> bool:
    """Report whether *value* has the shape of an Iranian landline number.

    Planned. This placeholder always answers ``False``.

    Args:
        value: The candidate telephone number.

    Returns:
        ``False``, until the shape patterns land.

    Example::

        is_iranian_landline_number("02112345678")
    """
    del value
    return False


def is_shamsi_date(value: str) -> bool:
    """Report whether *value* has the shape of a plausible Shamsi date.

    Planned. This placeholder always answers ``False``.

    Args:
        value: The candidate date string.

    Returns:
        ``False``, until the shape and range checks land.

    Example::

        is_shamsi_date("1403/06/14")
    """
    del value
    return False


def is_email_address(value: str) -> bool:
    """Report whether *value* has the shape of an e-mail address.

    Planned. This placeholder always answers ``False``.

    Args:
        value: The candidate address.

    Returns:
        ``False``, until the pattern lands.

    Example::

        is_email_address("ali@example.com")
    """
    del value
    return False


def classify_value(value: str, *, apply_persian_normalization: bool = False) -> SemanticType:
    """Classify a single value into one semantic type.

    Planned. This placeholder always answers ``"unknown"``.

    Args:
        value: The value to classify.
        apply_persian_normalization: Whether to normalize before matching.

    Returns:
        ``"unknown"``, until the detectors land.

    Example::

        classify_value("ali@example.com")
    """
    del value, apply_persian_normalization
    return "unknown"


def classify_column_name(column_name: str) -> SemanticType | None:
    """Suggest a semantic type from a column name alone.

    Planned. This placeholder always answers ``None``.

    Args:
        column_name: The column name to inspect.

    Returns:
        ``None``, until the hint table lands.

    Example::

        classify_column_name("code_melli")
    """
    del column_name
    return None


def classify_column(
    column_name: str,
    sample_values: Iterable[str | None],
    *,
    minimum_match_ratio: float = 0.8,
    max_sample_values: int = 1000,
    apply_persian_normalization: bool = False,
) -> ClassificationResult:
    """Classify one column from a bounded sample of its values.

    Planned. This placeholder always reports ``"unknown"`` with no evidence.

    Args:
        column_name: Name of the column being classified.
        sample_values: A bounded sample of the column's values.
        minimum_match_ratio: Fraction of usable values that must match.
        max_sample_values: Maximum number of values consumed from the sample.
        apply_persian_normalization: Whether to normalize before matching.

    Returns:
        A :class:`ClassificationResult` reporting ``"unknown"``.

    Example::

        classify_column("contact_email", ["a@b.com"])
    """
    del sample_values, minimum_match_ratio, max_sample_values, apply_persian_normalization
    return ClassificationResult(
        column_name=column_name,
        semantic_type="unknown",
        confidence=0.0,
        considered_count=0,
        matched_count=0,
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
