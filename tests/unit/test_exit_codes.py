"""The exit-code contract (DQT-06).

`DQT-critical-review.md` §1.10: DQT advertises itself as a data-quality gate
for CI, and a gate is exactly an exit code. There were none -- `dqt profile`
returned 0 whenever it did not crash, so a pipeline "gated" on it passed with
a table full of critical issues.

The decision is a pure function of the run result and the caller's threshold.
That is deliberate: a CI gate is the one behaviour where being able to reason
about every branch matters most, and a decision buried in an argparse handler
can only be tested by running the whole pipeline.

Codes are fixed by the roadmap's `DQT-06` body and are not ours to renumber:
0 clean, 1 error-severity findings, 2 warning-severity only, 3
configuration or connection error, 4 internal error.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from dqt.common.models import DQIssue, PipelineResult, StageError
from dqt.exit_codes import ExitCode, decide_exit_code


def _result(
    *,
    severities: tuple[str, ...] = (),
    status: str = "success",
    stage_errors: tuple[StageError, ...] = (),
) -> PipelineResult:
    """Build a run result carrying issues of the given severities.

    Args:
        severities: One issue is created per entry.
        status: Run status to report.
        stage_errors: Stage failures to attach.

    Returns:
        A PipelineResult suitable for exit-code decisions.

    Example:
        result = _result(severities=("error",))
    """
    return PipelineResult(
        run_id="run-001",
        connection_id="c",
        started_at=datetime(2026, 9, 5, tzinfo=UTC),
        ended_at=datetime(2026, 9, 5, tzinfo=UTC),
        status=status,  # type: ignore[arg-type]
        issues=[
            DQIssue(
                issue_id=f"i{n}",
                run_id="run-001",
                dimension="completeness",
                severity=severity,  # type: ignore[arg-type]
                message="x",
                table_name="t",
                column_name="c",
            )
            for n, severity in enumerate(severities)
        ],
        stage_errors=list(stage_errors),
    )


class TestFindingsDecideTheCode:
    """Codes 0, 1 and 2: what the data itself said."""

    def test_a_clean_run_is_zero(self) -> None:
        """No issues, nothing to gate on."""
        assert decide_exit_code(_result()) == ExitCode.SUCCESS

    def test_an_error_severity_finding_is_one(self) -> None:
        """This is the case the whole contract exists for.

        Before `DQT-06` this returned 0, so a CI job gated on `dqt profile`
        went green with error-severity issues in the report it just wrote.
        """
        assert decide_exit_code(_result(severities=("error",))) == ExitCode.ERROR_FINDINGS

    def test_critical_counts_as_error(self) -> None:
        """``critical`` is above ``error``, not beside it.

        The severity ladder is ordered, and a contract that failed on
        ``error`` but not on ``critical`` would be the wrong way round.
        """
        assert decide_exit_code(_result(severities=("critical",))) == ExitCode.ERROR_FINDINGS

    def test_warnings_alone_are_two_when_the_caller_asked_to_gate_on_them(self) -> None:
        """Code 2 is reachable, but only by opting in.

        The default threshold is ``error``, so warnings are reported and not
        fatal -- failing a build on warnings by default would train people to
        ignore the gate. ``--fail-on warning`` makes them hard, and the
        separate code lets a pipeline tell "warnings only" apart from "errors"
        without parsing output.
        """
        assert (
            decide_exit_code(_result(severities=("warning",)), fail_on="warning")
            == ExitCode.WARNING_FINDINGS
        )

    def test_the_worst_severity_wins(self) -> None:
        """A run with both reports the error, not the warning."""
        assert decide_exit_code(_result(severities=("warning", "error"))) == ExitCode.ERROR_FINDINGS

    def test_info_is_not_a_finding_to_gate_on(self) -> None:
        """``info`` is descriptive, and gating on it would make the gate useless."""
        assert decide_exit_code(_result(severities=("info",))) == ExitCode.SUCCESS


class TestFailOnRaisesOrLowersTheBar:
    """`--fail-on` chooses the threshold; it does not change what was found."""

    def test_fail_on_warning_makes_warnings_fail(self) -> None:
        assert (
            decide_exit_code(_result(severities=("warning",)), fail_on="warning")
            == ExitCode.WARNING_FINDINGS
        )

    def test_fail_on_error_lets_warnings_pass(self) -> None:
        """The default: warnings are reported, not fatal."""
        assert (
            decide_exit_code(_result(severities=("warning",)), fail_on="error") == ExitCode.SUCCESS
        )

    def test_fail_on_none_never_gates_on_findings(self) -> None:
        """For a run that should report without gating -- a scheduled scan."""
        assert (
            decide_exit_code(_result(severities=("critical",)), fail_on="none") == ExitCode.SUCCESS
        )

    def test_fail_on_none_still_reports_a_broken_run(self) -> None:
        """`--fail-on` governs findings, never whether the run worked.

        Suppressing a connection failure because the caller asked not to gate
        on data quality would be the silent-failure defect `NEW-B` removed,
        reintroduced one layer up.
        """
        result = _result(
            status="failed",
            stage_errors=(
                StageError(
                    stage="discover_schema",
                    message="unable to open database file",
                    exception_type="OperationalError",
                ),
            ),
        )

        assert decide_exit_code(result, fail_on="none") == ExitCode.CONFIGURATION_ERROR


class TestBrokenRunsOutrankFindings:
    """Codes 3 and 4: the run itself, which no threshold can wave through."""

    def test_a_discovery_failure_is_a_configuration_error(self) -> None:
        """Not reaching the database is the caller's to fix, so 3 not 4.

        Discovery is the first thing that touches the DSN, so a failure there
        is a wrong DSN, a missing file, or credentials -- all things the
        invoker can correct.
        """
        result = _result(
            status="failed",
            stage_errors=(
                StageError(
                    stage="discover_schema",
                    message="unable to open database file",
                    exception_type="OperationalError",
                ),
            ),
        )

        assert decide_exit_code(result) == ExitCode.CONFIGURATION_ERROR

    def test_a_later_stage_failure_is_an_internal_error(self) -> None:
        """The connection worked, so what broke is ours, and 4 says so.

        The split matters to whoever is on call: 3 means look at your
        invocation, 4 means open an issue.
        """
        result = _result(
            status="failed",
            stage_errors=(
                StageError(stage="profile_data", message="boom", exception_type="TypeError"),
            ),
        )

        assert decide_exit_code(result) == ExitCode.INTERNAL_ERROR

    def test_a_broken_run_outranks_its_findings(self) -> None:
        """A partial result's issue list is not a verdict on the data.

        Returning 1 here would say "your data has errors" when the truth is
        "we could not finish looking".
        """
        result = _result(
            severities=("error",),
            status="failed",
            stage_errors=(
                StageError(stage="profile_data", message="boom", exception_type="TypeError"),
            ),
        )

        assert decide_exit_code(result) == ExitCode.INTERNAL_ERROR

    def test_partial_runs_still_report_their_findings(self) -> None:
        """A missing rule file degrades the run but does not void what ran.

        `NEW-B` made a missing rule file yield ``partial``. The checks that
        did run produced real verdicts, so they still decide the code.
        """
        result = _result(
            severities=("error",),
            status="partial",
            stage_errors=(
                StageError(
                    stage="apply_rules",
                    message="rule file not found: r.yaml",
                    exception_type="missing_input",
                ),
            ),
        )

        assert decide_exit_code(result) == ExitCode.ERROR_FINDINGS


def test_every_documented_code_is_reachable() -> None:
    """All five codes are produced by some input, and none collide.

    A contract with an unreachable code is a documentation defect: a caller
    writing a case for it would be writing dead script.
    """
    assert {code.value for code in ExitCode} == {0, 1, 2, 3, 4}


@pytest.mark.parametrize("fail_on", ["error", "warning", "none"])
def test_fail_on_accepts_exactly_the_documented_values(fail_on: str) -> None:
    """The three documented thresholds all parse."""
    assert decide_exit_code(_result(), fail_on=fail_on) == ExitCode.SUCCESS


def test_an_unknown_threshold_is_rejected() -> None:
    """A typo must not silently become the most permissive setting.

    ``--fail-on erorr`` quietly meaning "never fail" is how a gate stops
    gating without anyone noticing.
    """
    with pytest.raises(ValueError, match="fail_on"):
        decide_exit_code(_result(), fail_on="erorr")
