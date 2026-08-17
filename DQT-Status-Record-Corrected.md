# DQT — Verified Status Record

**Verified:** 15 August 2026 · **Method:** direct source read of
`alisadeghiaghili/data-quality-toolkit` @ `main`

> **This document replaces `DQT_Space_Summary_Complete.md`.** That document
> presented itself as ground truth but derived most of its status claims from
> **file sizes in a directory listing** rather than from reading code. Five
> specific claims — including three of its five P0 items — do not hold against
> `main`. **Section 4** lists them so the errors are retired, not repeated.
>
> **Evidence rule for this document:** every row is `VERIFIED` (source read in
> this session, file named) or `UNVERIFIED` (stated as such). File size is not
> evidence. A large module is not a working module and a small one is not a
> broken one.

---

## 1. Identity

- **Repository:** `alisadeghiaghili/data-quality-toolkit` (public, MIT, `main`, 22 commits)
- **Package:** `dqt` v0.1.0 (pre-release)
- **Python:** `requires-python >= 3.11`
- **Runtime dependencies:** `pydantic>=2.0`, `rich>=13.0`, `pyyaml>=6.0`
- **Extras:** `dev`, `postgres`, `ui` (fastapi + uvicorn), `bridges` (commented out)
- **Database access:** DB-API 2.0 drivers directly. **SQLAlchemy is not a
  dependency.**

**Public description is wrong.** The GitHub repository description and
`README.md` both describe DQT as *"General-purpose data quality, cleaning,
profiling, and performance utilities for pandas DataFrames"* — contradicting the
actual SQL-first architecture. This is the project's most visible defect and the
cheapest to fix.

---

## 2. Verified Implementation Status

| Component | File | Status | Evidence |
|---|---|---|---|
| Public API | `dqt/__init__.py` | ✅ VERIFIED | Exports incl. `DQTPipeline`, `PipelineResult`, `DQIssue`, `DQMetric`, `Rule`, `RuleScope`, `SamplingConfig`, `from_dsn`, `from_yaml_config`. No `RuleSet`/`DomainConfig`/`ClassificationResult`/`from_sqlalchemy_engine` — correctly, since those types do not exist. |
| Schema discovery | `sql/schema_discovery.py` | ✅ VERIFIED | SQLite + PostgreSQL. |
| Profiling | `sql/profiling.py` | ⚠️ PARTIAL | Row counts, null counts, completeness. No min/max/mean/distinct/patterns/candidate keys. |
| Diagnostics | `sql/diagnostics.py` | ⚠️ THIN — **confirmed by reading** | `completeness` only; `warning` on any NULL, `error` at ≥50%. Docstring defers validity/uniqueness/consistency/referential integrity to "later versions". |
| Rules engine | `sql/rules.py` | ⚠️ PARTIAL | NOT NULL / UNIQUE / RANGE / REGEX, column scope only. Unknown expressions rejected (good). **Identifiers f-string interpolated; `range` bounds interpolated as literals; only `regex` is parameterized.** |
| Cleansing | `sql/cleansing.py` | ⚠️ UNSAFE AS DESIGNED | Primitives execute real `UPDATE`/`DELETE` on the source DB with `commit()` and need write access. "Reversible" means the log holds enough info to undo **manually** — no undo statements, no dry-run, no plan/apply split, log not persisted. The module-level `cleanse()` the pipeline calls is a separate pass-through that reaches none of them. See §3.1. |
| Pipeline | `sql/pipeline.py` | ⚠️ PARTIAL | Stages wired: discover → profile → diagnose → apply_rules → **cleanse (pass-through)** → metrics → monitor → persist → report. `status` hardcoded to `"success"`; no per-stage error handling. |
| Metrics | `sql/metrics.py` | ⚠️ MINIMAL | table_count, column_count, average_completeness. |
| Monitoring | `sql/monitoring.py` | ⚠️ STUB (deliberate, documented) | `monitor()` returns its input unchanged. Docstring states the intent honestly. Not a defect — an unbuilt feature. |
| Reports | `sql/reports.py` | ⚠️ PARTIAL | Self-contained HTML, score bars, severity badges. No PDF, no bilingual EN/FA, no `external_analyses` panel. |
| Data model | `common/models.py` | ✅ VERIFIED | Full Pydantic model set. |
| Storage | `common/storage.py` | ✅ VERIFIED | `RunStore` on SQLite; persists `connection_id` only, never DSNs. |
| Config loader | `common/config_loader.py` | ✅ VERIFIED | YAML/JSON + env expansion. |
| CLI / Rich CLI | `cli.py` | ⚠️ PARTIAL | `profile` subcommand only; progress bars and colorized tables present. |
| Dashboard UI | `ui/` | ❓ UNVERIFIED | Not read this session. `pyproject.toml` has a `ui` extra (fastapi + uvicorn), so a skeleton is likely. No frontend in any case. |
| Knowledge / Classification / Viz / Bridges | — | ❌ ABSENT | No `knowledge.py`, `classification.py`, `viz.py`, or `bridges/`. |
| CI | `.github/workflows/ci.yaml` | ✅ VERIFIED | lint (`ruff check` + `ruff format --check`) → typecheck (`mypy src/dqt/`) → unit tests (`--cov-fail-under=80`) → integration (SQLite). Matrix: Python 3.11, 3.12. |
| Tests | `tests/` | ⚠️ INCOMPLETE | Present: models, config_loader, storage, rules, pipeline, cleansing, public API, one integration test. **Missing:** `test_profiling.py`, `test_diagnostics.py`, `test_metrics.py`, `test_schema_discovery.py`. |

---

## 3. Findings Requiring Action

### 3.1 BLOCKER — the cleansing safety gap

