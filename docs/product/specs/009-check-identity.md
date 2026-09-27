# Spec 009: Two `failed_rows` checks on one table are two checks

| | |
| --- | --- |
| Backlog item | I-33 (data-steward, iteration 5 VERIFY; owner decision 2026-09-27; next by iteration 8 REVIEW) |
| Features | A (language hardening) |
| Phase | 2 (`0.2.0`); **gate: before the first PyPI release** |
| Size | S |
| Depends on | the owner's decision (option 1, 2026-09-27, ITERATIONS.md): change the id now, **no history migration** |
| Branch | `iter/009-check-identity` |
| Status | **ready** (iteration 9 PLAN, 2026-09-28, against `main` at `efa1a4e`). Every "today" id below was measured on `main` by loading the exact files with `tablewatch.load()` and the CLI; every "after" id was computed with the derivation in "The derivation", below |

## Problem and persona

**Dana, data engineer.** "Orders have two business rules I can't write
with the built-in metrics: no negative totals, and no order without a
customer. I wrote two `failed_rows` checks, one per rule, like the docs
show. `validate` said one was a duplicate of the other, and `run` did
nothing at all, not even `row_count`."

```yaml
dataset: orders

checks:
  - failed_rows:
      condition: total < 0
  - failed_rows:
      condition: customer_id is null
```

Reproduced on `main` (`efa1a4e`), DuckDB project, no database needed:

```text
$ tablewatch validate
checks/orders.yml:6:5: error: duplicate check (also at checks/orders.yml:4:5) — give one of them an explicit `id:`
tablewatch: 2 datasets, 2 checks — 2 errors
exit=3
$ tablewatch list
…same two errors…
tablewatch: 2 errors in the project — nothing ran
exit=3
```

The same for two `sql_metric > 0` checks with different `query:`
(`checks/metrics.yml:6:5` duplicates `4:5`). A different `name:` does not
help (measured: `name: A` and `name: B` still collide). A different
`sql_metric` label does (`sql_metric(a)` vs `sql_metric(b)`), because
the label is part of the expression.

**Why.** Without an explicit `id:`, a check's id is
`sha1(path \0 dataset \0 canonical \0 where)[:16]`
(`checks/model.py: derive_check_id`). Options are left out on purpose:
refining `valid_values` is the same check, better stated. But for these
two metrics the option *is* the check: `condition:` and `query:` say
what is measured, not how well. With them left out, every bare
`failed_rows` on one dataset in one file has the canonical text
`failed_rows` and the same id.

**How they cope today.** They add `id:` to every `failed_rows` and
`sql_metric` check, as the error says. It works, but it is a rule nobody
guesses (the data-steward hit it on a first try), and a project that
forgets it runs **nothing** (exit 3), so one new rule stops the whole
night's checks.

**Sam, data steward**, reads history on the check page. For him the
change costs one thing: those checks' history starts again once, on
upgrade (below). The owner accepted that before the first release, when
the only history that breaks is the owner's own.

### What others do

