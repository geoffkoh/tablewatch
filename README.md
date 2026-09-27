# tablewatch

Data quality checks for your tables. Declare checks in YAML, run them from
the command line, cron or Python, and keep a history of every result.

```yaml
# checks/sales/orders.yml
dataset: sales.orders

checks:
  - row_count > 0
  - missing_count(customer_id) = 0
  - duplicate_count(order_id) = 0
  - freshness(created_at) < 6h
  - invalid_percent(status) < 1%:
      valid_values: [pending, shipped, delivered, cancelled]
  - row_count:
      warn: when < 1000
      fail: when = 0
```

```console
$ tablewatch run
OUTCOME  DATASET       CHECK                                          VALUE  DETAIL
PASS     sales.orders  row_count > 0                                      7
FAIL     sales.orders  missing_count(customer_id) = 0                     1  expected = 0
FAIL     sales.orders  duplicate_count(order_id) = 0                      1  expected = 0
PASS     sales.orders  freshness(created_at) < 6h                     1h 8m  newest 2026-09-25T08:41:59+00:00
FAIL     sales.orders  invalid_percent(status) < 1%                  14.29%  expected < 1%
WARN     sales.orders  row_count | warn when < 1000 | fail when = 0       7  warn when < 1000

6 checks · 2 pass · 1 warn · 3 fail · 0.0s  (run d70214890cef)
```

All of a table's aggregate checks run in **one table scan**, however many
there are.

> **Status: alpha (`0.1.0`).** The engine and CLI are complete, and `serve`
> has a web page: the overview, and a page for each check. More of the web UI, alerting, and
> scheduling come next — see the [roadmap](docs/ROADMAP.md).

## Install

```bash
pip install 'tablewatch[duckdb]'      # or [postgres], or both: [duckdb,postgres]
```

## Try the example

The example project has a small retail database with defects planted on purpose:

```bash
uv run python examples/retail/build.py
uv run tablewatch --project-dir examples/retail run
```

## Start a project

```bash
tablewatch init my-checks && cd my-checks
tablewatch validate            # no database needed
tablewatch test-connection
tablewatch run
```

A project is a `tablewatch.yml` plus a `checks/` folder, organised however you
like:

```
tablewatch.yml             # datasources and the results store
checks/
├── _defaults.yml          # inherited by everything below: datasource, owner, tags
├── sales/
│   ├── orders.yml         # one file = one table
│   └── customers.yml
└── finance/ledger.yml
```

```yaml
# tablewatch.yml
name: acme-dq
datasources:
  warehouse:
    type: postgres
    host: ${env:PGHOST}
    database: analytics
    user: ${env:PGUSER}
    password: ${env:PGPASSWORD}   # secrets are referenced, never written down
results:
  url: sqlite:///.tablewatch/results.db
```

The full language — every metric, option and rule — is in
[docs/check-language.md](docs/check-language.md).

## Commands

