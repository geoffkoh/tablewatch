# Spec 014: An undefined datasource shown by name; counts name their unit (I-35 part 2, I-43)

- **Track:** full: changes the public `Dataset.datasource` meaning and the `/checks`, `/checks/{id}` and `/checks/{id}/sql` wire content.
- **Size:** S (batch: I-35 part 2 + I-43; both are check-page wording with the same reviewers).
- **Reviewers:** architect (REFINE), security-reviewer (REFINE, Q4 only), data-steward (REFINE wording + VERIFY), qa-engineer (VERIFY), ui-engineer builds the page part.
- **Status:** planned (iteration 14 PLAN, 2026-10-02). Backlog: I-35 (in progress, part 2), I-43.

## Problem and persona

**Priya, data steward** (reads the check page, does not edit YAML) opens a
check whose file says `datasource: warehous`. The Datasource row is blank and
the SQL section says "this dataset's datasource is not defined; run tablewatch
validate". She cannot tell what was written, so she cannot tell Sam what to
fix; she copies the check id to Sam, who opens the file. Measured on `0c63251`:
the loader turns an unknown name into `""` (`config/loader.py:288`), served as
`"datasource": ""`. On the same page, "That one read computes 6 values, for
this check and 6 others" reads as if the check computes values for others
(data-steward, iteration 5). And **Dana** reads `failed_rows` = `3` and
`row_count` = `1,204` with no unit, where `schema` already says `2 problems`.

