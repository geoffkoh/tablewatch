# tablewatch

Data quality checks for your tables: assert, monitor, and alert on the state
of your data.

> **Status: planning.** The package skeleton is in place and the name is
> reserved. The check engine is not designed yet — see
> [Open questions](#open-questions).

## Install

```bash
uv add tablewatch
```

## Usage

```bash
tablewatch --help   # or the short alias: tw --help
```

There are no commands yet. Adding one now would fix design decisions that
are still open.

## Open questions

These shape the API and are deliberately undecided:

- **Check authoring format** — YAML (as Soda's SodaCL), a Python API (as
  Great Expectations), or SQL-native.
- **Data sources** — warehouses (Snowflake, BigQuery, Databricks),
  DataFrames (pandas, polars), or files.
- **Scope of "watch"** — one-shot CLI validation, or scheduled monitoring
  with run history and anomaly detection. The name promises the latter; the
  first release need not deliver it.

## Development

```bash
uv sync
uv run pytest
uv run ruff check .
uv run mypy .
```

## License

MIT — see [LICENSE](LICENSE).
