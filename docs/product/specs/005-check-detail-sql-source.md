# Spec 005: Check detail 2 (the compiled SQL)

| | |
| --- | --- |
| Backlog item | I-26 (the second half of I-05, split in iteration 4 PLAN). Its Source half moved to I-29 ([spec 006](006-check-detail-source.md)) in iteration 5 REFINE |
| Features | C4 (check detail): the SQL part. C4 is complete when I-29 ships |
| Phase | 2 (`0.2.0`) |
| Size | S (after the split; see "Size") |
| Depends on | I-05 ✓ (spec 004: the check page, `CheckDetail`, the shared load hook) |
| Unblocks | I-29 (spec 006: reuses this spec's section split, `CodeBlock`, `CopyButton`, clipboard and invisible-character handling) |
| Branch | `iter/005-check-detail-sql-source` (name kept from PLAN) |
| Status | **ready** (iteration 5 REFINE settled, 2026-09-27) |

## REFINE outcome in brief (PM, 2026-09-27)

The architect, security-reviewer, ui-engineer and data-steward reported.
Every finding is folded in below; the decision on each is in "REFINE
decisions". The spec had grown past S (security fixes in `datasources/`,
a D2 span rule that needs block-scalar extents from the parse, a new
`filter` field, invisible-character marking, a clipboard fallback, and
45 scenarios), so **the pre-planned split was applied**: this spec ships
the shared compile path, `/sql`, the SQL section and the `CheckPage`
split. The Source half, with all its REFINE decisions, is
[spec 006](006-check-detail-source.md) (I-29), a draft that the next PLAN
makes ready.

## Problem and persona

**Dana, data engineer.** "Sam sends me the check page and asks why
`missing_percent(email)` says 20%. I open a terminal, find the file,
run `tablewatch compile checks/sales/customers.yml`, scroll to the right
dataset, and work out which of the `m0`…`m3` columns this check uses.
Then I paste the SQL into the warehouse console to look at the rows.
The page already has everything else. It should have the query."

**Priya, platform.** "Someone asks why their check costs a scan of a
billion-row table. I want to see that it rides the dataset's one scan,
and what else rides it, without reading the planner."

**Sam, data steward**, reads the SQL section's sentences, not the SQL:
which table is read, that the database returns counts and tablewatch
does the percentage, and that the statement describes the check files as
loaded, not the run behind the latest result. (Sam's own ask, the YAML
source, is spec 006.)

