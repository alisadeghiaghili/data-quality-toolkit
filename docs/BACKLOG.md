# DQT — Backlog Supplement

> **This is not the task list.** The authoritative task spec for DQT is
> `ROADMAP.md` in the **Aghili Data Ecosystem engineering standard**
> (`aghili-engineering-standards`), which defines task IDs `DQT-01` … `DQT-09`,
> their dependencies, locked decisions, and per-task acceptance criteria — plus
> the cross-repo `ALL-01`, `DOC-01` … `DOC-04`, and `ARC-01`.
>
> Work from those IDs. This file exists only to record **defects found since
> that roadmap was written that do not yet have an ID**, and to track which
> roadmap tasks have landed *where*.
>
> If an item here ever conflicts with the roadmap, the roadmap wins
> (`00-START-HERE.md` §1).

**Verified:** 2026-08-22 against `origin/main` at `915bb1c`.

---

## 1. Roadmap task status — and a landing problem

This section previously claimed both `DQT-02` and `DQT-03` were complete at
commits `a1f6ce7` and `7ae3fdc` respectively, exported as patches from an
environment with no push credentials. Neither commit exists in this
repository (`git cat-file -t a1f6ce7` and `git cat-file -t 7ae3fdc` both
fail) — that record could not be reproduced and should not have been trusted.

`DQT-02` has since actually been implemented, from scratch, in this
repository:

