# Guide — DQT UI Designer

> **This is a reference document, not installed tooling.** It has no runtime
> effect and activates nothing. It is prose to read when designing anything a
> DBA looks at. It was previously named `SKILL-*`, which implied a registered
> capability that does not exist.
>
> It does not override `docs/CONVENTIONS-DQT.md`. Where a screen would require
> breaking the safety model, the safety model wins and the screen does not ship.

**Use this guide for:** screens, layouts, HTML reports, the read-only API as a
product surface, severity presentation, bilingual and RTL output.

**Use `GUIDE-dqt-architect.md` instead for:** the data model, pipeline, storage,
rules, cleansing internals.

---

## 1. What exists today

More than the docs used to assume. Verified 2026-08-17:

- `src/dqt/ui/api.py` — a genuine read-only data-access layer over `RunStore`.
  Returns plain dicts and lists; no DQT domain models leak across the boundary.
  This is a good boundary. Keep it.
- `src/dqt/ui/app.py` — a FastAPI skeleton exposing `GET /runs`,
  `/runs/{run_id}`, `/runs/{run_id}/tables`, `/runs/{run_id}/metrics`,
  `/runs/{run_id}/issues`, `/health`. Behind the `ui` extra.
- `sql/reports.py` — self-contained HTML with score bars and severity badges.

Neither the UI module nor the report generator has any tests. There is no
frontend. Before designing new screens, be honest about which of these three
surfaces the work actually lands on.

---

## 2. Hard constraints

**No cleansing `apply` action in the UI in v0.1.** Not a button, not a menu item,
not behind a confirmation dialog. This holds even after `DQT-03` and `DQT-05` make
apply technically safe. A destructive database operation should require a
deliberate CLI invocation with an explicit flag and a prior plan — the friction is
the feature. A UI button turns a considered operation into a mis-click.

Showing a *plan* — the proposed change set, the forward and undo SQL, the
affected-row counts — is in scope and genuinely useful. Executing it is not.

**Never display a summed nested count.** `PipelineResult.issues` is the only
canonical list; the per-schema, per-table and per-column lists are overlapping
views (`CONVENTIONS-DQT-data-model.md` §1). Every total on screen must state what
it counted: "312 issues in this run" or "18 issues in this table", never an
unlabelled 330 produced by adding them.

**Do not group or filter by `dimension` yet.** The field currently holds real
dimensions from some emitters and metric names (`row_count`, `table_count`) from
others. A dimension filter built today returns wrong results that look right.
Blocked on `NEW-A`.

**Never render `evidence` unescaped.** It contains sample values pulled from
profiled columns — that is attacker-adjacent content arriving from the database.
Escape on render.

**Never surface a DSN, credential, or connection string.** Show the
`connection_id`, never the `dsn`.

---

## 3. Accessibility

**Colour must never be the sole carrier of severity.** Every severity indicator
pairs colour with a text label or a distinct shape/icon. Around 8% of men have
some form of red–green colour deficiency, and this is a tool whose entire job is
saying "this is fine" versus "this is not" — a distinction a meaningful fraction
of users would not be able to see.

Also required:

- Text contrast at WCAG AA (4.5:1 for body, 3:1 for large text). Check the
  severity badge colours specifically — they are usually where this fails.
- Every interactive element reachable and operable by keyboard, with a visible
  focus indicator.
- Data tables with real `<th>` headers and scope, not styled `<div>`s.
- Score bars carry their numeric value as text, not only as a bar length.
- The HTML report must remain readable and complete with CSS disabled. It is an
  artifact people email, archive, and print.

---

## 4. Bilingual and RTL

Persian output is a real differentiator and a real cost. Do not claim it before
it works.

- The report template needs `dir="rtl"` handling at the block level, not a single
  page-level attribute. A Persian report contains English identifiers — table
  names, column names, SQL — and those runs must be `dir="ltr"` inside RTL
  paragraphs or they render scrambled.
- Numbers, dates, and severity keywords need a decided convention. Pick one
  (recommendation: keep dimension and severity identifiers in their canonical
  English snake_case everywhere, and translate only the surrounding prose — the
  identifiers are a vocabulary, and translating a vocabulary breaks the ability
  to grep, search, and compare across languages).
- Mirror the layout, not the data. Charts, score bars, and time axes keep their
  reading direction; navigation and text flow mirror.
- PDF is a separate problem from HTML. Arabic-script shaping needs an engine that
  does it (WeasyPrint) and an embedded licence-cleared font (Vazirmatn). Neither
  is in `pyproject.toml`, and no roadmap task covers it yet.
- A test must assert *shaped* Persian output, not the presence of Persian bytes.

---

## 5. Design direction

The audience is a DBA who already knows their schema and wants to know what
changed and what is wrong. Not an analyst exploring. Not an executive wanting a
number.

That implies:

- **Lead with issues, not scores.** A composite quality score is a decoration; a
  ranked list of what is broken, where, and with what evidence is the product.
- **Every issue must be actionable without leaving the screen.** Show the
  evidence — counts, sample values, the rule that fired. If a DBA has to go write
  a query to understand an issue, the issue display failed.
- **Show absence honestly.** A dimension that was skipped (no `timeliness`
  reference column configured) must read as "not measured", visually distinct
  from "measured, passed". Blank space that looks like a pass is a lie.
- **Untested subsystems should be visibly marked in any status view.** Six
  modules have no tests. A UI that presents their output with the same confidence
  as the tested rule engine is overstating what it knows.

Worth borrowing (see `docs/dqt_competitors.md`): Talend's column-level quality
bar showing valid/invalid/empty distribution in the column header — it maps
cleanly onto `DQMetric` and is the best single UX idea in the competitive set.
OpenRefine's faceted issue browsing and first-class undo history are the right
mental model for anything cleansing-adjacent.