**How they cope today.** `tablewatch compile` prints every statement
for the selected datasets, but not which columns belong to which check,
and it needs a checkout and a shell. Principle 3 ("every number is
explainable") is met on the command line only.

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
  We borrow compiled code next to source (source in spec 006). We do not
  borrow tabs: both blocks are short and both are wanted at once.
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

On `/checks/<id>`, below the history, a new **SQL** section: the
statement(s) a run of this check's dataset sends that this check's value
comes from, in the datasource's dialect, exactly as `tablewatch compile`
prints them. For the single scan, the whole `SELECT` is shown and this
check's columns (`m0`, `m1`, …) are named with their expressions. A
`schema` check says it reads the column list, not rows. If the dataset
cannot be compiled (an unknown dialect, an unresolved datasource), the
section says so and the rest of the page is unaffected.

One read-only endpoint serves it: `GET /api/v1/checks/{id}/sql`. It
never connects to a datasource, resolves an `${env:}` reference, reads
the results store, or reads a file at request time. `tablewatch compile`
and the endpoint share one compile path. `compile`'s output does not
change, with one security fix: a datasource URL that is not
`scheme://…` is no longer echoed (R1).

## Scope at a glance

| Part | Who builds it | Where |
| --- | --- | --- |
| One compile path shared by `tablewatch compile` and the API (C1, C2, S7) | tech lead | new `src/tablewatch/engine/compiled.py` (architect Q1) |
| `dialect_for` stops echoing a malformed URL (R1) | tech lead | `datasources/__init__.py` |
| One endpoint, wire models, OpenAPI regenerated | tech lead | `server/routes.py`, `server/schemas.py`, `docs/api/openapi.json` |
| The `--host` warning and help name the SQL (X3) | tech lead | `cli/main.py` |
| `CheckPage.tsx` split into section components (its own no-behaviour-change commit); the SQL section; `CodeBlock`, `CopyButton`, `lib/clipboard.ts` | ui-engineer | `frontend/**`, `docs/UI_SPECIFICATION.md`, the bundle |
| README: "Reading a check's page" gains the SQL section; the `--host` warning text | data-steward | `README.md` |

**Order inside BUILD.** C1 and I1 golden files captured on `main` first,
then R1 with its canaries (`retail` has no malformed URL, so the
golden file does not change), then the shared
compile path, then the endpoint and `openapi.json`, then types are
regenerated (spec 003's K3 enforces the chain), then the `CheckPage`
split commit, then the SQL section.

## The contract change (additive)

One new operation under `/api/v1`. Nothing existing changes; `v1`
stays. It answers `404 not_found` (the existing envelope) for an id
that is malformed or not in the loaded project, and carries the same
security and `no-store` headers as every API response.

### `GET /api/v1/checks/{id}/sql` → `CheckSql`

```text
CheckSql   { check_id: string, dataset: string, datasource: string,
             dialect: string | null,          # the SQL dialect's name: "duckdb", "sqlite", "postgresql"
             statements: Statement[],         # in the order a run issues them; only those this check uses
             schema_lookup: boolean,          # this check reads the table's column list
             error: string | null }           # set when the dataset cannot be compiled; statements is []
Statement  = { kind: "scan",  sql: string, measures: int, uses: ScanColumn[], shared_by: int }
           | { kind: "query", sql: string, shared_by: int }
ScanColumn { label: string, sql: string, shared_by: int }   # label "m0", "m1", … as in the scan
```

- `dialect` is the SQL dialect's name (architect A5), not a promise that
  it is a SQLAlchemy dialect: Spark (B8) and files (I-08) may name theirs
  differently.
- **`Statement` is an open union on `kind`** (architect A4). C7
  (failed-row queries, Phase 2b) will add a kind. Clients ignore a
  statement whose `kind` they do not know; the page does (P15). Adding a
  kind is an additive change within `v1`.
- `sql` is the statement as `tablewatch compile` prints it, **without**
  the trailing `;`: values inlined (`literal_binds`) for reading. A run
  sends the same statement with bound parameters. (The page shows and
  copies it with `;`, P1/P9.)
- The scan is the one a run of the **whole dataset** issues (every
  loaded check on it). A run narrowed by selectors issues a smaller
  scan; see non-goals.
- `measures` is the number of columns in the scan. `shared_by` is the
  number of **other** loaded checks on the dataset that use that
  statement or column (`should`, S4).
- **Which combinations occur** (ui-engineer gap c). A `schema` check has
  `statements: []` and `schema_lookup: true`. No built-in metric mixes a
  schema lookup with statements, but the contract allows it and the page
  renders the statements, then the schema sentence. `statements: []`,
  `schema_lookup: false`, `error: null` does not occur with today's
  metrics; the page renders "This check sends no statement of its own."
  if it ever does.
- `error` is the message `tablewatch compile` prints after `-- cannot
  compile:`, or the fixed message of A1. It is built only from
  `DatasourceError`'s fixed-format messages and never contains a URL
  beyond a validated scheme, a user name, a host or a password (R1, R2).
- Every field of `CheckSql`, `Statement` and `ScanColumn` is `required`
  in `openapi.json` (nullable where shown), and `kind` is a literal per
  variant (ui-engineer gap b).

## Acceptance scenarios

**Fixtures** (`tests/conftest.py`; specs 002–004):

- `retail`: a copy of `examples/retail` with its database built.
- `recorded`, `edited-pending`: as spec 004.
- **`filtered`** (new): `retail` plus `checks/sales/returns.yml`, the
  file in spec 006's Y10 (a `filter:`, a `where:`, comments, and a
  top-level `owner:` after `checks:`). `sales.returns` is not in the
  database; nothing here connects. `tablewatch validate` on it: `4
  datasets, 21 checks — no problems found` (PM, REFINE, on a copy).
- **`broken`** (new, architect A1): `retail` plus
  `checks/sales/lost.yml`:

  ```yaml
  dataset: sales.lost
  datasource: nowhere
  checks:
    - row_count > 0
  ```

  `tablewatch validate` exits 3 with
  `checks/sales/lost.yml:2:13: error: unknown datasource 'nowhere' (defined in tablewatch.yml: lake)`.
  `serve` loads it anyway (the page's broken-project banner, spec 003);
  the check's id is `8e3148f570b166f3` and its dataset's datasource is
  `""` (PM, REFINE, with `tablewatch.load()`).
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
    bare:
      type: sqlalchemy
      url: "dana:hunter2@acct/db"
    colon:
      type: sqlalchemy
      url: "snowflake:dana:hunter2@acct"
    query:
      type: sqlalchemy
      url: "snowflake://acct/db?password=hunter2"
  results:
    url: sqlite:///.tablewatch/results.db
  ```

  with `checks/_defaults.yml` holding `owner: ops@example.com` under a
  comment line `# canary-tw-5f3a`, and check files:

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

  and `checks/wh/bare.yml`, `checks/wh/colon.yml`, `checks/wh/query.yml`,
  each the same as `events.yml` with `dataset:` and `datasource:` set to
  `bare`, `colon` and `query`. `TW_TEST_PG_PASSWORD` is unset. The
  snowflake dialect is not installed.

No fixture here draws anything on a time axis (iteration 4, requirement
(e)); none is needed, since `/sql` never reads the store.

Check ids (confirmed by the PM on 2026-09-27 against `main` with
`tablewatch.load()` and the planner on `examples/retail`; re-confirmed
by the data-steward in REFINE):

| id | dataset | expression | scan columns used |
| --- | --- | --- | --- |
| `b1ceb8262d8b5441` | sales.customers | `missing_percent(email) < 5%` | `m0`, `m1` |
| `32c8f939b90f6367` | sales.customers | `row_count > 0` | `m0` |
| `af0289a72fedd946` | sales.customers | `duplicate_count(customer_id) = 0` | none (own query) |
| `32867fbe86f483f3` | sales.orders | `row_count \| warn when < 100 \| fail when = 0` ("Order volume") | `m0` |
| `a81b0374b0b04f06` | sales.orders | `freshness(created_at) < 6h` | `m4` |
| `ed669ca6e5532a59` | sales.orders | `failed_rows` ("No negative amounts") | `m5` |
| `fbc3aa0b93b66eee` | sales.orders | `schema` | none (schema lookup) |
| `4a831091035ca6c6` | sales.returns (`filtered`) | `avg(amount) between 1 and 500` (`where:`) | `m2` |

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
- **Carve-out (R1):** the one change to `compile`'s output is the
  message for a datasource URL that is not `scheme://…` (C3). `retail`
  has none, so the golden file is unaffected.

**C2: one path** `must` (architect confirms in VERIFY)
- `tablewatch compile` and `GET /checks/{id}/sql` both call
  `engine.compiled.compile_dataset`. Neither `cli/` nor `server/` calls
  `plan_dataset` or `render` itself, and `server/` contains no SQL text.
  `compile` keeps its own printing.

**C3: a malformed URL is never echoed** `must` (security R1)
- Given `remote`
- When `tablewatch compile checks/wh` runs, and `/sql` is requested for
  the `row_count > 0` check on each of `events`, `bare`, `colon` and
  `query`
- Then for `bare` and `colon` the message is exactly
  `the url is not a SQLAlchemy URL (expected scheme://...)`: in `compile`
  as `-- cannot compile: the url is not a SQLAlchemy URL (expected scheme://...)`,
  in `/sql` as `error`
- And for `events` and `query` the message starts
  `unsupported SQLAlchemy URL scheme 'snowflake'`
- And neither `compile`'s stdout and stderr nor any `/sql` body contains
  `hunter2`, `dana` or `acct`
- The rule: the scheme is echoed only if it matches
  `^[A-Za-z][A-Za-z0-9+.\-]*$` **and** was followed by `://`; otherwise
  the fixed message. `compile`'s exit code is unchanged (0).

**I1: identity does not move** `must`
- Given `retail`, and `tablewatch list` output captured on `main` before
  BUILD (committed next to C1's golden file)
- When `tablewatch list` runs on the branch
- Then stdout is byte-for-byte the golden file, and the exit code is 0

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
- And each `uses[].sql` is taken from the measure's expression, never
  from the planner's internal `agg:` key (architect)

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
- And for `b1ceb8262d8b5441` (S1), the scan's `shared_by` is 3, `m0`'s is
  1 (`row_count > 0`) and `m1`'s is 0
- `uses` and `shared_by` are computed in `engine/compiled.py`
  (`CompiledDataset.for_check`), not in `server/`, so I-10's static
  report can reuse them (architect)

**S10: a check that uses the scan and its own query** `should`
- Given `retail` with `  - duplicate_percent(email) < 1%` appended to
  `checks/sales/customers.yml` (line 13)
- When `/sql` is requested for that check
- Then `statements` is, in run order, the `scan` (`measures` 4, `uses`
  `[{label: "m0", sql: "count(*)"}]`) and then one `query` whose `sql`
  groups by `email` (`… WHERE email IS NOT NULL GROUP BY email …`)
- And the query for `duplicate_count(customer_id)` is not listed (D1)

**S11: `filter:` and `where:` are visible in the SQL** `must`
- Given `filtered`
- When `/sql` for `4a831091035ca6c6` (`avg(amount) between 1 and 500`,
  `where: reason != 'damaged'`, in a file with `filter: status != 'test'`)
- Then the scan's `measures` is 3, its `sql` ends
  `FROM sales.returns \nWHERE (status != 'test')`, and `uses` is
  `[{label: "m2", sql: "avg(CASE WHEN (reason != 'damaged') THEN amount END)"}]`
  (PM, REFINE: matches `tablewatch compile checks/sales/returns.yml` on
  a copy)

**S5: credential-free** `must` (rule 6; security R2)
- Given `remote` served, `TW_TEST_PG_PASSWORD` unset, and both
  `create_engine_for` and `resolve_env` patched to fail the test if
  called
- When `GET /api/v1/checks/<id of row_count > 0 on public.orders>/sql`
- Then 200 within 2 seconds, `dialect` `"postgresql"`, one scan whose
  `sql` renders `FROM public.orders`, `error` null
- And no connection was attempted and no `${env:}` reference was
  resolved
- And the body contains none of `192.0.2.1`, `tw_reader`, `analytics`,
  `TW_TEST_PG_PASSWORD`: `CheckSql` serialises no datasource field but
  its name and dialect name

**S6: cannot compile, and nothing secret leaks** `must`
- Given `remote` served
- When `GET /api/v1/checks/<id of row_count > 0 on events>/sql`
- Then 200, `statements` `[]`, `dialect` null, and `error` starts with
  `unsupported SQLAlchemy URL scheme 'snowflake'`
- And the response body contains none of `hunter2`, `dana`, `acct`
- And `GET /api/v1/checks/<pg check id>/sql` is unaffected (200, SQL
  present): one dataset that cannot compile affects only its own checks
- And no `/sql` body on `remote` contains `canary-tw-5f3a` or
  `ops@example.com`

**S12: an unresolved datasource on a served broken project** `must`
(architect A1)
- Given `broken` served
- When `GET /api/v1/checks/8e3148f570b166f3/sql`
- Then 200, `datasource` `""`, `dialect` null, `statements` `[]`, and
  `error` exactly
  `this dataset's datasource is not defined; run tablewatch validate`
- And `/sql` for `b1ceb8262d8b5441` on the same server is S1's answer
- `compile_dataset` wraps the datasource lookup, `timezone_of`,
  `dialect_for`, `plan_dataset` and rendering, and turns each known
  failure (a missing datasource, `DatasourceError`) into `error`

**S13: anything unexpected is a plain 500** `must` (security R4)
- Given `retail` served, and rendering patched to raise
  `sqlalchemy.exc.CompileError("secret-canary-7c1e")`
- When `/sql` for `b1ceb8262d8b5441`
- Then 500 with the `internal_error` envelope and message
  `internal error — see the server log`; the body does not contain
  `secret-canary-7c1e`
- And `/checks/b1ceb8262d8b5441` still answers 200
- R4 is the backstop for what A1 does not anticipate: known failures are
  `error` (S6, S12), anything else is this 500. Neither path puts
  exception text in the body

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
- When `/sql` is requested for `b1ceb8262d8b5441`
- Then it answers 200 (while `/checks` answers 503 as today)

### Security and exposure (tech lead; security-reviewer judges)

**X1: methods** `must`
- `POST`, `PUT` and `DELETE` on `/api/v1/checks/{id}/sql` answer 405
  with the envelope, as the existing endpoints do.

**X2: OpenAPI** `must`
- `docs/api/openapi.json` declares `get_check_sql` with 404, 405 and
  500; every `CheckSql`, `Statement` and `ScanColumn` field `required`;
  `kind` a literal per variant and the discriminator; the description of
  `Statement` says clients ignore unknown kinds (A4). The generated
  frontend types are fresh (the CI drift check passes).

**X3: the network warning names the SQL** `must` (security R3, interim)
- When `tablewatch serve --host 0.0.0.0` starts
- Then stderr carries exactly:
  `tablewatch: warning: serving on 0.0.0.0 with no authentication — anyone who can reach this address can read this project's checks, the SQL each check runs, and its results: data values, database error messages that can quote row values, and owner emails. Authentication arrives in Phase 4 (tablewatch.yml cannot turn it on yet).`
- And `--host`'s help says "serves checks, SQL and results without
  authentication"; the README quotes the warning verbatim
- This is R3's sentence with "check files (comments included)" read as
  "checks", because check files are not served until spec 006, whose X3
  puts R3's exact sentence in. The security-reviewer confirms the
  interim wording in VERIFY.

**X4: nothing about a datasource is logged** `must` (security R2)
- Given `remote` served with logging at debug
- When `/sql` is requested for every loaded check, including S13's
  forced failure
- Then stderr contains none of `hunter2`, `dana`, `acct`, `192.0.2.1`,
  `tw_reader`

### The page (ui-engineer, vitest; data-steward by hand)

API responses in vitest are fixtures typed against the generated types.
The data-steward runs P1–P7 by hand against a real `serve` on
`recorded`, `edited-pending`, `remote`, `filtered` and `broken`.

**Layout (ui-engineer, REFINE).** The SQL section sits below the history
table and renders **open**: no `<details>`, no disclosure widget (a
collapsed section breaks the `#sql` link, find-in-page, and the jsdom
tests). `CheckPage.tsx` is first split into
`frontend/src/components/check/` (`Identity`, `RuleSection`,
`LatestSection`, `NotFoundPanel`, `HistorySection`) plus a
`useOlderHistory` hook, **as its own commit with no behaviour change and
the existing tests untouched**; then `SqlSection`, `CodeBlock`,
`CopyButton` and `lib/clipboard.ts` are added. No highlighter, no new
dependency. Colours from `--tw-surface`, `--tw-border`, `--tw-text`,
`--tw-text-muted`; `contrast.test.ts` gains muted-on-surface.

**P1: the SQL section** `must`
- Given `/checks/b1ceb8262d8b5441` on `recorded`
- Then a section headed "SQL" shows the dialect (`duckdb`), the scan's
  full text followed by `;` in a monospace block that preserves
  whitespace, and names this check's columns: `m0` `count(*)` and `m1`
  `sum(CASE WHEN …)`
- Words (data-steward, REFINE; the ui-engineer may shorten, not change
  the meaning). Above the block:

  > When tablewatch checks `sales.customers` on `lake` (duckdb), it reads
  > the table once with this statement. That one read computes 4 values,
  > for this check and 3 others. This check uses:
  >
  > `m0` `count(*)`, also used by 1 other check
  > `m1` `sum(CASE WHEN (email IS NULL OR email IN ('', 'N/A')) THEN 1 ELSE 0 END)`

  Below the block:

  > Built from the check files as loaded, for a run of every check on
  > `sales.customers`. Results do not store their SQL; a result recorded
  > before these files were loaded may have used different SQL.

  "3 others" is the scan's `shared_by`; "also used by 1 other check" is
  the column's `shared_by`, shown only when it is above 0 (ui-engineer
  gap d: both count *other* checks, consistent with S4). Counts are
  pluralised ("1 value", "1 other check"); for a scan `shared_by` of 0
  the line reads "for this check only". The page says "values", not
  "measures".
- For a `query` statement: "This check sends its own statement to
  `sales.customers`." plus, when `shared_by` > 0, "N other checks use the
  same statement."
- **Wording guard** (vitest, `must`): the text of the SQL section, on
  every fixture, matches none of `/\bproduced\b/i`, `/\blatest\b/i`,
  `/\bthis result\b/i`, `/\bran\b/i`, `/\bexecuted\b/i`. Spec 006 extends
  the guard to the Source section.

**P2: a schema check** `must`
- Given `/checks/fbc3aa0b93b66eee`
- Then no SQL block, and the words: "This check reads the list of
  columns in `sales.orders` and their types from the database. It reads
  no rows, so it has no SQL."

**P3: cannot compile** `must`
- Given `remote`, the page for the `events` check, and `broken`, the
  page for `8e3148f570b166f3`
- Then the SQL section shows "Cannot compile" with the `error` text in a
  wrapping monospace block (it may be several lines; ui-engineer gap j),
  every other section renders normally, and no page-level error banner
  appears beyond the broken-project banner `broken` already shows

**P5: the SQL does not claim the latest result** `must`
- Given `edited-pending` (`id: customer-email-completeness`; the file
  now says `< 25%`, the latest result says `expected < 15%`)
- Then the SQL section's words pass the wording guard (P1) and say "as
  loaded"; nothing in the section suggests the latest result was
  computed by this statement

**P6: a check that is no longer loaded** `must` (ui-engineer gap g)
- Given a check id with history in the store but not in the loaded
  project (spec 004 D15): `/checks/{id}` and `/sql` answer 404,
  `/history` answers 200
- Then the SQL section is one line: "SQL is not available: this check is
  not in the loaded check files." and no request error is shown
- When `/checks/{id}` and `/history` both answer 404, the page is the
  existing not-found panel and the SQL section is absent

**P7: one failure stays in its section** `must`
- Given `/sql` answers 500 (or the request fails) while every other
  request succeeds
- Then only the SQL section shows the failure, worded for a section
  ("The SQL could not be loaded."; `LoadError` gains a `useId()` id, a
  heading-level prop and section-scoped wording), and the rest of the
  page is unaffected
- A 404 from `/sql` means "no longer loaded" (P6) only when
  `/checks/{id}` is also 404; otherwise it is a failure shown here
- `/sql` is one more slot in the shared `useLoads` hook. Refresh reloads
  every slot, `/sql` included (ui-engineer gap h: accepted; the load is
  cheap and one Refresh meaning "reload the page's data" is simpler).
  The generation guard drops a late answer; a test covers a `/sql` answer
  arriving after a Refresh

**P8: text is text** `must`
- Given a check whose `condition:` is
  `amount < 0 /* <img src=x onerror=alert(1)> */`
- Then it appears literally in the SQL block, and no element other than
  the page's own is created (no raw HTML sinks; the spec 003 source rules
  cover the new components)

**P9: copy** `should`
- Each SQL statement has a button, accessible name "Copy the scan" or
  "Copy the query", that copies exactly the API's `sql` plus `;` (from
  the API string, never the DOM). The block also *shows* the `;`, so a
  hand selection equals what Copy copies
