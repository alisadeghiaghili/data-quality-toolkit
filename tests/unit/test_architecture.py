"""Structural tests for `DQT-08`'s single-authority guarantees.

These check the shape of the source tree, not its runtime behaviour, so they
keep holding when a future change is correct but reintroduces a second
authority. They are the plain-test stand-in for the checks
``tools/arch_audit.py`` will automate under `ARC-01`; when that tool lands,
these should become its seed cases rather than being deleted.
"""

from __future__ import annotations

import ast
import pathlib
import tomllib

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_SOURCE_ROOT = _REPO_ROOT / "src" / "dqt"

# Every database driver DQT may ever import, by module name.
_DRIVER_MODULES = frozenset({"sqlite3", "psycopg", "psycopg2", "pyodbc", "pymssql"})

# Modules permitted to import a driver, as paths relative to src/dqt.
#
# - sql/dialects/*   : the adapter layer. A dialect owning its own driver is
#                      the whole point of the abstraction; the alternative is
#                      _connect.py branching on database to choose an import,
#                      which is the inline branching this package removes.
# - common/storage.py: RunStore opens DQT's *own* results database, which must
#                      stay writable. The roadmap's DQT-08 body excludes it by
#                      name from the user-database consolidation.
_DRIVER_IMPORT_ALLOWLIST = frozenset(
    {
        "sql/dialects/base.py",
        "sql/dialects/__init__.py",
        "sql/dialects/sqlite.py",
        "sql/dialects/postgresql.py",
        "sql/dialects/sqlserver.py",
        "common/storage.py",
    }
)


