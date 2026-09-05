"""The read-only proof, against the servers that matter (`GATE-02`).

`docs/HONESTY-GATE.md` §1 defines a four-hash shape: fingerprint the data
before anything, after a read-only run, after a write attempted **under the
guard**, and after a real write with the guard deliberately removed. The
first three must be identical and the fourth must differ — which together say
that the guard stops writes and that the test would have noticed if it had
not.

That proof has only ever run against SQLite, where it hashes the database
file. This runs it against SQL Server and PostgreSQL, where there is no file
to hash, so the fingerprint is taken over the table's contents instead.

**SQL Server first, and the reason is not preference.** It is the dialect
where DQT's read-only promise is weakest:
:data:`~dqt.sql.dialects.base.ReadOnlyEnforcement.ADVISORY` means the ODBC
access-mode attribute is a *request*, and a write that reaches the server
lands. SQLite's driver refuses (``mode=ro``) and PostgreSQL's server refuses
(session read-only) — on SQL Server **only DQT's own guard stands between a
`read_only` config and a modified production table**. So the engine with the
least help from below is the one where this proof carries the most weight,
and it gets an extra hash the others do not need: a write pushed straight at
the server, bypassing DQT, to show the server really would have allowed it.

Skips when the DSN is unset, so a developer without an instance is not
blocked. CI sets both, which is what makes the skip honest rather than a way
of never finding out.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from collections.abc import Iterator

import pytest

from dqt.common.models import ConnectionConfig
from dqt.exceptions import ReadOnlyViolationError
from dqt.sql._connect import get_connection
from dqt.sql.cleansing import CleansingConfig, cleanse_apply, cleanse_plan
from dqt.sql.dialects import get_dialect_by_name
from dqt.sql.dialects.base import ReadOnlyEnforcement

#: The engines this proof runs against, and the environment variable naming
#: each one's server. SQL Server leads because it has the least protection
#: underneath DQT, not because it was reached first.
ENGINES: tuple[tuple[str, str], ...] = (
    ("sqlserver", "DQT_SQLSERVER_TEST_DSN"),
    ("postgresql", "DQT_POSTGRES_TEST_DSN"),
)


class _NullStore:
    """A store that keeps whatever plan it is handed.

    Example:
        store = _NullStore()
    """

    def __init__(self) -> None:
        """Start with no plan.

        Example:
            store = _NullStore()
        """
        self.plan: object | None = None

    def save_cleansing_plan(self, plan: object) -> None:
        """Keep *plan*.

        Args:
            plan: The plan to keep.

        Returns:
            None.

        Example:
            store.save_cleansing_plan(plan)
        """
        self.plan = plan

    def load_cleansing_plan(self, plan_id: str) -> object:
        """Return the kept plan.

        Args:
            plan_id: Ignored; only one plan is ever held.

        Returns:
            The plan.

        Example:
            plan = store.load_cleansing_plan("any")
        """
        return self.plan

    def mark_cleansing_plan_applied(self, plan_id: str, applied_at: object) -> None:
        """Record that a plan was applied.

        Args:
            plan_id: Ignored.
            applied_at: Ignored.

        Returns:
            None.

        Example:
            store.mark_cleansing_plan_applied("id", None)
        """

    def save_cleansing_log(self, plan_id: str, changes: object, applied_at: object) -> None:
        """Record what a plan changed.

        Args:
            plan_id: Ignored.
            changes: Ignored.
            applied_at: Ignored.

        Returns:
            None.

        Example:
            store.save_cleansing_log("id", [], None)
        """


def _dsn(engine: str) -> str:
    """Return the DSN for *engine*, or skip.

    Args:
        engine: Dialect name.

    Returns:
        The DSN.

    Example:
        dsn = _dsn("sqlserver")
    """
    variable = dict(ENGINES)[engine]
    dsn = os.environ.get(variable)
    if not dsn:
        pytest.skip(f"{variable} is not set; CI sets it against a service container.")
    return dsn


def _writable(engine: str) -> ConnectionConfig:
    """Return a writable connection config for *engine*.

    Args:
        engine: Dialect name.

    Returns:
        A ConnectionConfig with read_only disabled.

    Example:
        config = _writable("sqlserver")
    """
    return ConnectionConfig(id=f"{engine}-setup", dsn=_dsn(engine), read_only=False)


def _execute(engine: str, *statements: str) -> None:
    """Run statements on a writable connection and commit.

    Args:
        engine: Dialect name.
        *statements: SQL to run in order.

    Returns:
        None.

    Example:
        _execute("sqlserver", "CREATE TABLE t (id INT)")
    """
    connection = get_connection(_writable(engine))
    try:
        cursor = connection.cursor()
        for statement in statements:
            cursor.execute(statement)
        connection.commit()
    finally:
        connection.close()


def _fingerprint(engine: str, table: str) -> str:
    """Hash a table's contents, in a fixed order.

    The file-level ``sha256`` the SQLite proof uses has no analogue on a
    server, so the fingerprint is taken over the rows themselves. Ordered by
    the key, because an unordered read would make the hash depend on the
    planner rather than on the data — and a proof that changes when nothing
    did is worse than no proof.

    Args:
        engine: Dialect name.
        table: Table to fingerprint.

    Returns:
        A hex digest.

    Example:
        digest = _fingerprint("sqlserver", "dqt_proof_ab12")
    """
    connection = get_connection(_writable(engine))
    try:
        cursor = connection.cursor()
        cursor.execute(f"SELECT id, email FROM {table} ORDER BY id")
        rows = cursor.fetchall()
    finally:
        connection.close()
    return hashlib.sha256(repr([tuple(row) for row in rows]).encode("utf-8")).hexdigest()


@pytest.fixture(params=[engine for engine, _ in ENGINES])
def proof_table(request: pytest.FixtureRequest) -> Iterator[tuple[str, str]]:
    """Create a seeded table on each engine in turn, then drop it.

    Three rows, one of which has an untrimmed email so a ``standardize``
    cleanse has something to change.

    Args:
        request: Supplies the engine name.

    Yields:
        ``(engine, table_name)``.

    Example:
        def test_something(proof_table):
            engine, table = proof_table
    """
    engine = str(request.param)
    _dsn(engine)  # Skips before creating anything when the server is absent.

    table = f"dqt_proof_{uuid.uuid4().hex[:8]}"
    text_type = "NVARCHAR(200)" if engine == "sqlserver" else "VARCHAR(200)"
    _execute(
        engine,
        f"CREATE TABLE {table} (id INT NOT NULL PRIMARY KEY, email {text_type} NULL)",
        f"INSERT INTO {table} (id, email) VALUES (1, 'a@b.com '), (2, 'c@d.com'), (3, NULL)",
    )
    yield engine, table
    _execute(engine, f"DROP TABLE {table}")


def _standardize(table: str) -> CleansingConfig:
    """Return a trim standardization over *table*'s ``email``.

    Args:
        table: Table to target.

    Returns:
        A CleansingConfig.

    Example:
        config = _standardize("dqt_proof_ab12")
    """
    return CleansingConfig(
        table_name=table,
        column_name="email",
        operation="standardize",
        params={"trim": True},
    )


class TestTheFourHashProofHoldsOnEveryServer:
    """The shape `docs/HONESTY-GATE.md` §1 requires, run where it counts."""

    def test_the_guard_holds_and_the_proof_would_have_noticed(
        self, proof_table: tuple[str, str]
    ) -> None:
        """Four fingerprints: before, read-only, guarded attempt, real write.

        The first three identical says the guard stopped the write. The
        fourth differing says the fingerprint can actually detect one -- a
        proof whose measure never moves proves only that the measure is
        broken.
        """
        engine, table = proof_table
        dsn = _dsn(engine)

        before = _fingerprint(engine, table)

        # 2. A read-only run: DQT opens the connection its own way and reads.
        read_only = ConnectionConfig(id=engine, dsn=dsn)
        connection = get_connection(read_only)
        try:
            connection.cursor().execute(f"SELECT COUNT(*) FROM {table}")
        finally:
            connection.close()
        after_read = _fingerprint(engine, table)

        # 3. A write attempted through DQT under the guard.
        with pytest.raises(ReadOnlyViolationError):
            plan = cleanse_plan(read_only, [_standardize(table)], store=_NullStore())
            cleanse_apply(read_only, plan.plan_id, store=_NullStore())
        after_guarded = _fingerprint(engine, table)

        # 4. A real write, with both opt-outs supplied explicitly.
        writable = ConnectionConfig(id=engine, dsn=dsn, read_only=False)
        store = _NullStore()
        plan = cleanse_plan(writable, [_standardize(table)], store=store)
        cleanse_apply(writable, plan.plan_id, store=store)
        after_write = _fingerprint(engine, table)

        assert before == after_read == after_guarded
        assert after_write != before


class TestSqlServerIsProvedWhereItIsWeakest:
    """The extra hash the other engines do not need.

    On SQLite the driver refuses a write and on PostgreSQL the server does.
    On SQL Server neither does: ``ADVISORY`` means the access-mode attribute
    is a request. So the proof above, on this engine, is a claim about DQT
    alone -- and that claim is only meaningful if the server really would
    have allowed the write it stopped.
    """

    def test_the_dialect_admits_it_cannot_enforce(self) -> None:
        """Stated in the vocabulary before it is demonstrated below."""
        dialect = get_dialect_by_name("sqlserver")

        assert dialect.read_only_enforcement is ReadOnlyEnforcement.ADVISORY

    def test_a_write_pushed_past_dqt_on_a_read_only_connection_lands(self) -> None:
        """The uncomfortable half, and the reason the guard is load-bearing.

        This opens a connection DQT calls read-only and writes through it
        directly, without going through any DQT entry point. The write
        succeeds. Nothing below DQT was ever going to stop it, so the
        four-hash proof above is not decoration on this engine -- it is the
        whole of the protection.
        """
        engine = "sqlserver"
        dsn = _dsn(engine)
        table = f"dqt_advisory_{uuid.uuid4().hex[:8]}"
        _execute(engine, f"CREATE TABLE {table} (id INT NOT NULL PRIMARY KEY)")

        try:
            read_only = ConnectionConfig(id=engine, dsn=dsn)
            with pytest.warns(UserWarning):
                connection = get_connection(read_only)
            try:
                connection.cursor().execute(f"INSERT INTO {table} (id) VALUES (1)")
                connection.commit()
            finally:
                connection.close()

            connection = get_connection(_writable(engine))
            try:
                cursor = connection.cursor()
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                landed = int(cursor.fetchone()[0])
            finally:
                connection.close()
        finally:
            _execute(engine, f"DROP TABLE {table}")

        assert landed == 1, (
            "The SQL Server dialect reports ADVISORY enforcement. If this write "
            "was refused, the server now enforces read-only and the dialect's "
            "vocabulary is out of date -- which is good news, and still a "
            "change DQT has to describe accurately."
        )
