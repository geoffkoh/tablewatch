/**
 * `GET /checks/{id}/sql` responses (spec 005). The retail bodies are what
 * `/sql` answered for a scratch copy of examples/retail on 2026-09-27; the
 * rest are derived from them for the scenarios that need them.
 *
 * Typed against the generated contract: a contract change breaks `tsc` here.
 */
import type { CheckSql, Statement } from "../../api/types";

/** `b1ceb8262d8b5441`. */
export const EMAIL_SQL: CheckSql = {
  "check_id": "b1ceb8262d8b5441",
  "dataset": "sales.customers",
  "datasource": "lake",
  "dialect": "duckdb",
  "statements": [
    {
      "kind": "scan",
      "sql": "SELECT count(*) AS m0, sum(CASE WHEN (email IS NULL OR email IN ('', 'N/A')) THEN 1 ELSE 0 END) AS m1, sum(CASE WHEN (country IS NOT NULL AND (country NOT IN ('SG', 'MY', 'ID', 'TH', 'VN', 'PH'))) THEN 1 ELSE 0 END) AS m2, sum(CASE WHEN (NOT (email IS NULL OR email IN ('', 'N/A')) AND NOT regexp_matches(email, '^[^@]+@[^@]+\\.[a-z]+$')) THEN 1 ELSE 0 END) AS m3 \nFROM sales.customers",
      "measures": 4,
      "uses": [
        {
          "label": "m0",
          "sql": "count(*)",
          "shared_by": 1
        },
        {
          "label": "m1",
          "sql": "sum(CASE WHEN (email IS NULL OR email IN ('', 'N/A')) THEN 1 ELSE 0 END)",
          "shared_by": 0
        }
      ],
      "shared_by": 3
    }
  ],
  "schema_lookup": false,
  "error": null
};

/** `af0289a72fedd946`. */
export const DUPLICATES_SQL: CheckSql = {
  "check_id": "af0289a72fedd946",
  "dataset": "sales.customers",
  "datasource": "lake",
  "dialect": "duckdb",
  "statements": [
    {
      "kind": "query",
      "sql": "SELECT coalesce(sum(duplicate_groups.n - 1), 0) AS coalesce_1 \nFROM (SELECT count(*) AS n \nFROM sales.customers \nWHERE customer_id IS NOT NULL GROUP BY customer_id \nHAVING count(*) > 1) AS duplicate_groups",
      "shared_by": 0
    }
  ],
  "schema_lookup": false,
  "error": null
};

/** `fbc3aa0b93b66eee`. */
export const SCHEMA_SQL: CheckSql = {
  "check_id": "fbc3aa0b93b66eee",
  "dataset": "sales.orders",
  "datasource": "lake",
  "dialect": "duckdb",
  "statements": [],
  "schema_lookup": true,
  "error": null
};

/** `32867fbe86f483f3`. */
export const VOLUME_SQL: CheckSql = {
  "check_id": "32867fbe86f483f3",
  "dataset": "sales.orders",
  "datasource": "lake",
  "dialect": "duckdb",
  "statements": [
    {
      "kind": "scan",
      "sql": "SELECT count(*) AS m0, sum(CASE WHEN (customer_id IS NULL) THEN 1 ELSE 0 END) AS m1, sum(CASE WHEN (status IS NOT NULL AND (status NOT IN ('pending', 'shipped', 'delivered', 'cancelled'))) THEN 1 ELSE 0 END) AS m2, avg(amount) AS m3, max(created_at) AS m4, sum(CASE WHEN (amount < 0) THEN 1 ELSE 0 END) AS m5 \nFROM sales.orders",
      "measures": 6,
      "uses": [
        {
          "label": "m0",
          "sql": "count(*)",
          "shared_by": 2
        }
      ],
      "shared_by": 6
    }
  ],
  "schema_lookup": false,
  "error": null
};

/** `a81b0374b0b04f06`. */
export const FRESHNESS_SQL: CheckSql = {
  "check_id": "a81b0374b0b04f06",
  "dataset": "sales.orders",
  "datasource": "lake",
  "dialect": "duckdb",
  "statements": [
    {
      "kind": "scan",
      "sql": "SELECT count(*) AS m0, sum(CASE WHEN (customer_id IS NULL) THEN 1 ELSE 0 END) AS m1, sum(CASE WHEN (status IS NOT NULL AND (status NOT IN ('pending', 'shipped', 'delivered', 'cancelled'))) THEN 1 ELSE 0 END) AS m2, avg(amount) AS m3, max(created_at) AS m4, sum(CASE WHEN (amount < 0) THEN 1 ELSE 0 END) AS m5 \nFROM sales.orders",
      "measures": 6,
      "uses": [
        {
          "label": "m4",
          "sql": "max(created_at)",
          "shared_by": 0
        }
      ],
      "shared_by": 6
    }
  ],
  "schema_lookup": false,
  "error": null
};

