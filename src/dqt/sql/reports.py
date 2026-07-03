"""
Reporting stage for DQT SQL pipelines.

This module is currently a stub. Later versions will generate HTML/PDF
artifacts and bilingual DBA-facing reports.
"""

from __future__ import annotations

from dqt.common.models import PipelineResult


def generate_report(result: PipelineResult) -> dict[str, str]:
    """Generate a minimal in-memory report descriptor.

    Args:
        result: Final pipeline result.

    Returns:
        A small dictionary describing the current report status.

    Example:
        report = generate_report(result)
    """
    return {
        "status": result.status,
        "run_id": result.run_id,
        "message": "Report generation is not implemented yet.",
    }
