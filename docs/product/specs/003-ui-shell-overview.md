# Spec 003: Web UI shell and overview page

| | |
| --- | --- |
| Backlog item | I-03 |
| Features | C2 (UI shell and overview; `serve` itself shipped in I-02) |
| Phase | 2 (`0.2.0`) |
| Size | M |
| Depends on | I-02 ✓ (spec 002: `/api/v1`, `tablewatch serve`, `docs/api/openapi.json`) |
| Unblocks | I-05 check detail, I-04 check explorer, I-15 run detail and diff |
| Branch | `iter/003-ui-shell-overview` |
| Status | planned (PLAN, iteration 3) |

## Problem and persona

**Sam, data steward.** "Dana gave me a URL instead of a terminal, and it
returns JSON. I want to open it in a browser and see what is failing in my
tables, how long it has been failing, and whether that is today's news or
last week's. And I need to know when *tablewatch* is broken rather than my
data, because that is Dana's problem, not mine."

**Alex, analytics lead.** "Before I put a number in front of the board I
want one page that says whether the tables behind it are healthy. A check
that has never run is not healthy. It is unknown, and the page should say
so."

**How they cope today.** Since iteration 2 they can read
`/api/v1/checks?outcome=fail` in a browser, or ask Dana to run
`tablewatch runs` and `tablewatch history <id>`. Neither says how long a
check has been failing, which is Sam's first question in spec 002. The
JSON answers "what is failing" but it is not something Sam reads at a
glance. It also does not warn her that a broken check file has dropped
checks from the count.

### How others do it

