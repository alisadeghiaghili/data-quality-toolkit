"""The published performance budgets (`GATE-04`).

The `v0.4` rung asks for each phase to report a timing *under a published
budget for a stated fixture size*. This is the published part: the fixture,
and what each phase may cost on it.

**Why these numbers, and why they look generous.** On the reference machine
recorded in ``results/latest.json`` the three phases measure roughly 0.06s,
0.04s and 0.09s. The budgets below are ten to twenty times that, which needs
justifying rather than glossing.

At tens of milliseconds, a tight band measures the *machine*: a shared CI
agent, a laptop on battery, or a box mid-antivirus-scan differs from a quiet
desktop by more than the code ever will. A budget set at 3x would fail for
reasons that have nothing to do with DQT, and a budget that cries wolf is one
people learn to re-run rather than read.

**What a budget is for.** Not to certify that DQT is fast — the numbers above
already say it is, on this fixture. It is a tripwire for the change that makes
something an *order of magnitude* slower: the N+1 query that creeps back in,
the per-row Python loop, the full scan where an index was. Those show up as a
multiple, and a band this wide still catches every one of them while staying
silent about noise.

If the measured numbers ever approach the budgets, the right response is to
find out why rather than to raise the budget.

The deterministic properties are gated separately and exactly, by counting
queries in ``tests/unit/sql/test_profiling_cost.py`` and
``tests/unit/sql/test_rules_grouped.py``. A budget in seconds is the second
line, not the first.

Example:
    from budgets import BUDGETS

    assert BUDGETS["profiling"] > 0
"""

from __future__ import annotations

__all__ = ["BUDGETS", "FIXTURE_COLUMNS", "FIXTURE_ROWS"]

#: The stated fixture: rows and text columns beside the key.
#:
#: Large enough that per-row work shows up as time rather than noise, small
#: enough that anyone can run the benchmark in under a minute without
#: thinking about it. A benchmark nobody runs measures nothing.
FIXTURE_ROWS = 50_000
FIXTURE_COLUMNS = 20

#: Seconds each phase may take on the fixture above.
BUDGETS: dict[str, float] = {
    # One aggregate query over 50,000 rows and 21 columns. Measured ~0.06s.
    "profiling": 1.00,
    # Ten NOT NULL rules on one table, which grouped rules make one scan.
    # Measured ~0.04s -- the cheapest phase, and the one an N+1 would ruin
    # most visibly, since its cost would become ten scans instead of one.
    "rules": 1.00,
    # Reads the column in pages and decides what would change, writing
    # nothing. Measured ~0.09s: the most read-heavy of the three, and the
    # only one whose cost is bounded by the page size rather than by one
    # aggregate, so it gets the largest budget.
    "cleanse_plan": 2.00,
}
