"""
dqt.exceptions
==============

DQT's exception hierarchy, rooted in :class:`DQTError` (`DQT-09`).

Every exception DQT raises for a condition of its own descends from
:class:`DQTError`, so a caller can ask the one question that matters in a
scheduled job: *did DQT fail, or did Python?* Before this, every module
raised built-in ``ValueError`` and ``ImportError``, and there was no way to
tell a data-quality condition from a bug in the calling script.

Every type here **also inherits the built-in it replaced**. A caller catching
``ValueError`` around :func:`dqt.sql.cleansing.cleanse_apply` keeps working,
and a caller catching :class:`DQTError` starts working. Without that, making
the types more specific would be a breaking change dressed as a minor: an
exception type is as much a part of the public surface as a signature.

What is deliberately **not** here: argument errors. A score outside ``[0, 1]``
handed to :func:`dqt.viz.score_bar` stays a plain ``ValueError``, because a
caller passing a percentage where a ratio was wanted has a bug in their code,
not a data-quality condition to handle.

The hierarchy::

    DQTError
    +-- ConfigurationError          -- something in the configuration is wrong
    |   +-- ConnectionConfigError   -- specifically, the connection settings
    +-- RuleEvaluationError         -- a rule could not be compiled or run
    +-- CleansingError              -- a cleansing plan could not be applied
    +-- ReadOnlyViolationError      -- a write was attempted through a read-only connection

Example:
    try:
        pipeline.run()
    except DQTError:
        alert()
"""

from __future__ import annotations


class DQTError(Exception):
    """Base class for every error DQT raises for a condition of its own.

    Catching this separates a DQT failure from a bug in the calling code,
    which is the distinction a scheduled job needs in order to decide
    whether to alert.

    Example:
        try:
            pipeline.run()
        except DQTError:
            alert()
    """


class ConfigurationError(DQTError, ValueError):
    """Raised when DQT's configuration is wrong or self-contradictory.

    A configuration error is not a data-quality finding, which is why the
    CLI maps it to exit code 3 rather than 1: exiting 1 would tell a CI job
    that the data has problems when the truth is that the run never
    happened. That confusion was `NEW-V`.

    Also inherits ``ValueError``, which these conditions raised before
    `DQT-09`.

    Example:
        raise ConfigurationError("rule file names no rules")
    """


class ConnectionConfigError(ConfigurationError):
    """Raised when the connection settings cannot be used.

    An unsupported DSN scheme, a DSN naming no host or no database, or a
    driver that is not installed. Narrower than
    :class:`ConfigurationError` so a caller can single out "I cannot reach
    the database" from "this config file is wrong", and still catch both
    with the parent.

    Example:
        raise ConnectionConfigError("unsupported DSN scheme 'mysql'")
    """


class RuleEvaluationError(DQTError, ValueError):
    """Raised when a rule cannot be compiled into SQL or evaluated.

    A regex rule with no pattern, a range rule with neither bound, or a rule
    whose expression the dialect cannot express -- `regex` on SQL Server,
    which has no regular-expression operator and is refused rather than
    reported as zero violations.

    Also inherits ``ValueError``, which these conditions raised before
    `DQT-09`.

    Example:
        raise RuleEvaluationError("regex rule requires params.pattern")
    """


class CleansingError(DQTError, ValueError):
    """Raised when a cleansing plan cannot be applied or undone.

    The plan lifecycle is where a caller most needs to branch: an unknown
    plan id is a mistake in the calling code, while "the data drifted since
    this plan was computed" is a real condition to handle by re-planning.
    Both are cleansing failures and neither is a Python argument error.

    Also inherits ``ValueError``, which these conditions raised before
    `DQT-09`.

    Example:
        raise CleansingError("the data changed since the plan was computed")
    """


class ReadOnlyViolationError(DQTError):
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


__all__ = [
    "CleansingError",
    "ConfigurationError",
    "ConnectionConfigError",
    "DQTError",
    "ReadOnlyViolationError",
    "RuleEvaluationError",
]
