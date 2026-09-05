"""Connection wrappers that record the SQL run through them.

Shared by the cost tests, which measure what DQT asks the database rather
than how long it takes. A query count is deterministic where a wall-clock
budget is not, and it is the thing that actually scales badly -- the costs
worth gating here grow with schema width and rule count, and counting round
trips measures exactly that.

Example:
    connection = CountingConnection(sqlite3.connect(":memory:"))
    connection.execute("SELECT 1")
    assert len(connection.statements) == 1
"""

from __future__ import annotations

from typing import Any


class CountingCursor:
    """A cursor that records every statement executed through it.

    Attributes:
        statements: Every statement seen, in order.

    Example:
        cursor = CountingCursor(real_cursor, statements)
    """

    def __init__(self, inner: Any, statements: list[str]) -> None:
        """Wrap *inner*, appending each statement to *statements*.

        Args:
            inner: The real DBAPI cursor.
            statements: Shared list to append to.

        Example:
            CountingCursor(connection.cursor(), [])
        """
        self._inner = inner
        self.statements = statements

    def execute(self, statement: str, *args: Any, **kwargs: Any) -> Any:
        """Record and forward a statement.

        Args:
            statement: SQL to run.
            *args: Passed through.
            **kwargs: Passed through.

        Returns:
            Whatever the wrapped cursor returns.

        Example:
            cursor.execute("SELECT 1")
        """
        self.statements.append(statement)
        return self._inner.execute(statement, *args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        """Forward everything else to the wrapped cursor.

        Args:
            name: Attribute being looked up.

        Returns:
            The wrapped cursor's attribute.

        Example:
            rows = cursor.fetchall()
        """
        return getattr(self._inner, name)


class CountingConnection:
    """A connection that records every statement run against it.

    Attributes:
        statements: Every statement seen, in order.

    Example:
        connection = CountingConnection(real_connection)
    """

    def __init__(self, inner: Any) -> None:
        """Wrap *inner* and start an empty statement log.

        Args:
            inner: The real DBAPI connection.

        Example:
            CountingConnection(sqlite3.connect(":memory:"))
        """
        self._inner = inner
        self.statements: list[str] = []

    def execute(self, statement: str, *args: Any, **kwargs: Any) -> Any:
        """Record and forward a statement.

        Args:
            statement: SQL to run.
            *args: Passed through.
            **kwargs: Passed through.

        Returns:
            Whatever the wrapped connection returns.

        Example:
            connection.execute("SELECT 1")
        """
        self.statements.append(statement)
        return self._inner.execute(statement, *args, **kwargs)

    def cursor(self) -> CountingCursor:
        """Return a cursor that shares this connection's statement log.

        Returns:
            A CountingCursor.

        Example:
            cursor = connection.cursor()
        """
        return CountingCursor(self._inner.cursor(), self.statements)

    def __getattr__(self, name: str) -> Any:
        """Forward everything else to the wrapped connection.

        Args:
            name: Attribute being looked up.

        Returns:
            The wrapped connection's attribute.

        Example:
            connection.close()
        """
        return getattr(self._inner, name)
