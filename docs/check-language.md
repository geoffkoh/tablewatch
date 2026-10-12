# The check language

Checks live in YAML files under `checks/`. Each file describes **one
dataset** (a table) and the **named checks** that run against it. A check is
a set of **clauses**, every one of which must hold:

```yaml
dataset: sales.orders            # table, optionally schema.table
datasource: warehouse            # optional if inherited or only one exists
filter: created_at >= CURRENT_DATE - INTERVAL '1 day'   # optional; scopes every check
owner: sales-data@example.com    # optional
tags: [finance, tier-1]          # optional; a string or a list

checks:
  orders_usable:                 # the check's name: its identity
    clauses:
      - row_count > 0
      - missing_count(customer_id) = 0
      - invalid_percent(status) < 1%:
          valid_values: [pending, shipped, delivered, cancelled]
  orders_fresh: freshness(created_at) < 6h    # a check of one clause
```

## Folders and `_defaults.yml`

Organise files in any folder structure. A `_defaults.yml` in a folder applies
to every check file beneath it and may set `datasource`, `owner`, `tags` and
`notify`. The `_defaults.yml` nearest a file wins for `datasource`, `owner`
and `notify`; `tags` accumulate all the way down. If a project has exactly one datasource, datasets
use it without saying so.

## Writing a check

`checks:` maps each check's **name** to what it checks. A name is letters,
digits, `_` and `-`, starts with a letter, is at most 64 characters, and is
unique within its dataset. `.`, `:` and `/` are kept for referring to checks
later (`orders.orders_usable`).

A check of one clause can be written as just its expression:

```yaml
  orders_fresh: freshness(created_at) < 6h
```

Anything else lists its clauses under `clauses:`. A clause is a bare
expression, or an expression with options:

```yaml
  order_values_in_band:
    clauses:
      - avg(amount) between 10 and 500:
          where: status != 'cancelled'
      - max(amount) < 100000
```

**All clauses must hold.** The check's outcome is the worst of its clauses'
— `error`, then `fail`, then `warn`, then `pass`. A clause that is `skipped`
(a `change()` with no history yet) neither passes nor spoils the check; a
check whose clauses are all skipped is `skipped`. Every clause is evaluated,
even after one fails, and each keeps its own value and message: the console
shows the check, then one indented line per clause, in file order:

```console
OUTCOME  DATASET  CHECK                           VALUE  DETAIL
FAIL     orders   orders_usable                          2 pass, 1 fail
  pass            row_count > 0                   7 rows
  fail            missing_count(customer_id) = 0       1  expected = 0
  pass            invalid_percent(status) < 1%     0.00%
```

Each clause has a **key**, unique within its check: by default its metric
call without the rule (`missing_count(customer_id)`, `change(row_count)`).
Two clauses that measure the same thing need a `name:` on one of them:

```yaml
  volume:
    clauses:
      - row_count > 0
      - row_count < 1000000:
          name: not_exploded
```

The list shape of earlier versions (`checks:` as a list of unnamed
expressions) is an error: every check is named.

### Expectations and triggers

An expression with a comparison states what **should be true**. The check
passes when it holds and fails when it does not.

For two levels of severity, leave the comparison off and give triggers.
A trigger states a **problem**, which is what the `when` keyword signals:

```yaml
  order_volume:
    clauses:
      - row_count:
          warn: when < 1000
          fail: when = 0
```

`fail` is tested first, then `warn`. Use either a comparison or triggers,
never both on one clause.

### Comparisons

| Form | Example |
| --- | --- |
| `=` `!=` `<` `<=` `>` `>=` | `row_count >= 100` (`==` and `<>` also accepted) |
| `between A and B` | `avg(amount) between 10 and 500`, inclusive at both ends |
| `not between A and B` | `avg(delta) not between -1 and 1` |

### Values and units

| Value | Meaning | Used with |
| --- | --- | --- |
| `42`, `0.5`, `-3` | a number | counts and numbers |
| `1%`, `0.5%` | a percentage | `*_percent` metrics |
| `30s`, `15m`, `6h`, `2d` | a duration | `freshness` |

