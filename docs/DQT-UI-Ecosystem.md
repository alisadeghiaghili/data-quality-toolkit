# DQT UI Ecosystem Matrix (UX & Flows)

> *Verified against the repository on 2026-08-17 at commit `4629925`. Statuses rot — re-check before relying on one.*


Compares the planned **DQT UI** with other data-quality tools from a UX /
dashboard / flows perspective.

> **Correction notice.** The previous revision compared DQT against a tool called
> "DataLens" whose description blended two unrelated products: the research
> prototype in arXiv:2501.17074 (an ML-oriented tabular data-quality dashboard)
> and **Yandex DataLens**, a commercial cloud BI product. The BI features
> attributed to it — dashboards composed of widgets, cross-filtering, selectors,
> dashboard parameters, multi-page dashboards — belong to the BI product, not the
> research tool.
>
> This matters beyond pedantry: "Borrow from DataLens: dashboard organization
> with widgets" was a design instruction pointing DQT toward being a
> general-purpose BI tool, which is explicitly out of scope. The two are now
> separated, and the BI patterns are recorded as **anti-patterns** for this
> product.
>
> Maintenance status has also been added. Talend's open-source edition was
> retired in January 2024.

---

## Legend

`✓✓` strong / core to product · `✓` partial · `~` limited / niche · `-` none

---

## Columns

**DQ Dashboard** · **Schema/Table Explorer** · **Column Detail** ·
**Issue Management** · **Rule Management** · **Interactive Cleaning** ·
**Visualization Richness** · **Workflow Clarity** · **User-in-the-loop** ·
**Accessibility** (colour-independent severity encoding, keyboard path, contrast)
· **Complexity Level**

---

## Matrix

| Tool / UI | Status | DQ Dashboard | Explorer | Column Detail | Issues | Rules | Interactive Cleaning | Viz Richness | Workflow Clarity | User-in-loop | Accessibility | Complexity |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **DQT UI (current)** | Pre-alpha | - | - | - | - | - | - | - | - | - | - | — (read-only backend only; no frontend) |
| **DQT UI (target v1.0)** | — | ✓✓ | ✓✓ | ✓✓ | ✓✓ | ✓ | ~ | ✓✓ | ✓✓ | ~ | ✓✓ | **Low–Medium** |
| **Talend DQ UI** | Commercial (OSS retired 2024) | ✓✓ | ✓ | ✓✓ | ✓✓ | ✓✓ | ✓ | ✓✓ | ✓ | ~ | ~ | Medium–High |
| **DataLens (research prototype)** | Research | ✓✓ | ~ (dataset-centric) | ✓ | ✓✓ | ~ | ✓✓ | ✓✓ | ✓ | ✓✓ | Unknown | Medium |
| **OpenRefine** | Active | ~ (project list + facets) | ~ | ✓ | ~ | - | ✓✓ | ✓ | ✓ | ✓ | ~ | Medium |
| **Great Expectations Data Docs** | Active | ✓ | ~ | ✓✓ | ✓✓ | ✓✓ | - | ✓ | ✓ | - | ✓ | Low–Medium |
| *(reference only)* Yandex DataLens | Commercial BI | ✓✓ (generic BI) | - | - | - | - | - | ✓✓ | ✓ | ✓ | ✓ | High — **out of scope pattern** |

**Note on the DQT rows:** the `current` row is empty on purpose. Filling it
with the target values — as the previous single-row version effectively did —
makes the matrix unusable as a progress measure.

**What actually exists (verified 2026-08-17).** More than the previous revision
assumed, and it is worth being precise about, because the gap is narrower than
"no UI" suggests:

- `src/dqt/ui/api.py` — a real read-only data-access layer over `RunStore`,
  returning plain dicts. No domain models cross the boundary. This is a sound
  design and should be preserved as the single data path for every consumer.
- `src/dqt/ui/app.py` — a FastAPI skeleton exposing `GET /runs`,
  `/runs/{run_id}`, `/runs/{run_id}/tables`, `/runs/{run_id}/metrics`,
  `/runs/{run_id}/issues`, `/health`. Behind the `ui` extra
  (`fastapi`, `uvicorn`).
- Neither module has any tests.
- There is no frontend of any kind, so every `-` in the `current` row above is
  still accurate as a *user-facing* assessment.

So the honest position is: the backend contract for a UI largely exists and is
untested; the UI does not. Two of the target row's columns are closer than the
matrix implies, and none of them are reachable by a user yet.

---

## Tool Notes

### DQT UI (target)

