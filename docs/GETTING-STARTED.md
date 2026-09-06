# Getting Started with DQT

> For the person standing DQT up for the first time, against a real database.
> Every command here was run before it was written down. Where something is a
> limitation, it says so rather than leaving you to find out.

DQT points at a live SQL database and computes data-quality statistics **inside
the database**. It does not extract your rows into Python.

You get: profiling statistics, rule violations, quality metrics, a
self-contained HTML report, and an optional read-only web dashboard.

---

## 1. Before you start: the safety rule that matters most

**Connect with a read-only login.** Not because DQT tries to write — profiling
has no code path that mutates — but because `read_only=True` means three
different things:

| Database | What `read_only=True` gives you | Who refuses a write |
|---|---|---|
| SQLite | `mode=ro` on the connection | the driver |
| PostgreSQL | a read-only session | the server |
| **SQL Server** | an ODBC access-mode hint | **nobody** |

On SQL Server the hint is **advisory**. DQT warns you and still refuses to
build a mutating statement itself, but nothing at the server end would stop a
write that reached it. On SQL Server, DQT's own guard is the only guard —
so give it a login that cannot write, and the question stops mattering.

Creating one takes a minute:

```sql
CREATE LOGIN dqt_reader WITH PASSWORD = 'choose-a-strong-one';
CREATE USER dqt_reader FOR LOGIN dqt_reader;
ALTER ROLE db_datareader ADD MEMBER dqt_reader;
GRANT VIEW DEFINITION TO dqt_reader;
```

`db_datareader` covers the data. `VIEW DEFINITION` is what lets DQT discover
tables and columns; without it, discovery returns nothing and DQT reports an
empty database rather than an error.

---

## 2. Install

DQT needs **Python 3.11, 3.12, or 3.14** (all three are tested in CI).

```bash
pip install -e .
```

Then add the driver for your database:

```bash
pip install -e ".[sqlserver]"    # SQL Server (also needs an ODBC driver, below)
pip install -e ".[postgres]"     # PostgreSQL
pip install -e ".[ui]"           # the web dashboard
```

SQLite needs nothing extra — it is built into Python.

### SQL Server needs one more thing pip cannot install

`pip install "dqt[sqlserver]"` installs `pyodbc`, which needs a **system ODBC
driver** underneath it. Install Microsoft's **ODBC Driver 18 for SQL Server**
from Microsoft's download page.

Without it, DQT raises an error naming the missing driver rather than failing
obscurely — but it cannot install it for you.

---

## 3. Your first run

### Against SQL Server, with Windows authentication

```bash
dqt profile --dsn "mssql://sqlprod01/SalesDW" --report-dir reports
```

Omitting the username makes DQT emit `Trusted_Connection=yes`, so it connects
as the Windows account running the command.

### Against SQL Server, with a SQL login

```bash
dqt profile --dsn "mssql://dqt_reader:PASSWORD@sqlprod01:1433/SalesDW" --report-dir reports
```

### If the connection fails on the certificate

This is the most likely thing to go wrong on a first run inside a company.

DQT defaults to `Encrypt=yes;TrustServerCertificate=no`, which is the correct
default and which **many internal SQL Servers fail**, because they use a
self-signed certificate. The error mentions a certificate chain.

Two ways past it, in order of preference:

```bash
# Preferred: still encrypted, but do not verify the certificate.
dqt profile --dsn "mssql://sqlprod01/SalesDW?trust_server_certificate=yes"

# Last resort: no encryption at all. Only on a network you trust.
dqt profile --dsn "mssql://sqlprod01/SalesDW?encrypt=no"
```

Only `driver`, `encrypt`, and `trust_server_certificate` are accepted as DSN
options. Anything else is refused rather than forwarded — an ODBC connection
string is semicolon-delimited key/value pairs, so passing arbitrary text into
one would be a connection-string injection.

### Other databases

```bash
dqt profile --dsn "postgresql://user:pass@host:5432/mydb"
dqt profile --dsn "sqlite:///C:/data/mydb.db"
```

---

## 4. What you get back

A table of metrics and issues in the terminal, plus a **self-contained HTML
report** — one file, no external assets, safe to email:

```
Report: reports/dqt_report_run-4681e24c.html
```

Results are also written to a **run store** (`dqt_runs.db` by default, a SQLite
file). That is what gives you history and what the dashboard reads. Keep it
somewhere stable:

```bash
dqt profile --dsn "..." --store C:/dqt/dqt_runs.db --report-dir C:/dqt/reports
```

### Exit codes

Useful for a scheduled job, and stable across `1.x`:

| Code | Meaning |
|---|---|
| `0` | Nothing gated the run |
| `1` | Error- or critical-severity findings |
| `2` | Warning-severity findings |
| `3` | Configuration or connection problem |
| `4` | Internal error |

`--fail-on` decides **which findings gate the exit code**, and it changes what
you get back. Verified behaviour, on a database with both warnings and errors
present:

| `--fail-on` | Warnings present | Errors present |
|---|---|---|
| `error` *(default)* | `0` | `1` |
| `warning` | `2` | `1` |
| `none` | `0` | `0` |

The row worth noticing is the first one: **with the default settings, warnings
exit `0`.** A scheduled job that only checks "did it exit non-zero" will not
hear about warning-severity findings unless you pass `--fail-on warning`.

A **broken run exits non-zero whatever you set** — `--fail-on none` silences
findings, never failures. That is why `3` and `4` are not in the table above:
no setting suppresses them.