Units are checked: `missing_count(x) < 1%` is an error, and tablewatch
suggests `missing_percent`. `freshness(ts) < 6` is an error because it has
no unit.

A `*_percent` threshold is a percentage from 0 to 100, with or without `%`:
`missing_percent(email) < 5` means 5%. A bare number between 0 and 1, such
as `< 0.05`, is read as 0.05% and gets a warning, since it is often a
fraction meant as 5%; write `0.05%` to say you mean it.

### Common options

On a clause:

| Option | Meaning |
| --- | --- |
| `name` | The clause's key within its check (same rules as a check name). Defaults to its metric call. |
| `warn`, `fail` | Triggers, as above. |
| `where` | A SQL condition restricting the rows this clause looks at. Not available on `schema` and `sql_metric`. |

On a check, beside `clauses:`:

| Key | Meaning |
| --- | --- |
| `notify` | Notifiers to tell when this check changes state, overriding its file's (see Notifications). |

## Metrics

Column arguments are column names. Quote names that are not plain
identifiers: `missing_count("Order ID") = 0`.

| Metric | Arguments | Value | Notes |
| --- | --- | --- | --- |
| `row_count` | — | count | Rows in scope. |
| `missing_count` | column | count | NULL, or one of `missing_values`. |
| `missing_percent` | column | percent | Missing as a share of rows in scope. |
| `invalid_count` | column | count | Present but breaking a `valid_*` rule. Needs at least one rule. |
| `invalid_percent` | column | percent | Invalid as a share of rows in scope. |
| `distinct_count` | column | count | Distinct non-NULL values. |
| `duplicate_count` | column, … | count | Surplus rows sharing a key: a key seen 3 times adds 2. Rows with a NULL key are skipped. |
| `duplicate_percent` | column, … | percent | Surplus duplicates as a share of rows in scope. |
| `min` `max` `avg` `sum` | column | number | In the column's own units. Needs a numeric column: text, dates and booleans are `error` (`min needs a numeric column; got text`), and so is a stray text value in a numeric column. |
| `freshness` | column | duration | Age of the newest timestamp. Needs a date or timestamp column, or ISO-8601 text. |
| `failed_rows` | — | count | Rows matching `condition`. Bare `- failed_rows:` expects 0. |
| `sql_metric` | optional label | number | The number your `query` returns. The label is for display; the `query` already tells two checks apart. |
| `schema` | — | count | Problems with the options below, shown as `N problems`. Bare `- schema:` expects 0. |

### Metric options

| Option | Metrics | Meaning |
| --- | --- | --- |
| `missing_values` | `missing_*`, `invalid_*` | Values that count as missing, e.g. `['', 'N/A']`. NULL always counts as missing already, so never list it. To match the text `NULL`, quote it: `'NULL'`. |
| `valid_values` | `invalid_*` | Allowed values. NULL is always missing and never invalid, so never list it (check NULLs with `missing_count`). To match the text `NULL`, quote it: `'NULL'`. |
| `valid_min`, `valid_max` | `invalid_*` | Inclusive numeric bounds. |
| `valid_length`, `valid_min_length`, `valid_max_length` | `invalid_*` | String length rules. |
| `valid_regex` | `invalid_*` | Must match somewhere in the value. Anchor with `^…$` for a full match. This behaves the same on every database. |
| `condition` | `failed_rows` | SQL condition marking a row as bad. |
| `query` | `sql_metric` | SQL returning a single number. Runs exactly as written; the dataset `filter` is not applied. |
| `required_columns`, `forbidden_columns` | `schema` | Column names. |
| `column_types` | `schema` | `{column: type}`. Matches by case-insensitive substring, so `numeric` accepts `NUMERIC(10,2)`. |

A value that is missing is never also counted as invalid, so
`missing_count` and `invalid_count` don't report the same row twice.

In YAML, an unquoted `null`, `Null`, `NULL` or `~`, and a `-` with nothing
after it, all mean null, not text. A null item in `valid_values` or
`missing_values` does nothing, so `validate` warns at its `file:line:col` and
the item is ignored. A `valid_values` list with nothing but nulls is an error,
as is an item that is itself a list or a mapping.

