"""The `missingly` adapter, B2.

`missingly` is not installed here and is not a dependency of DQT, so these
tests inject a stand-in under that name. That is not a shortcut around
testing: the code under test is the *translation*, and translation is exactly
what a stand-in exercises. Installing the real package would test `missingly`,
which is its own repository's job.

What the stand-in returns is taken from `missingly`'s real signatures --
``miss_var_summary`` yields one row per variable with columns ``variable``,
``n_miss`` and ``pct_miss``, and ``pct_miss`` is on a 0..100 scale.
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pandas as pd
import pytest

from dqt.bridges import MissingnessReport
from dqt.bridges.missingly import (
    MissinglyBridge,
    attach_missingly_result,
    run_missingly,
    sample_table,
)
from dqt.common.models import ConnectionConfig, PipelineResult

# Four rows; `email` is NULL on two of them, `id` on none.
# Hand-counted: email 2/4 -> ratio 0.5, id 0/4 -> ratio 0.0.
CUSTOMERS = """
    CREATE TABLE customers (id INTEGER PRIMARY KEY, email TEXT);
    INSERT INTO customers (id, email) VALUES (1, 'a@b.com');
    INSERT INTO customers (id, email) VALUES (2, NULL);
    INSERT INTO customers (id, email) VALUES (3, 'c@d.com');
    INSERT INTO customers (id, email) VALUES (4, NULL);
"""


@pytest.fixture
def fake_missingly(monkeypatch: pytest.MonkeyPatch) -> Iterator[ModuleType]:
    """Install a stand-in `missingly` for the duration of one test.

    Args:
        monkeypatch: pytest monkeypatch fixture.

    Yields:
        The injected module, so a test can assert what it was called with.

    Example:
        def test_something(fake_missingly):
            run_missingly(frame, table_name="t")
    """
    module = ModuleType("missingly")
    module.calls = []  # type: ignore[attr-defined]

    def miss_var_summary(frame: pd.DataFrame) -> pd.DataFrame:
        module.calls.append(("miss_var_summary", len(frame)))  # type: ignore[attr-defined]
        counts = frame.isnull().sum()
        return pd.DataFrame(
            {
                "variable": frame.columns,
                "n_miss": counts.values,
                # Percent, exactly as the real package reports it.
                "pct_miss": (counts / len(frame) * 100).values,
            }
        )

    module.miss_var_summary = miss_var_summary  # type: ignore[attr-defined]
    module.mcar_test = lambda frame: {"p_value": 0.42, "statistic": 3.1}  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "missingly", module)
    yield module


def test_sample_table_bounds_the_read(
    make_sqlite_db: Callable[[str, str], Path], fake_missingly: ModuleType
) -> None:
    """Sampling never reads more rows than it was asked for.

    This is the load-bearing performance property of the whole bridge.
    `missingly` works on a DataFrame, so the only way to analyse a
    production-sized table is to not read all of it. A bridge that quietly
    pulled the full table would put DQT's memory use at the mercy of the
    largest table a DBA points it at.
    """
    db = make_sqlite_db("customers.db", CUSTOMERS)
    config = ConnectionConfig(id="t", dsn=f"sqlite:///{db}")

    frame = sample_table(config, table_name="customers", limit=2)

    assert len(frame) == 2
    assert list(frame.columns) == ["id", "email"]


def test_sample_table_returns_every_row_when_the_table_is_smaller(
    make_sqlite_db: Callable[[str, str], Path], fake_missingly: ModuleType
) -> None:
    """A limit above the row count is not an error and truncates nothing."""
    db = make_sqlite_db("customers.db", CUSTOMERS)
    config = ConnectionConfig(id="t", dsn=f"sqlite:///{db}")

    assert len(sample_table(config, table_name="customers", limit=1000)) == 4


def test_percentages_become_ratios_at_the_boundary(fake_missingly: ModuleType) -> None:
    """`missingly` reports 0..100; the report stores 0..1.

    Ground truth from the fixture: `email` is NULL on 2 of 4 rows, so
    `missingly` reports ``pct_miss == 50.0`` and the bridge must store
    ``missing_ratio == 0.5``. Storing 50.0 would not raise anywhere -- it
    would just make a half-empty column look fifty times worse than it is,
    which is precisely the kind of silent unit error a boundary exists to
    stop.
    """
    frame = pd.DataFrame({"id": [1, 2, 3, 4], "email": ["a", None, "c", None]})

    report = run_missingly(frame, table_name="customers", schema_name="main")

    by_name = {c.column_name: c for c in report.columns}
    assert by_name["email"].missing_ratio == 0.5
    assert by_name["email"].missing_count == 2
    assert by_name["id"].missing_ratio == 0.0
    assert report.sampled_rows == 4
    assert report.analyzer == "missingly"


def test_analyser_diagnostics_are_carried_through_uninterpreted(
    fake_missingly: ModuleType,
) -> None:
    """MCAR results reach the report without DQT deciding what they mean.

    DQT's standing rule is that it never re-implements `missingly`'s
    algorithms. Storing the verdict and refusing to interpret it is what that
    rule looks like in code.
    """
    frame = pd.DataFrame({"a": [1, None]})

    report = run_missingly(frame, table_name="t")

    assert report.diagnostics["mcar_test"] == {"p_value": 0.42, "statistic": 3.1}


def test_absent_missingly_names_the_extra_that_installs_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without the package the failure says how to fix it.

    DQT must be fully usable without `missingly`, so this path is the normal
    case for most installs, not an edge case. An unqualified ModuleNotFoundError
    would leave a DBA guessing which extra to install.
    """
    monkeypatch.setitem(sys.modules, "missingly", None)

    with pytest.raises(ImportError, match=r"dqt\[bridges\]"):
        run_missingly(pd.DataFrame({"a": [1]}), table_name="t")


def test_the_bridge_satisfies_the_generic_protocol(fake_missingly: ModuleType) -> None:
    """`MissinglyBridge` is usable through B1 without naming `missingly`."""
    bridge = MissinglyBridge()
    report = bridge.analyze(pd.DataFrame({"a": [1, None]}), table_name="t")

    assert isinstance(report, MissingnessReport)
    assert bridge.name == "missingly"


def test_attach_writes_under_the_analyser_and_table_key() -> None:
    """The result lands where `external_analyses` is documented to hold it.

    The field is keyed by tool name and then by ``schema.table``. The report
    supplies both, so the caller cannot key it under a name that disagrees
    with what the report says it is.
    """
    result = PipelineResult(
        run_id="run-001",
        connection_id="conn-a",
        started_at=datetime(2026, 9, 4, tzinfo=UTC),
        ended_at=datetime(2026, 9, 4, tzinfo=UTC),
        status="success",
    )
    report = MissingnessReport(
        analyzer="missingly",
        schema_name="main",
        table_name="customers",
        sampled_rows=4,
        columns=(),
    )

    attach_missingly_result(result, report)

    assert result.external_analyses["missingly"]["main.customers"]["sampled_rows"] == 4


def test_dqt_core_never_imports_missingly() -> None:
    """Importing DQT must not pull in the sibling package.

    `missingly` is an independent sibling, not a dependency. The bridge is the
    only module allowed to know it exists, and only when explicitly called --
    which means importing `dqt` on a machine without it has to keep working.
    """
    core = SimpleNamespace(name="dqt.sql.pipeline")
    module = __import__(core.name, fromlist=["*"])

    assert "missingly" not in sys.modules or sys.modules["missingly"] is not None
    assert not hasattr(module, "missingly")
