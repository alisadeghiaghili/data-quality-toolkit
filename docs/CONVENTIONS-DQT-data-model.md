# DQT — Data Model and Storage (CONVENTIONS-DQT-data-model)

> Normative for class shapes, the aggregation contract, and the storage schema.
> Ranked below `docs/CONVENTIONS-DQT.md` — see `00-START-HERE.md` §1. Where this
> document and the code disagree, the code wins and this document is the bug.

**Verified against source:** 2026-08-17 at commit `4629925`.

---

## 0. Two model families — do not mix them up

`common/models.py` contains **two kinds of class with two different base
mechanisms**, and confusing them is the most common mistake made against this
file.

| Family | Mechanism | Classes | Validation |
|---|---|---|---|
| **Result models** | plain `@dataclass` | `DQMetric`, `DQIssue`, `ColumnResult`, `TableResult`, `SchemaResult`, `RuleResult`, `RuleRunResult`, `PipelineResult`, `Rule` | **None at runtime.** Type hints only. |
| **Config models** | Pydantic v2 `BaseModel` | `SamplingConfig`, `RuleScope`, `ConnectionConfig`, `DQPipelineConfig`, `RuleConfig` | Full Pydantic validation, plus `field_validator` / `model_validator`. |

Consequences you must design around:

- **Result models accept anything the type checker lets through.** Constructing a
  `DQMetric` with `score=17.4` or `dimension="banana"` succeeds at runtime. Only
  `mypy --strict` catches shape errors, and it cannot catch value errors. Where a
  result value must be constrained, the constraint belongs either in the emitting
  code or in a storage `CHECK` — not in a docstring.
- **Config models validate at load.** Anything read from YAML/JSON goes through
  Pydantic and fails loudly on bad input. This is the correct boundary and should
  stay.
- Do not "helpfully" convert the result dataclasses to `BaseModel` without a
  reason. They are hot-path objects constructed per column per run; the current
  split is a defensible performance decision. If you change it, change it
  deliberately and say why here.

Type aliases (`Literal`, exported):

```python
RunStatus     = Literal["success", "failed", "partial"]
IssueSeverity = Literal["info", "warning", "error", "critical"]
RuleStatus    = Literal["pass", "fail", "error"]
```

There is no `DQDimension` alias yet. Adding one is `BACKLOG.md` `NEW-A`.

---

## 1. The aggregation contract

**`PipelineResult.issues` and `PipelineResult.metrics` are the only canonical,
flat, complete lists.** Everything else is a view.

`PipelineResult.schemas[*].issues`, `.tables[*].issues`,
`.tables[*].columns[*].issues` and their `.metrics` counterparts are
**non-authoritative navigational views**. They exist so a report can render a
tree without re-filtering the global list.

Therefore:

- To count issues, count `PipelineResult.issues`. Once.
- **Never sum the nested lists.** An issue scoped to a column may legitimately
  appear in the column view, the table view, and the global list. Summing them
  produces a number that is confidently, silently wrong — and it will look
  plausible, which is worse.
- Persistence reads the flat lists only. `RunStore.save_run` must never walk the
  tree.
- Any UI or report total must state which list it counted.

---

## 2. Result models

### 2.1 `PipelineResult`

```python
run_id: str
connection_id: str
started_at: datetime
ended_at: datetime
status: RunStatus
schemas: list[SchemaResult]              = []
tables: dict[str, TableResult]           = {}   # keyed "schema.table"
metrics: list[DQMetric]                  = []   # canonical
issues: list[DQIssue]                    = []   # canonical
rules_run: list[RuleRunResult]           = []
external_analyses: dict[str, dict[str, Any]] = {}
```

Two notes:

- `status` can only ever hold `"success"` today — `run()` hardcodes it and no
  stage is wrapped in error handling. See `BACKLOG.md` `NEW-B`. There is no
  `stage_errors` field yet; `NEW-B` adds one.
- `external_analyses` exists and **nothing reads it.** `reports.py` renders no
  panel from it. Either render the panel or delete the field (`NEW-E`). A field
  nothing reads is a promise nothing keeps.

### 2.2 `DQMetric`

```python
run_id: str
dimension: str
score: float
schema_name: str | None  = None
table_name: str | None   = None
column_name: str | None  = None
value: float | None      = None
metadata: dict[str, Any] = {}
```

