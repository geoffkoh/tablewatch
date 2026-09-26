# Spec 001: Python API — `tablewatch.load()` and `tablewatch.run()`

| | |
| --- | --- |
| Backlog item | I-01 |
| Features | B1 (Python API); E7 per call only (`record=`) |
| Phase | 2 (`0.2.0`) |
| Size | S |
| Depends on | nothing (Phase 1 engine) |
| Unblocks | I-02 REST API (and through it I-03..I-05), I-12 configurable recording |
| Branch | `iter/001-python-api` |
| Status | ready (PLAN, iteration 1) |

## Problem and persona

**Dana, data engineer.** "My Airflow task loads orders, and I want the checks
to run right after — in the same Python process, on the results of *this*
load. Today I shell out to `tablewatch run --output json`, parse stdout, and
map the exit code back myself. In a notebook it's worse: I iterate on a check
file and every trial run lands in the shared history."

How Dana copes today:

- `subprocess.run(["tablewatch", "run", ...])` and `json.loads(stdout)`. It
  works, but the results are untyped dicts, a second Python interpreter
  starts, and a crash inside tablewatch shows up as a traceback on stderr
  with exit code 1 — which the orchestrator reads as "the data is bad".
- Importing `tablewatch.config.load_project` and
  `tablewatch.engine.runner.run_checks` directly. These are internal: they
  carry no stability promise, do not record, and skip the selection rules.
- `--no-store` exists on the CLI, but there is no equivalent for a caller in
  Python.

**Priya, platform / SRE**, needs the same thing one level down: the REST API
(I-02) and the UI after it must run and read checks through one supported
code path, not a second copy of the CLI's logic.

Peers solve this in three different ways, and each teaches something:

