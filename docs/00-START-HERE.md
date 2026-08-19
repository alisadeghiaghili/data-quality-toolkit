# DQT — Start Here

Entry point for the **`dqt` (SQL Data Quality Toolkit)** documentation. Read this
page before any other document in this set.

**Repository:** `alisadeghiaghili/data-quality-toolkit` · **Package:** `dqt` ·
**Version:** 0.1.0 (pre-alpha, not released)

DQT is one of four repositories in the Aghili data ecosystem (`missingly`,
`py-distfit-pro`, `distfitr`, `data-quality-toolkit`). It is governed by that
ecosystem's engineering standard, which outranks everything in this directory.

---

## 1. Source-of-truth hierarchy

More than one document can describe the same rule. When they disagree, resolve
in this order — **higher wins, always**:

| Rank | Source | Authoritative for |
|---|---|---|
| 1 | **The source tree** (`src/dqt/`, `tests/`, `pyproject.toml`, `.github/workflows/ci.yaml`) | What the code *actually does*. No document overrides a read of the code. |
| 2 | **`AGENTS.md`** (this repo) — scope and non-goals section | Product decisions about what DQT is and is not. Outranks the ecosystem roadmap by that roadmap's own rule. |
| 3 | **`ROADMAP.md` §2.3 (non-goals) and §2.4 (honesty gate)** — ecosystem standard | The project-wide invariants. |
| 4 | **`ROADMAP.md` task bodies** — `DQT-01` … `DQT-09`, `ALL-01`, `DOC-01` … `DOC-04`, `ARC-01` | **The task list.** What to build, in what order, with what acceptance criteria. |
| 5 | **`ENGINEERING-STANDARDS.md`** — ecosystem standard | Layering, single-authority, docstring, and verification rules. |
| 6 | **`AGENTS.md`** — the rest of it | Enforceable working rules for this repo. |
| 7 | **`docs/HONESTY-GATE.md`** | What counts as evidence for a claim, specifically for DQT. The concrete, DQT-local instantiation of `ROADMAP.md` §2.4 — read it before writing any test that claims to verify a bug fix. |
| 8 | **`docs/CONVENTIONS-DQT.md`** | Scope, facet model, canonical vocabulary, supported dialects. Its §1 safety model is partly **proposal**, not settled — see `BACKLOG.md` §3. |
| 9 | **`docs/CONVENTIONS-DQT-data-model.md`** | Class shapes, the aggregation contract, the storage schema. |
| 10 | **`docs/BACKLOG.md`** | Defects with no roadmap ID yet, and open design questions. A supplement, not a task list. |
| 11 | Everything else (`docs/dqt_*`, `docs/DQT-UI-Ecosystem.md`, `docs/guides/`) | Context, comparisons, design direction. Never normative. |
| 12 | Dated reviews (`DQT-critical-review.md`; the 2026-08-16 Persian document review) | Historical record only — **never** cite as current state. |

Three consequences worth stating explicitly:

- **The task IDs are `DQT-xx`, from the roadmap.** Do not invent a parallel
  numbering. If a defect has no ID, it goes in `BACKLOG.md` §2 with a `NEW-x`
  placeholder and gets a real ID from the roadmap owner.
- **`AGENTS.md` and the ecosystem standard are not duplicated here.** They live
  where they are enforced. These documents reference them and never restate a
  rule. Two copies of a rule is one rule and one future bug.
- **Nothing here substitutes for reading the code.** Every status claim in §3 was
  verified by reading source on the date stamped there. Statuses rot.

---

## 2. What is in this doc set

```
docs/
  00-START-HERE.md                  ← you are here
  HONESTY-GATE.md                   ← what counts as evidence, made concrete for DQT
  BACKLOG.md                        ← defects with no roadmap ID; open questions
  CONVENTIONS-DQT.md                ← scope, vocabulary, safety model, statuses
  CONVENTIONS-DQT-data-model.md     ← classes, aggregation contract, storage
  DQT-UI-Ecosystem.md               ← UI screens and design direction
  dqt_ecosystem.md                  ← where DQT sits among adjacent tools
  dqt_competitors.md                ← capability floor + honest gap analysis
  dqt-reference-sources.md          ← external reading, with relevance notes
  guides/
    GUIDE-dqt-architect.md          ← how to reason about backend/data changes
    GUIDE-dqt-ui-designer.md        ← how to reason about UI changes
```

**On `guides/`:** reference documents, not installed tooling. Prose you read when
working on the relevant area; no runtime effect. They were previously named
`SKILL-*`, which implied a registered capability that does not exist.

Two dated reviews sit outside this set: `DQT-critical-review.md` in the repo root
(execution-based, 2026-08-11) and a Persian document review (2026-08-16, kept in
the project space). Both record why several conventions read as they do. **Never
cite either as current state.** Two claims in the Persian review have since been
superseded: it marked the legacy `src/data_quality_toolkit/` package "probably
gone" as an inference (now verified absent), and it left `src/dqt/ui/` unread
(now read — see §3).

