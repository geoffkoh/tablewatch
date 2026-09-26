# Changelog

All notable changes to tablewatch. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## Unreleased

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
