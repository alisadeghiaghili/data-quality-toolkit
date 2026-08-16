# DQT Reference Sources

Key references for DQT's data-quality design, architecture, and ecosystem
understanding.

> **Verification notice (August 2026).** Links and project statuses were
> re-checked. Corrections applied:
>
> - Great Expectations links pointed at the `docs/0.18/` branch, which that site
>   itself marks as no longer maintained (current stable: 1.20.x). Updated to the
>   current documentation, since GX 1.x reorganized the concepts that were being
>   referenced.
> - Apache Griffin was retired and moved to the Apache Attic in 2025; its
>   resources are read-only. Reclassified as a historical reference.
> - Talend's open-source Studio was retired on 31 January 2024; Talend is now
>   part of Qlik. Reclassified as commercial.
> - "DataLens" was split into two unrelated entries — the research prototype and
>   the Yandex BI product — which earlier documents had conflated.
> - Sources whose maintenance status could not be confirmed are marked
>   `UNVERIFIED` rather than presented as current.
>
> **Re-verify before citing.** Two of the tools originally listed here were
> retired between this list being written and being re-read.

---

## Surveys and Papers

| Name | Link | Status | Notes |
|---|---|---|---|
| A survey of open-source data quality tools (Papastergios & Gounaris, 2024) | https://arxiv.org/abs/2407.18649 | Stable | Maps OSS DQ tools to ISO/IEC 25012 dimensions. Useful for justifying DQT's six-dimension set. |
| A Survey of Data Quality Measurement and Monitoring Tools (Ehrlinger & Wöß, 2019) | https://arxiv.org/abs/1907.08138 | Stable (dated) | Functional scope of DQ tools. Predates most current tooling; treat tool-specific claims as historical. |
| A Survey on Data Quality Dimensions and Tools for ML (Zhou et al., 2024) | https://arxiv.org/abs/2406.19614 | Stable | DQ dimensions in ML pipelines. ML framing is out of DQT's scope; dimension taxonomy is not. |
| DataLens: ML-Oriented Interactive Tabular Data Quality Dashboard | https://arxiv.org/abs/2501.17074 | Research prototype | **Not** Yandex DataLens. User-in-the-loop and iterative cleaning patterns. |

---

## Tool Documentation — Active

| Name | Link | Notes |
|---|---|---|
| Great Expectations — docs (current) | https://docs.greatexpectations.io/docs/core/introduction/ | Current 1.x line. Concepts changed substantially from 0.18; do not design against the old branch. |
| Great Expectations — main site | https://greatexpectations.io | Product overview. |
| Soda Core | https://docs.soda.io | SQL-first checks; YAML check syntax worth studying for DQT's rule files. |
| Baselinr | https://baselinr.io/ | Closest direct competitor: OSS data quality + observability for SQL warehouses. Young project (2025). |
| OpenRefine — user manual | https://openrefine.org/docs | Faceted exploration, undo/redo model, interactive cleaning UX. |
| Deequ (AWS) | https://github.com/awslabs/deequ | Spark-based "unit tests for data"; metric/constraint model is a good reference. |
| PyDeequ | https://pydeequ.readthedocs.io/en/latest/README.html | Python interface to Deequ. |

---

## Tool Documentation — Historical / Commercial

| Name | Link | Status | Why still listed |
|---|---|---|---|
| Apache Griffin — intro | https://github.com/apache/griffin/blob/master/griffin-doc/intro.md | **Retired (Attic, 2025)** | Rule-DSL-plus-metric-model design remains instructive. Not a live baseline. |
| Apache Attic — Griffin | https://attic.apache.org/projects/griffin.html | — | Confirms retirement; read-only resources. |
| Talend Data Quality | https://www.talend.com/products/data-quality/ | **Commercial; OSS retired 31 Jan 2024** | Column-level quality bars remain the best UX reference in this space. |
| Qlik — Talend Open Studio retirement | https://www.qlik.com/us/products/talend-open-studio | — | Confirms the OSS end-of-life date. |
| MobyDQ | https://ubisoft.github.io/mobydq/ | `UNVERIFIED` | Pipeline-oriented indicators. Repository public and not archived; active maintenance unconfirmed. |
| pydqc | https://github.com/SauceCat/pydqc | `UNVERIFIED` | Automatic DQ check toolkit; maintenance unconfirmed. |
| Yandex DataLens — dashboards | https://yandex.cloud/en/docs/datalens/concepts/dashboard | Commercial BI | **Listed only to keep it distinct from the research prototype above.** Its widget/cross-filter patterns are explicit anti-patterns for DQT. |

---

## Curated Lists

| Name | Link | Notes |
|---|---|---|
| Awesome Data Quality (kwanUm) | https://github.com/kwanUm/awesome-data-quality | Tools for testing and monitoring DQ. |
| Awesome Data Quality (MigoXLab) | https://github.com/MigoXLab/awesome-data-quality | Broader DQ resource collection. |
| Awesome Public Datasets | https://github.com/awesomedata/awesome-public-datasets | Datasets for testing and benchmarking. |

---

## Implementation References

| Category | Name | Link | Notes |
|---|---|---|---|
| Config | Pydantic — models | https://pydantic.dev/docs/validation/latest/concepts/models/ | Verified current. Core validation model for all DQT configs. |
| Config | Pydantic — settings | https://pydantic.dev/docs/validation/latest/concepts/pydantic_settings/ | Verified current. Env-var handling for connection config. |
| Config | PyCon DE — Robust Configuration Management with Pydantic | https://www.youtube.com/watch?v=ZvcZDxS_mYE | Moving from loose YAML to typed config models. |
| Storage | SQLite + SQLAlchemy best practices | https://blog.sqlite.ai/sqlite-python-sqlalchemy | **Context:** DQT does **not** depend on SQLAlchemy — it uses DB-API 2.0 drivers directly (see `CONVENTIONS-DQT.md` §3). Retained for SQLite storage-design guidance only. |
| Talk | Sam Bail — The Wonderful World of Data Quality Tools in Python | https://www.youtube.com/watch?v=G_XHSh66zW0 | Landscape overview; predates current GX. |
| Talk repo | spbail/data-quality-tools | https://github.com/spbail/data-quality-tools | Code from the talk above. |

---

## Gaps in this list

Topics DQT's design depends on with no reference recorded. Each is a real
decision that has been made implicitly and should be made explicitly:

- **SQL identifier quoting and injection prevention per dialect** — directly
  relevant to `CONVENTIONS-DQT.md` §S6.
- **Table sampling techniques** (PostgreSQL `TABLESAMPLE`, approximate distinct
  counts / HyperLogLog) — needed for V2 performance budgets.
- **PDF generation with RTL and Arabic-script shaping** (e.g. WeasyPrint plus an
  embedded Persian font) — required before "bilingual PDF reports" can be
  claimed as achievable.
- **Accessible data visualization** (colour-independent severity encoding, WCAG
  contrast) — required by the UI skill.
- **Data-quality drift detection methodology** — DQT's monitoring facet currently
  names a goal with no defined method, baseline, or threshold semantics.
