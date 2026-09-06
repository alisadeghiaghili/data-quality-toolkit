# Roadmap to 2.0 — a critical reading

> Written 2026-09-06, against `1.0.2`. Every claim below was checked against
> the tree rather than remembered. Where I could not verify something, it says
> so.

`1.0.0` is a promise not to break the public API. `2.0.0` is the only release
allowed to break it — so the question this document answers is **not** "what
should DQT do next", it is **"what is wrong in a way that only a major version
can fix?"**

Anything additive — a new rule expression, a new dimension's diagnostics, a
new cleansing operation inside the existing `Literal` — is a `1.x` minor and
does not belong here. That test is what keeps a roadmap from becoming a
wishlist.

---

## 0. The honest state of 1.0

Three defects were found in the two days *after* `1.0.0` was tagged, by tests
written to raise the coverage floor:

| | What | Why it survived to 1.0 |
|---|---|---|
| `NEW-V` | Config errors exited `1` ("your data has errors") instead of `3` | The contract was tested through `decide_exit_code`, which needs a finished run. These paths exit before a pipeline exists. |
| `NEW-W` | CI enforced a coverage floor of 80 while the config said 90 | A command-line flag beats a config file, and nothing compared the two numbers. |
| `NEW-X` | `SamplingConfig`'s docstring described `TABLESAMPLE` / `LIMIT` SQL that is never generated | Nothing tested a facet's *absence*. |

**The pattern matters more than the three bugs.** Every one is a gap between
something *stated* and something *enforced*, and in each case the statement
was tested along its easy path. That is the failure mode this roadmap is
organised around, not feature coverage.

It is also the argument for the gates rather than against them: all three were
found by tests, within days, and fixed as patches. But `1.0.0` should not have
shipped with the first one.

---

## 1. Design flaws that only a major version can fix

These are the actual contents of `2.0`. Each is a shape that is wrong, not a
feature that is missing.

### 1.1 `RunStore` is a schema, a store, and a migration policy in one — and it refuses rather than migrates

**Current state, verified.** `RunStore.init_schema()` writes `PRAGMA
user_version` and `_assert_store_is_current()` refuses any file it did not
write, in either direction. Between `0.1.0` and `1.0.0` the schema went 1 → 3,
and each step told users to **delete their history**.

**Why this is a 2.0 problem.** It was defensible while DQT was pre-1.0 and the
store was "a local artifact meant to be recreated". It stops being defensible
the moment anyone uses the trend chart, because the value of a trend is
proportional to how far back it goes — and DQT currently deletes that history
on every schema change. A monitoring tool that cannot keep six months of
metrics is not a monitoring tool.

**The shape that is wrong:** `RunStore` owns the DDL, the reads, the writes,
and the decision about what to do with an old file. A migration path requires
separating "what the schema is at version N" from "how to get from N to N+1",
and that is a structural change to a public class.

**What 2.0 should do:** forward-only migrations, with the refusal kept only
for a store *newer* than the running DQT. `RunStore.init_schema` stops being
the place both questions are answered.

**Counter-argument, honestly:** this is real work for a benefit nobody has
asked for yet, because nobody has six months of history. If the answer is "not
yet", the honest alternative is to say in `docs/API-STABILITY.md` that run
history is **not** durable across minor versions — which is currently true and
undocumented.

### 1.2 `RunStore` never closes a connection (`NEW-T`, open since 2026-09-05)

**Verified:** 15 occurrences of `with self._connect() as conn:` in
`storage.py`. In `sqlite3` that context manager is a **transaction**, not a
close. Every call leaks a connection until garbage collection.

**Why it is 2.0 and not a patch.** Wrapping the same connection in `closing()`
as well as the transaction manager changes the nesting order of *commit* and
*close* — a change to when data becomes durable. Doing that quietly in a patch
is exactly the kind of change that is fine ninety-nine times and corrupts a
store the hundredth.

Cost today is bounded: a local SQLite file, a short-lived process. It stops
being bounded the moment the FastAPI surface is served for real, because that
opens one per request.

### 1.3 ~~Sampling~~ — **done in `1.1.0`, and this entry was wrong**

**What this section originally said:** that honouring `SamplingConfig`
belonged in `2.0`, because every consumer of a metric has to be able to tell a
sampled number from a full-scan one, and making existing stored rows
implicitly "unsampled" would need a store column that old rows do not have.

