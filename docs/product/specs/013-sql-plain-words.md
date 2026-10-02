# Spec 013: Datasource errors in plain words (I-35, part 1)

Status: ready (iteration 13 PLAN, 2026-09-30). Backlog item: I-35. Size: S.

## Problem and persona

**Dana, analytics engineer**, adds a Snowflake datasource to
`tablewatch.yml` by URL and opens the check page, or runs `tw compile`:

> "It says `Can't load plugin: sqlalchemy.dialects:snowflake`. Is my URL
> wrong? Is Snowflake unsupported? I had to search the SQLAlchemy docs to
> learn I need `pip install snowflake-sqlalchemy`."

**Sam, platform engineer**, typos a URL (drops the `://`). Today's message,
"the url is not a SQLAlchemy URL (expected scheme://...)", names neither the
datasource nor the file, so with three URL datasources Sam bisects by hand.
A run says `Could not parse SQLAlchemy URL from given URL string` - a
different message for the same mistake.

**Priya, data steward** (reads the check page, does not edit YAML), sees a
check whose datasource is misspelled: the Datasource row is blank and the SQL
section says "this dataset's datasource is not defined". She cannot tell
what name was written. (That part is split to I-35 part 2; see Non-goals.)

How they cope today: search the SQLAlchemy error text; bisect datasources.

## Today (measured on `b6f0416`, SQLAlchemy as locked)

`URLDatasource` built directly; `compile` = `dialect_for` (shown by
`tw compile` as `-- cannot compile: <text>` and served as `error` on
`/checks/{id}/sql`); `run` = `create_engine_for` (recorded on every check
of the datasource as `datasource <name>: <text>`; also `tw test-connection`
as `FAILED  <name>: <text>`).

| URL | compile today | run today |
| --- | --- | --- |
| `snowflake://u:p@acct/db` (dialect not installed) | `unsupported SQLAlchemy URL scheme 'snowflake': Can't load plugin: sqlalchemy.dialects:snowflake` | `Can't load plugin: sqlalchemy.dialects:snowflake` |
| `user:secret@host/db` (no `://`) | `the url is not a SQLAlchemy URL (expected scheme://...)` | `Could not parse SQLAlchemy URL from given URL string` |
| `a+b+c://x` (two drivers) | `the url is not a SQLAlchemy URL (expected scheme://...)` | **uncaught `ValueError: too many values to unpack (expected 2)`** |
| `mysql://u@h/db` (dialect present, DBAPI driver missing) | compiles (dialect only) | **uncaught `ModuleNotFoundError: No module named 'MySQLdb'`** |

The last two rows break design rule 7: `_run_datasource` in
`engine/runner.py` catches only `DatasourceError` and
`MissingEnvironmentVariableError`, so the exception leaves the worker and
`future.result()` ends the whole run with a traceback (the per-dataset net
does not cover engine creation). The crash exits **1**, the "checks
failed" code, so an orchestrator reads a tablewatch crash as bad data.
`tw test-connection` crashes the same way on both rows (it catches only
`DatasourceError`, `MissingEnvironmentVariableError` and `SQLAlchemyError`),
also exit 1. `mssql+pyodbc://` (no `pyodbc`) and `oracle://` (no `oracledb`)
crash identically to the `mysql` row. This spec fixes them with the
messages: same bug family, same function. (Rows re-measured on a scratch
project in REFINE, 2026-10-02, SQLAlchemy 2.1.0.)

Neither the compile nor the run message names the datasource or
`tablewatch.yml`; the compile path is shown under a dataset header, the run
path is prefixed `datasource <name>:` by the runner.

## Outcome

Every datasource problem reads the same in `tw compile`, the check page's
SQL section (`/checks/{id}/sql` `error`), a run's recorded `error`, and
`tw test-connection`: it names the datasource and `tablewatch.yml`, says
what is wrong in words, and for a missing driver says what to install. A
broken URL never ends a run: its checks get `error` outcomes (rule 7). No
message ever contains the URL or any part of it but a well-formed scheme.

## Acceptance scenarios

Common setup: `tablewatch.yml` defines one URL datasource named
`warehouse` and one dataset file `checks/orders.yml`:

