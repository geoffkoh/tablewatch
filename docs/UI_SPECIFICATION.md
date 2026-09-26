# tablewatch web UI specification

Owner: ui-engineer. This document describes what the web UI does. It is
updated in the same PR as the change it describes. Iteration specs in
`docs/product/specs/` say what an increment must do. This file records how
the UI does it: wording, layout, colour, and the rules behind them.

| Increment | Spec | What it added |
| --- | --- | --- |
| I-03 | `specs/003-ui-shell-overview.md` | Shell, overview page, "page not found" |
| I-05 (part 1) | `specs/004-check-detail-history.md` | Check page (`/checks/<id>`): identity, rule, latest result, history chart and table; links from the overview; the shared load hook |

## 1. Who it is for

Sam (data steward) and Alex (analytics lead), who may not read SQL (see
`docs/product/VISION.md`). So:

- Words over codes. The CLI's outcome words (Pass, Warn, Fail, Error,
  Skipped) are kept so that Sam and Dana use one vocabulary. Each word also
  gets a plain-language explanation where it could be misread. "Error"
  always comes with "could not evaluate".
- Problems first, in every list and every summary.
- The UI never claims more than the records show. A check with no result is
  unknown, not healthy. A broken check file makes every count incomplete.
  "Failing since" never says "continuously".

## 2. Build, toolchain, and dependencies

The frontend lives in `frontend/`. Its production build is committed to
`src/tablewatch/webapp/static/`, so the server and the wheel need no Node.

```bash
export PATH="/opt/miniconda3/envs/tablewatch-node/bin:$PATH"   # Node 24.13.0, npm 11.6.2
cd frontend
npm ci                 # installs exactly package-lock.json (install scripts are disabled)
npm run gen:types      # docs/api/openapi.json -> src/api/schema.gen.ts (committed)
npm run typecheck      # tsc --noEmit, strict
npm test               # vitest run
npm run build          # vite build -> ../src/tablewatch/webapp/static/
```

- `frontend/.nvmrc` pins Node `24.13.0`. `package.json` `engines` is
  `^24.13.0`.
- `frontend/.npmrc` sets `ignore-scripts=true` and `engine-strict=true`.
  The build works without any install script. Rolldown and Lightning CSS
  ship their native code as per-platform optional packages, and the
  lockfile records the Linux x64 ones (`@rolldown/binding-linux-x64-gnu`,
  `lightningcss-linux-x64-gnu`, and their `musl` variants).
- The build is deterministic. Two builds from one tree are byte-identical,
  and the file names carry content hashes.
- Do not use the `pystructurizr` conda env. It belongs to c4studio.

### Dependencies (all pinned exactly)

| Package | Version | Kind | Why |
| --- | --- | --- | --- |
| `react` | 19.3.0 | runtime | Component model |
| `react-dom` | 19.3.0 | runtime | DOM renderer. Escapes all text, which X4 relies on |
| `vite` | 8.3.1 | dev | Bundler (Rolldown) and its built-in JSX transform. No React plugin is needed: nothing is developed with hot reload against the committed bundle |
| `typescript` | 5.9.3 | dev | Strict type check. 5.9 because `openapi-typescript` 7 declares `typescript ^5.x` |
| `@types/react`, `@types/react-dom` | 19.3.0 | dev | Types for React 19 |
| `vitest` | 5.0.2 | dev | Test runner. It shares Vite's config and transform |
| `jsdom` | 29.1.1 | dev | DOM for component tests. 30.x needs Node ≥ 24.15, and `.nvmrc` pins 24.13.0 |
| `@testing-library/react` | 16.3.3 | dev | Renders components and queries them by role and accessible name |
| `@testing-library/dom` | 10.4.2 | dev | Peer of the above |
| `openapi-typescript` | 7.13.0 | dev | Generates `schema.gen.ts` from `docs/api/openapi.json` (K3) |

There is no router, component kit, CSS framework, date library, chart
library or icon font. Routing is one pure function (`lib/route.ts`). Dates
use `Date` and `Intl`. Icons and the history chart are hand-written SVG in
JSX. Spec 004 added no dependency.

### Vite configuration (`frontend/vite.config.ts`)

This follows spec 003 decision 14:

- `base: '/'`, `publicDir: false` (there is no `public/`), and `emptyOutDir: true`.
- `sourcemap: false`, so no `.map` files ship (X3).
- `assetsInlineLimit: 0`, so there are no `data:` URLs and the CSP needs no `data:`.
- `modulePreload.polyfill: false`, so `index.html` has no inline script.
- Legal comments are kept in the bundle (`@license` from React and the
  scheduler).
- No plugin-legacy, no PWA plugin, no service worker.

`index.html` then holds exactly one module `<script src>`, one stylesheet
`<link>` and one favicon `<link>`, all under `/assets/` with hashed names.
It has no inline script or style and no absolute URL.

## 3. Architecture

```
frontend/src/
  main.tsx                 mounts <App path={location.pathname}>
  App.tsx                  parseRoute(path) -> Overview | CheckPage | NotFound
  api/schema.gen.ts        GENERATED from docs/api/openapi.json; never edit
  api/types.ts             aliases into schema.gen.ts (Project, CheckSummary, CheckDetail,
                           Rule, Condition, HistoryEntry, HistoryPage, Run, Unit, ...)
  api/api.ts               the ONE client: getProject, listChecks, listRuns, getCheck,
                           getHistory; failureOf, isNotFound
  lib/route.ts             parseRoute(path), checkHref(id), the id pattern
  lib/useLoads.ts          the one load/refresh hook (named slots, generation guard,
                           busy, the minute clock, reload, capture)
  lib/status.ts            statuses, order, labels, SINCE_PREFIX, counting
  lib/rule.ts              a rule in words: ruleParts, ruleSentence, boundaries
  lib/time.ts              ages, absolute times, zone name, axis time labels
  lib/selection.ts         how a run's selection reads
  lib/chart/               the chart's pure functions: scale, ticks, format, domain,
                           bands, series, labels, layout, legend, summary
  components/              Header, ProjectProblems, Summary, LatestRun, CheckTable,
                           LatestResult (Result, When, LastEvaluatedNote), HistoryTable,
                           StatusIcon/StatusBadge, shapes (status shapes), Time (Ago),
                           LoadError
  components/chart/        HistoryFigure (title, key, captions), HistoryChart (SVG and
                           interaction), ChartKey
  pages/Overview.tsx       the overview
  pages/CheckPage.tsx      a check's page
  pages/NotFound.tsx       "Page not found"
  styles/tokens.css        colour tokens, light and dark (status and chart)
  styles/app.css           layout, components and the chart
  test/                    vitest tests and typed fixtures
```