- `lib/clipboard.ts` exports `canCopy()` (`isSecureContext &&
  navigator.clipboard?.writeText`) and `copyText`; it is the only module
  that touches `navigator.clipboard`. No `execCommand` fallback
- Where copying is unavailable (a non-loopback `http://` origin is not a
  secure context), a **"Select all"** button replaces Copy and selects
  the block's text (`selectAllChildren`) for the user to copy by hand
- After copying, "Copied" shows for about 2 seconds in a polite live
  region; if the clipboard rejects, "Could not copy. Select the text and
  copy it."

**P10: how the value is computed** `should`
- Keyed on the unit already on `CheckDetail` (spec 004), not on metric
  names; no contract change. Words:
  - `percent`: "The database returns counts; tablewatch computes the
    percentage from them."
  - `duration`: "The database returns a timestamp; tablewatch computes
    how long ago it was at the time of each run, so the same data looks
    older the later the run." (Reworded from "the newest value" so it
    stays true of any age metric; ui-engineer gap i.)
  - `count`, `number`: no sentence (the database returns the value
    itself).
  - `schema` has P2's sentence instead.
- When `/checks/{id}` has not answered, P10's sentence is simply absent
  (ui-engineer gap a)

**P11: link to the section** `should`
- `/checks/<id>#sql` scrolls to the section once, after the first round
  of loads settles (tested with a mocked `scrollIntoView`). The route
  parser is unchanged.

