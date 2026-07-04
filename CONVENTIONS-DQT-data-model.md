# DQT Data Model and Storage (CONVENTIONS-DQT-data-model)

This document defines the core data model and storage schema for **DQT**.
It is the single source of truth for:

- `PipelineResult` structure,
- issue and metric representations,
- config models,
- storage tables for monitoring and UI.

All implementations (CLI, UI, bridges, monitoring) MUST follow this model.

---

## Implementation Status

| Class / Model | File | Status |
| :-- | :-- | :-- |
| `PipelineResult` | `common/models.py` | ✅ DONE |
| `SchemaResult` | `common/models.py` | ✅ DONE |
| `TableResult` | `common/models.py` | ✅ DONE |
| `ColumnResult` | `common/models.py` | ✅ DONE |
| `DQMetric` | `common/models.py` | ✅ DONE |
| `DQIssue` | `common/models.py` | ✅ DONE |
| `Rule` / `RuleResult` / `RuleRunResult` | `common/models.py` | ✅ DONE |
| `ConnectionConfig` | `common/models.py` | ✅ DONE |
| `DQPipelineConfig` | `common/models.py` | ✅ DONE |
| `RuleConfig` / `RuleScope` | `common/models.py` | ✅ DONE |
| `SamplingConfig` | `common/models.py` | ✅ DONE |
| `CleansingConfig` / `CleansingLog` / `CleansingResult` | `sql/cleansing.py` | ✅ DONE |
| `RunStore` (SQLite storage) | `common/storage.py` | ✅ DONE |
| `from_dsn()` / `from_yaml_config()` helpers | `dqt/__init__.py` | ✅ DONE |
| `DomainConfig` | — | ❌ NOT STARTED |
| `ClassificationResult` | — | ❌ NOT STARTED |
| `MissingnessReport` / `MissingnessBridge` | — | ❌ NOT STARTED |

---

## 1. Core Classes

### 1.1 PipelineResult

`PipelineResult` represents the outcome of one data-quality run.

Fields (minimal set):

- `run_id: str` — unique identifier for the run.
- `connection_id: str` — identifier of the DB connection used.
- `started_at: datetime`
- `ended_at: datetime`
- `status: Literal["success", "failed", "partial"]`

Structural fields:

- `schemas: List[SchemaResult]`
- `tables: Dict[str, TableResult]` — keyed by `schema.table_name`.
- `metrics: List[DQMetric]` — global metrics (cross-table).
- `issues: List[DQIssue]` — global list of issues.
- `rules_run: List[RuleRunResult]`
- `external_analyses: Dict[str, Dict[str, Any]]` — e.g. `{"missingly": {table_name: report}}`.
  Field exists in model; rendering in reports not yet implemented.

### 1.2 SchemaResult

Represents data-quality summary at schema level.

- `schema_name: str`
- `tables: List[str]` — table names within the schema.
- `metrics: List[DQMetric]`
- `issues: List[DQIssue]`

### 1.3 TableResult

Represents data-quality summary for a single table.

- `schema_name: str`
- `table_name: str`
- `columns: List[ColumnResult]`
- `metrics: List[DQMetric]` — table-level metrics (e.g. completeness, validity).
- `issues: List[DQIssue]` — issues scoped to this table.

### 1.4 ColumnResult

Represents a single column within a table.

- `schema_name: str`
- `table_name: str`
- `column_name: str`
- `type: str` — DB type (e.g. VARCHAR(255), INT).
- `semantic_type: Optional[str]` — e.g. `email`, `phone`, `iban`.
  Set by classification module (not yet implemented).
- `metrics: List[DQMetric]` — column-level metrics (null ratio, distinct count).
- `issues: List[DQIssue]`

### 1.5 DQMetric

Generic metric object.

- `run_id: str`
- `schema_name: Optional[str]`
- `table_name: Optional[str]`
- `column_name: Optional[str]`
- `dimension: str` — e.g. `completeness`, `validity`, `uniqueness`.
- `score: float` — normalized score [0, 1] or similar.
- `value: Optional[float]` — raw value (e.g. null ratio, distinct count).
- `metadata: Dict[str, Any]` — extra info (e.g. thresholds used).