Scope is implied by which of the three name fields are set: all `None` = global,
`schema_name` only = schema level, and so on.

> **⚠ `dimension` is overloaded.** It is typed `str`, and emitters disagree about
> what it means:
>
> | Emitter | Values written to `dimension` |
> |---|---|
> | `diagnostics.py` | `completeness` — a real dimension |
> | `rules.py` | whatever the rule declares — a real dimension |
> | `metrics.py` | `table_count`, `column_count`, `average_completeness` — **metric names** |
> | `profiling.py` | `row_count` (metric name), `completeness` (dimension) |
>
> Any `GROUP BY dimension`, per-dimension score, or dimension filter is wrong
> until `NEW-A` adds a separate `metric_name` field and a closed `DQDimension`
> type. Do not build dashboards, trends, or scorecards on this field first.

### 2.3 `DQIssue`

```python
issue_id: str
run_id: str
dimension: str
severity: IssueSeverity
message: str
evidence: dict[str, Any] = {}
schema_name: str | None  = None
table_name: str | None   = None
column_name: str | None  = None
rule_name: str | None    = None
```

`rule_name` is `None` when the issue came from a diagnostic rather than a rule —
that is the discriminator between the two sources.

`evidence` is where a DBA's actual diagnosis happens. It must carry enough to act
on the issue without re-querying: counts, and sample values where they are not
sensitive. Never put credentials, DSNs, or full row dumps in it.

### 2.4 `SchemaResult` / `TableResult` / `ColumnResult`

Navigational views (see §1), each carrying its own `metrics` and `issues` lists.

- `SchemaResult`: `schema_name`, `tables: list[str]`, `metrics`, `issues`.
- `TableResult`: `schema_name`, `table_name`, `columns: list[ColumnResult]`,
  `metrics`, `issues`.
- `ColumnResult`: `schema_name`, `table_name`, `column_name`, `type` (raw DB
  type), `semantic_type: str | None`, `metrics`, `issues`.

`semantic_type` is populated by the classification module, which does not exist.
It is `None` in every run today.

### 2.5 `Rule` / `RuleResult` / `RuleRunResult`

`Rule` (dataclass): `name`, `dimension`, `severity`, `scope: RuleScope`,
`expression`, `params`.

`RuleResult` (per target): `run_id`, `rule_name`, `status: RuleStatus`,
`schema_name`, `table_name`, `column_name`, `details`.

`RuleRunResult` (per rule, summary): `run_id`, `rule_name`, `targets_checked`,
`targets_failed`, `targets_error`.

The `expression` field accepts exactly four values — `not_null`, `unique`,
`range`, `regex`. Unknown expressions are rejected with an `error` issue rather
than executed. **Preserve this.** It is the single design decision keeping rule
files from being arbitrary code execution, and it should not be relaxed into a
raw-SQL escape hatch without the allowlist and privilege model described in
`CONVENTIONS-DQT.md` §1 (S6).

---

## 3. Config models (Pydantic v2)

### 3.1 `SamplingConfig`

`strategy`, `limit`, `seed`. Drives the sampled-profiling path described in
`BACKLOG.md` `NEW-F`/sampling (no ID yet) — which is not built yet, so this model is currently
accepted and ignored.

### 3.2 `RuleScope`

`schema_pattern`, `table_pattern`, `column_pattern`. Pattern matching selects the
targets a rule applies to.

Note the security implication: these patterns become identifiers in generated
SQL. They are exactly the input that `quote_identifier()` and strict validation
must cover (`DQT-02`).

### 3.3 `ConnectionConfig`

`id`, `dsn`, `read_only`, `ssl`.

> `read_only` is currently **advisory metadata** — it records intent, it does not
> enforce anything. The enforcement mechanism is the two-connection split in
> `CONVENTIONS-DQT.md` §1 (S1), which is `DQT-03`/`DQT-05`. Do not read a `read_only: true` in a
> config and conclude the run cannot write.

### 3.4 `DQPipelineConfig`

`connection_id`, `include_schemas`, `exclude_schemas`, `include_tables`,
`exclude_tables`, `sampling`, `metric_thresholds`, `rule_files`.

`rule_files` is the executable-input surface. See `CONVENTIONS-DQT.md` §1 (S6).

### 3.5 `RuleConfig`

`name`, `dimension`, `severity`, `scope`, `expression`, `params`. The serialized
form of `Rule`; this is what a YAML rule file deserializes into.