- **The contract chain.** The Pydantic models produce `docs/api/openapi.json`
  (Python drift test), which produces `schema.gen.ts` (`gen:types` and the
  CI diff, K3). `types.ts` holds only aliases into the generated file, and
  the fixtures are typed with them. A contract change therefore breaks
  `tsc`.
- **One client.** Only `api.ts` calls `fetch` (a test enforces this). URLs
  are relative (`/api/v1/...`), with `credentials: 'same-origin'` and
  `cache: 'no-store'`. A non-2xx answer becomes `ApiError` with the
  envelope's `code` and `message`. A rejected fetch becomes a network
  failure with its own message.
- **No web storage** and no service worker. API data lives only in React
  state.
- **Routing** (spec 004, decision 7). The server answers every extensionless
  non-API path with `index.html` (W3). Links are plain `<a href>` and every
  navigation is a full page load: no router, no `pushState`, and the Back
  button just works. `lib/route.ts` maps a path to a page:

  | Path | Page |
  | --- | --- |
  | `/`, `/index.html` | the overview |
  | `/checks/<id>`, `/checks/<id>/` | the check page, when `<id>` is one non-empty segment that decodes (once, inside try/catch) to a string matching `^[A-Za-z0-9][A-Za-z0-9_.:-]*$` of at most 64 characters (the loader's `ID_PATTERN` and the store's column width) |
  | anything else | "Page not found", and **no request is made**: `/checks/`, `/checks/a/b`, `/checks/..`, `/checks/%2e%2e`, `/checks/a%2Fb`, `/checks/a%3Fb`, a malformed `%`, 65 characters |

  `checkHref(id)` is `/checks/` + `encodeURIComponent(id)`. Every API path
  segment and query value is built with `encodeURIComponent` in `api.ts`.
- **One load/refresh hook** (`lib/useLoads.ts`, D14, decision 8). A page
  names its requests as independent slots (the overview: `project`,
  `results`; the check page: `project`, `check`, `history`, `runs`). Each
  slot is `loading`, `ok` or `failed`. `reload` starts every slot again and
  bumps a generation counter; only the newest round writes state, so an
  older answer that lands late is dropped. `busy` holds until every slot of
  the newest round settles. A one-minute timer re-renders ages and fetches
  nothing. `capture()` gives a follow-up request (Load older results) a guard
  that turns false on the next reload, and `generation` tags state a page
  keeps per round, so older pages are dropped on refresh.
- **Shared wording** (D4). `SINCE_PREFIX` lives in `lib/status.ts`, and
  `Result`, `When` and `LastEvaluatedNote` in `components/LatestResult.tsx`.
  The overview's rows and the check page render the latest result with the
  same components, so the words cannot drift.

## 4. The overview page (`/`)

It reads `GET /api/v1/project`, `GET /api/v1/checks` and
`GET /api/v1/runs?limit=1` in parallel (spec 003, D3). Top to bottom:

### 4.1 Header (`<header>`)

- A skip link "Skip to content", which targets `#main` and is visible on
  focus.
- "tablewatch" and `project.version`.
- `project.name` as the page's only `<h1>`.
- "Check files loaded *3 hours ago*": the age of `project.loaded_at`
  (O7). `serve` reads the files once.
- A **Refresh** button (O10). It re-fetches the three endpoints. The page
  never polls. A one-minute timer re-renders the ages and fetches nothing.

If `/project` fails, the header shows "Overview" instead of a project name,
and an error panel explains the failure.

### 4.2 Check-file banner (O6)

When `project.ok` is false, a banner (`<section id="project-problems">`) is
shown above everything else:

- Title: "A check file has errors", or "Check files have errors" when the
  diagnostics span more than one file.
- "Checks from this file may be missing from this page and from every count
  on it, so the counts are incomplete." It says **may**, and never gives a
  number: the UI cannot know how many checks a broken file held.
- Each error as `file:line:col` (monospace) followed by the message.
- Warnings, if any, under a "Warnings" subheading below the errors.
- "`tablewatch serve` reads the check files once, when it starts. Fix the
  file and restart it."

When `project.ok` is true and there are warnings only, a collapsed
`<details>` notice reads "N warnings in the check files". There is no banner
and no marker.

### 4.3 Summary (O2, O3, O6)

Heading "Summary". Caption: "Latest result of each of the *N* checks
loaded". It counts **loaded** checks only. A check id that has results but
is no longer in the files is not counted. When `ok` is false, the caption
ends "(incomplete)", and "incomplete" links to the banner.

Tiles, in problem-first order. Each has an icon, a count and a label:

| Tile | Text | Note |
| --- | --- | --- |
| fail | "*n* failing" | the "incomplete" marker when `ok` is false |
| error | "*n* errors" | "could not evaluate". When error checks were failing at their last evaluation (P7): "; *k* were failing" |
| warn | "*n* warnings" | |
| no result | "*n* no result" | "state unknown" |
| skipped | "*n* skipped" | shown only when *n* > 0 |
| pass | "*n* passing" | the "incomplete" marker when `ok` is false |

