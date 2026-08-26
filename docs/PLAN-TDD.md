# DQT — TDD Implementation Plan (post DQT-03)

> ## Status header — added at landing, 2026-08-26
>
> This plan's body below is landed **unmodified in its analytical content**
> from the session it was written in. It was written against `main` at
> `1b3f917` (183 tests). It is landed here against `main` at `0fc372c`: **185
> tests passing**, `ruff check` / `ruff format --check` (39 files) /
> `mypy --strict` (22 source files) all green, `pytest --cov=src/dqt` at
> **~84.36%** total coverage. The gap between 183 and 185 tests is unit 1
> below, landing.
>
> **Unit 1 (`NEW-H`) is done and merged.** Red commit `9ed3840`
> (`test(cli): cover rule_files forwarding from --config (NEW-H)`), green
> commit `ebc9980` (`fix(cli): forward rule_files from --config into the
> pipeline (NEW-H)`), merged to `main` via PR #5 as merge commit `915bb1c`.
> **Units 2–15 below are not started.** The next unit in sequence is unit 2,
> `DQT-04` — register a `REGEXP` function for SQLite.
>
> **Rank and status of this document itself.** This is a **sequencing plan,
> not a task list and not normative** — `docs/00-START-HERE.md` §1 forbids
> inventing a task list that competes with the roadmap. The authoritative
> task list remains `ROADMAP.md`'s task bodies (`DQT-01`…`DQT-09`, `ALL-01`,
> `DOC-01`…`DOC-04`, `ARC-01`) in the ecosystem engineering-standard skill,
> which outranks this document exactly as it outranks everything in
> `docs/00-START-HERE.md` §1's table below rank 4. The `NEW-x` identifiers
> used throughout this plan (`NEW-A`, `NEW-B`, `NEW-C`, `NEW-H`, `NEW-I`,
> `NEW-J`) are **placeholders governed by `docs/BACKLOG.md` §2**, not
> official task IDs — their appearance here is not an assignment of one.
> Like every status claim in this doc set, the measured figures above rot
> the moment the tree changes again; the source tree wins on any
> disagreement, per `docs/00-START-HERE.md` §1 rank 1.
>
> **Two code citations below were corrected at landing** (checked against
> `0fc372c`; both are noted in place, not silently changed):
> `src/dqt/cli.py::_build_pipeline_config`'s span moved from the plan's
> original 210–241 to **210–246** once unit 1 landed (the fix added five
> lines of docstring/example text plus the one-line `rule_files` forward).
> Unit 2's `rules.py:362` reference was already wrong when this plan was
> first written, not a drift effect — line 362 sits inside `_eval_range`,
> not the regex path — and is corrected below to `rules.py::_eval_regex`
> (lines 379–424), which is where `NOT REGEXP ?` is actually emitted (line
> 417). Every other file/line and section citation in this document
> (`cleansing.py` lines 5 and 21, `pipeline.py` lines 14 and 302,
> `storage.py` line 18, `schema_discovery.py:98`, `rules.py:157`, and all
> `docs/*.md` section references) was re-checked against `0fc372c` and
> found still accurate — the files those citations name have not changed
> since the plan's `1b3f917` baseline.
>
> **The "§ Open questions for the owner" section below has since had some
> of its items settled by the owner.** Rather than rewrite that section,
> each settled item is annotated in place, dated 2026-08-19, without
> deleting the original question text — see the annotations inline within
> that section.

**Baseline this plan is written against:** `main` at `1b3f917`. 183 tests passing.
`ruff check`, `ruff format --check`, `mypy --strict` (22 files), and
`pytest --cov=src/dqt --cov-fail-under=80` all green (measured: 83.21% total
coverage). `DQT-01`, `DQT-02`, `DQT-03` are done and merged.

**Method.** Every claim below was checked by reading the source at that
commit, not by inference from a filename or a docstring. Where I could not
find a ground truth for a proposed test, I say so instead of inventing a
self-referential one (`docs/HONESTY-GATE.md` §0). Precedence follows
`docs/00-START-HERE.md` §1: code > `AGENTS.md` scope > `ROADMAP.md` §2.3/§2.4 >
`ROADMAP.md` task bodies > `ENGINEERING-STANDARDS.md` > rest of `AGENTS.md` >
`HONESTY-GATE.md` > `CONVENTIONS-DQT.md` > `CONVENTIONS-DQT-data-model.md` >
`BACKLOG.md` > everything else.

**Measured, not inherited:** the six "untested" modules named in
`docs/BACKLOG.md` `NEW-C` actually run at 66–100% *line* coverage today
(`profiling.py` 100%, `diagnostics.py` 100%, `monitoring.py` 100%,
`reports.py` 92%, `metrics.py` 88%, `schema_discovery.py` 66%) via
`tests/integration/test_pipeline_integration.py`, which drives the whole
pipeline against a real SQLite file. Every line in them executes. **None of
that coverage comes from an assertion that checks a hand-computed value** —
the integration test asserts shape (`result.status == "success"`, issue
counts are non-negative, a report file exists), not correctness of any one
number. This is the literal shape of the "coverage gate lies" problem named
in `GUIDE-dqt-architect.md` §4: high coverage, zero grounded claims. Treat
`NEW-C` as "zero *grounded* unit tests," not "zero executed lines," and see
§ Ordering rationale for what follows from that distinction.

---

## Unit sequence

### 1. `NEW-H` — CLI silently drops `rule_files` from `--config`

**Depends on:** nothing. **Blocked on Q1/Q2/Q4:** no.

**Why here.** Cheapest, highest-damage, most isolated fix available.
`src/dqt/cli.py::_build_pipeline_config` (lines 210–246; the plan's original
text cited 210–241, before unit 1's own fix grew the function by five lines
— corrected at landing) builds a
`DQPipelineConfig` from `file_cfg` but never reads `file_cfg.get("rule_files")`
— every other config-file key (`exclude_schemas`, `include_tables`, …) is
forwarded, `rule_files` is not. The result: `dqt profile --config x.yaml` where
`x.yaml` sets `rule_files:` runs the full pipeline and reports zero rule
issues, silently. Measured directly: the programmatic path
(`DQPipelineConfig(rule_files=[...])` constructed in Python) finds 4 issues
against `examples/rules/advanced_rules.yaml` fixtures; the CLI path against
the same file finds 1 (diagnostics only, no rule issues). This is a
false-negative data-quality tool — worse than DQT-04's dead `regex` rule,
because it silently disables *all* rule types, not one, and produces no error.
Touches only `cli.py`; nothing else in this sequence depends on it, so it can
land before any of the bigger structural work without being invalidated by it.

**Tests first.**
- `tests/unit/test_cli.py::test_build_pipeline_config_forwards_rule_files` —
  call `_build_pipeline_config(args, {"rule_files": ["a.yaml", "b.yaml"]})`
  and assert `cfg.rule_files == ["a.yaml", "b.yaml"]`. Ground truth: shape 3
  (seeded fixture, hand-computed expected value) — the expected list is the
  literal input, not a value the function produced.
- `tests/unit/test_cli.py::test_profile_cli_applies_rule_files_from_config` —
  build a throwaway SQLite file with one row that violates a `not_null` rule
  in a rule file referenced from a `--config` JSON file passed to
  `_cmd_profile`; assert the resulting `PipelineResult.issues` contains a
  `rule_name="…"` entry. Ground truth: shape 3 — the fixture is constructed by
  the test (one row, one column set to `NULL`), and "exactly one `not_null`
  failure" is a fact about the fixture a human wrote, independent of the code
  under test. This is also the fail→pass proof required by
  `HONESTY-GATE.md` §2: run it first against unfixed `cli.py`, paste the
  0-issues failure, then against the fix, paste the 1-issue pass.

**Implementation.** One line in `_build_pipeline_config`:
`rule_files=file_cfg.get("rule_files", [])` merged with any CLI-level
rule-file flag if one exists (none does today — note in the PR whether to add
one; out of scope for this unit if not requested).

**Acceptance criteria (derived — no roadmap task covers this defect).** A
config file with `rule_files` produces the same issue set through the CLI as
through direct `DQPipelineConfig` construction, for a fixed fixture. Existing
183 tests still pass.

**Docs to update in the same PR.** `docs/BACKLOG.md` §2 — add this as a
numbered defect once the owner assigns it a real ID; until then keep the
`NEW-H` placeholder in the PR description, not in a merged doc claiming it is
official.

**Size.** 2–3 hours, one PR.

---

### 2. `DQT-04` — Make `regex` rules work on SQLite

**Depends on:** `DQT-02` (merged). **Blocked on Q1/Q2/Q4:** no.

**Why here.** Same family as unit 1 — a declared rule type that silently
lies about validating data. `rules.py::_eval_regex` (lines 379–424; the
plan's original text cited `rules.py:362`, which is inside `_eval_range`,
not the regex path — corrected at landing) emits
`NOT REGEXP ?` (line 417) and SQLite has no built-in `REGEXP`; every `regex`
rule currently produces a
permanent false `error` on every target, including the shipped
`examples/rules/advanced_rules.yaml::valid_email_format` rule. Sequencing it
second (not first) only because unit 1 was strictly cheaper and blocks
nothing; there is no real dependency between them.