---

## 3. Verified state — 2026-08-17, `origin/main` at `4629925`

> **⚠ Read §3.0 first. The public repository is behind verified local work.**

### 3.0 `DQT-02` is fixed on a branch in this repository; `DQT-03` is a separate, unverified claim

The record that used to stand here claimed `DQT-02` was fixed at commit
`a1f6ce7`. That commit does not exist in this repository
(`git cat-file -t a1f6ce7` fails) — it was never landed, just claimed.
`DQT-02` (parameterize all SQL, unify identifier quoting) is now actually
implemented in this repository, on branch `dqt-02`: 158 → 166 passing tests,
with a pre-fix exploit reproduced against unfixed `main` and a
revert → fail → restore → pass transcript
(`tests/unit/sql/test_sql_injection.py`). It has not been merged to `main`.

`DQT-03` (enforce `read_only`, add `--dry-run`) was also recorded elsewhere in
this document set as done at commit `7ae3fdc`. That commit does not exist in
this repository (`git cat-file -t 7ae3fdc` fails, the same problem as the old
`DQT-02` record). `DQT-03` has since actually been implemented, from scratch,
in this repository, on branch `dqt-03`: 166 → 183 passing tests, with a
four-hash checksum proof (hash before / after a read-only run / after a
guarded write attempt / after a real write with the guard removed — the first
three match, the fourth differs) and a revert → fail → restore → pass
transcript (`tests/unit/sql/test_read_only.py`). It has not been merged to
`main`. See `BACKLOG.md` §1.

Everything in §3.1–§3.3 below therefore describes **the `main` branch**, which
— until `dqt-02` and `dqt-03` are merged — still nominally lists both the
`DQT-02` defect (§3.3 item 1) and the `DQT-03` defect (§3.3 item 2), even
though fixes for both exist on branches in this repository.

### 3.1 Works, and is tested

- **Rules engine, column scope** — `not_null`, `unique`, `range` are
  YAML/JSON-driven and unit-tested; unknown expressions are rejected rather than
  executed. **`regex` is the exception: it does not work at all on SQLite** and
  has no test — see §3.3.
- **Storage (`RunStore`)** — SQLite. `runs`, `run_metrics`, `run_issues`, with
  `NOT NULL` foreign keys and a `COALESCE`-based unique index that makes
  `save_run` idempotent. Unit-tested.
- **Config loading** — Pydantic v2 validation, env-var expansion. Unit-tested.
- **CI** — `ruff check` → `ruff format --check` → `mypy --strict` → `pytest` with
  an 80% coverage gate. Matrix: Python 3.11 and 3.12.

### 3.2 Exists, works, but has no tests

- `profiling.py`, `diagnostics.py`, `metrics.py`, `monitoring.py`,
  `schema_discovery.py`, `reports.py` — **six modules, zero unit tests.**
- `src/dqt/ui/` — a FastAPI skeleton (`app.py`) over a read-only data-access
  layer (`api.py`) exposing `/runs`, `/runs/{id}`, `/runs/{id}/tables`,
  `/runs/{id}/metrics`, `/runs/{id}/issues`, `/health`. **No tests, no
  frontend.** Behind the `ui` extra.

### 3.3 Known defects on `origin/main`

Each is a correctness or safety problem that constrains what can be built on top.

1. **SQL injection via rule files** (on `main`; fixed on branch `dqt-02`).
   `range` bounds were f-string-interpolated at `rules.py:295-319`; table
   identifiers were not quoted in the rules engine. `DQT-critical-review.md`
   §1.3 **reproduced a working exploit** — a subquery executing through a
   range bound. → **`DQT-02`, fixed on branch `dqt-02` in this repository,
   not merged to `main`.** The fix parameterizes every literal reaching SQL
   in `rules.py`/`cleansing.py` and routes every identifier through the
   single quoting authority in `sql/_identifiers.py`; see
   `tests/unit/sql/test_sql_injection.py` for the exploit reproduction and
   the fixed-code regression tests.
2. **`read_only` is enforced nowhere** on `main`. `ConnectionConfig.read_only`
   is accepted and has zero consumers; there is no `--dry-run`; the tool issues
   `UPDATE` and `DELETE` regardless of the flag. → **`DQT-03`, fixed on branch
   `dqt-03` in this repository, not merged to `main`.** The fix enforces
   `read_only` at the connection layer (`sql/rules.py::_get_connection` opens
   SQLite with `mode=ro`; PostgreSQL sessions get
   `SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY`), adds an
   independent `ReadOnlyViolationError` guard in
   `sql/cleansing.py::apply_cleansing` before any mutating statement is built,
   and adds `dry_run=True`-by-default to `apply_cleansing` plus
   `--dry-run`/`--commit` flags on `dqt profile`; see
   `tests/unit/sql/test_read_only.py` for the checksum proof and the
   revert → fail → restore → pass transcript.
