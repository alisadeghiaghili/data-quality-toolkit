# DQT — Critical Review

**Date:** 2026-08-11
**Reviewed:** `data-quality-toolkit` @ `main` — 4,432 LOC source / 3,633 LOC tests, 6 project docs, 2 convention docs (duplicated), 2 CI workflows
**Method:** full read of every source file, plus *executed* verification — installed the package, ran pytest / ruff / mypy / coverage, and ran the pipeline, CLI, rule engine and cleansing engine against real SQLite databases.

Every finding marked **CONFIRMED** below was reproduced by running code, not inferred from reading.

---

## 0. Verdict

The design documents describe an excellent product. The repository does not implement it.

DQT has the *shape* of a mature library — layered facets, Pydantic models, Google-style docstrings on every public symbol, a matrixed CI workflow, a data-model spec calling itself "the single source of truth." Underneath: **the CLI has never successfully run once**, **every quality gate the docs claim to enforce is red**, and the two modules that touch production data (rules, cleansing) contain a confirmed SQL-injection path and a confirmed silent-data-loss path.

The gap between claim and reality is itself the most serious defect, because it is systemic. `CONVENTIONS-DQT.md` marks C1, C2, C3, A1, A2, A3, T1, T2, T3, Q1, Q2 as `[x] DONE`. Verified: **none of those eleven claims is true as written.** A codebase whose docstrings lie is more dangerous than one with no docstrings, because reviewers — and coding agents — trust them and build on top.

The good news: the *architecture* is mostly right, the domain model is close, and the failures are concentrated and fixable. Roughly two weeks of disciplined work gets this to an honest v0.1. But nothing should be built on top of the current tree.

### Hard numbers (CONFIRMED)

| Gate | CONVENTIONS T3 claims | Actual |
| :-- | :-- | :-- |
| `pytest` | enforced, "60+ tests passing" | **17 failed, 1 error**, 155 passed |
| `ruff check src/ tests/` | enforced | **146 errors** |
| `ruff format --check` | enforced | **21 of 34 files would reformat** |
| `mypy src/dqt/ --strict` | enforced | **37 errors in 8 files** |
| Coverage ≥ 80% | enforced | **73.24%** — gate fails |
| `dqt profile` (the only command) | `[x]` implemented | **crashes 100% of invocations** |
| `dqt` console script | shipped in pyproject | **`ModuleNotFoundError`** |

CI has never been green. Not once. The workflow file is aspirational fiction.

---

## 1. P0 — Blockers

### 1.1 The CLI is completely non-functional — CONFIRMED

`src/dqt/cli.py:175` constructs `DQPipelineConfig(...)` without the required `connection_id` field:

```
$ python -m dqt profile --dsn sqlite:///demo.db
pydantic_core._pydantic_core.ValidationError: 1 validation error for DQPipelineConfig
connection_id
  Field required
```

Unhandled, no traceback suppression, no exit-code contract. **Facet: Viz/UI.**

This proves two things beyond the bug itself: `cli.py` has **0% test coverage** (confirmed — 134 statements, zero covered, no test file references `dqt.cli`), and the documented command in the module docstring and in `CONVENTIONS` Q1 has never been executed by anyone.

### 1.2 The packaged entry point points at a module that doesn't exist — CONFIRMED

```toml
[project.scripts]
dqt = "dqt.cli.plain:main"   # there is no dqt/cli/ package and no plain.py
```

`dqt --help` → `ModuleNotFoundError: No module named 'dqt.cli.plain'`. `python -m dqt` reaches the code (and then hits 1.1).

### 1.3 SQL injection through rule files — CONFIRMED EXECUTED

`src/dqt/sql/rules.py:299-310` interpolates `params.min` / `params.max` straight into the WHERE clause. Reproduced — the injected subquery ran against the target database:

```python
params={"max": "(SELECT COUNT(*) FROM secret WHERE x LIKE 'sensitive%') - 1"}
# → "Column 'v' in 't' has 2 value(s) outside the range
#    [-inf, (SELECT COUNT(*) FROM secret WHERE x LIKE 'sensitive%') - 1]"
```

Compounding factors:

- **Table names are never quoted at all.** `_qualified_table()` (`rules.py:190-192`) returns bare `schema.table`. Meanwhile `profiling.py:198-205` *does* quote and escape via `_ident()`. Two contradictory identifier policies in one library — the profiling one is correct, the rules one is exploitable by a hostile or merely awkward table name.
- Column names get `"` wrapping with **no escaping** of embedded quotes.
- Under psycopg2 (the driver `rules.py` chose for Postgres) `execute()` accepts multiple statements, so on Postgres this escalates from expression injection to arbitrary DDL/DML. Under sqlite3 it is currently contained to single-statement injection only by driver accident, not by design.

Rule files are semi-trusted config, but a DQ tool is aimed at production databases, is designed to accept rule files from other teams, and runs unattended in CI. This is not acceptable. **Facet: Rules.**

### 1.4 Cleansing silently no-ops on virtually every real table — CONFIRMED

`cleansing.py` identifies rows by `rowid`, reading `row["rowid"]` from a dict built off `cursor.description`. When a table has an `INTEGER PRIMARY KEY`, SQLite aliases `rowid` to that column and reports **the column's name** in `description`:

```
description for "SELECT rowid FROM u ..."  →  (('id', ...),)   # not 'rowid'
→ KeyError('rowid')
→ swallowed by `except Exception` at cleansing.py:559
→ result: total_changes=0, errors=["Error in 'deduplicate' on u.None: 'rowid'"]
```

A DBA runs cleansing, sees `0 changes`, and concludes the data was already clean. **This is the failure mode of a data-quality tool producing a false all-clear.** It is also the cause of 9 of the 17 test failures — the tests were written, committed, marked DONE, and never run.

### 1.5 Deduplication deletes distinct rows whose key is NULL — CONFIRMED

`cleansing.py:339-347` does `GROUP BY key_columns` with no NULL guard. SQL `GROUP BY` collapses all NULLs into one group, so *n* genuinely distinct customers with a NULL email become one survivor and *n-1* deletions. Reproduced: the delete-set query returned the rowids of three distinct NULL-email customers. Only the `rowid` bug above (1.4) currently prevents the data loss from landing. Fix 1.4 without fixing this and you ship a data-shredder. **Facet: Cleansing.**

### 1.6 `read_only=True` is enforced nowhere — CONFIRMED

`ConnectionConfig.read_only` defaults to `True` and is documented as "Enforce read-only session." Grep: it is read by **zero** lines of code. `apply_cleansing()` happily issues `UPDATE` and `DELETE` on a connection built from `read_only=True` config (verified). There is also no `--dry-run`, no confirmation prompt, and no transaction preview.

For a tool whose own security conventions say "DQT SHOULD operate with read-only roles: no DELETE/UPDATE/DDL on production data," this is a direct self-contradiction.

### 1.7 "Reversible, auditable" cleansing is neither — CONFIRMED

Claimed in the module docstring ("Operations are **reversible**"), in `CONVENTIONS` C3 ("Reversible, auditable, no silent changes"), and in the data-model doc.

Reality: `CleansingLog` objects are built in memory and returned to the caller. `RunStore` has **no cleansing table** (grep for "cleansing" in `storage.py`: no match). There is **no `revert()` / `undo()` function anywhere**. If the caller drops the return value — which the pipeline's own `cleanse()` adapter effectively does — the before-values are gone forever. The commit at `cleansing.py:565` is a point of no return.

### 1.8 Regex validity rules are dead on the only supported backend — CONFIRMED

```
Rule 'valid_email_format' evaluation error on 'customers.email': no such function: REGEXP
```

`rules.py:353-359` emits `NOT REGEXP ?` for SQLite. SQLite ships no `REGEXP` implementation; the caller must register one via `conn.create_function`. Grep: `create_function` appears **nowhere** in the codebase. The docstring even admits the requirement and then never satisfies it.

Consequences: every `regex` rule turns into a permanent false `error`-severity issue instead of validating anything. `examples/rules/advanced_rules.yaml`'s only email rule is broken out of the box. And because semantic validity (email, IBAN, phone, national_id) is the project's stated **differentiator**, the differentiator does not work. **Facet: Rules, Classification.**

### 1.9 Missing rule files are silently swallowed → false green — CONFIRMED

```python
# pipeline.py:284-288
except FileNotFoundError:
    pass   # "A proper logging call would go here once logging is wired."
```

Verified: pointing `rule_files` at a nonexistent path yields `status="success"`, `rules_run=[]`, zero rule issues, exit 0. A path typo in CI reads as "all checks passed."

Combined with 1.10 (no exit codes), DQT's headline use case — gate the pipeline on data quality — is not merely unimplemented, it is *actively unsafe*: it reports success when it checked nothing.

### 1.10 No exit-code semantics — the CI-gate use case is impossible

`_cmd_profile` returns `0` regardless of how many `critical` issues were found. No `--fail-on`, no `--json`, no machine-readable output at all. This is the single feature that made Great Expectations and Soda adoptable, and the competitor doc lists it as floor ("fail builds on data-quality regressions"). It's absent. **Facet: Viz/UI, Monitoring.**

### 1.11 Runtime dependencies are undeclared — a clean install cannot import the CLI

`[project.dependencies] = ["pydantic>=2.0"]`. Actually imported at runtime:

| Package | Imported by | Declared |
| :-- | :-- | :-- |
| `rich` | `cli.py` (unconditional, module level) | ❌ |
| `pyyaml` | `config_loader.py` (required for every documented flow) | dev extra only |
| `fastapi` | `ui/app.py` | ❌ |
| `psycopg` / `psycopg2` | `schema_discovery.py` / `rules.py` | ❌ (no extra) |
| `pandas`, `numpy`, `scipy`, `matplotlib`, `seaborn` | legacy `data_quality_toolkit` | ❌ |

`pip install dqt` then `import dqt.cli` → `ModuleNotFoundError: rich`. Worse, `[tool.setuptools.packages.find] where=["src"]` auto-discovers and **ships the legacy `data_quality_toolkit` package inside the `dqt` wheel**, so the distribution contains a module that cannot import in any environment matching its own declared metadata.

Note also the driver split: `schema_discovery.py` imports **psycopg (v3)**, `rules.py` imports **psycopg2**. Two incompatible Postgres drivers in one package.

---

## 2. P1 — Correctness and design

### Data-integrity and reporting bugs

