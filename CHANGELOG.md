# Changelog

All notable changes to tablewatch. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## Unreleased

### Added

- Run checks from Python: `tablewatch.run()` runs a project's checks in
  your own process — a pipeline task, a notebook, a test — and returns
  typed results instead of text to parse. `tablewatch.load()` reads a
  project without connecting to anything. See "Use from Python" in the
  README.
- `result.exit_code()` gives the same answer `tablewatch run` would: `0`
  clean, `1` the data failed a check, `2` tablewatch could not evaluate a
  check or record the run.
- Bad data never raises. `tablewatch.run()` raises `TablewatchError`
  (`ProjectError` or `SelectionError`) only when nothing ran.
- `record=False` keeps an exploratory run out of the history; runs recorded
  from Python are marked with the trigger `python`.
- Several `tablewatch.run()` calls can record into the same results store
  at once from one process (for example from worker threads) without losing
  runs.
- The package ships type information, so mypy and editors check your code
  against it.
- `tablewatch serve` publishes a project's checks and recorded results as a
  read-only JSON API at `/api/v1`, for dashboards, scripts and the web UI
  that comes next. Ask it what is failing right now
  (`/checks?outcome=fail&outcome=warn&outcome=error`), for one check's
  history, or for recent runs and their results. It reads the results store
  only: it never connects to a datasource, never starts a run, and needs no
  credentials. See "Serve results over HTTP" in the README.
- The API is described by an OpenAPI document, served at
  `/api/v1/openapi.json` and published in `docs/api/openapi.json`.
- `serve` needs the new optional `server` extra:
  `pip install 'tablewatch[server]'`. Without it, `tablewatch` installs
  nothing new, and `serve` says which extra is missing.
- `serve` listens on `127.0.0.1` by default. `--host` serves the network and
  warns that there is no authentication yet (it arrives in Phase 4). Host
  names other than `localhost` and IP addresses are refused unless named
  with `--allowed-host`, which guards against DNS rebinding.
- `serve` exits `0` when stopped and `3` when it cannot start (missing
  extra, unusable `tablewatch.yml`, results store that cannot be opened,
  port in use), with a one-line message that never repeats the results
  store's URL. A mistake in a check file does not stop it: it serves the
  checks that loaded and reports `"ok": false`.
- A web page for your checks. Open the address `tablewatch serve` prints
  (by default `http://127.0.0.1:8765/`) to see, at a glance, what is wrong
  with your tables: failing checks first, then checks tablewatch could not
  evaluate, then warnings, checks with no result yet, and passing checks.
  Each row shows how old its latest result is and how long the check has
  been failing. A check with no recorded result is shown as unknown, never
  as passing. If a check file fails to load, a banner lists each mistake
  at `file:line:col` and marks the counts incomplete. The page also shows
  when the check files were loaded and what the latest run covered. It
  refreshes when you press **Refresh**, never by itself. See "Reading the
  overview" in the README.
- The page comes with the `server` extra: no Node.js or other tooling is
  needed to use it. It loads nothing from other sites and is served with a
  strict Content-Security-Policy.
- The JSON API tells you since when: each check's `latest` result now has
  `since`, when the current state began ("failing since"). A run that could
  not evaluate the check (`error`) or skipped it does not reset how long a
  failure has lasted; a pass does. When the latest result is an `error`
  or `skipped`, the new `latest.last_evaluated` says what the data showed
  the last time tablewatch could measure it, so an outage does not hide a
  known failure.
- The OpenAPI document now describes the API exactly: a run's `selection`
  has named keys (`paths`, `tags`, `datasources`, `excludes`,
  `check_ids`); the 403, 405 and 500 errors are declared on every
  endpoint; timestamps are marked as date-times. Clients that generate
  code from it get precise types.

### Changed

- API timestamps always carry six fractional digits
  (`2026-09-26T06:56:12.000000+00:00`); before, the fraction was left out
  when it was zero. Standard date-time parsers read both.
- A request with a method other than `GET` to a path the server does not
  know, including an unknown `/api/v1/...` path, now answers `405 Method
  Not Allowed` instead of `404 Not Found`. Read-only clients are not
  affected.
- `GET /` on `tablewatch serve` now returns the web page; unknown paths
  outside `/api` that look like page addresses return the page too, and
  unknown paths under `/api` still return the JSON error.

- An explicit check `id:` can be at most 64 characters, the width of the
  results store's column. A longer id is now reported at its `file:line:col`
  when the project loads. Before, such a check ran but could not be recorded
  on PostgreSQL. If you have one, shorten it; its history starts again under
  the new id.

## 0.1.0 — not yet published

The first release: checks in YAML, run from the command line.

### Added

- Check files in YAML, in any folder structure, with `_defaults.yml`
  inheritance of datasource, owner and tags.
- A check language with 16 metrics — row counts, missing and invalid values,
  duplicates, distinct counts, min/max/avg/sum, freshness, schema,
  `failed_rows`, and `sql_metric` — and `warn:`/`fail:` thresholds.
- Every mistake in a check file reported at its `file:line:col`.
- DuckDB, PostgreSQL and SQLite datasources, plus any SQLAlchemy URL;
  secrets referenced from the environment.
- One table scan for all of a table's aggregate checks.
- Run history in a results store (SQLite by default).
- Commands: `init`, `validate`, `list`, `compile`, `run`, `test-connection`,
  `runs`, `history`, `schema`.
- Console, JSON and JUnit output; JSON logs; exit codes for schedulers.
- A JSON Schema for check files, for editor autocompletion.
