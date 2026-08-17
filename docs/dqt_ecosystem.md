# DQT Ecosystem Matrix

> *Verified against the repository on 2026-08-17 at commit `4629925`. Statuses rot — re-check before relying on one.*


> **Reading this matrix honestly.** Two changes from earlier revisions, both
> necessary for it to mean anything:
>
> 1. DQT appears as **two rows** — `DQT (current)` and `DQT (target v1.0)`.
>    Previously a single aspirational DQT row sat beside competitors' actual
>    capabilities, which compared a plan to a product and made DQT look
>    competitive on facets where it has no code at all.
> 2. The `Uses missingly` column is **removed**. It was a facet only DQT could
>    score on, by construction — a self-certifying column that turned a
>    benchmarking tool into a marketing one. It is replaced by
>    **Extensibility**: can this tool consume analyses from an external analyzer
>    through a documented interface? That is the same underlying property, stated
>    so that others can actually compete on it.
>
> **Maintenance status is now recorded.** Benchmarking a roadmap against retired
> software produces a roadmap aimed at 2019.

Legend (per facet): `✓✓` strong · `✓` partial · `~` limited/niche · `-` none/out of scope

Facets:

- **Profiling** — SQL/data profiling (stats, patterns, keys, FKs)
- **DQ Diagn** — diagnostics across the six canonical dimensions
- **Rules** — declarative data-quality checks
- **Cleansing** — repair (standardization, dedup, lookup correction)
- **Metrics** — quantitative scores
- **Monitoring** — tracking data-quality metrics over time + alerts
- **Knowledge** — domain/reference data
- **Classif.** — semantic column typing
- **Missing (int)** — internal missingness/completeness stats
- **Impute (ext)** — advanced missingness/imputation, typically external
- **Reports** — scorecards, HTML/PDF
- **Viz/UI** — dashboards and interactive UI
- **Extensibility** — documented interface for plugging in external analyzers

---

## Status Key

| Status | Meaning |
|---|---|
| **Active** | Maintained and released as of August 2026 |
| **Pre-release** | Under development, no release; capabilities are partial by definition |
| **Retired** | Project formally ended; archived or read-only |
| **Commercial** | Proprietary; open-source edition discontinued |
| **Research** | Academic prototype, not a maintained product |
| **Unverified** | Repository public but active maintenance not confirmed |

---

## Comparison

| Package | Status | Stack | Profiling | DQ Diagn | Rules | Cleansing | Metrics | Monitoring | Knowledge | Classif. | Missing (int) | Impute (ext) | Reports | Viz/UI | Extensibility |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **DQT (current)** | Pre-release | Python / SQLite+PostgreSQL | ✓ | ~ | ✓ | ~ | ~ | - | - | - | ✓ | - | ✓ | ~ | - |
| **DQT (target v1.0)** | — | Python / SQL DB | ✓✓ | ✓✓ | ✓✓ | ✓ | ✓✓ | ✓ | ✓ | ✓ | ✓ | ✓ (bridges) | ✓✓ | ✓✓ | ✓✓ |
| **missingly** | Active | Python / DataFrame | ✓ | ~ | - | ~ | ✓✓ | ~ | - | - | ✓✓ | ✓✓ | ✓✓ | ✓ | - |
| **Great Expectations** | Active | Python / multi | ✓✓ | ✓✓ | ✓✓ | - | ✓✓ | ✓ | ~ | ~ | ✓ | - | ✓✓ | ✓ | ✓✓ |
| **Soda Core** | Active | Python / SQL | ✓ | ✓ | ✓✓ | ~ | ✓ | ✓ | - | - | ~ | - | ✓✓ | ~ | ✓ |
| **Baselinr** | Active (young) | Python / SQL warehouse | ✓✓ | ✓✓ | ✓✓ | ~ | ✓✓ | ✓✓ | ~ | ~ | ✓ | ~ | ✓✓ | ✓ | ✓ |
| **SQL Server DQS** | Commercial | SQL Server | ✓✓ | ✓✓ | ✓✓ | ✓✓ | ✓ | ~ | ✓✓ | ~ | ✓ | ~ | ✓ | ✓ | ~ |
| **SSIS Data Profiling Task** | Commercial | SQL Server / SSIS | ✓✓ | ✓ | ~ | - | ~ | - | - | - | ✓ | - | ~ | ✓ | - |
| **Apache Griffin** | **Retired (2025)** | Java / Spark | ✓✓ | ✓✓ | ✓✓ | ~ | ✓✓ | ✓✓ | ~ | ~ | ✓ | ~ | ✓✓ | ✓ | ~ |
| **Talend DQ** | **Commercial (OSS retired 2024)** | Java / multi-source | ✓✓ | ✓✓ | ✓✓ | ✓✓ | ✓✓ | ✓✓ | ✓ | ✓✓ | ✓ | ~ | ✓✓ | ✓✓ | ~ |
| **MobyDQ** | Unverified | Python / pipelines | ✓ | ✓ | ✓ | ~ | ✓✓ | ✓✓ | ~ | ~ | ~ | ~ | ✓ | ~ | ~ |
| **OpenRefine** | Active | Java / tabular | ✓ | ~ | ~ | ✓✓ | ✓ | - | ✓ | ~ | ~ | ~ | ✓ | ✓✓ | ✓ |
| **DataLens (research)** | Research | Python / ML prototype | ✓✓ | ✓✓ | ~ | ✓✓ | ✓✓ | ✓ | ~ | ~ | ✓ | ✓✓ | ✓✓ | ✓✓ | ~ |
| **Redgate SQL Data Catalog** | Commercial | .NET | ~ | ~ | ~ | - | ~ | - | ✓✓ | ✓✓ | ~ | - | ✓✓ | ✓✓ | ~ |

