"""
Entry point for ``python -m dqt``.

Allows the package to be invoked directly::

    python -m dqt profile --dsn sqlite:///mydb.db
"""

from dqt.cli import main

main()
