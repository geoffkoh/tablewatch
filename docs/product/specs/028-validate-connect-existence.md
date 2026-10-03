# Spec 028: `validate --connect`, part 1 — datasets and columns exist (I-13, FEATURES H6)

- **Track:** full — the exit-code contract (a new flag on `validate`), credentials and network (`--connect` is the first `validate` that connects), a new module in `src/`.
- **Size:** S. Type suitability and checking every compiled statement (user SQL in `filter`/`where`/`condition`/`query`) stay in I-13 as part 2.
- **Reviewers:** architect (REFINE: Q1–Q3), security-reviewer (REFINE: Q4, Q5), data-steward (REFINE: Q6; VERIFY acceptance), qa-engineer (VERIFY).

**Why this slice:** a misspelt table or column is the commonest cause of a night's `error` outcomes, and checking it needs no per-dialect type map and sends no user-written SQL — the two things that make part 2 the riskier half.

## Problem and persona

Dana renames `email` to `email_address` in a migration, or types `missing_count(emial)`. `validate` passes in CI (it never connects, by rule 6), the PR merges, and the 02:00 run turns the check into `error: no such column: emial` (exit 2), which pages Priya for a mistake that was in the diff. Dana copes by running the whole suite against staging before merging — a full scan of every table. Dana wants CI to say `checks/orders.yml:5:19: column 'emial' not found` in seconds, without reading a row.

Research: dbt's `--empty` flag renders every relation as `(select * from <relation> where false limit 0)` so the warehouse resolves tables and columns without reading data ([docs.getdbt.com/docs/build/empty-flag](https://docs.getdbt.com/docs/build/empty-flag)); Soda's `test-connection` only connects. We borrow dbt's zero-row form.

## Behaviour

- `tablewatch validate --connect` does everything `validate` does, then, for each datasource that has datasets with checks, connects once and asks the database — without reading a row — whether each dataset exists and whether each column a check names exists.
- **Columns a check names** are the column arguments of its metric: `missing_count(email)`, `duplicate_count(id, email)`, `avg(amount)`, `freshness(updated_at)`. Not `sql_metric`'s argument (a label), not `schema`'s option lists (a run-time check of their own), not columns inside user SQL (part 2).
- **Exists** means what `run` would find: the database's own name resolution decides (case, quoting), not a comparison tablewatch makes. `duplicate_count(id, Email)` on SQLite, where `run` passes, is not a problem.
- **No row is read.** Every statement `--connect` sends is built by SQLAlchemy, reads the dataset's `FROM` (the table, or a files dataset's reader) and is zero-row (`WHERE 1 = 0`, Q1). The dataset `filter:` and every other piece of user SQL are not sent.
- One datasource that cannot be reached (an unset `${env:}`, a refused connection, a database file that does not exist) does not stop the others (rule 7); its checks are reported as not checked. `--connect` never creates a database file (SQLite and DuckDB are opened read-only, Q4).
- Plain `validate` is unchanged: no `${env:}` resolution, no connection, no file opened.

### Exit codes (the existing contract, unchanged)

| Found | Exit | Why |
| --- | --- | --- |
| nothing | 0 | |
| any error in a file — offline, or a missing dataset or column | 3 | "the project is invalid": as `validate` today; a retry will not fix it |
| no file error, but a datasource could not be reached | 2 | "could not do its job"; a retry may fix it |
| both | 3 | the certain answer wins; the unreached datasource is still reported |

## Scenarios

Project `p` (SQLite `shop.db` with `orders(id integer, email text, amount real)`, one row):

```yaml
# tablewatch.yml — the fixture writes each datasource in block style, so `down:` is at line 6, column 3
name: probe
datasources:
  shop: {type: sqlite, path: shop.db}
  down: {type: postgres, host: 127.0.0.1, port: 1, database: x, user: u, password: "${env:PGPASS}"}
```

```yaml
# checks/orders.yml          # checks/customers.yml       # checks/remote.yml
dataset: orders              dataset: main.customers      dataset: orders
datasource: shop             datasource: shop             datasource: down
checks:                      checks:                      checks:
  - row_count > 0              - row_count > 0              - row_count > 0
  - missing_count(emial) = 0
  - avg(amount) > 0
  - duplicate_count(id, Email) = 0
```

Messages are on stderr in the `Diagnostic` form (`file:line:col: error: …`); the closing line's wording is the data-steward's (Q6). Today: `validate` exits 0 with `3 datasets, 6 checks — no problems found`; `validate --connect` exits 3 (`No such option`); `run` gives three `error` outcomes and exits 2.

