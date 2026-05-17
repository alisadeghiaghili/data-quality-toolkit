"""Statistical utilities for multivariate analysis.

This module currently provides a Hotelling's T² test implementation
that was originally part of the `missingly` package but is now exposed
here as a general-purpose tool.
"""

from __future__ import annotations

from typing import Dict, Optional

import numpy as np
import pandas as pd
from scipy.stats import f as f_dist

__all__ = ["hotelling_test"]


def hotelling_test(
    frame: pd.DataFrame,
    missing_values: Optional[list] = None,
) -> Dict:
    """Hotelling's T² test: complete cases vs. incomplete cases.

    This is implemented as a general multivariate test on numeric
    columns only. Optionally, sentinel *missing_values* are replaced
    with ``NaN`` before processing.
    """
    if missing_values is not None:
        frame = frame.replace(missing_values, np.nan)

    num_df = frame.select_dtypes(include=[np.number])
    if num_df.shape[1] < 2:
        raise ValueError(
            "hotelling_test requires at least 2 numeric columns; "
            f"got {num_df.shape[1]}."
        )

    complete_mask = num_df.notna().all(axis=1)
    X_complete = num_df[complete_mask].to_numpy(dtype=float)
    n1, d = X_complete.shape
    n2 = int((~complete_mask).sum())

    _sufficient = n2 >= (d + 2) and n1 >= 2

    if not _sufficient:
        return {
            "t2": None,
            "f_statistic": None,
            "df1": d,
            "df2": None,
            "p_value": None,
            "n_complete": int(n1),
            "n_incomplete": n2,
            "sufficient_data": False,
        }

    complete_cols = np.where(num_df[~complete_mask].notna().all(axis=0))[0]
    if len(complete_cols) < 2:
        return {
            "t2": None,
            "f_statistic": None,
            "df1": d,
            "df2": None,
            "p_value": None,
            "n_complete": int(n1),
            "n_incomplete": n2,
            "sufficient_data": False,
        }

    X1 = X_complete[:, complete_cols]
    X2 = num_df[~complete_mask].iloc[:, complete_cols].to_numpy(dtype=float)
    d_eff = len(complete_cols)
    n1_eff, n2_eff = len(X1), len(X2)

    mean1 = X1.mean(axis=0)
    mean2 = X2.mean(axis=0)
    mean_diff = mean1 - mean2

    S1 = np.cov(X1, rowvar=False) if n1_eff > 1 else np.eye(d_eff)
    S2 = np.cov(X2, rowvar=False) if n2_eff > 1 else np.eye(d_eff)
    S_pool = ((n1_eff - 1) * S1 + (n2_eff - 1) * S2) / (n1_eff + n2_eff - 2)
    S_pool += np.eye(d_eff) * 1e-8

    S_inv = np.linalg.inv(S_pool)
    T2 = (n1_eff * n2_eff / (n1_eff + n2_eff)) * float(
        mean_diff @ S_inv @ mean_diff
    )

    df1 = d_eff
    df2 = n1_eff + n2_eff - d_eff - 1
    factor = (n1_eff + n2_eff - d_eff - 1) / ((n1_eff + n2_eff - 2) * d_eff)
    F = T2 * factor
    p_value = float(1 - f_dist.cdf(F, df1, df2)) if df2 > 0 else None

    return {
        "t2": float(T2),
        "f_statistic": float(F),
        "df1": df1,
        "df2": df2,
        "p_value": p_value,
        "n_complete": int(n1),
        "n_incomplete": n2,
        "sufficient_data": True,
    }
