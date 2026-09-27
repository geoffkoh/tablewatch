# Spec 008: A null in a value list is never a silent pass

| | |
| --- | --- |
| Backlog item | I-34 (qa-engineer, iteration 5 VERIFY; next by iteration 7 REVIEW) |
| Features | A (language hardening) |
| Phase | 2 (`0.2.0`) |
| Size | S |
| Depends on | nothing. The code involved shipped in Phase 1 |
| Branch | `iter/008-valid-values-null` |
| Status | **ready** (iteration 8 PLAN, 2026-09-28, against `main` at `faa1eee`; REFINE the same day: data-steward chose **option B**; architect and security-reviewer approved with follow-ups, all folded in below, see "Design (settled in REFINE)"). Every "today" value and every diagnostic position below was measured on `main` on DuckDB **and** SQLite, by running the CLI and reading ruamel's marks on the exact files |

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
the destination type VARCHAR[]`. Loud rather than silent, but the
security-reviewer flagged that message as a data-exposure path (a row
value lands in the stored and served error), so REFINE made it a
**must** (N8).

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

## The options (REFINE chose B)

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

A list with **only** nulls behaves differently in the two options,
because the two options mean different things (REFINE measured both):

- `valid_values: [null]` (or `[null, ~]`) is an **error** (N4). After the
  null is dropped there is no allowed value left, and read literally
  ("only NULL is valid") it would call every present value invalid,
  which nobody means. No project loses a working check: that check
  silently passes today (measured: PASS, value 0).
- `missing_values: [~]` is a **warning** per item and the option is
  dropped (N4). "Only NULL is missing" is exactly what no
  `missing_values` means, so the check keeps its number. Making it an
  error would break a check that is right today: `missing_count(status)
  = 0` with `missing_values: [~]` gives FAIL, value 1 on the fixture,
  which is correct.

### REFINE decision: B, drop with a warning

Chosen by the data-steward, tested against four real situations on the
fixture (all measured on `main`, both backends):

| Situation | Today | Under B |
| --- | --- | --- |
| Sam's CSV load writes the text `NULL`; he adds `- NULL` unquoted to `missing_values` on a `missing_count` (N3) | FAIL, value 2: right for NULL and `''`, but the text `NULL` row is not counted, and nothing says why | FAIL, value 2, unchanged; a warning at `7:11` tells him to quote it. Quoted, the value is 3 (M3) |
| A dbt `accepted_values` list migrated with `- null` in it (it means "null is allowed") | PASS, value 0, whatever the data | FAIL, value 2. Dropping the null *is* what the author meant (NULL is never invalid); the warning says why the item is not needed |
| A `valid_values` list built by copy-paste, with an empty `-` left behind (N5) | PASS, value 0 | FAIL, value 2; a warning at the dash says the item is empty. It may be where a value was meant to go, so the message says to fill it in or delete it |
| One check with a null in **both** lists (N6) | PASS, value 0 | FAIL, value 2; two warnings, one per null, from one load |

Why B, from each persona's side:

- **Dana** needs the nightly run to show the real failure, `shiped`,
  the next night. B does that: her check goes from PASS to FAIL (exit
  0 to 1), which is the correct signal to her orchestrator. Under **A**
  her scheduled run exits 3 and *nothing in the project runs*: every
  unrelated dataset goes dark over an item that, once the SQL is fixed,
  is harmless. A data quality blackout is worse than the defect it
  reports. A also breaks N3, which is right today.
- **Sam** will never read SQL, so the lesson has to come in words at
  the line. Under **C** his `- NULL` stays silently a null, the text
  `NULL` rows are never counted as missing, and nothing ever tells him.
  B tells him at `file:line:col` and tells him the fix (quote it).
- **Ravi's question**, "which past passes were not real?", has an answer
  under B: `tablewatch validate` after upgrading lists every affected
  check. Under C it has none.

A warning is not ignored by B's design, it is the point of B, so
`validate`'s closing line must not contradict it: today it prints
"no problems found" after a warning (measured with an empty `checks:`).
N11 fixes that line.

**Does this need the owner?** No. The exit-code contract is unchanged:
no file that loads today starts failing to load, except the two cases
that never worked (N4 `valid_values` of only nulls, which silently
passes, and N8, which errors every run). tablewatch is not on PyPI, so
no outside project is affected.

### What changes for projects that load today (option B)

- **`validate`**: still exits 0 for every file that loads today, except
  `valid_values` holding only nulls (N4) and a list or mapping inside a
  value list (N8), which now exit 3. Every null item now prints a
  warning at its `file:line:col` on stderr, and the closing line counts
  the warnings (N11).
- **`run`**: the same warnings on stderr, then every check runs. A check
  with a null in `valid_values`, or in `missing_values` on an
  `invalid_*` check, gets its true value for the first time: a PASS
  may become a FAIL, and the run's exit code may go from 0 to 1.
  `missing_*` checks keep their numbers exactly. The SQLAlchemy
  `SAWarning` on stderr is gone.
- **History**: the check id does not change (options do not feed it),
  so the check's history continues and jumps from the false `0` to the
  true count at the first run after upgrading; "failing since" starts
  there. Past results are not rewritten or annotated (non-goal). The
  CHANGELOG says so under **Fixed** and tells users to run `tablewatch
  validate` after upgrading.

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
outcome, value, message and position (`5:40`). The empty block item has
its own message and position (N5).

### Must: a null in the list (option B)

Every null item is a `warning` and is dropped before the check is built;
the file's other checks, and the project, run as normal. Messages are
settled; the tech lead may change punctuation, not meaning. Only the
first line is a contract for tests (`file:line:col: warning:` and the
option name and item number); message text is not a contract with users.

Messages, by where the null sits and how it was written:

- written null (`null`, `Null`, `NULL`, `~`) in `valid_values`:
  `` `valid_values:` item 3 is null and is ignored: NULL is always
  missing, never invalid (check it with missing_count). To match the
  text 'NULL', quote it ``
- written null in `missing_values`:
  `` `missing_values:` item 2 is null and is ignored: NULL always counts
  as missing already. To match the text 'NULL', quote it ``
- empty block item (`-` with nothing after it, N5), in either list:
  `` `valid_values:` item 2 is empty and is ignored: a `-` with nothing
  after it is null in YAML. Fill in the value you meant, or delete the
  line ``

"Item n" counts from 1, in the order written, so Sam can count the
dashes.

**Messages name an item by position and kind, never by its content**
(security): no diagnostic, warning or error ever prints `repr(item)` or
the item's value. The loader words its part generically, from the
`OptionType` and the position ("item 3 is null and is ignored"); the
option-specific hint (for example "check it with missing_count") lives
with the option's definition in its metric module, not in a branch on
the option name in the loader. The option's key in the text comes from
the YAML key, as it does for every option diagnostic today.

**N1 (must) Dana's check: null in `valid_values`.**

```yaml
datasource: lake
dataset: orders
checks:
  - invalid_count(status) = 0:
      valid_values: [pending, shipped, null]
      missing_values: ['']
