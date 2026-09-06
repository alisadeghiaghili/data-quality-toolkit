# Roadmap to 15 of 15 — reaching DQT's own capability floor

> Written 2026-09-07 against `1.1.0`. The current standing is
> [`dqt_competitors.md`](dqt_competitors.md) §1, re-verified cell by cell on
> 2026-09-06 at commit `1fee86e`: **5 met, 7 partial, 3 not met.**

## 0. The honest answer first: no such roadmap existed

The engineering-standards skill is installed now — it was not when
`ROADMAP-DERIVED.md` was written, which is why that file had to be
reconstructed by grepping this repo. `ROADMAP.md` has now been read directly.

**Two editions are installed and both were checked**, because reading only one
would leave which-edition an open question behind every claim below:
`aghili-engineering-standards` (`ROADMAP.md`, 77,710 bytes) and
`consilient-engineering-standards` (85,747 bytes), the latter a rebrand and
superset. **The DQT track is identical in both** — same eight task IDs, and
`DQT-09`'s body diffs clean between them. Every statement here holds against
the newer edition, which is the one to prefer.

**It contains no task for any floor item.** The DQT track is `DQT-01` … `DQT-06`,
`DQT-08`, `DQT-09` (there is no `DQT-07`), and every one is about correctness or
safety: parameterize SQL, unify quoting, enforce `read_only`, make `regex` work,
persist cleansing logs and implement `revert`, the exit-code contract, the
driver split, the exception hierarchy. The strings `F1`…`F15`, "floor", "min,
max", and "distinct" do not appear in it in a DQT context at all.

So this document is a **new plan**, not the recovery of a lost one. Nothing was
dropped; the floor was never scheduled.

### 0.1 And the roadmap deliberately deprioritizes DQT

This has to be stated before any sequencing, because it outranks everything
below. `ROADMAP.md` §10:

> Everything in `PDP` and `DQT` is risk reduction — necessary because those
> repos currently damage the credibility of the flagship, but not itself
> progress toward the goal. If owner attention must be rationed, protect the
> `MSY` path and do only Phase 0 on the others.

The declared strategic goal is `missingly` as the flagship, on the critical path
`MSY-01 → MSY-02 → MSY-03 → MSY-04 → MSY-05`.

**Building the floor out is therefore a deliberate reversal of the recorded
strategy, not an execution of it.** That may well be the right call — the
roadmap's DQT assessment was measured on 2026-08-12, before Phase 0 closed and
before everything since, and it describes a repo that no longer exists. But it
is an owner decision, and this document exists to make it a visible one rather
than a drift.

Nothing here is scope creep: every floor item maps to a declared DQT facet.
The question is not *whether* these belong to DQT, it is *whether DQT is what
should be worked on*.

### 0.2 One authoritative DQT task is genuinely still open

Verified today, not remembered:

**`DQT-09` — the exception hierarchy — is incomplete.** `src/dqt/exceptions.py`
exists and `ReadOnlyViolationError` was moved into it, but the hierarchy itself
was never built: that class derives from `Exception` directly, and there is no
root `DQTError`, no `RuleEvaluationError`, `ConnectionConfigError`, or
`CleansingError`.

Its acceptance criterion — *"`except DQTError` catches every package-specific
failure"* — is not met. Estimated at 4h in the roadmap, and it matters more now
than when it was written: a scheduled job that cannot distinguish "DQT failed"
from "Python failed" cannot react correctly to either.

The other five defects `ROADMAP.md` §1.5 lists as open are all closed —
parameterized range bounds, unified quoting, `read_only` with real consumers,
`revert`, and a registered SQLite `REGEXP`.

---

## 1. What actually blocks what

Ten items are short of `MET`. They are not independent, and the order matters
more than the count.

```
F1  column stats ──┬──→ F3  six dimensions ──┬──→ F7  per-scope metrics ──→ F8  monitoring + drift
                   │                          │                                    ▲
F2  FK discovery ──┴──→ F5  table rules       │                                    │
                                              │                       store migrations (2.0 §1.1)
F10 wire classification ──────────────────────┘
F14 CLI  ·  F12 PDF  ·  F11 missingness patterns   (independent)
```

**`F1` is the keystone.** `min`, `max`, `mean`, and `distinct` are not just a
profiling gap — they are the inputs three other rows need. Without a distinct
count there is no uniqueness *diagnostic* (only a uniqueness rule); without
min/max there is no validity diagnostic; without either there is nothing
per-column for `F7` to score. Doing `F1` first turns four rows from "build it"
into "expose it".

