# DQT — SQL Data Quality Toolkit (CONVENTIONS)

Sibling packages:
- `DQT` — SQL DB Data Quality Toolkit (DBA-focused).
- `missingly` — Missing Data Toolkit (missingness & imputation).

Relationship:
- Independent sister packages.
- DQT can optionally call `missingly` or other analyzers via bridges, but core DQT
  has no hard dependency on `missingly`.

Scope: **Data Quality Only** — no service/performance monitoring, no masking/compliance, no MDM/golden record.

---

## Session Log

### [2026-07-01] Initial DQT Design Review

**Critical Gaps Found:**
- No SQL‑first data-quality pipeline: profiling, diagnostics, rules, cleansing,
  metrics, monitoring, reporting for DBA use.
- Missing data handled only at dataset level (by `missingly`); DQT has no
  standard way to sample from SQL tables, call external missingness analyzers,
  or embed their results into data-quality reports.
- No unified facets model for DQT; risk of feature drift and mixing service
  metrics with data quality.
- No explicit conventions for tests, docstrings, examples, and CI.
- Visualization, performance, and a proper UI (beyond CLI/Rich CLI) not treated
  as first-class design concerns.

**Decisions Made:**
- DQT will provide a **DBA‑centric SQL data-quality pipeline**:
  schema discovery → profiling → diagnostics → rules → cleansing →
  metrics → monitoring → reporting.
- Missingness & imputation remain in `missingly`; DQT offers sampling + bridge helpers.
- Define a **facets model**: Profiling, DQ diagnostics, Rules, Cleansing, Metrics,
  Monitoring, Knowledge/Domain, Classification, Missingness (internal),
  Imputation (external), Reports, Viz/UI.
- Enforce scope: no service/performance metrics, masking/compliance, or MDM.
- Tests, English docstrings, and CI are **first-class requirements**.
- Visualization, performance, and DBA-friendly UI are explicit roadmap items.

**Next Steps (at the time):**
- Implement core SQL profiling + DQ diagnostics + rules + cleansing.
- Introduce `DQTPipeline` and `PipelineResult` with a clean public API.
- Define an optional `bridges` module to talk to `missingly` and other analyzers.
- Add testing layout, docstring policy, CI pipeline, visualization API,
  performance benchmarks, CLI, Rich CLI, and UI.
- Draft minimal CLI + report templates (EN/FA) for v0.1.0.

### [2026-08-11] Phase 0 Remediation — repository honesty pass

A full code-reading review (`DQT-critical-review.md`) found that the
[2026-07-04] sprint below marked 11 items `[x] DONE` that were not true as
written: the CLI crashed on every invocation, every CI gate (lint, format,
mypy, tests, coverage) was red, and several modules (rules regex, cleansing
row identity, storage idempotency) had confirmed correctness bugs. This entry
records what was actually fixed and verified, and the status table below was
rewritten to match.

**Fixed and verified (all gates green locally: `ruff check`, `ruff format
--check`, `mypy src/dqt/ --strict`, `pytest --cov` ≥ 80%):**
- Packaging: entry point pointed at a non-existent module (`dqt.cli.plain:main`);
  fixed to `dqt.cli:main`. Runtime dependencies (`rich`, `pyyaml`) were
  undeclared; added, plus `postgres`/`ui` extras and a `py.typed` marker.
- CLI: `_build_pipeline_config()` never set the required `connection_id` field,
  so every `dqt profile` invocation crashed with a `pydantic` validation error.
  Fixed; `dqt profile --dsn ...` now runs end-to-end and is covered by
  `tests/unit/test_cli.py`. Report directory is now created if missing.
- Cleansing (`sql/cleansing.py`): on tables with `INTEGER PRIMARY KEY`, SQLite
  aliases `rowid` to the PK column name in `cursor.description`, so
  `row["rowid"]` raised `KeyError` — swallowed by a broad `except Exception`,
  producing a silent `total_changes=0` false-clean result on the most common
  table shape. Fixed by explicitly aliasing (`SELECT rowid AS dqt_row_id`).
  Fixing that bug alone would have exposed a second, more serious one:
  `deduplicate`'s `GROUP BY` collapsed all NULL-keyed rows into one group and
  deleted all but one, even though they are genuinely distinct records. Both
  are fixed together and covered by a regression test.
- Storage (`common/storage.py`): `run_metrics` had no unique constraint on its
  natural key, so `INSERT OR IGNORE` never had a conflict target and re-saving
  a run duplicated every metric row, contradicting the method's own
  idempotency docstring. Fixed with a `UNIQUE` index.
