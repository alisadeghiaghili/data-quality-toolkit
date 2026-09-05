"""What the UI tells people to expose (`VIZ-0`).

`docs/PLAN-VIZ-UI.md` §1.1: `dqt.ui.app`'s docstring showed the server being
started with ``uvicorn.run(app, host="0.0.0.0", port=8000)``. That binds every
interface on a machine, and the app it binds has **no authentication of any
kind**.

Read-only is not the same as harmless. What these endpoints return is schema
names, table names, column names and issue messages read out of whatever
database DQT was pointed at — which is to say, a map of a production schema
and a list of where its data is weakest. A schema listing is reconnaissance.

The guidance a tool ships is the configuration most of its users will run,
because a copyable one-liner in a docstring is where people start. So the
default has to be the safe one, and anything wider has to be a decision
someone makes deliberately, after the authentication that is not there yet.

This is a documentation test, which is unusual and deliberate. There is no
runtime behaviour to assert — DQT never calls ``uvicorn.run`` itself, so
nothing in the package binds anything. The advice *is* the artifact, and it
is the artifact that was wrong.
"""

from __future__ import annotations

import dqt.ui.app as app_module


def _docstring() -> str:
    """Return the module docstring under test.

    Returns:
        ``dqt.ui.app``'s docstring, which is never None.

    Example:
        assert "127.0.0.1" in _docstring()
    """
    return app_module.__doc__ or ""


class TestTheDocumentedWayToRunItIsLocalOnly:
    """The copyable example is the configuration most people will run."""

    def test_no_example_binds_every_interface(self) -> None:
        """``0.0.0.0`` on an unauthenticated app is the whole problem.

        Scoped to the lines that start a server rather than to the whole
        docstring. The first version of this test forbade the string
        anywhere, which the fix itself then failed: the clearest way to warn
        someone off ``0.0.0.0`` is to name it. Banning the word banned the
        warning too.

        Checked per line, so a second example added beside a corrected one
        still fails -- which is what the blunt version was protecting.
        """
        offending = [
            line for line in _docstring().splitlines() if "uvicorn" in line and "0.0.0.0" in line
        ]

        assert offending == [], offending

    def test_it_binds_the_loopback_address(self) -> None:
        """``127.0.0.1`` reaches only the machine the server runs on."""
        assert "127.0.0.1" in _docstring()

    def test_it_says_why_rather_than_only_what(self) -> None:
        """A changed number with no reason gets changed back.

        Someone hitting "why can't I reach this from my laptop" will widen
        the bind unless the docstring tells them what they would be exposing
        and what is missing before it is safe to.
        """
        text = _docstring().lower()

        assert "authentication" in text or "authenticated" in text

    def test_the_shell_example_is_local_too(self) -> None:
        """Two examples, one of which is safe, is not a safe default.

        The ``uvicorn`` command line defaults to ``127.0.0.1`` already, so
        this passes today — it is here so that adding ``--host`` later cannot
        quietly reintroduce the problem through the other example.
        """
        for line in _docstring().splitlines():
            if "uvicorn dqt.ui.app" in line:
                assert "--host" not in line or "127.0.0.1" in line


class TestTheAppItselfBindsNothing:
    """DQT never starts a server, and that should stay true.

    The package exposes an ASGI application object; choosing an address is
    the operator's job. A module that called ``uvicorn.run`` at import time,
    or shipped a ``__main__`` that did, would take that choice away.
    """

    def test_the_module_does_not_call_uvicorn(self) -> None:
        """No import-time or module-level server start."""
        import inspect

        source = inspect.getsource(app_module)
        code = "\n".join(line for line in source.splitlines() if not line.strip().startswith("*"))

        assert "uvicorn.run(" not in code.split('"""')[-1]
