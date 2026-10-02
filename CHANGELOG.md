# Changelog

All notable changes to tablewatch. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## Unreleased

### Added

- A check explorer in the web UI at `/checks`: your `checks/` folders as a
  tree, with fail, warn and pass counts on every folder and file, a search
  box and a status filter. The filters are kept in the URL, so a view can be
  shared and Back returns to it.
- The check explorer filters by tag, owner and datasource as well as
  status, and its search also finds tags, owners and datasources. Ticking
  two tags shows checks with either, as `tw run --tag a --tag b` does.
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
- `GET /api/v1/checks` and `/checks/{id}` now say why a check's
  datasource isn't ready to run: the new `datasource_state` field is
  `"defined"`, `"not_defined"` (the name is written but not in
  `tablewatch.yml`), `"not_a_name"` (the value isn't a datasource name at
  all, for example a URL), or `"none"` (no `datasource:` is set anywhere
  for this check).

### Changed

- The overview says when a check started failing as a date ("Failing since
  Sep 19", "since 10:05 today"), not "since 7 days ago". "Incomplete" is
  on the summary caption only, and the overview says how many checks the
  latest run counted that are not loaded now.
- A check whose `datasource:` names a datasource that isn't defined, or
  isn't a datasource name at all, now shows that name as written — in
  `/checks`, `/checks/{id}`, `/checks/{id}/sql`, and in the Datasource
  row on the check page, marked "not defined" or "not a datasource
  name" — instead of a blank value. **If you read `Dataset.datasource`
  from Python**, it is now the name exactly as written in the check
  file (or `""` only when none is set or the value isn't a name), not
  always `""` for an undefined datasource; check `datasource_state` or
  look it up in `config.datasources` before using it.
- On a check's page, the SQL section's shared-scan sentence now reads
  "that one read computes 6 values, used by this check and 6 others"
  instead of "…for this check and 6 others": the check does not compute
  values for the checks it shares the read with, it shares the read.
- `failed_rows` and `row_count` values now say `1 row`, `3 rows`,
  `1,204 rows` — on the console, in JSON and JUnit reports, in the
  results store and on the check page — instead of a bare number.
  Results recorded before the upgrade keep their text.

- On a check's page, the history table's Rule column now says
  "Current" only for the results the chart shades under today's rule.
  An older result judged by the same rule, before a different rule ran,
  reads "Same as current, before a rule change", so the table and the
  chart no longer disagree after a rule is changed and changed back.
- A result with no value (an empty table, or a `where:` that matches no
  rows) now reads "No value measured" under Latest result and on the
  overview, as it already did in the history table, instead of a bare
  "—" that looked like nothing to report.
- A `between` rule's two lines on the history chart are labelled with
  the end each one marks (`>= 50` and `<= 60`; `< 50` and `> 60` for
  `not between`) instead of both repeating the whole rule, which is
  still shown above the chart. Thresholds on the chart are shown exactly,
  never rounded. A label for a threshold off the chart ("10,000 above")
  sits on the side it names and clear of the latest value.
- In a check's **Source** section, line numbers stay at the left edge
  when a long line is scrolled sideways, so you can always tell which
  line you are reading. Copying the lines is unchanged: no line numbers,
  no extra blank line.

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
- Freshness messages are easier to read, and they no longer look like the
  check should have failed. Before, a message showed the newest timestamp
  in UTC ISO form (`newest 2026-09-27T01:47:30.654321+00:00`), which read
  as a different time to anyone outside UTC. Now it says what the time
  is and names its zone, to the second: `newest row at 2026-09-27
  09:47:30 UTC`, or, on a datasource with a `timezone`, `newest row at
  2026-09-27 09:47:30 Asia/Singapore (UTC+08:00)`. That is the time as
  your table holds it, so you can match it with a query. A date column
  says `newest date 2026-09-26`.
- A freshness check whose newest row is more than a minute in the future
  now says so, and suggests why: `…, 1h 47m in the future; check the
  datasource's timezone`, or, more than 26 hours ahead,
  `…; check for placeholder or future-dated values` (a `9999-12-31` row,
  for example). Such a check still passes; only the message changes.
- A `schema` check's value now reads `0 problems`, `1 problem`,
  `2 problems` instead of a bare number, on the console, in the JSON and
  JUnit reports, in the results store and on the check page. The docs and
  editor hovers call them "problems" rather than "violations".
- The console's DETAIL column shows up to 200 characters before cutting
  a message short with `…` (it was 70), so a freshness message is shown
  whole.
- What does not change: every `value` (a freshness value is still the age
  in seconds, a schema value still a count), every outcome, exit code and
  check id, the SQL, and the shape of the JSON report (`schema_version`
  stays `1`) and the API. Results recorded by earlier versions keep the
  text they were recorded with, so one history can show both forms. **If
  a script parses the timestamp out of `message`, it will break: read
  `value` instead.** The text of `message` and `display_value` is for
  people and may change between versions; programs should read `value`
  and `outcome` (the README now says so).

- An explicit check `id:` can be at most 64 characters, the width of the
  results store's column. A longer id is now reported at its `file:line:col`
  when the project loads. Before, such a check ran but could not be recorded
  on PostgreSQL. If you have one, shorten it; its history starts again under
  the new id.
- `tablewatch validate` no longer ends with "no problems found" when it
  printed warnings. It says, for example, `1 datasets, 1 checks — no
  errors, 1 warning`, and still exits 0. A script that looks for "no
  problems found" will not see it on a project with warnings.
- **Check ids: `failed_rows` and `sql_metric`.** `failed_rows` and
  `sql_metric` checks with no `id:` get a new id, so two such checks with
  different SQL on one dataset no longer collide. Before, two
  `failed_rows` checks on one table (say `total < 0` and
  `customer_id is null`) were reported as duplicates and nothing in the
  project ran until one was given an `id:`. The id now includes the
  check's `condition:` or `query:`; reformatting the SQL (spacing, line
  breaks, a block scalar) keeps the id, and changing what it says starts
  a new one. Every other check keeps its id.

  Their history starts again on the first run after upgrading; old
  results stay readable with `tablewatch history <old id>`. To keep one
  history: **before upgrading**, run `tablewatch list --output json` and
  note each such check's `id`; after upgrading, add `id: <that id>` to
  the check. Use all 16 characters, not the 12 `tablewatch list` shows:
  a 12-character id is accepted but starts a new history. Already
  upgraded? This lists old ids from the results store:

  ```sql
  SELECT check_id, check_name, source, MAX(r.started_at) AS last_run
  FROM tablewatch_check_results c
  JOIN tablewatch_runs r ON r.id = c.run_id
  WHERE c.metric IN ('failed_rows', 'sql_metric')
  GROUP BY check_id, check_name, source;
  ```

  A check can show more than one id (for example if its file was moved);
  the old id is the one whose `last_run` is the last run before you
  upgraded. See "Check identity" in `docs/check-language.md`.

- The `duckdb` extra now also installs `pytz`. DuckDB needs it to read
  `TIMESTAMPTZ` values but does not install it itself. If you install
  `duckdb` on its own rather than through `tablewatch[duckdb]`, add
  `pytz` too.
- When tablewatch cannot compute or evaluate a check's value, the
  `error` message it stores and shows is now the error's first line, at
  most 500 characters, as database errors already were one line. Before,
  such a message was kept in full. Results recorded before the upgrade
  keep their text.

- Problems with a datasource now say which datasource and where it is
  defined, and say what is wrong in words: `datasource 'warehouse' in
  tablewatch.yml: the snowflake driver is not installed: pip install
  snowflake-sqlalchemy` instead of `Can't load plugin:
  sqlalchemy.dialects:snowflake`. `tablewatch compile`, the SQL section
  of a check's page, a run's recorded `error` and `tablewatch
  test-connection` all give the same reason. Other cases covered: a
  `postgres://` url (write `postgresql://`), a misspelt or unknown
  scheme, an unknown driver after `+`, a missing Python driver module
  (named), and a url that cannot be read. Errors recorded for a
  datasource on a run now start `datasource '<name>' in tablewatch.yml:`
  instead of `datasource <name>:`; results recorded before the upgrade
  keep their text.

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
- A freshness check on a column holding a far-future or far-past
  placeholder (`9999-12-31 23:59:59` or `0001-01-01 00:00:00`) on a
  datasource with a `timezone` no longer turns every check on that table,
  `row_count` included, into an error ("date value out of range"). Each
  check now gets its real outcome.
- **A `null` in `valid_values` no longer makes a check pass whatever the
  data holds.** Before, `valid_values: [pending, shipped, null]` was
  compiled to `status NOT IN ('pending', 'shipped', NULL)`, which SQL
  never counts as true, so `invalid_count` found nothing, even a status
  of `shiped`. The same happened with a null in `missing_values` on an
  `invalid_*` check. Now a null item never reaches the SQL: it is
  ignored, and `validate` and `run` warn at its `file:line:col` and say
  why (NULL is always counted as missing, never as invalid). **After
  upgrading, a check that has always passed may start to fail, because
  it was never checking.** Its id does not change, so its history
  continues and jumps from the old `0` to the true count at the first
  run; results already recorded are not rewritten. Run `tablewatch
  validate` after upgrading: it warns at every null in a value list,
  so it lists every check that may have been affected.
- YAML reads an unquoted `null`, `Null`, `NULL` or `~`, and a `-` with
  nothing after it, as null, not as text. If you listed `NULL` to match
  the four-letter text your loads write, the warning tells you to quote
  it: `'NULL'`. An empty `-` left behind in a list is pointed out at its
  own line, so you can fill it in or delete it.
- `missing_count` and `missing_percent` keep their numbers exactly: a
  null in their `missing_values` only adds the warning.
- A `valid_values` list with nothing but nulls in it, and a list item
  that is not a single value (for example a list inside the list), are
  now reported when the project loads, and `validate` exits 3. Before,
  the first passed every run and the second errored every run with a
  database message that could quote a row value. Editors that use
  tablewatch's JSON Schema underline both as you type.
- **A broken check file, `_defaults.yml` or `tablewatch.yml` is reported
  at its `file:line:col`, and `validate`, `list`, `compile` and `run`
  exit 3.** Before, some mistakes stopped tablewatch with a Python
  traceback and **exit 1**, which a scheduler reads as "a check failed"
  rather than "the project is broken". Every other check file is still
  read and reported in the same pass; `tablewatch.load()` returns the
  diagnostics instead of raising (a broken `tablewatch.yml` raises
  `ProjectError`, as before). The cases:
  - An invisible control character, for example a form feed pasted from
    a PDF or wiki page, or Word's vertical tab:
    `checks/orders.yml:2:13: error: invalid YAML: hidden control character U+000C (form feed) is not allowed; delete it`.
  - A file that is not UTF-8, such as a Notepad "ANSI" file holding a
    curly apostrophe from Word:
    `not UTF-8 text: byte 0x92 cannot be decoded; save the file as UTF-8`.
    A UTF-16 or UTF-32 file (Windows PowerShell's `>` writes UTF-16) says
    `not UTF-8 text: the file is UTF-16; save it as UTF-8`.
  - An explicit YAML tag on a value that does not fit it, such as
    `!!int xyz`: `invalid YAML: 'xyz' is not a valid !!int`, at the tag.
- **YAML merge keys (`<<:`) work everywhere a check file,
  `_defaults.yml` or `tablewatch.yml` accepts a key.** Before, a merge
  inside a check's options, in a check item, at a file's root or in
  `tablewatch.yml` could crash the loader. So you can now share
  triggers through an anchor:

  ```yaml
  checks:
    - missing_percent(email):
        <<: &nulls {warn: when > 1%, fail: when > 5%}
    - missing_percent(phone):
        <<: *nulls
  ```

  A key written beside the merge wins over the merged one, as YAML
  says. A mistake inside merged content is reported where it is
  written, inside the anchor (once for each check that uses it).
  Moving `warn:` and `fail:` into an anchor keeps the check's id, so
  its history continues.
- A freshness check on a DuckDB `TIMESTAMPTZ` column works. Before, it
  was an `error` on every run ("Required module 'pytz' failed to
  import") and `tablewatch run` exited 2. A zoned column holds instants,
  so its age does not depend on the datasource's `timezone`, which only
  changes how the newest row is displayed. See `docs/check-language.md`.
- An unexpected error in one check no longer turns every other check on
  the same table into an `error`. Only the check that hit it reports
  `error`, with the message `internal error in <metric>: …`; the others
  report as usual. The same holds when the database driver cannot read
  back one measured value (for example a year-1 `TIMESTAMPTZ` on DuckDB
  in a time zone west of UTC): only the checks that need that value
  error. Exit codes are unchanged.

- A datasource error no longer shows any part of the url's user,
  password, host or query. Before, some malformed urls (for example a
  password typed where the port goes) put that text into the stored
  result, the API and the check page. Messages are now fixed text; a bad
  port is never quoted. Results recorded before the upgrade keep their
  text. Errors raised by the driver while connecting can still name the
  host.
- A datasource whose Python driver is not installed (for example
  `mysql://` without `mysqlclient`), or whose url names two drivers
  (`a+b+c://`), no longer ends the whole run with a traceback and exit
  code 1. Its checks report `error` and the run exits 2, as for any
  other datasource problem; other datasources run as usual.
  `tablewatch test-connection` reports it and exits 2 too.
- A third-party SQLAlchemy dialect that fails while loading no longer
  crashes `tablewatch compile` or makes the check page's SQL section
  fail; it reads "the X dialect could not be loaded".

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
