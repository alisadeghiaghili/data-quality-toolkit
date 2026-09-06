"""`dqt serve` and `dqt check` (`F14`).

The CLI had one subcommand. Two consequences followed from that, and neither
was about convenience.

**Starting the dashboard required a `uvicorn` command**, which put it out of
reach of the person the dashboard is for -- a DBA who does not write Python.
DQT's stated differentiation is DBA-first framing, and "install Python, then
run an ASGI server" is not that.

**And it left the loopback rule unenforceable.** `dqt.ui.app`'s docstring has
always said, correctly and at length, that the application has no
authentication and must be bound to loopback. `VIZ-0` tests that the
docstring says it. But a docstring is read by people editing DQT, not by the
person starting a server, and nothing stopped `--host 0.0.0.0`. The reason
given at the time was sound: DQT never called `uvicorn.run`, so there was no
runtime moment at which to refuse.

`dqt serve` creates that moment. The rule becomes a refusal.

**What the refusal protects is not the data DQT stores.** It is the schema:
table names, column names, and a list of exactly where the data is weakest.
That is reconnaissance, and it is served without a login to anyone who can
reach the port.

`dqt check` is the other half. Rules need no profiles -- `apply_rules` takes
discovered tables, not profiles -- so a rules-only gate is genuinely cheaper
than a profile run, which is what makes it worth having as a CI step. Its
sharpest edge is that **checking nothing must not look like passing**.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from dqt.cli import main, resolve_bind_host
from dqt.exceptions import ConfigurationError

SEEDED = """
    CREATE TABLE people (id INTEGER, email TEXT);
    INSERT INTO people (id, email) VALUES (1, 'a@b.com'), (2, NULL), (3, 'c@d.com');
"""

RULES = """
rules:
  - name: email_present
    dimension: completeness
    severity: error
    scope:
      column_pattern: "email"
    expression: NOT NULL
    params: {}