- **Grafana alerting** treats "could not evaluate" as its own **Error**
  state. By default a failed evaluation moves the rule into Error; it does
  not keep its previous state. "Keep last state" is an opt-in, meant to
  stop flapping when a data source is briefly down.
  ([Grafana: No Data and Error states](https://grafana.com/docs/grafana/latest/alerting/fundamentals/alert-rule-evaluation/nodata-and-error-states/))
  PLAN adopted the default. *(REFINE, data-steward)* We adopt the other
  behaviour for `since` instead: an `error` keeps the last evaluated state.
  Grafana's "Keep last state" exists for exactly the case in question, a
  data source that is briefly unreachable. The `error` still shows as the
  check's latest outcome, and nothing is hidden (decision D1, revised).
- **Elementary** puts a health summary first on its dashboard (tests run,
  failures, anomalies) and then the execution history, where frequently
  failing tests can be found. Its report is generated as static HTML
  rather than served live.
  ([Elementary](https://github.com/elementary-data/elementary);
  [Xebia on Elementary](https://xebia.com/blog/monitoring-dbt-model-and-test-executions-using-elementary-data/))
  We keep "summary, then what needs attention". The static report is
  tablewatch's I-10.
- **dbt `docs serve`** serves a single-page app and its JSON from one local
  process, and after CVE-2024-36105 it binds to loopback by default. Spec
  002 already adopted the same default and the same `--host` opt-in. The
  UI rides on them unchanged.
  ([advisory](https://github.com/dbt-labs/dbt-core/security/advisories/GHSA-pmrx-695r-4349))
- **Vite and CSP.** Reported "Vite adds inline scripts" problems under
  `script-src 'self'` came from `@vitejs/plugin-legacy`, and the Vite issue
  was closed as invalid for core Vite
  ([vite#15404](https://github.com/vitejs/vite/issues/15404)). A plain
  modern Vite build loads its entry as an external module script, so a
  strict CSP with no `'unsafe-inline'` is possible as long as we do not
  use that plugin. Scenario X2 holds us to it.

## Outcome

After this ships, Dana or Priya runs

```bash
pip install 'tablewatch[server]'
tablewatch --project-dir /opt/dq/retail serve
# tablewatch serve: http://127.0.0.1:8765/ (project retail-example, 18 checks; API at /api/v1)
```

and Sam opens `http://127.0.0.1:8765/` (directly or through an SSH tunnel).
She sees one page that shows:

- the project name, the tablewatch version, and **when the check files
  were loaded**. `serve` reads the files once, at startup;
- a **banner** when a check file failed to load, listing each diagnostic
  at `file:line:col`, with a marker next to the failure count saying that
  the count is incomplete;
- a **summary** of every loaded check's latest result: failing, errors,
  warnings, no result recorded, passing. Errors and failures are counted
  and drawn apart;
- the **latest run**: when it ran, what triggered it, what it selected,
  and what it found;
- **every check, problems first**: fail, then error, then warn, then no
  result, then pass. Each row gives the age of its latest result, and
  problem rows say how long the problem has lasted ("failing since").

Nobody needs Node on the server: the built UI ships inside the wheel.
The API gains one additive field, `latest.since`, and its OpenAPI
document becomes precise enough to generate TypeScript types from.

## Scope at a glance

| Part | Who builds it | Where |
| --- | --- | --- |
| OpenAPI fidelity fixes (C1–C3) | tech lead | `src/tablewatch/server/`, `docs/api/openapi.json` |
| `latest.since`, `last_evaluated` (P1–P7) | tech lead | `results/store.py`, `server/schemas.py`, `server/routes.py` |
| Serving the bundle: static files, SPA fallback, CSP, `GET /` (W1–W6, X1–X5) | tech lead | `server/app.py`, new `src/tablewatch/webapp/` |
| Startup line and the `serving()` harness (W7, H1) | tech lead, qa-engineer | `cli/main.py`, `tests/` |
| Frontend: shell and overview (O1–O10), `docs/UI_SPECIFICATION.md` | ui-engineer | `frontend/**`, `src/tablewatch/webapp/static/` |
| CI: frontend job, bundle and types drift, wheel contents (K1–K4) | tech lead | `.github/workflows/checks.yml` |
| README "Serve results over HTTP" updated for the UI | data-steward | `README.md` |

**Order inside BUILD.** C1–C3 and P1–P7 come first, then `openapi.json` is
regenerated, and only then does the ui-engineer generate types from it.
This carried requirement (I-03 (d)) exists so that generated types are
never built from the imprecise document.

## The contract changes (additive)

### `LatestResult.since`

```text
LatestResult { run_id, started_at, trigger, outcome, value, display_value, message,
               since: Timestamp }        # new, required, never null
```

*(REFINE, data-steward: this definition replaces PLAN's. D1 below records
why.)* Outcomes split into **evaluated** ones (`pass`, `warn`, `fail`: a
statement about the data) and **not evaluated** ones (`error`, `skipped`:
no statement about the data). Read the check's history newest first.

- **When `latest.outcome` is evaluated**, `since` is the `started_at` of
  the oldest result in the leading streak of results with that outcome,
  where `error` and `skipped` results are **passed over**: they neither end
  the streak nor extend it. The first *evaluated* result with a different
  outcome ends it.
- **When `latest.outcome` is `error` or `skipped`**, `since` is the
  `started_at` of the oldest result in the leading streak of that exact
  outcome. Any other outcome ends it.

Consequences:

- Only results **for this check id in this project** count, the same
  scope as `latest` (spec 002). A run that did not select the check is not
  in its history, so it neither breaks the streak nor extends it.
- **An `error` does not end a streak of `fail`s.** The sequence `fail (A),
  fail (B), error (E), fail (F)` gives `latest.outcome == "fail"` and
  `since == A.started_at`. The data failed the rule every time it was
  evaluated from A to F. During E, tablewatch learned nothing about the
  data, so E is not evidence that the problem went away.
- **An `error` never hides a recovery.** `fail (A), error (E), pass (P),
  fail (F)` gives `since == F.started_at`. `P` is evaluated and differs.
- **Evaluated outcomes end one another**: `warn` ends a streak of `fail`s,
  and `fail` ends a streak of `warn`s.
- `since` is always the `started_at` of a result whose outcome is
  `latest.outcome`, never the `started_at` of an `error` that was passed over.
- `since` is present for every outcome, `pass` included, so a client does
  not have to special-case it. `since <= latest.started_at` always, with
  equality when the latest result is the first of its streak.
- **An expression edit under an explicit `id:`** does not end the streak.
  The user chose the id to keep one history across edits. *(REFINE,
  data-steward: Q3 is settled this way, scenario P6.)* A threshold edit is
  how a steward records an accepted tolerance. If the check still fails
  under the new rule, the problem is the same one. The history entries carry
  `expression`, so I-05 can show where the rule changed.
- Ties on `started_at` follow the order `/history` uses, so `since`
  always equals the `started_at` of an entry that `/history` returns (P4).

### `LatestResult.last_evaluated` *(REFINE, data-steward; `should`, P7)*

```text
LatestResult { …, last_evaluated: { outcome, started_at, since } | null }
```

This is null when `latest.outcome` is evaluated (`pass`, `warn`, `fail`),
and when the check has never been evaluated. When `latest.outcome` is
`error` or `skipped`, it is the newest **evaluated** result in the history:
its outcome and `started_at`, plus the `since` that result would have had
as `latest`. It comes out of the same window as `since`.

Why: without it, a database outage turns known failures into errors, and
the overview's "failing" count **drops**. In `interrupted` before run F it
goes from 6 to 4, and the two missing failures look like Dana's problem
rather than Sam's. An error row that says "Last evaluated: Fail, failing
since <A>" keeps the data problem in Sam's view while tablewatch cannot
see it.

### OpenAPI fidelity

1. **`selection`** is an object with five named, optional properties,
   `paths`, `tags`, `datasources`, `excludes` and `check_ids`, each an
   array of strings. A key is present only when it is non-empty
   (decision 4 of spec 002 stands). The PM's preference, for the
   architect to settle (Q2), is that `additionalProperties` stays
   "array of strings". A key written by a newer tablewatch into a shared
   store would then still reach the client. Dropping it would make a
   narrowed run look like `{}`, "every check", which is a false claim.
2. **403, 405 and 500** are declared on every operation, with
   `ErrorBody`, next to the existing 400, 404 and 503.
3. **Timestamps** are `type: string, format: date-time` in the document,
   and are **always** emitted with six fractional digits.
   `datetime(2026, 9, 26, 6, 56, 12)` is emitted as
   `"2026-09-26T06:56:12.000000+00:00"`, not `"…T06:56:12+00:00"`.

The API version stays `v1`. `since` is additive, and the other changes
make the document describe what the server already sends (the timestamp
fraction aside).

## Acceptance scenarios

**Fixtures** (as in spec 002; `tests/conftest.py`):

- `retail` is a copy of `examples/retail` with its database built: 3
  datasets and 18 checks.
- `recorded` is `retail` after **run A** (`tablewatch run`: 18 total, 10
  pass, 2 warn, 6 fail) and then **run B** (`tablewatch run checks/sales`:
  14 total, 7 pass, 1 warn, 6 fail, selection
  `{"paths": ["checks/sales"]}`).
- `interrupted` is `recorded` plus **run E** and then **run F**. For run E,
  move `retail.duckdb` aside, run `tablewatch run
  checks/sales/customers.yml` (exit 2; 5 total, 5 error), and put the file
  back. Run F is `tablewatch run` (exit 1; 18 total, 10 pass, 2 warn,
  6 fail).
- `broken` is `recorded` with `checks/sales/orders.yml` line 11 changed
  from `- invalid_percent(status) < 1%:` to
  `- invalid_percent(status) <<< 1%:`. This is spec 002's S5: `ok` is
  false, 17 checks load, and `a30dacf7316eef07` (failing in A and B)
  drops out.

The PM reproduced `recorded` and `interrupted` on `main` on 2026-09-26
using a scratch copy of `examples/retail`, the CLI, and the in-process
app. The histories below are what `/checks/{id}/history` returned (newest
first):

| id | check | history in `interrupted` | `since` in `interrupted` |
| --- | --- | --- | --- |
| `b1ceb8262d8b5441` | sales.customers `missing_percent(email) < 5%` | fail (F), error (E), fail (B), fail (A) | A *(REFINE: was F)* |
| `fc9cc3088acaf77a` | sales.orders `missing_count(customer_id) = 0` | fail (F), fail (B), fail (A) | A |
| `32c8f939b90f6367` | sales.customers `row_count > 0` | pass (F), error (E), pass (B), pass (A) | A *(REFINE: was F)* |
| `41e58afff9c48a46` | inventory.products `Price feed freshness` | warn (F), warn (A) | A |

*(REFINE, data-steward)* The data-steward reproduced every state on
2026-09-26 in a scratch copy, using the CLI and the in-process app. The
latest outcomes over the 18 loaded checks were:

| state | pass | warn | fail | error | none | loaded |
| --- | --- | --- | --- | --- | --- | --- |
| `recorded` (A, B) | 10 | 2 | 6 | 0 | 0 | 18 |
| A, B, E (`interrupted` before F) | 7 | 2 | 4 | 5 | 0 | 18 |
| `interrupted` (A, B, E, F) | 10 | 2 | 6 | 0 | 0 | 18 |
| `broken` | 10 | 2 | 5 | 0 | 0 | 17 |
| `broken-yaml` (below) | 6 | 1 | 2 | 0 | 0 | 9 |

In A, B, E the five `error`s are all of `sales.customers`. Before E, two of
them (`b1ceb8262d8b5441` and `000f8d0048744bfb`) were `fail` and three
were `pass`.

- *(REFINE)* `broken-yaml` is `recorded` with a YAML syntax error appended
  to `checks/sales/orders.yml` (`name: [unclosed` on a new last check).
  The whole file drops: `ok` is false, with one diagnostic
  `invalid YAML: expected ',' or ']', but got '<stream end>'` at
  `checks/sales/orders.yml:24:1`, and 9 checks load. **Four** checks that
  were failing leave the page. The UI cannot know how many checks the
  broken file held.

In `recorded` (runs A, B only), the latest outcomes over all 18 checks
are 10 pass, 2 warn, 6 fail, 0 error. The four inventory checks' latest
result is from run A, and the other fourteen are from run B.

Frontend scenarios (O*) are vitest component tests. Their API responses
are fixtures typed against the **generated** types, so a contract change
breaks `tsc`. The fixtures mirror the named Python fixture states. The
data-steward also runs O1–O8 by hand against a real `serve` on
`recorded`, `interrupted` and `broken` in VERIFY.

### Contract fidelity

**C1: `selection` has named keys** `must`
- When `GET /api/v1/openapi.json`
- Then `components.schemas.Run.properties.selection` has `properties`
  `paths`, `tags`, `datasources`, `excludes` and `check_ids`, each
  `{"type": "array", "items": {"type": "string"}}`, and none of them is
  `required`.
- And given `recorded`, `GET /api/v1/runs` returns run B's
  `selection == {"paths": ["checks/sales"]}` and run A's
  `selection == {}`, unchanged from spec 002.
- And *(`should`, pending Q2)* a run written straight to the store with
  `selection == {"owners": ["sam@example.com"]}` is served with that key
  intact.

**C2: every error status is declared** `must`
- When `GET /api/v1/openapi.json`
- Then every operation under `paths` declares responses `400`, `403`,
  `404`, `405`, `500` and `503`, each referencing `ErrorBody`.
- And the checked-in `docs/api/openapi.json` equals the generated document
  (the existing drift test).

**C3: timestamps are date-times with microseconds** `must`
- When `GET /api/v1/openapi.json`
- Then every timestamp property (`Project.loaded_at`,
  `LatestResult.started_at`, `LatestResult.since`, `HistoryEntry.started_at`,
  `Run.started_at`, `Run.finished_at`) has `format: date-time`.
- And the API's serialiser, given `datetime(2026, 9, 26, 6, 56, 12)`
  (naive) and `datetime(2026, 9, 26, 14, 56, 12,
  tzinfo=ZoneInfo("Asia/Singapore"))`, emits
  `"2026-09-26T06:56:12.000000+00:00"` for both.
- And every timestamp in every 200 body for `recorded` matches
  `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}\+00:00$`.

### Failing since

**P1: an unbroken run of failures** `must`
- Given `recorded`
- When `GET /api/v1/checks/b1ceb8262d8b5441`
- Then `latest.outcome == "fail"`, `latest.run_id == <run B id>`, and
  `latest.since == <run A started_at>`.
- And for `41e58afff9c48a46` (inventory, run A only),
  `latest.since == latest.started_at == <run A started_at>`, even though
  run B is newer. B did not select it.

**P2: an `error` does not end a streak of failures** `must` *(REFINE:
reversed from PLAN; see D1)*
- Given `interrupted`
- When `GET /api/v1/checks`
- Then `b1ceb8262d8b5441` has `latest.outcome == "fail"`,
  `latest.run_id == <run F id>`, and `latest.since == <run A started_at>`.
  Run E's error is passed over.
- And `fc9cc3088acaf77a` (not in run E) has `latest.since ==
  <run A started_at>`.
- And `32c8f939b90f6367` has `latest.outcome == "pass"` and
  `latest.since == <run A started_at>`.
- And given only `recorded` plus run E (before F), `b1ceb8262d8b5441` has
  `latest.outcome == "error"` and `latest.since == <run E started_at>`.
  A streak of errors is counted only from errors.

**P3: a different evaluated outcome ends the streak** `must`
- Given the check sales.orders `Order volume` (`32867fbe86f483f3`: `warn`
  when `row_count < 100`, `fail` when `= 0`), and runs of this project
  written to the store in the order given, with that check's outcomes as
  listed
- Then:

  | outcomes, oldest first | `latest.outcome` | `latest.since` is run |
  | --- | --- | --- |
  | `fail`, `warn`, `warn` | `warn` | 2nd |
  | `fail`, `error`, `pass`, `fail` | `fail` | 4th (an error never hides a recovery) |
  | `warn`, `error`, `error`, `warn` | `warn` | 1st |
  | `fail`, `error`, `error` | `error` | 2nd |
  | `error`, `fail`, `error` | `error` | 3rd |
  | `error`, `error`, `fail` | `fail` | 3rd (the errors before it never extend it) |
  | `skipped`, `fail`, `skipped`, `fail` | `fail` | 2nd (`skipped` is passed over like `error`) |

**P4: `since` agrees with `/history`** `must`
- Given `interrupted`
- Then for every check in `GET /api/v1/checks` whose `latest` is not null,
  `latest.since` equals the value computed from `/checks/{id}/history`
  by the rule in "`LatestResult.since`". Walk the entries newest first.
  When `latest.outcome` is evaluated, pass over `error` and `skipped`
  entries, stop at the first other entry whose outcome differs, and take
  the `started_at` of the last entry passed whose outcome equals
  `latest.outcome`. Otherwise take the leading streak of
  `latest.outcome` itself. *(REFINE)*
- And `GET /api/v1/checks/{id}` gives the same `since` as `/checks` for
  each of them.
- And given two runs with an **identical** `started_at` (ids `…0001` and
  `…0002`, as in spec 002 L3) where the check's outcome is `fail` in
  `…0001` and `pass` in `…0002`, `latest.outcome == "pass"` and `since`
  is that shared `started_at`.

**P5: `since` does not cost a query per check** `should`
- Given 500 checks with 50 recorded runs each (written directly to the
  store)
- When `GET /api/v1/checks`
- Then the number of SQL statements issued is independent of the number
  of checks (counted with a SQLAlchemy `before_cursor_execute` listener),
  and the request completes in under 2 s on SQLite in CI.

**P6: an explicit `id:` keeps its streak across an expression edit**
`should` *(REFINE, data-steward; settles Q3)*
- Given `retail` with `id: customer-email-completeness` added to the
  `missing_percent(email) < 5%` check in `checks/sales/customers.yml`,
  then `tablewatch run` (run A, `fail`, value 20.0)
- And the expression changed to `missing_percent(email) < 15%`, then
  `tablewatch run` (run C, still `fail`)
- When `GET /api/v1/checks/customer-email-completeness`
- Then `latest.run_id == <run C id>` and `latest.since == <run A
  started_at>`, and its `/history` lists C then A, with `expression`
  `missing_percent(email) < 15%` and then `missing_percent(email) < 5%`.

**P7: an error row still says what the data last showed** `should`
*(REFINE, data-steward)*
- Given A, B, E (`interrupted` before F)
- When `GET /api/v1/checks`
- Then `b1ceb8262d8b5441` has `latest.outcome == "error"` and
  `latest.last_evaluated == {"outcome": "fail", "started_at": <run B
  started_at>, "since": <run A started_at>}`.
- And `32c8f939b90f6367` has `latest.last_evaluated.outcome == "pass"`.
- And every check whose `latest.outcome` is `pass`, `warn` or `fail` has
  `latest.last_evaluated == null`. So does a check whose every recorded
  result is `error`.

### Serving the web UI

**W1: `GET /` is the UI** `must`
- Given `serve` on `retail`
- When `GET /` with `Host: 127.0.0.1:<port>`
- Then 200, `Content-Type: text/html; charset=utf-8`, and a body that is
  the committed `src/tablewatch/webapp/static/index.html`.
- And the JSON placeholder from spec 002 (`{"name": "tablewatch", …}`) is
  gone.

**W2: assets are served with the right types** `must`
- Given the `script` and `link rel="stylesheet"` URLs in the served
  `index.html`
- When each is requested
- Then 200, with `Content-Type: text/javascript` (charset optional) for
  `.js` and `text/css` for `.css`, **whatever the host's `mimetypes`
  table says**. `X-Content-Type-Options: nosniff` is on every response,
  and a module script served as `text/plain` would be refused by the
  browser.
- And every asset path in `index.html` is under `/assets/` and carries a
  content hash in its file name.

**W3: client routes fall back to the UI** `must`
- When `GET /checks/b1ceb8262d8b5441`, `GET /runs`, or `GET /anything/deep`
- Then 200 with the same `index.html` as W1. Later pages (I-05, I-04,
  I-15) are client routes, and a reload or a pasted link must work.
- And the UI renders a "page not found" view with a link to the overview
  for any path it does not know. In this increment that is every path
  but `/`.

**W4: `/api` stays JSON** `must`
- When `GET /api`, `GET /api/`, `GET /api/v1`, `GET /api/v1/nope`, or
  `GET /api/v2/checks`
- Then 404 with the JSON error envelope `{"error": {"code": "not_found",
  …}}`, never `index.html`.
- And every existing `/api/v1` scenario from spec 002 still passes
  unchanged, apart from the `GET /` placeholder, which W1 replaces.

**W5: missing files are 404, not the UI** `must`
- When `GET /assets/does-not-exist.js`, or `GET /favicon.png` when no such
  file ships
- Then 404 with the JSON error envelope. A path whose last segment has a
  file extension never falls back to `index.html`, because a script tag
  that gets HTML back fails confusingly.

**W6: read-only** `must`
- When `POST /`, `PUT /assets/<any>`, `DELETE /checks/x`, or `OPTIONS /`
- Then 405 with the JSON error envelope, as on the API.
- And *(`should`)* `HEAD /` behaves as `HEAD` does on the API (405,
  spec 002 decision 3). If the security-reviewer prefers HEAD allowed on
  UI paths, it is allowed on all of them consistently (Q5).

**W7: the startup line points at the UI** `must`
- When `serve` starts on `retail` with `--port 0`
- Then stderr has exactly one line matching
  `tablewatch serve: http://127\.0\.0\.1:\d+/ \(project retail-example, 18 checks; API at /api/v1\)`.
- And README "Serve results over HTTP" shows the new line (data-steward).

**W8: an installation without the bundle still serves the API** `should`
- Given the package with `webapp/static/index.html` removed
- When `serve` starts and `GET /`
- Then `serve` still starts, logs one warning at startup
  (`tablewatch: warning: web UI not found in this installation — serving the API only`),
  and `GET /` is 404 with the message
  `web UI not installed — the API is at /api/v1`. `/api/v1` works.

### The overview page

Labels below are the meaning required. The exact wording, layout and
styling are the ui-engineer's, recorded in `docs/UI_SPECIFICATION.md`.
Where a scenario quotes text in quotation marks, the test asserts it.

**O1: problems first** `must`
- Given `recorded`
- When the overview renders
- Then the check list has 18 rows in the order: the 6 `fail`s, then the 2
  `warn`s, then the 10 `pass`es. Within a group the order is the API's
  (project file order).
- And given `interrupted` without run F (so A, B, E), the order is the
  4 `fail`s, the 5 `error`s, the 2 `warn`s, then the 7 `pass`es.
- And the full order is always `fail`, `error`, `warn`, no result,
  `skipped`, `pass`.

**O2: `error` and `fail` never look alike** `must`
- Given A, B, E (as in O1)
- Then an `error` row and a `fail` row differ in **text label**
  ("Error" versus "Fail"), in **icon**, and in **colour**. A test asserts
  the label and the icon's accessible name, not the colour alone.
- And an `error` row states that tablewatch could not evaluate the check
  (for example "Could not evaluate"), and shows `latest.message`
  (`IO Error: Cannot open database …`) as text. It does not show
  `display_value` (`"—"`) as if it were a measured value.
- And the summary counts `error`s separately from `fail`s: "4 failing",
  "5 errors", never "9 failing".
- *(REFINE)* And the summary's error count, and every error row, carry the
  words "could not evaluate" (case-insensitive) as visible text or as the
  accessible description. In a data team "5 errors" is easily read as
  "5 errors in the data", which is the opposite of what it means. The
  label stays "Error", the CLI's word, so that Sam and Dana use one
  vocabulary.
- *(REFINE, `should`, with P7)* And the error row for `b1ceb8262d8b5441`
  says the last evaluated result was a failure, with its age ("Last
  evaluated: Fail", "failing since" run A). The error row for
  `32c8f939b90f6367` says it last passed. The summary does not move these
  checks into the failing count, but the error count notes how many were
  failing when last evaluated ("2 were failing").

**O3: no result is unknown, never healthy** `must`
- Given `recorded` with `checks/sales/customers.yml` line 6 changed to
  `- missing_percent(email) < 10%:` and `serve` restarted (spec 002 L2),
  which gives check `e41cf32f07f328c3` with `latest: null`
- Then that row is labelled "No result recorded", with a neutral
  (not green, not success) style and an icon distinct from pass. It
  sorts after `warn` and before `pass`.
- And the summary counts it under "No result", not under passing.
- And no element of the page presents the project as healthy while any
  check has no result. A test asserts that the summary never shows an
  all-clear message when the no-result count is non-zero.
- *(REFINE)* And the summary reads 5 failing, not 6. The old id
  `b1ceb8262d8b5441` still has a `fail` in the store, but its check is no
  longer in the files, so it is neither listed nor counted. The summary
  counts only loaded checks, and says so: its heading or caption names the
  scope, for example "Latest result of each of the 18 checks".
- *(REFINE)* And an all-clear message (for example "All checks passing")
  appears **only** when every loaded check's latest outcome is `pass`,
  `ok` is true, and there is at least one check. A test covers each of
  the three conditions failing on its own.
- *(REFINE)* And a `skipped` latest result, which the engine does not
  produce today, has its own label ("Skipped") and count. It never counts
  as passing, and the summary's counts always add up to the number of
  loaded checks.

**O4: the age of every latest result** `must`
- Given `recorded`, with the browser clock fixed at run B's `started_at`
  plus 3 hours
- Then each row with a result shows its age relative to now: "3 hours
  ago" for the 14 sales checks, and "3 hours ago" for the inventory checks
  too (A and B are seconds apart). The exact `started_at` is available as
  a machine-readable `<time datetime="…">`, and in full on hover or
  focus.
- And rows for checks whose `latest.run_id` is not the newest run's id
  (the 4 inventory checks) carry a note that they were **not in the
  latest run**. *(`should`)* *(REFINE: this note must be quiet, as
  secondary text and not a status colour or icon. A project that runs its
  folders on different schedules has it on most rows, all the time. The
  row's age is the signal that must not be missed.)*
- And a `started_at` in the future of the browser's clock (clock skew)
  shows as "just now", never as a negative age. *(`should`)*
- *(REFINE)* **Ages are elapsed time, not calendar days.** They are computed
  from the difference in epoch milliseconds and rounded **down**, so
  "2 days" means at least 48 hours. A DST change or the viewer's time zone
  never changes an age. The rounding rule and the unit boundaries (under
  one minute "just now", then minutes, hours, days) are recorded in
  `docs/UI_SPECIFICATION.md`. Tests put the clock a few seconds past an
  exact multiple, so rounding down is what they assert.
- *(REFINE)* **Absolute times are shown in the viewer's time zone, with the
  zone stated.** With the test's time zone set to `Asia/Singapore`, a
  `started_at` of `2026-09-26T06:56:12.000000+00:00` shows its hover or
  focus text with `14:56` and an explicit zone marker (`GMT+8`, `SGT` or
  `+08:00`), never a bare `14:56` or `06:56`. The `<time datetime>`
  attribute carries the API's UTC string unchanged. Sam in Singapore and
  Dana's server in UTC must not disagree about when a run happened, and
  `tablewatch runs` already labels its column `STARTED (UTC)`.

**O5: failing since** `must`
- *(REFINE: rewritten. In PLAN, A, B, E and F were seconds apart, so the
  test could not tell `since` from `started_at`.)* Given a component
  fixture of `/checks` where `fc9cc3088acaf77a` has `latest.started_at =
  2026-09-26T06:00:00.000000+00:00` and `latest.since =
  2026-09-19T06:00:00.000000+00:00`, with the clock fixed at
  `2026-09-26T09:00:05Z`
- Then its `fail` row shows that the latest result is 3 hours old **and**
  that it has been failing for 7 days ("failing since" or "failing for",
  the ui-engineer's choice), with the 7 days taken from `latest.since`.
  Both ages are visible without hovering.
- And for `interrupted` itself (values from the API), the `fail` rows for
  `fc9cc3088acaf77a` and `b1ceb8262d8b5441` both show a "failing since"
  age taken from run A's `started_at`.
- And given A, B, E, the `error` row for `b1ceb8262d8b5441` shows a
  "could not evaluate since" (or equivalent) age based on run E. It never
  says "failing since" for the error itself.
- And `warn` rows show their `since` ("warning since"), while `pass` and
  no-result rows do not show one.
- *(REFINE)* And the wording claims no more than the records show:
  "failing since <age>" or "failing in every evaluation since <age>", never
  "failing continuously". Runs happen at intervals, and passed-over errors
  sit inside the streak. The history (I-05) shows the gaps.

**O6: the project banner and an honest failure count** `must`
- Given `broken`
- Then a banner at the top says a check file has errors and that its
  checks are missing from the page and the counts. It lists
  `checks/sales/orders.yml:11:30` with the message
  `expected a number, found '<'`.
- And the summary's failure count reads 5, **with a marker right next to
  it** saying it is incomplete, which links or points to the banner. Sam
  must not read "5 failing" as the whole truth when six checks are
  failing.
- *(REFINE)* And the marker also covers the total and the passing count,
  or the summary as a whole ("17 checks loaded, incomplete"). A missing
  check could have been in any category, and "10 passing" is also not the
  whole truth.
- *(REFINE)* And given `broken-yaml`, the banner lists
  `checks/sales/orders.yml:24:1` and its message, the list has 9 rows, the
  failure count reads 2 with the marker, and neither the banner nor any
  count states how many checks are missing. The UI cannot know how many
  there are, so the banner says checks from that file **may** be missing,
  not "1 check is missing".
- And given `recorded` (where `ok` is true), neither the banner nor the
  marker is shown.
- And warnings (severity `warning`) in `project.diagnostics` are listed in
  the banner under the errors when `ok` is false. When `ok` is true and
  there are only warnings, they appear in a quieter, collapsible notice.
  *(`should`)*

**O7: when the check files were loaded** `must`
- Given any fixture
- Then the page header shows the project name (`retail-example`), the
  tablewatch version (`project.version`), and the age of `loaded_at`
  ("check files loaded 3 hours ago"). The full timestamp is in a
  `<time datetime>`, available on hover or focus.

**O8: the latest run** `must`
- Given `recorded`
- Then a latest-run panel shows run B's age, its trigger `cli`, its
  outcome `fail`, its counts (14 checks: 7 pass, 1 warn, 6 fail, 0
  error), and its selection as "paths: checks/sales".
- And for a run whose `selection` is `{}`, it says "all checks".
- *(REFINE)* And the panel's counts are labelled as that run's, for
  example "This run: 14 checks", and are visibly separate from the
  summary, which covers every loaded check. In `recorded` the two
  disagree: warn is 1 in the panel and 2 in the summary. Neither may be
  captioned in a way that makes them read as the same thing.
- *(REFINE)* And given A, B, E, the panel shows run E: outcome `error`,
  5 checks with 5 errors, selection "paths: checks/sales/customers.yml".
  It says the run could not evaluate its checks, and it does not say that
  the run failed.
- *(REFINE)* And when the selection has more than one key, every key is
  shown ("paths: checks/sales; tags: pii"). A key the UI does not
  recognise (C1, Q2) is shown with its raw name and values, never dropped.
  A narrowed run must not look like "all checks".
- And given a store with no runs for this project, the panel says no
  runs are recorded yet and names the command (`tablewatch run`). Every
  check row is "No result recorded", and nothing shows as passing.

**O9: API failures are shown, not blank** `must`
- Given `GET /api/v1/checks` answering 503 `store_unavailable`
- Then the page keeps its header and shows the error's `message`
  (`results store: unavailable — see the server log`), with a way to try
  again. It shows no counts, and no stale or empty list that could pass
  for "nothing failing".
- And a network failure (the fetch rejects) shows a comparable message.

**O10: refresh** `should`
- Given the overview is open
- When the user activates "Refresh"
- Then `/project`, `/checks` and `/runs?limit=1` are fetched again and
  the page re-renders. There is no automatic polling (non-goal).

**O11: accessible in light and dark** `should`
- The page uses semantic landmarks (`header`, `main`) and a real list or
  table for checks. Everything interactive is reachable and operable by
  keyboard, with a visible focus indicator. Text and status colours meet
  WCAG AA contrast in both `prefers-color-scheme: light` and `dark`.
  Status is never conveyed by colour alone (O2, O3). The ui-engineer
  records how this was checked.

### Security

**X1: the DNS-rebinding guard covers the UI** `must`
- Given `serve` on the default loopback bind
- When `GET /` or `GET /assets/<file>` with `Host: evil.example`
- Then 403 `forbidden_host` (JSON envelope), exactly as on `/api/v1`.

**X2: a strict Content-Security-Policy** `must`
- When `GET /` (and on every other response)
- Then the response carries
  `Content-Security-Policy: default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'`,
  or a stricter policy the security-reviewer approves. It never contains
  `'unsafe-inline'`, `'unsafe-eval'`, or any host other than `'self'`.
- And the existing security headers (spec 002 decision 13) are still on
  every response, including `X-Frame-Options: DENY`.
- And the served `index.html` contains no inline `<script>` (every
  `script` has a same-origin `src`), no inline `style` attribute or
  `<style>` element, and no `http:` or `https:` URL in any `src` or
  `href`.

**X3: nothing loads from a third party** `must`
- Given the committed bundle
- Then no file under `src/tablewatch/webapp/static/` references a
  third-party origin for loading: no web fonts, CDN scripts, analytics,
  or remote images. URL strings inside library error messages are
  allowed. What X3 forbids is anything the page would fetch.
- And the frontend makes requests only to relative, same-origin `/api/v1/…`
  paths, through the one typed client (`api.ts`).
- And no `.map` source-map files ship in the static directory. *(`should`)*

**X4: data values render as text** `must`
- Given a check file

  ```yaml
  # checks/sales/customers.yml, one more check
    - row_count > 0:
        name: "<img src=x onerror=alert(1)>"
  ```

  and a recorded `error` result whose `message` is
  `<script>alert(1)</script>`
- Then the name and the message render as literal text: no element is
  created from them, and no script runs. The frontend has no
  `dangerouslySetInnerHTML`, `innerHTML` or `eval` (a lint rule or a grep
  test enforces this).

**X5: no path escapes the static directory** `must`
- When `GET /../tablewatch.yml`, `GET /%2e%2e/tablewatch.yml`,
  `GET /assets/..%2f..%2fserver%2fapp.py`, `GET /assets/%2e%2e/%2e%2e/_version.py`,
  or `GET /static/index.html`
- Then none returns a file from outside `webapp/static/`. Each gets
  either the UI (a client-route fallback for paths without an extension)
  or a 404 envelope. It never returns 500, and never returns Python
  source or `tablewatch.yml`.
- And a symlink inside the static directory that points outside it is
  not followed. *(`should`; the committed bundle has none, and the
  wheel carries none)*

### Packaging and CI

**K1: the wheel carries the UI** `must`
- Given `uv build`
- Then the wheel contains `tablewatch/webapp/static/index.html` and every
  file that `index.html` references. A CI step fails the build when one
  is missing (carried requirement I-03 (g), from iteration 1).
- And *(`should`)* CI installs that wheel with the `server` extra into a
  fresh virtual environment, starts `serve --port 0` on a minimal
  project, and gets 200 `text/html` from `GET /`.

**K2: the committed bundle is the built bundle** `must`
- Given CI with Node from `frontend/.nvmrc`
- When the frontend job runs `npm ci`, the type check (`tsc --noEmit`,
  strict), the tests (`vitest run`) and `vite build`
- Then all pass, and `git diff --exit-code -- src/tablewatch/webapp/static`
  is empty. A frontend change without a rebuilt bundle, or a hand-edited
  bundle, fails CI.

**K3: generated types match the contract** `must`
- When the frontend job regenerates the TypeScript types from
  `docs/api/openapi.json`
- Then `git diff --exit-code` on the generated types file is empty.
  Together with the existing Python drift test this chains
  models → `openapi.json` → `types`, so the UI cannot silently drift from
  the API.

**K4: frontend supply chain** `must`
- `frontend/package-lock.json` is committed and CI installs with `npm ci`
  only.
- The runtime dependencies are **`react` and `react-dom` only**. Build and
  test tools (Vite, the React plugin, TypeScript, vitest, a DOM
  implementation for tests, Testing Library, an OpenAPI-to-TypeScript
  generator) are `devDependencies`. The PR names each one with a reason
  (ui-engineer principle 6). Adding a router, a component kit, a CSS
  framework, a chart library or a date library needs its own argument,
  and this page needs none of them.
- *(`should`)* Install scripts are disabled (`ignore-scripts=true` in
  `frontend/.npmrc`) if the build works without them, and
  `npm audit --audit-level=high` passes in CI.

### Test harness

**H1: `serving()` never hangs on a noisy server** `must`
- Given the process-test helper `serving()` in `tests/`, and `serve`
  started with access logging on (the default)
- When a test makes 2,000 requests (about 200 KB of access log, well past
  a 64 KiB pipe buffer)
- Then every request completes, and the helper keeps draining stderr
  after the startup line (carried requirement I-03 (e)). The lines it
  collected stay available to the test.

## Non-goals

- **No check detail page** (history chart, SQL, source: I-05). Overview
  rows may be ready to link to it, but no link goes anywhere yet.
- **No check explorer, tree, filters or search** (I-04). The overview
  lists every loaded check. A project large enough to need navigation
  waits for I-04.
- **No run detail or run list page, and no run diff** (I-15).
- **No charts.** The first chart is I-05's, and it loads the dataviz skill
  there.
- **No automatic refresh or polling, and no push.** O10 gives a manual
  refresh.
- **No authentication, tokens or TLS** (Phase 4, F1 and F2). The UI is
  covered by the same loopback default and the same `--host` warning.
- **No hosting under a URL prefix** (for example behind a proxy at
  `/tablewatch/`). The bundle assumes it is served at `/`, and a later
  item can add a base path.
- **No theme switcher.** The page follows `prefers-color-scheme`.
- **No new API endpoints.** `since` is the only contract addition, and
  `rules`, SQL and source stay I-05's.
- **No hot reload of check files.** O7 tells Sam how old they are.
- **No browser end-to-end framework** (Playwright or similar). Component
  tests plus the data-steward's run against a real `serve` cover this
  page, and a browser framework is a large dependency to justify later.
- **No change to what the CLI's `runs` and `history` show** (I-19).

## Design notes

### Constraints from CLAUDE.md

- **Rule 6 (secrets).** `serve` still never calls `create_engine_for`, and
  neither does the bundle. The UI reads only `/api/v1`, which exposes
  datasource names and types, never settings. The frontend must not use
  `import.meta.env` values beyond Vite's built-in `MODE`/`PROD`, so that
  nothing from the build machine's environment is baked into the wheel.
- **Rule 7 and the exit codes.** Unchanged. `serve` keeps spec 002's
  codes (3 when it cannot start, 0 on a clean stop). A missing bundle is
  not a reason to exit (W8).
- **Rule 2.** `since` is found by comparing outcomes and taking a
  timestamp. It needs no date arithmetic in SQL. Ages ("3 hours ago") are
  computed in the browser from ISO timestamps.
- **Rules 1, 3, 4 and 5** are not touched: no metric, planner, loader or
  dialect change.
- **Results store.** `since` is a read. If the tech lead adds an index to
  make it cheap, that is a model change and needs an Alembic revision.
  `(project, started_at)` is already planned for I-14, and the
  `(check_id, …)` side would be new. The store reads stay on
  `ResultStore`, and the server package still holds no SQL.
- **Check identity** is not touched.
- **CLAUDE.md's module table** needs a row for `webapp/` (the tech lead
  owns that file).

### Decisions made in PLAN

- **D1 (revised in REFINE by the data-steward): an `error` does not end
  a streak of evaluated outcomes.** PLAN's rule reset "failing since" on
  every error. Reasons for the change:
  1. **Understating age is the dangerous direction.** A three-week defect
     shown as "failing for 1 day" gets triaged as new, and Ravi's evidence
     of how long a control has been breached is wrong. Overstating needs
     the data to be fixed and then broken again inside an unobserved gap.
     The data was bad on both sides of that gap, and any `pass` in it still
     ends the streak.
  2. **Outages are routine.** Maintenance windows, credential rotation and
     timeouts all happen. With nightly runs and a weekly maintenance
     window, PLAN's rule could never show more than a week.
  3. **Honest outcomes cut the other way.** `error` is Dana's channel and
     says nothing about the data. Letting it reset Sam's claim about the
     data mixes the two channels that VISION keeps apart.
  4. **Never cry wolf (I-06).** I-06 must share this definition. Under
     PLAN's rule every blip would alert Sam to a "new" failure on
     fail → error → fail. Under this one, the blip alerts Dana (→ error)
     and then Sam hears nothing new.

  The error stays fully visible. It is `latest` while it lasts (O2), it is
  in `/history`, and P7's `last_evaluated` stops it from hiding a known
  failure. The wording rule in O5 keeps "since" from claiming continuity.

  *PLAN's text, kept for the record:* **`since` is on the API, and an
  `error` ends the run.** Deriving it
  in the browser would cost one `/history` request per check on the page,
  18 today and hundreds in a real project. Priya's portal would also have
  to re-implement the rule. It is additive (spec 002 finding F-S). On the
  semantics, `fail` and `error` go to different people (VISION: honest
  outcomes), so "failing since" must not bridge a period in which
  tablewatch did not know. This matches Grafana's default. The cost is
  that an intermittently unreachable database keeps resetting "failing
  since"; the full history (I-05) shows what came before. **I-06 must use
  the same definition of a run of outcomes for state changes, or state
  why not.** Otherwise the page would say "failing since Tuesday" while
  the alert said "failing again".
- **D2: CI builds the frontend** (setup-node) rather than trusting the
  committed bundle. The bundle is still committed so that the server and
  every Python-only contributor need no Node (ui-engineer principle 7),
  and CI proves that it is the bundle the sources produce (K2). Without
  it, `tsc` and the frontend tests would run only on a laptop, and the
  definition of done ("for UI work also `tsc` and `vite build`") would
  not be enforced. Node is pinned in `frontend/.nvmrc`. The PM suggests
  the current LTS line (24). The local toolchain is Node 25 in the
  `pystructurizr` conda env, and K2 shows whether the two produce the
  same bundle (Q7).
- **D3: the overview reads three endpoints**: `GET /project`,
  `GET /checks` and `GET /runs?limit=1`. The summary counts are computed
  in the browser from `/checks` (every loaded check's latest). They are
  not the latest run's counts, which describe only what that run selected.
  Both are shown, and they answer different questions.
- **D4: the static directory is `src/tablewatch/webapp/static/`**, per the
  ui-engineer brief. Served files are read through `importlib.resources`,
  so they also work from an installed wheel.
- **D5: the bundle is marked generated** in `.gitattributes`
  (`linguist-generated`), so a PR's review shows the sources and collapses
  the build output.

### Design decisions (settled in REFINE)

Reviews: architect approve-with-followups; security-reviewer
approve-with-followups; data-steward refined P2–P7 (an `error` or
`skipped` result does not end a streak of evaluated outcomes); ui-engineer
consulted. These supersede the open questions below and any scenario text
they contradict.

**Contract (tech lead)**

1. **`since` and `last_evaluated` are computed in Python** from one query
   that returns every result of the project, newest first per check, in
   history order `(started_at, run id)` desc (rule 2: SQL fetches, Python
   does the math). The data-steward's rule (P3, P4) needs "pass over
   errors" logic that a portable window query cannot express cleanly. The
   query count is constant in the number of checks (P5). The rule lives in
   one pure function in `results/state.py`, which I-06's state-change
   alerts will reuse. `/checks` and `/checks/{id}` both go through
   `ResultStore.latest_results(project, check_id=None)` (one path, P4).
   No index and no Alembic revision; `runs.project` indexing stays with
   I-14.
2. **Outcomes compare as recorded strings.** An outcome unknown to this
   version is served as `error` (spec 002) and treated like `error` for
   streaks.
3. **`selection`** stays `dict[str, list[str]]` on the wire, documented
   with the five named optional keys plus `additionalProperties` (array
   of strings); unknown keys pass through (Q2: keep). Key names are
   derived from `selection.Selection`.
4. **Timestamps** serialise with six fractional digits and carry
   `format: date-time`. The JSON report keeps its own format (its own
   `schema_version`); aligning it is a backlog item.
5. **Error statuses** 400, 403, 404, 405, 500, 503 are declared on every
   operation from one table in `routes.py`.

**Serving (architect DD6–DD9, security-reviewer)**

6. The bundle lives in `src/tablewatch/webapp/static/`, entirely Vite
   output (`emptyOutDir: true`); `webapp/` holds no Python. Read with
   `importlib.resources`; uv_build already ships non-Python files.
7. `server/ui.py` loads the bundle **once at startup** into an in-memory
   map, URL path → (bytes, content type): regular files only, no
   symlinks, no dotfiles, real path inside the directory, and only the
   suffixes `.html .js .css .svg .png .ico .woff2 .txt` with fixed
   content types. Requests are served by exact lookup; no filesystem
   path is ever built from a request (X5 closed by construction).
8. One `GET /{path:path}` route, registered last and out of the schema,
   answers in order: an exact file; `/api` or `/api/*` → 404 envelope;
   a last segment with an extension → 404; otherwise `index.html`. All
   inside the existing app and `_Guard`. A side effect: non-GET requests
   to **any** unmatched path, including unknown `/api/*` paths, are now
   405 (spec 002 answered 404) — accepted, consistent with W6.
9. `create_app(context, *, allowed_hosts=(), ui=None)`; the CLI loads the
   bundle and logs W8's warning; with no bundle, `GET /` is the W8 404.
10. **CSP on every response** (added to the security headers):
    `default-src 'none'; script-src 'self'; style-src 'self'; img-src
    'self'; font-src 'self'; connect-src 'self'; base-uri 'none';
    form-action 'none'; frame-ancestors 'none'` — no `data:` because the
    build sets `assetsInlineLimit: 0`. Plus `Cross-Origin-Opener-Policy:
    same-origin`. No `upgrade-insecure-requests` (loopback is http).
11. **`Cache-Control: no-store` everywhere**, assets included (Q5):
    nothing measurable is gained on a loopback server. HEAD stays 405.

**Frontend and supply chain (ui-engineer, security-reviewer)**

12. Runtime dependencies are `react` and `react-dom` only. Dev: vite,
    typescript 5.9, @types/react, @types/react-dom, vitest, jsdom,
    @testing-library/react, @testing-library/dom, openapi-typescript. All
    pinned exactly, lockfile committed, generated from a clean install
    and checked for the Linux native optional packages.
13. `frontend/.npmrc`: `ignore-scripts=true` and `engine-strict=true`
    (`must`). `.nvmrc` pins an exact Node 24 version; local builds use
    the conda env `tablewatch-node` (Node 24.13.0) — never c4studio's
    `pystructurizr` env. The frontend is built in a shell without
    warehouse credentials.
14. Vite: `base: '/'`, `sourcemap: false`, `assetsInlineLimit: 0`,
    `modulePreload.polyfill: false`, no `public/`, no plugin-legacy,
    `emptyOutDir: true`. No PWA plugin, no service worker, no web storage
    for API data (`must`). `@license` comments kept.
15. **CI**: `permissions: contents: read` on the workflow. A separate
    `frontend` job (setup-node from `.nvmrc`): `npm ci`, `npm audit
    signatures`, `npm audit --audit-level=high`, types regenerated, `tsc`,
    `vitest run`, `vite build`, then `git diff --exit-code` **and**
    `git status --porcelain --untracked-files=all` on the static
    directory and the generated types (K2, K3). CI never commits. The
    Python job stays Node-free.
16. Python-side checks over the committed bundle (pytest): K1 (the wheel
    carries `index.html` and exactly the files it references, plus an
    allowlist), X2 (no inline script or style, no remote URLs), X3 (no
    `.map` files, no absolute build paths such as `/Users/` or
    `/home/`), and a lockfile check (every `resolved` URL is
    `https://registry.npmjs.org/…` and every package has an `integrity`).
17. `frontend/node_modules/`, `frontend/.env*` and `*.tsbuildinfo` go in
    `.gitignore`; `[tool.mypy]` excludes `^frontend/`. `.gitattributes`
    marks the bundle `linguist-generated` with `eol=lf`.

**Deferred to the backlog**: `immutable` caching for hashed assets; the
JSON report's timestamp format; a save-time state table if history grows
past one scan per request.

### Open questions for the tech lead and the architect (REFINE)

1. **Q1: computing `since`.** One query for all checks, with window
   functions (SQLite ≥ 3.25 and Postgres both have them), or an extension
   of `latest_results`. For `/checks/{id}`, reuse the same method rather
   than scanning its history in Python. P5 bounds the cost. Is an index
   on `tablewatch_check_results (check_id, run_id)` warranted? If it is,
   that means a revision.
2. **Q2: unknown `selection` keys.** Named keys plus
   `additionalProperties: array of string` (the PM's preference), or
   strictly five keys, with unknown keys dropped?
3. **Q3 (data-steward): an expression edit under an explicit `id:`.**
   Does it end the run of outcomes for `since`? The PM's position is that
   it does not, because the id is the user's statement of continuity.
   The history entries carry `expression`, so the other rule is also
   implementable. *(REFINE, data-steward: agreed, it does not end the
   streak. See P6.)*
4. **Q4: mounting.** A static route inside the existing `_Guard`, so the
   host check, security headers and CSP apply to every file. SPA fallback
   applies only to `GET` requests whose path does not start with
   `/api/` (or equal `/api`) and whose last segment has no extension.
   Explicit MIME types for `.js`, `.css`, `.svg`, `.json` and `.woff2`
   (W2). Starlette's `StaticFiles` follows no symlinks by default.
5. **Q5 (security-reviewer): `HEAD` on UI paths**, and **caching of the
   hashed assets**. `Cache-Control: no-store` stays on `/api/*` and on
   `index.html`. Content-hashed `/assets/*` could be
   `public, max-age=31536000, immutable`, because they carry no data.
   Keep `no-store` everywhere unless the reviewer is content.
6. **Q6: the CSP on API responses.** Applying X2's header to every
   response is simplest and harmless for JSON. Confirm that it does not
   interfere with anything.
7. **Q7: bundle reproducibility.** If `vite build` output differs between
   macOS/Node 25 and Linux/Node 24, K2 would fail on every PR. Pin the
   local build to the `.nvmrc` version, or have CI's build be the
   committed one. Raise it; do not weaken K2 silently.
8. **Q8: the startup line** (W7) changes text that the README documents
   and that `serving()` parses. It is human-facing, not a contract, so
   the change is fine. Update the harness regex with it.

### Traps for the data-steward in REFINE

- The summary counts only **loaded** checks' latest results. The latest
  run panel shows only what that run selected. They disagree whenever a
  run was narrow (`recorded`: the summary says 6 failing and run B also
  says 6, but warn is 2 in the summary and 1 in run B). Check that the
  wording makes the difference obvious.
- A check whose latest result is old (the inventory checks in `recorded`)
  is easily mistaken for current. O4's "not in the latest run" note is
  the guard.
- `since` resets on an `error` (D1). Check that Sam, reading "failing
  since" on a check that failed for a week with a one-off error
  yesterday, is not misled. The row shows the age of the latest result,
  and I-05 will show the history. Say whether the overview needs more
  than that.
- Freshness values vary with build time (spec 002). Do not assert them in
  fixtures.
- `display_value` is `"—"` on `error`. The row should show the message,
  not an empty-looking value.

## Reviewers required

- **qa-engineer**: always. Focus: the static serving edge (traversal,
  encoded paths, extensions, `/api` prefixes, methods), `since` under
  ties and concurrent recording, H1, and the wheel check.
- **data-steward**: always. Semantics of `since` (Q3, D1), the wording of
  error vs fail vs no result, the banner and the incomplete-count marker,
  and a hand run of O1–O8 against a real `serve`. It also updates the
  README.
- **security-reviewer**: **required**. The same listening socket now
  serves static files, `GET /` changes, a CSP is introduced, rendered
  content comes from check files and data values (X4), and a new
  dependency ecosystem arrives (npm: runtime `react`/`react-dom`, plus
  build-time tools whose output ships in the wheel). Focus: X1–X5, K4, Q5
  and Q6.
- **architect**: **required**, in REFINE and VERIFY. This touches `src/`
  (the server, the store read for `since`, a new `webapp` package), it
  changes the public API contract (additive `since`, `selection` shape),
  and it adds a build seam between `frontend/` and the Python package.
- **ui-engineer**: builder of `frontend/**`, `docs/UI_SPECIFICATION.md`
  and the static bundle. Consulted in REFINE on the overview scenarios,
  the generated-types approach, and the `since` shape before it is
  built. Does not judge its own work: qa-engineer and data-steward do.

## Size

**M.** Python: two small contract fixes, one store read, static serving
with CSP, and a harness fix. Frontend: scaffold, typed client, one page,
and component tests. CI: one new job and two checks.

**Pre-planned split, if BUILD runs long.** P1–P7 (`latest.since`, `last_evaluated`) and O5
move to a new S item, **I-21 "Failing since"**, which ships next, ahead of
I-05. The overview ships without "failing since" and still shows the age
of every latest result (O4), which meets the carried requirement (4). The
rest stays together. C1–C3 must precede type generation. W, X and K are
what make the UI usable from a wheel, and O is the UI itself. If the
split is taken, the REVIEW records it, and the `since` decision (D1)
carries to I-21 unchanged.
