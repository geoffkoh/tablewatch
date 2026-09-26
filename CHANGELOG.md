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

### Changed

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