**`F8` cannot be finished inside `1.x`.** A metric-level trend needs
`run_metrics` queryable by metric identity across runs, and `RunStore` refuses
any file whose schema version it did not write — so a schema change today
deletes every user's history. That is `ROADMAP-2.0.md` §1.1, and it is a
decision before it is a task: *is run history a promise DQT makes at all?* If
the answer is "not yet", the honest move is to say so in `API-STABILITY.md` and
accept that `F8` stays partial until `2.0`.

**15 of 15 is therefore not reachable without answering that question.** Every
other row can land as a `1.x` minor.

---

## 2. The sequence

Sizes are relative and deliberately not in hours: this repo's TDD shape means a
"small" unit is still two commits, a live-CI pass, and a doc that survives the
honesty gate. Version numbers assume nothing else lands between.

### Wave 1 — cheap, unblocking, and visible to a DBA tomorrow

| | Item | Size | Why first |
|---|---|---|---|
| 1 | **`DQT-09`** exception hierarchy | S | The only open authoritative task. Closes the roadmap's own DQT track. |
| 2 | **`F10`** call `classify_column` during a run | S | The code exists, is locale-aware, and is tested. Nothing calls it. This is wiring, not building — the cheapest `PARTIAL → MET` on the board. |
| 3 | **`F14`** `dqt check` and `dqt serve` | M | `serve` is what makes the dashboard startable without Python — and it is the only way the loopback-bind rule stops being a docstring nobody reads and becomes a refusal. |
| 4 | **`F1`** column statistics | M | The keystone. Must stay **one aggregate query per table** — `min`/`max`/`avg` are free to add to the existing single pass; `COUNT(DISTINCT)` is not, so it goes behind the approximate-distinct path already built for `UNIQUE`. |

Target: **`1.2.0`**. After this wave: **8 met**, and the DBA-facing story is
whole — real profiling numbers, semantic types, and a command to start the UI.

### Wave 2 — the analysis depth a DBA judges the tool by

| | Item | Size | Notes |
|---|---|---|---|
| 5 | **`F2`** FK discovery + orphan-row detection | M | Each dialect already has a `fetch_column_metadata`; this adds the constraint query beside it. Orphan counting is an anti-join — the shape `knowledge.py` already uses. |
| 6 | **`F5`** table-level rules | M | Needs `F2` for FK integrity. `RuleScope` already permits `column_name=None`; nothing evaluates it. |
| 7 | **`F3`** the remaining five dimensions | L | Needs `F1` and `F2`. This is the largest single item and the one that most changes what the product *is* — `completeness` alone is one sixth of the promise. |

Target: **`1.3.0`** / **`1.4.0`**. After this wave: **11 met**.

### Wave 3 — the measurement layer

| | Item | Size | Notes |
|---|---|---|---|
| 8 | **`F7`** metrics per table / column / dimension | M | Needs `F3`. Today's three global metrics become a real scorecard. |
| 9 | **store migrations** (`ROADMAP-2.0.md` §1.1) | L | **Decision first.** Blocks `F8`. |
| 10 | **`F8`** metric trend + drift detection | L | Needs both above. `monitor()` stops being the identity function or the facet gets cut. |

Target: **`1.5.0`**, then **`2.0.0`** for the migration-gated half.

### Wave 4 — the last two, both carrying a trap

| | Item | Size | The trap |
|---|---|---|---|
| 11 | **`F12`** PDF export | M | **Adds a runtime dependency.** Every PDF library is heavy, and DQT's lean footprint is one of only three differentiators the competitor analysis credits it with. This belongs behind an extra, or not at all — "no PDF" may be the better answer than a dependency that costs more than the feature. |
| 12 | **`F11`** internal missingness patterns | M | **Boundary risk.** Co-occurrence patterns are what `missingly` does. `AGENTS.md` forbids re-implementing its algorithms, and the floor's wording ("null stats and patterns") does not say how deep. Scope this against `missingly` before writing a line, or it becomes the duplication the bridge exists to prevent. |

---

## 3. What 15 of 15 would and would not mean

It would mean DQT meets **its own floor** — the bar this project set in
`dqt_competitors.md` before it had the code to judge itself against.

It would **not** mean parity with Baselinr, which that same document names the
closest direct competitor and says already delivers most of this row. The
competitor analysis is explicit about where DQT can actually win, and it is not
feature count:

> DQT's defensible differentiation is DBA-first framing, a lean dependency
> footprint, and bilingual EN/FA reporting — not feature count.

Two of those three are live constraints on this roadmap rather than decoration.
The lean footprint is what makes `F12` questionable. DBA-first framing is what
makes `F14`'s `serve` worth more than its size suggests.

**The row most worth reaching is `F3`, and the one most worth refusing may be
`F12`.** A tool that reports one of six quality dimensions is not yet the thing
its own README describes; a tool that cannot emit PDF is merely a tool that
cannot emit PDF.
