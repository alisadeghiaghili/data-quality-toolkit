"""
dqt.exceptions
==============

Exception types raised by DQT.

This module currently defines a single exception, introduced for `DQT-03`'s
read-only enforcement. A package-wide exception hierarchy is a separate,
larger effort (`DQT-09`) that depends on `DQT-05`. When that hierarchy lands,
:class:`ReadOnlyViolationError` should become a subclass of whatever common
base class it introduces, without changing its name, its module path, or the
``except ReadOnlyViolationError`` call sites that already depend on it. Placing
it here now, rather than inline in ``sql/cleansing.py``, means that future
change is a one-line base-class edit rather than an import-path migration
across every caller.
"""

from __future__ import annotations


class ReadOnlyViolationError(Exception):
    """Raised when a mutating operation is attempted on a read-only connection.

    Two independent call sites can raise this:

    * :func:`dqt.sql.cleansing.apply_cleansing`, before opening a connection
      or building any mutating SQL statement, when its
      :class:`~dqt.common.models.ConnectionConfig` has ``read_only=True``.

    This is deliberately a plain check performed in application code, in
    addition to (not instead of) the connection-layer enforcement in
    :func:`dqt.sql.rules._get_connection`, which opens SQLite in
    ``mode=ro`` and sets PostgreSQL sessions to
    ``TRANSACTION READ ONLY`` so a write fails at the driver level even if
    this check were ever bypassed.

    Example::

        from dqt.common.models import ConnectionConfig
        from dqt.exceptions import ReadOnlyViolationError
        from dqt.sql.cleansing import CleansingConfig, apply_cleansing

        conn_cfg = ConnectionConfig(id="dev", dsn="sqlite:///dev.db", read_only=True)
        try:
            apply_cleansing(run_id="run-001", connection_config=conn_cfg, configs=[])
        except ReadOnlyViolationError as exc:
            print(exc)  # "Connection 'dev' has read_only=True; apply_cleansing() refuses ..."
    """
