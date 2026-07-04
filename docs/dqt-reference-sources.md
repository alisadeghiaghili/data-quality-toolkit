# DQT Reference Sources

This file lists key references (papers, tools, docs, and talks) that the DQT system should consult for data quality design, architecture, and ecosystem understanding.

| Category | Name | Link | Notes |
|---------|------|------|-------|
| Survey | A survey of open-source data quality tools (Papastergios & Gounaris, 2024) | https://arxiv.org/abs/2407.18649 | Mapping of open-source DQ tools to ISO/IEC 25012 dimensions. |
| Survey | A Survey of Data Quality Measurement and Monitoring Tools (Ehrlinger & Wöß, 2019) | https://arxiv.org/abs/1907.08138 | Functional scope of DQ tools: profiling, metrics, monitoring. |
| Survey | A Survey on Data Quality Dimensions and Tools for Machine Learning (Zhou et al., 2024) | https://arxiv.org/abs/2406.19614 | DQ dimensions and tools in ML pipelines. |
| Dashboard | DataLens: ML-Oriented Interactive Tabular Data Quality Dashboard | https://arxiv.org/abs/2501.17074 | ML-oriented DQ dashboard; user-in-the-loop and iterative cleaning. |
| Tool Docs | Great Expectations (GX) – main site | https://greatexpectations.io | OSS framework for data validation, expectations, and data docs. |
| Tool Docs | Great Expectations OSS – introduction | https://docs.greatexpectations.io/docs/0.18/core/introduction/introduction/ | Overview of GX OSS concepts and usage. |
| Tool Docs | Great Expectations – Data Docs | https://docs.greatexpectations.io/docs/0.18/reference/learn/terms/data_docs/ | Design of HTML documentation for expectations and validation results. |
| Tool Docs | Apache Griffin – intro | https://github.com/apache/griffin/blob/master/griffin-doc/intro.md | Big data DQ service platform overview. |
| Tool Docs | Apache Griffin – Quickstart | https://griffin.apache.org/docs/quickstart.html | Example configs and basic usage. |
| Tool Docs | Talend Data Quality – product page | https://www.talend.com/products/data-quality/ | Commercial DQ product with profiling, cleansing, and quality scores. |
| Tool Docs | OpenRefine – user manual | https://openrefine.org/docs | Interactive data cleaning tool; UX patterns and faceted exploration. |
| Tool Docs | MobyDQ – documentation | https://ubisoft.github.io/mobydq/ | Pipeline-oriented DQ indicators and monitoring. |
| Lists | Awesome Data Quality (kwanUm) | https://github.com/kwanUm/awesome-data-quality | Curated list of tools for testing and monitoring data quality. |
| Lists | Awesome Data Quality (MigoXLab) | https://github.com/MigoXLab/awesome-data-quality | Broad collection of DQ resources across domains. |
| Lists | Awesome Public Datasets | https://github.com/awesomedata/awesome-public-datasets | High-quality datasets for testing and benchmarking. |
| Lists | Awesome Data (datasets) | https://github.com/datasets/awesome-data | Curated open datasets; useful for examples. |
| Tool | Deequ (AWS) | https://github.com/awslabs/deequ | Spark-based "unit tests for data" and DQ metrics. |
| Tool | PyDeequ docs | https://pydeequ.readthedocs.io/en/latest/README.html | Python interface to Deequ (unit tests for data). |
| Tool | pydqc – GitHub | https://github.com/SauceCat/pydqc | Python automatic data quality check toolkit. |
| Tool | pydqc – Medium article | https://medium.com/@yiwenzh4/pydqc-python-automatic-data-quality-check-toolkit-95ef56ad9ec7 | Overview and examples of pydqc usage. |
| Talk | Sam Bail – "The Wonderful World of Data Quality Tools in Python" | https://www.youtube.com/watch?v=G_XHSh66zW0 | Landscape of Python DQ tools + Great Expectations demo. |
| Talk Repo | Sam Bail – data-quality-tools GitHub | https://github.com/spbail/data-quality-tools | Code and examples from the talk. |
| Config | Pydantic Settings docs | https://pydantic.dev/docs/validation/latest/concepts/pydantic_settings/ | Settings/config management using Pydantic. |
| Config | Pydantic Models docs | https://pydantic.dev/docs/validation/latest/concepts/models/ | Core Pydantic model usage and validation. |
| Config Talk | PyCon DE talk – Robust Configuration Management with Pydantic | https://www.youtube.com/watch?v=ZvcZDxS_mYE | How to move from loose YAML to typed config models. |
| Storage | SQLite + SQLAlchemy best practices | https://blog.sqlite.ai/sqlite-python-sqlalchemy | Guidance on using SQLAlchemy with SQLite for lightweight storage. |
