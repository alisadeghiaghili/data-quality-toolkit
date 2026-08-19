# DQT — SQL Data Quality Toolkit (CONVENTIONS)

> **Normative for scope, vocabulary, and safety.** Where this document and a
> lower-ranked one disagree, this one wins — see `00-START-HERE.md` §1 for the
> full hierarchy. Where this document and the **code** disagree, the code wins
> and this document is the bug.
>
> This document does **not** restate the rules in the repository's `AGENTS.md`
> (SQL-safety enforcement, the no-untested-status rule, the four gates). Those
> live next to the code they govern and are referenced, never copied.
>
> **What to build next is the ecosystem `ROADMAP.md` (`DQT-01` … `DQT-09`), not
> here and not `BACKLOG.md`.** This document says what is true and what is
> allowed. `BACKLOG.md` records only defects that have no roadmap ID yet.
>
> **Part of §1 below is a proposal, not a settled requirement.** Sections marked
> ⚖ describe a safety design that differs from what `DQT-03` actually shipped.
> Those are owner decisions, open in `BACKLOG.md` §3. Do not implement one by
> assuming it was decided.

**Package:** `dqt` · **Repository:** `alisadeghiaghili/data-quality-toolkit` ·
**Version:** 0.1.0 (pre-alpha) · **Statuses verified:** 2026-08-17 at `4629925`

Sibling packages:

- `dqt` — SQL DB Data Quality Toolkit (DBA-focused).
- `missingly` — Missing Data Toolkit (missingness analysis and imputation).

Relationship: independent sister packages. DQT MAY call `missingly` or other
analyzers through optional bridge modules. DQT core MUST NOT import `missingly`
and MUST remain fully usable without it.

Scope: **data quality only** — no service/performance monitoring, no
masking/compliance, no MDM/golden record.

---

## 0. Canonical Vocabulary

### 0.1 Data-quality dimensions (closed set)

Exactly six dimensions exist. This list is closed. Adding a seventh requires
editing this section first.

| Identifier (snake_case, canonical) | Meaning |
|---|---|
| `completeness` | Presence of values (NULL / empty / placeholder analysis). |
| `validity` | Conformance to a format, domain, range, or semantic type. |
| `uniqueness` | Absence of unintended duplicates for a key or key set. |
| `consistency` | Agreement between related values within or across tables. |
| `referential_integrity` | Child rows resolve to existing parent rows. |
| `timeliness` | Freshness of data relative to a configured reference timestamp. |

Rules:

- The identifier above is the ONLY spelling permitted in code, configs, storage,
  reports, and the API. No spaces, no title case, no synonyms.
- MUST be implemented as a closed `DQDimension` type exported from `dqt`, and
  enforced with a `CHECK` constraint in the storage layer.
- **`timeliness` requires an explicitly configured reference timestamp column.**
  If none is configured for a table, the dimension MUST be *skipped* — no metric
  emitted. It MUST NOT be scored 1.0 by default. A dimension nobody measured is
  not a dimension everybody passed.

> **⚠ The code does not currently honour this.** `DQMetric.dimension` and
> `DQIssue.dimension` are plain `str`, and the field is carrying two
> incompatible meanings at once: `diagnostics.py` and `rules.py` store real
> dimensions in it, while `metrics.py` and `profiling.py` store *metric names*
> (`table_count`, `column_count`, `average_completeness`, `row_count`). Until
> `BACKLOG.md` `NEW-A` separates `dimension` from `metric_name`, the closed set
> above is a specification, not an invariant — and any grouping or scoring by
> dimension is wrong. Do not build on it before `NEW-A`.

### 0.2 Severity (closed set)

`info` · `warning` · `error` · `critical`

### 0.3 Run status (closed set)

`success` · `partial` · `failed` — semantics in the data-model document.

> **⚠ Only `success` is currently reachable.** `run()` hardcodes it. See
> `BACKLOG.md` `NEW-B`.

---

## 1. Safety Model (normative — read before implementing anything that writes)

