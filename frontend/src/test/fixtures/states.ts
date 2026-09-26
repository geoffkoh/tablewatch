/*
 * API responses for the named Python fixture states of spec 003 (tests/conftest.py),
 * captured from the in-process app on examples/retail and normalised: run ids are
 * A/B/E/F placeholders, timestamps are fixed (A 06:55:50, B 06:56:12, E 06:56:30,
 * F 06:56:45 UTC on 2026-09-26), and the build path in the IO error is replaced.
 * Freshness values vary with build time (spec 002) and are not asserted.
 *
 * Typed against the generated contract: a contract change breaks `tsc` here.
 */
import type { CheckList, Project, RunPage } from "../../api/types";

export interface OverviewResponses {
  project: Project;
  checks: CheckList;
  runs: RunPage;
}

export const RUN_ID = {"A": "a0000000000000000000000000000001", "B": "b0000000000000000000000000000002", "E": "e0000000000000000000000000000003", "F": "f0000000000000000000000000000004"} as const;

export const STARTED = {"A": "2026-09-26T06:55:50.000000+00:00", "B": "2026-09-26T06:56:12.000000+00:00", "E": "2026-09-26T06:56:30.000000+00:00", "F": "2026-09-26T06:56:45.000000+00:00"} as const;

/** `recorded`. */
export const recorded: OverviewResponses = {
  "project": {
    "name": "retail-example",
    "version": "0.1.0",
    "loaded_at": "2026-09-26T06:56:50.000000+00:00",
    "ok": true,
    "datasources": [
      {
        "name": "lake",
        "type": "duckdb"
      }
    ],
    "counts": {
      "datasets": 3,
      "checks": 18
    },
    "diagnostics": []
  },
  "checks": {
    "items": [
      {
        "id": "cd3e8103b4318809",
        "name": "row_count between 1 and 10000",
        "expression": "row_count between 1 and 10000",
        "metric": "row_count",
        "unit": "count",
        "dataset": "inventory.products",
        "datasource": "lake",
        "owner": "data-platform@example.com",
        "tags": [
          "example",
          "catalogue"
        ],
        "source": "checks/inventory/products.yml:5:5",
        "location": {
          "file": "checks/inventory/products.yml",
          "line": 5,
          "column": 5
        },
        "latest": {
          "run_id": "a0000000000000000000000000000001",
          "started_at": "2026-09-26T06:55:50.000000+00:00",
          "since": "2026-09-26T06:55:50.000000+00:00",
          "trigger": "cli",
          "outcome": "pass",
          "value": 3.0,
          "display_value": "3",
          "message": null,
          "last_evaluated": null
        }
      },
      {
        "id": "8b9c5af854ba2a5f",
        "name": "duplicate_count(sku) = 0",
        "expression": "duplicate_count(sku) = 0",
        "metric": "duplicate_count",
        "unit": "count",
        "dataset": "inventory.products",
        "datasource": "lake",
        "owner": "data-platform@example.com",
        "tags": [
          "example",
          "catalogue"
        ],
        "source": "checks/inventory/products.yml:6:5",
        "location": {
          "file": "checks/inventory/products.yml",
          "line": 6,
          "column": 5
        },
        "latest": {
          "run_id": "a0000000000000000000000000000001",
          "started_at": "2026-09-26T06:55:50.000000+00:00",
          "since": "2026-09-26T06:55:50.000000+00:00",
          "trigger": "cli",
          "outcome": "pass",
          "value": 0.0,
          "display_value": "0",
          "message": null,
          "last_evaluated": null
        }
      },
      {
        "id": "ace45b91cd324084",
        "name": "min(price) > 0",
        "expression": "min(price) > 0",
        "metric": "min",
        "unit": "number",
        "dataset": "inventory.products",
        "datasource": "lake",
        "owner": "data-platform@example.com",
        "tags": [
          "example",
          "catalogue"
        ],
        "source": "checks/inventory/products.yml:7:5",
        "location": {
          "file": "checks/inventory/products.yml",
          "line": 7,
          "column": 5
        },
        "latest": {
          "run_id": "a0000000000000000000000000000001",
          "started_at": "2026-09-26T06:55:50.000000+00:00",
          "since": "2026-09-26T06:55:50.000000+00:00",
          "trigger": "cli",
          "outcome": "pass",
          "value": 39.9,
          "display_value": "39.9",
          "message": null,
          "last_evaluated": null
        }
      },
      {
        "id": "41e58afff9c48a46",
        "name": "Price feed freshness",
        "expression": "freshness(updated_at) | warn when > 1d | fail when > 7d",
        "metric": "freshness",
        "unit": "duration",
        "dataset": "inventory.products",
        "datasource": "lake",
        "owner": "data-platform@example.com",
        "tags": [
          "example",
          "catalogue"
        ],
        "source": "checks/inventory/products.yml:8:5",
        "location": {
          "file": "checks/inventory/products.yml",
          "line": 8,
          "column": 5
        },
        "latest": {
          "run_id": "a0000000000000000000000000000001",
          "started_at": "2026-09-26T06:55:50.000000+00:00",
          "since": "2026-09-26T06:55:50.000000+00:00",
          "trigger": "cli",
          "outcome": "warn",
          "value": 259200.817941,
          "display_value": "3d 1s",
          "message": "warn when > 1d; newest 2026-09-23T06:55:49.000000+00:00",
          "last_evaluated": null
        }
      },
      {
        "id": "32c8f939b90f6367",
        "name": "row_count > 0",
        "expression": "row_count > 0",
        "metric": "row_count",
        "unit": "count",
        "dataset": "sales.customers",
        "datasource": "lake",
        "owner": "sales-data@example.com",
        "tags": [
          "example",
          "sales",
          "tier-1"
        ],
        "source": "checks/sales/customers.yml:4:5",
        "location": {
          "file": "checks/sales/customers.yml",
          "line": 4,
          "column": 5
        },
        "latest": {
          "run_id": "b0000000000000000000000000000002",
          "started_at": "2026-09-26T06:56:12.000000+00:00",
          "since": "2026-09-26T06:55:50.000000+00:00",
          "trigger": "cli",
          "outcome": "pass",
          "value": 5.0,
          "display_value": "5",
          "message": null,
          "last_evaluated": null
        }
      },
      {
        "id": "af0289a72fedd946",
        "name": "duplicate_count(customer_id) = 0",
        "expression": "duplicate_count(customer_id) = 0",
        "metric": "duplicate_count",
        "unit": "count",
        "dataset": "sales.customers",
        "datasource": "lake",
        "owner": "sales-data@example.com",
        "tags": [
          "example",
          "sales",
          "tier-1"
        ],
        "source": "checks/sales/customers.yml:5:5",
        "location": {
          "file": "checks/sales/customers.yml",
          "line": 5,
          "column": 5
        },
        "latest": {
          "run_id": "b0000000000000000000000000000002",
          "started_at": "2026-09-26T06:56:12.000000+00:00",
          "since": "2026-09-26T06:55:50.000000+00:00",
          "trigger": "cli",
          "outcome": "pass",
          "value": 0.0,
          "display_value": "0",
          "message": null,
          "last_evaluated": null
        }
      },
      {
        "id": "b1ceb8262d8b5441",
        "name": "missing_percent(email) < 5%",
        "expression": "missing_percent(email) < 5%",
        "metric": "missing_percent",
        "unit": "percent",
        "dataset": "sales.customers",
        "datasource": "lake",
        "owner": "sales-data@example.com",
        "tags": [
          "example",
          "sales",
          "tier-1"
        ],
        "source": "checks/sales/customers.yml:6:5",
        "location": {
          "file": "checks/sales/customers.yml",
          "line": 6,
          "column": 5
        },
        "latest": {
          "run_id": "b0000000000000000000000000000002",
          "started_at": "2026-09-26T06:56:12.000000+00:00",
          "since": "2026-09-26T06:55:50.000000+00:00",
          "trigger": "cli",
          "outcome": "fail",
          "value": 20.0,
          "display_value": "20.00%",
          "message": "expected < 5%",
          "last_evaluated": null
        }
      },
      {
        "id": "000f8d0048744bfb",
        "name": "invalid_count(country) = 0",
        "expression": "invalid_count(country) = 0",
        "metric": "invalid_count",
        "unit": "count",
        "dataset": "sales.customers",
        "datasource": "lake",
        "owner": "sales-data@example.com",
        "tags": [
          "example",
          "sales",
          "tier-1"
        ],
        "source": "checks/sales/customers.yml:8:5",
        "location": {
          "file": "checks/sales/customers.yml",
          "line": 8,
          "column": 5
        },
        "latest": {
          "run_id": "b0000000000000000000000000000002",
          "started_at": "2026-09-26T06:56:12.000000+00:00",
          "since": "2026-09-26T06:55:50.000000+00:00",
          "trigger": "cli",
          "outcome": "fail",
          "value": 1.0,
          "display_value": "1",
          "message": "expected = 0",
          "last_evaluated": null
        }
      },
      {
        "id": "b6ecae522c1d4aaf",
        "name": "invalid_count(email) = 0",
        "expression": "invalid_count(email) = 0",
        "metric": "invalid_count",
        "unit": "count",
        "dataset": "sales.customers",
        "datasource": "lake",
        "owner": "sales-data@example.com",
        "tags": [
          "example",
          "sales",
          "tier-1"
        ],
        "source": "checks/sales/customers.yml:10:5",
        "location": {
          "file": "checks/sales/customers.yml",
          "line": 10,
          "column": 5
        },
        "latest": {
          "run_id": "b0000000000000000000000000000002",
          "started_at": "2026-09-26T06:56:12.000000+00:00",
          "since": "2026-09-26T06:55:50.000000+00:00",
          "trigger": "cli",
          "outcome": "pass",
          "value": 0.0,
          "display_value": "0",
          "message": null,
          "last_evaluated": null
        }
      },
      {
        "id": "f81f9ff5edea8887",
        "name": "row_count > 0",
        "expression": "row_count > 0",
        "metric": "row_count",
        "unit": "count",
        "dataset": "sales.orders",
        "datasource": "lake",
        "owner": "sales-data@example.com",
        "tags": [
          "example",
          "sales",
          "tier-1"
        ],
        "source": "checks/sales/orders.yml:4:5",
        "location": {
          "file": "checks/sales/orders.yml",
          "line": 4,
          "column": 5
        },
        "latest": {
          "run_id": "b0000000000000000000000000000002",
          "started_at": "2026-09-26T06:56:12.000000+00:00",
          "since": "2026-09-26T06:55:50.000000+00:00",
          "trigger": "cli",
          "outcome": "pass",
          "value": 7.0,
          "display_value": "7",
          "message": null,
          "last_evaluated": null
        }
      },
      {
        "id": "32867fbe86f483f3",
        "name": "Order volume",
        "expression": "row_count | warn when < 100 | fail when = 0",
        "metric": "row_count",
        "unit": "count",
        "dataset": "sales.orders",
        "datasource": "lake",
        "owner": "sales-data@example.com",
        "tags": [
          "example",
          "sales",
          "tier-1"
        ],
        "source": "checks/sales/orders.yml:5:5",
        "location": {
          "file": "checks/sales/orders.yml",
          "line": 5,
          "column": 5
        },
        "latest": {
          "run_id": "b0000000000000000000000000000002",
          "started_at": "2026-09-26T06:56:12.000000+00:00",
          "since": "2026-09-26T06:55:50.000000+00:00",
          "trigger": "cli",
          "outcome": "warn",
          "value": 7.0,
          "display_value": "7",
          "message": "warn when < 100",
          "last_evaluated": null
        }
      },
      {
        "id": "fc9cc3088acaf77a",
        "name": "missing_count(customer_id) = 0",
        "expression": "missing_count(customer_id) = 0",
        "metric": "missing_count",
        "unit": "count",
        "dataset": "sales.orders",
        "datasource": "lake",
        "owner": "sales-data@example.com",
        "tags": [
          "example",
          "sales",
          "tier-1"
        ],
        "source": "checks/sales/orders.yml:9:5",
        "location": {
          "file": "checks/sales/orders.yml",
          "line": 9,
          "column": 5
        },
        "latest": {
          "run_id": "b0000000000000000000000000000002",
          "started_at": "2026-09-26T06:56:12.000000+00:00",
          "since": "2026-09-26T06:55:50.000000+00:00",
          "trigger": "cli",
          "outcome": "fail",
          "value": 1.0,
          "display_value": "1",
          "message": "expected = 0",
          "last_evaluated": null
        }
      },
      {
        "id": "11c20dd55fb97fa9",
        "name": "duplicate_count(order_id) = 0",
        "expression": "duplicate_count(order_id) = 0",
        "metric": "duplicate_count",
        "unit": "count",
        "dataset": "sales.orders",
        "datasource": "lake",
        "owner": "sales-data@example.com",
        "tags": [
          "example",
          "sales",
          "tier-1"
        ],
        "source": "checks/sales/orders.yml:10:5",
        "location": {
          "file": "checks/sales/orders.yml",
          "line": 10,
          "column": 5
        },
        "latest": {
          "run_id": "b0000000000000000000000000000002",
          "started_at": "2026-09-26T06:56:12.000000+00:00",
          "since": "2026-09-26T06:55:50.000000+00:00",
          "trigger": "cli",
          "outcome": "fail",
          "value": 1.0,
          "display_value": "1",
          "message": "expected = 0",
          "last_evaluated": null
        }
      },
      {
        "id": "a30dacf7316eef07",
        "name": "invalid_percent(status) < 1%",
        "expression": "invalid_percent(status) < 1%",
        "metric": "invalid_percent",
        "unit": "percent",
        "dataset": "sales.orders",
        "datasource": "lake",
        "owner": "sales-data@example.com",
        "tags": [
          "example",
          "sales",
          "tier-1"
        ],
        "source": "checks/sales/orders.yml:11:5",
        "location": {
          "file": "checks/sales/orders.yml",
          "line": 11,
          "column": 5
        },
        "latest": {
          "run_id": "b0000000000000000000000000000002",
          "started_at": "2026-09-26T06:56:12.000000+00:00",
          "since": "2026-09-26T06:55:50.000000+00:00",
          "trigger": "cli",
          "outcome": "fail",
          "value": 14.285714285714286,
          "display_value": "14.29%",
          "message": "expected < 1%",
          "last_evaluated": null
        }
      },
      {
        "id": "366d9254d889c910",
        "name": "avg(amount) between 10 and 500",
        "expression": "avg(amount) between 10 and 500",
        "metric": "avg",
        "unit": "number",
        "dataset": "sales.orders",
        "datasource": "lake",
        "owner": "sales-data@example.com",
        "tags": [
          "example",
          "sales",
          "tier-1"
        ],
        "source": "checks/sales/orders.yml:13:5",
        "location": {
          "file": "checks/sales/orders.yml",
          "line": 13,
          "column": 5
        },
        "latest": {
          "run_id": "b0000000000000000000000000000002",
          "started_at": "2026-09-26T06:56:12.000000+00:00",
          "since": "2026-09-26T06:55:50.000000+00:00",
          "trigger": "cli",
          "outcome": "pass",
          "value": 54.357142857142854,
          "display_value": "54.3571",
          "message": null,
          "last_evaluated": null
        }
      },
      {
        "id": "a81b0374b0b04f06",
        "name": "freshness(created_at) < 6h",
        "expression": "freshness(created_at) < 6h",
        "metric": "freshness",
        "unit": "duration",
        "dataset": "sales.orders",
        "datasource": "lake",
        "owner": "sales-data@example.com",
        "tags": [
          "example",
          "sales",
          "tier-1"
        ],
        "source": "checks/sales/orders.yml:14:5",
        "location": {
          "file": "checks/sales/orders.yml",
          "line": 14,
          "column": 5
        },
        "latest": {
          "run_id": "b0000000000000000000000000000002",
          "started_at": "2026-09-26T06:56:12.000000+00:00",
          "since": "2026-09-26T06:55:50.000000+00:00",
          "trigger": "cli",
          "outcome": "pass",
          "value": 3601.231287,
          "display_value": "1h 1s",
          "message": "newest 2026-09-26T05:55:49.000000+00:00",
          "last_evaluated": null
        }
      },
      {
        "id": "ed669ca6e5532a59",
        "name": "No negative amounts",
        "expression": "failed_rows",
        "metric": "failed_rows",
        "unit": "count",
        "dataset": "sales.orders",
        "datasource": "lake",
        "owner": "sales-data@example.com",
        "tags": [
          "example",
          "sales",
          "tier-1"
        ],
        "source": "checks/sales/orders.yml:15:5",
        "location": {
          "file": "checks/sales/orders.yml",
          "line": 15,
          "column": 5
        },
        "latest": {
          "run_id": "b0000000000000000000000000000002",
          "started_at": "2026-09-26T06:56:12.000000+00:00",
          "since": "2026-09-26T06:55:50.000000+00:00",
          "trigger": "cli",
          "outcome": "fail",
          "value": 1.0,
          "display_value": "1",
          "message": "expected = 0",
          "last_evaluated": null
        }
      },
      {
        "id": "fbc3aa0b93b66eee",
        "name": "schema",
        "expression": "schema",
        "metric": "schema",
        "unit": "count",
        "dataset": "sales.orders",
        "datasource": "lake",
        "owner": "sales-data@example.com",
        "tags": [
          "example",
          "sales",
          "tier-1"
        ],
        "source": "checks/sales/orders.yml:18:5",
        "location": {
          "file": "checks/sales/orders.yml",
          "line": 18,
          "column": 5
        },
        "latest": {
          "run_id": "b0000000000000000000000000000002",
          "started_at": "2026-09-26T06:56:12.000000+00:00",
          "since": "2026-09-26T06:55:50.000000+00:00",
          "trigger": "cli",
          "outcome": "pass",
          "value": 0.0,
          "display_value": "0",
          "message": null,
          "last_evaluated": null
        }
      }
    ],
    "total": 18
  },
  "runs": {
    "items": [
      {
        "id": "b0000000000000000000000000000002",
        "project": "retail-example",
        "started_at": "2026-09-26T06:56:12.000000+00:00",
        "finished_at": "2026-09-26T06:56:12.900000+00:00",
        "outcome": "fail",
        "exit_code": 1,
        "trigger": "cli",
        "version": "0.1.0",
        "selection": {
          "paths": [
            "checks/sales"
          ]
        },
        "counts": {
          "total": 14,
          "pass": 7,
          "warn": 1,
          "fail": 6,
          "error": 0,
          "skipped": 0
        }
      }
    ],
    "next_cursor": "bmV4dC1wYWdl"
  }
};

