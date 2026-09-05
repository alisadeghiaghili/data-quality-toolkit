"""The config file a user writes is part of the frozen API (`v1.0`).

`docs/PROPOSAL-v1.0-roadmap.md` §1 says the compatibility promise covers more
than the export list: it covers the CLI's flags and exit codes, and **the
config-file schema `dqt` accepts**. That last one had nothing checking it.

It is the surface a user touches most and the one they can least easily
change. A Python caller who hits a renamed keyword argument sees a
`TypeError` at the call site; a DBA whose `connection.yaml` stopped being
accepted sees a run fail at 3am with a validation error about a file they
wrote months ago and have not opened since.

So the accepted keys are written out here by hand, exactly as
``tests/unit/test_public_api_surface.py`` writes out `dqt.__all__` and for
the same reason: a test that derives its expectation from the thing under
test cannot detect a change in it.

**Asserted by equality.** A *new* key is as much a decision as a removed one.
Adding one is cheap and reversing it after a release is not, so it should be
a line in this file rather than a side effect of adding a field.
"""

from __future__ import annotations

import pytest

from dqt.common.models import (
    ConnectionConfig,
    DQPipelineConfig,
    RuleConfig,
    RuleScope,
    SamplingConfig,
)

#: Every key DQT accepts in a config file, by the model that reads it.
#:
#: Copied here deliberately rather than read from the models.
FROZEN_CONFIG_SCHEMA: dict[str, set[str]] = {
    "ConnectionConfig": {"id", "dsn", "read_only", "ssl"},
    "DQPipelineConfig": {
        "connection_id",
        "include_schemas",
        "exclude_schemas",
        "include_tables",
        "exclude_tables",
        "sampling",
        "metric_thresholds",
        "rule_files",
    },
    "SamplingConfig": {"strategy", "limit", "seed"},
    "RuleConfig": {"name", "dimension", "severity", "scope", "expression", "params"},
    "RuleScope": {"schema_pattern", "table_pattern", "column_pattern"},
}

_MODELS = {
    "ConnectionConfig": ConnectionConfig,
    "DQPipelineConfig": DQPipelineConfig,
    "SamplingConfig": SamplingConfig,
    "RuleConfig": RuleConfig,
    "RuleScope": RuleScope,
}


class TestTheAcceptedKeysAreExactlyWhatIsPromised:
    """A config that worked on 1.0 works on every 1.x."""

    @pytest.mark.parametrize("model_name", sorted(FROZEN_CONFIG_SCHEMA))
    def test_the_model_accepts_exactly_the_frozen_keys(self, model_name: str) -> None:
        """Equality, so an addition is as visible as a removal.

        The failure message names the difference in both directions, because
        "the schema changed" without saying how is a message that sends
        someone to read a diff.
        """
        actual = set(_MODELS[model_name].model_fields)
        expected = FROZEN_CONFIG_SCHEMA[model_name]

        assert actual == expected, (
            f"{model_name}: added {sorted(actual - expected)}, removed {sorted(expected - actual)}"
        )

    def test_every_frozen_model_is_covered(self) -> None:
        """The list of models is itself part of the promise.

        A new config model could be added and documented and never appear
        here, which would freeze four shapes and leave the fifth free to
        move.
        """
        assert set(_MODELS) == set(FROZEN_CONFIG_SCHEMA)


class TestAnUnknownKeyIsRefusedRatherThanIgnored:
    """A typo in a config file must not pass as a default."""

    def test_a_misspelled_key_is_an_error(self) -> None:
        """An ignored key is a config that says something DQT never read.

        pydantic ignores unknown keys by default, so ``exclude_tabels`` parses
        cleanly and DQT profiles every table the author meant to skip --
        including, on a production database, the one they were most careful
        to name.

        ``read_only`` is the reassuring case rather than the representative
        one: its default is already ``True``, so misspelling it fails safe.
        Every other key fails in the direction of doing more than was asked.
        """
        with pytest.raises(Exception, match="exclude_tabels|extra"):
            DQPipelineConfig(connection_id="c", exclude_tabels=["secrets"])  # type: ignore[call-arg]

    def test_a_correct_config_is_accepted(self) -> None:
        """The control: the refusal above is about the typo, not about strictness."""
        config = ConnectionConfig(id="c", dsn="sqlite:///x.db", read_only=True)

        assert config.read_only is True


class TestTheDefaultsAreFrozenToo:
    """A default is what a config that omits a key means."""

    def test_a_connection_is_read_only_unless_it_says_otherwise(self) -> None:
        """The single most consequential default in DQT.

        Flipping it would turn every existing config that omits the key into
        one that permits writes -- a breaking change that no signature
        records and no import error announces.
        """
        assert ConnectionConfig(id="c", dsn="sqlite:///x.db").read_only is True

    def test_sampling_is_off_unless_asked_for(self) -> None:
        """A run that silently sampled would report a partial answer as whole."""
        assert DQPipelineConfig(connection_id="c").sampling is None

    def test_nothing_is_included_or_excluded_by_default(self) -> None:
        """Omitting the filters means "the whole database", not "nothing"."""
        config = DQPipelineConfig(connection_id="c")

        assert config.include_tables is None
        assert config.exclude_tables is None
