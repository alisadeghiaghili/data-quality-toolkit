"""Grounded unit tests for ``dqt.sql.diagnostics`` (NEW-C slice 1).

These tests construct ``TableProfile`` / ``ColumnProfile`` objects directly
rather than seeding a database. That is deliberate and architectural:
``DQDiagnostics.run`` maps profiling statistics onto issues and must not need
a live connection to do it. If these tests ever require a database to pass,
domain logic has leaked into an adapter and the dependency direction has been
violated.

On ground truth for the severity threshold: the boundary is DQT's own
invention, not a physical or statistical quantity, so there is no external
oracle to check it against. The correct substitute is a hand-derived boundary
case -- null counts chosen so the ratio lands exactly on, and exactly below,
the documented cut. That is a test of the *documented* behaviour holding, not
a test of the code against itself. A future reader should not mistake it for
the latter.
"""

from __future__ import annotations

from dqt.sql.diagnostics import DQDiagnostics
from dqt.sql.profiling import ColumnProfile, TableProfile


def _profile_with(null_count: int, row_count: int) -> TableProfile:
    """Build a one-column table profile with the given counts.

    Args:
        null_count: Number of NULL values to report for the column.
        row_count: Number of rows to report for the table and the column.

    Returns:
        A TableProfile carrying exactly one ColumnProfile.

    Example:
        profile = _profile_with(null_count=5, row_count=10)
    """
    return TableProfile(
        schema_name="main",
        table_name="t",
        row_count=row_count,
        columns=[
            ColumnProfile(
                schema_name="main",
                table_name="t",
                column_name="x",
                null_count=null_count,
                row_count=row_count,
            )
        ],
    )


def test_severity_threshold_at_50_percent_nulls() -> None:
    """Severity escalates to ``error`` at exactly half NULLs, and not before.

    Three hand-chosen fixtures bracket the documented cut:

    * 1 NULL in 10 rows  -> 0.10, below the cut  -> ``warning``
    * 49 NULLs in 100    -> 0.49, below the cut  -> ``warning``
    * 5 NULLs in 10 rows -> 0.50, *on* the cut   -> ``error``

    The 0.49 and 0.50 pair is the point of the test. It pins the comparison as
    inclusive (``>=``) and pins the constant at exactly one half: a rule of
    ``> 0.5`` would classify the 0.50 fixture as ``warning``, and a cut placed
    anywhere in (0.49, 0.50) would be indistinguishable from the true one on
    coarser fixtures.
    """
    diagnostics = DQDiagnostics()

    ten_percent = diagnostics.run([_profile_with(1, 10)], run_id="run-001")
    just_below = diagnostics.run([_profile_with(49, 100)], run_id="run-001")
    exactly_half = diagnostics.run([_profile_with(5, 10)], run_id="run-001")

    assert [i.severity for i in ten_percent] == ["warning"]
    assert [i.severity for i in just_below] == ["warning"]
    assert [i.severity for i in exactly_half] == ["error"]


def test_no_issue_when_no_nulls() -> None:
    """A column with zero NULLs produces zero issues.

    Conservation property: no defect present implies no defect reported. This
    is what keeps a clean table from generating noise, and it is the invariant
    that would break first if the NULL guard were ever inverted or dropped.
    """
    issues = DQDiagnostics().run([_profile_with(0, 10)], run_id="run-001")

    assert issues == []


def test_issue_carries_its_evidence_and_scope() -> None:
    """A raised issue identifies where it came from and what it saw.

    ``DQIssue.evidence`` is the only record of the numbers behind the verdict.
    If it disagreed with the profile, the HTML report and the metrics store
    would present two different truths for the same run.
    """
    issues = DQDiagnostics().run([_profile_with(3, 4)], run_id="run-001")

    assert len(issues) == 1
    issue = issues[0]
    assert issue.dimension == "completeness"
    assert issue.severity == "error"  # 3/4 = 0.75, above the cut
    assert issue.schema_name == "main"
    assert issue.table_name == "t"
    assert issue.column_name == "x"
    assert issue.evidence == {"null_count": 3, "row_count": 4}
    assert issue.rule_name is None
    assert "3 NULL values" in issue.message


def test_every_null_bearing_column_yields_exactly_one_issue() -> None:
    """Issues are per column, and clean columns contribute none.

    A table with three columns, two of which carry NULLs, must raise exactly
    two issues. This guards the per-column loop against both duplication and
    the table-wide short-circuit that a naive refactor tends to introduce.
    """
    profile = TableProfile(
        schema_name="main",
        table_name="t",
        row_count=10,
        columns=[
            ColumnProfile("main", "t", "clean", null_count=0, row_count=10),
            ColumnProfile("main", "t", "some_nulls", null_count=2, row_count=10),
            ColumnProfile("main", "t", "mostly_null", null_count=9, row_count=10),
        ],
    )

    issues = DQDiagnostics().run([profile], run_id="run-001")

    assert {i.column_name for i in issues} == {"some_nulls", "mostly_null"}
    assert {i.severity for i in issues} == {"warning", "error"}
