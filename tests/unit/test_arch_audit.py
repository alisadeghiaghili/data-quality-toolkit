"""The architecture audit, and whether it can actually catch anything (`ARC-01`).

`CLAUDE.md` §2 states DQT's architecture rules in prose. `tools/arch_audit.py`
checks them. This checks the checker.

**Every rule is given something to catch.** An audit that reports zero on a
clean tree and would also report zero on a broken one is worse than no audit:
it converts an unchecked assumption into a green tick. So each rule below is
handed a small synthetic module that breaks it, and has to say so — and only
then is it worth running the same rules over the real tree and believing the
answer.

The synthetic modules are parsed, never imported. A rule that had to import
what it checks would need every optional driver installed to say anything
about drivers.
"""

from __future__ import annotations

import ast
import pathlib
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "tools"))

from arch_audit import (  # noqa: E402
    audit,
    check_dialect_branching,
    check_drivers,
    check_inward,
    check_missingly,
    check_pipeline_cannot_cleanse,
    check_viz_purity,
)


def _tree(source: str) -> ast.Module:
    """Parse a synthetic module.

    Args:
        source: Python source text.

    Returns:
        The parsed module.

    Example:
        tree = _tree("import sqlite3")
    """
    return ast.parse(source)


class TestEachRuleCatchesItsOwnViolation:
    """A rule that cannot fail is a comment with a test-shaped costume."""

    def test_a_driver_outside_the_dialects_package_is_caught(self) -> None:
        """Two authorities on opening a connection is how one ignores read_only."""
        found = list(check_drivers("sql/rules.py", _tree("import pyodbc")))

        assert [violation.rule for violation in found] == ["driver-boundary"]
        assert "pyodbc" in found[0].detail

    def test_a_driver_inside_the_dialects_package_is_not(self) -> None:
        """A dialect owning its driver is the point of the abstraction."""
        assert list(check_drivers("sql/dialects/sqlite.py", _tree("import sqlite3"))) == []

    def test_an_outward_dependency_is_caught(self) -> None:
        """Persistence must not know about adapters."""
        found = list(
            check_inward("common/storage.py", _tree("from dqt.sql.cleansing import Thing"))
        )

        assert [violation.rule for violation in found] == ["inward"]

    def test_a_deferred_outward_dependency_is_caught_too(self) -> None:
        """An import moved inside a function is still a dependency.

        Hiding one from a reader makes it worse rather than better, and it is
        exactly how the violation this rule first found was written.
        """
        source = "def load():\n    from dqt.sql.cleansing import Thing\n    return Thing"
        found = list(check_inward("common/storage.py", _tree(source)))

        assert [violation.rule for violation in found] == ["inward"]

    def test_an_inward_dependency_is_allowed(self) -> None:
        """Adapters may know about the domain; that direction is the design."""
        assert (
            list(check_inward("sql/rules.py", _tree("from dqt.common.models import DQIssue"))) == []
        )

    def test_dialect_branching_is_caught(self) -> None:
        """A second place deciding what SQLite needs is one nobody updates."""
        found = list(check_dialect_branching("sql/rules.py", _tree('x = name == "sqlite"')))

        assert [violation.rule for violation in found] == ["dialect-branching"]

    def test_dialect_branching_inside_the_dialects_package_is_allowed(self) -> None:
        """Somewhere has to know; the point is that it is only there."""
        found = list(
            check_dialect_branching("sql/dialects/__init__.py", _tree('x = name == "sqlite"'))
        )

        assert found == []

    def test_missingly_outside_the_bridge_is_caught(self) -> None:
        """DQT must stay usable without its optional sibling."""
        found = list(check_missingly("sql/profiling.py", _tree("import missingly")))

        assert [violation.rule for violation in found] == ["missingly-bridge"]

    def test_missingly_inside_the_bridge_is_allowed(self) -> None:
        """The bridge is the one place that is allowed to know it exists."""
        assert list(check_missingly("bridges/missingly.py", _tree("import missingly"))) == []

    def test_a_database_reaching_chart_module_is_caught(self) -> None:
        """A chart module that can read a database is one that will."""
        found = list(check_viz_purity("viz.py", _tree("from dqt.sql import rules")))

        assert [violation.rule for violation in found] == ["viz-purity"]

    def test_the_pipeline_reaching_cleansing_is_caught(self) -> None:
        """`Q1` made this structural, not a default.

        A flag can be flipped; an import that does not exist cannot.
        """
        found = list(
            check_pipeline_cannot_cleanse(
                "sql/pipeline.py", _tree("from dqt.sql.cleansing import cleanse_apply")
            )
        )

        assert [violation.rule for violation in found] == ["no-cleansing-from-run"]

    def test_another_module_reaching_cleansing_is_not(self) -> None:
        """Cleansing is a supported API; only ``run()`` must not reach it."""
        found = list(
            check_pipeline_cannot_cleanse(
                "cli.py", _tree("from dqt.sql.cleansing import cleanse_apply")
            )
        )

        assert found == []


class TestTheRealTreeIsClean:
    """Having established the rules can fail, run them for real."""

    def test_the_package_has_no_architectural_violations(self) -> None:
        """`ARC-01`'s acceptance: zero, with no baseline to tolerate any.

        The message lists what was found, so a failure is actionable from the
        test output alone rather than requiring the tool to be re-run.
        """
        violations = audit(_ROOT / "src" / "dqt")

        assert violations == [], "\n".join(
            f"{violation.path}: [{violation.rule}] {violation.detail}" for violation in violations
        )


class TestTheRulesCoverWhatTheStandardStates:
    """A rule nobody wired into `audit()` protects nothing."""

    @pytest.mark.parametrize(
        "rule",
        [
            "driver-boundary",
            "inward",
            "dialect-branching",
            "missingly-bridge",
            "viz-purity",
            "no-cleansing-from-run",
        ],
    )
    def test_the_rule_is_reachable_from_the_entry_point(self, rule: str) -> None:
        """Each named rule is one ``audit()`` actually runs.

        Checked by source text rather than by triggering it: a rule can be
        correct, tested in isolation, and never called -- which is the one
        failure mode the tests above cannot see.
        """
        import arch_audit

        source = pathlib.Path(arch_audit.__file__).read_text(encoding="utf-8")
        body = source.split("def audit(")[1]

        checker = "check_" + rule.replace("-", "_")
        aliases = {
            "check_inward": "check_inward",
            "check_driver_boundary": "check_drivers",
            "check_dialect_branching": "check_dialect_branching",
            "check_missingly_bridge": "check_missingly",
            "check_viz_purity": "check_viz_purity",
            "check_no_cleansing_from_run": "check_pipeline_cannot_cleanse",
        }
        assert aliases.get(checker, checker) in body
