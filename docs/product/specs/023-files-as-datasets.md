# Spec 023: Files as datasets — CSV, Parquet and JSON through DuckDB (I-08)

- **Track:** full (new seams: dataset source, executor; a new datasource type in `tablewatch.yml`; file paths reach SQL; user SQL gains a file system to read; check identity for a path-named dataset).
- **Size:** REFINE grew it (the sandbox, R1–R7), so it is split: this spec is I-08 part 1. G3 (globs), S7–S8 (`schema` on files) and S5's glob rule stay in I-08 part 2.
- **Reviewers:** architect (REFINE Q1–Q3), security-reviewer (REFINE Q4–Q6), data-steward (REFINE Q7–Q8 + VERIFY), qa-engineer (VERIFY).

## Problem and persona

Dana receives partner extracts (`orders_2026-10-03.csv`, a Parquet drop from another team) and wants
to know they are fit **before** her pipeline loads them. Today tablewatch checks tables only, so she
loads the file into a scratch DuckDB first (a `build.py` like `examples/retail`'s), or checks it after
the load, when the bad rows are already in the warehouse. Phase 2, feature A8; the first increment to
touch the dataset-source and executor seams (`FEATURES.md`, "Modular seams").
Research: Soda reads files by creating DuckDB tables/views over `read_parquet` first
([Soda DuckDB](https://docs.soda.io/reference/data-source-reference-for-soda-core/duckdb/duckdb-advanced-usage));
dbt-duckdb names a file per source with `external_location` ([dbt-duckdb](https://github.com/duckdb/dbt-duckdb));
DuckDB confines file access with `enable_external_access`, `allowed_directories`, and has known bypasses
([Securing DuckDB](https://duckdb.org/docs/stable/operations_manual/securing_duckdb/overview.md),
[duckdb#26064](https://github.com/duckdb/duckdb/issues/26064)). We borrow "a path is the dataset", not
a view-building step.

## Behaviour

A new datasource type `files` names a directory; a check file on it names a file (or glob) relative
to that directory as its `dataset:`. The format follows the extension. The dataset is read in place by
an in-memory DuckDB (`duckdb` extra) as `read_csv` / `read_parquet` / `read_json`, in the **one** scan
of rule 1; nothing is copied or written. Every metric, `filter:` and `where:` works as on a table.

```yaml
# tablewatch.yml                       # checks/landing/orders.yml
datasources:                           datasource: drop
  drop:                                dataset: orders.csv
    type: files                        checks:
    root: landing     # rel. to project  - row_count = 5
    timezone: UTC                        - missing_count(email) = 0
```

## Scenarios

Fixture: project `landing-test` with the YAML above; `landing/orders.csv` (header `id,email,amount,created_at`,
5 rows, one `email` empty, `amount` numeric, `created_at` naive ISO timestamps 1 h old), and the same 5 rows
as `landing/orders.parquet`, `landing/orders.jsonl` (NDJSON) and `landing/orders.json` (a JSON array).
`tw run` output lines below show the console's CHECK/OUTCOME/VALUE columns only. Exact wording of the new
messages is the data-steward's to amend in REFINE (Q8); the exit codes are not.

| id | | Given | Expected |
| --- | --- | --- | --- |
| F1 | must | the fixture; `tw run` | `row_count = 5` pass, value `5 rows`; `missing_count(email) = 0` fail, value `1`; exit 1 |
| F2 | must | `dataset: orders.parquet`, same checks | same outcomes and values as F1; exit 1 |
| F3 | must | `dataset: orders.jsonl`; then `dataset: orders.json` | same as F1 each time |
| F4 | must | F1 plus `min(amount) > 0`, `avg(amount) between 1 and 1000`, `duplicate_count(id) = 0`, `invalid_count(email) = 0` with `valid_regex: '@'`, `freshness(created_at) < 6h`, `failed_rows` with `condition: amount < 0` | each value equals the one the same check gives on the same rows loaded into a DuckDB table (test parametrised over CSV, Parquet, JSON); freshness reads the naive timestamps in the datasource `timezone` |
| F5 | must | F4's checks; `tw compile checks/landing/orders.yml` | **one** aggregate `SELECT … FROM read_csv('orders.csv') …` (Q2 settles the exact call); no absolute path anywhere in the output; exit 0 |
| F6 | must | `filter: amount > 10` on the file; one check with `where: email IS NOT NULL` | both applied in SQL; values as on the table |
| F7 | must | `landing/` absent, no `duckdb` installed, no env vars: `tw validate`, `tw list`, `tw compile` | validate exits 0 when the YAML is valid; `list` lists both checks; `compile` exits 0 with F5's SQL (no file is opened to compile) — except without `duckdb`, where compile reports the F9 reason |
| F8 | must | `dataset: missing.csv`; one more check file on table `orders` in another datasource; `tw run` | every check on `missing.csv` is `error` with `no file matches 'missing.csv' in the files datasource 'drop'`; the other file's checks run; exit 2. No absolute path in the message, the store or the API |
| F9 | must | `duckdb` not installed; `tw run` | each check on `drop` is `error` with `datasource 'drop' in tablewatch.yml: the files datasource needs an optional dependency: pip install 'tablewatch[duckdb]'`; exit 2 |
| F10 | must | `orders.csv` where one `amount` is `N/A` | `min(amount) > 0` is `error` (rule 7: not `fail`); `row_count = 5` still passes. The message is I-30's, not this spec's |
| F11 | must | (Q7) the fixture CSV with `email`'s blank row written both unquoted (`,,`) and quoted (`,"",`) | `missing_count(email) = 0` fails with value `1` either way: DuckDB's `read_csv` reads every blank field, quoted or not, as NULL (there is no way to write a literal `''` in a plain CSV), so a blank is "missing" with no `missing_values: ['']` needed — the one divergence from a table, where blank text stays present unless configured |
| F12 | must | (Q7) `orders.jsonl` with one record's `"email"` key omitted and another's set to `""` | `missing_count(email) = 0` fails with value `1`, not `2`: JSON keeps NULL (an absent key) and `''` (an explicit empty string) distinct, exactly as a table does, so `''` only counts once `missing_values: ['']` is added — JSON and CSV disagree on this, each following its own format's native reading |
| F13 | must | (Q7) the fixture `orders.csv` saved with a UTF-8 byte-order mark | every check gives the same outcomes and values as F1; a BOM is not visible to Sam and needs no handling |
| F14 | must | (Q7) the fixture `orders.csv` saved as Latin-1 (one non-ASCII byte) | every check on it is `error` with a fixed message naming the file and that it is not valid UTF-8 (`'orders.csv' is not valid UTF-8`), never DuckDB's raw error, which quotes a line of the file's contents |
| G1 | must | `dataset: ../secret.csv`; `/etc/passwd`; `sub/../../x.csv` | Diagnostic `checks/landing/orders.yml:2:10: a files dataset must be a path inside its datasource's root; got '../secret.csv'`; `tw validate` exits 3; nothing runs |
| G2 | must | `dataset: s3://bucket/o.parquet`; `https://h/o.csv` | Diagnostic at the value: `files datasets are local paths; URLs are not supported; got 's3://bucket/o.parquet'`; exit 3 |
| G3 | part 2 | `dataset: daily/orders_*.csv` (two files, 3 + 2 rows, same header) | `row_count = 5` pass. A glob matching nothing: F8's error |
| G4 | must | `dataset: orders.txt`; `dataset: orders` | Diagnostic at the value: `cannot tell the format of 'orders.txt' from its extension: use .csv, .tsv, .parquet, .json, .jsonl or .ndjson`; exit 3 |
| G5 | should | `dataset: orders.csv.gz` (gzip of orders.csv) | as F1 |
| G6 | must | `root: ${env:LANDING}` with `LANDING` unset; `tw validate` | Q5 decides: either `root` takes no `${env:}` (a Diagnostic at `tablewatch.yml:line:col`) or it resolves only when connecting, and `validate` stays green |
| S1 | must | `sql_metric` with `query: SELECT count(*) FROM read_csv('../outside.csv')`, `../outside.csv` exists | `error` (the read is refused); the message does not quote the outside file's contents; exit 2 |
| S2 | must | `failed_rows` `condition: (SELECT count(*) FROM read_text('/etc/hosts')) > 0` | `error`, refused as S1 |
| S3 | must | `sql_metric` `query: SELECT count(*) FROM read_parquet('https://example.com/x.parquet')` | `error`, refused; **no network connection is attempted** (no extension autoinstall or autoload); test runs offline |
| S4 | must | `sql_metric` `query: SET enable_external_access = true` or `COPY (SELECT 1) TO 'landing/x.csv'` | `error`; no file is created anywhere |
| S5 | must | a symlink `landing/link.csv` → `/etc/hosts` (or a file outside `root`) | Q4 decides: refused (`error`), or followed with the reason written in the docs |
| I1 | must | `dataset: orders.csv` vs `dataset: ./orders.csv` | the same check id (the path is normalised before it feeds `derive_check_id`) |
| I2 | must | change `root: landing` to `root: landing2` (same files) | ids unchanged: `root` is not part of identity, so history carries over |
| I3 | must | a table dataset on any other datasource | ids unchanged from `main` (no table-dataset id moves) |
| S7 | part 2 | `schema` with `required_columns: [id, email]`, `column_types: {amount: double}` on `orders.parquet` | pass, value `0 problems` (DuckDB's types from the file) |
| S8 | part 2 | `schema` with `required_columns: [nope]` on `orders.csv` | fail, `1 problem` naming `nope` |
| U1 | must | after F1, `GET /api/v1/checks` and the check page | dataset `orders.csv`, datasource `drop`; the SQL section shows F5's SQL; no absolute path |
| D1 | must | `docs/check-language.md`, `README.md`, JSON Schema (`tw schema`) | `type: files` documented with formats, the root rule, the read-only sandbox and the `duckdb` extra; the schema accepts `type: files` with `root` |

## Non-goals

- Remote files (S3, GCS, HTTP), cloud credentials, `httpfs` — a later increment, and a security review of its own.
- Reader options (`delimiter:`, `header:`, `format:` override, `hive_partitioning:`): DuckDB's sniffing decides.
- Files through Postgres or SQLite datasources, Excel, Avro, Delta, Iceberg.
- Copying or caching file contents; a persisted DuckDB database for files.
- In-memory frames (A9), Spark (B8), streams (A17): the seams leave room for them; none is built.

## Decisions (REFINE: Q1–Q3 architect, Q4–Q6 security, Q7–Q8 data-steward)

- **D1 (Q1).** A datasource's `type: files` makes its datasets files. The loader sets `Dataset.source`:
  `TableSource(TableRef)` or `FileSource(path, format)` (new `checks/sources.py`), each with
  `from_clause()` and `columns(conn)`. The planner uses `source.from_clause()`, and `MetricContext.table`
  and `DatasetPlan.table` widen to `FromClause`. For files, `Dataset.name` is the normalised relative
  POSIX path, and it feeds `derive_check_id` as a table name does. `root` never feeds it (I2), and table
  ids do not move (I3).
- **D2 (Q2, R5).** No `file_search_path` and no inlined path. The SQL is `read_csv(:tw_path)` with the
  **relative** path, so compile, the store and the API show the relative path only. `create_engine_for`'s
  files branch, the only place `root` is resolved, swaps the absolute path in at execution, after
  checking it stays inside `root`.
- **D3 (Q3).** No executor protocol yet. The seam is the per-datasource `EngineFactory` plus
  `execute_plan`. FEATURES.md's seam table says so, and the protocol is deferred to B8.
- **D4 (Q4, R2–R4).** `type: files` needs duckdb ≥ 1.5.0, checked at connect, with a fixed `error`
  otherwise (older versions follow symlinks out of `allowed_directories`). The connection sets
  `enable_external_access=false`, `allowed_directories=[realpath(root)+'/']`, autoinstall and autoload
  off, and `lock_configuration=true`, all at connect. A test reads them back. Symlinks are refused
  (S5 → `error`), and the docs say so.
- **D5 (R1).** On a files engine the executor checks each rendered statement: exactly one statement,
  of type SELECT, or a fixed `error` (S4: no file is written). This covers `sql_metric`, `filter`,
  `where` and `condition`.
- **D6 (Q5, R6).** `root` takes no `${env:}` (a Diagnostic) and must be relative, with no `..`. At
  connect, realpath(root) must lie inside realpath(project), or a fixed `error` (G6 becomes the
  Diagnostic).
- **D7 (Q6, R7, F14).** No DuckDB exception text from a files engine reaches a message, the store, the API
  or any log level. Errors are mapped: no match → F8's text; a refused read → `the read was refused
  (outside root, a write, a URL or a setting)`; a conversion, invalid input or sniffing error →
  `could not read '<rel>' as <format>` (non-UTF-8: F14's text); anything else → `(ExceptionTypeName)`.
- **D8 (Q7, Q8).** DuckDB's native reading is kept (F11–F14), with the wording as the data-steward amended
  it. The DATASET column shows the relative path; I-45 is the general fix.
- **D10 (BUILD).** F10 moves to I-30. A text column (`N/A` in `amount`) makes `min()` compare strings and
  pass; a table's text column does the same today. The numeric-type check belongs in the metric layer
  (I-30, iteration 24); the strict xfail test stays. DuckDB 1.5.5 refuses `allowed_directories` in the
  connect config, so the three sandbox settings run first in the pool's connect hook, before any SQL
  (security re-checks in VERIFY).
- **D9 (non-blocking).** `memory_limit`, `threads` and no temp spill on the files connection.
