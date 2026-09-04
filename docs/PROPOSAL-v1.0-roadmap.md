# DQT — A Critical Roadmap to 1.0.0 (Proposal)

**Status: proposal for the owner's decision. Not authoritative. Not a task
list.** Written 2026-09-04 against `main` at `c80eb63` (190 tests passing,
~85.25% line coverage, all four gates green — re-verified while writing this
document; see § Verification log at the end).

---

## 0. Rank of this document — read this before anything else below

`docs/00-START-HERE.md` §1 defines a strict source-of-truth hierarchy and is
explicit that the authoritative task list is `ROADMAP.md`'s task bodies
(`DQT-01`…`DQT-09`, `ALL-01`, `DOC-01`…`DOC-04`, `ARC-01`) inside the
`aghili-engineering-standards` skill — a resource that governs this repository
but is **not installed on this machine**. It could not be read while writing
this document. `AGENTS.md` §11 and `docs/PLAN-TDD.md`'s own status header say
the same thing in their own words: no document written from inside this repo
may invent a task list that competes with that roadmap.

Consequences, stated plainly so nothing below is misread:

- This document **ranks below `ROADMAP.md`**, below `AGENTS.md`'s scope
  section, below `ROADMAP.md` §2.3/§2.4, and below every rank in
  `docs/00-START-HERE.md` §1's table. It sits alongside — not above —
  `docs/dqt_competitors.md`, `docs/dqt_ecosystem.md`, and
  `docs/DQT-UI-Ecosystem.md` at rank 12 ("context, comparisons, design
  direction. Never normative").
- **It assigns no task IDs.** Every `DQT-xx` or `NEW-x` identifier that
  appears below is a **citation** of an identifier that already exists in
  `ROADMAP.md` or `docs/BACKLOG.md` §2 — never a new assignment. Where this
  document names a gap that has no existing ID, it says so explicitly and
  does not invent one, following the same discipline `docs/BACKLOG.md`
  already uses for its own `NEW-x` placeholders.
- **It does not re-plan `docs/PLAN-TDD.md`.** That document's `§ Scope and
  cut line` already defines v0.1 as its units 1–9, in a specific order, with
  stated dependencies. This proposal treats that cut line as settled and
  builds forward from it — it does not re-sequence, re-estimate, or second-
  guess units 1–9. Where this document's release ladder (§6) names a rung
  that overlaps `PLAN-TDD.md`'s units 10–16, it cites those units by number
  rather than restating their content.
- **Nothing in this document is settled until the owner accepts it.** Every
  recommendation below is a recommendation. Where this document disagrees
  with the analytical brief it was written against, it says so in the body,
  not by silently softening the disagreement — see the pushback items
  flagged inline in §3.2, §4, and §6.

---

## 1. What 1.0.0 has to mean

For a library, `1.0.0` is not "the most features." It is a promise: **the
public API will not break without a major-version bump.** SemVer's own
definition is exactly this — everything else DQT might want to claim about
"1.0" (stability, maturity, feature completeness) is marketing unless it
reduces to that one promise being kept.

DQT's public API today, per `docs/CONVENTIONS-DQT.md` §5, is the export list
from `dqt/__init__.py`: `DQTPipeline`, `PipelineResult`, `SchemaResult`,
`TableResult`, `ColumnResult`, `DQIssue`, `DQMetric`, `Rule`, `RuleConfig`,
`RuleResult`, `RuleRunResult`, `RuleScope`, `SamplingConfig`,
`ConnectionConfig`, `DQPipelineConfig`, `IssueSeverity`, `RuleStatus`,
`RunStatus`, plus the loader functions and `__version__`. In the broader
sense a compatibility promise has to cover, it also includes: the CLI's
flags and exit codes (`dqt profile ...`), the config-file schema `dqt`
accepts, and — if it ships inside the freeze at all, see §4 — the six
read-only HTTP endpoints in `src/dqt/ui/app.py`.

**The bar this document holds every candidate item to:** an item earns a
place in this roadmap only if it changes what shape of that API needs to be
frozen — either because it is *already* in the surface and currently wrong
or unsettled in a way that would force a breaking change later if fixed
post-1.0, or because *not* building it now means committing to its absence
as part of the frozen contract. Everything else — a new dimension's
diagnostics logic, a new rule type evaluated through the existing closed
set, a new cleansing operation added to the existing `operation: Literal[...]`
— is a normal, additive, post-1.0 minor-version change and does not need to
exist before the freeze. This reframing matters because it is the test this
document applies throughout §§3–5: not "would this be good to have" but "does
1.0.0 become a lie without it."

Two concrete consequences of that framing, both argued in more detail below:

- `DQMetric.dimension`/`metric_name` (`NEW-A`, `docs/BACKLOG.md` §2) and the
  cleansing entry points' final shape (`docs/BACKLOG.md` §3 Q1/Q2, settled
  2026-08-26, not yet implemented — see §3.3) **must** be right before 1.0,
  because both are public-API shape questions, and getting the shape wrong
  and fixing it after 1.0 is exactly the kind of break SemVer exists to
  prevent.
- Whether all six canonical dimensions have diagnostics logic behind them
  is **not**, by itself, a 1.0 blocker — adding `validity` diagnostics in
  1.1 does not break anyone's code that already handles `DQIssue` objects
  carrying a `dimension` field from the closed six-value set. What *is* a
  blocker is the field's *shape* being wrong today (§3.3, `NEW-A`), not the
  *coverage* being incomplete.

DQT is currently `0.1.0`, marked pre-alpha, with **no `CHANGELOG.md`** in
this repository (verified absent) and no written deprecation policy anywhere
in the doc set. Freezing an API that has never been versioned, against a
tool with 190 tests and no PostgreSQL CI coverage of its central safety
claim, is the actual distance between here and 1.0.0 — not a feature count.

---

## 2. The current positioning is a liability

`docs/dqt_ecosystem.md`'s `DQT (target v1.0)` row (line 61) scores `✓✓` or
`✓` on all thirteen facet columns except one (`Cleansing: ✓`,
`Impute (ext): ✓ (bridges)`) — profiling, diagnostics, rules, metrics,
monitoring, knowledge, classification, missingness, reports, viz/UI, and
extensibility are *all* rated at or near the top of the scale for the same
tool. `docs/dqt_competitors.md` §3's "Floor (must be solid before v0.1.0
release)" list reads the same way: SQL profiling, diagnostics *across all
six dimensions*, a rule engine covering *both* column and table scope, safe
cleansing, core metrics, a monitoring/trend layer, HTML reports, and tested
public APIs — nearly the entire facet model, all at "solid" before even
v0.1. Read together, the two documents commit DQT to being strong
everywhere rather than to being the best available option for one
well-defined job. With a single maintainer (per `CLAUDE.md`'s own delegation
model — one person plans, reviews, and implements this entire codebase),
that is not an ambitious plan, it is a plan for twelve mediocre facets and
zero excellent ones. Say this plainly rather than softening it: the target
row's own numbers are the evidence against the target row's own framing.

`docs/dqt_competitors.md` itself already half-concedes this. Its §2.3 entry
for Baselinr — "the closest direct competitor" — states outright:
"Baselinr already delivers most of DQT's target row. DQT's defensible
differentiation is DBA-first framing, a lean dependency footprint, and
bilingual EN/FA reporting — not feature count." That sentence is the correct
thesis and it is buried in a competitor footnote instead of driving the
roadmap. §3 of this document proposes making it the roadmap.

**A documentation defect found while writing this section, not filed under
any ID (see `docs/BACKLOG.md` §2's own convention for unIDed defects —
this is not added there, since this proposal must not modify
`docs/BACKLOG.md`):** the `DQT (target v1.0)` row in `docs/dqt_ecosystem.md`
sits inside the same comparison table, in the same bold row-name styling and
the same `✓✓`/`✓`/`~`/`-` checkmark grid, as real, currently shipped
competitors (Great Expectations, Soda Core, Baselinr, SQL Server DQS, and
others whose `Status` column reads `Active` or `Commercial`). The table does
carry a `Status` column showing `—` for the target row, and the document's
own header notes explain the current/target split was added specifically to
fix an earlier version of this exact problem (a single row that "compared a
plan to a product"). That fix is real but partial: a reader scanning the
checkmark columns — not the `Status` column — could still read `DQT (target
v1.0): ✓✓ Profiling, ✓✓ DQ Diagnostics` as a claim about the shipped tool,
which is exactly what `docs/HONESTY-GATE.md` and `AGENTS.md`'s honesty gate
exist to prevent elsewhere in this project. Recommendation: visually
separate the target row from the comparison grid entirely (a second, small
table, or italics plus a footnote rule) rather than relying on a single
`Status` cell to carry the distinction.

---

## 3. The defensible wedge

Four claims, each checked against what is actually built, not what is
planned.

### 3.1 Operational databases, not warehouses

`docs/CONVENTIONS-DQT.md` frames DQT as "SQL DB Data Quality Toolkit
(DBA-focused)" (line 26) with scope explicitly excluding
service/performance monitoring, masking/compliance, and MDM (lines 33–34).
Every competitor `docs/dqt_competitors.md` records is warehouse- or
pipeline-oriented by its own description: Great Expectations is
"cross-platform (pandas, Spark, SQL, warehouses)" (§2.1); Soda Core is
explicitly "warehouse-native design" (§2.2); Baselinr is "open-source data
quality and observability for SQL warehouses" with "dbt/Airflow/Dagster
integration" (§2.3); Talend and SQL Server DQS both carry masking/compliance
breadth DQT explicitly excludes. None of this is a claim that these tools
are *unsafe* against an operational database — it is that their own
architecture (dbt models, Airflow DAGs, warehouse-native SQL dialects)
presupposes a warehouse deployment DQT does not. That is a real, citable
difference in target environment, not a positioning claim invented for this
document.

### 3.2 Read-only-by-default safety — real, but not yet universal

This is DQT's strongest already-built differentiator, and also the one
where this document's evidence forces a correction to the brief it was
written against.

**What is actually true, verified against `main` at `c80eb63`:**
`sql/rules.py::_get_connection` (lines 203–260) opens SQLite via the
`file:<path>?mode=ro` URI form and sets PostgreSQL sessions to
`SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY` immediately after
connecting; `sql/cleansing.py::apply_cleansing` raises
`ReadOnlyViolationError` (defined in `src/dqt/exceptions.py`) before
building any mutating statement, independently of the connection-layer
guard. Both are backed by `tests/unit/sql/test_read_only.py`'s four-hash
checksum proof, per `docs/BACKLOG.md` §1's own table.

**What undercuts the "structurally incapable of mutation" framing today,
also verified:**

1. **`sql/schema_discovery.py::connect_sql` (lines 74–104) is a second
   connection-opening path that does not consult `read_only` at all.** Read
   in full: it calls `sqlite3.connect(db_path)` directly (no `mode=ro`) and
   `psycopg.connect(dsn)` directly (no `TRANSACTION READ ONLY`) — grep
   confirms zero occurrences of `read_only` anywhere in the function. A
   connection returned by this path can write to the database regardless of
   `ConnectionConfig.read_only`. `docs/PLAN-TDD.md` unit 9 already found
   this and named it `NEW-I`, folding its fix into `DQT-08`'s consolidation
   rather than scheduling it separately — this document does not re-plan
   that, it only notes that **until `DQT-08` lands, the wedge's central
   safety claim is not actually connection-layer-universal**, only "true
   everywhere the rules engine's own helper happens to be used." No live
   exploit exists today (`discover_schema` and `SqlProfiler` only ever
   `SELECT` through this path, per the same unit's own reading) but the
   *guarantee* — the thing being sold as a differentiator — is narrower than
   advertised until the two connection-opening functions become one.
2. **`DQTPipeline.run()` still calls `self.cleanse(result)` unconditionally**
   (`sql/pipeline.py` lines 162–163, "Stage 5: cleansing (stub)"), even
   though `docs/BACKLOG.md` §3 Q1 was settled 2026-08-26 (per
   `docs/PLAN-TDD.md`'s own annotation) *in favor of removing that call* —
   "a profiling run must not be structurally capable of mutating what it
   profiles." That decision exists on paper, not in code. Today, a
   profiling run is *safe* only because `cleanse()` reaches a pass-through
   and because `DQT-03`'s guard stands between it and the database — which
   is precisely the single-point-of-failure pattern the settled decision
   itself rejects.
3. **The PostgreSQL half of `read_only` enforcement has never executed.**
   `_get_connection`'s own docstring says so directly: "Untested in this
   repository: there is no PostgreSQL driver or server available in CI."
   `docs/BACKLOG.md` §1 confirms: "The one gap that remains is the
   PostgreSQL side of the same enforcement... it is still untested." Given
   §3.1's claim that operational Postgres is the target environment, this
   is not a peripheral gap — it is untested on the one database this wedge
   is actually about. This is also why §5's first hard gate is
   non-negotiable rather than merely desirable.

**Correction to the analytical brief this document was written against:**
the brief's framing — "no competitor offers" a read-only-by-default safety
model — is directionally right (no tool in `docs/dqt_competitors.md` claims
anything like a connection-layer read-only guarantee) but overstates DQT's
own current position. As built today, the guarantee has one known bypass
path, one untested dialect, and one still-live call site the owner's own
settled decision says should not exist. §5 turns each of these into a named
gate rather than letting the wedge claim outrun what is actually true.

### 3.3 Reversible, audited cleansing with a `plan_id` — the strongest pillar, and the least built

Talend and SQL Server DQS both do cleansing (`docs/dqt_competitors.md` §2.5;
`docs/dqt_ecosystem.md` line 66) but neither exposes an addressable,
independently revertible plan — `docs/DQT-UI-Ecosystem.md`'s own note on
OpenRefine (§ "Borrow: ... the treatment of undo as a first-class product
feature rather than a log") is the closest existing articulation of why this
matters: reversibility as a feature the user can point at and invoke, not
prose in an audit log a human has to reconstruct by hand. `docs/BACKLOG.md`
§3 (Q1, Q2) and `docs/CONVENTIONS-DQT.md` §1 S4 already draw this exact
distinction — "a log that merely records enough for a human to reconstruct
the change by hand is an **audit trail**, not reversibility."

**What is actually built today: nothing.** Verified directly:

- No `revert()` or `undo()` function exists anywhere in `src/dqt/` (grep for
  `def revert` across `sql/cleansing.py` and `common/storage.py` returns
  nothing).
- No `cleansing_log` table exists in `common/storage.py`'s schema (grep
  confirms zero occurrences).
- `CleansingLog` (`sql/cleansing.py` line 122) is an in-memory `@dataclass`
  only; its module docstring's claim of "reversible, auditable" primitives
  (line 5, restated at line 21) is false today by `docs/HONESTY-GATE.md`'s
  own standard — a claim with no test behind it. `docs/PLAN-TDD.md`'s own
  "§ Claims currently unproven" names this as one of two confirmed-false
  claims in the codebase.
- Deduplication's `_deduplicate()` (`sql/cleansing.py` lines 391–398) does
  already capture the full pre-delete row via
  `_fetch_all_dicts(cursor, f"SELECT * FROM {tbl} WHERE rowid = ?")` before
  deleting — this is real, and it is the one piece of groundwork an
  automated revert could build on. It is not, itself, reversibility.
- The `cleanse_plan()`/`cleanse_apply()`/`revert(plan_id)` design that would
  make the claim true is fully specified in `docs/PLAN-TDD.md`'s "Unit 6
  reshaped design" section (added 2026-09-04) — two new storage tables
  (`cleansing_plans`, `cleansing_log`, both keyed by `plan_id`), a redefined
  `--dry-run`, and a deprecated `--commit`. None of it has a single line of
  implementation yet.

This is the honest state of DQT's single strongest differentiator: it is a
design document, not code. Every other pillar in this section has *some*
shipped, tested substance behind it (§3.1 is architectural framing that
needs no code to be true; §3.2 has real, checksum-proven code with named
gaps). This one has a docstring making a false claim and a plan to fix it.
If this document's central bet is that the `plan_id`-addressable revert is
what makes DQT worth using over Talend or SQL Server DQS, that bet is
currently unfunded, and §6 treats it accordingly — as a release rung on its
own, not folded into "v0.1 cleanup."

### 3.4 Regional semantic classification

`docs/CONVENTIONS-DQT.md`'s facets table already lists, as the Classification
facet's own example set: "Semantic typing (email, phone, IBAN, national
id)" (line 213) — "national id" and "IBAN" are already named there, not
invented for this document. `docs/dqt_competitors.md` (line 108) and
`docs/CONVENTIONS-DQT.md`'s Reports facet ("bilingual EN/FA", line 216)
already commit DQT to bilingual output, and `docs/DQT-UI-Ecosystem.md`
(line 85) references RTL requirements from the `dqt-ui-designer` skill.
Those three facts are the actual textual support for a regional-classifiers
angle in the existing doc set.

**What is not textually supported and must be stated as this document's own
proposal, not a grounded finding:** an Iranian national-ID checksum
validator, Sheba/IBAN validation specific to Iranian bank routing, Shamsi
calendar date handling, and Persian text normalization do not appear
anywhere in `docs/CONVENTIONS-DQT.md`, `docs/BACKLOG.md`,
`docs/dqt_competitors.md`, `docs/dqt_ecosystem.md`, or
`docs/DQT-UI-Ecosystem.md`. No competitor in `docs/dqt_competitors.md`
serves this niche, and it is genuinely underserved by every general-purpose
tool in that document — that much is a fair inference from an honest
absence. But the specific shape of the proposal is new, not found. Treat it
as a candidate wedge extension pending owner sign-off, not as a documented
gap the way §3.2/§3.3's gaps are documented gaps.

**Current build state: zero.** `knowledge.py` and `classification.py` do
not exist anywhere under `src/dqt/` (confirmed by listing the package —
present modules are `_identifiers.py`, `cleansing.py`, `diagnostics.py`,
`metrics.py`, `monitoring.py`, `pipeline.py`, `profiling.py`, `reports.py`,
`rules.py`, `schema_discovery.py`, plus `ui/api.py` and `ui/app.py`). This
is the facet with the largest gap between "plausible niche" and "anything
built," and building it means owning reference data (national-ID checksum
algorithms, Sheba validation rules, a Shamsi calendar library) with its own
ongoing correctness and maintenance burden — a different kind of work than
anything else in this roadmap, and one person's worth of new domain
expertise to acquire and keep current.

---

## 4. What to cut or defer past 1.0.0

| Cut | What is given up | Why the trade is worth it | Evidence |
|---|---|---|---|
| Full interactive dashboard UI | A competitive UI against OpenRefine, Talend, and DataLens, all with years of head start and, per `docs/DQT-UI-Ecosystem.md`'s own target-complexity note, a "Low–Medium" ambition even at target | Keep the read-only FastAPI surface (`src/dqt/ui/api.py`, `ui/app.py`) and self-contained HTML reports. `docs/DQT-UI-Ecosystem.md` itself borrows this exact reasoning from Great Expectations Data Docs: "a static, self-contained, shareable HTML artifact is often more useful to a DBA than a server-backed dashboard." A frontend does not serve the wedge in §3 at all. | `ui/api.py` and `ui/app.py` measured at **0% test coverage** in this session's `pytest --cov` run (31/31 and 37/37 lines uncovered) — "no tests, no frontend" is not a stale claim, it is the state right now. |
| MySQL support | A fourth dialect some users will ask for | Permanent non-goal, already decided and consistently stated across `docs/CONVENTIONS-DQT.md:240`, `AGENTS.md`, and `docs/BACKLOG.md` §4 ("do not open these, and do not accept a change that quietly adds one"). No driver, no discovery implementation exists; nothing in this proposal disturbs that. | `docs/CONVENTIONS-DQT.md` line 240. |
| Drift/anomaly detection (statistical trend analysis, alerting) | Competing with dedicated observability tooling — Baselinr's drift/anomaly detection, Soda Cloud's alerting, MobyDQ's indicator-failure alerts | `monitor()` is a four-line stub returning its input unchanged, and `docs/BACKLOG.md` `NEW-G` is explicitly blocked on `NEW-A` ("trending a field that means two things produces confident nonsense") | `sql/monitoring.py`; `docs/BACKLOG.md` `NEW-G`. |

**Pushback on the third row, stated plainly because the brief asked for it
where the evidence does not support the cut as written.** "Defer all
monitoring beyond simple metric snapshotting" is right for *drift and
anomaly detection* — that is genuinely out of scope for a single maintainer
and genuinely a different product (observability tooling). It is **wrong**
to cut monitoring so completely that 1.0 ships with `README.md`'s own claim
still standing unbacked: "Metrics and storage — persist per-run metrics and
issues to a local SQLite store, **so runs can be compared over time**"
(README.md line 27, emphasis added). `RunStore` already persists per-run
metrics (`common/storage.py`, tested, per `docs/00-START-HERE.md` §3.1); the
missing piece is not statistical drift detection, it is *reading two rows
back and subtracting them* — a two-run delta, not a trend model. Shipping
1.0 with that specific README sentence still false, next to a `monitor()`
that still returns its input unchanged, is the exact doc-vs-reality gap
named as this project's recurring failure mode in §7 below — the project
would be repeating its own named mistake inside the document meant to fix
it. **Recommendation:** either (a) build a minimal, real two-run delta
report before 1.0 — cheap, since the storage layer already exists and
`NEW-A` (§5) is what actually unblocks it, not new infrastructure — or (b)
soften `README.md`'s claim to describe only persistence, not comparison,
until real comparison ships. Cutting *drift detection* is right; cutting
*all monitoring, silently, while leaving the README claim standing* is not,
and this document recommends (a) over (b) because the cost is small and the
credibility cost of (b) — visibly retreating from an existing claim — is
larger than building the two-run delta.

**SQL Server is not on this cut list, deliberately.** The owner already
settled (2026-08-26, recorded in `docs/PLAN-TDD.md`'s "§ Non-goals
reaffirmed" amendment) that SQL Server support is being added, sequenced as
`docs/PLAN-TDD.md` unit 9a, built on the `dqt/sql/dialects/` abstraction
`DQT-08` (unit 9) opens. This document does not revisit that decision; it
only notes in §5 that unit 9a's own deliverable is precisely what satisfies
this roadmap's "third dialect" hard gate, so the two documents are already
aligned without either one repeating the other's content.

---

## 5. Hard gates for 1.0.0 that do not exist today

Each gate below is either explicitly required by the brief this document was
written against, or is a direct consequence of §3's wedge analysis. None of
these exist on `main` today; each entry states the verified current state.

| # | Gate | Current state (verified) | Why it is non-negotiable |
|---|---|---|---|
| 1 | PostgreSQL runs in CI with the full suite | `.github/workflows/ci.yaml` (read in full) has **zero** service containers, zero Postgres-related steps; its matrix varies only `python-version` (`3.11`, `3.12`) across four jobs (lint, typecheck, test-unit, test-integration). `README.md` declares PostgreSQL "supported" (line 32/`primary production target` per `docs/CONVENTIONS-DQT.md` line 239) while it is never exercised. | §3.2's central safety claim — `read_only` enforcement — is untested on the one dialect it is supposed to matter most for. Until this gate closes, "supports PostgreSQL" is an unbacked claim by this project's own honesty-gate standard. |
| 2 | A third dialect shipped | No `dqt/sql/dialects/` package exists (confirmed: `src/dqt/sql/dialects` does not exist). Two DB-API drivers are already used inconsistently for the two dialects that do exist — `sql/rules.py:290` imports `psycopg2` (v2), `sql/schema_discovery.py:98` imports `psycopg` (v3) for the same PostgreSQL support — exactly the single-authority violation `DQT-08` exists to close. | An abstraction validated against one-and-a-half dialects (SQLite plus a PostgreSQL path that is itself split across two drivers) will be shaped wrong. `docs/PLAN-TDD.md` unit 9a already schedules SQL Server as the forcing function; this gate does not re-plan it, it adopts it. |
| 3 | A benchmark suite with published performance budgets | No benchmark code, benchmark directory, or performance test exists anywhere in `tests/` (confirmed by search). `docs/PLAN-TDD.md` unit 16 names the need but is explicitly "not estimated... size it when it is picked up." | "Works on large data" is an unbacked claim — the same standard this document applies to every other claim in this project — until it is measured against a stated number. |
| 4 | API freeze: written deprecation policy + `CHANGELOG.md` | Neither exists (`CHANGELOG.md` confirmed absent from the repository root; no deprecation-policy document anywhere in `docs/`). | This is §1's entire argument restated as a checklist item: 1.0.0 without a changelog and a deprecation policy is a version number, not a promise. |
| 5 | Explicit decision on each of the four missing facet modules | `knowledge.py`, `classification.py`, `viz.py`, and `bridges/` do not exist (confirmed by listing `src/dqt/`). `docs/dqt_ecosystem.md`'s target row scores DQT `✓✓` on Extensibility and `✓` on Knowledge/Classification with zero code behind any of the three. | Per §2, an unmarked gap between target and reality is how this project's ecosystem matrix already misled once. Each of these four must, before 1.0, be either built-and-tested or formally marked cut in `docs/CONVENTIONS-DQT.md` §2 with a stated reason — never left as a silent absence the matrix keeps scoring as aspirational. |

---

## 6. A release ladder

`v0.1` is `docs/PLAN-TDD.md`'s existing units 1–9 cut line, cited, not
re-planned: `NEW-H`, `DQT-04` (both merged already), `DOC-01`, `NEW-C` slice
1, `NEW-A`, `DQT-05`, `NEW-B`, `DQT-06`, `DQT-08`. Everything below starts
from that line being complete.

| Rung | Contents | Exit bar (single falsifiable condition) |
|---|---|---|
| **v0.1** | `docs/PLAN-TDD.md` units 1–9, unchanged | All nine units are merged to `main`, and `ruff check`, `ruff format --check`, `mypy --strict`, and `pytest --cov=src/dqt --cov-fail-under=80` are all green on that state. |
| **v0.2 — Safety proven** | Gate 1 (§5): PostgreSQL in CI. `DQT-09` exception hierarchy (`docs/PLAN-TDD.md` unit 13, already sequenced right after `DQT-05`). | `tests/unit/sql/test_read_only.py`'s four-hash checksum proof runs and passes against a live PostgreSQL service container in CI, on both Python versions, in addition to SQLite. |
| **v0.3 — The wedge is real** | `cleanse_plan()` / `cleanse_apply()` / `revert(plan_id)` per `docs/PLAN-TDD.md`'s unit 6 reshaped design (§3.3 above). `cleanse` made structurally unreachable from `DQTPipeline.run()`'s call graph — not just unreachable by default. | A round-trip checksum test (before-mutation and after-revert states byte-identical) passes for both `standardize` and `deduplicate`, against both SQLite and PostgreSQL, and a static call-graph or import-scan test proves `run()` cannot reach `cleanse_plan`/`cleanse_apply`. |
| **v0.4 — Third dialect and a measured performance budget** | `docs/PLAN-TDD.md` unit 9a (SQL Server via `dqt/sql/dialects/`) and unit 16 (performance/scale), both cited not re-planned. | SQL Server passes the same `discover_schema`/rules/read-only test suite SQLite and PostgreSQL already pass, and a committed benchmark run reports profiling, rule-evaluation, and cleanse-plan timings each under a published budget for a stated fixture size. |
| **v0.5 — Every facet has a decision, not a silence** | Gate 5 (§5): `knowledge.py`, `classification.py`, `viz.py`, `bridges/` — each either built-and-tested (§3.4's regional-classification proposal, if accepted, lands here) or formally marked cut. | `docs/CONVENTIONS-DQT.md` §2's facet table carries no row still reading "not started" with no owner decision recorded next to it. |
| **v0.9 — Freeze candidate** | `CHANGELOG.md` with a full `[Unreleased]` history since `0.1.0`; a written SemVer/deprecation policy; `docs/PLAN-TDD.md` units 14–15 (`ARC-01`, `DOC-02`) landed so the architecture and docstring gates are at a clean baseline going into the freeze. | `doc_audit.py` and `arch_audit.py` both run against an empty baseline (zero tolerated violations), and every symbol in `dqt/__init__.py`'s export list, every CLI flag, and — unless explicitly exempted per §4's UI recommendation — every `ui/api.py` endpoint has a docstring/help text backed by a passing test. |
| **1.0.0** | Every gate in §5 met; every rung above shipped in order. | The owner explicitly signs off, in writing, that the frozen surface (Python exports, CLI flags and exit codes, config-file schema, and the UI HTTP contract if not exempted) is a promise DQT will not break without a major-version bump. |

---

## 7. Risks, named honestly

**Single-maintainer capacity against a twelve-facet surface.**
`docs/PLAN-TDD.md`'s own estimate for *just* its nine v0.1 units is
"17–22 working days across roughly 14–16 PRs... not a handful of PRs, say so
plainly" — and that is before any wedge-building (§3.3, currently zero
lines of code), a third dialect (§5 gate 2), a benchmark suite (§5 gate 3),
or a decision on four entirely absent modules (§5 gate 5). **Mitigation:**
this document's cut list (§4) and phased ladder (§6) are the mitigation —
sequencing safety (v0.2) and the wedge (v0.3) ahead of the more speculative
work (v0.4's third dialect, v0.5's classification module) so the calendar
cost is paid for provable value first. **Accepted, not solved:** the total
calendar time to 1.0.0 is long, and that is an owner-accepted cost of this
plan, not something this document can shrink further without cutting scope
this section has already argued is defensible.

**The doc-versus-reality gap is this project's actual recurring failure
mode, and it recurred while writing this document.** `AGENTS.md` names
Phase 0 by cause: eleven false `[x] DONE` markers, a crashing CLI, all CI
gates red — "things were written, documented as complete, and never
actually run." This document found two live instances of the same pattern,
post-Phase-0, while doing the reading this brief required: `common/models.py`
line 395's `Rule.expression` docstring claiming "a DSL keyword or SQL
fragment" against a closed four-keyword implementation (§2's evidence
carries the file:line citation), and `docs/dqt_ecosystem.md`'s target row
sitting unmarked-enough inside a real-competitor comparison table (§2).
Neither is large. Both are exactly the shape of mistake Phase 0 happened
over. **Mitigation:** `docs/PLAN-TDD.md` units 3 (`DOC-01`) and 14 (`ARC-01`)
are already scheduled and already the correct mechanism — this document adds
nothing new here except the observation that the pattern is still live, so
neither gate should be treated as closing out historical debt only.
**Owner:** whoever picks up those two units; no new owner is proposed here.

**The dialect abstraction risks being designed at the wrong time.**
`docs/PLAN-TDD.md` unit 9a already carries this exact risk analysis in full
— building `dqt/sql/dialects/` before `DQT-08`'s connection consolidation
means building it against the pre-consolidation two-driver shape and
rebuilding it after; building it too late means shipping SQL Server later
than the owner might want. That unit's own text states the tradeoff and
flags its recommended sequencing as owner-overridable. **This document does
not re-argue it** — it is cited here only so this risk section is complete,
per the brief's instruction to name it; the actual analysis lives in
`docs/PLAN-TDD.md` unit 9a and should not be duplicated. **Owner:** whoever
picks up unit 9a, per that unit's own explicit override clause.

**The wedge itself might be wrong.** §3.3 (cleansing with `plan_id`) and
§3.4 (regional classification) are, respectively, a fully-specified design
with zero implementation and a proposal with almost no grounding in the
existing doc set at all. If DQT's actual users turn out to want warehouse
support, or a dashboard, more than they want DBA-safe operational tooling
and reversible cleansing, most of §4's cut list would need revisiting and
most of this ladder's later rungs would be pointed at the wrong target.
**Mitigation:** none is built into this plan beyond sequencing — v0.3 tests
the cleansing half of the bet before v0.4/v0.5 spend calendar time on the
dialect and classification halves, so if the bet is wrong it is found out
after the cheaper half of the wedge, not after all of it. **Accepted risk,
owner-carried:** this document cannot de-risk a product bet by writing
about it more carefully; that is the owner's call to make and revisit, most
naturally at the v0.3 checkpoint.

---

## Verification log

Commands run against `roadmap-v1` (branched from `main` at `c80eb63`) while
writing this document, in addition to the source reads cited inline above:

- `git show main:src/dqt/sql/rules.py` — confirmed the closed four-expression
  set (`NOT NULL`, `UNIQUE`, `RANGE`, `REGEX`) at lines 645–751, the
  `else:` unknown-expression branch at line 751, and `_get_connection` at
  line 203.
- `git show main:src/dqt/common/models.py` — confirmed the `Rule.expression`
  docstring at line 395 and the equivalent `RuleConfig.expression` docstring
  at line 600.
- `git show main:src/dqt/sql/diagnostics.py` — confirmed `completeness`-only
  scope (line 6, line 58).
- `git show main:src/dqt/sql/pipeline.py` — confirmed `result.status =
  "success"` hardcoded (line 172) and `self.cleanse(result)` called
  unconditionally at stage 5 (lines 162–163).
- Read `src/dqt/sql/schema_discovery.py` lines 74–104 in full — confirmed
  `connect_sql` never references `read_only`.
- `grep -n "import psycopg"` across `sql/rules.py` and
  `sql/schema_discovery.py` — confirmed the two-driver split (`psycopg2` at
  `rules.py:290`, `psycopg` at `schema_discovery.py:98`).
- `grep -n "def revert\|cleansing_log"` across `sql/cleansing.py` and
  `common/storage.py` — zero matches for either.
- Listed `src/dqt/`, `src/dqt/sql/`: confirmed absence of `knowledge.py`,
  `classification.py`, `viz.py`, `bridges/`, and `dialects/`.
- Confirmed absence of `CHANGELOG.md` and `tools/` at the repository root.
- `.github/workflows/ci.yaml` read in full — confirmed no PostgreSQL service
  container and a `python-version` matrix of `3.11`/`3.12` only, across all
  four jobs.
- `PYTHONPATH=src python -m pytest` — **190 passed** (11.86s).
- `PYTHONPATH=src python -m pytest --cov=src/dqt --cov-report=term-missing`
  — **85.25%** total coverage; `src/dqt/ui/api.py` and `src/dqt/ui/app.py`
  both at **0%** (31/31 and 37/37 lines uncovered respectively).
- `python -m ruff check src/ tests/` — all checks passed.
- `python -m ruff format --check src/ tests/` — 39 files already formatted.
- Confirmed PRs #8 (`dqt-01`) and #9 (`docs-plan-tdd-amend`) open against
  `main`, untouched by this branch.

Claims this document could not verify against source, and what would
resolve them: whether the owner intends the UI's HTTP contract (§4, §6 v0.9)
to be inside or outside the 1.0 compatibility freeze — no document in this
set states a position either way; this proposal recommends outside (exempt,
until tested) but that is a recommendation, not a finding. Whether a
two-run delta (§4's pushback) is cheap in practice, as claimed, rather than
merely cheap in principle — resolving this requires someone to actually
attempt it against `NEW-A`'s post-split schema and report the real size.
