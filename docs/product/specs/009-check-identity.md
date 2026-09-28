# Spec 009: Two `failed_rows` checks on one table are two checks

| | |
| --- | --- |
| Backlog item | I-33 (data-steward, iteration 5 VERIFY; owner decision 2026-09-27; next by iteration 8 REVIEW) |
| Features | A (language hardening) |
| Phase | 2 (`0.2.0`); **gate: before the first PyPI release** |
| Size | S |
| Depends on | the owner's decision (option 1, 2026-09-27, ITERATIONS.md): change the id now, **no history migration** |
| Branch | `iter/009-check-identity` |
| Status | **ready** (REFINE settled 2026-09-28: data-steward answered Q2/Q3, architect approved Q1 with build constraints and answered Q4; planned in iteration 9 PLAN against `main` at `efa1a4e`). Every "today" id below was measured on `main` by loading the exact files with `tablewatch.load()` and the CLI; every "after" id was computed with the derivation in "The derivation", below |

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

REFINE kept this encoding (architect, Q1), so the "after" ids in this
spec stand as computed.

### What counts as a reformat (keeps the id)

| Edit to `condition:` / `query:` | Id |
| --- | --- |
| Spaces, tabs or newlines added, removed between words, or changed in number (`total  <  0` → `total < 0`) | kept |
| One line → a YAML block scalar, `|` or `>`, over several lines, with any indentation | kept |
| Quoting style in YAML: plain, `'…'`, `"…"` | kept (compared after parsing) |
| Leading or trailing whitespace, a final newline | kept |
| A YAML comment (`# why`) after the value or on its own line above the check | kept (YAML drops it before tablewatch sees the value) |
| A line break moved into or out of a `--` comment, nothing else changed | **kept — a known limit**, see below |
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

REFINE found a third (data-steward, measured): a line break is
whitespace, so tablewatch cannot tell code on the line after a `--`
comment from code inside it. These three `query:` values share one id
(`628ad6f24bdb05ed` after the change), though the second filters on
region and the others do not:

```text
select count(*) from orders\nwhere status = 'paid' -- and region = 'eu'
select count(*) from orders\nwhere status = 'paid' --\nand region = 'eu'
select count(*) from orders where status = 'paid' -- and region = 'eu'
```

### REFINE answer to Q2 (data-steward): whitespace-only is right

Keep whitespace-only, the same rule as `where:`. The deciding question is
which way a normalisation errs:

- **Too strict** (a harmless edit gets a new id): `total<0` →
  `total < 0`, `and` → `AND`, a comment edited. The cost is a history
  restart that the steward can see (the check page shows a check with no
  results) and can undo (`id:` set to the old id; the old results are
  still in the store). Loud and recoverable.
- **Too loose** (a change of meaning keeps the id): the history carries
  on across the change and the chart shows a step nobody can explain.
  Silent. This is the error a steward cannot catch.

Whitespace-only errs loose in exactly two corners: whitespace runs
inside a string literal (`'a  b'` = `'a b'`), and a line break moved
across a `--` comment (above). Both need an edit that is whitespace and
nothing else, which a reviewer sees as such in a diff, and in one file
both are reported as duplicates rather than merged. Lowercasing outside
quotes or stripping comments would open more loose corners, not fewer:
it needs to know every dialect's quoting (`"Region"` is case-sensitive on
Postgres and Snowflake, `'EU'` ≠ `'eu'` everywhere, `$$…$$`, `E'…'`,
`''` escapes), and a tokenizer that gets one wrong merges two different
checks silently.

What a real SQL formatter does to a pasted-back condition (measured
against the ids in M4): re-indenting and re-wrapping keep the id;
spacing operators (`total<0` → `total < 0`) and changing keyword case
start a new history. That is the price, and it is stated in the docs
(M12), with the way to avoid it: explain a check in a YAML `# comment`
or its `name:`, not in a `--` comment, and pin `id:` on a check whose
history matters before reformatting its SQL.