### 1.6 DQIssue

Generic issue object.

- `issue_id: str`
- `run_id: str`
- `schema_name: Optional[str]`
- `table_name: Optional[str]`
- `column_name: Optional[str]`
- `dimension: str` — same dimensions as metrics.
- `severity: Literal["info", "warning", "error", "critical"]`
- `message: str` — human-readable description.
- `evidence: Dict[str, Any]` — e.g. sample values, counts.
- `rule_name: Optional[str]` — if caused by a rule.

### 1.7 Rule / RuleResult / RuleRunResult

`Rule`:

- `name: str`
- `dimension: str`
- `severity: str`
- `scope: RuleScope` — defines table/column targets.
- `expression: str` — DSL or SQL fragment.
- `params: Dict[str, Any]`

`RuleResult` (per target):

- `run_id: str`
- `rule_name: str`
- `schema_name: Optional[str]`
- `table_name: Optional[str]`
- `column_name: Optional[str]`
- `status: Literal["pass", "fail", "error"]`
- `details: Optional[str]`

`RuleRunResult` (summary):

- `run_id: str`
- `rule_name: str`
- `targets_checked: int`
- `targets_failed: int`
- `targets_error: int`

---

## 2. Config Models

### 2.1 ConnectionConfig

- `id: str`
- `dsn: str` — connection string (may be env-expanded).
- `read_only: bool` — recommended true.
- `ssl: Optional[Dict[str, Any]]` — SSL/TLS options.

### 2.2 DQPipelineConfig

- `connection_id: str`
- `include_schemas: Optional[List[str]]`
- `exclude_schemas: Optional[List[str]]`
- `include_tables: Optional[List[str]]`
- `exclude_tables: Optional[List[str]]`
- `sampling: Optional[SamplingConfig]`
- `metric_thresholds: Optional[Dict[str, float]]` — e.g. min completeness score.
- `rule_files: List[str]` — YAML/JSON files containing rules.

### 2.3 RuleConfig

- `name: str`
- `dimension: str`
- `severity: str`
- `scope: RuleScope` — e.g. table pattern, column pattern.
- `expression: str`
- `params: Dict[str, Any]`

Configs MUST be validated via typed models (Pydantic) before pipeline runs.

---

## 3. Storage Schema (Monitoring & UI)

DQT uses a lightweight store (SQLite by default, via `common/storage.py` — `RunStore`)
to persist metrics and issues for monitoring and UI.

### 3.1 `runs`

- `run_id TEXT PRIMARY KEY`
- `connection_id TEXT`
- `started_at TIMESTAMP`
- `ended_at TIMESTAMP`
- `status TEXT` — `success`, `failed`, `partial`

### 3.2 `run_metrics`

- `run_id TEXT`
- `schema_name TEXT`
- `table_name TEXT`
- `column_name TEXT`
- `dimension TEXT`
- `score REAL`
- `value REAL`
- `metadata JSON`

Index: composite on `(run_id, schema_name, table_name, column_name, dimension)`.

### 3.3 `run_issues`

- `issue_id TEXT PRIMARY KEY`
- `run_id TEXT`
- `schema_name TEXT`
- `table_name TEXT`
- `column_name TEXT`
- `dimension TEXT`
- `severity TEXT`
- `message TEXT`
- `evidence JSON`
- `rule_name TEXT`

Index: composite on `(run_id, severity, dimension)`.

These tables back monitoring (trends over time), UI dashboards, and report generation.
Implementation can use SQLite, Postgres, or another backend; schema stays conceptually stable.

---

## 4. Security Conventions

- Credentials MUST come from environment variables or secure config files;
  DQT must never write DSNs/passwords into reports, logs, or UI artifacts.
- DQT SHOULD operate with **read-only** roles:
  - required privileges: SELECT on target schemas/tables,
  - no DELETE/UPDATE/DDL on production data.
- SSL/TLS options must be configurable in `ConnectionConfig` where applicable.