Screens, navigation, accessibility, and RTL requirements are specified by the
`dqt-ui-designer` skill and constrained by `CONVENTIONS-DQT.md`. Summary of
intent:

- Overview with per-dimension scorecards, issue counts by severity/dimension,
  score trend over time, and a **prominent run-status badge** so a `partial` or
  `failed` run never renders as a healthy one.
- Explorer: schema/table sidebar; per-table metrics, issue counts, last-check
  timestamp, and an explicit marker when values are sampled/approximate.
- Column detail: stats, semantic type, rules and their pass/fail status.
- Issues: filterable table (dimension / severity / rule), drill-down to evidence.
- Rules: view definitions and **history over time**; surface rules matching zero
  targets.
- Cleaning: **read-only plan display at most in v0.1.** No apply action in the UI.
- Visualization: scorecards, bar/line charts, trend plots, severity indicators
  encoded by colour **and** icon or label.

Target complexity: **Low–Medium**.

### Talend Data Quality UI — Commercial

Dataset overview with **quality bars** (valid / invalid / empty) and rule
compliance bars; per-column mini quality bars in the column headers; colour-coded
indicators tied to semantic type; graphical profiling tiles; UI-managed rules and
semantic types with a composite trust score.

**Strengths:** the best column-level quality visualization in this space. Quality
at a glance, with no drill-down required to know where to look.

**Weaknesses for DQT:** a heavy product with mixed focus (compliance, masking,
data preparation) well beyond DQT's scope. And the open-source edition no longer
exists, so it is a design reference rather than an adoptable baseline.

**Borrow:** the column-header quality bar, and the valid/invalid/empty tile in the
overview. These map directly onto `DQMetric` and require no new concepts.

### DataLens (research prototype) — Research

An interactive dashboard for tabular data quality combining statistical,
rule-based and ML-based detection with repair, plus user-in-the-loop modules for
rule validation, labeling, and custom rule definition, and iterative selection of
cleaning strategies.

**Borrow:** the *user-in-the-loop pattern* — letting a domain expert confirm,
override, or dismiss a machine-proposed finding. Scaled down for DQT, this is
"acknowledge / ignore / mark false-positive" on an issue, which is a small,
valuable feature.

**Do not borrow:** the ML machinery. DQT has no ML surface and does not need one
to be useful.

### OpenRefine — Active

Data grid with a faceted filter panel, undo/redo history, and per-column
transform menus.

**Borrow:** faceted filtering for issue and column lists, and the treatment of
**undo as a first-class product feature rather than a log**. OpenRefine's undo
model is the correct mental model for DQT's `undo_statement` requirement.

**Not applicable:** single-project focus, no multi-schema SQL overview, no notion
of metrics over time.

### Great Expectations Data Docs — Active

Generated static HTML documenting expectations, validation results, and data
assets.

**Borrow:** the idea that a **static, self-contained, shareable HTML artifact** is
often more useful to a DBA than a server-backed dashboard — it can be emailed,
attached to a ticket, and archived. DQT already generates self-contained HTML;
this validates that direction and suggests investing there before investing in
the frontend.

### Yandex DataLens — reference only, out of scope

A commercial BI platform: dashboards assembled from widgets, cross-filtering,
selectors, dashboard parameters, multi-page dashboards, ad-hoc chart building.

**Listed only to prevent re-confusion with the research prototype above.**

**Explicit anti-patterns for DQT** — do not implement any of these:

- a widget builder or configurable dashboard layout,
- cross-filtering engines and dashboard parameter systems,
- ad-hoc chart construction by the user,
- a general query/pivot surface.

DQT's screens are fixed, opinionated, and answer specific data-quality questions.
Every step toward configurability is a step toward becoming an unfinished BI
tool.

---

## Design Implications for DQT UI

**Borrow:**

- from **Talend** — column-level and dataset-level quality bars; valid / invalid /
  empty tiles;
- from **OpenRefine** — faceted filtering; undo as a real feature with visible
  history;
- from **DataLens (research)** — lightweight user-in-the-loop: acknowledge,
  override, flag as false positive;
- from **GX Data Docs** — the shareable, self-contained static report artifact.

**Reject:**

- BI-style configurable dashboards, widgets, and cross-filtering (Yandex DataLens);
- masking / compliance / data-preparation surfaces (Talend);
- ML training and labeling UI (DataLens research);
- any screen that cannot be mapped to a facet in `CONVENTIONS-DQT.md` §2.

**Keep DQT UI lean:** few screens, plain language, tight scope, and a short path
from overview → diagnosis → fix → report. Complexity must stay at or below the
**Low–Medium** band. Any new screen or component must be added to this matrix in
the same change that proposes it.
