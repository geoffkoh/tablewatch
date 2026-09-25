# CLAUDE.md: tablewatch

Data quality checking library — the same space as Soda, Great Expectations,
and Deequ. Python library + CLI, published to PyPI as `tablewatch`, with the
commands `tablewatch` and the short alias `tw`. Repo: `geoffkoh/tablewatch`.

This file is self-contained. Do not carry conventions in from `c4studio/` or
`bizkit/` beyond what is written here.

## Stack and commands

Python >= 3.13, managed with `uv`, `src/` layout, `uv_build` backend.

```bash
uv sync                # create .venv and resolve
uv run pytest          # tests
uv run ruff check .    # lint
uv run ruff format .   # format
uv run mypy .          # type check (strict)
uv build               # wheel + sdist into dist/
```

Run all four gates before opening a PR.

## Conventions

- **click** for the CLI, **pydantic** for models. Both are already
  dependencies; reach for them before adding a third.
- `from __future__ import annotations` at the top of every module.
- mypy runs `strict = true`. Annotate public functions fully.
- The ruff rule set is stated outright in `pyproject.toml` rather than
  inherited from ruff's defaults, so a ruff upgrade is an upgrade and not a
  silent change of contract. Add rules deliberately, with a reason.
- Docstrings on public API in `src/`. Comments explain *why*, not *what*.

## The name

`tablewatch` states the product in one read: the unit a data quality check
runs against is a table, and "watch" says monitoring rather than one-shot
validation.

`datawatch` was the first choice and was **rejected**: DATAWATCH is a live
trademark held by Altair Engineering (Datawatch Corp, data-prep software,
acquired 2018, mark re-registered Feb 2025) covering the same goods class.
Do not revive it. The metaphor names (`assay`, `litmus`, `touchstone`,
`winnow`, `hallmark`) are all squatted on PyPI.

## Open design decisions

Nothing downstream of these should be built until they are settled — a
placeholder command or config schema would fix them by accident:

1. **Check authoring format** — YAML (Soda's SodaCL), a Python API (Great
   Expectations), or SQL-native.
2. **Data sources** — warehouses (Snowflake / BigQuery / Databricks),
   DataFrames (pandas / polars), or files. This decides whether
   `sqlalchemy` becomes a core dependency, as it is in `bizkit`.
3. **Scope of "watch"** — one-shot CLI validation, or scheduled monitoring
   with run history and anomaly detection. The name promises the latter;
   the first release need not deliver it.

`src/tablewatch/checks/` is an empty package placeholder awaiting (1).

## Secrets

Never put a credential in a commit, a config file, or a test fixture. Data
source credentials are read from the environment at the moment they are
used. This matters more here than in a sibling project: the library connects
to production warehouses.