```yaml
# tablewatch.yml
name: shop
datasources:
  warehouse:
    type: sqlalchemy
    url: <URL from the scenario>
```

```yaml
# checks/orders.yml
dataset: orders
datasource: warehouse
checks:
  - row_count > 0
```

Below, `P` is the prefix `datasource 'warehouse' in tablewatch.yml: `.
"Compile" means `tw compile` prints `-- cannot compile: P<reason>` and
exits 0 (unchanged exit), and `GET /api/v1/checks/{id}/sql` returns
`"error": "P<reason>"`, `"dialect": null`, `"datasource": "warehouse"`.
"Run" means `tw run` records `error` on the check with message
`P<reason>`, the run completes, and exit code is 2 (unchanged contract).
"Test-connection" means `tw test-connection` prints
`FAILED  warehouse: <reason>` and exits 2.

**S1 (must). Dialect not installed, known database.** URL
`snowflake://u:p@acct/db`, no `snowflake-sqlalchemy` installed. Compile,
run and test-connection all give reason:
`the snowflake driver is not installed: pip install snowflake-sqlalchemy`.
The text `Can't load plugin` appears nowhere. (Colon, not semicolon: the
same shape as today's `the postgres datasource needs an optional
dependency: pip install 'tablewatch[postgres]'`, so the two install hints
read alike.)

**S2 (must). The known-driver table.** Same as S1 for each row (scheme →
package): `snowflake` → `snowflake-sqlalchemy`; `bigquery` →
`sqlalchemy-bigquery`; `redshift` and `redshift+redshift_connector` →
`sqlalchemy-redshift`; `databricks` → `databricks-sqlalchemy`; `trino` →
`trino`. The name in "the X driver" is the part of the scheme before `+`;
the table is keyed on that part, so `redshift+psycopg2` also maps to
`sqlalchemy-redshift`. Verified on PyPI in REFINE (2026-10-02): each
package exists and its wheel's `sqlalchemy.dialects` entry points register
exactly that name (`snowflake-sqlalchemy` 1.11.1 `snowflake`;
`sqlalchemy-bigquery` 1.17.2 `bigquery`; `sqlalchemy-redshift` 1.0.0
`redshift`, `redshift.psycopg2`, `redshift.redshift_connector`;
`databricks-sqlalchemy` 2.0.10 `databricks`; `trino` 0.340.0 `trino`).
Once the dialect is installed, a missing DBAPI (`redshift_connector`,
`psycopg2`) is S4, not S2.

**S2b (should). `postgres://`.** SQLAlchemy 1.4 dropped the `postgres`
alias, and `postgres://...` is the form many hosting providers hand out.
URL `postgres://u:p@h/db`. Reason:
`SQLAlchemy does not accept the scheme 'postgres'; write postgresql:// instead`.
Without this row Dana is told to install a package for a database whose
driver is already installed.

**S2c (should). Lookup is exact.** SQLAlchemy's dialect names are
case-sensitive (`Snowflake://` fails to load even with
`snowflake-sqlalchemy` installed). URL `Snowflake://u@acct/db` gets S3's
reason, never S1's: an install hint that cannot fix the problem is worse
than none.

**S3 (must). Dialect not installed, unknown scheme.** URL `foodb://h/db`.
Reason:
`no SQLAlchemy dialect named 'foodb' is installed; check the spelling of the url scheme, or install the dialect package for this database`.
(A misspelt scheme, `postgresq://`, `snowflak://`, is the commonest cause,
so spelling comes first; the old wording only told Dana to install
something.)

**S4 (must). Dialect installed, DBAPI module missing (run only).** URL
`mysql://u@h/db` with no `mysqlclient`. Compile succeeds (dialect `mysql`,
as today). Run and test-connection give reason:
`the mysql driver needs the Python module 'MySQLdb', which is not installed`.
The run completes and exits 2; test-connection exits 2; neither raises
`ModuleNotFoundError`. The module name is `ModuleNotFoundError.name`, not
the URL. (It is the import name, not always the pip name - `MySQLdb` comes
from `mysqlclient` - so the reason says "Python module", never "pip
install". No module→package table: not added.)

**S4b (should). DBAPI present but fails to import.** An `ImportError` that
is not a missing module (a broken native library) must not claim "not
installed". Reason: `the mysql driver could not be imported: <first line of
the ImportError>`, run completes, exit 2.

**S5 (must). Malformed URL, no `://`.** URL `user:secret@host/db`. Compile, run
and test-connection give reason:
`url is not a SQLAlchemy URL: it must start with dialect:// or dialect+driver://`.
("url" lowercase throughout: it is the YAML key Dana searches for.)
Neither `secret`, `user`, nor `host` appears in any output, recorded
result, API response or log line (security R1, spec 005).

**S6 (must). Two drivers.** URL `a+b+c://x`. Compile, run and
test-connection give reason:
`url scheme 'a+b+c' is not dialect or dialect+driver`.
S5's reason would be wrong here: the URL does start with `scheme://`. The
scheme is echoed only because it matches `URL_SCHEME` (no credential can
be in it). The run completes (today it ends with an uncaught `ValueError`,
exit 1). Run and test-connection exit 2.

**S7 (must). `${env:}` in the scheme.** URL `${env:WAREHOUSE_URL}`. Compile
reason: `cannot tell the dialect of a url whose scheme is an ${env:} reference`
(today's text with `URL` lowercased to match S5, now with `P`). Run with
`WAREHOUSE_URL` set to `user:secret@host/db`: S5's reason; `secret`,
`user` and `host` appear nowhere.

**S8 (must). One bad datasource does not end the run.** Add a second datasource
`local: {type: duckdb, path: shop.duckdb}` with a passing
`checks/local.yml`. With `warehouse` as in S4, S5 or S6: `tw run` records
`error` on `warehouse`'s checks and `pass` on `local`'s; exit 2.

**S9 (must). Other datasource-level errors share the prefix on a run.** An unset
`${env:WH_PASSWORD}` and an unknown `timezone:` keep their reason text
but are recorded as `P<reason>` instead of today's
`datasource warehouse: <reason>`. Results already in the store keep their
text.

**S10 (must). The check page.** The SQL section shows `error` as today (it renders
the string); `frontend` fixtures for "cannot compile"
(`frontend/src/test/fixtures/sql.ts` line 156, `sql.test.tsx` P3) are
updated to S1's string with `P`. No layout change.

## Non-goals

- **I-35 part 2 (stays in I-35, no new item; backlog frozen):** a check
  whose datasource is not defined shows the name as written, marked "not
  defined", in the Datasource row and the SQL section. Today the loader's
  `_resolve_datasource` returns `None` and `Dataset.datasource` becomes
  `""`, served on `/checks/{id}` and `/sql`. Keeping the name changes the
  loader, the public `Dataset` model (a field or a "defined" flag), two
  wire schemas and the page: with this part's run-path fix it would pass S.
  `datasource` is not in `derive_check_id`, so part 2 does not move any
  check id. Also left in part 2: "computes 6 values, used by this check and
  6 others" wording.
- No install of drivers, no `tablewatch[snowflake]` extras (outward-facing
  packaging: owner decision).
- No change to the `postgres`/`duckdb` "needs an optional dependency"
  messages beyond the run prefix (S9).
- No scrubbing of error text already in the store.
- No change to the exit codes or to `validate` (which never builds a
  dialect).

## Design notes

- Rule 7: the fix for S4/S6 is in `create_engine_for` (turn `ValueError`
  and `ImportError` from `create_engine` into `DatasourceError`), not only
  a wider catch in the runner. Catch `ModuleNotFoundError` (S4) before
  `ImportError` (S4b). `dialect_for` should catch `ImportError` too: a
  third-party dialect whose module imports a missing package at load time
  would otherwise crash `compile` and `/sql`. Tech lead: should `_run_datasource` also
  catch any exception from `factory(name)` as `internal error: ...`, like
  the per-dataset net? (Recommended; it is the gap that let S4/S6 crash.)
- Rule 6: compile still never resolves `${env:}`; S7 is today's guard.
- Security R1 (spec 005): only a scheme that matches `URL_SCHEME` is ever
  echoed; `create_engine_for` must stop passing SQLAlchemy's exception
  text through (`str(exc)`) for URL errors. The module name in S4 comes from
  the import error, not the URL. Tests assert the password, user and host
  of S5/S7 are absent from CLI output, the stored result, the API body and
  logs.
- One message source: the reason text is built in `datasources/` and the
  `P` prefix in one helper used by `compile_dataset`, the runner and the
  CLI, so compile and run cannot drift (they already have, see Today).
  `test-connection` keeps its `FAILED  <name>: ` shape.
- The known-driver table lives beside `URL_SCHEME`; a scheme not in it gets
  S3's reason. Open question (architect): a dict in `datasources/` is
  enough; no plugin seam.
- Tests: `tests/test_check_sql.py` `remote` fixture shape (URL datasource,
  no driver) for S1/S5 on `/sql`; CLI tests for compile/run/test-connection;
  a run test for S8 on DuckDB.

## Reviewers required

- qa-engineer (always): S4/S6 on a run, leakage in S5/S7.
- data-steward (always): wording of every reason.
- security-reviewer: the change touches error text that could carry a URL
  or credential (PROCESS.md trigger).
- architect: touches `src/` (`datasources/`, `engine/compiled.py`,
  `engine/runner.py`, `cli/main.py`); no new public API.
- ui-engineer: fixture and test strings only (S10); no layout change.

## Size

S. One module's messages, one helper, two caught exception types, fixture
strings. Part 2 (name as written) is the rest of I-35.

## REFINE decisions (tech lead, 2026-10-02)

Reviewers: architect (approve with follow-ups), security-reviewer (approve; R1–R4 blocking-for-ready, all taken), data-steward (wording above; package names verified on PyPI). Where security and the architect differed, security wins.

- **R1 (security, must): no SQLAlchemy or driver exception text ever reaches a message.** Every reason is fixed text. The only inputs: a scheme that passed `URL_SCHEME.fullmatch` (from the resolved URL on the run path), capped at 64 characters; and for `ModuleNotFoundError`, `exc.name` only if it matches `[A-Za-z_][A-Za-z0-9_.]*`, otherwise "a required Python module". Never `str(exc)`; keep `from None`. Any `ArgumentError`/`ValueError` from `create_engine` gives S5's reason.
  - Live leaks this closes (measured on main, SQLAlchemy 2.1.0): `sqlite://u:secret@h/x?foo=secret` echoed user, host and query; `postgresql+psycopg://admin@db.prod:Pa55w0rd/x` echoed the password typed into the port slot.
  - **S4b is reworded to fit R1**: `the <dialect> driver could not be imported`, with no exception text.
- **R2 (security, must): the run-path backstop.** `_run_datasource` wraps `timezone_of(config)` and the engine factory in one `except Exception` after the typed catch, recording `datasource '<name>' in tablewatch.yml: internal error creating the engine (<ExceptionTypeName>)` — not `_short_error`, not `log.exception`. It logs only the type name at warning (traceback at debug at most). `create_engine_for` also turns a bad port into a plain reason that never quotes the value (`port: ${env:PG_PASSWORD}` would otherwise put the secret in a `ValueError`).
- **R3 (security, must):** `tablewatch test-connection` gets the same messages through `create_engine_for` and never prints a traceback for these cases.
- **R4 (security, must): leak tests** for both cases above, the `port: ${env:…}` case, S5 and S7: the secret, user, host and query value are absent from CLI stdout and stderr, the stored result, `/checks/{id}/sql`, the run-results API and `caplog` at DEBUG.
- **Architect, design:** one private helper (`_url_problem`) shared by `dialect_for` and `create_engine_for`, so compile and run cannot drift; the driver table is a private dict keyed on the dialect name (the part before `+`); a public `datasource_problem(name, reason)` builds the prefix, called by `compile_dataset` and `_run_datasource` only (not the CLI: compile prints `compiled.error`; test-connection keeps `FAILED  <name>: <reason>`). `UNDEFINED_DATASOURCE` stays unprefixed (part 2). `dialect_for` also catches `ImportError` (`ModuleNotFoundError` first).
- **Security, non-blocking, taken:** the datasource name is rendered with control characters escaped in the prefix.
- **Not added (backlog freeze):** test-connection's `SQLAlchemyError` branch prints the driver's connect-time text, which names host and user (pre-existing); a module-to-package table for DBAPI drivers.
