"""Classification actually runs during a pipeline run (`F10`).

`classification.py` has been real, locale-aware, tested and publicly
exported for some time, and **nothing called it**. `ColumnResult` has carried
a `semantic_type` field the whole while, hard-coded to `None` at the one
place it is constructed. `dqt_competitors.md` records F10 as `PARTIAL` for
exactly that reason: a module existing is not a floor item met.

**Classification is the one stage that reads real values.** Everything else
in DQT aggregates inside the database and brings back numbers. A checksum
validator cannot work that way -- it has to see the value -- so this stage
genuinely pulls rows into Python, which makes two things load-bearing:

* **It is off by default.** Not because it is slow, but because of *what* it
  reads. The validators exist to recognise national IDs, IBANs and phone
  numbers, which is to say the stage is at its most useful exactly when the
  values are the ones you would least want copied anywhere. Turning that on
  should be a decision someone made.
* **It is one bounded query per table.** One `SELECT` over every candidate
  column at once, with a row limit -- not one query per column, and never an
  unbounded read. `AGENTS.md` "Performance rules" allows genuinely reading
  rows only when chunked or bounded.

The `db_type` assertion here is not about classification. It is a defect
found while threading the column's real type through for it: every
`ColumnResult` reported its database type as the string ``"ColumnProfile"``
-- the Python class name -- on the public model that the JSON API serves.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from dqt.common.models import ClassificationConfig, ConnectionConfig, DQPipelineConfig
from dqt.sql.pipeline import DQTPipeline

# Iranian national IDs are ten digits whose last is a checksum over the first
# nine: sum(d[i] * (10 - i)) for i in 0..8, r = sum % 11, and the check digit
# is r when r < 2, else 11 - r. These three were computed from that published
# rule by hand, not by asking DQT:
#   123456789 -> 210 % 11 = 1  -> check 1 -> 1234567891
#   987654321 -> 330 % 11 = 0  -> check 0 -> 9876543210
#   246813579 -> 240 % 11 = 9  -> check 11 - 9 = 2 -> 2468135792
SEEDED = """
    CREATE TABLE people (
        id INTEGER,
        contact TEXT,
        national_code TEXT,
        note TEXT
    );
    INSERT INTO people (id, contact, national_code, note) VALUES
        (1, 'ali@example.com',  '1234567891', 'first'),
        (2, 'sara@example.com', '9876543210', 'second'),
        (3, 'reza@example.com', '2468135792', 'third'),
        (4, 'mina@example.com', '1234567891', 'fourth');
