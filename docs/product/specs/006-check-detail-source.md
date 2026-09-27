# Spec 006: Check detail 3 (the check's own YAML source)

| | |
| --- | --- |
| Backlog item | I-29 (the Source half of I-26, split off in iteration 5 REFINE by the pre-planned split in spec 005) |
| Features | C4 (check detail): the source part. C4 is complete when this ships |
| Phase | 2 (`0.2.0`) |
| Size | S |
| Depends on | I-26 (spec 005: the `CheckPage` section split, `CodeBlock`, `CopyButton`, `lib/clipboard.ts`, invisible-character marking, the `useLoads` slot pattern for a check's sections) |
| Branch | `iter/006-check-detail-source` |
| Status | **ready** (iteration 6 PLAN, 2026-09-27, against `main` at `8687ebc`). Carried out of spec 005 with every iteration 5 REFINE decision on the Source half already made; re-checked against what spec 005 shipped (see "Iteration 6 PLAN re-check"). **Short REFINE settled** (iteration 6, 2026-09-27): security-reviewer (B1, B2 in; F1, F3–F5 decided), architect (Q1/Q2 shape), ui-engineer (Q3, P16, page wording). Decisions are in the contract (B1, B2), the scenarios (Y6, Y16, Y18, Y19, X3, X4, P4–P16) and Design notes (the architect's answers, SourceBlock, "Other iteration 6 REFINE decisions") |

Why this exists: spec 005 grew past S in REFINE (see its "Size"), so the
pre-planned split was applied. Everything below was written and reviewed
in iteration 5 REFINE; it is kept here so none of it is lost or re-argued.

## Problem and persona

**Sam, data steward.** "I don't write SQL, but I do read YAML. When the
page says 'Expected < 5%' I want to see what was written in the file,
including the comment that says why the rule is 5%, and which file to
ask Dana to change. I can't browse the repository."

**How Sam copes today.** The page shows `file:line:col`, so the source is
one editor jump away for Dana and out of reach for Sam.

**Others.** dbt docs show a model's source next to its compiled code
([dbt: documentation website](https://docs.getdbt.com/docs/building-a-dbt-project/testing-and-documentation/documentation-website/)).
Spec 005 ships the compiled half; this is the source half.

## Outcome

On `/checks/<id>`, below the SQL section, a **Source** section: the
check's own lines from its file in the project's checks directory, with
line numbers and the file path, as loaded by this server; and, when the
file has a dataset `filter:`, a sentence saying which rows the check
looks at (P13). One read-only endpoint serves it:
`GET /api/v1/checks/{id}/source`. It never reads a file at request time.

## The contract change (additive)

### `GET /api/v1/checks/{id}/source` → `CheckSource`

```text
CheckSource { check_id: string, path: string,           # project-relative, under the project's checks directory
              start_line: int | null, end_line: int | null,   # 1-based, inclusive; null when the span is unavailable
              text: string | null,                      # those lines, joined by "\n", no trailing newline; null with the span
              filter: FileFilter | null,                # the file's dataset `filter:`, if it has one
              loaded_at: date-time }                    # equals /project's loaded_at
FileFilter  { line: int,                                # 1-based line of the `filter:` key
              text: string,                             # the filter as loaded, as it appears in the SQL's WHERE
              applies: boolean }                        # false for metrics the filter never scopes (sql_metric, schema)
```

Every field is `required` in `openapi.json` (nullable where shown).
404 `not_found` for an id that is malformed or not loaded, as `/sql`.

- **Span unavailable (architect A2, decided in iteration 5 REFINE):**
  200 with `path` set and `start_line`, `end_line` and `text` all null,
  never 404. A 404 already means "not in the loaded project" to the page
  (spec 005's loading rule), and the path alone still tells Sam which file
  to ask about. The page says "The lines of this check could not be
  shown; it is in `<path>`." Capturing a span that fails is the tool's
  fault, not the user's: no diagnostic, no exception (rule 5).
- **The path (architect A3):** under the project's checks directory,
  which is `checks/` unless `checks_path` is configured.
- **Lines (security B1, iteration 6 REFINE; `must`).** The file's text as
  loaded is split on `\r\n`, `\r` and `\n` **only** —
  `re.split(r"\r\n|\r|\n", text)`, dropping one trailing empty string —
  and **never** with `str.splitlines`, which also breaks on `\x0b`,
  `\x0c`, `\x1c`–`\x1e`, U+0085, U+2028 and U+2029. ruamel's marks do not
  count those, so `splitlines` numbers lines differently from the parser
  and a span can serve a neighbouring line (reproduced: two U+0085 in a
  quoted `dataset:` value make a check's `text` the `filter:` line). Line
  numbers everywhere in this spec mean lines by this rule. See Y18.
- The span (D2, refined by the data-steward in iteration 5 REFINE). For a
  **block-style** list item, `c` is the column of its `-`:
  1. **Body.** From the `-` line through the last line of the item that is
     neither blank nor comment-only. Blank and comment lines *inside* that
     range stay (a blank line inside a `query: |` block, a comment between
     two options). Inline comments stay. A line inside a block scalar
     (`query: |`) is content even if it starts with `#`, so the rule
     needs the scalar's extent from the parse, not a text test.
  2. **Trailing comments belong to the check above if indented past its
     dash.** Comment-only lines directly below the body (no blank line
     between), each indented **more than `c`**, are part of the span.
  3. **Leading comments belong to the check below.** Comment-only lines
     directly above the `-` (no blank line between), not already claimed
     by rule 2 for the previous check, are part of the span, whatever
     their indentation. This includes a comment directly under
     `checks:` above the **first** check.
  4. **Nothing outside the list.** The span never reaches above the
     `checks:` key or into a later top-level key. Comment lines at or left
     of `c` after the last check belong to no check.
- **Flow style** (`checks: [a, b]`): the line(s) of the item's own node,
  no comment extension. Two checks on one line both get that whole line,
  including `checks: [`.
- **Flow style sharing a line with another key (iteration 6 PLAN, R6):**
  if any line of a flow-style span also holds part of a top-level key
  other than `checks` (its key or its value), the span is **unavailable**
  (A2: 200, `path` set, lines and `text` null). This loads today and would
  otherwise serve `dataset:` and `filter:`:
  `{dataset: sales.returns, filter: "status != 'test'", checks: [row_count > 0]}`.
  See Y17.
- **Post-condition on the item's own line (security B1 (b); `must`).**
  After the span is computed, the item's start line is checked against
  the split lines: in block style, the character at column `c` of the
  item's line is `-`; in flow style, the text at the item node's start
  mark (line and column) is the node's first character as written (`{`,
  `[`, a quote, or the scalar's first character). Otherwise the span is
  **unavailable**. This catches any disagreement between the parser's
  marks and the split lines that the split rule misses, and an alias item
  whose marks point at its anchor elsewhere (Y19).
- **The extent invariant (security B2; `must`; checked last, for every
  layout).** Every line of a span lies inside the `checks` extent **and**
  overlaps no other top-level key's extent. Otherwise the span is
  **unavailable**. From the composed root's marks: the `checks` extent
  runs from the line below the `checks:` key (block style; so rule 3's
  comment directly under `checks:`, Y11, is inside) or the key's own line
  (flow style) through the value node's last line; another key's extent
  runs from its key's line through its value's last line. A node's last
  line is its end mark's line, less one when the end mark's column is 0. It is the
  general form of the flow-style rule above and of D2 rule 4, and it is
  the last guard whatever rules 1–3 produced: alias items (`- *a`, whose
  marks are the anchored node's, elsewhere in the file), a `]` sharing a
  line with a following key, and bugs in rules 1–3. Y17's two cases are
  its flow instances; Y19 is the alias instance.
- **Multi-document files** are rejected by the loader today and never
  load. Unchanged.
- **`filter`** is the dataset `filter:` from the check's own file, never
  from anywhere else (`_defaults.yml` cannot set one). `applies` is the
  metric's existing `scoped` flag.
- The text is as loaded when `serve` started. No file is read at request
  time; nothing about the path comes from the request.
- The span is not part of check identity: `derive_check_id` is untouched.

### Decision on `CheckSource.filter` (PM, iteration 5 REFINE)

**Accepted.** The data-steward added it, departing from the earlier
non-goal "no inherited settings in the source" and from the carried
requirement "only the check's own lines". Reasons: a `filter:` changes
what every number on the page means; Sam does not read the SQL's
`WHERE`, which is the only other place it shows; and it exposes nothing
new, because spec 005's `/sql` already serves it inlined. It is a
**separate field**, so security R6 still holds for `text`: the span never
includes the `filter:` line (or `dataset:`, `datasource:`, `_defaults.yml`
lines). The carried requirement is restated as: "`text` is only the
check's own lines; `filter` is the one other value from the same file,
served as its own field." The security-reviewer confirms this in this
spec's REFINE (brief item 2); if rejected, `filter` and P13's filter
sentences drop out and nothing else changes.

**Confirmed by the security-reviewer (iteration 6 REFINE), with two
conditions, both taken:**
- `filter.text` is exactly the text `/sql` puts in the `WHERE`, never
  `${env:}`-resolved. Y6 gains an env canary for it.
- **Correction:** "it exposes nothing new" is not quite true. `/sql`
  shows the filter only for a scoped check; a file whose checks are all
  `sql_metric` or `schema` never showed its filter before, so `/source` is
  its first exposure over the API. Accepted: it is the same file whose
  comments `/source` already serves, and X3's warning names check files.

## Architect's shape (iteration 5 REFINE, Q2)

- The file's lines once per dataset: `Dataset.source_lines: tuple[str, ...]
  = field(default=(), repr=False)` (`repr=False` is required, I-18).
- `Check.span: SourceSpan | None` (frozen, 1-based inclusive, in
  `checks/model.py`), computed at load time by a private pure function in
  `config/`; any failure gives `span=None` and no diagnostic.
- The text comes from the same read `YAMLSource` already does (no second
  read), split by the line rule above (**not** `splitlines`: superseded
  in iteration 6 REFINE, security B1).
- Do not use ruamel's comment attachment; do not use "next item's start
  − 1" (it fails when `checks:` is not the last key). Block-scalar extents
  come from the parse (D2 rule 1). Iteration 6 REFINE settles how: see
  "Architect's answers to Q1 and Q2" under Design notes.
- `Check.location` does not change; `derive_check_id` takes explicit
  arguments and is not touched. Both attributes are provisional public
  API, as `expectation` is.

## Acceptance scenarios

**Fixtures:** `retail`, `recorded`, `edited-pending` (spec 004), `remote`
(spec 005), and **`commented`**: `retail` with `checks/sales/orders.yml`
replaced by the file in Y4, plus `checks/sales/returns.yml` (Y10),
`checks/flow.yml` and `checks/flowmulti.yml` (Y8). `tablewatch validate`
on it: `6 datasets, 18 checks — no problems found` (data-steward,
iteration 5 REFINE; **re-confirmed in iteration 6 PLAN** by building the
fixture and running the loader on `8687ebc`). `commented` is `tests/`'s
existing `filtered` fixture (spec 005, which already writes Y10's
`returns.yml`) plus Y4's `orders.yml` and Y8's two files.

Check ids and spans (iteration 5; **every id and start line re-confirmed
in iteration 6 PLAN** with `load_project` on `retail` and `commented`;
spans are by the rule above, checked by hand against the files):

| id | file | check | span on `retail` | span on `commented` |
| --- | --- | --- | --- | --- |
| `b1ceb8262d8b5441` | customers.yml | `missing_percent(email) < 5%` | 6–7 | 6–7 |
| `32c8f939b90f6367` | customers.yml | `row_count > 0` | 4 | 4 |
| `32867fbe86f483f3` | orders.yml | "Order volume" | 5–8 | 10–14 |
| `ed669ca6e5532a59` | orders.yml | "No negative amounts" | 15–17 | 4–8 |
| `fbc3aa0b93b66eee` | orders.yml | `schema` | 18–20 | — |
| `b744847e7c518188` | returns.yml | `row_count > 0` | — | 6–7 |
| `2e17ee98b3e57dc9` | returns.yml | "Every return has an order" | — | 8–10 |
| `4a831091035ca6c6` | returns.yml | `avg(amount) between 1 and 500` | — | 11–12 |
| `b6ecae522c1d4aaf` | customers.yml | `invalid_count(email) = 0` | 10–12 | 10–12 |
| `e3a77b3bf2c0c560` | flow.yml | `row_count > 0` | — | 3 |
| `db9a7d9aa48da0b3` | flow.yml | `duplicate_count(id) = 0` | — | 3 |
| `50da186584df05e1` | flowmulti.yml | `row_count > 0` | — | 3 |
| `1b12d65bb5987f8a` | flowmulti.yml | "Positive price" | — | 4 |

`Check.location` is the item's **content** column (`  - row_count > 0`
is `4:5`), not the dash's (column 3). D2's `c` is the dash's column.

### Identity (tech lead, pytest)

**I1: identity does not move** `must`
- Spec 005's `list` golden file still matches on `retail`.
- On `commented`, "No negative amounts" and "Order volume" keep their
  `retail` ids (`ed669ca6e5532a59`, `32867fbe86f483f3`) though their lines
  and comments differ. Capturing a span never feeds `derive_check_id`.

### Source (tech lead, pytest)

**Y1: a check with options** `must`
- Given `retail` served
- When `GET /api/v1/checks/b1ceb8262d8b5441/source`
- Then 200 with `path` `"checks/sales/customers.yml"`, `start_line` 6,
  `end_line` 7, and `text`

  ```text
    - missing_percent(email) < 5%:
        missing_values: ['', 'N/A']
  ```

  (two lines, original indentation, no trailing newline), `filter` null,
  and `loaded_at` equal to `GET /api/v1/project`'s `loaded_at`

**Y2: a trigger check in the middle of a file** `must`
- When `GET /api/v1/checks/32867fbe86f483f3/source`
- Then `path` `"checks/sales/orders.yml"`, lines 5–8:

  ```text
    - row_count:
        name: Order volume
        warn: when < 100
        fail: when = 0
  ```

**Y3: the last check in a file, and a one-line check** `must`
- `fbc3aa0b93b66eee` is `orders.yml` lines 18–20 (ending
  `      column_types: {amount: decimal}`)
- `32c8f939b90f6367` is `customers.yml` line 4 only (`start_line` =
  `end_line` = 4)

**Y4: comments** `must`
- Given `commented`, where `checks/sales/orders.yml` is

  ```yaml
  dataset: sales.orders

  checks:
    # Finance reconciles on amount: a negative amount breaks the ledger.
    # Refunds are separate rows, so none should be negative.
    - failed_rows:
        name: No negative amounts
        condition: amount < 0   # refunds are their own rows

    # Volume alarm agreed with ops, 2026-09.
    - row_count:
        name: Order volume
        warn: when < 100
        fail: when = 0
    # trailing note, not part of any check
  ```

- Then "No negative amounts" (`ed669ca6e5532a59`) is lines 4–8 (both
  comment lines above it, the inline comment kept, the blank line 9
  dropped)
- And "Order volume" (`32867fbe86f483f3`) is lines 10–14 (its comment line
  10 included; the trailing comment on line 15, at the dash's column, is
  not)

**Y5: as loaded, never re-read** `must`
- Given `retail` served
- When `checks/sales/customers.yml` is then edited on disk, and later
  deleted
- Then `/source` for `b1ceb8262d8b5441` still answers 200 with Y1's text
  and lines

**Y6: nothing outside the check's lines, ever** `must` (security R6)
- Given `remote` served
- When `/source` is requested for every loaded check
- Then no response body contains `canary-tw-5f3a` (it is only in
  `tablewatch.yml` and `_defaults.yml`) or `ops@example.com`, every `path`
  is under the checks directory and is not a `_defaults.yml`, and no
  `text` contains a `dataset:`, `datasource:` or `filter:` line
- The span never extends above the check's own item and its directly
  adjacent comment block (flow style, Y8, is the one exception: the
  shared line)
- **Env canary (security, iteration 6 REFINE):** given `TW_CANARY` set
  to `canary-env-9c1d` and a check file with
  `filter: "region = '${env:TW_CANARY}'"` and a comment
  `# ${env:TW_CANARY}` inside a check's span, no `/source` or `/sql`
  body contains `canary-env-9c1d`; `filter.text` is the text as written
  (`region = '${env:TW_CANARY}'`), which is also what `/sql`'s `WHERE`
  shows

**Y7: ids that look like paths** `must`
- When `GET /api/v1/checks/{x}/source` for `x` in `tablewatch.yml`,
  `..%2Ftablewatch.yml`, `%2e%2e`, `checks%2Fsales%2Fcustomers.yml`, and
  65 characters
- Then each answers 404 `not_found` (or the router's own 404), no file
  is opened while answering (the test patches `open`/`Path.read_text`
  to fail), and the body does not echo the id beyond what `/checks/{id}`
  already does

**Y8: flow-style lists** `should`
- Given `commented`, whose `checks/flow.yml` is

  ```yaml
  dataset: sales.customers
  # both checks on one line
  checks: [row_count > 0, "duplicate_count(id) = 0"]
  ```

  and whose `checks/flowmulti.yml` is

  ```yaml
  dataset: inventory.products
  checks: [
    row_count > 0,
    {"min(price) > 0": {name: Positive price}}
  ]
  ```

- Then both `flow.yml` checks' `/source` is line 3 alone, `text`
  `checks: [row_count > 0, "duplicate_count(id) = 0"]`
- And in `flowmulti.yml`, `row_count > 0` is line 3 (`  row_count > 0,`)
  and "Positive price" is line 4

**Y9: Windows line endings, and no final newline** `should`
- Given `customers.yml` saved with CRLF line endings
- Then Y1's lines and text are unchanged (no `\r` in `text`)
- And given `customers.yml` with the final newline removed, the last
  check (`b6ecae522c1d4aaf`, lines 10–12) ends
  `      missing_values: ['', 'N/A']` in full

**Y10: comments that belong to the check above, and a key after the list** `must`
- Given `commented`, whose `checks/sales/returns.yml` is

  ```yaml
  # Returns feed from the OMS; owned by ops.
  dataset: sales.returns
  filter: status != 'test'

  checks:
    # Tier-1: paged out of hours.
    - row_count > 0
    - missing_count(order_id) = 0:
        name: Every return has an order
        # fail: when > 5   (restore after the CRM backfill)
    - avg(amount) between 1 and 500:
        where: reason != 'damaged'
    # - duplicate_count(return_id) = 0   (off: known duplicates)
  # canary-tw-5f3a: not part of any check
  owner: returns@example.com
  ```

- Then "Every return has an order" (`2e17ee98b3e57dc9`) is lines 8–10
- And `avg(amount) between 1 and 500` (`4a831091035ca6c6`) is lines 11–12
  and does **not** include line 10
- And no span includes lines 13–15; no `/source` body contains
  `canary-tw-5f3a` or `returns@example.com`
- And no span includes line 1

**Y11: a comment directly under `checks:` is the first check's** `must`
- Given `commented`
- Then `row_count > 0` in `returns.yml` (`b744847e7c518188`) is lines 6–7,
  `text` starting `  # Tier-1: paged out of hours.`
- And given the same file with a blank line inserted after line 6, the
  same id's span is line 8 alone, and its id is unchanged

**Y12: the file's filter is stated with the source** `must`
- Given `commented`
- When `/source` for `4a831091035ca6c6`
- Then `filter` is `{line: 3, text: "status != 'test'", applies: true}`
- And for every `retail` check, `filter` is null
- And given `retail` plus `checks/sales/filtered.yml`

  ```yaml
  dataset: sales.returns
  filter: status != 'test'
  checks:
    - sql_metric > 0:
        name: Custom
        query: SELECT 1
    - schema:
        required_columns: [id]
  ```

  "Custom" (`98cd31ce24b6afef`) has `filter`
  `{line: 2, text: "status != 'test'", applies: false}`, and the `schema`
  check (`2f9a43de2ae47ba9`) has `applies: false` too. (`failed_rows` is
  scoped: its `applies` is true.)

**Y13: a block scalar with a blank line inside** `should`
- Given a check file

  ```yaml
  dataset: sales.orders
  checks:
    - sql_metric > 0:
        name: Refund ratio
        query: |
          SELECT count(*)
          FROM refunds

          WHERE amount > 0

    - row_count > 0
  ```

- Then "Refund ratio" is lines 3–9 (the blank line 8 inside the query
  kept, the blank line 10 dropped), and `row_count > 0` is line 11 alone
- And the variant with line 9 as `        # WHERE amount > 0` (validated:
  it loads with no problems) is still lines 3–9: line 9 is SQL text in a
  block scalar, not a YAML comment
- (On `retail` plus this file as `checks/sales/refunds.yml`: "Refund
  ratio" is `d0ebb1527db76d0e`, `row_count > 0` is `60a5659cd85bdeb3`.)

**Y14: span unavailable** `must` (architect A2)
- Given the span function patched to raise for one check
- Then `/source` for it answers 200 with `path` set and `start_line`,
  `end_line`, `text` null; `tablewatch validate` reports no new
  diagnostic; every other check's `/source` is unaffected

**Y15: a configured checks directory** `should` (architect A3)
- Given `retail` with its checks moved to `rules/` and `checks_path:
  rules` in `tablewatch.yml`
- Then the `missing_percent(email) < 5%` check's `path` is
  `"rules/sales/customers.yml"`, with Y1's lines and text. Its id is
  **`1c895d786d75783b`**, not Y1's: the path feeds the id, so moving the
  files starts new ids (corrected in iteration 6 PLAN; the draft reused
  Y1's id)

**Y16: symlinked check files are served under the link's path** `must`
(documents today's behaviour; F3 is a pending owner question)
- Given a check file in `checks/` that is a symlink to a file outside the
  project
- Then its checks load (as today) and `/source` serves its lines under
  the link's path. The README says so plainly.
- And (security, iteration 6 REFINE) `path` is the unresolved walk path
  relative to the project root (`checks/sales/linked.yml`); no `/source`
  body contains the symlink's target, the project root's absolute path,
  or any absolute path. The served path is never `resolve()`d.

**Y17: a flow-style check that shares a line with another key** `must`
(security R6; iteration 6 PLAN)
- Given `retail` plus `checks/sales/one.yml`, one line:

  ```yaml
  {dataset: sales.returns, filter: "status != 'test'", checks: [row_count > 0]}
  ```

  and `checks/sales/two.yml`:

  ```yaml
  dataset: sales.returns
  checks: [row_count > 0]
  filter: "x > 1"
  ```

  (both load today with no problems: `5 datasets, 20 checks`)
- Then `/source` for `ec91af87c6b3495e` (`one.yml`) answers 200 with
  `path` `"checks/sales/one.yml"`, `start_line`, `end_line` and `text`
  null, and `filter` `{line: 1, text: "status != 'test'", applies: true}`
- And `/source` for `05f53a5d2c6df89c` (`two.yml`) is line 2,
  `checks: [row_count > 0]` (the `filter:` on line 3 is not on the
  item's line)
- And no `/source` body's `text` contains `dataset:` or `filter:`

**Y18: line breaks YAML does not count** `must` (security B1; iteration 6
REFINE; loaded on `8687ebc`)
- Given `retail` plus `checks/sales/odd.yml`, whose line 1 holds two
  literal U+0085 characters inside a quoted scalar and whose line 5 holds
  a literal U+2028 inside a check's `name:` (shown escaped here; the file
  holds the characters themselves):

  ```text
  dataset: "sales.\u0085\u0085returns"
  filter: "status != 'test'"
  checks:
    - row_count > 0:
        name: "Row count"
    - missing_count(order_id) = 0
  ```

  (`tablewatch validate`: `4 datasets, 20 checks — no problems found`;
  `Check.location` is `4:5` and `6:5`)
- Then `8cc200a22eae9821` (`row_count > 0`) is lines 4–5, its `text`
  the two lines as written (the U+2028 inside, byte for byte)
- And `e221fe4ab178f661` (`missing_count(order_id) = 0`) is line 6 alone
- And no `text` contains `filter:` or `dataset:`; each span is either
  exactly the above or unavailable (never another line)
- And a unit test on the split: a line containing `\x0b`, `\x1c`,
  U+0085, U+2028 or U+2029 stays one line. (A file holding `\x0b`,
  `\x0c` or `\x1c`–`\x1e` does not load today — ruamel's `ReaderError`
  escapes as a traceback, I-36 — so only the split function is tested on
  those.)

**Y19: an alias as a check item** `must` (security B2, architect F2;
iteration 6 REFINE; loaded on `8687ebc`)
- Given `retail` plus `checks/sales/aliasblock.yml`:

  ```yaml
  dataset: sales.returns
  filter: &f "row_count > 0"
  checks:
    - *f
    - missing_count(order_id) = 0
  ```

  and `checks/sales/aliasflow.yml`:

  ```yaml
  dataset: sales.returns
  filter: &f "row_count > 0"
  checks: [*f]
  ```

  (`validate`: `5 datasets, 21 checks — no problems found`; the alias
  items' `Check.location` is `2:10`, the anchor's line)
- Then `/source` for `460df3094802aae6` (`aliasblock.yml`, `- *f`) and
  for `de7237bdd4e28185` (`aliasflow.yml`) answers 200 with `path` set,
  `start_line`, `end_line` and `text` null, and `filter`
  `{line: 2, text: "row_count > 0", applies: true}`: never line 2
- And `a9c725e6799c5296` (`missing_count(order_id) = 0`) is line 5 alone

### Exposure (tech lead; security-reviewer judges)

**X1: methods** `must`: `POST`, `PUT`, `DELETE` on `/source` answer 405
with the envelope.

**X2: OpenAPI** `must`: `get_check_source` with 404, 405 and 500,
`loaded_at` as `date-time`, every field required; generated types fresh.

**X3: the warning names the check files** `must` (security R3, full text)
- The `--host` warning becomes exactly R3's sentence:
  `tablewatch: warning: serving on {host} with no authentication — anyone who can reach this address can read this project's check files (comments included), the SQL each check runs, and its results: data values, database error messages that can quote row values, and owner emails. Authentication arrives in Phase 4 (tablewatch.yml cannot turn it on yet).`
  The README quotes it verbatim; `--host` help says "serves check files,
  SQL and results without authentication".
- Today (spec 005's interim, `cli/main.py` and README line 432) the
  sentence says "read this project's checks, the SQL…" and the help says
  "serves checks, SQL and results…". Only "checks" → "check files
  (comments included)" in the warning, and "checks" → "check files" in
  the help, change. Security accepted the interim only until the PR that
  starts serving check files, which is this one: this scenario ships
  here or `/source` does not ship.
- A test compares the CLI's warning string with the README's quoted
  block, so the two cannot drift (security, iteration 6 REFINE).

**X4: the README says who can read check files** `must` (security F1,
iteration 6 REFINE)
- The README's `serve` section says, next to the warning: "Anyone who can
  reach the server can read your check files, comments included. Keep
  credentials in environment variables (`${env:NAME}`), never in a check
  file or a comment." (data-steward may reword in VERIFY; the two facts
  stay.)

### The page (ui-engineer, vitest; data-steward by hand)

The block is a new `SourceBlock` component (Q3, decided below). Every
sentence quoted here is the PM's wording, settled in iteration 6 REFINE
from the ui-engineer's questions; **the data-steward confirms it in
VERIFY** (may shorten, not change the meaning). In the strings below,
`` `x` `` means `x` rendered in `<code>`.

**P4: the Source section** `must`
- Given `/checks/32867fbe86f483f3` on `retail`
- Then a section headed "Source" (open, no `<details>`, `id="source"`)
  shows lines 5–8 in a `SourceBlock`: one
  `<span class="line" data-line="5">` … per line, blank lines included,
  line numbers drawn by CSS (`.line::before { content: attr(data-line) }`)
  so they are never copied, the YAML verbatim, no wrapping
- The `<code>` element's `textContent` equals `text` exactly (the jsdom
  stand-in for "selecting the code does not select the numbers"; real
  selection is checked by hand)
- Caption, exactly: "`checks/sales/orders.yml`, lines 5–8, from the check
  files as loaded 2 hours ago." (en dash; "2 hours ago" is the `Ago`
  component rendered as `<time dateTime="{loaded_at}">`, using
  **`/source`'s own `loaded_at`**, so the caption renders when `/project`
  fails)
- A one-line span (`32c8f939b90f6367`): "`checks/sales/customers.yml`,
  line 4, from the check files as loaded 2 hours ago."
- A flow-style line shared by two checks (Y8 `flow.yml`) gets the same
  caption ("line 3") and no extra sentence: the other check is visible on
  the line itself, and the API does not say the line is shared.
  (Data-steward to confirm in VERIFY; a sentence would need a new field.)

**P5: the source is today's, the result may not be** `must`
- Given `edited-pending`, the Source section shows
  `missing_percent(email) < 25%` and its caption contains "as loaded"
- Spec 005's wording guard extends to the Source section: its words
  **outside the code block** (heading, caption, P13's sentences, P6/P7/
  P15's lines, the Copy button), on every fixture, match none of
  `/\bproduced\b/i`, `/\blatest\b/i`, `/\bthis result\b/i`, `/\bran\b/i`,
  `/\bexecuted\b/i`. The file's own lines are exempt: a comment may say
  anything.

**P6: no longer loaded** `must`: as spec 005's P6, for the Source section
("The source is not available: this check is not in the loaded check
files."). None of P13's sentences show.

**P7: one failure stays in its section** `must`: as spec 005's P7, for
`/source`: "The source could not be loaded." A 404 from `/source` means
"no longer loaded" (P6) only when `/checks/{id}` is also 404. The page
status gains `sourceFailed` beside `sqlFailed`, by the same rule: either
one makes the status "Could not load everything."

**P8: text is text** `must`: a comment containing
`<script>alert(1)</script>` appears literally.

**P9: copy** `should`: "Copy the source" copies `text` exactly, with spec
005's clipboard rules; the Select-all fallback selects the `<code>`
element only (not the line numbers, the caption or the region).

**P11: `#source`** `should`
- `/checks/<id>#source` scrolls to the Source section once the first
  round of loads settles, as `#sql` does; `CheckPage`'s single
  `SQL_FRAGMENT` becomes a small map (`#sql` → `sql`, `#source` →
  `source`)
- The identity panel's "Source" row value, the whole `file:line:col`
  (`checks/sales/orders.yml:11:5` for `32867fbe86f483f3` on `commented`), is a link to
  `#source` whenever the Source section is on the page; plain text when
  it is not (the not-found panel)

**P13: what the source does not show** `must`
- Given `/checks/4a831091035ca6c6` on `commented` (`applies: true`)
- Then below the lines, as text, not a code block, whether or not `/sql`
  compiled: "Only rows matching this file's
  `filter: status != 'test'` (line 3) are checked."
- `applies: false`: "This file's `filter:` (line 2) does not apply to
  this check." When `/checks/{id}` has loaded and its `metric` is
  `sql_metric`, the sentence continues: " Its query runs exactly as
  written." On Y12's fixture, "Custom" (`98cd31ce24b6afef`) shows both;
  the `schema` check (`2f9a43de2ae47ba9`) shows the first sentence only;
  so does any check while `/checks/{id}` has failed
- On every 200 from `/source`, P15 included (`should`): "The dataset,
  datasource, owner and tags shown at the top of the page come from this
  file's first lines or a `_defaults.yml`." Never on P6 or P7

**P14: invisible characters** `must` (security R5; promoted from `should`
in iteration 6 REFINE, security F3): as spec 005's P14, for the Source
block and the path, using the existing `Marked` component (it keeps the
character in the DOM and draws the marker from CSS, so P4's
`textContent` rule still holds).
- `lib/invisible.ts` also marks **U+2028 and U+2029** (ui-engineer: some
  browsers break a line on them inside `<pre>`, which would put text
  under the wrong number; this protects the SQL block too). U+0085 is
  already marked (C1)
- A vitest fixture: a comment line containing U+202E; a `name:` line
  containing U+2028 (Y18's); a `text` whose first character is U+FEFF
  (files are read as `utf-8`, not `utf-8-sig`, so a BOM stays in line 1:
  a flow-style file that starts `checks: [row_count > 0]` and names its
  `dataset:` on line 2 serves it; it is marked, not stripped); and a `path` of
  `checks/sales/orders​.yml` (U+200B) and one containing a C0
  control (U+001B) in the file name. Each is marked in place; the line
  count and numbering are unchanged; Copy copies `text` byte for byte

**P16: long lines** `should` (checked by hand; iteration 6 PLAN)
- The Source block does **not** soft-wrap (unlike spec 005's SQL block,
  P12): YAML's indentation is its meaning, and a wrapped line would sit
  under the wrong line number. It scrolls sideways inside itself; its
  container chain has `min-width: 0`; it is a focusable, labelled region
  (`tabIndex=0`, `role="region"`)
- At a 360 px wide viewport, with a 200-character `valid_regex:` line,
  **the page never scrolls sideways**, and **each line number stays level
  with its line** (option (a), decided in iteration 6 REFINE: guaranteed
  because nothing wraps). A number column that stays put while the block
  scrolls sideways (sticky, option (b)) is not required
- Vitest checks only the class, the attributes and the region; the 360 px
  behaviour and real text selection are the hand run's

**P15: span unavailable** `must`: given Y14's response, the section shows
"The lines of this check could not be shown; it is in `<path>`." (path
marked per P14), followed by P13's filter sentence if `filter` is set,
and P13's third sentence.

## Non-goals

- `_defaults.yml`, `dataset:`, `datasource:` and file-level `tags:` are
  never part of `text`; `_defaults.yml` is never read for display. The
  `filter:` is served only as its own field.
- No editing, no "open in editor" or repository links.
- No refusal of symlinked check files (F3, pending owner decision).
- No syntax highlighting.
- No size cap on a span (security F4; see Design notes).
- No fix here for files that do not load today because of a control
  character (I-36) or for an unvalidated `checks_path` (I-37).

## Design notes

- Rule 5: span capture is part of the load pass; failure is `span=None`,
  never a diagnostic or exception.
- Rule 6: `/source` never touches a datasource.
- Check identity is untouched (I1).
- **I-33 ships after this and changes `failed_rows` ids** (owner
  decision, 2026-09-27): `ed669ca6e5532a59` ("No negative amounts") will
  get a new id then. This spec's tests pin today's id; I-33 updates them.

### Open questions for the tech lead (iteration 6 PLAN) — answered in iteration 6 REFINE

- **Q1: where the body ends.** The round-trip nodes do not carry end
  marks. One option: compose the same text once more
  (`ruamel.yaml.YAML().compose(text)`; no second file read) and take each
  item node's `end_mark` and each block scalar's extent from it. The
  architect confirms or names another; "next item's start − 1" stays
  ruled out. **Answered below (architect).**
- **Q2: the dash column `c`.** `Check.location` is the content column,
  not the dash's (see the table above). Take `c` from the item line's
  text or the sequence node; do not change `location`. **Answered below
  (architect).**
- **Q3: `CodeBlock` gets a line-numbered, non-wrapping variant** (P4,
  P16) or the Source section gets its own block beside it; ui-engineer's
  call. `textContent` must equal `text`, so the newlines between line
  elements stay in the DOM. **Answered below (ui-engineer).**

### Architect's answers to Q1 and Q2 (iteration 6 REFINE; verified by running `compose`) — the shape to build

- **A second `compose` of the same text, but not the item node's
  `end_mark`.** A block-mapping item's `end_mark` runs to the next dash or
  key, past trailing comments: "next start − 1" again. What is exact:
  scalar end marks (quoted and multi-line plain included), flow
  collections' end marks, and a block scalar's extent (`start_mark.line`
  to `end_mark.line`, exclusive when the end column is 0; it includes the
  scalar's trailing blank lines, and a `#` line inside it is content).
  `lc` alone cannot do it (start marks only; `LiteralScalarString` has no
  extent).
- **Where it lives.** `YAMLSource.text` is set in `load()`; the composed
  root is computed once per file, after a clean load. A private pure
  function in `config/`, `_check_span(lines, root: MappingNode, index)
  -> SourceSpan | None`, is called per check (so Y14 can patch it).
- **Body end** = the greatest end line over the item's subtree: scalars
  and flow collections by their end mark; block collections recursed;
  a block scalar's last non-blank line inside its extent.
- **Rule 3** walks up from the dash through comment-only lines, and stops
  at the line below the `checks:` key and at the previous item's end
  (its body plus its rule-2 comments, by the same helper).
- **Rule 4 and the extent invariant** are one guard: the extents of every
  top-level key other than `checks` (key line through value end); any
  overlap makes the span unavailable, and rule 2 also stops at a later
  key. Y17: `one.yml` unavailable, `two.yml` line 2.
- **Q2: `c`** comes from the sequence node, `seq_node.start_mark.column`;
  `seq_node.flow_style` picks block or flow. Not from the item, and
  `Check.location` is left alone.
- **Guards (all "span unavailable", none a diagnostic):** the line rule
  and post-condition (security B1); the extent invariant (B2); in the
  loader, `try/except Exception` around span capture, only for checks
  that already loaded, never touching `derive_check_id`. If `compose`
  fails for a file, every check in it has `span=None`, with no diagnostic
  and nothing logged above `debug` (architect F4).
- Identity: `SourceSpan` stays out of anything hashed.

### SourceBlock (ui-engineer's answer to Q3, iteration 6 REFINE)

- A new `frontend/src/components/SourceBlock.tsx`. `CodeBlock` is left as
  it is (documented soft-wrap, no numbers). `SourceBlock` reuses
  `.code-block`, `Marked`, `CopyButton` and the region pattern, with a new
  `.code-block--lines` modifier.
- One `<span class="line" data-line={start + i}>` per line, blank lines
  included; a `\n` inside every span but the last, so the `<code>`'s
  `textContent === text` exactly. Numbers from
  `.line::before { content: attr(data-line) }`, their width from
  `end_line`'s digit count through a CSS custom property. `min-width: 0`
  down the container chain; no `<details>`.

### Other iteration 6 REFINE decisions

- **Size cap on a span (security F4): none; a known limit.** The loader
  already reads and holds each check file whole, and `text` is at most
  that file; the files are the project's own. A cap would be an untested
  branch guarding nothing new. Recorded here; revisit if check files are
  ever fetched from elsewhere.
- **QA focus (security F5), in addition to "Reviewers required":** a
  multi-line quoted scalar whose continuation line starts with `#` (it is
  content, not a comment); `|+` keep-chomping, whose trailing blank lines
  are content (the body still ends at the last non-blank line; say so if
  that is wrong); a comment between `-` and its mapping on the next line
  (`- # note` then `    row_count:`); architect F2's alias case (Y19);
  Y18's characters. Each: the span is right or unavailable, never another
  line.
- **Pre-existing, not in this PR, now in the backlog:** I-36 (a control
  character in a check file gives a traceback, not a diagnostic: rule 5
  is broken today, architect F3); I-37 (`checks_path` is not validated:
  `../shared` gives paths starting `../`, an absolute path raises at
  load, security F2). `/source` serves whatever `path` the loader has;
  I-37 is what makes it always project-relative.

### Iteration 6 PLAN re-check (against `8687ebc`)

- Loader run on `retail`, `commented`, and the Y9, Y12, Y13, Y15 and Y17
  variants (`load_project` and `tablewatch validate`, all no problems);
  every id and start line in this spec is from those runs.
- **Corrected:** Y15's id (the path feeds the id). **Added:** the
  flow-style-sharing-a-line rule and Y17 (a real R6 leak in the draft);
  P16 (the Source block cannot reuse `CodeBlock` as is: it soft-wraps
  and has no line numbers); concrete fixtures for Y12, Y13 and P14; the
  interim text X3 replaces; Q1–Q3.
- **Unchanged:** the contract, the architect's shape, D2 rules 1–4, the
  `filter` decision, every scenario's expected lines.
- Spec 005's parts this reuses exist on `main`: `components/check/`
  (`SqlSection` is the model for P6/P7/P11), `CodeBlock`, `CopyButton`,
  `Marked`, `lib/clipboard.ts`, `lib/invisible.ts`, `Ago`, the `#sql`
  scroll in `CheckPage.tsx`, the golden `tests/golden/retail-list.txt`,
  and the `filtered` and `remote` fixtures in `tests/test_check_sql.py`.
- **User docs in this PR** (data-steward): the README's `/source` row,
  the check page's Source section, the X3 warning text, and the symlink
  sentence (Y16).

### Brief for the security-reviewer (this spec's REFINE)

1. R6 as written into Y6, including the flow-style exception, and Y17
   (a flow-style line shared with another key: span unavailable).
2. `CheckSource.filter`: a value from the same file, already served by
   `/sql`, served as its own field. Confirm or reject (see the decision
   above).
3. Symlinks (Y16) pending F3.
4. The full R3 warning replaces spec 005's interim text.

**Outcome (iteration 6 REFINE):** approved with follow-ups. B1 (line
splitting) and B2 (extent invariant) are in the contract, with Y18 and
Y19. Item 1: Y17's two cases confirmed. Item 2: `filter` confirmed on two
conditions, both taken (see the `filter` decision). Item 3: Y16 accepted
pending F3, with the path conditions added to Y16. Item 4: confirmed; a
test ties the README to the CLI string. F1 → X4; F2 → I-37; F3 → P14 is
`must`, with U+2028/2029, a BOM and control characters in file names;
F4 → no cap (Design notes); F5 → QA focus.

## Reviewers required

- **qa-engineer**: the span rule on awkward YAML (comments, blank lines
  inside an options map, flow style, block scalars, `#` lines inside a
  block scalar, CRLF, no final newline, tabs where YAML allows them,
  commented-out options), path-shaped ids; and the iteration 6 REFINE
  focus: Y18's line breaks, aliases (Y19), security F5's three cases
  (see "Other iteration 6 REFINE decisions").
- **data-steward**: D2 on real files, P4/P5/P13/P15 wording (written by
  the PM in iteration 6 REFINE; confirm or shorten), P4's shared flow
  line with no extra sentence, X4's README text, the hand run.
- **security-reviewer**: required (a new endpoint; the warning changes).
- **architect**: required (`config/loader.py`, `checks/model.py`, a new
  provisional public attribute).
- **ui-engineer**: builder of the Source section.

**REFINE round before BUILD (short): done** (iteration 6). security-
reviewer, architect and ui-engineer reported; every finding is decided
above. The data-steward's D2 rules and fixtures are unchanged; the
data-steward reviews at VERIFY.

## Size

**S, at its upper edge** (re-judged in iteration 6 REFINE). One loader
change with a pure span function (now with a line rule, a post-condition
and one extent guard: more tests, not more surfaces), one endpoint, one
new small `SourceBlock` beside spec 005's components, one line in
`lib/invisible.ts`, and README text. Nothing added is a new surface.

**Fallback split, if BUILD finds it past S:** flow-style spans become
always unavailable (A2's 200 with the path), Y8 is re-pinned to that,
and flow-style lines move to a new backlog item. Block style, the line
rule, the post-condition and the extent invariant stay: they are the
security bar, not scope.
