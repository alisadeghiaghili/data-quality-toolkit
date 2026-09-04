"""
Unit tests for DQT-03: enforcing ConnectionConfig.read_only and --dry-run.

Before this fix, `ConnectionConfig.read_only` (default True) was read by zero
lines of code and `apply_cleansing()` issued UPDATE/DELETE regardless of it.
These tests are the honesty-gate ground truth named in `docs/HONESTY-GATE.md`
sec 1 for a read-only / write-prevention guarantee: a checksum of the
database file before and after each scenario, not a row count.

Covered here:

- `apply_cleansing()` on a read_only=True connection raises
  ReadOnlyViolationError before touching the database (guard #2 in
  cleansing.py), and the file is byte-identical afterwards.
- `get_connection()` opens SQLite in mode=ro when read_only=True, so even a
  direct write attempt through the returned connection fails at the driver
  level (guard #1, independent of guard #2).
- `get_connection()` still opens a normal writable connection when
  read_only=False.
- `apply_cleansing()` defaults to dry_run=True: on a writable (read_only=False)
  connection, the default call changes no rows; only an explicit
  dry_run=False call does.
- The connection-layer guard does not depend on the file already existing:
  read_only=True against a nonexistent SQLite file raises OperationalError
  instead of silently creating it (a documented behavior change from the
  pre-DQT-03 code).
- The CLI's --dry-run/--commit flags map onto ConnectionConfig.read_only.
- The critical trap named in the DQT-03 task brief: making the *profiled*
  database read-only must not make the RunStore (a separate SQLite file)
  read-only. A full pipeline run against a read_only=True profiled DB must
  still persist a run to the store.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from dqt.cli import _build_connection_config, _build_parser
from dqt.common.models import ConnectionConfig, DQPipelineConfig
from dqt.common.storage import RunStore
from dqt.exceptions import ReadOnlyViolationError
from dqt.sql._connect import get_connection
from dqt.sql.cleansing import CleansingConfig, apply_cleansing
from dqt.sql.pipeline import DQTPipeline

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sha256(path: Path) -> str:
    """Return the hex SHA-256 digest of the file at *path*.

    This is the "byte-identical" ground truth required by
    `docs/HONESTY-GATE.md` sec 1: a real file hash, not a row count.
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _dsn(db_file: Path) -> str:
    return f"sqlite:///{db_file}"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def users_db(make_sqlite_db) -> Path:
    """SQLite DB with a 'users' table containing whitespace/case issues."""
    return make_sqlite_db(
        "ro_users.db",
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            email TEXT,
            name  TEXT
        );
        INSERT INTO users VALUES (1, '  Alice@Example.COM  ', '  alice  ');
        INSERT INTO users VALUES (2, 'BOB@EXAMPLE.COM',       'BOB');
        INSERT INTO users VALUES (3, NULL,                    'carol');
        """,
    )


def _standardize_cfg() -> CleansingConfig:
    return CleansingConfig(
        table_name="users",
        column_name="email",
        operation="standardize",
        params={"trim": True, "case": "lower"},
    )


# ---------------------------------------------------------------------------
# Guard #2: apply_cleansing() raises on read_only=True
# ---------------------------------------------------------------------------


class TestApplyCleansingReadOnlyGuard:
    def test_raises_on_default_read_only_connection(self, users_db: Path) -> None:
        """ConnectionConfig defaults to read_only=True; apply_cleansing() must
        refuse rather than silently write, which is exactly the DQT-03 defect."""
        before = _sha256(users_db)
        conn_cfg = ConnectionConfig(id="test", dsn=_dsn(users_db))  # read_only=True (default)
        assert conn_cfg.read_only is True

        with pytest.raises(ReadOnlyViolationError):
            apply_cleansing("run-ro-1", conn_cfg, [_standardize_cfg()])

        after = _sha256(users_db)
        assert after == before, "table must be byte-identical after a refused write"

    def test_raises_before_opening_any_connection(self, tmp_path: Path) -> None:
        """The guard fires even for a DSN pointing at a file that does not
        exist, proving it runs before get_connection() (which would raise a
        different error for a missing file)."""
        missing = tmp_path / "does_not_exist.db"
        conn_cfg = ConnectionConfig(id="test", dsn=_dsn(missing))
        with pytest.raises(ReadOnlyViolationError):
            apply_cleansing("run-ro-2", conn_cfg, [_standardize_cfg()])
        assert not missing.exists()

    def test_deduplicate_also_refused(self, make_sqlite_db) -> None:
        db_file = make_sqlite_db(
            "ro_dup.db",
            """
            CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT);
            INSERT INTO users VALUES (1, 'a@example.com');
            INSERT INTO users VALUES (2, 'a@example.com');
            """,
        )
        before = _sha256(db_file)
        conn_cfg = ConnectionConfig(id="test", dsn=_dsn(db_file))
        cfg = CleansingConfig(
            table_name="users",
            column_name=None,
            operation="deduplicate",
            params={"key_columns": ["email"]},
        )
        with pytest.raises(ReadOnlyViolationError):
            apply_cleansing("run-ro-3", conn_cfg, [cfg])
        assert _sha256(db_file) == before


# ---------------------------------------------------------------------------
# Guard #1: get_connection() enforces read-only at the driver level
# ---------------------------------------------------------------------------


class TestGetConnectionEnforcesReadOnly:
    def test_read_only_connection_rejects_direct_write(self, users_db: Path) -> None:
        """Even bypassing apply_cleansing() entirely and using the raw
        connection returned by get_connection(), a write must fail at the
        SQLite driver level (mode=ro), not merely by application convention."""
        conn_cfg = ConnectionConfig(id="test", dsn=_dsn(users_db))  # read_only=True
        conn = get_connection(conn_cfg)
        try:
            with pytest.raises(sqlite3.OperationalError, match="readonly"):
                conn.execute("UPDATE users SET name = 'x' WHERE id = 1")
        finally:
            conn.close()

    def test_read_only_connection_still_allows_reads(self, users_db: Path) -> None:
        conn_cfg = ConnectionConfig(id="test", dsn=_dsn(users_db))
        conn = get_connection(conn_cfg)
        try:
            count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            assert count == 3
        finally:
            conn.close()

    def test_writable_connection_allows_write(self, users_db: Path) -> None:
        """Contrast case: read_only=False must not be blocked by mode=ro."""
        conn_cfg = ConnectionConfig(id="test", dsn=_dsn(users_db), read_only=False)
        conn = get_connection(conn_cfg)
        try:
            conn.execute("UPDATE users SET name = 'x' WHERE id = 1")
            conn.commit()
            row = conn.execute("SELECT name FROM users WHERE id = 1").fetchone()
            assert row[0] == "x"
        finally:
            conn.close()

    def test_read_only_nonexistent_file_raises_instead_of_creating(self, tmp_path: Path) -> None:
        """Documented behavior change: mode=ro does not create the database
        file. Pre-DQT-03, `sqlite3.connect(path)` always auto-created it,
        even for a connection later described as read-only."""
        missing = tmp_path / "brand_new.db"
        conn_cfg = ConnectionConfig(id="test", dsn=_dsn(missing))  # read_only=True
        with pytest.raises(sqlite3.OperationalError):
            get_connection(conn_cfg)
        assert not missing.exists()

    def test_writable_nonexistent_file_still_auto_creates(self, tmp_path: Path) -> None:
        """Contrast case: read_only=False preserves the pre-existing
        auto-create behavior exactly, so this is not a silent regression for
        callers who intend to write to a brand-new database."""
        new_file = tmp_path / "new_writable.db"
        conn_cfg = ConnectionConfig(id="test", dsn=_dsn(new_file), read_only=False)
        conn = get_connection(conn_cfg)
        conn.close()
        assert new_file.exists()


# ---------------------------------------------------------------------------
# dry_run: the second, independent safety default
# ---------------------------------------------------------------------------


class TestApplyCleansingDryRunDefault:
    def test_dry_run_default_changes_no_rows(self, users_db: Path) -> None:
        """dry_run defaults to True. On a writable connection (read_only=False,
        so the read-only guard does not apply), the default call must still
        leave the table byte-identical -- this is the 'no rows change without
        --commit' acceptance criterion, expressed at the library level."""
        before = _sha256(users_db)
        conn_cfg = ConnectionConfig(id="test", dsn=_dsn(users_db), read_only=False)

        result = apply_cleansing("run-dry-1", conn_cfg, [_standardize_cfg()])

        assert result.dry_run is True
        assert result.total_changes == 2  # planned changes: rows 1 and 2
        assert _sha256(users_db) == before, "dry run must not touch the file"

    def test_explicit_dry_run_false_commits(self, users_db: Path) -> None:
        before = _sha256(users_db)
        conn_cfg = ConnectionConfig(id="test", dsn=_dsn(users_db), read_only=False)

        result = apply_cleansing("run-dry-2", conn_cfg, [_standardize_cfg()], dry_run=False)

        assert result.dry_run is False
        assert result.total_changes == 2
        assert _sha256(users_db) != before, "a real commit must change the file"

    def test_dry_run_plan_matches_what_a_real_run_would_do(self, users_db: Path) -> None:
        """The dry-run log and the real-run log must describe the same
        changes, so a preview is trustworthy: it is not a different,
        weaker computation than the real path."""
        conn_cfg = ConnectionConfig(id="test", dsn=_dsn(users_db), read_only=False)

        planned = apply_cleansing("run-dry-3", conn_cfg, [_standardize_cfg()])
        applied = apply_cleansing("run-dry-4", conn_cfg, [_standardize_cfg()], dry_run=False)

        planned_changes = {(entry.before_value, entry.after_value) for entry in planned.log}
        applied_changes = {(entry.before_value, entry.after_value) for entry in applied.log}
        assert planned_changes == applied_changes


