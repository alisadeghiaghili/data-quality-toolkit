# data-quality-toolkit (`dqt`)

[![License: BUSL-1.1](https://img.shields.io/badge/license-BUSL--1.1-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue.svg)](pyproject.toml)
[![Coverage gate](https://img.shields.io/badge/coverage%20gate-90%25-brightgreen.svg)](pyproject.toml)

## Status: alpha

Version `0.1.0`. `docs/PLAN-TDD.md`'s cut line defines v0.1 as its units 1-9,
and all nine have landed. See [`CHANGELOG.md`](CHANGELOG.md).

What that bar meant, in the plan's own words, was closing everything that was
either **silently wrong** or **false in a shipped docstring**. Both are now
closed: `regex` rules evaluate on SQLite, the CLI forwards the rule files it
is given, `run()` reports failure instead of returning success on it,
`dimension` no longer carries two meanings, cleansing is genuinely reversible,
and the exit code is a contract rather than a constant.

**What is still true and worth knowing before you point this at anything.**
Profiling opens the connection read-only and cannot be made to write —
`run()`'s call graph contains no path that mutates. Cleansing does write, and
is reached only by calling it deliberately: `cleanse_plan()` computes and
stores a change set without touching anything, `cleanse_apply(plan_id)`
executes that stored plan, and `revert(plan_id)` undoes it. The legacy
`apply_cleansing()` remains reversible only by hand, and only while you still
hold the log it returns — prefer the triple.

Supported and exercised against a live server in CI: **SQLite**,
**PostgreSQL** and **SQL Server**.

One difference matters more than the others. `read_only` means different
things per database, and DQT reports which you are getting rather than
implying they are the same:

| Database | `read_only=True` gives you | Who refuses a write |
|---|---|---|
| SQLite | `mode=ro` on the connection | the driver |
| PostgreSQL | a read-only session | the server |
| SQL Server | an ODBC access-mode hint | **nobody** |

On SQL Server the hint is advisory. DQT emits a `RuntimeWarning` saying so and
still refuses to build a mutating statement itself, but a write that reaches
the server will land. **Connect with a read-only login there.** There is a
test asserting the write lands, so the limitation cannot quietly stop being
true without someone noticing.

Full audit: `DQT-critical-review.md`.

---

A SQL-first, DBA-oriented data-quality toolkit. Point it at a database, get back
profiling statistics, rule violations, quality metrics, and an HTML report — all
computed with SQL, against the live database, without extracting the data.

## What it does

- **Schema discovery** — enumerate schemas, tables, and columns.
- **Profiling** — row counts, null counts, completeness scores per column.
- **Diagnostics** — turn statistics into structured, evidence-carrying issues.
  Currently `completeness` only.
- **Rules** — declarative `NOT NULL`, `UNIQUE`, `RANGE`, and `REGEX` checks from
  YAML or JSON. See the status block above regarding `REGEX`.
- **Metrics and storage** — persist per-run metrics and issues to a local SQLite
  store, which is what a comparison across runs would read. DQT does not
  perform that comparison itself: `monitor()` is a pass-through today, so
  trend and drift detection are not implemented (`NEW-G`).
- **Reporting** — a self-contained HTML report with score bars and severity
  badges.
- **Read-only HTTP API** — an optional FastAPI surface over the stored results.

Supported databases: **SQLite**, **PostgreSQL** and **SQL Server**, all three
exercised against a live server in CI. MySQL is not supported.

SQL Server needs a system ODBC driver that pip cannot install, so
`pip install "dqt[sqlserver]"` is necessary but not sufficient — install
Microsoft's `msodbcsql18` as well. The dialect imports `pyodbc` lazily and
names the extra when it is missing. It has no regular-expression operator, so
`regex` rules are refused there rather than reported as zero violations.

Adding a database means registering a dialect in `dqt.sql.dialects`, not
editing branches across the codebase: identifier quoting, the read-only
incantation, regex matching and introspection are all asked of the dialect
rather than decided by the caller. Connections use DB-API 2.0 drivers
directly; SQLAlchemy is not a dependency.

## What it deliberately does not do

Service or performance monitoring (latency, CPU, wait stats), data masking,
compliance tooling, MDM / golden-record, and pandas DataFrame analysis. These are
permanent non-goals, not gaps.

## Install

```bash
pip install -e .                 # core
pip install -e ".[postgres]"     # + PostgreSQL driver
pip install -e ".[ui]"           # + FastAPI read-only API
pip install -e ".[dev]"          # + test and lint tooling
```

Requires Python 3.11 or newer.

## Run

```bash
dqt profile --dsn "sqlite:///path/to/database.db"
```

From Python:

```python
from dqt import from_dsn

pipeline = from_dsn("sqlite:///path/to/database.db")
result, report_path = pipeline.run()

print(f"{result.status}: {len(result.issues)} issue(s)")
print(f"report: {report_path}")
```

Count issues from `result.issues` only. The per-schema, per-table and per-column
lists are overlapping views of the same issues — summing them double-counts. See
`docs/CONVENTIONS-DQT-data-model.md` §1.

Note that `result.status` is currently always `"success"`: there is no per-stage
error handling yet, so a failed run raises rather than recording a failure.

## Cleansing on a large table

Cleansing is the one part of DQT that genuinely reads rows: it records a
before-value for every change so `revert()` can put it back. Everything else
aggregates inside the database.

Those reads are **paged by the row's primary key**, not taken all at once, so
the planner's memory is bounded by the page size rather than by the table.
Each page's query finishes before that page's writes are issued, and the next
page resumes after the last key seen — an `UPDATE` to some other column does
not move a primary key, so no row is skipped or read twice.

This is why cleansing refuses a table with no primary key on a dialect
without a stable row locator. The refusal names the fix: give the table a key.

## Rules

Rules are declarative, defined in YAML or JSON, and compile to set-based SQL —
never a row-by-row loop. Five expressions: `NOT NULL`, `UNIQUE`, `RANGE`,
`REGEX`, `REFERENCE`.

**Rules on the same table share one scan.** Each check compiles to aggregate
expressions rather than to a statement, and the checks over a table are run as
a single `SELECT`. Twenty rules on your busiest table cost one pass, not
twenty. The one exception is a `REFERENCE` rule pointing at a reference
*table*: it needs a join, and a join changes which rows the other aggregates
would see, so it pays its own scan.

If the database rejects a batched statement, DQT retries its checks one at a
time — so a mistake in one rule costs you that rule's verdict, not the whole
table's report.

### `REFERENCE` — values must come from a known set

The validity check neither `REGEX` nor `RANGE` can express: membership of a
set that lives in the data rather than in a pattern.

```yaml
- name: city-is-known
  dimension: validity
  severity: error
  expression: REFERENCE
  scope: { table_pattern: customers, column_pattern: city }
  params:
    reference_table: ref_cities
    reference_column: name
    normalize_persian: true      # optional; off by default
```

A reference **table** compiles to an anti-join, so matching a large table
against its reference is the query planner's work rather than Python's. For a
vocabulary small enough to read in the rule file, use `params: {values: [...]}`
instead — those are bound as parameters, never interpolated.

`normalize_persian` folds Persian and Arabic letter and digit variants on
**both** sides before comparing, in SQL. `شيراز` written with an Arabic yeh is
the same city as `شیراز` with a Persian one, and a check that calls them
different values reports a problem that does not exist. It is off unless
asked: changing values silently is not a data-quality tool's job.

**DQT ships no reference data.** A tool that carries its own country list is
one stale release away from reporting correct data as invalid, and a false
positive on a clean table costs more trust than the convenience is worth. DQT
provides the mechanism; you provide the authority.

`UNIQUE` counts duplicates with `COUNT(DISTINCT ...)`, which has to hold every
distinct value it sees. On a high-cardinality column of a very large table
that is the one operation in DQT that can cost real memory on the server, so a
rule may opt into an estimate:

```yaml
- name: unique-customer-email
  dimension: uniqueness
  severity: error
  expression: UNIQUE
  scope: { table_pattern: customers, column_pattern: email }
  params: { approximate: true }
```

Whether an estimate is acceptable is a property of the check, not of the run,
which is why it is set per rule. Only SQL Server has a native estimating form
(`APPROX_COUNT_DISTINCT`); SQLite has none and PostgreSQL's is an extension
rather than core, so on those the rule answers exactly. **Either way the
issue's evidence carries `approximate`**, so a reader never has to guess which
kind of number they are looking at — an estimate and an exact count are
different claims.

## Exit codes

`dqt profile` is meant to be usable as a data-quality gate in CI, which means
the exit code is a contract:

| Code | Meaning |
|---|---|
| `0` | Nothing at or above the chosen threshold was found. |
| `1` | At least one `error` or `critical` finding. |
| `2` | `warning` findings only, with `--fail-on warning`. |
| `3` | Configuration or connection error — DQT never reached your database. |
| `4` | Internal error — DQT reached your database and then broke. |

`--fail-on {error,warning,none}` chooses the threshold at which findings
become a failure; the default is `error`, so warnings are reported but do not
fail a build.

Two properties worth relying on. A run that did not finish outranks whatever
it managed to find, so a broken run never reports `1` — `3` and `4` mean the
verdict on your data is unknown, not clean. And `--fail-on` governs findings
only: `--fail-on none` still exits `3` on a connection failure, because
choosing not to gate on data quality is not the same as choosing not to be
told the run failed.

The `3`/`4` split tells you where to look: `3` is your invocation, `4` is a
bug in DQT.

```bash
dqt profile --dsn "sqlite:///app.db" --rules rules.yaml --fail-on error
echo "exit=$?"
```

## Documentation

| Document | What it covers |
|---|---|
| [`docs/00-START-HERE.md`](docs/00-START-HERE.md) | Entry point: source-of-truth hierarchy and verified state of the code. |
| [`docs/CONVENTIONS-DQT.md`](docs/CONVENTIONS-DQT.md) | Scope, vocabulary, safety model, supported dialects. |
| [`docs/CONVENTIONS-DQT-data-model.md`](docs/CONVENTIONS-DQT-data-model.md) | Classes, aggregation contract, storage schema. |
| [`docs/API-STABILITY.md`](docs/API-STABILITY.md) | What the public API promises, and how a name leaves it. |
| [`docs/BACKLOG.md`](docs/BACKLOG.md) | Defects with no task ID yet, and open design questions. |
| [`AGENTS.md`](AGENTS.md) | Enforceable working rules for contributors. |
| [`DQT-critical-review.md`](DQT-critical-review.md) | The 2026-08-11 execution-based audit. |

## Development

All gates must pass before a change is considered done:

```bash
ruff check src/ tests/
ruff format --check src/ tests/
mypy src/dqt/ --strict
pytest --cov=src/dqt --cov-fail-under=80
pytest --collect-only -q | tail -1     # count must not decrease
```

Docstrings are Google style, English only, and may only describe behaviour a
passing test covers.

## License

Source-available under the Business Source License 1.1 (BUSL-1.1), not an
OSI-approved open-source license — see [LICENSE](LICENSE) and
[NOTICE.md](NOTICE.md). On 2030-09-04 the license converts automatically to
the Apache License, Version 2.0.
