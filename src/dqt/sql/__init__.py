"""
SQL pipeline package for DQT.

This package contains the SQL-first data-quality pipeline modules used to
discover schema objects, profile relational data, run diagnostics, compute
metrics, and orchestrate end-to-end DQT runs.

The package is intentionally focused on data quality only. It does not include
service/performance monitoring, masking/compliance features, or MDM workflows.
"""

from dqt.sql.pipeline import DQTPipeline

__all__ = ["DQTPipeline"]
