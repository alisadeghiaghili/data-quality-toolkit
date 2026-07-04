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
  standard way to:
  - sample from SQL tables,
  - call external missingness analyzers,
  - embed their results into data-quality reports.
- No unified facets model for DQT; risk of feature drift and mixing service
  metrics with data quality.
- No explicit conventions for tests, docstrings, examples, and CI, despite being
  required for production-grade packages.
- Visualization, performance, and a proper UI (beyond CLI/Rich CLI) are critical
  but were not treated as first-class design concerns.

**Decisions Made:**
- DQT will provide a **DBA‑centric SQL data-quality pipeline**:
  - schema discovery → profiling → diagnostics → rules → cleansing →
    metrics → monitoring → reporting.
- Missingness & imputation remain in `missingly` and similar tools:
  - DQT offers sampling + bridge helpers,
  - DQT embeds external analyses when available, but stays fully usable without them.
- Define a **facets model** for data quality:
  - Profiling, DQ diagnostics, Rules, Cleansing, Metrics, Monitoring,
    Knowledge/Domain, Classification, Missingness (internal), Imputation (external),
    Reports, Viz/UI.
- Enforce scope: DQT will not implement service/performance metrics, masking/
  compliance, or MDM.
- Make tests, clear English docstrings (with arguments/returns/examples) and CI
  **first-class requirements** for any public API.
- Treat visualization, performance, and a DBA-friendly UI as explicit roadmap
  items (P5, D3).

**Next Steps:**
- Implement core SQL profiling + DQ diagnostics + rules + cleansing.
- Introduce `DQTPipeline` and `PipelineResult` with a clean public API.
- Define an optional `bridges` module to talk to `missingly` and other analyzers.
- Add testing layout, docstring policy, CI pipeline, visualization API,
  performance benchmarks, CLI, Rich CLI, and UI.
- Draft minimal CLI + report templates (EN/FA) for v0.1.0.

---

## Status Legend

- [ ] TODO — not started / not yet in code
- [~] IN PROGRESS — partially implemented / under refactor
- [x] DONE — implemented and verified in source

---

## P0 — Critical (core data-quality semantics)

### [ ] C1. SQL profiling & DQ diagnostics

- Implement `SqlProfiler` for Postgres/MySQL/SQL Server:
  - column stats: min/max, mean, distinct counts, null counts/ratios,
    pattern/length profiles.
  - table stats: row counts, orphan FK rows, referential integrity checks.
- Implement `DQDiagnostics`:
  - `DQIssue`, `DQDimension` (completeness, consistency, validity, uniqueness,
    timeliness),
  - severity + evidence, aggregated per table/column.

### [ ] C2. Rules engine (DB-level data quality)

- Implement rules engine (`Rule`, `RuleSet`, `RuleResult`) supporting:
  - column rules: range, regex, NOT NULL, uniqueness,
  - table rules: FK integrity, duplication, conditional constraints.
- Rules must be DBA-friendly:
  - YAML/JSON + Python API,
  - strictly about **data quality**, not service health.

### [ ] C3. Cleansing & repair primitives

- Provide minimal but robust cleansing primitives:
  - standardization (trim, normalize whitespace/case),
  - deduplication (based on keys or simple fuzzy matching),
  - lookup‑based correction using domain/knowledge tables.
- All cleansing must:
  - be logged (before/after), reversible, and auditable,
  - stay within data-quality scope.

### [ ] C4. Basic missingness stats (DQT internal)

- Compute internal completeness/missingness stats per table/column:
  - null counts, null ratios, simple co‑occurrence patterns.
- Expose them as part of `DQMetrics` without depending on any external package.

---

## P1 — Architecture (structural; unlocks maintainability and sister bridges)

### [ ] A1. DQTPipeline orchestrator

- Implement `DQTPipeline` with stages:
  - `discover_schema`, `profile_data`, `run_diagnostics`, `apply_rules`,
    `cleanse`, `compute_metrics`, `monitor`, `generate_report`.
