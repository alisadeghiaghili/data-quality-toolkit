"""`RunStore` closes what it opens (`NEW-T`).

Every method opened a connection with ``with self._connect() as conn:``. In
`sqlite3` that context manager is a **transaction**, not a close: it commits
on success, rolls back on an exception, and leaves the connection open. So
each call leaked one until garbage collection got round to it.

It was filed rather than fixed when it was found, because the fix is not a
one-liner. Wrapping the same connection in a close as well as a transaction
changes the **nesting order of commit and close**, and that is a change to
when data becomes durable — the kind that is fine ninety-nine times and
corrupts a store the hundredth. So the order is what these tests are mostly
about.

Cost today is bounded: a local SQLite file, a short-lived process. It stops
being bounded the moment the FastAPI surface is served for real, because
`dqt.ui.api` opens a store per request.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from dqt.common.models import DQIssue, DQMetric, PipelineResult
from dqt.common.storage import RunStore


class _WatchedConnection:
    """A real connection that records whether it was closed.

    Example:
        watched = _WatchedConnection(sqlite3.connect(":memory:"))
    """

    def __init__(self, inner: sqlite3.Connection) -> None:
        """Wrap *inner*.

        Args:
            inner: The real connection.

        Example:
            watched = _WatchedConnection(connection)
        """
        self._inner = inner
        self.closed = False

    def close(self) -> None:
        """Close the wrapped connection and remember that it happened.

        Returns:
            None.

        Example:
            watched.close()
        """
        self.closed = True
        self._inner.close()

    def __enter__(self) -> Any:
        """Begin the wrapped connection's transaction.

        Returns:
            Whatever the real connection's context manager returns.

        Example:
            with watched: ...
        """
        return self._inner.__enter__()

    def __exit__(self, *exception: Any) -> Any:
        """End the transaction, and refuse to do so after a close.

        This is the assertion that matters. If a future change closes before
        committing, the commit lands on a closed connection and the write is
        lost -- silently, because nothing else in the process would notice.

        Args:
            *exception: The exception triple, if any.

        Returns:
            Whatever the real connection's context manager returns.

        Raises:
            AssertionError: If the transaction ends after the close.

        Example:
            with watched: ...
        """
        assert not self.closed, "the transaction ended after the connection was closed"
        return self._inner.__exit__(*exception)

    def __getattr__(self, name: str) -> Any:
        """Delegate everything else.

        Args:
            name: Attribute name.

        Returns:
            The wrapped connection's attribute.

        Example:
            watched.execute("SELECT 1")
        """
        return getattr(self._inner, name)


@pytest.fixture
def watched_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Return a store whose connections are watched, and the list of them.

    Args:
        tmp_path: pytest's per-test directory.
        monkeypatch: Used to intercept ``sqlite3.connect``.

    Returns:
        A ``(store, opened)`` tuple, where *opened* grows as connections are
        made.

    Example:
        store, opened = watched_store
    """
    import dqt.common.storage as storage

    opened: list[_WatchedConnection] = []
    real_connect = sqlite3.connect

    def watching_connect(*args: Any, **kwargs: Any) -> _WatchedConnection:
        watched = _WatchedConnection(real_connect(*args, **kwargs))
        opened.append(watched)
        return watched

    monkeypatch.setattr(storage.sqlite3, "connect", watching_connect)
    return RunStore(db_path=tmp_path / "runs.db"), opened


def _result(run_id: str = "run-1") -> PipelineResult:
    """Build a small result with one metric and one issue.

    Args:
        run_id: Identifier for the run.

    Returns:
        A PipelineResult.

    Example:
        store.save_run(_result())
    """
    moment = datetime(2026, 9, 6, tzinfo=UTC)
    return PipelineResult(
        run_id=run_id,
        connection_id="c",
        started_at=moment,
        ended_at=moment,
        status="success",
        dqt_version="1.0.2",
        metrics=[
            DQMetric(
                run_id=run_id,
                dimension="completeness",
                score=1.0,
                table_name="orders",
                column_name="id",
            )
        ],
        issues=[
            DQIssue(
                issue_id="i-1",
                run_id=run_id,
                dimension="completeness",
                severity="warning",
                message="m",
                table_name="orders",
                column_name="id",
            )
        ],
    )


class TestEveryConnectionIsClosed:
    """A leak that only garbage collection cleans up is still a leak."""

    def test_writing_a_run_closes_what_it_opened(self, watched_store: Any) -> None:
        """The write path, which is also the one that must stay durable."""
        store, opened = watched_store
        store.init_schema()
        store.save_run(_result())

        assert opened, "no connection was opened, so this test proved nothing"
        assert all(connection.closed for connection in opened), (
            f"{sum(not c.closed for c in opened)} of {len(opened)} left open"
        )

    def test_reading_closes_too(self, watched_store: Any) -> None:
        """Reads are the common case on the HTTP surface, one per request."""
        store, opened = watched_store
        store.init_schema()
        store.save_run(_result())
        opened.clear()

        store.load_runs()
        store.load_metrics(run_id="run-1")
        store.load_issues(run_id="run-1")
        store.load_rule_results("run-1")
        store.load_rule_history("r")

        assert len(opened) >= 5
        assert all(connection.closed for connection in opened)

    def test_a_failing_call_still_closes(self, watched_store: Any) -> None:
        """The path a `finally` exists for.

        A store refused for being out of date must not leak the connection it
        opened to find that out -- and that is the one call guaranteed to
        raise.
        """
        store, opened = watched_store
        store.init_schema()
        with sqlite3.connect(store._db_path) as raw:  # noqa: SLF001
            raw.execute("PRAGMA user_version = 999")
        opened.clear()

        with pytest.raises(RuntimeError):
            store.init_schema()

        assert opened, "the guard opened no connection"
        assert all(connection.closed for connection in opened)


class TestDataStillBecomesDurable:
    """The risk the fix introduces, asserted from both sides."""

    def test_a_saved_run_survives_a_new_store_object(self, tmp_path: Path) -> None:
        """Commit must happen before close, not after.

        Read back through a *different* ``RunStore``, so the assertion cannot
        be satisfied by an object that still holds an uncommitted
        transaction.
        """
        RunStore(db_path=tmp_path / "runs.db").init_schema()
        RunStore(db_path=tmp_path / "runs.db").save_run(_result())

        reread = RunStore(db_path=tmp_path / "runs.db").load_runs()

        assert [run["run_id"] for run in reread] == ["run-1"]

    def test_a_failed_write_leaves_nothing_behind(self, tmp_path: Path) -> None:
        """Rollback must still happen, and still happen before the close.

        The failure is forced by dropping ``run_metrics`` after the schema is
        written: ``save_run`` inserts the ``runs`` row, then fails on the
        metrics. Either the whole save rolls back or the store keeps a run
        that never happened.

        A CHECK violation would have been the more natural trigger and does
        not work, which is worth recording: ``save_run`` inserts with ``OR
        IGNORE`` for idempotency, and ``OR IGNORE`` swallows constraint
        violations too -- so a metric with an invalid dimension is dropped
        silently rather than refused. That is a separate observation, noted
        in ``docs/BACKLOG.md``, not something this test asserts.
        """
        store = RunStore(db_path=tmp_path / "runs.db")
        store.init_schema()
        with sqlite3.connect(tmp_path / "runs.db") as raw:
            raw.execute("DROP TABLE run_metrics")

        with pytest.raises(sqlite3.OperationalError):
            store.save_run(_result("run-bad"))

        assert RunStore(db_path=tmp_path / "runs.db").load_runs() == []
