# AGENTS.md — DQT

Guardrails for any agent (or human) working in this repository. This file is
the short, enforceable subset. Start at `docs/00-START-HERE.md`, which
indexes the rest and records the verified state of the code; read
`docs/CONVENTIONS-DQT.md` and `docs/CONVENTIONS-DQT-data-model.md` for the
full facet model and data-model spec. Task IDs come from the Aghili
ecosystem `ROADMAP.md` (`DQT-01` … `DQT-09`), not from this repository.
`docs/BACKLOG.md` records only defects that have no ID yet.

## Scope — what DQT is and isn't

DQT is a **SQL-first, DBA-oriented data-quality toolkit**. In scope: schema
discovery, profiling, diagnostics, rules, cleansing, metrics, monitoring,
reporting — all against live SQL databases (SQLite, Postgres).

Non-goals — do not add code for these, even incidentally:
- Service/performance monitoring (latency, CPU, wait stats, uptime).
- Masking, compliance, or MDM/golden-record features.
- Pandas/DataFrame-based analysis as a first-class path. (A prior
  `data_quality_toolkit` pandas package was removed from this repo in the
  Phase 0 remediation precisely because it drifted out of scope, was
  untested, and dragged in undeclared dependencies. Don't reintroduce that
  pattern.)
- New third-party dependencies "just in case." If something needs an optional
  dependency (a DB driver, a web framework), it belongs behind an
  `[project.optional-dependencies]` extra, not a hard dependency.

## The rule that matters most: status claims must be test-backed

This repository was previously reviewed (`DQT-critical-review.md`) and found
to have eleven `[x] DONE` status markers in its conventions doc that were
false: the CLI crashed on every invocation, every CI gate was red, and
several "done" modules had confirmed correctness bugs (SQL injection, silent
data loss, broken regex rules). The root cause was mechanical: things were
written, documented as complete, and never actually run.

Do not repeat this:
- **Never mark a status `[x]` (or claim a feature "works") without a passing,
  named test that exercises it.** If you can't point to the test, the status
  is `[ ]` or `[~]`, not `[x]`. A self-referential test asserting the code
  does what the code does is not enough — see `docs/HONESTY-GATE.md` for what
  qualifies as evidence in this repo, and the mandatory revert→fail→restore→pass
  transcript required for any bug or security fix.
- **A docstring may only describe behavior covered by a passing test.**
  If you write "reversible," "auditable," or give an example return value,
  a test must verify that exact claim. Otherwise mark it aspirational
  (e.g. `.. note:: Not yet implemented`) or don't write it.
- Before claiming any task complete, run all four gates and confirm they
  pass — don't infer from reading the code that they would pass:

  ```bash
  ruff check src/ tests/ && ruff format --check src/ tests/ && \
  mypy src/dqt/ --strict && pytest --cov=src/dqt --cov-fail-under=80
  ```

## SQL safety rules

DQT executes SQL built from user-supplied config (rule files, connection
strings) against production databases. Two rules, no exceptions:

- **All identifiers (table/column/schema names) go through a single quoting
  path.** Never string-interpolate a raw identifier into SQL.
- **All literal values are bound parameters, never interpolated.** If you
  find yourself writing `f"... = {value}"` inside a SQL string, stop — use
  `?`/`%s` placeholders and pass `value` as a parameter instead.

(Note: `sql/rules.py` still interpolates rule parameter values and does not
fully quote table identifiers on this branch — a known, tracked gap, not a
pattern to copy. `DQT-critical-review.md` §1.3 reproduced a working exploit
through it. `DQT-02` fixes it.)

## Architecture rules

These are the rules `tools/arch_audit.py` enforces. It runs in CI at zero
tolerance, so a violation fails the build the same way a failing test does —
it is a blocker, not a follow-up ticket.

- **Dependencies point inward.** The core domain (results, metrics, issues,
  rules) never imports adapters, drivers, CLI, or UI. Adapters depend on core,
  never the reverse. *(`inward`)*
- **Database drivers live only in `sql/dialects/`.** No other module imports
  `sqlite3`, `psycopg`, or `pyodbc`. *(`driver-boundary`)*
- **No branching on dialect name outside the dialect layer.** Identifier
  quoting, the read-only incantation, regex matching and introspection are
  *asked of* the dialect, never decided by the caller. Adding a database means
  registering a dialect, not editing branches across the codebase.
  *(`dialect-branching`)*
- **`missingly` is reachable only through `bridges/`.** DQT core must be fully
  usable without it and must never re-implement its algorithms.
  *(`missingly-bridge`)*
- **`viz.py` performs no I/O.** It returns chart objects; it does not read or
  write. *(`viz-purity`)*
- **`run()` cannot cleanse.** No path from the pipeline reaches a mutating
  cleansing call. Cleansing is reached only by calling it deliberately.
  *(`no-cleansing-from-run`)*

The facets module layout is the architectural boundary — one module per facet,
no non-DQ concerns leaking into core modules. I/O and database access stay at
the edges; domain logic must be testable without a live database.

## Performance rules

DQT must work well on large data. This is an architectural constraint, not a
later optimization pass — a DBA points this at production tables.

- **Profiling is single-pass.** Many column statistics in one aggregate query
  per table, not one query per statistic per column.
- **Rules compile to set-based aggregate SQL.** Never iterate row by row.
- **Rules on the same table are grouped** so the table is scanned once, not
  once per rule.
- **`COUNT(DISTINCT ...)` is expensive at scale.** Offer an approximate-distinct
  path as a configurable option where the dialect supports it.
- **Honour `SamplingConfig`.** Don't force a full scan when a sample answers
  the question — but note that rules never sample: a profile is a description,
  a rule is a verdict.
- **Bound issue evidence with `LIMIT`.** A `DQIssue` must never materialize the
  whole violating set.
- **Reuse connections across rules.** Don't reopen per rule.
- **Chunk reads** where rows must genuinely be read (cleansing), or use a
  server-side cursor, so memory stays flat.

Before adding a query, state how many round-trips and table scans it costs, and
whether that cost grows with the number of columns or rules. **Per-row Python
work over a table is a design smell.**

Known limit: SQLite's `REGEXP` is a Python callback invoked per row, so `regex`
rules there are a full scan with per-row overhead and will not scale. Use
PostgreSQL's native `~` operator at size.

## Before claiming a task done

Run, in order, and don't report success unless every one passes:

```bash
ruff check src/ tests/
ruff format --check src/ tests/
mypy src/dqt/ --strict
pytest --cov=src/dqt --cov-fail-under=80
```

If you changed the CLI or pipeline behavior, also run it against a real
SQLite file and confirm the exit code and output, not just the test suite —
the CLI had 0% test coverage and had never successfully run even once before
the Phase 0 remediation.