```

| | Today (measured) | After |
| --- | --- | --- |
| `validate` | exit 0, "no problems found" | exit 0; stderr `` checks/orders.yml:5:40: warning: `valid_values:` item 3 is null and is ignored: … ``; closing line `1 datasets, 1 checks — no errors, 1 warning` (N11) |
| `run` | **PASS, value 0**, exit 0; one `SAWarning` on stderr | the same warning on stderr, no `SAWarning`; **FAIL, value 2** (`shiped` and the text `NULL`), exit 1 |
| `compile` | `status NOT IN ('pending', 'shipped', NULL)` | `status NOT IN ('pending', 'shipped')` |

The dbt-migrated form (block list with `- null` on its own line) gives
the same outcome, with the warning at the null's own line and column.

**N2 (must) Null in `missing_values` on an `invalid_*` check.**

```yaml
datasource: lake
dataset: orders
checks:
  - invalid_count(status) = 0:
      valid_values: [pending, shipped]
      missing_values: ['', ~]
```

| | Today (measured) | After |
| --- | --- | --- |
| `validate` | exit 0 | exit 0; `` checks/orders.yml:6:28: warning: `missing_values:` item 2 is null and is ignored: … `` |
| `run` | **PASS, value 0**, exit 0 | **FAIL, value 2**, exit 1 |

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

| | Today (measured) | After |
| --- | --- | --- |
| `validate` | exit 0 | exit 0; `` checks/orders.yml:7:11: warning: `missing_values:` item 2 is null and is ignored: … To match the text 'NULL', quote it `` |
| `run` | FAIL, value 2 (rows 4, 5; the text `NULL` in row 6 is not counted, because Sam's `NULL` is a null), exit 1 | FAIL, **value 2, unchanged**, exit 1; the warning on stderr. Once Sam writes `- 'NULL'`, no warning and value 3 (M3) |

**N4 (must) A list of only nulls.**

```yaml
datasource: lake
dataset: orders
checks:
  - invalid_count(status) = 0:
      valid_values: [null]
```

Today: PASS, value 0, exit 0. After: `validate` exits 3 with one error
at the list, `` checks/orders.yml:5:21: error: `valid_values:` has no
values: null is not a value (NULL is always missing, never invalid) ``,
and no per-item warning (one problem, one message); `run` exits 3,
nothing ran. The same for `[null, ~]` and for a block list of only
empty items.

`missing_values` of only nulls is **not** an error: with

```yaml
  - missing_count(status) = 0:
      missing_values: [~]
