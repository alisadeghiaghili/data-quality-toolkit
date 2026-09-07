"""
Data-quality diagnostics for DQT.

Turns profiling facts into :class:`~dqt.common.models.DQIssue` objects. It is
**pure**: it receives profiles and returns issues, opening no connection and
issuing no query. That is what lets every diagnostic be tested against
hand-written numbers rather than a live database.

Three of the six dimensions are diagnosed here, and all three come out of the
single profiling pass at no extra scan:

- **completeness** -- NULL counts.
- **uniqueness** -- the distinct count against the *non-NULL* count.
- **consistency** -- the distinct count against the case- and
  whitespace-folded distinct count.

The last two are easy to conflate and must not be. Two rows both saying
``"Shiraz"`` are *duplicated* and perfectly consistent. One row saying
``"Tehran"`` and another ``"tehran"`` are *inconsistent* and not duplicated
at all -- the distinct count cannot see them, because they genuinely are
distinct values.

The other three are diagnosed elsewhere, because they need something this
module deliberately cannot do: ``referential_integrity`` needs a join across
two tables (:mod:`dqt.sql.referential`), and ``validity`` and ``timeliness``
are not yet produced.
"""

from __future__ import annotations

from dqt.common.models import DQIssue, IssueSeverity
from dqt.sql.profiling import ColumnProfile, TableProfile


class DQDiagnostics:
    """Minimal diagnostics engine for DQT.

    Raises completeness, uniqueness and consistency issues from profiling
    facts alone. ``referential_integrity`` is produced by
    :mod:`dqt.sql.referential`, which needs a join this module cannot make
    without becoming impure; ``validity`` and ``timeliness`` are not yet
    produced.

    Example:
        diagnostics = DQDiagnostics()
        issues = diagnostics.run(profiles, run_id="run-001")
    """

    def run(self, profiles: list[TableProfile], run_id: str) -> list[DQIssue]:
        """Generate DQIssue records from profiling results.

        Args:
            profiles: Table profiles computed by SqlProfiler.
            run_id: Pipeline run identifier.

        Returns:
            A flat list of detected DQIssue objects.

        Example:
            issues = diagnostics.run(profiles, run_id="run-001")
        """
        issues: list[DQIssue] = []

        for table_profile in profiles:
            for column_profile in table_profile.columns:
                if column_profile.null_count > 0:
                    severity: IssueSeverity = "warning"
                    if column_profile.row_count > 0:
                        ratio = column_profile.null_count / column_profile.row_count
                        if ratio >= 0.5:
                            severity = "error"

                    issues.append(
                        DQIssue(
                            issue_id=(
                                f"{run_id}:{column_profile.schema_name}:"
                                f"{column_profile.table_name}:{column_profile.column_name}:nulls"
                            ),
                            run_id=run_id,
                            dimension="completeness",
                            severity=severity,
                            message=(
                                f"Column '{column_profile.column_name}' contains "
                                f"{column_profile.null_count} NULL values."
                            ),
                            evidence={
                                "null_count": column_profile.null_count,
                                "row_count": column_profile.row_count,
                            },
                            schema_name=column_profile.schema_name,
                            table_name=column_profile.table_name,
                            column_name=column_profile.column_name,
                            rule_name=None,
                        )
                    )

                issues.extend(self._uniqueness(column_profile, run_id))
                issues.extend(self._consistency(column_profile, run_id))
        return issues

    def _uniqueness(self, column: ColumnProfile, run_id: str) -> list[DQIssue]:
        """Report values that appear more than once.

        Compared against the **non-NULL** count, not the row count.
        ``COUNT(DISTINCT)`` already excludes NULL, so measuring against the
        row count would report every nullable column in the database as
        having duplicates -- the arithmetic slip this method exists to not
        make.

        Args:
            column: One profiled column.
            run_id: The current run.

        Returns:
            One issue when duplicates exist, otherwise none.

        Example:
            issues = DQDiagnostics()._uniqueness(column, "run-1")
        """
        if column.distinct_count is None or column.distinct_is_approximate:
            return []

        present = column.row_count - column.null_count
        duplicates = present - column.distinct_count
        if duplicates <= 0:
            return []

        return [
            DQIssue(
                issue_id=(
                    f"{run_id}:{column.schema_name}:{column.table_name}:"
                    f"{column.column_name}:duplicates"
                ),
                run_id=run_id,
                dimension="uniqueness",
                severity="warning",
                message=(
                    f"Column '{column.column_name}' has {duplicates} duplicate "
                    f"value(s) across {present} non-NULL rows."
                ),
                evidence={
                    "distinct_count": column.distinct_count,
                    "non_null_count": present,
                    "duplicate_count": duplicates,
                },
                schema_name=column.schema_name,
                table_name=column.table_name,
                column_name=column.column_name,
                rule_name=None,
            )
        ]

    def _consistency(self, column: ColumnProfile, run_id: str) -> list[DQIssue]:
        """Report values that are the same thing written more than one way.

        ``"Tehran"``, ``"tehran"`` and ``" Tehran "`` are one city recorded
        three ways. They are **not** duplicates -- the distinct count cannot
        see them, because they genuinely are distinct -- which is why this is
        its own dimension and not a special case of uniqueness.

        Two rows both saying ``"Shiraz"`` are the opposite case: duplicated,
        and perfectly consistent. Conflating the two would flag every column
        holding any repeated value, which is nearly all of them.

        Args:
            column: One profiled column.
            run_id: The current run.

        Returns:
            One issue when spellings collapse, otherwise none.

        Example:
            issues = DQDiagnostics()._consistency(column, "run-1")
        """
        if column.distinct_count is None or column.normalized_distinct_count is None:
            return []

        collapsed = column.distinct_count - column.normalized_distinct_count
        if collapsed <= 0:
            return []

        return [
            DQIssue(
                issue_id=(
                    f"{run_id}:{column.schema_name}:{column.table_name}:"
                    f"{column.column_name}:spelling"
                ),
                run_id=run_id,
                dimension="consistency",
                severity="warning",
                message=(
                    f"Column '{column.column_name}' writes {collapsed} value(s) more "
                    f"than one way: {column.distinct_count} spellings reduce to "
                    f"{column.normalized_distinct_count} once case and surrounding "
                    "whitespace are ignored."
                ),
                evidence={
                    "distinct_count": column.distinct_count,
                    "normalized_distinct_count": column.normalized_distinct_count,
                    "collapsed_count": collapsed,
                },
                schema_name=column.schema_name,
                table_name=column.table_name,
                column_name=column.column_name,
                rule_name=None,
            )
        ]