**2.1 `ColumnResult.db_type` is the literal string `"ColumnProfile"` for every column — CONFIRMED.**
`pipeline.py:459` writes `db_type=column_profile.__class__.__name__`. Verified: `{'ColumnProfile'}` is the entire set of distinct db_type values across a real run. The real type *is* discovered (`DiscoveredColumn.data_type`) and then discarded. The field's own docstring promises `"VARCHAR(255)"`. Every downstream consumer — reports, UI, future classification — is reading garbage.

**2.2 Severity is sorted alphabetically in three places.** `storage.py:359` (`ORDER BY severity DESC`), `cli.py:269`, `reports.py:248`. Alphabetical order is `warning > info > error > critical`, so **`critical` sorts last** in the store and the report, and the CLI's "most important first" is `warning, info, error, critical`. Needs a `severity_rank` column / `CASE` expression and a shared ordering constant.

**2.3 Critical issues render green in the HTML report.** `reports.py:124`: `{"error": "err", "warning": "warn", "info": "ok"}.get(severity, "ok")` — `critical` falls to the default `"ok"`, i.e. the green success badge. The most severe class of finding is displayed as passing. **Facet: Reports.**

**2.4 Empty/unprofiled tables report 100% completeness.** `reports.py:192-195` and `metrics.py:37-45` both default missing scores to `1.0`. A table that failed to profile shows a green 100% bar. Absence of evidence is rendered as evidence of quality — exactly backwards for this domain.

**2.5 `RunStore.save_run` is not idempotent, contrary to its docstring — CONFIRMED (failing test).** `run_metrics` has only an `AUTOINCREMENT` surrogate key and no unique constraint on `(run_id, schema, table, column, dimension)`, so `INSERT OR IGNORE` never fires and re-saving a run duplicates every metric row. The docstring claims "the entire save is skipped." `run_issues` is correct only because `issue_id` is the PK.

**2.6 Connection leak on every store operation.** `with self._connect() as conn:` — a sqlite3 connection context manager commits/rolls back but **does not close**. Every `load_runs` / `load_metrics` / `load_issues` / `save_run` leaks a file handle plus a WAL-mode connection.

**2.7 Storage schema diverges from the doc that calls itself the single source of truth.** The data-model spec mandates composite indexes on `(run_id, schema_name, table_name, column_name, dimension)` and `(run_id, severity, dimension)`. Only single-column `run_id` indexes exist. There is also no `schema_version` table (so no migration path), no retention/pruning, no `run_rules` table, and no `cleansing_log` table.

### Model and semantics

**2.8 Counts are being smuggled through a score-shaped field.** `row_count`, `table_count`, `column_count` are emitted as `DQMetric(score=1.0, value=<count>)`. A row count is a **measure**, not a normalized quality score. Today this pollutes the metrics table, renders as "100.00%" in the CLI's Score column, and will corrupt any future aggregate that averages `score`. Split the model: `Measure` (unbounded raw) vs `Score` (0–1, comparable, aggregatable), or add an explicit `kind` discriminator. Get this right before monitoring is built on top, or every trend chart inherits the confusion. **Facet: Metrics.**

**2.9 Three declared, validated, exported, documented features are read by zero lines of code:**

- `SamplingConfig` — profiling always full-scans; the sampling strategy is never consulted.
- `DQPipelineConfig.metric_thresholds` — validated to be in [0,1], then ignored. Diagnostics hardcode `ratio >= 0.5` for `error`.
- `ConnectionConfig.read_only` — see 1.6.

**2.10 `RuleResult` and `Rule` are dead code.** `RuleResult` is exported, documented, and required by the data-model spec ("per-target result") — and is **never constructed**; `PipelineResult` has no field to hold it. `Rule` (the domain object) is exported and documented while the engine operates directly on `RuleConfig`. So per-target rule outcomes are unavailable to the UI, and `rules_run` summaries are never persisted at all.

**2.11 `from_yaml_config()` cannot work as documented.** Its docstring says the file contains `connection` and `pipeline` **sections**, but it calls `load_connection(path)` and `load_pipeline(path)`, each of which validates the *entire document* against its own model. Those two statements are mutually exclusive. Untested (no test references it).

**2.12 Config models don't forbid extras.** No `model_config = ConfigDict(extra="forbid")`. A YAML typo — `include_shcemas` — is silently dropped and DQT profiles the entire database while the DBA believes it scoped to one schema. For a config-driven tool aimed at production, silent key-drop is the wrong default.

**2.13 Unresolved `${VAR}` placeholders pass validation.** `config_loader._expand_env` deliberately leaves them in place; `dsn_must_not_be_empty` only checks for blank. So an unset env var produces a connection attempt against the literal string `${PROD_DB_DSN}`. Fail loudly at load time instead.

**2.14 Fragile error classification.** `rules.py:645` decides `targets_error` vs `targets_failed` by substring-matching `"evaluation error" in i.message`. Any message rewording silently changes the summary. Unknown-expression issues are also miscounted as `failed` rather than `error`. Carry a structured status, not prose.

**2.15 Inconsistent denominators across rule evaluators.** `_eval_not_null` / `_eval_range` / `_eval_regex` use `COUNT(*)`; `_eval_unique` uses `COUNT(col)`. Pass rates across rules aren't comparable, and any future "rule score" will be wrong.

**2.16 Dead code:** `_eval_range` (`rules.py:299-303`) builds a `conditions` list and discards it. `reports.generate_report()` is an unused wrapper. `ui/app.py:39-60` wraps the fastapi import in `try/except ImportError` and then unconditionally `raise ImportError` anyway.

