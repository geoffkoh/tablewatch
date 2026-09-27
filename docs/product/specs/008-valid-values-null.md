# Spec 008: A null in a value list is never a silent pass

| | |
| --- | --- |
| Backlog item | I-34 (qa-engineer, iteration 5 VERIFY; next by iteration 7 REVIEW) |
| Features | A (language hardening) |
| Phase | 2 (`0.2.0`) |
| Size | S |
| Depends on | nothing. The code involved shipped in Phase 1 |
| Branch | `iter/008-valid-values-null` |
| Status | **ready once REFINE picks an option** (iteration 8 PLAN, 2026-09-28, against `main` at `faa1eee`). Every "today" value below was measured on `main` on DuckDB **and** SQLite |

## Problem and persona

**Dana, data engineer.** "I listed the allowed order statuses and put
`null` in because a status can be blank until the order is picked. The
check has passed every night for a month. Yesterday finance found 300
orders with status `shiped`." Her check was:

```yaml
- invalid_count(status) = 0:
    valid_values: [pending, shipped, null]
```

tablewatch compiles that to `status NOT IN ('pending', 'shipped', NULL)`.
In SQL, `'shiped' NOT IN (…, NULL)` is not true but NULL, so the row is
never counted. **The check cannot fail, whatever the data holds.** It is
the worst defect a data quality tool can have: a green light that
checks nothing.

**Sam, data steward.** "Our CSV loads write the text `NULL` for an empty
field, so I added it to `missing_values`." He wrote `- NULL` unquoted. In
YAML that is a null, not the text `NULL`, so the rows holding the text are
not counted as missing, and on any `invalid_*` check that shares the list
nothing is counted at all.