This section supersedes any earlier text implying that cleansing and read-only
operation coexist without qualification. They do not. This is how they are
reconciled.

### ⚖ S1. Two connection roles *(proposal — see `BACKLOG.md` §3, Q4)*

- `read_connection` — **default and mandatory.** Requires only `SELECT` on the
  target schemas. Every stage except cleansing MUST use this connection and MUST
  NOT be able to reach a write-capable connection.
- `write_connection` — **optional, explicitly configured, separately
  credentialed.** Only `dqt.sql.cleansing` may use it. If it is absent, cleansing
  in `apply` mode MUST fail loudly rather than fall back to `read_connection`.

Rationale: separating *credentials*, not just intent, is what makes the read-only
guarantee auditable by a DBA who is not reading DQT's source.

**Status:** `DQT-03` instead enforces read-only on a single connection (SQLite
opened `mode=ro`, PostgreSQL set to `TRANSACTION READ ONLY`,
`ReadOnlyViolationError` raised independently in `sql/cleansing.py` before any
statement is built). That is implemented and test-backed on branch `dqt-03`
(`tests/unit/sql/test_read_only.py`), not yet merged to `main`. The
two-connection split above is a stronger proposal that has not been adopted,
and it interacts with `DQT-08`'s driver decision.

### ⚖ S2. Cleansing execution modes *(proposal — see `BACKLOG.md` §3, Q2)*

`cleansing.mode` is one of:

- `plan` — **default.** Computes the change set, produces `CleansingLog` entries
  and an executable SQL script (forward + undo). Executes **nothing**.
- `apply` — executes the change set. Requires ALL of:
  1. `cleansing.mode: apply` set in a config file — never inferable from a default,
  2. a configured `write_connection`,
  3. an explicit CLI opt-in (`--apply-cleansing`),
  4. a preceding `plan` run whose `plan_id` is passed in.

**Status:** `DQT-03` implements `apply_cleansing(dry_run=True)` by default plus
`--dry-run`/`--commit` flags on `dqt profile` (branch `dqt-03`, not yet merged
to `main`). The CLI flags currently govern only whether the profiled
connection is opened read-write; `profile` does not itself invoke cleansing
yet (see S3 below), so they become load-bearing for an actual write once a
future task wires `CleansingConfig` into the pipeline. The four-condition
scheme above is a superset; whether the extra ceremony is worth it is
undecided.

### ⚖ S3. `cleanse` is not part of the default pipeline *(proposal — see `BACKLOG.md` §3, Q1)*

`DQTPipeline.run()` MUST NOT invoke cleansing. Cleansing is a separate entry
point (`cleanse_plan()` / `cleanse_apply()`).

A profiling run must never be capable of mutating the database it profiles.

> **⚠ Not implemented, and not agreed.** `run()` calls `self.cleanse(result)`
> unconditionally at stage 5. It reaches a pass-through today, so no writes
> occur, and `DQT-03`'s read-only enforcement (branch `dqt-03`, not yet merged)
> now stands between that path and the database. Two defensible philosophies
> are in play: defence in depth (what `dqt-03` implements) versus separation of
> paths (what this section proposes). Escalate; do not pick one silently.

### S4. Definition of "reversible"

An operation may be called reversible only if it emits a machine-executable
`undo_statement` restoring the prior state, persisted to the `cleansing_log`
table **before** the forward statement executes.

A log that merely records enough for a human to reconstruct the change by hand is
an **audit trail**, not reversibility. Both are required; they are different
requirements and MUST NOT be conflated in docs or docstrings.

### S5. Transaction and blast-radius rules

- One transaction per (table, operation). Commit per unit — never one giant
  transaction across the run.
- Every `apply` operation MUST enforce a configurable `max_affected_rows` ceiling
  (default 10 000) and abort the unit if exceeded.
- ⚖ **`DELETE` as a cleansing primitive** *(proposal — `BACKLOG.md` §3, Q3)*.
  This section proposes banning it in v0.1 in favour of mark/quarantine, on the
  grounds that row destruction is an irreversible operation dressed up as data
  quality. Deduplication currently *does* use `DELETE`, with a `not_null_guard`
  added in the Phase 0 remediation to close a silent-data-loss path. Banning it
  would change tested behaviour. Undecided.

