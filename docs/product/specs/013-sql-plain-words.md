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
does not cover engine creation). This spec fixes them with the messages:
same bug family, same function.

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

**S1. Dialect not installed, known database.** URL
`snowflake://u:p@acct/db`, no `snowflake-sqlalchemy` installed. Compile,
run and test-connection all give reason:
`the snowflake driver is not installed; pip install snowflake-sqlalchemy`.
The text `Can't load plugin` appears nowhere.

**S2. The known-driver table.** Same as S1 for each row (scheme →
package): `snowflake` → `snowflake-sqlalchemy`; `bigquery` →
`sqlalchemy-bigquery`; `redshift` and `redshift+redshift_connector` →
`sqlalchemy-redshift`; `databricks` → `databricks-sqlalchemy`; `trino` →
`trino`. The name in "the X driver" is the part of the scheme before `+`.
(Tech lead: confirm each package name on PyPI before merging; a wrong one
is worse than none.)

**S3. Dialect not installed, unknown database.** URL `foodb://h/db`.
Reason: `no installed package provides the SQLAlchemy dialect 'foodb'; install the SQLAlchemy dialect for this database`.

**S4. Dialect installed, DBAPI module missing (run only).** URL
`mysql://u@h/db` with no `mysqlclient`. Compile succeeds (dialect `mysql`,
as today). Run and test-connection give reason:
`the mysql driver needs the Python module 'MySQLdb', which is not installed`.
The run completes; it does not raise `ModuleNotFoundError`.

**S5. Malformed URL, no `://`.** URL `user:secret@host/db`. Compile, run
and test-connection give reason:
`url is not a SQLAlchemy URL (expected scheme://...)`.
Neither `secret`, `user`, nor `host` appears in any output, recorded
result, API response or log line (security R1, spec 005).

**S6. Two drivers.** URL `a+b+c://x`. Same reason as S5, on compile, run
and test-connection; the run completes (today it ends with an uncaught
`ValueError`). Exit 2.

**S7. `${env:}` in the scheme.** URL `${env:WAREHOUSE_URL}`. Compile
reason: `cannot tell the dialect of a url whose scheme is an ${env:} reference`
(today's text, now with `P`). Run with `WAREHOUSE_URL` set to
`user:secret@host/db`: S5's reason; `secret` appears nowhere.

**S8. One bad datasource does not end the run.** Add a second datasource
`local: {type: duckdb, path: shop.duckdb}` with a passing
`checks/local.yml`. With `warehouse` as in S4, S5 or S6: `tw run` records
`error` on `warehouse`'s checks and `pass` on `local`'s; exit 2.

**S9. Other datasource-level errors share the prefix on a run.** An unset
`${env:WH_PASSWORD}` and an unknown `timezone:` keep their reason text
but are recorded as `P<reason>` instead of today's
`datasource warehouse: <reason>`. Results already in the store keep their
text.

**S10. The check page.** The SQL section shows `error` as today (it renders
the string); `frontend` fixtures for "cannot compile"
(`frontend/src/test/fixtures/sql.ts`, `sql.test.tsx` P3) are updated to S1's
string. No layout change.

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
  a wider catch in the runner. Tech lead: should `_run_datasource` also
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