The counts always add up to the number of loaded checks. Errors are never
added to failures. An error whose last evaluation failed stays under
errors, and the note mentions it.

**All-clear.** "All checks passing" appears only when all three hold: at
least one check is loaded, every loaded check's latest outcome is `pass`,
and `project.ok` is true. With no checks loaded, the summary says "No checks
are loaded, so there is nothing to report."

### 4.4 Latest run (O8)

Heading "Latest run". This is the newest run from `/runs?limit=1`.

| Row | Content |
| --- | --- |
| Started | age of `started_at` (with "(did not finish)" when `finished_at` is null) |
| Trigger | `trigger` as recorded (`cli`) |
| Outcome | a status badge plus one sentence: fail "The data failed at least one check."; error "tablewatch could not evaluate one or more of its checks."; warn "At least one check warned; none failed."; pass "Every check it ran passed."; skipped "Its checks were skipped." |
| Selected | "all checks" when `selection` is `{}`; otherwise one line per key |

Selection keys come in a fixed order: `paths`, `tags`, `datasources`,
`excludes`, `check ids`, then any unknown key under its raw name in
alphabetical order (C1). An unknown key is never dropped, so a narrowed run
never reads as "all checks".

Below the table: "This run: *N* checks", then a list labelled "This run's
results" with "*a* pass", "*b* warn", "*c* fail" and "*d* error" (plus
"*e* skipped" when non-zero). "This run" keeps these counts from being
read as the summary's.

With no runs: "No runs are recorded for this project yet. Run
`tablewatch run` to record the first results."

### 4.5 Checks, problems first (O1, O2, O4, O5)

Heading "Checks, problems first". This is a real `<table>` with a
visually hidden caption and the columns **Status**, **Check**, **Latest
result** and **When**.

**Order:** fail, error, warn, no result, skipped, pass. The sort is stable,
so within a status the API's order (project file order) is kept.

- **Status:** a badge with an icon and a label (§5).
- **Check:** the name, as a link to the check's page (`checkHref(id)`, D1).
  The expression follows in monospace when it differs from the name, then
  the dataset and `source` (`file:line:col`). The row's text and layout are
  otherwise unchanged (D18).
- **Latest result:**
  - pass, warn, fail: `display_value`, then `message` when present.
  - error: "Could not evaluate", then `message` as text (monospace), or
    "No message was recorded." `display_value` (`—`) is **not** shown,
    because it is not a measured value. When `last_evaluated` is present:
    "Last evaluated: Fail, *3 hours ago*; failing since *3 hours ago*". The
    "since" part appears only for fail and warn ("warning since").
  - skipped: "Skipped", then `message`, and `last_evaluated` as for errors.
  - no result: "No result recorded" / "Its state is unknown."
- **When** (empty for no result):
  - The age of `latest.started_at`.
  - A streak line from `latest.since`: fail "Failing since *7 days ago*";
    warn "Warning since …"; error "Could not evaluate since …"; skipped
    "Skipped since …". pass has none. Both ages are visible without
    hovering. An error row never says "failing since" for the error
    itself.
  - "Not in the latest run" when `latest.run_id` differs from the newest
    run's id. This is quiet secondary text: muted colour, no icon, no
    status colour. On a project that runs folders on different schedules
    it is on many rows, and the age is the signal.

On narrow screens (under 48rem) each row becomes a block, and the table
semantics are kept.

### 4.6 Failures to load (O9)

When `/checks` or `/runs` fails, the page keeps its header and shows a
`role="alert"` panel titled "Could not load results". It gives the
envelope's `message` verbatim (for example "results store: unavailable — see
the server log"), then "HTTP 503 · store_unavailable", and a **Try again**
button. No summary, latest run or table is rendered, stale or empty, because
either could pass for "nothing failing". A refresh that fails replaces the
data on screen with the error. A network failure reads "Could not reach the
tablewatch server. Is `tablewatch serve` still running?". A failure of
`/project` gets its own panel ("Could not load the project").

When refreshes overlap, only the newest one may update the page. An older
answer that arrives late is dropped.

### 4.7 Page not found (W3)

For every path the route table does not know, the page shows the heading
"Page not found", "There is no page at `<path>`", and a "Go to the
overview" link to `/`. It makes no API requests.

## 4A. The check page (`/checks/<id>`)

Spec 004 (I-05, first half). It reads `GET /api/v1/project`,
`GET /api/v1/checks/{id}`, `GET /api/v1/checks/{id}/history?limit=200` and
`GET /api/v1/runs?limit=1` in parallel, through the shared hook. The
document title is "*check name* · tablewatch" ("Check not found ·
tablewatch" for an unknown id).

### 4A.1 Header and back link

The overview's header, with **Refresh** (it re-fetches all four endpoints
and drops any older history pages, D14). On this page the project name is a
paragraph, not a heading: the page's one `<h1>` is the check's name. Under
the header, a "Back to the overview" link to `/`.

### 4A.2 What the check is (D2)

A panel headed by the check's name (`<h1>`). When the expression differs
from the name (a named check such as "Order volume"), the expression follows
in monospace. Then a definition list: **Dataset**, **Datasource**,
**Owner** ("none" when null), **Tags** (pills, or "none"), **Source**
(`file:line:col`, monospace) and **Id** (the full id, monospace).

### 4A.3 Rule (D3, D4)

Heading "Rule". One line per condition, from `rule`:

| `rule` | Reads |
| --- | --- |
| `expect` set | "Expected" + `expect.text` |
| triggers | "Warn when" + `warn.text`, then "Fail when" + `fail.text` (either may be absent) |

The condition is always the API's `text`, in monospace. The page never
formats a threshold from its numbers (a test serves a `text` that differs
from its numbers). Below: "The current rule, from the check files loaded
*3 hours ago*." (the age of `project.loaded_at`).

