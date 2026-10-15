# Spec 043: Runs open datasources read-only by default (I-47)

- **Track:** full — how user-written SQL is executed (security review required), a config option
  on every datasource, and a behaviour change for existing projects. No store, identity or
  exit-code change.
- **Size:** S–M. **Builder:** tech lead. **Reviewers:** security-reviewer, architect (VERIFY),
  qa-engineer, data-steward. No REFINE: the tech lead decided R-D1–R-D7.
- **Item:** I-47 (owner-approved 2026-10-04; spec by the tech lead). Defence in depth: the
  database role stays the guarantee; I-48 (validate rejects write SQL) follows.

## Problem and persona

Ravi (platform/security) grants tablewatch a read-only role, but in practice roles drift and dev
copies run as owners. A check's `query:`, `filter:` or `where:` is user-written SQL; today `run`
opens every datasource read-write, so a mistaken `query: DELETE …` or a function with side effects
runs with whatever the role allows, and a run against a mistyped SQLite path silently creates an
empty database. `validate --connect` (spec 028) already opens datasources so nothing can be
written; runs should too.

## Decisions (tech lead)

- R-D1. **Who.** `run` (keyed or not), `tw.run()` and `test-connection` open every datasource
  through the read-only path of `create_engine_for` (spec 028 D3) unless the datasource opts out.
  `serve`, `sync`, `list`, `compile`, `validate` (without `--connect`) never connect a datasource.
- R-D2. **Opt-out per datasource:** `read_only: false` on any datasource type (moved to the
  shared base; default `true`). DuckDB's existing `read_only` keeps its name and default, and now
  also means the hardening below. `validate --connect` stays read-only whatever the setting: a
  probe never writes.
- R-D3. **Per engine,** in run mode:
  SQLite — `file:…?mode=ro` URI, `query_only`, no ATTACH (the probe's listener);
  DuckDB — `read_only`, external access off, configuration locked (the probe's listener);
  Postgres — `default_transaction_read_only=on` appended after any user `options`, so it cannot be
  overridden; **no** lock, statement or connect timeouts in run mode (a scan of a warehouse table
  may rightly take minutes; the probe keeps its 10 s / 30 s / 10 s);
  `sqlalchemy` URL — opened as written; read-only is the role's grants (documented), but a SQLite or
  DuckDB file that does not exist is still never created;
  files — read-only by construction (spec 023), unchanged.
- R-D4. **Missing file.** A SQLite or DuckDB datasource whose file does not exist makes every check
  on it `error` with "datasource 'x' in tablewatch.yml: database file not found" — never an empty
  database created (rule 7: one datasource never ends the run; exit 2 as for any error).
- R-D5. **A write attempt** by a check's SQL is an `error` outcome on that check (never `fail`),
  with the database's refusal mapped to fixed words: "the datasource is opened read-only and this
  check's SQL tried to write — set `read_only: false` on the datasource if that is intended". The
  other checks of the dataset and run continue (executor's measure isolation).
- R-D6. `create_engine_for(read_only=…)` becomes `access: Literal["write", "read", "probe"]`
  (`read` = R-D3; `probe` = spec 028's, with timeouts). The runner's default factory and
  `test-connection` pass `"read"` unless `read_only: false` → `"write"`.
- R-D7. Docs: README "Datasources" gains the `read_only` row and a "Read-only runs" paragraph
  (what each engine guarantees, the opt-out, that the role remains the guarantee); CHANGELOG under
  "Changed — breaking" (DuckDB `query:` reading external files now needs `read_only: false`).

## Scenarios

| id | m/s | given | expected |
|----|----|----|----|
| R1 | must | SQLite datasource; check `query: "DELETE FROM orders RETURNING 1"` (or a CTE that inserts) | check `error` with R-D5's words; the table unchanged; other checks pass |
| R2 | must | DuckDB datasource, same write | same as R1 |
| R3 | must | DuckDB `query:` reading `read_parquet('x.parquet')` | `error` (external access off); with `read_only: false` it passes |
| R4 | must | SQLite `path:` to a file that does not exist | its checks `error` "database file not found"; no file or directory created; exit 2 |
| R5 | must | Postgres (CI service): a writing `query:` | `error` R-D5; `SHOW default_transaction_read_only` is `on` in a run; no statement timeout set (`SHOW statement_timeout` = `0`) |
| R6 | must | Postgres `options: {options: "-c default_transaction_read_only=off"}` | still read-only (ours is appended last) |
| R7 | must | any datasource with `read_only: false` | writes allowed as before (the opt-out works) |
| R8 | must | `validate --connect` with `read_only: false` | still read-only (probe) |
| R9 | must | `test-connection` on a missing SQLite file | FAILED "database file not found"; nothing created |
| R10 | must | the retail example and the acceptance kit | `run` results unchanged |
| R11 | must | ATTACH / `VACUUM INTO` / `COPY … TO` in a `query:` | `error`; no file created |
| R12 | should | `sqlalchemy` URL datasource with `read_only: true` | opens as written; README says the role is the guarantee |

## Non-goals

Parsing SQL to reject writes before running (I-48); per-check opt-out; read-only for the results
store (it is written by design); statement timeouts for runs (a separate setting if wanted).
