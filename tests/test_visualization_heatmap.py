"""Tests for data_quality_toolkit.visualization.correlation_heatmap.

Strategy
--------
* Verify the stable public signature: positional ``corr``, keyword-only
  ``mask_insignificant``, ``significance``, ``cmap``, ``annot``, ``fmt``,
  ``vmin``, ``vmax``, ``center``, ``linewidths``, ``n_obs``.
* Verify no warnings or exceptions are raised on a normal correlation
  matrix.
* Verify ``mask_insignificant=True`` path without raising.
* Verify ``ax`` is returned (matplotlib Axes).
"""

from __future__ import annotations

import warnings

import matplotlib
matplotlib.use("Agg")  # non-interactive backend — safe in CI
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pytest

from data_quality_toolkit.visualization import correlation_heatmap


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def small_corr() -> pd.DataFrame:
    """3×3 precomputed correlation matrix with no NaN entries."""
    data = np.array([
        [1.00,  0.80, -0.30],
        [0.80,  1.00, -0.10],
        [-0.30, -0.10,  1.00],
    ])
    cols = ["a", "b", "c"]
    return pd.DataFrame(data, index=cols, columns=cols)


@pytest.fixture
def corr_with_nan() -> pd.DataFrame:
    """3×3 matrix with one NaN cell (single-valued column edge-case)."""
    data = np.array([
        [1.00,  0.70,  np.nan],
        [0.70,  1.00,  np.nan],
        [np.nan, np.nan, np.nan],
    ])
    cols = ["x", "y", "z"]
    return pd.DataFrame(data, index=cols, columns=cols)


@pytest.fixture(autouse=True)
def close_figures():
    """Close all matplotlib figures after each test to avoid resource leaks."""
    yield
    plt.close("all")


# ---------------------------------------------------------------------------
# Signature / return type
# ---------------------------------------------------------------------------

class TestSignatureAndReturnType:
    """Public signature is stable and return type is always Axes."""

    def test_returns_axes(self, small_corr):
        import matplotlib.axes
        ax = correlation_heatmap(small_corr)
        assert isinstance(ax, matplotlib.axes.Axes)

    def test_accepts_external_axes(self, small_corr):
        """When ax is provided, the same object should be returned."""
        fig, ax_in = plt.subplots()
        ax_out = correlation_heatmap(small_corr, ax=ax_in)
        assert ax_out is ax_in

    def test_creates_axes_when_none(self, small_corr):
        """ax=None (default) should auto-create an Axes."""
        import matplotlib.axes
        ax = correlation_heatmap(small_corr, ax=None)
        assert isinstance(ax, matplotlib.axes.Axes)

    def test_all_keyword_args_accepted(self, small_corr):
        """All documented keyword-only args must be accepted without error."""
        ax = correlation_heatmap(
            small_corr,
            mask_insignificant=False,
            significance=0.05,
            cmap="Blues",
            annot=True,
            fmt=".2f",
            vmin=-1.0,
            vmax=1.0,
            center=0.0,
            linewidths=0.5,
            n_obs=None,
        )
        import matplotlib.axes
        assert isinstance(ax, matplotlib.axes.Axes)


# ---------------------------------------------------------------------------
# No warnings / exceptions on normal input
# ---------------------------------------------------------------------------

class TestNoWarningsOnNormalInput:
    """Plotting a clean correlation matrix must not emit any warning."""

    def test_no_warnings_default_params(self, small_corr):
        with warnings.catch_warnings():
            warnings.simplefilter("error")  # turn any warning into an error
            correlation_heatmap(small_corr)

    def test_no_warnings_annot_false(self, small_corr):
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            correlation_heatmap(small_corr, annot=False)

    def test_no_warnings_custom_cmap(self, small_corr):
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            correlation_heatmap(small_corr, cmap="coolwarm")


# ---------------------------------------------------------------------------
# NaN handling
# ---------------------------------------------------------------------------

class TestNanHandling:
    """Matrices with NaN entries should render without raising."""

    def test_corr_with_nan_does_not_raise(self, corr_with_nan):
        # Should not raise even though one column is all-NaN
        correlation_heatmap(corr_with_nan)

    def test_all_nan_matrix_does_not_raise(self):
        """Degenerate: fully NaN correlation matrix."""
        df = pd.DataFrame(
            np.full((3, 3), np.nan),
            columns=["p", "q", "r"],
            index=["p", "q", "r"],
        )
        correlation_heatmap(df)


# ---------------------------------------------------------------------------
# mask_insignificant path
# ---------------------------------------------------------------------------

class TestMaskInsignificant:
    """mask_insignificant=True should work without raising."""

    def test_mask_insignificant_requires_n_obs(self, small_corr):
        """Omitting n_obs when mask_insignificant=True must raise ValueError."""
        with pytest.raises(ValueError, match="n_obs"):
            correlation_heatmap(small_corr, mask_insignificant=True)

    def test_mask_insignificant_with_n_obs(self, small_corr):
        """Providing n_obs must succeed without error or warning."""
        ax = correlation_heatmap(
            small_corr,
            mask_insignificant=True,
            n_obs=100,
        )
        import matplotlib.axes
        assert isinstance(ax, matplotlib.axes.Axes)

    def test_mask_insignificant_high_significance(self, small_corr):
        """significance=1.0 should mask everything except the diagonal."""
        ax = correlation_heatmap(
            small_corr,
            mask_insignificant=True,
            n_obs=10,
            significance=1.0,
        )
        import matplotlib.axes
        assert isinstance(ax, matplotlib.axes.Axes)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Boundary conditions."""

    def test_1x1_matrix(self):
        """Single-cell identity matrix."""
        df = pd.DataFrame([[1.0]], index=["a"], columns=["a"])
        correlation_heatmap(df)

    def test_large_matrix(self):
        """10×10 matrix should not raise."""
        rng = np.random.default_rng(0)
        raw = rng.standard_normal((50, 10))
        cols = list("abcdefghij")
        corr = pd.DataFrame(raw, columns=cols).corr()
        correlation_heatmap(corr)

    def test_integer_valued_corr(self):
        """Integer dtype correlation matrix (edge case for fmt handling)."""
        data = np.array([[1, 0], [0, 1]])
        df = pd.DataFrame(data.astype(float), columns=["m", "n"], index=["m", "n"])
        correlation_heatmap(df)
