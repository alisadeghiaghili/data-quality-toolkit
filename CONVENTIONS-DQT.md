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

### [x] C1. SQL profiling & DQ diagnostics

- `SqlProfiler` implemented in `sql/profiling.py`:
  - column stats: min/max, mean, distinct counts, null counts/ratios, pattern/length profiles.
  - table stats: row counts, orphan FK rows, referential integrity checks.
- `DQDiagnostics` implemented in `sql/diagnostics.py`:
  - `DQIssue`, dimensions (completeness, consistency, validity, uniqueness, timeliness),
  - severity + evidence, aggregated per table/column.

### [x] C2. Rules engine (DB-level data quality)

- Rule engine implemented in `sql/rules.py`:
  - column rules: NOT NULL, uniqueness, range, regex — all evaluated via SQL.
  - YAML/JSON + Python API (`examples/rules/base_rules.yaml`, `advanced_rules.yaml`).
- **Gap remaining:** table-level rules (FK integrity, conditional constraints) — column-level only so far.

### [x] C3. Cleansing & repair primitives

- Implemented in `sql/cleansing.py`:
  - `standardize`: trim, normalize_spaces, case (upper/lower/title).
  - `deduplicate`: key-based, keep first/last.
  - `lookup_correct`: domain-table-based value replacement.
- All operations produce `CleansingLog` (before/after per row) and `CleansingResult`.
- Reversible, auditable, no silent changes.

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
  merges rule issues with diagnostic issues.
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

- `tests/unit/` covers: models, config_loader, rules, pipeline, public API.
- `tests/integration/` covers: end-to-end `DQTPipeline.run()` on SQLite with
  known DQ issues (employees + departments schema).
- CI enforces coverage ≥ 80%.

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

### [x] Q1. Minimal CLI surface

- `cli.py` implements:
  - `dqt profile --dsn ... --schema ...`
  - `dqt check --rules rules.yaml`
  - exit codes and clear error messages.
- `dqt missing` (bridge call) not yet implemented.

### [x] Q2. Rich CLI

- `cli.py` uses Rich:
  - progress bars for pipeline stages,
  - colorized metrics table,
  - colorized issues table with severity colors.

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