- **Soda** identifies a check in Soda Cloud by "the check definition, the
  check YAML file name, and the file's location"; any edit to the
  definition, even a threshold, makes a new check and drops its history,
  and an explicit `identity` keeps it
  ([Soda: optional check configurations](https://docs.soda.io/sodacl-reference/optional-config)).
  tablewatch already works this way, with `id:` as the explicit identity.
  The SQL of a Soda user-defined check is part of its definition.
- **dbt** builds a generic test's `unique_id` from the test name and
  **all** its arguments, hashed when the name gets long, so two
  `expression_is_true` tests with different expressions are different
  tests; a custom `name` gives full control
  ([dbt-core #3254](https://github.com/fishtown-analytics/dbt/issues/3254),
  [dbt #4898](https://github.com/dbt-labs/dbt/pull/4898),
  [dbt: data tests](https://docs.getdbt.com/reference/resource-properties/data-tests)).

Borrowed: the SQL that defines the check is part of its identity; an
explicit id still wins. Not borrowed: dbt's "every argument" rule.
Refinement options (`valid_values`, `missing_values`, `schema`'s lists)
stay out, as `docs/check-language.md` promises.

## Outcome

Two `failed_rows` checks on one dataset in one file, with different
`condition:`, are two checks with two ids and two histories, and
`validate` and `run` accept them. Likewise two `sql_metric` checks with
different `query:`. Reflowing the SQL across lines keeps its id.
Every other check keeps the id it has today, to the character.

## The derivation

`condition:` (`failed_rows`) and `query:` (`sql_metric`) feed the derived
id. The input to the digest becomes:

```text
today, unchanged for every other check:
  {path}\0{dataset}\0{canonical}\0{scope}
failed_rows / sql_metric only:
  {path}\0{dataset}\0{canonical}\0{scope}\0{option}={normalised}
```

- `{option}` is the option's name: `condition` or `query`. Naming it
  keeps a future metric that opts in from sharing a key space with these.
- `{normalised}` is the option's value **after YAML parsing**, with every
  run of whitespace collapsed to one space and the ends stripped:
  `" ".join(value.split())`, the same rule `where:` already uses.
- The digest stays `sha1(…)[:16]`, as today.
- For every metric that has no such option, the input string is
  **byte-identical** to today's, so its id does not move. This is the
  property the tests guard hardest (M5, M6).

REFINE may change the exact encoding (Q1). If it does, the "after" ids in
this spec are recomputed with it before BUILD; the properties (M1–M12)
do not change.

### What counts as a reformat (keeps the id)

| Edit to `condition:` / `query:` | Id |
| --- | --- |
| Spaces, tabs or newlines added, removed between words, or changed in number (`total  <  0` → `total < 0`) | kept |
| One line → a YAML block scalar, `|` or `>`, over several lines, with any indentation | kept |
| Quoting style in YAML: plain, `'…'`, `"…"` | kept (compared after parsing) |
| Leading or trailing whitespace, a final newline | kept |
| Whitespace **removed entirely** between two tokens (`total < 0` → `total<0`) | **new id** — tablewatch does not parse the SQL |
| Letter case (`AND` → `and`, `NULL` → `null`) | **new id** |
| A SQL comment added or edited (`-- why`) | **new id** |
| A trailing `;`, added parentheses, reordered terms | **new id** |
| Any change of meaning | **new id** |

Two consequences, both accepted for PLAN and put to the data-steward in
REFINE (Q2):

- Whitespace **inside a string literal** is collapsed too, so
  `status = 'a  b'` and `status = 'a b'` get the same id. Two checks that
  differ only there are reported as duplicates (loud, fixable with an
  `id:`), never silently merged.
- `total<0` and `total < 0` are different ids, unlike the check
  expression, where `row_count>0` and `row_count > 0` are the same. The
  expression is parsed by tablewatch; the SQL is not, and parsing it per
  dialect is a non-goal. `where:` already behaves exactly this way.

### Which ids change

Only checks whose metric is `failed_rows` or `sql_metric` **and** that
have no explicit `id:`. Every such check gets a new id, whether or not it
collided before (the owner accepted this: option 1).

In `examples/retail` that is one check, and one row of
`tests/golden/retail-list.txt`:

| Check | File | Today | After |
| --- | --- | --- | --- |
| `failed_rows`, `name: No negative amounts`, `condition: amount < 0` | `checks/sales/orders.yml:15:5` | `ed669ca6e5532a59` | `e2948c41d4b15c10` |

The golden row changes from

```text
ed669ca6e553  sales.orders        lake        No negative amounts               checks/sales/orders.yml:15:5
```

to

```text
e2948c41d4b1  sales.orders        lake        No negative amounts               checks/sales/orders.yml:15:5
```

The row stays at line 18 (`list` orders by dataset and source position,
not id). **The other 17 rows do not change, and neither does
`retail-compile.txt` or `retail-compile-sales.txt`** (they print no ids).
retail has no `sql_metric` check.

Tests that pin today's id, updated in the same PR, and nothing else:
`tests/test_check_detail.py:27` (`ORDERS_NEGATIVE`),
`tests/test_check_source.py:100` and `:141`. The frontend's test
fixtures (`frontend/src/test/fixtures/*.ts`, `sql.test.tsx`) hold
`ed669ca6e5532a59` as a canned API response; an id is opaque to the UI,
so they stay valid and are **not** touched (no ui-engineer work).

### What changes for a project with history (the breaking part)

On the first run after upgrading, each `failed_rows` and `sql_metric`
check without an `id:` records under its new id. Nothing is migrated and
nothing is deleted (owner, option 1):

- On the overview and the check page it shows as a check with no results
  yet, then builds history from that run. "Failing since" starts again.
- Its old results stay in the store under the old id and remain
  readable: `tablewatch history <old id>` and
  `/api/v1/checks/<old id>/history` (history outlives the check,
  spec 002).
- A check with an explicit `id:` is untouched. Adding `id:` **before**
  upgrading does not keep the old history either, because an explicit id
  is a different id from the derived one. To keep the old history, set
  `id:` to the **old derived id** (the 16 characters shown by
  `tablewatch list --output json` or the check page before upgrading).
  The CHANGELOG says so.

## Acceptance scenarios

All scenarios load with no credentials (rule 6); the ones that run use
DuckDB **and** SQLite. "Today" ids were measured on `efa1a4e`.

### Fixture

`tablewatch.yml`:

```yaml
name: identity
datasources:
  lake:
    type: duckdb   # and a second project with type: sqlite
    path: lake.duckdb
```

Table `orders(order_id, customer_id, total, region, status, created_at)`
with rows: `(1, 10, 25.0, 'eu', 'paid', …)`, `(2, NULL, 40.0, 'us',
'paid', …)`, `(3, 11, -5.0, 'eu', 'paid', …)`, and table
`customers(customer_id)` with 2 rows.

### Must: the collision is gone

**M1 (must) Two `failed_rows` with different conditions load and run.**
Given `checks/orders.yml`:

```yaml
dataset: orders

checks:
  - failed_rows:
      condition: total < 0
  - failed_rows:
      condition: customer_id is null
```

When `tablewatch validate`, then exit 0, `1 datasets, 2 checks — no
problems found` (today: exit 3, a duplicate at `6:5`; I-28 owns the
"1 dataset" wording). The ids are `a37eb03d163d2dac` and
`3659f64dd11643df` (today both would be `d3003f92cee3be0f`). When
`tablewatch run`, then both checks fail with value `1` each, exit 1, and
both results are recorded under those ids.

**M2 (must) Two `sql_metric` with different queries load and run.**
Given `checks/orders.yml`:

```yaml
dataset: orders

checks:
  - sql_metric > 0:
      query: select count(*) from orders
  - sql_metric > 0:
      query: select count(*) from customers
```

When `validate`, then exit 0, 2 checks. The ids are `5319e7f87bb73935`
and `2c3087d4a224ea57` (today both `b68ef2d84375cb8e`). When `run`,
then both pass (values `3` and `2`), exit 0.

**M3 (must) The same SQL twice is still a duplicate, with today's
message.** Given

```yaml
dataset: orders

checks:
  - failed_rows:
      condition: total < 0
  - failed_rows:
      condition: >
        total   <
        0
```

When `validate`, then exit 3 and exactly one diagnostic:
`checks/orders.yml:6:5: error: duplicate check (also at
checks/orders.yml:4:5) — give one of them an explicit \`id:\`` — the
same text and position rule as today. Likewise two `sql_metric > 0` with
`query: select 1` and `query: "select   1\n"`.

### Must: reformatting keeps the id

**M4 (must) Whitespace, block scalars and quoting keep the id.** Given
M1's first check, and in turn each of these in its place:

```yaml
  - failed_rows:
      condition: "total  <  0"
```

```yaml
  - failed_rows:
      condition: |
        total
          < 0
```

```yaml
  - failed_rows:
      condition: >-
        total <
        0
```

```yaml
  - failed_rows:
      condition: '	total < 0   '   # a leading tab
```

When loaded, then the id is `a37eb03d163d2dac` every time. And each of
`total<0`, `TOTAL < 0`, `total < 0 -- negatives`, `(total < 0)` gives an
id that is **not** `a37eb03d163d2dac`. The same table of edits applied
to M2's first `query:` keeps `5319e7f87bb73935` for whitespace and
changes it for case, comments and `;`.

### Must: nothing else moves

**M5 (must) Every other metric keeps today's id, to the character.**
Given `checks/orders.yml` (a check per built-in metric, triggers,
`where:` and options; measured on `efa1a4e`):

```yaml
dataset: orders

checks:
  - row_count > 0
  - row_count:
      warn: when < 100
      fail: when = 0
  - row_count > 0:
      where: region = 'eu'
  - missing_count(customer_id) = 0
  - missing_percent(email) < 5%:
      missing_values: ['', 'N/A']
  - invalid_count(status) = 0:
      valid_values: [pending, shipped]
  - invalid_percent(email) < 1%:
      valid_regex: '^[^@]+@[^@]+$'
  - distinct_count(status) between 1 and 10
  - duplicate_count(order_id) = 0
  - duplicate_percent(order_id, line) < 1%
  - min(total) >= 0
  - max(total) < 100000
  - avg(total) between 10 and 500
  - sum(total) > 0
  - freshness(created_at) < 6h
  - schema:
      required_columns: [order_id]
  - sql_metric(orders_today) > 0:
      id: orders-today
      query: select count(*) from orders
  - failed_rows:
      id: no-negative-totals
      condition: total < 0
```

When loaded, then the ids are exactly, in order:

| Check | Id |
| --- | --- |
| `row_count > 0` | `bf60e0de98af522e` |
| `row_count \| warn when < 100 \| fail when = 0` | `d819df42ff59dbc4` |
| `row_count > 0` with `where:` | `2b59a5867efd0523` |
| `missing_count(customer_id) = 0` | `9bb8f5410e52896b` |
| `missing_percent(email) < 5%` | `e8097a71ecdf05c6` |
| `invalid_count(status) = 0` | `411abd1075a5408b` |
| `invalid_percent(email) < 1%` | `eaefe6cfca74ce15` |
| `distinct_count(status) between 1 and 10` | `46e59733b85749bf` |
| `duplicate_count(order_id) = 0` | `cb4d8d6e75ffceff` |
| `duplicate_percent(order_id, line) < 1%` | `30150163c7f9ff86` |
| `min(total) >= 0` | `06952f228e3c7019` |
| `max(total) < 100000` | `32ed55133b852b47` |
| `avg(total) between 10 and 500` | `1997ce366d684c5d` |
| `sum(total) > 0` | `69f297516fb36ee5` |
| `freshness(created_at) < 6h` | `3a3a65e2a3d55f4e` |
| `schema` | `63602d44bd3ef56c` |
| `sql_metric(orders_today) > 0` | `orders-today` |
| `failed_rows` | `no-negative-totals` |

This test is written and green **on `main` before the change**, then
kept (a regression guard written first).

**M6 (must) retail's `list` golden moves by one row.** When
`tablewatch --project-dir examples/retail list`, then the output equals
`tests/golden/retail-list.txt` with only line 18's id changed from
`ed669ca6e553` to `e2948c41d4b1` (above); a diff of the golden file in
the PR shows exactly that one line. `retail-compile*.txt` unchanged.
`tablewatch run` on retail still exits 1 with the same outcomes as
today (the planted defects), and "No negative amounts" still fails.

**M7 (must) An explicit `id:` is unaffected by the SQL.** Given

```yaml
  - failed_rows:
      id: no-negative-totals
      condition: total < 0
```

when `condition:` is changed to `total <= 0`, then the id is still
`no-negative-totals`. Same for `sql_metric` and `query:`.

**M8 (must) Two checks with the same explicit id are still a
duplicate**, whatever their SQL: two `failed_rows` with `id: x` and
different conditions give today's duplicate diagnostic at the second.

### Must: the new input behaves like the others

**M9 (must) Changing the SQL's meaning starts a new history.** Given M1
run and recorded once, when `condition: total < 0` is changed to
`condition: total <= 0` and run again, then the check records under a
new id and `/api/v1/checks/a37eb03d163d2dac/history` still returns the
first result (history outlives the check).

**M10 (must) `where:` and `condition:` both count, and don't alias.**
Given

```yaml
  - failed_rows:
      condition: total < 0
  - failed_rows:
      condition: total < 0
      where: region = 'eu'
```

then two ids: `a37eb03d163d2dac` and `dfb329f67a687a64`. And a
`failed_rows` whose `where:` is `A` and `condition:` is `B` has a
different id from one whose `where:` is `B` and `condition:` is `A`.

**M11 (must) The file path and dataset still count.** M1's first check
moved to `checks/finance/orders.yml` gets a different id from
`a37eb03d163d2dac`; so does the same check under `dataset: orders_v2`.

**M12 (must) Docs.** `docs/check-language.md`, "Check identity", says
(wording may be polished by the data-steward, the facts may not):

- the id is derived from the file path, the dataset, the normalised
  expression and triggers, the `where:` scope, **and, for `failed_rows`
  and `sql_metric`, the `condition:` or `query:`**;
- reflowing that SQL (spaces, tabs, line breaks, YAML block style) keeps
  the id; any other edit to it, including case, comments and removing
  the space between two words, starts a new history;
- other options, such as `valid_values` or `schema`'s column lists, still
  do not count: refining a rule is the same check;
- two checks that would get the same id are an error; give one an `id:`.

The `derive_check_id` docstring says the same. `tests/test_docs.py`
still passes.

### Should

**S1 (should) The `sql_metric` label is not needed to tell queries
apart.** `docs/check-language.md`'s `sql_metric` row stops implying the
label is how to distinguish two queries (it does not today, but check
the wording).

**S2 (should) Hostile input.** A `condition:` or `query:` holding a NUL
(`"total < 0\0x"` in a double-quoted YAML string), a very long query
(100 KB), or only whitespace: the loader never raises; the
whitespace-only case is today's "needs a condition" / "must be a
non-empty string" error at the option's `file:line:col`, not an id.

**S3 (should) The CHANGELOG entry** (written in REVIEW) states the
breaking change for existing history, who is affected, and the "set
`id:` to the old derived id" way to keep it.

## Non-goals

- **No history migration** and no re-keying of stored results (owner,
  option 1). No Alembic revision: `results/models.py` does not change.
- **No SQL parsing or dialect-aware normalisation** of `condition:` or
  `query:` (case, comments, `total<0`): whitespace only, as for `where:`.
- **`schema` stays as it is.** Two `schema` checks on one dataset in one
  file collide today (measured: `required_columns: [id]` and
  `forbidden_columns: [ssn]`, duplicate at `6:5`). Its options are
  refinements, not what is measured, and the owner's decision named only
  `failed_rows` and `sql_metric`; the fix there is one `schema` check
  holding both lists. A hint in the duplicate diagnostic for that case
  is folded into I-28 (loader wording), not this item.
- **`name:` does not feed the id** (measured: it does not today; a
  display name is not identity).
- The dataset's `filter:` does not feed the id (unchanged; it is per
  file, and the path already counts).
- No change to the duplicate diagnostic's text or position.
- No change to the frontend, its fixtures or its bundle.
- No change to explicit-id rules (`ID_PATTERN`, 64 characters).

## Design notes

- **Rule 5**: nothing here can raise from a check file. The new input is
  read only after the option has passed its own type check; a check
  whose `condition:`/`query:` is missing or not a string already errors
  before an id is derived.
- **Rule 6**: identity is computed at load, with no credentials; the SQL
  is hashed, never executed or connected for.
- **Rules 1–3** are untouched: no SQL is generated differently.
- **Check identity (CLAUDE.md)**: this *is* the breaking change CLAUDE.md
  warns about, approved by the owner on 2026-09-27 for these two metrics
  only, before the first release. Any change that would move another
  metric's id is out of scope and a blocking finding.
- **The seam.** Which options feed identity is a property of the metric,
  not of the loader. PLAN's proposal: a `Metric` class attribute, e.g.
  `identity_options: ClassVar[tuple[str, ...]] = ()`, set to
  `("condition",)` on `FailedRows` and `("query",)` on `SqlMetric`;
  the loader passes the normalised values to `derive_check_id`, which
  appends `\0{name}={value}` per option, in the declared order, only
  when the tuple is non-empty. This adds to the metric contract
  (`metrics/base.py`), so the architect reviews it in REFINE.

### Open questions for REFINE

- **Q1 (architect)** The seam and the encoding: `identity_options` on
  `Metric`, or a narrower mechanism? Is `\0{name}={normalised}` the right
  encoding, and does the new parameter to `derive_check_id` keep the
  byte-identical guarantee for every existing caller? Is a third-party
  metric (the registry is open) allowed to declare identity options, and
  should the docs for writing a metric say so?
- **Q2 (data-steward)** Is whitespace-only the right definition of a
  reformat, given `total<0` ≠ `total < 0` and `'a  b'` = `'a b'`? The
  alternative (lowercasing outside quotes, stripping comments) needs a
  SQL tokenizer per dialect, which PLAN rejects as a non-goal.
- **Q3 (data-steward)** The upgrade advice: is "set `id:` to the old
  derived id" something a steward can follow from the CHANGELOG alone,
  or does `tablewatch list` need to show the full 16 characters (it
  shows 12)? `list --output json` prints the full id today; confirm, or
  name the command.
- **Q4 (qa-engineer)** Anything else that derives or compares ids and
  could disagree with the loader after the change (the JSON and JUnit
  reporters, `selection.py`'s check-id selector, the API's
  `_is_check_id`)? PLAN found none that recompute it.

## Reviewers required

- **qa-engineer** (always): hunt for ids that move when they should not
  (M5 over every metric, `_defaults.yml` inheritance, `where:` on
  `sql_metric` rejected as today), aliasing between `where:` and
  `condition:`, anchors/aliases and `<<:` merge keys sharing a
  `condition:`, the S2 inputs, and a check selected by id with
  `run --check`.
- **data-steward** (always): Q2 and Q3 in REFINE; the check-language
  wording and the CHANGELOG note in VERIFY.
- **architect**: touches `src/` (`checks/model.py`, `config/loader.py`,
  `metrics/base.py`, `metrics/builtin/custom.py`) and adds to the metric
  contract, so in REFINE (Q1) and VERIFY.
- **security-reviewer: not required.** No trigger in PROCESS.md applies:
  the SQL is only hashed at load; what reaches SQL and how it runs are
  unchanged; no dependency, secret, network, file location or row data is
  involved. The tech lead may still ask.
- **ui-engineer: not involved** (no frontend change).

## Size

**S.** One attribute on two metrics, one parameter on
`derive_check_id`, the loader passing the values, a docs section, the
golden row and three pinned test ids, and tests (M5 first). Score 2.0
(reach 2, impact 1, confidence 1.0, effort 1).
