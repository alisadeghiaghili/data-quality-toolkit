# DQT Document Review — Deliverables Index

Produced 15 August 2026. Persian critical review + corrected English documents.

| File | Replaces | Nature of change |
|---|---|---|
| `DQT-Critical-Review-FA.md` | — (new) | Persian critical review: 2 blockers, 7 major, 8 minor findings, plus external-claim verification. Read this first. |
| `docs/CONVENTIONS-DQT.md` | `CONVENTIONS-DQT.md` | Now canonical. Adds a closed six-dimension vocabulary (§0), a normative safety model (§1: connection roles, plan/apply cleansing, undo statements, rule-file threat model), a supported-dialect matrix (§3), an evidence rule for status claims (§4), verified statuses throughout, and a Withdrawn/Closed register (§6). |
| `docs/CONVENTIONS-DQT-data-model.md` | `CONVENTIONS-DQT-data-model.md` | Adds the aggregation contract (§0) that resolves the double-counting ambiguity; defines `RuleScope` and `SamplingConfig` (previously referenced but never defined); adds `StageError`, `CleansingLog`, `EvidenceConfig`, `CleansingConfig`; run-status semantics; storage schema extended with `connections`, `run_rule_results`, `cleansing_log`, foreign keys, NULL-safe uniqueness indexes, dimension CHECKs, retention. |
| `SKILL-dqt-architect.md` | `SKILLdqtarchitect.md` | No longer restates the conventions (that duplication is what caused the drift). Adds evidence discipline, routing rules vs. the UI skill, non-negotiable safety refusals, and a structured output format. |
| `SKILL-dqt-ui-designer.md` | `SKILLdqtuidesigner.md` | Adds mandatory accessibility (colour is never the sole severity carrier), RTL/bilingual requirements, the aggregation constraint, run-status visibility, and an explicit ban on a cleansing apply action in v0.1. |
| `instruction.md` | `instruction.md` | Reduced to routing and working method; domain rules now live only in the conventions. |
| `docs/dqt_ecosystem.md` | `dqt_ecosystem.md` | Splits `DQT (current)` from `DQT (target)`; replaces the self-certifying "Uses missingly" column with "Extensibility"; adds maintenance status; adds an evidence table for every current rating. |
| `docs/dqt_competitors.md` | `dqt_competitors.md` | Every floor requirement now carries a MET/PARTIAL/NOT MET status (1 of 14 met); competitors carry maintenance status; the MobyDQ "latency" scope trap is called out. |
| `docs/DQT-UI-Ecosystem.md` | `DQT UI Ecosystem.md` | Separates the DataLens research prototype from Yandex DataLens (the BI product), which earlier revisions had conflated into one tool; the BI patterns are reclassified as anti-patterns. |
| `docs/dqt-reference-sources.md` | `dqt-reference-sources.md` | Great Expectations links moved off the unmaintained 0.18 branch; Griffin and Talend reclassified; unverifiable sources marked; a "gaps" section lists design dependencies with no reference. |
| `DQT-Status-Record-Corrected.md` | `DQT_Space_Summary_Complete.md` | Rewritten against read source. Adds a "Retired Claims" section listing five claims from the previous record that do not hold against `main`. |

## The two things to act on first

1. **§S1–S5 of `CONVENTIONS-DQT.md`** — the cleansing safety model. The previously
   recorded task "wire `cleanse` into `run()`" would make the default profiling
   run mutate production. It is formally withdrawn.
2. **§S6a** — `range` bounds from rule YAML are interpolated into SQL as literals.
   Bind them.
