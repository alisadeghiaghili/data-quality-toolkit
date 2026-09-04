"""
dqt.sql.dialects
================

The single authority for everything that varies by database.

Before this package, dialect-specific SQL was scattered: ``schema_discovery``
branched on SQLite versus PostgreSQL inline, ``rules`` carried its own
``dialect in ("postgresql", "postgres")`` test, and ``_identifiers`` held a
quote-character table that knew nothing about the dialects it was quoting
for. Adding a third database to that shape would have tripled the number of
places to change. Everything that differs now lives behind one protocol, and
no module outside this package may branch on which database is in use.

Layering. This package is the adapter layer: it may import
``dqt.common.models`` and it may import database drivers, always lazily and
inside the method that needs one. It must never import from the domain
modules that call it (``rules``, ``cleansing``, ``profiling``,
``schema_discovery``), and those modules must reach the database only through
a dialect and through :func:`dqt.sql._connect.get_connection`.

Public surface::

    from dqt.sql.dialects import get_dialect, get_dialect_by_name
    from dqt.sql.dialects import SQLITE, POSTGRESQL, SQLSERVER
    from dqt.sql.dialects import ColumnMetadata, Dialect, ReadOnlyEnforcement
"""

from __future__ import annotations

from dqt.sql.dialects.base import ColumnMetadata, Dialect, ReadOnlyEnforcement
from dqt.sql.dialects.postgresql import POSTGRESQL
from dqt.sql.dialects.sqlite import SQLITE
from dqt.sql.dialects.sqlserver import SQLSERVER

# DSN scheme prefixes, in the order they are tested, mapped to the dialect
# they select. Prefix matching (rather than a strict "scheme://" parse) is
# deliberate: it preserves exactly the behaviour the pre-DQT-08 dialect
# detection had, where "sqlite:///x.db" and "sqlite://x.db" both resolve.
_DSN_PREFIXES: tuple[tuple[tuple[str, ...], Dialect], ...] = (
    (("sqlite",), SQLITE),
    (("postgresql", "postgres"), POSTGRESQL),
    (("mssql", "sqlserver"), SQLSERVER),
)

_DIALECTS_BY_NAME: dict[str, Dialect] = {
    SQLITE.name: SQLITE,
    POSTGRESQL.name: POSTGRESQL,
    SQLSERVER.name: SQLSERVER,
}

#: Canonical names of every dialect DQT supports, in DSN-resolution order.
SUPPORTED_DIALECT_NAMES: tuple[str, ...] = tuple(_DIALECTS_BY_NAME)


def get_dialect(dsn: str) -> Dialect:
    """Resolve the dialect a DSN names.

    This is the only place a DSN is inspected to decide which database is on
    the other end. Callers pass the resulting dialect around rather than
    re-deriving it, so a DSN is parsed once per run, not once per query.

    Args:
        dsn: A DQT connection string, e.g. ``"sqlite:///dev.db"``,
            ``"postgresql://user:pw@host/db"``, or ``"mssql://sa@host/db"``.
            The ``postgres://`` and ``sqlserver://`` aliases are accepted and
            resolve to the same dialects as their canonical spellings.

    Returns:
        The shared, stateless dialect instance for that database.

    Raises:
        ValueError: If no supported dialect matches the DSN. The message
            names the DSN so a typo is visible.

    Example:
        assert get_dialect("sqlite:///dev.db").name == "sqlite"
        assert get_dialect("postgres://u:p@h/db").name == "postgresql"
        assert get_dialect("mssql://sa@h/db").name == "sqlserver"
    """
    normalised = dsn.strip()
    for prefixes, dialect in _DSN_PREFIXES:
        if normalised.startswith(prefixes):
            return dialect
    schemes = [prefix for prefixes, _ in _DSN_PREFIXES for prefix in prefixes]
    raise ValueError(
        f"Cannot detect a supported dialect from DSN: {dsn!r}. "
        f"Supported schemes: {', '.join(schemes)}."
    )


def get_dialect_by_name(name: str) -> Dialect:
    """Resolve a dialect by its canonical name.

    Args:
        name: One of :data:`SUPPORTED_DIALECT_NAMES`. The historical alias
            ``"postgres"`` is accepted for ``"postgresql"``, because rule
            evaluation used to pass that spelling around as a bare string.

    Returns:
        The shared, stateless dialect instance with that name.

    Raises:
        ValueError: If *name* is not a supported dialect name.

    Example:
        assert get_dialect_by_name("sqlserver").parameter_placeholder == "?"
    """
    if name == "postgres":
        return POSTGRESQL
    try:
        return _DIALECTS_BY_NAME[name]
    except KeyError as exc:
        raise ValueError(
            f"Unsupported dialect name: {name!r}. Supported: {', '.join(SUPPORTED_DIALECT_NAMES)}."
        ) from exc


__all__ = [
    "POSTGRESQL",
    "SQLITE",
    "SQLSERVER",
    "SUPPORTED_DIALECT_NAMES",
    "ColumnMetadata",
    "Dialect",
    "ReadOnlyEnforcement",
    "get_dialect",
    "get_dialect_by_name",
]
