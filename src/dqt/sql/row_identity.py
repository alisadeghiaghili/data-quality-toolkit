"""How cleansing addresses the rows it changes (NEW-M).

Cleansing used to locate rows with SQLite's ``rowid``, so every cleansing
entry point failed on PostgreSQL with ``UndefinedColumn``. ``DQT-08`` moved
identifier quoting, the read-only incantation and regex matching into the
dialects; row identity was missed because nothing exercised cleansing on a
second dialect.

The fix is not ``rowid`` to ``ctid``. A physical address moves when a row is
updated and can move under ``VACUUM FULL`` with no data change at all, while
a plan is applied and reverted in a *later* process -- so a stored plan
holding locators could address different rows than the ones it was reviewed
against. The plan fingerprint catches a data change; it cannot catch a
physical relocation. A physical address is also not what an audit log should
record: "I changed the row at disk position X" is not a statement anyone can
check afterwards.

So identity is the table's primary key where there is one, and a dialect
locator only where there is not and the dialect has one that is stable.

Example:
    from dqt.sql.row_identity import resolve_row_identity

    identity = resolve_row_identity(table, dialect)
    sql = f"UPDATE {t} SET {c} = ? WHERE {identity.where_clause(dialect)}"
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from dqt.sql.dialects.base import Dialect
from dqt.sql.schema_discovery import DiscoveredTable


@dataclass(frozen=True, slots=True)
class RowIdentity:
    """How one row of a particular table is named.

    Exactly one of the two is set. ``columns`` is the preferred form; a
    ``locator`` means the table had no primary key and the dialect offered a
    stable physical address instead.

    Attributes:
        columns: Primary-key column names, in key order.
        locator: Dialect physical-locator expression, or None when a key was
            found.

    Example:
        identity = RowIdentity(columns=("id",), locator=None)
    """

    columns: tuple[str, ...]
    locator: str | None

    def select_expressions(self, dialect: Dialect) -> list[str]:
        """Return the expressions that read this identity out of a row.

        Args:
            dialect: Dialect used to quote the key columns.

        Returns:
            One expression per identity component.

        Example:
            assert identity.select_expressions(dialect) == ['"id"']
        """
        raise NotImplementedError("select_expressions is specified but not implemented")

    def key_names(self) -> tuple[str, ...]:
        """Return the names this identity is recorded under in a log entry.

        Returns:
            The key-column names, or a single-element tuple naming the
            locator.

        Example:
            assert identity.key_names() == ("id",)
        """
        raise NotImplementedError("key_names is specified but not implemented")

    def where_clause(self, dialect: Dialect) -> str:
        """Return a parameterised predicate matching exactly this row.

        Values are bound, never interpolated. ``DQT-02`` parameterised rule
        literals for this reason, and a row key comes from user data just as
        a rule bound does.

        Args:
            dialect: Dialect supplying the bind placeholder and quoting.

        Returns:
            A predicate such as ``"tenant_id" = ? AND "id" = ?``.

        Example:
            assert identity.where_clause(dialect) == '"id" = ?'
        """
        raise NotImplementedError("where_clause is specified but not implemented")

    def bind_values(self, row_key: dict[str, Any]) -> tuple[Any, ...]:
        """Return the bind values for :meth:`where_clause`, in its order.

        Args:
            row_key: The identity recorded in a log entry.

        Returns:
            Values ordered to match the placeholders.

        Raises:
            KeyError: If *row_key* is missing part of the identity. Binding a
                missing component as None would match nothing, or match the
                wrong row.

        Example:
            assert identity.bind_values({"id": 42}) == (42,)
        """
        raise NotImplementedError("bind_values is specified but not implemented")


def resolve_row_identity(table: DiscoveredTable, dialect: Dialect) -> RowIdentity:
    """Decide how to address rows of *table* under *dialect*.

    Args:
        table: The discovered table, carrying its primary-key flags.
        dialect: Dialect that may offer a physical locator.

    Returns:
        The :class:`RowIdentity` to use.

    Raises:
        ValueError: If the table has no primary key and the dialect has no
            stable locator. Refusing names the real requirement -- give the
            table a primary key -- rather than silently addressing whatever
            now sits at a recorded position.

    Example:
        identity = resolve_row_identity(table, dialect)
    """
    raise NotImplementedError("resolve_row_identity is specified but not implemented")


__all__ = ["RowIdentity", "resolve_row_identity"]