### Performance — currently unusable at DBA scale

**2.17 Profiling is N+1 by construction.** `profiling.py:185` issues one `SELECT COUNT(*) ... WHERE col IS NULL` **per column**, plus one `COUNT(*)` per table. A 100-column table = **101 full table scans**. A 200-table schema = tens of thousands of scans. Every one of those is a single aggregate query away from being free:

```sql
SELECT COUNT(*), COUNT(c1), COUNT(c2), ..., MIN(c1), MAX(c1), COUNT(DISTINCT c1), ...
FROM tbl;   -- one pass, all columns, all measures
```

**2.18 The rule engine adds 1–2 more full scans per (rule × column)**, unbatched, and re-runs `SELECT COUNT(*)` for the same table on every single evaluation. Rules against the same table should compose into one query with `SUM(CASE WHEN ... END)` per rule.

**2.19 Deduplication is `rowid NOT IN (subquery)` + one `SELECT *` + one `DELETE` per duplicate row.** For a million duplicates that's two million round-trips against a non-indexed anti-join.

**2.20 No sampling, no `TABLESAMPLE`, no approximate distinct, no `LIMIT` on evidence collection, no query timeout, no statement cancellation.** `CONVENTIONS` V2 (performance budgets) is honestly marked `[ ]`, which is the right call — but the current design would need reworking, not tuning, to meet one.

**2.21 `ui.get_run_summary` loads up to 1000 runs and linear-scans them in Python** (`api.py:97`) because `RunStore` has no `get_run(run_id)`. Runs older than the newest 1000 return 404.

---

## 3. Facet reality check

`CONVENTIONS-DQT.md` status vs. verified behavior. This table is the single most important artifact in this review.

| Facet | Doc claims | Actually implemented | Verdict |
| :-- | :-- | :-- | :-- |
| **Profiling** | `[x]` min/max, mean, distinct counts, null counts/ratios, pattern & length profiles, row counts, orphan FK rows, referential integrity | **null counts and row counts only** | ✗ ~15% |
| **Diagnostics** | `[x]` completeness, consistency, validity, uniqueness, timeliness, severity + evidence | **one check: `null_count > 0`**, hardcoded 0.5 threshold | ✗ ~10% |
| **Rules** | `[x]` NOT NULL, UNIQUE, range, regex; column rules done, table rules the only gap | NOT NULL / UNIQUE / range work; **regex broken (1.8)**; injectable (1.3); no table/FK/conditional/SQL rules; unreachable from CLI | ✗ ~40% |
| **Cleansing** | `[x]` reversible, auditable, no silent changes | **non-functional on real tables (1.4)**, irreversible (1.7), unlogged, ignores read-only (1.6), data-loss bug (1.5) | ✗ — worse than absent |
| **Metrics** | `[x]` wired | 4 metrics, counts mislabeled as scores (2.8) | ~ 25% |
| **Monitoring** | `[x]` wired | `def monitor(m): return m` — literal identity | ✗ 0% |
| **Knowledge / Domain** | `[ ]` | absent | ✓ honest |
| **Classification** | `[ ]` | absent (and blocked on 1.8) | ✓ honest |
| **Missingness (internal)** | `[~]` null ratios yes, co-occurrence no | matches | ✓ honest |
| **Imputation (external)** | `[ ]` bridges | absent; `external_analyses` field exists, never written or rendered | ✓ honest |
| **Reports** | `[~]` HTML works, bilingual missing | HTML renders but **critical shows green (2.3)**, empty = 100% (2.4), no rules section, no trends | ✗ |
| **Viz / UI** | `[x]` CLI + Rich CLI; `[~]` UI skeleton | **CLI crashes (1.1)**; progress bar is fake (3.1); no plain CLI; no `dqt check`; UI has 0% coverage and no frontend | ✗ |
| **Schema discovery** | `[x]` "schema + FK discovery" | tables + columns only; **no FK discovery at all** | ✗ |
| **Tests / CI** | `[x]` all gates enforced, ≥80% coverage | **every gate red** (§0) | ✗ |

**3.1 The progress bar is theater.** `cli.py:339-356` iterates eight stage labels doing nothing, then runs the *entire pipeline* inside the last one:

```python
for stage in stages:
    progress.update(task, description=stage)
    if stage == "Generating HTML report":
        result, report_path = pipeline.run()   # the whole thing, here
    progress.advance(task)
```

The user watches seven stages flash by instantly, then stares at "Generating HTML report" for the duration of the actual work. `CONVENTIONS` Q2 marks "progress bars for pipeline stages" as DONE. This is worse than no progress bar — it misattributes where time is spent, which is precisely what a DBA is watching for.

**3.2 There is no plain CLI.** The requirement is explicitly *both* a non-interactive CLI for automation and a Rich CLI for humans. Only the Rich path exists, output goes to stderr with markup, and there is no `--json` / `--quiet`. Ironically the dead entry point (`dqt.cli.plain:main`) names the module that should have existed.

**3.3 `dqt check` doesn't exist and rules are unreachable from the CLI.** `CONVENTIONS` Q1 claims `dqt check --rules rules.yaml` with exit codes. There is no `check` subcommand, and `profile` has no `--rules` flag — `_build_pipeline_config` never sets `rule_files`. **The entire rule engine cannot be invoked from the command line.**

