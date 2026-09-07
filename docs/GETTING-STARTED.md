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

Per column: **null count, distinct count, minimum, maximum and mean**, plus a
completeness score. A cell reading `n/a` means the statistic was not produced
rather than that it is zero — a text column has no mean, and saying `0` would
be a number DQT never computed.

All six quality dimensions are measured, but two of them need you to say
what you expect.

**Four are answerable from the data alone** — completeness, uniqueness,
consistency and referential integrity. A dimension scores even when nothing is
wrong, so "measured and fine" reads differently from "not measured".

**Validity** needs an expectation, which classification supplies: turn it on
(§5b) and a column recognised as email will report the values that are not
emails.

**Timeliness** reports how old your newest row is without being told anything,
but will not call it *stale* until you say what stale means:

```yaml
timeliness:
  max_age_days: 7
```

Forty days is alarming for an order ledger and unremarkable for an archive.
DQT will not guess which yours is.

**Consistency** is the one people ask about. It does not mean "valid" — it
means *written the same way every time*. A `tier` column holding `gold`,
`Gold` and `GOLD` is one value recorded three ways, and a distinct count
cannot see it because those genuinely are three distinct values. That is
exactly what cleansing's `standardize` operation fixes.

DQT also reads your **foreign keys** and counts orphan rows — rows whose
reference names a parent that does not exist. Those appear under the
`referential_integrity` dimension. A row whose foreign key is NULL is *not* an
orphan: it references nothing, which the null count already tells you.

All of it costs **one query per table**, whatever the column count, so a wide
table is not a slow one.

You get a table of metrics and issues in the terminal, plus a **self-contained
HTML report** — one file, no external assets, safe to email:

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

Eight expressions are available. Five apply to a **column** — `NOT NULL`,
`UNIQUE`, `RANGE`, `REGEX` and `REFERENCE` (values must appear in a reference
list or table).

Three apply to a **table**, and answer questions no column rule can:

```yaml
  # A composite key your schema does not declare.
  - name: order_line_is_unique
    dimension: uniqueness
    severity: critical
    scope: {table_pattern: "order_lines"}
    expression: UNIQUE_TOGETHER
    params: {columns: [order_id, line_no]}

  # Referential integrity for a relationship the database does NOT enforce --
  # which is exactly where orphan rows accumulate.
  - name: customer_must_exist
    dimension: referential_integrity
    severity: error
    scope: {table_pattern: "order_lines"}
    expression: FOREIGN_KEY
    params:
      columns: [customer_id]
      references_table: customers
      references_columns: [id]

  # "When status is shipped, shipped_at must be set."
  - name: shipped_needs_a_date
    dimension: consistency
    severity: error
    scope: {table_pattern: "order_lines"}
    expression: CONDITIONAL_NOT_NULL
    params: {when_column: status, when_equals: shipped, then_column: shipped_at}
```

Omit `column_pattern` for a table rule — it runs once per table, not once per
column.

**No rule takes SQL from you.** Column and table names are quoted and checked
against the table before any query runs; values are bound parameters. That is
deliberate: a rule carrying a raw predicate would be more expressive and would
hand a config file the ability to run arbitrary SQL.

**`REGEX` does not work on SQL Server.** T-SQL has no regular-expression
operator, so DQT *refuses* the rule rather than reporting zero violations. On
SQLite it works but is a per-row Python callback and will not scale; PostgreSQL
evaluates it natively and is the right place for regex at size.

---

## 5b. Naming what a column holds (optional)

DQT can infer each column's **semantic type** — email, IBAN/Sheba, Iranian
national ID, mobile or landline number, Shamsi date — and show it in the
report beside the database type.

**It is off by default, and the reason is what it reads.** Every other stage
computes inside the database and brings back numbers. A checksum cannot work
that way: recognising a national ID means seeing the ten digits. So this is
the one stage that pulls real values into your Python process — and the
validators are most useful exactly where the values are the ones you would
least want copied. Turning it on should be your decision.

Enable it in the config file:

```yaml
connection_id: sales
classification:
  enabled: true
  sample_size: 500          # rows read per table; the read is always bounded
  persian_normalization: true   # fold Persian/Arabic digits before matching
```

When enabled it costs **one bounded query per table** — not one per column,
and never an unbounded read.

A column that was examined and matched nothing reads `unknown`. A column that
was never examined reads `n/a`. Those are different answers and the report
keeps them apart.

