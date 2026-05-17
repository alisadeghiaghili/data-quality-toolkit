"""Performance utilities for large-dataset workflows.

This module provides:

- memory_usage_mb: per-column and total memory usage summary
- optimize_dtypes: dtype downcasting and categorical conversion
- chunk_apply: row-chunked processing for large DataFrames
"""

from __future__ import annotations

from typing import Callable, Optional

import numpy as np
import pandas as pd

__all__ = [
    "memory_usage_mb",
    "optimize_dtypes",
    "chunk_apply",
]


def _is_string_like_dtype(dtype) -> bool:
    """Return True for object, str (StringDtype), and ArrowDtype string columns."""
    if dtype == object:
        return True
    dtype_str = str(dtype).lower()
    if dtype_str in ("string", "str"):
        return True
    if "string" in dtype_str and "arrow" in dtype_str:
        return True
    return False


def memory_usage_mb(
    df: pd.DataFrame,
    deep: bool = True,
) -> pd.DataFrame:
    """Return per-column and total memory usage in megabytes."""
    usage = df.memory_usage(deep=deep, index=False)
    dtypes = df.dtypes

    rows = []
    for col in df.columns:
        rows.append({
            "column": col,
            "dtype": str(dtypes[col]),
            "memory_mb": usage[col] / (1024 ** 2),
        })

    result = pd.DataFrame(rows).set_index("column")
    total_mb = result["memory_mb"].sum()
    total_row = pd.DataFrame(
        [{"dtype": "—", "memory_mb": total_mb}],
        index=pd.Index(["__total__"], name="column"),
    )
    return pd.concat([result, total_row])


def optimize_dtypes(
    df: pd.DataFrame,
    categorical_threshold: Optional[float] = 0.50,
    downcast_int: bool = True,
    downcast_float: bool = True,
) -> pd.DataFrame:
    """Downcast numeric dtypes and optionally convert low-cardinality string columns."""
    result = df.copy()

    for col in result.columns:
        col_dtype = result[col].dtype

        if downcast_int and pd.api.types.is_integer_dtype(col_dtype):
            col_min = result[col].min()
            col_max = result[col].max()
            for target in (np.int8, np.int16, np.int32, np.int64):
                info = np.iinfo(target)
                if info.min <= col_min and col_max <= info.max:
                    result[col] = result[col].astype(target)
                    break

        elif downcast_float and col_dtype == np.float64:
            as_f32 = result[col].astype(np.float32)
            mask = result[col].notna()
            if np.allclose(
                result.loc[mask, col].to_numpy(),
                as_f32[mask].astype(np.float64).to_numpy(),
                equal_nan=True,
            ):
                result[col] = as_f32

        elif (
            categorical_threshold is not None
            and _is_string_like_dtype(col_dtype)
            and len(result) > 0
        ):
            cardinality = result[col].nunique(dropna=True) / len(result)
            if cardinality < categorical_threshold:
                result[col] = result[col].astype("category")

    return result


def chunk_apply(
    df: pd.DataFrame,
    func: Callable[[pd.DataFrame], pd.DataFrame],
    chunk_size: int = 10_000,
    reset_index: bool = True,
) -> pd.DataFrame:
    """Apply a function to a DataFrame in fixed-size row chunks."""
    if chunk_size < 1:
        raise ValueError(f"chunk_size must be >= 1; got {chunk_size!r}")

    n = len(df)
    if n == 0:
        return func(df)

    chunks = []
    for start in range(0, n, chunk_size):
        chunk = df.iloc[start: start + chunk_size]
        chunks.append(func(chunk))

    result = pd.concat(chunks, ignore_index=reset_index)
    return result