/** `beforeF`. */
export const beforeF: OverviewResponses = {
  "project": {
    "name": "retail-example",
    "version": "0.1.0",
    "loaded_at": "2026-09-26T06:56:50.000000+00:00",
    "ok": true,
    "datasources": [
      {
        "name": "lake",
        "type": "duckdb"
      }
    ],
    "counts": {
      "datasets": 3,
      "checks": 18
    },
    "diagnostics": []
  },
  "checks": {
    "items": [
      {
        "id": "cd3e8103b4318809",
        "name": "row_count between 1 and 10000",
        "expression": "row_count between 1 and 10000",
        "metric": "row_count",
        "unit": "count",
        "dataset": "inventory.products",
        "datasource": "lake",
        "owner": "data-platform@example.com",
        "tags": [
          "example",
          "catalogue"
        ],
        "source": "checks/inventory/products.yml:5:5",
        "location": {
          "file": "checks/inventory/products.yml",
          "line": 5,
          "column": 5
        },
        "latest": {
          "run_id": "a0000000000000000000000000000001",
          "started_at": "2026-09-26T06:55:50.000000+00:00",
          "since": "2026-09-26T06:55:50.000000+00:00",
          "trigger": "cli",
          "outcome": "pass",
          "value": 3.0,
          "display_value": "3",
          "message": null,
          "last_evaluated": null
        }
      },
      {
        "id": "8b9c5af854ba2a5f",
        "name": "duplicate_count(sku) = 0",
        "expression": "duplicate_count(sku) = 0",
        "metric": "duplicate_count",
        "unit": "count",
        "dataset": "inventory.products",
        "datasource": "lake",
        "owner": "data-platform@example.com",
        "tags": [
          "example",
          "catalogue"
        ],
        "source": "checks/inventory/products.yml:6:5",
        "location": {
          "file": "checks/inventory/products.yml",
          "line": 6,
          "column": 5
        },
        "latest": {
          "run_id": "a0000000000000000000000000000001",
          "started_at": "2026-09-26T06:55:50.000000+00:00",
          "since": "2026-09-26T06:55:50.000000+00:00",
          "trigger": "cli",
          "outcome": "pass",
          "value": 0.0,
          "display_value": "0",
          "message": null,
          "last_evaluated": null
        }
      },
      {
        "id": "ace45b91cd324084",
        "name": "min(price) > 0",
        "expression": "min(price) > 0",
        "metric": "min",
        "unit": "number",
        "dataset": "inventory.products",
        "datasource": "lake",
        "owner": "data-platform@example.com",
        "tags": [
          "example",
          "catalogue"
        ],
        "source": "checks/inventory/products.yml:7:5",
        "location": {
          "file": "checks/inventory/products.yml",
          "line": 7,
          "column": 5
        },
        "latest": {
          "run_id": "a0000000000000000000000000000001",
          "started_at": "2026-09-26T06:55:50.000000+00:00",
          "since": "2026-09-26T06:55:50.000000+00:00",
          "trigger": "cli",
          "outcome": "pass",
          "value": 39.9,
          "display_value": "39.9",
          "message": null,
          "last_evaluated": null
        }
      },
      {
        "id": "41e58afff9c48a46",
        "name": "Price feed freshness",
        "expression": "freshness(updated_at) | warn when > 1d | fail when > 7d",
        "metric": "freshness",
        "unit": "duration",
        "dataset": "inventory.products",
        "datasource": "lake",
        "owner": "data-platform@example.com",
        "tags": [
          "example",
          "catalogue"
        ],
        "source": "checks/inventory/products.yml:8:5",
        "location": {
          "file": "checks/inventory/products.yml",
          "line": 8,
          "column": 5
        },
        "latest": {
          "run_id": "a0000000000000000000000000000001",
          "started_at": "2026-09-26T06:55:50.000000+00:00",
          "since": "2026-09-26T06:55:50.000000+00:00",
          "trigger": "cli",
          "outcome": "warn",
          "value": 259200.817941,
          "display_value": "3d 1s",
          "message": "warn when > 1d; newest 2026-09-23T06:55:49.000000+00:00",
          "last_evaluated": null
        }
      },
      {
        "id": "32c8f939b90f6367",
        "name": "row_count > 0",
        "expression": "row_count > 0",
        "metric": "row_count",
        "unit": "count",
        "dataset": "sales.customers",
        "datasource": "lake",
        "owner": "sales-data@example.com",
        "tags": [
          "example",
          "sales",
          "tier-1"
        ],
        "source": "checks/sales/customers.yml:4:5",
        "location": {
          "file": "checks/sales/customers.yml",
          "line": 4,
          "column": 5
        },
        "latest": {
          "run_id": "e0000000000000000000000000000003",
          "started_at": "2026-09-26T06:56:30.000000+00:00",
          "since": "2026-09-26T06:56:30.000000+00:00",
          "trigger": "cli",
          "outcome": "error",
          "value": null,
          "display_value": "—",
          "message": "IO Error: Cannot open database \"/opt/dq/retail/retail.duckdb\" in read-only mode: database does not exist",
          "last_evaluated": {
            "outcome": "pass",
            "started_at": "2026-09-26T06:56:12.000000+00:00",
            "since": "2026-09-26T06:55:50.000000+00:00"
          }
        }
      },
      {
        "id": "af0289a72fedd946",
        "name": "duplicate_count(customer_id) = 0",
        "expression": "duplicate_count(customer_id) = 0",
        "metric": "duplicate_count",
        "unit": "count",
        "dataset": "sales.customers",
        "datasource": "lake",
        "owner": "sales-data@example.com",
        "tags": [
          "example",
          "sales",
          "tier-1"
        ],
        "source": "checks/sales/customers.yml:5:5",
        "location": {
          "file": "checks/sales/customers.yml",
          "line": 5,
          "column": 5
        },
        "latest": {
          "run_id": "e0000000000000000000000000000003",
          "started_at": "2026-09-26T06:56:30.000000+00:00",
          "since": "2026-09-26T06:56:30.000000+00:00",
          "trigger": "cli",
          "outcome": "error",
          "value": null,
          "display_value": "—",
          "message": "IO Error: Cannot open database \"/opt/dq/retail/retail.duckdb\" in read-only mode: database does not exist",
          "last_evaluated": {
            "outcome": "pass",
            "started_at": "2026-09-26T06:56:12.000000+00:00",
            "since": "2026-09-26T06:55:50.000000+00:00"
          }
        }
      },
      {
        "id": "b1ceb8262d8b5441",
        "name": "missing_percent(email) < 5%",
        "expression": "missing_percent(email) < 5%",
        "metric": "missing_percent",
        "unit": "percent",
        "dataset": "sales.customers",
        "datasource": "lake",
        "owner": "sales-data@example.com",
        "tags": [
          "example",
          "sales",
          "tier-1"
        ],
        "source": "checks/sales/customers.yml:6:5",
        "location": {
          "file": "checks/sales/customers.yml",
          "line": 6,
          "column": 5
        },
        "latest": {
          "run_id": "e0000000000000000000000000000003",
          "started_at": "2026-09-26T06:56:30.000000+00:00",
          "since": "2026-09-26T06:56:30.000000+00:00",
          "trigger": "cli",
          "outcome": "error",
          "value": null,
          "display_value": "—",
          "message": "IO Error: Cannot open database \"/opt/dq/retail/retail.duckdb\" in read-only mode: database does not exist",
          "last_evaluated": {
            "outcome": "fail",
            "started_at": "2026-09-26T06:56:12.000000+00:00",
            "since": "2026-09-26T06:55:50.000000+00:00"
          }
        }
      },
      {
        "id": "000f8d0048744bfb",
        "name": "invalid_count(country) = 0",
        "expression": "invalid_count(country) = 0",
        "metric": "invalid_count",
        "unit": "count",
        "dataset": "sales.customers",
        "datasource": "lake",
        "owner": "sales-data@example.com",
        "tags": [
          "example",
          "sales",
          "tier-1"
        ],
        "source": "checks/sales/customers.yml:8:5",
        "location": {
          "file": "checks/sales/customers.yml",
          "line": 8,
          "column": 5
        },
        "latest": {
          "run_id": "e0000000000000000000000000000003",
          "started_at": "2026-09-26T06:56:30.000000+00:00",
          "since": "2026-09-26T06:56:30.000000+00:00",
          "trigger": "cli",
          "outcome": "error",
          "value": null,
          "display_value": "—",
          "message": "IO Error: Cannot open database \"/opt/dq/retail/retail.duckdb\" in read-only mode: database does not exist",
          "last_evaluated": {
            "outcome": "fail",
            "started_at": "2026-09-26T06:56:12.000000+00:00",
            "since": "2026-09-26T06:55:50.000000+00:00"
          }
        }
      },
      {
        "id": "b6ecae522c1d4aaf",
        "name": "invalid_count(email) = 0",
        "expression": "invalid_count(email) = 0",
        "metric": "invalid_count",
        "unit": "count",
        "dataset": "sales.customers",
        "datasource": "lake",
        "owner": "sales-data@example.com",
        "tags": [
          "example",
          "sales",
          "tier-1"
        ],
        "source": "checks/sales/customers.yml:10:5",
        "location": {
          "file": "checks/sales/customers.yml",
          "line": 10,
          "column": 5
        },
        "latest": {
          "run_id": "e0000000000000000000000000000003",
          "started_at": "2026-09-26T06:56:30.000000+00:00",
          "since": "2026-09-26T06:56:30.000000+00:00",
          "trigger": "cli",
          "outcome": "error",
          "value": null,
          "display_value": "—",
          "message": "IO Error: Cannot open database \"/opt/dq/retail/retail.duckdb\" in read-only mode: database does not exist",
          "last_evaluated": {
            "outcome": "pass",
            "started_at": "2026-09-26T06:56:12.000000+00:00",
            "since": "2026-09-26T06:55:50.000000+00:00"
          }
        }
      },
      {
        "id": "f81f9ff5edea8887",
        "name": "row_count > 0",
        "expression": "row_count > 0",
        "metric": "row_count",
        "unit": "count",
        "dataset": "sales.orders",
        "datasource": "lake",
        "owner": "sales-data@example.com",
        "tags": [
          "example",
          "sales",
          "tier-1"
        ],
        "source": "checks/sales/orders.yml:4:5",
        "location": {
          "file": "checks/sales/orders.yml",
          "line": 4,
          "column": 5
        },
        "latest": {
          "run_id": "b0000000000000000000000000000002",
          "started_at": "2026-09-26T06:56:12.000000+00:00",
          "since": "2026-09-26T06:55:50.000000+00:00",
          "trigger": "cli",
          "outcome": "pass",
          "value": 7.0,
          "display_value": "7",
          "message": null,
          "last_evaluated": null
        }
      },
      {
        "id": "32867fbe86f483f3",
        "name": "Order volume",
        "expression": "row_count | warn when < 100 | fail when = 0",
        "metric": "row_count",
        "unit": "count",
        "dataset": "sales.orders",
        "datasource": "lake",
        "owner": "sales-data@example.com",
        "tags": [
          "example",
          "sales",
          "tier-1"
        ],
        "source": "checks/sales/orders.yml:5:5",
        "location": {
          "file": "checks/sales/orders.yml",
          "line": 5,
          "column": 5
        },
        "latest": {
          "run_id": "b0000000000000000000000000000002",
          "started_at": "2026-09-26T06:56:12.000000+00:00",
          "since": "2026-09-26T06:55:50.000000+00:00",
          "trigger": "cli",
          "outcome": "warn",
          "value": 7.0,
          "display_value": "7",
          "message": "warn when < 100",
          "last_evaluated": null
        }
      },
      {
        "id": "fc9cc3088acaf77a",
        "name": "missing_count(customer_id) = 0",
        "expression": "missing_count(customer_id) = 0",
        "metric": "missing_count",
        "unit": "count",
        "dataset": "sales.orders",
        "datasource": "lake",
        "owner": "sales-data@example.com",
        "tags": [
          "example",
          "sales",
          "tier-1"
        ],
        "source": "checks/sales/orders.yml:9:5",
        "location": {
          "file": "checks/sales/orders.yml",
          "line": 9,
          "column": 5
        },
        "latest": {
          "run_id": "b0000000000000000000000000000002",
          "started_at": "2026-09-26T06:56:12.000000+00:00",
          "since": "2026-09-26T06:55:50.000000+00:00",
          "trigger": "cli",
          "outcome": "fail",
          "value": 1.0,
          "display_value": "1",
          "message": "expected = 0",
          "last_evaluated": null
        }
      },
      {
        "id": "11c20dd55fb97fa9",
        "name": "duplicate_count(order_id) = 0",
        "expression": "duplicate_count(order_id) = 0",
        "metric": "duplicate_count",
        "unit": "count",
        "dataset": "sales.orders",
        "datasource": "lake",
        "owner": "sales-data@example.com",
        "tags": [
          "example",
          "sales",
          "tier-1"
        ],
        "source": "checks/sales/orders.yml:10:5",
        "location": {
          "file": "checks/sales/orders.yml",
          "line": 10,
          "column": 5
        },
        "latest": {
          "run_id": "b0000000000000000000000000000002",
          "started_at": "2026-09-26T06:56:12.000000+00:00",
          "since": "2026-09-26T06:55:50.000000+00:00",
          "trigger": "cli",
          "outcome": "fail",
          "value": 1.0,
          "display_value": "1",
          "message": "expected = 0",
          "last_evaluated": null
        }
      },
      {
        "id": "a30dacf7316eef07",
        "name": "invalid_percent(status) < 1%",
        "expression": "invalid_percent(status) < 1%",
        "metric": "invalid_percent",
        "unit": "percent",
        "dataset": "sales.orders",
        "datasource": "lake",
        "owner": "sales-data@example.com",
        "tags": [
          "example",
          "sales",
          "tier-1"
        ],
        "source": "checks/sales/orders.yml:11:5",
        "location": {
          "file": "checks/sales/orders.yml",
          "line": 11,
          "column": 5
        },
        "latest": {
          "run_id": "b0000000000000000000000000000002",
          "started_at": "2026-09-26T06:56:12.000000+00:00",
          "since": "2026-09-26T06:55:50.000000+00:00",
          "trigger": "cli",
          "outcome": "fail",
          "value": 14.285714285714286,
          "display_value": "14.29%",
          "message": "expected < 1%",
          "last_evaluated": null
        }
      },
      {
        "id": "366d9254d889c910",
        "name": "avg(amount) between 10 and 500",
        "expression": "avg(amount) between 10 and 500",
        "metric": "avg",
        "unit": "number",
        "dataset": "sales.orders",
        "datasource": "lake",
        "owner": "sales-data@example.com",
        "tags": [
          "example",
          "sales",
          "tier-1"
        ],
        "source": "checks/sales/orders.yml:13:5",
        "location": {
          "file": "checks/sales/orders.yml",
          "line": 13,
          "column": 5
        },
        "latest": {
          "run_id": "b0000000000000000000000000000002",
          "started_at": "2026-09-26T06:56:12.000000+00:00",
          "since": "2026-09-26T06:55:50.000000+00:00",
          "trigger": "cli",
          "outcome": "pass",
          "value": 54.357142857142854,
          "display_value": "54.3571",
          "message": null,
          "last_evaluated": null
        }
      },
      {
        "id": "a81b0374b0b04f06",
        "name": "freshness(created_at) < 6h",
        "expression": "freshness(created_at) < 6h",
        "metric": "freshness",
        "unit": "duration",
        "dataset": "sales.orders",
        "datasource": "lake",
        "owner": "sales-data@example.com",
        "tags": [
          "example",
          "sales",
          "tier-1"
        ],
        "source": "checks/sales/orders.yml:14:5",
        "location": {
          "file": "checks/sales/orders.yml",
          "line": 14,
          "column": 5
        },
        "latest": {
          "run_id": "b0000000000000000000000000000002",
          "started_at": "2026-09-26T06:56:12.000000+00:00",
          "since": "2026-09-26T06:55:50.000000+00:00",
          "trigger": "cli",
          "outcome": "pass",
          "value": 3601.231287,
          "display_value": "1h 1s",
          "message": "newest 2026-09-26T05:55:49.000000+00:00",
          "last_evaluated": null
        }
      },
      {
        "id": "ed669ca6e5532a59",
        "name": "No negative amounts",
        "expression": "failed_rows",
        "metric": "failed_rows",
        "unit": "count",
        "dataset": "sales.orders",
        "datasource": "lake",
        "owner": "sales-data@example.com",
        "tags": [
          "example",
          "sales",
          "tier-1"
        ],
        "source": "checks/sales/orders.yml:15:5",
        "location": {
          "file": "checks/sales/orders.yml",
          "line": 15,
          "column": 5
        },
        "latest": {
          "run_id": "b0000000000000000000000000000002",
          "started_at": "2026-09-26T06:56:12.000000+00:00",
          "since": "2026-09-26T06:55:50.000000+00:00",
          "trigger": "cli",
          "outcome": "fail",
          "value": 1.0,
          "display_value": "1",
          "message": "expected = 0",
          "last_evaluated": null
        }
      },
      {
        "id": "fbc3aa0b93b66eee",
        "name": "schema",
        "expression": "schema",
        "metric": "schema",
        "unit": "count",
        "dataset": "sales.orders",
        "datasource": "lake",
        "owner": "sales-data@example.com",
        "tags": [
          "example",
          "sales",
          "tier-1"
        ],
        "source": "checks/sales/orders.yml:18:5",
        "location": {
          "file": "checks/sales/orders.yml",
          "line": 18,
          "column": 5
        },
        "latest": {
          "run_id": "b0000000000000000000000000000002",
          "started_at": "2026-09-26T06:56:12.000000+00:00",
          "since": "2026-09-26T06:55:50.000000+00:00",
          "trigger": "cli",
          "outcome": "pass",
          "value": 0.0,
          "display_value": "0",
          "message": null,
          "last_evaluated": null
        }
      }
    ],
    "total": 18
  },
  "runs": {
    "items": [
      {
        "id": "e0000000000000000000000000000003",
        "project": "retail-example",
        "started_at": "2026-09-26T06:56:30.000000+00:00",
        "finished_at": "2026-09-26T06:56:30.900000+00:00",
        "outcome": "error",
        "exit_code": 2,
        "trigger": "cli",
        "version": "0.1.0",
        "selection": {
          "paths": [
            "checks/sales/customers.yml"
          ]
        },
        "counts": {
          "total": 5,
          "pass": 0,
          "warn": 0,
          "fail": 0,
          "error": 5,
          "skipped": 0
        }
      }
    ],
    "next_cursor": "bmV4dC1wYWdl"
  }
};

