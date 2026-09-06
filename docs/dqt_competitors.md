# DQT Competitors, Feature Floor, and Current Gap

> *Section 1 re-verified against the repository on 2026-09-06 at commit `1fee86e`
> (version `1.1.0`). Sections 2 and 3 were last checked on 2026-08-17 at commit
> `4629925` and are not re-verified here. Statuses rot — re-check before relying
> on one.*


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

| # | Floor requirement | Aug 17 | **Now** | Where DQT actually is, at `1.1.0` |
|---|---|---|---|---|
| F1 | **Profiling** — column stats (min, max, mean, distinct, null count/ratio) | PARTIAL | **PARTIAL** | Unchanged. `ColumnProfile` carries `null_count` and `row_count` and nothing else — no min, max, mean, distinct or patterns. The single largest gap against what a DBA expects from the word "profiling". |
| F2 | **Profiling** — table stats (row counts, orphan FK rows, referential integrity) | NOT MET | **NOT MET** | Row counts, plus sampling metadata when a sample was taken. Still no orphan-FK detection and no FK discovery. |
| F3 | **Diagnostics** — all six canonical dimensions with structured issue objects | NOT MET | **NOT MET** | `completeness` only, one of six. `DQDiagnostics` says so in its own docstring. Issue objects remain well-structured. |
| F4 | **Rules** — column rules (range, regex, type, uniqueness, NOT NULL) | PARTIAL | **MET** | Five expressions, all working and tested: `NOT NULL`, `UNIQUE`, `RANGE`, `REGEX`, `REFERENCE`. `DQT-04` fixed `regex` on SQLite. Rules compile to grouped aggregate SQL, one scan per table. **`REGEX` is refused on SQL Server** — T-SQL has no such operator, and refusing is deliberate rather than reporting zero violations. |
| F5 | **Rules** — table rules (FK integrity, duplication, conditional constraints) | NOT MET | **NOT MET** | Column scope only. `RuleScope` has a `column_pattern`; nothing evaluates a table-level predicate. |
| F6 | **Cleansing** — reversible standardization, dedup, lookup correction with audit trail | PARTIAL | **MET** | `cleanse_plan()` / `cleanse_apply()` / `revert()`. The log is persisted against a `plan_id`, planning works against a read-only connection, and `cleanse_apply` refuses an already-applied plan, a read-only connection, or **data that drifted since the plan was computed**. Deduplication deletes and `revert` re-inserts the whole row. **Open gap:** `revert()` does not make that drift check — an edit made after apply is overwritten without warning. |
| F7 | **Metrics** — per table/column/dimension scores | PARTIAL | **PARTIAL** | Unchanged: three global metrics (`table_count`, `column_count`, `average_completeness`). Per-column completeness reaches the report and the UI, but not as `DQMetric` rows. |
| F8 | **Monitoring** — metric snapshots over time + drift detection | NOT MET | **PARTIAL** | Run history is stored and **rule pass-rate over time is charted** in the UI (`trend_line`, `load_rule_history`). But `monitor()` is still the identity function, there is no metric-level trend and no drift or anomaly detection. |
| F9 | **Knowledge/Domain** — reference tables for validation | NOT MET | **MET** | `sql/knowledge.py`, reachable through the `REFERENCE` rule expression: values must appear in a reference list or table, matched with an anti-join over `SELECT DISTINCT` so duplicate reference rows cannot inflate the denominator. Optional Persian character folding. |
| F10 | **Classification** — semantic column typing | NOT MET | **PARTIAL** | `classification.py` is real and locale-aware — Iranian national ID, IBAN/Sheba, mobile and landline numbers, Shamsi dates, email — and `classify_column` is publicly exported. **But nothing calls it during a run.** It is a library function, not a pipeline stage, so `semantic_type` is still never populated and a UI user never sees a classification. |
| F11 | **Missingness (internal)** — null stats and patterns | PARTIAL | **PARTIAL** | Counts and ratios internally. Co-occurrence patterns exist only through the optional `missingly` bridge, which is external by design. |
| F12 | **Reports** — HTML/PDF, per-table/column metrics, issues, trends | PARTIAL | **PARTIAL** | Self-contained HTML — verified to contain zero external references, so it survives being emailed. Bilingual EN/FA with RTL, an embedded font, and WCAG AA contrast computed in CI. A trend chart exists on the rule-history screen. **No PDF.** |
| F13 | **Code quality** — English docstrings, unit + integration tests, CI (pytest/mypy/ruff) | PARTIAL | **MET** | 1079 tests passing, coverage 95.51% against a 95 floor, `mypy --strict` clean, `ruff` clean, `doc_audit` and `arch_audit` at zero. Python 3.11 / 3.12 / 3.14, and **all three databases exercised against live servers in CI** — including SQL Server, which is what closed the biggest hole in this row. |
| F14 | **CLI** — profile, check rules, generate reports | PARTIAL | **PARTIAL** | `dqt profile` only, and it does run rules when a config supplies `rule_files`. There is still no `check` subcommand and **no `serve`**, so starting the dashboard needs a `uvicorn` command rather than a DQT one. |
| F15 | **Read-only query/API surface** for downstream consumers | PARTIAL | **MET** | Six JSON endpoints and five server-rendered HTML screens, tested, and frozen under the `1.0` API contract. No JS and no build step. **No authentication** — by design, and the reason the documented way to run it binds loopback. |

**Score: 5 of 15 met, 7 partial, 3 not met** — up from 0 of 15 in August.

Read the shape rather than the score. What moved was **safety and
trustworthiness**: cleansing became genuinely reversible, the rule engine
stopped lying on SQLite, every dialect gained a live CI server, and the
quality gates went from aspiration to enforcement. What did **not** move is
**breadth of analysis**: F1, F3 and F5 are the same as they were, and they are
the three a DBA notices first, because they are what the words "profiling" and
"rules" promise.

Two rows deserve reading twice:

* **F10 is the clearest case of a module that exists and a product that does
  not use it.** The classification code is good and locale-aware; nothing
  invokes it during a run. That is precisely the failure this document's own
  release rule was written to catch, and it is caught here rather than scored
  as `MET`.
* **F8 improved by accident of the UI, not by design.** Rule history charts
  because someone built a rules screen, not because a monitoring facet was
  built. `monitor()` is still the identity function.

**Release rule:** a floor item may not be marked `MET` on the strength of a
module existing, or of a module plus a test that only asserts the code does what
the code does. It requires read source and an externally grounded passing test —
see the honesty gate in `CONVENTIONS-DQT.md` §4.

F4 is the cautionary example, and it has now been both things. It once sat at
`MET` because four rule expressions existed and three of them had tests; the
fourth had no test and had never worked on the only supported backend. It is
`MET` again today — but on different evidence: five expressions, each with a
test, exercised against three live databases, and one of them (`REGEX` on SQL
Server) *refused* rather than silently passing where it cannot work.

The difference between those two `MET`s is the whole point of the rule.

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
