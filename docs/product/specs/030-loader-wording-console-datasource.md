# Spec 030: Loader wording, a percent written as a fraction, and console rows that can be told apart (I-28, I-45)

- **Track:** light — loader and `validate` wording, one new warning, and console table text. No
  risk trigger: check ids, the store, JSON/JUnit/HTML/API and every exit code are unchanged
  (L9, C6 guard it).
- **Size:** S (batch of two S hardening items with the same reviewers).
- **Reviewers:** qa-engineer, data-steward (the light track's domain reviewer: language and messages).
- **Items:** I-28 (rank 20, 1.0) and I-45 (rank 20a, 1.0), batched as planned in iteration 25.

## Problem and persona

Priya (analytics engineer) writes `missing_percent(email) < 0.05` from Great Expectations habit
(`mostly` is a 0–1 fraction); tablewatch reads 0.05% and the check fails on almost any blank, with
no hint why. Several loader messages mislead her ("must be a integer", "give one of them an explicit
`id:`" when both have one, a phantom "duplicate check" after a bad `where:`). Sam (on-call) runs one
project against `staging` and `prod`: the console shows two identical `orders row_count > 0` rows,
and two unnamed `failed_rows` checks read alike; he opens `--output json` to tell them apart.
Research: Soda's percent thresholds are 0–100, `%` optional ([Soda missing metrics](https://docs.soda.io/soda-cl/missing-metrics.html)); we keep that and warn on the ambiguous case.

## Decisions taken in PLAN (light track; the tech lead may amend)

- P-D1. The fraction warning fires for a **bare** number strictly between 0 and 1 compared with a
  `*_percent` metric — in a condition, a `between` bound, or a `warn:`/`fail:` trigger. `0.05%` is
  explicit and silences it; `0`, `1`, `5` never warn. A warning, so exit codes are unchanged.
- P-D2. The console adds a `DATASOURCE` column (after `DATASET`, as `tw list` does) only when the
  run's results span more than one datasource; a one-datasource run's table is byte-for-byte as today.
- P-D3. Rows that still read alike (same datasource, dataset and CHECK text) each get their source
  location after the name: `failed_rows (checks/a.yml:5)`. Applied after clipping, so the location is
  never clipped. Covers unnamed `failed_rows`/`sql_metric`, two `where:` variants, and equal `name:`s.

Fixture: a project with datasources `staging` and `prod` (SQLite, `orders(id, email, amount)`);
`checks/a.yml` on `staging`, `checks/b.yml` on `prod`.

## Scenarios

| id | | Given | Expected |
| --- | --- | --- | --- |
| L1 | must | `- missing_percent(email) < 0.05` (a.yml:4) | `checks/a.yml:4:5: warning: 0.05 on missing_percent means 0.05%, not 5% — write 5% for five percent, or 0.05% if 0.05% is meant`; `validate` exit 0, closing line `… — no errors, 1 warning`. Today: silent |
| L2 | must | `< 0.05%`; `< 5`; `< 5%`; `= 0`; `row_count > 0.5`; `avg(amount) < 0.05` | no warning (explicit `%`, ≥ 1 or 0, or not a percent metric) |
| L3 | must | `invalid_percent(status)` with `warn: when > 0.01`, `fail: when > 0.1`; and `duplicate_percent(id) between 0.01 and 0.5` | one L1-form warning per bare fraction (two each), at the check |
| L4 | must | L1 in `tw run` | the warning on stderr, the check still runs and is evaluated as 0.05%; exit as the data says |
| L5 | must | `valid_length: abc` | `` `valid_length:` must be an integer``. Today: "a integer" |
| L6 | must | `valid_values:` as a block list of only empty `-` items | `` `valid_values:` is empty: each `-` has nothing after it, which is null in YAML. Fill in the values you meant``; exit 3. Today: "has no values: null is not a value …" |
| L7 | must | `validate` on 1 dataset with 1 check; then 2 and 2 | `tablewatch: 1 dataset, 1 check — no problems found`; `2 datasets, 2 checks — …`; same on the error, warning and `--connect` closing lines. Today: "1 datasets, 1 checks" |
| L8 | must | two `schema` checks on one dataset (lines 12, 14), no `id:` | `checks/a.yml:14:5: error: duplicate check (also at checks/a.yml:12:5) — put both lists in one \`schema\` check, or give one of them an explicit \`id:\`` |
| L9 | must | two checks with `id: same` (lines 8, 10) | `checks/a.yml:10:5: error: the id 'same' is already used at checks/a.yml:8:5 — ids must be unique in the project`. Today: "give one of them an explicit `id:`" |
| L10 | must | `row_count > 0: {where: [1]}` (line 5) and `row_count > 0` (line 7) | only `checks/a.yml:6:14: error: \`where:\` must be a non-empty string`; no "duplicate check" at 7:5. Today: both |
| L11 | must | the retail example and the iteration-9 identity fixtures | every check id equal to `main`'s (no change to what feeds the hash) |
| C1 | must | fixture: `row_count > 0` on `orders` in both datasources; `tw run` | header `OUTCOME  DATASET  DATASOURCE  CHECK  VALUE  DETAIL`; rows `orders  staging` and `orders  prod`. Today: two identical rows |
| C2 | must | only `checks/a.yml` selected (one datasource) | header and rows exactly as today: no `DATASOURCE` column |
| C3 | must | two unnamed `failed_rows` (`amount < 0` at a.yml:5, `amount > 100` at a.yml:7) | CHECK cells `failed_rows (checks/a.yml:5)` and `failed_rows (checks/a.yml:7)`; other rows unchanged |
| C4 | must | the same check text on different datasources (C1) | no location suffix: the DATASOURCE column already tells them apart |
| C5 | should | two alike checks whose names exceed the 48-character clip | name clipped, then ` (checks/…:N)` appended whole |
| C6 | must | C1 and C3 with `--output json`, `junit`; `tw report`; `/api/v1` | byte-identical to `main` (names, ids, fields): console only |
| D1 | must | `docs/check-language.md` "Values and units" | one sentence: a `*_percent` threshold is 0–100; a bare fraction warns (L1) |

## Non-goals

- Changing a check's stored or displayed `name` (failed_rows showing its condition) anywhere but the console table.
- A `DATASOURCE` column in `runs`, `history`, the HTML report or JUnit names.
- Warning on bare numbers ≥ 1 for percent metrics, or making `%` mandatory (an error would break
  working projects).
- `change()` over percent metrics (I-07 part 3).

## Open questions (for the tech lead; no REFINE on the light track)

- Q1. L1's position: the check (as other expression diagnostics), or the number's own column if the
  parser can carry the token offset to the AST cheaply? Proposed: the check.
- Q2. P-D3's suffix form: the location (proposed: covers every collision) vs. a `failed_rows`
  condition (more readable, misses `where:` and `sql_metric`). The data-steward judges in VERIFY.

## Decisions


- Q1 — at the check, as every other expression Diagnostic: no AST offsets for one warning.
- Q2 — the source location: it is the one suffix that separates every collision.
