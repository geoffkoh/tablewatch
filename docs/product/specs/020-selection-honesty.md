# Spec 020: Selection honesty (I-16) and usage errors exit 3 (I-17 part 1)

- **Track:** full (the exit-code contract; the stored and served `selection`; `tw.SelectionError`, a public API).
- **Size:** S. I-16 whole, plus one part of I-17 (click usage errors → exit 3). The rest of I-17 (tracebacks in `runs`/`history`/`--output-file`, a malformed `results.url`, one root discovery) stays on I-17.
- **Reviewers:** data-steward (REFINE Q1–Q4 + VERIFY), architect (REFINE Q5–Q6), qa-engineer (VERIFY). security-reviewer not required: no dependency, network, secret, SQL reach or row data; the change only removes absolute paths from what is stored and served.

## Problem and persona

Dana's pipeline runs `tw run checks/inventory checks/inventry`. The typo selects nothing, the real
folder runs, and the job is green: a folder nobody checked reads as checked. Priya's scheduler can only
trust the exit code. Separately, the same run is recorded three ways (`checks/inventory`,
`./checks/inventory/`, `/Users/…/checks/inventory`), so the UI's "Selected" line and the API leak the
caller's filesystem and cannot be compared across runs. Owner decisions (2026-09-27, ITERATIONS.md
iteration 1): a selector that matches nothing, even beside ones that match, exits 3 and runs nothing,
naming it, in the CLI and `tw.run()`; click usage errors exit 3. Both are breaking. Research: dbt warns
"selection criterion … does not match any enabled nodes" and exits 0, a long-standing complaint
([dbt-core #12391](https://github.com/dbt-labs/dbt-core/issues/12391),
[#12863](https://github.com/dbt-labs/dbt-core/issues/12863)).

## Today (measured on `examples/retail`, 19 checks; `--no-store`)

| Input | Today |
| --- | --- |
| `run checks/inventory checks/inventry` | runs 5 checks, exit 1 (would be 0 on clean data); typo not mentioned |
| `run --tag sales --tag sails` / `--check cd3e81 --check zzzz` | runs what matched; exit by outcome |
| `list checks/inventry`, `list --tag sails`, `compile …` | `0 checks`, exit 0 |
| `run checks/inventry` alone | `tablewatch: no checks matched the selection — nothing ran`, exit 3 |
| `--exclude ./checks/inventory`, absolute, or `inventory` from `checks/` | excludes nothing (19 checks); only `checks/inventory` works — excludes are matched raw, paths are resolved |
| `tw.run(p, paths=[abs])`, `["./checks/inventory/"]` | `RunResult.selection` and the store keep the string as passed |
| `run --fail-on bad`, `run --bogus`, `tw` alone, `nosuchcmd` | click usage error, exit 2 (reserved for "could not evaluate") |

Code: `selection.py:select_checks` filters without tracking which selector matched; `_relative_to_project`
falls back to the project root for a missing path, so a typo becomes a root that matches nothing;
`api.execute` stores `selection.as_dict()` (raw input); `cli/main.py:_select` serves `list`/`compile`.

## Rule

Each **path, tag, check-id prefix, datasource, and exclude** must match at least one check in the
project, judged on its own against the whole project (Q1). If any does not, nothing runs, exit 3, and
every unmatched selector is named in one message. An empty intersection of selectors that each match
keeps today's message. The run records a normalised `selection`: paths and non-glob excludes
project-relative POSIX, no `./`, no trailing `/` (Q4).

## Scenarios (cwd `examples/retail` unless stated; `run` with `--no-store`)

| id | | Given | Expected |
| --- | --- | --- | --- |
| S1 | must | `tw run checks/inventory checks/inventry` | nothing runs; stderr `tablewatch: no checks match path 'checks/inventry' — nothing ran`; exit 3 |
| S2 | must | `tw.run(p, paths=["checks/inventory", "checks/inventry"], record=False)` (spec 001 R12) | `tw.SelectionError`, message `no checks match path 'checks/inventry' — nothing ran`; no store row |
| S3 | must | `tw run --tag sales --tag sails` | `… no checks match tag 'sails' — nothing ran`; exit 3 |
| S4 | must | `tw run --check cd3e81 --check zzzz` | `… no checks match check id 'zzzz' — nothing ran`; exit 3 |
| S5 | must | `tw run checks/inventry --tag sails --check zzzz` | one message naming all three, in that order: `no checks match path 'checks/inventry', tag 'sails', check id 'zzzz' — nothing ran`; exit 3 |
| S6 | must | `tw run checks/inventory --tag sales` (each matches; intersection empty) | unchanged: `no checks matched the selection — nothing ran`; exit 3 |
| S7 | must | `tw run checks/inventory --exclude checks/nope` | `… no checks match exclude 'checks/nope' — nothing ran`; exit 3 (Q2) |
| S8 | must | `tw list checks/inventry`; `tw compile --tag sails` | same message as S1/S3, exit 3 (Q3) |
| S9 | must | `tw run --exclude ./checks/inventory`; `--exclude <abs>/checks/inventory`; from `checks/`: `tw run --exclude inventory` | 14 checks run (inventory excluded) in all three |
| S10 | must | `tw.run(p, paths=X, record=False)` for X = `["checks/inventory"]`, `["./checks/inventory/"]`, `[<abs>/checks/inventory]` | `RunResult.selection == {"paths": ["checks/inventory"]}` for all three |
| S11 | must | from `examples/retail/checks`: `tw run sales --exclude 'checks/sales/orders*'` (recorded; 5 checks) | stored row, JSON report and `GET /api/v1/runs` show `{"paths": ["checks/sales"], "excludes": ["checks/sales/orders*"]}`; globs kept as typed (Q4) |
| S12 | must | `tw run .` from the project root; `tw run checks` | recorded `{"paths": ["."]}` and `{"paths": ["checks"]}` (Q4) |
| S13 | must | `tw run ../` | unchanged: `../ is outside the project at <root>`; exit 3 |
| S14 | must | `tw run --fail-on bad`; `tw run --bogus`; `tw nosuchcmd`; `tw history` (missing CHECK_ID); `tw serve --port 70000` | click's message unchanged on stderr; exit 3 |
| S15 | must | `tw`, with no command | usage on stderr; exit 3 |
| S16 | must | `tw --help`, `tw run --help`, `tw --version` | exit 0 |
| S17 | must | `tw.run(p, fail_on="bad")` | `ValueError` as today (Python has no usage errors) |
| S18 | should | a project with datasources `a` and `b`, checks only on `a`: `tw run --datasource b` | `… no checks match datasource 'b' — nothing ran`; exit 3 (an unknown datasource keeps `unknown datasource: …`) |
| S19 | should | a path that exists but holds no checks (an empty folder `checks/empty/`) | as S1, naming it |
| S20 | must | runs recorded before this change | stored as they were; the UI and API show them unchanged (no rewrite) |
| S21 | should | `tw.run(p, paths=[""], record=False)` (today: `Path("")` is `Path(".")`, so a blank arg silently resolves to the project root and runs all 19 checks, not an error) | still runs everything **or** raises naming the blank path — either is acceptable, but pick one; a blank arg (an unset shell var substituted into `--exclude $VAR`) must not pass as a no-op restriction |
| S22 | should | `tw run --tag ''` | message quotes the value: `no checks match tag '' — nothing ran`, not an unquoted trailing space a user can't see in a terminal |

Docs: README exit-code table (`3` gains "or the command line is wrong") and "Use from Python";
`cli/main.py` docstring; CHANGELOG under **Changed (breaking)** for both exit-code changes.

## Non-goals

- Rewriting `selection` on runs already in the store.
- The rest of I-17 (tracebacks in `runs`, `history`, `--output-file`; malformed `results.url`; one root discovery).
- A flag to allow empty selections (dbt's `--allow-empty-selection`); nobody has asked for one.
- Case-insensitive tags or fuzzy "did you mean" suggestions.
- Changing what `paths` resolve against in `tw.run()` (the project root, as documented).

## Decisions (REFINE: Q1–Q4 data-steward, Q5–Q6 architect)

- **D1 (Q1).** Each selector is judged on its own against the whole project. A day when nothing is
  tagged `tier-1` yet exits 3, like a typo would: tablewatch cannot tell the two apart, and an alert
  beats a cron job that quietly checks nothing.
- **D2 (Q2, Q3).** An unmatched exclude exits 3, literal or glob. `list` and `compile` follow the same rule.
- **D3 (Q4).** The recorded form is project-relative POSIX, the root as `.`, and glob excludes kept as
  typed. Messages name each value as typed, **always in single quotes** (S1–S8 and S18 above are
  written so; S22 follows). Only runs from this version on are normalised (S20).
- **D4 (S21).** A blank value (`""`, as from an unset shell variable) never widens a selection: it is
  unmatched, `no checks match path '' — nothing ran`, exit 3. The same holds for tag, check id,
  datasource and exclude.
- **D5 (Q5).** `Selection.resolve(project, cwd) -> Selection` in selection.py does all path work once
  and raises one `SelectionError` naming every unmatched selector, in the order path, tag, check id,
  datasource, exclude. `execute` and the CLI's `_select` both call it. After that, `select_checks`
  matches against the project root only, never re-resolving against cwd. `SelectionError` stays
  message-only.
- **D6 (Q6).** A `click.Group` subclass, `@click.group(cls=...)`, overrides `make_context` and `invoke`
  to give `click.UsageError` the exit code 3 and re-raise it. `--help` and `--version` stay 0. There is
  no wrapper entry point. The store needs no migration and `/api/v1` does not change shape.