### Empty scopes

When no rows are in scope, the `*_percent` metrics are 0 (nothing is missing,
invalid or duplicated). `min`/`max`/`avg`/`sum` and `freshness` have no
value, and the check **fails** with the reason: missing data is a data
problem, not a tablewatch problem.

## Freshness and time zones

`freshness` is computed as *now − MAX(column)*, against a single "now"
shared by the whole run. Timestamps without a time zone are read in the
datasource's `timezone` (default `UTC`). Set it if your columns hold local
time:

```yaml
datasources:
  erp:
    type: postgres
    timezone: Asia/Singapore
    ...
```

Getting this wrong fails silently: a local-time column read as UTC can look
hours fresher than it really is.

Timestamps *with* a time zone (Postgres `timestamptz`, DuckDB `TIMESTAMPTZ`)
are exact instants. Their age does not depend on `timezone`, which only sets
the zone the message shows them in, and rows written with different offsets
are compared as instants. Prefer a zoned column when you have the choice. On
DuckDB it needs the `duckdb` extra (`pip install 'tablewatch[duckdb]'`), which
brings `pytz`: DuckDB's Python client needs it to read `TIMESTAMPTZ` values but
does not install it.

The message names the newest value in the datasource's zone, to the second,
and the zone with its offset at that time:

```text
newest row at 2026-09-27 09:47:30 Asia/Singapore (UTC+08:00)
```

With the default `timezone` it ends in `UTC`. A date column shows a date
(`newest date 2026-09-26`). When the newest row is more than a minute in the
future, the message says so and names the likely cause: up to 26 hours ahead
it is usually a wrong `timezone` (`…, 1h 47m in the future; check the
datasource's timezone`); further ahead, a placeholder such as `9999-12-31` or a
forward-dated row. The age itself is the check's value; read that, not the
timestamp, to judge it.

## Files as datasets

A `type: files` datasource names a folder; each check file on it names a file
in that folder as its `dataset:`. The file is read in place by an in-memory
DuckDB, in the same single scan as a table: nothing is copied, cached or
written. Every metric, `filter:`, `where:` and `schema` works as on a table,
with one exception for now: a `sql_metric` reading the file itself. Its
query cannot name the file, because the sandbox below refuses relative
paths. It comes in a later release.

```yaml
# tablewatch.yml                       # checks/landing/orders.yml
datasources:                           datasource: drop
  drop:                                dataset: orders.csv
    type: files                        checks:
    root: landing                        orders_landed: row_count = 5
    timezone: UTC                        emails_present: missing_count(email) = 0
```

- **Install:** `pip install 'tablewatch[duckdb]'`, with duckdb 1.5.0 or later
  (older versions are refused at connect: they follow symlinks out of the
  allowed folder).
- **Formats** follow the extension: `.csv` and `.tsv` (`read_csv`), `.parquet`,
  `.json` (an array or one object per line), `.jsonl` and `.ndjson`; a trailing
  `.gz` is read through. DuckDB detects delimiters, headers and types; there
  are no reader options.
- **Root:** a folder inside the project, given relative to it: not the project
  itself, not `.tablewatch`, without `..` and not an `${env:}` reference. When tablewatch connects, the real path of `root`
  (symlinks followed) must still be inside the project, or every check on the
  datasource is `error`.
- **Dataset paths** are relative to `root` and use `/`: `orders.csv` and
  `./orders.csv` are the same dataset and the same check id, and moving `root`
  does not change ids. Absolute paths, `..` and URLs (`s3://`, `https://`) are
  reported by `validate`. SQL, `compile`, the results store and the web UI show
  the relative path only.
