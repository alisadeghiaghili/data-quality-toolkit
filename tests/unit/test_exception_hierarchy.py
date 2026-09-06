"""One exception hierarchy, rooted in `exceptions.py` (`DQT-09`).

The last open task on the authoritative roadmap's DQT track. Every module
raised built-in `ValueError` and `ImportError`, so a caller had no way to ask
"did *DQT* fail, or did Python?" -- which matters most in the place DQT is
meant to live, a scheduled job that has to decide whether to alert.

`exceptions.py` already existed and already said what to do: make
`ReadOnlyViolationError` a subclass of the new base *"without changing its
name, its module path, or the ``except ReadOnlyViolationError`` call sites
that already depend on it."* That is the constraint these tests encode.

**Every new type also inherits the built-in it replaces.** A caller catching
`ValueError` around `cleanse_apply` keeps working, and a caller catching
`DQTError` starts working. Converting the raises without that would be a
breaking change dressed as a minor -- the exception type is as much a part of
the public surface as the function signature, and `docs/API-STABILITY.md`
freezes the surface, not just the names in it.

`ConfigurationError` sits between the root and `ConnectionConfigError`
because the roadmap's four names do not cover everything that is a
configuration problem -- a bad bind host is not a bad `ConnectionConfig` --
and inventing a flat fifth name would have left the hierarchy shapeless.

**What deliberately stays a `ValueError`:** a score outside `[0, 1]` handed
to `viz.score_bar`, a negative bar value. Those are argument errors, and the
roadmap says so directly. A caller passing a nonsense number has a bug in
their code, not a data-quality condition to handle.
"""

from __future__ import annotations

import pytest

from dqt.exceptions import (
    CleansingError,
    ConfigurationError,
    ConnectionConfigError,
    DQTError,
    ReadOnlyViolationError,
    RuleEvaluationError,
)


class TestTheHierarchyHasOneRoot:
    """`except DQTError` is the question a scheduled job needs to ask."""

    @pytest.mark.parametrize(
        "error_type",
        [
            ReadOnlyViolationError,
            RuleEvaluationError,
            ConnectionConfigError,
            CleansingError,
            ConfigurationError,
        ],
    )
    def test_every_dqt_error_descends_from_the_root(self, error_type: type) -> None:
        """The acceptance criterion, stated directly."""
        assert issubclass(error_type, DQTError)

    def test_the_root_is_not_a_bare_exception_alias(self) -> None:
        """A root that caught everything would answer nothing.

        ``except DQTError`` has to exclude a `KeyError` from a caller's own
        code, or it is just ``except Exception`` with a friendlier name.
        """
        assert DQTError is not Exception
        assert not issubclass(KeyError, DQTError)

    def test_connection_config_errors_are_configuration_errors(self) -> None:
        """A connection is one thing that can be misconfigured, not the only one.

        The nesting is what lets a caller catch every configuration problem
        without enumerating them, and still distinguish a bad DSN when it
        wants to.
        """
        assert issubclass(ConnectionConfigError, ConfigurationError)


class TestExistingCallersKeepWorking:
    """The compatibility that makes this a minor rather than a break."""

    @pytest.mark.parametrize(
        "error_type",
        [RuleEvaluationError, ConnectionConfigError, CleansingError, ConfigurationError],
    )
    def test_each_still_answers_to_the_builtin_it_replaced(self, error_type: type) -> None:
        """These conditions raised ``ValueError`` before this task.

        Anything already catching that -- including DQT's own tests, the
        CLI's exit-code mapping, and any user script -- must not start
        seeing an uncaught exception because the type became more specific.
        """
        assert issubclass(error_type, ValueError)

    def test_the_read_only_error_keeps_its_identity(self) -> None:
        """Named in the README and raised across three public functions.

        Its module path and name are unchanged; only its base moved, which
        is precisely what ``exceptions.py`` said should happen.
        """
        assert ReadOnlyViolationError.__module__ == "dqt.exceptions"
        assert issubclass(ReadOnlyViolationError, DQTError)


