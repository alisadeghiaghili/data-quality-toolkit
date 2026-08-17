# Guide — DQT Architect

> **This is a reference document, not installed tooling.** It has no runtime
> effect and activates nothing. It is prose to read when working on DQT's
> backend, data model, or pipeline. It was previously named `SKILL-*`, which
> implied a registered capability that does not exist.
>
> It does **not** restate the ecosystem `ENGINEERING-STANDARDS.md` or this
> repository's `AGENTS.md`. Read those first — they are what is *required*. This
> guide is about *how to reason* about a change once you know the rules.

**Use this guide for:** the pipeline, data model, storage, rules, cleansing,
metrics, diagnostics, profiling, CI, packaging, dialect support.

**Use `GUIDE-dqt-ui-designer.md` instead for:** screens, layouts, the FastAPI
surface as a *product* surface, report design, anything a DBA looks at.

**Boundary case:** adding a field to `DQMetric` because the UI needs it is an
architect change. Deciding how that field is displayed is a UI change. When both
apply, do the model change first and design against the settled shape.

---

## 1. Evidence discipline

This repository has a documented history of features marked done that had never
been executed once: eleven false `DONE` markers, a CLI that crashed on every
invocation, every CI gate red. The root cause was mechanical — things were
written, documented as complete, and never run.

`docs/HONESTY-GATE.md` is the full rule — what counts as ground truth for each
kind of DQT change, and the mandatory fail→pass transcript for any fix. Read it
before writing a test that claims to verify a bug or security fix. What follows
here is the everyday habit that keeps you inside that rule without re-reading it
every time:

- **Tag every claim you make.** `VERIFIED` means you read the implementing code
  or ran the test *in this session*. `UNVERIFIED` means you inferred it. Both are
  acceptable to say out loud. Silently presenting the second as the first is not.
- **Never infer implementation from a filename, a file size, an export list, or a
  commit message.** A module named `monitoring.py` that returns its input
  unchanged is exactly the trap this rule exists for — and it is a real example
  from this repository.
- **A docstring is not evidence.** Docstrings here have described behaviour that
  did not exist, including examples of return values that were never produced.
- When you cannot verify something in the time you have, say which specific check
  you skipped and what it would take. "I did not read `reports.py`" is useful.
  "It looks fine" is not.

---

## 2. Safety comes before capability

Three refusals to hold regardless of how the request is framed:

**Do not connect write-capable cleansing to the profiling path.** `run()` must
not be able to mutate the database it profiles. If a task says "wire cleanse into
the pipeline", that task is withdrawn — see `CONVENTIONS-DQT.md` §1 (S3). The correct
move is to *remove* the existing call, not to complete it.

**Do not add a raw-SQL rule type.** Rule files are executable input carrying
database privileges. The four-fixed-expression design is what stands between a
YAML file and arbitrary code execution. If someone needs an expression that does
not exist, add a fifth *fixed* expression with its own quoting and binding — do
not add an escape hatch.

**Do not mark cleansing "reversible" without a persisted, machine-executable undo
statement.** A log a human could use to reconstruct the change is an audit trail.
Both are needed; they are not the same thing, and conflating them in a docstring
is how a DBA ends up trusting something that cannot actually be undone.

When a request conflicts with one of these, say so plainly and propose the safe
version. Do not quietly implement a weaker thing under the same name.

---

## 3. How to reason about a change

1. **Locate it in the facet model** (`CONVENTIONS-DQT.md` §2). A change that maps
   to no facet is out of scope — that is what the facet model is for. Service
   metrics, masking, and MDM will each arrive looking reasonable and dressed in
   data-quality vocabulary.
2. **Check whether it touches something already known-broken.** Six of the
   defects in `00-START-HERE.md` §3 change what is safe to build. Extending a
   subsystem before fixing its foundation produces work that has to be redone —
   the clearest case being anything that groups by `dimension` before `NEW-A`.
3. **Take your task from the roadmap (`DQT-01` … `DQT-09`), not from here.**
   Its dependencies are real, not bureaucratic. `BACKLOG.md` holds only defects
   with no ID yet. Do not invent a parallel numbering, and do not fix defects
   outside your task — list what you noticed and fix none of it.
4. **Write the test first — and make it externally grounded.** The honesty gate
   is stricter than "there is a test": a self-referential unit test asserting
   the code does what the code does is not evidence. Use a closed-form identity,
   a published value, a seeded fixture with known expected output, a checksum,
   or a property-based invariant.
5. **For any bug or security fix, prove the test catches the bug.** Revert the
   fix, run the new test, show it fails; restore the fix, show it passes. Paste
   both. A test that passes against the unfixed code protects nothing.
6. **Run the gates and paste real output** — including `doc_audit.py` and the
   collected-test count, which may never decrease. Do not infer from reading the
   code that they would pass.
7. **Update the docs in the same session** if a contract changed. Never edit a
   document to match broken code — fix the code, or mark the claim planned and
   say so. Documentation updated "later" is how this repository got into the
   state the review found.

---

## 4. Things that look like good ideas and are not

- **Adding a dependency to save an afternoon.** Optional capability goes behind
  a `[project.optional-dependencies]` extra. A lean footprint is one of the three
  things DQT can actually be better at than Baselinr or Great Expectations; the
  other two are DBA-first framing and bilingual reporting. Feature count is not
  on that list and will not be won.
- **Adding a third SQL dialect.** Not before `dqt/sql/dialects/` exists. The
  current per-driver branching would triple.
- **Converting the result dataclasses to Pydantic for consistency.** They are
  constructed per column per run. If you change it, change it for a measured
  reason and record it in the data-model doc.
- **Summing the nested issue lists.** See the aggregation contract
  (`CONVENTIONS-DQT-data-model.md` §1). The number will look plausible.
- **Scoring a dimension nobody measured.** `timeliness` with no configured
  reference column is *skipped*, not 1.0.
- **Raising the coverage gate to make the number look better.** Six modules have
  zero unit tests and the gate passes at 80% anyway. Fix the coverage, not the
  threshold.

---

## 5. Reporting your work

Use the roadmap's report format verbatim — `TASK`, `STATUS`, `FILES CHANGED`,
`DESIGN DECISIONS`, `VERIFICATION COMMANDS + OUTPUT`, `PROOF THE TEST CATCHES THE
BUG`, `ACCEPTANCE CRITERIA`, `UNTESTED CODE PATHS`, `CLAIMS I WEAKENED OR
REMOVED`, `NEW RISKS INTRODUCED`, `OTHER DEFECTS NOTICED BUT NOT FIXED`, `WHAT I
DID NOT DO`.

Three of those fields are the ones people quietly drop, and they are the ones
that matter most here: `UNTESTED CODE PATHS` (say "the PostgreSQL path is written
but never executed" rather than nothing), `CLAIMS I WEAKENED OR REMOVED`, and
`WHAT I DID NOT DO`.

If you cannot paste command output for a claim, you have not verified it — say
so. `STATUS: BLOCKED` reported honestly is a better outcome than a task completed
by lowering its bar.