- **Patterns:** a dataset may be a pattern, `daily/orders_*.csv`, with `*`,
  `?`, `[ ]`, and `**` for any depth (`**/*.csv` includes files at `root`
  itself); braces (`{ }`) are reported by `validate`. One pattern is **one
  dataset and one scan**: every check sees the rows of all matching files
  together. tablewatch expands the pattern itself, at run time, and DuckDB
  reads exactly that list. As in a shell, hidden files and folders (a name
  starting with `.`) are matched only by a segment that starts with `.`
  (`.staging/*.csv`), never by `*`, `?` or `**`; only regular files match. The check
  id keys on the pattern, so a new day's file keeps the history. A pattern
  matching more than 10,000 files, nothing at all, or a file whose name holds
  `*`, `?`, `[ ]` or `{ }` makes every check on it `error`.
- **Files are unified by column name** (`union_by_name`): a file with its
  columns in another order reads the same, and a column missing from one
  file reads NULL for that file's rows, so it counts as missing rather than
  stopping the dataset. To catch a column a partner drops, pair the pattern
  with a `schema` check: `required_columns: [email]`.
- **`schema`** on a file or pattern checks DuckDB's column names and types
  without reading rows beyond the sample DuckDB takes to detect them. For a
  CSV the types are the ones DuckDB detects (`bigint`, `double`,
  `timestamp`, `varchar`, ...), not declared ones.
- **A read-only sandbox.** The DuckDB connection can read only files under
  `root`: no other folder, no URL, no extension install or load, and its
  configuration is locked before any check runs. Every statement must be a
  single `SELECT`, so a `sql_metric` cannot `COPY`, `SET` or `ATTACH`. A path
  that goes through a **symlink is refused**, even one pointing inside `root`;
  for a pattern, one symlink among the matches or on a folder the pattern
  walks refuses the whole dataset rather than silently changing its rows.
  Memory is capped at 2 GB and 4 threads, with no spill to disk.
- **Errors** are fixed text, never DuckDB's own (which quotes file paths and
  lines of the file), and for a pattern they name the pattern, never one of
  its files: `no file matches 'x.csv' in the files datasource 'drop'`,
  `could not read 'x.csv' as csv`, `'x.csv' is not valid UTF-8`, `the read was
  refused (outside root, a write, a URL or a setting)`, or the error type, such
  as `(BinderException)` for a column that does not exist.
- **Blanks:** in a CSV every blank field, quoted or not, reads as NULL, so it
  counts as missing; JSON keeps an absent key (NULL) and `""` apart, as a table
  does. A UTF-8 byte-order mark is ignored.

## Check identity

History, and in later phases alert state, follows a check by its **name**
on its dataset and datasource. The id that `tablewatch list` shows is
derived from those three, and nothing else.

- Moving or renaming the file keeps the id and the history.
- Editing, adding, removing or reordering clauses keeps the check's id: it is
  the same check, stated better.
- **Renaming a check starts a new history.** The old results stay readable
  (`tablewatch history <old id>`). There is no rename mapping.
- `id:` is not a key any more: a check's name is its identity.
- Two checks with one name on one dataset are an error, even in two files.
  The same name on two datasets is two checks.
- **Moving a check to another dataset or datasource starts a new history**,
  as a rename does: the results store registers each check by project,
  datasource, dataset and name, and gives it an id of its own.

Each clause has its own history too, keyed by its check, its key, its
`where:` and, for `failed_rows` and `sql_metric`, its `condition:` or
`query:` — what it measures, not its rule:

