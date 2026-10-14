Track: full
Size: M
Reviewers: architect, data-steward, qa-engineer, ui-engineer (builder)
Item: I-46 part 5 (owner-fixed; spec written by the tech lead), the last part

## Problem and persona

Priya (data steward) sees `row_count` on `orders` start failing on
Tuesday. Was it the data, or did someone tighten the threshold in a PR on
Monday? The check keeps its id and history across clause edits (spec 032),
so its page shows one unbroken line and nothing says the rule changed.

Marco (platform engineer) runs the shared Postgres store. His DBA team
applies every schema change through Flyway; the tablewatch role must not
hold DDL rights, and a nightly job must not upgrade the schema because a
newer tablewatch was deployed. Today every writer migrates on open.

This part records each check's definition history, and lets a store's
schema be managed outside tablewatch: `tablewatch store sql` emits the DDL,
`results.migrate: never` stops writers from migrating, and `tablewatch
store migrate` upgrades on demand.

## Scenarios

| id | m/s | given | expected |
|----|----|----|----|
| S1 | must | a check's first recorded run | one definition, version 1: its clauses (`key`, `expression` with triggers, `where`, options), `recorded_at`, the `run_id` that first carried it |
| S2 | must | the threshold of one clause changed, then `run` | version 2; the check's id, history and baselines unchanged; results from then on reference version 2 |
| S3 | must | `run` again with no change; the file moved or reformatted; `notify:`, `enabled:` or a dataset's `owner`/`tags` changed | no new version (D-list: what is not a definition) |
| S4 | must | a change reverted (A → B → A) | three versions; never two consecutive equal versions for a check, including two writers recording the same new definition at once (Postgres) |
| S5 | must | `tablewatch sync` (or `results.sync: on_run`) with a changed definition and no run | a new version with `run_id: null`; a check registered by sync and never run has version 1 |
| S6 | must | `GET /api/v1/checks/{id}/definitions` | versions newest first: `version`, `recorded_at`, `run_id`, `clauses`; 404 for an unknown id; works for a retired check |
| S7 | must | history items (`/checks/{id}/history`) | gain `definition_version` (int, null for results recorded before this change) |
| S8 | must | web UI, a check's page | a "Definition" section lists the versions (date, run, clauses, what changed from the previous); the history chart marks where the version changes |
| S9 | must | a store at revision 0008 with history | revision 0009 adds the table and the nullable result column; no backfill (old results have no version); `test_migrations_match_the_models` passes |
| S10 | must | `tablewatch store sql` (no project, no credentials) | PostgreSQL DDL on stdout from an empty database to head, including `tablewatch_alembic_version`; no `BEGIN`/`COMMIT` (the migration tool owns the transaction); exit 0 |
| S11 | must | that SQL applied with `psql` to an empty Postgres, then `run` with `results.migrate: never` | the run records; `schema()` is `current`; the tables match the models (autogenerate finds no difference) |
| S12 | must | `store sql --from 0008` | only 0009's DDL and its version update; `--from` at head prints a comment and nothing else |
| S13 | must | `store sql --from 0006` (a revision after it reads data: 0007, 0008) | exit 3: `revision 0007 rewrites existing rows and cannot be written as SQL — upgrade this store once with \`tablewatch store migrate\``; nothing on stdout; an unknown revision is exit 3 listing the known ones |
| S14 | must | `results.migrate: never`, store at 0008 | `run` scans, reports, then fails to record: exit 2 with `results store: its schema is at revision 0008, this tablewatch needs 0009 — apply \`tablewatch store sql --from 0008\` or run \`tablewatch store migrate\``; a keyed `run`, `sync` exit 2 before scanning; `serve` exits 3; the store is unchanged |
| S15 | must | `results.migrate: never`, empty database | as S14, naming `tablewatch store sql` with no `--from` |
| S16 | must | `tablewatch store migrate` | upgrades to head whatever `results.migrate` says; exit 0 (and `already current` when it was); 2 when the store is unreachable or newer; 3 for an invalid project |
| S17 | must | `results.migrate: never` and a current store, role with only `SELECT, INSERT, UPDATE, DELETE` (Postgres) | `run`, keyed `run`, `sync`, `serve` all work; no DDL attempted |
| S18 | must | `results.migrate: sometimes` | Diagnostic at `tablewatch.yml:line:col` naming `auto`, `never` |
| S19 | should | the read paths' "older store" message under `migrate: never` | names `store migrate` / `store sql --from <rev>` instead of "upgraded by the next run" |

## Design

Decisions (below) override this section where they differ.

- **Definition.** Per clause, in file order: `key`, `expression` (its
  `canonical`, triggers included), `where`, `options` (raw text values).
  Not part of it: location, span, `notify`, `enabled`, dataset owner/tags
  (S3). `fingerprint` = sha256 of its canonical JSON.
- **Table (revision 0009).** `tablewatch_check_definitions`: `id` PK,
  `check_id` FK, `version` (1, 2, … per check; unique with `check_id`),
  `fingerprint`, `definition` (JSON), `recorded_at`, `run_id` (nullable, no
  FK: a definition outlives a deleted run). `tablewatch_check_results`
  gains `definition_id` (nullable FK).
- **Writing.** `results/definitions.py::record_definitions(session,
  checks, run_id, now) -> {check_id: definition_id}`: reads each check's
  latest version in one query, inserts a version where the fingerprint
  differs. Called after `register_all` and the registry lock in `save`
  and `KeyedRun.record_dataset` (results get `definition_id`), and from
  `registry.sync` (S5).
- **`store sql`.** A `store` click group: `store sql [--from REV]` runs
  Alembic offline (`upgrade <from>:head`, `as_sql`) against the
  `postgresql` dialect, without a project. A revision that reads or
  rewrites existing rows declares `REWRITES_ROWS = True` (0004, 0007, 0008);
  offline, its data step is skipped (a database built from nothing has no
  rows), and `--from` before one of them is refused (S13). A test fails if
  a revision calls `op.get_bind()` without the flag.
- **`results.migrate: auto | never`** in `ResultsConfig`. `never`: every
  writer opens with `migrate=False` and `require_current()`; the error
  names the store's revision and the command (S14, S15).
- **`store migrate`.** Opens the project's store with `migrate=True`.

## Non-goals

- Backfilling definitions from recorded results (old results have none).
- Diffing definitions in the CLI (`history`), or alerts on a definition
  change.
- `store sql` for SQLite, Liquibase XML/YAML changelogs, downgrades.
- Changing what feeds check or clause identity.

## Open questions (REFINE)

- Q1 (architect): `definition_id` on every result vs. resolving the
  version by `recorded_at` (out-of-order saves, spec 037 S2); concurrency
  of two writers recording one new version (lock order with
  `heads.lock_checks`, sync not holding it today).
- Q2 (architect): the offline approach — skipping data steps offline and
  `REWRITES_ROWS`, or emitting the head schema from the models instead of
  replaying revisions; PostgreSQL only.
- Q3 (architect): `store` as a group (and `store sql` needing no project),
  `migrate: never`'s failure point for an unkeyed run (at record, after the
  scan, as any store failure today) vs. before scanning.
- Q4 (data-steward): what belongs in a definition (S3's list); whether
  `owner` belongs; what the UI's "what changed" should say.

## Decisions

(REFINE)