- Expose:
  - `run(engine, config) -> PipelineResult`,
  - pure per‑run behavior (no global mutable state).

### [ ] A2. Facets-based module layout

- Map modules one-to-one with facets:
  - `schema_discovery.py`, `profiling.py`, `diagnostics.py`, `rules.py`,
    `cleansing.py`,
  - `metrics.py`, `monitoring.py`, `knowledge.py`, `classification.py`,
  - `reports.py`, `viz.py`, `bridges/`.
- Keep non‑DQ concerns out of core modules.

### [ ] A3. Public API surface

- At `dqt/__init__.py`, export:
  - `DQTPipeline`, `PipelineResult`, `RuleSet`, `DQIssue`, `DQMetrics`,
    `DomainConfig`, `ClassificationResult`.
- Provide helper constructors:
  - `from_sqlalchemy_engine()`, `from_dsn()`, `from_yaml_config()`.

---

## P2 — Bridges & Sister Integration (optional, no hard coupling)

### [ ] B1. Generic missingness bridge interface

- Define a generic interface for external missingness analyzers:
  - `MissingnessBridge` that:
    - receives a DataFrame/Arrow table sampled from SQL,
    - returns a structured result (`MissingnessReport`) independent of any specific package.

### [ ] B2. Optional `dqt.bridges.missingly`

- Implement `dqt.bridges.missingly` (extra dependency):
  - `sample_table(engine, table_name, limit, strategy) -> DataFrame`,
  - `run_missingly(df, config=None) -> MissingnessReport`,
  - `attach_missingly_result(pipeline_result, table_name, report)`.
- DQT core must **not** import `missingly` directly:
  - the bridges module imports `missingly` and is only used when explicitly called.

### [ ] B3. External analyses in PipelineResult

- Extend `PipelineResult` with:
  - `external_analyses: Dict[str, Dict[str, Any]]`, e.g. `"missingly" -> {table_name: report}`.
- Reports module:
  - if `external_analyses["missingly"]` exists, include a "Missing Data (sister package)" panel in HTML/PDF output;
  - otherwise, only show internal completeness/missingness stats.

---

## P3 — Testing, Docstrings, and CI (before v0.1.0)

### [ ] T1. Test layout and coverage

- Create `tests/` with clear separation:
  - `tests/unit/` for profiling, diagnostics, rules, cleansing, metrics, classification.
  - `tests/integration/` for DQTPipeline end-to-end runs on dockerized Postgres/MySQL/SQLite.
- Aim for high coverage on core modules; no public API without tests.

### [ ] T2. Docstring and examples policy

- Every public function/class **must** have a docstring with:
  - clear description of behavior,
  - arguments section (name, type, meaning, defaults),
  - returns section (type + semantics),
  - one minimal usage example.
- Docstrings and all code-level documentation **must be written in clear,
  unambiguous English only**; no mixed-language comments.
- Adopt a single style (e.g. Google-style docstrings) and enforce it via CI.

### [ ] T3. CI pipeline

- GitHub Actions workflow:
  - run `pytest` on supported Python versions,
  - run `mypy` and `ruff`/`black`,
  - fail on missing type coverage or lint violations.
- Optional: job for building docs (mkdocs/Sphinx) and ensuring they compile.

---

## P4 — Documentation, Ecosystem Matrix, UX

### [ ] D1. Bilingual documentation & reports

- `README.en.md` — English (technical).
- `README.fa.md` — Persian (DBA-oriented explanation of DQ facets and how DQT and `missingly` fit together).
- Reports:
  - bilingual headings (EN/FA),
  - translated data-quality dimensions (e.g. completeness → "data completeness").

### [ ] D2. Ecosystem matrix doc