3. **`regex` rules are dead on the only fully supported backend.** `rules.py:362`
   emits `NOT REGEXP ?`; SQLite ships no `REGEXP` implementation and
   `create_function` appears nowhere in the codebase. Every regex rule produces a
   permanent false `error`-severity issue instead of validating anything —
   including the email rule in `examples/rules/advanced_rules.yaml`. Semantic
   validity is the stated differentiator, so this is not a small gap. → **`DQT-04`.**
4. **Cleansing is neither reversible nor persisted.** No `revert()` or `undo()`
   exists; `storage.py` has no cleansing table. `CleansingLog` is built in memory
   and returned — drop the return value and the before-values are gone. → **`DQT-05`.**
5. **`cleanse()` is on the default call path.** `run()` calls
   `self.cleanse(result)` unconditionally at stage 5. It reaches a pass-through
   today, but the write-capable primitives live in the same module. Whether to
   remove the call or rely on `DQT-03`'s enforcement is an **open design
   question** — `BACKLOG.md` §3, Q1.
6. **`dimension` means two different things.** `diagnostics.py` and `rules.py`
   write real dimensions; `metrics.py` and `profiling.py` write metric names
   (`table_count`, `column_count`, `average_completeness`, `row_count`). Any
   grouping or scoring by dimension is wrong. → **`BACKLOG.md` `NEW-A`.**
7. **Run status is always `success`.** `run()` hardcodes it and no stage is
   wrapped in error handling. → **`NEW-B`.**
8. **Only one of six dimensions is implemented** — `completeness`.
9. **`monitor()` returns its input unchanged.** → **`NEW-G`.**
10. **`README.md` is factually wrong and publicly visible** — it describes DQT as
    a pandas DataFrame utility, its pre-repurpose identity. → **`DQT-01`.**
11. **PostgreSQL is the primary production target and is untested in CI.**
12. **The `postgres` extra installs two redundant drivers** (`psycopg[binary]`
    and `psycopg2-binary`). → **`DQT-08`.**
13. **No exception hierarchy.** → **`DQT-09`.**
14. **No exit-code contract**, so the "DQ gate in CI" use case is impossible. → **`DQT-06`.**

### 3.4 Confirmed *not* problems

Recorded so they are not re-investigated:

- No duplicate `.github/workflows/ci.yml`. Only `ci.yaml` exists.
- No orphaned `tests/test_visualization_heatmap.py`.
- The legacy `src/data_quality_toolkit/` pandas package is gone; the tree
  contains only `src/dqt/`.
- `black` is not used. `ruff format` replaces it.
- The coverage gate is 80% in both `pyproject.toml` and CI.
- The CLI runs. The `rowid` aliasing bug and the NULL-key dedup data-loss bug
  were both fixed in the Phase 0 remediation.

---

## 4. Doc drift

**Three files in the repo are behind these docs:** `README.md` (wrong
description), and the root-level `CONVENTIONS-DQT.md` and
`CONVENTIONS-DQT-data-model.md`, which predate the current model and storage
layer and still say `cleanse` is not wired into the pipeline.

Landing the corrected versions is part of `DQT-01`. Note that `DQT-01` specifies
a **verbatim status block** for the README; use it rather than paraphrasing, and
keep its five bullets tied to their task IDs.

---

## 5. How to start a work session

1. **Read the roadmap first** — §0 (agent contract), §2.3 (non-goals), §2.4
   (honesty gate), §3 (definition of done), and your task's body. Then
   `ENGINEERING-STANDARDS.md` in full.
2. **Re-measure the baseline** before changing anything: test count, collected
   count, lint and type error counts. Report any discrepancy against the
   roadmap's recorded numbers *before* proceeding.
3. **Pick a `DQT-xx` task** and respect its dependencies. Do not fix defects
   outside your task — list what you noticed and fix none of it.
4. **Back every claim with an external, executable ground truth** — see
   `docs/HONESTY-GATE.md` for what qualifies in this repo specifically. A
   passing self-referential unit test is not evidence. A docstring is never
   evidence.
5. **For any bug or security fix, prove the test catches the bug:** revert the
   fix, run the new test, show it fails; restore the fix, show it passes. Paste
   both transcripts. `docs/HONESTY-GATE.md` §2 has the exact four steps.
6. **Run the gates** and paste real output:

   ```bash
   python tools/doc_audit.py --root . --path src/dqt --style google --require-example
   python -m pytest --no-header
   python -m pytest --collect-only -q | tail -1     # must not decrease
   python -m ruff check src/ tests/
   python -m ruff format --check src/ tests/
   python -m mypy src/dqt/ --strict
   ```

7. **Report in the roadmap's format** — including `UNTESTED CODE PATHS`,
   `CLAIMS I WEAKENED OR REMOVED`, and `WHAT I DID NOT DO`. A task reported
   `BLOCKED` honestly is a better outcome than one completed by lowering its bar.
8. **Update docs in the same session** if a contract changed. Never edit a
   document to match broken code — fix the code, or mark the claim planned and
   say so.