**P12: long lines** `should` (checked by hand)
- The SQL block soft-wraps (`white-space: pre-wrap; overflow-wrap:
  anywhere`), has no line numbers and no maximum height; its container
  has `min-width: 0`. At a 360 px wide viewport the scan for
  `sales.orders` (first line 309 characters) wraps or scrolls inside its
  block and **the page never scrolls sideways**. A block that scrolls is
  a focusable, labelled region (`tabIndex=0`, `role="region"`).

**P13: the store is down, the SQL is not** `should` (ui-engineer gap a; D4)
- Given the store unreadable (S9): `/checks/{id}` and `/history` answer
  503 while `/sql` answers 200
- Then the SQL section renders in full from `/sql` alone (its sentences
  need only `dataset`, `datasource`, `dialect` and the statements), P10's
  sentence is absent, and the store's failure shows only where spec 004
  already shows it

**P14: invisible characters are marked** `should` (security R5)
- Given a check whose `condition:` contains U+202E and U+200B
- Then the SQL block shows each such code point visibly marked in place
  (U+200B–200F, U+202A–202E, U+2060–2069, U+FEFF, U+00AD, and C0/C1
  controls except tab and newline), without changing the text: Copy
  copies the exact bytes, and the API returns the text verbatim
- A vitest fixture covers U+202E and U+200B

