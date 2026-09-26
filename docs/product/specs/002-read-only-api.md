# Spec 002: Read-only REST API and `tablewatch serve`

| | |
| --- | --- |
| Backlog item | I-02 |
| Features | C1 (read-only REST API, OpenAPI); the `serve` command from C2 (API only; the UI is I-03) |
| Phase | 2 (`0.2.0`) |
| Size | M |
| Depends on | I-01 ✓ (spec 001, `execute()` and the sink seam) |
| Unblocks | I-03 UI shell and overview, then I-05, I-04, I-15 |
| Branch | `iter/002-read-only-api` |
| Status | done (REVIEW, iteration 2) — see `ITERATIONS.md` |

## Problem and persona

**Sam, data steward.** "I own the sales tables. When someone tells me a
dashboard is wrong I want to see which checks are failing and since when.
Today I have to ask Dana to SSH into the box and run `tablewatch runs` and
`tablewatch history <id>`, and then read a table in a terminal."

**Priya, platform / SRE.** "I want to put the check results in front of
people, and later in our own portal, without giving everyone a shell on
the server that holds the warehouse credentials. And I won't run anything
that listens on all interfaces with no login."

**Dana, data engineer**, is the one Sam and Priya ask. She copes with
`tablewatch runs`, `tablewatch history`, `tablewatch list --output json`,
and by querying `tablewatch_runs` and `tablewatch_check_results` with
SQL. Those tables are internal. The CLI lists history for a single check
and cannot answer "what is failing right now across the project".

This increment helps nobody on its own screen, because it has no screen.
It is the contract that the UI (I-03 onwards) and any portal integration
are built against, so its value is that it holds steady. What goes into it
has to be decided carefully, and anything left out can be added later.

### How others do it

