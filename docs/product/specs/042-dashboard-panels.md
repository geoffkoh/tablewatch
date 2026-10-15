# Spec 042: App shell, part 4 — the Dashboard's panels (I-51 part 4)

- **Track:** full — one new read-only endpoint (`GET /api/v1/check-changes`) over the registry and
  definition history. No store schema, identity or exit-code change; no security trigger.
- **Size:** M. **Builders:** tech lead (endpoint), ui-engineer (panels; loads the dataviz skill for
  the trend). **Reviewers:** architect (VERIFY), qa-engineer, data-steward.
- **Item:** I-51 (owner-fixed; spec by the tech lead). Last part: I-51 is done after this.

## Problem and persona

Sam opens the Dashboard in the morning. It shows the latest run and every check, but not whether
things are getting better or worse, what changed overnight, which tables stopped being scanned,
or which checks someone added, edited or retired. C9's Dashboard panels answer those four
questions above the check table.

## Decisions (tech lead)

- K-D1. **Trend.** "Problems per run": the last 30 runs from `/runs?limit=30`, oldest left, one
  bar per run of `fail + error` counts with the run's outcome as the mark state, the time axis by
  run order (runs are irregular), each bar a link to nothing (Runs come with I-15) but with a
  tooltip/accessible label "Run of 14 Oct 02:00: 3 failing, 1 in error, 40 passing". Under the
  dataviz skill; fewer than 2 runs → "Not enough runs to show a trend yet."
- K-D2. **Changed recently.** The 5 newest state changes from `/alerts?limit=5`, worded as on the
  Alerts page (`lib/alerts.ts`), with "All alerts" linking to `/alerts`. None →
  "No state changes recorded yet."
- K-D3. **Not scanned recently.** Datasets (as the Datasets page groups them, `lib/datasets.ts`)
  whose newest `latest.started_at` over their enabled checks is more than **24 hours** before the
  newest run's `started_at`, oldest first, each "<dataset> · <datasource> — last scanned
  <Ago>" linking to the explorer filtered to it; a dataset with enabled checks never run reads
  "never scanned". Measured against the newest run, not the clock, so a project that has not run
  at all this week shows nothing stale (the Latest run panel already says how old that is).
  Disabled-only datasets are left out. None → "Every dataset was scanned within a day of the
  latest run."
- K-D4. **Check changes.** `GET /api/v1/check-changes?limit=` (1–50, default 10) →
  `{items: [{check: AlertCheck, kind, at, version}]}` newest first, from the registry and
  definition history of the served project:
  `added` (`registered_at`), `redefined` (a definition version ≥ 2: its `recorded_at`, `version`),
  `disabled` / `retired` (the check's current `state` with `state_since`). `version` null except
  for `redefined`. An `active` check's `state_since` after its `registered_at` is `enabled`
  (re-enabled or returned). One read in a new `results/changes.py`; each source query is limited
  to `limit` rows then merged, so it never scans the whole registry. Panel: the 5 newest, worded
  "Added", "Definition changed (version 3)", "Disabled", "Retired", "Enabled again", check name
  linking to its page, `Ago`. None → "No changes to checks recorded yet."
- K-D5. Each panel is a slot of its own in the page's `useLoads`; a panel whose request fails
  shows a one-line "Could not load <panel>." with Retry and never hides the others or the check
  table (the existing O9 rule keeps checks + latest run as one slot). Layout: a two-column grid
  of panels above the check table on wide screens, one column under 60rem.

## Scenarios

| id | m/s | given | expected |
|----|----|----|----|
| K1 | must | 3 runs: 0, 2 fail + 1 error, 1 fail | three bars, heights 0, 3, 1, oldest left; each labelled with its counts |
| K2 | must | 1 run | "Not enough runs to show a trend yet." |
| K3 | must | 7 state changes | 5 newest, worded as `/alerts`; "All alerts" → `/alerts` |
| K4 | must | newest run today 02:00; `orders` last scanned yesterday 01:00, `customers` today 02:00 | `orders` listed, `customers` not |
| K5 | must | a dataset with enabled checks that never ran; a disabled-only dataset | "never scanned"; the disabled one absent |
| K6 | must | no runs at all | stale panel shows its empty sentence; trend "Not enough runs…" |
| K7 | must | registry: one check added, one redefined to v2, one disabled, one retired | `/check-changes` lists all four, newest first, kinds as K-D4; `version: 2` on the redefined |
| K8 | must | a check disabled then enabled again | kind `enabled` at its `state_since` |
| K9 | must | another project in the same store | its checks never listed |
| K10 | must | `limit=0` / `limit=51` / `POST` | 400 / 400 / 405 envelopes |
| K11 | must | `/alerts` fails, others load | only that panel says "Could not load recent changes." with Retry |
| K12 | must | markup in a check or dataset name | text only |
| K13 | should | narrow screen | panels in one column, above the check table |

## Non-goals

A clock-based "missed run" (needs schedules — Phase 3 scheduler); per-dataset expected cadence;
the Runs section and run detail (I-15); a nav count beside Alerts; scorecards (C6).
Docs: `docs/UI_SPECIFICATION.md` §4 (Dashboard panels), OpenAPI, CHANGELOG.