**Tests first.**
- `tests/unit/sql/test_rules.py::test_regexp_function_registered_on_sqlite_connection`
  — open a connection via `_get_connection`, execute
  `SELECT 1 WHERE 'abc' REGEXP '^a'`, assert it returns a row instead of
  raising `OperationalError: no such function: REGEXP`. Ground truth: shape 4
  (property/invariant) — a `REGEXP` function existing is a binary fact
  independent of DQT's own regex-rule logic.
- `tests/unit/sql/test_rules.py::test_email_rule_flags_exactly_invalid_addresses`
  — seed a table with a **hand-enumerated** list, e.g.
  `["a@b.com", "not-an-email", "x@y", "", None]`, apply
  `examples/rules/advanced_rules.yaml`'s `valid_email_format` pattern, and
  assert the failing set is exactly `{"not-an-email", "x@y"}` (empty string
  and `NULL` are policy calls — state explicitly in the test which of
  "invalid" vs "not applicable" each represents, since the current `NOT NULL`
  guard in `_eval_regex`-adjacent code, if any, determines whether `NULL`
  rows are silently excluded). Ground truth: shape 3 — a human enumerated
  which of the 5 seeded values are valid emails by reading the pattern, not
  by running the code.
- `tests/unit/sql/test_rules.py::test_malformed_pattern_is_a_config_error_not_a_data_issue`
  — an invalid regex (e.g. unbalanced `(`) must not be reported as a `DQIssue`
  with false "all rows failed"; it must raise a typed, catchable error at
  rule-evaluation time (a `ValueError` today; `RuleEvaluationError` once
  `DQT-09` lands — file the second half as a follow-up note in that unit
  rather than doing exception-hierarchy work here). Ground truth: shape 2 —
  reproduce the current defect (a malformed pattern producing a false
  "all rows invalid" `error` issue) against unfixed code before writing the
  fix, per the roadmap's locked instruction to treat this as a configuration
  error, not a rule failure.
- Bounded-pattern-cache / pattern-size-limit test: `functools.lru_cache`
  (or equivalent) plus a guard rejecting patterns above a size limit — a
  property test asserting the cache does not grow unboundedly under repeated
  calls with distinct large patterns (shape 4).

**Implementation.** Register a Python `REGEXP` callable via
`conn.create_function("REGEXP", 2, ...)` on every SQLite connection opened by
`_get_connection` (the single connection-opening function this task must not
duplicate — see unit 9, `DQT-08`, for the parallel PostgreSQL-side
consolidation). Bound the compiled-pattern cache; reject patterns over a
configurable size limit before compiling.

**Acceptance criteria (from roadmap `DQT-04`).** A test asserts
`valid_email_format` flags exactly the invalid addresses in a seeded fixture
— neither zero rows nor all rows. No rule type exists in the schema that
cannot execute on a supported backend.

**Docs to update.** `docs/00-START-HERE.md` §3.3 item 3 (regex dead) and §3.4;
`docs/CONVENTIONS-DQT.md` §5 status register row for "Rules engine — regex";
`docs/BACKLOG.md` §1 remaining-tasks list (drop `DQT-04`).

**Size.** 1 day, one PR.

---

### 3. `DOC-01` — Land the documentation gate in DQT

**Depends on:** nothing. **Blocked on Q1/Q2/Q4:** no.

**Why here, this early.** `ROADMAP.md` §4.5 is explicit: "Run these early. A
standard introduced after the work is a wish; introduced before, it is a
gate." Landing it now — before the larger structural work in units 4–6 —
means every subsequent unit in this plan is held to "no new docstring
violation," which is the actual point of doing this under a TDD mandate:
the gate should exist before the rewrites, not be reconciled against them
afterward. The tradeoff (accepted): the baseline captured now will shrink
and shift as `NEW-A`/`DQT-05`/`DQT-09` rewrite `cleansing.py` and
`common/models.py` docstrings. That is fine — ratchet mode only forbids
*growth*; removing baselined entries because the code got better is always
welcome and does not require touching every consumer atomically.

**Tests first.** None to write — `tools/doc_audit.py` is a provided,
self-passing, already-doctested script per the roadmap (`DOC-01` body); it is
copied, not authored. The verification is running it and pasting output, and
proving the gate bites (add a public function with no docstring, show
`exit=1`, remove it, show `exit=0`) — this is the honesty-gate's own
prescribed proof, not a unit test in `tests/`.

**Implementation.** Copy `tools/doc_audit.py` from the ecosystem skill's
reference tree (it is absent from this repo today — the prompt that set up
this plan flags this explicitly) into `data-quality-toolkit/tools/`. Run
`python tools/doc_audit.py --root . --path src/dqt --style google
--require-example --write-baseline .doc_audit_baseline.json`. Wire a required
CI job running it against the committed baseline.

**Acceptance criteria (from roadmap `DOC-01`).** Gate wired into CI. Baseline
committed. Measured roadmap count for DQT style=google is 29 violations as of
2026-08-12 — **re-measure at PR time**, since `DQT-02`/`DQT-03` landed
docstrings after that count was taken; report the actual number, do not copy
29 forward uncritically. A deliberately planted violation fails the gate,
shown in the PR.

**Docs to update.** None beyond the new `.doc_audit_baseline.json` and a CI
workflow file; no conventions doc makes a claim this contradicts.

**Size.** 4–6 hours (mostly re-measuring the baseline and wiring CI; the tool
itself is not written here).

---

### 4. `NEW-C` (slice 1) — Ground `profiling.py` and `diagnostics.py`

**Depends on:** nothing structurally; sequenced before `NEW-A`/`DQT-05`
because both later units build on trusting what profiling/diagnostics report.
**Blocked on Q1/Q2/Q4:** no.

**Why here.** `docs/BACKLOG.md` `NEW-C` itself names this order: "diagnostics
and profiling first — they produce the issues everything else consumes."
`DQT-05`'s revert-round-trip test (unit 6) needs to trust that a checksum
taken "before mutation" reflects a real, understood table state; if
profiling's row/null counts were themselves unverified, a passing revert test
would only prove self-consistency, not correctness. This is also the first
opportunity to retire the "100%/100% coverage, zero grounded assertions"
problem measured in this plan's preamble.

**Tests first.**
- `tests/unit/sql/test_profiling.py::test_row_and_null_counts_match_hand_seeded_fixture`
  — build a SQLite table with an explicit literal INSERT list (e.g. 5 rows,
  2 with `NULL` in column `x`), and assert
  `SqlProfiler.profile_tables(...)[0].row_count == 5` and
  `.columns[0].null_count == 2`. Ground truth: shape 3 — the counts are
  written in the test as a comment deriving them by hand from the literal
  INSERT statements, not computed by calling the profiler and asserting
  equality with itself.
- `tests/unit/sql/test_profiling.py::test_completeness_score_formula` — for
  the same fixture, assert
  `build_metrics(...)` yields `score == 1.0 - 2/5 == 0.6` for that column.
  Ground truth: shape 3 (closed-form arithmetic on the seeded fixture).
- `tests/unit/sql/test_profiling.py::test_zero_row_table_is_not_a_division_by_zero`
  — an empty table must report `completeness == 1.0`, not raise or report
  `NaN`. Ground truth: shape 4 (boundary-condition invariant: a measure of
  "how complete is nothing" is defined to be vacuously complete, matching the
  code's explicit `if row_count > 0` guard — this test exists to lock that
  choice, not discover it).
- `tests/unit/sql/test_diagnostics.py::test_severity_threshold_at_50_percent_nulls`
  — three fixtures: 10% nulls (expect `warning`), exactly 50% nulls (expect
  `error` — the code uses `>=`), 49% (expect `warning`). Ground truth: shape 3
  — the boundary is read directly out of `diagnostics.py`'s `ratio >= 0.5`
  and the fixture null-counts are chosen by hand to land exactly on it, which
  is legitimate: this is testing that the *documented* threshold behavior
  holds, not inventing an independent oracle for an arbitrary threshold DQT
  itself defines. Where a test cannot get an *external* oracle because the
  quantity being tested is a threshold DQT itself invented (not a physical or
  statistical quantity), a hand-derived boundary case is the correct
  substitute — flag this reasoning explicitly in the test docstring so a
  future reader does not mistake it for a self-referential test.
- `tests/unit/sql/test_diagnostics.py::test_no_issue_when_no_nulls` — a
  zero-null column produces zero issues. Ground truth: shape 4 (conservation:
  no defect present implies no defect reported).

**Implementation.** No behavior change expected — these are characterization
tests for code that is already correct as far as this reading found. If a
test fails against current code, that is a real defect to fix as part of
this unit (report it, do not soften the test).

