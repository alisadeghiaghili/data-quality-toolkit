"""The documents a newcomer reads first must describe this code (`DOC-05`).

`docs/HONESTY-GATE.md` makes a doc claim answerable to a test. Existing gates
cover the claims that live *inside* the package -- `tests/unit/test_version.py`
holds ``dqt/_version.py`` and ``pyproject.toml`` together,
`tests/unit/test_supported_pythons.py` holds the trove classifiers and the CI
matrix together, `tests/unit/test_documented_surface.py` holds the docstrings
to the exports.

Nothing held the **entry points**: `README.md` and `docs/00-START-HERE.md`.
They are the first thing anyone reads and the last thing anyone updates, and
by `1.1.0` both had drifted -- the README announced `1.0.0`, advertised
Python 3.11 and 3.12 while CI tested 3.14, showed a 90% coverage gate against
a configured 95, and denied a feature the pipeline had gained; START-HERE
still called the project "0.1.0 (pre-alpha, not released)" against six
published tags.

Every one of those was true when written. That is the point: prose does not
fail when the code moves under it, so nothing announces the drift. These
tests make the entry documents fail like anything else.

**The import check is the odd one out and earns its place.** It asserts that
the ``dqt`` under test is the one in this working tree. On 2026-09-06 a stale
editable install pointed the interpreter at an unrelated copy of DQT
elsewhere on disk; the suite stopped collecting with 49 ``NameError``s from a
module this repository does not contain. That failure was loud but said
nothing about its cause, and the far worse version is silent: a copy close
enough to import cleanly would let the whole suite pass while testing code
nobody was editing. A green suite must mean *this* source is green.
"""

from __future__ import annotations

import pathlib
import re
import tomllib

import dqt

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_README = _ROOT / "README.md"
_START_HERE = _ROOT / "docs" / "00-START-HERE.md"


def _pyproject() -> dict[str, object]:
    """Return the parsed ``pyproject.toml``.

    Returns:
        The parsed document.

    Example:
        metadata = _pyproject()
    """
    return tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def _classified_pythons() -> set[str]:
    """Return the Python versions the trove classifiers claim.

    Returns:
        Versions such as ``{"3.11", "3.12", "3.14"}``.

    Example:
        assert "3.11" in _classified_pythons()
    """
    metadata = _pyproject()
    classifiers = metadata["project"]["classifiers"]  # type: ignore[index]
    return {
        classifier.rsplit(" :: ", 1)[-1]
        for classifier in classifiers  # type: ignore[union-attr]
        if classifier.startswith("Programming Language :: Python :: 3.")
    }


class TestTheSuiteIsTestingThisCheckout:
    """A green suite must mean *this* source tree is green."""

    def test_the_imported_package_comes_from_this_repository(self) -> None:
        """Otherwise every other assertion here describes someone else's code.

        A stale editable install, a leftover entry on ``sys.path``, a wheel
        installed alongside the checkout -- each silently substitutes a
        different DQT, and the only signal is that failures stop making
        sense.
        """
        imported = pathlib.Path(dqt.__file__).resolve()
        expected = (_ROOT / "src" / "dqt").resolve()

        assert imported.parent == expected, (
            f"`import dqt` resolved to {imported}, not to {expected}. "
            "The suite would be testing a different copy of DQT. "
            'Reinstall from this checkout: pip install -e ".[dev,ui]"'
        )


class TestTheReadmeDescribesThisRelease:
    """The README is the first document, and drifts the most quietly."""

    def test_it_announces_the_current_version(self) -> None:
        """A README naming an older release understates what is installed.

        Someone reading it looks for a feature the changelog promised, does
        not find it described, and concludes their install is wrong.
        """
        readme = _README.read_text(encoding="utf-8")

        assert f"`{dqt.__version__}`" in readme, (
            f"README does not mention version {dqt.__version__}."
        )

    def test_the_python_badge_lists_every_supported_version(self) -> None:
        """A badge is a claim about what will work when they install it.

        Omitting a version that CI proves works costs an adopter who filters
        on it; listing one that CI never runs is the unbacked direction, and
        `tests/unit/test_supported_pythons.py` already guards the classifiers
        against the matrix -- so agreeing with the classifiers is enough
        here.
        """
        readme = _README.read_text(encoding="utf-8")
        badge = re.search(r"badge/python-([^-]+)-blue", readme)

        assert badge is not None, "README has no Python badge to check."
        advertised = set(re.findall(r"3\.\d+", badge.group(1)))

        assert advertised == _classified_pythons(), (
            f"README badge advertises {sorted(advertised)}, "
            f"classifiers claim {sorted(_classified_pythons())}."
        )

    def test_the_coverage_badge_matches_the_enforced_floor(self) -> None:
        """`NEW-W` was two coverage numbers disagreeing; this is a third.

        The badge is the number a reader trusts without opening
        ``pyproject.toml``, which makes it the one most worth holding to the
        gate that actually runs.
        """
        readme = _README.read_text(encoding="utf-8")
        badge = re.search(r"coverage%20gate-(\d+)%25", readme)

        assert badge is not None, "README has no coverage badge to check."
        metadata = _pyproject()
        floor = metadata["tool"]["coverage"]["report"]["fail_under"]  # type: ignore[index]

        assert int(badge.group(1)) == floor, (
            f"README badge says {badge.group(1)}%, pyproject enforces {floor}%."
        )


class TestStartHereDescribesThisRelease:
    """It tells the reader to read it before anything else, so it must be true."""

    def test_it_states_the_current_version(self) -> None:
        """It carried "0.1.0 (pre-alpha, not released)" against six tags.

        Of every document in the set this is the one whose staleness
        propagates furthest, because it is the one that claims precedence.
        """
        start_here = _START_HERE.read_text(encoding="utf-8")

        assert f"**Version:** {dqt.__version__}" in start_here, (
            f"docs/00-START-HERE.md does not state version {dqt.__version__}."
        )

    def test_it_does_not_call_a_released_project_unreleased(self) -> None:
        """Pinned separately from the number, because the phrasing outlives it.

        Updating the digits and leaving "pre-alpha, not released" beside them
        is the natural half-fix, and it keeps the part that actually misleads.
        """
        start_here = _START_HERE.read_text(encoding="utf-8")

        assert "not released" not in start_here
        assert "pre-alpha" not in start_here.lower()


class TestTheMaturityClaimMatchesTheVersion:
    """``Development Status`` is what PyPI shows before anyone reads a word."""

    def test_a_one_point_x_release_is_not_classified_pre_release(self) -> None:
        """`1.0.0` froze four surfaces under test; "Pre-Alpha" denies that.

        This is the honesty gate pointing the other way from usual -- the
        code is further along than the claim, and understating maturity on
        the page a prospective user lands on is still a false statement about
        the project.
        """
        major = int(dqt.__version__.split(".", 1)[0])
        if major < 1:
            return

        metadata = _pyproject()
        classifiers = metadata["project"]["classifiers"]  # type: ignore[index]
        status = [
            classifier
            for classifier in classifiers  # type: ignore[union-attr]
            if classifier.startswith("Development Status ::")
        ]

        assert status, "No Development Status classifier."
        assert not any(
            phase in status[0] for phase in ("Pre-Alpha", "Alpha", "Beta", "Planning")
        ), f"Version {dqt.__version__} is classified {status[0]!r}."