| Command | Does |
| --- | --- |
| `tablewatch init [DIR]` | Scaffold a project, with editor schemas for autocompletion. |
| `tablewatch validate` | Report every mistake at its `file:line:col`. Needs no credentials. |
| `tablewatch list` | Show checks after inheritance, with their ids. |
| `tablewatch compile` | Print the SQL each table will run, without running it. |
| `tablewatch run` | Run checks and record the results. |
| `tablewatch test-connection` | Connect to each datasource. |
| `tablewatch runs` | Show recent runs. |
| `tablewatch history ID` | Show one check's outcomes over time. |
| `tablewatch schema` | Print the JSON Schema for check files. |
| `tablewatch serve` | Serve checks and results as a web page and a read-only JSON API ([below](#serve-results-over-http)). |

`list`, `compile` and `run` take selectors: paths (`checks/sales`), `--tag`,
`--datasource`, `--exclude PATH_OR_GLOB`, and `--check ID`.
`tw` is a short alias for `tablewatch`.

## On servers

`tablewatch run` is built to run unattended. It never prompts, and it writes
logs to stderr, as JSON with `--log-format json`, so stdout stays clean for
`--output json`. It exits with a code an orchestrator can act on:

| Exit | Meaning | Typical response |
| --- | --- | --- |
| `0` | All checks passed (warnings too, unless `--fail-on warn`) | — |
| `1` | A check **failed**: the data is bad | Alert the data owner |
| `2` | A check could not be **evaluated**: connection, query, store | Retry, then page the platform team |
| `3` | The project is invalid, or nothing matched: **nothing ran** | Fix the deployment |

```cron
*/30 * * * *  TABLEWATCH_PROJECT_DIR=/srv/dq  tablewatch --log-format json run --output junit --output-file /var/log/dq/latest.xml
```

Give tablewatch a **read-only** database role. `filter:`, `where:`,
`condition:` and `query:` are SQL from your checks repository, and they run
with the datasource's credentials.

## Serve results over HTTP

`tablewatch serve` publishes one project's checks and recorded results as a
web page for people and a read-only JSON API for dashboards and scripts. It
reads the check files once, at startup, and the results store on each
request. It never connects to a datasource, never starts a run, and needs no
credentials: the SQL it shows is compiled, not run.

```bash
pip install 'tablewatch[duckdb,server]'
tablewatch --project-dir examples/retail run      # record a run first
tablewatch --project-dir examples/retail serve
# tablewatch serve: http://127.0.0.1:8765/ (project retail-example, 18 checks; API at /api/v1)
```

Open `http://127.0.0.1:8765/` in a browser. The page is built into the
package, so the server needs no Node and the page loads nothing from the
internet.

### Reading the overview

The page answers "what is wrong with my tables, and since when?" From the
top down, it shows:

- **The header**: the project, the tablewatch version, and when the check
  files were loaded. `serve` reads them once, at startup (see below).
  **Refresh** fetches the results again. The page never refreshes itself.
- **A banner, if a check file failed to load.** It lists each mistake
  at `file:line:col`. That file's checks are missing from the page, so the
  counts are marked **incomplete**. The page cannot tell how many checks the
  broken file held, so a count marked incomplete, such as "5 failing",
  covers only the checks the page can see. There may be more. Fix the file
  and restart `serve`.
- **Summary**: the latest result of every loaded check, counted as failing,
  errors, warnings, no result, and passing.
- **Latest run**: when the most recent run started, what triggered it, what
  it selected ("all checks" or, for example, "paths: checks/sales"), and its
  own counts under "This run". A run of one folder counts only that folder,
  so its numbers can differ from the summary's. The summary is the state of
  the project. The run panel says what the last run looked at.
- **Every check, problems first**: failing, then could not evaluate, then
  warning, then no result recorded, then passing. Each check's name links
  to its own page (below).

The status words mean different things and go to different people:

| Row says | Meaning | Who acts |
| --- | --- | --- |
| **Fail** | The data broke the rule. The row shows the measured value and the rule. | The data owner |
| **Error**, "Could not evaluate" | tablewatch could not measure the check: the database was unreachable, a query failed, or similar. The row shows the error message. It says nothing about the data. | Whoever runs tablewatch |
| **Warn** | The data crossed a warning threshold but not the failure threshold. | The data owner, soon |
| **No result recorded** | This check has never run, so its state is unknown. It is **not** a pass. A new or edited check shows this until the next `tablewatch run`. | Run it |
| **Pass** | The data met the rule in the latest result. | — |

"All checks passing" appears only when every loaded check's latest result
is a pass and every check file loaded. Any check with no result recorded
prevents it.

The times on each row:

- **The age of the latest result** ("3 hours ago"). Hover over or focus any
  time to see it in full, in your own time zone. A row marked **Not in the
  latest run** has an older result because the latest run selected other
  checks. Check its age before you rely on it.
- **"Failing since"** or **"Warning since"**: the oldest result in the
  current streak of that outcome. Errors do not break a streak. A check that
  failed, errored during a database outage, and failed again is "failing
  since" the first failure, because the outage showed nothing about the
  data. Any other evaluated result ends the streak: a pass, or a warn
  between fails. "Since" means "in every evaluation since", not "every
  minute since": runs happen at intervals, and the check's history
  (`/api/v1/checks/{id}/history`, below) shows the gaps.
- **"Could not evaluate since"** on an error row: how long tablewatch has
  been unable to measure the check. Below the message, **"Last evaluated:
  Fail, 4 days ago; failing since 7 days ago"** says what the data showed
  the last time it could be measured. The error count in the summary adds
  how many of those checks were failing then ("5 errors could not evaluate; 2
  were failing"). They still need attention, but not in the failing count.

### A check's page

Click a check's name, or open `/checks/<id>` (for example
`http://127.0.0.1:8765/checks/b1ceb8262d8b5441`), to see one check and its
history. The address stays the same across reloads and restarts, so you
can send it to a colleague. It changes if the check's id does: editing
the expression of a check without an explicit `id:` gives it a new id and
a new page. The old address then says the check is no longer in the
loaded files and still shows its recorded results. The page shows:

- **What the check is**: its name and expression, dataset, datasource,
  owner, tags, `file:line:col` (a link to the Source section), and id.
- **Rule**: the rule in the check files as `serve` loaded them, for example
  "Expected `< 5%`", or "Warn when `> 1d`" and "Fail when `> 7d`". A
  `schema` or `failed_rows` check with no triggers reads "Expected `= 0`".
- **Latest result**, in the same words as the overview.
- **History**: a chart of the recorded values over time, then a table of
  every result, newest first. The table holds everything the chart draws,
  with the full message. Its **Rule** column reads "Current" for a result
  recorded under today's expression, and "Different rule" with the
  recorded expression for one that was not. The page loads the latest 200
  results. When there are more, the chart says so, and **Load older
  results** adds the next 200 to both.
- **SQL**: the statements tablewatch sends to the database for this check,
  in the datasource's own dialect, exactly as `tablewatch compile` prints
  them. Link straight to it with `/checks/<id>#sql`. See below.
- **Source**: the check as written in its check file, comments included,
  with line numbers and the file's path. Link straight to it with
  `/checks/<id>#source`. See below.

How to read the chart:

- **Each point is one recorded result**, at the time its run started. Its
  shape and colour give the outcome that run recorded, using the overview's
  icons. The page never re-judges an old value against today's rule: a
  point keeps the outcome its run recorded.
- **The shaded band is where the current rule fails** (red) or warns
  (amber), with a line at each boundary labelled with the rule's text. For
  `= 0`, everything above 0 is shaded, and the line is at 0. When a boundary
  is far outside the values, the chart leaves it off the axis and names it
  at the edge instead: "10,000 above". "Current rule" above the chart
  always states the whole rule.
- **Lanes under the axis hold results with no value.** "Could not evaluate"
  holds errors: tablewatch could not measure the check, which says nothing
  about the data. "No value" holds a fail with nothing to measure, such as
  an average over no rows or freshness with no timestamps: that is bad
  data. Neither is drawn at 0, and the line breaks across them.
- **"Rule changed" marks a change of rule under an explicit `id:`.** Two
  consecutive results were judged by different expressions. The caption
  under the chart names both, with the two runs either side, because the
  history knows only that the edit happened between them. The band covers
  only the results judged by the current rule, so an old result is never
  drawn against a threshold it was not judged by. If the check's metric
  changed (`missing_count` to `missing_percent`, say), results measured by
  the other metric are left off the axis, and the caption says how many.
  The table still lists them.
- **"Failing since"** (or "Warning since") brackets the current streak, as
  on the overview. It follows outcomes, not rules, so it can span a rule
  change.
- **Times on the axis, in the table and in tooltips are in your time zone,
  and the page names it** ("times in GMT+8"). Messages are stored text and
  keep UTC: a freshness message such as `newest 2026-09-26T11:33:48…+00:00`
  is in UTC. Read the age in the value column, not the timestamp in the
  message.
- **A value below 0 is drawn below 0.** A negative freshness means the
  newest row is in the future, which usually means naive timestamps read in
  the wrong time zone. It passes `< 6h` every time, so check the
  datasource's `timezone`.

Focus the chart and use the arrow keys, or hover, to read each result.
If you edit the rule of a check with an explicit `id:` and restart `serve`
before the next run, the page says that no run has used the new rule yet,
draws no band, and notes that the latest result was judged by the earlier
rule. (Without an `id:`, the edited check has a new id, and its page reads
"No result recorded" until it runs.)

How to read the SQL:

- **Most checks share one read of the table.** tablewatch reads each
  dataset once per run: one `SELECT` computes a value for every check on
  that dataset that it can (the *scan*). The page shows that whole
  statement, so you can see what the read costs, and says how many values
  it computes and for how many other checks ("That one read computes 4
  values, for this check and 3 others").
- **"This check uses" names this check's part of the scan.** The scan's
  columns are labelled `m0`, `m1`, and so on, as in `tablewatch compile`.
  For `missing_percent(email) < 5%` the page lists `m0` `count(*)` and `m1`
  `sum(CASE WHEN (email IS NULL OR email IN ('', 'N/A')) THEN 1 ELSE 0
  END)`: the rows, and the rows with no email. "Also used by 1 other check"
  means another check reads the same column, so it is computed once.
- **The database returns counts; tablewatch does the arithmetic.** For a
  percentage the page says so, and for freshness it says the database
  returns a timestamp and tablewatch computes its age at the time of each
  run. The same data looks older the later the run.
- **Some checks send their own statement.** `duplicate_count` needs a
  `GROUP BY`, so it cannot ride the scan. Its page shows "This check sends
  its own statement" and that query, and says how many other checks send
  the same one.
- **A `schema` check has no SQL.** It reads the list of columns and their
  types from the database, not rows, and the page says so.
- **`filter:` and `where:` appear in the SQL.** A file's `filter:` is the
  scan's `WHERE`. A check's `where:` narrows only that check's columns, as a
  `CASE WHEN` inside them.
- **"Cannot compile"** means tablewatch cannot build the SQL for this
  dataset, and says why: the datasource is not defined (run
  `tablewatch validate`), or its URL names a database tablewatch has no
  driver for. It affects only that dataset's checks. The message never
  repeats the URL beyond its scheme.
- **It is the SQL as the check files were loaded, not a record of what a
  past run sent.** Results do not store their SQL. The statement is built
  from the check files `serve` loaded at startup, for a run of every check
  on the dataset. A run narrowed with a path or `--check` sends a smaller
  scan, and a result recorded before the files were edited may have used
  different SQL. Values are written into the statement so you can read it;
  a run sends the same statement with bound parameters.
- **Copy the scan** (or **Copy the query**) copies the statement, with its
  closing `;`, ready to paste into the warehouse's console. If the page is
  opened over plain `http://` on an address other than this machine, the
  browser does not allow copying, and the button reads **Select all**
  instead: it selects the statement for you to copy with your keyboard.
- **Invisible characters are marked.** A zero-width space or a
  right-to-left override in a check file would change what the SQL means
  without showing, so the page marks each one where it sits with its code,
  such as `U+200B`. Copy still copies the exact text.

How to read the source:

- **It shows the check's own lines, numbered as in the file.** That is the
  check's entry under `checks:`, from its `-` to its last option, plus the
  comments that go with it. A comment goes with a check when it sits:
  - directly above the check's `-`, with no blank line between. This is the
    place for the note that says why the rule is 5%;
  - directly below the check's last line, with no blank line between, and
    indented further than its `-`, such as a commented-out option.

  A comment after a blank line, or a comment at or left of the `-` after the
  last check, goes with no check and is not shown. A comment at the end of a
  line is always shown with that line. A `#` line inside a `query: |` block
  is part of the query, not a comment.
- **Nothing else in the file appears in the lines.** `dataset:`,
  `datasource:`, `owner:`, `tags:`, `filter:` and `_defaults.yml` never do.
  The page says where the settings at the top of the page come from instead.
- **The file's `filter:` is stated under the lines:** "Only rows matching
  this file's `filter: status != 'test'` (line 3) are checked." Every value
  on the page is about those rows only. A `sql_metric` or `schema` check is
  not narrowed by `filter:`, and the page says so ("does not apply to this
  check").
- **A check written on one line with others**
  (`checks: [row_count > 0, "duplicate_count(id) = 0"]`) shows that whole
  line, the other checks included.
- **Sometimes the lines cannot be shown.** The page then says "The lines of
  this check could not be shown; it is in `checks/sales/orders.yml`", so you
  still know which file to open or ask about. This happens when the check
  shares a line with `dataset:` or `filter:` (a whole file written on one
  line), when the check is a YAML alias (`- *name`), or whenever tablewatch
  cannot place the check's lines exactly: it shows no lines rather than the
  wrong ones. The check itself loads and runs as usual.
- **It is the file as `serve` loaded it**, like the rule and the SQL.
  Editing or deleting the file changes nothing on the page until `serve`
  restarts, and a result recorded before an edit may have been judged by
  different lines.
- **A symbolic link is shown under its own name.** A check file in `checks/`
  that links to a file elsewhere loads like any other, and the page shows its
  lines under the link's path (`checks/sales/linked.yml`), never the path the
  link points to.
- **Copy the source** copies the lines exactly, without the line numbers;
  selecting the lines by hand skips the numbers too. Long lines do not wrap,
  because a YAML line's indentation is part of its meaning: scroll the block
  sideways. Invisible characters are marked, as in the SQL.

### The JSON API

To list what is failing right now, ask for every check whose latest
recorded result is `fail`, `warn` or `error`. The same query shows how long
each problem has lasted and, for errors, what the data last showed:

```console
$ curl -s 'http://127.0.0.1:8765/api/v1/checks?outcome=fail&outcome=warn&outcome=error' \
    | jq -r '.items[] | [.latest.outcome, .latest.since, .latest.last_evaluated.outcome // "-", .dataset, .name] | @tsv'
warn    2026-09-19T06:00:00.000000+00:00  -     inventory.products  Price feed freshness
error   2026-09-25T06:00:00.000000+00:00  pass  sales.customers     row_count > 0
error   2026-09-25T06:00:00.000000+00:00  pass  sales.customers     duplicate_count(customer_id) = 0
error   2026-09-25T06:00:00.000000+00:00  fail  sales.customers     missing_percent(email) < 5%
...
fail    2026-09-19T06:00:00.000000+00:00  -     sales.orders        missing_count(customer_id) = 0
...
$ curl -s http://127.0.0.1:8765/api/v1/checks/b1ceb8262d8b5441/history \
    | jq -r '.items[] | [.started_at, .outcome, .display_value] | @tsv'
2026-09-25T06:00:00.000000+00:00    error   —
2026-09-22T06:00:00.000000+00:00    fail    20.00%
2026-09-19T06:00:00.000000+00:00    fail    20.00%
```

| `GET /api/v1/...` | Returns |
| --- | --- |
| `project` | Name, datasources (names and types only), counts, and any check-file diagnostics |
| `checks` | Every check, each with its latest recorded result. Filter with `?outcome=`, which is repeatable and takes `pass`, `warn`, `fail`, `error`, `skipped` or `not_run` |
| `checks/{id}` | One check, with its `rule` as loaded: `expect`, `warn` and `fail`, each with the condition's `text` and its numbers. Ids are exact: the full id from `tablewatch list` |
| `checks/{id}/history` | That check's results, newest first, including results for checks since deleted. Each carries the `expression`, `metric`, `unit` and `dataset` it was recorded with |
| `checks/{id}/sql` | The SQL a run of that check's dataset sends and this check's value comes from, compiled from the check files as loaded: `dialect`, then `statements` in run order, each a `scan` (with `measures`, the columns this check `uses`, and `shared_by`, the number of *other* checks sharing it) or a `query`. `sql` is the statement as `tablewatch compile` prints it, without the closing `;`. `schema_lookup` is `true` for a `schema` check, which has no statements. `error` says why the dataset cannot be compiled, and `statements` is then empty. Ignore a statement whose `kind` you do not know: later versions add kinds. Never connects to a datasource and does not need the results store |
| `checks/{id}/source` | That check's own lines in its check file, as loaded: `path`, relative to the project and under the checks directory; `start_line` and `end_line`, 1-based and inclusive; and `text`, those lines joined by `\n`. `start_line`, `end_line` and `text` are all `null` when the lines cannot be placed exactly, and `path` is still set. `filter` is the file's `filter:` or `null`: its `line`, its `text` as written (a `${env:NAME}` in it is never resolved), and `applies`, which is `false` for `sql_metric` and `schema` checks. `loaded_at` equals `project`'s. Never reads a file while answering |
| `runs`, `runs/{id}` | Runs, newest first, with counts. One run's detail includes its results |
| `openapi.json` | The contract, also checked in at [docs/api/openapi.json](docs/api/openapi.json) |

Every endpoint is `GET`. `runs` and `history` are paged with `?limit=` (1 to
200, default 50) and the `next_cursor` from the previous page. Timestamps
are UTC, always with six fractional digits.

How to read the results:

- **`latest` is the check's most recent result, which is not always from the
  most recent run.** A run of `checks/sales` leaves the inventory checks'
  results as they were. `latest.started_at` says how old a result is.
- **`latest.since` is when the current streak began**, by the rule the page
  uses for "failing since": for `pass`, `warn` and `fail`, `error` and
  `skipped` results are passed over, and a different evaluated outcome ends
  the streak. For `error`, it is when the errors began. It is always set, and
  it equals `latest.started_at` when the streak is one result long.
- **An `error` replaces the last pass or fail as `latest`.** If tablewatch
  could not evaluate a check last time, the check appears under
  `?outcome=error` and not under `fail`. Ask for `fail`, `warn` and `error`
  together. `latest.last_evaluated` then holds the last pass, warn or fail
  (`outcome`, `started_at`, `since`). It is `null` when `latest` is itself
  evaluated, or when the check has never been evaluated.
- **`not_run` means no result is recorded for this check id.** Editing a
  check's expression gives it a new id, so it matches `not_run` until it runs
  again, and its old results stay under the old id's `history`. Treat
  `not_run` as unknown, not healthy. An explicit `id:` keeps one history
  across edits, and "failing since" with it
  ([check language](docs/check-language.md)).
- **`value` is in the metric's unit, which `unit` names**: `count`, `percent`
  (`20.0` means 20%), `duration` (seconds), or `number`. Show
  `display_value` to people.

### What `serve` reads, and when

- **It reads check files once, at startup. It reads results live.** Restart
  `serve` to pick up edited checks. The page header says how long ago they
  were loaded. A `tablewatch run` from cron appears on the next request, or
  when you press Refresh.
- **A mistake in a check file does not stop `serve`.** It prints the
  diagnostics and serves the checks that loaded. `project` reports
  `"ok": false`, and the page shows the banner. The broken file's checks are
  missing from `checks`, so the failure count can go down. Check `ok` before
  you trust a count.
- **It serves one project per server.** In a results store shared by several
  projects, `serve` shows only runs recorded under this project's `name:`.
  If you rename the project, its earlier runs stay in the store but no longer
  appear. Run one `serve` per project, each on its own `--port`.
- **If the results store cannot be read,** the page says so and shows no
  counts, rather than an empty list that could pass for "nothing failing".

### Who can reach it

There is no authentication yet (it is planned for Phase 4). `serve` listens
on `127.0.0.1` by default, so only the same machine can connect. From your
laptop, the safest way in is an SSH tunnel:

```bash
ssh -L 8765:127.0.0.1:8765 dq-host      # then open http://127.0.0.1:8765/
```

`--host 0.0.0.0` (or any address that is not loopback) serves the network and
prints a warning:

```text
tablewatch: warning: serving on 0.0.0.0 with no authentication — anyone who can reach this address can read this project's check files (comments included), the SQL each check runs, and its results: data values, database error messages that can quote row values, and owner emails. Authentication arrives in Phase 4 (tablewatch.yml cannot turn it on yet).
```

Anyone who can reach the server can read your check files, comments
included. Keep credentials in environment variables (`${env:NAME}`), never
in a check file or a comment.

Results can contain data values, such as a minimum price or a newest
timestamp, and owners' email addresses. An error message can quote a row's
value verbatim (`could not convert string to float: 'N/A'`). The SQL shows
your table and column names, and the values written in your checks:
`valid_values`, `missing_values`, `filter:` and `where:`.

The server answers requests addressed to an IP address or to `localhost`.
To guard against DNS rebinding, it rejects any other host name with
`403 forbidden_host`, in every bind mode. Name each host name that clients
use:

```bash
tablewatch serve --host 0.0.0.0 --allowed-host dq.internal
```

`serve` exits `0` when stopped with Ctrl-C or SIGTERM. It exits `3` when it
could not start: the `server` extra is missing, `tablewatch.yml` is unusable,
the results store cannot be opened, or the port is in use. Its access log
goes to stderr, as JSON with `--log-format json`, and `-q` turns it off.

`serve` is meant for a handful of readers. It accepts at most 64 connections
at once; beyond that the web server itself answers `503` in plain text,
without the API's JSON error body. Anything past a trusted network belongs
behind a reverse proxy, which is also where TLS goes.

## Use from Python

Run checks in the same process as your pipeline or notebook, and get typed
results back:

```python
import tablewatch as tw

result = tw.run("examples/retail", record=False)
print(result)
# RunResult(id='0dbec5384cce', project='retail-example', outcome=fail, pass=10, warn=2, fail=6)

for r in result.results:
    if r.outcome is not tw.Outcome.PASS:
        print(r.outcome, r.check.dataset.name, r.check.name, r.display_value, r.message)
# warn inventory.products Price feed freshness 3d warn when > 1d; newest 2026-...
# fail sales.customers missing_percent(email) < 5% 20.00% expected < 5%
# ...

if result.exit_code() != 0:  # 1: the example has defects planted on purpose
    raise RuntimeError(f"{result.count(tw.Outcome.FAIL)} checks failed")
```

`result.exit_code()` means what `tablewatch run`'s exit code means (see the
table above): `0` clean, `1` the data failed a check, `2` tablewatch could
not evaluate a check or could not record the run. `result.outcome` describes
only the data, so read `exit_code()` to decide what your pipeline does.

`tw.run()` does not raise for bad data. It raises `tw.TablewatchError` only
when **nothing ran**, the library's exit `3`: `tw.ProjectError` when the
project has mistakes (all of them are on `exc.diagnostics`), and
`tw.SelectionError` when no checks matched. Invalid arguments raise
`ValueError` or `TypeError`.

```python
project = tw.load("examples/retail")      # reads YAML; connects to nothing
print(project.ok, len(project.checks))    # True 18

sales = tw.run(project, paths=["checks/sales"], record=False)
print(sales.exit_code())                  # 1

catalogue = tw.run(project, tags=["catalogue"], fail_on="warn", record=False)
print(catalogue.exit_code(), catalogue.exit_code("fail"))   # 1 0
```

- **The project** is a directory, a loaded `tw.load()` project, or `None`
  for the nearest `tablewatch.yml` at or above the current directory.
  `tw.load()` reports check-file mistakes on `project.diagnostics` instead of
  raising.
- **Selectors** are lists (`paths`, `tags`, `datasources`, `excludes`,
  `check_ids`) and narrow the run as their CLI counterparts do. `paths` are
  relative to the project root, not the current directory. `check_ids`
  match by prefix, as `--check` does, so `["a"]` selects every check whose
  id starts with `a`.
- **History.** `record=True`, the default, stores the run in the project's
  results store with `trigger` set to `"python"`. Pass `record=False` for
  exploratory runs: the store is not opened at all. If recording fails, the
  outcomes are still returned, the reasons are in `result.record_errors`, and
  `exit_code()` is `2` whatever `fail_on` says.
- **`fail_on="warn"`** makes warnings count as failures in `exit_code()`,
  and in the exit code recorded for the run. Pass `exit_code("fail")` to ask
  the other question.
- **Values** are in the metric's unit: percentages from 0 to 100, freshness
  in seconds. `display_value` is the same value formatted for people
  (`"14.29%"`, `"1h 13s"`). `started_at` and `finished_at` are UTC.
- **Logging.** The library never configures logging. It logs recording
  failures and check-file warnings at `WARNING` on the `tablewatch` logger,
  so they are silent until your application configures logging (for example
  `logging.basicConfig()`).

The package is typed: mypy checks your code against it. Everything in
`tablewatch.__all__` is public; on `Project`, `Check` and `Dataset`, only
the attributes their docstrings list are promised.

## Development

```bash
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run mypy .
```

## License

MIT — see [LICENSE](LICENSE).