---

## 4. Storage schema

SQLite via `common/storage.py` (`RunStore`). The DDL below is what the code
actually creates.

### 4.1 `runs`

```sql
CREATE TABLE IF NOT EXISTS runs (
    run_id        TEXT PRIMARY KEY,
    connection_id TEXT NOT NULL,
    started_at    TEXT NOT NULL,
    ended_at      TEXT NOT NULL,
    status        TEXT NOT NULL
);
```

Missing: `CHECK (status IN ('success','failed','partial'))`. Add in `NEW-A`.

Note `ended_at NOT NULL` — a run cannot be persisted mid-flight. When `NEW-B` adds
partial-result persistence, this constraint has to be revisited alongside it.

### 4.2 `run_metrics`

```sql
CREATE TABLE IF NOT EXISTS run_metrics (
    ...
    run_id      TEXT NOT NULL REFERENCES runs(run_id),
    schema_name TEXT,
    table_name  TEXT,
    column_name TEXT,
    dimension   TEXT NOT NULL,
    score       REAL NOT NULL,
    ...
);
CREATE INDEX        IF NOT EXISTS idx_run_metrics_run_id       ON run_metrics(run_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_run_metrics_natural_key  ON run_metrics(...);
```

`idx_run_metrics_natural_key` is `COALESCE`-based, which is the right call: the
scope columns are nullable, and a plain unique index over nullable columns would
not deduplicate in SQLite. This is what makes `save_run` idempotent — re-saving
the same run does not double the metrics. Do not "simplify" it away.

Missing: `CHECK` on `dimension` (blocked on `NEW-A` fixing what `dimension` means).

### 4.3 `run_issues`

```sql
CREATE TABLE IF NOT EXISTS run_issues (
    issue_id    TEXT PRIMARY KEY,
    run_id      TEXT NOT NULL REFERENCES runs(run_id),
    schema_name TEXT,
    table_name  TEXT,
    column_name TEXT,
    dimension   TEXT NOT NULL,
    severity    TEXT NOT NULL,
    message     TEXT NOT NULL,
    ...
);
CREATE INDEX IF NOT EXISTS idx_run_issues_run_id ON run_issues(run_id);
```

Missing, all in `NEW-A`:

- `CHECK (severity IN ('info','warning','error','critical'))`,
- `CHECK` on `dimension`,
- an index on `(run_id, severity, dimension)` — the UI's issue list filters on
  exactly this and currently falls back to the `run_id` index plus a scan.

### 4.4 Tables the model implies but storage does not have

Two classes are exported and documented, and neither has anywhere to persist:

- **`run_rule_results`** — `RuleResult` and `RuleRunResult` are produced every run
  and then dropped on the floor. Rule outcomes are not queryable across runs, so
  "which rule started failing last Tuesday" is currently unanswerable.
- **`cleansing_log`** — `CleansingLog` exists as a class with no table. Per
  `CONVENTIONS-DQT.md` §1 (S4), reversibility *is* this table: the undo statement must
  be persisted before the forward statement runs. Without it, `apply` mode cannot
  be made safe, which is why `DQT-03`/`DQT-05` includes creating it.

Design note for `cleansing_log.run_id`: make it nullable with
`ON DELETE SET NULL`, not `NOT NULL`. A cleansing action may be applied outside a
pipeline run, and an audit record must outlive the retention window of the run
that triggered it. The audit trail is the last thing that should cascade away.

### 4.5 Retention

There is no retention policy and no pruning code. A long-running monitoring
deployment grows the store without bound. Decide a policy before shipping
monitoring (`NEW-G`): keep N runs, or keep runs younger than D days, with
per-connection granularity, and delete through the foreign keys rather than
around them.

---

## 5. Security conventions

- Credentials come from environment variables or secure config files. DQT must
  never write a DSN or password into a report, log, store row, or UI response.
- DQT should run with a read-only role: `SELECT` on target schemas, no
  `DELETE`/`UPDATE`/DDL on production data. The only exception is the separately
  credentialed `write_connection` in `CONVENTIONS-DQT.md` §1 (S1) — which does not
  exist yet.
- TLS options are configurable via `ConnectionConfig.ssl` where the driver
  supports them.
- `evidence` payloads are attacker-adjacent data rendered into HTML reports.
  Escape on render. A sample value from a profiled column can contain markup.
