"""
dqt.sql._connect
================

The single place a **user database** connection is ever opened (`DQT-08`).

Before this module there were two independent connection paths:
``rules._get_connection`` and ``schema_discovery.connect_sql``. They used
different PostgreSQL drivers (``psycopg2`` and ``psycopg``), and only the
first honoured ``ConnectionConfig.read_only`` at all â€” ``connect_sql``
contained no reference to the flag, so schema discovery and profiling opened
writable connections no matter what the configuration said. Nothing exploited
that (both paths only ever issued ``SELECT``), but it meant `DQT-03`'s
read-only enforcement was a property of one helper rather than of the
codebase.

Not in scope, deliberately. :meth:`dqt.common.storage.RunStore._connect`
opens DQT's **own** results database, which must stay writable. The roadmap's
`DQT-08` body excludes it by name and so does this module.

Compatibility with the still-open two-connection question. The owner has an
open proposal to give DQT two separately-credentialed connections, one
read-only and one writable. Consolidating on a single
:func:`get_connection` today is not a vote against that: if it is adopted,
this module gains a sibling ``get_write_connection`` beside the existing
function. One function per role, in one module, is the shape either
resolution wants.
"""

from __future__ import annotations
import warnings
from typing import Any
from dqt.common.models import ConnectionConfig
from dqt.sql.dialects import Dialect, ReadOnlyEnforcement, get_dialect


def get_connection(connection_config: ConnectionConfig) -> Any:
    """Open a connection to the user database described by *connection_config*.

    The dialect is resolved from the DSN and asked to open the connection, so
    the read-only incantation is whichever one that database actually
    supports rather than a branch written here.

    Where a dialect cannot enforce read-only at the driver or server â€” today
    only SQL Server, whose
    :attr:`~dqt.sql.dialects.base.ReadOnlyEnforcement.ADVISORY` value says so
    â€” a :class:`RuntimeWarning` is emitted for a ``read_only=True``
    connection. Opening it silently would let a caller believe it had a
    guarantee DQT cannot give on that database.

    Args:
        connection_config: Validated connection configuration. Its
            ``read_only`` flag defaults to ``True``.

    Returns:
        An open DBAPI 2.0 connection. The caller owns it and must close it.

    Raises:
        ValueError: If the DSN names no supported dialect.
        ImportError: If the resolved dialect's driver is not installed.

    Example:
        from dqt.common.models import ConnectionConfig

        config = ConnectionConfig(id="t", dsn="sqlite:///:memory:")
        connection = get_connection(config)
        connection.close()
    """
    raise NotImplementedError("get_connection is specified but not implemented yet")


def get_dialect_for(connection_config: ConnectionConfig) -> Dialect:
    """Resolve the dialect for a connection configuration.

    A one-line convenience over :func:`~dqt.sql.dialects.get_dialect`, so a
    caller that holds a :class:`~dqt.common.models.ConnectionConfig` does not
    have to reach into its ``dsn`` attribute to find out which database it is
    talking to.

    Args:
        connection_config: Validated connection configuration.

    Returns:
        The shared dialect instance for that configuration's DSN.

    Raises:
        ValueError: If the DSN names no supported dialect.

    Example:
        from dqt.common.models import ConnectionConfig

        config = ConnectionConfig(id="t", dsn="sqlite:///:memory:")
        assert get_dialect_for(config).name == "sqlite"
    """
    raise NotImplementedError("get_dialect_for is specified but not implemented yet")


__all__ = ["ReadOnlyEnforcement", "get_connection", "get_dialect_for"]