## 6. The dashboard

The web UI is **read-only and has no authentication.**

```bash
pip install -e ".[ui]"
dqt serve --store C:\dqt\dqt_runs.db
```

Then open <http://127.0.0.1:8000/ui>. Use `--port` for a different port.

### DQT refuses to publish itself, and you should know why

`dqt serve` binds `127.0.0.1` — reachable only from the machine it runs on —
and **refuses any other address** unless you say explicitly that something
authenticates in front of it:

```
$ dqt serve --host 0.0.0.0
Configuration error: Refusing to bind '0.0.0.0': the dashboard has no
authentication, and that address is reachable from other machines...
```

That is not caution for its own sake. What these pages return is schema names,
table names, column names, and a ranked list of exactly where your data is
weakest. Read-only does not mean harmless — that is a map of a production
schema and its soft spots, served without a login to anyone who can open the
port.

If a reverse proxy or tunnel already authenticates in front of DQT, say so:

```bash
dqt serve --host 0.0.0.0 --allow-unauthenticated-remote-access
```

### What the dashboard cannot do

**It cannot start a scan.** Every route is a `GET`; there is no run button.
The dashboard shows runs that already happened.

That is not a problem in practice, and the answer is the next section.

---

## 5c. Which columns go missing together (optional)

Completeness tells you *how much* is missing. This tells you *what is missing
with what*:

```yaml
missingness:
  enabled: true
  top_patterns: 5
```

```
2 columns are missing together in 'leads': email, phone are all NULL in 3 row(s).
2 columns are missing together in 'leads': company, source are all NULL in 2 row(s).
```

Three columns each 20% NULL might be one upstream feed dropping all three from
the same fifth of your rows, or three unrelated gaps. **The null counts are
identical either way** — only the pattern distinguishes them, and the first is
one bug while the second is three.

Off by default because it costs a second scan of each table, on top of the one
profiling already makes.

Rows missing *nothing* are not reported, and neither is a single column on its
own — that is just the null count again.

**This counts; it does not explain.** Whether the missingness is random is a
statistical question, and `missingly` answers it through DQT's bridge. DQT
reports the pattern; missingly explains it.

## 6a. Watching quality change over time

Every metric records how far it moved since the previous run against the same
store. That happens automatically — it is what the store is for.

DQT will not call a change a *problem* until you say how far is too far:

```yaml
monitoring:
  max_score_drop: 0.1     # a dimension score may fall 10 points between runs
```

Then a bigger fall is reported:

```
WARNING  people  email  completeness
  Drift: completeness on 'people.email' fell 0.750 since the previous run,
  past the 0.1 tolerance (1.000 -> 0.250).
```

Three things worth knowing:

- **An improvement is never reported.** A tolerance on the size of the change
  would alert you whenever your data got cleaner.
- **A first run cannot drift.** There is nothing to have drifted from, and a
  metric seen for the first time is recorded as having no drift rather than
  zero drift.
- **Tables drift too, not just columns.** A table's score is the mean of its
  columns, so a table-wide decline shows up even when no single column crossed
  the line.

A score that swings ten points a day is alarming on a customer table and normal
on a staging table that is truncated and reloaded. DQT will not guess which
yours is.

## 6b. `dqt check` — rules only, for CI

`dqt profile` computes statistics and writes a report. When all you want is a
gate, `dqt check` evaluates the rules and nothing else:

```bash
dqt check --dsn "mssql://sqlprod01/SalesDW" --rules rules.yaml --fail-on warning
```

It is genuinely cheaper: rules need the table list, not the profile, so no
column statistics are computed. Same exit codes as `profile`.

**Running it with no rules exits `3`, not `0`.** A gate that checks nothing
must not report success — that failure would be silent, in CI, exactly where
nobody is watching.

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

Run the dashboard the same way — as a service, on their machine:

```
Program:   C:\Python313\Scripts\dqt.exe
Arguments: serve --store C:\dqt\dqt_runs.db
```

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

**Telling a DQT failure from a bug in your script** — every error DQT raises
for a condition of its own descends from `DQTError`:

```python
from dqt import DQTError, ConfigurationError, ReadOnlyViolationError

try:
    pipeline.run()
except ConfigurationError:
    ...   # the run never happened; fix the config
except DQTError:
    ...   # DQT failed; alert
```

Each type also inherits the built-in it replaced, so `except ValueError`
around older code keeps working.

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
