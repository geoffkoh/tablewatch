# Spec 032: Named checks, part 1 — the language and evaluation (I-46, A20, Phase 1b)

- **Track:** full — touches `src/` (`dsl`, `config/loader.py`, `checks/model.py`, `engine/evaluate.py`,
  `output/`) and adds a public-shape seam (a check's clauses) that later parts and I-50 build on.
- **Size:** M. Part of I-46 (L), split three ways — see Parts below.
- **Reviewers:** architect (REFINE: Q1–Q2; VERIFY), data-steward (REFINE: Q3; VERIFY acceptance),
  qa-engineer (VERIFY). security-reviewer not triggered: no new dependency, no change to secrets,
  SQL execution path or network surface.

## Problem and persona

Priya's checks today are each one atomic expression; its identity is a hash of file path,
expression text and `where:`. She cannot express "orders are usable" as one named thing with four
related rules — she writes four separate list entries that show up as four unrelated rows in `list`,
`report` and history, with no name to page on or alert on. The roadmap (Phase 1b) commits to naming
every check and giving it clauses before anything else in Phase 2 lands, so every later surface
(store, API, UI, alerting) is built once, against the named shape.

## Parts

| Part | Carries | Size |
| --- | --- | --- |
| **1 (this spec)** | YAML shape (`checks:` as name → clauses), parsing, the `Check`/`Clause` model, worst-clause evaluation, console/JSON/JUnit output. Decision 3 (rename starts new history) and decision 4 (no unnamed shorthand) land here; decision 6 (reserve room for cross-check references) is a naming constraint only. | M |
| **2** | Store redesign: `tablewatch_checks` registry (surrogate id; natural key project/datasource/dataset/name — decision 5), per-clause result rows, shaped together with I-49's run-key/outbox/per-dataset columns so the store migrates once (decision 8). API and UI follow the new identity. | M |
| **3** | Check registry lifecycle and sync surface (decision 7): `enabled: false` → `disabled`; retired when gone from YAML (hidden by default, a returning name resumes id + history); `tablewatch sync` and `results.sync: on_run \| manual`; `tablewatch store sql` DDL; `results.migrate: auto \| never`. | S–M |

Research: Great Expectations' "Expectation Suite" names a set of expectations as one unit but
reports each separately with no combined outcome; Soda's checks are named individually, one outcome
each — neither combines several rules into one named outcome, which is why tablewatch's "worst
clause" rule (owner decision 1) has no prior art to borrow syntax from.

## Part 1: the language and evaluation

### YAML shape

```yaml
dataset: sales.orders

checks:
  orders_usable:
    clauses:
      - row_count > 0
      - missing_count(customer_id) = 0
      - invalid_percent(status) < 1%:
          valid_values: [pending, shipped, delivered, cancelled]
      - freshness(created_at):
          warn: when > 6h
          fail: when > 24h
```

`checks:` is now a mapping of name → `{clauses: [...]}`. Each clause is exactly what a check entry is
today (a bare expression string, or a mapping of expression → options/`warn`/`fail`/`where`). A
check's outcome is the worst of its clauses' outcomes (`error` > `fail` > `warn` > `pass`); `error`
on one clause does not skip evaluating the others. `id:` is no longer a recognised key anywhere — a
check's name is its only identity (decision 3); this is breaking, with no migration path, because
nothing is released yet (0.1.0 is not on PyPI) — decided by the owner's 2026-09-27 precedent
(identity changes before the first release, no history migration).

### Scenarios

| id | | given | expected |
| --- | --- | --- | --- |
| S1 | must | the YAML above, `validate` | exit 0, no diagnostics |
| S2 | must | `list` on S1's project | one row named `orders_usable`, not four unnamed rows (today: four) |
| S3 | must | `checks:` as a bare list of expression strings (today's shape) | `validate` diagnostic at `checks:`'s line:col: ``"checks:" is a mapping of name to clauses — a list is the old unnamed shorthand, no longer supported``; exit 3 (today: loads and runs) |
| S4 | must | two checks both named `orders_usable` in one file | diagnostic at the second occurrence's line:col: ``duplicate check name "orders_usable" — names must be unique within a dataset``; exit 3 |
| S5 | must | `orders_usable` above; `row_count > 0` and `missing_count` pass, `freshness` triggers its `warn` | `run` outcome for `orders_usable` is `warn`; console shows one check row, outcome `WARN` (uppercase, the check's own outcome, what exit code and history key on), followed by its four clauses as indented sub-rows in YAML order (not severity order, so the layout is stable run to run), each with its own lowercase outcome, value and message: `pass  row_count > 0`, `pass  missing_count(customer_id) = 0`, `pass  invalid_percent(status) < 1%`, `warn  freshness(created_at)` (literal block under D7) |
| S6 | must | S5's data, but `customer_id` column dropped from the table | `missing_count` clause outcome `error`; check outcome `error` (ranks above the sibling `warn`); the other three clauses still evaluate and show their own outcome (today: one bad column only errors its own check — unchanged, now scoped to the clause) |
| S7 | must | S1's YAML, `compile` | one `SELECT` for `sales.orders` folding every clause's aggregate measure (rule 1 unchanged) |
| S8 | must | JSON reporter on S5 | one result per check with `"name"`, `"outcome"` (the worst clause) and `"clauses": [{"expression": ..., "outcome": ..., "value": ...}, ...]`; `schema_version` bumped (a wire contract) |
| S9 | must | JUnit reporter on S5 | one `<testcase name="orders_usable">` (not four) with the check's outcome; clause detail in `<system-out>` |
| S10 | must | a clause mapping with `id: abc123` (today's per-check override) | diagnostic at `id:`'s line:col: ``"id:" is not used here — a check's name is its identity``; exit 3 |
| S11 | must | a check named `orders.usable` (contains `.`) | diagnostic at the name's line:col: ``check name "orders.usable" is not valid — use letters, digits, "_" and "-", starting with a letter``; exit 3 (decision 6, nothing built yet) |
| S12 | must | `tablewatch schema` (editor JSON Schema) | accepts the named shape; rejects a bare list under `checks:` |
| S13 | must | `_defaults.yml` sets `where:` / options today inherited per check | inherited by every clause, as today by every check |
| S14 | must | `run --check orders_usable`, `history orders_usable` | select / show the named check (selection and `history` take the name; Q5 settles the stored key) |
| S15 | must | S1's file moved to another folder under `checks/`, then `run` | the check keeps its identity and history (file path no longer feeds it) |

## Non-goals

- Persisting per-clause results to the store, or any store/migration change (part 2).
- Lifecycle, sync, `tablewatch sync`, `results.sync`, `store sql` DDL, `results.migrate` (part 3).
- Checks referencing other checks (`dataset.check`, `dataset.check.clause`) — only the `.` reservation
  in S11 lands here.
- `requires:` preconditions (I-50), resumable runs (I-49), app shell changes (I-51).
- `any` / `at least N` clause combination — only "all must hold" (owner decision 1, fixed).
- Renaming tooling or a rename-mapping file (owner decision 3: a rename starts a new history, full stop).

## Open questions

- **Q1 (architect).** Model shape: does `Check` keep one dataclass with a new `clauses: list[Clause]`
  field (where `Clause` holds today's `metric`/`expression`/`options`/`warn`/`fail`/`where`), or does
  today's single-expression `Check` become `Clause` and a new `Check` wraps a `name` and a list of
  them? Decide the seam so `engine/evaluate.py` and `output/` have one place to fold clause outcomes
  into the check's.
- **Q2 (architect).** `engine/planner.py`/`executor.py` assume one measure set per check today; with
  N clauses per check, confirm the fold is unchanged (still one scan per dataset, rule 1) and that a
  clause's own measure failure only errors that clause (S6), not sibling clauses in the same check.
- **Q4 (architect + data-steward).** Clause identity. `dataset.check.clause` references (decision 6)
  and per-clause history need a clause key, unique within the check. Options: an optional `name:` per
  clause with a derived default (the metric call, e.g. `missing_count(customer_id)`), clauses as a
  name → clause mapping, or position. Which survives editing a clause's threshold, and what is the
  diagnostic for two clauses with the same key?
- **Q5 (architect).** Recording in part 1, before part 2's registry: what key do `run`, `history`,
  `change()`, selection and `/api/v1/checks` use, and what row(s) does a run write — one per clause
  under the existing schema (check id = hash of datasource, dataset, name; clause key alongside), or
  should the store change move into this part? Whatever part 1 writes is thrown away by part 2
  (nothing is released), so prefer the smallest change that keeps every surface working.
- **Q3 (data-steward).** Exact wording for S5's per-clause console breakdown (indentation, the order
  clauses print in — file order or outcome-severity order) and S11's reserved-character list (just
  `.`, or also `:` and `/`, kept for future dotted/path-shaped references).

## Decisions


Recorded by the tech lead after REFINE (architect: Q1, Q2, Q4, Q5; data-steward: Q3, Q4).

- **D1 (Q1) Model.** Today's `Check` becomes `Clause`, its body unchanged (metric, expression,
  triggers, `where`, options, span) plus `key` and a back-reference `check`. A new `Check` holds `id`,
  `name`, `dataset`, `location` (the name's key), `notify`, `clauses`. In `engine/runner.py`, today's
  `CheckResult` becomes `ClauseResult`; a new `CheckResult(check, clauses)` computes `outcome` as a
  property — the one fold; console, JSON, JUnit, notify and the exit code read it. `MetricContext.check`
  is renamed `clause`.
- **D2 (Q1) Skipped.** A check is `skipped` when every clause is skipped; otherwise the worst of its
  non-skipped clauses (`error` > `fail` > `warn` > `pass`).
- **D3 (Q2) One scan.** The planner loops over clauses; `wiring`/`contexts`/`errors` key by clause id;
  the executor is unchanged. A failing measure errors exactly the clauses wired to it (S6).
- **D4 (Q4) Clause key.** An optional clause `name:` is its key; the default is the metric call without
  its rule (`missing_count(customer_id)`, `change(row_count)`). Tightening a threshold, editing options
  or reordering keeps the key. Two clauses with one key are a diagnostic at the second:
  `duplicate clause "row_count" in check "orders_usable" — give one of them a name:`. The stored clause
  id hashes the check id, the key, `where:` and the metric's identity options, so changing what is
  measured starts that clause's history while its key stays. Today's display `name:` ("Order volume")
  no longer exists as a label: a clause `name:` follows the name pattern (D6).
- **D5 (Q5) Store in part 1: no schema change.** A run writes one summary row per check (`check_id` =
  `derive_check_id(datasource, dataset, name)`, outcome the worst, value and measured NULL, metric
  `"check"`) and one row per clause (`check_id` = an independent hash, D4 — never a prefix-extension of
  the check id). `run --check`, `history`, `latest_results`, state and `/api/v1/checks` read summary
  rows; `change()` baselines read clause rows. Readers listing a whole run (`store.run`, run detail,
  totals) take summary rows. Part 2 replaces this.
- **D6 (Q3) Names.** Check and clause names match `^[A-Za-z][A-Za-z0-9_-]{0,63}$`, reserving `.`, `:`
  and `/` for later references. S11's message: ``check name "orders.usable" is not valid — use letters,
  digits, "_" and "-", starting with a letter``. A derived clause key is not a name and is not checked
  against the pattern; a later reference to it is the reference grammar's problem (split from the right,
  skip parentheses) or needs an explicit `name:`.
- **D7 (Q3) Console.** The data-steward's block in S5: check row uppercase outcome, VALUE blank, DETAIL
  a tally (`3 pass, 1 warn`); clause rows indented two spaces, lowercase outcome, file order:
  ```
  OUTCOME  DATASET  CHECK                           VALUE  DETAIL
  WARN     orders   orders_usable                          3 pass, 1 warn
    pass            row_count > 0                    5,000  rows
    pass            missing_count(customer_id) = 0       0
    pass            invalid_percent(status) < 1%     0.00%
    warn            freshness(created_at)            7h 12m  newest row at …; warn: > 6h, fail: > 24h
  ```
- **D8 JSON.** Each clause carries `key`, `expression`, `outcome`, `value`, `message` (the audit needs
  the words). `schema_version` bumps.
- **D9 One-clause shorthand (tech lead).** `name: <expression string>` is a one-clause check; anything
  with options, triggers or several clauses uses `clauses:`. Named, so decision 4 holds.
- **D10 Breaking change.** Old list-shaped files are a diagnostic (S3); no history migration (owner's
  2026-09-27 precedent: identity changes before the first release, no migration).
