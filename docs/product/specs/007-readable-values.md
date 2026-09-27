# Spec 007: Readable values and messages on every surface

| | |
| --- | --- |
| Backlog item | I-24 (from iteration 3's data-steward acceptance; impact raised in iteration 4 REFINE) |
| Features | E0 (CLI output), C2 (overview), C4 (check detail): hardening |
| Phase | 2 (`0.2.0`) |
| Size | S (the structured-field half is split off now, as I-40; see "Size") |
| Depends on | nothing open. Touches only code that shipped in Phase 1 and iterations 2–6 |
| Branch | `iter/007-readable-values` |
| Status | **shipped** (iteration 7, PR #12, reviewed 2026-09-28: 19/19 scenarios; see ITERATIONS.md). Was **ready** (iteration 7 PLAN, 2026-09-27, against `main` at `940c776`; REFINE settled the same day: data-steward and architect, see "REFINE: decisions"). Every value and message below was reproduced by running `main` |

## Problem and persona

**Sam, data steward (Singapore, GMT+8).** "The check says it passed with
a value of `1h`. Next to it the message says `newest
2026-09-26T11:33:48.035115+00:00`. My clock says 20:33. If the newest row
was at 11:33, it's nine hours old and the check should have failed. Which
one is lying?" Neither is: the message is in UTC and does not say so in
words anyone reads. The zone offset (8h) is larger than the threshold
(6h), so on the one check whose whole meaning is a time, the message
reads as the opposite of the verdict (spec 004, "REFINE: data-steward
decisions").

**Sam, again, on the schema check.** "`schema` … `0`. Zero what? Zero
columns?" A passing `schema` check shows a bare `0` in every place a
value is shown, because its value is a count of violations and the
check's name is just `schema`.

**Dana, data engineer.** "The freshness message is in UTC, but my
datasource is `timezone: Asia/Singapore`, because the column holds local
time. The table says the newest row is `13:17:11`; tablewatch says
`05:17:11+00:00`. I have to do the arithmetic to check it's the same
row." She also sees microseconds she never asked for.

**How they cope today.** The README tells Sam to read the age in the
value column and ignore the timestamp in the message (iteration 4). The
page labels its own times with the viewer's zone so they are not
confused with the message (spec 004 D11, D12). Both are workarounds for
the text itself.

**Others.** dbt records `max_loaded_at`, `snapshotted_at` and
`max_loaded_at_time_ago_in_s`, computing the age in Python "to handle
timezone complexity" ([dbt: sources.json](https://docs.getdbt.com/reference/artifacts/sources-json)).
Soda's freshness diagnostics give both the column's maximum as found and
in UTC, and "now" in both forms ([Soda: freshness checks](https://docs.soda.io/sodacl-reference/freshness)).
Both keep the timestamp as a structured field; tablewatch borrows that for
later (I-40) and, now, the idea that the timestamp is shown in a named
zone, as the table holds it.

## Outcome

After this ships, on every surface (console, JSON report, JUnit, the
results store, the API, the web UI):

- a freshness message says what the timestamp is and names its zone in
  words, to the second: `newest row at 2026-09-27 09:47:30 UTC`, or, on a
  datasource with `timezone: Asia/Singapore`, `newest row at 2026-09-27
  09:47:30 Asia/Singapore (UTC+08:00)`, which is what Dana sees when she
  queries the table;
- a newest row in the future says so, with the likely cause;
- a `schema` check's value reads `0 problems`, `1 problem`, `2 problems`.

The numbers do not change: `value`, outcomes, exit codes, check ids and
the SQL are exactly as before. Results recorded before this version keep
their old text; nothing is rewritten.

## The contract (what changes, what does not)

| Surface | Changes | Does not change |
| --- | --- | --- |
| `message` of a `freshness` result | Text form (F1–F6, F8) | Present/absent exactly as before; `no timestamps in scope` unchanged; the rule prefix (`expected …`, `fail when …; `, `warn when …; `) unchanged |
| `display_value` of a `schema` result | `N problem(s)` (S1) | `—` when there is no value |
| `display_value` of every other metric | nothing | `format_value` by unit, as today |
| `value` | nothing | Freshness in seconds, schema a count, as today |
| JSON report | the two strings above | Shape, keys, `schema_version` **stays 1** (E3) |
| API `/api/v1` and `openapi.json` | the two strings above, in newly recorded results | Shape, schemas, `v1` |
| Results store | newly recorded rows carry the new text | No migration, no new column; `display_value` still fits `String(100)` |
| Outcomes and exit codes (0/1/2/3) | only F8: a dataset that is `error` today because formatting a freshness timestamp overflowed gets its real outcomes | Contract untouched (E4) |
| Check ids | nothing | `derive_check_id` untouched; `tests/golden/retail-list.txt` unchanged |
| SQL | nothing | `tests/golden/retail-compile*.txt` unchanged (rule 1, rule 2) |

`schema_version` stays 1 because no key is added, removed, renamed or
retyped. The texts of `message` and `display_value` have never been part
of that contract (spec 001: "`display_value` is the same value formatted
for people"; spec 002: "Clients that chart or compare use `value`"). A
consumer that parsed the ISO timestamp out of `message` breaks; the
CHANGELOG says so under **Changed**, and points to `value` (the age in
seconds). The JSON report's own timestamp form stays I-25's.

## Acceptance scenarios

### Fixture (every scenario below unless it says otherwise)

A fixed run time, **`now = 2026-09-27T12:00:00Z`**, passed to
`run_checks(..., now=...)` (the CLI has no `--now`; scenarios that go
through the CLI say so and match a pattern instead). One row, on DuckDB
**and** SQLite (rule 3; SQLite holds the timestamps as text):

| column | DuckDB type | value |
| --- | --- | --- |
| `id` | `INTEGER` | `1` |
| `loaded_at` | `TIMESTAMP` | `2026-09-27 09:47:30.654321` |
| `nines_at` | `TIMESTAMP` | `2026-09-27 09:47:30.999999` |
| `future_at` | `TIMESTAMP` | `2026-09-27 19:00:00` |
| `skew_at` | `TIMESTAMP` | `2026-09-27 12:00:20` |
| `skew60_at` | `TIMESTAMP` | `2026-09-27 12:01:00` |
| `skew61_at` | `TIMESTAMP` | `2026-09-27 12:01:01` |
| `far_at` | `TIMESTAMP` | `2026-09-29 14:00:01` |
| `day` | `DATE` | `2026-09-26` |
| `day_future` | `DATE` | `2026-09-28` |
| `empty_at` | `TIMESTAMP` | `NULL` |
| `aware_at` | (SQLite only, text) | `2026-09-27 17:47:30+08:00` |

(The data-steward added `nines_at`, `skew60_at`, `skew61_at`, `far_at` and
`day_future` in REFINE, and the `lake_ny` and `lite_ny` datasources below.
Every value quoted for them was measured on `main`; the messages were
produced by a scratch prototype of the rules below, since the new code
does not exist yet.)

`tablewatch.yml`:

```yaml
name: readable
datasources:
  lake:
    type: duckdb
    path: lake.duckdb
  lake_sgt:
    type: duckdb
    path: lake.duckdb
    timezone: Asia/Singapore
  lake_london:
    type: duckdb
    path: lake.duckdb
    timezone: Europe/London
  lite:
    type: sqlite
    path: lite.db
  lite_sgt:
    type: sqlite
    path: lite.db
    timezone: Asia/Singapore
  lake_ny:
    type: duckdb
    path: lake.duckdb
    timezone: America/New_York
  lite_ny:
    type: sqlite
    path: lite.db
    timezone: America/New_York
```

`checks/lake_ny.yml` (and `checks/lite_ny.yml` with `datasource:
lite_ny`). The columns hold UTC but the datasource says New York: the
misconfiguration F5 exists to catch.

```yaml
dataset: events
datasource: lake_ny
checks:
  - freshness(loaded_at) < 6h
  - freshness(loaded_at):
      name: Stale feed
      warn: when > 1d
```

`checks/lake.yml` (and `checks/lite.yml`, identical but for
`datasource: lite`):

```yaml
dataset: events
datasource: lake
checks:
  - freshness(loaded_at) < 6h
  - freshness(loaded_at):
      name: Stale feed
      fail: when > 1h
  - freshness(future_at) < 6h
  - freshness(skew_at) < 6h
  - freshness(day) < 2d
  - freshness(empty_at) < 6h
  - schema:
      required_columns: [id, loaded_at]
```

`checks/lake_bad.yml` (and `checks/lite_bad.yml`; a second `schema` check
on one dataset needs its own file today, because options do not feed the
check id):

```yaml
dataset: events
datasource: lake
checks:
  - schema:
      name: Schema with problems
      required_columns: [id, nope]
      forbidden_columns: [loaded_at]
```

`checks/lake_sgt.yml` (and `checks/lite_sgt.yml` with `datasource:
lite_sgt`):

```yaml
dataset: events
datasource: lake_sgt
checks:
  - freshness(loaded_at) < 12h
  - freshness(loaded_at):
      name: Stale feed
      fail: when > 1h
```

**Today, on `main` (`940c776`), verified by the PM** — values and display
values that must not change:

| datasource | check | outcome | `value` | `display_value` | `message` today |
| --- | --- | --- | --- | --- | --- |
| lake, lite | `freshness(loaded_at) < 6h` | pass | 7949.345679 | `2h 12m` | `newest 2026-09-27T09:47:30.654321+00:00` |
| lake, lite | Stale feed | fail | 7949.345679 | `2h 12m` | `fail when > 1h; newest 2026-09-27T09:47:30.654321+00:00` |
| lake, lite | `freshness(future_at) < 6h` | pass | -25200.0 | `-7h` | `newest 2026-09-27T19:00:00+00:00` |
| lake, lite | `freshness(skew_at) < 6h` | pass | -20.0 | `-20s` | `newest 2026-09-27T12:00:20+00:00` |
| lake, lite | `freshness(day) < 2d` | pass | 129600.0 | `1d 12h` | `newest 2026-09-26T00:00:00+00:00` |
| lake, lite | `freshness(empty_at) < 6h` | fail | null | `—` | `no timestamps in scope` |
| lake, lite | `schema` | pass | 0.0 | `0` | null |
| lake, lite | Schema with problems | fail | 2.0 | `2` | `expected = 0; missing column nope; forbidden column loaded_at is present` |
| lake_sgt, lite_sgt | `freshness(loaded_at) < 12h` | pass | 36749.345679 | `10h 12m` | `newest 2026-09-27T01:47:30.654321+00:00` |
| lake_sgt, lite_sgt | Stale feed | fail | 36749.345679 | `10h 12m` | `fail when > 1h; newest 2026-09-27T01:47:30.654321+00:00` |
| lake_london | `freshness(loaded_at) < 6h` | pass | 11549.345679 | `3h 12m` | `newest 2026-09-27T08:47:30.654321+00:00` |
| lite | `freshness(aware_at) < 6h` | pass | 7950.0 | `2h 12m` | `newest 2026-09-27T09:47:30+00:00` |
| lake, lite | `freshness(nines_at) < 6h` | pass | 7949.000001 | `2h 12m` | `newest 2026-09-27T09:47:30.999999+00:00` |
| lake, lite | `freshness(skew61_at) < 6h` | pass | -61.0 | `-1m 1s` | `newest 2026-09-27T12:01:01+00:00` |
| lake, lite | `freshness(day_future) < 6h` | pass | -43200.0 | `-12h` | `newest 2026-09-28T00:00:00+00:00` |
| lake_ny, lite_ny | `freshness(loaded_at) < 6h` | pass | -6450.654321 | `-1h 47m` | `newest 2026-09-27T13:47:30.654321+00:00` |

### Freshness messages (tech lead, pytest, DuckDB and SQLite)

**F1: the timestamp says what it is, in the datasource's zone, to the
second** `must`
- Given the fixture, on `lake` and on `lite`
- When the checks run
- Then `freshness(loaded_at) < 6h` passes with `value` 7949.345679,
  `display_value` `2h 12m`, and `message` exactly
  `newest row at 2026-09-27 09:47:30 UTC`.
- And Stale feed fails with the same value and `message` exactly
  `fail when > 1h; newest row at 2026-09-27 09:47:30 UTC`.
- And no message contains `T`-separated ISO text, a `+00:00` offset or
  fractional seconds. Fractional seconds are **truncated**, never
  rounded, so the shown second is never later than the row:
  `freshness(nines_at) < 6h` passes with `value` 7949.000001 and
  `message` exactly `newest row at 2026-09-27 09:47:30 UTC` (not `:31`).
  The age (`value`) still uses the full precision.

**F2: a datasource with a `timezone` shows its own zone, named** `must`
- Given the fixture, on `lake_sgt` and on `lite_sgt`
- When the checks run
- Then `freshness(loaded_at) < 12h` passes with `value` 36749.345679,
  `display_value` `10h 12m`, and `message` exactly
  `newest row at 2026-09-27 09:47:30 Asia/Singapore (UTC+08:00)`
  (the wall-clock time the column holds, which is what Dana sees when she
  queries the table; today's message shows `01:47:30+00:00`).
- And Stale feed fails with `message` exactly
  `fail when > 1h; newest row at 2026-09-27 09:47:30 Asia/Singapore (UTC+08:00)`.
- The zone is the datasource's `timezone` key as written in
  `tablewatch.yml`, followed by its UTC offset **at that instant** in
  `(UTC±HH:MM)`. When the key is `UTC` (the default) the offset is left
  out: `UTC`, never `UTC (UTC+00:00)`. Any other key keeps its offset,
  including `Etc/UTC` (`Etc/UTC (UTC+00:00)`): the rule is "the key as
  written", with one exception, not a list of aliases. West of UTC the
  sign is an ASCII hyphen-minus: `America/New_York (UTC-04:00)`. Offsets
  with seconds (pre-1900 local mean time, e.g. Singapore's `+06:55:25` in
  year 1) are shown to the minute, truncated: `(UTC+06:55)`.
- **A naive value is shown as the column holds it.** The wall-clock time
  in the message is the stored value, never a round trip through UTC and
  back; the offset is the one the age was computed with. So when the
  `timezone` key is wrong, the message still shows what is in the table,
  and the age and F5's note show the misreading. (A round trip through
  UTC would show a time that is not in the table at a DST gap; see F3.)

**F3: the offset is the one in force at that instant** `should`
- Given the fixture, on `lake_london` (British Summer Time on 27
  September)
- Then `freshness(loaded_at) < 6h` passes with `value` 11549.345679,
  `display_value` `3h 12m`, and `message`
  `newest row at 2026-09-27 09:47:30 Europe/London (UTC+01:00)`.
- And a row at `2026-01-15 09:47:30` on the same datasource shows
  `(UTC+00:00)`.

**F3a: DST edges and historical offsets** `should` (Python-level test of
the formatter and `compute`, `now = 2026-09-27T12:00:00Z`; the values
were measured on `main`)
- **Gap.** A naive `2026-03-29 01:30:00` on `Europe/London` (a time that
  does not exist: clocks went from 01:00 to 02:00) gives `value`
  15762600.0 and `message`
  `newest row at 2026-03-29 01:30:00 Europe/London (UTC+00:00)`: the
  wall clock as stored, never `02:30:00`, and the offset the age used.
- **Fold.** A naive `2025-10-26 01:30:00` on `Europe/London` (a time
  that happened twice) is read as the **first** occurrence, as today
  (`fold=0`): `value` 29071800.0, `message`
  `newest row at 2025-10-26 01:30:00 Europe/London (UTC+01:00)`. The
  first occurrence is the older instant, so the check never reads the
  data as fresher than it could be.
- **History.** A naive `1970-01-01 00:00:00` on `Asia/Singapore` gives
  `value` 1790537400.0 and `(UTC+07:30)`, Singapore's offset in 1970:
  "the offset at that instant" is the tz database's, not today's.

**F4: a zone-aware timestamp is shown in the datasource's zone** `should`
- Given the fixture, on `lite` (`timezone` UTC), column `aware_at` holding
  `2026-09-27 17:47:30+08:00`
- Then `freshness(aware_at) < 6h` passes with `value` 7950.0,
  `display_value` `2h 12m`, and `message`
  `newest row at 2026-09-27 09:47:30 UTC`.
- There is one zone per datasource; a message never shows the zone the
  value happened to carry. (DuckDB `TIMESTAMPTZ` cannot be tested here:
  it errors on `main` for a missing `pytz`, see I-41.)

**F5: a newest row in the future says so** `must`
- Given the fixture, on `lake` and on `lite`
- Then `freshness(future_at) < 6h` passes with `value` -25200.0,
  `display_value` `-7h` (unchanged), and `message` exactly
  `newest row at 2026-09-27 19:00:00 UTC, 7h in the future; check the datasource's timezone`.
- And `freshness(skew_at) < 6h` (20 seconds ahead) passes with `value`
  -20.0, `display_value` `-20s` and `message` exactly
  `newest row at 2026-09-27 12:00:20 UTC`: the note appears only when the
  newest row is **more than 60 seconds** ahead, so ordinary clock skew
  between the database and the runner does not shout.
- **The boundary.** `freshness(skew60_at) < 6h` (`value` -60.0) has no
  note: `newest row at 2026-09-27 12:01:00 UTC`. `freshness(skew61_at)
  < 6h` (`value` -61.0, `display_value` `-1m 1s`) has one:
  `newest row at 2026-09-27 12:01:01 UTC, 1m 1s in the future; check the datasource's timezone`.
  The test is `value < -60` on the unrounded age.
- **The case it exists for.** On `lake_ny` and `lite_ny` (UTC data,
  `timezone: America/New_York`), `freshness(loaded_at) < 6h` passes with
  `value` -6450.654321, `display_value` `-1h 47m`, and `message` exactly
  `newest row at 2026-09-27 09:47:30 America/New_York (UTC-04:00), 1h 47m in the future; check the datasource's timezone`.
  Stale feed (`warn: when > 1d`) also passes, with the same message:
  the note is how Sam learns that a check passing every run is reading
  the column in the wrong zone.
- **The hint names the likely cause, and only a possible one.** A wrong
  `timezone` can shift a naive value by at most 26 hours (UTC+14 against
  UTC-12). Further ahead than that, the zone cannot be the cause; the
  usual one is a placeholder (`9999-12-31`) or a forward-dated row. So:
  - ahead by more than 60 s and at most 26 h (93600 s):
    `…, <duration> in the future; check the datasource's timezone`;
  - ahead by more than 26 h:
    `…, <duration> in the future; check for placeholder or future-dated values`.
  `freshness(far_at) < 6h` (`value` -180001.0, `display_value` `-2d 2h`)
  gives exactly
  `newest row at 2026-09-29 14:00:01 UTC, 2d 2h in the future; check for placeholder or future-dated values`.
- The duration in the note is `format_duration` of the absolute age,
  the same words as `display_value` uses. This is the case the README
  warns about (a naive local-time column read as UTC passes `< 6h` every
  time); the message now says it where Sam reads it. The note follows
  the rule prefix like any detail
  (`fail when …; newest row at …, 7h in the future; …`).

**F6: a date column shows a date** `should`
- Given the fixture, on `lake` (`DATE`) and on `lite` (text
  `2026-09-26`, exactly ten characters)
- Then `freshness(day) < 2d` passes with `value` 129600.0,
  `display_value` `1d 12h`, and `message` exactly `newest date 2026-09-26`.
- A date has no time of day; showing `00:00:00 UTC` invents one. The age
  is still measured from midnight in the datasource's zone, as today
  (documented in `docs/check-language.md`). The date form names no zone:
  a date has none, and the age in the value column already reflects it.
- And `freshness(day_future) < 6h` passes with `value` -43200.0,
  `display_value` `-12h`, and `message` exactly
  `newest date 2026-09-28, 12h in the future; check the datasource's timezone`
  (F5's note applies to dates with the same thresholds).
- On SQLite, the text `2026-09-26 00:00:00` is a timestamp, not a date:
  it shows `newest row at 2026-09-26 00:00:00 UTC`. Only a value that
  arrives as a `date` (DuckDB) or as exactly ten characters of ISO date
  text (SQLite) is a date.

**F8: an extreme value never breaks the dataset** `must`
- Given a SQLite table `contracts` on `lite_ny`
  (`timezone: America/New_York`) with one row, `loaded_at`
  `2026-09-27 09:47:30` and `valid_to` `9999-12-31 23:59:59` (an SCD2
  open-ended row, as every banking warehouse has), and

  ```yaml
  dataset: contracts
  datasource: lite_ny
  checks:
    - row_count > 0
    - freshness(loaded_at) < 12h
    - freshness(valid_to) < 12h
  ```
- When the checks run
- Then `row_count > 0` passes, `freshness(loaded_at) < 12h` passes, and
  `freshness(valid_to) < 12h` passes with `value` -251611808399.0 and
  `message` exactly
  `newest row at 9999-12-31 23:59:59 America/New_York (UTC-05:00), 2912173d 16h in the future; check for placeholder or future-dated values`.
- **Today, on `main`, all three are `error` with
  `internal error: date value out of range`**: the message's
  `astimezone(UTC)` overflows past year 9999, and an exception in one
  metric's `compute` errors every check on the dataset. The same happens
  for `0001-01-01 00:00:00` on `Asia/Singapore`. After this change the
  formatter must not raise for any value `_as_datetime` returns; F2's
  "as stored" rule already avoids the conversion for naive values. An
  aware value whose conversion overflows is shown in its own offset
  rather than raising (the tech lead chooses the fallback and tests it).
- And `0001-01-01 00:00:00` on `lake_sgt` gives `value` 63926132125.0
  and `newest row at 0001-01-01 00:00:00 Asia/Singapore (UTC+06:55)`
  `should`.

**F7: nothing else in freshness changes** `must`
- Given the fixture
- Then `freshness(empty_at) < 6h` fails with `value` null,
  `display_value` `—` and `message` `no timestamps in scope`, as today.
- And the same holds, with the same message, for `freshness(loaded_at)
  < 6h` with `where: id < 0` (a scope that matches nothing) and on a
  table with no rows: an empty scope is a data problem (`fail`), never an
  `error`, and never a message with a timestamp.
- And every `value` and outcome in the "Today" table above is unchanged,
  on both backends.

### Schema values (tech lead, pytest, DuckDB and SQLite)

**S1: a schema check's value names what it counts** `must`
- Given the fixture, on `lake` and on `lite`
- Then `schema` passes with `value` 0.0, `display_value` `0 problems`,
  and `message` null.
- And Schema with problems fails with `value` 2.0, `display_value`
  `2 problems`, and `message` unchanged:
  `expected = 0; missing column nope; forbidden column loaded_at is present`.
- And a schema check with one problem (`required_columns: [id, nope]`
  alone) shows `1 problem`.
- The noun is singular only for exactly 1; `0` takes the plural. Counts
  keep `format_value`'s thousands separator (`1,204 problems`).
- One word everywhere: the metric's `summary` (shown in editor hovers
  via the generated JSON schema), its module docstring, and the
  `schema` row of `docs/check-language.md` say "problems", not
  "violations" (Q2).
- `value` stays a bare number; only `display_value` changes, and only for
  `schema`. `missing_count`, `duplicate_count`, `failed_rows` and
  `row_count` keep their bare counts (non-goal N3).

### Every surface agrees (tech lead, pytest)

**E1: console, JSON and JUnit show the same text** `must`
- Given the fixture run
- When it is rendered by the console, JSON and JUnit reporters
- Then the JSON report's `results[].message` and `display_value` are the
  strings in F1–F7 and S1.
- And the console's VALUE column shows `2h 12m`, `0 problems`,
  `2 problems`, and its DETAIL column shows each freshness message **in
  full**, without the `…` clip, including the longest one in the fixture
  (Stale feed on `lake_sgt`, 76 characters:
  `fail when > 1h; newest row at 2026-09-27 09:47:30 Asia/Singapore (UTC+08:00)`)
  and F5's (88 characters). Today DETAIL is clipped at 70 characters
  (`output/console.py`, `_MAX_DETAIL`). **Decided in REFINE: the clip
  is raised to 200** (see "REFINE: decisions", R3). The schema message
  (72 characters) then also shows in full.
- **And a realistic freshness message is not clipped either** (added in
  REFINE): on a datasource named with a long zone, F5's note comes last,
  so a clip cuts exactly the part that explains the verdict. Given the
  fixture on `lake_ny`, the console shows `freshness(loaded_at) < 6h`'s
  DETAIL whole, 117 characters:
  `newest row at 2026-09-27 09:47:30 America/New_York (UTC-04:00), 1h 47m in the future; check the datasource's timezone`.
  With a rule that also catches the future
  (`freshness(loaded_at) between 0s and 6h`, which fails on `main` with
  `value` -6450.654321) the DETAIL is exactly 145 characters and appears
  whole, with no `…`:
  `expected between 0s and 6h; newest row at 2026-09-27 09:47:30 America/New_York (UTC-04:00), 1h 47m in the future; check the datasource's timezone`.
- **And the clip still bounds other text** (`should`): a message of 201
  characters or more (for example a driver error) is shown as its first
  199 characters and `…`, as `_clip` does today at 70.
- And JUnit's `<failure message=…>` for Stale feed on `lake` is exactly
  `2h 12m: fail when > 1h; newest row at 2026-09-27 09:47:30 UTC`, and for
  Schema with problems
  `2 problems: expected = 0; missing column nope; forbidden column loaded_at is present`.

**E2: the example project, end to end through the CLI** `must`
- Given `examples/retail` built with `build.py`
- When `tablewatch --project-dir examples/retail run --no-store --output json`
  runs
- Then it exits **1**, with 18 results: 10 pass, 2 warn, 6 fail (as
  today).
- And `fbc3aa0b93b66eee` (`schema` on `sales.orders`) has `value` 0.0 and
  `display_value` `0 problems`.
- And `a81b0374b0b04f06` (`freshness(created_at) < 6h`) has a `message`
  matching `^newest row at \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} UTC$`, and
  `41e58afff9c48a46` (Price feed freshness, warn) matches
  `^warn when > 1d; newest row at \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} UTC$`.
  (Freshness values depend on build time; do not assert them exactly.)
- And the table output (`run --no-store`) shows `0 problems` in the
  schema row's VALUE column.

**E3: the JSON report's contract** `must`
- Given E2's report
- Then `schema_version` is `1`, the top-level keys are `schema_version`,
  `run`, `results`, and each result has exactly the keys it has today
  (`tests/test_api_adversarial.py` already pins both; it passes
  unchanged).

**E4: outcomes, exit codes, ids and SQL** `must`
- Then `tests/golden/retail-list.txt`, `retail-compile.txt` and
  `retail-compile-sales.txt` are unchanged, and every existing exit-code
  test passes unchanged.

### The store, the API and the page (tech lead, pytest; data-steward by hand)

Runs on a time axis are spaced by a day, not seconds (iteration 4).

**H1: old results are shown as they were recorded** `must`
- Given a results store holding one run started `2026-09-26T12:00:00Z`,
  recorded by the previous version, with a `freshness(loaded_at) < 6h`
  result (`message` `newest 2026-09-26T09:47:30.654321+00:00`,
  `display_value` `2h 12m`) and a `schema` result (`display_value` `0`,
  `message` null). The test writes these rows as the old version did;
  it does not need the old code.
- And a second run of the same checks with this version at
  `2026-09-27T12:00:00Z`
- When `GET /api/v1/checks/{id}/history` is called for each
- Then the freshness history is, newest first,
  `newest row at 2026-09-27 09:47:30 UTC` then
  `newest 2026-09-26T09:47:30.654321+00:00` (verbatim).
- And the schema history's `display_value` is `0 problems` then `0`.
- And `GET /api/v1/checks` shows the new text in `latest`.
- And `tablewatch history <id>` prints both rows, each with its own text.
- Nothing rewrites, migrates or reformats a stored `message` or
  `display_value`, on read or on write.

**H2: the page shows messages verbatim** `must` (no frontend change
expected)
- Given H1's store, served by `tablewatch serve`
- Then on `/checks/<freshness id>` the history table's message column
  shows both texts exactly as the API returns them, and Latest result
  shows `newest row at 2026-09-27 09:47:30 UTC`; on `/checks/<schema id>`
  the value column shows `0 problems` and `0`. The page still does not
  reformat messages (spec 004 D12). The data-steward checks this by hand
  in a GMT+8 browser; if any frontend test pins today's text as *new*
  output (rather than as a recorded fixture), it is updated with the
  wording, not around it.

### Documentation (tech lead; data-steward reviews)

**D1** `must` The README's check-page section no longer says messages
"keep UTC": it says a freshness message names its zone (the datasource's
`timezone`), that results recorded before this version keep the old UTC
form, and that the age is in the value column.
**D2** `must` `docs/check-language.md`, "Freshness and time zones":
what the message says (F1, F2, F5, F6), with one example. The `schema`
row says the value is shown as "N problems".
**D3** `must` CHANGELOG under **Changed**: the freshness message's new
form and the schema value's wording, that `value` and `schema_version`
are unchanged, and that anyone parsing the timestamp out of `message`
should use `value` instead (written by the PM in REVIEW).
**D4** `must` (architect, REFINE) The README's JSON report section
(`## On servers`, `--output json`) and its API section
(`### The JSON API`) each say, in one sentence, that the text of
`message` and `display_value` is for people and not part of the
contract: it may change between versions, and a program should read
`value` and `outcome`. (It has never been part of it, see "The
contract"; this spec is the first to change it, so it is now written
down.)

## Non-goals

- **N1: No structured timestamp field.** The newest timestamp as its own
  field (store column, JSON key, API field) so the UI can show it in the
  viewer's zone is **I-40**, split off here. The message names its zone,
  which removes the misreading; showing it in the viewer's zone is a
  convenience.
- **N2: No rewrite of stored results.** Old messages stay in UTC ISO form;
  old schema values stay `0`. The page and the API show them verbatim.
- **N3: No change to other metrics' display.** `failed_rows` (a count of
  rows under a user's name such as "No negative amounts") and the other
  counts keep bare numbers. Whether `failed_rows` should say `1 row` is
  put to the data-steward in REFINE (Q2): yes, with `row_count`, as a
  follow-up, not this PR: **I-43** (two lines of data on the
  `count_noun` hook below, plus tests).
- **N4: No change to how the age is computed**, to `format_duration`, or
  to negative `display_value` (`-7h` stays). The note in F5 is in the
  message only.
- **N5: No "now" in the message.** The run's start time is already on
  every surface.
- **N6: The JSON report's own timestamps** (`started_at` and so on) are
  I-25's.
- **N7: DuckDB `TIMESTAMPTZ` columns** erroring on a missing `pytz` is
  I-41, not this spec (found in this PLAN).

## Design notes

- **Rule 2 (SQL counts, Python does the math).** All formatting is Python.
  The SQL is untouched (E4). The timestamp is converted to the
  datasource's zone in Python (`ZoneInfo`), never in SQL.
- **Rule 3 (same meaning on every database).** F1, F2, F5, F6 and S1 are
  tested on DuckDB and SQLite with identical expected strings. SQLite
  hands back text; `_as_datetime` already parses it. F6's "is a date" on
  SQLite is "a ten-character ISO date string"; the tech lead may choose a
  different test if it is stated and tested on both.
- **Where the formatting lives (decided in REFINE, architect).** The
  freshness message stays built in `Freshness.compute`
  (`metrics/builtin/freshness.py`), which has `ctx.timezone` and
  `ctx.now`. The timestamp and date formatting is **private to
  `freshness.py`**: putting it in `engine/evaluate.py` and calling it
  from the metric would make `metrics/` import `engine/`, reversing
  today's dependency direction. `format_duration` **moves out of the
  engine** to a module both can import without it (`metrics/base.py`
  beside `as_float` and `percent`, or a small `tablewatch/formatting.py`;
  tech lead's call) and is **re-exported from `engine/evaluate.py`**
  (`tests/test_engine.py` imports it there), so F5's note and
  `display_value` share one duration formatter and N4 holds.
  `_as_datetime` also reports whether the value arrived as a date (F6);
  the SQLite ten-character test lives there. This departs from BACKLOG's
  I-24 wording ("formatting stays in `engine/evaluate.py`"); the intent
  (Python, not SQL; rule 2) is kept.
- **Timezone name and offset.** `MetricContext.timezone` is already the
  `ZoneInfo` from `timezone_of(config)`; its `.key` is the name as
  written in `tablewatch.yml` (F2), and the offset is
  `newest.astimezone(ctx.timezone).utcoffset()` for aware values or the
  offset the age was computed with for naive ones. No new context field.
  The formatter must not raise for any value `_as_datetime` returns
  (F8).
- **The schema noun: a declarative hook (decided in REFINE,
  architect).** `Metric` gains
  `count_noun: ClassVar[tuple[str, str] | None] = None`, a
  `(singular, plural)` pair shown after a `count` value, in
  `metrics/base.py`. `Schema` sets `("problem", "problems")`.
  `format_value(unit, value, noun=None)` applies it only for
  `Unit.COUNT`, keeps `f"{round(value):,}"`, uses the singular only when
  the rounded value is 1, and leaves `—` for None unchanged.
  `CheckResult.display_value` (`engine/runner.py`) passes
  `self.check.metric.count_noun`. It is data, not a method, so
  formatting stays in `evaluate.py`; the JSON schema and check identity
  are unaffected. It is a new public attribute on the metric contract:
  the architect reviews it again in VERIFY.
- **Console clip (decided in REFINE).** `_MAX_DETAIL` goes from 70 to
  200 (E1). See R3 for why a single limit, not a freshness exemption.
- **Rule 7 and the exit-code contract.** No outcome changes except F8,
  where a dataset that errors today because formatting overflowed gets
  its real outcomes: that is rule 7 working as intended, not a change to
  the 0/1/2/3 contract (E2, E4).
- **Check identity.** Untouched (E4).
- **Security.** No trigger in PROCESS.md is touched: no dependency, no
  network, no new place written, no new data stored or exposed (the
  newest timestamp was already in `message`; F6 shows less of it).
  security-reviewer is not required. Spec 005's note stands:
  `message` can quote data values; this changes their form, not their
  presence.

### Open questions for REFINE (all settled; see "REFINE: decisions")

- **Q1 (architect).** The schema wording: a per-metric display hook on
  `Metric`, or a special case in `format_value`? If a hook, name it and
  say whether `failed_rows` should use it later (Q2).
- **Q2 (data-steward).** "problems" or "violations" (the docs' word
  today)? Should `failed_rows` say `1 row`/`3 rows` (a follow-up item if
  yes)?
- **Q3 (data-steward).** Show the timestamp in the datasource's zone (the
  PM's call, F2: it matches the table Dana queries, and one rule covers
  naive and aware columns) or always in UTC (spec 004 REFINE's first
  suggestion)? Either way the zone is named. If UTC, F2's expected text
  becomes `newest row at 2026-09-27 01:47:30 UTC` and F3 is dropped.
- **Q4 (data-steward).** "Age in words" (BACKLOG's requirement) is met by
  `display_value` (`2h 12m`), which every surface already shows next to
  the message, and by F5's `7h in the future`. The PM does not repeat the
  age inside the message (it would say `2h 12m` twice on the console and
  in JUnit). Confirm, or give the wording.
- **Q5 (data-steward).** F5's wording and its 60-second tolerance.

### REFINE: data-steward answers (2026-09-27)

Every value below was measured on `main` (`bce044a`) against the fixture
above; the new message strings come from a scratch prototype of these
rules applied to those values.

- **Q2: "problems".** A missing column or a wrong type is a problem with
  the table; "violation" is a compliance word and makes Sam ask "of
  what?". It is also the word the schema message's own items already
  imply (`missing column nope`), and the metric's code calls the list
  `problems`. The docs row and the metric summary change to match (S1),
  so one word is used everywhere. **`failed_rows`: yes, `1 row` /
  `3 rows`, as a follow-up.** "No negative amounts … `3`" leaves Sam to
  guess the unit; `3 rows` does not. The same follow-up should cover
  `row_count` (`1,204 rows`). `missing_count` and `duplicate_count` name
  their unit in the metric name already, and `sql_metric` cannot know
  one; leave them bare. If the architect's hook (Q1) is a noun pair on
  the metric, the follow-up is two lines of data plus tests.
- **Q3: the datasource's zone, named.** The stronger reason is not
  Dana's convenience but truthfulness: for a naive column (the common
  case, and the one that goes wrong) the datasource's zone shows the
  value exactly as stored whether or not `timezone` is right (F2's "as
  stored" rule). A UTC display would show a time *derived from* the
  configured zone, so when the configuration is wrong, the one number
  Sam can check against the table would also be wrong. With the zone
  named and the offset shown, Sam in GMT+8 can still convert, and a
  datasource left at `UTC` shows `UTC`. Keep F2 and F3; F3a and F8 follow
  from the same rule.
- **Q4: confirmed, with one condition.** `display_value` next to the
  message meets "age in words" on every surface today (console VALUE,
  JUnit's `<value>: <message>`, JSON, API, the page's value column).
  Repeating the age inside the message would say it twice. The condition:
  any future surface that shows `message` alone (notifications, I-06)
  must show `display_value` with it, or a freshness alert will carry a
  timestamp and no age. PM: please add that to I-06's acceptance.
- **Q5: 60 s is right; the wording gains a second hint.** Clock skew
  between a loader and the runner is seconds; the smallest offset
  difference between two real zones is 15 minutes, so any tolerance
  under 15 minutes separates skew from a zone error, and 60 s keeps
  ordinary skew quiet. The boundary is strict (`value < -60`, F5). The
  hint "check the datasource's timezone" is only true up to 26 hours
  ahead (the widest possible zone error); beyond that it misdirects Sam
  toward configuration when the data holds a placeholder such as
  `9999-12-31`, so the note there says
  `check for placeholder or future-dated values` (F5). The duration uses
  `format_duration` unchanged (N4), so a placeholder reads
  `2912173d 16h in the future`: ugly but true, and the date is right
  next to it.

### Found in REFINE, outside this spec (for the PM)

- **One metric's exception errors its whole dataset.** An exception in
  any metric's `compute` reaches `_run_dataset`'s safety net, so every
  check on the dataset, including `row_count`, becomes
  `internal error: …`. F8 removes the trigger this spec owns (the
  timestamp overflow); the isolation gap itself (a `compute` failure
  should error only its own check, as the executor already does for a
  failing measure) is a backlog item. Reproduced on `main`:
  `valid_to = 9999-12-31 23:59:59` on `timezone: America/New_York`
  errors `row_count > 0` on the same table. **Recorded as I-42**
  (BACKLOG).
- **A future row passes every freshness check.** F5 makes it visible;
  it is still a `pass` (N4 keeps outcomes). Whether a newest row more
  than 60 s ahead should `warn` by default is an outcome change, so a
  decision for the owner and a later spec, not this one. **Put to the
  owner in ITERATIONS.md (iteration 7); it does not stop the loop.**

### REFINE: decisions (PM, 2026-09-27)

- **R1: Q1 settled by the architect's `count_noun` hook** (Design
  notes). Q2–Q5 settled by the data-steward's answers above; the
  spec's scenarios already carry them (F2, F3, F3a, F5's second hint,
  F8, S1's "problems").
- **R2: Formatting placement follows the architect** (Design notes):
  timestamp formatting private to `freshness.py`; `format_duration`
  moved out of the engine and re-exported from `engine/evaluate.py`.
- **R3: E1's console clip is 200, for every message.** The
  data-steward needs the 145-character message whole and offered two
  options: no clip on freshness messages, or a limit of at least 160.
  The PM takes a single limit of 200, because (a) an exemption keyed on
  the metric would put a metric special case in a reporter, which the
  hook in R1 exists to avoid; (b) the longest freshness message this
  spec can produce is bounded: the longest tz key is 32 characters, and
  `fail when not between 0s and 6h; newest row at 9999-12-31 23:59:59
  America/Argentina/ComodRivadavia (UTC-03:00), 2912173d 16h in the
  future; check for placeholder or future-dated values` is 185; and
  (c) a clip still bounds driver error text, which is what the clip was
  for. DETAIL is the last column, so the wider limit costs no alignment.
  Wrapping DETAIL to the terminal's width is a follow-up (**I-44**),
  not this PR.
- **R4: D4 added** (architect): the README states that `message` and
  `display_value` text is not part of the contract.
- **R5: Q4's condition recorded on I-06.** Any surface that shows
  `message` alone (notifications) must show `display_value` with it;
  added to I-06's requirements in BACKLOG, to become an acceptance
  scenario in its spec.
- **R6: Size stays S.** REFINE added F8 (a `must` that changes one
  outcome, on a path this spec already rewrites), the placeholder hint,
  a one-attribute hook and D4. Each is a few lines beside code the spec
  already touches; there is still no store revision, no API or JSON
  shape change and no frontend change. If F8's fallback for an aware
  overflowing value turns out to need changes outside `freshness.py`,
  the tech lead stops and the PM splits it.
- **Follow-ups recorded in BACKLOG:** I-42 (per-check isolation of a
  `compute` exception), I-43 (`failed_rows` and `row_count` nouns),
  I-44 (console DETAIL wraps to the terminal).

## Reviewers required

- **qa-engineer** (always). Focus: truncation at `.999999`; offsets at a
  DST change and for half-hour and 45-minute zones (`Asia/Kolkata`
  `(UTC+05:30)`, `Asia/Kathmandu` `(UTC+05:45)`); a key of `Etc/UTC`;
  `-60s` against `-61s` for F5; a date string on SQLite that is not ten
  characters; very old rows (year 1970, year 9999); the console's column
  widths with a 200-character DETAIL and the clip at 201; old and new rows mixed in one
  history.
- **data-steward** (always). REFINE: Q2–Q5. VERIFY: H2 by hand in a GMT+8
  browser; D1 and D2.
- **architect** (touches `src/`; reviewed Q1 in REFINE and approved with
  follow-ups; in VERIFY checks the `count_noun` hook, the
  `format_duration` move and its re-export, and that `metrics/` still
  does not import `engine/`).
- **security-reviewer**: not required (see Design notes). The tech lead
  may call one if the build touches anything in PROCESS.md's list.
- **ui-engineer**: not required; no frontend change is expected. Consulted
  only if H2 finds a frontend test that pins today's text as new output.

## Size

**S** (re-confirmed in REFINE, R6). Two metrics' text (`freshness`,
`schema`), a `count_noun` attribute on the metric contract,
`format_duration` moved and re-exported, the console's clip width, F8's
no-raise formatting, tests on two backends, three docs. No store
revision, no API or JSON shape change, no frontend change.

**Split already applied (planned in iteration 4, applied now).** The
backlog item as written also asked "ideally" for a structured field the
UI can show in the viewer's zone. That needs a store column and an
Alembic revision, an additive JSON and API field, the OpenAPI document,
and frontend work: M on its own. It is **I-40**, scored in BACKLOG. This
spec ships the console, JSON, JUnit and store text first, as the tech
lead asked. The `failed_rows` and `row_count` nouns (Q2) are I-43, not
this PR.
