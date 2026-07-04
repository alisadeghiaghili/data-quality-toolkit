# DQT Competitors and Best-of Features

This document lists key competitors to **DQT (SQL Data Quality Toolkit)** and the
best features they offer, so we can continuously benchmark DQT against them.
It also defines a **baseline feature floor** for DQT and highlights aspirational
targets inspired by each tool.

Sources include surveys of data quality tools and dimensions, as well as
individual tool documentation.

---

## 1. Baseline Feature Floor for DQT

DQT is a **DBA-focused, SQL-first data quality toolkit**. The baseline floor
defines the minimum acceptable capabilities before DQT can be considered
seriously usable.

### 1.1 Core Data Quality Facets (Floor)

DQT must **at least** support:

- **Profiling**
  - Column-level stats: min, max, mean, distinct count, null count/ratio.
  - Table-level stats: row counts, orphan foreign-key rows, referential integrity issues.

- **DQ Diagnostics**
  - Issue types: completeness, consistency, validity, uniqueness, timeliness, referential integrity.
  - Structured diagnostics objects (issue type, severity, evidence).

- **Rules**
  - Declarative rule engine for:
    - Column rules: ranges, regex, type checks, uniqueness, NOT NULL.
    - Table rules: foreign-key integrity, duplication, conditional constraints.
  - Rules definable via YAML/JSON or Python API.

- **Cleansing**
  - Reversible operations:
    - Standardization (trim, case normalization, canonical forms).
    - Deduplication (key-based, simple fuzzy matching).
    - Lookup-based corrections using domain tables.
  - Logging and audit trail for before/after states.

- **Metrics**
  - Quantitative data-quality metrics per table/column and per dimension
    (e.g. completeness score, validity score).

- **Monitoring**
  - Snapshotting metrics over time and basic trend analysis.
  - Ability to detect drops or drift in data quality (not service metrics).

- **Knowledge / Domain**
  - Reference tables and domain lists to validate values (e.g. country codes,
    known categories).

- **Classification**
  - Semantic typing for columns (email, phone, IBAN, national_id, date, amount)
    to apply appropriate rules and visualizations.

- **Missingness (internal)**
  - Basic completeness/missingness statistics; null patterns and ratios.

- **Reports & Visualization**
  - HTML/PDF reports summarizing:
    - per-table and per-column metrics,
    - issues and rules results,
    - trends over time.
  - Scorecards and simple charts (bar/line) for DQ metrics and issue counts.

- **Code Quality & UX**
  - Clear English docstrings for all public APIs:
    - behavior, arguments, returns, examples.
  - Unit + integration tests for all public APIs, with CI running pytest, mypy,
    ruff/black.
  - CLI for profiling, checking rules, and generating reports.

---

## 2. Competitors and Their Best Features

This section lists selected competitors and the **best-of features** we want to
keep an eye on. For each tool we highlight:
- standout capabilities,
- why they matter,
- whether they are **floor** or **stretch** for DQT.

### 2.1 Great Expectations (GX)

Core idea: expectation-based data testing, documentation, and profiling.

**Best-of features:**

- Rich **expectation library**:
  - Dozens of built-in expectations for schema, ranges, uniqueness, regex,
    nulls, distributions, etc.
- **Data Docs**:
  - Automatically generated HTML documentation of expectations, validation
    results, and data assets.
- **Cross-platform support**:
  - Pandas, Spark, SQL databases, cloud warehouses.
- **CI/CD integration**:
  - Validations as part of pipelines; fail builds on data-quality regressions.

**Implications for DQT:**

- DQT floor: a minimal expectation-like rule system for SQL (already in baseline).
- Stretch: a curated, extensible rule catalog and auto-generated docs similar to
  Data Docs.

---

### 2.2 Soda Core

SQL-centric data testing via extended SQL queries.

**Best-of features:**

- **SQL-first checks**:
  - Define data-quality checks as SQL queries or Soda's YAML syntax.
- **Monitoring and alerts**:
  - Integration with Soda Cloud for continuous monitoring, alerting, and
    collaboration.
- **Warehouse-native design**:
  - Targets data warehouses and lakes (BigQuery, Snowflake, etc.).

**Implications for DQT:**