# ---------------------------------------------------------------------------
# Four-hash checksum proof, in one place (mirrors the task's mandatory proof)
# ---------------------------------------------------------------------------


class TestFourHashChecksumProof:
    def test_read_only_and_guarded_write_leave_file_identical_but_real_write_differs(
        self, users_db: Path
    ) -> None:
        """Reproduces the exact four-hash shape required by
        docs/HONESTY-GATE.md sec 1: hash before, after a read-only run, after
        an attempted write under the guard, and after a real write with the
        guard removed (dry_run=False on a read_only=False connection)."""
        hash_before = _sha256(users_db)

        # 2. After a "read-only run" -- exercised via get_connection reads only.
        ro_cfg = ConnectionConfig(id="test", dsn=_dsn(users_db))
        conn = get_connection(ro_cfg)
        conn.execute("SELECT COUNT(*) FROM users").fetchone()
        conn.close()
        hash_after_read_only_run = _sha256(users_db)

        # 3. After an attempted write under the guard.
        with pytest.raises(ReadOnlyViolationError):
            apply_cleansing("run-hash-1", ro_cfg, [_standardize_cfg()])
        hash_after_guarded_attempt = _sha256(users_db)

        # 4. After a real write with the guard removed (read_only=False,
        #    dry_run=False -- both opt-outs supplied explicitly).
        rw_cfg = ConnectionConfig(id="test", dsn=_dsn(users_db), read_only=False)
        apply_cleansing("run-hash-2", rw_cfg, [_standardize_cfg()], dry_run=False)
        hash_after_real_write = _sha256(users_db)

        assert hash_before == hash_after_read_only_run == hash_after_guarded_attempt
        assert hash_after_real_write != hash_before


