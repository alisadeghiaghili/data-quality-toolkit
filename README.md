# data-quality-toolkit (`dqt`)

[![License: BUSL-1.1](https://img.shields.io/badge/license-BUSL--1.1-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue.svg)](pyproject.toml)
[![Coverage gate](https://img.shields.io/badge/coverage%20gate-90%25-brightgreen.svg)](pyproject.toml)

## Status: pre-alpha — not for production use

Version `0.1.0.dev0`. Nothing has been released: there are no git tags and no
published package. `0.1.0` is not claimed yet — `docs/PLAN-TDD.md`'s cut line
defines v0.1 as its units 1-9, of which 3 have landed. See
[`CHANGELOG.md`](CHANGELOG.md).

DQT connects to databases and can issue UPDATE and DELETE statements. Known open defects:

- Cleansing operations are not persisted and cannot be reverted (DQT-05)

Do not point this tool at a production database. Full audit: `DQT-critical-review.md`.

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

Supported databases: **SQLite** and **PostgreSQL**. MySQL and SQL Server are not
supported. Connections use DB-API 2.0 drivers directly; SQLAlchemy is not a
dependency.

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
