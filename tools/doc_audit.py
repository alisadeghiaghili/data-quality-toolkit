#!/usr/bin/env python3
"""Enforce the docstring standard from ``ENGINEERING-STANDARDS.md`` §2.

This is a CI gate, not a linter suggestion: it exits non-zero when any public
symbol is missing a section the standard requires for its kind. It understands
both Google-style (``Args:``/``Returns:``) and NumPy/numpydoc-style
(``Parameters``/``Returns`` underlined) docstrings, and is configured per repo
so that a repo's existing convention is enforced rather than replaced.

The check is deliberately structural, not stylistic. It verifies that a section
exists and that every parameter is named in it. It cannot verify that the prose
is *true* -- that is what ``tools/claim_audit.py`` and the doc-vs-code integrity
rule (§2.3) are for.

Usage
-----
::

    python tools/doc_audit.py                    # audit configured package, cwd repo
    python tools/doc_audit.py --path src/dqt --style google --require-example
    python tools/doc_audit.py --baseline .doc_audit_baseline.json   # ratchet mode

Exit codes
----------
0
    No violations above the baseline.
1
    One or more violations.
2
    Configuration or usage error.
"""

from __future__ import annotations

import argparse
import ast
import json
import pathlib
import re
import sys
from dataclasses import dataclass, field
from typing import Iterable, Literal

Style = Literal["google", "numpy"]

# --------------------------------------------------------------------------
# Section detection
# --------------------------------------------------------------------------

_GOOGLE_SECTIONS = {
    "params": re.compile(r"^\s*(Args|Arguments|Parameters)\s*:\s*$", re.M),
    "returns": re.compile(r"^\s*(Returns|Yields)\s*:\s*$", re.M),
    "raises": re.compile(r"^\s*Raises\s*:\s*$", re.M),
    "example": re.compile(r"^\s*Examples?\s*:?:?\s*$", re.M),
    "attributes": re.compile(r"^\s*Attributes\s*:\s*$", re.M),
}

_NUMPY_SECTIONS = {
    "params": re.compile(r"^\s*Parameters\s*\n\s*-{3,}\s*$", re.M),
    "returns": re.compile(r"^\s*(Returns|Yields)\s*\n\s*-{3,}\s*$", re.M),
    "raises": re.compile(r"^\s*Raises\s*\n\s*-{3,}\s*$", re.M),
    "example": re.compile(r"^\s*Examples?\s*\n\s*-{3,}\s*$", re.M),
    "attributes": re.compile(r"^\s*Attributes\s*\n\s*-{3,}\s*$", re.M),
}


def _sections(style: Style) -> dict[str, re.Pattern[str]]:
    """Return the section-header patterns for *style*.

    Parameters
    ----------
    style : {"google", "numpy"}
        Docstring convention in force for the repository under audit.

    Returns
    -------
    dict[str, re.Pattern[str]]
        Mapping of logical section name to the compiled header pattern.
    """
    return _GOOGLE_SECTIONS if style == "google" else _NUMPY_SECTIONS


def _has(doc: str, section: str, style: Style) -> bool:
    """Report whether *doc* contains *section*.

    Parameters
    ----------
    doc : str
        The docstring text.
    section : str
        One of ``"params"``, ``"returns"``, ``"raises"``, ``"example"``,
        ``"attributes"``.
    style : {"google", "numpy"}
        Docstring convention.

    Returns
    -------
    bool
        ``True`` if a header for *section* is present.

    Examples
    --------
    >>> _has("Args:\\n    x: thing", "params", "google")
    True
    >>> _has("no sections here", "returns", "numpy")
    False
    """
    if section == "example" and (">>>" in doc or ".. code-block::" in doc):
        return True
    return bool(_sections(style)[section].search(doc))