A `--` comment has a second reason to stay out of `condition:`: the
condition is folded into the dataset's scan, so a comment there
comments out the rest of the statement. Measured on `main`:
`condition: total < 0 -- negatives` gives `ERROR … Parser Error: syntax
error at or near "FROM"` (exit 2). `sql_metric` runs its `query:` as
written, so comments there run fine.

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

### REFINE answer to Q3 (data-steward): followable, if the CHANGELOG says four things

Walked through on a copy of `examples/retail` with recorded history, on
`main`:

1. **Before upgrading**, `tablewatch list --output json` prints the full
   id: `"id": "ed669ca6e5532a59"` for "No negative amounts". Confirmed.
2. Adding `id: ed669ca6e5532a59` to that check and running again:
   `tablewatch history ed669ca6e5532a59` shows the new result on top of
   every earlier one. **The advice works** with the 16 characters.
3. **The trap:** `tablewatch list` (table) shows `ed669ca6e553`, 12
   characters. Pinning `id: ed669ca6e553` is valid, loads, and silently
   starts a **new** history, because `id:` is exact and the store keys on
   the full string. `list` then looks identical either way (it shows the
   first 12 of the pinned id too), so the steward cannot see the mistake.
   Worse, `tablewatch history ed669ca6e553` then prints
   `tablewatch: ed669ca6e553 is ambiguous: ed669ca6e553, ed669ca6e553`
   (exit 3): both matches are clipped to the same 12 characters.
4. **After upgrading without step 1**, `list` shows only new ids and no
   CLI command lists old ones (`history` needs the id; `runs` shows
   12-character run ids and `/api/v1/runs/{id}` needs all 32). The old
   id is in the results store; this query found it (SQLite store,
   measured; plain SQL, so it works on any store database):

   ```sql
   SELECT check_id, check_name, source, MAX(r.started_at) AS last_run
   FROM tablewatch_check_results c
   JOIN tablewatch_runs r ON r.id = c.run_id
   WHERE c.metric IN ('failed_rows', 'sql_metric')
   GROUP BY check_id, check_name, source;
   ```

   It can return several ids for one check (retail's store also held
   `8ce8903ab36db2f2`, from before an earlier file move); the old id is
   the one whose `last_run` is the last run before the upgrade.

So `list` does **not** need to change for this iteration: the CHANGELOG
(S3, now must M13) names `list --output json`, says "before upgrading",
says **all 16 characters, not the 12 that `tablewatch list` shows**, and
gives the query above for anyone who already upgraded.

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
`query: select 1` and `query: "select   1\n"` (both `d7f3dc68d33c50ea`
after the change; today both `b68ef2d84375cb8e`).

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

```yaml
  # negatives are refunds booked wrong
  - failed_rows:
      condition: total < 0   # a YAML comment, not SQL
```

When loaded, then the id is `a37eb03d163d2dac` every time. And each of
these gives its own id, **not** `a37eb03d163d2dac` (measured with the
derivation above):

| `condition:` | Id |
| --- | --- |
| `total<0` | `30d25ee6881e8d1e` |
| `TOTAL < 0` | `f2dc97d574a56230` |
| `total < 0 -- negatives` | `09d14440d6efefd5` |
| `(total < 0)` | `14379d71ac3ad19f` |

(Ids only: `total < 0 -- negatives` loads but errors when run, see Q2.) The same table of edits applied
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
`failed_rows` whose `where:` is `A` and `condition:` is `B`
(`8d2b6f562501a9b6`) has a different id from one whose `where:` is `B`
and `condition:` is `A` (`31ab427637456300`); all four in one file load
with no diagnostic.

**M11 (must) The file path and dataset still count.** M1's first check
moved to `checks/finance/orders.yml` gets `e837f5e50ffe3193`; the same
check under `dataset: orders_v2` gets `0d3aa10538bdfd35`.

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
- two checks that would get the same id are an error; give one an `id:`;
- to explain a check, use a YAML `# comment` or `name:`, which never
  touch the id; a `--` comment inside `condition:` breaks the scan, and
  one inside `query:` is part of the id;
