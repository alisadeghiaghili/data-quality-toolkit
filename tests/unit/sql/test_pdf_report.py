"""A printable PDF report (`F12`).

The last floor row. It stayed open longest on purpose: every PDF library is
a heavy dependency, and a lean footprint is one of only three
differentiators `dqt_competitors.md` credits DQT with. The answer is an
**extra** -- `pip install "dqt[pdf]"` -- so nobody who does not want a PDF
pays for one.

**Persian has to survive, or the feature is worse than not having it.**
Bilingual EN/FA reporting is another of those three differentiators, and
Arabic-script text that renders as disconnected letters in the wrong order
is not a report, it is a bug with a page count. The font already embedded
for the HTML report is reused -- converted from `woff2` at runtime by
`fonttools`, which the PDF library already depends on, so no new asset ships
and the two reports cannot disagree about which typeface they are.

**The content is not duplicated.** `AGENTS.md` forbids that, and it would
matter here: two renderers each deciding which columns to show is two places
to change when a statistic is added, and one of them will be forgotten. The
row builders are shared; only the rendering differs.

**A missing extra is refused, not degraded.** Writing a PDF without the
embedded font, or without shaping, would produce a file that opens and is
wrong -- which is harder to notice than a file that was never written.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from dqt.common.models import ConnectionConfig, DQPipelineConfig
from dqt.sql.pipeline import DQTPipeline
from dqt.sql.reports import generate_pdf_report

pytest.importorskip("fpdf", reason="the pdf extra is not installed")

SEEDED = """
    CREATE TABLE customers (id INTEGER PRIMARY KEY, email TEXT, city TEXT);
    INSERT INTO customers (id, email, city) VALUES
        (1, 'ali@example.com', 'Tehran'),
        (2, NULL,              'tehran'),
        (3, 'reza@example.com', NULL);