- Tightening a threshold (`< 1%` → `< 0.5%`), changing triggers, refining
  options such as `valid_values`, or reordering clauses keeps the clause's
  history (and a `change()` clause's baseline).
- Changing what is measured — the metric call, `where:`, `condition:` or
  `query:`, or the clause's `name:` — starts a new one. Text in `where:`,
  `condition:` and `query:` is compared with any run of whitespace counted as
  one space, so reflowing SQL keeps the history; any other edit to it,
  letter case included, starts a new one.
- To explain a check, use a YAML `# comment`. Don't use a SQL `--` comment:
  in `condition:` it comments out the rest of the dataset's scan and the
  clause errors, and in `query:` it is part of what is measured.

## Change over time

`change(<metric>)` compares a clause with the same clause's previous recorded
run, so a threshold follows the data instead of being guessed:

```yaml
checks:
  volume_steady: change(row_count) > -20%     # no more than a 20% drop since the last run
  revenue_steady: change(sum(amount)) between -5000 and 5000
  volume_alarm:
    clauses:
      - change(row_count):
          warn: when < -10%
          fail: when < -50%
```

- The value is **signed**, now minus then: a drop is negative and a rise shows
  its sign (`+50 rows`, `-15.00%`). `between -20% and 20%` catches a move
  either way. A relative change always shows two decimals (`0.00%`); an
  absolute one is shown in the metric's own format (`0 rows`, `+3400`). A
  relative change is measured against the size of the old value, so a sum
  that rises from -100 to -50 reads `+50.00%`.
- With `%` the change is relative, `(now − then) ÷ then × 100`; with plain
  numbers it is absolute, in the metric's own units. Use one or the other in a
  check, not both.
- `change()` wraps counts and numbers (`row_count`, `missing_count`,
  `failed_rows`, `sum`, `avg`, `sql_metric`, …), not percentages, durations or
  `schema`, and it always needs a comparison or triggers.
- **Previous** is the newest result of the same check in this project, from a
  run that started earlier and measured a value. An `error` is passed over.
  The first run, and a relative change from a previous 0, are `skipped`: there
  is nothing meaningful to compare.
- Under `run --run-key`, every attempt under the same key is one run: a
  retry or `--rerun` never takes an earlier attempt under its own key as its
  baseline, only runs from before (see "On servers" in the README).
- It reads the results store, also under `run --no-store` (which still writes
  nothing). If the store cannot be read, only the `change()` checks are
  `error`. Changing what a clause measures starts a new baseline; tightening
  its rule keeps it (see Check identity).
- **Baselines.** A second argument says what to compare with:

  ```yaml
  weekly_volume: change(row_count, same weekday) > -20%   # the newest run on this weekday, 6+ days ago
  smoothed_volume: change(row_count, last 7 runs) > -20%  # the average of the 7 newest earlier runs
  ```

  Without one, it is the previous run, whatever its weekday, so a quiet
  weekend shows as a drop; `same weekday` compares a Saturday with a Saturday
  (weekdays in UTC, as run times are). `last N runs` (N from 2 to 100) takes the
  mean, so one odd run does not become the next run's yardstick, and stays
  `skipped` until N earlier results exist. A message names its baseline:
  `1,000 → 950 rows since the run of 2026-09-26 06:00 UTC (same weekday)`,
  `average 1,000 of the last 3 runs (2026-09-30 06:00 to 2026-10-02 06:00 UTC) → 500 rows`.

## Notifications

tablewatch tells you when a check **changes state**, then stays quiet while
it stays that way. Define notifiers in `tablewatch.yml` and name them with
`notify:` in a check file, a `_defaults.yml`, or on one check (beside its `clauses:`):

```yaml
# tablewatch.yml
notifiers:
  data-alerts:
    type: webhook
    url: ${env:TW_DATA_ALERTS_URL}
```

```yaml
# checks/sales/_defaults.yml
notify: data-alerts          # or a list: [data-alerts, platform]
```

- A webhook URL is a secret: `url:` must be exactly one `${env:NAME}`
  reference, read only when a notification is sent. `validate`, `list` and
  `compile` work without it.
- `notify:` is inherited like `owner`: the nearest setting wins, and
  `notify: []` turns notifications off below it. Adding or removing
  `notify:` keeps a check's id and history.
- A notifier name is letters, digits, `_`, `.` and `-`. `owner` is reserved.

**Events.** After a run is recorded, each check's result is compared with
its history:

| Event | When |
| --- | --- |
| `failing` | It fails, and the newest earlier `fail` or `pass` was a `pass` (or there is none). |
| `recovered` | It passes, and the newest earlier `fail` or `pass` was a `fail`. |
| `erroring` | tablewatch could not evaluate it, and the newest earlier result that was not `skipped` was not an `error`. |

`warn` and `skipped` send nothing. `warn` and `error` results neither open nor
close a failure: `fail`, `error`, `fail` alerts once, and `fail`, `warn`,
`pass` is a recovery. A check that fails on its first run alerts; one that
passes does not. A run of some checks (`--path`, `--tag`) only considers
those checks. Renaming a check starts it afresh, so
it alerts as new.

**Delivery.** Each notifier gets one POST per run that has at least one
event for it: JSON, `https` only (plain `http` only to this machine),
redirects not followed, a 10-second timeout per network step, no retry.
A notification that cannot be sent is a warning on stderr that names the
notifier and the reason (`HTTP 500`, `timed out`), never the URL. It never
changes the exit code. `run --no-store` and `tw.run(record=False)` send
nothing, because events come from history. `run --no-notify` and
`tw.run(notify=False)` record the run without notifying.

**Payload** (`schema_version` 1; [JSON Schema](api/notification.schema.json)):

```json
{"schema_version": 1, "project": "retail-example", "notifier": "data-alerts",
 "run": {"id": "…", "started_at": "2026-10-02T08:00:00.000000+00:00", "trigger": "cli"},
 "events": [{"event": "failing", "outcome": "fail", "previous_outcome": "pass",
   "check": {"id": "…", "name": "…", "path": "checks/sales/orders.yml",
             "dataset": "orders", "datasource": "lake",
             "owner": "sales-data@example.com", "tags": ["sales"]},
   "value": 3.0, "display_value": "3 rows", "message": "…",
   "recorded_at": null}]}
```

`recorded_at` is when the check's dataset was recorded, under `run
--run-key` (null otherwise): an attempt that resumes a run can send a change
an earlier attempt recorded, and Slack then adds `(recorded 2026-10-02 05:00
UTC)` to the line.

**Under `--run-key`.** Each dataset's changes are written to the results
store with its results and sent at the end of the attempt; one that does not
get through — the process died, or the notifier failed — is sent by the next
attempt under the key (a resume, a `--rerun`, or running a completed key
again), in one message per run and notifier. Only an attempt under the same key
sends them: with a key per day, what the day's last attempt could not send
stays unsent, and that attempt's warning is the last word on it. A change is sent once, unless
the process dies between a send that succeeded and recording it as sent.
A notifier that keeps failing warns on each attempt — `notifier
'data-alerts' could not send: HTTP 500 (2 pending, oldest since 2026-10-02
05:00 UTC)` — and is given up on after 5 attempts or 24 hours, with a
warning naming how many and why (`gave up on 2 alerts after 5 attempts`). A change for a notifier no longer named in the
check's `notify:`, or one a later attempt has re-evaluated, is dropped. The
store keeps which notifier to tell, never its URL: it is read from
`tablewatch.yml` when sent, so anyone who can write to the results store can
make tablewatch post to a configured channel.

**Slack.** `type: slack` posts to a Slack
[incoming webhook](https://docs.slack.dev/messaging/sending-messages-using-incoming-webhooks),
with the same `url: ${env:NAME}` rule and the same events:

```yaml
notifiers:
  sales-slack:
    type: slack
    url: ${env:TW_SALES_SLACK_URL}
```

The message has a header such as `retail-example: 2 failing, 1 could not
evaluate, 1 recovered`. Below it are the groups **Failing**, **Could not
evaluate** and **Recovered**, one line per check: `orders · row_count > 0:
0 rows — expected > 0 (owner: sales-data@example.com)`. A context line gives
the run id, its trigger and the time in UTC. Channel, name and icon come from
the webhook's own settings in Slack.

- Names, datasets, owners and messages can never ping a channel or become a
  link. `<`, `>` and `&` are escaped, `@here` stays plain text, line breaks
  and direction controls become spaces, and link previews are off.
- Each string is cut at 200 characters (a message at 300). A long group ends
  `…and 12 more failing`. The header always gives the true totals.
- The message holds no file path, datasource, URL or link.

An `erroring` event's `message` is always `could not evaluate`. The
database's own error text can quote your data, so it stays in the run's
results (`tablewatch history`, the web UI). Adding a field keeps
`schema_version`; removing or renaming one changes it.

## Security note

`filter`, `where`, `condition` and `query` are SQL written in your checks
repository. They run with the datasource's credentials. Treat the checks
repository as trusted code, and give tablewatch a **read-only** database role.
