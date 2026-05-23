"""Tests for data_quality_toolkit.visualization.correlation_heatmap.

Verifies that:
* The function exists and is callable with a stable signature.
* It renders without errors or warnings on a small correlation matrix.
* Optional parameters (mask_insignificant, n_obs, cmap, annot) work correctly.
* Edge cases (1-column matrix, all-NaN diagonal, perfect correlation) do not raise.
"""

from __future__ import annotations

import warnings
import numpy as np
import pandas as pd
import pytest
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from data_quality_toolkit.visualization import correlation_heatmap


@pytest.fixture(autouse=True)
def close_plots():
    yield
    plt.close("all")


@pytest.fixture
def small_corr() -> pd.DataFrame:
    """3x3 correlation matrix with no NaNs."""
    data = np.array([
        [1.00,  0.80, -0.30],
        [0.80,  1.00,  0.10],
        [-0.30, 0.10,  1.00],
    ])
    cols = ["a", "b", "c"]
    return pd.DataFrame(data, index=cols, columns=cols)


@pytest.fixture
def corr_with_nan() -> pd.DataFrame:
    """3x3 correlation matrix where off-diagonals for column 'c' are NaN."""
    data = np.array([
        [1.00,  0.75,  np.nan],
        [0.75,  1.00,  np.nan],
        [np.nan, np.nan, 1.00],
    ])
    cols = ["x", "y", "z"]
    return pd.DataFrame(data, index=cols, columns=cols)


# ---------------------------------------------------------------------------
# Existence and callable
# ---------------------------------------------------------------------------

def test_correlation_heatmap_is_callable():
    assert callable(correlation_heatmap)


def test_correlation_heatmap_in_all():
    from data_quality_toolkit import visualization
    assert "correlation_heatmap" in visualization.__all__


# ---------------------------------------------------------------------------
# Basic rendering — no errors, no warnings
# ---------------------------------------------------------------------------

def test_basic_no_error(small_corr):
    """Renders without raising any exception."""
    ax = correlation_heatmap(small_corr)
    assert ax is not None


def test_basic_no_warnings(small_corr):
    """Renders without emitting any Python warnings."""
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        correlation_heatmap(small_corr)


def test_returns_axes(small_corr):
    import matplotlib.axes
    ax = correlation_heatmap(small_corr)
    assert isinstance(ax, matplotlib.axes.Axes)


# ---------------------------------------------------------------------------
# Signature stability — all documented parameters accepted
# ---------------------------------------------------------------------------

def test_accepts_ax_parameter(small_corr):
    fig, ax = plt.subplots(figsize=(4, 4))
    result = correlation_heatmap(small_corr, ax=ax)
    assert result is ax


def test_accepts_cmap(small_corr):
    ax = correlation_heatmap(small_corr, cmap="coolwarm")
    assert ax is not None


def test_accepts_annot_false(small_corr):
    ax = correlation_heatmap(small_corr, annot=False)
    assert ax is not None


def test_accepts_vmin_vmax(small_corr):
    ax = correlation_heatmap(small_corr, vmin=-1.0, vmax=1.0)
    assert ax is not None


def test_accepts_fmt(small_corr):
    ax = correlation_heatmap(small_corr, fmt=".3f")
    assert ax is not None


def test_accepts_linewidths(small_corr):
    ax = correlation_heatmap(small_corr, linewidths=1.0)
    assert ax is not None


# ---------------------------------------------------------------------------
# mask_insignificant
# ---------------------------------------------------------------------------

def test_mask_insignificant_requires_n_obs(small_corr):
    """mask_insignificant=True without n_obs must raise ValueError."""
    with pytest.raises(ValueError, match="n_obs"):
        correlation_heatmap(small_corr, mask_insignificant=True)


def test_mask_insignificant_with_n_obs(small_corr):
    """mask_insignificant=True with n_obs must not raise."""
    ax = correlation_heatmap(small_corr, mask_insignificant=True, n_obs=30)
    assert ax is not None


# ---------------------------------------------------------------------------
# NaN handling
# ---------------------------------------------------------------------------

def test_handles_nan_in_matrix(corr_with_nan):
    """Correlation matrix with NaN cells renders without error."""
    ax = correlation_heatmap(corr_with_nan)
    assert ax is not None


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_single_column_matrix():
    """1x1 identity correlation matrix does not raise."""
    corr = pd.DataFrame([[1.0]], index=["a"], columns=["a"])
    ax = correlation_heatmap(corr)
    assert ax is not None


def test_perfect_correlation_no_masking():
    """Perfect correlation (r=1) with mask_insignificant should not raise."""
    data = np.array([[1.0, 1.0], [1.0, 1.0]])
    corr = pd.DataFrame(data, index=["p", "q"], columns=["p", "q"])
    ax = correlation_heatmap(corr, mask_insignificant=True, n_obs=50)
    assert ax is not None


def test_large_matrix_no_error():
    """10x10 correlation matrix renders without error."""
    rng = np.random.default_rng(0)
    raw = rng.standard_normal((100, 10))
    df = pd.DataFrame(raw, columns=list("abcdefghij"))
    corr = df.corr()
    ax = correlation_heatmap(corr)
    assert ax is not None