| id | | given | expected |
| --- | --- | --- | --- |
| S1 | must | `examples/retail`, `validate --connect` | stdout `3 datasets, 19 checks — no problems found`, plus that 1 datasource was checked (Q6); exit 0 |
| S2 | must | `p` without `remote.yml` and `customers.yml` | `checks/orders.yml:5:19: error: column 'emial' not found in orders (datasource 'shop')`; exit 3. No line for `Email` (S4) |
| S3 | must | `p` without `remote.yml` | S2's line and `checks/customers.yml:1:1: error: table main.customers not found (datasource 'shop')`; no column lines for a missing table; exit 3 |
| S4 | must | `duplicate_count(id, Email)` on SQLite; the same on DuckDB | no diagnostic (both resolve `Email` to `email`, as `run` does) |
| S5 | must | `p` with only `remote.yml` and `orders.yml` fixed (`email`); `PGPASS` unset | `tablewatch.yml:6:3: error: datasource 'down': environment variable PGPASS is not set — 1 check not checked`, then the closing line `3 datasets, 6 checks — no errors; datasource 'down' not reached (1 check not checked)`; `shop`'s checks still checked; exit 2 |
| S6 | must | as S5 with `PGPASS=x` (port 1 refuses) | the same line with `connection failed — run with -v for details` (D3: never the driver's text for a networked database; it is at INFO with `-v`); exit 2 |
| S7 | must | the whole of `p`, `PGPASS` unset | S2's, S3's and S5's lines, then the closing line `3 datasets, 6 checks — 2 errors; datasource 'down' not reached (1 check not checked)`; exit 3 |
| S8 | must | `p`, plain `validate`, `PGPASS` unset | exit 0, as today; no connection is made and no file is opened (`shop.db` deleted beforehand is not recreated) |
| S9 | must | `shop: {type: sqlite, path: nothere.db}`, `validate --connect` | `tablewatch.yml:5:3: error: datasource 'shop': database file not found — 1 check not checked` (D3); exit 2; `nothere.db` is **not** created (today `run` and `test-connection` create it) |
| S10 | must | a statement log (SQLAlchemy `before_cursor_execute`) over S3 on SQLite and DuckDB | every statement is zero-row (Q1's form) and contains no `filter:`, `where:`, `condition` or `query` text, even when the dataset has a `filter:` |
| S11 | must | `type: files`, `dataset: orders.csv` with a header `id,email`; checks `missing_count(emial) = 0` and, in a second file, `dataset: gone.csv` | the column line at the argument; `checks/gone.yml:1:1: error: …` naming the file not found (the files datasource's existing words); exit 3; the sandbox (spec 023) still applies |
| S12 | must | a parse error in one file (`- missing_count(email = 0`) and S2 in another | the parse diagnostic and S2's line, one pass; exit 3. A check that did not load is not probed |
| S13 | should | `sql_metric(revenue)` with a `query:`, `revenue` not a column | no diagnostic; the query is not sent |
| S14 | must | `--connect` with no results store configured, and with one | the results store is neither opened nor created |
| S15 | should | a column given twice on one dataset, missing (`missing_count(emial)`, `distinct_count(emial)`) | one line per check, each at its own argument |
| S16 | must | `tablewatch validate --help` | documents `--connect`, that it needs credentials, and the exit codes above; the module docstring in `cli/main.py` says the same |

## Non-goals (part 1)

- Type suitability (`avg` on text, `valid_min` on a text column) and checking compiled statements and user SQL — part 2 of I-13.
- `schema` checks' `required_columns`: they are the run-time check of the same question, by design.
- Selectors on `validate --connect` (`--datasource`, paths, tags): the whole project, as `validate`.
- Connection timeouts: the driver's default, as `run` and `test-connection`.
- Changing `run` or `test-connection` creating an empty SQLite file for a mistyped path (S9 measured it): listed under "Not added (backlog freeze)" in REVIEW.
- SARIF output (I-09); the Python API (`tw.validate`) unless Q2 says it must come with the CLI.
- Postgres in CI (I-14 waits on the owner): tests run on DuckDB and SQLite (rule 3); Postgres is covered by compiling the statements only.

## Decisions (REFINE: Q1–Q3 architect, Q4–Q5 security, Q6 data-steward)

- **D1 (Q1).** Zero-row probes with `.where(false())`, no `LIMIT 0`; columns through
  `MetricContext.column`, as metrics do (S4). Probes run in order: all named columns; if that fails,
  `SELECT 1`, and a failure there means the table is missing; otherwise one probe per column. Each
  failure rolls back. No driver text is parsed. On files, "no row is returned" (the sniffer reads a
  sample).
- **D2 (Q2, Q3).** A new `engine/probe.py` with `probe_project(project, *, engine_factory=None,
  max_workers=4) -> ConnectResult`. `ConnectResult` holds `diagnostics` (missing tables and columns)
  and `unreached` (`Unreached(name, reason, location, checks)`), not error Diagnostics, so `Project.ok`
  is untouched. `exit_code(...)` encodes the 0/3/2/3 table, and the CLI only prints. One helper opens
  an engine or returns a reason, shared with the runner and test-connection. `create_engine_for` gains
  `read_only`. The loader records each datasource key's location. `MetricCall.arg_offsets` (`compare=False`,
  not in `__str__`) keeps argument positions out of check identity. `Metric.args_are_columns` is
  `False` on `sql_metric`.
- **D3 (Q4–Q5, security R1–R7; security wins on wording).** The connection is read-only: SQLite
  `file:…?mode=ro` with a properly encoded URI, DuckDB `read_only=True` always, Postgres
  `default_transaction_read_only=on` with `lock_timeout` and `statement_timeout`, and every probe rolls
  back. A missing SQLite or DuckDB file is checked before opening and reads `database file not found`;
  nothing is created (S9). Missing table and column messages carry fixed words plus the names as written,
  never driver text (which can suggest other tables). Only a "not found" failure is a mistake (exit 3);
  anything else is unreached. For networked databases the reason is `connection failed — run with -v
  for details`, with the driver text at INFO; local files may show the driver's first line. S10 logs
  every statement. The README and `--help` warn against running `--connect` with secrets on untrusted
  fork PRs.
- **D4 (Q6).** The data-steward's wording for the column, table and closing lines, and the exit codes
  3/2/3. S6 and S9 follow D3.
