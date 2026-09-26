"""Files written by `tablewatch init`."""

from __future__ import annotations

TABLEWATCH_YML = """\
name: {name}

# Each datasource is a connection checks can run against. Secrets are only
# ever referenced from the environment — never written here.
datasources:
  warehouse:
    type: duckdb
    path: warehouse.duckdb
  # analytics:
  #   type: postgres
  #   host: ${{env:PGHOST}}
  #   database: analytics
  #   user: ${{env:PGUSER}}
  #   password: ${{env:PGPASSWORD}}

# Where run history is kept. Point several servers at one Postgres to share it.
results:
  url: sqlite:///.tablewatch/results.db
"""

DEFAULTS_YML = """\
# Settings inherited by every check file in this folder and below.
# A _defaults.yml nearer a file wins; tags accumulate down the tree.
datasource: warehouse
owner: data-team@example.com
tags: [example]
"""

EXAMPLE_CHECKS_YML = """\
dataset: orders
# filter: created_at >= CURRENT_DATE - INTERVAL 1 DAY   # check only recent rows

checks:
  - row_count > 0
  - missing_count(order_id) = 0
  - duplicate_count(order_id) = 0
  - freshness(created_at) < 1d
  - invalid_percent(status) < 1%:
      valid_values: [pending, shipped, delivered, cancelled]
  - row_count:
      name: Order volume
      warn: when < 100
      fail: when = 0
"""

GITIGNORE = """\
.tablewatch/
*.duckdb
*.duckdb.wal
"""

VSCODE_SETTINGS = """\
{
  "yaml.schemas": {
    "./schemas/check-file.schema.json": ["checks/**/*.yml", "checks/**/*.yaml"],
    "./schemas/tablewatch.schema.json": ["tablewatch.yml"]
  }
}
"""