"""


def _run(
    make_sqlite_db: Callable[[str, str], Path],
    tmp_path: Path,
    name: str,
    classification: ClassificationConfig | None = None,
) -> object:
    """Run the pipeline over the seeded table.

    Args:
        make_sqlite_db: Factory fixture building a SQLite file.
        tmp_path: pytest's per-test directory.
        name: Distinct database filename for this run.
        classification: Classification settings, or None for the defaults.

    Returns:
        The :class:`~dqt.common.models.PipelineResult`.

    Example:
        result = _run(make_sqlite_db, tmp_path, "a.db")
    """
    db_file = make_sqlite_db(name, SEEDED)
    config = DQPipelineConfig(connection_id="s")
    if classification is not None:
        config = DQPipelineConfig(connection_id="s", classification=classification)
    result, _ = DQTPipeline(
        ConnectionConfig(id="s", dsn=f"sqlite:///{db_file}"),
        config,
        store_path=tmp_path / "runs.db",
        report_dir=tmp_path,
    ).run()
    return result


def _columns(result: object) -> dict[str, object]:
    """Index a result's column results by column name.

    Args:
        result: A PipelineResult.

    Returns:
        Column name to :class:`~dqt.common.models.ColumnResult`.

    Example:
        assert _columns(result)["contact"].semantic_type == "email"
    """
    found: dict[str, object] = {}
    for table in result.tables.values():  # type: ignore[attr-defined]
        for column in table.columns:
            found[column.column_name] = column
    return found


class TestItIsOffUnlessAskedFor:
    """The default has to answer for what this stage reads, not what it costs."""

    def test_no_classification_happens_by_default(
        self, make_sqlite_db: Callable[[str, str], Path], tmp_path: Path
    ) -> None:
        """``semantic_type`` stays absent, exactly as before.

        Absent rather than ``"unknown"``: the column was never examined, and
        saying "unknown" would claim it was looked at and nothing matched.
        """
        columns = _columns(_run(make_sqlite_db, tmp_path, "off.db"))

        assert columns["contact"].semantic_type is None  # type: ignore[attr-defined]

    def test_no_rows_are_read_by_default(
        self, make_sqlite_db: Callable[[str, str], Path], tmp_path: Path
    ) -> None:
        """The claim that matters more than the field being None.

        DQT's whole position is that it computes inside the database. A
        default that quietly reads four columns of real values would
        contradict that whether or not anyone looked at the answer, so this
        watches the statements rather than the result.
        """
        db_file = make_sqlite_db("off-rows.db", SEEDED)
        statements = _traced_run(db_file, tmp_path, None)

        assert not [s for s in statements if "contact" in s and "COUNT" not in s.upper()], (
            f"a value-reading SELECT ran with classification off: {statements}"
        )


class TestWhenEnabledItClassifies:
    """The payoff: the validators finally see data."""

    def test_an_email_column_is_recognised(
        self, make_sqlite_db: Callable[[str, str], Path], tmp_path: Path
    ) -> None:
        """Four values, all addresses, so the match ratio is 1.0."""
        columns = _columns(
            _run(make_sqlite_db, tmp_path, "email.db", ClassificationConfig(enabled=True))
        )

        assert columns["contact"].semantic_type == "email"  # type: ignore[attr-defined]

    def test_an_iranian_national_id_column_is_recognised(
        self, make_sqlite_db: Callable[[str, str], Path], tmp_path: Path
    ) -> None:
        """The case that justifies the facet existing at all.

        These four values are three distinct checksum-valid national IDs and
        one repeat, computed from the published rule in this file's header.
        A generic profiler sees a ten-character text column; this is the
        difference.
        """
        columns = _columns(
            _run(make_sqlite_db, tmp_path, "nid.db", ClassificationConfig(enabled=True))
        )

        assert columns["national_code"].semantic_type == "iranian_national_id"  # type: ignore[attr-defined]

    def test_a_column_matching_nothing_is_unknown_rather_than_absent(
        self, make_sqlite_db: Callable[[str, str], Path], tmp_path: Path
    ) -> None:
        """``note`` holds prose. Examined and unmatched is a real answer.

        This is the pair to the default-off test: ``None`` means not looked
        at, ``"unknown"`` means looked at and nothing fit. Collapsing them
        would lose the only evidence that the stage ran.
        """
        columns = _columns(
            _run(make_sqlite_db, tmp_path, "unknown.db", ClassificationConfig(enabled=True))
        )

        assert columns["note"].semantic_type == "unknown"  # type: ignore[attr-defined]


class TestTheReadIsBoundedAndSingle:
    """Reading rows is allowed here; reading them badly is not."""

    def test_one_query_reads_every_column_at_once(
        self, make_sqlite_db: Callable[[str, str], Path], tmp_path: Path
    ) -> None:
        """Not one per column.

        Four columns costing four scans is the shape `AGENTS.md` forbids, and
        it returns exactly the same classifications -- so only a statement
        count can tell the difference.
        """
        db_file = make_sqlite_db("one-query.db", SEEDED)
        statements = _traced_run(db_file, tmp_path, ClassificationConfig(enabled=True))

        reads = [s for s in statements if "contact" in s and "COUNT" not in s.upper()]

        assert len(reads) == 1, f"expected one value read, got {len(reads)}: {reads}"

    def test_the_read_carries_a_row_limit(
        self, make_sqlite_db: Callable[[str, str], Path], tmp_path: Path
    ) -> None:
        """An unbounded read of a production table is the failure mode.

        The sample size is what keeps this stage's memory flat regardless of
        how large the table is.
        """
        db_file = make_sqlite_db("limit.db", SEEDED)
        statements = _traced_run(
            db_file, tmp_path, ClassificationConfig(enabled=True, sample_size=25)
        )

        read = next(s for s in statements if "contact" in s and "COUNT" not in s.upper())

        assert "LIMIT 25" in read.upper(), read


class TestTheColumnTypeIsTheDatabaseType:
    """A defect found while threading the type through, and fixed with it."""

    def test_it_is_not_the_python_class_name(
        self, make_sqlite_db: Callable[[str, str], Path], tmp_path: Path
    ) -> None:
        """Every ColumnResult reported ``db_type='ColumnProfile'``.

        That is the profiler's Python class name reaching the public model
        the JSON API serves, in a field documented as the column's database
        type.
        """
        columns = _columns(_run(make_sqlite_db, tmp_path, "dbtype.db"))

        assert columns["id"].db_type != "ColumnProfile"  # type: ignore[attr-defined]

    def test_it_is_what_the_database_declared(
        self, make_sqlite_db: Callable[[str, str], Path], tmp_path: Path
    ) -> None:
        """Read off the CREATE TABLE in this file, not off the code."""
        columns = _columns(_run(make_sqlite_db, tmp_path, "dbtype2.db"))

        assert columns["id"].db_type.upper() == "INTEGER"  # type: ignore[attr-defined]
        assert columns["contact"].db_type.upper() == "TEXT"  # type: ignore[attr-defined]


def _traced_run(
    db_file: Path, tmp_path: Path, classification: ClassificationConfig | None
) -> list[str]:
    """Run the pipeline and return every SELECT SQLite executed.

    Taken from SQLite's own trace callback rather than from inside DQT, so a
    query issued by a route the test did not anticipate is still counted.

    Every module that opens connections is patched, not just one. Each does
    ``from dqt.sql._connect import get_connection``, which binds the name at
    import time -- so patching the source module alone changes nothing the
    pipeline calls, and the trace silently attaches to no connection at all.
    That is worse than a broken test: an assertion that *no* value-reading
    query ran passes trivially when no query was recorded. The empty-trace
    guard below is what makes that impossible to miss again.

    Args:
        db_file: The seeded database.
        tmp_path: Where the store and report go.
        classification: Settings under test, or None for the defaults.

    Returns:
        The SELECT statements executed, in order.

    Example:
        assert len(_traced_run(path, tmp, None)) >= 1
    """
    import dqt.sql.pipeline as pipeline_module
    import dqt.sql.profiling as profiling_module
    import dqt.sql.rules as rules_module
    import dqt.sql.schema_discovery as discovery_module
    import dqt.sql.semantic_typing as semantic_typing_module
    from dqt.sql._connect import get_connection as real_connect

    patched = [
        pipeline_module,
        profiling_module,
        rules_module,
        discovery_module,
        semantic_typing_module,
    ]

    statements: list[str] = []

    def traced(*args: object, **kwargs: object) -> object:
        connection = real_connect(*args, **kwargs)  # type: ignore[arg-type]
        connection.set_trace_callback(statements.append)
        return connection

    config = DQPipelineConfig(connection_id="s")
    if classification is not None:
        config = DQPipelineConfig(connection_id="s", classification=classification)

    originals = {m: getattr(m, "get_connection", None) for m in patched}
    for module in patched:
        if originals[module] is not None:
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
            if original is not None:
                module.get_connection = original  # type: ignore[attr-defined]

    selects = [s for s in statements if s.strip().upper().startswith("SELECT")]

    assert selects, (
        "the trace recorded no SELECT at all, so any assertion about which "
        "queries ran would pass without meaning anything"
    )
    return selects


class TestTheReportShowsTheTypes:
    """A semantic type nobody sees is the state `F10` was already in."""

    def test_the_database_type_is_a_column_in_the_report(
        self, make_sqlite_db: Callable[[str, str], Path], tmp_path: Path
    ) -> None:
        """It was never shown, which is partly why the defect survived.

        ``db_type`` held the string ``"ColumnProfile"`` on every column for
        as long as it existed, and nothing rendered it -- so nobody read the
        wrong value and nobody reported it.
        """
        html = _report(make_sqlite_db, tmp_path, "report-type.db", None)

        assert "Type" in html
        assert ">TEXT<" in html.upper()

    def test_a_recognised_column_says_what_it_is(
        self, make_sqlite_db: Callable[[str, str], Path], tmp_path: Path
    ) -> None:
        """The payoff of the facet, in the artifact a DBA is sent.

        "This ten-character text column is a national ID" is the sentence a
        generic profiler cannot produce.
        """
        html = _report(
            make_sqlite_db, tmp_path, "report-sem.db", ClassificationConfig(enabled=True)
        )

        assert "iranian_national_id" in html
        assert "email" in html

    def test_an_unclassified_run_shows_no_semantic_claim(
        self, make_sqlite_db: Callable[[str, str], Path], tmp_path: Path
    ) -> None:
        """With classification off, the cell must not invent one.

        ``n/a`` is reused here for the same reason the statistic cells use
        it: the column was not examined, and a blank would read as a finding.
        """
        html = _report(make_sqlite_db, tmp_path, "report-nosem.db", None)

        assert "iranian_national_id" not in html
        assert "n/a" in html


def _report(
    make_sqlite_db: Callable[[str, str], Path],
    tmp_path: Path,
    name: str,
    classification: ClassificationConfig | None,
) -> str:
    """Run the pipeline and return the rendered HTML report.

    Args:
        make_sqlite_db: Factory fixture building a SQLite file.
        tmp_path: pytest's per-test directory.
        name: Distinct database filename.
        classification: Settings, or None for the defaults.

    Returns:
        The report's HTML.

    Example:
        assert "Type" in _report(make_sqlite_db, tmp_path, "a.db", None)
    """
    db_file = make_sqlite_db(name, SEEDED)
    config = DQPipelineConfig(connection_id="s")
    if classification is not None:
        config = DQPipelineConfig(connection_id="s", classification=classification)
    _, report_path = DQTPipeline(
        ConnectionConfig(id="s", dsn=f"sqlite:///{db_file}"),
        config,
        store_path=tmp_path / "runs.db",
        report_dir=tmp_path,
    ).run()
    return Path(str(report_path)).read_text(encoding="utf-8")
