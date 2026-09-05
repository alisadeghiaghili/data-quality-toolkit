"""The run store learns what each rule did (`NEW-S`).

`docs/PLAN-VIZ-UI.md` §7 names two blockers that stop the Rules screen being
built without lying, and both are here rather than in the UI:

**The store drops rule results on the floor.** ``PipelineResult.rules_run`` is
populated on every run — one :class:`RuleRunResult` per rule, carrying how many
targets it checked, how many failed, and how many errored — and ``save_run``
writes ``runs``, ``run_metrics`` and ``run_issues`` and simply does not mention
it. The data is computed and thrown away, so "rule history over time" and "this
rule matched zero targets" have nothing to read.

That second one matters more than it sounds. A rule whose scope no longer
matches anything reports no failures, which is indistinguishable from a rule
that passes — and a silently-matching-nothing rule is the most common way a
rule set rots. ``targets_checked == 0`` is the only signal, and it is currently
discarded.

**Runs do not record which DQT produced them.** Scores are only comparable
within a version line, so a trend chart spanning two versions has to say so.
There is no column to read.

**And the version guard was a column probe.** It asked whether ``run_metrics``
had the column ``NEW-A`` added. Every future schema change would append another
one-off question, and the chain would only ever detect the specific past it was
taught about. ``PRAGMA user_version`` is SQLite's own answer: one integer, set
when the schema is written, checked when it is opened.

Switching to it rejects stores written before this change — which is correct
and unavoidable, because this change alters the schema anyway. The store is a
local artifact meant to be recreated rather than migrated
(``docs/CONVENTIONS-DQT.md``), and the refusal is what makes that survivable:
without it the first symptom is an ``OperationalError`` thrown from the middle
of a run that has already done its work.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from dqt.common.models import PipelineResult, RuleRunResult
from dqt.common.storage import SCHEMA_VERSION, RunStore


def _result(
    run_id: str = "run-1",
    *,
    rules_run: list[RuleRunResult] | None = None,
    dqt_version: str = "0.1.0",
) -> PipelineResult:
    """Build a minimal PipelineResult carrying rule summaries.

    Args:
        run_id: Identifier for the run.
        rules_run: Rule summaries to attach, or None for none.
        dqt_version: Version string to record on the run.

    Returns:
        A PipelineResult ready to save.

    Example:
        result = _result("run-1", rules_run=[summary])
    """
    moment = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
    return PipelineResult(
        run_id=run_id,
        connection_id="conn-1",
        started_at=moment,
        ended_at=moment,
        status="success",
        rules_run=rules_run or [],
        dqt_version=dqt_version,
    )


def _summary(
    rule_name: str,
    *,
    run_id: str = "run-1",
    checked: int = 3,
    failed: int = 1,
    errored: int = 0,
) -> RuleRunResult:
    """Build one rule summary.

    Args:
        rule_name: Name of the rule.
        run_id: Run the summary belongs to.
        checked: Targets evaluated.
        failed: Targets that failed.
        errored: Targets whose evaluation itself failed.

    Returns:
        A RuleRunResult.

    Example:
        summary = _summary("not-null-email")
    """
    return RuleRunResult(
        run_id=run_id,
        rule_name=rule_name,
        targets_checked=checked,
        targets_failed=failed,
        targets_error=errored,
    )


@pytest.fixture
def store(tmp_path: Path) -> RunStore:
    """Return an initialised store in a temporary directory.

    Args:
        tmp_path: pytest's per-test directory.

    Returns:
        A RunStore with its schema written.

    Example:
        store.save_run(result)
    """
    created = RunStore(db_path=tmp_path / "runs.db")
    created.init_schema()
    return created


class TestRuleResultsAreKept:
    """The data was already being computed; now it is written down."""

    def test_saving_a_run_saves_its_rule_summaries(self, store: RunStore) -> None:
        """Two rules in, two rows back, with their counts intact."""
        store.save_run(
            _result(
                rules_run=[
                    _summary("not-null-email", checked=3, failed=1),
                    _summary("unique-email", checked=1, failed=0),
                ]
            )
        )

        kept = store.load_rule_results("run-1")

        assert [row["rule_name"] for row in kept] == ["not-null-email", "unique-email"]
        assert kept[0]["targets_checked"] == 3
        assert kept[0]["targets_failed"] == 1
        assert kept[0]["targets_error"] == 0

    def test_a_run_with_no_rules_stores_nothing_and_reads_back_empty(self, store: RunStore) -> None:
        """An empty list is not an error, and must not become a phantom row."""
        store.save_run(_result())

        assert store.load_rule_results("run-1") == []

    def test_a_rule_matching_zero_targets_is_recorded_as_such(self, store: RunStore) -> None:
        """The signal that a rule set has rotted, and the reason for this unit.

        A rule whose scope no longer matches anything reports no failures,
        which reads exactly like a rule that passes. ``targets_checked == 0``
        is the only thing that distinguishes them, so it has to survive the
        round trip rather than being normalised away.
        """
        store.save_run(_result(rules_run=[_summary("orphan-rule", checked=0, failed=0)]))

        kept = store.load_rule_results("run-1")

        assert kept[0]["targets_checked"] == 0
        assert kept[0]["targets_failed"] == 0

    def test_saving_the_same_run_twice_does_not_double_the_rows(self, store: RunStore) -> None:
        """``save_run`` is idempotent for metrics and issues; rules match that.

        A retried save that doubled every rule's history would make a trend
        chart show a step no data supports.
        """
        result = _result(rules_run=[_summary("not-null-email")])
        store.save_run(result)
        store.save_run(result)

        assert len(store.load_rule_results("run-1")) == 1


class TestRuleHistoryAcrossRuns:
    """One rule, read along the time axis rather than the run axis."""

    def test_history_returns_one_entry_per_run_newest_first(self, store: RunStore) -> None:
        """Three runs of one rule, ordered so the latest reads first.

        Newest first because a DBA opening a rule wants to know its current
        state, and scrolling to the bottom for it is the wrong default.
        """
        for index, (run_id, failed) in enumerate(
            [("run-1", 3), ("run-2", 2), ("run-3", 0)], start=1
        ):
            store.save_run(
                _result(
                    run_id=run_id,
                    rules_run=[_summary("not-null-email", run_id=run_id, failed=failed)],
                )
            )
            assert index  # the loop body ran

        history = store.load_rule_history("not-null-email")

        assert [entry["run_id"] for entry in history] == ["run-3", "run-2", "run-1"]
        assert [entry["targets_failed"] for entry in history] == [0, 2, 3]

    def test_history_carries_the_run_timestamp(self, store: RunStore) -> None:
        """A trend needs a time axis, and the rule row has no clock of its own.

        Joining to ``runs`` here rather than duplicating the timestamp on
        every rule row keeps one answer to when a run happened.
        """
        store.save_run(_result(rules_run=[_summary("not-null-email")]))

        history = store.load_rule_history("not-null-email")

        assert history[0]["started_at"].startswith("2026-09-05")

    def test_history_of_an_unknown_rule_is_empty_rather_than_an_error(
        self, store: RunStore
    ) -> None:
        """A renamed or deleted rule has no history, which is an answer."""
        assert store.load_rule_history("never-existed") == []

    def test_history_is_bounded(self, store: RunStore) -> None:
        """A rule that has run for years must not return every run at once.

        Evidence is bounded everywhere else in DQT for the same reason: the
        size of a response should not depend on how long the tool has been in
        use.
        """
        for index in range(10):
            run_id = f"run-{index}"
            store.save_run(_result(run_id=run_id, rules_run=[_summary("r", run_id=run_id)]))

        assert len(store.load_rule_history("r", limit=4)) == 4


class TestRunsRecordWhichDqtProducedThem:
    """Scores are only comparable within a version line."""

    def test_the_version_is_stored_and_read_back(self, store: RunStore) -> None:
        """Without it a trend chart cannot warn that it is comparing apples."""
        store.save_run(_result(dqt_version="9.9.9"))

        assert store.load_runs()[0]["dqt_version"] == "9.9.9"

    def test_an_unstated_version_is_stored_as_unknown_not_guessed(self, store: RunStore) -> None:
        """A result that does not say must not be stamped with whatever is
        installed now.

        The version that *saved* a result is not necessarily the version that
        produced it, and inventing the difference away would make the warning
        this column exists for unreliable in exactly the case it matters.
        """
        store.save_run(_result(dqt_version=""))

        assert store.load_runs()[0]["dqt_version"] == ""

    def test_a_real_pipeline_run_stamps_the_running_version(self, tmp_path: Path) -> None:
        """The empty case above is for a hand-built result, not for DQT itself.

        A run DQT performed must never read as "unknown version", or the
        warning this column exists for would be missing exactly when the tool
        was the thing that changed.
        """
        import dqt
        from dqt import ConnectionConfig, DQPipelineConfig, DQTPipeline

        source = tmp_path / "source.db"
        with sqlite3.connect(source) as conn:
            conn.execute("CREATE TABLE people (id INTEGER PRIMARY KEY, email TEXT)")
            conn.execute("INSERT INTO people (id, email) VALUES (1, 'a@b.com')")

        store_path = tmp_path / "runs.db"
        DQTPipeline(
            ConnectionConfig(id="stamp", dsn=f"sqlite:///{source}"),
            DQPipelineConfig(connection_id="stamp"),
            store_path=store_path,
            report_dir=tmp_path,
        ).run()

        saved = RunStore(db_path=store_path).load_runs()

        assert saved[0]["dqt_version"] == dqt.__version__
        assert saved[0]["dqt_version"] != ""


class TestTheSchemaVersionIsAnInteger:
    """One number, asked and answered, rather than a chain of column probes."""

    def test_a_fresh_store_records_the_current_version(self, tmp_path: Path) -> None:
        """``PRAGMA user_version`` is SQLite's own mechanism for this."""
        RunStore(db_path=tmp_path / "runs.db").init_schema()

        with sqlite3.connect(tmp_path / "runs.db") as conn:
            assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION

    def test_an_older_store_is_refused_by_name(self, tmp_path: Path) -> None:
        """The refusal names the file and the fix, not just the symptom.

        Half-using a store written by an older DQT surfaces as an
        ``OperationalError`` from the middle of a run that has already done
        its work -- the worst possible moment to find out.
        """
        db_path = tmp_path / "runs.db"
        RunStore(db_path=db_path).init_schema()
        with sqlite3.connect(db_path) as conn:
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION - 1}")

        with pytest.raises(RuntimeError, match=str(db_path.name)) as raised:
            RunStore(db_path=db_path).init_schema()

        assert "recreate" in str(raised.value).lower()

    def test_a_store_from_a_newer_dqt_is_refused_too(self, tmp_path: Path) -> None:
        """Reading forwards is no safer than reading backwards.

        An older DQT opening a newer store would silently ignore columns it
        does not know about, which is how a run reports numbers computed from
        a schema it only half understands.
        """
        db_path = tmp_path / "runs.db"
        RunStore(db_path=db_path).init_schema()
        with sqlite3.connect(db_path) as conn:
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")

        with pytest.raises(RuntimeError):
            RunStore(db_path=db_path).init_schema()

    def test_initialising_twice_is_still_safe(self, tmp_path: Path) -> None:
        """The guard must not reject the store it just wrote itself."""
        created = RunStore(db_path=tmp_path / "runs.db")
        created.init_schema()
        created.init_schema()

        assert created.load_runs() == []

    def test_an_empty_path_is_not_treated_as_an_old_store(self, tmp_path: Path) -> None:
        """A store that does not exist yet has no version to disagree with."""
        RunStore(db_path=tmp_path / "nested" / "runs.db").init_schema()
