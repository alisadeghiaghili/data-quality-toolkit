# Changelog

All notable changes to `data-quality-toolkit` are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
the project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Per `docs/HONESTY-GATE.md`, a version number is a claim like any other, so
`0.1.0` is claimed only now that `docs/PLAN-TDD.md`'s cut line — its units 1-9 —
has actually been met.

Dates are the merge dates on `main`.

## [Unreleased]

## [0.5.0] — 2026-09-06

**Why this is `0.5.0` and not `0.2.0`.** `docs/PROPOSAL-v1.0-roadmap.md` §6
defines a release ladder whose rungs are *gates*, not decorations. Four of
them are now met, in order, and this release is the first tag since `0.1.0`
because the work that closed them landed continuously rather than in four
separable batches:

| rung | gate | closed by |
|---|---|---|
| **v0.2** — safety proven | The four-hash read-only proof against a **live SQL Server** and a live PostgreSQL, not only SQLite | `GATE-02` |
| **v0.3** — the wedge is real | Cleansing round-trips — apply then revert to identical data — for **both** operations, on both servers | `GATE-03`, which found `NEW-U` |
| **v0.4** — a measured budget | A committed benchmark run reporting profiling, rule-evaluation and cleanse-plan timings under published budgets at a stated fixture size | `GATE-04` |
| **v0.5** — every facet decided | No row in the facet table still reads "not started" without an owner decision | `NEW-K`, `VIZ-1`…`VIZ-6` |

`0.2.0`, `0.3.0` and `0.4.0` were **never published**. Their gates were closed
in sequence and are listed above rather than invented as releases that did not
happen.

**The ladder was also reordered.** It originally put PostgreSQL at `v0.2` and
SQL Server at `v0.4` as "the third dialect" — written before the owner named
SQL Server as DQT's primary target. SQL Server now leads every rung, which
makes `v0.2` stronger rather than weaker: it is the engine where
`ReadOnlyEnforcement.ADVISORY` means the server will *not* refuse a write, so
DQT's own guard is the only thing standing between a `read_only` config and a
modified production table.

### ⚠️ Upgrading from `0.1.0`

**Delete your `dqt_runs.db` and let DQT recreate it.** The store's schema
version went from 1 to 3 (`NEW-S`, then `NEW-U`), and DQT refuses a store it
did not write rather than half-reading one — the store is a local artifact
meant to be recreated, not migrated. Nothing else in this release requires
action.


### Deprecated

- **`dqt.sql.cleansing.apply_cleansing`** — superseded by `cleanse_plan()` /
  `cleanse_apply()` / `revert()`. It writes its log to memory and returns it,
  so a caller who drops the return value loses the before-values permanently
  and the change cannot be undone: the defect `DQT-05` exists to fix. It now
  emits a `DeprecationWarning`. See [`docs/API-STABILITY.md`](docs/API-STABILITY.md)
  for the removal schedule.

### Removed

- **`dqt.sql.cleansing.cleanse`** — the pipeline adapter, orphaned when `Q1`
  removed the cleansing stage from `DQTPipeline.run()`. Nothing called it.


### Added

- **Python 3.14 is supported**, and the claim is tied to its evidence: a test
  reads both `pyproject.toml`'s classifiers and the CI matrix and fails if
  either names a version the other does not. A classifier with no CI run is
  an unbacked claim of the most expensive kind — someone installs on that
  version because the metadata said so.
- **The rules screen (`VIZ-6`).** `GET /ui/runs/{id}/rules` lists what each
  rule did, and `GET /ui/rules/{name}` follows one rule across runs. The
  screen exists for the zero: a rule whose scope matches nothing reports no
  failures, which everywhere else reads exactly like a rule that passes, so
  those rules are named **in words above the table** — and only when there
  are any. Failed and errored stay separate columns: a rule that failed found
  a problem, a rule that errored found nothing. History charts oldest-first,
  since the store returns newest-first and plotting it as given would draw
  every improving rule as though it were getting worse.
- **Accessibility is measured, not intended (`VIZ-5`).** `dqt/_theme.py` names
  the palette once and declares which pairs meet on screen; CI computes every
  WCAG 2.1 contrast ratio and fails the build on one that falls short. Doing
  that found two: the conventional amber and teal severity marks measured
  **1.51:1** and **2.81:1** against the page — the amber was barely
  distinguishable from the paper. Both darkened. Structural rules are checked
  on rendered output too: every chart carries `role="img"` and an
  `aria-label`, every table has header cells, there is exactly one `h1` and no
  skipped heading level, and every link is a real focusable `<a href>`.
