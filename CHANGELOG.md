# Changelog

All notable changes to `data-quality-toolkit` are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
the project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Per `docs/HONESTY-GATE.md`, a version number is a claim like any other, so
`0.1.0` is claimed only now that `docs/PLAN-TDD.md`'s cut line — its units 1-9 —
has actually been met.

Dates are the merge dates on `main`.

## [Unreleased]

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
