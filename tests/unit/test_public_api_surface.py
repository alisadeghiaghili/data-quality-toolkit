"""What DQT promises not to break (API freeze, 1.0.0 gate).

For a library, `1.0.0` is a commitment not to break the public API. That
commitment is only meaningful if the surface is *decided* rather than
inherited: whatever happens to be importable on the day of the release
otherwise becomes the promise.

Two things are pinned here.

**The top-level surface**, exactly. Equality rather than containment, so a
name added by accident fails as loudly as a name removed on purpose. Adding
to a frozen API is cheap and removing from it is expensive, which is exactly
why additions should be deliberate.

**That modules do not leak their imports.** A module without ``__all__``
re-exports everything it imported, so ``dqt.sql.cleansing`` advertised
``quote_identifier``, ``discover_schema`` and ``get_connection`` -- none of
which are cleansing's API, all of which a caller could have come to depend
on. Freezing that would have frozen accidents.

See ``docs/API-STABILITY.md`` for what the promise is and how something
leaves the surface once it is in it.
"""

from __future__ import annotations

import importlib

import pytest

import dqt

#: Everything importable from ``dqt`` itself. Copied here deliberately rather
#: than read from the package: a test that derives its expectation from the
#: thing under test cannot detect a change in it.
TOP_LEVEL_API = {
    # Version
    "__version__",
    # Entry points
    "DQTPipeline",
    "from_dsn",
    "from_yaml_config",
    # Configuration
    "ConnectionConfig",
    "DQPipelineConfig",
    "RuleConfig",
    "RuleScope",
    "SamplingConfig",
    "load_connection",
    "load_pipeline",
    "load_rules",
    "load_rules_from_files",
    # Results
    "PipelineResult",
    "SchemaResult",
    "TableResult",
    "ColumnResult",
    "DQMetric",
    "DQIssue",
    "Rule",
    "RuleResult",
    "RuleRunResult",
    "StageError",
    # Vocabulary
    "DQDimension",
    "IssueSeverity",
    "RuleStatus",
    "RunStatus",
    "SemanticType",
    # Classification
    "ClassificationResult",
    "classify_column",
    "classify_column_name",
    "classify_value",
    "normalize_persian_text",
    # Failure and CI gating
    "ReadOnlyViolationError",
    "ExitCode",
    "FAIL_ON_CHOICES",
    "decide_exit_code",
}

#: Modules whose own ``__all__`` is part of the promise. Reaching one level
#: down is deliberate for these: cleansing writes, so ``Q1`` wants the reach
#: to be an act rather than an import that happens to be at hand.
SUBMODULE_API = {
    "dqt.sql.cleansing": {
        "CleansingConfig",
        "CleansingLog",
        "CleansingPlan",
        "CleansingResult",
        "apply_cleansing",
        "cleanse_apply",
        "cleanse_plan",
        "revert",
    },
    "dqt.bridges": {"ColumnMissingness", "MissingnessBridge", "MissingnessReport"},
    "dqt.common.storage": {"RunStore"},
    "dqt.exceptions": {"ReadOnlyViolationError"},
    "dqt.exit_codes": {"ExitCode", "FAIL_ON_CHOICES", "decide_exit_code"},
}


def test_the_top_level_surface_is_exactly_what_is_promised() -> None:
    """No name appears or disappears without this test saying so.

    Equality, not a subset check. A name added by accident is as much a
    problem as one removed on purpose: additions to a frozen API are cheap to
    make and expensive to undo, so they should be a decision rather than a
    side effect of an import.
    """
    assert set(dqt.__all__) == TOP_LEVEL_API


def test_everything_promised_is_actually_importable() -> None:
    """``__all__`` is a claim, and this is what backs it.

    A name listed but absent turns ``from dqt import X`` into an
    ImportError at the caller, which is a broken promise rather than a
    missing feature.
    """
    missing = [name for name in dqt.__all__ if not hasattr(dqt, name)]

    assert missing == []


@pytest.mark.parametrize("module_name", sorted(SUBMODULE_API))
def test_submodules_declare_their_own_surface(module_name: str) -> None:
    """Each supported submodule says what it offers, and offers exactly that."""
    module = importlib.import_module(module_name)

    assert hasattr(module, "__all__"), f"{module_name} must declare __all__"
    assert set(module.__all__) == SUBMODULE_API[module_name]


def test_no_module_leaks_its_imports_as_public_api() -> None:
    """A module's surface is what it declares, not what it happened to import.

    Without ``__all__`` every imported name becomes part of the apparent API.
    ``dqt.sql.cleansing`` advertised ``quote_identifier``, ``discover_schema``
    and ``get_connection`` this way -- none of them cleansing's to promise,
    and all of them things a caller could have come to rely on before anyone
    noticed.

    The rule checked here is narrow and mechanical: every module that is part
    of the promise declares ``__all__``, so the surface is a decision rather
    than a consequence.
    """
    undeclared = [
        name
        for name in ["dqt", *SUBMODULE_API]
        if not hasattr(importlib.import_module(name), "__all__")
    ]

    assert undeclared == []


def test_private_modules_are_named_as_private() -> None:
    """Anything a caller should not import is spelled with a leading underscore.

    ``_connect`` and ``_identifiers`` hold real machinery that other modules
    use. The underscore is the only signal a Python caller gets, so it has to
    be there rather than relying on a doc nobody reads.
    """
    internal = ("dqt.sql._connect", "dqt.sql._identifiers")

    for module_name in internal:
        importlib.import_module(module_name)
        assert module_name.rsplit(".", 1)[-1].startswith("_")


class TestTheResultTypesAreReachable:
    """A caller who receives an object must be able to name its type.

    This is the gap that motivated the audit: ``PipelineResult.stage_errors``
    hands back ``StageError`` objects, and there was no way to import
    ``StageError``. A caller could read the attributes but could not annotate
    a function that takes one, or catch it in a match statement.
    """

    def test_stage_error_is_importable(self) -> None:
        """Returned by every run, so it belongs in the surface."""
        from dqt import PipelineResult, StageError

        assert "stage_errors" in PipelineResult.__annotations__
        assert StageError.__name__ == "StageError"

    def test_the_exit_code_contract_is_importable(self) -> None:
        """A CI gate is scripted against these, so they cannot be internal.

        ``DQT-06`` made the exit code a contract; a contract a caller cannot
        import is one they have to hardcode, and hardcoded numbers drift.
        """
        from dqt import FAIL_ON_CHOICES, ExitCode, decide_exit_code

        assert ExitCode.SUCCESS == 0
        assert "error" in FAIL_ON_CHOICES
        assert callable(decide_exit_code)

    def test_the_error_callers_must_catch_is_importable(self) -> None:
        """``ReadOnlyViolationError`` is raised at users, so they need the name.

        Catching it by string match on the message would be the alternative,
        and that is not an API.
        """
        from dqt import ReadOnlyViolationError

        assert issubclass(ReadOnlyViolationError, Exception)
