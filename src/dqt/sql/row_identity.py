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
        if self.locator is not None:
            return [self.locator]
        return [dialect.quote_identifier(column) for column in self.columns]

    def key_names(self) -> tuple[str, ...]:
        """Return the names this identity is recorded under in a log entry.

        Returns:
            The key-column names, or a single-element tuple naming the
            locator.

        Example:
            assert identity.key_names() == ("id",)
        """
        return (self.locator,) if self.locator is not None else self.columns

    def order_by_expressions(self, dialect: Dialect) -> list[str]:
        """Return the ordering that makes this identity pageable.

        Args:
            dialect: Dialect used to quote the key columns.

        Returns:
            One ordering term per identity component, in key order.

        Example:
            assert identity.order_by_expressions(dialect) == ['"id"']
        """
        raise NotImplementedError

    def after_clause(self, dialect: Dialect) -> str:
        """Return a predicate matching rows ordered after a given one.

        Args:
            dialect: Dialect supplying the bind placeholder and quoting.

        Returns:
            A predicate such as ``("id" > ?)``.

        Example:
            assert identity.after_clause(dialect) == '("id" > ?)'
        """
        raise NotImplementedError

    def after_bind_values(self, row_key: dict[str, Any]) -> tuple[Any, ...]:
        """Return the bind values for :meth:`after_clause`, in its order.

        Args:
            row_key: The identity of the last row of the previous page.

        Returns:
            Values ordered to match the placeholders.

        Example:
            assert identity.after_bind_values({"id": 42}) == (42,)
        """
        raise NotImplementedError

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
        placeholder = dialect.parameter_placeholder
        if self.locator is not None:
            return f"{self.locator} = {placeholder}"
        return " AND ".join(
            f"{dialect.quote_identifier(column)} = {placeholder}" for column in self.columns
        )

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
        return tuple(row_key[name] for name in self.key_names())


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
    key_columns = tuple(column.column_name for column in table.columns if column.is_primary_key)
    if key_columns:
        return RowIdentity(columns=key_columns, locator=None)

    locator = dialect.physical_row_locator
    if locator is None:
        raise ValueError(
            f"Table {table.table_name!r} has no primary key, and the "
            f"{dialect.name!r} dialect has no row locator stable enough to "
            "substitute for one. Cleansing addresses rows so it can undo "
            "them later, and a physical address that moves under an UPDATE "
            "or a VACUUM would make a stored plan edit the wrong rows. Add a "
            "primary key to the table."
        )
    return RowIdentity(columns=(), locator=locator)


__all__ = ["RowIdentity", "resolve_row_identity"]