- Test suite: 9 of ~20 test modules failed to collect (`DiscoveredColumn`
  constructed with kwargs — `is_nullable`, `ordinal_position` — that don't
  exist on the dataclass). Fixed to match the real model.
- Deleted the orphaned pandas-based `data_quality_toolkit` legacy package
  (never imported by `dqt`, buggy, dragged in undeclared dependencies) and the
  duplicate/broken `.github/workflows/ci.yml`.
- Added `.gitignore`, `LICENSE`, `.pre-commit-config.yaml`, `tests/conftest.py`,
  `AGENTS.md`.

**Explicitly not fixed in this pass (tracked as open gaps below, Phase 1):**
SQL injection in rule parameter interpolation, missing SQLite `REGEXP`
registration, `read_only` not enforced on any connection, cleansing still not
reversible/persistently logged, rules unreachable from the CLI, no exit-code
semantics or `dqt check`, missing-rule-file silently swallowed as success.

### [2026-07-04] Implementation Sprint — v0.1.0 core complete

**What was implemented:**
- `common/models.py` — full data model with typed Pydantic classes.
- `common/storage.py` — RunStore backed by SQLite.
- `common/config_loader.py` — YAML/JSON loader with env expansion, merging, validation.
- `sql/schema_discovery.py` — schema + FK discovery.
- `sql/profiling.py` — column & table stats via SQL.
- `sql/diagnostics.py` — DQIssue generation across dimensions.
- `sql/rules.py` — rule engine: NOT NULL, UNIQUE, range, regex via SQL; YAML-driven.
- `sql/cleansing.py` — standardize, deduplicate, lookup_correct with audit log.
- `sql/pipeline.py` — full DQTPipeline with apply_rules() wired correctly.
- `sql/metrics.py` — metric computation (stub, wired into pipeline).
- `sql/monitoring.py` — monitoring stub (wired into pipeline).
- `sql/reports.py` — HTML report generation (partial template).
- `cli.py` — Rich CLI with progress bars, colorized metrics and issues tables.
- `ui/api.py` — thin read-only data layer over RunStore (5 functions).
- `ui/app.py` — FastAPI skeleton with 6 endpoints.
- `dqt/__init__.py` — complete public API surface with `from_dsn()`,
  `from_yaml_config()`, `__version__`, all exports.
- `examples/rules/base_rules.yaml` + `advanced_rules.yaml` — example rule files.
- `tests/unit/` — 60+ unit tests across models, config_loader, rules, pipeline, public API.
- `tests/integration/` — end-to-end integration tests with SQLite.
- `.github/workflows/ci.yaml` — CI: ruff + mypy --strict + pytest (py3.11, py3.12),
  coverage gate ≥ 80%.

---

## Status Legend

- `[ ]` TODO — not started / not yet in code
- `[~]` IN PROGRESS — partially implemented / needs work
- `[x]` DONE — implemented, tested, and in source

---

## P0 — Critical (core data-quality semantics)

### [~] C1. SQL profiling & DQ diagnostics

- `SqlProfiler` implemented in `sql/profiling.py`, but only **null counts and
  row counts** — min/max, mean, distinct counts, pattern/length profiles are
  not implemented despite being claimed below in prior revisions of this doc.
- `DQDiagnostics` implemented in `sql/diagnostics.py`, but only **one check**:
  `null_count > 0` with a hardcoded `ratio >= 0.5` severity threshold
  (`DQPipelineConfig.metric_thresholds` is validated but never consulted).
  Consistency, validity, uniqueness, timeliness, and referential-integrity
  diagnostics are not implemented; no FK/orphan-row discovery exists.

### [~] C2. Rules engine (DB-level data quality)

- Rule engine implemented in `sql/rules.py`; NOT NULL, UNIQUE, and range
  column rules are evaluated via SQL and unit-tested.
- **regex rules are non-functional**: SQLite has no built-in `REGEXP`, and
  DQT never registers one via `conn.create_function`, so every regex rule
  either errors or silently never matches. Not fixed in this pass.
- **No table-level rules** (FK integrity, conditional constraints) —
  column-level only.
- **Rules cannot be invoked from the CLI**: `dqt profile` has no `--rules`
  flag and never sets `DQPipelineConfig.rule_files`. Not fixed in this pass.
- Range/regex rule parameter values are string-interpolated into SQL rather
  than bound; this is a known injection risk against untrusted rule files,
  tracked for the Phase 1 dialect-layer work. Not fixed in this pass.

### [~] C3. Cleansing & repair primitives

- Implemented in `sql/cleansing.py`: `standardize`, `deduplicate`,
  `lookup_correct`, all unit-tested including a NULL-key regression test.