- **dbt `docs serve`** listened on all interfaces until CVE-2024-36105.
  Since dbt-core 1.6.15, 1.7.15 and 1.8.1 it binds `127.0.0.1` by default,
  and `--host` is the opt-in. That default broke some deployments, and the
  owner's decision (BACKLOG, I-02) takes the same default and the same
  way out.
  ([advisory](https://github.com/dbt-labs/dbt-core/security/advisories/GHSA-pmrx-695r-4349),
  [dbt#10229](https://github.com/dbt-labs/dbt/issues/10229))
- **Jupyter** binds to localhost and still checks the `Host` header, so a
  web page cannot reach the local server through DNS rebinding. A request
  whose `Host` is not local gets a 403. We borrow this because the API has
  no authentication until Phase 4, which leaves it with no other protection.
  ([jupyter/notebook#3714](https://github.com/jupyter/notebook/pull/3714))
- **Soda Cloud's Reporting API** pages with `page`/`size`. When it is asked
  for a page past the end it returns no content.
  ([Soda Reporting API](https://docs.soda.io/reporting-api-v1/reporting-api-v1-migration-guide))
  Run history only grows, and a cron job can add a run while someone is
  paging, so offsets would repeat or skip rows. We use a keyset cursor
  instead.
- **Great Expectations Data Docs** and **Elementary** publish static HTML
  reports and do not offer a queryable API. tablewatch covers that case
  with C8 (`tablewatch report`, I-10). This API is for a live view.

## Outcome

After this ships, Dana or Priya runs

```bash
pip install 'tablewatch[server]'
tablewatch --project-dir /opt/dq/retail serve
# tablewatch serve: http://127.0.0.1:8765/api/v1 (project retail-example, 18 checks)
```

and anyone on that machine, or on the other end of an SSH tunnel, can read:

- the project: its name, datasources (names and types only), its checks, and
  any diagnostics;
- for each check, its **latest recorded result**, filterable by outcome.
  That list is "what is failing right now";
- runs, newest first and paginated, each with its selection, counts and
  results;
- the history of one check, including checks since deleted from the
  project.

The OpenAPI document describes every response. The ui-engineer builds
I-03 from it.

Nothing about running checks changes. The server never connects to a
datasource and never starts a run.

## The contract

All paths are under `/api/v1`. Every endpoint is `GET`. Every response is
`application/json`. The field names match `tablewatch run --output json`
and `tablewatch list --output json` wherever the two describe the same
thing.

### Conventions

- **Timestamps** are ISO 8601 in UTC with an explicit offset and
  microseconds, the form Python's `datetime.isoformat()` produces. An example
  is `"2026-09-26T06:56:12.385676+00:00"`. SQLite gives stored timestamps
  back **without** a timezone (verified on `main`: `datetime(2026, 9, 26, 6,
  56, 12, 385676)` with no tzinfo). They are stored in UTC and must be
  emitted with `+00:00`.
  *(REFINE, data-steward)* The offset is always `+00:00`, whatever the
  driver returns. A naive value is read as UTC. An aware value is converted
  with `astimezone(UTC)`, because Postgres returns `timestamptz` in the
  session's `TimeZone`, which is `Asia/Singapore` on a Singapore server.
  That would give `+08:00`: the same instant, but a string that sorts and
  compares differently in a client. Timestamps inside `message` text, such
  as a freshness check's `newest …`, are data. The API passes them through
  unchanged.
- **Ids are exact.** A check id is the full 16-hex-character id. A run id is
  the full 32-hex-character id. Prefix matching is a CLI convenience and is
  not part of the API.
  *(REFINE, data-steward)* A check with an explicit `id:` has that string
  as its id: letters, digits, `.`, `_`, `:` and `-`, such as
  `customers-email-missing` (`docs/check-language.md`). Only derived ids
  are 16 hex characters. The API must not validate check ids against a
  hex pattern. An explicit id is matched exactly, like any other, and
  reaches `/checks/{id}` and `/checks/{id}/history` (L2). The OpenAPI
  schema describes `check_id` as a string, with no hex pattern.
- **Numbers.** `value` is a JSON number or `null`. A non-finite float (NaN,
  ±inf) is emitted as `null`, because JSON cannot represent it.
- **One project.** The server serves the project it was started with. Runs
  and history are limited to runs whose recorded `project` equals that
  project's `name`, because a shared store (E5) holds other projects' runs
  too.
- **Outcomes** are the strings `pass`, `warn`, `fail`, `error`, `skipped`.
  The engine does not produce `skipped` today, but it is part of the
  `Outcome` enum and of `Counts`, so it is accepted wherever an outcome is.
- *(REFINE, data-steward)* **`not_run` is a filter value, not an
  outcome.** `GET /checks?outcome=not_run` matches checks whose `latest` is
  `null`, meaning that no result is recorded **for this check id in this
  project's runs**. It does not mean "left out of the last run": a check
  that a narrower run skipped keeps its older `latest` (C1). It appears
  nowhere else in a response. A check whose id changed because it was
  edited also matches (L2). The UI should label it "no result recorded",
  not "not run".
- *(REFINE, data-steward)* **Units of `value`.** `value` is in the
  metric's unit (`docs/check-language.md`, Metrics): a **count**; a
  **percent in percentage points**, so `20.0` is 20% and not 0.2; a
  **duration in seconds**, so a 3-day-old feed is about `259200`; or a
  **number** in the column's own units. `display_value` is always a
  string formatted for people, and it is `"—"` (U+2014) when `value` is
  `null`, which happens on every `error`. Clients that show a value to a
  person use `display_value`. Clients that chart or compare use `value`
  and need the unit. The unit follows from `metric`, but see finding F-U
  about exposing it.

### Shared shapes

```text
Location     { file: str, line: int, column: int }        # file is project-relative, "/"-separated
Diagnostic   { severity: "error" | "warning", message: str, location: Location | null }
Counts       { total: int, pass: int, warn: int, fail: int, error: int, skipped: int }
             # all six keys always present; skipped = total - pass - warn - fail - error
Page[T]      { items: [T], next_cursor: str | null }
Error        { error: { code: str, message: str } }
```

`Counts` always has all six keys, unlike `--output json`, which leaves
out the outcomes that did not occur. A typed client should not have to
guess which keys exist.

### Endpoints

| Method and path | Returns | Notes |
| --- | --- | --- |
| `GET /api/v1/project` | `Project` | Doubles as a liveness probe until E4 (`/healthz`, Phase 3) |
| `GET /api/v1/checks` | `{ items: [CheckSummary], total: int }` | Every check in the project, in `tablewatch list` order. Not paginated (see below). Filter: `outcome` (repeatable) |
| `GET /api/v1/checks/{check_id}` | `CheckSummary` | 404 if the id is not in the loaded project |
| `GET /api/v1/checks/{check_id}/history` | `Page[HistoryEntry]` | Newest first. `limit`, `cursor`. 404 only if the id is in neither the project nor this project's history |
| `GET /api/v1/runs` | `Page[Run]` | Newest first. `limit`, `cursor` |
| `GET /api/v1/runs/{run_id}` | `RunDetail` | 404 if unknown or another project's |
| `GET /api/v1/openapi.json` | OpenAPI 3.x document | `info.version` is tablewatch's version |
| `GET /` | `{ name: "tablewatch", version: str, api: "/api/v1", openapi: "/api/v1/openapi.json" }` | Placeholder. I-03 serves the UI here |

```text
Project {
  name: str,
  version: str,                      # tablewatch's version
  loaded_at: timestamp,              # when serve read the check files
  ok: bool,                          # false when any diagnostic is an error
  datasources: [{ name: str, type: str }],   # names and types ONLY
  counts: { datasets: int, checks: int },
  diagnostics: [Diagnostic],
}

CheckSummary {
  id: str, name: str, expression: str, metric: str,
  dataset: str, datasource: str, owner: str | null, tags: [str],
  source: str,                       # "checks/sales/customers.yml:6:5", as the CLI prints it
  location: Location,
  latest: LatestResult | null,       # null: never recorded
}

LatestResult {
  run_id: str, started_at: timestamp, trigger: str,
  outcome: str, value: number | null, display_value: str, message: str | null,
}

HistoryEntry {
  run_id: str, started_at: timestamp, trigger: str,
  outcome: str, value: number | null, display_value: str, message: str | null,
  duration_ms: number,
  name: str, expression: str, source: str,   # as recorded in that run; an explicit id: can outlive edits
}

Run {
  id: str, project: str, started_at: timestamp, finished_at: timestamp | null,
  outcome: str, exit_code: int, trigger: str,
  hostname: str, username: str, version: str,
  selection: { paths?: [str], tags?: [str], datasources?: [str], excludes?: [str], check_ids?: [str] },
  counts: Counts,
}

RunDetail = Run + { results: [RunResultItem] }   # in recorded order

RunResultItem {                      # same names as --output json "results"
  check_id: str, name: str, expression: str, metric: str,
  dataset: str, datasource: str, outcome: str,
  value: number | null, display_value: str, message: str | null,
  source: str, owner: str | null, tags: [str], duration_ms: number,
}
```

**`latest`** is this check id's result from the most recent run (by
`started_at`) of this project that included the check. It does not have to
come from the most recent run overall: a run limited to `checks/sales` does
not clear the latest result of an inventory check. `latest.started_at` says
how old that result is, and the UI must show it.

*(REFINE, data-steward)* The rules below pin `latest` down exactly. The UI
turns it into "what is failing right now", so any ambiguity here becomes a
wrong answer on Sam's screen.

- **Ties.** Runs are ordered by `(started_at, run id)`, both descending,
  which is the same key as the pagination cursor. As a result, `latest`
  always equals the first entry of the check's `/history` (L3).
- **The last result stands, whatever it is.** If the check errored in its
  most recent run, `latest.outcome` is `error`, with `value` `null` and
  `display_value` `"—"`. It does **not** fall back to the last `pass` or
  `fail`. The check then leaves `?outcome=fail` and joins `?outcome=error`
  (L1). That is the honest answer, because tablewatch no longer knows the
  state of the data. The UI's "needs attention" view should ask for
  `fail`, `warn` **and** `error` together.
- **Keyed on the current id, and on this project only.** Results recorded
  under an older id of an edited check are not carried over. The edited
  check shows `latest: null` until it runs again (L2). Results recorded by
  another project in a shared store never count, even when the check ids
  match. A copy of a project has the **same** ids, because the id hash
  does not include the project name (R5).
- **Not re-evaluated.** `latest` is the result as recorded, against the
  check as it was then. After an edit that keeps the id (an explicit
  `id:`, or a change to an option such as `valid_values`), `latest` still
  describes the old rule until the next run. Its `message` usually names
  the old threshold (`expected < 5%`), which helps.
- **Not "since when".** `latest` does not say how long a check has been
  failing. Sam asks for exactly that in the problem statement. A client
  can work it out from `/history`. A `since` field is additive and is left
  for I-03 or I-05 to request (finding F-S).
- **Only checks in the loaded project.** A check that failed to load
  (S5), or was deleted (H2), has no entry in `/checks`, and so none in
  `?outcome=fail`, even if its last recorded result was `fail`.
  `project.ok == false` is the only sign of this, so I-03 must show it
  next to any count of failures (finding F-B).

**`selection`** is shown **as recorded**. It holds only the keys that were
non-empty. `{}` means nothing was narrowed, so every check was selected.
Until I-16 normalises selections, `paths` holds exactly what the caller
passed: `"checks/sales"` from a CLI run in the project root, and an
absolute path if the caller passed one. The API does not rewrite it,
because a rewritten value would disagree with the store and with
`--output json`.

**Why `/checks` is not paginated.** Its length is the number of checks in
git, which is bounded and known at startup, and the explorer (I-04) needs
the whole tree. It returns `{items, total}` so that pagination can be
added later without changing the shape. Runs and history grow with every
run, so they are paginated.

**Pagination.** `limit` is 1–200 and defaults to 50. `next_cursor` is an
opaque string, or `null` on the last page. The cursor is a keyset on
`(started_at, id)`, both descending. A run recorded while someone is
paging does not repeat or shift what follows. The format of the cursor is
not part of the contract.

**Errors.** The HTTP status and `error.code` are:

| Status | `code` | When |
| --- | --- | --- |
| 400 | `invalid_parameter` | Bad `limit`, `cursor` or `outcome`. The message names the parameter |
| 403 | `forbidden_host` | `Host` header not local while bound to loopback (scenario X3) |
| 404 | `not_found` | Unknown run, check, or path |
| 405 | `method_not_allowed` | Anything but `GET` (and `HEAD`) |
| 500 | `internal_error` | Unexpected. The message is fixed, `internal error — see the server log`, with no traceback and no exception text |
| 503 | `store_unavailable` | The results store failed during the request. The message starts `results store: ` and never contains the URL |

FastAPI's default validation response is a 422 with a `detail` list. It is
replaced by this format everywhere, so every error has the same shape.

## Acceptance scenarios

**Fixtures.**
- `retail` is `tests/conftest.py`'s copy of `examples/retail` with its
  database built: 3 datasets and 18 checks.
- `recorded` is `retail` after two CLI runs, in this order:
  - **run A**: `tablewatch run`. Recorded as 18 total, 10 pass, 2 warn,
    6 fail, 0 error, selection `{}`, trigger `cli`, exit_code 1.
  - **run B**: `tablewatch run checks/sales`, run from the project root.
    Recorded as 14 total, 7 pass, 1 warn, 6 fail, 0 error, selection
    `{"paths": ["checks/sales"]}`, exit_code 1.
- The API is exercised in-process against the app factory. The test
  client's base URL must be `http://127.0.0.1`, because the default
  `testserver` host is rejected by X3. Scenarios marked *(process)* start
  the real command.

The PM reproduced every count below on `main` on 2026-09-26 by building
the example, running A then B into a fresh store, and querying the store.
Check ids come from `tablewatch list --output json` and are stable because
they are derived from path and expression. The ids used below:

| id | check | latest outcome |
| --- | --- | --- |
| `b1ceb8262d8b5441` | sales.customers `missing_percent(email) < 5%` | fail (run B), value `20.0`, display `20.00%`, message `expected < 5%` |
| `41e58afff9c48a46` | inventory.products `Price feed freshness` | warn (run A only) |
| `32867fbe86f483f3` | sales.orders `Order volume` | warn (run B) |
| `000f8d0048744bfb` | sales.customers `invalid_count(country) = 0` | fail (run B), value `1.0`, display `1`, message `expected = 0` *(REFINE)* |
| `a30dacf7316eef07` | sales.orders `invalid_percent(status) < 1%` (line 11, the line S5 breaks) | fail (run B), display `14.29%` *(REFINE)* |
| `e41cf32f07f328c3` | sales.customers `missing_percent(email) < 10%`: the L2 edit of `b1ceb8262d8b5441` | not in `recorded` *(REFINE)* |

*(REFINE, data-steward)* The data-steward reproduced the whole table, run
A's and run B's counts, and the three added ids on 2026-09-26, using a
copy of `examples/retail` and `tablewatch list --output json`. The six
checks that fail in run B are `b1ceb8262d8b5441` and `000f8d0048744bfb`
(customers), and `fc9cc3088acaf77a`, `11c20dd55fb97fa9`,
`a30dacf7316eef07` and `ed669ca6e5532a59` (orders). The two warnings are
`41e58afff9c48a46` (run A) and `32867fbe86f483f3` (run B).

*(REFINE, data-steward)* **Do not assert freshness values exactly.**
`build.py` writes timestamps relative to the moment it runs. The two
freshness checks' `value`, `display_value` and `message` therefore change
with the time between build and run. On one build, run A gave `3d` and run
B, 0.4 s later, gave `1h 1s`. Assert their outcomes only, or bounds on
their values (U1).

### Starting and stopping `serve`

**S1: loopback by default** `must` *(process)*
- Given `recorded`
- When `tablewatch --project-dir <recorded> serve --port 0` starts
- Then it listens on `127.0.0.1` only, and stderr carries one line
  `tablewatch serve: http://127.0.0.1:<port>/api/v1 (project retail-example, 18 checks)`
  with the port actually bound. No line contains the word `warning`, and
  nothing is written to stdout.
- And `GET http://127.0.0.1:<port>/api/v1/project` returns 200.

**S2: other interfaces are an opt-in with a warning** `must` *(process)*
- Given `recorded`
- When `serve --host 0.0.0.0 --port 0` starts
- Then before the `tablewatch serve:` line, stderr carries exactly:
  ```
  tablewatch: warning: serving on 0.0.0.0 with no authentication — anyone who can reach this address can read this project's checks and results. Authentication arrives in Phase 4 (tablewatch.yml cannot turn it on yet).
  ```
- And the same warning appears for `--host ::`, for a LAN address such as
  `--host 192.168.1.10` (unit-level, without binding), and for any host
  name other than `localhost`.
- And no warning appears for `127.0.0.1`, `127.0.0.2` (all of `127/8` is
  loopback), `::1`, or `localhost`.

**S3: the extra is optional** `must`
- Given tablewatch installed without the `server` extra (simulated by
  making `import fastapi` fail)
- When `tablewatch serve` runs
- Then it exits **3** and prints only
  `tablewatch: tablewatch serve needs the server extra: pip install 'tablewatch[server]'`
  to stderr.
- And importing `tablewatch`, `tablewatch.api` or `tablewatch.cli.main`
  leaves `fastapi`, `starlette` and `uvicorn` out of `sys.modules`. No
  other command pays for the extra.

**S4: an unusable `tablewatch.yml` stops serve** `must`
- Given a project whose `tablewatch.yml` is missing `name:`
- When `serve` runs
- Then it prints the diagnostics as `tablewatch validate` does, exits
  **3**, and never listens.

**S5: check-file mistakes do not stop serve** `must`
- Given `recorded` with `checks/sales/orders.yml` line 11 changed from
  `- invalid_percent(status) < 1%:` to `- invalid_percent(status) <<< 1%:`
- When `serve` starts
- Then it starts, and stderr carries the diagnostic
  `checks/sales/orders.yml:11:30: error: expected a number, found '<'`
  together with a line
  `tablewatch: 1 error in the project — serving the 17 checks that loaded`.
  The PM reproduced both on `main` with `tw.load()`: `ok` is False and 17
  checks load.
- And `GET /api/v1/project` returns `"ok": false` and that diagnostic with
  `location == {"file": "checks/sales/orders.yml", "line": 11, "column": 30}`,
  and `counts.checks == 17`.
- And `GET /api/v1/runs` still returns runs A and B, so the history stays
  readable while a file is broken.
- *(REFINE)* And the check that line 11 held, `a30dacf7316eef07`, is
  **failing** in runs A and B. It is missing from `/checks`, so
  `GET /api/v1/checks?outcome=fail` returns `total == 5`, not 6.
  `GET /checks/a30dacf7316eef07` returns 404, and its `/history` still
  returns 2 `fail` entries. The data-steward confirmed with `tw.load()`
  that this is the check that drops. This scenario pins down, on purpose,
  that a broken file makes the failure count go **down**. `project.ok ==
  false` is how a client learns that the count is incomplete (finding F-B).

**S6: no credentials needed, no datasource touched (rule 6)** `must`
- Given spec 001's `demo` project (`wh` password `${env:TW_TEST_PG_PASSWORD}`,
  **unset**; `lake.duckdb` absent) with one valid check file
- When `serve` starts and every endpoint is called once
- Then every call returns 200 or the documented 404, `lake.duckdb` still
  does not exist, and no connection is attempted to `wh`.

**S7: the store is migrated once, at startup** `must`
- Given `retail` with **no** `.tablewatch/` directory
- When `serve` starts
- Then the store is created and migrated **before** the server listens.
  After 50 requests across all endpoints, the Alembic upgrade has run
  exactly once in the process (counted by wrapping `ResultStore._migrate`
  or an equivalent seam the tech lead names). `GET /api/v1/runs` returns
  `{"items": [], "next_cursor": null}`, and every check's `latest` is
  `null`.

**S8: a store that cannot be opened stops serve before it listens** `must`
- Given `retail` with `results: {url: "sqlite:////dev/null/tw/results.db"}`
- When `serve` starts
- Then it exits **3** without listening, and stderr's last line starts
  `tablewatch: results store: `. No line contains `/dev/null/tw`, because
  store URLs can carry passwords.

**S9: stop cleanly** `should` *(process)*
- Given a running `serve`
- When it receives SIGINT or SIGTERM
- Then it exits **0** within 5 seconds.

**S10: logs go to stderr, never stdout** `must` *(process)*
- Given `serve` started with the global `--log-format json`
- When three requests are made
- Then stdout is empty. Each request's access log line is on stderr and
  parses as JSON. By default uvicorn writes its access log to stdout,
  which this scenario prevents.

### Project and checks

**P1: project** `must`
- Given `recorded`, served
- When `GET /api/v1/project`
- Then 200 with `name == "retail-example"`, `ok == true`,
  `diagnostics == []`, `counts == {"datasets": 3, "checks": 18}`,
  `datasources == [{"name": "lake", "type": "duckdb"}]`, `version` equal to
  `tablewatch.__version__`, and `loaded_at` a UTC timestamp.
- And the body contains no `path`, `url`, `host`, `user` or `password` key
  at any depth, and no filesystem path of the project root.

**C1: every project check, with its latest result** `must`
- Given `recorded`
- When `GET /api/v1/checks`
- Then `total == 18` and `items` lists the same 18 ids in the same order
  as `tablewatch list --output json`.
- And the item for `b1ceb8262d8b5441` has `source ==
  "checks/sales/customers.yml:6:5"`, `location == {"file":
  "checks/sales/customers.yml", "line": 6, "column": 5}`,
  `tags == ["example", "sales", "tier-1"]`,
  `owner == "sales-data@example.com"`, and `latest` with
  `run_id == <run B id>`, `outcome == "fail"`, `value == 20.0`,
  `display_value == "20.00%"`, `message == "expected < 5%"`.
- And the item for `41e58afff9c48a46` has `latest.run_id == <run A id>`
  and `latest.outcome == "warn"`. Run B did not select it, and that does
  not clear it.

**C2: filter by latest outcome** `must`
- Given `recorded`
- When `GET /api/v1/checks?outcome=fail`, then
  `?outcome=fail&outcome=warn`, then `?outcome=error`
- Then `total` is **6**, then **8** (including `41e58afff9c48a46` and
  `32867fbe86f483f3`), then **0**, and `items` keep `tablewatch list`
  order.
- And `?outcome=not_run` against a fresh store (S7) returns all 18.
- And `?outcome=bad` returns 400 `invalid_parameter` naming `outcome`.
- *(REFINE)* And `total` is the number of items **after** filtering, and
  `items` holds exactly that many. On `recorded`, `?outcome=not_run`
  returns `total == 0`, and `?outcome=pass` returns `total == 10`: every
  check was recorded at least once, and 18 − 6 − 2 = 10.
- *(REFINE)* And `?outcome=skipped` is a valid filter: 200 with
  `total == 0`, not 400.
- *(REFINE)* And `?outcome=FAIL` returns 400. Outcome values are
  lower-case, as they are everywhere else in the contract.

**C3: one check** `must`
- Given `recorded`
- When `GET /api/v1/checks/b1ceb8262d8b5441`
- Then 200 with the same object as its item in C1.
- And `GET /api/v1/checks/b1ceb826` (a prefix) returns 404 `not_found`.

**C4: check files edited after startup** `should`
- Given `serve` running on `recorded`
- When `checks/sales/customers.yml` is edited to add a check, and then
  `GET /api/v1/checks` is called
- Then the list is unchanged (still 18) and `project.loaded_at` is
  unchanged. Serve reads check files once, and a restart picks up the
  edit. This is the documented behaviour until hot reload is decided.
- And a `tablewatch run` recorded after startup **is** visible (R4), since
  the store is read live.

### Latest result semantics *(REFINE, data-steward)*

**L1: a check that errored last time shows `error`** `must`
- Given `recorded`, then **run E**, recorded as follows. Move
  `retail.duckdb` aside (DuckDB opens it read-only, so no empty file is
  created in its place). Run `tablewatch run checks/sales/customers.yml`.
  Put the file back. Run E is recorded as 5 total, 5 error, outcome
  `error`, exit_code 2, selection `{"paths": ["checks/sales/customers.yml"]}`.
  The data-steward reproduced this on 2026-09-26.
- When `GET /api/v1/checks/b1ceb8262d8b5441`
- Then `latest.run_id == <run E id>`, `latest.outcome == "error"`,
  `latest.value is null`, `latest.display_value == "—"`, and
  `latest.message` starts with `IO Error: Cannot open database`.
- And `?outcome=fail` returns `total == 4`: `b1ceb8262d8b5441` and
  `000f8d0048744bfb` have left it. `?outcome=error` returns `total == 5`.
  `?outcome=fail&outcome=warn&outcome=error` returns `total == 11`
  (4 + 2 + 5).
- And `GET /checks/b1ceb8262d8b5441/history` returns 3 items, E, B, A.
  The two earlier `fail` entries are unchanged.

**L2: editing an expression starts a new history** `must`
- Given `recorded`, with `checks/sales/customers.yml` line 6 changed from
  `- missing_percent(email) < 5%:` to `- missing_percent(email) < 10%:`,
  and `serve` restarted
- When `GET /api/v1/checks`
- Then the item at that position has `id == "e41cf32f07f328c3"` and
  `latest == null`. `?outcome=not_run` returns exactly that one check, and
  `?outcome=fail` returns `total == 5`. The data still fails (20% is not
  below 10%), but nothing is recorded for the new id yet. This is why the
  UI must present `not_run` as unknown, never as healthy.
- And `GET /checks/b1ceb8262d8b5441` returns 404, while
  `GET /checks/b1ceb8262d8b5441/history` returns its 2 entries with
  `expression == "missing_percent(email) < 5%"`.
- And *(`should`)* with an explicit `id: customers-email-missing` on that
  check, a run, the same threshold edit, another run, and a restart,
  `latest` is the second run's result, and `/history` of
  `customers-email-missing` returns both entries, each with its own
  recorded `expression`. This is the documented way to keep history
  across an edit (`docs/check-language.md`).

**L3: `latest` is the head of history, and ties break by run id** `must`
- Given `recorded`
- Then for every check in `GET /checks` whose `latest` is not null,
  `latest.run_id` equals the `run_id` of the first item of its `/history`,
  and `latest.outcome`, `latest.value` and `latest.started_at` match that
  item's.
- And given two runs of this project written directly to the store with an
  **identical** `started_at`, both including `b1ceb8262d8b5441`, with ids
  `…0001` and `…0002` (32 hex characters each)
- Then `latest.run_id` is the `…0002` run, `/history` lists `…0002`
  before `…0001`, and `/runs?limit=1` followed by its cursor yields both,
  neither repeated nor skipped.

**U1: units of `value`** `should`
- Given `recorded`
- Then `latest` for `b1ceb8262d8b5441` has `value == 20.0` (percentage
  points, not `0.2`). For `41e58afff9c48a46` (freshness), `value` is in
  seconds, with `259200 <= value < 259200 + 600`, and `display_value`
  starts with `3d`. For `32867fbe86f483f3` (`row_count`), `value == 7.0`
  and `display_value == "7"`.

**T1: timestamps are always emitted in UTC** `should`
- Given the API's serialiser, called at unit level (no Postgres needed
  until I-14)
- When it is handed `datetime(2026, 9, 26, 14, 56, 12, 385676,
  tzinfo=ZoneInfo("Asia/Singapore"))`, and separately the naive
  `datetime(2026, 9, 26, 6, 56, 12, 385676)`
- Then both are emitted as `"2026-09-26T06:56:12.385676+00:00"`.

### Runs

**R1: runs, newest first, paginated** `must`
- Given `recorded`
- When `GET /api/v1/runs?limit=1`
- Then `items` holds run B only, with `selection == {"paths":
  ["checks/sales"]}`, `counts == {"total": 14, "pass": 7, "warn": 1,
  "fail": 6, "error": 0, "skipped": 0}`, `outcome == "fail"`,
  `exit_code == 1`, `trigger == "cli"`, `finished_at` not null, and
  `started_at` ending in `+00:00` (the store is SQLite).
- And `next_cursor` is a string. Fetching `?limit=1&cursor=<it>` returns
  run A (`selection == {}`, `counts.total == 18`) with `next_cursor ==
  null`.
- And `GET /api/v1/runs` with no parameters returns both, B then A, with
  `next_cursor == null`.

**R2: paging is stable while runs arrive** `must`
- Given `recorded`, and page 1 fetched with `?limit=1` (run B)
- When a third run C is recorded, and page 2 is then fetched with the
  cursor from page 1
- Then page 2 is run A. Run C appears only on a fresh first page, and no
  run is repeated or skipped.

**R3: run detail** `must`
- Given `recorded`
- When `GET /api/v1/runs/<run B id>`
- Then 200, with the `Run` fields of R1 and `results` holding 14 items
  whose field names and values equal the `results` of
  `tablewatch run checks/sales --output json` for the same run. The
  exception is `duration_ms`, which is the stored value.
- *(REFINE)* And for every run returned by `/runs` or `/runs/{id}`,
  `counts` equals the tally of `results` by `outcome`, and
  `counts.total == len(results)`. The run's list entry and its detail
  must never disagree about how many checks failed.
- And an unknown id, a 12-character prefix of run B's id, and the id of a
  run recorded by another project in the same store (R5) each return 404
  `not_found`.

**R4: the store is read live** `must`
- Given `serve` running on `recorded`
- When `tablewatch run checks/inventory` records run C from another process
- Then the next `GET /api/v1/runs` lists C first, without a restart.
  `latest` for `41e58afff9c48a46` now carries C's id, and no request
  failed while C was being written.

**R5: one project per server** `must`
- Given `recorded`, and a second project named `other` whose
  `results.url` points at the **same** SQLite file, with one run recorded
  by `other`
- When `GET /api/v1/runs` and `GET /api/v1/checks/<any>/history` are
  called on retail's server
- Then `other`'s run appears in neither.
- *(REFINE)* Make `other` a **copy of `retail`** whose `tablewatch.yml`
  says `name: other`, and record its run **after** run B. Its check ids
  are identical to retail's, because the id hash does not include the
  project (`derive_check_id`), so a filter on `check_id` alone would pass
  the check above by accident. Then, on retail's server:
  `latest.run_id` for `b1ceb8262d8b5441` is still run B;
  `/checks/b1ceb8262d8b5441/history` returns exactly 2 items (B, A), not 3;
  `/runs` returns exactly 2 runs; and `GET /runs/<other's run id>` returns
  404.
- *(REFINE)* And a server for a project named `fresh` (a third copy of `retail`), started on that
  same store file, in which only `retail-example` and `other` have
  recorded runs, returns `/runs` as `{"items": [], "next_cursor": null}`,
  and every check's `latest` is `null`. For this project, "empty" means
  "no runs recorded by this project", whatever else the store holds.

**R6: bad paging parameters** `must`
- When `?limit=0`, `?limit=201`, `?limit=abc`, or `?cursor=not-a-cursor`
  is sent to `/runs` or to a check's `/history`
- Then 400 with `error.code == "invalid_parameter"` and a message naming
  the parameter. The error has no `detail` key.

**R7: selection as recorded** `should`
- Given a run recorded through `tw.run(recorded, paths=[<absolute path to
  checks/sales>])`
- When that run is fetched
- Then `selection.paths` is the absolute path exactly as recorded, and
  `trigger == "python"`. This is the form until I-16 (BACKLOG) normalises
  it.

**R8: non-finite values** `should`
- Given a run whose stored result has `value` NaN (written directly to the
  store)
- When it is fetched through `/runs/{id}` and `/checks/{id}/history`
- Then `value` is `null` and the response is 200, not 500.

### History

**H1: history of a check** `must`
- Given `recorded`
- When `GET /api/v1/checks/b1ceb8262d8b5441/history`
- Then 200 with 2 items, run B then run A, each `outcome == "fail"`,
  `value == 20.0`, `display_value == "20.00%"`, `trigger == "cli"`, and
  `source == "checks/sales/customers.yml:6:5"`.
- And for `41e58afff9c48a46`, 1 item (run A).
- And `?limit=1` pages exactly as R1 does.

**H2: a check with no history, and a check no longer in the project** `must`
- Given `recorded`
- When a check is added to `checks/inventory/products.yml`, `serve` is
  restarted, and that new check's history is fetched
- Then 200 with `{"items": [], "next_cursor": null}`.
- And when `sales.orders`' `Order volume` check is deleted from its file
  and `serve` is restarted, `GET /checks/32867fbe86f483f3` returns 404, but
  `GET /checks/32867fbe86f483f3/history` returns its 2 recorded entries,
  each with `name == "Order volume"`. History outlives the check.
- And an id that is in neither the project nor the store, such as
  `0000000000000000`, returns 404 `not_found`.

### Errors and the read-only surface

**E1: one error format** `must`
- When `GET /api/v1/nope`, `GET /api/v1/runs/zzz`, or `GET
  /api/v1/checks/zzz` is sent
- Then 404 with a body exactly of the shape `{"error": {"code":
  "not_found", "message": <str>}}`.

**E2: read-only** `must`
- When `POST /api/v1/runs`, `PUT /api/v1/checks/b1ceb8262d8b5441`, or
  `DELETE /api/v1/runs/<run B id>` is sent
- Then 405 `method_not_allowed`, and the store is unchanged (still two
  runs).
- And every operation in the OpenAPI document is a `get`. No route starts
  a run. If a later increment adds one, it must go through `api.execute()`
  with its own `trigger` (BACKLOG, I-02 requirement b).

**E3: the store fails mid-flight** `should`
- Given `serve` running, and the store made to raise on the next read
  (patched in-process)
- When `GET /api/v1/runs` is sent
- Then 503 `store_unavailable`, with a message that starts
  `results store: ` and contains no URL. The next `GET /api/v1/project`
  still returns 200.

**E4: no internals leak** `must`
- Given a handler made to raise `RuntimeError("secret-ish detail")`
- When it is called
- Then 500 `internal_error` with the fixed message. The body contains
  neither `secret-ish detail` nor `Traceback`, and the traceback is logged
  to stderr.

### Security scenarios

**X1: no interactive docs from a CDN** `must`
- When `GET /docs`, `GET /redoc`, or `GET /api/v1/docs` is sent
- Then 404. FastAPI's Swagger UI and ReDoc pages load JavaScript from
  `cdn.jsdelivr.net`, a third-party service pulled into the user's browser.
  Only `openapi.json` is served.

**X2: no cross-origin access** `must`
- When any endpoint is called with `Origin: https://evil.example`,
  including an `OPTIONS` preflight
- Then no response carries an `Access-Control-Allow-*` header. The
  preflight gets 405.

**X3: DNS-rebinding guard on loopback** `must`
- Given `serve` bound to `127.0.0.1` (the default)
- When a request carries `Host: evil.example` or
  `Host: evil.example:8765`
- Then 403 `forbidden_host`.
- And `Host` values `127.0.0.1:<port>`, `localhost:<port>`, and
  `[::1]:<port>` are accepted.
- And with `--host 0.0.0.0` (opted in, S2) the check is off, because the
  user has chosen to be reachable by name or address.

**X4: the OpenAPI contract** `must`
- When `GET /api/v1/openapi.json`
- Then 200 with an OpenAPI 3.x document whose `info.version` is
  tablewatch's version. It describes each endpoint above with a named
  response schema (`Project`, `CheckSummary`, `Page_Run_` or an equivalent
  the tech lead names). Every 200 body in C1–H2 validates against its
  schema (`jsonschema` is already a dev dependency).
- And `should`: a copy of the document is checked in (the tech lead picks
  the path; `docs/api/openapi.json` is suggested), and a test fails when it
  drifts from the generated one, as `test_migrations_match_the_models` does
  for the store. The ui-engineer mirrors I-03 against the checked-in copy.

## Non-goals

- **No UI and no static files.** I-03 serves the bundle at `/`, and CI
  checking the bundle in the wheel is I-03's requirement.
- **No authentication, tokens or TLS.** F1 and F2 are Phase 4, and TLS
  belongs to a reverse proxy. The owner decided on loopback plus a warning.
- **No starting runs, and no writes of any kind**, including acknowledging
  or muting (D4, Phase 4).
- **No compiled SQL and no check-file source text.** Check detail (I-05)
  adds these with its own endpoints. `compile` is credential-free, so
  adding them later carries no rule-6 risk.
- **No hot reload of check files** (C4). A restart picks up edits.
- **No run diff** (I-15, C5), **no `/healthz` or `/metrics`** (E4, Phase 3),
  **no multiple projects per server** (F8, Phase 4).
- **Server-side filtering is limited to `outcome` on `/checks`.** Filters
  by tag, owner and folder for the explorer are I-04's call, client-side or
  added then.
- **No change to the CLI's `runs` and `history`.** They still show every
  project in a shared store. I-19 aligns them.

## Design notes

### The framework: FastAPI + uvicorn, as an optional `server` extra

The roadmap names FastAPI (`docs/ROADMAP.md`, Phase 2). CLAUDE.md says to
reach for click, pydantic and SQLAlchemy before adding a dependency. None
of the three serves HTTP, so a new dependency is unavoidable, and the
question is which one:

| Option | For | Against |
| --- | --- | --- |
| stdlib `http.server` | No dependency | Its docs say it is not for production. No OpenAPI. We would hand-write routing, threading and error handling, all of it code the security-reviewer then has to read |
| Starlette alone | Small (Starlette, anyio) | No OpenAPI generation. We would hand-maintain the contract that I-03 mirrors |
| **FastAPI + uvicorn** | Built on pydantic, which is already a core dependency. Response models *are* the OpenAPI contract, which X4 needs. The ui-engineer can generate TypeScript from it | FastAPI, Starlette, anyio, uvicorn and h11 enter the security review |

Decision: **FastAPI + uvicorn**, declared as

```toml
[project.optional-dependencies]
server = ["fastapi>=…", "uvicorn>=…"]    # plain uvicorn, NOT uvicorn[standard]; plain fastapi, NOT fastapi[standard]
```

`uvicorn[standard]` adds uvloop, httptools, watchfiles, websockets,
python-dotenv and PyYAML. `fastapi[standard]` adds python-multipart, the
fastapi CLI and email-validator. The API needs none of them. `httpx` joins
the **dev** group for FastAPI's `TestClient`. The core install and every
other command stay free of all of these (S3).

### Constraints from CLAUDE.md

- **Rule 6 (secrets).** `serve` is in the same class as `validate`, `list`
  and `compile`: it needs no credentials and never calls
  `create_engine_for` (S6). `/project` exposes datasource names and types
  only.
- **Rule 7 and the exit codes.** `serve` is a new command, and existing
  codes are unchanged. Proposal for the architect: a `serve` that stops
  before it listens exits **3** ("nothing ran"). That covers a missing
  extra, an unusable `tablewatch.yml`, a store that cannot be opened or
  migrated, and an address in use. A clean shutdown exits **0**. `serve`
  never exits 1 or 2. Click's own usage errors (`--port abc`) still exit
  2, which is the open I-17 question and is not changed here.
- **Logs** go to stderr only, including uvicorn's access log, and honour
  `--log-format json` (S10).
- **Results store.** Opening the store once at startup is the migration
  (`ResultStore.__init__` migrates). The server keeps that `ResultStore`,
  and its engine pool, for its lifetime. This meets the iteration 1
  requirement "migrate once at startup" and needs no new migration seam.
  New read queries (keyset-paged runs, run by id, latest result per check
  for this project, paged history) belong on `ResultStore` in
  `results/store.py`. They do not belong in the server module, which
  holds no SQL. `results/models.py` does not change, so no Alembic
  revision is expected. If the tech lead adds an index (for example on
  `tablewatch_runs.project`), that **is** a model change and needs a
  revision.
- **API models are separate from ORM rows.** They are pydantic response
  models in the server package, so a later store change cannot silently
  change the contract.
- **CLAUDE.md's module table** needs a row for the new server package. The
  tech lead owns that file; the PM does not edit it.

### Design decisions (settled in REFINE)

Reviews: architect approve-with-followups; security-reviewer block on X3
(resolved below), otherwise approve-with-followups; data-steward
accept-with-followups; ui-engineer consulted. Tech lead decisions below
supersede the open questions that follow, and any scenario text they
contradict.

**Contract changes**

1. **Check ids are strings**, validated against the loader's id pattern
   (`^[A-Za-z0-9][A-Za-z0-9_.:-]*$`, at most ~~128~~ **64** characters) —
   explicit `id:` values are free text. *(Corrected in VERIFY: the store's
   `check_id` column is 64 wide, so the loader now rejects a longer
   explicit `id:` with a Diagnostic, and the API uses the same cap.)* **Run ids** are exactly 32 lowercase hex.
   Anything else is 404 before any query. The API never uses a prefix or
   `LIKE` query.
2. **`outcome` filter values** are `pass|warn|fail|error|skipped|not_run`.
   `not_run` means `latest == null` and is a filter value only, never an
   outcome in a body. Anything else (including `FAIL`) is 400 naming
   `outcome`.
3. **HEAD** is 405 like every other non-GET method; the OpenAPI document
   holds only `get` operations.
4. **Every response field is `required`** in the OpenAPI schema; nullable
   fields are `required` + nullable. The one exception is `selection`, whose
   keys are present only when non-empty. `Outcome`, `Diagnostic.severity`
   and `error.code` are enums.
5. **`CheckSummary.unit`**: `"count" | "percent" | "duration" | "number"`
   (from the metric). Added because every client would otherwise copy the
   metric-to-unit table. `latest.since` ("failing since") is **deferred to
   I-03** — additive, decided with the first screen that shows it.
6. **`Run` does not carry `hostname` or `username`** — no planned screen
   needs them and they map the estate. They stay in the store and in
   `--output json`; a later item may add them back behind auth.
7. **`GET /` is not part of the contract**; I-03 replaces it with the UI.
8. **Named page models** `RunPage` and `HistoryPage` (not a generic whose
   OpenAPI name depends on the pydantic version).

**Security (security-reviewer)**

9. **The Host check is on in every bind mode** (resolves the blocking
   finding). Accepted `Host` values, case-insensitive, port stripped:
   `localhost`, any IP literal (IPv4, or bracketed IPv6), and names given
   with the repeatable `--allowed-host NAME`. Anything else — including a
   missing or empty `Host`, `localhost.evil.example`,
   `127.0.0.1.evil.example`, `127.0.0.1@evil.example` — is 403
   `forbidden_host`. An IP literal cannot carry an attacker's DNS name,
   so accepting it is safe. X3's last bullet is replaced: with
   `--host 0.0.0.0`, `Host: evil.example:8765` is 403 and
   `Host: 192.168.1.10:8765` is 200; `--allowed-host dq.internal` accepts
   `Host: dq.internal`. Implemented as a pure ASGI middleware (not
   Starlette's `TrustedHostMiddleware`, which mishandles `[::1]:port` and
   returns plain-text 400).
10. **The S2 warning** names what is exposed: `tablewatch: warning: serving
    on <host> with no authentication — anyone who can reach this address
    can read this project's checks and results, including data values and
    owner emails. Authentication arrives in Phase 4 (tablewatch.yml cannot
    turn it on yet).`
11. **Store errors over HTTP carry a fixed message**:
    `results store: unavailable — see the server log`; the driver's text
    (host, user) goes only to the log. At startup, S8's line is
    `tablewatch: results store: could not be opened — run with -v for
    details`, with details logged at DEBUG. No URL, host or path reaches
    stderr at the default level.
12. **Cursor**: base64url of `"<utc isoformat>|<run id>"`, at most 256
    characters, strictly decoded; any failure is 400 naming `cursor`. The
    project predicate always comes from the server. 400 messages name the
    parameter and never echo its value.
13. **Response headers** on every response, errors included:
    `X-Content-Type-Options: nosniff`, `Cache-Control: no-store`,
    `Cross-Origin-Resource-Policy: same-origin`, `Referrer-Policy:
    no-referrer`, `X-Frame-Options: DENY`. No `server` header.
14. **uvicorn/FastAPI settings**: `docs_url=None`, `redoc_url=None`,
    `debug=False`, `redirect_slashes=False`, `proxy_headers=False`,
    `server_header=False`, `limit_concurrency=64`.
15. **Dependencies**: extra `server = ["fastapi>=0.115,<1",
    "uvicorn>=0.30,<1", "starlette>=0.49.1", "h11>=0.16"]` — plain
    packages, no `[standard]`. `httpx` in the dev group *(changed in
    BUILD: `httpx2>=2.13,<3`, which Starlette 1.7's TestClient requires)*. The lock diff must
    add nothing from uvloop, httptools, watchfiles, websockets,
    python-dotenv or python-multipart.

**Design (architect)**

16. **Layout** `src/tablewatch/server/`: `__init__.py` (docstring only,
    never imports fastapi/starlette/uvicorn), `hosts.py` (stdlib:
    `is_loopback`, `host_allowed`), `schemas.py` (wire models, `Timestamp`
    and `JsonFloat` types, the only ORM→wire mapping), `routes.py` (the
    six GETs and the cursor; no SQL), `app.py` (`create_app`, host guard,
    headers, error handlers, OpenAPI post-processing), `serve.py` (bind,
    uvicorn, logging, signals). All internal.
17. **Timestamps** serialise with `isoformat()` after `astimezone(UTC)`
    (naive → UTC). **Non-finite floats** serialise as `null`.
18. **Store reads** live on `ResultStore`, all scoped by `project` and
    returning fully loaded rows: `runs_page`, `run` (results eager, ordered
    by result id), `latest_results` (one window-function query, tie-break
    `(started_at, run id)` desc), `history_page`. A `StoreError` base
    (`RecordError` subclasses it) is the only exception the server sees.
    No model change, no migration; a `(project, started_at)` index is
    I-14's.
19. **The CLI command** imports the server lazily (missing extra → exit 3,
    before loading the project), loads the project (unusable → 3), rejects
    an in-memory store (3), opens the store once (3 on failure), binds the
    socket itself (3 on failure), warns if not loopback, prints the startup
    line, and runs. SIGINT/SIGTERM exit 0. `serve` never exits 1 or 2 of
    its own accord.
20. **Logging**: uvicorn's loggers use the tablewatch stderr handler; access
    lines at INFO (shown by default, hidden by `-q`); startup and warning
    lines via `click.echo(err=True)`.
21. **OpenAPI**: `info.version = __version__`; FastAPI's 422 responses and
    schemas removed; 400/404/503 declared with `ErrorBody`; checked in at
    `docs/api/openapi.json` with a drift test.
22. **Deferred to the backlog**: `latest.since` (I-03); `rules`, compiled
    SQL and source endpoints (I-05); one shared `Check`→dict mapping for
    `list --output json` and `CheckSummary`; raw driver text (with absolute
    paths) in `error` messages served over the API; a `(project,
    started_at)` index (I-14).

### Open questions for the tech lead and the architect (REFINE)

1. **SQLite and threads.** FastAPI runs sync handlers in a thread pool, so
   the server shares one SQLite engine across threads. Confirm the pool
   and `check_same_thread` settings under SQLAlchemy 2.x. Also confirm
   that a CLI run writing while the server reads (R4) cannot hit
   `database is locked` beyond SQLite's busy timeout. If it can, set a
   busy timeout. WAL mode would change the store file's behaviour for
   every user, so raise it rather than slip it in.
2. **Where `serve` builds the app.** The proposal is an app factory,
   `create_app(project, store, *, loopback: bool)`, with `cli/main.py`
   importing the server package lazily inside the command. The architect
   decides whether this is a public seam. The PM's view is that it is
   internal, as `api.execute` is.
3. **Default port.** The proposal is `8765`. The only requirement is that
   `--port 0` works and the startup line prints the bound port.
4. **"Latest per check" on Postgres.** One query (a window function or
   `max(started_at)` grouped by `check_id`) rather than N queries; it must
   work on SQLite and Postgres. I-14 verifies Postgres in CI. Here,
   SQLite is enough.
5. **Exit code 3 for "could not start"** (above). The architect confirms
   or proposes otherwise. This is a new command's contract, not a change
   to an existing one.

### Traps the data-steward should test in REFINE

- A check's "latest" result can be old, because narrower runs skip it
  (C1). The API returns `started_at` so the UI can show the age, and I-03
  must show it.
- A project renamed in `tablewatch.yml` loses its history in the server,
  because runs are keyed by the recorded `project` name (R5 is the other
  side of this). Nothing is lost from the store. This is documented rather
  than solved here.
- `value`, `display_value` and `message` can carry data values: the
  minimum price, or the newest timestamp in a freshness message
  (`newest 2026-09-23T06:56:03…`). On loopback that is what the CLI
  already shows the same user. With `--host` it reaches the network,
  which is exactly what the S2 warning says.

## Reviewers required

- **qa-engineer**: always. Keep the concurrent-caller angle from
  iteration 1: requests during a recording run (R4), paging during
  inserts (R2), many requests against one store (S7).
- **data-steward**: always. Semantics of `latest`, `selection` and
  counts, and the scenario numbers.
- **security-reviewer**: **required**. It adds inbound network access
  (a listening socket with no authentication), new dependencies (FastAPI,
  Starlette, anyio, uvicorn, h11; httpx in dev), and exposes stored results
  that may carry data values over HTTP. Focus: S2, S8, X1–X4, E4, P1, and
  the transitive dependency list.
- **architect**: **required**, in REFINE and in VERIFY. It adds a public
  API contract (`/api/v1`, OpenAPI), a new package in `src/`, new
  `ResultStore` read methods, and a new command's exit codes.
- **ui-engineer**: consulted in REFINE on the contract, since it mirrors it
  in I-03, especially the shapes of `CheckSummary.latest`, `Counts` and
  `Page`. It does not build anything in this increment.

## Size

**M** (about two iterations of effort). The work is six endpoints, the
`serve` command with host and startup handling, the store read methods,
the error envelope and security middleware, and the OpenAPI snapshot. If
BUILD runs long, the split is: **R** (this spec without `/checks/{id}/history`,
the X4 snapshot and R7/R8) first, with history following as its own S
increment ahead of I-05, which is the first screen that needs it. I-03's
overview needs only `/project`, `/checks` and `/runs`.
