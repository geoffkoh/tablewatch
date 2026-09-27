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
- A page for every check. On the overview, each check's name is now a
  link to `/checks/<id>`, an address you can reload, bookmark or send to
  a colleague. The page shows what the check is and where it is written
  (`file:line:col`), its rule in words ("Expected < 5%", "Warn when > 1d ·
  Fail when > 7d"), its latest result in the overview's words, and its
  recorded history as a chart and as a table. See "Reading a check's
  page" in the README.
- The history chart plots each recorded value against the check's
  current rule, with the failing region shaded, so you can see how far
  from the line a check is and for how long. Each result is marked by the
  outcome it was given at the time, by shape as well as colour. Runs that
  could not evaluate the check, and failures with no value, sit in their
  own lanes below the plot instead of being drawn as zero. When a rule is
  edited under an explicit `id:`, the chart marks where it changed and
  says from what to what; values measured by a different metric are
  listed but kept off today's axis. Hover or use the arrow keys to read
  any point; the table below lists every result, 200 at a time, with
  **Load older results** for more. Times are shown in your own time zone,
  and the page says which.
- The JSON API describes a check's rule: `GET /api/v1/checks/{id}` has a
  new `rule` field with each condition's operator, its numbers on the
  same scale as the recorded values (`5%` is `5.0`, `6h` is `21600.0`
  seconds), and its text. Each entry in a check's history now says which
  `metric`, `dataset` and `unit` it recorded. Both additions are
  backwards-compatible; `GET /api/v1/checks` is unchanged.
- A check's page shows its SQL. A new **SQL** section, below the
  history, shows the statement this check's value comes from, in your
  database's dialect, exactly as `tablewatch compile` prints it. Most
  checks share their table's single scan: the page shows the whole
  `SELECT`, points out which of its columns (`m0`, `m1`, …) belong to this
  check, and says how many other checks the same read serves. A `schema`
  check says it reads the table's column list, not rows. Copy buttons
  put the SQL on your clipboard, ready to paste into your warehouse's
  console. If the dataset cannot be compiled (a driver that is not
  installed, a datasource that is not defined) the section says so and
  the rest of the page still works. See "Reading a check's page" in the
  README.
- The JSON API serves the same thing at `GET /api/v1/checks/{id}/sql`.
  Like the rest of the API it is read-only: it never connects to a
  database, needs no credentials, and returns no rows. Each statement
  has a `kind` (`scan` or `query`); more kinds may be added within `v1`,
  so clients should skip a kind they do not know.
- A check's page shows the check as it is written. A new **Source**
  section, below the SQL, shows the check's own lines from its check
  file, numbered as in the file, with the comments that go with it (the
  one directly above that says why the rule is 5%, a commented-out option
  below it) and the file's path. If the file has a `filter:`, the section
  says which rows the check looks at, or that the filter does not apply
  (`sql_metric` and `schema` checks). Copy the lines with one button. The
  `file:line:col` at the top of the page links to it. When tablewatch
  cannot place a check's lines exactly (a whole file on one line, a check
  that is a YAML alias), it shows no lines rather than the wrong ones and
  still names the file. See "How to read the source" in the README.
- The JSON API serves the same thing at `GET /api/v1/checks/{id}/source`:
  the path, the first and last line, the text, and the file's `filter:`.
  It is read from the check files as `serve` loaded them; nothing is read
  from disk while answering, and nothing from `tablewatch.yml` or
  `_defaults.yml` is ever served.

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
- The warning `tablewatch serve --host` prints now says that anyone who
  can reach the address can read this project's check files, comments
  included, the SQL each check runs, and database error messages, which
  can quote row values, as well as results and owner emails. Keep
  credentials in environment variables (`${env:NAME}`), never in a check
  file or a comment: the check page now shows check files as written.
- `tablewatch compile` no longer repeats a datasource `url` that is not of
  the form `scheme://…` (for example one missing its `://`), because such
  a value can contain a password. It says "the url is not a SQLAlchemy
  URL (expected scheme://...)" instead. Well-formed URLs are reported as
  before.

- An explicit check `id:` can be at most 64 characters, the width of the
  results store's column. A longer id is now reported at its `file:line:col`
  when the project loads. Before, such a check ran but could not be recorded
  on PostgreSQL. If you have one, shorten it; its history starts again under
  the new id.

### Fixed

- A number in a check too large to represent (for example a threshold
  400 digits long) is now reported as "this number is too large" at its
  `file:line:col` when the project loads, and `validate` exits 3. Before,
  `tablewatch validate` crashed on it.
- `tablewatch compile` no longer crashes when a check option is a
  decimal number, a whole number, a boolean or a timestamp written in
  YAML (for example `valid_max: 99.5`). Running such checks was not
  affected; check ids do not change.
- Datasource URLs whose driver name contains `_`
  (`oracle+cx_oracle://…`, `postgresql+psycopg_async://…`) are
  recognised by `compile` and the check page.

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