"""


class TestTheBindGuard:
    """The rule that was advisory for as long as nothing bound a port."""

    @pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1"])
    def test_loopback_is_allowed_without_ceremony(self, host: str) -> None:
        """The safe case must stay the easy one.

        A guard that made the correct configuration inconvenient would be
        routed around, and the flag would end up in everyone's start script.
        """
        assert resolve_bind_host(host, allow_remote=False) == host

    @pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.10", "10.0.0.5", "::"])
    def test_a_reachable_address_is_refused(self, host: str) -> None:
        """Refused, not warned about.

        A warning on stderr scrolls past. This is the difference between the
        docstring `VIZ-0` guards and a rule that holds.
        """
        with pytest.raises(ConfigurationError):
            resolve_bind_host(host, allow_remote=False)

    def test_the_refusal_says_what_is_at_risk(self) -> None:
        """ "No authentication" is the fact someone needs to act on.

        A message that only said "use 127.0.0.1" would leave the reader to
        guess whether the rule is a nuisance or a warning, and the honest
        answer is what makes them put a proxy in front of it.
        """
        with pytest.raises(ConfigurationError) as raised:
            resolve_bind_host("0.0.0.0", allow_remote=False)

        message = str(raised.value).lower()

        assert "authentication" in message
        assert "schema" in message or "table names" in message

    def test_it_can_be_overridden_deliberately(self) -> None:
        """The escape hatch exists, and has to be typed in full.

        Someone behind an authenticating proxy has a legitimate need. The
        flag is long on purpose: it should be impossible to add by reflex
        while debugging, and it names what is being allowed rather than
        asking for agreement with something unstated.
        """
        assert resolve_bind_host("0.0.0.0", allow_remote=True) == "0.0.0.0"


class TestServeRefusesBeforeItBinds:
    """A guard that fires after the port is open has already failed."""

    def test_a_refused_host_never_reaches_the_server(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Exit 3 -- a configuration error, per the exit-code contract.

        `NEW-V` was config errors exiting 1, which reads as "your data has
        problems". Getting this wrong the same way would tell a CI job the
        data failed when the operator mistyped a host.
        """
        started: list[object] = []
        monkeypatch.setattr("dqt.cli._run_server", lambda *a, **k: started.append(a), raising=False)
        monkeypatch.setattr("sys.argv", ["dqt", "serve", "--host", "0.0.0.0"])

        with pytest.raises(SystemExit) as raised:
            main()

        assert raised.value.code == 3
        assert started == [], "the server was started despite the refusal"

    def test_the_default_host_is_loopback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Someone who passes no host at all must get the safe one.

        This is the case that decides what most deployments do, because most
        deployments accept the default.
        """
        started: list[tuple[object, ...]] = []
        monkeypatch.setattr("dqt.cli._run_server", lambda *a, **k: started.append(a), raising=False)
        monkeypatch.setattr("sys.argv", ["dqt", "serve"])

        with pytest.raises(SystemExit) as raised:
            main()

        assert raised.value.code == 0
        assert started and started[0][0] == "127.0.0.1"


class TestCheckRunsRulesWithoutProfiling:
    """A gate is only worth having if it is cheaper than the thing it gates."""

    def test_a_failing_rule_exits_one(
        self,
        make_sqlite_db: Callable[[str, str], Path],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """One NULL email against an error-severity NOT NULL rule."""
        db_file = make_sqlite_db("check-fail.db", SEEDED)
        rules = tmp_path / "rules.yaml"
        rules.write_text(RULES, encoding="utf-8")
        monkeypatch.setattr(
            "sys.argv",
            ["dqt", "check", "--dsn", f"sqlite:///{db_file}", "--rules", str(rules)],
        )

        with pytest.raises(SystemExit) as raised:
            main()

        assert raised.value.code == 1

    def test_a_passing_rule_exits_zero(
        self,
        make_sqlite_db: Callable[[str, str], Path],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The control. Without it, exit 1 could mean the rule never ran."""
        db_file = make_sqlite_db("check-pass.db", "CREATE TABLE people (id INTEGER, email TEXT);")
        rules = tmp_path / "rules.yaml"
        rules.write_text(RULES, encoding="utf-8")
        monkeypatch.setattr(
            "sys.argv",
            ["dqt", "check", "--dsn", f"sqlite:///{db_file}", "--rules", str(rules)],
        )

        with pytest.raises(SystemExit) as raised:
            main()

        assert raised.value.code == 0

    def test_checking_nothing_is_not_passing(
        self,
        make_sqlite_db: Callable[[str, str], Path],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The sharpest edge of the whole subcommand.

        A gate invoked with no rules that exits 0 reports a clean bill of
        health for a check that never happened -- and it fails that way
        silently, in CI, exactly where nobody is watching. An empty rule set
        is a configuration error, so it exits 3.
        """
        db_file = make_sqlite_db("check-empty.db", SEEDED)
        empty = tmp_path / "empty.yaml"
        empty.write_text("rules: []\n", encoding="utf-8")
        monkeypatch.setattr(
            "sys.argv",
            ["dqt", "check", "--dsn", f"sqlite:///{db_file}", "--rules", str(empty)],
        )

        with pytest.raises(SystemExit) as raised:
            main()

        assert raised.value.code == 3

    def test_it_computes_no_column_statistics(
        self,
        make_sqlite_db: Callable[[str, str], Path],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Being cheaper than ``profile`` is the reason it exists.

        A ``check`` that quietly profiled would return the same exit code and
        cost the same as the run it was meant to replace, so only the
        statements can tell.
        """
        db_file = make_sqlite_db("check-cost.db", SEEDED)
        rules = tmp_path / "rules.yaml"
        rules.write_text(RULES, encoding="utf-8")

        import dqt.sql.rules as rules_module
        import dqt.sql.schema_discovery as discovery_module
        from dqt.sql._connect import get_connection as real_connect

        statements: list[str] = []

        def traced(*args: object, **kwargs: object) -> object:
            connection = real_connect(*args, **kwargs)  # type: ignore[arg-type]
            connection.set_trace_callback(statements.append)
            return connection

        monkeypatch.setattr(rules_module, "get_connection", traced)
        monkeypatch.setattr(discovery_module, "get_connection", traced)
        monkeypatch.setattr(
            "sys.argv",
            ["dqt", "check", "--dsn", f"sqlite:///{db_file}", "--rules", str(rules)],
        )

        with pytest.raises(SystemExit):
            main()

        assert statements, "nothing was traced, so this proves nothing"
        assert not [s for s in statements if "MIN(" in s.upper() or "AVG(" in s.upper()], (
            f"check computed column statistics: {statements}"
        )