**3.4 Credentials on the command line.** `--dsn postgresql://user:pass@host/db` is visible in `ps`, shell history, and CI logs — contradicting the project's own security convention that credentials must come from env vars. Needs `--dsn-env DQT_DSN` and DSN redaction in all error output.

---

## 4. The legacy `data_quality_toolkit` package — delete it

A pandas toolkit from before the repo was repurposed. **Never imported by `dqt`** (grep confirms), 3 of its 4 modules have **zero tests**, and it drags five undeclared dependencies into the wheel (1.11). It also directly contradicts the project's SQL-first scope.

It is not merely vestigial, it is buggy — CONFIRMED by repro:

- **`cleaning.remove_empty` causes silent data loss.** It collects index *labels* and calls `result.drop(index=labels)`, which drops **every row sharing that label**. A 2-row frame with duplicate index `0`, one row all-NaN → both rows deleted, including the fully valid one.
- **`performance.optimize_dtypes` crashes on nullable integer dtypes with NA** (`ValueError: cannot convert NA to integer`) — which is exactly what you get reading a SQL `INTEGER NULL` column.
- **`optimize_dtypes` silently loses precision.** It gates float64→float32 with `np.allclose` at numpy's default `rtol=1e-5`, so `999999.999 → 1000000.0` and `100000.001 → 100000.0`, no warning. Silent mutation of precise/monetary values, inside a *data quality* tool.
- `statistics.hotelling_test` math checks out, but its sufficiency gate (`n2 >= d+2`) contradicts its own identity-matrix fallback.

Supporting evidence that this is stale residue: `README.md` still describes *this* package, not DQT; and a second, orphaned `.github/workflows/ci.yml` runs `pip install .[test]` (**no `test` extra exists — that job fails outright**), matrixes Python 3.9–3.13 against a `requires-python = ">=3.11"` project, and installs from `git+https://github.com/alisadeghiaghili/data-quality-toolkit.git@main`.

**Recommendation:** delete `src/data_quality_toolkit/`, `tests/test_visualization_heatmap.py`, and `.github/workflows/ci.yml`. If any of it has value, it belongs in a separate sibling package next to `missingly` — not in DQT's namespace or its wheel. Keeping it costs coverage percentage, install weight, CI time, and reviewer confusion, and buys nothing.

---

## 5. Test suite — the quality gate that isn't

Coverage measured at **73.24%**, below the 80% gate the CI claims to enforce.

```
src/dqt/cli.py                 0%    (134 statements, entirely uncovered)
src/dqt/ui/api.py              0%
src/dqt/ui/app.py              0%
src/dqt/ui/__init__.py         0%
src/dqt/__main__.py            0%
src/dqt/sql/schema_discovery.py 65%  (entire Postgres path untested)
src/dqt/sql/rules.py           79%  (_eval_regex and the unknown-expression branch: 0%)
```

Beyond the numbers, the suite has structural problems:

**5.1 The broken tests were never run.** `test_rules.py` constructs `DiscoveredColumn(..., is_nullable=True, ordinal_position=1)` — fields that don't exist on the dataclass (`schema_name, table_name, column_name, data_type, nullable`). `TypeError` on every use. That means the rule-engine test class has *never* passed, which is why `_eval_regex` sits at 0% coverage and why 1.8 shipped.

**5.2 Vacuous assertions that would pass on a fully broken feature:**

- `test_public_api.py` asserts imported symbols `is not None` — trivially true for any successful import. It tests the import statement, nothing else.
- `test_from_dsn_with_custom_connection_id` / `test_from_dsn_with_explicit_config`: docstrings claim they verify `connection_id` **propagation**; the assertions only check `isinstance(pipeline, DQTPipeline)`. Propagation could be entirely broken.
- `test_multiple_rules_from_yaml` (integration): comment says "at least one rule should fire," assertion is `len(summaries) == len(rules)` — true whether or not anything is ever detected.

**5.3 A test that silently skips instead of failing.** The same integration test uses a **cwd-relative** `Path("examples/rules/base_rules.yaml")` with `pytest.skip()` if absent. Run pytest from any other directory and it quietly vanishes. Use `Path(__file__).parent`.

**5.4 100% line coverage caught nothing.** `storage.py` reports **100%** coverage and still ships the idempotency bug (2.5) and the connection leak (2.6). Line coverage is measuring that code ran, not that it was correct. `monitoring.py` also reports 100% — for `return metrics`.

**5.5 What is genuinely good:** `tests/unit/sql/test_pipeline.py` and most of `test_pipeline_integration.py` build a real SQLite DB, seed specific defects (duplicate `employee_code`, negative salary, NULL email), run the real engine, and assert on actual issue counts, messages, and severities. That is the right pattern. Extend *that* style; delete the isinstance-and-not-None tests.

**5.6 Missing entirely:** no `conftest.py` / shared fixtures, no property-based tests (a rule engine and an identifier-quoter are ideal Hypothesis targets), no Postgres integration tests (so the second "supported" backend is unverified — and per §1 largely non-functional), no CLI tests, no golden-file test for the HTML report, no benchmark or regression harness.

---

## 6. Documentation

The docs are the strongest part of this project and the source of its biggest risk.

