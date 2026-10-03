# Spec 029: Files as datasets, part 2 — glob patterns and `schema` on files (I-08)

- **Track:** full (widens what the files sandbox reads: user-written patterns reach the file system; `schema` adds a statement on the files engine; check identity for a pattern-named dataset).
- **Size:** S. Globs (G3) and `schema` on files (S7–S8) are the two halves spec 023 already wrote scenarios for; a `sql_metric` reading the file stays in I-08 (non-goals).
- **Reviewers:** security-reviewer (REFINE Q3–Q4), architect (REFINE Q1–Q2), data-steward (REFINE Q5–Q6 + VERIFY), qa-engineer (VERIFY).

## Problem and persona

Dana's partners drop one file per day (`daily/orders_2026-10-01.csv`, `…-02.csv`); part 1 makes her
write one check file per date, or concatenate the drops first. She also cannot assert the drop's shape
(`schema` is `error`: "schema checks on files are not supported yet"), which is the first thing a
landing check should catch. Phase 2, A8, finishing spec 023's G3, S7, S8 and S5's glob rule.
Research: DuckDB reads a list or a glob (`*`, `**`, `?`, `[ ]`) and unifies differing files only
with `union_by_name` ([DuckDB multiple files](https://duckdb.org/docs/current/data/multiple_files/overview.html));
GX makes each matched file its own batch ([GX filesystem](https://docs.greatexpectations.io/docs/core/connect_to_data/filesystem_data/));
we keep one pattern = one dataset = one scan (rule 1), and tablewatch, not DuckDB, expands the pattern.

## Behaviour

A files dataset may be a pattern relative to `root`: `*`, `?`, `[ ]` and `**` (any depth). tablewatch
expands it in Python inside `realpath(root)`, checks **every** match with part 1's `_inside` rule (inside
root, no symlink anywhere on its path), sorts the matches, and hands DuckDB the list of absolute paths;
DuckDB never globs. SQL, `compile`, the store and the API show the pattern only. The format follows the
pattern's extension. `schema` on a file or pattern reads DuckDB's column names and types without
reading rows beyond what DuckDB samples to detect types.

Fixture: spec 023's `landing-test` project, plus `landing/daily/orders_2026-10-01.csv` (3 rows) and
`landing/daily/orders_2026-10-02.csv` (2 rows), header `id,email,amount,created_at`, one empty `email`.

## Scenarios

| id | | Given | Expected |
| --- | --- | --- | --- |
| G3 | must | `dataset: daily/orders_*.csv`; `row_count = 5`, `missing_count(email) = 0` | `row_count` pass, value `5 rows`; `missing_count` fail, value `1`; exit 1 |
| G7 | must | `dataset: daily/returns_*.csv` (no match); `tw run` | every check on it `error`: `no file matches 'daily/returns_*.csv' in the files datasource 'drop'`; exit 2 |
| G8 | must | G3; `tw compile`; then `tw validate`, `tw list` with `landing/` absent | compile: one `SELECT … FROM read_csv(:tw_path)`, the bind shown as `daily/orders_*.csv`, no absolute path, no matched file name; all three exit 0 and open no file |
| G9 | must | `dataset: '**/*.csv'` with `orders.csv` at root and the two daily files | `row_count = 10 rows` (5 + 3 + 2): `**` matches at any depth, root included |
| G10 | must | `dataset: daily/orders_{01,02}.csv` | Diagnostic at the value: `a files dataset pattern may use *, ?, [ ] and **; braces ({ }) are not supported; got 'daily/orders_{01,02}.csv'`; `validate` exit 3 |
| G11 | must | `dataset: '../*.csv'`; `'daily/../../*.csv'`; `'/tmp/*.csv'`; `'s3://b/*.parquet'`; `'daily/*'` | spec 023's G1, G2 and G4 Diagnostics respectively (a pattern gets no exemption); exit 3 |
| G12 | must | G3 plus `daily/orders_zz.csv` a symlink → `../orders.csv` (inside root); again → `/etc/hosts` | every check on the dataset `error` with `the read was refused (outside root, a write, a URL or a setting)`; no row of any file counted (Q3); exit 2. Replaces part 1's `test_s5_a_glob…` |
| G13 | must | `landing/daily` itself a symlink to a directory inside, then outside, root | as G12, both times |
| G14 | must | a match whose own name holds a pattern character, e.g. `daily/orders_[x].csv`, under `daily/*.csv` | refused as G12 (Q4): DuckDB would re-expand the name |
| G15 | should | `daily/.orders_tmp.csv` (hidden) and `daily/.part/x.csv` next to G3's files | not matched by `*` or `**`; G3's values unchanged |
| G16 | should | a pattern matching more than the cap (Q4; proposed 10,000 files) | `error`: `'<pattern>' matches more than 10,000 files in the files datasource 'drop'`; nothing read |
| G17 | must | (Q5) `orders_2026-10-02.csv` with its columns in another order (`email,id,created_at,amount`) | values as G3: files are unified **by column name**; a column absent from one file reads NULL there |
| G18 | must | (Q6) the second daily file saved as Latin-1 | every check `error`: `'daily/orders_*.csv' is not valid UTF-8` (the pattern, not the file: DuckDB's text, which names the file absolutely, is never echoed) |
| G19 | must | `tw validate --connect` on G3, then on G7 | G3: exit 0; G7: `no file matches 'daily/returns_*.csv' …` at the dataset value, exit 3 (spec 028's "project mistake") |
| I4 | must | `daily/orders_*.csv` vs `./daily/orders_*.csv`; then a third daily file added | same check id each time: the id keys on the normalised pattern, never on what matches |
| I5 | must | single-file datasets from part 1 | ids unchanged from `main` |
| S7 | must | `schema` with `required_columns: [id, email]`, `column_types: {amount: double}` on `orders.parquet` | pass, value `0 problems` |
| S8 | must | `schema` with `required_columns: [nope]` on `orders.csv` | fail, `1 problem`, detail `missing column nope`; exit 1 |
| S9 | must | `schema` with `column_types: {id: bigint, created_at: timestamp}` on `orders.csv` | pass: CSV types are DuckDB's detected types, and the docs say so |
| S10 | must | `schema` with `required_columns: [email]` on G3's pattern, then G17's | pass both times: the columns are the unified set (Q5) |
| S11 | must | `schema` on `missing.csv`; on G12's symlinked set | F8's `no file matches …` error; G12's refused error; exit 2 |
| S12 | must | `schema` plus `row_count = 5` on `orders.csv`; `tw compile` | one aggregate scan as before; the schema statement passes D5 (one `SELECT`) and the sandbox |
| D2 | must | `docs/check-language.md` "Files as datasets"; `tw schema` | patterns, the symlink rule for every match, hidden files, union by name, the cap, and `schema` on files documented; the "two exceptions" sentence names only `sql_metric` |

## Non-goals

- A `sql_metric` (or `failed_rows` subquery) naming its own file: needs a language decision on how a
  query names its dataset. It stays in I-08, which remains in progress after this spec.
- One outcome per matched file (GX batches), a `filename` column, or a per-file row count.
- Brace patterns, regex patterns, reader options (including a `union_by_name: false` switch).
- Remote patterns (S3, HTTP) — spec 023's non-goal stands.
- Caching the match list between checks or runs; a byte cap (the 2 GB memory limit of D9 stands).

## Open questions

- **Q1 (architect).** The matched list replaces `tw_path`'s value at execution (a list bind to
  `read_csv`), keeping `FileSource.from_clause()` and compile unchanged — or does `FileSource` gain a
  pattern flag the planner sees? Where does expansion live so that `run`, `--connect` (probe.py) and
  `schema` share one function, and the expansion happens once per dataset per run, not per statement?
- **Q2 (architect).** `schema` on a file: `SELECT * FROM read_x(:tw_path) LIMIT 0` and DuckDB's type
  names from the result, or `DESCRIBE`? It must pass D5's one-`SELECT` gate unchanged and fill the
  existing `SchemaMeasure`'s `(name, type)` list; is `FileSource.columns(conn)` (D1) the home?
- **Q3 (security).** A symlink among the matches, or on a directory the walk enters: refuse the whole
  dataset (proposed, G12–G13) or skip that file? Skipping silently changes row counts; refusing lets
  one stray link stop a dataset. Does the walk itself (`os.scandir`, no `follow_symlinks`) need to
  avoid entering symlinked directories before `_inside` checks the files?
- **Q4 (security).** (a) Does DuckDB re-glob an element of a list argument, so a file named
  `orders_[x].csv` or `*.csv` widens the read (G14)? Escape, or refuse such names? (b) The match cap
  and a `**` depth limit: values, and `error` vs. reading the first N. (c) Between expansion and read a
  file can be swapped for a symlink: is duckdb ≥ 1.5's `allowed_directories` the accepted backstop
  (it follows a link only inside root), or must the read re-check?
- **Q5 (data-steward).** Files whose columns differ: unify by name with NULLs (proposed, G17, S10),
  or require identical headers and `error` otherwise? A by-name union hides a column missing from one
  day's file behind `missing_count`; an error stops every check on the pattern for one bad file.
- **Q6 (data-steward).** Messages on a pattern name the pattern (G7, G18) rather than the failing file
  (which tablewatch cannot name without parsing DuckDB's text). Wording of G10 and G16.

## Decisions

- **Q1 (architect).** `FileSource.from_clause()` always emits `read_x(:tw_path, union_by_name => true)`;
  compile and the planner see no pattern flag. One `expand(root, pattern) -> list[str]` in `files.py`
  next to `_inside` is called only from `swap_path`, which binds the list of absolute paths (a single
  file too). Matches are cached per pattern in a dict held by the run's sandbox (not `conn.info`), so a
  dataset expands once per run. No match raises `FilesError("no file matches …")`, which probe.py's
  `_not_found` already classifies (G19). The loader allows `* ? [ ] **` and keeps the brace Diagnostic.
- **Q2 (architect).** `FileSource.schema_statement()` returns `SELECT column_name, column_type FROM
  (DESCRIBE SELECT * FROM read_x(:tw_path, union_by_name => true))` with the path bound; the executor's
  `_schema` gains a `FileSource` branch. Spec 023's D1 `columns(conn)` is dropped. The statement passes
  the one-`SELECT` gate (S12; security R7).
- **Q3 (security R1, R3).** The walk is `os.scandir`, `is_dir(follow_symlinks=False)`; it never enters a
  symlinked directory and never uses `glob`/`Path.glob`. A symlink on the path or among the matches
  refuses the **whole** dataset (G12, G13). Every match goes through `_inside`; only regular files
  (`lstat` + `S_ISREG`) match.
- **Q4 (security R2, R4–R6).** (a) DuckDB re-globs list elements, so a match whose name holds `* ? [ ] { }`
  or a control character refuses the dataset as G12 — **G14's expected result is that refusal**. `_inside`
  keeps refusing these characters. (b) `error`, nothing read, past 10,000 matches, a `**` depth of 32,
  or 100,000 directory entries scanned (G16). Hidden entries are never matched or entered (G15).
  (c) `allowed_directories` is the accepted backstop between expansion and read; DuckDB's permission
  error maps to the refusal. Absolute paths exist only inside `swap_path`.
- **Q5 (data-steward) — unify by column name (G17, S10 stand).** Verified on DuckDB: `union_by_name`
  reorders columns and reads a column absent from one file as NULL for that file's rows. Without it,
  DuckDB refuses every file on a schema mismatch, so a partner adding a column on day 2 would stop
  every day's checks. A column silently dropped reads as missing, not as an error; D2's docs pair a
  pattern with a `schema` check (`required_columns`) next to the union-by-name sentence.
- **Q6 (data-steward) — wording.** G10, G16 (`'daily/orders_*.csv' matches more than 10,000 files in the
  files datasource 'drop'`) and G18 stand. Messages name the pattern and datasource, never a matched
  file, an absolute path, or DuckDB's text: tablewatch cannot attribute a reader failure to one file
  without reopening each, so a message must not claim that precision.
