"""Data Quality Toolkit.

General-purpose data quality, cleaning, profiling, and performance utilities
for pandas DataFrames.
"""

from __future__ import annotations

from .cleaning import clean_names, remove_empty, coalesce_columns
from .performance import memory_usage_mb, optimize_dtypes, chunk_apply
from .statistics import hotelling_test
from .visualization import correlation_heatmap, parallel_coordinates

__all__ = [
    # cleaning
    "clean_names",
    "remove_empty",
    "coalesce_columns",
    # performance
    "memory_usage_mb",
    "optimize_dtypes",
    "chunk_apply",
    # statistics
    "hotelling_test",
    # visualization
    "correlation_heatmap",
    "parallel_coordinates",
]