- **Vazirmatn embedded in Persian pages (`VIZ-4`).** SIL OFL, vendored with
  its licence and inlined as a `data:` URI — never fetched, so a report still
  renders on an air-gapped machine, which is exactly where a DBA opens one.
  Persian without Arabic-script shaping is not slightly off, it is
  unreadable. English pages carry none of it.
- **Persian, and right-to-left layout (`VIZ-4`).** `dqt.i18n` holds a fixed
  English↔Persian glossary — a closed table, proved complete by a test, so a
  missing translation fails CI instead of shipping an English word into a
  Persian page. The screens render in either language, and **identifiers, SQL
  and numbers keep their own direction**: inside an RTL block a browser
  reorders bare Latin text, so `orders.customer_id` would still be present
  but no longer correct. Charts do not mirror — a bar chart is a measurement.
  CLI output and code stay English-only, unchanged.
- **The first three screens (`VIZ-3`).** `GET /ui`, `/ui/runs/{id}` and
  `/ui/runs/{id}/issues` — server-rendered HTML from the same `dqt._html`
  builder and `dqt.viz` charts the report uses, added *beside* the JSON API
  rather than instead of it. No JavaScript: plain pages are keyboard
  accessible and back-button correct by construction. A run that does not
  exist is a 404, because an empty run page reads as a run that went
  perfectly.
- **Set-based dashboard counts.** `RunStore.count_issues_by_severity`,
  `count_issues_by_dimension` and `average_score_by_dimension` group in the
  database — one query each — so a page's cost does not grow with how bad the
  data is. A dimension nothing measured is **absent** rather than zero: the
  screens rely on that distinction to render "not measured" instead of a
  measured failure.
- **The HTML report draws what it reports (`VIZ-2`).** Six dimension
  scorecards — including the five nothing measured, which say "not measured"
  and draw no bar — and an issues-by-dimension chart, both from `dqt.viz`, so
  the static artifact and the pages that come later render the same charts
  from the same code. Every chart's text equivalent is shown on the page, not
  hidden.
- **`dqt.viz` — the chart primitives (`VIZ-1`).** Score bars, bar charts,
  trend lines, severity indicators and scorecards, as inline SVG produced by
  pure functions. No plotting library: a raster image can only be
  smoke-tested, and *"this bar is drawn shorter than that one"* is a claim
  the honesty gate wants a test behind. Every function returns the SVG **and**
  its text equivalent, so the accessibility requirement is structural rather
  than remembered. Severity is carried by a shape and a word as well as a
  colour, and an unmeasured dimension draws no bar at all — "not measured"
  must never look like a full score.
- **The Knowledge/Domain facet (`NEW-K`).** A `REFERENCE` rule expression
  checks that a column's values come from a known set — the validity check
  neither `REGEX` nor `RANGE` can express. The set is either a table in the
  same database, compiled to an anti-join so the planner does the matching,
  or an inline list bound as parameters. An optional `normalize_persian`
  folds Persian and Arabic letter and digit variants on both sides, in SQL.
  DQT deliberately ships no reference *data*: a tool carrying its own
  country list is one stale release away from reporting correct data as
  invalid. This was the last facet in `docs/CONVENTIONS-DQT.md` §2 with no
  module behind it, and a `1.0.0` blocker in `docs/API-STABILITY.md`.
- **An approximate-distinct option for `UNIQUE` rules.** `params:
  {approximate: true}` asks the dialect for an estimate where it has one —
  only SQL Server does. The issue's evidence always carries `approximate`,
  because an estimate and an exact count are different claims.
- **SQL Server exercised against a live server in CI.** `DQT-08` shipped the
  dialect with every assertion made against SQL text; whether `pyodbc` accepts
  the generated ODBC connection string, and whether `INFORMATION_SCHEMA`
  returns what discovery expects, could only be settled against an instance.
  Twelve tests now do, including one asserting that a write on a read-only
  connection **lands** — the limitation `ReadOnlyEnforcement.ADVISORY` encodes,
  now checked rather than only documented.