**P15: an unknown statement kind is skipped** `must` (architect A4)
- Given a fixture whose `statements` holds a `scan`, a `{kind:
  "failed_rows", sql: "…"}` and a `query`
- Then the section renders the scan and the query, and nothing for the
  unknown kind, with no error

## Non-goals

- **No Source section or `/source` endpoint.** Spec 006 (I-29).
- **No per-selection SQL.** The scan shown is the one a whole-dataset
  run issues. `tablewatch run --check <id>` issues a narrower one; the
  page does not model selectors.
- **Not "the query that produced this result".** Results do not record
  their SQL, and the check may have changed since (P5).
- **No pretty-printing or syntax highlighting.** No SQL formatter, no
  highlighter dependency.
- **No failed-row samples or failed-row queries** (C7, Phase 2b).
- **No change to `tablewatch compile`'s output, flags or exit codes**,
  except R1's message for a URL that is not `scheme://…` (C1, C3). The
  owner's exit-code decisions of 2026-09-27 (I-16, I-17) are not touched.
- **No change to the results store, check identity, `/checks` or
  `CheckDetail`.**
- **No `list --output json` refactor** (iteration 4's requirement (d)
  applies only if the `Check`→dict mapping is touched; it is not).
- **I-27 does not ride along** (D8).

## Design notes

