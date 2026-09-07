"""Every config-file key reaches the pipeline (`NEW-AC`).

`_build_pipeline_config` enumerated the keys it forwarded. Five of them.
Every key added to `DQPipelineConfig` after the CLI was written was therefore
**silently dropped** from config files -- `sampling` since `1.1.0`,
`profiling` and `classification` since `1.2.0`, and `timeliness` as it was
being added.

The failure mode is the one this project keeps circling: the user writes

    sampling:
      limit: 5000

DQT parses it, ignores it, scans the whole table, and reports numbers that
look exactly like the ones they asked for. Nothing errors. `1.0.2` had to
correct a docstring that described sampling SQL DQT never generated; this is
the same lie relocated into the CLI.

Enumerating the keys was the mistake, so the fix stops enumerating: the file
is handed to the model, which knows its own fields and -- through
``extra="forbid"`` -- refuses a key it does not have. The test below is
written against the *model's* field list rather than a copy of it, so a key
added tomorrow is covered without anybody remembering to come back here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dqt.common.models import DQPipelineConfig


def _build(tmp_path: Path, payload: dict[str, object]) -> DQPipelineConfig:
    """Build a pipeline config the way the CLI does, from a file.

    Args:
        tmp_path: pytest's per-test directory.
        payload: The config file's contents.

    Returns:
        The resulting :class:`~dqt.common.models.DQPipelineConfig`.

    Example:
        cfg = _build(tmp_path, {"connection_id": "c"})
    """
    import argparse

    from dqt.cli import _build_pipeline_config, _load_config_file

    path = tmp_path / "dqt.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    args = argparse.Namespace(connection_id="cli", schema=None, config=str(path))
    return _build_pipeline_config(args, _load_config_file(str(path)))


class TestNoKeyIsSilentlyDropped:
    """A setting that parses and does nothing is worse than one that errors."""

    def test_every_model_field_survives_the_round_trip(self, tmp_path: Path) -> None:
        """Written against the model, not against a copied list.

        A hand-maintained list of expected keys is the same mistake one level
        up: it would have to be updated by the same person who forgot to
        update the builder.
        """
        payload: dict[str, object] = {
            "connection_id": "from-file",
            "include_schemas": ["a"],
            "exclude_schemas": ["b"],
            "include_tables": ["c"],
            "exclude_tables": ["d"],
            "rule_files": ["r.yaml"],
            "metric_thresholds": {"completeness": 0.9},
            "sampling": {"strategy": "first_n", "limit": 5000},
            "profiling": {"distinct_counts": False},
            "classification": {"enabled": True},
            "timeliness": {"max_age_days": 7},
            "monitoring": {"max_score_drop": 0.1},
            "missingness": {"enabled": True},
        }

        missing = set(DQPipelineConfig.model_fields) - set(payload)
        assert not missing, (
            f"this test does not cover {sorted(missing)}; add them to the payload "
            "so the assertion below actually checks them"
        )

        built = _build(tmp_path, payload)

        for field in DQPipelineConfig.model_fields:
            value = getattr(built, field)
            assert value not in (None, [], {}), f"{field} was dropped on the way through"

    def test_sampling_specifically_survives(self, tmp_path: Path) -> None:
        """Called out because it shipped in `1.1.0` and never worked from a file.

        The unit that added it tested the pipeline object directly, so the
        CLI path -- the only way a DBA configures anything -- was never
        exercised.
        """
        built = _build(tmp_path, {"connection_id": "c", "sampling": {"limit": 5000}})

        assert built.sampling is not None
        assert built.sampling.limit == 5000

    def test_a_misspelled_key_is_refused(self, tmp_path: Path) -> None:
        """The other half of not enumerating.

        Handing the file to the model means ``extra="forbid"`` now sees it,
        so ``exclude_tabels`` fails loudly instead of being quietly ignored
        while DQT profiles every table the author meant to skip.
        """
        with pytest.raises(Exception, match="tabels|extra"):
            _build(tmp_path, {"connection_id": "c", "exclude_tabels": ["secrets"]})


class TestCommandLineArgumentsStillWin:
    """The precedence the CLI documented, kept while the mechanism changes."""

    def test_connection_id_from_the_command_line_overrides_the_file(self, tmp_path: Path) -> None:
        """``--connection-id`` is explicit; a file value is a default."""
        import argparse

        from dqt.cli import _build_pipeline_config

        args = argparse.Namespace(connection_id="from-cli", schema=None, config=None)
        built = _build_pipeline_config(args, {"connection_id": "from-file"})

        assert built.connection_id == "from-cli"

    def test_schema_from_the_command_line_overrides_the_file(self, tmp_path: Path) -> None:
        """``--schema`` narrows a run; a file's include list is the default."""
        import argparse

        from dqt.cli import _build_pipeline_config

        args = argparse.Namespace(connection_id="cli", schema="sales", config=None)
        built = _build_pipeline_config(args, {"include_schemas": ["everything"]})

        assert built.include_schemas == ["sales"]