- Create `docs/dqt_ecosystem.md` (see file below):
  - rows: DQT, `missingly`, Baselinr, Soda, SQL Server DQS, SSIS Data Profiling,
    SSIS DQS Cleansing, Redgate SQL Data Catalog, Apache Griffin, Talend DQ,
    MobyDQ, OpenRefine+MetricDoc, DataLens.
  - columns: Profiling, DQ diagnostics, Rules, Cleansing, Metrics, Monitoring,
    Knowledge, Classification, Missingness (internal), Imputation (external),
    Reports, Viz/UI, "Uses `missingly`".
- Use the matrix as the design north star; update when facets change.

### [ ] D3. UI (desktop/web) for DBAs

- Provide a **DBA-friendly UI** in addition to CLI:
  - either a desktop app (e.g. Qt) or a web UI (e.g. FastAPI + frontend),
  - backed by the same DQTPipeline APIs used by the CLI.
- The UI should let users:
  - select connections/schemas/tables,
  - run profiling and rules checks,
  - explore metrics and issues via tables and charts,
  - filter, sort, and search issues,
  - export HTML/PDF reports.
- Keep UI focused on data quality:
  - no service/performance dashboards,
  - no masking/compliance configuration,
  - no MDM workflows.

### [ ] Q1. Minimal CLI surface

- Implement `dqt` CLI:
  - `dqt profile --dsn ... --schema ...` → profiling + diagnostics report.
  - `dqt check --rules rules.yaml` → rules summary.
  - `dqt missing --table ...` → sample + call missingness bridge (if configured) and embed results.

### [ ] Q2. Rich CLI

- Implement a rich CLI (e.g. using Rich) with:
  - progress bars for long-running operations,
  - structured, colorized output tables for metrics and issues,
  - clear error messages and exit codes.

### [ ] Q3. HTML report template

- Implement `reports.py` HTML template:
  - per-table/column data-quality metrics,
  - optional external missingness panel,
  - scorecard for core data-quality dimensions.

### [ ] Q4. Integration test with `missingly` bridge

- Add tests demonstrating sister usage:
  - create a test table with controlled missingness,
  - run DQT profiling + diagnostics,
  - call `bridges.missingly` to attach analysis,
  - assert that the report contains both DQT and `missingly` sections.

---

## P5 — Visualization and Performance

### [ ] V1. Visualization API

- Provide a small, consistent visualization API:
  - functions for column/table scorecards, issue summaries, and trend charts
    over time.
  - output as Plotly/Matplotlib or similar, and embedded into HTML reports and UI.
- Ensure visual defaults are DBA-friendly:
  - clear labels and legends,
  - no unnecessary ML jargon or noisy plots.

### [ ] V2. Performance budgets and profiling

- Define performance budgets for core operations (profiling, diagnostics, rules).
- Add benchmarks on realistic datasets (large tables, multiple schemas).
- Optimize:
  - SQL queries (indexes, joins, aggregation),
  - batching and concurrency,
  - avoiding full-table scans when unnecessary.
- Track performance regressions in CI where feasible (e.g. simple benchmark suite).

---

## Keep As-Is / External (do not re-implement)

- `missingly` algorithms (missingness diagnostics, multi-imputation) — DQT **uses** them via bridges; does **not** re-implement.
- Service/performance monitoring (latency, CPU, wait stats, uptime) — out of scope.
- Masking/compliance features (SQL Data Catalog + Data Masker) — out of scope.
- MDM/golden record (SQL Server MDS) — out of scope.

---

## Recommended Execution Order for DQT v0.1.0

1. C1, C2, C3, C4 — build core SQL data-quality features (profiling, diagnostics, rules, cleansing, basic missingness stats).
2. A1, A2, A3 — introduce DQTPipeline, facets-based modules, and public API surface.
3. T1, T2, T3 — establish tests, docstring policy, and CI pipeline.
4. B1, B2, B3 — implement generic MissingnessBridge and optional `bridges.missingly`.
5. D1, D2, D3, Q1–Q4, V1–V2 — docs, ecosystem matrix, CLI, rich CLI, UI, HTML report,
   visualization API, performance benchmarks, and integration tests.
