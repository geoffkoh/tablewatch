# Spec 039: App shell and side navigation, part 1 — Dashboard, Checks, Datasets (I-51 part 1)

- **Track:** light — frontend only. No risk trigger: no API or wire change (the nav count uses
  `/checks?outcome=`, which exists), no Python change, check ids, store and exit codes untouched.
  The one rule change (web storage for a single layout preference, P-D5) is decided here.
- **Size:** M. **Builder:** ui-engineer. **Reviewers:** qa-engineer, data-steward (UI judge).
- **Item:** I-51 part 1 (owner-fixed; spec written by the tech lead). Part 2: Alerts and Settings,
  and the Dashboard's extra panels; Runs arrives with I-15.

## Problem and persona

Sam (on-call) opens tablewatch from an alert. Every page is a dead end except through the
overview's links; there is no way to see "which tables are in trouble" without reading checks one
by one, and the only navigation is the browser's Back button. Projects hold hundreds of checks
across dozens of datasets, so the nav must hold major sections only, never the check list (C9).

## Decisions (tech lead)

- P-D1. Sections shown now: **Dashboard** (`/`, the overview's content, unchanged), **Checks**
  (`/checks`, the explorer, and every `/checks/<id>`), **Datasets** (`/datasets`, new). Runs,
  Alerts and Settings are not shown until built — no dead links, no "coming soon".
- P-D2. The shell (`components/AppShell.tsx`) wraps every page including Not found: the existing
  top bar (brand, project, Refresh), a `<nav aria-label="Sections">` list of links (plain
  `<a href>`, full page load, as today), and `<main id="main">`. The current section's link has
  `aria-current="page"`; a check page marks Checks.
- P-D3. Checks carries a count of problems: active checks whose latest outcome is `fail` or
  `error`, from `listChecks` with `outcome=fail&outcome=error` (`total`), a slot of its own
  in the page's `useLoads`, so Refresh reloads it. Hidden when 0, while loading, or when it fails
  (the page's own error states already say so). Accessible name: "Checks, 3 failing or in error".
- P-D4. Wide screens (> 60rem): the nav is a left column; a button "Collapse navigation" /
  "Expand navigation" (`aria-expanded`, `aria-controls`) turns it into an icon rail where each link
  keeps its accessible name and a visible tooltip on hover/focus (`title` is not enough: a
  visually hidden label plus a CSS tooltip). Narrow (≤ 60rem): a "Menu" button in the top bar opens
  the nav as a drawer over the page; Escape, the close button, or a click outside closes it and
  focus returns to "Menu"; focus moves into the drawer on open. No focus trap library.
- P-D5. The collapsed state is remembered per browser in `localStorage` key `tablewatch.nav`,
  value exactly `"rail"` (absent = expanded). Only `lib/navPreference.ts` touches storage, inside
  try/catch (storage may throw or be absent; the default is expanded). The security test's ban on
  web storage stays for every other file; no API data is ever stored. Icons are inline SVG in
  `components/NavIcons.tsx` under the chart's rules (no `href`, no `<use>`, classes only).
- P-D6. Datasets page, one row per (datasource, dataset), built in the browser from
  `listChecks()` (active and disabled): **Dataset** (link to the explorer filtered to it, P-D7),
  **Datasource**, **Status** (worst latest status over its enabled checks in `STATUS_ORDER`; all
  disabled → "Disabled"), **Checks** (counts by status, as the overview's Summary words them),
  **Last scanned** (newest `latest.started_at` over its checks, as an age with the absolute time;
  "Never" when none), **Owner** (distinct owners, comma-separated; "—" when none), **Tags**.
  Sorted problems first, then datasource, then dataset. A search box (`?q=`, cut to 200 code
  points) matches dataset, datasource, owner and tags, case-insensitive. Summary line:
  "12 datasets, 3 with problems" (problems = fail or error status).
- P-D7. The explorer gains `?dataset=<name>` (exact, repeatable like the facets, kept by the
  URL code in `lib/explorer.ts`); with it the explorer shows a removable chip
  "Dataset: orders" above the tree. A Datasets link sets both `datasource` and `dataset`.
- P-D8. `document.title`: "Dashboard — <project>", "Checks — <project>", "Datasets — <project>"
  (the check page keeps its own). The page `<h1>`s: Dashboard keeps the project name; Datasets
  has `<h1>Datasets</h1>`.

## Scenarios

| id | m/s | given | expected |
|----|----|----|----|
| N1 | must | any page (`/`, `/checks`, `/checks/<id>`, `/datasets`, an unknown path) | the nav with Dashboard, Checks, Datasets, in that order; exactly one link has `aria-current="page"` (none on Not found) |
| N2 | must | 2 checks fail, 1 errors, 4 pass | Checks shows `3`, accessible name "Checks, 3 failing or in error"; 0 problems → no count |
| N3 | must | the count's request fails or is slow | no count; nothing else on the page changes or waits on it |
| N4 | must | wide screen, click "Collapse navigation", reload | the rail stays; each link's name is still announced; storage holds `"rail"` |
| N5 | must | `localStorage` throws on read and write | the nav is expanded and the toggle still works for the page's life |
| N6 | must | `tablewatch.nav` holds anything but `"rail"` (`"<img src=x>"`, `"RAIL"`) | expanded; nothing rendered from the value |
| N7 | must | narrow screen, "Menu" → drawer open, Escape | drawer closed, focus on "Menu"; same for the close button and a click outside |
| D1 | must | retail example: `orders` has a failing check, `customers` all pass, a dataset with only disabled checks | rows in that order of status; the disabled one reads "Disabled" |
| D2 | must | the same dataset name on two datasources | two rows, each linking to `/checks?datasource=<ds>&dataset=<name>` |
| D3 | must | that link | the explorer shows only that dataset's checks and a "Dataset: <name>" chip; removing it drops `dataset` from the URL |
| D4 | must | a dataset never run | Status "No result recorded" (`STATUS_META.none`), Last scanned "Never" |
| D5 | must | `?q=ORD` | rows whose dataset, datasource, owner or tag contains `ord`; a `q` of `<img src=x onerror=alert(1)>` creates no element |
| D6 | must | no checks at all / `/checks` fails | "No datasets yet." / the shared `LoadError` with Retry |
| D7 | must | a dataset name or owner holding markup | rendered as text |
| S1 | must | security test | storage allowed only in `lib/navPreference.ts`; every other ban unchanged |
| S2 | should | keyboard only | Tab order: skip link, Menu (narrow) or the nav, then the page; the collapse button is reachable |

## Non-goals

Runs, Alerts, Settings sections; new Dashboard panels (trend, changed since last run, stale runs,
sync changes); a dataset detail page; freshness on the Datasets page (needs per-clause values);
a project switcher; any API change; a router library. Docs: `docs/UI_SPECIFICATION.md` §3, §9,
and a new §4C Datasets.
