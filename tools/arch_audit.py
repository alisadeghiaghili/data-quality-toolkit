"""Check the shape of the source tree against DQT's architecture rules.

`CLAUDE.md` §2 states them in prose: dependencies point inward, the facets
module layout is the boundary, I/O stays at the edges, `missingly` is reached
only through a bridge. Prose is where a rule goes to be forgotten — this is
where it goes to be checked.

Every rule here is structural: it reads the import graph and the source text
with ``ast``, never imports the package, and never runs a query. That is what
lets it hold on a machine with no database and no optional driver installed,
and what makes a violation a fact about the tree rather than about the run.

`tests/unit/test_architecture.py` was the plain-test stand-in for this tool
and said so in its own docstring. Its cases seeded these rules.

**There is no baseline.** `DOC-02` deleted the documentation one for the
reason that applies here too: a list of tolerated exceptions is where the
next violation gets filed instead of fixed.

Run it::

    python tools/arch_audit.py --root . --path src/dqt

Example:
    python tools/arch_audit.py
"""

from __future__ import annotations

import argparse
import ast
import pathlib
import sys
from collections.abc import Iterator
from dataclasses import dataclass

#: Every database driver DQT may ever import, by top-level module name.
DRIVER_MODULES = frozenset({"sqlite3", "psycopg", "psycopg2", "pyodbc", "pymssql"})

#: Modules permitted to import a driver, relative to the package root.
#:
#: ``sql/dialects/*`` is the adapter layer, and a dialect owning its driver is
#: the point of the abstraction — the alternative is one module branching on
#: database to choose an import, which is what the package removed.
#: ``common/storage.py`` opens DQT's *own* results database, which must stay
#: writable and is excluded by name from `DQT-08`'s consolidation.
DRIVER_ALLOWLIST = frozenset(
    {
        "sql/dialects/base.py",
        "sql/dialects/__init__.py",
        "sql/dialects/sqlite.py",
        "sql/dialects/postgresql.py",
        "sql/dialects/sqlserver.py",
        "common/storage.py",
    }
)

#: Layers, innermost first. A module may import its own layer and any layer
#: before it, never one after.
#:
#: The names are not decoration: "domain" is what DQT knows about data
#: quality, "persistence" is where a run is written down, "adapters" are what
#: talk to somebody else's database, and "entrypoints" are what a person
#: invokes. A dependency pointing the other way means the thing that knows
#: what a metric *is* has been made to care how one is stored.
LAYERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "domain",
        (
            "models.py",
            "config_loader.py",
            "classification.py",
            "exceptions.py",
            "exit_codes.py",
            "i18n.py",
            "viz.py",
            "_html.py",
            "_theme.py",
            "_version.py",
            "fonts/",
        ),
    ),
    ("persistence", ("common/storage.py",)),
    ("adapters", ("sql/", "bridges/")),
    ("entrypoints", ("cli.py", "__main__.py", "ui/", "__init__.py")),
)

#: Dialect names that must not be branched on outside the dialects package.
DIALECT_NAMES = ("sqlite", "postgresql", "postgres", "sqlserver", "mssql")


@dataclass(frozen=True, slots=True)
class Violation:
    """One architectural rule broken in one place.

    Attributes:
        rule: Short name of the rule, so a failure can be looked up.
        path: File that broke it, relative to the package root.
        detail: What was found, in terms a reader can act on.

    Example:
        Violation(rule="inward", path="common/storage.py", detail="imports dqt.sql")
    """

    rule: str
    path: str
    detail: str


def _relative(path: pathlib.Path, root: pathlib.Path) -> str:
    """Return *path* relative to *root*, POSIX-style.

    Args:
        path: The file.
        root: The package root.

    Returns:
        A forward-slash path, so a rule reads the same on every platform.

    Example:
        assert _relative(root / "a" / "b.py", root) == "a/b.py"
    """
    return path.relative_to(root).as_posix()


def _dqt_imports(tree: ast.Module) -> set[str]:
    """Return the ``dqt.*`` modules a parsed file imports.

    Deferred imports count. A dependency moved inside a function is still a
    dependency — it is only hidden from a reader, which makes it worse rather
    than better.

    Args:
        tree: The parsed module.

    Returns:
        Dotted module names.

    Example:
        assert "dqt.common.models" in _dqt_imports(tree)
    """
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            if node.module.startswith("dqt"):
                found.add(node.module)
        elif isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names if alias.name.startswith("dqt"))
    return found


