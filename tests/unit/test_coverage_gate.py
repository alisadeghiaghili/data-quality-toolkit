"""The coverage floor is one number, and CI enforces it (`NEW-W`).

`pyproject.toml` sets `fail_under`. CI ran `pytest --cov-fail-under=80`, and
a command-line flag beats a config file — so for as long as both existed, the
gate that actually ran was **80** while the file said otherwise, and every
local run used the file.

Nobody was lying; there were simply two numbers and only one of them was
enforced. That is the failure mode worth a test rather than a fix: the fix
lasts until the next person adds the flag back for a reason that seems good
at the time.

So the workflow must not pass `--cov-fail-under` at all. `pyproject.toml` is
the single authority, and this checks that nothing overrides it.
"""

from __future__ import annotations

import pathlib
import tomllib

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_WORKFLOW = _ROOT / ".github" / "workflows" / "ci.yaml"


class TestThereIsOnlyOneCoverageFloor:
    """Two numbers means the quieter one wins, and nobody notices which."""

    def test_ci_does_not_override_the_configured_floor(self) -> None:
        """A flag on the command line beats ``pyproject.toml`` silently.

        The failure this prevents is not a low gate -- it is a gate that
        disagrees with the file everyone reads to find out what the gate is.

        Comment lines are stripped before the check. The workflow explains in
        a comment why the flag is absent, and a test that could not tell a
        comment from a command would forbid the explanation along with the
        thing it explains.
        """
        commands = [
            line
            for line in _WORKFLOW.read_text(encoding="utf-8").splitlines()
            if not line.strip().startswith("#") and "--cov-fail-under" in line
        ]

        assert commands == [], (
            "CI passes --cov-fail-under, which overrides pyproject.toml. "
            f"Set the floor in pyproject.toml alone. Found: {commands}"
        )

    def test_the_configured_floor_is_the_one_that_was_agreed(self) -> None:
        """95, set on 2026-09-06 at the owner's instruction.

        Pinned so that lowering it is a visible decision in a diff rather
        than a quiet edit to a number in a config file.
        """
        metadata = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

        assert metadata["tool"]["coverage"]["report"]["fail_under"] == 95

    def test_ci_still_measures_coverage(self) -> None:
        """Removing the flag must not remove the measurement with it.

        Without ``--cov`` there is no coverage data, and ``fail_under`` has
        nothing to judge -- which would pass silently and prove nothing.
        """
        workflow = _WORKFLOW.read_text(encoding="utf-8")

        assert "--cov=src/dqt" in workflow