```

`validate` exits 0 with a warning at `5:24` (item 1), the option is
dropped, and `run` gives FAIL, value 1 (row 4), exactly as today.

**N5 (must) An empty block item (copy-paste leftover).**

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

Today: PASS, value 0, exit 0 (one `SAWarning`). After: `validate` exit
0 with `` checks/orders.yml:7:9: warning: `valid_values:` item 2 is empty
and is ignored: … ``; `run` FAIL, value 2, exit 1.

**Position: the dash, `7:9`.** ruamel marks an empty item one column
after its dash (`7:10`); on line 7 (`        -`, 9 characters) that is
past the end of the line, and with a trailing comment (`-   # todo`)
it lands in whitespace (measured). The dash is the only character the
item has, so the diagnostic points at it: for an empty item, the
column is ruamel's mark minus one. The loader already has to tell an
empty item from a written null to choose the message (the source text
at the mark is not `null`/`Null`/`NULL`/`~`), so this is the same
test, not a new one. The test asserts `7:9`.

**N6 (must) Several nulls, one diagnostic each, one load.**
`valid_values: [null, pending, ~, shipped]` with `missing_values: ['']`
gives two warnings, `5:22` (item 1) and `5:37` (item 3), and FAIL, value
2. And a null in **each** list on one check:

```yaml
  - invalid_count(status) = 0:
      valid_values: [pending, shipped, null]
      missing_values: ['', ~]
```

gives two warnings from one `validate`, `5:40` (`valid_values:` item 3)
and `6:28` (`missing_values:` item 2), and FAIL, value 2 (today PASS,
value 0, with two `SAWarning`s).

**N7 (must) The Python API agrees with the CLI.** `tw.load()` on N1
returns one diagnostic in `project.diagnostics` with severity `warning`,
file `checks/orders.yml`, line 5, column 40, and `project.ok` is true;
`tw.run()` gives FAIL, value 2, the same as the CLI.

**N11 (must) `validate` does not say "no problems found" over a
warning.** Today, with any warning, the closing line on stdout is still
`1 datasets, 1 checks — no problems found` (measured with an empty
`checks:`). Under B the warning is how a user finds a check that never
checked, and the last line is the one people read in a CI log. After:
with warnings and no errors, `validate` exits 0 and ends
`1 datasets, 1 checks — no errors, 1 warning` (plural `warnings`); with
none, `no problems found` as today; with errors, as today (exit 3).
This is a **stdout change**: any test or user script that expects
`no problems found` from a project that has warnings must be updated
(`tests/test_cli.py:36` asserts it on the retail example, which has no
warnings today and must stay that way).

**N8 (must, promoted in REFINE) A list or mapping inside a value list
is a load error.**

```yaml
datasource: lake
dataset: orders
checks:
  - invalid_count(status) = 0:
      valid_values: [pending, [shipped, lost]]
```

Today: `validate` exit 0; `run` exits 2 with, on DuckDB, `Conversion
Error: Type VARCHAR with value 'pending' can't be cast …` (a row value in
an error message; see I-30) and, on SQLite, `Error binding parameter 2:
type 'list' is not supported` (both measured). After: `validate` exits 3 with
`` checks/orders.yml:5:31: error: `valid_values:` items must be single
values (text, a number, true/false); item 2 is a list ``; the same for a
mapping (`{shipped: 1}`: "is a mapping"). No project loses a working
check: this one errors on every run today. The message names the
item's position and kind only; it never quotes the item. Every such
item is reported in the one load, alongside any null warnings.

An unquoted YAML date (`2024-01-01`, which the loader turns into a
`date`) is **not** a list or mapping and keeps loading exactly as today
(non-goal below): the loader excludes `None`, lists and mappings; it
does not allowlist types.

**M5 (must) One way into `IN`, and it is safe without the loader.**
Given `ctx.one_of(col, values)` called directly (bypassing the loader):

- with `['pending', None, 'shipped']`, compiled with `literal_binds` on
  DuckDB and SQLite, the SQL is `status IN ('pending', 'shipped')`, and
  no `SAWarning`;
- with `[None]` or `[]`, the result is SQLAlchemy `false()` (never
  `in_([])`, whose SQL differs by dialect), so `valid_predicate` counts
  every present value as invalid and `missing_predicate` reduces to
  `IS NULL`; the same result on both dialects;
- with an item that is a list or a mapping, the check gets an `error`
  outcome with a fixed message that contains no data (for example
  "valid_values: an item is not a single value"), on both dialects; a
  `date` item compiles as today;
- a test scans `src/tablewatch/metrics/builtin/` and fails if `.in_(`
  appears anywhere outside the helper, so a future list option cannot
  bypass it.