**6.1 `dqt_competitors.md`, `dqt_ecosystem.md`, `DQT-UI-Ecosystem.md`, `dqt-reference-sources.md` are genuinely good.** Clear floor-vs-stretch framing, honest competitor reading, and the UI matrix's "Low–Medium complexity band" is a real design constraint rather than a platitude. Keep these. Two refinements: the ecosystem matrix should visibly distinguish **DQT (target)** from **DQT (today)** in a second row — right now a reader sees `✓✓` across Profiling/Metrics/Reports/Viz for a tool that has none of it. And the competitor doc should name the one differentiator DQT is actually chasing (see §7.4); "match the floor of six tools" is not a strategy.

**6.2 The status markers in `CONVENTIONS-DQT.md` are the core problem.** Eleven `[x] DONE` items are false (§3). The status legend is well-designed — `[ ]` / `[~]` / `[x]` — and then applied to intent rather than verified state. A `[x]` must mean: implemented, tested, tests green in CI. Nothing else.

**Concrete fix:** make status mechanical, not editorial. Add a `scripts/status_check.py` that maps each claim to an executable assertion (a passing test id, a coverage threshold, a working CLI invocation) and regenerates the status column. Run it in CI. A claim that can't be expressed as an assertion isn't a status, it's a wish.

**6.3 The "single source of truth" exists twice, and the copies have drifted.** `CONVENTIONS-DQT.md` and `CONVENTIONS-DQT-data-model.md` are duplicated at repo root and in `docs/`, with confirmed textual divergence — the root copies carry the newer Session Log and Implementation Status table; the `docs/` copies are older and reworded. Delete one pair (keep `docs/`) and, if the project space needs a copy, generate it rather than maintaining it by hand.

**6.4 Docstrings describe intended behavior as though it were current.** This is systemic and it is the mechanism by which the other defects survived review:

| Docstring says | Reality |
| :-- | :-- |
| cleansing: "Operations are **reversible**" | no log persistence, no undo (1.7) |
| `save_run`: "the entire save is skipped" | metrics duplicate (2.5) |
| `ColumnResult.db_type`: `"VARCHAR(255)"` | literal `"ColumnProfile"` (2.1) |
| `from_yaml_config`: "`connection` and `pipeline` sections" | validates whole doc as each model (2.11) |
| `_get_connection`: "opened in read-only mode where the driver supports it" | never opened read-only (1.6) |
| `profiling` module: min/max, patterns, length profiles | null counts only |

Adopt a rule with teeth: **a docstring may only describe behavior covered by a passing test.** Anything else goes under an explicit `.. warning:: Not implemented` or is deleted. Every example in a docstring should be executable — wire up `pytest --doctest-modules` and the class of defect in this table becomes impossible.

