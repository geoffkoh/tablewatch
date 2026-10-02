# The check language

Checks live in YAML files under `checks/`. Each file describes **one
dataset** (a table) and the checks that run against it:

```yaml
dataset: sales.orders            # table, optionally schema.table
datasource: warehouse            # optional if inherited or only one exists
filter: created_at >= CURRENT_DATE - INTERVAL '1 day'   # optional; scopes every check
owner: sales-data@example.com    # optional
tags: [finance, tier-1]          # optional; a string or a list

checks:
  - row_count > 0
  - missing_count(customer_id) = 0
  - invalid_percent(status) < 1%:
      valid_values: [pending, shipped, delivered, cancelled]
```

## Folders and `_defaults.yml`

Organise files in any folder structure. A `_defaults.yml` in a folder applies
to every check file beneath it and may set `datasource`, `owner`, `tags` and
`notify`. The `_defaults.yml` nearest a file wins for `datasource`, `owner`
and `notify`; `tags` accumulate all the way down. If a project has exactly one datasource, datasets
use it without saying so.

## Writing a check

A check is either a bare expression:

```yaml
  - freshness(created_at) < 6h
```

or an expression with options:

```yaml
  - avg(amount) between 10 and 500:
      name: Average order value in band
      where: status != 'cancelled'
```

### Expectations and triggers

An expression with a comparison states what **should be true**. The check
passes when it holds and fails when it does not.

For two levels of severity, leave the comparison off and give triggers.
A trigger states a **problem**, which is what the `when` keyword signals:

```yaml
  - row_count:
      warn: when < 1000
      fail: when = 0
```

`fail` is tested first, then `warn`. Use either a comparison or triggers,
never both on one check.

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

### Common options

| Option | Meaning |
| --- | --- |
| `name` | Label shown in results. Defaults to the expression. |
| `id` | Pins the check's identity (see below). Letters, digits, `.` `_` `:` `-`. |
| `warn`, `fail` | Triggers, as above. |
| `where` | A SQL condition restricting the rows this check looks at. Not available on `schema` and `sql_metric`. |
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
| `min` `max` `avg` `sum` | column | number | In the column's own units. |
| `freshness` | column | duration | Age of the newest timestamp. |
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

## Check identity

History, and in later phases alert state, follows a check by its **id**.
Without an explicit `id:`, the id is derived from the file path, the dataset,
the normalised expression and triggers, the `where:` scope and, for
`failed_rows` and `sql_metric`, the `condition:` or `query:`. For those two
metrics the SQL *is* the check, so two `failed_rows` checks with different
conditions on one dataset are two checks, each with its own history.

- Reformatting the expression (`row_count>0` → `row_count > 0`) keeps the id.
- Reflowing `where:`, `condition:` or `query:` keeps the id: adding or
  removing spaces, tabs and line breaks between words, or switching to a YAML
  block (`|`, `>`) or to quotes. Any run of whitespace, including
  non-breaking spaces, counts as one space, even inside a quoted string, so
  `status = 'a  b'` and `status = 'a b'` share an id. A line break counts as
  a space too, so moving one into or out of a `--` comment keeps the id even
  though it changes what the SQL does. Any other edit to that SQL starts a new
  history, including a change of letter case (`AND` → `and`), a `--`
  comment added or edited, a `;`, parentheses, and removing the space
  between two words (`total < 0` → `total<0`). tablewatch does not parse
  your SQL, so it cannot tell that these mean the same.
- Changing the expression, triggers, `where:`, `condition:` or `query:`, the
  dataset, or moving the file starts a new history. The old results stay
  readable under the old id (`tablewatch history <old id>`).
- Other options still do not count: refining `valid_values`,
  `missing_values` or `schema`'s column lists keeps the id. It's the same
  check, stated better. `name:` does not count either.
- Two checks that would get the same id are an error. Give one an `id:`.
- To explain a check, use a YAML `# comment` or `name:`; neither touches the
  id. Don't use a SQL `--` comment: in `condition:` it comments out the rest
  of the dataset's scan and the check errors, and in `query:` it is part of
  the id.
- Before reformatting the SQL of a check whose history matters, pin its
  current id: copy all 16 characters of its `id` from
  `tablewatch list --output json` into `id:`. Not the 12 that
  `tablewatch list` shows: a 12-character `id:` is accepted but starts a new
  history.
- An explicit `id:` is never derived, so edits to the check don't change it.
  It uses letters, digits, `.`, `_`, `:` and `-`, starts with a letter or
  digit, and is at most 64 characters.

## Notifications

tablewatch tells you when a check **changes state**, then stays quiet while
it stays that way. Define notifiers in `tablewatch.yml` and name them with
`notify:` in a check file, a `_defaults.yml`, or on one check:

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
those checks. Editing a check so that its id changes starts it afresh, so
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
   "value": 3.0, "display_value": "3 rows", "message": "…"}]}
```

An `erroring` event's `message` is always `could not evaluate`. The
database's own error text can quote your data, so it stays in the run's
results (`tablewatch history`, the web UI). Adding a field keeps
`schema_version`; removing or renaming one changes it.

## Security note

`filter`, `where`, `condition` and `query` are SQL written in your checks
repository. They run with the datasource's credentials. Treat the checks
repository as trusted code, and give tablewatch a **read-only** database role.
