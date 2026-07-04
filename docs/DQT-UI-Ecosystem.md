# DQT UI Ecosystem Matrix (UX & Flows)

This document compares the planned **DQT UI** with selected data-quality tools
from a **UX / dashboard / flows** perspective:

- Talend Data Quality (and Data Preparation)
- DataLens (ML-oriented data-quality dashboard)
- OpenRefine

Goal: keep DQT's UI honest and simple, while learning from best patterns in
existing tools.

---

## Legend

Per feature:

- `✓✓` — strong support / core to product
- `✓`  — partial support / available but not central
- `~`  — limited / niche
- `-`  — none / out of scope

---

## Features and Flows

Columns:

- **DQ Dashboard** — overall data-quality overview page(s)
- **Schema/Table Explorer** — navigation across DBs/schemas/tables
- **Column Detail** — per-column stats, semantic type, rule status
- **Issue Management** — list of issues, filters, triage flows
- **Rule Management** — create/edit rules, see rule histories
- **Interactive Cleaning** — human-in-the-loop edits and transforms
- **Visualization Richness** — charts, scorecards, visual indicators
- **Workflow Clarity** — end-to-end flow (overview → drill-down → fix → re-check)
- **User-in-the-loop** — explicit mechanisms for rule validation, labeling, approval
- **Complexity Level** — how heavy/complex the UI feels for non-experts (Low/Medium/High)

---

## Matrix

| Tool / UI             | DQ Dashboard | Schema/Table Explorer | Column Detail | Issue Management | Rule Management | Interactive Cleaning | Visualization Richness | Workflow Clarity | User-in-the-loop | Complexity Level |
|-----------------------|-------------|-----------------------|--------------|------------------|-----------------|----------------------|------------------------|------------------|------------------|------------------|
| **DQT UI (target)**   | ✓✓          | ✓✓                    | ✓✓           | ✓✓               | ✓               | ~                    | ✓✓                     | ✓✓               | ~                | **Low–Medium**   |
| **Talend DQ UI**      | ✓✓          | ✓                     | ✓✓           | ✓✓               | ✓✓              | ✓                    | ✓✓                     | ✓                | ~                | Medium–High      |
| **DataLens**          | ✓✓          | ~ (dataset-centric)   | ✓            | ✓✓               | ~               | ✓✓                   | ✓✓                     | ✓                | ✓✓               | Medium           |
| **OpenRefine**        | ~ (project list + facets) | ~        | ✓            | ~                | -               | ✓✓                   | ✓                      | ✓                | ✓                | Medium           |

---

## Tool Notes

### DQT UI (target)

**Intended design:**

- Dashboard: one or more overview screens showing:
  - per-database / per-schema data-quality scores,
  - counts of issues by severity and dimension,
  - trend charts of data-quality scores over time.
- Explorer:
  - sidebar with schemas/tables,
  - main panel with per-table metrics, last-check status, and quick links.
- Column detail:
  - stats (min/max, distinct, null ratio),
  - semantic type (email, IBAN, etc.),
  - associated rules and pass/fail status.
- Issues:
  - table listing issues with filters (dimension/severity/status),
  - drill-down into evidence and affected rows.
- Rules:
  - simple view/edit of rule definitions and their latest results (no huge rule IDE).
- Cleaning:
  - minimal guided actions (e.g., mark as ignore, trigger standardization routines);
    heavier, interactive transformations are not core.
- Visualization:
  - scorecards, bar/line charts, simple trend plots, traffic-light indicators.
- Workflow:
  - "Pick connection → run checks → overview → drill down → fix → re-run → export report".
- User-in-the-loop:
  - basic acknowledgment/override mechanisms; no full labeling/ML training UI.

Target complexity: **Low–Medium** — DBAs should feel at home quickly.

### Talend Data Quality UI

Talend's DQ/DP UI provides:

- Dataset overview with **quality bars** (valid/invalid/empty) and rule compliance bars.
- Column headers with mini quality bars indicating distribution of valid/invalid/empty values.
- Color-coded indicators (green/gray/red) tied to semantic type and rules.
- Graphical profiling: charts and tiles showing distributions and anomalies.
- Rules and semantic types manageable via UI, with strong compliance indicators.

Strengths:

- Very strong visualization for column-level quality (quality bars, colors).
- Clear indicators in dataset overview and header: user can see quality at a glance.
- Integrated rule management and trust score.

Weaknesses for DQT context:

- Heavier product, more complex than desired for a lean SQL toolkit.
- Mixed focus on compliance/masking and data preparation, beyond DQT's scope.

### DataLens UI

DataLens is an ML-oriented interactive dashboard for tabular data quality:

- Dashboards composed of widgets (charts, tables) with cross-filtering, selectors, parameters.
- Integrated profiling, error detection and repair, using statistical, rule-based and ML-based methods.
- User-in-the-loop modules for:
  - interactive rule validation,
  - labeling,
  - custom rule definition.
- Iterative cleaning: dashboard helps select and sequence cleaning strategies.

Strengths:

- Strong interactive visualization and dashboard model (widgets, filters, multiple pages).
- Powerful user-in-the-loop flows for rule validation and repair.
- Good foundation for future DQT evolution if ML-based detection becomes important.

Weaknesses for DQT context:

- More complex than what a DBA needs initially.
- ML-heavy; DQT should borrow patterns, not complexity.

### OpenRefine UI

OpenRefine UI is project-centric with faceted exploration:

- Main grid of data, with:
  - facets/filter panel on the side,
  - undo/redo history,
  - per-column drop-down menus for transforms and facets.
- Interactive cleaning:
  - clustering functions,
  - text transformations,
  - faceted operations.
- Strong for manual exploration and fixing messy data.

Strengths:

- Very good for human-in-the-loop cleaning and exploration.
- Clear layout: data grid + facets + history = powerful yet understandable.

Weaknesses for DQT context:

- Focused on one dataset/project, not on multi-schema SQL DB overview.
- Little concept of rules/metrics over time; more of a cleaning workbench.

---

## Design Implications for DQT UI

Based on this comparison:

- **Borrow from Talend:**
  - quality indicators at column and dataset level (bars and colors),
  - clear tiles in overview showing valid/invalid/empty distribution.
- **Borrow from DataLens:**
  - dashboard organization with widgets (scorecards, charts, tables),
  - simple user-in-the-loop mechanisms (approve/override rules, flag issues).
- **Borrow from OpenRefine:**
  - faceted/filtered views for issues and columns,
  - clear history and context when applying cleansing actions.

But keep DQT UI:

- **Lean and DBA-focused:**
  - fewer screens,
  - plain language, tight scope (data quality only),
  - low friction to go from overview → diagnosis → fix → report.

Use this matrix as the **UI/UX north star**:
- any new screen or component should be explicitly mapped here,
- complexity must be kept at or below the "Low–Medium" band for DQT UI.
