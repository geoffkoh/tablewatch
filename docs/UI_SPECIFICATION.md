# tablewatch web UI specification

Owner: ui-engineer. This document describes what the web UI does. It is
updated in the same PR as the change it describes. Iteration specs in
`docs/product/specs/` say what an increment must do. This file records how
the UI does it: wording, layout, colour, and the rules behind them.

| Increment | Spec | What it added |
| --- | --- | --- |
| I-03 | `specs/003-ui-shell-overview.md` | Shell, overview page, "page not found" |

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
library or icon font. Routing is one `if`. Dates use `Date` and `Intl`.
Icons are hand-written SVG in JSX.

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
  App.tsx                  "/" -> Overview; anything else -> NotFound
  api/schema.gen.ts        GENERATED from docs/api/openapi.json; never edit
  api/types.ts             aliases into schema.gen.ts (Project, CheckSummary, Run, ...)
  api/api.ts               the ONE client: getProject, listChecks, listRuns
  lib/status.ts            statuses, their order, labels, icon names, counting
  lib/time.ts              ages (elapsed, rounded down) and absolute times
  lib/selection.ts         how a run's selection reads
  components/              Header, ProjectProblems, Summary, LatestRun,
                           CheckTable, StatusIcon/StatusBadge, Time (Ago), LoadError
  pages/Overview.tsx       loads the three endpoints; owns refresh
  pages/NotFound.tsx       "Page not found"
  styles/tokens.css        colour tokens, light and dark
  styles/app.css           layout and components
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
- **Routing.** The server answers every extensionless non-API path with
  `index.html` (W3). The UI renders the overview for `/` (and
  `/index.html`), and "Page not found" with a link to `/` for anything
  else. Later increments add client routes here.

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
- **Check:** the name. The expression follows in monospace when it differs
  from the name, then the dataset and `source` (`file:line:col`).
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

For every path but `/` this increment shows the heading "Page not found",
"There is no page at `<path>`", and a "Go to the overview" link to `/`. It
makes no API requests.

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

Why these choices (no dataviz skill was available in I-03; I-05 loads it
before the first chart):

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
`CanvasText` borders. Icons and labels still carry the status.

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
- Nothing is loaded from a third party: no web fonts (system font stack),
  no CDN, no analytics, no remote images.

## 10. Tests

`npm test` runs these (vitest, jsdom, time zone fixed to `Asia/Singapore`):

| File | Covers |
| --- | --- |
| `test/overview.test.tsx` | O1–O11 and W3 at component level |
| `test/security.test.tsx` | X4 rendering, source rules (§9) |
| `test/contrast.test.ts` | the palette, both schemes (§5) |
| `test/lib.test.ts` | age boundaries and rounding, DST, absolute format, selection wording, status order and counts |
| `test/api.test.ts` | the client: URLs, init, envelope errors, non-JSON, network failure |

**Fixtures** (`test/fixtures/states.ts`) are real API responses for
spec 003's `recorded`, A-B-E (`beforeF`) and `interrupted`. They were
captured from the in-process app on `examples/retail` and normalised: run
ids become A/B/E/F placeholders, timestamps are fixed (A 06:55:50, B
06:56:12, E 06:56:30, F 06:56:45 UTC), and the build path in the IO error
is replaced. `test/fixtures/derived.ts` builds the states the spec defines
from them: `broken`, `broken-yaml`, the O3 edit, no runs, warnings only,
all-clear variants and skipped. Every fixture is typed with the generated
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
- Rows do not link anywhere yet. I-05 (check detail) adds the link.
