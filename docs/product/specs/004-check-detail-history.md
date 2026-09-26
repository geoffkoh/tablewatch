# Spec 004: Check detail page (the rule, the latest result, the history chart)

| | |
| --- | --- |
| Backlog item | I-05 (split in this PLAN: this spec is its first half; the compiled SQL and the check's source are I-26) |
| Features | C4 (check detail), without its SQL and source parts |
| Phase | 2 (`0.2.0`) |
| Size | M |
| Depends on | I-03 ✓ (spec 003: the UI shell, `latest.since`, `last_evaluated`, generated types) |
| Unblocks | I-26 check detail 2 (compiled SQL and source); I-04 and I-15 link to this page |
| Branch | `iter/004-check-detail-history` |
| Status | planned (iteration 4 PLAN) |

## Problem and persona

**Sam, data steward.** "The overview tells me `missing_percent(email) <
5%` has been failing for a week. Is that 6% or 60%? Was it getting worse
before it crossed the line? Did someone loosen the threshold last month?
I click the row and nothing happens."

**Dana, data engineer.** "When Sam asks why a check is red, I run
`tablewatch history b1ceb8262d8b5441` and read a column of numbers to her
over chat. I want to send her a link."

**Alex, analytics lead.** "Before I trust a table I want to see whether
its checks have been steady or noisy, not only today's colour."

**How they cope today.** The overview (iteration 3) shows each check's
latest value, its age, and "failing since". Anything more needs Dana at
a terminal: `tablewatch history <id>` prints the values, or someone reads
`/api/v1/checks/{id}/history` as JSON. Neither shows the values against
the threshold, and neither makes a rule change under an explicit `id:`
visible. The history carries `expression` for each entry, but only as a
string among other strings.

### How others do it

- **Soda's metric monitor page** puts a plot of the metric over time
  above a table of every scan result. "The plot is aligned with the table,
  so each data point in the plot directly corresponds to a result in the
  table." The expected range is a shaded band. Scans that collected no
  metric are shown as missing, not as zero. Configuration changes
  (thresholds, sensitivity) get visual markers on the timeline.
  ([Soda: metric monitor page](https://docs.soda.io/soda-v4/data-observability/metric-monitor-page))
  We borrow the plot-over-table layout, the band, the missing-value
  treatment and the rule-change marker. We do not borrow the range slider
  or drag-to-zoom (non-goal), or the anomaly band (G1, Phase 5).
- **Elementary's test details** show each test's pass and fail history,
  its fail rate, and the exact compiled query.
  ([Elementary](https://github.com/elementary-data/elementary);
  [Elementary: dbt observability 101](https://www.elementary-data.com/post/dbt-observability-101-how-to-monitor-dbt-run-and-test-results))
  The compiled query is our I-26. We ship the history first because
  Sam's question comes before Dana's.
- **Accessible SVG charts.** The reliable pattern is `<svg role="img">`
  with `aria-labelledby` pointing at a `<title>` and a `<desc>`. A complex
  chart needs a short text summary plus a long alternative, and for a
  line chart that is a data table.
  ([Léonie Watson: accessible SVG line graphs](https://tink.uk/accessible-svg-line-graphs/);
  [Deque: creating accessible SVGs](https://www.deque.com/blog/creating-accessible-svgs/))
  The history table under the chart is that data table. Scenario D11
  holds us to the pattern.

## Outcome

After this ships, every check name on the overview is a link. Sam clicks
`missing_percent(email) < 5%` and gets `/checks/b1ceb8262d8b5441`, a page
that shows:

- **what the check is**: its name, expression, dataset, datasource,
  owner, tags, `file:line:col` and full id;
- **its rule in words**, from a new structured `rule` on the API:
  "Expected < 5%", or "Warn when > 1d · Fail when > 7d";
- **its latest result**, in exactly the overview's words: the value, the
  message, the age, "Failing since …", and for an error "Could not
  evaluate" with "Last evaluated: Fail";
- **a chart of its recorded values over time** against the current rule's
  threshold: the failing region shaded, each result marked by its recorded
  outcome in shape and colour, errors and missing values in their own
  lane instead of plotted as zero, and a marker where the rule changed
  under an explicit `id:`;
- **the history as a table** under the chart: one row per result, newest
  first. It is also the chart's accessible alternative.

The link can be pasted, reloaded and bookmarked. The page has the
overview's header and a Refresh button. The two pages share one
load/refresh hook, so they behave the same when the store is down.

The API gains one additive field, `rule`, on `GET /api/v1/checks/{id}`,
and (REFINE, R7) `metric` and `dataset` on each history entry, read from
columns the store already has. No new endpoint, no new dependency, no
migration, and no chart library.

## Scope at a glance

| Part | Who builds it | Where |
| --- | --- | --- |
| `rule` on the check (R1–R6), `metric`/`dataset` on history entries (R7), OpenAPI regenerated | tech lead | `server/schemas.py`, `server/routes.py`, `docs/api/openapi.json` |
| Types regenerated; shared load/refresh hook (D14); shared status wording (D4) | ui-engineer | `frontend/src/api/`, `frontend/src/lib/` |
| Detail page, chart, history table, links from the overview (D1–D19) | ui-engineer | `frontend/**`, `docs/UI_SPECIFICATION.md`, the bundle |
| README: "Reading a check's page" | data-steward | `README.md` |

**Order inside BUILD.** R1–R6 first, then `openapi.json` is regenerated,
then the ui-engineer regenerates types (K3 from spec 003 enforces the
chain). **The tech lead loads the dataviz skill** before briefing the
ui-engineer on the chart and again in VERIFY. The subagents do not have
the skill, so the chart requirements are written out in full below.

## The contract change (additive)

### `rule` on `GET /api/v1/checks/{id}`

```text
Rule      { expect: Condition | null, warn: Condition | null, fail: Condition | null }
Condition = { kind: "compare", op: "=" | "!=" | "<" | "<=" | ">" | ">=", value: number, text: string }
          | { kind: "between", low: number, high: number, negated: boolean, text: string }
```

- Exactly one of these holds: `expect` is set and `warn` and `fail` are
  null, or `expect` is null and at least one of `warn` and `fail` is set.
  This is the check's `expectation` / `warn` / `fail` as loaded (see
  `checks/model.py`).
- **Numbers are magnitudes on the scale of the recorded `value`.** A
  percent threshold `5%` is `5.0`, because `value` for 20% is `20.0`. A
  duration `6h` is `21600.0` seconds, because freshness `value` is in
  seconds. A client can draw a boundary and a value on the same axis
  without knowing the DSL. (`Number.magnitude` and `Duration.magnitude`
  already give this.)
- `text` is the condition as the DSL renders it (`str(condition)`):
  `"< 5%"`, `"> 1d"`, `"between 10 and 500"`, `"not between 5 and 10"`.
  The UI shows this text and never builds it from the numbers.
- Checks whose expression has no condition (`schema`, `failed_rows`) have
  the implied `expect` the engine evaluates: `= 0`.
- `rule` describes the check **as loaded by this server** (`loaded_at`).
  It is not historical. Past rules are only available as the recorded
  `expression` text on each history entry.

`GET /api/v1/checks` is unchanged unless the architect decides otherwise
(Q1). The API version stays `v1`.

### `metric` (and `dataset`) on each history entry *(REFINE)*

`HistoryEntry` gains `metric: string`, and should gain `dataset: string`,
both as recorded in that run, read from columns the store already has
(R7). Additive; no migration. Without it the chart cannot keep a value
measured by another metric off today's axis (D20).

## Acceptance scenarios

**Fixtures** (spec 002 and 003; `tests/conftest.py`):

- `retail`: a copy of `examples/retail` with its database built, 3
  datasets and 18 checks.
- `recorded`: `retail` after **run A** (`tablewatch run`) and **run B**
  (`tablewatch run checks/sales`).
- `interrupted`: `recorded` plus **run E** (`retail.duckdb` moved aside,
  `tablewatch run checks/sales/customers.yml`, 5 errors) and **run F**
  (`tablewatch run`).
- **`edited`** (new; the same steps as spec 003 P6): `retail` with
  `id: customer-email-completeness` added to the `missing_percent(email)
  < 5%` check in `checks/sales/customers.yml`, then `tablewatch run` (run
  A: `fail`, value `20.0`), then the expression changed to
  `missing_percent(email) < 15%`, then `tablewatch run` (run C: `fail`,
  value `20.0`).
- **`edited-pending`** *(REFINE)*: `edited`, then the expression changed
  to `missing_percent(email) < 25%` and the server restarted, with **no
  run**. The current rule has judged nothing yet. The latest result (C,
  `fail`, 20.0, message `expected < 15%`) would pass the current rule.
- **`metric-changed`** *(REFINE)*: `edited`, then the expression changed to
  `missing_count(email) = 0` and `tablewatch run checks/sales/customers.yml`
  (run M: `fail`, value `1`, message `expected = 0`). The data-steward
  reproduced this on 2026-09-26: `tablewatch history
  customer-email-completeness` lists M `1`, C `20.00%`, A `20.00%` under
  one id.

Check ids used below. The PM confirmed these on `main` on 2026-09-26
with `tablewatch.load()` on a scratch copy of `examples/retail`
(`[(c.id, c.canonical, c.expectation, c.warn, c.fail) for c in
p.checks]`):

| id | dataset | expression | unit |
| --- | --- | --- | --- |
| `b1ceb8262d8b5441` | sales.customers | `missing_percent(email) < 5%` | percent |
| `32c8f939b90f6367` | sales.customers | `row_count > 0` | count |
| `41e58afff9c48a46` | inventory.products | `freshness(updated_at) \| warn when > 1d \| fail when > 7d` (name "Price feed freshness") | duration |
| `32867fbe86f483f3` | sales.orders | `row_count \| warn when < 100 \| fail when = 0` (name "Order volume") | count |
| `366d9254d889c910` | sales.orders | `avg(amount) between 10 and 500` | number |
| `cd3e8103b4318809` | inventory.products | `row_count between 1 and 10000` | count |
| `a81b0374b0b04f06` | sales.orders | `freshness(created_at) < 6h` | duration |
| `fbc3aa0b93b66eee` | sales.orders | `schema` | count |
| `ed669ca6e5532a59` | sales.orders | `failed_rows` (name "No negative amounts") | count |

In `interrupted`, `/checks/b1ceb8262d8b5441/history` is, newest first:
F `fail` 20.0, E `error` (value null, message `IO Error: Cannot open
database …`), B `fail` 20.0, A `fail` 20.0. `32c8f939b90f6367` is F
`pass` 5, E `error`, B `pass` 5, A `pass` 5.

Freshness values depend on when the database was built. Do not assert
them.

Frontend scenarios (D*) are vitest tests. Their API responses are
fixtures typed against the **generated** types, as in spec 003. Pure
functions (bands, domain, ticks, summary) are tested with the tables
below. The data-steward also runs D1–D7, D12 and D15 by hand against a
real `serve` on `recorded`, `interrupted` and `edited` in VERIFY.

### The `rule` field (tech lead, pytest)

**R1: an expectation** `must`
- Given `recorded`
- When `GET /api/v1/checks/b1ceb8262d8b5441`
- Then the body has every field it had in spec 003, unchanged, plus
  `"rule": {"expect": {"kind": "compare", "op": "<", "value": 5.0,
  "text": "< 5%"}, "warn": null, "fail": null}`.
- And `latest.value == 20.0`, so the boundary and the value share a
  scale.
- *(REFINE, `should`)* And given `- missing_percent(email) < 5` (no `%`,
  which the loader accepts on a percent metric), `rule.expect.value ==
  5.0` and `text == "< 5"`. The UI shows `< 5` and does not add a `%`.
  Given `< 0.05`, `value == 0.05`, not `5.0`: a bare number on a percent
  metric is already on the 0–100 scale (Q3, answered below).

**R2: triggers** `must`
- When `GET /api/v1/checks/41e58afff9c48a46`
- Then `rule == {"expect": null, "warn": {"kind": "compare", "op": ">",
  "value": 86400.0, "text": "> 1d"}, "fail": {"kind": "compare", "op":
  ">", "value": 604800.0, "text": "> 7d"}}`.
- And for `32867fbe86f483f3`, `rule.warn` is `<` `100.0` (`"< 100"`) and
  `rule.fail` is `=` `0.0` (`"= 0"`).
- And for `a81b0374b0b04f06`, `rule.expect` is `<` `21600.0` (`"< 6h"`).
- *(REFINE, `should`)* And a fractional duration `< 1.5h` is `5400.0`
  with `text` `"< 1.5h"`.

**R3: between** `must`
- Then `366d9254d889c910` has `rule.expect == {"kind": "between", "low":
  10.0, "high": 500.0, "negated": false, "text": "between 10 and 500"}`.
- And given a check file with `- row_count not between 5 and 10`, its
  `rule.expect` has `"negated": true` and `"text": "not between 5 and
  10"`.
- *(REFINE, `should`)* And negative bounds keep their sign:
  `min(amount) not between -1 and 1` has `low == -1.0`, `high == 1.0`.
  `between 5 and 5` (allowed; the loader rejects only low > high) has
  `low == high == 5.0`.

**R4: the implied expectation** `must`
- Then `fbc3aa0b93b66eee` (`schema`) and `ed669ca6e5532a59`
  (`failed_rows`) each have `rule.expect == {"kind": "compare", "op":
  "=", "value": 0.0, "text": "= 0"}` and null `warn` and `fail`, although
  their `expression` has no condition.
- *(REFINE, `must`)* And the implied `= 0` applies only when the check has
  no triggers, as the loader does. Given `- failed_rows:` with `warn: when
  > 0` and `fail: when > 10` (and its `sql:`), `rule.expect` is null,
  `rule.warn.text == "> 0"` and `rule.fail.text == "> 10"`. The API must
  not add an `expect` the engine does not evaluate.

**R5: `rule` is the loaded rule, not history** `must`
- Given `edited`
- When `GET /api/v1/checks/customer-email-completeness`
- Then `rule.expect.value == 15.0` and `rule.expect.text == "< 15%"`.
- And `/checks/customer-email-completeness/history` lists C then A, with
  `expression` `missing_percent(email) < 15%` and then
  `missing_percent(email) < 5%` (already true since spec 003; asserted
  here because D7 depends on it).

**R6: the contract is documented** `must`
- `components.schemas` in `/api/v1/openapi.json` has `Rule` and the two
  condition shapes, with `kind` as the discriminator and every field
  required. The checked-in `docs/api/openapi.json` matches it (the
  existing drift test), and the regenerated TypeScript types match it
  (spec 003 K3).
- And every spec 002 and 003 scenario for `/checks/{id}` still passes.
  The change is additive.

**R7: each history entry says what it measured** `must` *(REFINE)*
- Given `metric-changed`
- When `GET /api/v1/checks/customer-email-completeness/history`
- Then each entry carries `metric` as recorded in that run: `missing_count`
  for M, `missing_percent` for C and A. The store already has this column
  (`tablewatch_check_results.metric`), so this needs no model change and no
  migration. It is additive, in `openapi.json` and the generated types.
- *Why:* an explicit `id:` can outlive a change of metric. The history
  then mixes a count (`1`) with percentages (`20.0`), and a chart on
  today's axis would draw the count as "1%". The page must be able to tell
  which values are on today's scale without parsing `expression` (a second
  copy of the DSL). The unit follows from the metric, because every metric
  has one fixed unit.
- *(`should`)* And each entry carries `dataset` as recorded, so a check
  moved to another dataset under the same `id:` is visible (D20).

### The page (ui-engineer, vitest; data-steward by hand)

Wording in quotation marks is asserted. Other labels give the meaning
required; the exact words, layout and styling are the ui-engineer's,
recorded in `docs/UI_SPECIFICATION.md`.

**D1: every check has a link, and the link survives a reload** `must`
- Given the overview on `recorded`
- Then each check's name is a link (`<a href>`) to
  `/checks/<id>`, with the id URL-encoded: `/checks/b1ceb8262d8b5441`,
  `/checks/customer-email-completeness`.
- And `GET /checks/b1ceb8262d8b5441` from the server returns `index.html`
  (spec 003 W3, unchanged), and the app renders the detail page for that
  path. It no longer renders "page not found".
- And `/checks/b1ceb8262d8b5441/` (trailing slash) renders the same page.
  `/checks/` and `/checks/a/b` render "page not found".
- And the detail page has a link back to the overview.

**D2: what the check is** `must`
- Given `recorded`, on `/checks/b1ceb8262d8b5441`
- Then the page shows the name (`missing_percent(email) < 5%`), the
  dataset `sales.customers`, the datasource `lake`, the owner
  `sales-data@example.com`, the tags `example`, `sales`, `tier-1`, the
  source `checks/sales/customers.yml:6:5`, and the full id
  `b1ceb8262d8b5441`.
- And for `32867fbe86f483f3` the page shows the name "Order volume" and,
  separately, the expression.
- And the document title names the check (for example "Order volume ·
  tablewatch"), so browser tabs and history are readable. *(`should`)*

**D3: the rule in words** `must`
- Then `b1ceb8262d8b5441` shows "Expected" with `< 5%`.
- And `41e58afff9c48a46` shows "Warn when" with `> 1d` and "Fail when"
  with `> 7d`.
- And `fbc3aa0b93b66eee` shows "Expected" with `= 0`.
- And the condition text on the page is always `rule.*.text`. The
  frontend never formats a threshold number itself (a test renders a rule
  whose `text` differs from its numbers and asserts the `text` is shown).
- And the page says that the rule is the one in the check files as
  loaded, with the age of `loaded_at` ("check files loaded 3 hours
  ago"). *(`should`)*

**D4: the latest result in the overview's words** `must`
- Given A, B, E (`interrupted` before F), on `/checks/b1ceb8262d8b5441`
- Then the latest result reads "Could not evaluate" with the message,
  "Last evaluated: Fail", and a "failing since" age from run A. It never
  says "Failing since" for the error itself, and it does not show
  `display_value` (`"—"`) as a value.
- And given `interrupted`, it reads `20.00%`, `expected < 5%`, and
  "Failing since" with run A's age.
- And the status label, icon and "since" wording come from the **same
  code** as the overview's rows. `SINCE_PREFIX` and the result/last-
  evaluated rendering move out of `CheckTable.tsx` into a shared module,
  and both pages import it. A second copy of the wording is a failed
  scenario, even if its words match today.
- And "Not in the latest run" appears when `latest.run_id` is not the
  newest run's id, as on the overview. *(`should`)*
- *(REFINE, `must`)* And given `edited-pending`, the rule reads "Expected
  < 25%", and the latest result (`20.00%`, `fail`) says it was judged by
  an earlier rule and names that rule's recorded expression
  (`missing_percent(email) < 15%`). The page knows this because the first
  history entry's `expression` differs from the check's `expression`.
  Without the note, Sam sees "Expected < 25%" beside a red 20.00% and
  concludes that tablewatch is wrong. The rule section also says that no
  run has used the current rule yet.

**D5: the chart plots recorded values and marks recorded outcomes** `must`
- Given `interrupted`, on `/checks/b1ceb8262d8b5441`
- Then the chart has 3 value marks (A, B, F, each at 20.0, each marked
  `fail`) and 1 mark for E in a separate lane labelled "No value" (REFINE:
  was "Could not evaluate"). E's mark has the `error` shape, and the legend
  names it "Could not evaluate". E is **not** plotted at 0 or at any
  value. The lane gets a neutral name because a `fail` with no value (D9)
  also sits in it, and a `fail` under a "Could not evaluate" label would
  say the opposite of what happened.
- And the line joining consecutive values **breaks** at E. There is a
  segment from A to B and none from B to F. A line through E would draw
  a value nobody measured.
- And given `interrupted`, `32c8f939b90f6367` has 3 marks at 5, each
  marked `pass`, and 1 error mark.
- And the x-axis is time (`started_at`), not run index. Runs happen at
  irregular intervals, and the gap between them is information.
- And given a check with one result, the chart shows one mark and no
  line. Given two results with the same `started_at`, both are drawn in
  history order and neither is dropped. *(`should`)*

**D6: the threshold band** `must`
- The failing region of the **current** rule is shaded in the fail colour,
  and the warning region in the warn colour. Each boundary is drawn as a
  line labelled with its `text`. The regions come from one pure function
  of (rule, y-domain), tested with this table:

  | rule | y-domain | fail region(s) | warn region(s) | lines at |
  | --- | --- | --- | --- | --- |
  | expect `< 5` | [0, 25] | [5, 25] | — | 5 |
  | expect `> 0` | [0, 10] | — (zero height) | — | 0 |
  | expect `between 10 and 500` | [0, 600] | [0, 10), (500, 600] | — | 10, 500 |
  | expect `not between 5 and 10` | [0, 20] | [5, 10] | — | 5, 10 |
  | expect `= 0` | [0, 3] | (0, 3] | — | 0 |
  | expect `= 0` | [-2, 3] | [-2, 0), (0, 3] | — | 0 |
  | expect `!= 0` | [0, 3] | — (a single value) | — | 0 |
  | expect `between 5 and 5` | [0, 10] | [0, 5), (5, 10] | — | 5 |
  | warn `< 100`, fail `= 0` | [0, 120] | — (a single value) | [0, 100) | 0, 100 |
  | fail `!= 0` | [0, 3] | (0, 3] | — | 0 |
  | warn `> 86400`, fail `> 604800` | [0, 700000] | (604800, 700000] | (86400, 604800] | 86400, 604800 |

  A fail region is drawn over a warn region where they overlap. **The
  rule (REFINE):** shade every failing (or warning) interval that has
  height in the domain. When the failing set is a single value (`expect
  != v`, `fail when = v`), draw only its line, in the fail colour. When it
  is everything but one value (`expect = v`, `fail when != v`), shade both
  sides of the line. *Why:* `= 0` is the most common rule there is (8 of
  the 18 retail checks, including `schema` and `failed_rows`). Left
  unshaded, a failing `invalid_count(country) = 0` at 1 sits in white
  space, and on this chart white means passing.
- *(REFINE, `must`)* And given `recorded`, `000f8d0048744bfb`
  (`invalid_count(country) = 0`, `fail`, 1) has its mark at 1 inside a
  shaded fail region, with the `= 0` line at 0.
- And given `interrupted`, `b1ceb8262d8b5441`'s chart shows the region
  from 5 upward shaded, a line labelled `< 5%` at 5, and the marks at 20
  inside the region.
- And the rule's text is visible on or next to the chart even when a
  boundary lies outside the plotted range (D10).

**D7: a rule change under an explicit id** `must`
- Given `edited`, on `/checks/customer-email-completeness`
- Then the chart has one rule-change marker at a time between A and C,
  labelled with both rules: from `missing_percent(email) < 5%` to
  `missing_percent(email) < 15%` (the recorded `expression` strings).
- And the band and the boundary line (`< 15%`, at 15) cover only the
  span of the newest run of entries whose recorded `expression` equals
  the current check's `expression`, C here. A is drawn without a band.
  The page does not draw today's threshold over a period that was judged
  by another one.
- And the history table's row for A shows its recorded expression,
  marked as a different rule from the current one. Rows under the current
  rule do not repeat it.
- And a marker is placed wherever two consecutive entries (in history
  order) have different `expression` strings. A → B → A gives two
  markers. The band still covers only the newest segment.
- *(REFINE, `must`)* And given `edited-pending`, **no band and no boundary
  line are drawn anywhere**: no recorded entry was judged by `< 25%`. The
  rule's text (`< 25%`) is shown beside the chart with a note that no run
  has used it yet (D4). The newest marker's label reads from
  `missing_percent(email) < 5%` to `missing_percent(email) < 15%`. Nothing
  suggests a marker for the pending edit, because no run recorded it.
- *(REFINE, `should`)* And the marker label says the rule changed "between
  runs", not "at" a time. The history knows only the two runs either side
  of the edit, not when the file was edited.

**D8: marks follow the recorded outcome, never a recomputed one** `must`
- Given a history fixture with three entries under different rules
  (A: `pass` 20.0 with expression `missing_percent(email) < 25%`; B:
  `fail` 20.0 with `< 5%`; C: `fail` 20.0 with `< 15%`, the current rule)
- Then A's mark is `pass`, although 20 is inside today's failing region.
  The outcome comes from the entry. The frontend never evaluates a value
  against a rule.

**D9: a failure with no value** `must`
- Given an entry with `outcome: "fail"`, `value: null`, `display_value:
  "—"` and `message: "no value to evaluate"` (what the engine records for
  `avg(amount)` on an empty table)
- Then it is drawn as a `fail` mark in the no-value lane, labelled as
  having no value, and not plotted at 0. The table row shows the message.
- And the no-value lane is labelled so that a `fail` there reads
  differently from an `error` there: the first is bad data (an empty
  table), the second is tablewatch unable to evaluate.
- *(REFINE, `must`)* The asserted words: the lane is "No value". The
  legend and tooltip name a `fail` there "Fail: no value measured" and an
  `error` there "Could not evaluate". A second realistic source of the
  former is freshness on a table with no timestamps (`message: "no
  timestamps in scope"`), and it is tested with that message too.
- *(REFINE, `should`)* And a `skipped` entry (in the API's enum, although
  the engine does not produce it today) goes in the same lane with its
  own shape and the legend name "Skipped". It is never drawn as `error`
  or as `pass`.

**D10: the y-axis** `must`
- **Ticks are formatted by `unit`** by one pure function, tested with
  this table:

  | unit | value | tick |
  | --- | --- | --- |
  | percent | 20 | `20%` |
  | percent | 2.5 | `2.5%` |
  | count | 12000 | `12,000` |
  | duration | 21600 | `6h` |
  | duration | 86400 | `1d` |
  | duration | 90 | `1m 30s` |
  | duration | -25200 | `-7h` |
  | number | 54.3571 | `54.36` |
  | number | -1.5 | `-1.5` |

  Ticks are chosen at round values for the unit (for durations: seconds,
  minutes, hours, days). *Formatting ticks in the browser does not break
  rule 2 or I-24*: the value shown for a result (mark tooltip, table)
  is always `display_value` from Python. Only the axis labels are made
  here.
- **The domain** comes from one pure function of (values, rule
  boundaries). Tested cases:
  - values {20}, boundary 5 → both are inside the domain.
  - values {3}, boundaries 1 and 10000 (`cd3e8103b4318809` on
    `recorded`: 3 rows, run A only) → the domain contains 1 and 3 and
    leaves 10000 out, so the value is not squashed against the baseline.
    The chart shows the off-range boundary as text at the edge ("10,000
    above").
  - values {3, 4, 5, 3}, boundaries 1 and 10000 → the values span at
    least half the plot height, and 10000 is again off-range.
  - no values (every entry is an `error`), boundary 5 → the domain
    contains 5, and no line is drawn.
  - *(REFINE, `must`)* values {-25200, -21600} (freshness), boundary
    21600 → the domain contains the negative values and 0, and they are
    drawn below 0, never clamped to it. A negative freshness means the
    newest timestamp is in the future. That is usually a naive timestamp
    read in the wrong `timezone`, and it passes `< 6h` for ever. The chart
    is where Sam can see it, so it must not hide it.
  - *(REFINE, `must`)* values only from entries whose `metric` differs
    from the check's current `metric` (D20) → those values do not enter
    the domain.

  The exact rule for when a boundary is left off-range is the
  ui-engineer's, recorded in `docs/UI_SPECIFICATION.md`.
- The axis is titled with the metric and its unit, for example
  "missing_percent (%)", "freshness (age)", "row_count (rows)".
  *(`should`)*

**D11: the chart is accessible, in light and dark** `must`
- The chart is `<svg role="img" aria-labelledby="<title id> <desc
  id>">`. Its `<desc>` is a summary built by one pure function. For
  `interrupted` / `b1ceb8262d8b5441` it contains "4 results", "3 fail",
  "1 could not evaluate", the latest value `20.00%`, and the rule `< 5%`.
  It contains the dates of the first and last result.
- And the history table (D12) holds every plotted result, so the chart
  is never the only way to read a value. A test asserts that the table
  has one row per entry the chart draws.
- And **outcomes are never shown by colour alone**. Each outcome has its
  own mark shape, matching the status icons (`StatusIcon.tsx`), and a
  legend names every shape shown.
- And in both `prefers-color-scheme: light` and `dark`, marks, boundary
  lines and band edges have at least 3:1 contrast against the plot
  background (WCAG 1.4.11), and axis and label text at least 4.5:1. The
  existing `contrast.test.ts` is extended to the chart's tokens. A band
  fill may be lighter than 3:1 as long as its edge line is not.
- And pointer hover or keyboard focus on a mark shows its time (in the
  viewer's time zone, with the zone stated, as spec 003 O4), outcome,
  `display_value`, and the message if there is one. *(`should`; the
  table already carries all of it)*
- And the x-axis states the time zone its labels are in. *(REFINE:
  raised from `should` to `must`.)* Until I-24, the only UTC times on
  the page are inside stored messages (`newest 2026-09-26T11:33:48…+00:00`).
  Every time the page makes itself must name its zone, so a local axis
  label is never read as the same zone as the message beside it. See
  "REFINE: data-steward decisions" for the I-24 call.

**D12: the history table** `must`
- Given `interrupted`, on `/checks/b1ceb8262d8b5441`
- Then the table has 4 rows, newest first (F, E, B, A). Each row shows
  the age with a `<time datetime>` holding the API's UTC string, the
  outcome badge, `display_value` (except for `error`, where it shows
  "Could not evaluate" and the message), the message, and the trigger.
- And messages are shown **verbatim**. The page does not reformat the
  timestamp inside a freshness message (`newest 2026-09-23T12:23:02…`) or
  the bare `0` of a passing schema check. Those are I-24's, fixed in
  Python for every surface at once.
- *(REFINE, `must`)* And the value column is headed so that a
  freshness row reads as an age (for example "Value" holding `1h`), and
  it comes before the message. Sam reads the verdict from the value and
  not from the timestamp inside the message.
- *(REFINE, `should`)* And the table states the zone of its absolute
  times once, in a caption or header (for example "Times in GMT+8"),
  matching the axis.

**D13: long histories** `must`
- The page requests `/history?limit=200` once. The chart and the table
  show those entries.
- And when `next_cursor` is not null, the chart's caption says it shows
  the latest 200 results, not all of them.
- And a "Load older results" control fetches the next page with the
  cursor and adds it to both the chart and the table. *(`should`)*

**D14: one load/refresh hook for both pages** `must`
- The load and refresh logic in `Overview.tsx` (the generation counter
  that drops a late, older answer; the busy state; the once-a-minute
  clock tick) becomes one hook in `frontend/src/` used by both pages.
  Neither page keeps its own copy.
- And the overview's spec 003 tests (O9, O10 and the late-answer test)
  pass unchanged, or move to the hook's tests with the same assertions.
- And on the detail page, "Refresh" re-fetches `/project`,
  `/checks/{id}` and the first page of `/history`, and discards any
  older pages that were loaded.

**D15: failures and unknown checks** `must`
- Given `GET /api/v1/checks/{id}` answering 404 `not_found` (an id not in
  the loaded check files)
- Then the page says no check with that id is loaded, names the id as
  text, and links to the overview. It shows no chart, no empty table, and
  no status.
- And given 503 `store_unavailable` from `/checks/{id}` or `/history`,
  the page keeps its header and the check's identity (if `/checks/{id}`
  answered), shows the error's message with a retry, and draws no chart
  and no "no results" text that could pass for "nothing wrong" (as
  spec 003 O9).
- And given a check that is loaded but has **no history** (`latest:
  null`, for example `e41cf32f07f328c3` from spec 003 O3), the page shows
  its identity and rule, "No result recorded" in the overview's neutral
  style, and "No results recorded yet" where the chart would be. Nothing
  shows as passing.
- *(`should`)* And given an id whose check is not loaded but whose
  history exists (the old id `b1ceb8262d8b5441` after the expression is
  edited without an `id:`, as in spec 003 O3), the page says the check is
  no longer in the loaded files and still shows the history table and a
  chart without a band.
  *(REFINE)* With no loaded check there is no `unit`. The ticks are then
  plain numbers, the axis title says the unit is unknown, and values are
  plotted only if every entry has the same recorded `metric` (R7).
  Otherwise the page shows the table alone.

**D16: data renders as text** `must`
- Given a check named `<img src=x onerror=alert(1)>` and a history entry
  whose `message` is `<script>alert(1)</script>` and whose `expression`
  is `row_count > 0 <b>x</b>`
- Then each renders as literal text in the heading, the chart's `<title>`
  and `<desc>`, the rule-change label, any tooltip, and the table. No
  element is created from them, and no script runs.
- And the existing test (no `dangerouslySetInnerHTML`, `innerHTML` or
  `eval` in the frontend) still passes.

**D17: no new dependencies; the CSP holds** `must`
- `frontend/package.json` `dependencies` are still exactly `react` and
  `react-dom`. The chart is hand-written SVG in React. **Adding a chart,
  scale, date or router library fails this scenario unless the PR argues
  for it** (ui-engineer principle 6) and the security-reviewer accepts
  it. The scales this chart needs are two linear maps and a tick picker.
- And the served CSP (spec 003 decision 10) is unchanged. The chart uses
  classes and SVG presentation attributes from the stylesheet, not
  `<style>` elements. Spec 003's bundle checks (no inline script or style
  in `index.html`, no remote URLs, no `.map` files) pass.

**D18: the overview is otherwise unchanged** `must`
- Every spec 003 O-scenario still passes. D1 adds links, and the row's
  text and layout stay as they are.

**D19: the chart marks where the current streak began** `should`
- Given `interrupted`, `b1ceb8262d8b5441`'s chart marks run A's time as
  the start of the current streak (`latest.since`), with the overview's
  "Failing since" wording in its label. An `error` that was passed over
  (E) sits inside the marked span, and D5 still shows it.
- *(REFINE)* And given `edited`, the streak runs from A and so spans the
  rule-change marker (`latest.since` follows outcomes, not rules; spec
  003). Both stay visible, and neither label covers the other. "Failing
  since" together with a visible rule change is the honest reading: the
  check has been red throughout, under two thresholds.

**D20: a value measured by another metric is not plotted on today's axis** `must` *(REFINE)*
- Given `metric-changed` and the check file then changed back to
  `missing_percent(email) < 15%` and run again (run N: `fail`, `20.0`),
  on `/checks/customer-email-completeness`
- Then the chart plots N, C and A (`missing_percent`, on the percent
  axis) and does **not** plot M (`missing_count`, value 1). M does not
  enter the y-domain (D10), and the line breaks across it.
- And the chart's caption says that 1 result measured a different metric
  (`missing_count`) and is not plotted. The history table still lists M,
  with its `display_value` `1` and its recorded expression marked as a
  different rule (D7).
- And rule-change markers still sit at C → M and M → N.
- And the rule for what is plotted is "the entry's `metric` equals the
  check's current `metric`". It uses R7's field, not a parse of
  `expression`.
- *(`should`)* And a change of recorded `dataset` under one id (R7) gets
  a marker labelled with both dataset names, even when the expression is
  unchanged.

## Non-goals

- **No compiled SQL and no check source on the page.** They are I-26,
  next, with their own security review (see "What the split leaves").
- **No reformatting of values or messages in the browser.** The raw UTC
  timestamps in freshness messages and the bare `0` of a passing schema
  check are I-24's, fixed in Python across console, JSON, JUnit, the
  store and the page. Messages stored by earlier runs stay as recorded
  (I-24's own requirement), so this page will show some raw timestamps
  in any store with history, whichever ships first.
- **No bands for past rules.** Only the current rule is structured
  (`rule`). Drawing a past rule's band would mean parsing recorded
  `expression` strings, a second copy of the DSL. Past rules are shown as
  text at their change markers.
- **Changes the history cannot see are not marked.** Options
  (`valid_values`, `missing_values`) and `where:` are not recorded per
  result, so editing them under an explicit `id:` leaves no marker.
  Recording them would be a store change for a later item, if anyone
  asks.
- **No zoom, brush, range slider or time-range picker** (Soda has them).
  The chart shows what was loaded (D13).
- **No anomaly or expected-range bands** (G1, Phase 5).
- **No failed-row samples** (C7, Phase 2b).
- **No run detail page** (I-15). History rows do not link to runs yet.
- **No explorer, tree, search or filters** (I-04).
- **No automatic refresh** (as spec 003).
- **No change to `GET /api/v1/checks`** unless Q1 settles on it.
- **No change to the CLI**, the engine, the store or check identity.

## What the split leaves for I-26

**I-26, check detail 2: compiled SQL and the check's source.** Size S,
depends on I-05. It adds a read-only way to get the statement(s) that
answer a check and the check's own lines of YAML, and shows them on this
page. It carries iteration 3's I-05 requirement (a):

- **Security review is required.** New endpoints change what the server
  exposes over the network.
- Compiling stays credential-free (rule 6): `dialect_for`, never
  `create_engine_for`, as `tablewatch compile` does.
- No endpoint returns row data.
- The source endpoint serves **only the check's own lines from a file
  under `checks/`**. It never serves `tablewatch.yml`, which today can
  hold a literal store password (see I-14), and never builds a path from
  the request.
- The spec settles whether the SQL shown is the dataset's whole single
  scan (with this check's measures pointed out, which is honest about
  the cost) or only this check's measures. The PM leans to the former.

## Design notes

### Constraints from CLAUDE.md

- **Rule 2.** The page computes nothing about outcomes. Outcomes, values
  and `display_value` come from Python. The browser only maps numbers to
  pixels and formats axis ticks (D10). Streak starts come from
  `latest.since`.
- **Rule 6.** Nothing here compiles or connects. `rule` is read from the
  loaded `Check` objects, as `expression` already is.
- **Rule 7 and the exit codes.** Untouched.
- **Rules 1, 3, 4, 5.** Not touched: no metric, planner, dialect or loader
  change.
- **Results store and check identity.** Not touched: no model change, no
  migration. `rule` is served from the loaded check, not stored.
- **Public API.** `rule` is additive on `/api/v1`. `Check.expectation`,
  `warn` and `fail` are documented as provisional. `schemas.py` may read
  them because it lives in the same package, but the wire shape must not
  leak their Python types.

### Chart requirements, stated for the ui-engineer

Because the dataviz skill is available only to the tech lead, these are
the requirements it would otherwise supply. The tech lead checks the
built chart against the skill in VERIFY.

1. **Encode the question.** Sam's question is "how far from the line,
   and for how long". So: values on a linear y-axis, time on x, and the
   rule as a shaded region plus a labelled line. No dual axes, no
   gradients, no 3-D, no area fill under the line.
2. **Outcome marks.** Shape and colour both, from the status tokens and
   the status icons. Legend present whenever more than one outcome is
   shown.
3. **Missing is not zero.** `error`, and any result without a value, go
   in a separate labelled lane below the plot. The line breaks around
   them.
4. **Direct labels over legends** for the threshold lines and the rule
   change markers. Keep text horizontal.
5. **Both themes.** Colours come from `tokens.css` custom properties
   through classes, so they switch with `prefers-color-scheme`. Contrast
   as in D11.
6. **Responsive, no layout JS.** A `viewBox` with a fixed aspect ratio.
   Nothing measures the DOM to lay out the chart, which keeps it testable
   in jsdom.
7. **Pure functions for every decision.** Bands, domain, ticks, segments
   (where the line breaks), rule segments, and the summary text are pure
   and unit-tested. The SVG component only draws what they return.
8. **No chart library** (D17).

### Design decisions (settled in REFINE)

Reviews: architect, security-reviewer and data-steward approve/accept with
follow-ups; ui-engineer consulted. These supersede the open questions below
and any scenario text they contradict. The dataviz skill was loaded by the
tech lead; its rules are binding on the chart (listed in 13).

**API (tech lead; built)**

1. **Q1:** `rule` is on a new `CheckDetail(CheckSummary)`, served only by
   `GET /api/v1/checks/{id}` (`CheckDetail.of_detail`, as `RunDetail`).
   `GET /checks` and `CheckSummary` are unchanged — moving a field onto the
   list later is additive; taking it back would not be.
2. `Rule`, `CompareCondition`, `BetweenCondition`: a union discriminated on
   `kind` (no default), every field required, `op` a `Literal` tested equal
   to `dsl.Op`.
3. `rule` is built from the parsed `expectation` / `warn` / `fail`
   (including the metric's implied `= 0`), never from `check.canonical`,
   options, `where:` or `filter:`. Numbers are `Number.magnitude` /
   `Duration.magnitude` — by construction exactly what each recorded value
   was judged against (`engine/evaluate.py`); `text` is `str(condition)`.
   No unit or scale logic in `server/` or `frontend/`. An exhaustive match
   with `assert_never` makes a new condition kind a type error.
4. **R7:** each history entry carries `metric`, `dataset` and `unit` (the
   metric's unit, `null` for a metric this version doesn't know), so the
   page can leave other-metric values off the axis (D20) and format ticks
   for a check no longer loaded (D15).
5. A number literal too large for a float is a syntax error at
   `file:line:col` ("this number is too large") — it used to crash
   `validate` and would have reached the wire as `null`.
6. The recorded `expression` equals the served `expression` for an
   unchanged check (both `Check.canonical`), tested for triggers and implied
   conditions, so D7's `===` never draws a false rule change.

**Page (ui-engineer)**

7. **Q4:** plain `<a href>` and full page loads; no router, no
   `pushState`. `lib/route.ts` holds a pure `parseRoute(path)` and
   `checkHref(id)`: one non-empty segment, decoded inside try/catch,
   checked against the id pattern (`^[A-Za-z0-9][A-Za-z0-9_.:-]*$`, at
   most 64); anything else is "page not found" **with no request made**
   (`..`, `%2e%2e`, `a%2Fb`, `a%3Fb`, malformed `%`, 65 characters). Every
   API path and query value is built with `encodeURIComponent`.
8. **Q5:** one hook `lib/useLoads.ts` with named independent slots, a
   generation guard, `busy`, the minute clock, `reload`, and `isCurrent`
   so "Load older" answers after a refresh are dropped. Refresh on the
   detail page also re-fetches `/runs?limit=1`. `failureOf` moves to
   `api/api.ts`. Status wording (`SINCE_PREFIX`) stays in `lib/status.ts`;
   `Result`, `When`, `LastEvaluatedNote` move to a shared component
   imported by both pages.
9. Chart logic is plain functions in `frontend/src/lib/chart/` (scale,
   ticks, domain, bands, series, hit columns, label stacking, summary,
   layout) testable without the DOM; `HistoryChart.tsx` only draws.
   Status shapes are shared with `StatusIcon` so marks and icons can't
   drift. No generic chart framework until a second chart exists.
10. Two lanes, each drawn only when it has entries: "Could not evaluate"
    (`error`) and "No value" (any other outcome with no value).
11. D7 "labelled": a solid hairline marker "Rule changed" (numbered if
    more than one) on the chart, with an HTML caption under it: "Rule
    changed between runs <time> and <time>: from `A` to `B`".
12. Off-range edge labels are axis annotations formatted by the tick
    formatter (the D10 carve-out); rule text is never formatted from
    numbers.

**Chart rules (dataviz skill, binding)**

13. One series → no legend box (an inline shape key under the title is
    allowed). One y-axis. Line 2px round, neutral colour (it can't take a
    status colour); markers ≥ 8px with a 2px surface-colour ring; bands a
    ~10% wash; boundary lines solid; gridlines and markers 1px solid
    hairlines — nothing dashed. Status colours only for status, always
    with shape and text; text never wears the data colour. Label
    selectively (latest point, boundaries, off-range, markers). Hover and
    keyboard focus: a crosshair snapping to hit columns ≥ 24 units wide
    and a tooltip (value first); the SVG keeps `role="img"` with
    `<title>`/`<desc>`, interaction lives on a wrapping focusable group.
    The table view carries every value. Dark mode uses its own validated
    steps. New chart-only mark tokens (`--tw-{pass,warn,fail,error}-mark`,
    `--tw-grid`, `--tw-series`) are validated with the skill's
    `validate_palette.js` in both modes; the overview's text tokens are
    unchanged.

**Security (security-reviewer)**

14. The chart contains no `<a>`, `<use>`, `<image>` or `<foreignObject>`
    and no `href` of any kind; element ids come from `useId()`, never from
    data. The tooltip is positioned without any inline style (SVG
    transforms or class-based positions). The not-found page shows only a
    well-formed id, inside `<code>`. Source rules in the security test
    cover the chart directory.

**Deferred**: I-24 moves up to run straight after I-26 (data-steward: UTC
timestamps in freshness messages are misleading next to local-time axes);
a loader warning for a bare `< 0.05` on a percent metric; `list --output
json` sharing the API's check mapping.

### Open questions for the tech lead and the architect (REFINE)

1. **Q1: where `rule` lives.** On `CheckSummary`, so that `/checks` and
   `/checks/{id}` both carry it (one model; I-04 might use it), or on a
   `CheckDetail` returned only by `/checks/{id}` (keeps the list lean).
   The PM prefers `CheckDetail`: the overview does not need rules, and
   `/checks` is the request whose cost I-23 watches.
2. **Q2: the condition shape.** A discriminated union on `kind`, as above,
   or one flat object with nullable fields. The PM prefers the union,
   because it generates clean TypeScript. Keep `text` either way.
3. **Q3: scale parity.** Confirm that every percent metric records
   `value` on the 0–100 scale (as `missing_percent` does, 20.0) and every
   duration metric in seconds, so that `magnitude` is always on the
   value's scale. If any metric differs, R1–R3 need a unit note and a
   test per metric.
   **Answered by the data-steward in REFINE: confirmed, no unit note
   needed.** `percent()` in `metrics/base.py` returns `100 * part /
   whole` for all three percent metrics (`missing_`, `invalid_`,
   `duplicate_percent`), and `Number.magnitude` ignores the `%` flag, so
   `5%` and a bare `5` are both `5.0` on the 0–100 scale. `freshness` is
   the only duration metric, and it records `total_seconds()`.
   `Duration.magnitude` is in seconds. The loader's `_check_units`
   requires a duration unit on duration metrics, rejects durations
   elsewhere, and rejects `%` on non-percent metrics, so no threshold can
   sit on another scale. Counts and `number` metrics compare raw. The
   implied `= 0` of `schema` and `failed_rows` is a count of differences
   or rows. One trap stays in the language (not this spec): `< 0.05` on a
   percent metric means 0.05%, not 5%. It fails loudly, not silently, and
   the chart makes it obvious. **The scale is not stable across a
   rule change under an explicit `id:`**, because the metric itself can
   change. R7 and D20 cover that.
4. **Q4: navigation.** Plain `<a href>` links with a full page load (the
   PM's preference: the server already answers every client route with
   `index.html`, the Back button just works, and there is no router), or
   `history.pushState` in `App.tsx` for instant navigation. Either way,
   no router dependency (D17).
5. **Q5: where the shared hook and wording live** (D4, D14). For
   example `frontend/src/lib/useLoad.ts` and `frontend/src/lib/wording.ts`.
   The ui-engineer decides and records it in `docs/UI_SPECIFICATION.md`.

### Traps for the data-steward in REFINE

- **The band is today's rule, not the rule that judged the data.** D7
  limits it to the current segment, and D8 keeps marks on the recorded
  outcome. Check that nothing on the page reads as "this old result
  failed today's rule".
- **A `fail` with no value** (D9) and an `error` both sit in the
  no-value lane. They mean opposite things to Sam and Dana. Check the
  lane's labels.
- **The error streak.** On the chart, run E sits inside the "failing
  since A" span (D19). Check that the chart does not suggest the data
  was measured during E.
- **Time zones.** The x-axis ticks and tooltips are in the viewer's zone.
  The stored messages (until I-24) are in UTC. On one page Sam sees
  `14:56 GMT+8` on the axis and `06:56:12+00:00` in the message. State
  whether that is acceptable until I-24, or whether it raises I-24's
  priority (see BACKLOG).
- **Crushed charts.** `row_count between 1 and 10000` with 3 rows (D10).
  Check that the off-range label reads correctly.
- **Freshness values** vary with build time. Do not assert them.

### REFINE: data-steward decisions

- **Old results against today's rule.** This is covered by D7 (band
  only on the current segment), D8 (marks keep their recorded outcome),
  and two added cases: D4 and D7 for an edit not yet run (`edited-pending`),
  and D20 for a metric change, where today's axis would have mislabelled
  old values.
- **Errors are not plotted as 0.** D5 and D9 cover this. The lane is
  renamed "No value", because the same lane holds a `fail` with no value,
  and "Could not evaluate" would mislabel it.
- **`= 0` gets a band** (D6). Before this, the most common rule was the
  only one whose failures sat in unshaded (passing-looking) space.
- **Negative values** (D10). They are real (future timestamps, negative
  `min`) and must be drawn below 0.
- **The since and last-evaluated wording** reuses the overview's code
  (D4). The overview already says "Could not evaluate since …" for an
  error streak and "failing since …" inside "Last evaluated". The detail
  page must match word for word, which D4's shared module guarantees.
- **I-24, the time-zone trigger: pull it forward.** In REFINE, on a
  scratch run of `examples/retail`, `freshness(created_at) < 6h` passed
  with value `1h` and message `newest 2026-09-26T11:33:48.035115+00:00`.
  The run started at about 12:33 UTC. A steward in GMT+8 (Singapore, for
  example) sees that run on the axis at about `20:33 GMT+8`, and a
  "newest" of `11:33` in the message. Read as local time, the newest row
  looks 9 hours old against a value of `1h`. **The zone offset (8h) is
  larger than the threshold (6h).** Read naively, the message says the
  check should have failed.
  That is *misleading*, not untidy, and it hits exactly the check whose
  whole meaning is a time. The trigger recorded in BACKLOG ("I-24's
  impact goes 1 → 2, and it runs straight after I-26") is met. I-24 does
  **not** move ahead of I-05: doing it first would not clean stored
  messages, and the page is still worth shipping. Inside this spec the
  mitigation is labelling, not reformatting. The axis zone is now a
  `must` (D11), the table states its zone (D12), and the value (the age)
  is read before the message (D12). For I-24's own spec: the freshness
  message should name the zone in words, drop the microseconds, and say
  what the timestamp is ("newest row at 2026-09-26 11:33:48 UTC"). Ideally
  it lets the UI show it in the viewer's zone from a structured field,
  rather than by rewriting text.
- **Not taken up here (non-blocking, for the backlog):** `latest.since`
  runs across rule and metric changes (spec 003 semantics; D19 keeps it
  visible). A bare `< 0.05` on a percent metric means 0.05%, and a
  loader warning would help.

## Reviewers required

- **qa-engineer**: always. Focus: the pure functions at their edges
  (empty history, every value null, one point, equal timestamps, huge and
  negative values, `between` with low = high, NaN never reaches the page
  because the API sends null), the route parsing (encoded ids, trailing
  slashes, `/checks/..`), paging with a cursor, and the hook's late-answer
  handling on both pages.
- **data-steward**: always. The semantics above (the traps), the wording
  (D4 shares the overview's), a hand run on `recorded`, `interrupted` and
  `edited`, and the README section.
- **security-reviewer**: **required, narrow.** This changes what the
  server exposes over the network (the `rule` field), though only as a
  structured form of the `expression` it already serves. (REFINE: also
  `metric` and `dataset` on history entries, R7. Both are already
  visible through `expression` and `/checks`.) It also renders
  check-file and data text into SVG (`<title>`, `<desc>`, labels,
  tooltips; D16), and it must keep the CSP and the dependency surface
  unchanged (D17). No new endpoint: the SQL and source endpoints, the
  heavier review, are I-26's.
- **architect**: **required**, in REFINE and VERIFY. It touches
  `src/tablewatch/server/` and adds a field to the public API (Q1, Q2,
  Q3). It also reviews the frontend seams this adds: the shared hook and
  wording module (D4, D14), which I-04 and I-15 will reuse.
- **ui-engineer**: builder of `frontend/**`, `docs/UI_SPECIFICATION.md`
  and the bundle. Consulted in REFINE on D5–D11 and Q4–Q5. Does not
  judge its own work.

## Size

**M.** Python: one additive field with its schema and tests (small).
Frontend: a route, the shared hook and wording extraction, the detail
page, the history table, and the first chart with its pure functions and
tests. The chart is most of the work.

**Pre-planned split, if BUILD runs long.** D5–D11, D19 and D20 (the chart)
move to a new S item that ships next. This PR then ships the page with
identity, rule, latest result, the history table, links, the hook and
the failure states (R*, D1–D4, D12–D18). The page is useful without the
chart, because the table answers "how bad, since when" in numbers. The
REVIEW records the split if it is taken.
