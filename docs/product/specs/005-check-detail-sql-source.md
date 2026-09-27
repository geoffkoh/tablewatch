# Spec 005: Check detail 2 (the compiled SQL and the check's own YAML)

| | |
| --- | --- |
| Backlog item | I-26 (the second half of I-05, split in iteration 4 PLAN) |
| Features | C4 (check detail): the SQL and source parts. C4 is complete when this ships |
| Phase | 2 (`0.2.0`) |
| Size | S |
| Depends on | I-05 ✓ (spec 004: the check page, `CheckDetail`, the shared load hook) |
| Unblocks | nothing directly; I-24 (4.8) runs straight after it by the iteration 4 REFINE decision |
| Branch | `iter/005-check-detail-sql-source` |
| Status | planned (iteration 5 PLAN, 2026-09-27) |

## Problem and persona

**Dana, data engineer.** "Sam sends me the check page and asks why
`missing_percent(email)` says 20%. I open a terminal, find the file,
run `tablewatch compile checks/sales/customers.yml`, scroll to the right
dataset, and work out which of the `m0`…`m3` columns this check uses.
Then I paste the SQL into the warehouse console to look at the rows.
The page already has everything else. It should have the query."

**Sam, data steward.** "I don't write SQL, but I do read YAML. When the
page says 'Expected < 5%' I want to see what was written in the file,
including the comment that says why the rule is 5%, and which file to
ask Dana to change. I can't browse the repository."

**Priya, platform.** "Someone asks why their check costs a scan of a
billion-row table. I want to see that it rides the dataset's one scan,
and what else rides it, without reading the planner."

**How they cope today.** `tablewatch compile` prints every statement
for the selected datasets, but not which columns belong to which check,
and it needs a checkout and a shell. The page shows `file:line:col`, so
the source is one editor jump away for Dana and out of reach for Sam.
Principle 3 ("every number is explainable") is met on the command line
only.

### How others do it