- Row identity is resolved via an explicit `rowid AS dqt_row_id` alias, so
  cleansing now works correctly on tables with `INTEGER PRIMARY KEY` (SQLite's
  most common table shape) — previously this silently no-opped on such tables.
  `deduplicate` excludes rows with a NULL key column from duplicate detection,
  preventing the data-loss failure mode where `GROUP BY` would otherwise treat
  all NULL-keyed rows as one group.
- **Not reversible or persistently audited**: `CleansingLog` entries are
  returned in memory only — `RunStore` has no `cleansing_log` table and there
  is no `revert()`/`undo()`. The module docstring's claim of "reversible" is
  aspirational, not yet true. `read_only` on `ConnectionConfig` is not
  enforced anywhere. The `cleanse` pipeline stage is still a pass-through
  stub (see A1) — cleansing only runs via a direct `apply_cleansing()` call.
  None of this was in scope for this pass; tracked as Phase 1 (plan/apply/
  revert restructure).

### [~] C4. Basic missingness stats (DQT internal)

- Null counts and null ratios are computed in `sql/profiling.py` and surfaced as metrics.
- **Gap remaining:** null co-occurrence patterns across columns not yet implemented.

---

## P1 — Architecture

### [x] A1. DQTPipeline orchestrator

- `DQTPipeline` in `sql/pipeline.py` with stages:
  `discover_schema → profile_data → run_diagnostics → apply_rules →
  compute_metrics → monitor → generate_report`.
- `apply_rules()` correctly wired: loads `rule_files` from `DQPipelineConfig`,
  merges rule issues with diagnostic issues. **Caveat:** a missing rule file
  is silently swallowed (`except FileNotFoundError: pass`) rather than failing
  the run — a path typo currently reads as "all checks passed." Not fixed in
  this pass.
- Pure per-run behavior; no global mutable state.
- `cleanse` stage not yet wired into the pipeline (exists as standalone module).

### [x] A2. Facets-based module layout

- All implemented facets map to dedicated files:
  `schema_discovery.py`, `profiling.py`, `diagnostics.py`, `rules.py`,
  `cleansing.py`, `metrics.py`, `monitoring.py`, `reports.py`.
- `cli.py` and `ui/` (FastAPI) present.
- **Missing:** `knowledge.py`, `classification.py`, `viz.py`, `bridges/`.

### [x] A3. Public API surface

- `dqt/__init__.py` exports:
  - `DQTPipeline`, `PipelineResult`, `DQIssue`, `DQMetric`,
    `ConnectionConfig`, `DQPipelineConfig`, `RuleConfig`, `RuleResult`,
    `RuleRunResult`, `RuleScope`, `SamplingConfig`, `ColumnResult`,
    `SchemaResult`, `TableResult`, `Rule`, `IssueSeverity`, `RuleStatus`, `RunStatus`.
  - Helper constructors: `from_dsn()`, `from_yaml_config()`.
  - Config loaders: `load_connection`, `load_pipeline`, `load_rules`,
    `load_rules_from_files`.
  - `__version__ = "0.1.0"`.
- Tested in `tests/unit/test_public_api.py` (6 tests, including `__all__` completeness check).
- **Not yet exported** (implementations missing): `from_sqlalchemy_engine()`.

---

## P2 — Bridges & Sister Integration

### [ ] B1. Generic missingness bridge interface

- Define `MissingnessBridge` interface:
  - receives a DataFrame/Arrow table sampled from SQL,
  - returns a structured `MissingnessReport` independent of any specific package.

### [ ] B2. Optional `dqt.bridges.missingly`

- Implement `dqt.bridges.missingly` (extra dependency):
  - `sample_table(engine, table_name, limit, strategy) -> DataFrame`,
  - `run_missingly(df, config=None) -> MissingnessReport`,
  - `attach_missingly_result(pipeline_result, table_name, report)`.
- DQT core must **not** import `missingly` directly.

### [ ] B3. External analyses in PipelineResult

- `external_analyses: Dict[str, Dict[str, Any]]` field is already in `PipelineResult` model.
- **Gap:** Reports module does not yet render an external missingness panel.

---

## P3 — Testing, Docstrings, and CI

### [x] T1. Test layout and coverage

- `tests/unit/` covers: models, config_loader, rules, pipeline, cleansing,
  storage, CLI, public API. `tests/integration/` covers end-to-end
  `DQTPipeline.run()` on SQLite with known DQ issues (employees + departments
  schema).
- Verified as of 2026-08-11: full suite passes (0 failures, 0 collection
  errors) with 83%+ coverage, `--cov-fail-under=80` passes. Previously this
  status was marked `[x]` while the suite had 9 collection errors and 17
  failures — see the Phase 0 Remediation log entry above.

