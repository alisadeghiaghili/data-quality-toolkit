"""Everything a user can reach explains itself (`v0.9`).

The freeze candidate's acceptance names three surfaces: every symbol in
`dqt.__all__`, every CLI flag, and every `dqt.ui.api` endpoint has
documentation backed by a passing test.

`tools/doc_audit.py` already checks every *definition* under `src/dqt`. This
checks the *surfaces*, which is a different question and catches two things
the audit cannot:

* **A re-exported name.** `dqt.__all__` promises names whose definitions live
  elsewhere. The audit checks the definition; nothing checked that the
  promise resolves to it.
* **CLI help text.** ``--fail-on`` is documentation a user reads far more
  often than any docstring, and it is an `argparse` keyword rather than a
  docstring, so the audit never sees it.

The point of freezing an API is that people build on it. A frozen surface
with an undocumented corner freezes the confusion too.
"""

from __future__ import annotations

import argparse
import inspect

import pytest

import dqt
from dqt.cli import _build_parser


def _documented(obj: object) -> bool:
    """Return whether *obj* carries a non-trivial docstring.

    Args:
        obj: The object to check.

    Returns:
        True when it has a docstring of more than a few characters.

    Example:
        assert _documented(dqt.DQTPipeline)
    """
    text = inspect.getdoc(obj)
    return bool(text and len(text.strip()) > 10)


class TestEveryExportedSymbolExplainsItself:
    """`dqt.__all__` is the promise; this is what stands behind each name."""

    @pytest.mark.parametrize("name", sorted(dqt.__all__))
    def test_the_symbol_resolves(self, name: str) -> None:
        """A name in ``__all__`` that does not resolve is a broken promise.

        It surfaces at the caller as an ImportError on a documented name,
        which reads as DQT being broken rather than as a typo in a list.
        """
        assert hasattr(dqt, name), f"dqt.__all__ promises {name!r} and dqt has no such attribute"

    @pytest.mark.parametrize("name", sorted(dqt.__all__))
    def test_the_symbol_is_documented(self, name: str) -> None:
        """Freezing an undocumented name freezes the confusion with it.

        Type aliases and the version string are exempt: a ``Literal`` of six
        dimension names documents itself by being read, and there is nowhere
        on a ``str`` to put a docstring.
        """
        value = getattr(dqt, name)
        if isinstance(value, str) or not (inspect.isclass(value) or inspect.isfunction(value)):
            pytest.skip(f"{name} is a value or alias, not something with a docstring")

        assert _documented(value), f"dqt.{name} has no usable docstring"


class TestEveryCommandLineFlagExplainsItself:
    """Help text is the documentation a user reads most and audits least."""

    def _actions(self) -> list[argparse.Action]:
        """Return every flag the CLI defines, across subcommands.

        Returns:
            The argparse actions, excluding the automatic ``-h``.

        Example:
            assert self._actions()
        """
        parser = _build_parser()
        found: list[argparse.Action] = []
        for action in parser._actions:  # noqa: SLF001
            if isinstance(action, argparse._SubParsersAction):  # noqa: SLF001
                for subparser in action.choices.values():
                    found.extend(subparser._actions)  # noqa: SLF001
            else:
                found.append(action)
        return [action for action in found if not isinstance(action, argparse._HelpAction)]  # noqa: SLF001

    def test_the_cli_defines_flags_at_all(self) -> None:
        """Guards the two tests below from passing over an empty list.

        A parser that failed to build would make "every flag is documented"
        vacuously true, which is the failure mode of every test that iterates.
        """
        assert len(self._actions()) >= 5

    def test_every_flag_has_help_text(self) -> None:
        """``argparse`` prints an empty column rather than complaining.

        So a flag with no help is invisible in ``--help`` and looks like a
        flag that does not exist.
        """
        undocumented = [action.dest for action in self._actions() if not action.help]

        assert undocumented == [], f"flags with no help text: {undocumented}"

    def test_every_choice_bounded_flag_lists_its_choices(self) -> None:
        """A flag with a closed set must say what the set is.

        ``--fail-on`` decides whether CI goes red, and guessing at its values
        is guessing at a gate.
        """
        for action in self._actions():
            if action.choices is not None:
                rendered = str(action.help or "")
                assert any(str(choice) in rendered for choice in action.choices), (
                    f"{action.dest} has choices {list(action.choices)} "
                    "and names none of them in its help"
                )


class TestEveryReadApiEndpointExplainsItself:
    """`dqt.ui.api` is the one path every UI consumer goes through."""

    def _public_functions(self) -> list[tuple[str, object]]:
        """Return the module's public functions.

        Returns:
            ``(name, function)`` pairs, underscored names excluded.

        Example:
            assert self._public_functions()
        """
        import dqt.ui.api as api

        return [
            (name, value)
            for name, value in vars(api).items()
            if inspect.isfunction(value)
            and not name.startswith("_")
            and value.__module__ == api.__name__
        ]

    def test_the_module_exposes_functions(self) -> None:
        """The same guard against iterating over nothing."""
        assert len(self._public_functions()) >= 5

    def test_every_function_is_documented(self) -> None:
        """A UI reads through here, so an undocumented reader is a guess."""
        undocumented = [
            name for name, function in self._public_functions() if not _documented(function)
        ]

        assert undocumented == [], f"undocumented api functions: {undocumented}"

    def test_every_function_says_what_it_returns(self) -> None:
        """The shape of the dict is the contract.

        These return plain dicts by design, so a caller has no type to read
        and the docstring is the only place the keys are named.
        """
        missing = [
            name
            for name, function in self._public_functions()
            if "Returns:" not in (inspect.getdoc(function) or "")
        ]

        assert missing == [], f"api functions with no Returns section: {missing}"