def _imported_modules(path: pathlib.Path) -> set[str]:
    """Return the top-level module names *path* imports, at any nesting depth."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imported.add(node.module.split(".")[0])
    return imported


def _source_files() -> list[pathlib.Path]:
    return sorted(_SOURCE_ROOT.rglob("*.py"))


class TestDriverBoundary:
    def test_only_the_dialects_package_imports_a_database_driver(self):
        offenders = {}
        for path in _source_files():
            relative = path.relative_to(_SOURCE_ROOT).as_posix()
            if relative in _DRIVER_IMPORT_ALLOWLIST:
                continue
            drivers = _imported_modules(path) & _DRIVER_MODULES
            if drivers:
                offenders[relative] = sorted(drivers)
        assert offenders == {}, (
            "only dqt.sql.dialects (and common/storage.py, DQT's own results "
            f"database) may import a driver; found {offenders}"
        )

    def test_the_allowlist_names_only_files_that_exist(self):
        # A stale allowlist entry would silently excuse a file that no longer
        # exists while a renamed one slipped through.
        missing = [name for name in _DRIVER_IMPORT_ALLOWLIST if not (_SOURCE_ROOT / name).exists()]
        assert missing == []

    def test_no_dialect_imports_its_optional_driver_at_module_scope(self):
        """Importing dqt must not require psycopg or pyodbc to be installed.

        Only the top level of each dialect module is inspected: a driver
        import nested inside a function body is exactly the intended shape.
        """
        for name in ("postgresql.py", "sqlserver.py"):
            path = _SOURCE_ROOT / "sql" / "dialects" / name
            tree = ast.parse(path.read_text(encoding="utf-8"))
            top_level: set[str] = set()
            for node in tree.body:
                if isinstance(node, ast.Import):
                    top_level.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    top_level.add(node.module.split(".")[0])
            assert not (top_level & _DRIVER_MODULES), (
                f"{name} imports a driver at module scope; import it inside connect() instead"
            )


class TestDialectDispatchIsNotDuplicated:
    def test_no_module_outside_dialects_branches_on_a_dialect_name(self):
        """Only the dialects package may compare against a dialect name.

        This is the check that stops the old shape growing back: before
        `DQT-08`, ``rules.py`` tested ``dialect in ("postgresql", "postgres")``
        and ``schema_discovery.py`` tested DSN prefixes, so adding a third
        database meant editing every such site.

        Detection is over the AST, not the source text, and that distinction
        is the point. A textual scan cannot tell a comparison from a docstring
        that merely names a dialect, so it would forbid documenting which
        databases a function supports -- which is not an architectural
        property and would push the codebase toward vaguer docs to satisfy a
        test. Comparisons are what couple a module to a dialect; prose does
        not.
        """
        names = {"sqlite", "postgresql", "postgres", "sqlserver", "mssql"}
        offenders = []
        for path in _source_files():
            relative = path.relative_to(_SOURCE_ROOT).as_posix()
            if relative.startswith("sql/dialects/"):
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                literals: list[str] = []
                if isinstance(node, ast.Compare):
                    for operand in node.comparators:
                        if isinstance(operand, ast.Constant) and operand.value in names:
                            literals.append(operand.value)
                        elif isinstance(operand, ast.Tuple | ast.List | ast.Set):
                            literals += [
                                e.value
                                for e in operand.elts
                                if isinstance(e, ast.Constant) and e.value in names
                            ]
                elif (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    # dsn.startswith("postgresql://") and friends.
                    and node.func.attr in {"startswith", "endswith"}
                ):
                    literals += [
                        a.value.split(":")[0]
                        for a in node.args
                        if isinstance(a, ast.Constant)
                        and isinstance(a.value, str)
                        and a.value.split(":")[0] in names
                    ]
                if literals:
                    offenders.append(f"{relative}:{node.lineno}: {sorted(set(literals))}")
        assert offenders == [], f"dialect-name branching outside dqt.sql.dialects: {offenders}"


class TestPackagingDeclaresOneDriverPerDatabase:
    def test_exactly_one_postgres_driver_in_the_postgres_extra(self):
        pyproject = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        extras = pyproject["project"]["optional-dependencies"]["postgres"]
        drivers = [name for name in extras if name.startswith(("psycopg[", "psycopg2", "psycopg>"))]
        assert len(drivers) == 1, (
            f"exactly one PostgreSQL driver must be declared (DQT-08), found {drivers}"
        )
        assert drivers[0].startswith("psycopg["), "psycopg (v3) is the chosen driver, not psycopg2"

    def test_sqlserver_driver_is_an_optional_extra(self):
        pyproject = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        extras = pyproject["project"]["optional-dependencies"]
        assert "sqlserver" in extras
        assert any(name.startswith("pyodbc") for name in extras["sqlserver"])

    def test_no_driver_is_a_required_dependency(self):
        pyproject = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        required = pyproject["project"]["dependencies"]
        assert not [name for name in required if name.startswith(("psycopg", "pyodbc", "pymssql"))]


class TestProfilingCannotMutate:
    """Q1, settled 2026-08-26: `run()` must be structurally incapable of writing.

    Not "defaults to off", not "guarded by a flag" -- incapable. A read-only
    guard is a single point of failure, and `ENGINEERING-STANDARDS.md` §1.4's
    reasoning is that a profiling run pointed at production should not have a
    write path in its call graph at all, so that no future edit, config toggle
    or default change can open one.
    """

    def test_the_pipeline_module_does_not_import_a_cleansing_entry_point(self):
        """`pipeline.py` cannot reach plan or apply, by import.

        Import is the cheapest place to enforce this and the hardest to
        subvert by accident: a later contributor adding a cleansing call to
        `run()` has to add an import first, and this fails on the import.
        """
        source = (_SOURCE_ROOT / "sql" / "pipeline.py").read_text(encoding="utf-8")
        tree = ast.parse(source)

        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").endswith("cleansing"):
                imported += [alias.name for alias in node.names]

        forbidden = {"cleanse_plan", "cleanse_apply", "apply_cleansing", "revert", "cleanse"}
        assert not (set(imported) & forbidden), (
            f"pipeline.py imports a cleansing entry point: {sorted(set(imported) & forbidden)}. "
            "Q1 requires run()'s call graph to contain no path that mutates."
        )

    def test_the_pipeline_has_no_cleanse_stage(self):
        """`DQTPipeline` exposes no cleansing method at all.

        A `cleanse()` method that happens to be a no-op today is still a
        method a caller can find, and still a place a future edit can fill in.
        """
        from dqt.sql.pipeline import DQTPipeline

        assert not hasattr(DQTPipeline, "cleanse")