### Constraints from CLAUDE.md

- **Rule 1.** The endpoint shows the planner's own plan. It never builds
  a second, per-check statement to display.
- **Rule 2.** SQL counts and Python does the math; the page says so
  (P10).
- **Rule 3.** The SQL is in the datasource's own dialect, the same text
  `compile` prints; S7 checks DuckDB and SQLite.
- **Rule 5.** Unaffected: nothing here reads check files.
- **Rule 6.** Compiling uses `dialect_for`, never `create_engine_for` or
  `resolve_env` (S5). `validate`, `list` and `compile` stay
  credential-free.
- **Rule 7.** One dataset that cannot compile affects only its own
  checks (S6, S12, P3). The exit codes are untouched.
- **`server/` holds no SQL.** Planning and rendering live in
  `engine/compiled.py`; the route only serialises (C2).

### The compile path (architect, REFINE Q1)

- New module `src/tablewatch/engine/compiled.py`. Not `planner.py` (it
  does not import `datasources`), not `api.py` (no public surface), not
  exported from `tablewatch/__init__`.
- Frozen dataclasses `ScanColumn(label, sql, key)`,
  `CompiledScan(sql, columns)`, `CompiledQuery(key, sql)`,
  `CompiledDataset(dataset, dialect, scan, queries, schema_lookup,
  wiring, error)` with `for_check(check_id)` computing `uses` and
  `shared_by`.
