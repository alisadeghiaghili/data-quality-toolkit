"""No tracked file names an assistant's instruction file (`NEW-AA`).

The repository's governance is deliberately split: the owner's local
assistant-instruction file is kept out of the repository through
``.git/info/exclude`` rather than ``.gitignore``, so that the exclusion
itself leaves no trace in a tracked file.

That arrangement was defeated from the other direction. Twelve tracked
files -- shipped source, the CI workflow, ``tools/arch_audit.py``, tests and
docs -- cited that excluded file **by name**, nineteen times, as the
authority for DQT's architecture and performance rules.

Two separate things were wrong with it, and the second matters more:

1. The filename is an assistant-tool artifact, which is precisely what the
   exclusion exists to keep out of the tree.
2. **The rules had no tracked home at all.** Someone who cloned this
   repository could read ``tools/arch_audit.py`` saying it enforces rules
   "stated in prose" in a file that is not there, and had no way to read
   them. A CI gate whose specification is missing from the repository it
   gates is broken governance on its own terms, regardless of what the
   missing file is called.

So the fix was not a find-and-replace. The architecture and performance
rules moved **into** ``AGENTS.md``, which is tracked, and the citations now
point at it. This test holds that line.

It checks tracked files only. What a contributor keeps in their own working
directory is their business; what the repository publishes is not.
"""

from __future__ import annotations

import pathlib
import re
import subprocess

_ROOT = pathlib.Path(__file__).resolve().parents[2]

#: Instruction-file and configuration names that identify a specific coding
#: assistant. Matched case-insensitively against tracked file contents and
#: against the tracked path list itself.
_ASSISTANT_ARTIFACTS = (
    r"CLAUDE\.md",
    r"\.claude/",
    r"\.cursorrules",
    r"copilot-instructions",
    r"\.aider(?:\.conf)?",
    r"\.github/copilot",
)

#: This file names the artifacts in order to forbid them, and the commit
#: that introduced the rule has to be able to explain itself. Excluding the
#: test from its own check is not a loophole -- a check that failed on its
#: own source could only be satisfied by describing the rule so vaguely that
#: nobody could tell what it forbade.
_EXEMPT = {"tests/unit/test_no_assistant_footprint.py"}


def _tracked_files() -> list[str]:
    """Return every path Git tracks, as repo-relative POSIX strings.

    Returns:
        The tracked paths.

    Example:
        assert "README.md" in _tracked_files()
    """
    output = subprocess.run(
        ["git", "ls-files"],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [line for line in output.splitlines() if line]


class TestNoTrackedFileNamesAnAssistant:
    """The repository must not advertise how it was edited."""

    def test_no_tracked_path_is_an_assistant_artifact(self) -> None:
        """The exclusion is meant to keep these out of the tree entirely.

        Checked separately from content because a committed
        ``.claude/settings.json`` would be a footprint even if no file
        mentioned it.
        """
        pattern = re.compile("|".join(_ASSISTANT_ARTIFACTS), re.IGNORECASE)
        offenders = [path for path in _tracked_files() if pattern.search(path)]

        assert offenders == [], f"Assistant artifacts are tracked: {offenders}"

    def test_no_tracked_file_cites_an_assistant_instruction_file(self) -> None:
        """The failure that prompted this: 19 citations across 12 files.

        A citation is worse than a stray mention. It tells a reader that the
        authority for a rule lives somewhere they cannot look, and it does so
        in the CI workflow and in shipped source.
        """
        pattern = re.compile("|".join(_ASSISTANT_ARTIFACTS), re.IGNORECASE)
        offenders: list[str] = []

        for path in _tracked_files():
            if path in _EXEMPT:
                continue
            full = _ROOT / path
            try:
                text = full.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue  # binary or unreadable: nothing to cite with
            for number, line in enumerate(text.splitlines(), start=1):
                if pattern.search(line):
                    offenders.append(f"{path}:{number}: {line.strip()[:90]}")

        assert offenders == [], (
            f"{len(offenders)} tracked line(s) name an assistant instruction "
            "file. Cite AGENTS.md, which is tracked, and move the rule there "
            "if it does not already say it.\n" + "\n".join(offenders[:20])
        )


class TestTheRulesHaveATrackedHome:
    """Repointing the citations is only half the fix.

    If the architecture and performance rules had simply been deleted from
    the citations, the tree would pass the check above while leaving
    ``tools/arch_audit.py`` enforcing a specification that exists nowhere.
    These assert the rules actually arrived.
    """

    def test_agents_md_states_the_architecture_rules(self) -> None:
        """``arch_audit.py`` and `ARC-01` both cite these as prose."""
        agents = (_ROOT / "AGENTS.md").read_text(encoding="utf-8")

        assert "point inward" in agents
        assert "facet" in agents.lower()

    def test_agents_md_states_the_performance_rules(self) -> None:
        """Cited by the rule engine and by four test modules."""
        agents = (_ROOT / "AGENTS.md").read_text(encoding="utf-8")

        assert "single-pass" in agents.lower() or "single pass" in agents.lower()
        assert "design smell" in agents.lower()