**How they cope today.** They don't know to. Nothing warns: `validate`
exits 0 with "no problems found", `run` prints a green PASS with value
`0`, and the only hint is a SQLAlchemy `SAWarning` on stderr ("rendering
literal NULL in a SQL expression") that names no file and no check.

### Where a null in a list reaches SQL (all of it)

Found by reading every option of type `list` and running each on
`main` (DuckDB and SQLite give the same numbers):

| Option | Used by | Code | What a null does today |
| --- | --- | --- | --- |
| `valid_values` | `invalid_count`, `invalid_percent` | `validity.valid_predicate`: `col.in_([literal(v) …])` | `NOT IN (…, NULL)` is never true: **every value outside the list goes uncounted**. With another `valid_*` rule on the same check the count is wrong in a data-dependent way (measured: 3 where 4 is right) |
| `missing_values` on `invalid_*` | `invalid_count`, `invalid_percent` | `completeness.missing_predicate`, negated as "present" | `NOT (col IS NULL OR col IN (…, NULL))` is NULL for every value not in the list, so **no row is "present" and nothing is ever invalid** |
| `missing_values` on `missing_*` | `missing_count`, `missing_percent` | `completeness.missing_predicate` | Harmless by luck: the `IS NULL` branch already counts NULLs, and `OR NULL` does not remove a true. The number is right today |

Checked and **not** affected: `required_columns` and `forbidden_columns`
(`list of strings`: a null is already a load error), `column_types`
(a mapping of strings), the DSL's comparison values (numbers, durations
and percentages only), and the SQL users write themselves in `filter:`,
`where:`, `condition:` and `query:` (it runs as written; a `NOT IN (NULL)`
there is the author's SQL, not ours).

Found on the way, same validator (`_matches` accepts any list item): a
list or mapping **inside** a value list (`valid_values: [pending,
[shipped, lost]]`) passes `validate` (exit 0) and then errors the check
on every run (exit 2) with a message that quotes a row value:
`Conversion Error: Type VARCHAR with value 'pending' can't be cast to
the destination type VARCHAR[]`. Loud rather than silent, so a `should`
here (N8).

YAML spells null five ways, all of which reach the list as `None`:
`null`, `Null`, `NULL`, `~`, and an empty block item (`-` with nothing
after it). Quoted `'null'` and `'NULL'` are text and must stay text.

### What others do

- **dbt** `accepted_values` compiles to `not in (…)` and has the same
  NULL trap; the common advice is to add a `where:` or to list `null`
  knowingly ([ADHDecode on accepted_values](https://adhdecode.com/debugging/dbt/dbt-test-failed-accepted-values-unexpected/),
  [Elementary test hub](https://www.elementary-data.com/dbt-tests/accepted-values)).
  dbt also once compiled an empty string in the list as `'None'`
  ([dbt-core #2587](https://github.com/fishtown-analytics/dbt/issues/2587)).
- **Great Expectations**: `expect_column_values_to_be_in_set` with
  `None` in the set gives opposite verdicts on pandas and SQL engines; the
  proposed fix reads `None` in the set as "null is allowed"
  ([GX #12273](https://github.com/fivetran/great_expectations/issues/12273),
  [GX #412](https://github.com/great-expectations/great_expectations/issues/412)).
- **Soda** counts NULL as missing by default, and splits every value into
  missing, invalid or valid, so NULL is never invalid
  ([Soda: missing metrics](https://docs.soda.io/sodacl-reference/missing-metrics),
  [Soda: validity metrics](https://docs.soda.io/soda-documentation/soda-v3/sodacl-reference/validity-metrics)).

tablewatch already has Soda's partition (`docs/check-language.md`: "A
value that is missing is never also counted as invalid"). So a null in
either list never changes what the user meant: NULL is missing, never
invalid. The only question is how loudly to tell them.

## Outcome

After this ships, a null in `valid_values` or `missing_values` can never
make a check pass that should fail, on any database: the SQL never
contains `NULL` inside an `IN (…)` list, and the user is told, at the
null's own `file:line:col`, that the item does nothing and why. Dana's
check fails with value 2 on the fixture below; Sam learns that `NULL`
needs quotes to mean the text.

## The options (data-steward decides in REFINE)

All three share the SQL fix (M2): nulls never reach an `IN` list, in one
helper both predicates use, so the engine is safe whatever the loader
does (and whatever later feeds options without YAML, such as A9's
in-pipeline API). They differ in what the loader says.

| | A. Error | B. Drop with a warning (**PM recommends**) | C. Drop silently ("null is allowed") |
| --- | --- | --- | --- |
| Loader | `error` at the null | `warning` at the null; the item is dropped | nothing; the item is dropped |
| `validate` on a file with a null | **exit 3** (today 0) | exit 0; the warning on stderr | exit 0 |
| `run` | **exit 3, nothing in the project runs** | runs; the check gets its true value; warning on stderr | runs; true value |
| A check that is correct today (`missing_count` with `missing_values: ['', null]`, N3) | **breaks**: the whole project stops until edited | unchanged number, one warning | unchanged |
| Checks that silently passed (N1, N2, N5) | stop until edited, then show the true value | show the true value next run (a pass may become a fail, exit 0 → 1) | same as B |
| Can a user find which past passes were not real? | yes (every error) | yes: `tablewatch validate` lists every one | **no** |
| Catches Sam's unquoted `NULL` meaning text | yes | yes (the message says to quote it) | no |

What every option does to **recorded numbers**: options do not feed the
check id (`docs/check-language.md`, "Refining options such as
`valid_values` keeps the id"), so history continues under the same id and
jumps from the false `0` to the true count at the first run after the
upgrade; "failing since" starts there. Nothing recorded is rewritten or
annotated (non-goal). Under A there is also a gap until the file is
edited. The CHANGELOG says so under **Fixed**, and tells users to run
`tablewatch validate` after upgrading to find every affected check.

A list with **only** nulls (`valid_values: [null]`, N4) is an `error` in
every option, the PM proposes: after dropping the null there is no rule
left, and read literally ("only NULL is valid") it would call every
present value invalid, which nobody means. No project loses a working
check: that check silently passes today.

**Why B.** It fixes every number, keeps every correct check running, and
makes the fake passes discoverable, without turning a project that runs
today into one where nothing runs. A is the strictest, but it stops a
whole project over an item that, once the SQL is fixed, is harmless, and
it breaks N3, which is correct today. C fixes the numbers but hides the
lesson and Sam's quoting mistake.

**Does this need the owner?** No, for any option. The exit-code contract
is unchanged: 3 already means "the project is invalid, nothing ran", and
a new diagnostic is how rule 5 grows (I-28 and I-36 add more).
tablewatch is not on PyPI, so no outside project is affected. Under A,
though, projects that load today would exit 3; if REFINE picks A, the
iteration log says so plainly for the owner to read after the fact.

## Acceptance scenarios

Every scenario runs on DuckDB **and** SQLite (rule 3). "Today" values
were measured on `main` at `faa1eee`.

### Fixture

Table `orders`, column `status` (text):

| id | status |
| --- | --- |
| 1 | `pending` |
| 2 | `shipped` |
| 3 | `shiped` |
| 4 | NULL |
| 5 | `''` (empty text) |
| 6 | `NULL` (the four-letter text, as a CSV load writes it) |

`tablewatch.yml`:

```yaml
name: nulls
datasources:
  lake:
    type: duckdb
    path: lake.duckdb
  lite:
    type: sqlite
    path: lite.db
```

Each scenario's check file is `checks/orders.yml` with the lines shown
(line numbers are part of the expected output); the SQLite twin differs
only in `datasource: lite`. Diagnostic columns were read from ruamel's
own marks on these exact files.

### Must: the fix, in every option

**M1 (must) The list without null is unchanged.**
Given

```yaml
datasource: lake
dataset: orders
checks:
  - invalid_count(status) = 0:
      valid_values: [pending, shipped]
      missing_values: ['']
```

When `tablewatch run`, then the check fails with value `2` (`shiped`
and the text `NULL`), exit 1. `compile` prints exactly the SQL it prints
today. (Guards against the fix changing lists that have no null.)

**M2 (must) No null reaches an `IN` list, and nothing warns from
SQLAlchemy.** Given a `MetricContext` whose options hold `None` in
`valid_values` or `missing_values` (built directly, bypassing the
loader), when `valid_predicate` and `missing_predicate` are compiled with
`literal_binds` on both dialects, then no `IN (…)` list in the SQL
contains `NULL`, and no `SAWarning` is raised (pytest's
`filterwarnings = error` would catch one). Items are still wrapped in
`literal()` (rule 4).

**M3 (must) Quoted `'null'` and `'NULL'` are text.**
Given

```yaml
datasource: lake
dataset: orders
checks:
  - invalid_count(status) = 0:
      valid_values: [pending, shipped, 'NULL']
      missing_values: ['']
```

then no diagnostic, and the check fails with value `1` (`shiped` only),
as today. And `missing_count(status) = 0` with `missing_values: ['',
'NULL']` fails with value `3` (rows 4, 5, 6), as today.

**M4 (must) Every spelling of null is treated the same.** N1 below,
repeated with `Null`, `NULL` and `~` in place of `null`, gives the same
outcome, value and diagnostic (same line and column), and N5 covers the
empty block item.

### Must: a null in the list (outcome depends on the option)

REFINE keeps one of the three expected-result columns and deletes the
others. Messages are proposals; REFINE settles the wording. Under B, each
file's other checks run as normal; under A, nothing in the project runs.

**N1 (must) Dana's check: null in `valid_values`.**

```yaml
datasource: lake
dataset: orders
checks:
  - invalid_count(status) = 0:
      valid_values: [pending, shipped, null]
      missing_values: ['']
```

| | Today | A | B | C |
| --- | --- | --- | --- | --- |
| `validate` | exit 0, "no problems found" | exit 3; `checks/orders.yml:5:40: error: …` | exit 0; `checks/orders.yml:5:40: warning: …` on stderr | exit 0 |
| `run` | **PASS, value 0**, exit 0; `SAWarning` on stderr | exit 3, nothing ran | **FAIL, value 2**, exit 1; the warning on stderr | FAIL, value 2, exit 1 |
| `compile` | `status NOT IN ('pending', 'shipped', NULL)` | exit 3 | `status NOT IN ('pending', 'shipped')` | as B |

Proposed message (B): `` `valid_values:` item 3 is null, which does
nothing: NULL is always missing, never invalid (count it with
missing_count). It is ignored. To match the text 'NULL', quote it ``.
(A: the same, ending "remove it" instead of "It is ignored".)

**N2 (must) Null in `missing_values` on an `invalid_*` check.**

```yaml
datasource: lake
dataset: orders
checks:
  - invalid_count(status) = 0:
      valid_values: [pending, shipped]
      missing_values: ['', ~]
```

| | Today | A | B | C |
| --- | --- | --- | --- | --- |
| `validate` | exit 0 | exit 3; error at `6:28` | exit 0; warning at `6:28` | exit 0 |
| `run` | **PASS, value 0**, exit 0 | exit 3 | **FAIL, value 2**, exit 1 | FAIL, value 2, exit 1 |

Proposed message (B): `` `missing_values:` item 2 is null, which does
nothing: NULL is always missing. It is ignored. To match the text 'NULL',
quote it ``.

**N3 (must) Sam's unquoted `NULL` on a `missing_*` check, correct today.**

```yaml
datasource: lake
dataset: orders
checks:
  - missing_count(status) = 0:
      missing_values:
        - ''
        - NULL
```

| | Today | A | B | C |
| --- | --- | --- | --- | --- |
| `validate` | exit 0 | **exit 3**; error at `7:11` | exit 0; warning at `7:11` | exit 0 |
| `run` | FAIL, value 2 (rows 4, 5; the text `NULL` in row 6 is not counted, because Sam's `NULL` is a null), exit 1 | exit 3 | FAIL, value 2, exit 1, as today; the warning tells Sam to quote it | as today, no hint |

**N4 (must) A list of only nulls is an error in every option.**

```yaml
datasource: lake
dataset: orders
checks:
  - invalid_count(status) = 0:
      valid_values: [null]
```

Today: PASS, value 0, exit 0. After: `validate` exits 3 with
`checks/orders.yml:5:22: error: `valid_values:` has no values: null is
not a value (NULL is always missing, never invalid)`; `run` exits 3. The
same for `missing_values: [~]` on any metric that takes it.

**N5 (must) An empty block item is a null.**

```yaml
datasource: lake
dataset: orders
checks:
  - invalid_count(status) = 0:
      valid_values:
        - pending
        -
        - shipped
      missing_values: ['']
```

Today: PASS, value 0. After: as N1 in the chosen option, with the
diagnostic at `7:10` (where ruamel places an empty item: just after the
dash; the tech lead may choose the dash itself, `7:9`, and says which in
the test).

**N6 (must) Two nulls, two diagnostics, one pass.** `valid_values:
[null, pending, ~, shipped]` gives two diagnostics (items 1 and 3, each
at its own column) from one `validate` (rule 5: all problems in one
pass), and under B/C the value 2.

**N7 (must) The Python API agrees with the CLI.** `tw.load()` on N1
returns the diagnostic (with its severity, file, line and column) in
`project.diagnostics`; `tw.run()` gives the same value and outcome as the
CLI in the chosen option.

### Should

**N8 (should) A list or mapping inside a value list is a load error.**

```yaml
datasource: lake
dataset: orders
checks:
  - invalid_count(status) = 0:
      valid_values: [pending, [shipped, lost]]
```

Today: `validate` exit 0; `run` exits 2 with `Conversion Error: Type
VARCHAR with value 'pending' can't be cast …` (a row value in an error
message; see I-30). After: `validate` exits 3 with
`checks/orders.yml:5:31: error: `valid_values:` items must be single
values (text, a number, true/false); item 2 is a list`; the same for a
mapping (`{shipped: 1}`: "is a mapping"). No project loses a working
check: this one errors on every run today.

**N9 (should) The editor schema says the same.** The JSON schema
generated for `list` options (`config/jsonschema.py`) no longer accepts
null, list or mapping items, so VS Code underlines N1, N4 and N8 as the
user types. (Under B the editor's mark is stronger than the loader's
warning; acceptable, as the item does nothing.)

**N10 (should) Docs.** `docs/check-language.md`'s options table says,
for `valid_values` and `missing_values`: NULL is always missing and never
invalid, so never list it; quote `'NULL'` to match the text. The
CHANGELOG entry (PM, in REVIEW) says a check that passed may now fail
because it was never checking, and to run `tablewatch validate` after
upgrading.

## Non-goals

- **Rewriting or annotating past results.** History keeps its false
  zeros; the CHANGELOG explains the jump.
- **A way to count NULL as invalid.** `missing_count(status) = 0` already
  says "no NULLs"; the missing/invalid partition does not change.
- **The SQL users write** in `filter:`, `where:`, `condition:`, `query:`.
  It runs as written.
- **Other YAML typing surprises in lists**: unquoted dates
  (`2024-01-01`), `true`/`false`, numbers against a text column. They
  reach SQL as typed values and are covered by existing QA tests
  (`tests/test_check_sql_qa.py`); a separate item if they turn out to
  mislead.
- **Changing check identity.** Options stay out of the id.
- Percent-as-fraction warnings (I-28), row values in error messages
  (I-30).

## Design notes

- **Rule 4.** Items that reach SQL stay `literal(value)`; the fix drops
  `None` before wrapping, never binds a bare value.
- **Rule 5.** Each diagnostic sits at the null item's own
  `file:line:col` (`YAMLSource.of_item`, from ruamel's `lc.item`), and
  one load reports every null in every list. Never raise.
- **Rule 3.** Same SQL shape on both dialects; tests on DuckDB and SQLite.
- **Rule 7 / exit codes.** Unchanged contract. Options A and N4/N8 add
  new exit-3 cases for files that would otherwise load; none of them
  (N4, N8) is a check that works today.
- **Check identity** is untouched: options do not feed
  `derive_check_id`; `tests/golden/retail-list.txt` stays as it is.

**Open questions for the tech lead / architect:**

1. Where does the one IN-list helper live: on `MetricContext` (rule 3's
   place for normalisation, e.g. `ctx.in_values(col, values)`) or as a
   function beside the predicates? It must be the only way a list option
   reaches `in_()`, so a future list option cannot regress.
2. `_option_ok` returns one bool per option; per-item diagnostics need a
   per-item pass for `list` options. Does the dropped-null list (B/C)
   reach `Check.options` already cleaned, so the metric never sees a
   `None` from YAML, with the helper as a backstop only?
3. Does `list` stay one `OptionType`, or does it gain an item type
   ("list of values") so that N8 and N9 come from the same definition?

## Reviewers required

- **qa-engineer** (always): hunt for other ways a null or non-scalar
  reaches SQL; anchors, merge keys, `_defaults.yml`.
- **data-steward** (always): chooses A, B or C in REFINE; wording.
- **architect** (touches `src/`: metrics, loader, possibly
  `MetricContext` and `OptionType`).
- **security-reviewer**: the change alters **what can reach SQL** (a
  trigger in PROCESS.md). Expected to be light.

## Size

**S.** Two predicates, one helper, a per-item check in the loader, the
schema line, a docs row, and tests on two backends.
