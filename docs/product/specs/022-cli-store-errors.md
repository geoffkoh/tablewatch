# Spec 022: CLI store and file errors without tracebacks; `runs` and `history` per project (I-17 rest, I-19)

- **Track:** full (exit codes of `runs`, `history` and `run --output-file` change; what `runs`/`history` show from a shared store changes; error text near a URL that can hold a password).
- **Size:** S, at the edge. If REFINE grows it, R1–R2 (one root discovery) split off and stay in I-17.
- **Reviewers:** architect (REFINE Q1–Q2), security-reviewer (REFINE Q3), data-steward (REFINE Q2, Q4 + VERIFY), qa-engineer (VERIFY).

## Problem and persona

Priya runs `tw runs` and `tw history` on the box where the nightly job writes its store, often a store
shared by several projects. A mistyped `results.url`, a corrupt or unreadable `results.db`, or a full
disk under `run --output-file` gives her a Python traceback and exit 1, which her orchestrator reads as
"the data is bad". `runs` and `history` even create an empty store when there is none, and in a shared
store they list every project's runs, so Dana's `history` mixes in another team's results. `report`
(spec 021) already does this right; the older commands should behave the same.
Research: dbt keeps a distinct exit code for "did not complete" (2) apart from handled failures (1)
([dbt exit codes](https://docs.getdbt.com/reference/exit-codes)); our contract already does (2 vs 1).

## Behaviour

`runs`, `history` and `report` read the store one way: `open_store(url, root, create=False)`, scoped to
`project.config.name`, with report's `except` block (one helper, Q1). A store that cannot be opened or
read is one line on stderr, `tablewatch: could not read the results store: <reason>`, never the URL,
and exit 2 (Q2). No store yet is not an error and creates nothing. `run --output-file` writes through
`_write_atomically`; an `OSError` is one line and exit 2, after the run is recorded and notified. The
CLI and `tw.load()` find the project root with one function.

## Scenarios (cwd `examples/retail`, built; store `.tablewatch/results.db`)

`<bad>` = `results: {url: "postgresql://u:secret@host:notaport/db"}`. "No trace" = stderr has no
`Traceback`, no `secret`, no `notaport`, no `invalid literal`.

| id | | Given | Expected |
| --- | --- | --- | --- |
| E1 | must | no `.tablewatch/`; `tw runs` | stdout `no runs recorded for project retail-example — run "tw run" first`; exit 0; `.tablewatch/` not created. Today: creates an empty store, prints `no runs recorded yet` |
| E2 | must | no `.tablewatch/`; `tw history abc` | stderr `tablewatch: no recorded results for check abc in project retail-example`; exit 3; nothing created. Today: creates the store |
| E3 | must | `<bad>`; `tw runs`, `tw history abc`, `tw report` | each: stderr exactly `tablewatch: could not read the results store: results.url is not a valid database URL`; exit 2; no trace. Today: runs/history `ValueError` traceback, exit 1; report `…: invalid literal for int() with base 10: 'notaport'`, exit 2 |
| E4 | must | `url: nonsense`; the three commands | as E3. Today: `ArgumentError` traceback, exit 1 |
| E5 | should | `url: "snowflake://u@acct/db"` (driver absent); `tw runs` | `tablewatch: could not read the results store: the snowflake driver is not installed: pip install snowflake-sqlalchemy` (spec 013's sentence); exit 2. Today: `NoSuchModuleError` traceback, exit 1 |
| E6 | must | `.tablewatch/results.db` holds the text `garbage`; `tw runs`, `tw history abc` | `tablewatch: could not read the results store: file is not a database`; exit 2; file unchanged. Today: `OperationalError` traceback, exit 1 |
| E7 | must | `.tablewatch/` mode 000; `tw runs`, `tw history abc` | `tablewatch: could not read the results store: unable to open database file`; exit 2. Today: traceback, exit 1 |
| E8 | must | `<bad>`; `tw run` | all 19 checks run; stderr `tablewatch: could not record the run: results.url is not a valid database URL`; exit 2 (unchanged code). Today: `…: results store: invalid literal for int() …` |
| E9 | must | `url: sqlite:////nonexistent_root/x/results.db`; `tw runs` | stdout `no runs recorded for project retail-example — run "tw run" first` (E1's text: a missing parent directory reads the same as no store yet); exit 0; no directory created. Today: `OSError` traceback, exit 1 |
| P1 | must | projects `retail-example` and `other` (a copy, `name: other`) share `results.url: sqlite:////abs/shared.db`; each ran once; `tw runs` in retail | one row: retail's run. Today: both runs |
| P2 | must | as P1; `tw history cd3e` (`row_count between 1 and 10000`, the same id in both copies) | rows from retail's run only. Today: both projects' rows |
| P3 | must | as P1; a check id prefix recorded only by `other` | `tablewatch: no recorded results for check <prefix> in project retail-example`; exit 3 |
| P4 | must | as P1; a prefix matching one id in retail and another only in `other` | the retail check's history; not "ambiguous" |
| P5 | should | `tw history ''` (or blanks) | stderr `tablewatch: history needs the first characters of a check id`; exit 3 (as `report --run ''`). Today: all 19 ids listed as ambiguous |
| O1 | must | `tw run --output json --output-file /nonexistent/dir/x.json` | checks run and are recorded; stdout the one-line summary; stderr `tablewatch: could not write /nonexistent/dir/x.json: No such file or directory`; exit 2. Today: `FileNotFoundError` traceback, exit 1, after recording |
| O2 | must | `--output junit --output-file ro/x.xml`, `ro/` mode 555 | `…: could not write ro/x.xml: Permission denied`; exit 2 |
| O3 | must | `link.json` a symlink to `target.txt`; `tw run --output json --output-file link.json` | `link.json` is now a regular file holding the JSON; `target.txt` unchanged; exit 1. Today: written through the link |
| O4 | must | `--output-file new.json` (absent), umask 022 | `new.json` mode per Q3 (report: 0600). Today: 0644 |
| O5 | must | `tw run --output json --output-file out.json`, writable | as today: file written, summary on stdout, exit 1 (the retail defects) |
| O6 | should | `tw run --output json --output-file -`; `tw report --output-file -` | `-` means stdout (Q4a): treated exactly as if `--output-file` were absent — `run` prints the JSON and exits on the checks' own outcome (1, the retail defects); `report` prints the HTML and exits 0. No "wrote -" line. Today: a file literally named `-` |
| R1 | must | cwd a directory with no `tablewatch.yml` above it; `tw runs`; `tw.load()` | CLI stderr `tablewatch: no tablewatch.yml in <cwd> or any parent directory — run "tablewatch init"`, exit 3; `tw.load()` raises `ProjectError` with the same text (one function). Today: two different texts |
| R2 | should | `tw --project-dir examples/retail/tablewatch.yml list` | lists 19 checks, exit 0, as `tw.load("examples/retail/tablewatch.yml")` already accepts. Today: usage error, exit 3 |
| R3 | must | `tw --project-dir /nope list`; `TABLEWATCH_PROJECT_DIR=/nope tw list` | exit 3, one line naming `/nope` (as today) |
| E10 | must | `results.url: postgresql://u:p@ss@host/db` (no server); `tw runs`, `tw run` | no `ss@host`, `p@ss` or `secret` in stderr; `runs` exit 2 with D6's fixed line |
| D1 | must | `cli/main.py` module docstring | states `runs`/`history`: 0 listed (empty included), 2 store unreadable, 3 no such check/usage; `run`: an unwritable `--output-file` is 2 |

## Non-goals

- `${env:}` in `results.url`, and the store verified on Postgres (I-14).
- `serve`'s own store messages and exit 3 on start-up failure (I-20 polishes `serve`).
- Checking `--output-file` is writable before the run starts: racy, and the run is recorded either way.
- `runs --output json`, paging, filters; `history` by check name.
- `validate` checking `results.url` (see Q2).

## Decisions (REFINE: Q1 architect, Q2 architect + data-steward, Q3 security, Q4 data-steward)

- **D1 (Q1a–b).** Delete the unscoped `recent_runs`, `matching_check_ids(prefix)` and `history`, and
  move their tests to the scoped reads. Add `matching_check_ids(project, prefix, limit=10)` beside
  `matching_run_ids`, without lowering the case (an explicit `id:` can be mixed-case). The blank-prefix
  guard (P5) lives in the CLI.
- **D2 (Q1c, R4).** One `@contextmanager _reading_store(project)` in cli/main.py yields the store, or
  None on `NoStoreError`, so each command keeps its own "no store" meaning (`runs` exits 0, `history`
  and `report` exit 3). Any other `StoreError` becomes the one line and exit 2. store.py is the only
  place a store error becomes text: `open_store` parses the URL first (one parse helper shared with
  `is_persistent` and `resolve_store_url`), and `store_sink` and the notify sink open through `open_store`.
- **D3 (Q1d).** `config.find_project(project_dir: Path | None) -> Path` sits beside `find_project_root`.
  It takes a directory or a `tablewatch.yml` path and raises `ProjectError` with R1's text; `api.load`
  and `_project` both call it. `--project-dir` accepts a file (R2).
- **D4 (Q2).** Exit 2, with no load-time Diagnostic for `results.url`. `serve`'s 3 is recorded under I-20.
- **D5 (Q3, R1).** `_write_atomically` keeps an existing regular file's permission bits (`st_mode &
  0o777`, never setuid/setgid/sticky). A new file, or a replaced symlink, gets 0600. One
  `_write_output(path, text)` serves `run` and `report`, and closes the fd if `fdopen` fails.
- **D6 (Q3, R2–R3).** Driver text is shown only for SQLite stores (a local file, no credentials). Any
  other backend reads `could not connect to the results store — run with -v for details`, with the
  driver text at INFO. A URL parse failure (`ValueError`, `ArgumentError`) always reads `results.url is
  not a valid database URL`, never `str(exc)`. The same rules apply to `run`'s record error (E8). New
  must scenario E10: `postgresql://u:p@ss@host/db` never shows `ss@host`.
- **D8 (VERIFY, QA).** A store migrated by a newer tablewatch is one line, exit 2 (`serve`: 3). A directory
  at the store's path is exit 2, not "no store". E7 reads `… results store: Permission denied`:
  a filesystem error gives its reason, never the path (data-steward). The record error drops its `results store:` prefix on the CLI (E8 as written). `-v` may
  show driver text (D6, as security accepted).
- **D7 (Q4).** `--output-file -` is stdout for `run` and `report`. On O1 the summary is still printed
  and the exit is 2. Wording is as above (E1/E9 carry R7's suffix); R1's text replaces both old texts.
