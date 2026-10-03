# Spec 024: Metric errors name the column's kind, never a row value; text is not a number (I-30)

- **Track:** full (row data reaching stored results and the API; results semantics: some outcomes move from `pass`/`fail` to `error`; the metric contract in `metrics/base.py`).
- **Size:** S.
- **Reviewers:** security-reviewer (REFINE Q1–Q2), architect (REFINE Q3–Q4), data-steward (REFINE Q5–Q6 + VERIFY), qa-engineer (VERIFY).

## Problem and persona

Priya runs `tw serve` for her team; Sam reads a failing check in the UI. Today a text value from the
data becomes the stored, served error message (`could not convert string to float: 'bob@x.com'`,
`Invalid isoformat string: 'zzz-secret'`), so an email, an id or a secret in a mistyped column lands in
the results store, the JSON report, the API and notifications (security F1, iteration 5). Worse (F10,
iteration 23): `min`/`max` on a text column compare strings and **pass** with a wrong number, and
`avg`/`sum` mean different things on each database (rule 3). Users cope by not noticing.
Research: Soda treats numeric metrics on TEXT columns as incalculable and reports a non-numeric value as
"not evaluated", not a scan failure ([Soda numeric metrics](https://docs.soda.io/soda-cl/numeric-metrics.html),
[soda-core#2858](https://github.com/sodadata/soda-core/pull/2858)).

## Measured today (`09a2c2e`, DuckDB VARCHAR / SQLite TEXT, values `'10.5','9','20'`)

| Check | DuckDB | SQLite |
| --- | --- | --- |
| `min(amt) > 0` / `max(amt) > 0` | pass 10.5 / pass **9.0** (string order) | same |
| `avg(amt)`, `sum(amt)` | error `Binder Error: No function matches … 'avg(VARCHAR)'…` | pass 13.17 / 39.5 (coerced) |
| `avg(email)`, `sum(email)` (no numbers) | Binder Error | **fail, value 0.0** |
| `max(email)` | error `could not convert string to float: 'bob@x.com'` | same |
| SQLite REAL column with one `'N/A'`: min / max / avg / sum | — | pass 5 / error quoting `'N/A'` / pass 4.0 / pass 12 |
| `freshness(ts)`, non-ISO text | error `Invalid isoformat string: 'zzz-secret'` | same |
| `sql_metric > 0`, query returns text | error quoting the value | same |
| `min(d)` on a DATE column | error `float() argument must be … not 'datetime.date'` | n/a |
| `min(b)` on a BOOLEAN column | pass 1.0 | n/a |

There is no `stddev` metric; nothing to change there. Paths where a value reaches a message: `as_float`
(`metrics/base.py`) and `fromisoformat` (`freshness.py`) → `runner._run_dataset`'s
`except (TypeError, ValueError)` → `_short_error`; `_internal_error` and the dataset-wide
`internal error: …` net (exception text, first line, 500 chars); `executor.error_message` (driver text,
`conn` failures, per-measure). `evaluate`/`format_value` only format floats and the metric's own `detail`.

## Scenarios

Fixture: tables `t` on a DuckDB and a SQLite datasource, as above, plus `row_count > 0` on each.
"Both" means DuckDB and SQLite; each must row is a test on both (rule 3). Wording is proposed; Q5.

| id | | Given | Expected |
| --- | --- | --- | --- |
| S1 | must | `min(amt) > 0`, `max(amt) > 0`, text column of numerals, both | `error`, `min needs a numeric column; got text` (resp. `max`); `row_count > 0` passes; exit 2. F10's strict xfail in `tests/test_files_datasets.py` is removed and passes |
| S2 | must | `avg(amt) > 0`, `sum(amt) > 0`, same column, both | `error`, `avg needs a numeric column; got text` (resp. `sum`) — not `Binder Error`, not a number |
| S3 | must | `max(email) > 0`, `avg(email) > 0`, both | same message; nothing from the column in message, JSON, store or `/api/v1` |
| S4 | must | SQLite REAL column holding `1, 'N/A', 3` (`mixed`); `min`/`max`/`avg`/`sum(mixed) > 0` | each `error`, `<metric> needs a numeric column; found a non-numeric value` — not `got text` (Q5: the column is declared numeric, so "got text" would mischaracterise it; the row is the problem) |
| S5 | must | `freshness(ts) < 1d`, `ts` text `'zzz-secret'`, both | `error`, `freshness needs a date or timestamp column, or ISO-8601 text; got other text` |
| S6 | must | `freshness(ts)` on ISO-8601 text (SQLite) | unchanged: passes or fails on age, message `newest row at …` |
| S7 | must | `sql_metric > 0` with `query: "select max(email) from t"`, both | `error`, `sql_metric's query must return a number; got text` |
| S8 | must | a metric whose `compute` raises `ValueError("row-secret")` (planted) | `error`, `internal error in <metric> (ValueError)`; `row-secret` in no message, JSON, store or API; traceback to stderr only (Q1) |
| S9 | must | an exception escaping to the dataset net, text `row-secret` | `internal error (KeyError)` on its checks; same assertions |
| S10 | must | numeric columns: INTEGER, DOUBLE/REAL, DECIMAL (DuckDB), a Postgres `Decimal` fed to `compute` | values and outcomes identical to today, both |
| S11 | should | `min(d) > 0` on a DuckDB DATE column; `min(b) > 0` on BOOLEAN | `min needs a numeric column; got date` / `… got boolean` (Q6: boolean is not numeric, even though DuckDB coerces it and today passes 1.0) |
| S12 | should | Postgres `text` column, `min` and `avg` | same messages as S1/S2: `compute` unit test for `str`; the driver path as Q4 decides |
| S13 | must | the metric contract | `metrics/base.py` documents: an exception message never includes a value from the data; a metric raises the safe error type (Q3) |
| S14 | must | docs | `docs/check-language.md`: `min max avg sum` need a numeric column; `freshness` takes a date, timestamp or ISO-8601 text. README: history recorded before this release is not scrubbed |

## Non-goals

- Driver error text from **user-written SQL** (`condition:`, `where:`, `sql_metric`'s query) — e.g. DuckDB
  `Conversion Error: Could not convert string 'N/A' to DOUBLE` — stays as is; redacting it is I-31.
- Scrubbing existing history. No store revision; check identity and exit codes unchanged.
- `valid_min`/`valid_max` on a text column (DuckDB Binder Error; SQLite compares text to numbers and
  counts every row invalid): same family, other metric; it belongs to I-13's "type suitability" (folded there, freeze).
- Casting numeric text to numbers (`avg(cast(amt as double))` is the user's `sql_metric`).

## Decisions (REFINE: Q1–Q2 security, Q3–Q4 architect, Q5–Q6 data-steward)

- **D1 (Q1, R1–R3).** A stored, reported or served message names the metric and a fixed column kind
  (`text`, `other text`, `date`, `timestamp`, `boolean`, `binary`), never a value. Every other
  exception from `compute`, `_internal_error` or the dataset net stores only its class name:
  `internal error in <metric> (<Class>)` or `internal error (<Class>)`. The traceback goes to stderr
  only, and the README says stderr can hold row values at ERROR level.
- **D2 (Q2, R4–R6).** `min`/`max` values and freshness's `newest row at …` are results by design.
  The executor's failed-scan `log.info` stays. Driver text from user SQL is I-31. Specs 018 D7 and
  021 D1 keep their fixed messages, and 018's "revisit with I-30" now reads "with I-31".
- **D3 (Q3).** `MetricInputError(Exception)` (not a ValueError) in `metrics/base.py` is the only
  exception whose text is shown; its text is built from constants and `kind_of()` only. The runner's
  `except (TypeError, ValueError)` branch goes. `as_float` becomes `numeric(value, what)`, raising it.
  `freshness` wraps its parse errors in it.
- **D4 (Q4).** The type is decided in Python from the fetched value. `MetricContext.type_probes(col)` adds
  `MIN` and `MAX` of the scoped column (deduped with `min`/`max`), so the scan stays one; `missing_*`/
  `invalid_*` add them only when an option compares with numbers only (VERIFY: DuckDB's conversion
  error quoted a row). A new
  `Metric.check_input(ctx, values)` hook (default no-op) runs before measure errors are reported, so
  DuckDB/Postgres bind errors on `avg(VARCHAR)` become S2's message. Postgres is covered by unit tests
  on `str`/`Decimal`/`bool`/`date`, and a DSN-gated test waits for I-14.
- **D6 (VERIFY).** A database's conversion-error text (it quotes the value) is never stored for a measure;
  it reads `a value in the column could not be converted: …`. An empty scope on DuckDB still shows
  `avg(VARCHAR)`'s bind error (strict xfail; not added, freeze).
- **D5 (Q5, Q6; data-steward).** A text column of numerals on SQLite errors. Today it returns a
  string-ordered wrong number, and rule 3 means the same check means the same thing. A steward who
  wants that casts in a `sql_metric`. S4 (a stray value in a numeric column) says `found a
  non-numeric value`, not `got text`. Boolean is not numeric (`got boolean`): DuckDB coerces it,
  Postgres refuses it.