### [x] T2. Docstring and examples policy

- All public functions/classes in new code have Google-style docstrings with
  behavior, args, returns, and at least one example.
- Code-level documentation is English-only.

### [x] T3. CI pipeline

- `.github/workflows/ci.yaml` implemented:
  - `ruff check` + `ruff format --check`
  - `mypy src/dqt/ --strict`
  - `pytest tests/unit/` + coverage ≥ 80%
  - `pytest tests/integration/` (needs test-unit)
  - Python 3.11 and 3.12 matrix.
- Verified as of 2026-08-11: every command above passes locally against a
  clean editable install. Previously this status was marked `[x]` while every
  one of these gates was red (146 lint errors, 21 unformatted files, 37 mypy
  errors, 73% coverage) — see the Phase 0 Remediation log entry above. The
  duplicate, broken `.github/workflows/ci.yml` (installed a nonexistent
  `test` extra) has been removed.

---

## P4 — Documentation, Ecosystem Matrix, UX

### [ ] D1. Bilingual documentation & reports

- `README.en.md` — not yet written.
- `README.fa.md` — not yet written.
- Reports: bilingual headings (EN/FA) not yet in `reports.py` template.

### [ ] D2. Ecosystem matrix doc

- `docs/dqt_ecosystem.md` file not yet committed to repo.
- Matrix exists in Space context docs but not in the repository.

### [~] D3. UI (desktop/web) for DBAs

- `ui/app.py` — FastAPI skeleton with 6 read-only endpoints (runs, metrics, issues).
- `ui/api.py` — thin data layer over RunStore.
- **Gap:** no frontend (HTML/JS) served; no connection selector; no charts;
  no report export via UI. Skeleton only.

### [~] Q1. Minimal CLI surface

- `cli.py` implements `dqt profile --dsn ... --schema ...`, and it now
  actually runs end-to-end (fixed 2026-08-11; previously crashed on every
  invocation with a missing-`connection_id` validation error — see the Phase
  0 Remediation log entry above).
- **Not implemented:** `dqt check` subcommand does not exist; `profile` has
  no `--rules` flag, so the rule engine is unreachable from the CLI (see C2).
  No exit-code semantics (`--fail-on`), no `--json` output. `dqt missing`
  (bridge call) not implemented. None of these were in scope for this pass.

### [~] Q2. Rich CLI

- `cli.py` uses Rich for colorized metrics and issues tables.
- **The progress bar is cosmetic, not accurate**: it iterates through stage
  labels instantly and runs the entire pipeline inside the last one
  ("Generating HTML report"), so the displayed per-stage timing does not
  reflect where time is actually spent. Not fixed in this pass.

### [~] Q3. HTML report template

- `sql/reports.py` generates an HTML report.
- **Gap:** no bilingual headings, no external missingness panel, scorecard
  visualization is minimal.

### [ ] Q4. Integration test with `missingly` bridge

- Not started; depends on B1/B2 being implemented first.

---

## P5 — Visualization and Performance

### [ ] V1. Visualization API

- Not started.
- `ui/app.py` exposes raw data; no Plotly/chart generation in the library itself.

### [ ] V2. Performance budgets and profiling

- Not started.
- No benchmarks or performance regression tests exist yet.

---

## Keep As-Is / External (do not re-implement)

- `missingly` algorithms — DQT **uses** them via bridges; does **not** re-implement.
- Service/performance monitoring (latency, CPU, wait stats, uptime) — out of scope.
- Masking/compliance features — out of scope.
- MDM/golden record — out of scope.

---

## Recommended Next Steps (post v0.1.0 core)

**Immediate gaps to close:**
1. `[ ]` C4 — null co-occurrence patterns across columns.
2. `[ ]` C2 — table-level rules: FK integrity, conditional constraints.
3. `[ ]` `cleanse` stage wired into `DQTPipeline.run()`.
4. `[ ]` B1, B2, B3 — MissingnessBridge + `bridges.missingly`.

**Medium term:**
5. `[ ]` `knowledge.py` + `classification.py` (semantic typing: email, IBAN, phone).
6. `[ ]` `viz.py` — Plotly scorecards and trend charts (V1).
7. `[ ]` D3 UI frontend — real DBA dashboard on top of FastAPI skeleton.
8. `[ ]` D1 — README.en.md + README.fa.md.

**Stretch:**
9. `[ ]` V2 — performance benchmarks + CI regression gate.
10. `[ ]` Q4 — integration test with `missingly` bridge.
