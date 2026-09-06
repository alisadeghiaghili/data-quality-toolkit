"""Referential integrity: counting rows whose foreign key points nowhere (`F2`).

The question this answers is about a database rather than a column: *are
there orders pointing at customers that no longer exist?* Nothing else in
DQT asks across two tables.

**A NULL foreign key is not an orphan.** A row with no reference references
nothing, which is a completeness question the null count already answers. A
row whose reference names a parent that does not exist is broken. Counting
the first as the second would inflate every orphan count on every nullable
foreign key in the database.

**Composite keys are compared whole.** Matching one column of a two-column
key and calling the row satisfied is a false clean bill of health, so every
column of the key joins at once.

**Cost.** One ``COUNT(*)`` over an anti-join per foreign key. Not batchable
the way column statistics are -- each key joins a different parent -- but
proportional to the number of keys, which is small, and no row is
materialised. The naive implementation of this check reads the parent keys
into a Python set and compares row by row; that is correct and unusable at
size, which is what `AGENTS.md` "Performance rules" forbids by name.

Example:
    orphans = count_orphans(connection_config, foreign_key)
"""

from __future__ import annotations

from dqt.common.models import ConnectionConfig
from dqt.sql.schema_discovery import DiscoveredForeignKey

__all__ = ["count_orphans", "orphan_count_sql"]


def orphan_count_sql(dialect: object, key: DiscoveredForeignKey) -> str:
    """Build the anti-join that counts rows whose reference is unmatched.

    Args:
        dialect: The dialect to quote identifiers with.
        key: The foreign key to check.

    Returns:
        A ``SELECT COUNT(*)`` statement.

    Example:
        sql = orphan_count_sql(dialect, key)
    """
    raise NotImplementedError


def count_orphans(connection_config: ConnectionConfig, key: DiscoveredForeignKey) -> int:
    """Count rows whose foreign key names a parent row that does not exist.

    Args:
        connection_config: Connection to read through. May be read-only.
        key: The foreign key to check.

    Returns:
        The number of orphaned rows. Rows whose key is NULL are excluded.

    Example:
        orphans = count_orphans(connection_config, key)
    """
    raise NotImplementedError
