"""What the CLI exits with when the caller got something wrong (`NEW-V`).

`README.md` and :class:`dqt.exit_codes.ExitCode` both promise that **3** means
"configuration or connection error — DQT never reached your database", and
that **1** means "at least one `error` or `critical` finding". The exit code
is the contract a CI pipeline branches on, and `docs/API-STABILITY.md` freezes
it: changing what a code *means* is a major-version change.

`tests/unit/test_exit_codes.py` covers `decide_exit_code`, which maps a
finished run's findings onto a code. It cannot cover the paths where there is
no run — a config file that does not exist, one that will not parse, a YAML
file with no parser installed. Those exit before a pipeline is ever built,
and nothing tested them.

**They all exit 1.** A pipeline that branches on the contract reads "your data
has errors" and reports a data-quality failure, when the truth is that DQT
never opened the database and the caller has a typo in a path. The two demand
opposite responses: one is a finding to triage, the other is a build to fix.

That is a defect against documented behaviour rather than a change of mind, so
`docs/API-STABILITY.md` §3 makes correcting it a patch — the docs already say
3, and the code disagrees with them.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dqt.cli import _load_config_file
from dqt.exit_codes import ExitCode


def _exit_code(raised: pytest.ExceptionInfo[SystemExit]) -> int:
    """Return the code a ``SystemExit`` carries.

    Args:
        raised: The captured exception.

    Returns:
        The exit code as an int.

    Example:
        assert _exit_code(raised) == 3
    """
    return int(raised.value.code or 0)


class TestAConfigProblemExitsThree:
    """ "DQT never reached your database" is a different failure from a finding."""

    def test_a_missing_config_file(self, tmp_path: Path) -> None:
        """The commonest one: a path typo, or a file that moved.

        Exiting 1 tells a CI pipeline the data has errors. It does not: DQT
        never looked at any.
        """
        with pytest.raises(SystemExit) as raised:
            _load_config_file(str(tmp_path / "nope.yaml"))

        assert _exit_code(raised) == ExitCode.CONFIGURATION_ERROR

    def test_a_config_file_that_will_not_parse(self, tmp_path: Path) -> None:
        """A trailing comma is a config error, not a data-quality finding."""
        broken = tmp_path / "config.json"
        broken.write_text('{"connection_id": "c",}', encoding="utf-8")

        with pytest.raises(SystemExit) as raised:
            _load_config_file(str(broken))

        assert _exit_code(raised) == ExitCode.CONFIGURATION_ERROR

    def test_yaml_without_a_yaml_parser(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A missing optional dependency is the caller's to fix, and says so.

        DQT reads YAML through an extra. Without it there is nothing wrong
        with the data or with DQT -- the install is incomplete.
        """
        import dqt.cli as cli

        config = tmp_path / "config.yaml"
        config.write_text("connection_id: c\n", encoding="utf-8")
        monkeypatch.setattr(cli, "_YAML_AVAILABLE", False)

        with pytest.raises(SystemExit) as raised:
            _load_config_file(str(config))

        assert _exit_code(raised) == ExitCode.CONFIGURATION_ERROR


class TestAGoodConfigStillLoads:
    """The control: the refusals above are about the failure, not strictness."""

    def test_json_is_read(self, tmp_path: Path) -> None:
        """The happy path, so a change that made everything exit 3 would fail."""
        config = tmp_path / "config.json"
        config.write_text(json.dumps({"connection_id": "c"}), encoding="utf-8")

        assert _load_config_file(str(config)) == {"connection_id": "c"}

    def test_an_empty_yaml_file_is_an_empty_config(self, tmp_path: Path) -> None:
        """Empty is a valid config that says nothing, not a parse failure."""
        pytest.importorskip("yaml")
        config = tmp_path / "config.yaml"
        config.write_text("", encoding="utf-8")

        assert _load_config_file(str(config)) == {}


class TestTheCodesStayDistinct:
    """The contract is only useful while the numbers mean different things."""

    def test_configuration_and_findings_are_not_the_same_code(self) -> None:
        """Stated directly, because this is exactly what was collapsed.

        If these were ever made equal, every test above would pass while the
        distinction they exist to protect had been thrown away.
        """
        assert ExitCode.CONFIGURATION_ERROR != ExitCode.ERROR_FINDINGS

    def test_the_documented_numbers_have_not_moved(self) -> None:
        """README.md's table, restated where a change to it would fail.

        `docs/API-STABILITY.md` makes renumbering these a major change, so
        the numbers are pinned rather than merely named.
        """
        assert (int(ExitCode.SUCCESS), int(ExitCode.ERROR_FINDINGS)) == (0, 1)
        assert (int(ExitCode.WARNING_FINDINGS), int(ExitCode.CONFIGURATION_ERROR)) == (2, 3)
        assert int(ExitCode.INTERNAL_ERROR) == 4