- **PostgreSQL exercised against a live server in CI**, which verified
  `read_only` enforcement for the first time and immediately found `NEW-M`.

### Changed

- **One stylesheet for the report and the screens.** `VIZ-2` and `VIZ-3` grew
  near-identical CSS in two modules; a severity colour defined twice is one
  that will eventually mean two different things. Alignment and spacing now
  use `start` and `margin-inline-end` rather than `left` and `margin-right`,
  which is what lets a single stylesheet serve both reading directions, and
  the stylesheet has a print mode.
- **Report HTML is built through an escape-by-default builder**
  (`dqt/_html.py`) instead of twenty-odd hand-placed `html.escape` calls.
  Text is escaped, markup is explicit; the one call that would eventually be
  forgotten now cannot be. No new dependency: the plan's Jinja2 proposal was
  reversed because `docs/BACKLOG.md` §4 rules out new hard dependencies and
  the Reports facet must work with no extras installed.
- **The run store records what each rule did (`NEW-S`).** `save_run` was
  dropping `PipelineResult.rules_run` on every run, so the count that says a
  rule matched **zero targets** — the usual way a rule set rots unnoticed —
  was computed and thrown away. There is now a `run_rule_results` table, and
  `load_rule_results` / `load_rule_history` read it back through
  `dqt.ui.api`.
- **Runs record which DQT produced them.** Scores are only comparable within
  a version line; the pipeline stamps the running version onto the result and
  the store keeps it. A result that does not state one is stored as unknown
  rather than guessed at save time.
- **The store's schema version is `PRAGMA user_version`**, replacing a probe
  for one column added by `NEW-A`. A store from an older *or newer* DQT is
  refused by name — reading forwards is no safer than reading backwards.
  **Existing `dqt_runs.db` files must be deleted and recreated**; DQT does not
  migrate this file, by design.
- **Rules on the same table share one scan.** Each check compiles to
  aggregate expressions rather than to a statement, and the checks over a
  table run as a single `SELECT` — what `CLAUDE.md` §3 asks for. Twenty rules
  on one table cost one pass, not twenty. A `REFERENCE` rule pointing at a
  reference table still pays its own scan, because the join it needs changes
  which rows the other aggregates would see. A batch the database rejects is
  retried one check at a time, so a mistake in one rule costs that rule's
  verdict rather than the table's whole report.
- **Cleansing reads are paged by row identity** rather than taken in one
  `fetchall()`, so planning a cleanse of a very large table no longer builds
  a Python list the size of the table. Paged rather than streamed because
  cleansing writes while it reads, and a streaming cursor would have made
  the result depend on the engine's isolation level.
- **Profiling is one aggregate query per table** rather than one per column,
  and `RANGE` and `UNIQUE` rules each cost one query rather than two.
  `_deduplicate` no longer issues a `SELECT *` per duplicate row.

### Fixed

- **`deduplicate` never worked through the supported API (`NEW-U`).** `DQT-05`
  replaced `apply_cleansing` with `cleanse_plan` / `cleanse_apply` /
  `revert` and deprecated the old one — but for `deduplicate` the
  replacement had **three** fatal breaks, on every dialect including SQLite:
  the log could not be stored (the deleted row is a dict, written raw to
  SQLite), apply replayed a deletion as `UPDATE ... SET "None" = ?`, and
  revert did the same against a row that was already gone. Only the
  deprecated path handled it, because it deletes inline and never round-trips
  through storage. `docs/API-STABILITY.md` requires a replacement to be at
  least as capable *before* the old one is deprecated; that deprecation was
  written against an intention. Found by `GATE-03`.
- **`RunStore`'s cleansing log now stores JSON** for `before_value` and
  `after_value` (schema version 3). **Existing `dqt_runs.db` files must be
  recreated.**
- **The HTML report never stated the run's status (`VIZ-0`).** It rendered a
  severity badge reading "info" for a success and "warning" for everything
  else, so `partial` and `failed` were indistinguishable and neither word
  appeared. It now names the status.
- **The HTML report dropped `stage_errors`.** `NEW-B` added them so a run
  could report failure; a degraded run showed an unexplained badge and
  nothing actionable. Failed stages are now listed with what went wrong, and
  a clean run shows no section at all rather than an empty panel.
- **`generate_html_report` raised `FileNotFoundError`** for an output path
  whose directory did not exist, where `RunStore` creates it.
