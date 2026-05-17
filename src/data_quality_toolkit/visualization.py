"""Visualization utilities for general data quality and profiling.

This module exposes generic plotting primitives that can be reused from
higher-level libraries (such as `missingly`) without depending on any
missing-data-specific logic.
"""

from __future__ import annotations

from typing import Optional

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

__all__ = [
    "correlation_heatmap",
    "parallel_coordinates",
]


def correlation_heatmap(
    corr: pd.DataFrame,
    ax=None,
    *,
    mask_insignificant: bool = False,
    significance: float = 0.05,
    cmap: str = "RdBu",
    annot: bool = True,
    fmt: str = ".2f",
    vmin: float = -1.0,
    vmax: float = 1.0,
    center: float = 0.0,
    linewidths: float = 0.5,
    n_obs: Optional[int] = None,
    **kwargs,
) -> plt.Axes:
    """Generic correlation heatmap for a precomputed correlation matrix.

    Parameters
    ----------
    corr : pd.DataFrame
        Square correlation matrix.
    ax : matplotlib.axes.Axes, optional
        Axes to draw on. Created automatically if omitted.
    mask_insignificant : bool, optional
        If True, mask cells whose p-value exceeds *significance*.
    significance : float, optional
        P-value cutoff used when *mask_insignificant* is True.
    n_obs : int, optional
        Number of observations used to estimate correlations. Required
        when *mask_insignificant* is True.
    """
    if ax is None:
        n = corr.shape[1]
        fig, ax = plt.subplots(figsize=(max(6, n), max(5, n - 1)))

    values = corr.values
    nan_mask = np.isnan(values)
    sig_mask = np.zeros_like(nan_mask)

    if mask_insignificant:
        if n_obs is None:
            raise ValueError("n_obs must be provided when mask_insignificant=True")
        from scipy import stats
        for i in range(corr.shape[0]):
            for j in range(corr.shape[1]):
                if i == j or nan_mask[i, j]:
                    continue
                r = values[i, j]
                if abs(r) < 1.0:
                    t_stat = r * np.sqrt(n_obs - 2) / np.sqrt(1 - r**2)
                    p = 2 * stats.t.sf(abs(t_stat), df=n_obs - 2)
                    if p > significance:
                        sig_mask[i, j] = True

    final_mask = nan_mask | sig_mask

    sns.heatmap(
        corr,
        mask=final_mask,
        ax=ax,
        cmap=cmap,
        annot=annot,
        fmt=fmt,
        vmin=vmin,
        vmax=vmax,
        center=center,
        linewidths=linewidths,
        **kwargs,
    )
    return ax


def parallel_coordinates(
    df: pd.DataFrame,
    class_column: str,
    ax=None,
    **kwargs,
) -> plt.Axes:
    """Generic parallel coordinates plot for a labelled DataFrame.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame containing numeric features and a class column.
    class_column : str
        Column name used to group lines.
    ax : matplotlib.axes.Axes, optional
        Axes to draw on. Created automatically if omitted.
    """
    if ax is None:
        fig, ax = plt.subplots(figsize=(12, 8))
    pd.plotting.parallel_coordinates(df, class_column, ax=ax, **kwargs)
    return ax