/** Every captured body, by check id. */
export const SQL_BY_ID: Readonly<Record<string, CheckSql>> = {
  b1ceb8262d8b5441: EMAIL_SQL,
  af0289a72fedd946: DUPLICATES_SQL,
  fbc3aa0b93b66eee: SCHEMA_SQL,
  "32867fbe86f483f3": VOLUME_SQL,
  a81b0374b0b04f06: FRESHNESS_SQL,
};

/** A `/sql` body for a check with no captured one: one scan, one column. */
export function genericSql(id: string, dataset = "sales.customers", datasource = "lake"): CheckSql {
  return {
    check_id: id,
    dataset,
    datasource,
    dialect: "duckdb",
    statements: [
      {
        kind: "scan",
        sql: `SELECT count(*) AS m0 \nFROM ${dataset}`,
        measures: 1,
        uses: [{ label: "m0", sql: "count(*)", shared_by: 0 }],
        shared_by: 0,
      },
    ],
    schema_lookup: false,
    error: null,
  };
}

/** `remote`, the `events` check: the snowflake dialect is not installed (S6). */
export const REMOTE_EVENTS_SQL: CheckSql = {
  check_id: "0e7e5c0de0e7e5c0",
  dataset: "events",
  datasource: "wh",
  dialect: null,
  statements: [],
  schema_lookup: false,
  error: "unsupported SQLAlchemy URL scheme 'snowflake': Can't load plugin: sqlalchemy.dialects:snowflake",
};

/** `broken`, `8e3148f570b166f3`: its datasource is not defined (S12). */
export const BROKEN_SQL: CheckSql = {
  check_id: "8e3148f570b166f3",
  dataset: "sales.lost",
  datasource: "",
  dialect: null,
  statements: [],
  schema_lookup: false,
  error: "this dataset's datasource is not defined; run tablewatch validate",
};

/** S10: a check that uses the scan and sends its own query. */
export const SCAN_AND_QUERY_SQL: CheckSql = {
  ...EMAIL_SQL,
  check_id: "d0d0d0d0d0d0d0d0",
  statements: [
    {
      kind: "scan",
      sql: EMAIL_SQL.statements[0]?.sql ?? "",
      measures: 4,
      uses: [{ label: "m0", sql: "count(*)", shared_by: 1 }],
      shared_by: 4,
    },
    {
      kind: "query",
      sql: "SELECT coalesce(sum(duplicate_groups.n - 1), 0) AS coalesce_1 \nFROM (SELECT count(*) AS n \nFROM sales.customers \nWHERE email IS NOT NULL GROUP BY email \nHAVING count(*) > 1) AS duplicate_groups",
      shared_by: 2,
    },
  ],
};

/** P8: a `condition:` that looks like HTML. */
export const HOSTILE_CONDITION = "amount < 0 /* <img src=x onerror=alert(1)> */";
export const HOSTILE_SQL: CheckSql = {
  ...VOLUME_SQL,
  check_id: "ed669ca6e5532a59",
  statements: [
    {
      kind: "scan",
      sql: `SELECT count(*) AS m0, sum(CASE WHEN (${HOSTILE_CONDITION}) THEN 1 ELSE 0 END) AS m1 \nFROM sales.orders`,
      measures: 2,
      uses: [{ label: "m1", sql: `sum(CASE WHEN (${HOSTILE_CONDITION}) THEN 1 ELSE 0 END)`, shared_by: 0 }],
      shared_by: 1,
    },
  ],
};

/** P14: a `condition:` holding U+202E (right-to-left override) and U+200B (zero-width space). */
export const INVISIBLE_CONDITION = "amount < 0‮ -- ​";
export const INVISIBLE_SQL: CheckSql = {
  ...VOLUME_SQL,
  check_id: "ed669ca6e5532a59",
  statements: [
    {
      kind: "scan",
      sql: `SELECT sum(CASE WHEN (${INVISIBLE_CONDITION}) THEN 1 ELSE 0 END) AS m0 \nFROM sales.orders`,
      measures: 1,
      uses: [{ label: "m0", sql: `sum(CASE WHEN (${INVISIBLE_CONDITION}) THEN 1 ELSE 0 END)`, shared_by: 0 }],
      shared_by: 0,
    },
  ],
};

/**
 * P15: a scan, a kind this client does not know, and a query. The unknown
 * statement is outside the generated union, which is the point: a later
 * server may send it.
 */
export const UNKNOWN_KIND_SQL: CheckSql = {
  ...SCAN_AND_QUERY_SQL,
  statements: [
    SCAN_AND_QUERY_SQL.statements[0],
    { kind: "failed_rows", sql: "SELECT * FROM sales.customers WHERE email IS NULL" } as unknown as Statement,
    SCAN_AND_QUERY_SQL.statements[1],
  ].filter((s): s is Statement => s !== undefined),
};