| Task | Branch | Result | On `main`? |
|---|---|---|---|
| `DQT-02` — parameterize SQL, unify identifier quoting | `dqt-02` | 158 → 166 passing; `range` bounds bound as DBAPI params; `_qualified_table` deleted; `sql/_identifiers.py` the sole quoting authority; the exact `DQT-critical-review.md` §1.3 payload plus a malicious-table-name payload blocked in `tests/unit/sql/test_sql_injection.py`, with a revert → fail → restore → pass transcript | **Yes** (merged via PR #3, `e72d93d`) |
| `DQT-03` — enforce `read_only`, add `--dry-run` | `dqt-03` | 166 → 183 passing; `sql/rules.py::_get_connection` opens SQLite `mode=ro` (PostgreSQL: `SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY`, untested — no driver in CI); `sql/cleansing.py::apply_cleansing` raises `ReadOnlyViolationError` (new: `src/dqt/exceptions.py`) before building any mutating statement when `read_only=True`, and separately defaults to `dry_run=True`; `dqt profile` gained `--dry-run`/`--commit`; four-hash checksum proof and a revert → fail → restore → pass transcript in `tests/unit/sql/test_read_only.py` | **Yes** (merged via PR #4, `1b3f917`) |
| `DQT-04` — register a SQLite `REGEXP` function | `dqt-04` | 185 → 190 passing; `sql/rules.py::_get_connection` registers a Python `re`-backed `REGEXP` function on every SQLite connection it opens, behind a bounded (256-entry), length-limited (1000 char) compiled-pattern cache; `_eval_regex` now raises `ValueError` for a malformed pattern before any query runs instead of reporting a false data failure; fail → pass transcript (`sqlite3.OperationalError: no such function: REGEXP` → passing) in `tests/unit/sql/test_rules.py` | **No** (PR open, not merged) |

**Consequence:** `main` (at `915bb1c`) now has both `DQT-02`'s fix (PR #3,
`e72d93d`) and `DQT-03`'s fix (PR #4, `1b3f917`) merged. `read_only`
enforcement is real on `main`: `sql/rules.py::_get_connection` opens SQLite
`mode=ro`, and `sql/cleansing.py::apply_cleansing` raises
`ReadOnlyViolationError` before building any mutating statement when
`read_only=True` (`git grep -n read_only -- src/` and
`git grep -n ReadOnlyViolationError -- src/ tests/` both show it wired
through; see `tests/unit/sql/test_read_only.py`). The full suite passes: 185
tests (`pytest -q`).

**Action:** none — both fixes are merged. The one gap that remains is the
PostgreSQL side of the same enforcement (`SET SESSION CHARACTERISTICS AS
TRANSACTION READ ONLY`): it is still untested, since there is no PostgreSQL
driver or server available in CI.

`DQT-04` (SQLite `REGEXP` registration) has since been implemented on branch
`dqt-04` (see the table above) — a PR is open but not yet merged.

Remaining roadmap tasks, unstarted as far as this check could determine:
`DQT-01` (README status block), `DQT-05` (persist cleansing log, implement
`revert`), `DQT-06` (exit-code contract), `DQT-08`
(two-PostgreSQL-driver split), `DQT-09` (exception hierarchy),
`DOC-01`/`DOC-02` (documentation gate and debt), `ARC-01` (architecture gate).

### Update 2026-09-04 — `DQT-04` merged, `DOC-01` partially landed

`DQT-04` is merged: PR #7, merge commit `c80eb63`. `main` now carries the
SQLite `REGEXP` registration; the README bullet that called it an open defect
was removed on branch `dqt-01`.

**`DOC-01` — the DQT slice landed on branch `doc-01`; the task is NOT closed.**
The roadmap scopes `DOC-01` to three repositories (`MSY`, `DQT`, `PDP`) and its
acceptance criteria require the gate wired into CI in **all three**. Only the
`DQT` slice is done. The `MSY` and `PDP` slices remain outstanding and
`DOC-01` stays open until they land.

Doing DQT alone was a deliberate sequencing decision, not an oversight: the
gate's value is per-repo with no technical coupling between the three, and
14 of the 30 baselined violations sit in `common/models.py`, which units 5 and
6 of `docs/PLAN-TDD.md` rewrite. Delaying DQT's gate to bundle three repos
would let those rewrites land ungated — which is precisely what the task
exists to prevent.

**Count drift, and what was fixed rather than baselined.** The roadmap records
29 violations for `DQT` measured 2026-08-12; re-measured on `c80eb63` the tree
had **31**. The difference is code added since that measurement, so the
acceptance criterion's "exact counts above" is no longer literally
satisfiable. Ratchet mode tolerates existing debt but forbids growth, so debt
introduced by our own recent work was **fixed, not baselined**:
`src/dqt/exceptions.py` did not exist on 2026-08-12 — it was created by
`DQT-03` — and its `missing-example` violation was repaired by writing the
`Example` block the standard requires. The remaining **30** entries are
genuine pre-existing debt in `common/models.py` (14), `ui/app.py` (12) and
four single violations elsewhere; `DOC-02` exists to pay them down.

**Gate proof.** With a baseline matching the tree the gate exits `0`; with a
public function carrying no docstring planted in `src/dqt/`, it exits `1` and
names both the module and the function; with the plant removed it returns to
`0`. Note `NEW-L` below: the committed baseline is in POSIX form because CI
runs on `ubuntu-latest`, and the tool does not normalise path separators, so
the gate is not runnable locally on Windows against that file without
regenerating it.

---

## 2. New defects — no roadmap ID yet

Found by reading source on 2026-08-17. Each needs an ID assigned by whoever owns
the roadmap; the labels below are placeholders, deliberately in a separate range
so they cannot be mistaken for roadmap IDs.

### `NEW-A` · `dimension` carries two incompatible meanings — **fixed**

**Fixed:** 2026-09-05 on branch `new-a-dimension`. `DQMetric.dimension` is now
`DQDimension | None` (the closed six-value `Literal`, exported from `dqt` as
§0.1 requires) and raw measurements moved to a new `metric_name` field.
`__post_init__` enforces exactly one of the two and rejects a dimension
outside the set; four `CHECK` constraints plus one table-level check put the
same rules in the DDL, so direct SQL cannot store what the model would
refuse. The natural-key index now coalesces both fields, closing the
duplicate-row hole that making `dimension` nullable would otherwise open.

**Severity:** high — silently wrong output · **Blocks:** any per-dimension
scoring, trend, or filter

`DQMetric.dimension` and `DQIssue.dimension` are free-form `str`, and the
emitters disagree about what the field means:

| Emitter | Written to `dimension` | Actually a DQ dimension? |
|---|---|---|
| `diagnostics.py` | `completeness` | yes |
| `rules.py` | whatever the rule declares | yes |
| `metrics.py` | `table_count`, `column_count`, `average_completeness` | **no — metric names** |
| `profiling.py` | `row_count`, `completeness` | mixed |

Any `GROUP BY dimension`, per-dimension score, or dimension filter is therefore
wrong today, and the closed six-value vocabulary in `CONVENTIONS-DQT.md` §0.1
cannot be enforced while this holds.

Proposed fix: add a closed `DQDimension` type; add a separate `metric_name` field
to `DQMetric`; make `dimension` optional on `DQMetric` (a row count is a
measurement, not a quality dimension); add `CHECK` constraints on
`run_metrics.dimension`, `run_issues.dimension`, `run_issues.severity`,
`runs.status`. The store is a local SQLite artifact — recreate rather than
migrate, and document that older store files are unreadable.

Interacts with `DQT-05`: the `cleansing_log` table lands in the same DDL, so
doing these together avoids two schema breaks.

### `NEW-B` · `run()` cannot report failure

**Severity:** high — silent failure that looks like health

`run()` hardcodes `result.status = "success"` and wraps no stage in
`try/except`. A failing stage raises before anything is persisted, so
`runs.status` can only ever hold `success`. Any alert built on "failed runs"
reports zero forever.

Proposed fix: per-stage error capture into a `stage_errors` field on
`PipelineResult`; persist partial results; derive status from actual outcomes;
a test for each of the three statuses. Overlaps `DQT-06`'s exit-code contract —
an exit code derived from a status that is always `success` is not a contract.

### `NEW-C` · Six modules have zero unit tests

**Severity:** medium — the coverage gate does not see them

`profiling.py`, `diagnostics.py`, `metrics.py`, `monitoring.py`,
`schema_discovery.py`, `reports.py`. The 80% gate passes on the strength of the
modules that *are* tested, which is how a coverage gate lies.

Order: `diagnostics.py` and `profiling.py` first — they produce the issues
everything else consumes — then `metrics.py` (after `NEW-A` changes its shape),
then the rest. Per the honesty gate, prefer property-based invariants and
seeded-fixture expected values over tests that assert the code does what the
code does.

### `NEW-D` · `src/dqt/ui/` is untested and undocumented

**Severity:** medium

`ui/api.py` is a working read-only data-access layer over `RunStore` returning
plain dicts; `ui/app.py` is a FastAPI skeleton exposing `/runs`,
`/runs/{run_id}`, `/runs/{run_id}/tables`, `/runs/{run_id}/metrics`,
`/runs/{run_id}/issues`, `/health`. Behind the `ui` extra. No tests, no
frontend, and no mention in any conventions doc until now.

The boundary design is sound — no domain models cross it — and should be
preserved as the single data path for every consumer.

Hard constraint regardless of what `DQT-03`/`DQT-05` make technically possible:
**the UI must not expose a cleansing apply action.** A destructive database
operation should require a deliberate CLI invocation; the friction is the
feature.

### `NEW-E` · `PipelineResult.external_analyses` is written and never read — **fixed**

**Severity:** low · **Fixed:** 2026-09-04 on branch `bridges-b1-b3`

The field existed; `reports.py` rendered no panel from it. A field nothing
reads is a promise nothing keeps.

`reports.py::_external_section` now renders it. The panel is omitted entirely
when no bridge ran rather than rendered empty, because an empty "Missing Data"
heading reads as "we looked and found nothing", which is a different claim
from not having looked. It names the analyser and the sampled row count: a
figure computed by a sibling package carries a different warranty from one DQT
computed, and a ratio shown without its sample size presents an estimate as a
census.

### `NEW-F` · No retention policy for `RunStore`

**Severity:** low, until monitoring is real

No pruning code exists. A long-running monitoring deployment grows the store
without bound. Decide a policy — keep N runs, or runs younger than D days, per
connection — and delete through the foreign keys rather than around them.

### `NEW-G` · `monitor()` is a stub

**Severity:** low — honestly declared, so not a lie, just absent

Returns its input unchanged. The storage layer already keeps per-run metrics, so
the data is there; what is missing is comparison across runs. Blocked on `NEW-A`
— trending a field that means two things produces confident nonsense.

### `NEW-H` · CLI silently dropped `rule_files` from `--config` — **fixed, needs a roadmap ID**

**Severity:** was high — silent false negative; **Status: fixed** on branch
`new-h`, not yet assigned a roadmap task ID.

`cli.py::_build_pipeline_config` built a `DQPipelineConfig` from the parsed
config-file dict but forwarded every filter key (`exclude_schemas`,
`include_tables`, `exclude_tables`) except `rule_files`. The practical effect:
`dqt profile --config x.yaml` with `x.yaml` naming `rule_files:` ran the full
pipeline and reported zero rule-engine issues — completeness diagnostics still
fired, but every declared rule (`NOT NULL`, `UNIQUE`, `range`, `regex`) was
silently skipped, with no error or warning. Measured directly: the same rule
file driven through `DQPipelineConfig(rule_files=[...])` in Python reported
issues that the CLI path, given an equivalent `--config` file, did not.

Fixed by forwarding `file_cfg.get("rule_files", [])` into the built
`DQPipelineConfig`, proven by a red-then-green test pair in
`tests/unit/test_cli.py` (`test_build_pipeline_config_forwards_rule_files`,
`test_profile_cli_applies_rule_files_from_config`) driven through `main()`
against a hand-seeded SQLite fixture with one enumerated `NOT NULL` violation.
No CLI-level rule-file flag exists; this fix only closes the config-file path.

---

### `NEW-M` · Cleansing addresses rows by SQLite's `rowid`

**Severity:** high — cleansing is unusable on PostgreSQL · **Found:** 2026-09-05,
by the first CI run that ever pointed DQT at a real PostgreSQL server

`sql/cleansing.py` locates rows with `rowid`: `SELECT rowid AS dqt_row_id`,
`UPDATE ... WHERE rowid = ?`, and `row_key={"rowid": ...}` in the log. `rowid`
is a SQLite implementation detail. PostgreSQL raises

    psycopg.errors.UndefinedColumn: column "rowid" does not exist

so `cleanse_plan`, `cleanse_apply` and `revert` all fail there. `DQT-08` moved
identifier quoting, the read-only incantation and regex matching into the
dialects; row identity was missed because nothing exercised cleansing on a
second dialect. It stayed invisible for the same reason the `read_only` gap
did: PostgreSQL was declared supported and never run.

**Not a one-line substitution.** Three distinct problems:

1. `_standardize` and `_lookup_correct` need only a row locator, so a dialect
   method returning `rowid` / `ctid` / `%%physloc%%` would carry them.
2. `_deduplicate` orders by `MIN(rowid)` / `MAX(rowid)` to choose which
   duplicate to keep. PostgreSQL has no aggregate over `tid`, so there is no
   direct translation — the "keep first" rule has to be re-expressed, most
   likely over the primary key.
3. **`ctid` is not stable.** It changes when a row is updated and can move
   under `VACUUM FULL` without the data changing at all. A `plan_id` is
   applied and reverted in a later process, so a plan holding `ctid`s could
   address the wrong rows. The plan fingerprint catches a data change but not
   a physical relocation.

Proposed fix: address rows by **primary key** where the table has one, which is
stable, portable, and what an audit log should record anyway; fall back to a
dialect-provided physical locator only for tables without one, and say plainly
in the docs that cleansing such a table is best-effort. Refuse rather than
generate invalid SQL where a dialect cannot express the operation at all.

Tracked by an `xfail(strict=True)` in
`tests/integration/test_postgresql.py`, so fixing this forces the marker off
rather than leaving it to rot.

### `NEW-K` · `expression` is documented as accepting SQL, but does not

**Severity:** medium — a false docstring on a public field · **Blocks:** nothing

`common/models.py:395` documents `RuleConfig.expression` as "A DSL keyword or
SQL fragment defining the check". There is no SQL-fragment path.
`sql/rules.py:645` normalises the field with
`expr = rule.expression.strip().upper()` and dispatches over a closed set —
`NOT NULL`, `UNIQUE`, `RANGE`, `REGEX` — emitting an error-severity `DQIssue`
for anything else (`rules.py:752-764`). A SQL fragment placed in that field is
not executed; it is reported as an unknown expression.

The docstring is therefore false, and it undersells the design: a closed
keyword set has **no SQL injection surface at all**, which is a stronger
safety property than the docstring implies. `DQT-02` parameterised the rule
*parameters*; this field was never an injection vector in the first place.

Proposed fix: correct the docstring on both `models.py:395` and `models.py:600`
to describe the closed vocabulary, and say plainly that unknown values produce
an error-severity issue rather than being executed. Consider narrowing the type
to a `Literal` so the closed set is enforced at validation time instead of at
dispatch time — that is a behaviour change and needs an owner decision.

### `NEW-L` · `doc_audit.py` baseline keys are not portable across platforms

**Severity:** medium — the gate cannot be run locally on Windows · **Blocks:**
nothing in CI · **Found:** 2026-09-04, while landing `DOC-01`

`Violation.key()` is `path::qualname::rule`, and `path` is emitted with the
**native** separator. The tool never normalises it: a baseline written on
Windows contains `src\dqt\common\models.py::...`, one written on Linux
contains `src/dqt/common/models.py::...`, and neither is accepted by the other.
Every entry then reads as a new violation and the gate exits `1`.

Consequence for this repo: `.doc_audit_baseline.json` is committed in POSIX
form because the gate's enforcement point is CI on `ubuntu-latest`, where it is
correct and green. A developer on Windows cannot run the gate locally against
the committed baseline without regenerating it first.

This is **not** `DOC-04`. `DOC-04` concerns two symbols colliding on one
`path::qualname::rule` triple — the roadmap measures `data-quality-toolkit` at
0 colliding keys. This is a separate portability defect in the same `key()`
function, and both are fixed in the same place.

Proposed fix: normalise the path to POSIX form inside `Violation.key()`
(`PurePath(path).as_posix()`) before composing the key, then regenerate every
baseline. The tool is vendored verbatim from the engineering standard and the
roadmap says not to rewrite it, so this must be fixed upstream in the standard's
copy and re-vendored — not patched here.

### `NEW-M` · The declared version claimed a release that never happened

**Severity:** low — a false claim, not a runtime fault · **Found:** 2026-09-04

`pyproject.toml` and `src/dqt/__init__.py` both declared `0.1.0` from the
beginning, while `git tag -l` is empty, no package has been published, and
`docs/PLAN-TDD.md`'s own cut line defines v0.1 as its units 1-9 — of which
three have landed. The number asserted a release that does not exist and a
maturity the project had not reached.

A version string is a claim, and `docs/HONESTY-GATE.md` governs claims. Fixed
by setting `0.1.0.dev0`, which states the intent without asserting the
release. `0.1.0` becomes true when units 1-9 land and the tag is cut.

Remaining gap: there is still no release process — no tagging convention, no
deprecation policy, and until now no `CHANGELOG.md`. `CHANGELOG.md` is added
alongside this fix; the other two are listed as hard gates for 1.0.0 in
`docs/PROPOSAL-v1.0-roadmap.md` and need an owner decision.

## 3. Open design questions — owner decisions, not agent decisions

Each of these is a place where the conventions in this doc set propose something
the implemented code does not do. Per the roadmap's precedence rule, a conflict
about *what the software should do* is escalated, not resolved unilaterally.
They are recorded here so nobody implements one by assuming it was settled.

**Q1. Should `cleanse` stay on the `run()` call path?**
`run()` calls `self.cleanse(result)` unconditionally at stage 5; it reaches a
pass-through today. `DQT-03` addressed the danger with read-only enforcement and
`dry_run=True` by default. `CONVENTIONS-DQT.md` §1 proposes something stronger —
removing the call entirely in favour of separate `cleanse_plan()` /
`cleanse_apply()` entry points — on the grounds that a profiling run should not
be *structurally capable* of mutating what it profiles. These are two different
safety philosophies (defence in depth vs. separation of paths) and both are
defensible. **Not decided.**

**Q2. `plan`/`apply` with a `plan_id`, or `--dry-run`?**
`DQT-03` shipped `dry_run`. `CONVENTIONS-DQT.md` §1 (S2) specifies a stricter
four-condition `apply` mode requiring a preceding plan run whose `plan_id` is
passed in. The stricter form is a superset; whether the extra ceremony is worth
it is an owner call. **Not decided.**

**Q3. Is `DELETE` permitted as a cleansing primitive?**
Deduplication currently uses `DELETE` with a `not_null_guard` added during the
Phase 0 remediation. `CONVENTIONS-DQT.md` §1 (S5) proposes banning it in v0.1 in
favour of mark/quarantine. That would change existing, tested behaviour.
**Not decided.**

**Q4. Separate read and write connections?**
`CONVENTIONS-DQT.md` §1 (S1) proposes two separately credentialed connections so
the read-only guarantee is auditable by a DBA who is not reading the source.
`DQT-03` instead enforces read-only on the single connection (`mode=ro` on
SQLite). The proposal is stronger but is a larger change and interacts with
`DQT-08`'s driver decision. **Not decided.**

Until each of these is decided, the corresponding text in `CONVENTIONS-DQT.md`
§1 is marked as a proposal, not as a requirement.

---

## 4. Not in v0.1 — and not by accident

Do not open these, and do not accept a change that quietly adds one:

- Service or performance monitoring — latency, CPU, wait stats, uptime.
- Masking, compliance tooling, or MDM / golden-record features.
- Pandas/DataFrame analysis as a first-class path.
- A third SQL dialect, until a `dqt/sql/dialects/` abstraction exists.
- New hard dependencies. Optional capability goes behind an extra.
- Merging DQT into the other ecosystem packages — explicitly rejected in the
  roadmap §2.3, because it would import DQT's open security debt into the one
  credible asset.
