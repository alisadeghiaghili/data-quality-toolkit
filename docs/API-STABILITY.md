# API stability

What DQT promises not to break, and how something leaves the promise once it
is in it.

This exists because `1.0.0` means, for a library, exactly one thing: a
commitment not to break the public API. That commitment is only meaningful if
the surface was **decided** rather than inherited — otherwise whatever happens
to be importable on release day becomes the promise, including the accidents.

`tests/unit/test_public_api_surface.py` enforces everything on this page. A
document nobody checks is a wish.

---

## 1. What is public

**Everything exported from `dqt` itself.** Import it from there:

```python
from dqt import DQTPipeline, ConnectionConfig, ExitCode, decide_exit_code
```

That surface covers configuring a run, running it, reading the result,
catching what it raises, and gating CI on the outcome. It is asserted by
**equality**, not containment: a name added by accident fails the suite as
loudly as one removed on purpose, because additions to a frozen API are cheap
to make and expensive to undo.

**Plus these submodules, each declaring its own `__all__`:**

| Module | Why it is not at the top level |
|---|---|
| `dqt.sql.cleansing` | Cleansing writes. `Q1` requires reaching it to be a deliberate act rather than an import that happens to be at hand. |
| `dqt.bridges` | Optional by design; DQT is fully usable without any sibling analyser. |
| `dqt.common.storage` | `RunStore` is for tools built on DQT, not for a first run. |
| `dqt.exceptions`, `dqt.exit_codes` | Re-exported at the top level; the modules are the canonical home. |

## 2. What is not public

- **Anything not listed in a module's `__all__`.** A module without one
  re-exports everything it imported, which is how `dqt.sql.cleansing` came to
  advertise `quote_identifier`, `discover_schema` and `get_connection` —
  none of them cleansing's to promise. Every module in the promise now
  declares its surface, so what is public is a decision rather than a
  consequence of an import.
- **Anything under a leading underscore.** `dqt.sql._connect` and
  `dqt.sql._identifiers` hold real machinery that DQT uses internally. The
  underscore is the only signal a Python caller gets, so it carries the whole
  message.
- **The CLI's internal helpers.** `dqt profile`'s flags and
  [exit codes](../README.md#exit-codes) are a contract; the functions behind
  them are not.
- **The storage schema.** `dqt_runs.db` is a local artifact meant to be
  recreated, not migrated. Querying it directly is supported for reading;
  its shape may change in a minor release, and `RunStore.init_schema` refuses
  a store written by an older DQT rather than half-using it.

## 3. What the version number means

`MAJOR.MINOR.PATCH`, and the numbers are claims like any other
(`HONESTY-GATE.md`).

| Change | Version |
|---|---|
| Removing or renaming a public name; changing a signature incompatibly; changing an exit code's meaning | **major** |
| Adding a public name; adding an optional parameter; deprecating something | **minor** |
| Fixing behaviour that was already documented and wrong | **patch** |

A fix that changes what a correct caller observes is not a patch, whatever
its size. If a rule that silently passed starts failing, runs that used to
exit `0` now exit `1` — that is a behaviour change reaching a CI gate, and it
gets a minor at least.

## 4. How something leaves the surface

Removal takes a full minor cycle, and the caller finds out from their own
test suite rather than from a changelog they had no reason to open:

1. **Deprecate.** The name keeps working and emits a `DeprecationWarning`
   naming its replacement and pointing here. Recorded in `CHANGELOG.md` under
   *Deprecated*.
2. **Wait at least one minor release.** Long enough for a caller who upgrades
   normally to see the warning before the removal.
3. **Remove**, in a major release, listed under *Removed*.

A deprecation that never warns is a note; a removal without one is a break.

The replacement has to exist and be at least as capable **before** step 1.
"Use something else" is not a migration path.

## 5. Current deprecations

| Name | Since | Replacement | Why |
|---|---|---|---|
| `dqt.sql.cleansing.apply_cleansing` | 0.1.0 | `cleanse_plan()` / `cleanse_apply()` / `revert()` | It writes its log to memory and returns it, so a caller who drops the return value loses the before-values permanently and the change cannot be undone — the defect `DQT-05` exists to fix. The replacement persists the log against a `plan_id` and can undo automatically. |

## 6. What is deliberately not frozen yet

DQT is `0.x`. Under semver that is *no* stability promise at all, and this
page describes the shape the promise will take rather than one already in
force. Two things have to be true before `1.0.0` claims it:

- **The facet modules are decided.** `sql/knowledge.py` now exists and is
  tested (`NEW-K`); `viz.py` still does not. Freezing a surface with a named
  gap in it means either adding to a frozen API later or admitting the facets
  model overstated what DQT does.
- ~~**The performance work is finished enough to have shaped the
  interfaces.**~~ Done. The approximate-distinct option and grouped rules
  have both landed, and both did change how a rule is evaluated — which is
  exactly why freezing before them would have meant deprecating a
  just-frozen API.