**M6 (must) Quotes inside a value stay escaped.** `valid_values:
[pending, "o'brien"]` compiles under `literal_binds` to
`'o''brien'` on DuckDB and SQLite, and `run` counts rows as today
(guards the helper change against losing `literal()`'s escaping).

### Should

**N9 (should) The editor schema says the same.** The JSON schema
generated for value-list options (`config/jsonschema.py`) becomes
exactly `{"type": "array", "minItems": 1, "items": {"type": ["string",
"number", "boolean"]}}`, so VS Code underlines N1, N4 and N8 as the
user types. (Under B the editor's mark is stronger than the loader's
warning; accepted in REFINE, as the item does nothing. The YAML
language server reads an unquoted date as a string, so dates are not
underlined.)

**N10 (should) Docs.** `docs/check-language.md`'s options table says,
for `valid_values` and `missing_values`: NULL is always missing and never
invalid, so never list it; quote `'NULL'` to match the text. The
CHANGELOG entry (PM, in REVIEW) says a check that passed may now fail
because it was never checking, that `missing_count` and
`missing_percent` checks keep their numbers exactly, that `validate`'s
closing line now counts warnings, and to run `tablewatch validate`
after upgrading.

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
- **Rule 7 / exit codes.** Unchanged contract. N4 (`valid_values` of
  only nulls) and N8 add new exit-3 cases for files that would otherwise
  load; neither is a check that works today (measured: N4 passes
  whatever the data holds, N8 errors on every run).
- **Check identity** is untouched: options do not feed
  `derive_check_id`; `tests/golden/retail-list.txt` stays as it is.

### Design (settled in REFINE; the open questions are closed)

1. **The helper.** `MetricContext.one_of(col, values) ->
   ColumnElement[bool]` in `metrics/base.py`, beside `count_where` and
   `regex_search`. It drops `None`, wraps every kept item in
   `literal()`, and returns `sqlalchemy.false()` when nothing is left
   (never `in_([])`). It rejects a list or mapping item with a fixed,
   data-free error that becomes the check's `error` outcome (rule 7);
   it accepts dates and every other scalar. `validity.valid_predicate`
   and `completeness.missing_predicate` both use it; the latter's
   `if missing_values:` guard today lets `[None]` through, so the empty
   case must go through the helper too. It is the only `.in_(` in
   `metrics/builtin/` (M5's test enforces it). It is a backstop: from
   YAML, the metric never sees a `None`.
2. **The loader.** `_option_ok`'s bool becomes a method that returns the
   cleaned value or "invalid". For a value-list option it walks the
   `CommentedSeq` by index: `None` is a warning at `of_item` and is
   dropped (an empty item one column left, N5); a list or mapping is an
   error at `of_item` (N8); nothing left is an error at
   `of_value(node, key)` for `valid_values` (N4) and a dropped option
   for `missing_values`. Every item is reported in one pass; nothing
   raises (rule 5). It excludes `None`, lists and mappings rather than
   allowlisting types, so unquoted YAML dates keep loading. The cleaned
   list is what reaches `Check.options`, so `compile` prints the
   cleaned SQL.
3. **Merged and aliased options.** `of_value` can raise `KeyError` for
   an option that arrives through a `<<:` merge key; the loader must
   fall back to `of_node(seq)` or `locate`, never raise. An aliased list
   (`*anchor`) reports at the anchor's item, which is right: that is
   where the user fixes it.
4. **`OptionType`.** No second list type. `LIST` has exactly two users
   (`valid_values`, `missing_values`); it is redefined as a value list,
   renamed `VALUE_LIST` with the label "list of values", and `LIST` is
   deleted. The item rule (scalar, not null) and the schema line (N9)
   come from that one definition.
5. **Exit codes.** A warning alone leaves `validate` and `load` at exit
   0 / `project.ok` true (N1, N7); only N4 and N8 are new exit-3 cases.

## Reviewers required

- **qa-engineer** (always): hunt for other ways a null or non-scalar
  reaches SQL. Focus: an anchor/alias sharing a list that holds a null
  (one warning, at the anchor's item; untested today), a `<<:` merge
  key carrying `valid_values` (no `KeyError`), `_defaults.yml`
  inheritance of a value list, and a mix of nulls and N8 items in one
  list.
- **data-steward** (always): chose B in REFINE; checks the wording and
  the `missing_*` numbers in VERIFY.
- **architect** (touches `src/`: `MetricContext`, loader, `OptionType`).
- **security-reviewer**: the change alters **what can reach SQL** (a
  trigger in PROCESS.md). Checks in VERIFY: no message quotes an item,
  M5's list/dict error is data-free, M6's escaping.

## Size

**S** (confirmed in REFINE). One helper and two predicates moved onto
it, a per-item walk in the loader, one `OptionType` renamed, the schema
line, `validate`'s closing line, a docs row, and tests on two backends.
Anything the QA hunt finds beyond value lists becomes a backlog item,
not scope.
