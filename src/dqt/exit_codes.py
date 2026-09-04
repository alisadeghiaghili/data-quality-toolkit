"""Exit-code contract for CI gating (DQT-06).

DQT advertises itself as a data-quality gate for continuous integration, and
a gate is exactly an exit code. Before this module there were none:
``dqt profile`` returned 0 whenever it did not crash, so a pipeline "gated" on
it passed with a table full of critical issues
(``DQT-critical-review.md`` section 1.10).

The decision is a pure function of the run result and the caller's threshold,
deliberately kept out of the argparse handler. A CI gate is the one behaviour
where being able to reason about every branch matters most, and a decision
buried in a command handler can only be exercised by running the whole
pipeline against a real database.

Example:
    from dqt.exit_codes import decide_exit_code

    code = decide_exit_code(result, fail_on="error")
"""

from __future__ import annotations

from enum import IntEnum

from dqt.common.models import PipelineResult

#: Thresholds accepted by ``--fail-on``, in increasing permissiveness.
FAIL_ON_CHOICES = ("error", "warning", "none")

#: Severities that count as an error-level finding. ``critical`` is above
#: ``error`` on the ladder, not beside it, so a contract that failed on one
#: but not the other would be the wrong way round.
_ERROR_SEVERITIES = frozenset({"error", "critical"})

#: Stages whose failure means the caller could not reach the database. A
#: failure here is a wrong DSN, a missing file, or credentials -- all things
#: the invoker can correct, which is what separates code 3 from code 4.
_CONFIGURATION_STAGES = frozenset({"discover_schema"})


class ExitCode(IntEnum):
    """Process exit codes, fixed by the roadmap's ``DQT-06`` body.

    These numbers are a public contract that CI scripts branch on, so they
    are not ours to renumber.

    Attributes:
        SUCCESS: Nothing at or above the caller's threshold was found.
        ERROR_FINDINGS: At least one ``error`` or ``critical`` finding.
        WARNING_FINDINGS: ``warning`` findings only, with a threshold that
            treats them as failing.
        CONFIGURATION_ERROR: The run could not reach the database or the
            configuration was wrong. The caller can fix this.
        INTERNAL_ERROR: The run reached the database and then broke. DQT's
            fault, not the caller's.

    Example:
        assert ExitCode.SUCCESS == 0
    """

    SUCCESS = 0
    ERROR_FINDINGS = 1
    WARNING_FINDINGS = 2
    CONFIGURATION_ERROR = 3
    INTERNAL_ERROR = 4


def decide_exit_code(result: PipelineResult, fail_on: str = "error") -> ExitCode:
    """Map a completed run onto the process exit code it should produce.

    A run that did not finish outranks whatever it managed to find: returning
    a findings code for a broken run would say "your data has errors" when the
    truth is "we could not finish looking". ``fail_on`` governs findings only,
    never whether the run worked -- suppressing a connection failure because
    the caller asked not to gate on data quality would reintroduce, one layer
    up, the silent-failure defect ``NEW-B`` removed.

    Args:
        result: The completed :class:`~dqt.common.models.PipelineResult`.
        fail_on: Threshold at which findings become a failure. One of
            ``"error"`` (default), ``"warning"``, or ``"none"``.

    Returns:
        The :class:`ExitCode` the process should exit with.

    Raises:
        ValueError: If *fail_on* is not one of the documented thresholds. A
            typo must not silently become the most permissive setting; that is
            how a gate stops gating without anyone noticing.

    Example:
        code = decide_exit_code(result, fail_on="warning")
    """
    raise NotImplementedError("decide_exit_code is specified but not implemented")


__all__ = ["FAIL_ON_CHOICES", "ExitCode", "decide_exit_code"]
