# Spec 012: Check detail polish: "Current" agrees with the band, a missing value says so, `between` lines say which end they are, line numbers stay in view

| | |
| --- | --- |
| Backlog items | I-27 (data-steward, iteration 4 acceptance of I-05; named next by iteration 11 REVIEW) and I-39 (data-steward, iteration 6 VERIFY), combined: both are frontend-only polish of the check page, built by the ui-engineer. I-35 does **not** ride along (see "Why I-35 is not in this slice") |
| Features | C4 (hardening) |
| Phase | 2 (`0.2.0`) |
| Size | S |
| Depends on | I-05 ✓, I-29 ✓ |
| Branch | `iter/012-check-detail-polish` |
| Touches | `frontend/**`, `docs/UI_SPECIFICATION.md` and the committed bundle only. **No change to `src/`, the API, `openapi.json`, the store or the CLI** |
| Status | **ready** (iteration 12 PLAN, 2026-09-29, against `main` at `d39305f`). Every "today" below was measured on `d39305f`: API output from `tablewatch serve` on a scratch copy of `examples/retail`; chart geometry from `layoutChart` run in vitest on the spec 004 fixtures (`frontend/src/test/fixtures/detail.ts`) |

## Problem and persona

**Sam, data steward**, reads the check page to decide whether a failure
is real and whose it is. He does not write SQL; he reads the words, the
chart and the table, and he expects all three to say the same thing.
Four places on the page make him stop and work it out:

1. **"Current" in the table vs. the band on the chart.** On
   `customer-email-completeness` (spec 004's `metric-changed`, then
   changed back: runs A `< 5%`, C `< 15%`, M `missing_count(email) = 0`,
   N `< 15%`), the history table's Rule column says **"Current"** on both
   N and C, because they were judged by the same text as today's rule.
   The chart draws the `< 15%` band only over N: the band covers the
   newest run of results under today's rule (spec 004 D7, a `must`), and
   M breaks it. Measured: the band starts at rule change 3 (between M and
   N) and C sits in white space at 20%, while the key says the shading is
   "Fails the current rule". "Current rule" in the table and on the chart
   mean two different sets of rows. Sam: "The table says C was judged by
   the current rule. Then why isn't it red?"
2. **"—" under Latest result.** A check that measured nothing (an empty
   table, or a `where:` that matches no rows) fails with no value. The
   table and chart say "No value measured" / "Fail: no value measured".
   The Latest result section (and the overview row, which uses the same
   component) shows a bare **"—"**. Measured on a scratch retail copy with

   ```yaml
   # checks/polish/empty.yml
   dataset: sales.orders

   checks:
     - avg(amount) between 10 and 500:
         id: avg-on-nothing
         where: "amount > 1000000"
   ```

   `GET /api/v1/checks/avg-on-nothing` answers `latest.outcome: "fail"`,
   `value: null`, `display_value: "—"`, `message: "no non-NULL values in
   scope"`, and the page shows `—` then the message. Sam reads "—" as
   "nothing to report", which is the opposite of a failure.
3. **`between` boundary lines both carry the whole rule.** Each boundary
   line is labelled with its condition's `text`. A compare has one line,
   so `< 5%` beside the line at 5 reads well. A `between` has two lines,
   and each is labelled `between 50 and 60`. Measured with `avg(amount)
   between 50 and 60` on the retail history (value 54.3571): labels
   `between 50 and 60` at y 49.3 and y 16, the latest value `54.3571` at
   y 34.8 squeezed between them. When one end is off the axis, the one
   line in range still says `between 10 and 500` (`366d9254d889c910`: a
   line at 10 labelled with the whole rule, and `500 above` at the top).
4. **"10,000 above" crowds the latest value.** On `cd3e8103b4318809`
   (`row_count between 1 and 10000`, value 3), the latest value's label
   `3` is at y 16 and the off-range label `10,000 above` at y 30: stacked
   the minimum 14 units apart, and the "above" label sits **below** the
   value. It reads as if 3 were the thing above.

**Sam, again, on the Source block** (I-39): a check with a long
`valid_regex:` line scrolls sideways inside the block, and the line
numbers scroll away with the text (spec 006 P16 accepted this as option
(a)). Once scrolled, he cannot tell which line he is reading, and "line
11" in a review comment no longer matches anything he can see.