Research: dbt names the missing target as written ("depends on a node named
'stg_customer' which was not found"), [dbt debug guide](https://docs.getdbt.com/guides/debug-errors).

## Fixture

`tablewatch.yml` defines one datasource `warehouse` (duckdb) and a second,
`staging` (sqlite), so the single-datasource fallback does not apply.

```yaml
# checks/orders.yml                     # checks/customers.yml (no datasource:, no _defaults.yml)
dataset: orders                         dataset: customers
datasource: warehous                    checks:
checks:                                   - row_count > 0
  - row_count > 0
```

## Scenarios

| id | | given | expected |
| --- | --- | --- | --- |
| U1 | must | `tw validate` on the fixture | Diagnostics unchanged: `unknown datasource 'warehous' (defined in tablewatch.yml: staging, warehouse)` at `checks/orders.yml:2:13`, and `no datasource for this dataset — set ...` for customers; exit 3. Today: same |
| U2 | must | `tw.load()`; the `orders` dataset | `dataset.datasource == "warehous"` (the name as written); customers' is `""`. Today: `""` for both |
| U3 | must | `GET /api/v1/checks/{orders row_count id}` | `"datasource": "warehous"`, and the check marked not defined (field shape: Q1). Same on its `/checks` row |
| U4 | must | `GET /api/v1/checks/{id}/sql` for orders | `"datasource": "warehous"`, `"dialect": null`, `"statements": []`, `"error": "datasource 'warehous' is not defined in tablewatch.yml; run tablewatch validate"` |
| U5 | must | `/sql` for customers | `"datasource": ""`, `"error": "this dataset has no datasource; add datasource: to its check file or a _defaults.yml; run tablewatch validate"` |
| U6 | must | Check page, orders | Datasource row reads `warehous (not defined)` (marker styled quiet; exact markup: ui-engineer); the SQL section shows U4's error under "Cannot compile" |
| U7 | must | Check page, customers | Datasource row reads `none set`, styled as Owner's `none`. Not bare `none`: unlike `owner`, a dataset always has a datasource, so the marker must read as a gap, not a valid "no owner" state |
| U8 | must | `tw run`, `tw compile`, `tw list` on the fixture | `tw run` exits 3 before anything runs, as today; `compile` and `list` output and exit codes as today; no traceback anywhere |
| U9 | must | A defined datasource | Every surface byte-identical to today (row, `/sql`, page) |
| W1 | must | Scan with `shared_by: 6`, `measures: 6` | `That one read computes 6 values, used by this check and 6 others.` ("used by", not "for": a check does not compute values for other checks, it shares the read with them — the wording the persona section objects to) |
| W1b | must | Scan with `shared_by: 1`, `measures: 1` (retargets the existing singular test, `frontend/src/test/sql.qa.test.tsx:70-71`, pinned on today's "for this check and 1 other") | `That one read computes 1 value, used by this check and 1 other.` |
| W2 | must | Scan with `shared_by: 0` | `That one read computes 3 values, used by this check only.` |
| W3 | should | One column, `shared_by: 1` in `uses` | `, also used by 1 other check` (unchanged; a different sentence from W1/W1b — listed so the QA test pins it) |
| C1 | must | `failed_rows` returning 1 and 3, DuckDB and SQLite | `display_value` `1 row`, `3 rows`; the message and console VALUE use it; JSON and the store carry it; `value` stays `3` |
| C2 | must | `row_count` = 1204, both backends | `display_value` `1,204 rows`; 0 → `0 rows` (zero is plural, the same rule `schema`'s `count_noun = ("problem", "problems")` already applies via `format_value`) |
| C3 | must | `missing_count`, `duplicate_count`, `sql_metric` | Unchanged (bare numbers) |
| C4 | must | A result recorded before the change | Its stored `display_value` and message are served as stored |
| C5 | should | Check page history chart for `row_count` | Axis ticks stay numbers; the latest label and table show `1,204 rows` (they print `display_value`) |

Every `must` becomes a test; the API ones in `tests/test_server*.py`, the page
ones as vitest with fixtures.

## Non-goals

- No change to loader diagnostics, `validate`, exit codes or check identity
  (`datasource` is not in `derive_check_id`; no id moves).
- No suggestion of the nearest defined name ("did you mean `warehouse`?"); the
  diagnostic already lists the defined names.
- No unit on `missing_count`, `duplicate_count`, `sql_metric` (I-43 as written);
  no rewriting of stored history; no JSON report `schema_version` bump
  (`display_value` is human text, not a contract).
- No change to the run path for undefined datasources: a project with errors
  never runs (`api.py:141`).
- Nothing from iteration 13's "Not added" list.

## Decisions (tech lead, after REFINE)

- **D1 (security Q4, wins over architect Q2 on where):** the loader alone decides. A
  written name is kept only if it fullmatches `DATASOURCE_NAME =
  [A-Za-z0-9_][A-Za-z0-9_.\-]{0,63}` (`checks/model.py`, beside the
  `Dataset`); otherwise `Dataset.datasource` is `""`. Defined names are untouched (U9).
- **D2 (Q1):** `Dataset` gains a provisional `datasource_state`: `"defined"`
  (default) · `"not_defined"` · `"not_a_name"` · `"none"`, set by the loader only.
  The wire gets `datasource_state` on `CheckSummary` (so `/checks` and
  `/checks/{id}`); not on `CheckSql`, whose `error` says why. A string, not the
  architect's bool: a bool cannot tell `not_a_name` from `none` once the name is `""`.
- **D3 (Q2):** `compile_dataset` builds the text from the state and drops
  `UNDEFINED_DATASOURCE`; no `datasource_problem` prefix (that prefix says the
  datasource exists). Texts: U4, U5, and U10's.
- **D4:** `Dataset.datasource` docstring: the name as written, `""` when none is
  set or it is not a name; may be missing from `config.datasources` when the
  project has errors. CHANGELOG line for the meaning change.
- **D5 (I-43):** `count_noun = ("row", "rows")` on `RowCount` and `FailedRows`.
- **D6:** list/compile/run exit 3 before printing a dataset on an invalid project;
  U8 pins that no written name reaches their stdout.
- **Not added (backlog freeze):** the loader diagnostic (`loader.py:346`) echoes the raw name
  to validate and `/project`; test-connection connect errors naming the host.

| id | | given | expected |
| --- | --- | --- | --- |
| U10 | must | `datasource: postgresql://admin:Pa55w0rd@db.prod/x`, and one holding `\x1b[2J` | `datasource: ""`, `datasource_state: "not_a_name"`; `/sql` error `this dataset's datasource: value is not a name defined in tablewatch.yml; run tablewatch validate`; page row `not a datasource name`; password, user, host and escape absent from `/checks`, `/checks/{id}`, `/sql`, list/compile stdout |
| U11 | must | U3/U5 wire | orders `datasource_state: "not_defined"`; customers `"none"`; a defined check `"defined"` |