### S6. Threat model for rule files

**A rules YAML/JSON file is executable input with database privileges. Treat it
as code, not configuration.** It MUST come from the same trust boundary as the
application's own source — never user upload, never an untrusted repository.

Implementation obligations:

- **All identifiers** (schema, table, column) MUST pass through a per-dialect
  `quote_identifier()` and a strict validation pattern before interpolation.
  Direct f-string interpolation of an identifier is a defect.
- **All literals** — `range` bounds, lookup values, every parameter from a rule
  file — MUST be bound parameters.
- **No raw-SQL rule type** until a reviewed allowlist and a documented privilege
  model exist. The current design — four fixed expressions, unknown expressions
  rejected — is correct and MUST be preserved.
- Config loaders expand environment variables. Documented consequence: a rule
  file can read any environment variable visible to the process. Never run DQT
  with secrets in the environment that the rule author should not see.

> **⚠ Violated on `origin/main`; fixed locally.** `range` bounds are
> f-string-interpolated and table identifiers are not fully quoted on the public
> repository — `DQT-critical-review.md` §1.3 reproduced a working exploit.
> `DQT-02` (commit `a1f6ce7`) fixes both and is verified against seven
> supervisor-written exploits, but is **not pushed**. This is a live vector, and it is
> `DQT-02` for that reason.

---

## 2. Facets Model

Every feature MUST map to at least one facet, or be rejected as out of scope.

| Facet | Module | Responsibility | State |
|---|---|---|---|
| Profiling | `sql/profiling.py` | SQL-level column/table statistics. | partial, untested |
| Diagnostics | `sql/diagnostics.py` | Map statistics to `DQIssue` per dimension. | `completeness` only, untested |
| Rules | `sql/rules.py` | Declarative constraints, column and table level. | column scope only; `regex` dead on SQLite |
| Cleansing | `sql/cleansing.py` | Plan/apply repair with undo statements. | primitives exist, unsafe |
| Metrics | `sql/metrics.py` | Quantitative scores per table/column/dimension. | 3 global metrics, untested |
| Monitoring | `sql/monitoring.py` | Trends and drift of DQ metrics over time. | stub, untested |
| Knowledge/Domain | `knowledge.py` | Reference data for validation and correction. | not started |
| Classification | `classification.py` | Semantic typing (email, phone, IBAN, national id). | not started |
| Missingness (internal) | within profiling/metrics | Null counts, ratios, co-occurrence patterns. | counts and ratios only |
| Imputation (external) | `bridges/` | Delegated to `missingly` et al. Never reimplemented. | not started |
| Reports | `sql/reports.py` | HTML/PDF scorecards, bilingual EN/FA. | HTML only, untested |
| Viz/UI | `viz.py`, `ui/` | Charts, dashboards, DBA-facing screens. | `ui/` backend skeleton; no `viz.py` |

Out of scope, permanently:

- Service/performance monitoring (latency, CPU, wait stats, uptime).
- Masking/compliance (masking policies, compliance audit trails).
- MDM / golden record.
- Reimplementing `missingly` algorithms.

**Disambiguation:** "monitoring" in DQT means tracking *data-quality metrics*
over time. Where competitor documentation uses "latency" or "freshness" as a
pipeline indicator, that maps to our `timeliness` dimension — a property of the
*data*, not of the *service*. Do not let shared vocabulary pull service metrics
into scope.

---

## 3. Supported Platforms (normative)

| Dialect | Status in v0.1 | Notes |
|---|---|---|
| SQLite | Supported — development and test target | Used by unit and integration tests. |
| PostgreSQL | Supported — primary production target | `postgres` extra. **Untested in CI.** |
| MySQL | **Not supported** | No driver, no discovery implementation. |
| SQL Server | **Not supported** | No driver, no discovery implementation. |

Rules:

- No document, docstring, or README may claim support for a dialect not marked
  Supported above.
