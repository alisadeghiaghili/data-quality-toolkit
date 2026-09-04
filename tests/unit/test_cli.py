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

from dqt.cli import _build_connection_config, _build_parser, _build_pipeline_config, main
from dqt.common.storage import RunStore
from dqt.exit_codes import ExitCode


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

    # DQT-06: the seeded fixture has NULLs, so diagnostics raise error-severity
    # issues and the gate exits 1. That the exit code moved off 0 is itself
    # evidence the checks ran -- under the old always-zero behaviour this
    # assertion held whether or not anything had been evaluated.
    assert exc_info.value.code == int(ExitCode.ERROR_FINDINGS)
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
    # DQT-06: the seeded fixture has NULLs, so diagnostics raise error-severity
    # issues and the gate exits 1. That the exit code moved off 0 is itself
    # evidence the checks ran -- under the old always-zero behaviour this
    # assertion held whether or not anything had been evaluated.
    assert exc_info.value.code == int(ExitCode.ERROR_FINDINGS)

    reports = list(report_dir.glob("*.html"))
    assert len(reports) == 1
    run_id = reports[0].stem.removeprefix("dqt_report_")

    store = RunStore(db_path=store_path)
    issues = store.load_issues(run_id)
    rule_issues = [i for i in issues if i["rule_name"] == "email_not_null"]

    assert len(rule_issues) == 1
    assert rule_issues[0]["evidence"]["null_count"] == 1
    assert rule_issues[0]["evidence"]["total_rows"] == 3


# ---------------------------------------------------------------------------
# DQT-05: profile can no longer write, so --commit cannot mean anything
# ---------------------------------------------------------------------------


def test_profile_has_no_commit_flag() -> None:
    """`--commit` is gone, because after Q1 it could only weaken safety.

    It set ``read_only=False`` on the connection the pipeline profiles. Now
    that ``run()`` has no cleansing stage, nothing downstream of that flag
    writes -- so its entire remaining effect was to open a writable connection
    to a database DQT only reads from. A flag whose only consequence is to
    remove a guard, in exchange for nothing, should not be offered.
    """
    parser = _build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["profile", "--dsn", "sqlite:///x.db", "--commit"])


def test_profile_still_accepts_dry_run_as_a_no_op() -> None:
    """`--dry-run` keeps parsing, because scripts pass it.

    The behaviour it asked for is now permanent and unconditional. Removing
    the flag as well would break existing invocations to no purpose -- the
    caller's intent is still honoured, it just no longer needs stating.
    """
    parser = _build_parser()

    args = parser.parse_args(["profile", "--dsn", "sqlite:///x.db", "--dry-run"])

    assert args.dsn == "sqlite:///x.db"


def test_the_profiled_connection_is_always_read_only(tmp_path: Path) -> None:
    """Whatever the caller passes, profiling opens read-only.

    This is Q1 reaching the CLI: the guarantee is that a profiling invocation
    cannot mutate, and a guarantee that a command-line flag can switch off is
    not one.
    """
    parser = _build_parser()
    args = parser.parse_args(["profile", "--dsn", f"sqlite:///{tmp_path / 'x.db'}"])

    conn_cfg = _build_connection_config(args)

    assert conn_cfg.read_only is True


# ---------------------------------------------------------------------------
# DQT-06: the exit-code matrix, end to end through main()
# ---------------------------------------------------------------------------


def _run_cli(argv: list[str], monkeypatch: pytest.MonkeyPatch) -> int:
    """Invoke the CLI and return the exit code it produced.

    Args:
        argv: Arguments after the program name.
        monkeypatch: pytest monkeypatch fixture, used to set sys.argv.

    Returns:
        The integer passed to SystemExit.

    Example:
        code = _run_cli(["profile", "--dsn", "sqlite:///x.db"], monkeypatch)
    """
    monkeypatch.setattr("sys.argv", ["dqt", *argv])
    with pytest.raises(SystemExit) as exc_info:
        main()
    return int(exc_info.value.code or 0)


class TestExitCodeMatrix:
    """The roadmap's `DQT-06` verification block, as tests.

    The unit tests in ``test_exit_codes.py`` cover the decision itself. This
    matrix covers the wiring: a contract that is correct in a pure function
    and unreachable from the command line is not a contract a CI job can use.
    """

    @staticmethod
    def _argv(db: Path, tmp_path: Path, *extra: str) -> list[str]:
        return [
            "profile",
            "--dsn",
            f"sqlite:///{db}",
            "--store",
            str(tmp_path / "r.db"),
            "--report-dir",
            str(tmp_path),
            *extra,
        ]

    def test_clean_database_exits_zero(
        self, tmp_path: Path, make_sqlite_db, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No NULLs, no findings, no gate."""
        db = make_sqlite_db(
            "clean.db", "CREATE TABLE t (id INTEGER NOT NULL); INSERT INTO t VALUES (1);"
        )

        code = _run_cli(self._argv(db, tmp_path), monkeypatch)

        assert code == int(ExitCode.SUCCESS)

    def test_dirty_database_exits_one(
        self, tmp_path: Path, make_sqlite_db, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Every row NULL, so completeness raises an error-severity issue.

        This is the case the contract exists for: before `DQT-06` this exited
        0 and a CI job gated on it went green.
        """
        db = make_sqlite_db(
            "dirty.db",
            "CREATE TABLE t (id INTEGER, email TEXT);"
            "INSERT INTO t VALUES (1, NULL); INSERT INTO t VALUES (2, NULL);",
        )

        code = _run_cli(self._argv(db, tmp_path), monkeypatch)

        assert code == int(ExitCode.ERROR_FINDINGS)

    def test_fail_on_none_exits_zero_on_the_same_dirty_database(
        self, tmp_path: Path, make_sqlite_db, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Same data, different threshold, different code.

        Proves the flag reaches the decision rather than being accepted and
        ignored -- which is exactly the defect `NEW-H` was.
        """
        db = make_sqlite_db(
            "dirty.db",
            "CREATE TABLE t (id INTEGER, email TEXT);"
            "INSERT INTO t VALUES (1, NULL); INSERT INTO t VALUES (2, NULL);",
        )

        code = _run_cli(self._argv(db, tmp_path, "--fail-on", "none"), monkeypatch)

        assert code == int(ExitCode.SUCCESS)

    def test_unreachable_database_exits_three(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A wrong DSN is the caller's to fix, and 3 says so.

        Critically it is neither 0 nor 1: a CI job must be able to tell "your
        data is bad" from "I never saw your data".
        """
        code = _run_cli(self._argv(tmp_path / "missing" / "nope.db", tmp_path), monkeypatch)

        assert code == int(ExitCode.CONFIGURATION_ERROR)
