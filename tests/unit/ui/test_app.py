"""Grounded unit tests for the read-only HTTP surface, ``dqt.ui.app`` (NEW-D).

`docs/CONVENTIONS-DQT.md` calls this surface read-only. That was an unbacked
claim: nothing tested it. ``test_api_exposes_no_mutating_route`` makes it a
checked property instead, which matters more here than anywhere else in the
codebase -- this is the one component designed to be reachable over a network.

Expectations come from the literal fixture in ``client``: four metrics, three
of them ``completeness`` with scores 1.0, 0.5 and 0.0, and two issues, across
tables ``orders`` and ``customers``.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

pytest.importorskip("fastapi", reason="the ui extra is not installed")

from fastapi.testclient import TestClient  # noqa: E402

import dqt  # noqa: E402
from dqt.common.models import DQIssue, DQMetric, PipelineResult  # noqa: E402
from dqt.common.storage import RunStore  # noqa: E402
from dqt.ui.app import app  # noqa: E402

RUN_ID = "run-001"


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """Point the app at a store seeded with one hand-known run.

    Args:
        tmp_path: pytest temporary directory.
        monkeypatch: pytest monkeypatch fixture, used to set DQT_STORE_PATH.

    Yields:
        A TestClient bound to the app reading that store.

    Example:
        response = client.get("/health")
    """
    db = tmp_path / "runs.db"
    store = RunStore(db_path=db)
    store.init_schema()

    def metric(dimension: str, score: float, table: str, column: str | None = None) -> DQMetric:
        return DQMetric(
            run_id=RUN_ID,
            dimension=dimension if dimension in {"completeness"} else None,
            metric_name=None if dimension in {"completeness"} else dimension,
            score=score,
            schema_name="main",
            table_name=table,
            column_name=column,
            value=score,
            metadata={},
        )

    def issue(severity: str, table: str, column: str) -> DQIssue:
        return DQIssue(
            issue_id=f"{RUN_ID}:{table}:{column}",
            run_id=RUN_ID,
            dimension="completeness",
            severity=severity,  # type: ignore[arg-type]
            message=f"Column '{column}' contains NULL values.",
            evidence={"null_count": 1, "row_count": 2},
            schema_name="main",
            table_name=table,
            column_name=column,
            rule_name=None,
        )

    store.save_run(
        PipelineResult(
            run_id=RUN_ID,
            connection_id="conn-a",
            started_at=datetime(2026, 9, 4, 10, 0, tzinfo=UTC),
            ended_at=datetime(2026, 9, 4, 10, 1, tzinfo=UTC),
            status="success",
            metrics=[
                metric("completeness", 1.0, "orders", "id"),
                metric("completeness", 0.5, "orders", "email"),
                metric("completeness", 0.0, "customers", "phone"),
                metric("row_count", 1.0, "orders"),
            ],
            issues=[
                issue("warning", "orders", "email"),
                issue("error", "customers", "phone"),
            ],
        )
    )
    monkeypatch.setenv("DQT_STORE_PATH", str(db))
    yield TestClient(app)


def test_health_reports_the_active_store(client: TestClient) -> None:
    """The liveness probe names the store it is actually reading.

    Reporting the resolved path, not just ``ok``, is what makes the probe
    useful: a UI pointed at the wrong store is otherwise indistinguishable
    from one pointed at an empty one.
    """
    body = client.get("/health").json()

    assert body["status"] == "ok"
    assert body["store"].endswith("runs.db")


def test_runs_endpoint_returns_the_seeded_run(client: TestClient) -> None:
    """One run was seeded, so the collection has exactly one member."""
    response = client.get("/runs")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["run_id"] == RUN_ID
    assert body[0]["connection_id"] == "conn-a"


def test_run_detail_averages_only_completeness(client: TestClient) -> None:
    """The summary endpoint reports the hand-derived completeness mean.

    Ground truth: completeness scores 1.0, 0.5 and 0.0 average to 0.5. The
    ``row_count`` metric scores 1.0 and must be excluded; including it would
    give 0.625, so the fixture discriminates between the two implementations.
    """
    body = client.get(f"/runs/{RUN_ID}").json()

    assert body["overall_completeness"] == 0.5
    assert body["metric_count"] == 4
    assert body["issue_count"] == 2


def test_unknown_run_is_404_not_a_200_carrying_an_error(client: TestClient) -> None:
    """A missing run is an HTTP error, not a 200 with an error field.

    The data-access layer returns ``{"error": ...}``; the HTTP layer must
    translate that into a status code. A 200 body containing an error is the
    kind of thing a UI silently renders as an empty dashboard.
    """
    response = client.get("/runs/does-not-exist")

    assert response.status_code == 404


def test_tables_endpoint_is_sorted_and_deduplicated(client: TestClient) -> None:
    """Ground truth: ``orders`` appears in three metrics, ``customers`` in one."""
    assert client.get(f"/runs/{RUN_ID}/tables").json() == ["customers", "orders"]


def test_metrics_and_issues_endpoints_filter(client: TestClient) -> None:
    """Query parameters select the hand-known subsets rather than being ignored."""
    assert len(client.get(f"/runs/{RUN_ID}/metrics").json()) == 4
    assert len(client.get(f"/runs/{RUN_ID}/metrics?dimension=completeness").json()) == 3
    assert len(client.get(f"/runs/{RUN_ID}/metrics?table_name=orders").json()) == 3

    assert len(client.get(f"/runs/{RUN_ID}/issues").json()) == 2
    errors = client.get(f"/runs/{RUN_ID}/issues?severity=error").json()
    assert [i["table_name"] for i in errors] == ["customers"]


def test_api_exposes_no_mutating_route(client: TestClient) -> None:
    """The surface is read-only, and this is what makes that a fact.

    ``docs/CONVENTIONS-DQT.md`` describes this API as read-only. Until now
    nothing enforced it, so the next endpoint added could have quietly made
    the description false. DQT connects to production databases; a write
    route reachable over HTTP is the highest-consequence mistake available in
    this package.
    """
    mutating = {"POST", "PUT", "PATCH", "DELETE"}
    offenders = [
        (route.path, sorted(route.methods & mutating))
        for route in app.routes
        if getattr(route, "methods", None) and route.methods & mutating
    ]

    assert offenders == []


def test_app_version_matches_the_package_version() -> None:
    """The advertised API version must be the package version.

    A hardcoded version drifts the moment the package is bumped, and an API
    that misreports its own version is a claim that contradicts the code --
    exactly what ``docs/HONESTY-GATE.md`` exists to prevent. The value is
    served in the OpenAPI document, so consumers pin against it.
    """
    assert app.version == dqt.__version__


# ---------------------------------------------------------------------------
# The HTML screens (VIZ-3)
# ---------------------------------------------------------------------------
#
# The pages themselves are pure and tested in test_pages.py without a server.
# What is left for a live app is the part only routing can get wrong: that a
# URL exists, that it serves HTML rather than JSON, and that a run which does
# not exist says so instead of rendering an empty page that looks like a
# healthy one.


class TestTheScreensAreServed:
    """Routing only. The rendering is asserted in test_pages.py."""

    def test_the_overview_is_served_as_html(self, client: TestClient) -> None:
        """The entry point a DBA actually opens."""
        response = client.get("/ui")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        assert "<!DOCTYPE html>" in response.text

    def test_a_run_has_its_own_page(self, client: TestClient) -> None:
        """Overview to run is the first step of the drill-down path."""
        response = client.get(f"/ui/runs/{RUN_ID}")

        assert response.status_code == 200
        assert RUN_ID in response.text

    def test_a_run_s_issues_have_their_own_page(self, client: TestClient) -> None:
        """Run to issues is the second step, and the last one that exists."""
        response = client.get(f"/ui/runs/{RUN_ID}/issues")

        assert response.status_code == 200
        assert "Issues" in response.text

    def test_an_unknown_run_is_a_404_rather_than_an_empty_page(self, client: TestClient) -> None:
        """An empty run page reads as a run that went perfectly.

        Which is the same defect as a failed run rendering green, reached by
        a different route: the page has to distinguish "nothing wrong" from
        "nothing here".
        """
        assert client.get("/ui/runs/no-such-run").status_code == 404

    def test_the_json_api_still_answers(self, client: TestClient) -> None:
        """The screens are added beside the JSON, not instead of it.

        Anything already reading /runs keeps working; `VIZ-3` only adds a
        second way to look at the same store.
        """
        response = client.get("/runs")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/json")
