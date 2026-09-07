"""Which columns go missing together (`F11`).

Profiling has always reported *how much* is missing, per column. It has
never reported *what is missing with what* -- and those are different
findings. Three columns each 20% NULL might be twenty percent of rows
missing all three, or sixty percent of rows missing one each. The first is
one broken upstream feed; the second is three unrelated gaps, and the null
counts are identical.

**The boundary with `missingly` is the reason this needed thinking about
before writing.** `AGENTS.md` forbids re-implementing that package's
algorithms, and the bridge exists because missingness analysis is its job.
The line drawn here:

* **`missingly` infers the mechanism.** `mcar_test` asks whether the
  missingness is random -- a statistical inference, over a DataFrame, which
  is exactly what the bridge samples rows for.
* **DQT counts co-occurrence.** "These three columns are NULL together in
  412 rows" is a `GROUP BY`. It asserts nothing about *why*, runs inside the
  database, and materialises no rows.

Describing a pattern is not inferring a mechanism, and a `GROUP BY` is not
one of missingly's algorithms. DQT reports the pattern; missingly explains
it.

**Off by default**, because it costs a second scan of the table. Profiling
is already one deliberate full pass, and doubling it should be a decision.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from dqt.common.models import ConnectionConfig, DQPipelineConfig, MissingnessConfig
from dqt.sql.pipeline import DQTPipeline

# Hand-derived from the rows below. Writing '1' for NULL, in column order
# (email, phone, note):
#   rows 1,2,3 -> '110'  : email and phone missing together, 3 rows
#   row 4      -> '001'  : only note missing, 1 row
#   rows 5,6   -> '000'  : nothing missing, 2 rows
# So email and phone are each 3/6 NULL, note is 1/6, and the null counts
# alone cannot tell you that email and phone always fail together.
SEEDED = """
    CREATE TABLE contacts (
        id INTEGER PRIMARY KEY,
        email TEXT,
        phone TEXT,
        note TEXT
    );
    INSERT INTO contacts (id, email, phone, note) VALUES
        (1, NULL,      NULL,   'a'),
        (2, NULL,      NULL,   'b'),
        (3, NULL,      NULL,   'c'),
        (4, 'd@x.com', '0912', NULL),
        (5, 'e@x.com', '0913', 'e'),
        (6, 'f@x.com', '0914', 'f');
