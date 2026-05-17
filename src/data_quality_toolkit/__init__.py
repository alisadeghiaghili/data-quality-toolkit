"""Data Quality Toolkit.

General-purpose data quality, cleaning, profiling, and performance utilities
for pandas DataFrames.
"""

from __future__ import annotations

from .cleaning import clean_names, remove_empty, coalesce_columns
from .performance import memory_usage_mb, optimize_dtypes, chunk_apply

__all__ = [
    "clean_names",
    "remove_empty",
    "coalesce_columns",
    "memory_usage_mb",
    "optimize_dtypes",
    "chunk_apply",
]
