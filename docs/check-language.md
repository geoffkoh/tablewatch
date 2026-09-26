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
to every check file beneath it and may set `datasource`, `owner` and `tags`.
The `_defaults.yml` nearest a file wins for `datasource` and `owner`; `tags`
accumulate all the way down. If a project has exactly one datasource, datasets
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
| `sql_metric` | optional label | number | The number your `query` returns. |
| `schema` | — | count | Violations of the options below. Bare `- schema:` expects 0. |

### Metric options

| Option | Metrics | Meaning |
| --- | --- | --- |
| `missing_values` | `missing_*`, `invalid_*` | Values that count as missing, e.g. `['', 'N/A']`. |
| `valid_values` | `invalid_*` | Allowed values. |
| `valid_min`, `valid_max` | `invalid_*` | Inclusive numeric bounds. |
| `valid_length`, `valid_min_length`, `valid_max_length` | `invalid_*` | String length rules. |
| `valid_regex` | `invalid_*` | Must match somewhere in the value. Anchor with `^…$` for a full match. This behaves the same on every database. |
| `condition` | `failed_rows` | SQL condition marking a row as bad. |
| `query` | `sql_metric` | SQL returning a single number. Runs exactly as written; the dataset `filter` is not applied. |
| `required_columns`, `forbidden_columns` | `schema` | Column names. |
| `column_types` | `schema` | `{column: type}`. Matches by case-insensitive substring, so `numeric` accepts `NUMERIC(10,2)`. |

A value that is missing is never also counted as invalid, so
`missing_count` and `invalid_count` don't report the same row twice.

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

## Check identity

History, and in later phases alert state, follows a check by its **id**.
Without an explicit `id:`, the id is derived from the file path, the dataset,
the normalised expression and triggers, and the `where:` scope.

- Reformatting (`row_count>0` → `row_count > 0`) keeps the id.
- Changing the expression, triggers, `where:`, or moving the file starts a
  new history. Set `id:` to keep history across such edits.
- Refining options such as `valid_values` keeps the id: it's the same check,
  stated better.
- Two checks that would get the same id are an error. Give one an `id:`.
- An explicit `id:` uses letters, digits, `.`, `_`, `:` and `-`, starts with a
  letter or digit, and is at most 64 characters.

## Security note

`filter`, `where`, `condition` and `query` are SQL written in your checks
repository. They run with the datasource's credentials. Treat the checks
repository as trusted code, and give tablewatch a **read-only** database role.