"""


def _run(
    make_sqlite_db: Callable[[str, str], Path],
    tmp_path: Path,
    name: str,
    config: DQPipelineConfig | None = None,
) -> object:
    """Run the pipeline over the seeded table.

    Args:
        make_sqlite_db: Factory fixture building a SQLite file.
        tmp_path: pytest's per-test directory.
        name: Distinct database filename.
        config: Pipeline settings, or None for the defaults.

    Returns:
        The :class:`~dqt.common.models.PipelineResult`.

    Example:
        result = _run(make_sqlite_db, tmp_path, "a.db")
    """
    db_file = make_sqlite_db(name, SEEDED)
    result, _ = DQTPipeline(
        ConnectionConfig(id="s", dsn=f"sqlite:///{db_file}"),
        config or DQPipelineConfig(connection_id="s"),
        store_path=tmp_path / "runs.db",
        report_dir=tmp_path,
    ).run()
    return result


def _patterns(result: object) -> list:
    """Return the missingness-pattern issues from a result.

    Args:
        result: A PipelineResult.

    Returns:
        The issues.

    Example:
        found = _patterns(result)
    """
    return [
        issue
        for issue in result.issues  # type: ignore[attr-defined]
        if "missing together" in issue.message
    ]


class TestItIsOffUnlessAskedFor:
    """A second full scan of a production table is a decision, not a default."""

    def test_nothing_is_reported_by_default(
        self, make_sqlite_db: Callable[[str, str], Path], tmp_path: Path
    ) -> None:
        """Profiling is already one deliberate pass; this would be a second."""
        assert _patterns(_run(make_sqlite_db, tmp_path, "patterns-off.db")) == []

    def test_no_grouping_query_runs_by_default(
        self, make_sqlite_db: Callable[[str, str], Path], tmp_path: Path
    ) -> None:
        """The claim that matters more than the absent issue.

        An implementation that computed the patterns and then declined to
        report them would cost exactly what this default exists to avoid.
        """
        db_file = make_sqlite_db("patterns-off-cost.db", SEEDED)
        statements = _traced(db_file, tmp_path, None)

        assert not [s for s in statements if "GROUP BY" in s.upper()]


class TestPatternsAreCounted:
    """The finding the null count cannot produce."""

    def test_columns_failing_together_are_reported_together(
        self, make_sqlite_db: Callable[[str, str], Path], tmp_path: Path
    ) -> None:
        """``email`` and ``phone`` are NULL in the same 3 rows.

        Each is 50% NULL on its own, which says nothing about whether they
        fail together. This is the whole point of the facet.
        """
        result = _run(
            make_sqlite_db,
            tmp_path,
            "patterns-on.db",
            DQPipelineConfig(connection_id="s", missingness=MissingnessConfig(enabled=True)),
        )
        found = _patterns(result)

        assert found
        message = found[0].message
        assert "email" in message
        assert "phone" in message
        assert "3" in message

    def test_a_pattern_of_one_column_is_not_reported(
        self, make_sqlite_db: Callable[[str, str], Path], tmp_path: Path
    ) -> None:
        """``note`` is NULL alone in one row, and that is just a null count.

        A single-column "pattern" restates what completeness already
        reported. Reporting it would double every null finding under a
        second dimension.
        """
        result = _run(
            make_sqlite_db,
            tmp_path,
            "patterns-single.db",
            DQPipelineConfig(connection_id="s", missingness=MissingnessConfig(enabled=True)),
        )

        assert not [issue for issue in _patterns(result) if "note" in issue.message]

    def test_rows_missing_nothing_are_not_a_pattern(
        self, make_sqlite_db: Callable[[str, str], Path], tmp_path: Path
    ) -> None:
        """Two rows have every value. That is the good case, not a finding.

        The ``GROUP BY`` returns it as the largest group, so an
        implementation that reported the most common pattern without
        excluding it would report "nothing is missing" as a problem on every
        healthy table.
        """
        result = _run(
            make_sqlite_db,
            tmp_path,
            "patterns-complete.db",
            DQPipelineConfig(connection_id="s", missingness=MissingnessConfig(enabled=True)),
        )

        for issue in _patterns(result):
            assert "0 column" not in issue.message


class TestTheQueryIsBounded:
    """One extra scan is the price. Two would not be."""

    def test_it_costs_one_grouping_query_per_table(
        self, make_sqlite_db: Callable[[str, str], Path], tmp_path: Path
    ) -> None:
        """Not one per column, and not one per pattern."""
        db_file = make_sqlite_db("patterns-cost.db", SEEDED)
        statements = _traced(db_file, tmp_path, MissingnessConfig(enabled=True))
        grouping = [s for s in statements if "GROUP BY" in s.upper()]

        assert len(grouping) == 1, f"expected one grouping query, got {len(grouping)}"

    def test_the_query_carries_a_limit(
        self, make_sqlite_db: Callable[[str, str], Path], tmp_path: Path
    ) -> None:
        """A wide table has exponentially many possible patterns.

        Twenty nullable columns admit a million of them. Reading them all
        back to report the top three is the failure `AGENTS.md` means by
        bounding evidence.
        """
        db_file = make_sqlite_db("patterns-limit.db", SEEDED)
        statements = _traced(db_file, tmp_path, MissingnessConfig(enabled=True, top_patterns=2))
        grouping = next(s for s in statements if "GROUP BY" in s.upper())

        assert "LIMIT 2" in grouping.upper()


def _traced(db_file: Path, tmp_path: Path, missingness: MissingnessConfig | None) -> list[str]:
    """Run the pipeline and return every statement SQLite executed.

    Args:
        db_file: The seeded database.
        tmp_path: Where the store and report go.
        missingness: Settings under test, or None for the defaults.

    Returns:
        The statements executed.

    Example:
        assert _traced(path, tmp, None)
    """
    import dqt.sql.missingness as missingness_module
    import dqt.sql.pipeline as pipeline_module
    import dqt.sql.profiling as profiling_module
    from dqt.sql._connect import get_connection as real_connect

    statements: list[str] = []

    def traced(*args: object, **kwargs: object) -> object:
        connection = real_connect(*args, **kwargs)  # type: ignore[arg-type]
        connection.set_trace_callback(statements.append)
        return connection

    config = DQPipelineConfig(connection_id="s")
    if missingness is not None:
        config = DQPipelineConfig(connection_id="s", missingness=missingness)

    patched = [pipeline_module, profiling_module, missingness_module]
    originals = {module: module.get_connection for module in patched}
    for module in patched:
        module.get_connection = traced  # type: ignore[attr-defined]
    try:
        DQTPipeline(
            ConnectionConfig(id="s", dsn=f"sqlite:///{db_file}"),
            config,
            store_path=tmp_path / "runs.db",
            report_dir=tmp_path,
        ).run()
    finally:
        for module, original in originals.items():
            module.get_connection = original  # type: ignore[attr-defined]

    assert statements, "nothing was traced, so any assertion here proves nothing"
    return statements