- before reformatting the SQL of a check whose history matters, pin its
  current id with `id:` (all 16 characters, from
  `tablewatch list --output json`).

The `derive_check_id` docstring says the same. `tests/test_docs.py`
still passes.

### Should

**S1 (should) The `sql_metric` label is not needed to tell queries
apart.** `docs/check-language.md`'s `sql_metric` row stops implying the
label is how to distinguish two queries (it does not today, but check
the wording).

**S2 (should) Hostile input.** A `condition:` or `query:` holding a NUL
(`"total < 0\0x"` in a double-quoted YAML string), a very long query
(100 KB), or only whitespace: the loader never raises. Measured on
`main`: `condition: "   \n  "` gives `checks/orders.yml:5:18: error:
\`condition:\` must be a string` and `query: "  \t "` gives
`…:7:14: error: \`query:\` must be a string`, at the value, and no id;
these stay exactly as they are. The NUL condition loads, with id
`d5df30c18e8ecb1f` after the change.

**S3 (should) The known loose corners are pinned by tests**, so they
are decided, not accidental: `status = 'a  b'` and `status = 'a b'` give
one id (`dfae2ed81ea02750`), and the three `--` queries in "What counts
as a reformat" give one id (`628ad6f24bdb05ed`).

**M13 (must, was S3) The CHANGELOG lets a steward keep history without
reading the spec.** The entry (written in REVIEW, checked by the
data-steward in VERIFY) says:

- who is affected: `failed_rows` and `sql_metric` checks with no `id:`;
  their history starts again on the first run after upgrading, and the
  old results stay readable under the old id;
- **before upgrading**, run `tablewatch list --output json` and note the
  `id` of each such check; after upgrading, add `id: <that id>` to the
  check;
- **all 16 characters**, not the 12 `tablewatch list` shows: a 12-character
  id is accepted but starts a new history;
- already upgraded: the query in "REFINE answer to Q3", which lists old
  ids from the results store.

Acceptance, on a copy of retail with recorded history (measured on
`main`, the steps are the same after the change): with `id:
ed669ca6e5532a59` added to "No negative amounts" and one more run,
`tablewatch history ed669ca6e5532a59` lists that run above every earlier
result for the check.

### Not added (REFINE, data-steward; backlog frozen by the owner)

Found while answering Q3, outside this item, recorded for the owner and
not proposed as backlog items:

- `tablewatch history` clips ids to 12 characters in its "ambiguous"
  message, so two ids that share 12 characters print as
  `ed669ca6e553 is ambiguous: ed669ca6e553, ed669ca6e553` and the
  steward cannot pick one. Anyone who pins a 12-character id by mistake
  meets it (M13 warns against that).
- `list` shows 12 characters and no way to see the full id except
  `--output json`; the CLI has no command that lists ids present only in
  the results store.
- A `--` comment in `condition:` errors the check (pre-existing; M12
  only documents it).
- (Architect) When ROADMAP H1 (plugin SDK) opens the metric registry,
  decide whether third-party metrics may declare `identity_options` and
  document it then.

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
  not of the loader. PLAN proposed a `Metric` class attribute; the
  architect approved it in REFINE, with the build constraints below.

### Build constraints (REFINE, architect: approved with these)

1. **Seam.** `identity_options: ClassVar[tuple[str, ...]] = ()` on
   `Metric` (`metrics/base.py`); `("condition",)` on `FailedRows`,
   `("query",)` on `SqlMetric`. A comment on the ClassVar says: the names
   and their order feed the check id; changing them is a breaking change
   for every user's history.
2. **Encoding** exactly as in "The derivation":
   `{path}\0{dataset}\0{canonical}\0{scope}`, then `\0{name}={normalised}`
   per identity option, in declared order. The NUL ambiguity (a `where:`
   or `condition:` holding a NUL) is accepted: at worst it surfaces as a
   loud duplicate diagnostic, never a silent merge.