Stated precisely, because the previous record blurred it:

- `cleansing.py` contains **write-capable primitives** — `standardize`,
  `deduplicate`, `lookup_correct` — which issue real `UPDATE`/`DELETE` against the
  source database and `commit()`. They require write access.
- The same module also exposes a module-level `cleanse()` that is a
  **pass-through** and reaches none of them.
- `pipeline.run()` calls `self.cleanse(result)` **unconditionally**, and that
  method delegates to the pass-through.

So: the primitives write, the pipeline path does not, and nothing is mutated
today. The original security convention (`CONVENTIONS-DQT-data-model.md` §4)
required DQT to operate with a read-only role, which the primitives cannot honour
by construction — a contradiction the documents never acknowledged.

**The danger is the pending task.** "Wire cleansing into `run()`" was recorded as
a P0 item and a next step. Executing it as written would make the default
profiling run mutate production, with no dry-run, no config gate, and no
automated undo.

**Resolution:** implement `CONVENTIONS-DQT.md` §S1–S5 (two connection roles,
`plan`/`apply` modes, mandatory `undo_statement`, row ceiling, quarantine instead
of delete) and **remove `cleanse` from `run()`** before touching the cleansing
module further. The "wire cleanse into run()" task is formally withdrawn.

### 3.2 BLOCKER — SQL injection via rule files

`rules.py` interpolates identifiers and `range` bounds directly into SQL. `range`
bounds come from user-authored YAML. No document defines a trust boundary for
rule files.

**Resolution:** `CONVENTIONS-DQT.md` §S6 — bind all literals, quote all
identifiers, keep the no-raw-SQL restriction, and document rule files as trusted
code.

### 3.3 MAJOR — run status can never be `failed` or `partial`

`status` is hardcoded to `"success"` and there is no per-stage error handling, so
a failing stage raises before anything is persisted. Every alert or dashboard
built on failed-run counts will report zero forever.

### 3.4 MAJOR — dimension vocabulary is not enforced

`dimension` is a free-text string in both the model and storage, and four
documents defined the dimension set differently. Two spelling variants create two
independent time series and silently break trend analysis.

### 3.5 MAJOR — storage cannot back required features

No table for rule results (required by the UI's rule-history screen); no table
for the cleansing log (required by C3's audit-trail requirement); no foreign
keys; no uniqueness constraint on metrics.

### 3.6 MAJOR — PostgreSQL is the primary target and is untested in CI

Integration tests run on SQLite only.

### 3.7 MINOR

- `postgres` extra installs both `psycopg[binary]` and `psycopg2-binary` — two
  drivers for one database.
- `external_analyses` exists on the model and is rendered by nothing.
- Docstring policy compliance never audited.
- `README.md` and the GitHub description are factually wrong.

---

## 4. Retired Claims

These appeared in the previous summary and do **not** hold against `main`. They
are recorded here so no future session re-opens them.

| Previous claim | Reality | Consequence |
|---|---|---|
| P0 #1 — duplicate `.github/workflows/ci.yml` must be deleted | The file returns 404; it does not exist | The task, the "denied deletion", and the follow-up "re-confirm with the user" are all moot |
| P0 #3 — `cleanse` is not called in `run()` | It **is** called; the callee is a pass-through | Correct instinct, wrong description — and the wrong description hid the real safety issue in §3.1 |
| §7 — a legacy `src/data_quality_toolkit/` package creates an identity conflict | Repository root renders `src/dqt/`; GitHub collapses that path only when `src/` has exactly one child | The "biggest unresolved product risk" is very likely already gone. Confirm once, then close permanently |
| Orphaned `tests/test_visualization_heatmap.py` | 404 | The inference of hidden visualization code in a legacy package collapses with it |
| CI matrix spans Python 3.9–3.13 | Matrix is 3.11 and 3.12, matching `requires-python >= 3.11` | Unfounded |

**Root cause:** implementation status was inferred from byte counts. Two of those
inferences happened to be right (diagnostics really is thin; monitoring really is
a stub), which produced false confidence in a method that was wrong five times.

---

## 5. Timeline

| Date (2026) | Event |
|---|---|
| Jul 01 | Initial design review; facets model defined; scope boundaries set |
| Jul 03 | Pipeline shell; end-to-end pipeline + HTML reports + CLI; Rich CLI + UI API + FastAPI skeleton |
| Jul 03–04 | Rules engine wired; CI added; cleansing implemented; public API surface (`from_dsn`, `from_yaml_config`) |
| Jul 04 | Design docs pushed to `docs/` |
| Jul 04 → Aug 15 | **Dormant — no commits (6 weeks)** |
| Aug 15 | Repo audits; document review; conventions rewritten against verified source |

Substantially all feature work occurred in roughly 36 hours on 3–4 July.

---

## 6. Assessment

DQT is meaningfully more than a design exercise. The data model, config loading,
storage layer, rule engine, and CI pipeline are real, typed, tested, and sound.
The facets model has successfully prevented scope creep across every document —
that is rare and worth protecting.

The gap is between what the documents claimed and what exists. Five of the twelve
named facets have no implementation (knowledge, classification, viz, bridges,
monitoring), diagnostics covers one of six dimensions, and cleansing is
implemented in a form that cannot be safely enabled. None of that was visible in
the previous status record, which is the more serious problem: a project can
recover from missing features far more easily than from a status document nobody
can trust.

**Recommended order:** the two blockers (§3.1, §3.2) first, since only they carry
irreversible cost. Then the four missing unit tests and a PostgreSQL CI job. Then
the two-minute fix to the repository description. Then diagnostics — the facet
whose absence most undercuts the product's core claim. UI, visualization, and
bridges remain real goals and remain secondary.
