# Spec 011: Freshness works on a DuckDB `TIMESTAMPTZ` column; one metric's crash errors only its own check

| | |
| --- | --- |
| Backlog items | I-41 (PM, iteration 7 PLAN; next by iteration 10 REVIEW) and I-42 (data-steward, iteration 7 REFINE; QA, iteration 7 VERIFY), combined because what is left of I-42 is a few lines in the same run path and a test beside I-41's |
| Features | A, E0 (hardening) |
| Phase | 2 (`0.2.0`) |
| Size | S |
| Depends on | nothing |
| Branch | `iter/011-freshness-timestamptz` |
| Status | **ready** (iteration 11 PLAN, 2026-09-29, against `main` at `af0bd3c`). Every "today" output below was measured on `af0bd3c` with `tablewatch run` or directly against `duckdb` 1.5.5, `duckdb-engine` 0.17.0, SQLAlchemy 2.1.0 |

## Problem and persona

**Dana, data engineer**, loads events into DuckDB with a `loaded_at
TIMESTAMPTZ` column. That is the type DuckDB's own docs recommend for
instants, and it is what `now()` returns. Her first freshness check:

```yaml
# checks/events.yml
dataset: events
datasource: wh
checks:
  - freshness(loaded_at) < 1d
  - row_count > 0
```

`tablewatch run` today (`af0bd3c`):

```text
OUTCOME  DATASET  CHECK                      VALUE  DETAIL
ERROR    events   freshness(loaded_at) < 1d      —  Invalid Input Error: Required module 'pytz' failed to import, due to the following Python exception:
PASS     events   row_count > 0                  1
exit=2
```

It errors on **every run**, and the check she cares about most never
evaluates. Exit 2 pages whoever handles "tablewatch could not tell". The
message names a module she has never heard of. To get round it today she
either `pip install pytz` into the venv by hand (then the next clean
install breaks again) or changes the column to a naive `TIMESTAMP`. The
second is worse, because freshness then depends on the datasource's
`timezone` being right, and our docs warn that getting that wrong "fails
silently".

**Why it happens.** The DuckDB Python client builds a zone-aware
`datetime` for a `TIMESTAMPTZ` value with `pytz`. It imports `pytz` at
fetch time but does not declare it: neither `duckdb` nor `duckdb-engine`
lists it in `Requires-Dist`, not even `duckdb[all]`. Measured:

- Only `TIMESTAMPTZ` needs it. `TIMESTAMP`, `DATE`, `TIMETZ`,
  `TIMESTAMP_NS` and text fetch without it.
- It is needed whatever the session `TimeZone` is, `UTC` included, so
  setting the session zone does not help.
