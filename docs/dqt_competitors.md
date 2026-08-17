# DQT Competitors, Feature Floor, and Current Gap

> *Verified against the repository on 2026-08-17 at commit `4629925`. Statuses rot — re-check before relying on one.*


This document does three things: defines the **minimum capability floor** DQT
must reach before release, records **where DQT actually stands against that
floor**, and tracks **best-of features** worth borrowing from other tools.

> **What changed and why.** The previous revision defined a floor and never
> compared it to reality, so a list of unbuilt capabilities read like a
> description of the product. Every floor item now carries a status column. It is
> not flattering, and that is the point — a floor you never measure yourself
> against is a wish list.
>
> Maintenance status has also been added to each competitor. Two of the eight
> originally listed have since been retired.

---

## 1. Baseline Feature Floor — and DQT's Actual Position

Status: `MET` · `PARTIAL` · `NOT MET`. Evidence is source-read, not inferred.

| # | Floor requirement | Status | Where DQT actually is |
|---|---|---|---|
| F1 | **Profiling** — column stats (min, max, mean, distinct, null count/ratio) | PARTIAL | Null counts, row counts, completeness only. No min/max/mean/distinct/patterns. |
| F2 | **Profiling** — table stats (row counts, orphan FK rows, referential integrity) | NOT MET | Row counts only. No orphan-FK detection. |
| F3 | **Diagnostics** — all six canonical dimensions with structured issue objects | NOT MET | `completeness` only. Issue objects themselves are well-structured. |
| F4 | **Rules** — column rules (range, regex, type, uniqueness, NOT NULL) | PARTIAL | Four expressions declared, YAML/JSON-driven; `not_null`/`unique`/`range` unit-tested. **`regex` is dead on SQLite** — no REGEXP function is registered, so every regex rule emits a permanent false `error`. Semantic validity is the stated differentiator, so this is the costliest single gap. |
| F5 | **Rules** — table rules (FK integrity, duplication, conditional constraints) | NOT MET | Column scope only. |
| F6 | **Cleansing** — reversible standardization, dedup, lookup correction with audit trail | PARTIAL | Write-capable primitives exist (real `UPDATE`/`DELETE` + `commit()`). `run()` *does* call `cleanse()` on every run, but it reaches a pass-through, so nothing is written today — the primitives sit one wiring commit off the default path. "Reversible" currently means *manually* reconstructable, the audit log is not persisted, and there is no plan/apply split. Not safely usable as-is. |
| F7 | **Metrics** — per table/column/dimension scores | PARTIAL | Three global metrics: table count, column count, average completeness. |
| F8 | **Monitoring** — metric snapshots over time + drift detection | NOT MET | `monitor()` returns its input unchanged. Storage exists but no trend layer. |
| F9 | **Knowledge/Domain** — reference tables for validation | NOT MET | No module. |
| F10 | **Classification** — semantic column typing | NOT MET | No module. The `semantic_type` field exists and is never populated. |
| F11 | **Missingness (internal)** — null stats and patterns | PARTIAL | Counts and ratios; no co-occurrence patterns. |
| F12 | **Reports** — HTML/PDF, per-table/column metrics, issues, trends | PARTIAL | Self-contained HTML with score bars and severity badges. No PDF, no bilingual content, no trends. |
| F13 | **Code quality** — English docstrings, unit + integration tests, CI (pytest/mypy/ruff) | PARTIAL | CI is real and enforces lint, strict typing, and an 80% coverage gate. **Six** modules have zero unit tests (`profiling`, `diagnostics`, `metrics`, `monitoring`, `schema_discovery`, `reports`), plus both `ui/` modules; docstring compliance unaudited; PostgreSQL — the primary target — is untested in CI. |
| F14 | **CLI** — profile, check rules, generate reports | PARTIAL | `dqt profile` only. `check` and `missing` subcommands absent. |

| F15 | **Read-only query/API surface** for downstream consumers | PARTIAL | `ui/api.py` + a FastAPI skeleton in `ui/app.py` expose runs, tables, metrics and issues read-only. Untested; no frontend. |

**Score: 0 of 15 fully met** (was recorded as 1 of 14 before `regex` was found
dead on SQLite). Nothing here is a reason for discouragement — the
architecture, data model, rule engine, and CI are real and sound. But DQT is not
currently at its own stated floor, and any document, README, or matrix that
implies otherwise should be corrected rather than defended.

**Release rule:** a floor item may not be marked `MET` on the strength of a
module existing, or of a module plus a test that only asserts the code does what
the code does. It requires read source and an externally grounded passing test —
see the honesty gate in `CONVENTIONS-DQT.md` §4.

F4 is the cautionary example: it sat at `MET` because four rule expressions
existed and three of them had tests. The fourth had no test and had never worked
on the only fully supported backend.

---

## 2. Competitors and Best-of Features

Status key: **Active** · **Retired** · **Commercial** (OSS edition discontinued)
· **Research** · **Unverified**

### 2.1 Great Expectations — Active

Expectation-based data testing, documentation, and profiling.

**Best-of:** large built-in expectation library; auto-generated HTML "Data Docs";
cross-platform (pandas, Spark, SQL, warehouses); CI/CD integration that fails
builds on data-quality regressions.

