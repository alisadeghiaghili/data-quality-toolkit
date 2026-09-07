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
| F1 | **Profiling** — column stats (min, max, mean, distinct, null count/ratio) | PARTIAL | **MET** | All five, in **one aggregate query per table** whatever the column count — a test counts the statements SQLite actually executes, because a per-column implementation returns identical numbers. `MIN`/`MAX`/`AVG` are gated on the column's type by the **dialect**, since `TEXT` orders fine on SQLite and errors on SQL Server. Distinct counting is on by default and can be declined; an estimate is flagged as one. Patterns are still absent — see F11. |
| F2 | **Profiling** — table stats (row counts, orphan FK rows, referential integrity) | NOT MET | **MET** | Foreign keys discovered on all three engines, on the same connection as the column catalogue. Orphan rows counted with one `COUNT(*)` anti-join per key, no rows materialised. Composite keys are matched **whole** — a per-column comparison calls a row satisfied when half of it matches — and a NULL reference is not an orphan. Surfaces as the `referential_integrity` dimension, which the dashboard had always rendered "not measured". |
| F3 | **Diagnostics** — all six canonical dimensions with structured issue objects | NOT MET | **MET** | All six. `completeness`, `uniqueness` and `consistency` from the profiling pass; `referential_integrity` from F2. `validity` and `timeliness` differ in kind and say so: neither is answerable from the data alone — whether `"n/a"` is a valid email depends on what the column is for, and whether a 90-day-old table is stale depends on whether it is a ledger or an archive. Validity is measured when classification supplies an expectation; timeliness reports data age as a measurement always and scores it only against a configured maximum. Neither invents a default. |
| F4 | **Rules** — column rules (range, regex, type, uniqueness, NOT NULL) | PARTIAL | **MET** | Five expressions, all working and tested: `NOT NULL`, `UNIQUE`, `RANGE`, `REGEX`, `REFERENCE`. `DQT-04` fixed `regex` on SQLite. Rules compile to grouped aggregate SQL, one scan per table. **`REGEX` is refused on SQL Server** — T-SQL has no such operator, and refusing is deliberate rather than reporting zero violations. |
| F5 | **Rules** — table rules (FK integrity, duplication, conditional constraints) | NOT MET | **MET** | All three, one target per table rather than one per column. `UNIQUE_TOGETHER` is a composite key the schema does not declare; `FOREIGN_KEY` is referential integrity for relationships the database does **not** enforce, which is where orphans actually accumulate; `CONDITIONAL_NOT_NULL` covers the shape most real conditional constraints take. **None takes SQL from the user** — identifiers go through the quoting path and are checked against the table, values are bound. A raw-predicate rule stays undecided in `BACKLOG.md` §3 rather than being settled by implementation. |
| F6 | **Cleansing** — reversible standardization, dedup, lookup correction with audit trail | PARTIAL | **MET** | `cleanse_plan()` / `cleanse_apply()` / `revert()`. The log is persisted against a `plan_id`, planning works against a read-only connection, and `cleanse_apply` refuses an already-applied plan, a read-only connection, or **data that drifted since the plan was computed**. Deduplication deletes and `revert` re-inserts the whole row. **Open gap:** `revert()` does not make that drift check — an edit made after apply is overwritten without warning. |
| F7 | **Metrics** — per table/column/dimension scores | PARTIAL | **PARTIAL** | Unchanged: three global metrics (`table_count`, `column_count`, `average_completeness`). Per-column completeness reaches the report and the UI, but not as `DQMetric` rows. |
| F8 | **Monitoring** — metric snapshots over time + drift detection | NOT MET | **PARTIAL** | Run history is stored and **rule pass-rate over time is charted** in the UI (`trend_line`, `load_rule_history`). But `monitor()` is still the identity function, there is no metric-level trend and no drift or anomaly detection. |
| F9 | **Knowledge/Domain** — reference tables for validation | NOT MET | **MET** | `sql/knowledge.py`, reachable through the `REFERENCE` rule expression: values must appear in a reference list or table, matched with an anti-join over `SELECT DISTINCT` so duplicate reference rows cannot inflate the denominator. Optional Persian character folding. |
| F10 | **Classification** — semantic column typing | NOT MET | **MET** | Runs as a pipeline stage and populates `ColumnResult.semantic_type`, rendered in the report beside the database type. **Off by default** — not for cost but for what it reads: it is the only stage that pulls real values into Python, and the validators are most useful exactly where the values are most sensitive. One bounded query per table when enabled. |
| F11 | **Missingness (internal)** — null stats and patterns | PARTIAL | **PARTIAL** | Counts and ratios internally. Co-occurrence patterns exist only through the optional `missingly` bridge, which is external by design. |
| F12 | **Reports** — HTML/PDF, per-table/column metrics, issues, trends | PARTIAL | **PARTIAL** | Self-contained HTML — verified to contain zero external references, so it survives being emailed. Bilingual EN/FA with RTL, an embedded font, and WCAG AA contrast computed in CI. A trend chart exists on the rule-history screen. **No PDF.** |
| F13 | **Code quality** — English docstrings, unit + integration tests, CI (pytest/mypy/ruff) | PARTIAL | **MET** | 1079 tests passing, coverage 95.51% against a 95 floor, `mypy --strict` clean, `ruff` clean, `doc_audit` and `arch_audit` at zero. Python 3.11 / 3.12 / 3.14, and **all three databases exercised against live servers in CI** — including SQL Server, which is what closed the biggest hole in this row. |
| F14 | **CLI** — profile, check rules, generate reports | PARTIAL | **MET** | `dqt profile`, `dqt check` (rules only, for CI — no column statistics computed) and `dqt serve`. `serve` is what makes the dashboard startable without Python, and it is where the loopback rule stopped being a docstring: it binds `127.0.0.1` and **refuses** a reachable address unless told something authenticates in front. |
| F15 | **Read-only query/API surface** for downstream consumers | PARTIAL | **MET** | Six JSON endpoints and five server-rendered HTML screens, tested, and frozen under the `1.0` API contract. No JS and no build step. **No authentication** — by design, and the reason the documented way to run it binds loopback. |

**Score: 11 of 15 met, 4 partial, 0 not met** — up from 0 of 15 in August.
F1, F2, F3, F5, F10 and F14 closed on 2026-09-07, along with the roadmap's own
`DQT-09`. **Nothing is outright unmet any more**; the four partials are F7
(metrics per scope), F8 (drift), F11 (missingness patterns) and F12 (PDF).

A sequenced plan for the remaining ten, with its dependencies and the one
decision that blocks a full score, is in
[`ROADMAP-FLOOR-15.md`](ROADMAP-FLOOR-15.md).

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
* **F10 is closed, and the note that recorded it as `PARTIAL` is worth
  keeping.** The module was real, tested and exported, and nothing called it.
  What closed the row was forty lines of wiring, which is the point: the gap
  between "built" and "reachable" cost nothing to cross and had gone
  uncrossed for as long as the module existed.
* **F1 was the keystone, and closing it changes what F3, F5 and F7 cost.**
  A distinct count is what a uniqueness *diagnostic* needs; bounds are what a
  validity diagnostic needs. Those rows are now "expose what exists" rather
  than "build it".
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
