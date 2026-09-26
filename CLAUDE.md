# CLAUDE.md: tablewatch

Data quality checking library — the same space as Soda, Great Expectations,
and Deequ. Python library + CLI, published to PyPI as `tablewatch`, with the
commands `tablewatch` and the short alias `tw`. Repo: `geoffkoh/tablewatch`.

This file is self-contained. Do not carry conventions in from `c4studio/` or
`bizkit/` beyond what is written here.

Phase 1 (engine + CLI, `0.1.0`) is built. The phases after it are in
`docs/ROADMAP.md`; build one phase at a time, and do not pull later-phase
features forward without being asked.

## Team and process

Everything after Phase 1 is built in iterations. **`docs/product/PROCESS.md`
is the protocol — read it before running an iteration.** It covers steps,
definitions of ready and done, when security review is mandatory, the merge
policy, and when to stop and ask the user.

- The main session is **tech lead**: it runs each step, builds core Python,
  and opens and merges PRs.
- Agents in `.claude/agents/`: `product-manager` (plans, specs, retro),
  `data-steward` (domain semantics, acceptance), `qa-engineer`
  (adversarial tests), `security-reviewer` (read-only), `architect`
  (design review, read-only), `ui-engineer` (frontend), `platform-engineer`
  (connectors, deployment, benchmarks).
  Builders never judge their own work.
- Product documents live in `docs/product/`: `VISION.md`, `FEATURES.md`,
  `BACKLOG.md`, `specs/`, `ITERATIONS.md`, `PROCESS.md`.
- **Merge policy (tablewatch only):** auto-merge an iteration PR when CI is
  green, no required reviewer has an open blocking finding, and the
  definition of done is met. Outward-facing steps (PyPI releases, new
  external services) always need the user.
- "Run N iterations" runs N. Without a number, run one and stop.

## Stack and commands

Python >= 3.13, managed with `uv`, `src/` layout, `uv_build` backend.

```bash
uv sync                # create .venv and resolve (dev group includes duckdb)
uv run pytest          # tests; warnings are errors (filterwarnings = error)
uv run ruff check .    # lint
uv run ruff format .   # format
uv run mypy .          # type check (strict)
uv build               # wheel + sdist into dist/

uv run python examples/retail/build.py                   # example database
uv run tablewatch --project-dir examples/retail run      # exits 1: planted defects
```

Run all four gates before opening a PR. If the shell has another project's
venv active, uv warns `VIRTUAL_ENV ... does not match`; `unset VIRTUAL_ENV`.

## How it works

```
load YAML tree ─► parse DSL ─► resolve ─► plan ─► execute ─► evaluate ─► record ─► report
```

| Module | Responsibility |
| --- | --- |
| `diagnostics.py` | `Diagnostic` with a 1-based `file:line:col` |
| `dsl/` | lexer, recursive-descent parser, AST for check expressions |
| `config/project.py` | pydantic models for `tablewatch.yml`; `${env:}` resolution |
| `config/yamlsource.py` | ruamel round-trip loading; ruamel marks → `SourceLocation` |
| `config/loader.py` | walks `checks/`, `_defaults.yml` inheritance, builds `Check`s, collects diagnostics |
| `config/jsonschema.py` | editor schemas, generated from the metric registry |
| `checks/model.py` | `Dataset`, `Check`, `Outcome`, check identity |
| `metrics/base.py` | the metric contract: measures + compute |
| `metrics/builtin/` | one module per metric family |
| `engine/planner.py` | folds aggregates into one scan; dedupes measures |
| `engine/executor.py` | runs a plan; isolates a failing measure |
| `engine/evaluate.py` | value + rule → outcome; value formatting |
| `engine/runner.py` | orchestration: parallel across datasources, serial within one |
| `datasources/` | config → dialect (no credentials) or engine (credentials) |
| `results/` | ORM models, Alembic migrations, `ResultStore` |
| `output/` | console, JSON and JUnit reporters |
| `selection.py` | paths / tags / datasources / excludes / check ids |
| `cli/main.py` | click commands and the exit-code contract |
| `api.py` | the Python API (`load`, `run`) and `execute`, the one run path shared with the CLI |
| `server/` | internal HTTP adapter for `serve`: read-only `/api/v1`, wire schemas, host guard; holds no SQL; FastAPI and uvicorn are imported only here, only when `serve` runs |

### Rules the design depends on — keep them

1. **One scan per dataset.** A metric never runs SQL itself: it returns
   *measures* — `AggregateMeasure` (folded into the dataset's single
   `SELECT`), `QueryMeasure` (its own statement), or `SchemaMeasure`. Keep new
   metrics aggregate-shaped wherever possible.
2. **SQL counts, Python does the math.** Percentages, freshness (`now − MAX`),
   and thresholds are computed in Python so the SQL stays portable. Do not add
   per-dialect date arithmetic.
3. **Same meaning on every database.** Where dialects differ, normalise in
   `MetricContext` (see `regex_search`: DuckDB's `~` is a full match, so it
   uses `regexp_matches`). Metric tests run on DuckDB **and** SQLite; add
   both for any new metric.
4. **Columns are untyped** (the table is never reflected), so compare them
   against `literal(value)`, never a bare Python value — a bare value binds
   as NULL-typed and cannot be rendered.
5. **Every user mistake is a `Diagnostic` at `file:line:col`**, and loading
   reports all of them in one pass. Never raise from a check file.
6. **Secrets are `${env:NAME}` references**, resolved only in
   `create_engine_for`. `validate`, `list`, and `compile` must keep working
   with no credentials.
7. **One dataset never ends a run.** Failures become `error` outcomes on
   the checks they affect. `error` means tablewatch could not evaluate;
   `fail` means the data is bad. The exit codes (0/1/2/3, documented in
   `cli/main.py`) are a contract with orchestrators — do not change them.

### Check identity

An explicit `id:`, or a hash of the file path, dataset, canonical expression
with its triggers, and `where:` (`derive_check_id`). History keys on it, so
changing what feeds the hash is a breaking change for every user's history.

### Results store

Tables are prefixed `tablewatch_`, and Alembic uses its own
`tablewatch_alembic_version` table, so the store can share a database.
`ResultStore` migrates on open. **Any change to `results/models.py` needs a
new revision in `results/migrations/versions/`**:
`uv run alembic revision --autogenerate -m "..."` (uses `alembic.ini`).
`tests/test_results.py::test_migrations_match_the_models` fails on drift.

## Conventions

- **click** for the CLI, **pydantic** for config models, **SQLAlchemy Core**
  for SQL. Reach for these before adding a dependency; every dependency is a
  line item in someone's security review.
- `from __future__ import annotations` at the top of every module.
- mypy runs `strict = true`. Annotate everything.
- Logs go to stderr, never stdout.
- The ruff rule set is stated outright in `pyproject.toml` rather than
  inherited from ruff's defaults. Add rules deliberately, with a reason.
- Docstrings on public API in `src/`. Comments explain *why*, not *what*.
- New metric: a module in `metrics/builtin/`, registered at import; tests
  in `tests/test_metrics.py` on both backends; a row in
  `docs/check-language.md` (`tests/test_docs.py` enforces it).

## The name

`tablewatch` states the product in one read. `datawatch` was rejected:
DATAWATCH is a live Altair Engineering trademark in the same goods class. Do
not revive it.

## Secrets

Never put a credential in a commit, a config file, or a test fixture.
Datasource credentials come from the environment at the moment of
connecting. This matters here: the library connects to production
warehouses.
