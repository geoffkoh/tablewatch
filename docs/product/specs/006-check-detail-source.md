# Spec 006: Check detail 3 (the check's own YAML source)

| | |
| --- | --- |
| Backlog item | I-29 (the Source half of I-26, split off in iteration 5 REFINE by the pre-planned split in spec 005) |
| Features | C4 (check detail): the source part. C4 is complete when this ships |
| Phase | 2 (`0.2.0`) |
| Size | S |
| Depends on | I-26 (spec 005: the `CheckPage` section split, `CodeBlock`, `CopyButton`, `lib/clipboard.ts`, invisible-character marking, the `useLoads` slot pattern for a check's sections) |
| Branch | `iter/006-check-detail-source` (to be created) |
| Status | **draft**: carried out of spec 005 with every iteration 5 REFINE decision on the Source half already made. The next PLAN re-checks it against `main` after spec 005 merges (line numbers, ids, component names) and sets it `ready`. The security-reviewer reviews it in that REFINE (brief below); the architect and ui-engineer confirm nothing moved |

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
- The span (D2, refined by the data-steward in iteration 5 REFINE). Lines
  are the file's lines as loaded (`\r\n` and `\n` both end a line). For a
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

## Architect's shape (iteration 5 REFINE, Q2)

- The file's lines once per dataset: `Dataset.source_lines: tuple[str, ...]
  = field(default=(), repr=False)` (`repr=False` is required, I-18).
- `Check.span: SourceSpan | None` (frozen, 1-based inclusive, in
  `checks/model.py`), computed at load time by a private pure function in
  `config/`; any failure gives `span=None` and no diagnostic.
- The text comes from the same read `YAMLSource` already does (no second
  read); `splitlines` handles CRLF.
- Do not use ruamel's comment attachment; do not use "next item's start
  − 1" (it fails when `checks:` is not the last key). Block-scalar extents
  come from the parse (D2 rule 1).
- `Check.location` does not change; `derive_check_id` takes explicit
  arguments and is not touched. Both attributes are provisional public
  API, as `expectation` is.

## Acceptance scenarios

**Fixtures:** `retail`, `recorded`, `edited-pending` (spec 004), `remote`
(spec 005), and **`commented`**: `retail` with `checks/sales/orders.yml`
replaced by the file in Y4, plus `checks/sales/returns.yml` (Y10),
`checks/flow.yml` and `checks/flowmulti.yml` (Y8). `tablewatch validate`
on it: `6 datasets, 18 checks — no problems found` (data-steward,
iteration 5 REFINE; PLAN re-confirms).

Check ids and spans (iteration 5, against `main`; PLAN re-confirms):

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
- And given a check file with `filter: status != 'test'` and a
  `sql_metric` check, that check's `filter.applies` is false, and a
  `schema` check's is false too

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
- And a variant whose last `query:` content line starts with `#` keeps
  that line (it is SQL text, not a YAML comment)

**Y14: span unavailable** `must` (architect A2)
- Given the span function patched to raise for one check
- Then `/source` for it answers 200 with `path` set and `start_line`,
  `end_line`, `text` null; `tablewatch validate` reports no new
  diagnostic; every other check's `/source` is unaffected

**Y15: a configured checks directory** `should` (architect A3)
- Given `retail` with its checks moved to `rules/` and `checks_path:
  rules` in `tablewatch.yml`
- Then Y1's `path` is `"rules/sales/customers.yml"`

**Y16: symlinked check files are served under the link's path** `must`
(documents today's behaviour; F3 is a pending owner question)
- Given a check file in `checks/` that is a symlink to a file outside the
  project
- Then its checks load (as today) and `/source` serves its lines under
  the link's path. The README says so plainly.

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

### The page (ui-engineer, vitest; data-steward by hand)

**P4: the Source section** `must`
- Given `/checks/32867fbe86f483f3`
- Then a section headed "Source" (open, no `<details>`) shows
  `checks/sales/orders.yml`, lines 5–8 with line numbers drawn by CSS
  (`::before { content: attr(data-line) }`) so they are never copied, and
  the YAML verbatim: no wrapping, horizontal scroll inside the block
- The code element's `textContent` equals `text` exactly (the jsdom
  stand-in for "selecting the code does not select the numbers"; real
  selection is checked by hand)
- Caption, exactly: "`checks/sales/orders.yml`, lines 5–8, from the check
  files loaded 2 hours ago", where "2 hours ago" is the header's `Ago`
  component, rendered as `<time dateTime="{loaded_at}">`

**P5: the source is today's, the result may not be** `must`
- Given `edited-pending`, the Source section shows
  `missing_percent(email) < 25%` and its "as loaded" time; spec 005's
  wording guard passes on it

**P6: no longer loaded** `must`: as spec 005's P6, for the Source section
("The source is not available: this check is not in the loaded check
files.").

**P7: one failure stays in its section** `must`: as spec 005's P7, for
`/source`.

**P8: text is text** `must`: a comment containing
`<script>alert(1)</script>` appears literally.

**P9: copy** `should`: "Copy the source" copies `text` exactly, with spec
005's clipboard rules and Select-all fallback.

**P11: `#source`** `should`: scrolls to the section once the first round
of loads settles; the identity panel's "Source" row links to `#source`.

**P13: what the source does not show** `must`
- Given `/checks/4a831091035ca6c6` on `commented`
- Then below the lines: "Only rows matching this file's
  `filter: status != 'test'` (line 3) are checked." As text, not a code
  block, whether or not `/sql` compiled
- For a `sql_metric` check in a filtered file: "This file's `filter:`
  (line 3) does not apply to this check: its query runs exactly as
  written."
- On every check (`should`): "The dataset, datasource, owner and tags
  shown at the top of the page come from this file's first lines or a
  `_defaults.yml`."

**P14: invisible characters** `should` (security R5): as spec 005's P14,
for the Source block and the path.

**P15: span unavailable** `must`: given Y14's response, the section shows
"The lines of this check could not be shown; it is in `<path>`."

## Non-goals

- `_defaults.yml`, `dataset:`, `datasource:` and file-level `tags:` are
  never part of `text`; `_defaults.yml` is never read for display. The
  `filter:` is served only as its own field.
- No editing, no "open in editor" or repository links.
- No refusal of symlinked check files (F3, pending owner decision).
- No syntax highlighting.

## Design notes

- Rule 5: span capture is part of the load pass; failure is `span=None`,
  never a diagnostic or exception.
- Rule 6: `/source` never touches a datasource.
- Check identity is untouched (I1).

### Brief for the security-reviewer (this spec's REFINE)

1. R6 as written into Y6, including the flow-style exception.
2. `CheckSource.filter`: a value from the same file, already served by
   `/sql`, served as its own field. Confirm or reject (see the decision
   above).
3. Symlinks (Y16) pending F3.
4. The full R3 warning replaces spec 005's interim text.

## Reviewers required

- **qa-engineer**: the span rule on awkward YAML (comments, blank lines
  inside an options map, flow style, block scalars, `#` lines inside a
  block scalar, CRLF, no final newline, tabs where YAML allows them,
  commented-out options), path-shaped ids.
- **data-steward**: D2 on real files, P4/P13 wording, the hand run, the
  README.
- **security-reviewer**: required (a new endpoint; the warning changes).
- **architect**: required (`config/loader.py`, `checks/model.py`, a new
  provisional public attribute).
- **ui-engineer**: builder of the Source section.

## Size

**S.** One loader change with a pure span function, one endpoint, one
section reusing spec 005's components.
