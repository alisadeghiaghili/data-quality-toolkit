"""Which Python versions DQT claims to support (`PY-314`).

A trove classifier is a claim, and `docs/HONESTY-GATE.md` makes no exception
for packaging metadata: ``Programming Language :: Python :: 3.14`` tells
someone on 3.14 that DQT works there. The only thing that can back it is CI
running the suite on 3.14.

So the two are checked against each other here. Neither is allowed to move
without the other: a classifier without a matrix entry is an unbacked claim,
and a matrix entry without a classifier is work being done that nobody is
told about.
"""

from __future__ import annotations

import pathlib
import re
import tomllib

_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _classified_versions() -> set[str]:
    """Return the Python versions ``pyproject.toml`` claims.

    Returns:
        Versions as ``"3.11"``-style strings.

    Example:
        assert "3.11" in _classified_versions()
    """
    metadata = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    classifiers = metadata["project"]["classifiers"]
    return {
        classifier.rsplit(" :: ", 1)[-1]
        for classifier in classifiers
        if classifier.startswith("Programming Language :: Python :: 3.")
    }


def _matrix_versions() -> set[str]:
    """Return the Python versions the CI matrices actually run.

    Returns:
        Every version named in a ``python-version: [...]`` matrix.

    Example:
        assert "3.11" in _matrix_versions()
    """
    workflow = (_ROOT / ".github" / "workflows" / "ci.yaml").read_text(encoding="utf-8")
    versions: set[str] = set()
    for matrix in re.findall(r"python-version:\s*\[([^\]]+)\]", workflow):
        versions.update(re.findall(r'"([^"]+)"', matrix))
    return versions


class TestTheClaimAndTheEvidenceAgree:
    """A supported version is one the suite is proven to pass on."""

    def test_every_classified_version_is_tested(self) -> None:
        """A classifier with no matrix entry is an unbacked claim.

        It is also the most expensive kind: someone installs DQT on that
        version because the metadata said so, and finds out for themselves.
        """
        missing = _classified_versions() - _matrix_versions()

        assert missing == set(), f"classified but never run in CI: {sorted(missing)}"

    def test_every_tested_version_is_classified(self) -> None:
        """The other direction, so effort is not spent invisibly.

        A version CI runs and the metadata omits is work nobody benefits
        from -- a user filtering by classifier never sees it.
        """
        missing = _matrix_versions() - _classified_versions()

        assert missing == set(), f"run in CI but not classified: {sorted(missing)}"

    def test_the_floor_is_not_above_anything_claimed(self) -> None:
        """``requires-python`` must not exclude a version being claimed.

        pip reads the floor, not the classifiers, so a mismatch here refuses
        an install on a version the metadata advertises.
        """
        metadata = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        floor = metadata["project"]["requires-python"].lstrip(">=")
        floor_parts = tuple(int(part) for part in floor.split("."))

        for version in _classified_versions():
            assert tuple(int(part) for part in version.split(".")) >= floor_parts, version


class TestPython314IsSupported:
    """The owner asked for 3.14 on 2026-09-05.

    Named rather than left implicit in the sets above, so the requirement is
    visible in the suite and a later trim of the matrix has to delete a test
    that says who asked for it and when.
    """

    def test_it_is_classified(self) -> None:
        """What a user reads on PyPI."""
        assert "3.14" in _classified_versions()

    def test_it_is_run_in_ci(self) -> None:
        """What makes the classifier true."""
        assert "3.14" in _matrix_versions()