- **`dqt.ui.app`'s docstring told people to bind `0.0.0.0`** — every
  interface, on an app with no authentication, serving schema and table names
  read from a production database. It now binds loopback and says what would
  be exposed.
- **`regex` rules cost two queries**, a bare row count followed by the match.
  The query-budget test never parametrised `regex`, so the pass that removed
  exactly that shape from `RANGE` and `UNIQUE` walked past it.
- **A reference table holding a value twice inflated the denominator.** The
  join matched each data row once per repeat, so "how many values did we
  check" grew and the column looked cleaner than it was — the direction of
  error that hides problems. The join now reads distinct reference values.
- **`NEW-M`** — cleansing addressed rows by SQLite's `rowid`, so every
  cleansing entry point failed on PostgreSQL and SQL Server. Rows are now
  addressed by primary key; deduplication's `MIN(rowid)` ordering became a
  portable `ROW_NUMBER()` window function that also handles composite keys.


## [0.1.0] — 2026-09-05

The v0.1 cut line: everything `docs/PLAN-TDD.md` judged either **silently
wrong** or **false in a shipped docstring**.

Nine units, in the plan's order: `NEW-H` (the CLI dropped the rule files it
was given), `DQT-04` (`regex` rules never evaluated on SQLite), `DOC-01`
(documentation gate — DQT slice; the `MSY` and `PDP` slices remain open, so
the roadmap task itself is not closed), `NEW-C` slice 1 (profiling and
diagnostics grounded), `NEW-A` (`dimension` carried two incompatible
meanings), `DQT-05` (cleansing claimed to be reversible and was not),
`NEW-B` (`run()` could not report failure), `DQT-06` (no exit-code contract,
so the advertised CI gate did not gate), and `DQT-08` (two connection paths,
one of which ignored `read_only`).

Also landed outside that line: the `dqt.sql.dialects` abstraction with a
SQL Server dialect, the semantic classification facet with Iranian
identifiers, the `missingly` bridge, and the read-only HTTP surface's tests.

Suite: 564 tests, 93.70% coverage against a 90% gate.


### Added

- **Classification facet** — `src/dqt/classification.py`, the first code behind
  the facet `docs/CONVENTIONS-DQT.md` §2 had listed as "not started". Pure
  domain logic, no database access, exercised by 132 unit tests.
  - Checksum-**validated**: Iranian national ID (weighted sum modulo 11),
    Iranian Sheba and generic IBAN (ISO 13616 / ISO 7064 MOD 97-10). Expected
    values in the tests are hand-derived from the published algorithms and
    written out as arithmetic in comments.
  - Shape-**recognised** only, and named `is_*` rather than `is_valid_*` to say
    so: Iranian mobile and landline numbers, Shamsi (Jalali) dates, e-mail
    addresses.
  - Persian text normalization (`normalize_persian_text`) as a separate,
    opt-in operation: Persian and Arabic-Indic digits to ASCII, Arabic yeh,
    alef maksura and kaf to their Persian forms, ZWNJ and ZWJ removed. It
    changes values, so it never runs implicitly inside classification.
  - Public API gains `ClassificationResult`, `SemanticType`, `classify_column`,
    `classify_column_name`, `classify_value` and `normalize_persian_text`.
  - **Not** included, deliberately: Shamsi-to-Gregorian conversion (so the
    Esfand leap rule is not applied and 30 Esfand is accepted in every year),
    IBAN per-country length rules, Iranian area-code and mobile-operator
    allocation lists, and any wiring into profiling — `ColumnResult.semantic_type`
    is still `None` in every run. (2026-09-04)
- Documentation gate (`DOC-01`, DQT slice) — `tools/doc_audit.py`, vendored
  verbatim from the Consilient engineering standard, wired into CI as a
  required job running in ratchet mode against `.doc_audit_baseline.json`.
  Pre-existing debt is accepted; any new violation fails the build. `DOC-01`
  itself remains open: the roadmap scopes it to three repositories and only the
  DQT slice is done. (2026-09-04)
- `docs/PROPOSAL-v1.0-roadmap.md` — a critical proposal defining what 1.0.0
  should mean, the defensible product wedge, what to cut, and the hard gates
  that do not exist yet. A proposal for the owner's decision, ranked below the
  authoritative `ROADMAP.md`; nothing in it is settled. (2026-09-04)
