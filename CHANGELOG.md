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
