# DQT Ecosystem Matrix

Legend (per facet):

- `✓✓` — strong support
- `✓`  — partial support
- `~`  — limited / niche support
- `-`  — none / out of scope

Facets (columns):

- **Profiling** — data/SQL profiling (stats, patterns, keys, FKs)
- **DQ Diagn** — data-quality diagnostics (completeness, consistency, validity, etc.)
- **Rules** — declarative data-quality checks/constraints
- **Cleansing** — reversible repair (standardization, deduplication, lookup corrections)
- **Metrics** — quantitative data-quality metrics/scores
- **Monitoring** — tracking data-quality metrics over time + alerts
- **Knowledge** — domain/reference data and knowledge bases
- **Classif.** — semantic typing of columns (email, IBAN, national_id, phone…)
- **Missing (int)** — basic missingness/completeness stats inside the tool
- **Impute (ext)** — advanced missing-data analysis/imputation via external tools
- **Reports** — data-quality reports/scorecards (HTML/PDF, dashboards)
- **Viz/UI** — strength of visualization, dashboards, interactive UI
- **Uses missingly** — can easily consume analyses from `missingly` as a sister package

---

## Ecosystem Comparison

| Package                          | Stack                     | Profiling | DQ Diagn | Rules | Cleansing | Metrics | Monitoring | Knowledge | Classif. | Missing (int) | Impute (ext)           | Reports | Viz/UI | Uses missingly |
|----------------------------------|---------------------------|-----------|----------|-------|-----------|--------|-----------|-----------|----------|--------------|------------------------|---------|--------|----------------|
| **DQT (target)**                 | Python / SQL DB           | ✓✓        | ✓✓       | ✓✓    | ✓         | ✓✓     | ✓         | ✓         | ✓         | ✓            | ✓ (via bridges)        | ✓✓      | ✓✓     | ✓✓             |
| **missingly**                    | Python / DataFrame        | ✓✓        | ✓✓       | ~     | ~         | ✓✓     | ~         | ~         | ~         | ✓✓           | ✓✓                     | ✓✓      | ✓      | -              |
| **Baselinr**                     | Python / SQL warehouse    | ✓✓        | ✓✓       | ✓✓    | ~         | ✓✓     | ✓✓        | ~         | ~         | ✓            | ~                      | ✓✓      | ✓      | -              |
| **Soda core**                    | Python / SQL              | ✓         | ✓        | ✓✓    | ~         | ✓      | ✓         | -         | -         | ~            | -                      | ✓✓      | ~      | -              |
| **SQL Server DQS**               | SQL Server                | ✓✓        | ✓✓       | ✓✓    | ✓✓        | ✓      | ~         | ✓✓        | ~         | ✓            | ~                      | ✓       | ✓      | -              |
| **SSIS Data Profiling Task**     | SQL Server / SSIS         | ✓✓        | ✓✓       | ~     | -         | ~      | -         | -         | -         | ✓            | -                      | ~       | ✓      | -              |
| **SSIS DQS Cleansing**           | SQL Server / SSIS         | ✓        | ✓        | ✓✓    | ✓✓        | ~      | ~         | ✓✓        | ~         | ✓            | ~                      | ~       | ~      | -              |
| **Redgate SQL Data Catalog**     | Commercial                | ~         | ~        | ~     | ~         | ~      | ~         | ✓✓        | ✓✓        | ~            | ~                      | ✓✓      | ✓✓     | -              |
| **Apache Griffin**               | Java / Big Data (Spark)   | ✓✓        | ✓✓       | ✓✓    | ~         | ✓✓     | ✓✓        | ~         | ~         | ✓            | ~                      | ✓✓      | ✓      | -              |
| **Talend Open Studio (DQ)**      | Java / multi-source       | ✓✓        | ✓✓       | ✓✓    | ✓✓        | ✓✓     | ✓✓        | ✓         | ~         | ✓            | ~                      | ✓✓      | ✓✓     | -              |
| **MobyDQ**                       | Python / pipelines        | ✓         | ✓        | ✓     | ~         | ✓✓     | ✓✓        | ~         | ~         | ~            | ~ (ML anomaly WIP)     | ✓       | ~      | -              |
| **OpenRefine + MetricDoc**       | Java / DF + metadata      | ✓         | ~        | ~     | ✓✓        | ✓      | ~         | ✓         | ~         | ~            | ~                      | ✓       | ✓✓     | -              |
| **DataLens**                     | Python / ML dashboard     | ✓✓        | ✓✓       | ~     | ✓✓        | ✓✓     | ✓         | ~         | ~         | ✓            | ✓✓ (ML-based repair)   | ✓✓      | ✓✓     | -              |

Notes:

- **DQT (target)**: DBA-focused SQL Data Quality Toolkit, aiming for strong
  visualization and a good UI (not just CLI/Rich CLI), while staying a lean,
  SQL-centric library.
- Competitors and their strengths in profiling, metrics, monitoring, and UI are
  derived from open-source tool surveys and individual tool documentation.
