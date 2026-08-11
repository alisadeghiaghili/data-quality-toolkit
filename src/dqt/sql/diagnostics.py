"""
Basic data-quality diagnostics for DQT.

This module converts simple profiling facts into actionable DQIssue objects.
The current implementation is intentionally minimal and focuses on
completeness-related diagnostics only.
"""

from __future__ import annotations

from dqt.common.models import DQIssue, IssueSeverity
from dqt.sql.profiling import TableProfile


class DQDiagnostics:
    """Minimal diagnostics engine for DQT.

    The current version raises completeness issues when a column contains
    NULL values. Later versions can add validity, uniqueness, consistency,
    and referential integrity diagnostics.

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
        return issues
