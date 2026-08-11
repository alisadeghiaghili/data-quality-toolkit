"""
Unit tests for dqt.cli.

Covers the end-to-end `dqt profile` invocation via main() — this is the
regression test for the confirmed `connection_id` crash (DQPipelineConfig
requires it, but _build_pipeline_config never set it).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dqt.cli import main


@pytest.fixture
def small_db(make_sqlite_db) -> Path:
    """Create a small SQLite DB and return its file path."""
    return make_sqlite_db(
        "cli_test.db",
        """
        CREATE TABLE customers (
            id INTEGER PRIMARY KEY,
            email TEXT,
            name TEXT NOT NULL
        );
        INSERT INTO customers VALUES (1, 'alice@example.com', 'Alice');
        INSERT INTO customers VALUES (2, NULL, 'Bob');
        """,
    )


def test_profile_command_runs_end_to_end(small_db: Path, tmp_path: Path, monkeypatch) -> None:
    """`dqt profile --dsn ...` must exit 0 and produce an HTML report."""
    report_dir = tmp_path / "reports"
    store_path = tmp_path / "runs.db"
    argv = [
        "dqt",
        "profile",
        "--dsn",
        f"sqlite:///{small_db}",
        "--report-dir",
        str(report_dir),
        "--store",
        str(store_path),
    ]
    monkeypatch.setattr("sys.argv", argv)

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
    reports = list(report_dir.glob("*.html"))
    assert len(reports) == 1