- `docs/PLAN-TDD.md` — the 15-unit TDD implementation plan, landed as a
  sequencing document. (2026-08-27)
- `--dry-run` / `--commit` flags on `dqt profile`, with `--dry-run` the default
  (`DQT-03`). (2026-08-19)

### Changed

- **License: Apache-2.0 to BUSL-1.1.** Change Date 2030-09-04, Change License
  Apache 2.0, and an Additional Use Grant limited to internal business
  operations. BUSL-1.1 is source-available, not an OSI-approved open-source
  licence. Versions previously distributed under Apache-2.0 remain available
  under Apache-2.0 — a relicence cannot apply retroactively to published
  releases. (2026-09-04)
- Version set to `0.1.0.dev0`. It had read `0.1.0` since the beginning while
  nothing had ever been released and the project's own v0.1 bar was unmet
  (`NEW-M`). (2026-09-04)
- `docs/PLAN-TDD.md` amended: unit 6 (`DQT-05`) reshaped around the settled Q2
  decision (`cleanse_plan()` / `cleanse_apply()` keyed by `plan_id`, neither
  reachable from `run()`), plus a new SQL Server unit and a new performance and
  scale unit. The document's convention is to annotate in place and never
  delete, so the superseded text remains visible. (2026-09-04)

### Fixed

- `regex` rules now work on SQLite (`DQT-04`). A Python `re`-backed `REGEXP`
  function is registered on every SQLite connection, behind a 256-entry,
  1000-character-limited compiled-pattern cache; a malformed pattern raises
  before any query runs instead of being reported as a data failure. Note the
  scaling limit: the callback is invoked per row, so `regex` rules on SQLite are
  a full scan with per-row Python overhead. (2026-08-27)
- CLI no longer silently drops `rule_files` from a `--config` file, which had
  made `dqt profile --config <file>` run no rule checks at all (`NEW-H`).
  (2026-08-19)
- README no longer claims MIT while the repository shipped a different licence,
  and no longer lists `DQT-04` as an open defect after it was fixed (`DQT-01`).
  (2026-09-04)
- README no longer implies DQT compares runs over time. The metrics store holds
  the data such a comparison would read, but `monitor()` is a pass-through and
  performs no comparison (`NEW-G`). (2026-09-04)
- `ReadOnlyViolationError` gained the `Example` block the documentation standard
  requires. (2026-09-04)
- Phase 0 repository remediation: deleted a legacy pandas package and a broken
  duplicate CI workflow, fixed a CLI that crashed on every invocation, fixed the
  packaging entry point and undeclared dependencies, and rewrote every false
  `[x] DONE` status marker to match verified reality. Three correctness bugs
  were fixed in the process — SQLite rowid/`INTEGER PRIMARY KEY` aliasing that
  silently reported zero changes, NULL-key deduplication that would delete
  distinct rows as duplicates, and non-idempotent `run_metrics` writes that
  duplicated every metric row on re-save. (2026-08-11)

### Security

- All SQL literals are bound as DBAPI parameters and identifier quoting has a
  single authority in `sql/_identifiers.py` (`DQT-02`). The reproduced
  pre-fix exploit — an attacker subquery executing through a range-rule bound —
  is covered by a regression test. (2026-08-19)
- `ConnectionConfig.read_only` is enforced rather than merely accepted
  (`DQT-03`): SQLite connections open with `mode=ro`, and `apply_cleansing()`
  raises `ReadOnlyViolationError` before building any mutating statement.
  Two gaps remain and are tracked: the PostgreSQL path has never been exercised
  because CI has no PostgreSQL service, and `sql/schema_discovery.py`'s
  `connect_sql()` does not consult `read_only` at all (`DQT-08`). (2026-08-19)

### Known limitations

- SQLite and PostgreSQL only. MySQL is a permanent non-goal; SQL Server is
  planned and blocked on a `dqt/sql/dialects/` abstraction.
- Diagnostics cover completeness only.
- `PipelineResult.status` is always `"success"` — there is no per-stage error
  handling, so a failed run raises rather than recording failure (`NEW-B`).
- Cleansing is not persisted and cannot be reverted (`DQT-05`).
- No performance benchmarks exist, so no claim is made about behaviour on
  large tables.

[Unreleased]: https://github.com/alisadeghiaghili/data-quality-toolkit/commits/main