**For DQT:** floor — a minimal expectation-like rule system for SQL (F4/F5).
Stretch — a curated, extensible rule catalog with generated documentation.

**Caution:** GX 1.x reorganized its concepts substantially from the 0.18 line.
Any DQT design borrowed from GX must be checked against current GX docs, not the
0.18 branch, which is explicitly unmaintained.

### 2.2 Soda Core — Active

SQL-centric checks via YAML or SQL.

**Best-of:** SQL-first check definitions; monitoring and alerting via Soda Cloud;
warehouse-native design.

**For DQT:** SQL-first thinking for rules and diagnostics is already DQT's core
identity. Stretch — a simple outbound integration point for pushing metrics and
events to an external monitoring stack, rather than building alerting in-house.

### 2.3 Baselinr — Active (young, 2025)

Open-source data quality and observability for SQL warehouses.

**Best-of:** end-to-end coverage (profiling, diagnostics, validation, schema and
statistical drift, anomaly detection); dbt/Airflow/Dagster integration; web
dashboard, CLI, and Python SDK; multi-database (PostgreSQL, MySQL, SQLite,
Snowflake, BigQuery, Redshift).

**For DQT:** this is the **closest direct competitor** and the most useful
benchmark in this document — same positioning, same stack family, similar
surface. Floor — profiling and diagnostics for SQL tables. Stretch — drift
detection for metrics, which maps directly to DQT's unbuilt F8.

**Honest note:** Baselinr already delivers most of DQT's target row. DQT's
defensible differentiation is DBA-first framing, a lean dependency footprint, and
bilingual EN/FA reporting — not feature count. That should shape the roadmap.

### 2.4 Apache Griffin — **Retired (Attic, 2025)**

Big-data data quality for batch and streaming.

**Best-of (historical):** a flexible rule DSL tied to a metric model; batch and
streaming; metric dashboards over time.

**For DQT:** the rule-DSL-and-metric-model design remains a good reference. Do
**not** treat Griffin as a live competitive baseline or cite it as evidence that
a capability is table stakes today.

### 2.5 Talend Data Quality — **Commercial (OSS retired 31 Jan 2024)**

**Best-of:** graphical profiling; strong cleansing and standardization; a
composite "trust score"; and — most relevant to DQT — **column-level quality bars
showing valid/invalid/empty distribution directly in column headers**.

**For DQT:** the quality-bar visual is the single best UX idea in this document
and maps cleanly onto DQT's `DQMetric` model. Stretch — a DQT quality score per
table. Masking/compliance is explicitly out of scope and must not follow the
visual idea in.

**Caution:** Talend Open Studio no longer exists as an open-source option. It
cannot be positioned as "the free alternative DQT competes with".

### 2.6 MobyDQ — Unverified

Pipeline-oriented data-quality indicators.

**Best-of:** indicator design toolbox; alerting on indicator failure.

**For DQT:** floor — basic completeness and validity metrics. Stretch — simple
alerting hooks.

**Scope warning:** MobyDQ's indicator set includes "latency". That means *data*
latency — how stale the data is — which maps to DQT's `timeliness` dimension.
It does **not** mean service latency, which is a permanent non-goal. This
document previously listed the term without the distinction, which is exactly the
kind of vocabulary bleed that pulls service metrics into a data-quality product.

### 2.7 OpenRefine — Active

Interactive tabular cleaning with faceted exploration.

**Best-of:** faceted browsing; clustering; undo/redo history; strong
human-in-the-loop repair.

**For DQT:** stretch — faceted filtering for issue lists, and a clear history of
applied cleansing actions. OpenRefine's undo model is also the right mental model
for DQT's undo-statement requirement: reversibility is a first-class feature, not
a log.

**Not applicable:** single-dataset, project-centric; no multi-schema SQL view, no
metrics over time.

### 2.8 DataLens (research prototype) — Research

arXiv:2501.17074 — an ML-oriented interactive dashboard for tabular data quality.

**Best-of:** integrated profiling, error detection and repair combining
statistical, rule-based and ML methods; user-in-the-loop rule validation and
labeling; iterative cleaning strategy selection; experiment tracking.

**For DQT:** floor — none. Stretch — a clean abstraction where ML-based detectors
could be plugged in later, and a future path to interactive rule validation.

**Naming caution:** this is a research prototype, not Yandex DataLens (a
commercial BI product with the same name). They are unrelated. Do not attribute
BI dashboard features to this tool.

---

## 3. Floor vs. Stretch — summary

**Floor (must be solid before v0.1.0 release):**
SQL profiling · diagnostics across all six dimensions · a rule engine covering
column *and* table scope · **safe** cleansing primitives · core metrics · a
minimal monitoring/trend layer · clear HTML reports · tested public APIs.

**Stretch (directional):**
Rule catalog with generated docs (GX) · warehouse/pipeline monitoring with alerts
(Soda, Baselinr) · column-level quality bars and a table trust score (Talend) ·
faceted issue exploration and first-class undo (OpenRefine) · pluggable ML
detectors (DataLens research) · a well-structured metric model (Griffin,
historical).

DQT should never try to match all of these. The floor defines what "usable"
means; the stretch list defines where a lean, DBA-focused, SQL-centric tool can
be genuinely better than a general-purpose one — by being narrower and more
trustworthy, not broader.
