"""How cleansing addresses the rows it changes (NEW-M).

Cleansing used SQLite's ``rowid`` directly, so `cleanse_plan`,
`cleanse_apply` and `revert` all failed on PostgreSQL with
``UndefinedColumn: column "rowid" does not exist``. `DQT-08` moved identifier
quoting, the read-only incantation and regex matching into the dialects; row
identity was missed because nothing exercised cleansing on a second dialect.

The fix is not ``rowid`` -> ``ctid``. Three things make that wrong:

* ``ctid`` moves when a row is updated, and can move under ``VACUUM FULL``
  with no data change at all. A plan is applied and reverted in a *later*
  process, so a stored plan holding physical locators could address different
  rows than the ones it was reviewed against. The plan fingerprint catches a
  data change; it cannot catch a physical relocation.
* PostgreSQL has no aggregate over ``tid``, so deduplication's
  ``MIN(rowid)`` / ``MAX(rowid)`` ordering has no direct translation.
* A physical address is not what an audit log should record. "I changed the
  row at disk position X" is not a statement anyone can check later.

So identity is the table's **primary key** where there is one, and a
dialect-supplied physical locator only where there is not.
"""

from __future__ import annotations

import pytest

from dqt.sql.dialects import get_dialect_by_name
from dqt.sql.row_identity import RowIdentity, resolve_row_identity
from dqt.sql.schema_discovery import DiscoveredColumn, DiscoveredTable


def _table(*columns: tuple[str, bool]) -> DiscoveredTable:
    """Build a discovered table from (column_name, is_primary_key) pairs.

    Args:
        *columns: One pair per column.

    Returns:
        A DiscoveredTable carrying those columns.

    Example:
        table = _table(("id", True), ("email", False))
    """
    return DiscoveredTable(
        schema_name="main",
        table_name="customers",
        columns=[
            DiscoveredColumn(
                schema_name="main",
                table_name="customers",
                column_name=name,
                data_type="TEXT",
                nullable=not is_pk,
                is_primary_key=is_pk,
            )
            for name, is_pk in columns
        ],
    )


SQLITE = get_dialect_by_name("sqlite")
POSTGRESQL = get_dialect_by_name("postgresql")


class TestThePrimaryKeyIsPreferred:
    """A key the database maintains beats an address the storage engine owns."""

    def test_a_single_column_key_is_used(self) -> None:
        """The obvious case, and the one almost every table falls into."""
        identity = resolve_row_identity(_table(("id", True), ("email", False)), SQLITE)

        assert identity.columns == ("id",)
        assert identity.locator is None

    def test_a_composite_key_uses_every_column(self) -> None:
        """Dropping part of a composite key would address more than one row.

        An UPDATE built from half a key silently edits siblings, and the log
        would record one change where several happened.
        """
        identity = resolve_row_identity(
            _table(("tenant_id", True), ("id", True), ("email", False)), SQLITE
        )

        assert identity.columns == ("tenant_id", "id")

    def test_the_key_is_preferred_even_where_a_locator_exists(self) -> None:
        """SQLite has ``rowid`` for every table, and still should not use it.

        Portability is only half the reason. The other half is that a primary
        key is stable across the gap between planning and applying, which is
        the gap `DQT-05` opened.
        """
        identity = resolve_row_identity(_table(("id", True), ("x", False)), SQLITE)

        assert identity.locator is None


class TestFallbackToAPhysicalLocator:
    """Tables without a key still have to be cleansable where that is safe."""

    def test_sqlite_falls_back_to_rowid(self) -> None:
        """Every SQLite table has one, and it is stable for its lifetime."""
        identity = resolve_row_identity(_table(("a", False), ("b", False)), SQLITE)

        assert identity.columns == ()
        assert identity.locator == "rowid"

    def test_postgresql_refuses_rather_than_using_ctid(self) -> None:
        """A moving address is worse than an error.

        ``ctid`` would make the code run and the results wrong: a plan applied
        after a ``VACUUM FULL`` would update whatever now sits at the recorded
        position. Refusing names the real requirement -- give the table a
        primary key -- instead of silently corrupting it.
        """
        with pytest.raises(ValueError, match="primary key"):
            resolve_row_identity(_table(("a", False), ("b", False)), POSTGRESQL)

    def test_the_error_names_the_table_and_what_to_do(self) -> None:
        """A DBA reading this should not have to guess which table."""
        with pytest.raises(ValueError, match="customers"):
            resolve_row_identity(_table(("a", False)), POSTGRESQL)


class TestTheIdentityBuildsSql:
    """What the resolved identity is actually for."""

    def test_select_expressions_name_the_key_columns(self) -> None:
        """Planning selects the key so the log can record which row it saw."""
        identity = resolve_row_identity(_table(("id", True)), SQLITE)

        assert identity.select_expressions(SQLITE) == ['"id"']

    def test_select_expressions_fall_back_to_the_locator(self) -> None:
        identity = resolve_row_identity(_table(("a", False)), SQLITE)

        assert identity.select_expressions(SQLITE) == ["rowid"]

    def test_the_where_clause_is_parameterised(self) -> None:
        """Values are bound, never interpolated.

        `DQT-02` parameterised rule literals for exactly this reason, and a
        row key comes from user data just as a rule bound does.
        """
        identity = resolve_row_identity(_table(("tenant_id", True), ("id", True)), SQLITE)

        clause = identity.where_clause(SQLITE)

        assert clause == '"tenant_id" = ? AND "id" = ?'
        assert "%" not in clause

    def test_the_where_clause_uses_the_dialects_placeholder(self) -> None:
        """PostgreSQL binds with ``%s``, and the clause has to say so."""
        identity = resolve_row_identity(_table(("id", True)), POSTGRESQL)

        assert identity.where_clause(POSTGRESQL) == '"id" = %s'

    def test_bind_values_follow_the_clause_order(self) -> None:
        """A composite key whose values were ordered differently from its
        placeholders would address the wrong row while looking correct.
        """
        identity = resolve_row_identity(_table(("tenant_id", True), ("id", True)), SQLITE)

        values = identity.bind_values({"tenant_id": 7, "id": 42})

        assert values == (7, 42)

    def test_a_row_key_missing_part_of_the_identity_is_rejected(self) -> None:
        """Silently binding None would match nothing, or the wrong row."""
        identity = resolve_row_identity(_table(("tenant_id", True), ("id", True)), SQLITE)

        with pytest.raises(KeyError, match="id"):
            identity.bind_values({"tenant_id": 7})


def test_identity_is_hashable_and_comparable() -> None:
    """It travels inside a persisted plan, so equality has to mean something."""
    first = resolve_row_identity(_table(("id", True)), SQLITE)
    second = RowIdentity(columns=("id",), locator=None)

    assert first == second
    assert len({first, second}) == 1