How they cope today: Sam asks Dana; Dana reads the YAML. The page is
meant to spare both of them that.

## Outcome

After this ships, on the check page:

- The table calls a result's rule "Current" exactly when the chart
  shades it under the current rule. A result judged by the same text
  before a later change says so in words.
- A result with no value reads "No value measured" everywhere a result
  is shown: Latest result, the overview row, the history table. The
  words come from one place.
- Each `between` boundary line says which end it is (`>= 50`, `<= 60`),
  and the full rule stays above the chart as today.
- An off-range label sits on the side it names, and never close to the
  latest value's label.
- In the Source block, line numbers stay at the block's left edge while
  the text scrolls sideways under them.

## Research

- **Grafana** colours threshold regions and draws threshold lines on
  time series, but does not label threshold lines at all; labels on the
  line are an open feature request ("ideally … labeled on the graph next
  to the line"). Our direct labels are already ahead; the lesson is that
  a label must identify *its* line, which `between 50 and 60` twice does
  not. ([Grafana: configure thresholds](https://grafana.com/docs/grafana/latest/panels-visualizations/configure-thresholds/),
  [grafana/grafana#90807](https://github.com/grafana/grafana/issues/90807),
  [community thread](https://community.grafana.com/t/defining-labels-for-thresholds/50792))
- **Sticky line numbers:** the established pure-CSS technique is a
  number on each line with `position: sticky; inset-inline-start: 0` and
  an opaque background, so code slides under it; supported in every
  current engine (Chrome 56+, Firefox 59+, Safari 13+). No library is
  needed, and it keeps numbers as generated content, so copy is
  unchanged. ([Veriphor: code block line numbers](https://www.veriphor.com/articles/code-block-line-numbers/),
  [jaseg: CSS-only code blocks](https://jaseg.de/blog/css-only-code-blocks/))
- The boundary labels borrow the DSL's own operators (`>=`, `<=`, `<`,
  `>`) rather than any tool's syntax (docs/check-language.md: `between`
  is inclusive at both ends, as SQL's `BETWEEN` is).

## Acceptance scenarios

Frontend scenarios are vitest tests on the spec 004 fixtures
(`frontend/src/test/fixtures/detail.ts`, typed against the generated
contract), plus the new fixtures named below. Wording in quotation marks
is asserted exactly. "Right labels" are the chart's
`[data-label="boundary" | "latest" | "off-range"]` texts; y values are
the `y` attributes in the chart's viewBox units. The data-steward repeats
K1, L1, B1, B4 and N2 by hand against a real `serve` in VERIFY.

### K: the table's "Current" agrees with the band (I-27 a)

**K1: "Current" only where the band is** `must`
- Given `metricChangedBack` (history N `< 15%`, M `missing_count(email)
  = 0`, C `< 15%`, A `< 5%`; the check loaded as
  `missing_percent(email) < 15%`)
- When the check page renders
- Then N's Rule cell reads "Current"
- And C's Rule cell reads exactly "Same as current, before a rule change",
  with no "Current", no "Different rule" flag and no expression (the
  text is today's, already shown above the chart), styled `quiet` like
  "Current" and "Same as the newest": it is a note, not a warning
- And M's reads "Different rule" `missing_count(email) = 0` and A's
  "Different rule" `missing_percent(email) < 5%` (unchanged)
- And the chart is unchanged: the fail band starts at rule change 3 (the
  x midway between M and N) and C's mark is outside it.

**K2: one rule decides both** `must`
- The set of rows the table calls "Current" is computed by the same
  function that places the band (`series.ts`'s newest run of entries
  whose `expression` equals the check's), not by a second comparison in
  `HistoryTable`. A unit test on `buildSeries` asserts, for
  `metricChangedBack`, that exactly N is in the current run; for
  `edited` (C `< 15%`, A `< 5%`), exactly C; for `threeRules`, exactly C.
- And every row in the current run whose recorded `dataset` equals the
  check's reads "Current"; a row in the current run with another dataset
  keeps its "Other dataset" flag (spec 004 D20, unchanged).
- *(`should`)* "Current" follows the run, not whether a band is drawn:
  on a check whose current-run values are all NULL (no band area to
  shade, only the No value lane), those rows still read "Current". An
  entry `buildSeries` drops for an unreadable `started_at` is never
  "Current" (the API always sends ISO times, so this is a guard, not a
  case).

**K3: a pending edit** `must`
- Given `edited-pending` (history C `< 15%`, A `< 5%`; the check now
  loaded as `< 25%`, no run since)
- Then no band is drawn (unchanged) and no row reads "Current": C and A
  both read "Different rule" with their expressions (unchanged).
- *(`should`)* And given a history A `< 5%`, C `< 15%` with the check
  changed back to `< 5%` and not yet run: no band; C "Different rule";
  A "Same as current, before a rule change".

**K4: a check no longer loaded** `must`
- Given a history with no loaded check (`current === null`), rows whose
  expression equals the newest entry's still read "Same as the newest"
  (unchanged).

### L: a result with no value says so (I-27 b)

**L1: Latest result** `must`
- Given `GET /checks/avg-on-nothing` answering `latest: {outcome:
  "fail", value: null, display_value: "—", message: "no non-NULL values
  in scope", …}` (the real response above, as a fixture)
- When the check page renders
- Then the Latest result section contains "No value measured" and "no
  non-NULL values in scope", and does not contain "—"
- And its status badge is Fail (unchanged).

**L2: the overview row** `must`
- Given the same check in `GET /checks` on the overview
- Then its row's result reads "No value measured" and the message, with
  no "—".

**L3: every outcome that can lack a value** `must`
- Given `latest` with `value: null` and `outcome` `warn`, then `pass`
- Then both read "No value measured" (and the message when there is one).
- And `error` still reads "Could not evaluate" and `skipped` "Skipped"
  (unchanged; overview test line 102 and D9 still pass).

**L4: one source for the words** `must`
- The string `No value measured` appears in exactly one module under
  `frontend/src/` outside `test/`, and the history table, the Latest
  result section and the overview all render it from there (a source-rule
  test, like the existing ones in `sql.test.tsx`).
- The chart's own "Fail: no value measured" (markName, D9) is a
  different, asserted string and is unchanged.

### B: boundary labels (I-27 c)

New fixture: `recorded`'s `366d9254d889c910` history (two passes at
`54.3571`) under a substituted rule, as the PM's measurement did.

**B1: an inclusive `between`, both ends in range** `must`
- Given the rule `{expect: {kind: "between", low: 50, high: 60, negated:
  false, text: "between 50 and 60"}}`
- Then the boundary labels, in ascending value, are exactly `[">= 50",
  "<= 60"]`
- And "Current rule: Expected between 50 and 60" is still shown above
  the chart (unchanged).

**B2: `not between`** `must`
- Given `{kind: "between", low: 50, high: 60, negated: true, text: "not
  between 50 and 60"}`
- Then the boundary labels are exactly `["< 50", "> 60"]`.

**B3: one end off the axis** `must`
- Given `recorded`, `366d9254d889c910` (`between 10 and 500`, value
  54.3571)
- Then the boundary labels are exactly `[">= 10"]` and the off-range
  labels `["500 above"]`.
- And given `cd3e8103b4318809` (`between 1 and 10000`, value 3): boundary
  `[">= 1"]`, off-range `["10,000 above"]` (the existing test at
  `check.test.tsx:336` keeps its assertion).

**B4: a trigger, and the colour follows the role** `must`
- Given `{expect: null, warn: {kind: "between", low: 50, high: 60,
  negated: false, text: "between 50 and 60"}, fail: null}`
- Then the labels are `[">= 50", "<= 60"]`, drawn as warn lines
  (`chart__boundary--warn`). The label names where the condition holds,
  whatever its role, exactly as a compare line's `text` does today.

**B5: what does not change** `must`
- A compare condition's line is still labelled with its `text`: `< 5%`
  on `b1ceb8262d8b5441`, `= 0` on `000f8d0048744bfb`; every existing D6
  label assertion passes unedited.
- `between 5 and 5` draws one line, labelled `between 5 and 5` (its
  `text`: one line cannot repeat itself); `not between 5 and 5` likewise.

**B6: labels never round a threshold** `should`
- Given `between 0.125 and 100` on the same history: labels `[">=
  0.125", "<= 100"]`, not `0.13`.
- Given a percent check with `{low: 0.5, high: 2, text: "between 0.5%
  and 2%"}`: `[">= 0.5%", "<= 2%"]`. A duration check with `{low: 3600,
  high: 86400, text: "between 1h and 1d"}`: `[">= 1h", "<= 1d"]`.
- And an off-range label uses the same formatter: a lower boundary of
  0.125 left off the axis reads `0.125 below`, not `0.13 below`.

**B7: an off-range label sits on its side, clear of the latest value** `must`
- Given `cd3e8103b4318809` on `recorded`
- Then the `10,000 above` label's y is **less than** the latest label
  `3`'s y (it is above it), and they are at least **20** units apart
  centre to centre (today: 14, and the order is reversed).
- And in general: an `above` edge label is never below the latest
  label, a `below` edge label never above it, and every right label is at
  least 20 units from the latest label (other pairs keep today's 14).
  Tested on `cd3e8103b4318809`, `366d9254d889c910`, and B1's and B2's
  fixtures.

**B8: the latest label stays near its mark** `should`
- In the four fixtures of B7, the latest label is within 20 units of its
  mark's y. (B1 today: latest 34.8 between lines at 16 and 49.3.)

### N: line numbers stay in view (I-39)

**N1: the numbers are sticky** `must`
- A source-rule test reads `app.css` and finds, for the Source block's
  line numbers (`.code-block--lines .line::before` or whatever element
  the ui-engineer chooses): `position: sticky`, a left inset of 0
  (`left: 0` or `inset-inline-start: 0`), and a background set from the
  block's own surface token (not transparent).
- And the numbers stay generated content: the `<code>`'s `textContent`
  equals the API's `text` exactly (spec 006's existing test passes
  unedited), and no number is a text node.

**N2: by hand, scrolled sideways** `must` (data-steward, VERIFY)
- Given a scratch retail copy whose `checks/sales/customers.yml` ends
  with

  ```yaml
    - invalid_count(email) = 0:
        valid_regex: '[a-z0-9][a-z0-9][a-z0-9][a-z0-9][a-z0-9][a-z0-9][a-z0-9][a-z0-9][a-z0-9][a-z0-9][a-z0-9][a-z0-9][a-z0-9][a-z0-9][a-z0-9][a-z0-9][a-z0-9][a-z0-9][a-z0-9][a-z0-9][a-z0-9][a-z0-9][a-z0-9][a-z0-9]'
        missing_values: ['', 'N/A']
  ```

  served, on that check's page, in Chrome, Firefox and Safari, at 1280 px
  and at 360 px wide, light and dark
- When the Source block is scrolled fully to the right (trackpad, and
  the arrow keys with the block focused)
- Then all three line numbers stay visible at the block's left edge,
  each level with its line, and the text passes under the number column,
  not over it
- And the page itself never scrolls sideways (P16, unchanged)
- And a hand selection of the three lines, pasted into a text editor,
  holds no line numbers; **Copy the source** copies `text` exactly
  (unchanged).

**N3: the contract changes in the UI spec** `must`
- `docs/UI_SPECIFICATION.md` §4A.10 says the number column is sticky
  (option (b) of spec 006 P16), replacing "it is not sticky".

### G: gates

**G1** `must`: `npm test`, `tsc` and `vite build` pass; the committed
bundle is the fresh build (CI's check); `uv run pytest` passes unchanged
(no Python changes); D16 (data renders as text), D17 (no new
dependencies; `package.json` `dependencies` still exactly `react` and
`react-dom`) and the served CSP are unchanged.

## Non-goals

- **I-35** (the SQL section's wording, the driver and URL messages, a
  datasource that is not defined). Next, as its own S; see below.
- **No band over earlier segments under the same rule.** Spec 004 D7
  (`must`) keeps the band on the newest run only; this spec makes the
  table agree with it rather than reopening D7.
- **No change to what the API sends.** `display_value` stays `"—"` for a
  result with no value; the page chooses the words (spec 004 D12). The
  console's `—` is unchanged.
- **No coarser durations.** A duration threshold is labelled with the
  axis's formatter, which shows the largest unit and the next (`1d 1h`
  for 90061 s). Durations past a year belong to I-43/I-44.
- **No labels on the past rules' lines** (spec 004: past rules are
  shown as text at their markers).
- **No change to the SQL block**, which keeps wrapping and has no line
  numbers (spec 005 P12).
- **The pending caption's wording** ("Every result here was judged by an
  earlier rule") is not changed, even in K3's `should` case where an
  older row has today's text.
- Seconds-level x ticks on fixtures whose runs are seconds apart
  (iteration 4's fixture note) are not touched.

## Design notes

- **Rule 7 and the exit codes:** untouched; nothing here runs in Python.
- **Decision 12 (UI spec §4A.6.3, `format.ts`): the browser formats only
  axis ticks and off-range edge labels**, and `lib/rule.ts` says a
  condition is always shown as `rule.*.text`. B1–B6 extend decision 12 by
  one case: a `between` condition's two boundary lines are labelled with
  an operator and the boundary value from `low`/`high`, formatted by the
  same formatter as the off-range labels (which already formats a
  threshold from its number). Parsing `text` to recover `50` and `60` as
  written was rejected: it is a second copy of the DSL (spec 004
  non-goals). The full `text` stays visible above the chart. Compare
  conditions and one-line `between`s keep `text`. `format.ts`'s header,
  `rule.ts`'s header and §4A.6.3/§4A.6.4 change with it.
- **Operators:** `between` is inclusive at both ends (`Between.holds` in
  `src/tablewatch/dsl/ast.py`), so its lines are `>=` / `<=`; `not
  between` is `<` / `>`. ASCII, as the DSL writes them and as every other
  rule text on the page reads.
- **"Current" (K2):** today `HistoryTable` compares `entry.expression`
  with the check's; the band comes from `buildSeries`. Two rules for one
  idea is how they drifted. Expose the current run from `Series` (for
  example the entry indexes in it) and have the table use it. The table
  does not otherwise take the series today; how it gets it is the
  ui-engineer's call.
- **L4:** `HistoryTable`'s private `Value` and `LatestResult.tsx`'s
  `Result` both need "No value measured"; one exported constant or one
  small component in `LatestResult.tsx` serves both.
- **I-39:** the numbers are `.line::before` on inline `.line` spans
  today. A sticky pseudo-element sticks only within its containing box,
  so each line box must be at least as wide as the widest line (for
  example `display: block; width: max-content; min-width: 100%`), or the
  number leaves with a short line's box. `textContent === text` must
  hold, so the `\n` between line spans stays in the DOM; check that a
  block-level line with a trailing `\n` under `white-space: pre` does
  not render an extra blank line in any of the three engines.
- **CSP:** no inline style; everything is in `app.css` (spec 003
  decision 10).

### Open questions for REFINE

*Answered by the data-steward in REFINE (2026-09-29): Q2 and Q3, below
the list. The K, L and B "today" measurements were repeated on a scratch
retail copy served from this branch (still `d39305f` in `src/` and the
bundle) and hold: `email-completeness` run as A `< 5%`, C `< 15%`, M
`missing_count(email) = 0`, N `< 15%` gives history N 20.00% fail, M 1
fail, C 20.00% fail, A 20.00% fail, all `sales.customers`; `GET
/checks/avg-on-nothing` and its `GET /checks` row both carry `latest:
{outcome: "fail", value: null, display_value: "—", message: "no non-NULL
values in scope"}`; `avg(amount) between 50 and 60` passes at `54.3571`
with `rule.expect` `{kind: "between", low: 50.0, high: 60.0, negated:
false, text: "between 50 and 60"}`; N2's check serves its source as four
lines once an `id:` is added (the spec's three-line YAML has no `id:`;
either shape is fine for N2).*

1. **ui-engineer:** the crowding rule in B7 (20 units from the latest
   label; edge labels ordered by their side). Is 20 right at the chart's
   12-unit font, and does forcing `above` to the top ever push the latest
   label more than B8's 20 units off its mark? If the stack cannot meet
   B7 and B8 together, B7 wins and B8 is dropped with a note.
2. **ui-engineer + data-steward:** B1's labels `>= 50` / `<= 60` versus
   `≥ 50` / `≤ 60`. The PM chose ASCII to match the DSL and every other
   rule text on the page; the steward may prefer the symbols for Sam.
   Either is fine if it is the same on all four operators.
   **Answer (data-steward): ASCII, `>=` `<=` `<` `>`.** Sam never sees a
   `between` label alone. It sits under "Current rule: Expected between
   50 and 60", beside the Rule column, and near the Source block, all in
   DSL text, and on sibling checks next to compare lines labelled from
   `text` (`>= 100`, `< 5%`), which are ASCII and stay ASCII (B5).
   Symbols would put `≥ 50` on one chart and `>= 100` on the next for the
   same idea. Sam would then ask whether they mean different things, and
   he would be right to. The file he reviews with Dana says `>=`, so
   that is the form he has to learn anyway. `≥` reads a little better
   alone, but that is not how Sam reads the page. So B1–B6 stand as
   written, and no label uses `≥`/`≤`.
3. **data-steward:** K1's "Same as current, before a rule change". It
   must say that the text is the same *and* that it is outside the
   shaded span; shorter words are welcome.
   **Answer (data-steward): keep it, exactly "Same as current, before a
   rule change".** "Same as current" answers "was this judged by today's
   words?" (yes). "before a rule change" answers "then why isn't it
   shaded?" (a different rule ran after it, and the shading starts where
   the chart's "Rule change *n*" marker says). Rejected alternatives:
   "Same rule, earlier" (same as what? and it hides the reason);
   anything with "Current" in it (K1 forbids it, and it is the drift
   this spec removes); "Same as current, before rule change 3" (ties to
   the caption's number, but the chart numbers changes only when there
   are two or more and says "Rule changed" for one, so the words would
   have to vary; not worth it at S). In the K3 `should` case (check
   changed back, not yet run) the words are still true: a rule change
   followed that row. Show it `quiet`, with no expression (K1), because
   it is information, not a defect.
4. **ui-engineer:** L2 changes the overview's row for a no-value result.
   Spec 003 has no O-scenario that pins `—` (checked: only
   `overview.test.tsx:102`, which asserts its absence on an error). Any
   objection?

## Why I-35 is not in this slice

The iteration 11 REVIEW let I-35 ride only if the PR stayed S. Measured
on `d39305f`, it cannot stay frontend-only:

- the driver message (`unsupported SQLAlchemy URL scheme 'snowflake':
  Can't load plugin: sqlalchemy.dialects:snowflake`) and the malformed-URL
  message (`the url is not a SQLAlchemy URL (expected scheme://...)`)
  come from `dialect_for` in `src/tablewatch/datasources/__init__.py`,
  and a run through `create_engine_for` raises the same `Can't load
  plugin` text, so the fix belongs in Python for `compile`, runs and the
  page alike;
- a check whose datasource is not defined is served with `"datasource":
  ""` (`GET /checks/c2f00d8ebc53948d` and its `/sql` on a scratch copy
  with `datasource: nowhere`), so showing "the name as written" needs the
  loader to keep it: a model and API change.

That is `src/`, the API and an architect review, on top of a chart
change. It stays I-35 (rank 3, 1.0), planned next as its own S; the
served `""` is recorded on I-35 as a requirement.

## Reviewers required

- **qa-engineer**: always.
- **data-steward**: always; answers Q2 and Q3 in REFINE; hand runs K1,
  L1, B1, B4 and N2 in VERIFY.
- **ui-engineer**: builds it; answers Q1, Q2 and Q4 in REFINE; updates
  `docs/UI_SPECIFICATION.md`.
- **architect: not required.** No change to `src/`, no seam, no public
  API. If BUILD finds it needs one, the tech lead stops and adds the
  architect.
- **security-reviewer: not required.** No trigger in PROCESS.md is
  touched: no dependency (D17 holds), no new endpoint or network call, no
  change to what data is exposed, the CSP unchanged, CSS only in
  `app.css`.

## Size

**S.** Three small changes to existing chart and table code (the label
text for `between`, the right-label stacking rule, one shared "current
run"), one shared string, and one CSS rule with its UI-spec paragraph. No
Python, no contract change. The largest risk is B7/B8's label stacking,
where iteration 4's blocking findings were; if REFINE finds B7 and B8
cannot both hold, B8 (`should`) goes, not the slice.
