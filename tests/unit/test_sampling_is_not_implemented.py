"""What `SamplingConfig` actually does today (`NEW-X`).

`docs/HONESTY-GATE.md`: a docstring may only describe behaviour a passing
test covers. `SamplingConfig`'s said DQT "can sample rows instead of scanning
full tables", and described `strategy` as *"``random`` uses ``TABLESAMPLE`` or
``ORDER BY RANDOM()``; ``first_n`` takes the first ``limit`` rows via
``LIMIT``"*.

**None of that SQL is ever generated.** The string `sampling` appears nowhere
under `src/dqt/` outside the model that defines it. A user can write
``sampling: {strategy: first_n, limit: 1000}``, DQT accepts it — the config
schema is strict now, so it is a *valid* key — and then scans the whole
table.

That is the worst kind of unbacked claim, because the config is accepted. A
key DQT refused would tell the user immediately. A key it accepts and ignores
tells them nothing, and they believe their overnight job sampled.

`CLAUDE.md` §3 asks for it: *"Honour SamplingConfig; don't force a full scan
when a sample answers the question."* Implementing it is a feature and
belongs in a roadmap. Saying so is not: it is a correction, and it is why
these tests exist before the feature does.

The class stays in the frozen API. Removing it would be a major-version
break for a name people may already reference, and it is the right shape for
the feature when it lands — it is the *description* that was wrong, not the
type.
"""

from __future__ import annotations

import pathlib

from dqt.common.models import DQPipelineConfig, SamplingConfig

_SOURCE_ROOT = pathlib.Path(__file__).resolve().parents[2] / "src" / "dqt"


class TestSamplingIsAcceptedAndNotYetHonoured:
    """Stated as a test so the day it changes, this file has to change too."""

    def test_no_module_reads_the_sampling_config(self) -> None:
        """The measurable form of "not implemented".

        Asserted over the source rather than by running a query, because
        there is no query to run -- which is precisely the finding.

        When sampling lands, this test fails, and whoever implements it has
        to come here and replace it with one that checks the SQL. That is the
        point: the claim and its correction move together.
        """
        # ``.sampling`` is attribute access on a config -- somebody reading
        # the setting. A bare ``SamplingConfig`` is only the name being
        # re-exported, which several ``__init__`` files do and which reads
        # nothing.
        readers = [
            path.relative_to(_SOURCE_ROOT).as_posix()
            for path in sorted(_SOURCE_ROOT.rglob("*.py"))
            if ".sampling" in path.read_text(encoding="utf-8") and path.name != "models.py"
        ]

        assert readers == [], (
            f"sampling is now read by {readers} -- if it is implemented, "
            "replace this test with one that checks the generated SQL and "
            "restore the description on SamplingConfig."
        )

    def test_the_docstring_does_not_claim_it_works(self) -> None:
        """The honesty gate, applied to the class it was broken by.

        The old text named ``TABLESAMPLE``, ``ORDER BY RANDOM()`` and
        ``LIMIT``. A reader had every reason to believe one of them would be
        emitted.
        """
        text = SamplingConfig.__doc__ or ""

        for promised in ("TABLESAMPLE", "ORDER BY RANDOM"):
            assert promised not in text, (
                f"SamplingConfig's docstring still promises {promised!r}, "
                "which DQT does not generate."
            )

    def test_the_docstring_says_it_is_not_yet_honoured(self) -> None:
        """Silence would be better than a lie and worse than a warning.

        A user reading the class needs to know now, not after an overnight
        run they believed was sampled.
        """
        text = (SamplingConfig.__doc__ or "").lower()

        assert "not" in text and ("honour" in text or "honor" in text or "ignored" in text)

    def test_the_config_still_accepts_it(self) -> None:
        """The key stays valid, because removing it would break configs.

        `docs/API-STABILITY.md` makes removing a config key a major change,
        and the type is the right shape for the feature when it lands. What
        was wrong is the description, not the type.
        """
        config = DQPipelineConfig(
            connection_id="c", sampling=SamplingConfig(strategy="first_n", limit=1000)
        )

        assert config.sampling is not None
        assert config.sampling.limit == 1000