**Why it was wrong.** `DQMetric.metadata` and the `run_metrics.metadata`
column already exist, with a `DEFAULT '{}'`. There was already somewhere to
record it, and rows written before the feature read correctly as unsampled
rather than contradicting it. No schema change, therefore no forced deletion
of history, therefore a **minor**.

Shipped as `1.1.0` (`NEW-Z`). Two decisions from it are worth keeping here
because they will come up again:

* **Rules never sample.** A profile is a description; a rule is a verdict.
  "No duplicates" read off a sample means "none among the rows I looked at",
  which is the false-clean-bill-of-health failure `DQT-04` and `GATE-02` both
  exist to prevent. Sampling a verdict would reintroduce it by design.
* **`seed` is refused, not ignored.** No dialect can seed a random sample
  inside one scalar subquery. Accepting the parameter and producing an
  unseeded sample is the exact failure this whole area was cleaning up.

**The lesson, kept deliberately.** This document argued from memory of the
schema rather than from reading it, and reached a wrong conclusion that would
have deferred a useful feature by a major version. The closing section already
says the roadmap reasons from code rather than usage; it should also have said
that reasoning from code means *checking* the code.

### 1.4 `monitor()` is the identity function, and Monitoring is a named facet

**Verified:** `src/dqt/sql/monitoring.py` is 26 lines and returns its input
unchanged. The docs are honest about it — `CONVENTIONS-DQT.md` marks it
"stub, untested" and the README says `monitor()` is a pass-through — so this
is **not** an honesty-gate breach.

**Why it is still a 2.0 item.** A facet that does nothing is either a feature
DQT owes or a facet DQT should cut, and `1.0` shipped without deciding which.
Building it means a real two-run delta — which metrics moved, by how much,
since when — and that needs `run_metrics` to be queryable by *metric identity*
across runs. Whether the current schema supports that efficiently is
**unverified**; I did not check the index situation, and this document does
not claim it either way.

### 1.5 The bridge reaches into another package's private module

**Verified:** `bridges/missingly.py` imports `dqt.sql._connect`.

The architecture audit does not flag this, because I did not add the rule.
That was a deliberate omission and it is worth recording why: the principled
rule ("a module private to a package may only be imported inside it") has
exactly one violation, and every fix has a public-API consequence — move
`_connect` up a level, or invert the dependency so the bridge is handed a
connection. **Inventing a rule and then contorting the code to satisfy it is
worse than not having the rule**, so I left it out rather than add an
exception to the audit.

`2.0` is where the dependency can be inverted without a deprecation cycle.

---

## 2. What does *not* belong in 2.0

Stated so the list above stays honest.

| Not in 2.0 | Why |
|---|---|
| MySQL, Oracle | Additive. A fourth dialect behind the existing protocol breaks nothing. The protocol was validated against three engines, which is the point at which the abstraction stops being guesswork. |
| More rule expressions | The `expression` field is a string; adding `LENGTH` or `IN SET` breaks nobody. |
| Diagnostics for the other five dimensions | `DQDimension` is already a closed six-value `Literal`. Filling in coverage is a minor. |
| A richer UI | The HTML screens are deliberately outside the freeze, so they can change in any release. |
| `missingly` features | It is a sibling package with its own version. |

---

## 3. Sequence, and what would make me wrong

1. **`NEW-T`** first (connection lifetime). It is the smallest, it is
   prerequisite for serving the API for real, and it has no design questions
   left — only care.
2. **Sampling** (§1.3), because it is the only item a user can currently be
   *misled* by, and because it forces the "is this number comparable"
   question that §1.1 and §1.4 both also need answered.
3. **Store migrations** (§1.1) — but only after deciding whether run history
   is a promise at all. If it is not, document that instead and drop the item.
4. **Monitoring** (§1.4), which depends on 3.
5. **The bridge dependency** (§1.5), last, because it is the cheapest and the
   least visible.

**What would make this roadmap wrong:** if nobody ever runs DQT against a
table large enough to need sampling, §1.3 is wasted work and §1.1's history
argument weakens with it. That is an empirical question about real usage, and
I have no data on it — this document is reasoning from the code, not from
users. If the owner has usage information that contradicts any of the above,
it should win.