"""


@pytest.fixture
def result(make_sqlite_db: Callable[[str, str], Path], tmp_path: Path) -> object:
    """Run the pipeline once and return the result.

    Args:
        make_sqlite_db: Factory fixture building a SQLite file.
        tmp_path: pytest's per-test directory.

    Returns:
        The :class:`~dqt.common.models.PipelineResult`.

    Example:
        assert result.run_id
    """
    db_file = make_sqlite_db("pdf.db", SEEDED)
    completed, _ = DQTPipeline(
        ConnectionConfig(id="s", dsn=f"sqlite:///{db_file}"),
        DQPipelineConfig(connection_id="s"),
        store_path=tmp_path / "runs.db",
        report_dir=tmp_path,
    ).run()
    return completed


def _text_of(pdf_path: Path) -> str:
    """Extract the text a reader would see from a PDF.

    Read back through a real PDF parser rather than checked against the
    bytes written, so an assertion cannot pass on a file that happens to
    contain the right characters somewhere without displaying them.

    Args:
        pdf_path: The generated file.

    Returns:
        The extracted text of every page.

    Example:
        assert "DQT" in _text_of(path)
    """
    pypdf = pytest.importorskip("pypdf", reason="pypdf is needed to read the PDF back")
    reader = pypdf.PdfReader(str(pdf_path))
    return "\n".join(page.extract_text() for page in reader.pages)


class TestAPdfIsWritten:
    """The artifact exists, opens, and says what the run found."""

    def test_it_produces_a_readable_file(self, result: object, tmp_path: Path) -> None:
        """A PDF that no reader can parse is not a report."""
        path = generate_pdf_report(result, tmp_path / "report.pdf")  # type: ignore[arg-type]

        assert path.exists()
        assert path.read_bytes().startswith(b"%PDF-")

    def test_it_names_the_run(self, result: object, tmp_path: Path) -> None:
        """Without the run id, two reports on a desk are indistinguishable."""
        text = _text_of(generate_pdf_report(result, tmp_path / "named.pdf"))  # type: ignore[arg-type]

        assert result.run_id in text  # type: ignore[attr-defined]

    def test_it_carries_the_findings(self, result: object, tmp_path: Path) -> None:
        """The fixture has one NULL email and one NULL city.

        Asserted on the extracted text, so a report that rendered an empty
        table would fail rather than pass on having the right headings.
        """
        text = _text_of(generate_pdf_report(result, tmp_path / "findings.pdf"))  # type: ignore[arg-type]

        assert "customers" in text
        assert "email" in text

    def test_it_defaults_its_own_filename(self, result: object, tmp_path: Path) -> None:
        """Matching ``generate_html_report``, so the two behave alike."""
        path = generate_pdf_report(result, tmp_path)  # type: ignore[arg-type]

        assert path.name.endswith(".pdf")
        assert result.run_id in path.name  # type: ignore[attr-defined]


class TestPersianSurvives:
    """Bilingual reporting is a differentiator, or it is a liability."""

    def test_persian_text_round_trips(self, result: object, tmp_path: Path) -> None:
        """Arabic-script letters must come back as themselves.

        Extracted through a PDF parser, so this fails if the glyphs were
        embedded without a correct ``ToUnicode`` mapping -- the failure mode
        where a document looks right on screen and yields mojibake when
        copied, searched, or read by anything but a human eye.
        """
        path = generate_pdf_report(
            result,  # type: ignore[arg-type]
            tmp_path / "fa.pdf",
            language="fa",
        )
        text = _text_of(path)

        # "گزارش" -- the word for "report".
        assert "گزارش" in text

    def test_the_font_is_embedded(self, result: object, tmp_path: Path) -> None:
        """A PDF that relies on the reader having Vazirmatn is not portable.

        The HTML report embeds the font for exactly this reason; a PDF that
        did not would render Persian as boxes on any machine without it.
        """
        path = generate_pdf_report(
            result,  # type: ignore[arg-type]
            tmp_path / "embedded.pdf",
            language="fa",
        )

        assert b"FontFile2" in path.read_bytes()

    def test_english_is_unaffected(self, result: object, tmp_path: Path) -> None:
        """The control. Shaping must not disturb Latin text."""
        text = _text_of(generate_pdf_report(result, tmp_path / "en.pdf"))  # type: ignore[arg-type]

        assert "Data Quality" in text


class TestTheContentIsShared:
    """Two renderers deciding what to show is two places to forget."""

    def test_both_reports_describe_the_same_columns(self, result: object, tmp_path: Path) -> None:
        """A statistic added to one must appear in the other.

        Not a rendering comparison -- the two look nothing alike -- but a
        check that the *selection* is one decision. When `F1` added the mean
        and the distinct count, a second hand-maintained column list would
        have been the place they went missing.
        """
        from dqt.sql.reports import column_rows

        rows = column_rows(result)  # type: ignore[arg-type]
        text = _text_of(generate_pdf_report(result, tmp_path / "shared.pdf"))  # type: ignore[arg-type]

        assert rows, "no columns were described at all"
        for column_name in {row.column_name for row in rows}:
            assert column_name in text, f"{column_name} is in the shared rows but not the PDF"


class TestAMissingExtraIsRefused:
    """A PDF that opens and is wrong is worse than one that was never written."""

    def test_it_names_the_extra_rather_than_failing_obscurely(
        self, result: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The pattern `pyodbc` already uses for the SQL Server driver.

        A bare ``ModuleNotFoundError: fpdf`` tells a DBA nothing about what
        to install.

        The import itself is made to fail, rather than the wrapper that
        translates it. The first version of this test replaced
        ``_import_pdf_backend`` -- which is the function doing the
        translating, so it asserted nothing about the behaviour it named.
        """
        import sys

        monkeypatch.setitem(sys.modules, "fpdf", None)

        with pytest.raises(Exception, match=r"dqt\[pdf\]"):
            generate_pdf_report(result, tmp_path / "missing.pdf")  # type: ignore[arg-type]