**Acceptance criteria (derived — no roadmap ID covers unit-testing debt
directly; this is `BACKLOG.md` `NEW-C`'s first slice).** Both modules move
from "0 dedicated unit tests, incidentally covered" to having every public
function backed by a hand-computed-fixture test. Existing integration test
still passes unchanged (it is not being replaced, just no longer the *only*
evidence).

**Docs to update.** `docs/00-START-HERE.md` §3.2 (remove profiling/
diagnostics from the "no tests" list); `docs/CONVENTIONS-DQT.md` §5 status
register rows for Profiling and Diagnostics.

**Size.** 1–1.5 days, one PR.

---

### 5. `NEW-A` — Split `dimension` from `metric_name`; add storage `CHECK`s

**Depends on:** nothing technically; sequenced immediately before `DQT-05`
so both land in the **same** storage-schema recreation (see rationale below).
**Blocked on Q1/Q2/Q4:** no — this is a data-shape fix, not a safety-model
question.

**Why here.** `metrics.py` and `profiling.py` write metric names
(`table_count`, `average_completeness`, `row_count`) into the same `dimension`
field that `diagnostics.py`/`rules.py` use for real dimensions
(`completeness`, `validity`, …). `CONVENTIONS-DQT.md` §0.1's closed six-value
vocabulary cannot be enforced while this holds, and any later feature that
groups or scores by `dimension` (a scorecard, a trend, `monitor()`'s eventual
real implementation) would be silently wrong. `docs/BACKLOG.md` explicitly
flags the schema interaction: `cleansing_log` (from `DQT-05`, unit 6) lands
in the same DDL file as the new `CHECK` constraints this unit adds, and the
store is a local SQLite artifact meant to be **recreated, not migrated** —
doing both schema changes in one PR-pair avoids two separate breaking
recreates for anyone with an existing `dqt_runs.db`.

**Tests first.**
- `tests/unit/common/test_models.py::test_dq_dimension_is_a_closed_literal` —
  assert `DQDimension` (new `Literal[...]` alias, or a `StrEnum`) contains
  exactly the six values in `CONVENTIONS-DQT.md` §0.1 and no others. Ground
  truth: shape 3 — the six-value set is copied verbatim from the convention
  doc, not derived from any code path.
- `tests/unit/common/test_models.py::test_dq_metric_dimension_is_optional_metric_name_is_required_for_aggregates`
  — construct a `DQMetric` for `table_count` with `dimension=None,
  metric_name="table_count"` and one for `completeness` with
  `dimension="completeness", metric_name=None` (or `"completeness"` — pick
  one convention and assert it, see § Specification gaps below for why this
  needs an explicit decision first). Ground truth: shape 3 — this is a type-
  shape assertion, not a numeric claim; "does this construct without
  raising, and are the two fields what I put in" is checkable without an
  oracle beyond the dataclass/model definition itself.
- `tests/unit/common/test_storage.py::test_run_metrics_check_constraint_rejects_bad_dimension`
  — attempt to `INSERT` a row into `run_metrics` with `dimension='banana'`
  directly via `sqlite3`, bypassing `RunStore.save_run`, and assert
  `sqlite3.IntegrityError`. Ground truth: shape 2/4 — this is an independent
  reproduction of the defect (today, the same insert succeeds silently; run
  it against unfixed `storage.py`, paste the row that should not exist,
  then show the `IntegrityError` after the fix) doubling as a conservation
  invariant (the schema itself, not application code, is the enforcement
  point).
- Same pattern for `run_issues.severity`, `run_issues.dimension`,
  `runs.status` `CHECK` constraints — one test each, same shape.
- `tests/unit/sql/test_metrics.py` and `tests/unit/sql/test_profiling.py`
  (extending unit 4's fixtures) — after the split, assert
  `compute_run_metrics(...)` sets `dimension=None` (or the agreed sentinel)
  and `metric_name="table_count"` on the run-level metrics, per the seeded
  fixture from unit 4.

**Implementation.** Add `DQDimension` (`Literal["completeness", "validity",
"uniqueness", "consistency", "referential_integrity", "timeliness"]`) to
`common/models.py`; add `metric_name: str | None` to `DQMetric`; make
`DQMetric.dimension: DQDimension | None`; update `metrics.py` and
`profiling.py`'s run/table-level metric construction to set `metric_name`
instead of overloading `dimension`; add `CHECK` constraints to
`storage.py::init_schema` DDL for `run_metrics.dimension`,
`run_issues.dimension`, `run_issues.severity`, `runs.status`; add
`run_metrics.metric_name TEXT` column.

**Acceptance criteria (derived from `BACKLOG.md` `NEW-A`, no roadmap ID
exists for this — needs one from the owner).** `DQMetric.dimension` holds
only real dimensions or `None`; every DQ-dimension value written anywhere in
the codebase is a member of the closed set; direct SQL against `run_metrics`/
`run_issues`/`runs` cannot insert an out-of-set value. All four `CHECK`
constraints proven by a reproduced-then-fixed test.

**Docs to update in the same PR.** `docs/CONVENTIONS-DQT.md` §0.1 (remove the
"⚠ not honoured" warning), §5 status register row "Dimension vocabulary";
`docs/CONVENTIONS-DQT-data-model.md` §2.2 (`DQMetric` shape — add
`metric_name`), §4.1–4.3 (add the `CHECK` DDL, document `run_metrics.
metric_name`); `docs/00-START-HERE.md` §3.3 item 6; `docs/BACKLOG.md`
`NEW-A` entry (mark resolved, keep for history).

**Size.** 1.5–2 days, one PR (or two: model/emitter change, then storage DDL
— see the note in unit 6 about sharing the migration).

---

### 6. `DQT-05` — Persist cleansing logs and implement `revert()`

**Depends on:** `DQT-03` (merged). **Sequenced immediately after `NEW-A`** to
share one storage-schema recreation. **Blocked on Q1/Q2/Q4:** partially — see
below.

**Why here.** This is the confirmed false claim in the codebase today:
`cleansing.py`'s module docstring calls its primitives "Reversible, auditable"
and lists "Operations are reversible" as design invariant #2, but
`grep -c cleansing src/dqt/common/storage.py` is 0, there is no `revert()`
anywhere, and `CleansingLog` objects exist only in memory — drop the return
value of `apply_cleansing()` and the before-values needed to undo anything
are gone permanently. `CONVENTIONS-DQT.md` §1 S4 is explicit that a log a
human could use to reconstruct a change by hand is an **audit trail**, not
reversibility, and the two must not be conflated — which is exactly what the
current docstring does. Q3 (may `DELETE` be used as a cleansing primitive) is
now **decided: yes** — deduplication keeps `DELETE` plus its `not_null_guard`
— so this unit's `revert()` must handle reinserting deleted rows, which is
tractable today because `_deduplicate()` already captures the **full row**
(via `_fetch_all_dicts(..., "SELECT * FROM ...")`) as `CleansingLog.
before_value` before deleting — the data needed for a real, automated revert
already exists; it just is not persisted or replayed yet.

**Not blocked by Q1 or Q2.** Q1 (should `cleanse` stay on `run()`'s path) is
about whether `DQTPipeline.run()` invokes cleansing automatically; this unit
only makes `apply_cleansing()`/`revert()` correct and persistent as directly
callable functions, and does not change what `run()` calls. Q2 (`--dry-run`
vs. a stricter `plan`/`apply` with `plan_id`) is about the *calling
convention*; implement persistence at the level `apply_cleansing()` already
exists at (keyed by `run_id`, which every call already carries) so it survives
either resolution — do not invent a `plan_id` concept preemptively, since
that is the owner's call.

**Tests first.**
- `tests/integration/test_cleansing_revert.py::test_standardize_round_trip`
  — seed a table, run `apply_cleansing(..., dry_run=False)` with a
  `standardize` config, checksum the affected rows (`sha256` over their
  serialized values, not a row count — `HONESTY-GATE.md`'s explicit
  instruction: "row counts can match while values changed"), call
  `revert(run_id)`, checksum again, assert byte-identical to the pre-mutation
  checksum. Ground truth: shape 1 (checksum comparison) — this is literally
  the pattern `DQT-03` already used and proved out.
- `tests/integration/test_cleansing_revert.py::test_deduplicate_delete_round_trip`
  — same pattern for the `deduplicate` operation: seed duplicate rows,
  delete via cleansing, revert, assert the table (including the deleted
  rows' full original column values) is byte-identical to the pre-mutation
  state. This is the test that proves the Q3-decided behavior ("`DELETE`
  stays, and must be revertible") actually holds, not just that it is
  policy.
- `tests/unit/sql/test_cleansing.py::test_log_persisted_before_mutation_commits`
  — the mandated kill-the-process proof from `CONVENTIONS-DQT.md` §1 S4 and
  `DQT-05`'s own acceptance criteria: begin a cleansing operation, simulate a
  crash between the log INSERT and the mutating statement's commit (e.g. by
  wrapping the mutation in a context that raises after the log write but
  before commit, or by structuring the two statements in the same
  transaction and asserting via `sqlite3`'s isolation semantics that an
  uncommitted mutation leaves no committed row change), and assert nothing
  committed. Ground truth: shape 2/4 — an independent reproduction that the
  *pre-fix* code (log built in memory, mutation executed and committed
  separately) can lose the log entirely on a crash between the two, which is
  today's actual behavior; the fix's proof is that the same crash simulation
  now leaves either both durable or neither.
- `tests/unit/sql/test_cleansing.py::test_revert_refuses_on_post_hoc_drift`
  — mutate a row via cleansing, then mutate the *same* row again through a
  second, unrelated write, then call `revert(run_id)` for the first
  operation; assert it raises rather than clobbering the second write.
  Ground truth: shape 4 (a revert must not silently destroy a later, unlogged
  change — checksum the row before the second write, compare against the
  row's checksum at revert time, and the mismatch is the trigger).

**Implementation.** Add `cleansing_log` table to `storage.py::init_schema`
(same PR/migration as `NEW-A`'s `CHECK` constraints): `run_id` **nullable**
with `ON DELETE SET NULL` per `CONVENTIONS-DQT-data-model.md` §4.4's explicit
design note (an audit record must outlive the run's retention window), plus
table, column, row key, before/after value, operation, timestamp. Write the
log row and the mutating statement in the same transaction inside
`apply_cleansing`. Implement `revert(run_id: str) -> CleansingResult`-shaped
return, replaying inverse operations in reverse chronological order, with a
pre-revert checksum comparison per affected row to detect drift.

**Acceptance criteria (from roadmap `DQT-05`).** Round-trip test passes.
Killing the process between mutation and log write leaves no committed
mutation (simulated, shown). `revert` refuses on post-hoc drift, with a test.

**Docs to update in the same PR.** `docs/CONVENTIONS-DQT.md` §1 S4 (the
claim becomes true — remove hedging), S5's ⚖ `DELETE` marker changes from
"undecided" to "decided: permitted, and now revertible" (the owner's Q3
decision, recorded); `docs/CONVENTIONS-DQT-data-model.md` §4.4 (the
`cleansing_log` table moves from "implied, not built" to built — document the
final DDL); `sql/cleansing.py`'s own module docstring — this is the one
place the "reversible" claim can finally be written truthfully, once the
test proves it; `docs/00-START-HERE.md` §3.3 item 4; `docs/BACKLOG.md` §1.

**Size.** 2–3 days, likely two PRs (storage DDL + `revert()` logic, then the
crash-simulation and drift tests if they surface a design gap the first pass
missed).

---

### 7. `NEW-B` — `run()` can report failure; real `stage_errors`

**Depends on:** nothing technically; sequenced after `DQT-05` so cleansing
errors are one of the failure sources this unit can capture and test.
**Blocked on Q1/Q2/Q4:** touches Q1's territory but does not need it
resolved — see below.

**Why here.** `run()` hardcodes `result.status = "success"` and wraps no
stage in `try/except`; a failing stage raises before anything is persisted,
so `runs.status` can only ever hold `"success"`. This is a silent-failure
defect in the `ENGINEERING-STANDARDS.md` §1.6 sense ("a function that cannot
do its job raises... it does not return `None`/`0`/empty to mean failure" —
here it's worse, it returns a *positive* signal on failure). It must land
before `DQT-06` (exit-code contract, unit 8): an exit code derived from a
status that is always `"success"` is not a contract, it is theater — the
roadmap's own text for `NEW-B` says as much.

**Not blocked by Q1.** Q1 asks whether `cleanse` should be *invoked* by
`run()` at all. This unit only wraps whichever stages `run()` currently calls
(discovery, profiling, diagnostics, rules, cleanse-stub, metrics, monitor) in
per-stage error capture — it does not change which stages are called, so it
is orthogonal to Q1's resolution either way.

**Tests first.**
- `tests/unit/sql/test_pipeline.py::test_run_reports_failed_when_discovery_raises`
  — point `DQTPipeline` at a DSN that does not exist (or an
  intentionally-broken `ConnectionConfig`), call `run()`, assert
  `result.status == "failed"` and `result.stage_errors` (new field) contains
  an entry naming the `discover_schema` stage. Ground truth: shape 2 — this
  reproduces the actual current defect first (unfixed code either raises an
  uncaught exception out of `run()`, or — check both possibilities in the
  investigation before writing the test — silently reports "success"; paste
  which one it does before writing the fix).
- `tests/unit/sql/test_pipeline.py::test_run_reports_partial_when_one_of_several_rule_files_is_missing`
  — a config with two rule files, one missing; today `apply_rules` silently
  suppresses `FileNotFoundError` per-file (see `pipeline.py`'s
  `contextlib.suppress(FileNotFoundError)`), which is itself worth
  re-examining under this unit — decide and test whether a missing rule file
  should downgrade status to `"partial"` or remain silent, and state which,
  with a test either way.
  > **Settled 2026-08-19 (annotated at landing):** a missing rule file named
  > in a config yields run status **`"partial"`**, not `"failed"` and not a
  > pre-run abort. This unit (`NEW-B`) must carry the reason in
  > `stage_errors`. This is explicitly **not** part of `NEW-H` (unit 1,
  > already merged) — `NEW-H` only fixed `rule_files` forwarding, it did not
  > touch what happens when a forwarded file is missing.
  Ground truth: shape 3 (seeded fixture: exactly one
  of two named files exists on disk).
- `tests/unit/sql/test_pipeline.py::test_run_reports_success_only_when_every_stage_succeeds`
  — the mirror case: a fully clean run against a well-formed fixture reports
  `"success"` with an empty `stage_errors`. Ground truth: shape 4 (identity/
  conservation — no failure injected, none reported).

**Implementation.** Add `stage_errors: dict[str, str]` (or a small dataclass
list) to `PipelineResult`. Wrap each stage call in `run()` in a narrow
`try/except` that captures a **typed** exception (not bare `except
Exception:` swallowing control flow — `ENGINEERING-STANDARDS.md` §1.6),
records it, and derives `status` from whether any stage recorded an error
(`"failed"` if a required stage errored, `"partial"` if a non-fatal one did,
`"success"` otherwise — the fatal/non-fatal split is a design decision to
make explicit in the PR, not infer silently).

**Acceptance criteria (derived from `BACKLOG.md` `NEW-B`, no roadmap ID
exists — needs one).** A test exists for each of the three `RunStatus`
values actually being reachable. `runs.status` in `RunStore` can hold values
other than `"success"` after a real run (shown, not asserted from reading the
code).

**Docs to update.** `docs/CONVENTIONS-DQT.md` §0.3 (remove the "⚠ only
success is reachable" warning); `docs/CONVENTIONS-DQT-data-model.md` §2.1
(add `stage_errors` to `PipelineResult`'s shape, and revisit the note about
`runs.ended_at NOT NULL` needing reconsideration once partial-result
persistence exists — decide in this unit whether partial results persist at
all, or whether "failed" simply means "not persisted," and say which);
`docs/00-START-HERE.md` §3.3 item 7; `docs/BACKLOG.md` `NEW-B` entry.

**Size.** 1–1.5 days, one PR.

---

### 8. `DQT-06` — Exit-code contract for CI gating

**Depends on:** `DQT-04` (unit 2, done) and, as a practical prerequisite this
plan adds, `NEW-B` (unit 7) — a status that is always `"success"` cannot
drive a meaningful exit code, so scheduling this before `NEW-B` would produce
a contract that only ever exercises one branch. **Blocked on Q1/Q2/Q4:** no.

**Why here.** Directly enables the "DQ gate in CI" use case that is
currently impossible (`DQT-critical-review.md` §1.10, restated in the
roadmap). Natural next step once `run()` can actually distinguish outcomes.

**Tests first.**
- `tests/unit/test_cli.py::test_exit_code_0_on_clean_run` — a fixture DB with
  no rule violations and a rules file with only rules it satisfies; assert
  `_cmd_profile` (or the `main()` wrapper) returns `0`. Ground truth: shape 3
  — the fixture is hand-built to satisfy every configured rule.
- `tests/unit/test_cli.py::test_exit_code_1_on_error_severity_failure` —
  fixture with a `not_null` violation at `severity: error`; assert exit `1`.
- `tests/unit/test_cli.py::test_exit_code_2_on_warning_only_failure` —
  fixture with only a `severity: warning` violation and `--fail-on warning`;
  assert exit `2`. Also assert exit `0` for the same fixture under the
  default `--fail-on error` (warnings alone should not fail a default run —
  confirm this reading of the roadmap's `--fail-on {error,warning,none}`
  spec against the owner's intent in the PR description, since the roadmap
  text is terse here).
- `tests/unit/test_cli.py::test_exit_code_3_on_connection_error` — a DSN
  pointing at a nonexistent SQLite file with `read_only=True` (per `DQT-03`'s
  `mode=ro` behavior, this now raises rather than auto-creating); assert
  exit `3`, not an uncaught traceback.
- `tests/unit/test_cli.py::test_exit_code_4_on_internal_error_never_0` — force
  an unexpected exception (e.g. monkeypatch a stage to raise `RuntimeError`)
  and assert the process exits `4`, explicitly proving the roadmap's "never
  let an unexpected exception exit 0" requirement — this is the one exit-code
  test that is itself a regression guard, so state in the test docstring
  that it must fail if `main()`'s top-level exception handling is ever
  loosened to swallow-and-continue.

All five: ground truth shape 3 (each fixture's rule outcome is enumerated by
hand against the fixture's literal contents, matching `HONESTY-GATE.md`'s
"rule engine change" row exactly).

**Implementation.** Define the five exit codes in `cli.py` (or a new
`dqt.cli._exit_codes` module if `DQT-09`'s exception hierarchy, unit 12,
should map onto them — decide ordering of that mapping there, not here).
Add `--fail-on {error,warning,none}`. Ensure `main()`'s top-level exception
handling never falls through to a bare `0`.

**Acceptance criteria (from roadmap `DQT-06`).** A test matrix asserts each
code. Exit codes documented in `README.md`.

**Docs to update.** `README.md` (new exit-code section); `docs/00-START-HERE.md`
§3.3 item 14; `docs/BACKLOG.md` §1.

**Size.** 4–6 hours, one PR.

---

### 9. `DQT-08` — Single connection authority; resolve the driver split (also fixes the undocumented `schema_discovery.connect_sql` bypass)

**Depends on:** `DQT-03` (merged). **Blocked on Q4:** partially — see below.

**Why here.** Two separate, previously-undocumented defects converge on the
same fix:

1. **The roadmap's own `DQT-08`:** `schema_discovery.py::connect_sql()` uses
   `psycopg` (v3); `rules.py::_get_connection()` uses `psycopg2` (v2). Two
   drivers, two different read-only APIs, one codebase — a live
   `ENGINEERING-STANDARDS.md` §1.2 single-authority violation, confirmed by
   reading both files (`schema_discovery.py:98`, `rules.py:157`).
2. **A defect this plan surfaces that has no ID yet:**
   `schema_discovery.connect_sql()` is a *second connection-opening path*
   that bypasses `DQT-03`'s read-only enforcement entirely — it calls
   `sqlite3.connect(db_path)` directly (no `mode=ro`) and `psycopg.connect(dsn)`
   directly (no `SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY`),
   regardless of `connection_config.read_only`. Confirmed by reading the
   function body: it does not even receive or check the `read_only` field.
   No live safety impact today — `discover_schema()` and `SqlProfiler` only
   ever `SELECT` through this path — but it means `DQT-03`'s enforcement is
   not actually connection-layer-universal, only "everywhere `rules.py`'s
   helper happens to be used." Placeholder `NEW-I` until the owner assigns
   an ID; do not schedule it as a separate unit from `DQT-08`, since fixing
   one without the other reintroduces the single-authority violation from
   the opposite direction (a second, now-correct, connection function still
   competing with the first).

**Not blocked by Q4**, but shaped by it: Q4 asks whether DQT should move to
two separately-credentialed connections (read/write). `DQT-08`'s
consolidation to **one** connection-opening function
(`dqt.sql._connect.get_connection`) is compatible with either resolution —
if Q4 later resolves toward two connections, `_connect.py` gains a second,
sibling entry point (`get_write_connection`) rather than being redesigned.
State this compatibility explicitly in the PR so a future reader does not
read "one connection function" as a de facto vote against the two-connection
proposal.

**Tests first.**
- `tests/unit/sql/test_connect.py::test_read_only_sqlite_via_schema_discovery_path`
  — the `NEW-I` half: today, calling `discover_schema` (or `connect_sql`
  directly) with `read_only=True` against a real file and attempting a write
  through the returned connection **succeeds** (the bug). Ground truth:
  shape 2 — reproduce this first (an `UPDATE` through the connection returned
  by `connect_sql(cfg_with_read_only_true)` commits), paste the pre-fix
  success, then show the fixed code raises `sqlite3.OperationalError` the
  same way `rules.py`'s connection already does. This is a genuine
  fail→pass proof, not a new-feature test, even though the roadmap files it
  under `DQT-08` rather than as a named security defect.
- `tests/unit/test_public_api.py`-style test:
  `test_only_connect_module_imports_a_db_driver` — grep-based test (AST or
  plain `import` scan) asserting no module under `src/dqt/` other than the
  new `sql/_connect.py` (and `common/storage.py`, explicitly excluded per
  the roadmap's own note that `RunStore` is DQT's internal DB and stays
  outside this consolidation) imports `sqlite3`, `psycopg`, or `psycopg2`.
  Ground truth: shape 4 (a structural invariant — single authority by
  construction, checkable by static inspection, not by running the drivers).
- `tests/unit/sql/test_connect.py::test_one_postgres_driver_in_pyproject` —
  parse `pyproject.toml`'s `[project.optional-dependencies].postgres` list
  and assert exactly one of `psycopg[binary]` / `psycopg2-binary` is present.
  Ground truth: shape 4 (structural).
- **`NEW-C` slice for `schema_discovery.py`, folded into this unit rather
  than done separately:** `tests/unit/sql/test_schema_discovery.py::
  test_discovers_tables_and_columns_from_hand_built_sqlite_db` — create a
  SQLite file with two explicitly-DDL'd tables and known column types/
  nullability, assert `discover_schema` returns exactly those tables/columns
  with exactly those `nullable` flags. Ground truth: shape 3 (the expected
  shape is the literal `CREATE TABLE` statement the test wrote). Doing this
  here, not as its own later slice, avoids writing schema_discovery tests
  twice — once against the two-driver version, once after consolidation.

**Implementation.** Create `src/dqt/sql/_connect.py` with the sole
`get_connection(config: ConnectionConfig) -> Any` for user-database
connections (SQLite `mode=ro` + PostgreSQL `psycopg` v3 read-only session,
following `_get_connection`'s existing, already-tested logic as the template
— it is the correct shape per `ENGINEERING-STANDARDS.md`'s own precedent
citation). Delete `schema_discovery.connect_sql` and `rules._get_connection`;
repoint every caller (`profiling.py`, `diagnostics.py`'s callers via
profiling, `cleansing.py`, `schema_discovery.py`) at the new module. Drop
`psycopg2-binary` from `pyproject.toml`'s `postgres` extra, keeping
`psycopg[binary]`, per the roadmap's own recommendation.

**Acceptance criteria (from roadmap `DQT-08`, extended to cover the
undocumented bypass).** Exactly one connection-opening function for user
databases. One Postgres driver in `pyproject.toml`. A test asserts no other
module imports a DB driver. `read_only=True` is enforced identically whether
reached via profiling, discovery, or cleansing.

**Docs to update.** `docs/CONVENTIONS-DQT.md` §1 S1 (note the single-
connection-function consolidation, distinct from the still-open two-role
proposal); `docs/00-START-HERE.md` §3; `ENGINEERING-STANDARDS.md` §1.2's own
"Incident #2 (still open)" note — mark closed once merged (this is an
ecosystem doc, not a DQT one — flag it for the roadmap owner rather than
editing it unilaterally, since precedence rank puts ecosystem docs outside
a single repo's PR).

**Size.** 1–1.5 days, one PR.

---

### 10. `NEW-C` (slice 2) — Ground `metrics.py`, post-`NEW-A`

**Depends on:** `NEW-A` (unit 5) — this is the case `BACKLOG.md` names
explicitly: "`metrics.py`'s shape changes if `dimension` is fixed, so testing
it first may mean writing those tests twice." Sequenced here, after the
shape settled in unit 5, precisely to avoid that duplication.

**Tests first.**
- `tests/unit/sql/test_metrics.py::test_compute_run_metrics_hand_computed`
  — reuse unit 4's seeded fixture (5 rows, 2 nulls in one column across
  N columns/tables); assert `table_count`, `column_count`, and
  `average_completeness` match hand-derived arithmetic over that exact
  fixture, and that each carries `metric_name=<name>, dimension=None` per
  `NEW-A`'s settled shape. Ground truth: shape 3.
- `tests/unit/sql/test_metrics.py::test_average_completeness_is_1_when_no_columns`
  — boundary case already present in the code (`if column_count == 0:
  average_completeness = 1.0`); lock it with a test rather than leaving it
  implicit. Ground truth: shape 4 (vacuous-truth boundary, same reasoning as
  unit 4's zero-row case).

**Implementation.** None expected beyond `NEW-A`'s emitter change (already
done in unit 5); this slice is pure test-writing unless it surfaces a defect.

**Acceptance criteria.** `metrics.py` has dedicated, hand-grounded tests; its
docstring's `Example::` block is exercised by an actual test, closing one of
the unproven-`Example` claims counted in § Claims currently unproven.

**Docs to update.** `docs/00-START-HERE.md` §3.2/§5 (Metrics row).

**Size.** 3–4 hours, folds into the same PR as unit 5's model change if
convenient, or its own small PR.

---

### 11. `NEW-C` (slice 3) — Ground `monitoring.py` as what it is today; do not build `NEW-G` here

**Depends on:** nothing for the stub test; the *real* monitoring feature
(`BACKLOG.md` `NEW-G`) is explicitly **blocked on `NEW-A`** per that
backlog entry ("trending a field that means two things produces confident
nonsense") — which is why this unit only tests the current identity
pass-through and does not attempt trend detection.

**Tests first.**
- `tests/unit/sql/test_monitoring.py::test_monitor_is_identity` — assert
  `monitor(metrics) is metrics` or at least `monitor(metrics) == metrics`
  for an arbitrary non-trivial list. Ground truth: shape 4 (property:
  round-trip identity is exactly what the module's own docstring claims —
  "Return metrics unchanged" — so this is the one module in `NEW-C` whose
  *entire* documented behavior is a property test, not a computed-value
  test).

**Implementation.** None. This unit exists to convert "0% dedicated tests,
100% line coverage" into an honestly-small, honestly-scoped test that matches
the module's honestly-small, honestly-scoped current behavior.

**Acceptance criteria.** `monitor()`'s docstring claim ("returns metrics
unchanged") is now backed by a test, not just by reading the four-line
function body.

**Docs to update.** None — `CONVENTIONS-DQT.md` §5's "Monitoring — stub"
row is already accurate.

**Size.** 30 minutes. Bundle into whichever adjacent PR is smallest; not
worth its own PR.

---

### 12. `NEW-C` (slice 4) — Ground `reports.py`, including the evidence-escaping gap

**Depends on:** nothing structurally.

**Tests first.**
- `tests/unit/sql/test_reports.py::test_html_escapes_hostile_column_and_issue_values`
  — build a `PipelineResult` with a table name, column name, and issue
  message each containing `<script>alert(1)</script>`, generate the report,
  assert the literal string does not appear unescaped in the output (assert
  `&lt;script&gt;` appears, and `<script>` inside a `<td>` position does not).
  Ground truth: shape 2 — this is an independent reproduction of an XSS-style
  defect *if* one exists; the code review for this plan found `reports.py`
  already calls `html.escape` on every rendered field it touches (schema/
  table/column names, messages, run metadata) — so this test is expected to
  **pass against current code**, which is a legitimate and useful thing to
  assert (a regression guard), but it is not proof of a *fixed* defect the
  way unit 6's tests are. State this distinction in the test docstring so
  a future reader does not mistake "passes today" for "was broken and got
  fixed here."
- `tests/unit/sql/test_reports.py::test_evidence_field_is_not_currently_rendered`
  — a documented gap, not a defect to fix in this unit: `DQIssue.evidence`
  is never read anywhere in `reports.py` (confirmed: zero occurrences of
  `evidence` in that file). `CONVENTIONS-DQT-data-model.md` §5's instruction
  to "escape on render" is therefore currently vacuous — there is no render
  path to escape. Write this as an explicit, named test asserting the
  current (non-)behavior, so that the day someone adds an evidence panel,
  this test fails loudly and forces the escaping requirement to be honored
  at the same time the feature is added, rather than after. Ground truth:
  shape 4 (an absence, asserted directly — `"evidence" not in
  generate_html_report(result_with_evidence).read_text()` for evidence
  containing a distinctive marker string).
- `tests/unit/sql/test_reports.py::test_report_summarizes_hand_counted_issues_by_severity`
  — a fixture with a known count of `critical`/`error`/`warning`/`info`
  issues; assert the rendered HTML's per-severity counts match. Ground
  truth: shape 3.

**Implementation.** None expected for the escaping tests (already correct);
none for the evidence gap (documented as a gap, not fixed — rendering
`evidence` at all is `NEW-E`'s territory, explicitly out of scope here).

**Acceptance criteria.** `reports.py` has dedicated tests for its escaping
behavior and its severity-grouping logic; the `evidence`-is-unrendered gap is
a named, asserted fact rather than an implicit one.

**Docs to update.** `docs/CONVENTIONS-DQT-data-model.md` §5 — soften "Escape
on render" to note it is currently aspirational because there is no render
path yet, rather than implying an active control exists.

**Size.** 4–6 hours.

---

### 13. `DQT-09` — Introduce the `DQT` exception hierarchy

**Depends on:** `DQT-05` (unit 6, per the roadmap's own stated dependency —
now satisfied). **Blocked on Q1/Q2/Q4:** no.

**Why here.** `DQT-05` is the last unit in this sequence that would need to
choose new exception types (`CleansingError`, refusal-on-drift in `revert()`)
— doing the hierarchy after it means those choices inform the hierarchy's
shape instead of being retrofitted into it.

**Tests first.**
- `tests/unit/test_exceptions.py::test_read_only_violation_is_a_dqt_error` —
  `assert issubclass(ReadOnlyViolationError, DQTError)`. Ground truth: shape
  4 (structural/type invariant).
- `tests/unit/test_exceptions.py::test_all_package_exceptions_derive_from_root`
  — an AST or `__subclasses__()`-based scan asserting every exception class
  defined under `src/dqt/` derives from `DQTError`. Ground truth: shape 4 —
  this is the same check `tools/arch_audit.py` will eventually automate
  (`ARC-01`, unit 14); write it as a plain test now so it exists before that
  tool lands, per this plan's TDD mandate.
- `tests/unit/test_exceptions.py::test_deprecated_import_path_still_works_and_warns`
  — `from dqt.sql.cleansing import ReadOnlyViolationError` (the pre-`DQT-09`
  import path) must still succeed and emit `DeprecationWarning`. Ground
  truth: shape 2/4 — reproduce that the old path works today (it must,
  since it's the only path today), then show it still works *and* warns
  after the move.

**Implementation.** `DQTError` root in `exceptions.py`; `ReadOnlyViolationError`
already there, now subclasses `DQTError`; add `RuleEvaluationError` (used by
unit 2's malformed-pattern handling), `ConnectionConfigError`,
`CleansingError` (used by unit 6's drift-refusal in `revert()`). Re-export
`ReadOnlyViolationError` from `cleansing.py` with a `DeprecationWarning` on
import (module-level `__getattr__` or a shim) for one release.

**Acceptance criteria (from roadmap `DQT-09`).** `except DQTError` catches
every package-specific failure. Old import path still works and warns.

**Docs to update.** `docs/00-START-HERE.md` §3.3 item 13; `docs/
CONVENTIONS-DQT.md` §5 (Exception hierarchy row); `docs/BACKLOG.md` §1.

**Size.** 4–6 hours, one PR.

---

### 14. `ARC-01` — Architecture gate

**Depends on:** `DOC-01` (unit 3, merged) — reuses its `Violation`/baseline
machinery per the roadmap's explicit instruction not to invent a second
reporting format.

**Why here, this late.** `ARC-01`'s four checks (layering, single-authority,
exception-root, determinism) are far more useful once the two violations this
plan already knows about are fixed (`DQT-08`'s connection-authority
consolidation, unit 9; `DQT-09`'s exception root, unit 13) rather than
baselined as tolerated debt on day one. Running it earlier is defensible too
(catch regressions sooner) — this plan's choice is that a smaller, truer
initial baseline is worth the wait, since ratchet-mode debt that starts large
tends to stay large in practice (the same dynamic `DOC-02`, unit 15, exists
to correct for documentation debt).

**Tests first.** As with `DOC-01`, the tool itself is authored fresh here (no
existing DQT copy) — this is the one gate-tool unit in this plan that is not
"copy and baseline." Its own tests are:
- A planted layering violation (e.g. a fake `models.py` importing from
  `sql/`) is detected. Ground truth: shape 2 (write the violation, show it's
  caught, remove it).
- A planted duplicate-authority violation (two functions named
  `_get_connection`-alike performing the same concern) is detected — this is
  exactly the historical `_qualified_table`/`_ident` pattern from `DQT-02`'s
  incident, plantable as a regression fixture.
- A planted exception not deriving from `DQTError` is detected.
- A planted module-level `random.seed(`/`np.random.seed(` call is detected
  (DQT has no numpy dependency today — confirm this check is a no-op-but-
  present rule, not dead code, since `ENGINEERING-STANDARDS.md` §1.8 applies
  ecosystem-wide even where a given repo doesn't currently trigger it).

All four: ground truth shape 2 (the tool's own correctness is proven by
reproducing each violation class before the tool exists to catch it, then
showing the tool catches it).

**Implementation.** `tools/arch_audit.py`, sharing `doc_audit.py`'s
`Violation`/baseline classes (import or copy the shared base — per §1.2's
own rule, do not reimplement baseline I/O a second time).

**Acceptance criteria (from roadmap `ARC-01`).** Gate green with a baseline.
Planted violation of each of the four rules is detected (all four shown).

**Docs to update.** None expected to become false; this is new tooling only.

**Size.** 2 days.

---

### 15. `DOC-02` — Pay down the DQT documentation debt to zero

**Depends on:** `DOC-01` (unit 3). Sequenced last because every prior unit
in this plan touches docstrings in `models.py`, `cleansing.py`, `storage.py`,
`metrics.py`, `exceptions.py` — paying debt to zero before that churn
finishes would mean re-paying it.

**Tests first.** None new — the verification is `doc_audit.py` at an empty
baseline (`exit 0`) plus `pytest --doctest-modules` (or the repo's chosen
mechanism for `ENGINEERING-STANDARDS.md` §2.4, "examples executed in CI")
green, proving every `Example::` block genuinely runs. This is where the
`Example::` blocks counted as unproven in § Claims currently unproven get
closed out formally, module by module.

**Implementation.** Backfill missing `Args`/`Returns`/`Raises` per
`ENGINEERING-STANDARDS.md` §2.2, for whatever the baseline still contains
after units 1–14's incidental docstring rewrites.

**Acceptance criteria (from roadmap `DOC-02`).** Baseline file empty. All
examples execute in CI.

**Docs to update.** The docstrings themselves; no conventions doc.

**Size.** 1–2 days, depends heavily on what's left after the churn above —
re-measure before estimating precisely.

---

### Deferred, not scheduled in this sequence

- **`ALL-01`** — its concrete deliverable (`tools/claim_audit.py`) is built
  against `MSY` first, per the roadmap's own text; DQT's copy is "a separate,
  unstarted follow-up PR" that this repo cannot start before `MSY`'s version
  exists. Track as a placeholder `NEW-J` ("port `claim_audit.py` into DQT")
  with a hard external dependency, not a DQT-internal blocker.
- **`DOC-03`** — `PDP`-only; not applicable to this repo.
- **`DOC-04`** — measured baseline-key collisions for DQT are **zero** (29
  entries, 29 unique keys, per the roadmap's own measurement table). Nothing
  to do here for this repo specifically; note it and move on.
- **The two-connection split (Q4, if resolved that way), the `plan`/`apply`
  ceremony (Q2, if resolved that way), and wiring real `CleansingConfig`
  objects into `run()` (Q1, if resolved "yes")** — all explicitly owner
  decisions this plan does not schedule work against. See § Open questions.

---

## § Ordering rationale

**Cheap, isolated, high-damage fixes first (units 1–2).** `NEW-H` and
`DQT-04` share nothing code-wise but share a shape: a declared capability
(config-driven rules, regex validation) that silently does nothing. Neither
touches the schema, the exception hierarchy, or the pipeline's control flow,
so nothing later in this plan is invalidated by doing them first, and every
day they stay unfixed is a day the CLI's primary use case (rule-gated CI
checks) produces false negatives.

**The documentation gate lands before the big rewrites (unit 3), not after.**
This is the roadmap's own instruction (§4.5), and it matters more here than
usual because units 5, 6, 9, and 13 rewrite the exact modules
(`models.py`, `cleansing.py`, `storage.py`, `exceptions.py`) whose docstrings
carry this repo's worst historical failure mode (eleven false `DONE`
markers). A gate that exists before those rewrites can catch a regression
during them; a gate added after can only measure the result.

**On whether the six `NEW-C` modules should be tested before new features
land on top of them:** yes, with one qualification, and the qualification
matters more than the yes. The unqualified position — "test all six before
any feature work" — is wrong for `NEW-H` and `DQT-04` (units 1–2): those
touch `cli.py` and `rules.py`, not the `NEW-C` six, and delaying two cheap,
high-damage, already-well-understood fixes behind a multi-day testing
initiative on unrelated modules would be exactly the kind of scope-creep
`GUIDE-dqt-architect.md` §3 warns against ("do not fix defects outside your
task"). The qualified position — test `profiling.py`/`diagnostics.py` before
`DQT-05`, and test `metrics.py` only after `NEW-A` — is right, and is what
this plan does, for a reason stronger than "the gate doesn't see them": the
80% coverage number passing today on modules with **100% line coverage and
zero grounded assertions** (measured in the preamble) is not a hypothetical
risk, it is the exact failure mode this plan's mandate exists to prevent,
concretely present in this specific codebase right now. Building `DQT-05`'s
revert-round-trip checksum proof on top of an unverified profiling layer
would mean the checksum proves internal consistency, not correctness — a
subtler version of the same "self-referential test" problem `HONESTY-GATE.md`
names directly. `NEW-A` interacting with `metrics.py`'s shape is the other
half of the qualification: writing `metrics.py` tests before `NEW-A` lands
would mean writing them twice, once against the overloaded `dimension` field
and once after the split — pure waste with no offsetting safety benefit,
since nothing else in this plan depends on `metrics.py` being tested before
unit 10.

**Schema-affecting units (`NEW-A`, `DQT-05`) are adjacent, not merged.**
They touch different code (`models.py`/emitters vs. `cleansing.py`/`revert`)
and have independently statable acceptance criteria, so keeping them as two
PR-sized units respects "one task, one branch, one PR" — but they are
sequenced back-to-back and explicitly coordinated to land one storage-schema
recreation, not two, because `RunStore` is a local SQLite artifact meant to
be recreated rather than migrated (per `BACKLOG.md` `NEW-A`'s own note), and
recreating it twice in two consecutive PRs would break any existing
`dqt_runs.db` twice for no benefit over breaking it once.

**`DQT-08` absorbs the undocumented `schema_discovery` bypass rather than
treating it as a separate unit,** because the two problems are the same
problem from opposite ends: `DQT-08` says "there should be one connection
function"; the bypass says "there are two, and the second one skips
enforcement." Fixing the driver split without also fixing the bypass would
leave two connection-opening paths again, just newly-both-correct ones,
which reproduces the single-authority violation the task exists to close.

**`ARC-01` lands after `DQT-08`/`DQT-09`, not before**, so its first baseline
is closer to the target architecture. This is the one placement in this plan
where the opposite choice is nearly as defensible — an earlier `ARC-01` would
catch regressions in units 9 and 13 themselves, which this plan instead
catches via unit 13's own hand-written structural tests (`test_exceptions.py`)
as a stopgap. State that tradeoff plainly rather than pretending only one
answer exists.

---

## § Claims currently unproven

Swept `src/dqt/` for `reversible`, `auditable`, `enforced`, `guarantee(d)`,
`idempotent`, `thread-safe`, `production-ready`, and "safe for concurrent" —
the high-risk vocabulary `ALL-01`'s future `claim_audit.py` will scan for —
plus every `Example::` block in the six `NEW-C` modules, since none of them
run under any test today (`ENGINEERING-STANDARDS.md` §2.4 requires every
`Example` to execute in CI; none of these do, so all are "unproven" by that
rule regardless of whether the example is actually correct).

**Count: 3 confirmed-false claims, 1 confirmed-untested-but-plausible claim,
1 vacuous-but-not-false convention claim, and roughly 17 unexecuted `Example`
blocks across the six `NEW-C` modules** (5 in `profiling.py`, 2 in
`diagnostics.py`, 1 in `metrics.py`, 1 in `monitoring.py`, 5 in
`schema_discovery.py`, 3 in `reports.py`).

**The two worst:**

1. **`src/dqt/sql/cleansing.py` module docstring, line 5: "Reversible,
   auditable SQL cleansing primitives for DQT," restated as design invariant
   #2 at line 21.** False today, confirmed by reading: `revert()` does not
   exist anywhere in the codebase, `cleansing_log` has no table, and
   `CleansingLog` objects returned by `apply_cleansing()` are the caller's
   only copy — dropped, they are gone. This is the exact incident
   `ENGINEERING-STANDARDS.md` §2.3 names by name. Unit 6 (`DQT-05`) is the
   only place in this plan that can make this claim true, and the docstring
   must not be corrected to say "reversible" until that unit's round-trip
   test passes.
2. **The same claim repeated at `src/dqt/sql/pipeline.py` line 14** (module
   docstring's stage-5 description: "apply reversible cleansing primitives"),
   a second location asserting the identical false thing — this is worth
   flagging separately because it means fixing `cleansing.py`'s docstring
   alone would leave a second, easy-to-miss copy of the same false claim
   in a different file. `pipeline.py:302`'s method-level docstring is a
   third, softer occurrence ("Apply reversible cleansing primitives (stub)")
   — hedged by "(stub)" and by an accurate body ("currently a pass-through"),
   so it is aspirational-by-context rather than a bare false claim, but the
   word choice should still change once unit 6 lands, for consistency.

**The confirmed-untested-but-plausible one:** `src/dqt/common/storage.py`
line 18, "All write operations are safe for concurrent readers." No
concurrency test exists anywhere in `tests/unit/common/test_storage.py`
(confirmed by reading the file — it has idempotency and DSN-non-persistence
tests, but nothing opening two connections at once). `WAL` mode's reader/
writer semantics make this plausible, but "plausible because of the SQLite
mode chosen" and "verified" are different claims, and this document exists
to keep that distinction. Not scheduled as its own unit above because no
unit in this sequence touches concurrent access; flag it for whoever next
touches `RunStore` under load (e.g. a future monitoring-daemon use case) to
either test or soften before that work ships.

**The vacuous-but-not-false one:** `docs/CONVENTIONS-DQT-data-model.md` §5,
"`evidence` payloads are attacker-adjacent data rendered into HTML reports.
Escape on render." `reports.py` never reads `DQIssue.evidence` at all (zero
occurrences, confirmed by grep) — so there is no render path to have escaped
or unescaped. The claim is not false so much as describing a feature that
does not exist yet, stated as though it were a control already exercised.
Unit 12 downgrades the doc wording; `NEW-E` (render or delete `evidence` and
`external_analyses`) is the actual fix, and remains unscheduled here — see
§ Non-goals reaffirmed.

---

## § Specification gaps

1. **`DQMetric.dimension`/`metric_name` split (unit 5's own subject) has no
   settled convention for which field non-dimensional metrics populate.**
   `BACKLOG.md`'s proposed fix says "make `dimension` optional... a row count
   is a measurement, not a quality dimension," but does not say whether
   `metric_name` should *also* be populated for real-dimension metrics (e.g.
   should a `completeness` score also carry `metric_name="completeness"`, or
   is `metric_name` exclusively for the three current non-dimension metrics?
   Both are defensible; neither is written down.) Unit 5 cannot write a
   ground-truthed shape test without this decision — the plan picks the
   narrower reading (`metric_name` populated only when `dimension` is
   `None`) as the one that changes less existing data, but this is this
   plan's inference, not a settled spec, and should be confirmed by the
   owner before unit 5 starts, not discovered mid-implementation.
   > **Settled 2026-08-19 (annotated at landing):** this decision is
   > **delegated to the implementing agent** in unit 5 (`NEW-A`), on
   > condition that `NEW-A`'s PR body documents the reasoning prominently
   > so the choice is reviewable at PR time, not buried in a diff. The
   > plan's own narrower-reading inference above is a reasonable default
   > for that agent to start from, not a mandate to deviate from it silently.
2. **The fatal/non-fatal stage split for `NEW-B`'s `status` derivation has no
   spec at all.** Nothing in `CONVENTIONS-DQT-data-model.md` §2.1 (which
   defines `"success"`/`"partial"`/`"failed"` only by name, not by which
   stage failures produce which value) says whether, e.g., a rule-file
   parse error should ever produce `"failed"` (the whole run is suspect) or
   only ever `"partial"` (rules are additive, other stages' results are
   still valid). Unit 7 has to invent this split; it should be written down
   in `CONVENTIONS-DQT-data-model.md` as part of that PR, not left implicit
   in the exception-handling code.
   > **Settled 2026-08-19 (annotated at landing), for the missing-rule-file
   > case specifically:** yields `"partial"`, with the reason carried in
   > `stage_errors` — see unit 7's inline annotation above. The broader
   > fatal/non-fatal split for *other* stage-failure kinds remains for
   > unit 7 to write down, as this item originally said.
3. **No spec exists for what "the same transaction" means across DQT's two
   supported dialects for `DQT-05`'s log-before-mutation requirement.**
   `CONVENTIONS-DQT.md` §1 S4 says the undo statement "must be persisted to
   the `cleansing_log` table **before** the forward statement executes," but
   `cleansing_log` and the target table being cleansed are, in general, in
   *different databases* in DQT's architecture (`cleansing_log` lives in
   `RunStore`'s SQLite file; the mutated table lives in the profiled
   database, which may be PostgreSQL). A single DBAPI transaction cannot
   span both. The spec needs to say whether "before" means "before, in wall-
   clock/statement order, across two separate commits" (weaker — a crash
   between the two commits can still lose the log-mutation ordering
   guarantee, just not silently) or something else. This plan's unit 6 tests
   the SQLite-same-database case, and explicitly does not claim to have
   solved the cross-database case — flagging it here rather than papering
   over it with a same-database test that would not generalize to
   PostgreSQL, DQT's stated primary production target.

---

## § Open questions for the owner

- **Q1 (should `cleanse` stay on `run()`'s call path).** Blocks: wiring real
  `CleansingConfig` objects into `DQTPipeline.run()` (not scheduled in this
  plan at all, for exactly this reason). Options: keep the call as
  defence-in-depth now that `DQT-03`/unit 6 make it safe even if invoked
  (current code), or remove it in favor of separate `cleanse_plan()`/
  `cleanse_apply()` entry points (the stronger, `CONVENTIONS-DQT.md`-proposed
  separation-of-paths design). Recommendation: remove the call — a profiling
  run should not be *structurally capable* of mutating what it profiles,
  and `DQT-03`'s read-only guard being the only thing standing between
  "profile" and "write" is exactly the single-point-of-failure pattern
  `ENGINEERING-STANDARDS.md` §1.4 says to avoid by design, not just by
  configuration.
  > **Still OPEN as of 2026-08-19 (annotated at landing).** Not resolved by
  > this reconciliation.
- **Q2 (`--dry-run` vs. a stricter `plan`/`apply` with `plan_id`).** Blocks:
  any future work formalizing distinct cleansing entry points, and shapes
  (without blocking) unit 6's persistence design. Options: keep the shipped
  `dry_run` boolean (simpler, already tested), or add the four-condition
  `plan`/`apply`/`plan_id` ceremony from `CONVENTIONS-DQT.md` §1 S2
  (stronger audit trail, more moving parts). Recommendation: keep `dry_run`
  for v0.1 — the `plan_id` ceremony's main benefit (proving a specific
  reviewed plan was the one applied) matters most once cleansing is
  wired into automated pipelines, which Q1's likely resolution (remove
  `cleanse` from `run()`) would delay anyway; revisit once/if Q1 resolves
  toward keeping cleansing on an automated path.
  > **Still OPEN as of 2026-08-19 (annotated at landing).** Not resolved by
  > this reconciliation.
- **Q4 (separate read/write connections).** Blocks: nothing in this plan
  outright, but determines whether `DQT-08`'s `_connect.py` (unit 9) later
  grows a second entry point. Options: single enforced connection (current,
  `DQT-03`'s shipped design) or two separately-credentialed connections (the
  stronger, DBA-auditable-without-reading-source proposal). Recommendation:
  defer — the single-connection model has a real, tested proof today; the
  two-connection model's main benefit (a DBA auditing *credentials* rather
  than *code*) matters more at the point DQT is deployed against a
  production database with a real DBA-managed role system, which is not
  this plan's v0.1 scope.
  > **Deferred, as recommended (annotated 2026-08-19 at landing).** No
  > change to this plan's treatment of Q4.
- **New: the `metric_name`/`dimension` co-population question (§ Specification
  gaps item 1).** Blocks: unit 5 starting with a settled ground truth for its
  shape tests. Options stated there. Recommendation: the narrower reading
  (mutually exclusive fields), because it is smaller and reversible — widening
  later to co-populate both is backward compatible; narrowing later is not.
  > **Settled 2026-08-19 (annotated at landing):** delegated to the
  > implementing agent in unit 5, conditioned on the PR body documenting
  > the reasoning — see the matching annotation under § Specification gaps
  > item 1.
- **New: is a missing rule file (`contextlib.suppress(FileNotFoundError)` in
  `pipeline.py::apply_rules`) a silent skip or a `"partial"`-status
  condition (§ Specification gaps item 2)?** Blocks: unit 7's exact status-
  derivation logic and its test's expected value. Recommendation: `"partial"`
  — a DBA who configured three rule files and typo'd one should see that in
  the run's status, not just in a log line nobody is watching; this is the
  same "silent all-clear is the worst failure mode" reasoning
  `ENGINEERING-STANDARDS.md` §1.6 already applies to `cleansing.py`'s old
  `except Exception` incident.
  > **Settled 2026-08-19 (annotated at landing):** the recommendation above
  > was adopted — `"partial"`, reason carried in `stage_errors`, to be
  > implemented in unit 7 (`NEW-B`) — see that unit's inline annotation.
- **Settled elsewhere, recorded here for completeness (annotated at
  landing, 2026-08-19) — `docs/BACKLOG.md` §3 Q3, is `DELETE` permitted as
  a cleansing primitive?** This question is not one of this plan's own
  listed items above (it belongs to `BACKLOG.md`, and unit 6's own "Why
  here" paragraph already treats it as decided), but it interacts directly
  with this section so it is recorded here too: **`DELETE` remains a
  permitted cleansing primitive.** Deduplication keeps its `DELETE` and its
  `not_null_guard`; `revert()` (unit 6, `DQT-05`) must restore deleted rows
  by reinserting from logged before-values. **Consequence:**
  `docs/CONVENTIONS-DQT.md` §1 S5 still proposes banning `DELETE` in v0.1 and
  therefore now contradicts this settled decision — it must be amended in
  whichever PR next touches cleansing (most naturally unit 6). **This PR
  does not touch cleansing and does not amend it.**

---

## § Non-goals reaffirmed

Carried forward from `AGENTS.md` and `ROADMAP.md` §2.3, restated so no unit
above is later read as license to add them "while in there":

- No pandas/DataFrame path, ever, as a first-class citizen — `AGENTS.md`
  names the prior removal of exactly this by name.
- No service/performance monitoring (latency, CPU, wait stats, uptime) —
  `NEW-G`'s eventual real implementation, when it happens, means trend
  detection on **data-quality metrics**, never on the pipeline's own
  runtime characteristics.
- No masking, compliance, or MDM/golden-record features.
- No third SQL dialect (MySQL, SQL Server) before a `dqt/sql/dialects/`
  abstraction exists — nothing in this plan adds one; `DQT-08`'s
  consolidation to `_connect.py` makes adding that abstraction later
  easier, but does not itself build it.
- No new hard runtime dependency. `DQT-08` (unit 9) *removes* one
  (`psycopg2-binary`); nothing here adds one. If `ARC-01`'s tooling or
  `DOC-01`'s copied script needs a package not already a `dev` extra, name
  it explicitly in that unit's PR rather than assuming.
- No merging DQT into `missingly`/`py-distfit-pro`/`distfitr` — explicitly
  rejected in the roadmap because it would import DQT's (shrinking, but
  still real) security/correctness debt into the ecosystem's one externally-
  verifiable asset.
- No raw-SQL rule type, ever, regardless of how reasonable a specific request
  sounds — `CONVENTIONS-DQT.md` §1 S6 and `GUIDE-dqt-architect.md` §2 are
  both explicit that the four-fixed-expression design (now five callers
  reading naturally after unit 2's regex fix, still exactly four expression
  types) is what stands between a rule file and arbitrary code execution.
- No rendering of `PipelineResult.external_analyses` or `DQIssue.evidence`
  in this plan (`NEW-E`) — noted as a gap in unit 12, deliberately not
  fixed, since it is a new-feature decision (build the panel) rather than a
  correctness fix, and out of scope for a plan whose brief is "as if we
  hadn't implemented anything yet," not "add the missing UI."

---

## § Scope and cut line

**Total: 15 scheduled units, an estimated 17–22 working days across roughly
14–16 PRs** (several units share a PR; `DQT-05` may split into two). This is
not a "handful of PRs" — say so plainly, as instructed. If the full sequence
above is more calendar time than the owner wants before the next release
candidate, here is the honest cut line:

**What makes v0.1 credible (do these; roughly the first 9 units, ~10–12
days):** units 1–9 — `NEW-H`, `DQT-04`, `DOC-01`, `NEW-C` slice 1
(profiling/diagnostics), `NEW-A`, `DQT-05`, `NEW-B`, `DQT-06`, `DQT-08`.
These close every defect this plan found that is either **silently wrong
today** (`NEW-H`, `DQT-04`, `NEW-B`, the `schema_discovery` bypass inside
`DQT-08`) or **false in a shipped docstring** (`DQT-05`'s "reversible"
claim). Without these nine, DQT cannot honestly claim its rules engine works,
its cleansing is reversible, its runs can fail visibly, or its exit codes
mean anything — which is to say, without these nine, "pre-alpha" is not
just a cautious label, it is the accurate one.

**What can wait (units 10–15, ~7–10 days):** `NEW-C` slices 2–4
(metrics/monitoring/reports tests), `DQT-09` (exception hierarchy — a real
improvement, but nothing in the first nine units is *blocked* on it existing,
only shaped by it existing later), `ARC-01`, `DOC-02`. These are genuine
quality-of-implementation work, not defects that make a claim false today;
deferring them does not create a new gap between what DQT says and what it
does, which is this plan's actual bar.

**Status of this cut line at landing (2026-08-26, added by this header, not
part of the original plan text above):** unit 1 of the first-nine group is
done. Units 2–9 of that group are not started. Nothing in units 10–15 has
started either.