- Other projects hit the same undeclared import and fixed it the same
  two ways: declare `pytz`, or cast the column to naive `TIMESTAMP`
  ([cyber-response-agent #1126 / PR #1129](https://github.com/beetroot-salad/cyber-response-agent/issues/1126),
  [coxswain #159](https://github.com/ppfenning/coxswain/issues/159)).
  Soda compares freshness in UTC once both sides carry a zone
  ([Soda freshness checks](https://docs.soda.io/soda-cl/freshness.html)),
  which is what our `compute` already does with an aware value.

**Sam, data steward** (I-42): when one metric's `compute` raises
something other than `TypeError`/`ValueError`, every check on the
dataset becomes `internal error: …`, `row_count` included. That breaks
rule 7: failures should become `error` outcomes only "on the checks they
affect".

### What is left of I-42 (measured on `af0bd3c`)

`_run_dataset` has caught `TypeError` and `ValueError` from `compute`
per check since Phase 1. So all three triggers recorded on I-42 **now
error only their own check**. Each was measured beside a passing
`row_count > 0`:

| Trigger recorded on I-42 | Today |
| --- | --- |
| DuckDB `TIMESTAMP '10000-01-01'` (returned as `str`) | `ERROR … Invalid isoformat string: '10000-01-01 00:00:00'`; `row_count` passes |
| SQLite text `29/09/2026 10:00` in a freshness column | `ERROR … Invalid isoformat string: '29/09/2026 10:00'`; `row_count` passes |
| `9999-12-31 23:59:59` on `timezone: America/New_York` | passes, with the placeholder note (spec 007 F8 removed the overflow) |

The gap that remains is structural. Any other exception type from
`compute` (`OverflowError`, `ZeroDivisionError`, `KeyError`,
`AttributeError`, …) still reaches the dataset-wide safety net in
`_run_dataset`'s caller. So does any exception from `evaluate()`, which
sits outside the per-check `try`. No built-in metric is known to trigger
it today. It is the backstop that iteration 7 said is needed ("a
formatter's 'must not raise' rule is only as strong as the parser in
front of it"). It also matters before any plugin metric exists (H1,
Phase 5). The fix is to widen one `try` and add one test pair, so the
combination stays S.

## Options for I-41, and what each costs

Each option was measured against DuckDB 1.5.5 with the session
`TimeZone` set to `Asia/Singapore` (this machine), `America/New_York`,
`Asia/Kolkata` and `UTC`.

| Option | Result | Rule check | Verdict |
| --- | --- | --- | --- |
| **A. Declare `pytz`** in the `duckdb` extra (and the dev group) | Fetch returns an aware `datetime`. The instant is exact in every session zone tried, including the ambiguous DST hour (`2026-11-01 05:30Z` and `06:30Z` in New York) and an LMT-era value (`1890-01-01`, Kolkata `+05:21:10`). `infinity` / `-infinity` come back as the same naive `9999-12-31 23:59:59.999999` / `0001-01-01` that a `TIMESTAMP` column gives today. Year > 9999 comes back as `str`, as it does for `TIMESTAMP`. No SQL changes. It also fixes every future `TIMESTAMPTZ` fetch on DuckDB, e.g. B6 failed-row samples (Phase 2b) | No rule touched. Adds a **dependency**: pure Python, MIT, no dependencies of its own, no native code, no network; `pytz` 2026.4 is current | **Chosen** |
| B. `CAST(col AS TIMESTAMP)` in SQL | Converts to the **session** zone's wall clock (machine-local by default: `16:00` in Singapore, `04:00` in New York for the same row). That value is then read as naive in the datasource's `timezone`, so it is wrong by the machine's offset, silently. It also turns a `DATE` into midnight, so "newest date" is lost | Not arithmetic, so rule 2 is not pressed. But it breaks **rule 3**: the meaning would depend on the DuckDB session setting. Columns are untyped (rule 4), so the cast cannot be limited to `TIMESTAMPTZ` columns | Rejected |
| C. `epoch(col)` | An aware column comes out right. A naive `TIMESTAMP` is read as UTC, which ignores the datasource `timezone`, and a `DATE` becomes a number. It cannot be limited to aware columns (untyped) | Presses rule 2 (the conversion moves into SQL, per dialect) and breaks the naive-timestamp contract | Rejected |
| D. `CAST(MAX(col) AS VARCHAR)` on DuckDB only, parsed in Python (a `MetricContext` normalisation like `regex_search`) | Works for the common case, with no dependency. Costs: it parses DuckDB's text format forever; an LMT-era value loses seconds (`1890-01-01 05:21:10+05:21`, 10 s off); `infinity` becomes an `error` on `TIMESTAMPTZ` but stays a pass on `TIMESTAMP`, so the two types disagree; and freshness on an `INTEGER` or `TIME` column changes from "freshness needs a date or timestamp column, got int" to "Invalid isoformat string: '5'". It fixes freshness only | This is rule 3 normalisation, not rule 2: no date arithmetic, and the age is still computed in Python. But it is a DuckDB-only code path the other options don't need | Fallback, only if security review rejects A |

**Decision: A.** It is the only option that fixes the cause. It changes
no SQL and no metric, and a `TIMESTAMPTZ` column behaves exactly like a
`TIMESTAMP` column at every edge. Its cost is one dependency and a
security review.

**Does this need the owner?** No. PROCESS.md's outward-facing list is a
PyPI release, a new external service, and licence or trademark
questions. Adding a runtime dependency to an extra is none of those.
`pytz` is MIT-licensed, which raises no licensing question for an
MIT/Apache project. PROCESS.md makes the security-reviewer mandatory
for a new dependency, and that is the gate. If the security-reviewer
blocks `pytz`, the tech lead falls back to D without coming back to
PLAN. D changes no user-visible outcome in the `must` scenarios below,
and the scenarios are written to hold for either.

## Outcome

A freshness check on a DuckDB `TIMESTAMPTZ` column passes or fails on
the data, installed the documented way (`pip install
'tablewatch[duckdb]'`). The result is the same on any machine,
whatever DuckDB's session zone. A metric that crashes errors only its
own check. Every other check on the dataset still reports.

## Acceptance scenarios

Tests pin `now` with `run_checks(..., now=NOW)`, where `NOW =
2026-09-27 12:00:00 UTC` as in `tests/test_readable_values.py`. The
project used by F1 to F5:

```yaml
# tablewatch.yml
name: tz
datasources:
  wh: {type: duckdb, path: w.duckdb}
  ny: {type: duckdb, path: w.duckdb, timezone: America/New_York}
```

```sql
CREATE TABLE events (id INTEGER, loaded_at TIMESTAMPTZ, local_at TIMESTAMP, day DATE);
INSERT INTO events VALUES
  (1, TIMESTAMPTZ '2026-09-27 09:30:00+00', TIMESTAMP '2026-09-27 09:30:00', DATE '2026-09-26'),
  (2, TIMESTAMPTZ '2026-09-27 18:00:00+08', TIMESTAMP '2026-09-27 05:00:00', DATE '2026-09-25');
-- row 2's loaded_at is 10:00:00Z: the newest instant, written with another offset
```

### F: freshness on `TIMESTAMPTZ`

**F1 (must): a zoned column is measured as an instant.**
Given `checks/events.yml`:

```yaml
dataset: events
datasource: wh
checks:
  - freshness(loaded_at) < 3h
  - row_count > 0
```

When run at `NOW`, then `freshness(loaded_at) < 3h` is `pass` with value
`7200.0` (2h) and message `newest row at 2026-09-27 10:00:00 UTC`.
`row_count > 0` is `pass` (`2`). The `2026-09-27 18:00:00+08` row wins
because MAX compares instants, not wall clocks. Through the CLI, which
cannot pin `now`, a table whose newest `loaded_at` is `now() - INTERVAL
2 HOUR` makes `tablewatch run` exit 0. This is the reproduction above,
which exits 2 today.

**F2 (must): a stale zoned column fails, not errors.**
`freshness(loaded_at) < 1h` on the same data is `fail` with value
`7200.0` (with the CLI and a row 2h old, exit 1).

**F3 (must): the datasource `timezone` changes the display, never the
age.** The same check on datasource `ny` is `pass` with value `7200.0`
and message `newest row at 2026-09-27 06:00:00 America/New_York
(UTC-04:00)`. For an aware column, `timezone` is only how the time is
shown (docs/check-language.md, "Freshness and time zones").

**F4 (must): naive and date columns are unchanged.** In the same run,
`freshness(local_at) < 3h` on `wh` is `pass`, `9000.0`, `newest row at
2026-09-27 09:30:00 UTC`. `freshness(day) < 2d` is `pass`, `129600.0`,
`newest date 2026-09-26`. Both are what `af0bd3c` gives today (a
regression guard).

**F5 (must): an empty or all-NULL zoned column fails as today.** With
`DELETE FROM events`, `freshness(loaded_at) < 3h` is `fail` with no value
and the message `no timestamps in scope`, the same as an empty
`TIMESTAMP` column (spec 007).

**F6 (must): the dependency is declared where users install from.**
`pyproject.toml`'s `duckdb` extra and the `dev` group both list `pytz`,
and `uv.lock` resolves it. A test reads `pyproject.toml` and asserts the
`duckdb` extra contains a `pytz` requirement, so a later cleanup cannot
silently drop it. (Under fallback D this scenario is replaced by the
`MetricContext` method's DuckDB and SQLite unit tests.)

**F7 (should): the result does not depend on the machine's zone.**
F1's value and message are identical when DuckDB's session `TimeZone`
is `America/New_York`, `Asia/Kolkata` or `UTC` (the default is
machine-local). QA picks the mechanism, e.g. a `TZ` environment
override in a subprocess or a connect-time `SET`, used only in the
test. If none is practical, a direct `duckdb` fetch test that asserts
the instant across zones is acceptable.

**F8 (should): the edges match `TIMESTAMP`.** On a `TIMESTAMPTZ` column,
`'infinity'` gives the same outcome and message as a `TIMESTAMP`
`'infinity'` gives today (`pass` with the placeholder note, `9999-12-31
23:59:59`). `'10000-01-01 00:00:00+00'` gives `error` with `Invalid
isoformat string: …` on that check alone, with `row_count > 0` passing.

**F9 (should): the retail example covers it.** The data-steward adds
one `TIMESTAMPTZ` column and one freshness check on it to
`examples/retail`, and the example still exits 1 only for its planted
defects.

### I: one metric's crash stays on its check

Tests register a throwaway metric in the test module (not shipped), e.g.
`explodes(col)`, whose `compute` raises the exception under test.

**I1 (must): any `compute` exception errors only its own check.**
Given, on DuckDB **and** SQLite, a table `t` with 3 rows:

```yaml
dataset: t
datasource: <backend>
checks:
  - explodes(id) > 0
  - row_count > 0
  - missing_count(id) = 0
```

When `explodes`' `compute` raises `ZeroDivisionError("boom")`, then
`explodes(id) > 0` is `error` with message `internal error in explodes:
boom`, `row_count > 0` is `pass` (`3`), and `missing_count(id) = 0` is
`pass`. The CLI exits 2 (an error, and no failure). The traceback is
logged to **stderr** at ERROR level, naming the check, and never goes
to stdout. Repeat this for `OverflowError`, `KeyError("x")` and
`AttributeError`. Each errors only its own check.

**I2 (must): the messages users rely on are unchanged.** A
`TypeError`/`ValueError` from `compute` keeps today's message, the
exception text alone. For example `freshness needs a date or timestamp
column, got int` for `freshness(id) < 1d` on an `INTEGER` column, and
`Invalid isoformat string: '29/09/2026 10:00'` for the SQLite case in
the table above. Neither gains an `internal error` prefix.

**I3 (must): an exception in evaluation is isolated too.** When
`evaluate()` raises for one check (planted by monkeypatching it for one
check id), that check is `error` with `internal error in <metric>: …`,
and the other checks on the dataset report normally.

**I4 (must): the dataset-wide safety net still catches what is not per
check.** An exception in planning or execution (planted in
`plan_dataset`) still errors every check on that dataset with
`internal error: …`. Other datasets in the run are unaffected. This is
today's behaviour, and the test pins it.

**I5 (should): the history and JSON agree.** In I1, the stored result
and `run --output json` carry the same `error` outcome and message for
`explodes(id) > 0`, and `pass` for the others.

## Non-goals

- `min`/`max` on timestamp columns. They are numeric metrics
  (`Unit.NUMBER`). With `pytz`, `max(loaded_at)` changes from the `pytz`
  error to that metric's usual "not a number" error, like a `TIMESTAMP`
  column.
- Rewording the `pytz` error for users who install `duckdb` without the
  extra. The documented install brings it.
- Setting DuckDB's session `TimeZone` on tablewatch's connections. It
  would change how user-written `where:`/`filter:` SQL such as
  `loaded_at::date = current_date` behaves. That is a separate question
  (see Q2).
- Whether a newest row in the future should `warn` (the owner question
  from iteration 7), or how `infinity` is treated. F8 only pins that
  zoned and naive columns agree.
- Postgres `timestamptz`. psycopg already returns aware values, and
  spec 002 covers them.
- New wording for `error` messages beyond the `internal error in
  <metric>:` prefix that I1 needs.

## Design notes

- **Rules.** Option A touches no rule. Rule 1: freshness is still one
  `AggregateMeasure`. Rule 2: the age is still `now − newest` in Python,
  and no SQL changes. Rule 3: the value reaches Python as a `datetime` on
  every backend, which is what `_as_datetime` already expects from
  Postgres. **Rule 7** is I-42's reason to exist: I1 to I4 make "error on
  the checks they affect" true for `compute` and `evaluate`. The exit
  codes are unchanged (I1 exits 2 today too, just with three errors
  instead of one).
- **Who builds what.** The `duckdb` extra belongs to the
  platform-engineer (PROCESS.md: extras). The widened `try` in
  `engine/runner.py` and its tests belong to the tech lead.
- **Dependency hygiene.** Floor `pytz>=2024.1` or whatever the
  security-reviewer prefers. No upper cap: pytz uses calendar versions
  and has a stable API. `pytz` is only a label for DuckDB's output zone.
  Conversion to the datasource zone stays in `zoneinfo`
  (`freshness.py`), so tz-database skew between pytz and ICU can only
  affect the offset DuckDB attaches, not the instant (verified in the
  ambiguous hour and the LMT case above).
- **I-42 shape (for the architect).** In `_run_dataset`, the per-check
  `try` wraps both `compute` and `evaluate`. `TypeError`/`ValueError`
  keep `str(exc)` (I2). Any other `Exception` becomes `internal error in
  <metric>: <exc>`, and `log.exception` names the check id. The outer
  safety net stays for planning and execution (I4).

### Open questions for the tech lead

- **Q1 (tech lead / architect).** `except Exception` per check, or a
  named set (`ArithmeticError`, `LookupError`, `AttributeError`,
  `TypeError`, `ValueError`)? The PM prefers `Exception`: the outer net
  already uses it, and a plugin can raise anything. `KeyboardInterrupt`
  and `SystemExit` are not `Exception`, so they still stop the run.
- **Q2 (architect, record only).** Should tablewatch pin DuckDB's
  session `TimeZone`? Today `where: loaded_at::date = current_date`
  means something different on a laptop in Singapore and on a UTC CI
  runner. This is not in this slice, and the backlog is frozen, so
  record the answer in the iteration log.

## Reviewers required

- **qa-engineer:** always.
- **data-steward:** always. Owns F9 and checks the zone semantics in
  F3 and F4.
- **security-reviewer:** **required**. A new dependency (`pytz`) is a
  PROCESS.md trigger. Under fallback D it is still asked to confirm the
  cast is not user-controlled SQL.
- **architect:** required. `src/tablewatch/engine/runner.py` changes
  (I-42), and `pyproject.toml` extras change.
- ui-engineer: not involved (no UI change).

## Size

**S.** One dependency line in two places plus the lock file, one widened
`try` in `engine/runner.py`, and tests: F1 to F6 on DuckDB, I1 to I4 on
DuckDB and SQLite.