3. **Normalisation lives inside `derive_check_id`**, in one private
   helper shared with the `where:` scope normalisation
   (`checks/model.py`, around line 164). The loader passes raw strings;
   there is exactly one whitespace rule in the codebase.
4. **Signature.** `derive_check_id` gains a keyword-only
   `identity: Sequence[tuple[str, str]] = ()`. Existing callers pass
   nothing and get a byte-identical digest input.
5. **Loader** builds the pairs from the parsed options dict (after
   `plain()`, after validation), in `identity_options` order, skipping
   absent keys. A missing or non-string option has already produced its
   diagnostic (rule 5); no id is derived for it.
6. **The four guard tests**, all required:
   - M5's pinned ids, written and green on `main` first;
   - a unit test that `derive_check_id(p, d, c, w)` with no identity
     equals `sha1(f"{p}\0{d}\0{c}\0{scope}")[:16]`;
   - a test over `all_metrics()` that every registered metric other than
     `failed_rows` and `sql_metric` has `identity_options == ()`, and that
     every declared entry is a key of the metric's `options` with kind
     `OptionType.STRING`;
   - the one-line golden diff (M6).
7. **Not a public contract.** The metric registry stays internal until
   Phase 5. `identity_options` is kept out of user docs
   (`docs/check-language.md` describes the behaviour, M12, not the
   attribute). The architect's note for ROADMAP H1 (plugin SDK) — decide
   there whether third-party metrics may declare identity options — is
   recorded here, not added to the backlog (frozen).

### Open questions for REFINE

- **Q1 (architect)** *Answered in REFINE: `identity_options` on
  `Metric`, encoding unchanged, keyword-only parameter keeps existing
  input byte-identical; not a public contract. See "Build constraints".*
  The seam and the encoding: `identity_options` on
  `Metric`, or a narrower mechanism? Is `\0{name}={normalised}` the right
  encoding, and does the new parameter to `derive_check_id` keep the
  byte-identical guarantee for every existing caller? Is a third-party
  metric (the registry is open) allowed to declare identity options, and
  should the docs for writing a metric say so?
- **Q2 (data-steward)** *Answered in REFINE: yes, see "REFINE answer to Q2".* Is whitespace-only the right definition of a
  reformat, given `total<0` ≠ `total < 0` and `'a  b'` = `'a b'`? The
  alternative (lowercasing outside quotes, stripping comments) needs a
  SQL tokenizer per dialect, which PLAN rejects as a non-goal.
- **Q3 (data-steward)** *Answered in REFINE: yes, with M13's CHANGELOG wording; `list` unchanged. See "REFINE answer to Q3".* The upgrade advice: is "set `id:` to the old
  derived id" something a steward can follow from the CHANGELOG alone,
  or does `tablewatch list` need to show the full 16 characters (it
  shows 12)? `list --output json` prints the full id today; confirm, or
  name the command.
- **Q4 (qa-engineer)** Anything else that derives or compares ids and
  could disagree with the loader after the change (the JSON and JUnit
  reporters, `selection.py`'s check-id selector, the API's
  `_is_check_id`)? PLAN found none that recompute it.
  *Answered in REFINE (architect): none re-derives an id.
  `selection.py` prefix-matches loaded ids; the store prefix-matches
  stored ids; the server's `_is_check_id` checks shape, then looks up
  loaded ids; an old id's history stays readable; compiled wiring uses
  loaded ids; the JSON and JUnit reporters print `check.id`;
  `results/state.py` keys on the stored id; the frontend treats ids as
  opaque; `_defaults.yml` cannot supply `condition:` or `query:`. The
  qa-engineer still probes these in VERIFY (Reviewers required).*

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
golden row and three pinned test ids, and tests (M5 first, then the
other guard tests in "Build constraints"). Still S after REFINE. Score 2.0
(reach 2, impact 1, confidence 1.0, effort 1).