# --------------------------------------------------------------------------
# Findings
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Violation:
    """A single docstring-standard violation.

    Attributes
    ----------
    path : str
        Repo-relative file path.
    line : int
        1-indexed line of the offending definition.
    symbol : str
        Dotted symbol name.
    kind : str
        ``"module"``, ``"class"``, ``"function"``, ``"method"`` or
        ``"property"``.
    rule : str
        Short machine-readable rule id, e.g. ``"missing-returns"``.
    detail : str
        Human-readable explanation.

    Examples
    --------
    >>> v = Violation("src/dqt/rules.py", 42, "apply_rules", "function",
    ...               "missing-returns", "no Returns section")
    >>> v.format()
    'src/dqt/rules.py:42: [missing-returns] function apply_rules -- no Returns section'
    """

    path: str
    line: int
    symbol: str
    kind: str
    rule: str
    detail: str

    def key(self) -> str:
        """Return a stable identity used for baseline comparison.

        Returns
        -------
        str
            ``"<path>::<symbol>::<rule>"`` -- deliberately excludes the line
            number so that unrelated edits above a symbol do not invalidate a
            baseline entry.
        """
        return f"{self.path}::{self.symbol}::{self.rule}"

    def format(self) -> str:
        """Render the violation as a single ``file:line: message`` line.

        Returns
        -------
        str
            A line suitable for CI log output.
        """
        return f"{self.path}:{self.line}: [{self.rule}] {self.kind} {self.symbol} -- {self.detail}"


@dataclass
class AuditConfig:
    """Per-repository audit configuration.

    Attributes
    ----------
    root : pathlib.Path
        Repository root.
    package : str
        Path of the package to audit, relative to *root*.
    style : {"google", "numpy"}
        Docstring convention enforced for this repo.
    require_example : bool
        Whether public functions and classes must carry an ``Example`` section.
    exclude : list[str]
        Glob patterns, relative to *root*, skipped entirely.

    Examples
    --------
    >>> import pathlib
    >>> cfg = AuditConfig(root=pathlib.Path("."), package="src/dqt", style="google")
    >>> cfg.require_example, cfg.style
    (True, 'google')
    """

    root: pathlib.Path
    package: str
    style: Style = "numpy"
    require_example: bool = True
    exclude: list[str] = field(default_factory=lambda: ["**/__pycache__/**", "**/tests/**"])


# --------------------------------------------------------------------------
# Core audit
# --------------------------------------------------------------------------


def _is_public(name: str) -> bool:
    """Report whether *name* is part of the public surface.

    Dunder methods are treated as public because they are user-facing
    behaviour, while single-underscore names are private per §1.7.

    Parameters
    ----------
    name : str
        Symbol name.

    Returns
    -------
    bool
        ``True`` for public symbols.

    Examples
    --------
    >>> _is_public("fit"), _is_public("_helper"), _is_public("__init__")
    (True, False, True)
    """
    return not (name.startswith("_") and not name.startswith("__"))


