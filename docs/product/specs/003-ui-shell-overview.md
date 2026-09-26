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
  We adopt the default. An `error` ends a run of `fail`s, so "failing
  since" never claims more than the recorded results show (decision D1).
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
| `latest.since` (P1–P4) | tech lead | `results/store.py`, `server/schemas.py`, `server/routes.py` |
| Serving the bundle: static files, SPA fallback, CSP, `GET /` (W1–W6, X1–X5) | tech lead | `server/app.py`, new `src/tablewatch/webapp/` |
| Startup line and the `serving()` harness (W7, H1) | tech lead, qa-engineer | `cli/main.py`, `tests/` |
| Frontend: shell and overview (O1–O10), `docs/UI_SPECIFICATION.md` | ui-engineer | `frontend/**`, `src/tablewatch/webapp/static/` |
| CI: frontend job, bundle and types drift, wheel contents (K1–K4) | tech lead | `.github/workflows/checks.yml` |
| README "Serve results over HTTP" updated for the UI | data-steward | `README.md` |

**Order inside BUILD.** C1–C3 and P1–P4 come first, then `openapi.json` is
regenerated, and only then does the ui-engineer generate types from it.
This carried requirement (I-03 (d)) exists so that generated types are
never built from the imprecise document.

## The contract changes (additive)

### `LatestResult.since`

```text
LatestResult { run_id, started_at, trigger, outcome, value, display_value, message,
               since: Timestamp }        # new, required, never null
```

`since` is the `started_at` of the **oldest result in the unbroken run of
this check's recorded results that share `latest.outcome`**, reading its
history newest first. Consequences:

- Only results **for this check id in this project** count, the same
  scope as `latest` (spec 002). A run that did not select the check is not
  in its history, so it neither breaks the run nor extends it.
- **Any different outcome ends the run**: `error` ends a run of `fail`s,
  and `warn` ends a run of `fail`s. The sequence `fail (A), fail (B),
  error (E), fail (F)` gives `latest.outcome == "fail"` and
  `since == F.started_at`, not A's. The honest claim is "failing
  continuously, as far as the records show", and during E tablewatch did
  not know (decision D1).
- `since` is present for every outcome, `pass` included, so a client does
  not have to special-case it. `since <= latest.started_at` always, with
  equality when the latest result is the first of its run.
- **An expression edit under an explicit `id:`** does not end the run: the
  user chose the id to keep one history across edits (question Q3 for
  REFINE).
- Ties on `started_at` follow the order `/history` uses, so `since`
  always equals the `started_at` of an entry that `/history` returns (P4).

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
| `b1ceb8262d8b5441` | sales.customers `missing_percent(email) < 5%` | fail (F), error (E), fail (B), fail (A) | F |
| `fc9cc3088acaf77a` | sales.orders `missing_count(customer_id) = 0` | fail (F), fail (B), fail (A) | A |
| `32c8f939b90f6367` | sales.customers `row_count > 0` | pass (F), error (E), pass (B), pass (A) | F |
| `41e58afff9c48a46` | inventory.products `Price feed freshness` | warn (F), warn (A) | A |

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

**P2: an `error` ends a run of failures** `must`
- Given `interrupted`
- When `GET /api/v1/checks`
- Then `b1ceb8262d8b5441` has `latest.outcome == "fail"` and
  `latest.since == <run F started_at>`.
- And `fc9cc3088acaf77a` (not in run E) has `latest.since ==
  <run A started_at>`.
- And `32c8f939b90f6367` has `latest.outcome == "pass"` and
  `latest.since == <run F started_at>`.
- And given only `recorded` plus run E (before F), `b1ceb8262d8b5441` has
  `latest.outcome == "error"` and `latest.since == <run E started_at>`.

**P3: a different outcome ends the run** `must`
- Given a check `row_count` with `warn: when < 100` and `fail: when = 0`
  (sales.orders `Order volume`, `32867fbe86f483f3`), and three runs of this
  project written to the store in order with that check's outcomes
  `fail`, `warn`, `warn`
- Then `latest.outcome == "warn"` and `latest.since` is the second run's
  `started_at`.

**P4: `since` agrees with `/history`** `must`
- Given `interrupted`
- Then for every check in `GET /api/v1/checks` whose `latest` is not null,
  `latest.since` equals the `started_at` of the last item in the leading
  run of `/checks/{id}/history` entries whose `outcome` equals
  `latest.outcome`.
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
  (`IO Error: Cannot open database …`) as text.
- And the summary counts `error`s separately from `fail`s: "4 failing",
  "5 errors", never "9 failing".

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
  latest run**. *(`should`)*
- And a `started_at` in the future of the browser's clock (clock skew)
  shows as "just now", never as a negative age. *(`should`)*

**O5: failing since** `must`
- Given `interrupted`, with the clock fixed at run F's `started_at` plus 2
  days
- Then the `fail` row for `fc9cc3088acaf77a` shows "failing since" with an
  age of 2 days (its `since` is run A), and the `fail` row for
  `b1ceb8262d8b5441` shows 2 days as well (its `since` is run F), taken
  from `latest.since`, not computed from `started_at`.
- And given A, B, E, the `error` row for `b1ceb8262d8b5441` shows an
  "erroring since" (or equivalent) age based on run E.
- And `warn` rows show their `since`, while `pass` and no-result rows do
  not show one.

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

- **D1: `since` is on the API, and an `error` ends the run.** Deriving it
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
   implementable.
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

**Pre-planned split, if BUILD runs long.** P1–P5 (`latest.since`) and O5
move to a new S item, **I-21 "Failing since"**, which ships next, ahead of
I-05. The overview ships without "failing since" and still shows the age
of every latest result (O4), which meets the carried requirement (4). The
rest stays together. C1–C3 must precede type generation. W, X and K are
what make the UI usable from a wheel, and O is the UI itself. If the
split is taken, the REVIEW records it, and the `since` decision (D1)
carries to I-21 unchanged.