class TestTheRaisesActuallyUseThem:
    """A hierarchy nothing raises is the F10 failure in a different costume."""

    def test_an_unsupported_dsn_scheme_raises_a_connection_config_error(self) -> None:
        """The first thing that goes wrong for a new user, and by far."""
        from dqt.sql.dialects import get_dialect

        with pytest.raises(ConnectionConfigError):
            get_dialect("mysql://user:pw@host/db")

    def test_a_malformed_rule_becomes_an_error_issue_not_a_silent_pass(self) -> None:
        """A regex rule with no pattern cannot be compiled into SQL.

        It does **not** propagate, and that is deliberate rather than a gap:
        `apply_rules` catches a failed compilation per target and records it
        as an error-severity issue, so one malformed rule cannot abort a run
        across twenty tables. `RuleEvaluationError` types that internal
        failure and its message reaches the issue.

        The assertion this test originally made -- that the error reaches
        the caller as an exception -- was simply wrong about the code, and
        asserting it would have forced a worse design to satisfy the test.
        What matters to a user is the property below: a rule that could not
        run is reported as a problem rather than counted as a pass, which is
        the same false-clean-bill-of-health failure `DQT-04` and `GATE-02`
        both exist to prevent.
        """
        from dqt.common.models import ConnectionConfig, RuleConfig, RuleScope
        from dqt.sql.rules import apply_rules
        from dqt.sql.schema_discovery import DiscoveredColumn, DiscoveredTable

        rule = RuleConfig(
            name="broken",
            dimension="validity",
            severity="error",
            scope=RuleScope(column_pattern="email"),
            expression="REGEX",
            params={},
        )
        table = DiscoveredTable(
            schema_name="main",
            table_name="people",
            columns=[
                DiscoveredColumn(
                    schema_name="main",
                    table_name="people",
                    column_name="email",
                    data_type="TEXT",
                    nullable=True,
                    is_primary_key=False,
                )
            ],
        )

        issues, _ = apply_rules(
            "run-1",
            ConnectionConfig(id="c", dsn="sqlite:///:memory:"),
            [rule],
            [table],
        )

        assert [issue.severity for issue in issues] == ["error"]
        assert "regex rule requires params.pattern" in issues[0].message

    def test_a_dialect_that_cannot_express_a_rule_raises(self) -> None:
        """SQL Server has no regular-expression operator, and says so.

        This is the one rule failure that does reach a caller directly, and
        the module's own docstring named `DQT-09` as the task that should
        re-home it off ``ValueError``. Refusing rather than mapping `regex`
        onto ``LIKE`` is the point: a wildcard matcher would answer a
        different question while looking like it answered this one.
        """
        from dqt.sql.dialects import get_dialect_by_name

        with pytest.raises(RuleEvaluationError, match="no regular-expression"):
            get_dialect_by_name("sqlserver").regex_not_matching_predicate('"email"', "^a")

    def test_an_unknown_cleansing_plan_raises_a_cleansing_error(self) -> None:
        """The plan lifecycle is where a caller most needs to branch.

        "Unknown plan" is a caller mistake; "the data drifted" is a real
        condition to retry after re-planning. Both are cleansing failures,
        and neither is a Python argument error.
        """
        from dqt.common.models import ConnectionConfig
        from dqt.sql.cleansing import cleanse_apply

        class _EmptyStore:
            def load_cleansing_plan(self, plan_id: str) -> None:
                return None

        with pytest.raises(CleansingError):
            cleanse_apply(
                "plan-nope",
                ConnectionConfig(id="c", dsn="sqlite:///:memory:", read_only=False),
                store=_EmptyStore(),
            )


class TestArgumentErrorsStayArgumentErrors:
    """The roadmap draws this line, and it is worth holding."""

    def test_a_nonsense_score_is_not_a_dqt_error(self) -> None:
        """``viz.score_bar(5.0)`` is a bug in the caller's code.

        Wrapping it in DQTError would tell a scheduled job that the data had
        a quality problem, when what actually happened is that somebody
        passed a percentage where a ratio was wanted.
        """
        from dqt.viz import score_bar

        with pytest.raises(ValueError) as raised:
            score_bar(5.0, label="nope")

        assert not isinstance(raised.value, DQTError)