**A rule no run has used yet** (`edited-pending`). The page knows this when
the newest history entry's recorded `expression` differs from the check's
`expression`. The rule section then adds "No run has used this rule yet.
The results below were judged by an earlier rule."

### 4A.4 Latest result (D4)

Heading "Latest result": the status badge, then `Result` and `When`, the
same components as the overview's row. So an error reads "Could not
evaluate", the message, and "Last evaluated: Fail, *3 hours ago*; failing
since *3 hours ago*", and never shows `display_value` (`—`). A failure reads
`20.00%`, `expected < 5%`, "Failing since *3 hours ago*". "Not in the latest
run" appears when `latest.run_id` is not the newest run's id. With no result:
"No result recorded / Its state is unknown."

With a rule no run has used yet, a note follows: "Judged by an earlier
rule, `missing_percent(email) < 15%`. The check files now say
`missing_percent(email) < 25%`, and no run has used that yet." Without it,
"Expected < 25%" beside a red 20.00% would read as tablewatch being wrong.

### 4A.5 History (D5–D13, D19, D20)

A panel headed "History", holding the chart figure (4A.6), then the table
(4A.7), then, when `next_cursor` is not null, a **Load older results**
button. It fetches the next page with the cursor and appends it to both the
chart and the table. An answer that lands after a Refresh is dropped.

### 4A.6 The chart

A `<figure>`:

1. The y-axis title in text above the chart: "*metric* (*unit*)", for
   example "missing_percent (%)", "freshness (age)", "row_count (count)",
   "avg (value)", or "(unit unknown)".
2. "Current rule: `Expected < 5%`" (`ruleSentence`, from `text`), whenever a
   rule is loaded. This keeps the rule next to the chart even when its
   boundary is off the plotted range (D6).
3. The key (an inline list, not a legend box, since there is one series).
   It names every shape shown: "Fail", "Warn", "Pass", "Skipped", "Could not
   evaluate", "Fail: no value measured" (and "Warn: …", "Pass: …" if they
   ever occur), "Fails the current rule", "Warns under the current rule",
   "Rule changed between two runs", "The current streak". Each has a swatch
   drawn with the chart's own shapes and classes.
4. The SVG, inside a focusable group (4A.6.6).
5. Captions under it (`<figcaption>`, one list):
   - rule changes: "Rule changed between runs *time* and *time*: from `A` to
     `B`." Numbered ("Rule change 1: between runs …") when there is more than
     one. A dataset change adds "dataset from `x` to `y`". Times are full, in
     the viewer's zone with the zone named, inside `<time datetime>`.
   - "No run has used the current rule yet, so no threshold is drawn. Every
     result here was judged by an earlier rule." (edited-pending)
   - "This check is not in the loaded check files, so no rule is drawn."
   - "1 result measured a different metric (missing_count) and is not
     plotted. The table lists it." (D20)
   - "Shows the latest 200 results, not all of them." while older results
     exist (the count is what is loaded).

#### 4A.6.1 What is drawn (encoding)

- **x is time** (`started_at`), linear, not run index. Marks sit 14 units
  inside the plot's edges. A single result is centred.