def _params_of(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    """List the documented-worthy parameter names of *node*.

    ``self``, ``cls``, and purely positional markers are excluded.

    Parameters
    ----------
    node : ast.FunctionDef or ast.AsyncFunctionDef
        The function definition.

    Returns
    -------
    list[str]
        Parameter names that must appear in the docstring.
    """
    a = node.args
    names = [p.arg for p in (*a.posonlyargs, *a.args, *a.kwonlyargs)]
    if a.vararg:
        names.append(a.vararg.arg)
    if a.kwarg:
        names.append(a.kwarg.arg)
    return [n for n in names if n not in {"self", "cls"}]


def _returns_something(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Report whether *node* is annotated as returning a value.

    Parameters
    ----------
    node : ast.FunctionDef or ast.AsyncFunctionDef
        The function definition.

    Returns
    -------
    bool
        ``True`` unless the return annotation is ``None`` or absent.
    """
    r = node.returns
    if r is None:
        return False
    if isinstance(r, ast.Constant) and r.value is None:
        return False
    return True


def _raised_types(node: ast.AST) -> set[str]:
    """Collect exception type names raised directly in *node*.

    Raises inside nested function definitions are excluded, since those belong
    to the nested function's own docstring.

    Parameters
    ----------
    node : ast.AST
        The function definition to scan.

    Returns
    -------
    set[str]
        Exception class names, e.g. ``{"ValueError", "TypeError"}``.
    """
    found: set[str] = set()
    for child in ast.walk(node):
        if child is not node and isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if isinstance(child, ast.Raise) and child.exc is not None:
            exc = child.exc
            if isinstance(exc, ast.Call):
                exc = exc.func
            if isinstance(exc, ast.Name):
                found.add(exc.id)
            elif isinstance(exc, ast.Attribute):
                found.add(exc.attr)
    return found


def _is_property(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Report whether *node* is decorated as a property.

    Parameters
    ----------
    node : ast.FunctionDef or ast.AsyncFunctionDef
        The function definition.

    Returns
    -------
    bool
        ``True`` if any decorator is ``property`` or ``*.setter``/``*.getter``.
    """
    for d in node.decorator_list:
        if isinstance(d, ast.Name) and d.id in {"property", "cached_property"}:
            return True
        if isinstance(d, ast.Attribute) and d.attr in {"setter", "getter", "cached_property"}:
            return True
    return False


def _audit_function(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    path: str,
    qualname: str,
    kind: str,
    cfg: AuditConfig,
) -> list[Violation]:
    """Audit one function or method against §2.2.

    Parameters
    ----------
    node : ast.FunctionDef or ast.AsyncFunctionDef
        Definition to audit.
    path : str
        Repo-relative file path, used in the report.
    qualname : str
        Dotted symbol name.
    kind : str
        ``"function"``, ``"method"`` or ``"property"``.
    cfg : AuditConfig
        Active configuration.

    Returns
    -------
    list[Violation]
        Zero or more violations.
    """
    out: list[Violation] = []
    doc = ast.get_docstring(node)
    v = lambda rule, detail: Violation(path, node.lineno, qualname, kind, rule, detail)  # noqa: E731

    if not doc:
        return [v("missing-docstring", "no docstring")]
    if not doc.strip().splitlines()[0].strip().endswith("."):
        out.append(v("summary-no-period", "summary line must end with a period"))

    if kind == "property":
        if not _has(doc, "returns", cfg.style):
            out.append(v("missing-returns", "a property must document what it returns"))
        return out

    params = _params_of(node)
    if params:
        if not _has(doc, "params", cfg.style):
            out.append(v("missing-params", f"documents none of: {', '.join(params)}"))
        else:
            undocumented = [p for p in params if not re.search(rf"^\s*[*]{{0,2}}{re.escape(p)}\s*[:(]", doc, re.M)]
            if undocumented:
                out.append(v("undocumented-param", f"not described: {', '.join(undocumented)}"))

    if _returns_something(node) and not _has(doc, "returns", cfg.style):
        out.append(v("missing-returns", "annotated to return a value but has no Returns section"))

    raised = _raised_types(node)
    if raised and not _has(doc, "raises", cfg.style):
        out.append(v("missing-raises", f"raises {', '.join(sorted(raised))} but has no Raises section"))

    if cfg.require_example and kind != "method" and not _has(doc, "example", cfg.style):
        out.append(v("missing-example", "public function requires a runnable Example"))

    return out


def audit(cfg: AuditConfig) -> list[Violation]:
    """Audit every public symbol under the configured package.

    Parameters
    ----------
    cfg : AuditConfig
        Repository configuration.

    Returns
    -------
    list[Violation]
        All violations found, ordered by file then line.

    Raises
    ------
    SystemExit
        If the configured package directory does not exist.

    Examples
    --------
    >>> import pathlib, tempfile, os
    >>> d = tempfile.mkdtemp()
    >>> os.makedirs(os.path.join(d, "pkg"))
    >>> src = "'''Mod.'''\\ndef f(x):\\n    '''Do it.'''\\n"
    >>> _ = pathlib.Path(d, "pkg", "m.py").write_text(src, encoding="utf-8")
    >>> cfg = AuditConfig(root=pathlib.Path(d), package="pkg", require_example=False)
    >>> [v.rule for v in audit(cfg)]
    ['missing-params']
    """
    base = cfg.root / cfg.package
    if not base.is_dir():
        raise SystemExit(f"doc_audit: package directory not found: {base}")

    violations: list[Violation] = []
    for f in sorted(base.rglob("*.py")):
        rel = str(f.relative_to(cfg.root))
        if any(f.match(pat) for pat in cfg.exclude):
            continue
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
        except SyntaxError as exc:  # pragma: no cover - malformed source
            violations.append(Violation(rel, exc.lineno or 1, f.stem, "module", "syntax-error", str(exc)))
            continue
        except UnicodeDecodeError as exc:  # pragma: no cover - non-UTF-8 source
            # Surfaced as a violation rather than crashing the gate: a file that
            # cannot be read cannot be audited, and silently skipping it would
            # be exactly the false all-clear ENGINEERING-STANDARDS.md §1.6 forbids.
            violations.append(Violation(rel, 1, f.stem, "module", "undecodable-source", str(exc)))
            continue

        if not ast.get_docstring(tree) and f.name != "__init__.py":
            violations.append(Violation(rel, 1, f.stem, "module", "missing-docstring", "module has no docstring"))

        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _is_public(node.name):
                violations += _audit_function(node, rel, node.name, "function", cfg)
            elif isinstance(node, ast.ClassDef) and _is_public(node.name):
                cdoc = ast.get_docstring(node)
                if not cdoc:
                    violations.append(
                        Violation(rel, node.lineno, node.name, "class", "missing-docstring", "no docstring")
                    )
                elif cfg.require_example and not _has(cdoc, "example", cfg.style):
                    violations.append(
                        Violation(rel, node.lineno, node.name, "class", "missing-example", "public class requires an Example")
                    )
                for sub in node.body:
                    if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) and _is_public(sub.name):
                        kind = "property" if _is_property(sub) else "method"
                        violations += _audit_function(sub, rel, f"{node.name}.{sub.name}", kind, cfg)

    return sorted(violations, key=lambda x: (x.path, x.line))


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _load_baseline(path: pathlib.Path | None) -> set[str]:
    """Load an accepted-violations baseline.

    The baseline enables ratchet mode: existing debt is tolerated while any
    *new* violation fails the build. Entries are removed as debt is paid.

    Parameters
    ----------
    path : pathlib.Path or None
        Baseline JSON file, or ``None`` for no baseline.

    Returns
    -------
    set[str]
        Accepted violation keys.
    """
    if path is None or not path.exists():
        return set()
    return set(json.loads(path.read_text(encoding="utf-8")))


def main(argv: Iterable[str] | None = None) -> int:
    """Run the audit and report results.

    Parameters
    ----------
    argv : Iterable[str] or None
        Command-line arguments; defaults to :data:`sys.argv`.

    Returns
    -------
    int
        Process exit code -- ``0`` clean, ``1`` violations, ``2`` usage error.

    Examples
    --------
    >>> main(["--path", "nonexistent_pkg_xyz", "--root", "."])  # doctest: +SKIP
    2
    """
    p = argparse.ArgumentParser(description="Enforce ENGINEERING-STANDARDS.md §2.")
    p.add_argument("--root", default=".", help="Repository root.")
    p.add_argument("--path", required=True, help="Package path relative to root, e.g. src/dqt.")
    p.add_argument("--style", choices=["google", "numpy"], default="numpy")
    p.add_argument("--require-example", action="store_true", default=False)
    p.add_argument("--baseline", default=None, help="JSON file of accepted existing violations.")
    p.add_argument("--write-baseline", action="store_true", help="Rewrite the baseline from current state.")
    p.add_argument("--summary-only", action="store_true")
    args = p.parse_args(list(argv) if argv is not None else None)

    cfg = AuditConfig(
        root=pathlib.Path(args.root).resolve(),
        package=args.path,
        style=args.style,
        require_example=args.require_example,
    )
    try:
        found = audit(cfg)
    except SystemExit as exc:
        print(exc, file=sys.stderr)
        return 2

    baseline_path = pathlib.Path(args.baseline) if args.baseline else None
    if args.write_baseline and baseline_path:
        baseline_path.write_text(json.dumps(sorted(v.key() for v in found), indent=2), encoding="utf-8")
        print(f"doc_audit: baseline written with {len(found)} entries -> {baseline_path}")
        return 0

    accepted = _load_baseline(baseline_path)
    new = [v for v in found if v.key() not in accepted]

    by_rule: dict[str, int] = {}
    for v in found:
        by_rule[v.rule] = by_rule.get(v.rule, 0) + 1

    print(f"doc_audit: {len(found)} violation(s) total, {len(new)} new (baseline accepts {len(accepted)})")
    for rule, n in sorted(by_rule.items(), key=lambda kv: -kv[1]):
        print(f"  {n:5}  {rule}")
    if new and not args.summary_only:
        print("\nNew violations:")
        for v in new:
            print("  " + v.format())

    return 1 if new else 0


if __name__ == "__main__":
    raise SystemExit(main())