**6.5 Missing repo hygiene (all confirmed absent):** `LICENSE` (pyproject declares MIT — legally the license text needs to be there), `.gitignore` (so `dqt_runs.db`, generated reports, and `__pycache__` are all commit candidates), `CHANGELOG.md`, `CONTRIBUTING.md`, `.pre-commit-config.yaml` (would have caught all 146 ruff errors before commit), `src/dqt/py.typed` (**without it, none of this carefully-typed library's annotations reach consumers**), `README.en.md` / `README.fa.md`.

**6.6 On "skills": the repo has no agent guardrails at all.** No agent instruction file at the repo root — no `AGENTS.md`, no per-tool skills directory. The conventions live only in an external documentation space outside the repository, so any coding agent working directly in this repository — which, given the code's uniformly LLM-shaped docstrings, appears to be how much of it was written — starts with zero knowledge of the scope boundaries, the facet model, or the docstring policy. That is very likely a root cause of both the scope drift (legacy pandas package, `performance.py`) and the confident-but-false status claims.

**Concrete fix:** commit an `AGENTS.md` at the repo root containing: the facet list and non-goals; the "docstring must be test-backed" rule; "never mark `[x]` without a green test"; the identifier-quoting and parameter-binding rules from §7.1; and "run `ruff check && mypy && pytest` before claiming completion." Add a `dqt-review` skill that runs the gates and checks status claims against reality. This is cheap and directly prevents the failure mode this review is documenting.

---

## 7. What "best data quality tool ever" actually requires

The competitor doc asks the right question and then answers it with a feature checklist. Matching the floor of six tools produces a worse GX. Here is where I'd actually place the bets.

### 7.1 First, one architectural decision that dissolves most of the P0s

Nearly every P0 — injection (1.3), unquoted identifiers, broken REGEXP (1.8), `rowid` (1.4), `?` vs `%s`, psycopg-vs-psycopg2 — has the same root cause: **there is no dialect layer.** Three ad-hoc connection helpers (`schema_discovery.connect_sql`, `rules._get_connection`, `RunStore._connect`), two Postgres drivers, and two contradictory identifier-quoting policies.

Introduce `dqt/sql/dialects/` with a `Dialect` protocol:

```python
class Dialect(Protocol):
    name: str
    def connect(self, cfg: ConnectionConfig) -> Connection: ...
    def quote_ident(self, name: str) -> str: ...
    def qualify(self, schema: str | None, table: str) -> str: ...
    def placeholder(self, i: int) -> str: ...        # "?" vs "%s"
    def regex_predicate(self, col: str, param: str) -> str: ...
    def row_identity(self, table: DiscoveredTable) -> list[str]: ...  # PK, never rowid
    def set_read_only(self, conn: Connection) -> None: ...
    def sample_clause(self, cfg: SamplingConfig) -> str: ...
    def approx_distinct(self, col: str) -> str: ...
```

Then: `SqliteDialect` registers the `REGEXP` function on connect (1.8 gone); `row_identity` returns the primary key (1.4 gone); every literal goes through `placeholder` as a bound parameter (1.3 gone); `quote_ident` is the only path to an identifier (unquoted-table bug gone); `set_read_only` enforces the flag (1.6 gone). Pick **one** Postgres driver — psycopg 3.

Whether to build this by hand or adopt SQLAlchemy Core is a real trade-off worth deciding deliberately. SQLAlchemy gives you correct quoting, dialect coverage (Postgres, MySQL, SQL Server, Oracle, Snowflake, DuckDB), reflection including foreign keys, and compiled parameter binding — most of §7.2 and all of FK discovery, for one dependency. Hand-rolling keeps the dependency footprint at zero and the SQL fully inspectable, which has real appeal for a DBA tool where "show me the query you ran" matters. Either way, the layer must exist; today's implicit `if dsn.startswith("sqlite")` scattered across four modules is the thing that has to go.

### 7.2 Second, make profiling single-pass

Rewrite `SqlProfiler` to emit **one aggregate query per table** covering every column and every measure — `COUNT(*)`, per-column `COUNT`, `MIN`, `MAX`, `AVG`, `COUNT(DISTINCT)` (or dialect approx), plus length and pattern profiles via `LENGTH()` and character-class `CASE` expressions. That is a 100× reduction in query count on wide tables and simultaneously closes most of the Profiling facet gap (§3). Then wire `SamplingConfig` in so large tables can be profiled at a bounded cost, and add `--timeout` so a profiling run can never wedge a production box.

Add real FK discovery (`PRAGMA foreign_key_list` / `information_schema.table_constraints`) plus orphan-row counts — that's the Diagnostics facet's referential-integrity dimension, currently absent despite being claimed.

### 7.3 Third, make DQT a trustworthy CI gate

This is the highest-leverage feature per unit of work and it is mostly plumbing:

```
dqt check --config dqt.yaml --rules rules/*.yaml \
          --fail-on error --json --output results.json
```

- exit codes: `0` clean / `1` threshold breached / `2` execution error
- `--json` with a stable, versioned schema
- **fail loudly on a missing rule file** (1.9) — a check that didn't run must never report success
- honest per-stage progress on the Rich path, plain machine output on the other

Add a JUnit-XML reporter and DQT plugs into any CI dashboard for almost no extra code.

### 7.4 The differentiator: classification-driven rule suggestion

Every tool in the competitor matrix makes you *write* the expectations. GX gives you a large library; Soda gives you YAML over SQL; both start from a blank file. The DBA's actual first question is not "how do I express this check" but **"what should I even be checking in this 400-table schema?"**

DQT is positioned to answer that, and the pieces are already in the design:

```
dqt suggest-rules --dsn ... --out rules/suggested.yaml
```

1. Profile (single-pass, §7.2) → per-column stats and pattern profiles.
2. Classify semantically from name + pattern + cardinality: `email`, `phone`, `iban`, `national_id`, `postal_code`, `date`, `amount`, `enum`.
3. Emit a **suggested, commented, human-editable** rule file: regex validity for classified columns, ranges from observed distributions, NOT NULL where observed nulls are 0, UNIQUE where cardinality equals row count, FK checks from discovered constraints.
4. The DBA reviews and commits it. Human in the loop, never auto-applied.

Time-to-first-value drops from "write 200 rules" to "run one command, review a diff." That is a genuinely different product, it fits the DBA persona exactly, and it turns the Knowledge and Classification facets from checklist items into the reason someone chooses DQT.

Two hard prerequisites, both currently unmet: **regex must work** (1.8), and profiling must be cheap enough to run against a whole schema (§7.2). Which is why §7.1–7.3 come first.

For Snapp! Market specifically, this is also where Persian-locale knowledge becomes a moat no international tool will build: Iranian national ID checksum validation, Shamsi/Jalali date validity and range checks, IR IBAN (Sheba) checksum, Iranian mobile prefixes, Persian/Arabic character normalization (ی/ي, ک/ك, ZWNJ, Persian vs Arabic-Indic digits) as both a *validity* dimension and a *standardization* primitive. That last one is a real, common, expensive data-quality problem in Persian datasets that no tool in the competitor matrix addresses at all. Ship it as `dqt.knowledge.fa` — pluggable, so the core stays locale-neutral.

### 7.5 Cleansing: split plan from apply, and mean "reversible"

The current design cannot be made safe incrementally. Restructure:

```python
plan = plan_cleansing(conn_cfg, configs)      # read-only; returns every intended change
print(plan.summary())                          # DBA reviews before anything is written
result = apply_cleansing(plan, confirm=True)   # requires read_only=False AND explicit confirm
revert(run_id)                                 # replays the inverse from cleansing_log
```

Non-negotiables: **dry-run is the default**; row identity is the primary key, never `rowid`; the log is written to `cleansing_log` in the RunStore **inside the same transaction as the changes**; NULL-keyed groups are excluded from deduplication unless explicitly opted in; `read_only=True` hard-blocks every write path. Until `revert()` exists and is tested, the word "reversible" does not belong in any docstring.

### 7.6 Monitoring: nearly free, and currently 0%

`RunStore` already holds run history. Add `load_metric_history(dimension, table, column, limit)` and the entire Monitoring facet — trend charts, drift detection (z-score or absolute delta against the trailing *n* runs), new-issue-since-last-run, regression gating in `dqt check` — becomes a small module rather than a project. This is the cheapest large win on the board after §7.3, and it's what the ecosystem matrix rates `✓✓` for Baselinr and Griffin.

### 7.7 Reports and UI: fix truth before adding polish

Before any new chart: correct the severity ordering and the green-critical bug (2.2, 2.3), stop rendering unprofiled tables as 100% (2.4), and add the rule-results section. Then trends (from §7.6), evidence with sample offending values behind a `--no-samples` flag for sensitive columns, and the EN/FA bilingual template.

For the UI, resist the FastAPI-plus-SPA instinct. The `DQT-UI-Ecosystem.md` "Low–Medium complexity" constraint is right, and a DBA's real workflow — run checks, see what's red, drill into evidence, export — is served by a **self-contained single-file HTML report** better than by a server they have to deploy and secure. Invest in making the static report excellent; keep the FastAPI layer as the multi-run history explorer only, and add the auth and CORS it currently lacks before it goes anywhere near a network.

---

## 8. Prioritized roadmap

### Phase 0 — Make the repository honest (1–2 days)

Nothing else should start until this is done, because right now no one can tell what works.

1. Delete `src/data_quality_toolkit/`, `tests/test_visualization_heatmap.py`, `.github/workflows/ci.yml`.
2. Fix `pyproject.toml`: entry point → `dqt.cli:main`; declare runtime deps (`pydantic`, `pyyaml`, `rich`) and extras (`postgres`, `ui`, `bridges`); add `src/dqt/py.typed`.
3. Fix the CLI crash (1.1) and add a smoke test that runs `python -m dqt profile` end-to-end.
4. Fix the 17 failing tests + 1 error: `DiscoveredColumn` kwargs, the `rowid` identity bug, `run_metrics` uniqueness.
5. Get all four gates green: `ruff check --fix`, `ruff format`, resolve 37 mypy errors, coverage ≥ 80% (much of which arrives free with the legacy package gone).
6. Add `.gitignore`, `LICENSE`, `.pre-commit-config.yaml`, `tests/conftest.py`.
7. Rewrite `CONVENTIONS-DQT.md` status markers to reflect §3 of this review. De-duplicate the convention docs.
8. Commit `AGENTS.md` (§6.6).

### Phase 1 — Make it safe (3–5 days)

9. Build the dialect layer (§7.1). Single Postgres driver. All identifiers quoted, all literals bound.
10. Register SQLite `REGEXP` (1.8). Add a test asserting an email rule actually detects a bad address.
11. Enforce `read_only` on every connection (1.6).
12. Restructure cleansing: plan/apply/revert, PK identity, NULL-key guard, log persisted transactionally (§7.5).
13. Fail loudly on missing rule files (1.9). Add `--rules` to the CLI and the `dqt check` subcommand.
14. Exit codes + `--fail-on` + `--json` (§7.3).
15. Fix severity ordering (2.2), green-critical (2.3), `db_type` (2.1), storage connection leak (2.6).

### Phase 2 — Make it useful (1–2 weeks)

16. Single-pass profiler with real column stats; wire `SamplingConfig`; add `--timeout` (§7.2).
17. FK discovery + orphan-row checks.
18. Diagnostics across all claimed dimensions, driven by `metric_thresholds` instead of hardcoded 0.5.
19. Table-level rules, FK rules, conditional rules, and a bound-parameter `sql` expression type.
20. Split measures from scores (2.8). Persist `RuleResult` and `rules_run`; add `run_rules` and `cleansing_log` tables, the mandated composite indexes, and a `schema_version` table.
21. Postgres integration tests in CI (Docker service) — the second backend is currently unverified.
22. Honest per-stage progress; plain CLI alongside the Rich one.

### Phase 3 — Make it the best (ongoing)

23. Monitoring and drift from stored history (§7.6) — cheapest large win.
24. `dqt suggest-rules`: classification → suggested rule file (§7.4).
25. `dqt.knowledge.fa`: national ID, Shamsi dates, Sheba IBAN, Persian normalization (§7.4).
26. Reports: trends, evidence samples, EN/FA.
27. `bridges/` + `MissingnessBridge` for `missingly`.
28. Performance benchmarks with a CI regression gate.
29. UI frontend on the corrected data layer, with auth.

---

## 9. The one thing to change

Not a bug — a practice.

Every defect in §1 shares a cause: **something was written, documented as complete, and never executed.** The tests for the broken rule engine exist. The tests for the broken cleansing engine exist. The CI workflow that would have caught all of it exists. None of it was ever run.

So the highest-value change is mechanical, not architectural: **make "done" mean "green in CI," enforced by a script rather than by intent.** Pre-commit hooks so lint and format can't drift. `pytest --doctest-modules` so a docstring example that doesn't run is a build failure. A status-check script (§6.2) so `[x]` in the conventions is generated from passing assertions, not typed by hand. An `AGENTS.md` so the next contributor — human or model — inherits the rule instead of rediscovering it.

Do that first, and the rest of this roadmap is ordinary engineering. Skip it, and Phase 1 will produce another tree of confident green checkmarks over code that has never run.