# ---------------------------------------------------------------------------
# CLI: --dry-run/--commit map onto ConnectionConfig.read_only
# ---------------------------------------------------------------------------


class TestCliDryRunFlag:
    def _parse(self, argv: list[str]):
        parser = _build_parser()
        return parser.parse_args(argv)

    def test_default_is_dry_run_read_only_true(self) -> None:
        args = self._parse(["profile", "--dsn", "sqlite:///demo.db"])
        assert args.commit is False
        cfg = _build_connection_config(args)
        assert cfg.read_only is True

    def test_explicit_dry_run_flag_is_read_only_true(self) -> None:
        args = self._parse(["profile", "--dsn", "sqlite:///demo.db", "--dry-run"])
        assert args.commit is False
        assert _build_connection_config(args).read_only is True

    def test_commit_flag_is_read_only_false(self) -> None:
        args = self._parse(["profile", "--dsn", "sqlite:///demo.db", "--commit"])
        assert args.commit is True
        assert _build_connection_config(args).read_only is False

    def test_dry_run_and_commit_are_mutually_exclusive(self) -> None:
        with pytest.raises(SystemExit):
            self._parse(["profile", "--dsn", "sqlite:///demo.db", "--dry-run", "--commit"])


# ---------------------------------------------------------------------------
# The critical trap: profiled-DB read-only must not affect the RunStore
# ---------------------------------------------------------------------------


class TestRunStoreRemainsWritableWhenProfiledDbIsReadOnly:
    def test_full_pipeline_run_persists_with_read_only_profiled_db(
        self, make_sqlite_db, tmp_path: Path
    ) -> None:
        """RunStore lives in its own, separate SQLite file. Making the
        *profiled* database read-only (the DQT-03 default) must not prevent
        the pipeline from writing its results to the run store -- that would
        break every profiling run. This is the named regression test for
        that trap."""
        db_file = make_sqlite_db(
            "ro_pipeline.db",
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
        profiled_hash_before = _sha256(db_file)

        conn_cfg = ConnectionConfig(id="test", dsn=_dsn(db_file))  # read_only=True (default)
        assert conn_cfg.read_only is True
        pipe_cfg = DQPipelineConfig(connection_id="test")
        store_path = tmp_path / "dqt_runs.db"
        pipeline = DQTPipeline(
            connection_config=conn_cfg,
            pipeline_config=pipe_cfg,
            store_path=store_path,
            report_dir=tmp_path,
        )

        result, _report_path = pipeline.run()

        # The run store (a completely different SQLite file) must be
        # writable and must actually contain this run.
        assert store_path.exists()
        store = RunStore(db_path=store_path)
        runs = store.load_runs()
        assert any(r["run_id"] == result.run_id for r in runs)

        # The profiled database itself must be untouched.
        assert _sha256(db_file) == profiled_hash_before