def _third_party_imports(tree: ast.Module) -> set[str]:
    """Return the top-level non-``dqt`` modules a parsed file imports.

    Args:
        tree: The parsed module.

    Returns:
        Top-level module names.

    Example:
        assert "sqlite3" in _third_party_imports(tree)
    """
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module.split(".")[0])
    return {name for name in found if not name.startswith("dqt")}


def _layer_of(relative_path: str) -> str | None:
    """Return the layer *relative_path* belongs to.

    Args:
        relative_path: A path relative to the package root.

    Returns:
        The layer name, or None when the file belongs to none — a package
        ``__init__`` that only re-exports, for instance.

    Example:
        assert _layer_of("sql/rules.py") == "adapters"
    """
    for layer, patterns in LAYERS:
        for pattern in patterns:
            if pattern.endswith("/"):
                if relative_path.startswith(pattern):
                    return layer
            elif relative_path == pattern or relative_path.endswith("/" + pattern):
                return layer
    return None


def _module_to_path(module: str) -> str:
    """Turn a dotted ``dqt.*`` module name into a path-like string.

    Args:
        module: A dotted module name.

    Returns:
        The path form, without an extension.

    Example:
        assert _module_to_path("dqt.sql.rules") == "sql/rules"
    """
    return module.removeprefix("dqt").lstrip(".").replace(".", "/")


def _layer_of_module(module: str) -> str | None:
    """Return the layer an imported ``dqt.*`` module belongs to.

    Args:
        module: A dotted module name.

    Returns:
        The layer name, or None.

    Example:
        assert _layer_of_module("dqt.sql.rules") == "adapters"
    """
    as_path = _module_to_path(module)
    return _layer_of(f"{as_path}.py") or _layer_of(f"{as_path}/")


def check_drivers(relative_path: str, tree: ast.Module) -> Iterator[Violation]:
    """Refuse a database driver imported outside the dialects package.

    Two authorities on how to open a connection is how one of them ends up
    ignoring ``read_only`` — the defect `DQT-08` existed to remove.

    Args:
        relative_path: The file being checked.
        tree: Its parsed source.

    Yields:
        One violation per driver imported where it may not be.

    Example:
        list(check_drivers("sql/rules.py", tree))
    """
    if relative_path in DRIVER_ALLOWLIST:
        return
    for driver in sorted(_third_party_imports(tree) & DRIVER_MODULES):
        yield Violation(
            rule="driver-boundary",
            path=relative_path,
            detail=(
                f"imports the driver {driver!r}. Only sql/dialects/* and "
                "common/storage.py may; everything else goes through a dialect."
            ),
        )


def check_inward(relative_path: str, tree: ast.Module) -> Iterator[Violation]:
    """Refuse a dependency that points outward.

    Args:
        relative_path: The file being checked.
        tree: Its parsed source.

    Yields:
        One violation per import of a layer further out than this file's.

    Example:
        list(check_inward("common/storage.py", tree))
    """
    order = [name for name, _ in LAYERS]
    own_layer = _layer_of(relative_path)
    if own_layer is None:
        return
    own_rank = order.index(own_layer)

    for module in sorted(_dqt_imports(tree)):
        imported_layer = _layer_of_module(module)
        if imported_layer is None:
            continue
        if order.index(imported_layer) > own_rank:
            yield Violation(
                rule="inward",
                path=relative_path,
                detail=(
                    f"is {own_layer} and imports {module} ({imported_layer}). "
                    "Dependencies point inward: an inner layer that knows about "
                    "an outer one cannot be tested or reused without it."
                ),
            )


def check_dialect_branching(relative_path: str, tree: ast.Module) -> Iterator[Violation]:
    """Refuse dialect-name branching outside the dialects package.

    A second place that decides what SQLite needs is a second place to update
    when a third database arrives, and the one nobody remembers.

    Args:
        relative_path: The file being checked.
        tree: Its parsed source.

    Yields:
        One violation per comparison against a dialect name.

    Example:
        list(check_dialect_branching("sql/rules.py", tree))
    """
    if relative_path.startswith("sql/dialects/"):
        return
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        for comparator in node.comparators:
            if (
                isinstance(comparator, ast.Constant)
                and isinstance(comparator.value, str)
                and comparator.value.lower() in DIALECT_NAMES
            ):
                yield Violation(
                    rule="dialect-branching",
                    path=relative_path,
                    detail=(
                        f"compares against the dialect name "
                        f"{comparator.value!r} on line {node.lineno}. Ask the "
                        "dialect instead; that is what it is for."
                    ),
                )