- **y is the recorded `value`**, linear, one axis.
- **Plotted:** entries with a value, whose outcome is not `error`, and whose
  recorded `metric` equals the axis metric. The axis metric is the loaded
  check's `metric`; for a check no longer loaded, the one metric every entry
  shares (otherwise there is no chart, only the table, and the caption "These
  results measured different metrics, so they are not charted. The table
  lists every one.").
- **Marks** keep the recorded outcome (D8): the status shape (shared with the
  status icons, `components/shapes.tsx`) at 12 units, filled with the mark
  colour, with a 2px ring in the plot's background colour.
- **The line** joins consecutive plotted values (2px, round, neutral
  `--tw-series`). It breaks at anything in between: an error, a missing
  value, or a value measured by another metric. One result: one mark, no
  line. Equal times: both drawn, in history order.
- **Lanes below the plot** (decision 10), each drawn only when it has
  entries, each labelled at the left: "Could not evaluate" (`error`
  entries) and "No value" (any other outcome without a value: a `fail` with
  "no value to evaluate", freshness with "no timestamps in scope", a
  `skipped`). Nothing in a lane is ever plotted at 0.
- **Values measured by another metric** are not drawn at all and do not
  enter the y-domain (D20).

#### 4A.6.2 The band and boundary lines (D6, D7)

Only the **current** rule is drawn, and only over the newest run of entries
whose recorded `expression` equals the check's `expression`: from the
rule-change marker before that run (or the chart's left edge) to the right
edge. If the newest entry's expression differs (a rule no run has used),
**no band and no line** are drawn.

`bands(rule, domain)` in `lib/chart/bands.ts` decides the regions. A
condition's satisfied set is a union of intervals; an `expect` fails outside
it and a `warn`/`fail` trigger fires inside it. Each set is cut to the
domain:

- every piece with height is shaded (fail: `--tw-fail-mark`, warn:
  `--tw-warn-mark`, both a 10% wash);
- a single value (`expect != v`, `fail when = v`) has no height: only its
  line is drawn, in its colour;
- everything but one value (`expect = v`) is shaded on both sides of its
  line, because on this chart white means passing;
- warn regions leave out shaded fail regions (the engine checks `fail`
  first); fail is drawn over warn.

Each boundary in the domain is a 1.5px solid line in the fail or warn mark
colour (the expectation's lines are fail lines), labelled at the right with
the condition's `text`. Tested with the D6 table.

#### 4A.6.3 The y-domain and ticks (D10)

`yAxis(values, boundaries, unit)` in `lib/chart/domain.ts`:

1. The plotted values' extent is the base. A single value (or all equal)
   extends to 0.
2. Zero joins an all-positive extent when that at most doubles its height,
   and always joins when a value is negative, so a negative freshness (a
   future timestamp, usually a naive time read in the wrong zone) is drawn
   below 0 and never clamped.
3. **A boundary joins the domain only if the domain with it is at most twice
   the base's height**, so the values keep at least half the plot. A
   boundary left out is an edge label at the top or bottom of the right-hand
   column, formatted by the tick formatter: "10,000 above", "5 below"
   (decision 12).
4. With no plotted values (every result an error), the domain is the
   boundaries and 0.
5. The domain is extended to round ticks: at most 6 intervals, steps 1-2-5
   × 10ⁿ (whole numbers for counts), and for durations 1/2/5/10/15/30 s,
   1/2/5/10/15/30 min, 1/2/3/6/12 h, 1/2/7/14/30 d.

Ticks are formatted by unit (`formatTick`): percent `20%`, `2.5%`; count
`12,000`; duration `6h`, `1d`, `1m 30s`, `-7h` (the largest unit and the next
one, if not zero); number `54.36`, `-1.5`; unknown unit as a plain number.
Decimals follow the tick step. This formats **axis labels only**: every
value shown for a result (tooltip, table, the latest-value label) is
`display_value` from Python.

#### 4A.6.4 Labels (selective, horizontal)

- Right of the plot: each boundary line's `text`, the newest plotted value's
  `display_value`, and off-range edge labels. They are stacked so no two
  overlap (14 units apart, `stackLabels`), as close to their line as
  possible. Longer than about 22 characters, a label is cut with "…" (the
  rule is in full above the chart).
- **Rule-change markers** (D7, decision 11): a solid 1px vertical hairline
  midway between the two runs, labelled "Rule changed" (or "Rule change
  1", "2", … when more than one) in a row above the plot. Labels that would
  overlap take the next row (`assignRows`).
- **The current streak** (D19): when the latest outcome has a "since"
  wording, a hairline bracket in its own top row from `latest.since` to the
  latest result, labelled with the overview's words and the full time:
  "Failing since Sep 26, 2026, 14:55:50 GMT+8". An error passed over inside
  the streak (E) stays visible in its lane. The streak row and the marker
  rows never share a row, so neither label covers the other.
- The x-axis: round local times (1/5/15/30 s, 1/5/15/30 min, 1/3/6/12 h, days
  at local midnight, months, years), formatted "14:56:15", "14:30", "Sep 26
  14:00" (spanning days), "Sep 26" or "Sep 2026". Under the axis, right
  aligned: "Sep 26, 2026 · times in GMT+8" (one day) or "Times in GMT+8".
  The zone is always named (D11).

#### 4A.6.5 Geometry

The SVG has a fixed 720-unit-wide `viewBox`, `width: 100%` and `height:
auto`, with a `min-width` of 36rem inside a horizontally scrolling wrapper
on narrow screens. Its height grows with the rows it needs: label rows
above, a 200-unit plot, 22 units per lane, the x-axis band. Nothing is
measured in the DOM: text widths are estimated at 7 units per character,
which errs towards more space. The left margin fits the widest tick or lane
label; the right margin fits the widest right label (48–168 units).

#### 4A.6.6 Interaction and accessibility (D11)

- The `<svg>` is `role="img"` with `aria-labelledby` naming its `<title>`
  ("History of *name*") and its `<desc>`. The `<desc>` is `chartSummary`:
  "4 results, from *first* to *last*: 3 fail, 1 could not evaluate. Latest
  plotted value 20.00% (fail). Current rule: Expected < 5%." plus notes for
  other metrics, rule changes, a rule not yet used, and "The latest *n*
  results" when older ones exist. Ids come from `useId()`.
- The SVG sits in a focusable `role="group"` ("History chart. Use the left
  and right arrow keys to read each result."). Hovering a column, or
  focusing the group and using ←/→/Home/End, shows a 1px crosshair at the
  result and a tooltip beside it; Escape or leaving hides it. Hover columns
  are at least 24 units wide. Results at the same time share a column.
- The tooltip puts the value first (semibold): `display_value`, or "Could
  not evaluate", or "Fail: no value measured"; then the outcome; the full
  time in the viewer's zone with the zone named; the message (cut at 64
  characters). It is drawn in the SVG and positioned by a `transform`,
  never inline style. The same text goes to a polite live region.
- The table is the full alternative: one row per entry the chart draws or
  leaves off its axis.
- Outcomes are never colour alone: shape, key name, table badge.

### 4A.7 The history table (D12)

A real `<table>` with a visible caption, "Every loaded result, newest first.
Times in GMT+8.", and the columns **When**, **Outcome**, **Value**,
**Message**, **Rule**, **Trigger**. One row per entry, newest first:

- **When:** the full local time (the caption names the zone), then the age
  as a focusable `<time datetime>` holding the API's UTC string.
- **Outcome:** the status badge.
- **Value:** `display_value`; "Could not evaluate" for an error; "No value
  measured" when the value is null. A value measured by another metric adds
  "Not on the chart: measured by *metric*". The value comes before the
  message, so a freshness row reads as an age before the timestamp inside
  its message.
- **Message:** verbatim. The page does not reformat timestamps inside
  messages or the bare `0` of a passing schema check (I-24's work).
- **Rule:** "Current" when the recorded expression is the check's; otherwise
  "Different rule" and the recorded expression. A different recorded dataset
  adds "Other dataset" and its name. For a check no longer loaded, rows are
  compared with the newest entry ("Same as the newest").
- **Trigger:** as recorded (`cli`).

### 4A.8 Failures and unknown checks (D15)

| `/checks/{id}` | `/history` | The page shows |
| --- | --- | --- |
| 200 | 200, entries | identity, rule, latest result, chart and table |
| 200 | 200, empty | identity, rule, "No result recorded" (neutral), and "No results recorded yet." where the chart would be |
| 200 | 503 or network | identity, rule, latest result, and a "Could not load the history" alert with the message and **Try again**; no chart, no table, no "no results" text |
| 503 or network | any | an `<h1>` "Check `<id>`" and a "Could not load the check" alert with **Try again**; no identity, no status, no chart |
| 404 | 404 | "Check not found": "No check with the id `<id>` is loaded, and no results are recorded for it.", a link to the overview; no chart, no table, no status. When the project has broken check files, it adds that the check may be in one of them |
| 404 | 200, entries | the newest entry's name as `<h1>`, "This check is no longer in the loaded check files. Its recorded results are below.", then the chart (no band, no rule) and the table. With several recorded metrics, the table alone |

The id is shown only after it has passed the route's id pattern, and only
as text inside `<code>`.

## 5. Status: label, icon, colour

Every status has a **text label**, an **icon shape** and a **colour**.
Colour is never the only signal. The icon is `role="img"` with an
accessible name that states the meaning.

| Status | Label | Icon shape | Icon accessible name | Hue |
| --- | --- | --- | --- | --- |
| fail | Fail | octagon with a cross | "Data failed the check" | red |
| error | Error | rounded square with "?" | "Could not evaluate" | violet |
| warn | Warn | triangle with "!" | "Data crossed the warning threshold" | amber |
| no result | No result recorded | dashed empty circle with a dash | "Unknown: never recorded" | neutral grey |
| skipped | Skipped | outline circle with a skip arrow | "Not evaluated: skipped" | slate blue |
| pass | Pass | filled circle with a tick | "Data passed the check" | green |

Why these choices (no dataviz skill was available in I-03; the chart's own
tokens, validated with it in I-05, are below):

- **fail vs error** is the distinction the product exists to keep (VISION:
  honest outcomes). They use hues about 90° apart: red, and violet, which
  reads as blue under deuteranopia and protanopia. Their shapes are
  unrelated (octagon vs square), and so are their labels. Violet is not a
  "danger" colour, which suits a state that goes to Dana, not Sam.
- **fail vs warn** (red vs amber) is the pair most at risk under red-green
  colour blindness. The triangle and the octagon, and the words Fail and
  Warn, separate them.
- **no result** is deliberately neutral grey and hollow. It is not green,
  not filled, and does not look like a tick, so "unknown" never reads as
  "healthy" (O3).
- Problem rows (fail, error, warn) also carry a coloured left edge. This is
  decoration only, and the badge carries the meaning.

### Palette and contrast (O11)

Tokens are in `frontend/src/styles/tokens.css`. `prefers-color-scheme`
picks light or dark, and there is no theme switcher.
`src/test/contrast.test.ts` **parses that file** and asserts WCAG AA for
every pair below, in both schemes. It also asserts that the fail, error and
warn hues are apart (fail–error ≥ 60°, error–warn ≥ 60°, fail–warn ≥ 25°).

| Pair | Required | Light | Dark |
| --- | --- | --- | --- |
| text on bg / surface | 4.5 | 16.56 / 15.45 | 15.42 / 14.19 |
| muted text on bg / surface | 4.5 | 6.89 / 6.43 | 8.17 / 7.52 |
| link on bg / surface | 4.5 | 6.39 / 5.96 | 8.91 / 8.20 |
| focus ring on bg / surface | 3.0 | 6.39 / 5.96 | 8.91 / 8.20 |
| fail on bg / surface / tint | 4.5 | 6.57 / 6.13 / 5.75 | 8.51 / 7.83 / 7.22 |
| error on bg / surface / tint | 4.5 | 7.54 / 7.04 / 6.43 | 9.75 / 8.97 / 7.83 |
| warn on bg / surface / tint | 4.5 | 6.80 / 6.35 / 6.11 | 10.41 / 9.58 / 8.12 |
| no result on bg / surface / tint | 4.5 | 7.45 / 6.95 / 6.46 | 9.77 / 8.99 / 7.52 |
| skipped on bg / surface / tint | 4.5 | 7.67 / 7.16 / 6.57 | 9.96 / 9.16 / 7.93 |
| pass on bg / surface / tint | 4.5 | 5.84 / 5.45 / 5.14 | 10.98 / 10.10 / 8.61 |

The test also covers the icon mark inside a filled icon (3:1), the body text
on every tint (4.5:1, the banner), and the focus tooltip (4.5:1). Status
colours clear 4.5:1 even where only 3:1 (non-text) is required, because the
same token colours the badge text.

In `forced-colors` mode, badges, tiles and the banner fall back to
`CanvasText` borders. Icons and labels still carry the status. The chart's
line, boundary lines, markers and marks fall back to `CanvasText`; shapes
and the key carry the outcome.

### Chart tokens (spec 004, decision 13)

The chart plots on `--tw-bg`. Its colours are chart-only tokens, used for
marks, boundary lines and band washes, **never for text** (a test scans
`app.css` for any `color:` rule using a mark token outside `.mark--*`).
Chart text uses `--tw-text` and `--tw-text-muted`. The overview's text
tokens are unchanged.

| Token | Light | Dark | Role |
| --- | --- | --- | --- |
| `--tw-pass-mark` | `#0c7f5c` | `#23a58a` | pass marks |
| `--tw-warn-mark` | `#ac7d1b` | `#bd8630` | warn marks, warn lines and wash |
| `--tw-fail-mark` | `#b42318` | `#d02b31` | fail marks, fail lines and wash |
| `--tw-error-mark` | `#6b2fbf` | `#9677e0` | "could not evaluate" marks |
| `--tw-series` | `#6b7480` | `#8b95a1` | the value line (neutral: it cannot take a status colour) |
| `--tw-grid` | `#e4e7eb` | `#262c34` | gridlines (recessive, one step off the background) |

Skipped marks use `--tw-skipped-fg`. Markers, the streak bracket and the
crosshair use `--tw-text-muted`. The zero gridline, axis and lane rule use
`--tw-border`. Nothing is dashed.

**Validation with the dataviz skill's `validate_palette.js`** (4 slots in
the order pass, warn, fail, error; against `--tw-bg` in each scheme; run on
2026-09-26, adjacent pairs and all pairs):

| Check | Light (`#ffffff`) | Dark (`#0f1216`) |
| --- | --- | --- |
| Lightness band | PASS, all inside L 0.43–0.77 | PASS, all inside L 0.48–0.67 |
| Chroma floor | PASS, all ≥ 0.1 | PASS, all ≥ 0.1 |
| CVD separation, adjacent | PASS, worst warn↔pass ΔE 8.8 (protan) · tritan 15.3 | PASS, worst fail↔warn ΔE 9.5 (deutan) · tritan 15.1 |
| CVD separation, all pairs | PASS, worst fail↔pass ΔE 8.3 (deutan) · tritan 13.5 | PASS, worst fail↔warn ΔE 9.5 (deutan) · tritan 11.8 |
| Normal-vision floor (adjacent and all) | PASS, worst warn↔pass ΔE 18.0 | PASS, worst warn↔pass ΔE 18.0 |
| Contrast vs surface | PASS, all ≥ 3:1 | PASS, all ≥ 3:1 |

The REFINE proposal (light warn `#a85c00`, dark warn `#c08419` and fail
`#e0584f`) **failed** CVD separation (fail↔warn ΔE 4.9 light, 4.4 dark,
deutan) and the normal-vision floor (10.8 light, 13.1 dark). Red and amber
sit on one deutan confusion line, so they have to be told apart by
lightness. The shipped steps keep pass, fail and error as proposed in light
and pass and error in dark, and move warn lighter and more yellow (light) or
fail darker and warn lighter (dark), searched in OKLCH around each hue with
a 3.4:1 floor on the dark background.

`contrast.test.ts` also asserts, in both schemes: each mark token and
`--tw-series` at least 3:1 on `--tw-bg`; `--tw-on-status` (the glyph inside a
filled mark) at least 3:1 on each mark token; and the skipped mark and the
muted hairlines at least 3:1.

| Pair (3:1 required) | Light | Dark |
| --- | --- | --- |
| pass mark on bg | 4.99 | 6.10 |
| warn mark on bg | 3.68 | 5.92 |
| fail mark on bg | 6.57 | 3.64 |
| error mark on bg | 7.54 | 5.38 |
| series on bg | 4.74 | 6.18 |

Band washes are the mark colour at 10% opacity and are lighter than 3:1 by
design; their edges are the boundary lines, which are not.

## 6. Time

**Ages** ("3 hours ago") are elapsed time: `floor((now − t) / unit)` on epoch
milliseconds. Rounding is always **down**, so "2 days" means at least 48
hours. Neither the viewer's time zone nor a DST change affects an age.

| Elapsed | Reads |
| --- | --- |
| < 1 minute, or in the future (clock skew) | "just now" |
| 1 minute to < 1 hour | "*n* minute(s) ago" |
| 1 hour to < 24 hours | "*n* hour(s) ago" |
| ≥ 24 hours | "*n* day(s) ago" (no weeks or months: "45 days" is exact) |

**Absolute times** are shown in the viewer's time zone **with the zone
stated**, via `Intl.DateTimeFormat` (browser locale, 24-hour clock,
`timeZoneName: 'short'`). In Singapore: "Sep 26, 2026, 14:56:12 GMT+8".

Every age is a `<time datetime="…">`, and the attribute holds the API's
UTC string unchanged. The full time shows on **hover** (`title`) and on
**keyboard focus**: the element is focusable (`tabindex="0"`), and a CSS
tooltip draws `attr(data-full)` on `:focus-visible`.

## 7. Wording rules

- "Error" always travels with "could not evaluate": on the summary tile,
  on every error row, and in the latest-run sentence. A run whose outcome
  is `error` is never called "failed".
- "since", never "continuously". Runs happen at intervals, and errors that
  were passed over sit inside a streak.
- A missing check "may be missing". The UI never gives a number it cannot
  know.
- "No result recorded" / "state unknown". Never "not run yet" (the id may
  have changed) and never anything that reads as healthy.
- The summary is "Latest result of each of the N checks loaded". The run
  panel is "This run: N checks". Each scope is named, so neither reads as
  the other.
- The check page's latest result uses the overview's components word for
  word (D4).
- A value nobody measured is never a number: "Could not evaluate" (error)
  and "Fail: no value measured" (no value) in the chart; "Could not evaluate"
  and "No value measured" in the table. The lane holding the latter is "No
  value", never "could not evaluate".
- A rule change says "between runs", not "at" a time: the history knows the
  two runs on either side, not when the file was edited.
- A result judged by an earlier rule says so and names that rule's recorded
  expression.
- Every time the page makes names its zone (axis, tooltip, captions, table
  caption). Stored messages may hold UTC timestamps (until I-24) and are
  shown verbatim.

## 8. Accessibility (O11)

- Landmarks: `<header>` (banner), `<main id="main">`, and a labelled
  `<section>` per panel (Summary, Latest run, Checks, and the banner). One
  `<h1>`, then `<h2>`/`<h3>`.
- The check list is a `<table>` with `<th scope="col">` and a caption.
- Everything interactive is native: `<button type="button">`, `<a href>`,
  `<details>`. The focusable `<time>` elements carry their full timestamp.
  Focus is visible everywhere as a 3px outline in `--tw-focus` (≥ 3:1 on
  both backgrounds).
- A polite `role="status"` region announces "Loading…", "Up to date." or
  "Could not load everything.". Load failures are `role="alert"`.
- Status is never colour alone (§5). The tests assert labels and icon
  accessible names, not colours.
- The check page (§4A): one `<h1>` (the check's name), labelled sections
  (Rule, Latest result, History), the chart as `role="img"` with a title and
  a summary description, a keyboard-operable focus group for its tooltip,
  and the history table as the chart's full text alternative.

**How this was checked:** component tests query by role and accessible name
(landmarks, headings, table, column headers, buttons, links, icon names);
`contrast.test.ts` computes WCAG contrast from the shipped tokens in both
schemes; and the production bundle was run in jsdom against a real
`tablewatch serve` on the example project (18 rows, correct order, no
`style` attribute or element in the rendered DOM). A screen-reader pass and
a real-browser pass in both schemes are for the data-steward's VERIFY run.

## 9. Security rules for the frontend (X2–X4)

- The CSP is `default-src 'none'; script-src 'self'; style-src 'self'; …`,
  so styles live in CSS files only: no `style` prop, no `style` attribute,
  no `<style>` element. SVG uses presentation attributes and classes.
- Data renders as text through React. The sources never use
  `dangerouslySetInnerHTML`, `innerHTML`, `outerHTML`, `insertAdjacentHTML`,
  `document.write`, `eval(`, `new Function`, `srcdoc` or
  `createContextualFragment`. `src/test/security.test.tsx` scans every file
  under `frontend/src` for these, and for `localStorage`, `sessionStorage`,
  `indexedDB`, `serviceWorker`, any `fetch(` outside `api.ts`, any
  `import.meta.env` other than `MODE`/`PROD`, and any `http(s)://` or CSS
  `@import` in app code.
- X4 is tested with a check named `<img src=x onerror=alert(1)>`, an error
  message `<script>alert(1)</script>`, a project name and a diagnostic
  holding markup. All of them appear as literal text, and no element is
  created from them.
- **The chart** (spec 004 D16, decision 14). The same test runs on the check
  page: a hostile name, message and recorded expression render as text in
  the heading, the chart's `<title>` and `<desc>`, the rule-change caption,
  the tooltip and the table, and in `document.title`. The source rules add,
  for `components/chart/`, `lib/chart/` and `components/shapes.tsx`: no
  `<a>`, `<use>`, `<image>` or `<foreignObject>`, no `href` of any kind, no
  `style`, and element ids only from `useId()` (`titleId`, `descId`), never
  from data or a literal. The tooltip is positioned with an SVG `transform`.
- **Routes** make no request for an id that fails the id pattern, and the
  not-found page shows only a well-formed id, inside `<code>`.
- Nothing is loaded from a third party: no web fonts (system font stack),
  no CDN, no analytics, no remote images.

## 10. Tests

`npm test` runs these (vitest, jsdom, time zone fixed to `Asia/Singapore`):

| File | Covers |
| --- | --- |
| `test/overview.test.tsx` | O1–O11 and W3 at component level (W3 now uses `/runs/<id>`, since `/checks/<id>` is a page) |
| `test/qa.test.tsx` | spec 003 VERIFY edge cases (qa-engineer) |
| `test/check.test.tsx` | spec 004 D1–D20 at component level, including the rendered chart (lanes, bands, markers, streak, tooltip by keyboard and pointer, label collisions) |
| `test/chart.test.ts` | the chart's pure functions: the D6 bands table, the D10 tick table and domain cases, series and lanes (D5, D9), rule changes and the band's span (D7), recorded outcomes (D8), other metrics (D20), label stacking and rows, hover columns, tooltip placement, the key, x ticks, the summary (D11) |
| `test/route.test.ts` | the route table and `checkHref` (decision 7) |
| `test/security.test.tsx` | X4 rendering, source rules (§9), the chart's source rules (decision 14) |
| `test/contrast.test.ts` | the palette and the chart tokens, both schemes (§5) |
| `test/lib.test.ts` | age boundaries and rounding, DST, absolute format, selection wording, status order and counts |
| `test/api.test.ts` | the client: URLs, init, envelope errors, non-JSON, network failure |

**Fixtures** (`test/fixtures/states.ts`) are real API responses for
spec 003's `recorded`, A-B-E (`beforeF`) and `interrupted`. They were
captured from the in-process app on `examples/retail` and normalised: run
ids become A/B/E/F placeholders, timestamps are fixed (A 06:55:50, B
06:56:12, E 06:56:30, F 06:56:45 UTC), and the build path in the IO error
is replaced. `test/fixtures/derived.ts` builds the states the spec defines
from them: `broken`, `broken-yaml`, the O3 edit, no runs, warnings only,
all-clear variants and skipped. `test/fixtures/detail.ts` adds the check
page's responses: `rule` for each retail check used (as `tablewatch serve`
answered on a scratch copy of `examples/retail`), the `interrupted`
histories of `b1ceb8262d8b5441` and `32c8f939b90f6367`, and spec 004's
`edited`, `edited-pending` and `metric-changed` (then back to `< 15%`)
states, with runs C, M and N at 07:30, 08:00 and 08:30 UTC. Every fixture is typed with the generated
types. The clock is fixed with fake `Date` only, at B + 3h 43s, so every
age in the fixtures reads "3 hours ago" and rounding down is exercised.

## 11. Known limits and follow-ups

- **Cross-platform bundle identity (spec 003 Q7).** Two local builds on
  macOS/Node 24.13.0 are byte-identical. Linux/CI identity is proven only
  when K2 first runs in CI. If it differs, raise it rather than weakening
  K2.
- jsdom is held at 29.1.1 while Node is 24.13.0. Moving `.nvmrc` to
  ≥ 24.15 allows jsdom 30.
- Each age is a tab stop (hover/focus requirement of O4). A check list
  with hundreds of rows will want roving focus or a detail view instead.
  Revisit with I-04 and I-05.
- History rows do not link to runs yet (I-15).
- The chart's text widths are estimates (7 units per character at 12
  units). A very wide glyph run (for example many `W`s in a rule's text)
  could crowd its neighbour; the rule is also shown in full above the
  chart.
- Only the current rule is drawn. Past rules are text at their markers
  (spec 004 non-goal).
- The chart was checked visually by rasterising its SVG, with the shipped
  stylesheet, in both schemes (macOS Quick Look / WebKit). A real-browser
  pass, with a screen reader, is for VERIFY.