- **Soda Core** has a builder-style `Scan` object; `execute()` returns an int
  and `set_is_local()` stops results going to Soda Cloud — the same need as
  our `record=False`. Its exit codes mix warnings and failures (1 = warn,
  2 = fail), which tablewatch's contract deliberately does not do.
  ([Soda Python API](https://docs.soda.io/soda-documentation/soda-v3/run-a-scan/python_api))
- **dbt** `dbtRunner.invoke()` returns a result with `success` and a separate
  `exception`: a failing model is `success=False`, and only an unhandled
  error raises. That matches rule 7 — bad data and "could not evaluate" are
  outcomes, not exceptions.
  ([dbt programmatic invocations](https://docs.getdbt.com/reference/programmatic-invocations))
- **Great Expectations** runs a checkpoint and then a list of *actions*
  (store results, notify Slack, build docs) over its result — the
  result-sink idea, with notification as just another consumer.
  ([GX checkpoint actions](https://docs.greatexpectations.io/docs/core/trigger_actions_based_on_results/create_a_checkpoint_with_actions/))

We borrow dbt's rule (return outcomes, raise only when nothing could run) and
GX's shape (outcomes flow to replaceable consumers), with plain functions
rather than Soda's stateful builder.

## Outcome

After this ships Dana can write:

```python
import tablewatch as tw

result = tw.run("/opt/pipelines/retail", paths=["checks/sales"], record=False)
if result.exit_code() != 0:
    raise RuntimeError(f"{result.count(tw.Outcome.FAIL)} checks failed")
```

and get typed results that mypy checks, the same outcomes and exit-code
meaning as `tablewatch run`, and the choice per call of whether the run goes
into history. The CLI's `run` goes through the same function, and the
results store becomes one replaceable *result sink* instead of being wired
into the command.

A Phase 1 defect is fixed on the way (see scenario R4): today a results
store at an unusable path crashes `tablewatch run` with a traceback and exit
code **1**, telling the orchestrator the data is bad when it is not.

## Proposed public surface

A proposal for architect review in REFINE; names may change, behaviour in
the scenarios may not.

```python
def load(project_dir: str | os.PathLike[str] | None = None) -> Project: ...

def run(
    project: Project | str | os.PathLike[str] | None = None,
    *,
    paths: Sequence[str] = (),
    tags: Sequence[str] = (),
    datasources: Sequence[str] = (),
    excludes: Sequence[str] = (),
    check_ids: Sequence[str] = (),
    record: bool = True,
    fail_on: Literal["fail", "warn"] = "fail",
    concurrency: int = 4,
) -> RunResult: ...
```

Top-level exports (`tablewatch.__all__`): `load`, `run`, `Project`,
`RunResult`, `CheckResult`, `Outcome`, `Diagnostic`, `ProjectError`,
`SelectionError`, `__version__`. `None` as the project means "the nearest
directory at or above the current directory holding a `tablewatch.yml`",
as the CLI does.

## Acceptance scenarios

Fixtures: `retail` is `tests/conftest.py`'s copy of `examples/retail` with
its database built (3 datasets, 18 checks; planted defects give 6 fail,
10 pass, 2 warn). `demo` is a project written in the test:

```yaml
# demo/tablewatch.yml
name: demo
datasources:
  lake:
    type: duckdb
    path: lake.duckdb
  wh:
    type: postgres
    host: localhost
    database: dw
    user: tw
    password: ${env:TW_TEST_PG_PASSWORD}
```

Exact strings below were captured from the current CLI on 2026-09-26, and
re-verified by the data steward in REFINE on the same day. Counts, the L2/R4/R5/R6
messages and the S4 defect all reproduce as written.

### Loading

**L1 — load returns a project without running anything** `must`
- Given the `retail` project **with `retail/retail.duckdb` deleted** *(sharpened
  in REFINE: DuckDB creates its file on connect, so the file's absence proves
  no engine was opened without patching internals)*
- When `project = tw.load(retail)`
- Then `project.ok is True`, `len(project.datasets) == 3`,
  `len(project.checks) == 18`, `project.diagnostics == []`,
  `retail/retail.duckdb` still does not exist, and no `.tablewatch/`
  directory is created under `retail`.

**L2 — check-file mistakes are diagnostics, not exceptions (rule 5)** `must`
- Given `demo` with `checks/orders.yml`:
  ```yaml
  dataset: orders
  datasource: lake
  checks:
    - row_cnt > 0
    - missing_count(id) = 0
  ```
- When `project = tw.load(demo)`
- Then it does not raise; `project.ok is False`; and
  `[str(d) for d in project.diagnostics] ==
  ["checks/orders.yml:4:5: error: unknown metric 'row_cnt' — did you mean 'row_count'?"]`.

**L3 — no credentials needed to load (rule 6)** `must`
- Given `demo` with `checks/orders.yml` naming `datasource: wh` and
  `TW_TEST_PG_PASSWORD` unset
- When `tw.load(demo)`
- Then it succeeds with `project.ok is True`.

**L4 — an unusable project raises** `must`
- Given an empty directory `empty/`
- When `tw.load(empty)`
- Then `tw.ProjectError` is raised and `str(exc)` contains
  `no tablewatch.yml in` followed by the resolved directory.

**L5 — default project directory** `should`
- Given the process's current directory is `retail/checks/sales`
- When `tw.load()` is called with no argument
- Then the project at `retail` is loaded (`len(project.checks) == 18`).

**L6 — no project anywhere above the cwd raises** `must` *(added in REFINE)*
- Given the process's current directory is `tmp_path / "nowhere"`, with no
  `tablewatch.yml` in it or any parent
- When `tw.load()` (and, separately, `tw.run(record=False)`)
- Then `tw.ProjectError` is raised and `str(exc)` contains
  `no tablewatch.yml`. Nothing is created in `nowhere/`.
- Why: in a container whose working directory is wrong, the default must not
  quietly load nothing and pass.

**L7 — pointing at the project file itself** `should` *(added in REFINE)*
- Given the `retail` project
- When `tw.load(retail / "tablewatch.yml")`
- Then either it loads `retail` (18 checks), or it raises `tw.ProjectError`
  whose message says to pass the directory. Today it would say
  `no tablewatch.yml in .../tablewatch.yml`, which reads as nonsense.

### Running

**R1 — a run returns typed outcomes and the CLI's exit-code meaning** `must`
- Given the `retail` project
- When `result = tw.run(retail, record=False)`
- Then `isinstance(result, tw.RunResult)`; `len(result.results) == 18`;
  `result.count(tw.Outcome.FAIL) == 6`, `result.count(tw.Outcome.PASS) == 10`,
  `result.count(tw.Outcome.WARN) == 2`; `result.outcome is tw.Outcome.FAIL`;
  `result.exit_code() == 1`; and the set of `r.check.name` for failing results
  equals the six names asserted in
  `tests/test_cli.py::test_run_example_reports_every_planted_defect`.
- And *(added in REFINE)* `result.trigger == "python"`;
  `result.started_at.utcoffset() == timedelta(0)` and likewise
  `finished_at` (aware UTC, never naive — a naive datetime in a notebook is
  read as local time); `result.started_at <= result.finished_at`; and
  `result.outcome == "fail"` (an `Outcome` compares equal to its string).

**R2 — selection by path is relative to the project, not the cwd** `must`
- Given the process's current directory is **a second copy of `retail`**
  (`tmp_path / "other"`, which has its own `checks/sales`) *(sharpened in
  REFINE: an empty "elsewhere" does not catch the trap. The CLI's
  "cwd first" rule would resolve `checks/sales` inside `other` and raise "is
  outside the project"; the API must not)*
- When `result = tw.run(retail, paths=["checks/sales"], record=False)`
- Then `len(result.results) == 14`, with 6 fail, 7 pass and 1 warn, and
  `result.selection == {"paths": ["checks/sales"]}`.
- And `tw.run(retail, paths=[str(retail / "checks" / "sales")], record=False)`
  (absolute, inside the project) gives the same 14.
- And *(should, added in REFINE)* `paths=[pathlib.Path("checks/sales")]` is
  accepted and gives the same 14. Python users will hand over `Path`s.

**R3 — every CLI selector is available** `must`
- Given the `retail` project
- When `tw.run(retail, tags=["catalogue"], record=False)`
- Then exactly the 4 checks of `inventory.products` run (3 pass, 1 warn),
  `result.exit_code() == 0`, and `result.exit_code("warn") == 1`
  — the same as `tablewatch run checks/inventory [--fail-on warn]` today.
- And `tw.run(retail, excludes=["checks/sales"], record=False)` gives the same
  4 checks; `tw.run(retail, datasources=["lake"], record=False)` gives all 18;
  `tw.run(retail, check_ids=[c.id], record=False)` for one check `c` from
  `tw.load(retail).checks` gives exactly that check.
- Note *(REFINE)*: `check_ids` match by **prefix**, as `--check` does
  (`check_ids=["a"]` selects the 3 retail checks whose id starts with `a`).
  That is intended, and the docstring and README must say so.

**R4 — bad data is an outcome, unevaluable is an outcome, neither raises (rule 7)** `must`
- Given `demo` with `checks/orders.yml` naming `datasource: wh`,
  `checks: [row_count > 0]`, and `TW_TEST_PG_PASSWORD` unset
- When `result = tw.run(demo, record=False)`
- Then it does not raise; the one result has `outcome is tw.Outcome.ERROR`
  and `message == "datasource wh: environment variable TW_TEST_PG_PASSWORD is not set"`;
  `result.exit_code() == 2`.
- Test note *(REFINE)*: remove the variable with `monkeypatch.delenv(...,
  raising=False)`; do not assume CI leaves it unset.

**R5 — nothing runs when the project is invalid (mirrors exit 3)** `must`
- Given `demo` with the `row_cnt` file from L2
- When `tw.run(demo)`
- Then `tw.ProjectError` is raised; `exc.diagnostics` holds exactly the
  diagnostic from L2; no store file is created and no run is recorded.
- Rationale: an invalid project returning an empty `RunResult` would have
  `outcome == PASS` and `exit_code() == 0` — a pipeline would sail on.
- And *(added in REFINE)* given `demo` with **no `checks/` directory at all**
  (a container image built without its checks), `tw.load(demo).ok is False`
  with a diagnostic whose text is
  `error: checks directory 'checks' does not exist`, and `tw.run(demo)`
  raises `tw.ProjectError` carrying it. (CLI today: exit 3, same text.)

**R6 — nothing runs when nothing matches (mirrors exit 3)** `must`
- Given the `retail` project
- When `tw.run(retail, tags=["no-such-tag"])`
- Then `tw.SelectionError` is raised with message
  `no checks matched the selection — nothing ran`.
- And `tw.run(retail, datasources=["nope"])` raises `tw.SelectionError` with
  message `unknown datasource: nope`.
- And `tw.run(retail, paths=["/etc"])` raises `tw.SelectionError` whose
  message contains `is outside the project at`.
- And *(added in REFINE)* given `demo` whose only check file is an empty
  `checks/orders.yml`, `tw.run(demo)` with **no selectors** raises
  `tw.SelectionError` (`no checks matched the selection — nothing ran`),
  and does not return an empty passing result. (CLI today: exit 3, after the
  `checks/orders.yml:1:1: warning: empty check file` warning.)

**R7 — load once, run many** `should`
- Given `project = tw.load(retail)`
- When `a = tw.run(project, record=False)` and `b = tw.run(project, record=False)`
- Then `a.id != b.id`, both have 18 results with the same outcomes, and
  `len(project.checks)` is still 18 (the project is not mutated).

**R8 — the library is quiet** `must`
- Given the `retail` project, and pytest's `capsys`
- When `tw.run(retail, record=False)`
- Then nothing is written to stdout; and
  `logging.getLogger("tablewatch").handlers` gains no handler other than,
  at most, a `logging.NullHandler` (the library never configures logging;
  the CLI does).
- And *(should, added in REFINE)* with `record=True`, the level of the
  `alembic` logger is unchanged after the run. Today `ResultStore._migrate`
  calls `logging.getLogger("alembic").setLevel(WARNING)`, which changes the
  host application's logging config. That is fine in the CLI's process but
  not in someone else's Airflow worker.

**R9 — bad arguments are rejected plainly** `should`
- When `tw.run(retail, concurrency=0)` or `tw.run(retail, fail_on="error")`
- Then `ValueError` is raised naming the argument, before any database is
  opened.
- And *(added in REFINE, **must**)* a bare string where a list is expected
  (`tw.run(retail, paths="checks/sales")`, `tags="catalogue"`) raises
  `TypeError` naming the argument. A `str` is a `Sequence[str]`, so mypy
  accepts it; the run would then select by each *character*, and at worst
  select a different set of checks.
- And *(added in REFINE)* `result.exit_code("warm")` raises `ValueError`.
  Today any value other than `"warn"` silently means `"fail"`.

**R10 — `exit_code()` follows the run's `fail_on`** `must` *(added in REFINE)*
- Given the `retail` project
- When `result = tw.run(retail, tags=["catalogue"], fail_on="warn", record=False)`
- Then `result.exit_code() == 1` (3 pass, 1 warn); and
  `result.exit_code("fail") == 0` still lets the caller ask the other
  question.
- Why: Dana writes `fail_on="warn"` once, at the call, and then checks
  `result.exit_code()`. If the no-argument form ignored the run's `fail_on`,
  a warning would pass silently, and the recorded exit code (S3) would
  disagree with the one she acted on. (R3 still holds: the default run gives
  `exit_code() == 0`.)

**R11 — results read well in a notebook** `should` *(added in REFINE)*
- Given `result = tw.run(retail, record=False)`
- Then `len(repr(result)) < 300`, and it shows the project, outcome and
  counts (e.g. `RunResult(project='retail-example', outcome=fail, 18 checks:
  10 pass, 2 warn, 6 fail, id='4cdf…')`). `repr(result.results[0])` is one
  line naming outcome, dataset, check name and display value.
- Today the dataclass repr of the retail run is **72,962 characters**,
  because each `CheckResult` embeds its `Check`, which embeds its `Dataset`
  and every sibling check. A notebook cell ending in `result` fills the
  screen.

**R12 — a selector that names nothing is not silently dropped** — **deferred**
*(added in REFINE; deferred by the tech lead: it changes CLI behaviour, so it
goes to the backlog as its own item rather than riding on this one)*
- Given the `retail` project
- When `tw.run(retail, paths=["checks/inventory", "checks/inventry"], record=False)`
- Then `tw.SelectionError` is raised naming `checks/inventry`.
- Today the CLI equivalent
  (`tablewatch run checks/inventory checks/inventry`) runs the 4 inventory
  checks and **exits 0**: the pipeline believes it checked a folder it never
  touched. The same holds for a misspelt `--tag` next to a real one. An
  unknown *datasource* already raises (R6), so paths and tags are the odd
  ones out.

### Recording and the result-sink seam

**S1 — `record=False` writes nothing** `must`
- Given a fresh copy of `retail` with no `.tablewatch/` directory
- When `tw.run(retail, record=False)`
- Then `retail/.tablewatch/` does not exist afterwards.
- And *(added in REFINE)* with the unusable store from S4 configured,
  `result = tw.run(retail, tags=["catalogue"], record=False)` gives
  `result.exit_code() == 0` and no recording error. This proves
  `record=False` never opens the store, rather than opening it and
  ignoring what it finds.

**S2 — `record=True` (the default) writes one run, marked as from Python** `must`
- Given a fresh copy of `retail`
- When `result = tw.run(retail)`
- Then the results store (`sqlite:///.tablewatch/results.db`, relative to the
  project root) holds one row in `tablewatch_runs` with `id == result.id`,
  `trigger == "python"`, `total == 18`, `failed == 6`, `exit_code == 1`,
  `selection == {}`, and 18 rows in `tablewatch_check_results`.
- And a run of the same project through `tablewatch run` records
  `trigger == "cli"` (unchanged).
- REFINE note on the value: `trigger` is an audit field, and Ravi reads it
  as "what started this run". I-02 will add runs started over **HTTP**; if
  those are also `"api"`, history cannot tell a notebook from the server.
  Consider `"python"` here, which leaves `"api"` (or `"rest"`) and
  `"schedule"` (E1) free. **Settled by the tech lead: `"python"`.**

**S3 — the recorded exit code is the caller's exit code** `must`
- Given the `retail` project
- When `result = tw.run(retail, tags=["catalogue"], fail_on="warn")`
- Then the recorded `exit_code` is `1`, and equals `result.exit_code()`
  for that call (see R10).
- Scope *(REFINE)*: this holds when recording succeeds. Under S6, a sink
  that fails *after* the store has written makes the caller's code 2 while
  the stored row says 1. That is acceptable, but the README must not promise
  more than this scenario does.

**S4 — a recording failure is "could not do its job", not a crash** `must`
- Given a copy of `retail` whose `tablewatch.yml` sets
  `results: {url: "sqlite:///tablewatch.yml/results.db"}` (the parent is a
  file, so the store cannot be created)
- When `result = tw.run(retail, tags=["catalogue"])`
- Then it does not raise; the 4 outcomes are intact (3 pass, 1 warn);
  `result.exit_code() == 2` **and `result.exit_code("fail") == 2`** (an
  explicit `fail_on` never hides the recording failure); `result.outcome`
  stays `warn` (it describes the data, and the exit code describes the
  run); the reason is available on the result (attribute name for the tech
  lead: **`result.record_errors`, a list of reasons, empty when recording
  succeeded or was not asked for**) and is logged at WARNING on a `tablewatch.*` logger.
- And `tablewatch --project-dir <copy> run checks/inventory` exits **2**,
  prints `tablewatch: could not record the run: ` followed by the reason on
  stderr, prints no traceback, **and still prints the 4 outcomes on stdout**.
  *(Verified in REFINE: today it exits 1 with a `FileExistsError` traceback
  and stdout is **empty**, because the store is written before the report.
  The outcomes are lost as well as the exit code.)*
- And the same holds for a store that is unreachable
  (`postgresql+psycopg://nobody@127.0.0.1:1/none`): exit 2, message on
  stderr, outcomes printed — as today.

**S5 — where results go is a replaceable component** `must`
- Given a sink written in the test — a class with the sink interface the
  tech lead defines (e.g. `write(run: RunResult) -> None`) that appends each
  run to a list — handed to the engine's entry point in place of the store
- When the `retail` checks run through it
- Then the list holds exactly one `RunResult` with 18 results, and no store
  file is created.
- And `src/tablewatch/engine/runner.py` does not import from
  `tablewatch.results` (checked by a test reading the module's imports), so
  the runner knows nothing about the store.

**S6 — one failing sink does not stop the others** `should`
- Given two sinks where the first raises `RuntimeError("boom")`
- When a run goes through both
- Then the second still receives the run, the outcomes are intact, and
  `exit_code()` is 2 with `boom` in the recorded reason.

### The CLI shares the code path

**C1 — the CLI is unchanged to its users** `must`
- Given the existing `tests/test_cli.py`
- When it runs against the new code
- Then every test passes **unmodified**; exit codes, console, JSON
  (`schema_version` 1) and JUnit output are unchanged.

**C2 — one code path** `must` (verified by architect in VERIFY)
- `tablewatch run` delegates selection, running and recording to the same
  function `tw.run()` uses; it keeps only argument parsing, printing
  diagnostics, and reporting. `--no-store` maps to `record=False`.

### Typing

**T1 — the package is typed for its users** `must`
- Given `uv build`
- Then the wheel contains `tablewatch/py.typed`.

**T2 — user code type-checks** `should`
- Given a file outside `src/` containing
  ```python
  import tablewatch as tw
  result: tw.RunResult = tw.run("examples/retail", record=False)
  first: tw.Outcome = result.results[0].outcome
  code: int = result.exit_code()
  ```
- When `mypy --strict` runs on it
- Then it reports no errors.

## Non-goals

- **The REST API and `tablewatch serve`** — I-02, which builds on this.
- **Configurable recording in YAML** (`record:` in `tablewatch.yml`,
  `_defaults.yml`, per check) — I-12. This spec gives only the per-call
  switch, which will be the strongest layer of E7.
- **Custom sinks as public API.** The seam is real and tested (S5), but
  `tw.run()` takes no `sinks=` or callback yet. Exposing it is a promise; A9
  (in-pipeline validation) and H1 (plugin SDK) will say what it must carry.
  Notifications (I-06) are the next internal consumer.
- **Raising on failure** (`assert_no_fail()` and the like). A9 decides how
  `fail` and `error` map to exceptions for in-pipeline use; a helper now
  would pre-empt it. Callers use `exit_code()`.
- **`compile()` / `validate()` / `history()` functions.** `load()` gives
  diagnostics; the SQL and history the UI needs arrive with I-02 and I-05.
- **DataFrames, files, or a `now=` override.** A9, I-08; `now` stays internal
  to tests.
- **Async.** A server can call `run()` from a worker thread (I-02's problem).
- **Any change to exit codes, the JSON report schema, check identity or the
  results-store tables.** `trigger` already exists as a column; `"api"` is a
  new value, not a migration.

## Design notes

Rules from `CLAUDE.md` that bind this item:

- **Rule 5.** `load()` never raises for a check-file mistake; `run()`
  refuses an invalid project by raising `ProjectError` *carrying every
  diagnostic*, which is the library equivalent of exit 3.
- **Rule 6.** `load()` and selection must work without credentials; secrets
  are still resolved only in `create_engine_for`. If the build moves that,
  security review becomes required.
- **Rule 7.** `run()` raises only when nothing could run (invalid project,
  empty or bad selection, bad arguments). `fail` and `error` are outcomes;
  a recording failure is an `error`-class exit (2), never an exception and
  never exit 1.
- **Exit codes.** Unchanged. S4 *restores* the contract where Phase 1 broke
  it (an `OSError` from creating the store's directory escapes the CLI's
  `except SQLAlchemyError`).
- **Check identity.** Untouched.
- **Results store.** No model change, so no migration. `ResultStore` stays
  the store; it becomes one implementation of the sink.

The seam (BACKLOG requirement, FEATURES "Modular seams"):

- The runner produces a `RunResult` and hands it to zero or more sinks. It
  must not know which. `record=False` means "no store sink", not a flag the
  store checks.
- The seam must leave room for **I-06 notifications**, which need the
  previous state of each check to alert only on change. Either a notifier
  sink reads history before the store sink writes, or the store sink exposes
  the previous outcomes. Do not settle it here; do not make it impossible.
- The stored `exit_code` depends on `fail_on`, which today only the CLI
  knows. S3 requires the recorded value to equal what the caller gets; how
  (a `fail_on` field on `RunResult`, or an argument to the sink) is the tech
  lead's call.

### Design decisions (settled in REFINE)

Architect review (approve-with-followups) and tech lead decisions. These
supersede the open questions below, which are kept for the record.

1. **Modules.** New `src/tablewatch/api.py`: `load`, `run` (public), and
   `execute`, `default_sinks` (internal — the one path shared by the CLI and,
   later, I-02). New `src/tablewatch/errors.py`: `TablewatchError`. Add
   `src/tablewatch/py.typed`. `__init__.py` assigns `__version__` first (the
   runner imports it), adds a `NullHandler` to the `tablewatch` logger, then
   re-exports.
2. **Exports** (`tablewatch.__all__`): `load`, `run`, `Project`,
   `RunResult`, `CheckResult`, `Check`, `Dataset`, `Outcome`, `Diagnostic`,
   `Severity`, `SourceLocation`, `TablewatchError`, `ProjectError`,
   `SelectionError`, `__version__`. Promised attributes — `Project`: `root`,
   `datasets`, `checks`, `diagnostics`, `ok`; `Check`: `id`, `short_id`,
   `name`, `canonical`, `location`, `dataset`; `Dataset`: `name`,
   `datasource`, `path`, `owner`, `tags`; `CheckResult`: `check`, `outcome`,
   `value`, `display_value`, `message`, `duration_ms`; `RunResult`: `id`,
   `project`, `started_at`, `finished_at`, `results`, `selection`,
   `trigger`, `fail_on`, `record_errors`, `outcome`, `count()`,
   `exit_code()`. Everything else (`Check.metric`, `expression`, `options`,
   `Project.config`, …) is provisional and says so in docstrings.
3. **Exceptions.** `TablewatchError` means "nothing ran";
   `ProjectError` and `SelectionError` subclass it. Bad arguments raise
   `ValueError` / `TypeError`. `load(None)` with no project above the cwd
   raises `ProjectError`.
4. **Sink.** `ResultSink = Callable[[RunResult], None]` in
   `engine/runner.py`. The store sink is a closure in `results/` that opens,
   saves and closes the store inside the call (lazy — so `record=False` and
   an invalid project never touch it). `ResultStore.save(run)` takes the exit
   code from `run.exit_code()`. `execute` delivers to each sink in order,
   catching `Exception` per sink; each failure appends a short reason to
   `RunResult.record_errors`, and `exit_code()` is 2 whenever that list is
   non-empty. The runner imports nothing from `tablewatch.results`.
5. **`fail_on`** is a field on `RunResult`, set by `execute`;
   `exit_code(fail_on=None)` uses it unless overridden (R10, S3).
   Not added to the JSON report — `schema_version` stays 1.
6. **Trigger.** `run_checks` takes `trigger`; the engine has no default
   caller. Values: `"cli"`, `"python"` (I-02 will add its own).
7. **Paths.** The API passes `cwd=project.root` to `select_checks`; the CLI
   passes `Path.cwd()`. `select_checks` is unchanged.
8. **Logging.** The library never adds handlers or changes levels; the
   `alembic` level moves into `logs.configure` (CLI only). `tw.run()` logs
   each recording failure and each warning diagnostic at WARNING on
   `tablewatch.api`; `execute` itself does not log them, so the CLI prints
   its existing `tablewatch: could not record the run: …` line once.
9. **Deferred to the backlog:** R12 (selectors that match nothing); exit 2
   instead of a traceback for store and file errors in `runs`, `history`
   and `--output-file`; a one-time store migration for long-lived servers
   (I-02 / I-14).

Open questions for the tech lead and architect (REFINE):

1. The exact public export list and whether `Check`/`Dataset` (reachable
   through `CheckResult.check`) are declared public now. They will be, in
   practice, once anyone writes `r.check.name`; the architect should say
   which attributes we promise.
2. An exception base class (`tw.TablewatchError`) for `ProjectError` and
   `SelectionError`, so callers can catch "nothing ran" in one clause?
3. Where the sink protocol lives (`results/`, `engine/`, or a new module)
   given that `results/store.py` imports `RunResult` from `engine/runner.py`
   today — avoid a cycle.
4. Thread-safety: I-02 will call `run()` from a server. Confirm no
   module-level mutable state in the run path.
5. Path selection: the API resolves relative paths against the project root
   (R2); the CLI keeps "cwd first, then project root". Confirm
   `select_checks(..., cwd=project.root)` gives exactly that without
   changing the CLI.

User docs: a "Use from Python" section in `README.md` (data-steward), with
the example from **Outcome** and a note that `record=False` keeps
exploratory runs out of history. Written against the final names.

## Reviewers required

- **qa-engineer** — always. Focus: S4/S6 failure paths, R5/R6 "nothing ran"
  vs. an empty passing run, path resolution from odd working directories,
  running the same `Project` twice.
- **data-steward** — always. Focus: that `fail` vs `error` and the exit
  codes read the same from Python as from the CLI; the README section.
- **architect** — required: this touches `src/`, and it adds a **public
  API and a seam**, so architect reviews in **REFINE** (open questions 1–5)
  as well as VERIFY (C2, S5).
- **security-reviewer** — **not required.** Checked against every trigger
  in PROCESS.md: no new dependency; no change to where or how secrets are
  resolved (rule 6 is preserved and tested by L3/R4); nothing new reaches
  SQL; no network calls; no new place files are written (the store is
  existing, and `record=False` writes less); no row data stored or exposed.
  This becomes required if the build adds a dependency or touches
  credential resolution.
- ui-engineer, platform-engineer — not involved.

## Size

**S** — one iteration. A thin module over existing functions, a sink
interface with one real implementation, a CLI refactor held in place by the
existing CLI tests, one bug fix, `py.typed`, and a README section. Nothing
was split out; the related work already sits in other items (I-12 for YAML
recording, I-02 for serving).