def check_missingly(relative_path: str, tree: ast.Module) -> Iterator[Violation]:
    """Refuse ``missingly`` anywhere but the bridge.

    `CLAUDE.md` §1: DQT must be fully usable without it. An import outside
    ``bridges/`` makes an optional sibling a hard dependency of whatever
    module reached for it.

    Args:
        relative_path: The file being checked.
        tree: Its parsed source.

    Yields:
        One violation if the file imports ``missingly``.

    Example:
        list(check_missingly("sql/profiling.py", tree))
    """
    if relative_path.startswith("bridges/"):
        return
    if "missingly" in _third_party_imports(tree):
        yield Violation(
            rule="missingly-bridge",
            path=relative_path,
            detail=(
                "imports 'missingly'. It is an independent sibling reachable "
                "only through bridges/, so that DQT stays usable without it."
            ),
        )


def check_viz_purity(relative_path: str, tree: ast.Module) -> Iterator[Violation]:
    """Refuse I/O or database knowledge in the visualisation facet.

    ``viz.py`` turns numbers into shapes. A chart module that can read a
    database is one that will, and then a report cannot be rendered from
    stored results alone.

    Args:
        relative_path: The file being checked.
        tree: Its parsed source.

    Yields:
        One violation per forbidden import.

    Example:
        list(check_viz_purity("viz.py", tree))
    """
    if relative_path != "viz.py":
        return
    forbidden = _third_party_imports(tree) & (DRIVER_MODULES | {"requests", "httpx"})
    for name in sorted(forbidden):
        yield Violation(
            rule="viz-purity",
            path=relative_path,
            detail=f"imports {name!r}; the visualisation facet takes numbers, not sources.",
        )
    for module in sorted(_dqt_imports(tree)):
        if module.startswith("dqt.sql") or module.startswith("dqt.ui"):
            yield Violation(
                rule="viz-purity",
                path=relative_path,
                detail=f"imports {module}; the visualisation facet knows nothing about SQL.",
            )


def check_pipeline_cannot_cleanse(relative_path: str, tree: ast.Module) -> Iterator[Violation]:
    """Refuse a cleansing entry point reachable from the pipeline.

    `Q1` made cleansing structurally unreachable from ``run()`` rather than
    unreachable by default. A flag can be flipped; an import that does not
    exist cannot.

    Args:
        relative_path: The file being checked.
        tree: Its parsed source.

    Yields:
        One violation if the pipeline imports cleansing.

    Example:
        list(check_pipeline_cannot_cleanse("sql/pipeline.py", tree))
    """
    if relative_path != "sql/pipeline.py":
        return
    for module in sorted(_dqt_imports(tree)):
        if module.startswith("dqt.sql.cleansing"):
            yield Violation(
                rule="no-cleansing-from-run",
                path=relative_path,
                detail=(
                    f"imports {module}. run() must not be able to reach a write; "
                    "that is structural, not a default."
                ),
            )


def audit(package_root: pathlib.Path) -> list[Violation]:
    """Run every rule over every source file.

    Args:
        package_root: The package to check, e.g. ``src/dqt``.

    Returns:
        Every violation found, ordered by file then rule.

    Example:
        assert audit(pathlib.Path("src/dqt")) == []
    """
    found: list[Violation] = []
    for path in sorted(package_root.rglob("*.py")):
        relative_path = _relative(path, package_root)
        tree = ast.parse(path.read_text(encoding="utf-8"))

        found.extend(check_drivers(relative_path, tree))
        found.extend(check_inward(relative_path, tree))
        found.extend(check_dialect_branching(relative_path, tree))
        found.extend(check_missingly(relative_path, tree))
        found.extend(check_viz_purity(relative_path, tree))
        found.extend(check_pipeline_cannot_cleanse(relative_path, tree))
    return sorted(found, key=lambda violation: (violation.path, violation.rule))


def main() -> int:
    """Audit the tree and report.

    Returns:
        0 when the tree is clean, 1 otherwise.

    Example:
        raise SystemExit(main())
    """
    parser = argparse.ArgumentParser(description="Check DQT's architecture rules.")
    parser.add_argument("--root", default=".", help="Repository root.")
    parser.add_argument("--path", default="src/dqt", help="Package to audit.")
    arguments = parser.parse_args()

    package_root = pathlib.Path(arguments.root).resolve() / arguments.path
    violations = audit(package_root)

    print(f"arch_audit: {len(violations)} violation(s)")
    for violation in violations:
        print(f"  {violation.path}: [{violation.rule}] {violation.detail}")
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
