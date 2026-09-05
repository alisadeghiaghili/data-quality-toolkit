"""The version number, stated once and checked everywhere (`v0.5.0`).

`docs/HONESTY-GATE.md`: a version number is a claim like any other. It is
written in two places that cannot import each other — ``dqt/_version.py``,
which the running package reports, and ``pyproject.toml``, which the wheel
carries — and nothing made them agree.

A mismatch is quiet and expensive. `NEW-S` made every run record the DQT that
produced it so a trend chart can warn when a comparison spans versions; if the
runtime number and the packaged number disagree, that record names a release
nobody ever published, and the warning it exists for is wrong in exactly the
case it matters.

The roadmap's release ladder is checked here too. Its rungs are gates rather
than decorations, and the number DQT calls itself should not run ahead of
them.
"""

from __future__ import annotations

import pathlib
import re
import tomllib

import dqt

_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _packaged_version() -> str:
    """Return the version ``pyproject.toml`` declares.

    Returns:
        The version string.

    Example:
        assert _packaged_version().count(".") == 2
    """
    metadata = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(metadata["project"]["version"])


class TestTheTwoDeclarationsAgree:
    """One number, two files that cannot import each other."""

    def test_the_runtime_and_the_package_report_the_same_version(self) -> None:
        """``dqt.__version__`` is what a run records; pyproject is what pip sees.

        A run stamped with a version the wheel never carried names a release
        nobody published.
        """
        assert dqt.__version__ == _packaged_version()

    def test_it_is_a_three_part_version(self) -> None:
        """``docs/API-STABILITY.md`` §3 assigns meaning to each component.

        A two-part or suffixed version would leave one of those meanings with
        nowhere to live.
        """
        assert re.fullmatch(r"\d+\.\d+\.\d+", dqt.__version__), dqt.__version__


class TestTheChangelogRecordsThisRelease:
    """A version with no entry is a number, not a release."""

    def test_the_current_version_has_a_changelog_section(self) -> None:
        """Someone upgrading reads this to find out what changed.

        A tag with nothing written against it asks them to read the commit
        log instead, which is the thing a changelog exists to spare them.
        """
        changelog = (_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

        assert f"## [{dqt.__version__}]" in changelog

    def test_the_unreleased_section_still_exists(self) -> None:
        """Cutting a release must not remove the place the next one collects.

        Deleting it is the easy mistake, and the next change then lands with
        nowhere obvious to be recorded.
        """
        changelog = (_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

        assert "## [Unreleased]" in changelog