- DQT talks to databases through **DB-API 2.0 drivers directly**. SQLAlchemy is
  **not** a dependency. Any convention assuming a SQLAlchemy `Engine` is withdrawn.
- **Before adding a third dialect**, a `dqt/sql/dialects/` abstraction MUST exist
  (identifier quoting, parameter style, information-schema queries, LIMIT/TOP).
  Adding one to the current per-driver branching would triple the SQL paths.
- The `postgres` extra currently installs both `psycopg[binary]` and
  `psycopg2-binary`. Exactly one must remain; `psycopg` (v3) is the choice.

---

## 4. Evidence rule for status claims

The full rule — what counts as evidence in this repo, worked examples per
subsystem, and the mandatory fail→pass proof for any fix — lives in
`docs/HONESTY-GATE.md` and is not repeated here. The one-line version: **a claim
must be backed by an external, executable ground truth, and a passing
self-referential unit test is not one.**

File size is not evidence. A commit message is not evidence. A docstring is not
evidence; docstrings in this repository have described behaviour that had never
been executed. Where a claim is untested, mark it as such rather than softening
the wording — "implemented" and "works" are different words for a reason.

### 4.1 Docstring policy

**Style: Google, English only.** This is fixed per repo by the ecosystem standard
and must not be churned — `missingly` and `py-distfit-pro` use NumPy/numpydoc,
`distfitr` uses roxygen2, DQT uses Google. Do not "harmonize" them.

Every public symbol needs a one-line summary ending in a period; **every**
parameter documented with type, default, and boundary behaviour; `Returns` naming
each key or field for dict/tuple returns; `Raises` for every exception type
raised directly; and a **runnable** `Example`.

A docstring may only describe behaviour covered by a passing test. If you write
"reversible", "auditable", or give an example return value, a test must verify
that exact claim — otherwise mark it aspirational or do not write it. Docstrings
in this repository have described behaviour that had never been executed.

Comments explain **why**, never what. A comment recording an empirical finding —
"verified: sqlite3 raises OperationalError for `PRAGMA table_info(?)`" — is high
value; keep those.

The gate is `tools/doc_audit.py`, which supports ratchet mode against a recorded
baseline. Wiring it in is `DOC-01`; paying down the existing debt is `DOC-02`.

---

## 5. Status Register

Current state per area, as of the verification date in the header. This is a
register, not a plan — for what to do about it, and in what order, see
`BACKLOG.md`.

State is given for **`origin/main`**. Where a fix exists but is unpushed, the
table says so — see `BACKLOG.md` §1.

| Area | State on `origin/main` | Task |
|---|---|---|
| Rules engine — `not_null`, `unique`, `range` | Works, tested | — |
| Rules engine — `regex` | **Dead on SQLite.** Emits `NOT REGEXP ?`; no `create_function` anywhere. Every regex rule yields a permanent false `error`. No test | `DQT-04` |
| Rules engine, table scope | Not started | no ID yet |
| Rule-file SQL safety | **Defective** — reproduced exploit. Fixed at `a1f6ce7`, **not pushed** | `DQT-02` |
| `read_only` enforcement | **None.** Zero consumers, no `--dry-run`. Fixed at `7ae3fdc`, **not pushed** | `DQT-03` |
| Cleansing persistence and `revert` | Absent. `CleansingLog` in memory only; no `revert()`/`undo()`; no table | `DQT-05` |
| Pipeline orchestration | Works. Whether `cleanse` belongs on the `run()` path is undecided | `BACKLOG.md` §3 Q1 |
| Pipeline error handling | **Absent**; status always `success` | `NEW-B` |
| Exit-code contract | **Absent** — the CI-gate use case is impossible | `DQT-06` |
| Exception hierarchy | **Absent** | `DQT-09` |
| Profiling | Row/null counts, completeness. No min/max/mean/distinct/patterns. Untested | `NEW-C` |
| Diagnostics | `completeness` only. Untested | `NEW-C` |
| Dimension vocabulary | **Not enforceable** — field carries two meanings | `NEW-A` |
| Metrics | 3 global metrics. Untested | `NEW-A`, `NEW-C` |
| Monitoring | Stub — returns input unchanged | `NEW-G` |
| Storage (`RunStore`) | Works, tested. Missing `CHECK` constraints and two tables | `NEW-A`, `DQT-05` |
| Public API surface | Matches reality | — |
| CLI | `dqt profile` only | — |
| HTML report | Self-contained, score bars, severity badges. Untested | `NEW-C` |
| UI backend | FastAPI skeleton over a read-only data layer. Untested, no frontend | `NEW-D` |
| Bridges to `missingly` | Not started; `external_analyses` field unread | `NEW-E` |
| CI | Works: ruff, ruff format, mypy strict, pytest at 80%. Python 3.11/3.12 | — |
| PostgreSQL in CI | **Absent** | no ID yet |
| Two PostgreSQL drivers installed | Both `psycopg[binary]` and `psycopg2-binary` | `DQT-08` |
| Unit test coverage | 6 modules with zero unit tests | `NEW-C` |
| Docstring compliance | Unaudited. A gate exists (`doc_audit.py`) and is not wired in | `DOC-01`, `DOC-02` |
| Architecture / layering | Unaudited against the standard's layering rule | `ARC-01` |
| README and repo description | **Factually wrong**, publicly visible | `DQT-01` |

