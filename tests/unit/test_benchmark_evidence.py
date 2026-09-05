"""The committed benchmark run, checked as evidence (`GATE-04`).

The `v0.4` rung asks for a committed benchmark run reporting profiling, rule
evaluation and cleanse-plan timings, each under a published budget, for a
stated fixture size.

**This test never times anything.** It reads
``benchmarks/results/latest.json`` — a file produced on a real machine and
committed — and checks that the evidence is complete, matches the fixture the
budgets were published for, and came in under them. Reading a file is
deterministic where reading a clock is not, so the gate holds in CI without
becoming the flaky test `benchmarks/budgets.py` explains at length.

What it therefore catches is not slowness. It catches **evidence that stopped
being evidence**: a run recorded at a different fixture size than the budgets
describe, a phase quietly dropped, or a number that has crept past the band.
A budget nobody records against is a wish, and a recording nobody checks is a
file.
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_BENCHMARKS = _ROOT / "benchmarks"
sys.path.insert(0, str(_BENCHMARKS))

from budgets import BUDGETS, FIXTURE_COLUMNS, FIXTURE_ROWS  # noqa: E402

_RESULTS = _BENCHMARKS / "results" / "latest.json"


@pytest.fixture(scope="module")
def recorded() -> dict[str, object]:
    """Load the committed run.

    Returns:
        The recorded measurement.

    Example:
        assert recorded["rows"] == FIXTURE_ROWS
    """
    return dict(json.loads(_RESULTS.read_text(encoding="utf-8")))


class TestTheEvidenceExistsAndIsComplete:
    """A budget nobody records against is a wish."""

    def test_a_run_is_committed(self) -> None:
        """The rung asks for a *committed* run, not a runnable script."""
        assert _RESULTS.exists(), f"no recorded benchmark at {_RESULTS}"

    def test_every_budgeted_phase_was_measured(self, recorded: dict[str, object]) -> None:
        """A phase can be dropped from the script and nobody would notice.

        Asked from the budget side rather than the result side, so adding a
        budget without measuring it fails here too.
        """
        timings = dict(recorded["timings"])  # type: ignore[arg-type]

        assert set(timings) == set(BUDGETS)

    def test_it_names_the_machine_it_was_taken_on(self, recorded: dict[str, object]) -> None:
        """A timing with no machine beside it cannot be argued with.

        The budgets are justified by what this machine measured, so the next
        person needs to know whether their slower number means a regression
        or a slower box.
        """
        machine = dict(recorded["machine"])  # type: ignore[arg-type]

        assert machine["platform"]
        assert machine["python"]


class TestTheEvidenceMatchesTheBudgetsItIsJudgedBy:
    """A budget for one fixture proves nothing about another."""

    def test_the_run_used_the_published_fixture(self, recorded: dict[str, object]) -> None:
        """Halving the rows would halve every timing and prove nothing.

        This is the assertion that stops the gate being passed by shrinking
        the problem, which is the cheapest way to make any budget hold.
        """
        assert recorded["rows"] == FIXTURE_ROWS
        assert recorded["columns"] == FIXTURE_COLUMNS

    def test_the_run_is_a_median_rather_than_a_single_shot(
        self, recorded: dict[str, object]
    ) -> None:
        """One measurement of a noisy thing is an anecdote."""
        assert int(recorded["repeats"]) >= 3  # type: ignore[call-overload]

    @pytest.mark.parametrize("phase", sorted(BUDGETS))
    def test_the_phase_came_in_under_budget(self, recorded: dict[str, object], phase: str) -> None:
        """The rung's actual claim, one case per phase.

        The message names both numbers, because "over budget" without them
        tells whoever sees it nothing about whether to investigate or to
        re-measure on a quieter machine.
        """
        timings = dict(recorded["timings"])  # type: ignore[arg-type]
        seconds = float(timings[phase])  # type: ignore[arg-type]

        assert seconds <= BUDGETS[phase], (
            f"{phase} took {seconds:.3f}s against a {BUDGETS[phase]:.2f}s budget"
        )

    def test_no_phase_is_suspiciously_close_to_its_budget(
        self, recorded: dict[str, object]
    ) -> None:
        """A number at 90% of budget is a failure that has not happened yet.

        The budgets are ten to twenty times the measured times on purpose, so
        anything approaching one means something changed by an order of
        magnitude and the right response is to find out why -- not to wait
        for the assertion above to start failing intermittently.
        """
        timings = dict(recorded["timings"])  # type: ignore[arg-type]
        crowded = {
            phase: float(seconds)  # type: ignore[arg-type]
            for phase, seconds in timings.items()
            if float(seconds) > 0.5 * BUDGETS[phase]  # type: ignore[arg-type]
        }

        assert crowded == {}, f"over half their budget: {crowded}"