- `compile_dataset(dataset, datasources, checks=None, *, now=None) ->
  CompiledDataset`. The CLI keeps its own printing and calls it (C1, C2).
- `m<i>` labels come from a new `DatasetPlan.labels()`, which `scan()`
  also uses, so the labels cannot drift. Column `sql` comes from
  `measure.expression`, never from the `agg:` key.
- The runner keeps planning with `engine.dialect`; the `FROM` clause is
  shared through `table_clause`.
- `compile_dataset` catches known failures into `error` (A1, S12);
  anything else propagates to the server's last-resort 500 (R4, S13).

### REFINE decisions (PM, 2026-09-27)

| Finding | Decision |
| --- | --- |
| Architect Q1 (module, shape) | Adopted as written above |
| Architect Q2 (how the loader keeps text) | Moved with the Source half to spec 006, adopted there |
| Architect Q3 (two endpoints, compile per request) | Agreed; D4 and D6 stand. With the split, spec 005 adds only `/sql` |
| A1 compile problems never 500 | In: S12, and `compile_dataset` owns the wrapping |
| A2 span unavailable | Spec 006: 200 with `path` and null span/text, not 404 |
| A3 "under the project's checks directory" | Spec 006 |
| A4 open union on `kind` | In: contract note, X2, P15 |
| A5 "the SQL dialect's name" | In: contract |
| R1 malformed URL echoed (blocking-for-ready) | In: C3, with the explicit carve-out from C1 and the non-goal |
| R2 no `resolve_env`, no datasource fields, no logging of config (blocking-for-ready) | In: S5 (patched `resolve_env`), S6, X4, contract note on `error` |
| R3 warning wording (blocking-for-ready) | In: X3, with an interim "checks" in place of "check files (comments included)" until spec 006 serves them; spec 006 X3 puts R3's exact text in. Security confirms in VERIFY |
| R4 unexpected exception → generic 500 (must) | In: S13 |
| R5 invisible characters (should) | In: P14 for the SQL block; spec 006 for Source and the path |
| R6 span limits (must) | Spec 006, Y6 |
| Security note: a future `Permissions-Policy` keeps `clipboard-write=(self)` | Recorded below |
| UI 1 sections open | In: layout note; D7 updated |
| UI 2 copy, Select-all fallback, `;` | In: P9. **Select all** replaces "not shown". The API keeps `sql` without `;` (C1's contract with S7); the page shows and copies it with `;` |
| UI 3 wrap, no highlighting, tokens | In: P12 reworded ("wraps or scrolls inside itself; the page never scrolls sideways"). YAML line numbers go to spec 006 |
| UI 4 component split as its own commit | In: layout note and scope table |
| UI 5 loading, 404 rule, `LoadError`, `#sql` | In: P6, P7, P11 |
| UI gaps a–j | a: P13 (and P10 absent without `/checks/{id}`); b: X2; c: contract note; d: P1; e: spec 006 P4; f: P5 made concrete; g: P6; h: P7, accepted; i: P10, count/number show nothing, duration reworded; j: P3 |
| Data-steward `CheckSource.filter` | **Accepted**, in spec 006, as its own field (the span still excludes the `filter:` line, so R6 holds). Spec 006's security brief item 2 asks security to confirm |
| Data-steward D2 indentation rule | **Accepted**, in spec 006 (rules 1–4). The block-scalar extent comes from the parse, per the architect |
| Data-steward: spec 004's `test_rule_never_carries_options_or_sql` | Stays green (`rule` does not change). `/sql` serves option values and `where:`/`filter:` inlined on purpose; security brief item 6 |
| Security follow-ups F1, F2 | Backlog I-30, I-31 |
| Security F3 (skip symlinked check files outside the root; changes `run`) | Pending owner question in `ITERATIONS.md`; not in this spec. Spec 006 Y16 documents today's behaviour |
| Data-steward `duplicate_*` counts `''` and `'N/A'` | Backlog I-32 |

### Decisions carried from PLAN

1. **D1, the SQL shown:** the dataset's whole single scan with this
   check's columns named, plus this check's own queries and a note for a
   schema lookup. Other checks' own queries are not listed; `shared_by`
   says how much the scan is shared.
2. **D2, the span:** moved to spec 006.
3. **D3, as loaded:** moved to spec 006 for the text. For SQL, "as
   loaded" means compiled from the project loaded at startup (Y5's SQL
   half is covered by D6: nothing is re-read).
