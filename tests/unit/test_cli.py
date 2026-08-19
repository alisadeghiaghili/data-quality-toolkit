"""
Unit tests for dqt.cli.

Covers the end-to-end `dqt profile` invocation via main() — this is the
regression test for the confirmed `connection_id` crash (DQPipelineConfig
requires it, but _build_pipeline_config never set it).

Also covers `NEW-H`: `_build_pipeline_config` must forward `rule_files` from
an optional `--config` file into the `DQPipelineConfig` it builds, and the
`profile` CLI command must therefore run rule-engine checks (not only the
built-in completeness diagnostics) when a config file names rule files.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from dqt.cli import _build_pipeline_config, main
from dqt.common.storage import RunStore


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


# ---------------------------------------------------------------------------
# NEW-H: rule_files from --config must reach the pipeline
# ---------------------------------------------------------------------------


def test_build_pipeline_config_forwards_rule_files() -> None:
    """A `rule_files` list in the config-file dict must land on the built
    DQPipelineConfig unchanged.

    Ground truth: shape 3 (seeded fixture, hand-computed expected value) —
    the expected list is the literal input dict value, not a value the
    function under test produced.
    """
    args = argparse.Namespace(schema=None, connection_id="cli")
    file_cfg = {"rule_files": ["a.yaml", "b.yaml"]}

    cfg = _build_pipeline_config(args, file_cfg)

    assert cfg.rule_files == ["a.yaml", "b.yaml"]


@pytest.fixture
def rule_violation_db(make_sqlite_db) -> Path:
    """A hand-built SQLite DB with exactly one NOT NULL rule violation.

    Ground truth (derived by hand from the literal INSERT statements below,
    not by running any DQT code): the ``customers`` table has 3 rows; row
    id=2 has ``email IS NULL``; rows id=1 and id=3 have non-NULL emails.
    A ``NOT NULL`` rule scoped to ``customers.email`` must therefore report
    exactly one violation: ``null_count=1`` out of ``total_rows=3``.
    """
    return make_sqlite_db(
        "rule_violation.db",
        """
        CREATE TABLE customers (
            id INTEGER PRIMARY KEY,
            email TEXT,
            name TEXT NOT NULL
        );
        INSERT INTO customers VALUES (1, 'alice@example.com', 'Alice');
        INSERT INTO customers VALUES (2, NULL, 'Bob');
        INSERT INTO customers VALUES (3, 'carol@example.com', 'Carol');
        """,
    )


@pytest.fixture
def rule_file(tmp_path: Path) -> Path:
    """A rule file with a single NOT NULL rule scoped to customers.email."""
    path = tmp_path / "rules.json"
    path.write_text(
        json.dumps(
            {
                "rules": [
                    {
                        "name": "email_not_null",
                        "dimension": "completeness",
                        "severity": "error",
                        "scope": {
                            "table_pattern": "customers",
                            "column_pattern": "email",
                        },
                        "expression": "NOT NULL",
                        "params": {},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def pipeline_config_file(tmp_path: Path, rule_file: Path) -> Path:
    """A --config file naming `rule_file` under `rule_files`."""
    path = tmp_path / "dqt_config.json"
    path.write_text(json.dumps({"rule_files": [str(rule_file)]}), encoding="utf-8")
    return path


def test_profile_cli_applies_rule_files_from_config(
    rule_violation_db: Path,
    pipeline_config_file: Path,
    tmp_path: Path,
    monkeypatch,
) -> None:
    """`dqt profile --config <file>` must run the rule engine, not just
    diagnostics, when the config file names `rule_files`.

    Before the fix, `_build_pipeline_config` drops `rule_files` from the
    config dict entirely, so `apply_rules` short-circuits on an empty
    `rule_files` list and the run reports zero rule issues — only the
    built-in completeness diagnostic on the NULL email fires. This test
    asserts the rule-engine issue (`rule_name="email_not_null"`) is present
    in the persisted run, which is the fixture's one hand-derived violation
    (see `rule_violation_db`).
    """
    report_dir = tmp_path / "reports"
    store_path = tmp_path / "runs.db"
    argv = [
        "dqt",
        "profile",
        "--dsn",
        f"sqlite:///{rule_violation_db}",
        "--config",
        str(pipeline_config_file),
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
    run_id = reports[0].stem.removeprefix("dqt_report_")

    store = RunStore(db_path=store_path)
    issues = store.load_issues(run_id)
    rule_issues = [i for i in issues if i["rule_name"] == "email_not_null"]

    assert len(rule_issues) == 1
    assert rule_issues[0]["evidence"]["null_count"] == 1
    assert rule_issues[0]["evidence"]["total_rows"] == 3