- DQT should adopt SQL-first thinking for rules and diagnostics.
- Stretch: simple integration points for external monitoring stack.

---

### 2.3 Baselinr

Open-source data quality platform for SQL warehouses.

**Best-of features:**

- **End-to-end pipeline coverage**:
  - Profiling, diagnostics, validation, drift detection, anomaly detection.
- **Warehouse integration**:
  - Tight integration with dbt, Airflow, Dagster, and popular warehouses.
- **Transparency & control**:
  - Rule definitions and checks are explicit and inspectable.

**Implications for DQT:**

- Floor: robust profiling + diagnostics for SQL tables.
- Stretch: richer anomaly/drift detection for data quality metrics.

---

### 2.4 Apache Griffin

Big-data data quality solution for batch and streaming.

**Best-of features:**

- **Rule DSL and metrics**:
  - Flexible DSL for defining DQ rules and associated metrics.
- **Batch + streaming**:
  - Supports data quality in streaming contexts (e.g. Spark).
- **Dashboarding and monitoring**:
  - Visualization of metrics over time for distributed systems.

**Implications for DQT:**

- Floor: rule engine with metrics for relational databases.
- Stretch: well-designed metric model and dashboards for DBA workflows.

---

### 2.5 Talend Open Studio for Data Quality

Talend's data quality stack for profiling, cleansing, and masking.

**Best-of features:**

- **Graphical profiling and exploration**:
  - Visual profiling views (distributions, patterns, anomalies).
- **Cleansing and standardization**:
  - Built-in transforms for standardizing, deduplicating, and enriching data.
- **Trust score**:
  - A composite data-quality score to summarize dataset quality.

**Implications for DQT:**

- Floor: strong profiling + cleansing primitives.
- Stretch: interactive/visual profiling and a DQT "quality score" per table.

---

### 2.6 MobyDQ

Open-source data-quality tool for pipelines.

**Best-of features:**

- **Indicators for pipeline-oriented questions**:
  - Completeness, freshness, latency, validity, anomaly detection.
- **Custom indicator design**:
  - Toolbox for designing DQ indicators tailored to pipeline requirements.
- **Alerts and observability**:
  - Captures DQ issues and triggers alerts when indicators fail.

**Implications for DQT:**

- Floor: basic completeness and validity metrics.
- Stretch: pipeline-oriented metrics (freshness) and simple alerting hooks.

---

### 2.7 OpenRefine

Interactive tabular data cleaning.

**Best-of features:**

- **Interactive exploration and cleaning**:
  - Faceted browsing and transformation of tabular data.
- **Strong UI for manual repair**:
  - Human-in-the-loop cleaning for complex issues.

**Implications for DQT:**

- Stretch: interactive views or good HTML reports that DBAs can use to inspect
  and manually fix issues.

---

### 2.8 DataLens

ML-oriented interactive tabular data-quality dashboard.

**Best-of features:**

- **Integrated profiling, error detection, and repair**:
  - Combines statistical, rule-based, and ML-based methods.
- **User-in-the-loop module**:
  - Interactive rule validation, data labeling, and custom rule definition.
- **Iterative cleaning**:
  - Automatic selection of cleaning strategies guided by ML and user feedback.

**Implications for DQT:**

- Floor: none (DQT is not ML-heavy by default).
- Stretch: clean abstraction for plugging in ML-based detectors.

---

## 3. Floor vs. Stretch Summary

- **Floor (must-have for DQT)**:
  - SQL profiling (GX, Soda, Talend, Griffin).
  - Strong diagnostics and rule engine (GX, Soda, Griffin, DQS).
  - Basic cleansing primitives (Talend, OpenRefine).
  - Core metrics and simple monitoring (MobyDQ, Griffin).
  - Clear, visual HTML/PDF reports (GX, Talend, DataLens).

- **Stretch (directional goals)**:
  - Rich expectation catalog + auto docs (GX).
  - Warehouse- and pipeline-friendly monitoring with alerts (Soda, Baselinr, MobyDQ).
  - Well-structured DQ metric model and dashboards (Griffin, Talend).
  - Interactive exploration / human-in-the-loop cleaning (OpenRefine, DataLens).
  - ML-based anomaly/error detection & guided repair (DataLens, MobyDQ).