---

## Ratings for `DQT (current)` — evidence

Each rating below is grounded in read source, not file size:

| Facet | Rating | Evidence |
|---|---|---|
| Profiling | ✓ | `profiling.py`: row counts, null counts, completeness. No min/max/distinct/patterns/candidate keys. |
| DQ Diagnostics | ~ | `diagnostics.py` computes `completeness` only; its own docstring defers the other five dimensions. |
| Rules | ✓ | `rules.py`: NOT NULL, UNIQUE, RANGE, REGEX, column-scope only. No table-level rules. |
| Cleansing | ~ | `cleansing.py` implements the primitives, but the pipeline stage is a pass-through and the safety model (plan/apply, undo statements) is unbuilt. |
| Metrics | ~ | `metrics.py`: table_count, column_count, average_completeness. |
| Monitoring | - | `monitoring.py` returns its input unchanged. Honestly documented as a placeholder. |
| Knowledge / Classification | - | No `knowledge.py`, no `classification.py`. |
| Missing (internal) | ✓ | Null counts and ratios present; co-occurrence patterns absent. |
| Impute (external) | - | No `bridges/`. `external_analyses` exists on the model but nothing populates or renders it. |
| Reports | ✓ | Self-contained HTML with score bars and severity badges. No PDF, no bilingual content. |
| Viz/UI | ~ | No frontend and no charts. A FastAPI backend skeleton is likely (a `ui` extra exists in `pyproject.toml`) but `src/dqt/ui/` was not read — `UNVERIFIED`. |
| Extensibility | - | Bridge interface not defined. |

**Honest summary:** measured against the baseline floor in `dqt_competitors.md`,
DQT meets **1 of 14** floor requirements outright. It is below floor on
diagnostics, table-level profiling, table-level rules, cleansing safety, metrics,
monitoring, knowledge, classification, reports, and CLI coverage. The gap between
the two DQT rows above is the actual backlog; `dqt_competitors.md` §1 is the
itemized version and is authoritative where the two differ.

---

## Notes on specific entries

- **Apache Griffin** was retired in September 2025 and moved to the Apache Attic
  in November 2025; all its resources are read-only. Keep it as a *design
  reference* for its rule-DSL-plus-metrics model, not as a live competitor.
- **Talend**: the open-source Talend Studio was retired on 31 January 2024;
  Talend is now part of Qlik and the data-quality capability is commercial. Its
  column-level quality bars remain the best UX reference in this table, but it is
  no longer an OSS baseline anyone can adopt.
- **DataLens** in this table means the **research prototype**
  (arXiv:2501.17074) — an ML-oriented tabular data-quality dashboard. It is
  *not* Yandex DataLens, the commercial BI product of the same name. Earlier
  revisions of the UI documents blended the two, attributing BI dashboard
  features (widgets, cross-filtering, selectors, parameters) to the research
  tool. See `DQT-UI-Ecosystem.md`.
- **MobyDQ**: repository public and not archived, but active maintenance is
  unconfirmed. Marked Unverified rather than assumed alive.
- **Baselinr** is the closest direct competitor to DQT's stated positioning:
  open-source data quality and observability for SQL warehouses, with profiling,
  drift and anomaly detection, rules, a dashboard, CLI and Python SDK. It is
  young (2025), which is both the reason it is not yet an industry default and
  the reason DQT should track it closely.

---

## Maintenance rule

Re-verify every `Status` cell before using this matrix to justify a roadmap
decision. Two of the original eight competitors were retired between the matrix
being written and being re-read. A matrix that is not re-verified is a matrix
that quietly benchmarks against ghosts.
