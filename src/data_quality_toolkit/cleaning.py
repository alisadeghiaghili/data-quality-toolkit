"""Cleaning utilities for tabular data.

This module provides generic data cleaning helpers such as:

- clean_names: normalize column names to consistent identifiers
- remove_empty: drop empty or mostly-empty rows/columns
- coalesce_columns: fill missing values from donor columns (SQL COALESCE)
"""

from __future__ import annotations

import re
import unicodedata
from typing import Dict, List, Optional, Union

import numpy as np
import pandas as pd

__all__ = [
    "clean_names",
    "remove_empty",
    "coalesce_columns",
]


def clean_names(
    df: pd.DataFrame,
    *,
    case: str = "lower",
    sep: str = "_",
    strip_accents: bool = False,
) -> pd.DataFrame:
    """Normalise DataFrame column names to clean, consistent identifiers.

    Inspired by ``janitor::clean_names`` from R.

    The transformation pipeline applied to each column name:

    1. Convert to string (handles non-string column labels).
    2. Optionally decompose and strip Unicode accent marks
       (``strip_accents=True``).
    3. Apply case transformation (``lower``, ``upper``, or ``snake``).
    4. Replace any character that is *not* a Unicode word character
       ("\\w", i.e. letters, digits, underscore — including Persian,
       Arabic, CJK, etc.) with the separator character.
    5. Collapse consecutive separators into one.
    6. Strip leading/trailing separators.
    7. If the name starts with a digit, prepend the separator so the
       result is a valid Python identifier.
    8. Resolve duplicate names by appending ``_2``, ``_3``, … suffixes.
    """
    valid_cases = {"lower", "upper", "snake"}
    if case not in valid_cases:
        raise ValueError(
            f"case must be one of {valid_cases!r}; got {case!r}"
        )
    if not sep or (re.fullmatch(r"[A-Za-z0-9]+", sep) is not None):
        raise ValueError(
            f"sep must be a non-empty, non-alphanumeric string "
            f"(e.g. '_', '-', '.'); got {sep!r}"
        )

    def _clean_one(name: str) -> str:
        """Apply the full normalisation pipeline to a single name string."""
        s = str(name)
        if strip_accents:
            s = unicodedata.normalize("NFD", s)
            s = "".join(c for c in s if unicodedata.category(c) != "Mn")
        if case in ("lower", "snake"):
            s = s.lower()
        elif case == "upper":
            s = s.upper()
        s = re.sub(r"\W+", sep, s, flags=re.UNICODE)
        escaped = re.escape(sep)
        s = re.sub(escaped + "+", sep, s)
        s = s.strip(sep)
        if s and s[0].isdigit():
            s = sep + s
        return s or sep

    raw_names = [_clean_one(col) for col in df.columns]

    seen: Dict[str, int] = {}
    clean: List[str] = []
    for name in raw_names:
        if name not in seen:
            seen[name] = 1
            clean.append(name)
        else:
            seen[name] += 1
            clean.append(f"{name}{sep}{seen[name]}")

    return df.rename(columns=dict(zip(df.columns, clean)))


def remove_empty(
    df: pd.DataFrame,
    *,
    axis: Union[str, int] = "both",
    missing_values: Optional[List] = None,
    thresh_row: Optional[float] = None,
    thresh_col: Optional[float] = None,
) -> pd.DataFrame:
    """Remove rows and/or columns that are entirely (or mostly) missing.

    Inspired by ``janitor::remove_empty`` from R.
    """
    valid_axes = {"rows", "cols", "both", 0, 1}
    if axis not in valid_axes:
        raise ValueError(
            f"axis must be one of {valid_axes!r}; got {axis!r}"
        )
    for name, thresh in (("thresh_row", thresh_row), ("thresh_col", thresh_col)):
        if thresh is not None and not (0.0 < thresh <= 1.0):
            raise ValueError(
                f"{name} must be in the range (0, 1]; got {thresh!r}. "
                f"Pass None to drop only fully-empty rows/columns."
            )

    def _is_missing(frame: pd.DataFrame) -> pd.DataFrame:
        if missing_values is None:
            return frame.isnull()
        return frame.isnull() | frame.isin(missing_values)

    result = df.copy()
    n_rows, n_cols = result.shape

    drop_rows = axis in ("rows", "both", 0)
    drop_cols = axis in ("cols", "both", 1)

    if drop_cols and n_cols > 0:
        miss_frac_col = _is_missing(result).mean(axis=0)
        if thresh_col is None:
            cols_to_drop = miss_frac_col[miss_frac_col == 1.0].index.tolist()
        else:
            cols_to_drop = miss_frac_col[miss_frac_col > thresh_col].index.tolist()
        result = result.drop(columns=cols_to_drop)

    if drop_rows and result.shape[0] > 0:
        miss_frac_row = _is_missing(result).mean(axis=1)
        if thresh_row is None:
            rows_to_drop = miss_frac_row[miss_frac_row == 1.0].index.tolist()
        else:
            rows_to_drop = miss_frac_row[miss_frac_row > thresh_row].index.tolist()
        result = result.drop(index=rows_to_drop)

    return result


def coalesce_columns(
    df: pd.DataFrame,
    target: str,
    *donors: str,
    remove_donors: bool = False,
) -> pd.DataFrame:
    """Fill missing values in a column using donor columns (SQL COALESCE).
    """
    if not donors:
        raise ValueError("At least one donor column must be provided.")
    missing_cols = [c for c in (target, *donors) if c not in df.columns]
    if missing_cols:
        raise KeyError(f"Columns not found in DataFrame: {missing_cols}")

    result = df.copy()
    filled = result[target].copy()
    for donor in donors:
        filled = filled.combine_first(result[donor])
    result[target] = filled

    if remove_donors:
        result = result.drop(columns=list(donors))

    return result
