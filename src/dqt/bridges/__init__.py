"""Optional bridges to sibling analysers (B1-B3).

DQT is fully usable without anything in this package. Nothing here is
imported by DQT core, and importing this module pulls in no sibling package
either -- the adapters do that lazily, inside the call that needs them.

Example:
    from dqt.bridges import MissingnessReport
"""

from __future__ import annotations

from dqt.bridges.base import ColumnMissingness, MissingnessBridge, MissingnessReport

__all__ = ["ColumnMissingness", "MissingnessBridge", "MissingnessReport"]