- **Elementary** shows each test's details, including the exact compiled
  query, and lets the user copy it in one click to run in the warehouse.
  ([Elementary: inspecting test results](https://www.elementary-data.com/demo-videos/inspecting-test-results);
  [Elementary data tests](https://docs.elementary-data.com/data-tests/introduction))
  We borrow the compiled query on the test's own page and the copy
  button (`should`, P9).
- **dbt docs** give each model a Code tab showing both the source code
  and the compiled code.
  ([dbt: discover data with Catalog](https://www.getdbt.com/blog/using-dbt-docs/);
  [dbt: documentation website](https://docs.getdbt.com/docs/building-a-dbt-project/testing-and-documentation/documentation-website/))
  We borrow source next to compiled SQL. We do not borrow tabs: our two
  blocks are short and both are wanted at once.
- **Soda** shows the SQL it runs through the scan's verbose option
  (`soda scan -V`) rather than on the check's page, and carries failed-row
  queries as diagnostics.
  ([Soda: run a scan and view results](https://docs.soda.io/soda-documentation/soda-v3/run-a-scan);
  [Soda: failed rows check](https://docs.soda.io/data-testing/failed-rows-check))
  Our `tablewatch compile` is that today. Failed-row queries are C7,
  Phase 2b, and not part of this spec.

What none of them does, and tablewatch can, is say **which part of a
shared scan answers this check**. Our planner folds a dataset's
aggregates into one `SELECT` (rule 1). Showing only this check's
columns would hide the cost; showing only the whole scan would hide
the answer. We show the whole statement and name this check's columns.

## Outcome

On `/checks/<id>`, below the history, two new sections:

- **SQL.** The statement(s) a run of this check's dataset sends that
  this check's value comes from, in the datasource's dialect, exactly as
  `tablewatch compile` prints them. For the single scan, the whole
  `SELECT` is shown and this check's columns (`m0`, `m1`, …) are named
  with their expressions. A `schema` check says it reads the column list,
  not rows. If the dataset cannot be compiled (an unknown dialect), the
  section says so and the rest of the page is unaffected.
- **Source.** The check's own lines from its file under `checks/`, with
  line numbers and the file path, as loaded by this server.

Two read-only endpoints serve them: `GET /api/v1/checks/{id}/sql` and
`GET /api/v1/checks/{id}/source`. Neither connects to a datasource,
reads the results store, or reads a file at request time. `tablewatch
compile` and the endpoint share one compile path; `compile`'s output
does not change.

## Scope at a glance

| Part | Who builds it | Where |
| --- | --- | --- |
| One compile path shared by `tablewatch compile` and the API (C1, S7) | tech lead | outside `server/` (it holds no SQL); architect picks the module (Q1) |
| The check's line span and the file text as loaded (Y*) | tech lead | `config/loader.py`, `checks/model.py` (provisional attributes) |
| Two endpoints, wire models, OpenAPI regenerated | tech lead | `server/routes.py`, `server/schemas.py`, `docs/api/openapi.json` |
| The `--host` warning names SQL and source (X3) | tech lead | `cli/main.py` |
| `CheckPage.tsx` split into section components; the SQL and Source sections | ui-engineer | `frontend/**`, `docs/UI_SPECIFICATION.md`, the bundle |
| README: "Reading a check's page" gains the two sections; the `--host` warning text | data-steward | `README.md` |

**Order inside BUILD.** C1 (golden `compile` output captured on `main`)
first, then the shared compile path, then the endpoints and
`openapi.json`, then types are regenerated (spec 003's K3 enforces the
chain), then the page.

## The contract change (additive)

Two new operations under `/api/v1`. Nothing existing changes; `v1`
stays. Both answer `404 not_found` (the existing envelope) for an id
that is malformed or not in the loaded project, and carry the same
security and `no-store` headers as every API response.

### `GET /api/v1/checks/{id}/sql` → `CheckSql`

```text
CheckSql   { check_id: string, dataset: string, datasource: string,
             dialect: string | null,          # SQLAlchemy dialect name: "duckdb", "sqlite", "postgresql"
             statements: Statement[],         # in the order a run issues them; only those this check uses
             schema_lookup: boolean,          # this check reads the table's column list
             error: string | null }           # set when the dataset cannot be compiled; statements is []
Statement  = { kind: "scan",  sql: string, measures: int, uses: ScanColumn[], shared_by: int }
           | { kind: "query", sql: string, shared_by: int }
ScanColumn { label: string, sql: string, shared_by: int }   # label "m0", "m1", … as in the scan
```

- `sql` is the statement as `tablewatch compile` prints it, without the
  trailing `;`: values inlined (`literal_binds`) for reading. A run sends
  the same statement with bound parameters.
- The scan is the one a run of the **whole dataset** issues (every
  loaded check on it). A run narrowed by selectors issues a smaller
  scan; see non-goals.
- `measures` is the number of columns in the scan. `shared_by` is the
  number of **other** loaded checks on the dataset that use that
  statement or column (`should`, S4).
- A `schema` check has `statements: []` and `schema_lookup: true`.
- `error` is the message `tablewatch compile` prints after `-- cannot
  compile:`. It never contains a URL, user name or password (S6).

### `GET /api/v1/checks/{id}/source` → `CheckSource`

```text
CheckSource { check_id: string, path: string,         # project-relative, always under checks/
              start_line: int, end_line: int,           # 1-based, inclusive
              text: string,                             # those lines, joined by "\n", no trailing newline
              loaded_at: date-time }                    # equals /project's loaded_at
```

- The span (D2): from the check's list item (`- …`) through the last line
  of its options, **extended upward over a comment block directly above
  it** (no blank line between) and **trimmed of trailing blank and
  comment-only lines**. Inline comments stay.
- The text is as loaded when `serve` started, like `rule` (spec 004). No
  file is read at request time; nothing about the path comes from the
  request.

## Acceptance scenarios

**Fixtures** (`tests/conftest.py`; specs 002–004):

- `retail`: a copy of `examples/retail` with its database built.
- `recorded`, `edited`, `edited-pending`: as spec 004.
- **`commented`** (new): `retail` with `checks/sales/orders.yml` replaced
  by the file in Y4.
- **`remote`** (new): a project with no database, whose `tablewatch.yml`
  is

  ```yaml
  # canary-tw-5f3a: never served
  name: remote
  datasources:
    pg:
      type: postgres
      host: 192.0.2.1          # TEST-NET-1: unroutable
      database: analytics
      user: tw_reader
      password: ${env:TW_TEST_PG_PASSWORD}
    wh:
      type: sqlalchemy
      url: snowflake://dana:hunter2@acct/db
  results:
    url: sqlite:///.tablewatch/results.db
  ```

  with `checks/_defaults.yml` holding `owner: ops@example.com` under a
  comment line `# canary-tw-5f3a`, and two check files:

  ```yaml
  # checks/pg/orders.yml
  dataset: public.orders
  datasource: pg
  checks:
    - row_count > 0
    - invalid_count(status) = 0:
        valid_values: [open, closed]
  ```

  ```yaml
  # checks/wh/events.yml
  dataset: events
  datasource: wh
  checks:
    - row_count > 0
  ```

  `TW_TEST_PG_PASSWORD` is unset. The snowflake dialect is not installed.

No fixture here draws anything on a time axis. Any fixture that records
runs for these scenarios spaces them by hours (iteration 4, requirement
(e)); none is needed, since SQL and source never read the store.

Check ids (confirmed by the PM on 2026-09-27 against `main` with
`tablewatch.load()` and the planner on `examples/retail`):

| id | dataset | expression | lines | scan columns used |
| --- | --- | --- | --- | --- |
| `b1ceb8262d8b5441` | sales.customers | `missing_percent(email) < 5%` | customers.yml 6–7 | `m0`, `m1` |
| `32c8f939b90f6367` | sales.customers | `row_count > 0` | customers.yml 4 | `m0` |
| `af0289a72fedd946` | sales.customers | `duplicate_count(customer_id) = 0` | customers.yml 5 | none (own query) |
| `32867fbe86f483f3` | sales.orders | `row_count \| warn when < 100 \| fail when = 0` ("Order volume") | orders.yml 5–8 | `m0` |
| `a81b0374b0b04f06` | sales.orders | `freshness(created_at) < 6h` | orders.yml 14 | `m4` |
| `ed669ca6e5532a59` | sales.orders | `failed_rows` ("No negative amounts") | orders.yml 15–17 | `m5` |
| `fbc3aa0b93b66eee` | sales.orders | `schema` | orders.yml 18–20 | none (schema lookup) |

On `retail`, `sales.customers`' scan has 4 measures, `sales.orders`' 6.
Reproduce with `tablewatch --project-dir examples/retail compile` and
`plan_dataset(...).wiring`.

### The compile path (tech lead, pytest)

**C1: `compile` does not change** `must`
- Given `retail`, and the output of `tablewatch compile` captured on
  `main` before BUILD (committed as a golden file)
- When `tablewatch compile` runs on the branch
- Then stdout is byte-for-byte the golden file, and the exit code is 0
- And the same holds for `tablewatch compile checks/sales` (a selection)

**C2: one path** `must` (architect confirms in VERIFY)
- `tablewatch compile` and `GET /checks/{id}/sql` call the same function
  to plan and render a dataset. Neither `cli/` nor `server/` calls
  `plan_dataset` or `render` itself, and `server/` contains no SQL text.

### SQL (tech lead, pytest)

**S1: a percent check names its columns** `must`
- Given `retail` served
- When `GET /api/v1/checks/b1ceb8262d8b5441/sql`
- Then 200, `dataset` `"sales.customers"`, `datasource` `"lake"`,
  `dialect` `"duckdb"`, `schema_lookup` false, `error` null
- And `statements` is one `scan` whose `sql` equals the scan statement
  `tablewatch compile checks/sales/customers.yml` prints (without `;`),
  with `measures` 4
- And `uses` is, in scan order, `{label: "m0", sql: "count(*)"}` and
  `{label: "m1", sql: "sum(CASE WHEN (email IS NULL OR email IN ('', 'N/A')) THEN 1 ELSE 0 END)"}`

**S2: a check with its own query** `must`
- When `GET /api/v1/checks/af0289a72fedd946/sql`
- Then `statements` is one `query`, whose `sql` is the
  `duplicate_groups` statement `compile` prints for `sales.customers`,
  and there is no `scan`

**S3: a schema check** `must`
- When `GET /api/v1/checks/fbc3aa0b93b66eee/sql`
- Then `statements` is `[]`, `schema_lookup` is true, `error` null

**S4: sharing** `should`
- When `GET /api/v1/checks/32867fbe86f483f3/sql` ("Order volume")
- Then the scan has `measures` 6 and `uses` is `[{label: "m0", sql:
  "count(*)", shared_by: 2}]` (`row_count > 0` and
  `invalid_percent(status) < 1%` on `sales.orders` also use `m0`)
- And the scan's `shared_by` is 6 (every other `sales.orders` check but
  `duplicate_count(order_id)` and `schema`)
- And for `af0289a72fedd946`, the query's `shared_by` is 0

**S5: credential-free** `must`
- Given `remote` served, `TW_TEST_PG_PASSWORD` unset, and
  `create_engine_for` patched to fail the test if called
- When `GET /api/v1/checks/<id of row_count > 0 on public.orders>/sql`
- Then 200 within 2 seconds, `dialect` `"postgresql"`, one scan whose
  `sql` renders `FROM public.orders`, `error` null
- And no connection was attempted

**S6: cannot compile, and nothing secret leaks** `must`
- Given `remote` served
- When `GET /api/v1/checks/<id of row_count > 0 on events>/sql`
- Then 200, `statements` `[]`, `dialect` null, and `error` starts with
  `unsupported SQLAlchemy URL scheme 'snowflake'`
- And the response body contains none of `hunter2`, `dana`, `acct`
- And `GET /api/v1/checks/<pg check id>/sql` is unaffected (200, SQL
  present): one dataset that cannot compile affects only its own checks

**S7: the same SQL as `compile`, on DuckDB and SQLite** `must`
- Given `retail`, and a SQLite copy of `retail` (the project the metric
  tests already build on both backends)
- When `/sql` is requested for every loaded check
- Then every `statements[].sql + ";"` appears in `tablewatch compile`'s
  output for that check's dataset, and every scan column's `sql` is a
  column of that scan

**S8: not in the loaded project** `must`
- When `GET /api/v1/checks/0000000000000000/sql`, or an id the store has
  history for but the loaded project does not (spec 004 D15)
- Then 404 with the `not_found` envelope

**S9: no store needed** `should`
- Given `retail` served, then the results store file made unreadable
- When `/sql` and `/source` are requested for `b1ceb8262d8b5441`
- Then both answer 200 (while `/checks` answers 503 as today)

### Source (tech lead, pytest)

**Y1: a check with options** `must`
- Given `retail` served
- When `GET /api/v1/checks/b1ceb8262d8b5441/source`
- Then 200 with `path` `"checks/sales/customers.yml"`, `start_line` 6,
  `end_line` 7, and `text`

  ```text
    - missing_percent(email) < 5%:
        missing_values: ['', 'N/A']
  ```

  (two lines, original indentation, no trailing newline), and
  `loaded_at` equal to `GET /api/v1/project`'s `loaded_at`

**Y2: a trigger check in the middle of a file** `must`
- When `GET /api/v1/checks/32867fbe86f483f3/source`
- Then `path` `"checks/sales/orders.yml"`, lines 5–8:

  ```text
    - row_count:
        name: Order volume
        warn: when < 100
        fail: when = 0
  ```

**Y3: the last check in a file, and a one-line check** `must`
- `fbc3aa0b93b66eee` is `orders.yml` lines 18–20 (ending
  `      column_types: {amount: decimal}`)
- `32c8f939b90f6367` is `customers.yml` line 4 only (`start_line` =
  `end_line` = 4)

**Y4: comments** `must`
- Given `commented`, where `checks/sales/orders.yml` is

  ```yaml
  dataset: sales.orders

  checks:
    # Finance reconciles on amount: a negative amount breaks the ledger.
    # Refunds are separate rows, so none should be negative.
    - failed_rows:
        name: No negative amounts
        condition: amount < 0   # refunds are their own rows

    # Volume alarm agreed with ops, 2026-09.
    - row_count:
        name: Order volume
        warn: when < 100
        fail: when = 0
    # trailing note, not part of any check
  ```

- Then "No negative amounts" is lines 4–8 (both comment lines above it,
  the inline comment kept, the blank line 9 dropped)
- And "Order volume" is lines 10–14 (its comment line 10 included; the
  trailing comment on line 15 is not)

**Y5: as loaded, never re-read** `must`
- Given `retail` served
- When `checks/sales/customers.yml` is then edited on disk, and later
  deleted
- Then `/source` for `b1ceb8262d8b5441` still answers 200 with Y1's text
  and lines, and `/sql` with S1's SQL

**Y6: nothing outside the check's lines, ever** `must`
- Given `remote` served
- When `/source` and `/sql` are requested for every loaded check
- Then no response body contains `canary-tw-5f3a` (it is only in
  `tablewatch.yml` and `_defaults.yml`), and every `path` starts with
  `checks/` and is not a `_defaults.yml`

**Y7: ids that look like paths** `must`
- When `GET /api/v1/checks/{x}/source` for `x` in `tablewatch.yml`,
  `..%2Ftablewatch.yml`, `%2e%2e`, `checks%2Fsales%2Fcustomers.yml`, and
  65 characters
- Then each answers 404 `not_found` (or the router's own 404), no file
  is opened while answering (the test patches `open`/`Path.read_text`
  to fail), and the body does not echo the id beyond what `/checks/{id}`
  already does

**Y8: flow-style lists** `should`
- Given a check file `checks/flow.yml` with
  `checks: [row_count > 0, "duplicate_count(id) = 0"]` on line 3
- Then both checks' `/source` is line 3 alone

**Y9: Windows line endings** `should`
- Given `customers.yml` saved with CRLF line endings
- Then Y1's lines and text are unchanged (no `\r` in `text`)

### Security and exposure (tech lead; security-reviewer judges)

**X1: methods** `must`
- `POST`, `PUT` and `DELETE` on both new paths answer 405 with the
  envelope, as the existing endpoints do.

**X2: OpenAPI** `must`
- `docs/api/openapi.json` declares both operations (`get_check_sql`,
  `get_check_source`) with 404, 405 and 500, `loaded_at` as
  `date-time`, `kind` as a discriminator; the generated frontend types
  are fresh (the CI drift check passes).

**X3: the network warning says what is now served** `must`
- When `tablewatch serve --host 0.0.0.0` starts
- Then the stderr warning names, among what anyone who can reach the
  address can read, **the compiled SQL and the check files' text**, as
  well as data values and owner emails. The README quotes the new text.

### The page (ui-engineer, vitest; data-steward by hand)

API responses in vitest are fixtures typed against the generated types.
The data-steward runs P1–P7 by hand against a real `serve` on
`recorded`, `edited-pending` and `remote`.

**P1: the SQL section** `must`
- Given `/checks/b1ceb8262d8b5441` on `recorded`
- Then a section headed "SQL" shows the dialect (`duckdb`), the scan's
  full text in a monospace block that preserves whitespace, and names
  this check's columns: `m0` `count(*)` and `m1` `sum(CASE WHEN …)`
- And it says the scan reads `sales.customers` once for 4 measures,
  from all its checks. It does not say this is the query that produced
  the latest result (see D5)

**P2: a schema check** `must`
- Given `/checks/fbc3aa0b93b66eee`
- Then the SQL section says the check reads the column list of
  `sales.orders` and no rows, and shows no SQL block

**P3: cannot compile** `must`
- Given `remote`, the page for the `events` check
- Then the SQL section shows "Cannot compile" with S6's `error` text, the
  Source section and every other section render normally, and no
  page-level error banner appears

**P4: the Source section** `must`
- Given `/checks/32867fbe86f483f3`
- Then a section headed "Source" shows `checks/sales/orders.yml`, lines
  5–8 with their line numbers in a gutter that is not part of the text
  (selecting the code does not select the numbers), and the YAML
  verbatim
- And it says the text is as loaded, with the time from `loaded_at`, in
  the same words the header uses for `loaded_at`

**P5: the source is today's, the result may not be** `must`
- Given `edited-pending` (`id: customer-email-completeness`; the file
  now says `< 25%`, the latest result says `expected < 15%`)
- Then the Source section shows `missing_percent(email) < 25%` and its
  "as loaded" time, and nothing on the page suggests the latest result
  was judged by this text. (The Rule section and the chart's change
  marker already say so; the SQL and Source sections must not undo it.)

**P6: a check that is no longer loaded** `must`
- Given a check id with history in the store but not in the loaded
  project (spec 004 D15)
- Then both sections say the SQL and source are not available because
  the check is not in the loaded project, and no request error is shown

**P7: one failure stays in its section** `must`
- Given `/sql` answers 500 (or the request fails) while every other
  request succeeds
- Then only the SQL section shows the failure; Refresh retries it; the
  rest of the page is unaffected. The same for `/source`

**P8: text is text** `must`
- Given a check whose `condition:` is
  `amount < 0 /* <img src=x onerror=alert(1)> */` and whose comment
  contains `<script>alert(1)</script>`
- Then both appear literally in the SQL and Source blocks, and no
  element other than the page's own is created (no raw HTML sinks; the
  spec 003 source rules cover the new components)

**P9: copy** `should`
- Each SQL statement and the source block have a "Copy" button that
  copies exactly the `sql` (with a trailing `;`) or `text`. Where the
  clipboard API is unavailable (a non-loopback `http://` origin is not a
  secure context), the button is not shown and the block stays
  selectable.

**P10: how the value is computed** `should`
- On a percent check, the SQL section says the database returns the
  counts and tablewatch computes the percentage from them; on
  `freshness`, that the database returns the newest value and
  tablewatch computes the age at the time of the run (rule 2, principle
  3). The data-steward words these; they are keyed on the metric's
  unit, not on metric names.

**P11: links to the sections** `should`
- `/checks/<id>#sql` and `/checks/<id>#source` scroll to the sections.
  The route parser is unchanged (the fragment never reaches the server).

**P12: long lines** `should` (checked by hand)
- The scan for `sales.orders` (one long line) scrolls inside its block
  at a 360 px wide viewport; the page does not scroll sideways.

## Non-goals

- **No per-selection SQL.** The scan shown is the one a whole-dataset
  run issues. `tablewatch run --check <id>` issues a narrower one; the
  page does not model selectors.
- **Not "the query that produced this result".** Results do not record
  their SQL, and the check may have changed since (P5). SQL and source
  describe the check as loaded.
- **No pretty-printing or syntax highlighting.** No SQL formatter, no
  highlighter dependency. SQLAlchemy's rendering is shown as `compile`
  prints it; wrapping and highlighting can come later if asked.
- **No inherited settings in the source.** `_defaults.yml`, the file's
  `dataset:`, `datasource:`, `filter:` and file-level `tags:` are not
  shown in the Source section. Owner, tags and dataset are already in the
  identity panel; the dataset `filter:` appears in the SQL's `WHERE`.
- **No editing, no "open in editor" links, no repository links.** The
  page is read-only; a repository URL is configuration we don't have.
- **No failed-row samples or failed-row queries** (C7, Phase 2b).
- **No change to `tablewatch compile`'s output, flags or exit codes**
  (C1). The owner's exit-code decisions of 2026-09-27 (I-16, I-17) are
  not touched here.
- **No change to the results store, check identity, `/checks` or
  `CheckDetail`.**
- **No `list --output json` refactor.** Iteration 4's requirement (d)
  applies only if this touches the `Check`→dict mapping; the new models
  do not, so it stays with whichever item next touches either.
- **I-27 does not ride along** (D8).

## Design notes

### Constraints from CLAUDE.md

- **Rule 1.** Unchanged: the endpoint shows the planner's own plan. It
  must never build a second, per-check statement to display, because that
  would show a query no run sends.
- **Rule 2.** SQL counts and Python does the math; the page says so
  (P10) rather than pretending the SQL returns the percentage.
- **Rule 3.** The SQL is in the datasource's own dialect, the same text
  `compile` prints; S7 checks DuckDB and SQLite.
- **Rule 5.** Nothing here reads check files beyond what the loader
  already does. The span and text are captured by the loader in the same
  pass; a problem capturing them must never become a new diagnostic or an
  exception (it would be the tool's fault, not the user's).
- **Rule 6.** Compiling uses `dialect_for`, never `create_engine_for`
  (S5). `validate`, `list` and `compile` stay credential-free.
- **Rule 7.** One dataset that cannot compile affects only its own
  checks (S6, P3).
- **`server/` holds no SQL** (the module table). Planning and rendering
  live outside `server/`; the route only serialises (C2).
- **Public API.** The new `Check` attributes (the span, and however the
  text is held) are provisional, as `expectation` is.

### Decisions (PM, open to REFINE)

1. **D1, the SQL shown:** the dataset's whole single scan with this
   check's columns named, plus this check's own queries and a note for a
   schema lookup (the lean recorded when I-26 was split). Other checks'
   own queries on the dataset are not listed; `shared_by` says how much
   the scan is shared. Reason: Dana needs the statement she can paste;
   Priya needs to see it is one shared scan, not one per check.
2. **D2, the span:** as defined under `CheckSource`. A comment block
   directly above a check describes it; a comment after the last line
   usually introduces the next. Data-steward to confirm in REFINE.
3. **D3, as loaded:** the text is captured at load time, not read per
   request. It agrees with `rule` and `expression` (both "as loaded"),
   survives the file changing or vanishing (Y5), and no request path
   leads to a file read (Y7).
4. **D4, two endpoints, not fields on `CheckDetail`:** a compile error
   must not break the detail response, the page loads them in their own
   slots of the shared hook (P7), and `/checks/{id}` stays cheap. So no
   third `*Detail` model is added and iteration 4's requirement (c) is
   not triggered. If REFINE moves them onto `CheckDetail`, (c) applies:
   extract the validate-twice helper instead of copying it.
5. **D5, wording:** the SQL section says what a run of the dataset sends,
   never "the query behind this result".
6. **D6, compile per request** (cheap; no cache) unless the architect
   prefers once at startup. Today no metric renders `now` into SQL (the
   PM checked `metrics/`: freshness computes the age in Python), so both
   give the same text. A future metric that does would make per-request
   the honest choice.
7. **D7, the page:** both sections go below the history table, SQL
   first. Sam's flow (rule → latest → chart → table) is unchanged, and
   Dana scrolls. Whether SQL starts collapsed (`<details>`) is the
   ui-engineer's call in REFINE; no JS disclosure widget either way.
8. **D8, I-27 stays separate.** I-26 is already at the top of S: a
   shared compile path, a loader change, two endpoints with a security
   review, and the `CheckPage.tsx` split. I-27 is chart-label layout,
   exactly where iteration 4's four blocking findings were. Folding it in
   would make this PR M and widen the review. I-27 follows I-24.

### Carried requirements (BACKLOG, I-26)

| Requirement | Where it is met |
| --- | --- |
| Security review: new endpoints change what the server exposes | Reviewers; X1–X3, Y6, Y7, S6 |
| Compiling stays credential-free (`dialect_for`, never `create_engine_for`) | S5 |
| No endpoint returns row data | S5 (no connection is possible), D3 (no data read) |
| Source: only the check's own lines, from a file under `checks/`; never `tablewatch.yml`; no path from the request | Y1–Y7, D3 |
| Whole scan with this check's measures pointed out, or only its measures | D1 (whole scan) |
| (a) Re-review of `message` and `display_value` as exposed data | Security brief below; X3 |
| (b) `CheckPage.tsx` split into section components under `frontend/src/components/` | ui-engineer in BUILD; architect in VERIFY |
| (c) A third `*Detail` model means one helper | D4 (not triggered unless REFINE changes D4) |
| (d) `list --output json` shares the API's mapping, if touched | Non-goals (not touched) |
| (e) Time-axis fixtures spaced by hours or days | Fixtures (none on a time axis) |

### Open questions for the architect (REFINE)

1. **Q1: where the shared compile path lives** (`engine/planner.py`, a
   new `engine/compiled.py`, or `api.py` next to `execute`), and its
   shape: one function per dataset returning statements plus each
   check's wiring as labels, which `compile` prints and the route
   serialises.
2. **Q2: how the loader keeps the text.** Per-check `(start, end)` on
   `Check` plus the file's lines held once per `Dataset`, or the check's
   own text on `Check`. Memory is small either way; the PM prefers the
   file's lines held once, so the span rule (D2) runs on lines, not on
   ruamel's comment attachment.
3. **Q3:** D4 (two endpoints) and D6 (per request).

### Brief for the security-reviewer

Beyond the scenarios, the review decides and writes down:

1. **The data-exposure re-review (iteration 4, (a)).** `message` and
   `display_value` already quote aggregates of data: `min(price)` is
   one row's value, freshness quotes the newest timestamp, `sql_metric`
   returns whatever its query computes. The PM's position: aggregates are
   the product's output, are already printed by the console and stored,
   and are not "row data" in principle 4's sense. The review confirms or
   rejects that, and states what changes for a non-loopback bind (X3).
2. **Driver error text in `error` results.** A database error can quote
   a row's value (a failed cast names the offending string). That text
   is stored and served today. Is it acceptable until Phase 4, a README
   note, or a backlog item to scrub?
3. **Symlinked check files.** The loader walks `checks/` with `rglob`. A
   check file that is a symlink to a file elsewhere is loaded today; the
   Source section now serves its lines verbatim, comments included.
   Acceptable, or should the loader refuse files that resolve outside
   the project?
4. **Invisible and bidirectional characters** in served YAML and SQL
   (the "Trojan Source" class). Show as is, or mark them on the page?
   The PM's default is to show as is and note it; the reviewer may make
   it a `should`.
5. **Size.** A `sql_metric` `query:` can be long. The PM sees no need for
   a cap on a locally loaded file; the reviewer may set one.

### Traps for the data-steward in REFINE

- The scan is not necessarily what ran: a selective run sends less, and
  the check may have been edited since its latest result (P5, D5).
- `m0` shared by several checks: the page must not read as if this check
  alone costs the whole scan, nor as if it is free.
- Percent and freshness: the SQL returns counts and a newest value, not
  the number on the page (P10). Check the words.
- The comment rule (D2) on real files: a comment block that describes
  the whole list, placed above the first check, will be shown as that
  check's. Acceptable?
- Freshness and time zones remain I-24's; nothing here formats times
  except the "as loaded" label, which reuses the header's words.

## Reviewers required

- **qa-engineer**: always. Focus: the span rule on awkward YAML
  (comments, blank lines inside an options map, flow style, block
  scalars in `query:`, CRLF, a file whose last line has no newline, tabs
  where YAML allows them); ids shaped like paths (Y7); a dataset that
  cannot compile next to one that can (S6); `compile` unchanged (C1);
  late answers for the two new slots during Refresh (P7).
- **data-steward**: always. D2's comment rule, the wording (P1, P2, P5,
  P10), the hand run, and the README.
- **security-reviewer**: **required.** Two new endpoints change what the
  server exposes over the network, and the `--host` warning changes.
  The brief above, plus iteration 4's data-exposure re-review.
- **architect**: **required** in REFINE (a new public API; Q1–Q3) and in
  VERIFY (`config/loader.py`, `checks/model.py`, `cli/main.py`,
  `server/`, and the `CheckPage.tsx` split).
- **ui-engineer**: builder of `frontend/**`, `docs/UI_SPECIFICATION.md`
  and the bundle; consulted in REFINE on D7 and P9–P12. Does not judge
  its own work.

## Size

**S**, at the top of it. Python: extracting the compile path (with the
golden test), the span and text capture in the loader, two small routes
and their models. Frontend: the mechanical split of `CheckPage.tsx` and
two sections that render text. No chart work, no migration, no
dependency.

**Pre-planned split, if BUILD runs long.** The Source half (Y*, P4, P5,
the loader change) moves to its own S that ships next; this PR ships the
compile path, `/sql`, the SQL section and the component split. SQL goes
first because it is the part only a terminal gives today.
