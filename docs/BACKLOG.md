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

**Verified:** 2026-08-17 against `origin/main` at `4629925`.

---

## 1. Roadmap task status — and a landing problem

Two roadmap tasks are **complete and independently verified, but their commits
are not on `origin/main`.** They were built in an environment with no push
credentials and exported as `git format-patch` output.

| Task | Local commit | Result | On `origin/main`? |
|---|---|---|---|
| `DQT-02` — parameterize SQL, unify identifier quoting | `a1f6ce7` | 158 → 197 passing; range bounds bound as DBAPI params; `_qualified_table` deleted; `sql/_identifiers.py` the sole quoting authority; 7 supervisor exploits blocked incl. a schema-name vector | **No** |
| `DQT-03` — enforce `read_only`, add `--dry-run` | `7ae3fdc` | 197 → 218 passing; SQLite opened `mode=ro`; `ReadOnlyViolationError` raised before any statement; `apply_cleansing(dry_run=True)` by default; four-hash checksum proof | **No** |

**Consequence, and it is the most urgent item in this file:** the public
repository still contains both defects. `origin/main` has 158 tests, an
unparameterized `range` bound at `rules.py:295-319`, and an unenforced
`read_only`. Anyone who clones the repo today — or reads its docs and starts
work — will either be exposed to the vulnerabilities or will redo two days of
verified work.

**Action:** land `a1f6ce7` and `7ae3fdc` before starting anything else. Nothing
below is worth doing on top of a `main` that is two verified security fixes
behind a local branch.

Remaining roadmap tasks, unstarted as far as this check could determine:
`DQT-01` (README status block), `DQT-04` (regex dead on SQLite), `DQT-05`
(persist cleansing log, implement `revert`), `DQT-06` (exit-code contract),
`DQT-08` (two-PostgreSQL-driver split), `DQT-09` (exception hierarchy),
`DOC-01`/`DOC-02` (documentation gate and debt), `ARC-01` (architecture gate).

---

## 2. New defects — no roadmap ID yet

Found by reading source on 2026-08-17. Each needs an ID assigned by whoever owns
the roadmap; the labels below are placeholders, deliberately in a separate range
so they cannot be mistaken for roadmap IDs.

### `NEW-A` · `dimension` carries two incompatible meanings

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

### `NEW-E` · `PipelineResult.external_analyses` is written and never read

**Severity:** low

The field exists; `reports.py` renders no panel from it. Either render the panel
or delete the field. A field nothing reads is a promise nothing keeps.

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

---

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
