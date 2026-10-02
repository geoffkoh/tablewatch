# Spec 017: overview wording and counts (I-21)

- **Track:** light. Frontend only: `/api/v1/checks` already serves `latest.since`, `latest.run_id` and `project.ok`, and `/api/v1/runs` serves each run's `id` and `counts.total`. No `src/`, API, store, identity or exit-code change.
- **Size:** S. **Builder:** ui-engineer. **Reviewers:** qa-engineer, data-steward (wording).
- **Score:** I-21 is R2 (Sam, Alex) × I0.5 × C0.8 ÷ S1 = **0.8**, rank 6. It finishes the owner's "UI first" chain, ahead of I-06 (4.5). Not batched: no other open S item has the same builder and reviewers.

## Problem and persona

Sam opens the overview to see what is broken and since when. Three things on it read wrong (data-steward, iteration 3).
(1) When a check file is broken, "incomplete" is on the caption and the fail and pass tiles, but not on the error, warning or no-result tiles, which are just as incomplete.
(2) The latest run can report more checks than the summary, with nothing to say why.
(3) The streak reads "Failing since 7 days ago", which mixes a start point with a duration.
Today Sam works it out from the banner or by hovering, or asks Dana.
Research: Grafana's alert list shows "Active since" with a timestamp, not an age ([Grafana: view alert state](https://grafana.com/docs/plugins/grafana-prometheusalerting-app/latest/monitor-status/view-alert-state/)).
A date also stays true when the latest result is old. A duration ("for 7 days") would suggest the check is failing now.

## Decisions taken in PLAN (light track; the tech lead may amend)

- **P1. The caption alone carries "incomplete".** A marker on every tile is noise, and the red banner sits directly above. Every count is incomplete in the same way, so the caption says so once.
- **P2. "Since" reads as a point in time** in the viewer's zone. If it is the same local day as now, it shows the time and "today": "since 10:05 today". If it is the same year, it shows the day: "since Sep 19". Otherwise it adds the year: "since Dec 31, 2025". Hovering or focusing still shows the full time with its zone (the `<time>` element is unchanged). The chart's streak label already uses an absolute time and does not change.
- **P3. "Not loaded now" is counted exactly:** `k = run.counts.total − (number of loaded checks whose latest.run_id is run.id)`. Nothing is shown when k ≤ 0. A run needs a clean project (`run` exits 3 otherwise), so a check counted in k was dropped by a broken file, edited (a derived id changes), or removed.

## Scenarios

Vitest runs with `TZ=Asia/Singapore` (`vite.config.ts`). "now" is `2026-09-26T12:00:00Z` (20:00 SGT). The fixtures are built by hand or derived from `states.ts`.

| id | | given | expected |
| --- | --- | --- | --- |
| C1 | must | project `ok: false` (one error diagnostic), 15 checks loaded | the caption reads "Latest result of each of the 15 checks loaded (incomplete)"; "incomplete" links to `#project-problems` |
| C2 | must | same as C1 | no tile (fail, error, warn, no result, skipped, pass) contains the word "incomplete" |
| C3 | must | project `ok: true` | "incomplete" appears nowhere on the page (as today) |
| S1 | must | a fail row, `since` `2026-09-19T03:00:00Z` | the row reads "Failing since Sep 19"; its `<time dateTime>` is the API string unchanged; the title is the full time with its zone |
| S2 | must | a fail row, `since` `2026-09-26T02:05:00Z` (10:05 SGT) | "Failing since 10:05 today" |
| S3 | must | a warn row, `since` `2025-12-31T20:00:00Z` (Jan 1 04:00 SGT) | "Warning since Jan 1": the viewer's zone decides the day and the year |
| S4 | must | a skipped row, `since` `2025-12-31T15:00:00Z` (Dec 31 23:00 SGT) | "Skipped since Dec 31, 2025" |
| S5 | must | an error row, `since` the same as S1 | "Could not evaluate since Sep 19" |
| S6 | must | an error row with `last_evaluated` fail, `since` the same as S2 | the note reads "Last evaluated: Fail, *age*; failing since 10:05 today" |
| S7 | must | any row, any page (overview, check page Latest result) | no text matches `/since [^<]*ago/`: "ago" stays only on the age of the latest result |
| S8 | must | `since` is not a timestamp (`"garbage"`) | "Failing since an unknown time"; no exception |
| S9 | should | `since` is 30 seconds in the future (clock skew), the same local day | "Failing since 20:00 today" |
| R1 | must | `ok: false`, the latest run with `counts.total` 18; 15 checks loaded, all with `latest.run_id` = that run | the banner adds, after its "may be missing" paragraph: "The latest run checked 3 checks that are not loaded now. Its counts include them; the summary's do not." |
| R2 | must | same as R1 | the Latest run panel shows, under "This run: 18 checks": "3 of them are not loaded now." (quiet text) |
| R3 | must | `ok: true`, the run's `counts.total` 18, 17 loaded checks in that run (one edited since) | no banner; the panel shows "1 of them is not loaded now. It was edited or removed since the run." |
| R4 | must | a run of one folder (`counts.total` 4, all 4 loaded), 15 loaded | no sentence anywhere (k = 0; selection makes the run smaller, which the README already explains) |
| R5 | must | no runs recorded | no sentence; "No runs are recorded…" as today |
| R6 | should | `counts.total` less than the number of matching checks (inconsistent data) | k ≤ 0: no sentence, no negative number |
| R7 | must | `ok: false`, k = 1 | the singular: "checked 1 check that is not loaded now. Its counts include it; the summary's do not." |
| D1 | must | docs | the README overview section (incomplete, "since", the run panel) and `docs/UI_SPECIFICATION.md` §4.2, §4.3 and the **When** rules say what ships; the existing tests that pin "since 3 hours ago" are updated to the new wording, not deleted |

## Non-goals

- No API change: `latest.since` keeps its meaning and form (spec 003 D1). No duration form ("for 7 days").
- No list of which checks are missing. The UI cannot know what a broken file held, so the banner still says "may" and gives no number for that file.
- The history chart, history table and explorer tree are unchanged. The explorer shows no streak.
- Run detail and diff (I-15).

## Decisions

P1–P3 accepted as written (tech lead, 2026-10-02); the data-steward judges the wording in VERIFY. The
relative-day rule in P2 uses the same `Intl` zone as the existing `<time>` title, not a second clock.
