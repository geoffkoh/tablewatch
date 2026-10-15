# Spec 040: App shell, part 2 — the Settings page (I-51 part 2)

- **Track:** full — a new wire endpoint (`GET /api/v1/settings`) that exposes project
  configuration, so security review is required. No store, identity or exit-code change.
- **Size:** M. **Builders:** tech lead (endpoint), ui-engineer (page). **Reviewers:** qa-engineer,
  data-steward, architect (VERIFY), security-reviewer (VERIFY). No REFINE: the tech lead decided the
  open questions below.
- **Item:** I-51 (owner-fixed; spec written by the tech lead). I-51 split again: part 2 = Settings
  (this spec); part 3 = Alerts (state changes and deliveries, needs a design for reading
  transitions cheaply); part 4 = the Dashboard's panels (trend, changed since the last run, stale
  runs, sync changes).

## Problem and persona

Alex (platform owner) is asked "which store is this server reading, is it migrated, which
notifiers are set up, and which environment variables do they need?" Today the answers are in
`tablewatch.yml` on a server Alex may not have a shell on, and the store's schema state only shows
up as a 503. C9's Settings section answers them read-only, without ever showing a credential.

## Decisions (tech lead)

- S-D1. `GET /api/v1/settings` → `Settings`. Built from the project as loaded at startup and one
  read of the store; no SQL in `server/`; nothing taken from the request.
  ```
  Settings { project: { name, version, loaded_at, checks_path },
             datasources: [{ name, type, datasets, checks }],      # config order
             notifiers:   [{ name, type, url_variable }],          # config order
             results: { dialect, schema, revision, head, migrate, sync },
             checks: { active, disabled, retired } }
  ```
- S-D2. **Never on the wire:** the store URL (it may hold a password, and a SQLite path names the
  server's file system), any datasource field but `name` and `type`, any resolved environment
  value, the project root. `url_variable` is the `NAME` of the notifier's `${env:NAME}` (the only
  form `url` accepts); whether it is set in the server's environment is not shown (rule 6: nothing
  is resolved before use).
- S-D3. `results.dialect` is the store engine's dialect name (`sqlite`, `postgresql`).
  `results.schema` is `ResultStore.schema()` — `current | empty | older | newer` — or
  `unavailable` when the store cannot be read; then `revision` and `checks.retired` are `null`
  and the endpoint still answers 200 (Settings is where you go when the store is down).
  `revision` is the store's Alembic revision (null when empty); `head` this version's.
- S-D4. `checks.active` / `disabled` count loaded checks by `enabled`; `retired` counts
  `ResultStore.retired_checks` (S-D3 for null). `datasources[].datasets` / `checks` count loaded
  datasets and checks per datasource (0 for a datasource no check uses).
- S-D5. A new store method is not needed for `revision`: `ResultStore` gains a public
  `revisions()` (today's `_revisions`), so the route never imports Alembic.
- S-D6. Page `/settings`, in the nav after Datasets, gear icon (inline SVG under P-D5's rules).
  `<h1>Settings</h1>`, `document.title` "Settings — <project>". Sections, each a `<section>` with
  an `<h2>` and a two-column definition list or table:
  **Project** (Name, Check files `checks_path`, tablewatch `version`, Loaded `loaded_at` as
  `Time`), **Datasources** (table: Name, Type, Datasets, Checks; empty → "No datasources."),
  **Notifiers** (table: Name, Type, URL from — `${env:NAME}` in a `<code>`; empty →
  "No notifiers configured."), **Results store** (Database `dialect`; Schema as words:
  current → "Up to date (<revision>)", older → "Older than this tablewatch (<revision>; this
  version is at <head>)", newer → "Newer than this tablewatch (<revision>)", empty →
  "Nothing recorded yet", unavailable → "Could not be read"; Migrations `migrate`: auto →
  "Applied by tablewatch when a run opens the store", never → "Managed outside tablewatch
  (`tablewatch store sql`)"; Registry sync `sync`: on_run → "On every recorded run", manual →
  "Only by `tablewatch sync`"), **Checks** (Active, Disabled, Retired — Retired "—" when null).
- S-D7. Read-only: no form control, no button but Refresh. A load failure shows the shared
  `LoadError` with Retry.

## Scenarios

| id | m/s | given | expected |
|----|----|----|----|
| S1 | must | retail example, `GET /api/v1/settings` | 200; datasources in config order with counts that sum to `/project`'s counts; `results.dialect` `sqlite`, `schema` `current`, `revision == head` |
| S2 | must | a Postgres datasource with `password: ${env:PG_PASSWORD}` set, store URL with a password | no response byte contains the password, the store URL, the project root or the SQLite file path |
| S3 | must | notifiers `ops: {type: slack, url: ${env:OPS_SLACK}}`, `hook: {type: webhook, …}` | `[{name: ops, type: slack, url_variable: OPS_SLACK}, …]` in config order, whether or not `OPS_SLACK` is set |
| S4 | must | the store file deleted / unreadable after `serve` started | 200 with `schema: unavailable`, `revision: null`, `checks.retired: null`; the page reads "Could not be read" and Retired "—" |
| S5 | must | a store migrated by a newer tablewatch (unknown revision) | `schema: newer`, `revision` = that id; page "Newer than this tablewatch (<id>)" |
| S6 | must | an empty store (no tables) | `schema: empty`, `revision: null`, `checks.retired: null` (no registry to read); page "Nothing recorded yet" |
| S7 | must | 3 active, 1 disabled loaded, 2 retired in the store | `checks: {active: 3, disabled: 1, retired: 2}` |
| S8 | must | `results: {migrate: never, sync: manual}` | page shows both sentences of S-D6 |
| S9 | must | any page | nav lists Dashboard, Checks, Datasets, Settings in that order; `/settings` marks Settings `aria-current` |
| S10 | must | a notifier or datasource name holding markup | rendered as text |
| S11 | must | `/settings` load fails | `LoadError` with Retry; the nav still renders |
| S12 | must | `POST /api/v1/settings` | 405 envelope, as every other route |
| S13 | should | no datasources / no notifiers | "No datasources." / "No notifiers configured." |

## Non-goals

Editing anything; whether an environment variable is set; datasource connection details (host,
database, user); a "test connection" button; Alerts, Dashboard panels, Runs (later parts / I-15);
a nav count beside Alerts. Docs: `docs/UI_SPECIFICATION.md` (§3 nav, new §4D Settings),
`docs/api/openapi.json` regenerated, CHANGELOG.
