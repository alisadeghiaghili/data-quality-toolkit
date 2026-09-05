"""The one place DQT's version number is written.

``dqt/__init__.py`` re-exports it and the pipeline stamps it onto every
:class:`~dqt.common.models.PipelineResult`. It lives in its own module so the
pipeline can import it without importing the package that imports the
pipeline.

Example:
    from dqt._version import __version__
"""

from __future__ import annotations

__version__ = "1.0.0"

__all__ = ["__version__"]
