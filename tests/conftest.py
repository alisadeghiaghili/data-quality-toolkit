"""
Shared pytest fixtures for the DQT test suite.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path

import pytest


@pytest.fixture
def make_sqlite_db(tmp_path: Path) -> Callable[[str, str], Path]:
    """Factory fixture: build a SQLite file DB from a DDL/DML script.

    Returns a callable that creates ``tmp_path / filename``, executes
    *script* against it, and returns the resulting file path.

    Example::

        def test_something(make_sqlite_db):
            db_file = make_sqlite_db("orders.db", '''
                CREATE TABLE orders (id INTEGER PRIMARY KEY, amount REAL);
                INSERT INTO orders VALUES (1, 100.0);
            ''')
    """

    def _make(filename: str, script: str) -> Path:
        db_file = tmp_path / filename
        conn = sqlite3.connect(str(db_file))
        try:
            conn.executescript(script)
            conn.commit()
        finally:
            conn.close()
        return db_file

    return _make