4. **D4, a separate endpoint, not a field on `CheckDetail`:** a compile
   error must not break the detail response, the page loads it in its
   own slot (P7), and `/checks/{id}` stays cheap. No third `*Detail`
   model; iteration 4's requirement (c) is not triggered.
5. **D5, wording:** what a run of the dataset sends, never "the query
   behind this result" (P1's guard).
6. **D6, compile per request**, no cache. No metric renders `now` into
   SQL today, so per request and at startup give the same text; a
   future metric that does would make per request the honest choice.
7. **D7, the page:** the SQL section goes below the history table,
   **open** (REFINE: no `<details>`). Spec 006's Source section goes
   below it.
8. **D8, I-27 stays separate.**

### Security answers recorded in REFINE

- **`display_value` and `message` (brief item 1).** `display_value`
  quotes aggregates only (confirmed). `message` can quote a single row
  value verbatim (Python-side `float(value)` in `metrics/base.py`,
  freshness `fromisoformat`: `could not convert string to float: 'N/A'`,
  `Invalid isoformat string: 'eve@example.com'`), and driver error text
  can too. Pre-existing, stored and served today; X3 now says so, and
  I-30 and I-31 follow up.
- **Driver error text (item 2).** Acceptable until Phase 4 with X3's
  warning; I-30 (stop quoting values) before Phase 4 or before any
  recommendation to serve beyond loopback; I-31 (a redaction setting).
- **Symlinks (item 3).** Spec 006; F3 is an owner question.
- **Invisible characters (item 4).** A `should`: P14 here, spec 006 for
  Source.
- **Size cap (item 5).** None needed.
- **Spec 004's line (item 6).** `/sql` serves `valid_values`,
  `missing_values` and `where:`/`filter:` SQL inlined; that is the
  feature. `test_rule_never_carries_options_or_sql` stays green.
- **Clipboard.** If a `Permissions-Policy` header is ever added, it must
  keep `clipboard-write=(self)`, or P9 stops working.

### Carried requirements (BACKLOG, I-26)

| Requirement | Where it is met |
| --- | --- |
| Security review: new endpoints change what the server exposes | Reviewers; X1–X4, C3, S5, S6, S13 |
| Compiling stays credential-free (`dialect_for`, never `create_engine_for`) | S5 (also `resolve_env`) |
| No endpoint returns row data | S5 (no connection is possible) |
| Source: only the check's own lines, from a file under `checks/`; never `tablewatch.yml`; no path from the request | Spec 006 (Y1–Y7, Y10, Y16); restated there with the `filter` field |
| Whole scan with this check's measures pointed out, or only its measures | D1 (whole scan) |
| (a) Re-review of `message` and `display_value` as exposed data | "Security answers recorded in REFINE"; X3; I-30, I-31 |
| (b) `CheckPage.tsx` split into section components under `frontend/src/components/` | Layout note; architect in VERIFY |
| (c) A third `*Detail` model means one helper | D4 (not triggered) |
| (d) `list --output json` shares the API's mapping, if touched | Non-goals (not touched) |
| (e) Time-axis fixtures spaced by hours or days | Fixtures (none on a time axis) |

## Reviewers required

- **qa-engineer**: always. Focus: `compile` unchanged (C1) and the R1
  carve-out (C3) on more malformed URLs than the canaries (`://x`,
  `1abc://x`, `sn owflake://x`, an `${env:}` scheme); a dataset that
  cannot compile next to one that can (S6, S12); S13's backstop; late
  `/sql` answers during Refresh (P7); unknown `kind` (P15).
- **data-steward**: always. The wording (P1, P2, P5, P6, P10), the hand
  run, the README.
- **security-reviewer**: **required.** A new endpoint changes what the
  server exposes over the network; the `--host` warning changes (X3,
  interim wording to confirm); R1 changes `datasources/`.
- **architect**: **required** in VERIFY: `engine/compiled.py`,
  `DatasetPlan.labels()`, `datasources/__init__.py`, `cli/main.py`,
  `server/`, and the `CheckPage.tsx` split.
- **ui-engineer**: builder of `frontend/**`, `docs/UI_SPECIFICATION.md`
  and the bundle. Does not judge its own work.

## Size

**S**, after the split. Python: extracting the compile path behind
golden tests, the R1 fix in `dialect_for`, one route and its models, the
warning text. Frontend: the mechanical `CheckPage.tsx` split (its own
commit) and one section that renders text, with a copy button. No
loader change, no chart work, no migration, no dependency.

**The split applied in REFINE.** Before it, the spec carried the Source
half too: a loader change with an indentation- and block-scalar-aware
span rule, a new `filter` field, a second endpoint, R6, and 18 more
scenarios. With the security and UI findings folded in, that was an M.
The Source half is [spec 006](006-check-detail-source.md) (I-29), which
ships next.