---

## 5. Adding rules

Profiling describes your data. Rules make a **verdict** about it.

Write a YAML file:

```yaml
rules:
  - name: not_null_customer_id
    dimension: completeness
    severity: critical
    scope:
      table_pattern: "customer*"
      column_pattern: "id"
    expression: NOT NULL
    params: {}

  - name: unique_national_id
    dimension: uniqueness
    severity: critical
    scope:
      column_pattern: "national_id"
    expression: UNIQUE
    params: {}

  - name: sane_age
    dimension: validity
    severity: error
    scope:
      column_pattern: "age"
    expression: RANGE
    params:
      min: 0
      max: 130
```

Point a config file at it and pass that to `--config`. There are working
examples in `examples/rules/`.

Five expressions are available: `NOT NULL`, `UNIQUE`, `RANGE`, `REGEX`, and
`REFERENCE` (values must appear in a reference list or table). Rules are
**column-scoped** — there are no table-level rules such as foreign-key
integrity yet.

**`REGEX` does not work on SQL Server.** T-SQL has no regular-expression
operator, so DQT *refuses* the rule rather than reporting zero violations. On
SQLite it works but is a per-row Python callback and will not scale; PostgreSQL
evaluates it natively and is the right place for regex at size.

---

## 6. The dashboard

The web UI is **read-only and has no authentication.**

```bash
pip install -e ".[ui]"
python -m uvicorn dqt.ui.app:app --host 127.0.0.1 --port 8000
```

Then open <http://127.0.0.1:8000/ui>.

Set `DQT_STORE_PATH` if your store is not `dqt_runs.db` in the working
directory:

```bash
set DQT_STORE_PATH=C:\dqt\dqt_runs.db
```

### Read this before making it reachable from other machines

**Bind the loopback address, as above.** What these pages return is schema
names, table names, column names, and a list of exactly where your data is
weakest. Read-only does not mean harmless — that is a map of a production
schema and its soft spots.

Serving it on `0.0.0.0` publishes that to every network the host can reach,
with no login in front of it. If people need to reach it from elsewhere, put
it behind something that authenticates — a reverse proxy with access control,
or an SSH tunnel — and make that a deliberate decision.

### What the dashboard cannot do

**It cannot start a scan.** Every route is a `GET`; there is no run button.
The dashboard shows runs that already happened.

That is not a problem in practice, and the answer is the next section.

---

## 7. Giving it to someone who does not use Python

This is the normal deployment, and it works today:

1. **You** schedule `dqt profile` — Windows Task Scheduler or cron.
2. **You** run the dashboard as a service, bound to loopback on their machine
   or behind an authenticating proxy.
3. **They** open the dashboard and read it. They never touch Python.

A Task Scheduler action for a nightly scan:

```
Program:   C:\Python313\Scripts\dqt.exe
Arguments: profile --dsn "mssql://sqlprod01/SalesDW" --store C:\dqt\dqt_runs.db --report-dir C:\dqt\reports --fail-on warning
Start in:  C:\dqt
```

Every morning the dashboard has fresh numbers, and the rule-history page shows
each rule's pass rate over time.

---

## 8. Cleansing — read this before you use it

Cleansing is the one part of DQT that **writes**. It is never reached by
`dqt profile`; you have to call it deliberately from Python.

It is a three-step cycle, and the split is the safety feature:

```python
from dqt.sql.cleansing import cleanse_plan, cleanse_apply, revert

plan = cleanse_plan(config, configs, store=store)   # reads only, writes nothing
cleanse_apply(plan.plan_id, config, store=store)    # executes the reviewed plan
revert(plan.plan_id, config, store=store)           # puts it back
```

`cleanse_plan` works against a **read-only connection** — producing a plan from
production needs no write authority. Only `cleanse_apply` writes, and it
refuses to run if:

- the plan is unknown, or was already applied (a plan is a one-shot
  authorisation), or
- the connection is read-only, or
- **the data changed since the plan was computed.** Applying a stale plan would
  record before-values that no longer describe what is there, so the undo built
  on it would corrupt rather than restore.

**Known gap, being fixed:** `revert()` does *not* currently make that
last check. If someone edits a row after `cleanse_apply` and before `revert`,
the revert overwrites their edit without warning. Until that lands, do not
revert a plan on a table that has been changed since it was applied.

The older `apply_cleansing()` is deprecated. It returns its audit log instead
of persisting it, so dropping the return value loses the before-values
permanently. Use the three-step cycle.

---

## 9. Troubleshooting

**`No module named uvicorn`** — the dashboard needs its extra:
`pip install -e ".[ui]"`.

**A certificate error on SQL Server** — see §3.

**Discovery finds no tables** — the login is missing `VIEW DEFINITION`. See §1.

**A `RuntimeWarning` about read-only being advisory on SQL Server** — that is
DQT telling you the truth from §1, not a bug. Use a read-only login.

**`import dqt` picks up the wrong copy** — if you have DQT checked out in more
than one place, an old editable install can shadow the one you are working in.
Check with:

```bash
python -c "import dqt; print(dqt.__file__, dqt.__version__)"
```

---

## 10. What DQT does not do

Permanent non-goals, not gaps: service or performance monitoring (latency, CPU,
wait stats), data masking, compliance tooling, and MDM / golden-record.

For where DQT stands against its own capability floor, see
[`dqt_competitors.md`](dqt_competitors.md) §1.