### Public API surface — currently exported from `dqt/__init__.py`

`DQTPipeline`, `PipelineResult`, `SchemaResult`, `TableResult`, `ColumnResult`,
`DQIssue`, `DQMetric`, `Rule`, `RuleConfig`, `RuleResult`, `RuleRunResult`,
`RuleScope`, `SamplingConfig`, `ConnectionConfig`, `DQPipelineConfig`,
`IssueSeverity`, `RuleStatus`, `RunStatus`, `from_dsn`, `from_yaml_config`,
`load_connection`, `load_pipeline`, `load_rules`, `load_rules_from_files`,
`__version__`.

To add when the backing types exist, and not before: `DQDimension` (`NEW-A`),
`RuleSet` (table-scope rules (no ID yet)), `DomainConfig`, `ClassificationResult`.

**Standing rule:** never export a name with no real type behind it. A public API
that lies is worse than a small one.

---

## 6. Withdrawn / Closed Items

Recorded so future sessions do not resurrect them.

| Item | Resolution |
|---|---|
| Delete duplicate `.github/workflows/ci.yml` | Closed — does not exist. Only `ci.yaml`. |
| Wire `cleanse` into `DQTPipeline.run()` | **Withdrawn** — violates §1 (S3). It is already there and must be removed. |
| Investigate legacy `src/data_quality_toolkit/` package | Closed — verified absent; the tree contains only `src/dqt/`. |
| Orphaned `tests/test_visualization_heatmap.py` | Closed — does not exist. |
| `from_sqlalchemy_engine()` | Withdrawn — SQLAlchemy is not a dependency (§3). |
| `black` in CI | Withdrawn — `ruff format` is used instead. |
| 90% coverage gate | Withdrawn — the gate is 80% in both `pyproject.toml` and CI. To change it, change the gate first, then the document. |
| Python 3.9–3.13 CI matrix | Withdrawn — the matrix is 3.11 and 3.12, matching `requires-python`. |
| `DQMetrics` (plural) in the public API | Withdrawn — never existed. The class is `DQMetric`. |
| "Avoid full-table scans" as guidance | Withdrawn — unimplementable as written; replaced by the sampling and budget work in `NEW-F`/sampling (no ID yet). |
| `src/dqt/ui/` is unverified | Closed — read on 2026-08-17. FastAPI skeleton over a read-only data layer, no tests, no frontend. |
| A DQT-local task numbering (`B1`…`B15`) | Withdrawn — the ecosystem `ROADMAP.md` already defines `DQT-01`…`DQT-09`. A second numbering is the same defect this document set exists to prevent. |
| "Four rule expressions work" | Withdrawn — three work. `regex` is dead on SQLite (`DQT-04`). |
