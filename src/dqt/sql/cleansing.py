"""
Cleansing stage for DQT SQL pipelines.

This module is intentionally stubbed in the current phase. DQT will later
provide reversible and auditable cleansing primitives, but that work does not
belong in the initial pipeline shell.
"""

from __future__ import annotations

from dqt.common.models import PipelineResult


def cleanse(result: PipelineResult) -> PipelineResult:
    """Return the input result unchanged.

    Args:
        result: Pipeline result produced by earlier stages.

    Returns:
        The same pipeline result instance.

    Example:
        result = cleanse(result)
    """
    return result