/** `interrupted`. */
export const interrupted: OverviewResponses = {
  "project": {
    "name": "retail-example",
    "version": "0.1.0",
    "loaded_at": "2026-09-26T06:56:50.000000+00:00",
    "ok": true,
    "datasources": [
      {
        "name": "lake",
        "type": "duckdb"
      }
    ],
    "counts": {
      "datasets": 3,
      "checks": 18
    },
    "diagnostics": []
  },
  "checks": {
    "items": [
      {
        "id": "cd3e8103b4318809",
        "name": "row_count between 1 and 10000",
        "expression": "row_count between 1 and 10000",
        "metric": "row_count",
        "unit": "count",
        "dataset": "inventory.products",
        "datasource": "lake",
        "owner": "data-platform@example.com",
        "tags": [
          "example",
          "catalogue"
        ],
        "source": "checks/inventory/products.yml:5:5",
        "location": {
          "file": "checks/inventory/products.yml",
          "line": 5,
          "column": 5
        },
        "latest": {
          "run_id": "f0000000000000000000000000000004",
          "started_at": "2026-09-26T06:56:45.000000+00:00",
          "since": "2026-09-26T06:55:50.000000+00:00",
          "trigger": "cli",
          "outcome": "pass",
          "value": 3.0,
          "display_value": "3",
          "message": null,
          "last_evaluated": null
        }
      },
      {
        "id": "8b9c5af854ba2a5f",
        "name": "duplicate_count(sku) = 0",
        "expression": "duplicate_count(sku) = 0",
        "metric": "duplicate_count",
        "unit": "count",
        "dataset": "inventory.products",
        "datasource": "lake",
        "owner": "data-platform@example.com",
        "tags": [
          "example",
          "catalogue"
        ],
        "source": "checks/inventory/products.yml:6:5",
        "location": {
          "file": "checks/inventory/products.yml",
          "line": 6,
          "column": 5
        },
        "latest": {
          "run_id": "f0000000000000000000000000000004",
          "started_at": "2026-09-26T06:56:45.000000+00:00",
          "since": "2026-09-26T06:55:50.000000+00:00",
          "trigger": "cli",
          "outcome": "pass",
          "value": 0.0,
          "display_value": "0",
          "message": null,
          "last_evaluated": null
        }
      },
      {
        "id": "ace45b91cd324084",
        "name": "min(price) > 0",
        "expression": "min(price) > 0",
        "metric": "min",
        "unit": "number",
        "dataset": "inventory.products",
        "datasource": "lake",
        "owner": "data-platform@example.com",
        "tags": [
          "example",
          "catalogue"
        ],
        "source": "checks/inventory/products.yml:7:5",
        "location": {
          "file": "checks/inventory/products.yml",
          "line": 7,
          "column": 5
        },
        "latest": {
          "run_id": "f0000000000000000000000000000004",
          "started_at": "2026-09-26T06:56:45.000000+00:00",
          "since": "2026-09-26T06:55:50.000000+00:00",
          "trigger": "cli",
          "outcome": "pass",
          "value": 39.9,
          "display_value": "39.9",
          "message": null,
          "last_evaluated": null
        }
      },
      {
        "id": "41e58afff9c48a46",
        "name": "Price feed freshness",
        "expression": "freshness(updated_at) | warn when > 1d | fail when > 7d",
        "metric": "freshness",
        "unit": "duration",
        "dataset": "inventory.products",
        "datasource": "lake",
        "owner": "data-platform@example.com",
        "tags": [
          "example",
          "catalogue"
        ],
        "source": "checks/inventory/products.yml:8:5",
        "location": {
          "file": "checks/inventory/products.yml",
          "line": 8,
          "column": 5
        },
        "latest": {
          "run_id": "f0000000000000000000000000000004",
          "started_at": "2026-09-26T06:56:45.000000+00:00",
          "since": "2026-09-26T06:55:50.000000+00:00",
          "trigger": "cli",
          "outcome": "warn",
          "value": 259202.133546,
          "display_value": "3d 2s",
          "message": "warn when > 1d; newest 2026-09-23T06:55:49.000000+00:00",
          "last_evaluated": null
        }
      },
      {
        "id": "32c8f939b90f6367",
        "name": "row_count > 0",
        "expression": "row_count > 0",
        "metric": "row_count",
        "unit": "count",
        "dataset": "sales.customers",
        "datasource": "lake",
        "owner": "sales-data@example.com",
        "tags": [
          "example",
          "sales",
          "tier-1"
        ],
        "source": "checks/sales/customers.yml:4:5",
        "location": {
          "file": "checks/sales/customers.yml",
          "line": 4,
          "column": 5
        },
        "latest": {
          "run_id": "f0000000000000000000000000000004",
          "started_at": "2026-09-26T06:56:45.000000+00:00",
          "since": "2026-09-26T06:55:50.000000+00:00",
          "trigger": "cli",
          "outcome": "pass",
          "value": 5.0,
          "display_value": "5",
          "message": null,
          "last_evaluated": null
        }
      },
      {
        "id": "af0289a72fedd946",
        "name": "duplicate_count(customer_id) = 0",
        "expression": "duplicate_count(customer_id) = 0",
        "metric": "duplicate_count",
        "unit": "count",
        "dataset": "sales.customers",
        "datasource": "lake",
        "owner": "sales-data@example.com",
        "tags": [
          "example",
          "sales",
          "tier-1"
        ],
        "source": "checks/sales/customers.yml:5:5",
        "location": {
          "file": "checks/sales/customers.yml",
          "line": 5,
          "column": 5
        },
        "latest": {
          "run_id": "f0000000000000000000000000000004",
          "started_at": "2026-09-26T06:56:45.000000+00:00",
          "since": "2026-09-26T06:55:50.000000+00:00",
          "trigger": "cli",
          "outcome": "pass",
          "value": 0.0,
          "display_value": "0",
          "message": null,
          "last_evaluated": null
        }
      },
      {
        "id": "b1ceb8262d8b5441",
        "name": "missing_percent(email) < 5%",
        "expression": "missing_percent(email) < 5%",
        "metric": "missing_percent",
        "unit": "percent",
        "dataset": "sales.customers",
        "datasource": "lake",
        "owner": "sales-data@example.com",
        "tags": [
          "example",
          "sales",
          "tier-1"
        ],
        "source": "checks/sales/customers.yml:6:5",
        "location": {
          "file": "checks/sales/customers.yml",
          "line": 6,
          "column": 5
        },
        "latest": {
          "run_id": "f0000000000000000000000000000004",
          "started_at": "2026-09-26T06:56:45.000000+00:00",
          "since": "2026-09-26T06:55:50.000000+00:00",
          "trigger": "cli",
          "outcome": "fail",
          "value": 20.0,
          "display_value": "20.00%",
          "message": "expected < 5%",
          "last_evaluated": null
        }
      },
      {
        "id": "000f8d0048744bfb",
        "name": "invalid_count(country) = 0",
        "expression": "invalid_count(country) = 0",
        "metric": "invalid_count",
        "unit": "count",
        "dataset": "sales.customers",
        "datasource": "lake",
        "owner": "sales-data@example.com",
        "tags": [
          "example",
          "sales",
          "tier-1"
        ],
        "source": "checks/sales/customers.yml:8:5",
        "location": {
          "file": "checks/sales/customers.yml",
          "line": 8,
          "column": 5
        },
        "latest": {
          "run_id": "f0000000000000000000000000000004",
          "started_at": "2026-09-26T06:56:45.000000+00:00",
          "since": "2026-09-26T06:55:50.000000+00:00",
          "trigger": "cli",
          "outcome": "fail",
          "value": 1.0,
          "display_value": "1",
          "message": "expected = 0",
          "last_evaluated": null
        }
      },
      {
        "id": "b6ecae522c1d4aaf",
        "name": "invalid_count(email) = 0",
        "expression": "invalid_count(email) = 0",
        "metric": "invalid_count",
        "unit": "count",
        "dataset": "sales.customers",
        "datasource": "lake",
        "owner": "sales-data@example.com",
        "tags": [
          "example",
          "sales",
          "tier-1"
        ],
        "source": "checks/sales/customers.yml:10:5",
        "location": {
          "file": "checks/sales/customers.yml",
          "line": 10,
          "column": 5
        },
        "latest": {
          "run_id": "f0000000000000000000000000000004",
          "started_at": "2026-09-26T06:56:45.000000+00:00",
          "since": "2026-09-26T06:55:50.000000+00:00",
          "trigger": "cli",
          "outcome": "pass",
          "value": 0.0,
          "display_value": "0",
          "message": null,
          "last_evaluated": null
        }
      },
      {
        "id": "f81f9ff5edea8887",
        "name": "row_count > 0",
        "expression": "row_count > 0",
        "metric": "row_count",
        "unit": "count",
        "dataset": "sales.orders",
        "datasource": "lake",
        "owner": "sales-data@example.com",
        "tags": [
          "example",
          "sales",
          "tier-1"
        ],
        "source": "checks/sales/orders.yml:4:5",
        "location": {
          "file": "checks/sales/orders.yml",
          "line": 4,
          "column": 5
        },
        "latest": {
          "run_id": "f0000000000000000000000000000004",
          "started_at": "2026-09-26T06:56:45.000000+00:00",
          "since": "2026-09-26T06:55:50.000000+00:00",
          "trigger": "cli",
          "outcome": "pass",
          "value": 7.0,
          "display_value": "7",
          "message": null,
          "last_evaluated": null
        }
      },
      {
        "id": "32867fbe86f483f3",
        "name": "Order volume",
        "expression": "row_count | warn when < 100 | fail when = 0",
        "metric": "row_count",
        "unit": "count",
        "dataset": "sales.orders",
        "datasource": "lake",
        "owner": "sales-data@example.com",
        "tags": [
          "example",
          "sales",
          "tier-1"
        ],
        "source": "checks/sales/orders.yml:5:5",
        "location": {
          "file": "checks/sales/orders.yml",
          "line": 5,
          "column": 5
        },
        "latest": {
          "run_id": "f0000000000000000000000000000004",
          "started_at": "2026-09-26T06:56:45.000000+00:00",
          "since": "2026-09-26T06:55:50.000000+00:00",
          "trigger": "cli",
          "outcome": "warn",
          "value": 7.0,
          "display_value": "7",
          "message": "warn when < 100",
          "last_evaluated": null
        }
      },
      {
        "id": "fc9cc3088acaf77a",
        "name": "missing_count(customer_id) = 0",
        "expression": "missing_count(customer_id) = 0",
        "metric": "missing_count",
        "unit": "count",
        "dataset": "sales.orders",
        "datasource": "lake",
        "owner": "sales-data@example.com",
        "tags": [
          "example",
          "sales",
          "tier-1"
        ],
        "source": "checks/sales/orders.yml:9:5",
        "location": {
          "file": "checks/sales/orders.yml",
          "line": 9,
          "column": 5
        },
        "latest": {
          "run_id": "f0000000000000000000000000000004",
          "started_at": "2026-09-26T06:56:45.000000+00:00",
          "since": "2026-09-26T06:55:50.000000+00:00",
          "trigger": "cli",
          "outcome": "fail",
          "value": 1.0,
          "display_value": "1",
          "message": "expected = 0",
          "last_evaluated": null
        }
      },
      {
        "id": "11c20dd55fb97fa9",
        "name": "duplicate_count(order_id) = 0",
        "expression": "duplicate_count(order_id) = 0",
        "metric": "duplicate_count",
        "unit": "count",
        "dataset": "sales.orders",
        "datasource": "lake",
        "owner": "sales-data@example.com",
        "tags": [
          "example",
          "sales",
          "tier-1"
        ],
        "source": "checks/sales/orders.yml:10:5",
        "location": {
          "file": "checks/sales/orders.yml",
          "line": 10,
          "column": 5
        },
        "latest": {
          "run_id": "f0000000000000000000000000000004",
          "started_at": "2026-09-26T06:56:45.000000+00:00",
          "since": "2026-09-26T06:55:50.000000+00:00",
          "trigger": "cli",
          "outcome": "fail",
          "value": 1.0,
          "display_value": "1",
          "message": "expected = 0",
          "last_evaluated": null
        }
      },
      {
        "id": "a30dacf7316eef07",
        "name": "invalid_percent(status) < 1%",
        "expression": "invalid_percent(status) < 1%",
        "metric": "invalid_percent",
        "unit": "percent",
        "dataset": "sales.orders",
        "datasource": "lake",
        "owner": "sales-data@example.com",
        "tags": [
          "example",
          "sales",
          "tier-1"
        ],
        "source": "checks/sales/orders.yml:11:5",
        "location": {
          "file": "checks/sales/orders.yml",
          "line": 11,
          "column": 5
        },
        "latest": {
          "run_id": "f0000000000000000000000000000004",
          "started_at": "2026-09-26T06:56:45.000000+00:00",
          "since": "2026-09-26T06:55:50.000000+00:00",
          "trigger": "cli",
          "outcome": "fail",
          "value": 14.285714285714286,
          "display_value": "14.29%",
          "message": "expected < 1%",
          "last_evaluated": null
        }
      },
      {
        "id": "366d9254d889c910",
        "name": "avg(amount) between 10 and 500",
        "expression": "avg(amount) between 10 and 500",
        "metric": "avg",
        "unit": "number",
        "dataset": "sales.orders",
        "datasource": "lake",
        "owner": "sales-data@example.com",
        "tags": [
          "example",
          "sales",
          "tier-1"
        ],
        "source": "checks/sales/orders.yml:13:5",
        "location": {
          "file": "checks/sales/orders.yml",
          "line": 13,
          "column": 5
        },
        "latest": {
          "run_id": "f0000000000000000000000000000004",
          "started_at": "2026-09-26T06:56:45.000000+00:00",
          "since": "2026-09-26T06:55:50.000000+00:00",
          "trigger": "cli",
          "outcome": "pass",
          "value": 54.357142857142854,
          "display_value": "54.3571",
          "message": null,
          "last_evaluated": null
        }
      },
      {
        "id": "a81b0374b0b04f06",
        "name": "freshness(created_at) < 6h",
        "expression": "freshness(created_at) < 6h",
        "metric": "freshness",
        "unit": "duration",
        "dataset": "sales.orders",
        "datasource": "lake",
        "owner": "sales-data@example.com",
        "tags": [
          "example",
          "sales",
          "tier-1"
        ],
        "source": "checks/sales/orders.yml:14:5",
        "location": {
          "file": "checks/sales/orders.yml",
          "line": 14,
          "column": 5
        },
        "latest": {
          "run_id": "f0000000000000000000000000000004",
          "started_at": "2026-09-26T06:56:45.000000+00:00",
          "since": "2026-09-26T06:55:50.000000+00:00",
          "trigger": "cli",
          "outcome": "pass",
          "value": 3602.133546,
          "display_value": "1h 2s",
          "message": "newest 2026-09-26T05:55:49.000000+00:00",
          "last_evaluated": null
        }
      },
      {
        "id": "ed669ca6e5532a59",
        "name": "No negative amounts",
        "expression": "failed_rows",
        "metric": "failed_rows",
        "unit": "count",
        "dataset": "sales.orders",
        "datasource": "lake",
        "owner": "sales-data@example.com",
        "tags": [
          "example",
          "sales",
          "tier-1"
        ],
        "source": "checks/sales/orders.yml:15:5",
        "location": {
          "file": "checks/sales/orders.yml",
          "line": 15,
          "column": 5
        },
        "latest": {
          "run_id": "f0000000000000000000000000000004",
          "started_at": "2026-09-26T06:56:45.000000+00:00",
          "since": "2026-09-26T06:55:50.000000+00:00",
          "trigger": "cli",
          "outcome": "fail",
          "value": 1.0,
          "display_value": "1",
          "message": "expected = 0",
          "last_evaluated": null
        }
      },
      {
        "id": "fbc3aa0b93b66eee",
        "name": "schema",
        "expression": "schema",
        "metric": "schema",
        "unit": "count",
        "dataset": "sales.orders",
        "datasource": "lake",
        "owner": "sales-data@example.com",
        "tags": [
          "example",
          "sales",
          "tier-1"
        ],
        "source": "checks/sales/orders.yml:18:5",
        "location": {
          "file": "checks/sales/orders.yml",
          "line": 18,
          "column": 5
        },
        "latest": {
          "run_id": "f0000000000000000000000000000004",
          "started_at": "2026-09-26T06:56:45.000000+00:00",
          "since": "2026-09-26T06:55:50.000000+00:00",
          "trigger": "cli",
          "outcome": "pass",
          "value": 0.0,
          "display_value": "0",
          "message": null,
          "last_evaluated": null
        }
      }
    ],
    "total": 18
  },
  "runs": {
    "items": [
      {
        "id": "f0000000000000000000000000000004",
        "project": "retail-example",
        "started_at": "2026-09-26T06:56:45.000000+00:00",
        "finished_at": "2026-09-26T06:56:45.900000+00:00",
        "outcome": "fail",
        "exit_code": 1,
        "trigger": "cli",
        "version": "0.1.0",
        "selection": {},
        "counts": {
          "total": 18,
          "pass": 10,
          "warn": 2,
          "fail": 6,
          "error": 0,
          "skipped": 0
        }
      }
    ],
    "next_cursor": "bmV4dC1wYWdl"
  }
};
