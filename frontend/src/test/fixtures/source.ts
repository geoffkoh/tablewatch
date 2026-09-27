/**
 * `GET /checks/{id}/source` responses (spec 006). The `retail` and
 * `commented` bodies are what `/source` answered from the in-process app on
 * a scratch copy of examples/retail (and the spec's `commented` files) on
 * 2026-09-27; only `loaded_at` is replaced, by `LOADED_AT`, so every caption
 * reads "2 hours ago" against the tests' clock. The rest are built for the
 * scenarios that need them (P8, P14, P15).
 *
 * Typed against the generated contract: a contract change breaks `tsc` here.
 */
import type { CheckDetail, CheckSource } from "../../api/types";

/** Two hours and seven minutes before the tests' clock (`CLOCK`, 09:56:55Z). */
export const LOADED_AT = "2026-09-26T07:50:00.000000+00:00";

function body(fields: Omit<CheckSource, "loaded_at" | "filter"> & Partial<Pick<CheckSource, "filter">>): CheckSource {
  return { filter: null, loaded_at: LOADED_AT, ...fields };
}

// ---- retail -------------------------------------------------------------------

/** `b1ceb8262d8b5441`, Y1. */
export const EMAIL_SOURCE = body({
  check_id: "b1ceb8262d8b5441",
  path: "checks/sales/customers.yml",
  start_line: 6,
  end_line: 7,
  text: "  - missing_percent(email) < 5%:\n      missing_values: ['', 'N/A']",
});

/** `32c8f939b90f6367`, Y3: one line. */
export const ROWS_SOURCE = body({
  check_id: "32c8f939b90f6367",
  path: "checks/sales/customers.yml",
  start_line: 4,
  end_line: 4,
  text: "  - row_count > 0",
});

/** `32867fbe86f483f3`, Y2. */
export const VOLUME_SOURCE = body({
  check_id: "32867fbe86f483f3",
  path: "checks/sales/orders.yml",
  start_line: 5,
  end_line: 8,
  text: "  - row_count:\n      name: Order volume\n      warn: when < 100\n      fail: when = 0",
});

/** `fbc3aa0b93b66eee`, Y3: the last check in a file. */
export const SCHEMA_SOURCE = body({
  check_id: "fbc3aa0b93b66eee",
  path: "checks/sales/orders.yml",
  start_line: 18,
  end_line: 20,
  text: "  - schema:\n      required_columns: [order_id, customer_id, status, amount, created_at]\n      column_types: {amount: decimal}",
});

/** Every captured `retail` body, by check id; `render.tsx` answers with these by default. */
export const SOURCE_BY_ID: Readonly<Record<string, CheckSource>> = {
  b1ceb8262d8b5441: EMAIL_SOURCE,
  "32c8f939b90f6367": ROWS_SOURCE,
  "32867fbe86f483f3": VOLUME_SOURCE,
  fbc3aa0b93b66eee: SCHEMA_SOURCE,
};

/** A body for a loaded check the captures lack: one plain line. */
export function genericSource(id: string): CheckSource {
  return body({ check_id: id, path: "checks/sales/customers.yml", start_line: 4, end_line: 4, text: "  - row_count > 0" });
}

// ---- commented ------------------------------------------------------------------

/** `32867fbe86f483f3` on `commented`, Y4: its comment line 10 included. */
export const COMMENTED_VOLUME_SOURCE = body({
  check_id: "32867fbe86f483f3",
  path: "checks/sales/orders.yml",
  start_line: 10,
  end_line: 14,
  text: "  # Volume alarm agreed with ops, 2026-09.\n  - row_count:\n      name: Order volume\n      warn: when < 100\n      fail: when = 0",
});

/** `/checks/32867fbe86f483f3` on `commented`: the fields P11 needs differ from retail's. */
export const COMMENTED_VOLUME_SOURCE_LOCATION: Pick<CheckDetail, "source" | "location"> = {
  source: "checks/sales/orders.yml:11:5",
  location: { file: "checks/sales/orders.yml", line: 11, column: 5 },
};

/** `4a831091035ca6c6`, Y12: the file's filter applies. */
export const AVG_SOURCE = body({
  check_id: "4a831091035ca6c6",
  path: "checks/sales/returns.yml",
  start_line: 11,
  end_line: 12,
  text: "  - avg(amount) between 1 and 500:\n      where: reason != 'damaged'",
  filter: { line: 3, text: "status != 'test'", applies: true },
});

/** `e3a77b3bf2c0c560`, Y8: a flow-style line shared by two checks. */
export const FLOW_SOURCE = body({
  check_id: "e3a77b3bf2c0c560",
  path: "checks/flow.yml",
  start_line: 3,
  end_line: 3,
  text: 'checks: [row_count > 0, "duplicate_count(id) = 0"]',
});

/** `98cd31ce24b6afef` ("Custom", sql_metric), Y12: the filter does not apply. */
export const CUSTOM_SOURCE = body({
  check_id: "98cd31ce24b6afef",
  path: "checks/sales/filtered.yml",
  start_line: 4,
  end_line: 6,
  text: "  - sql_metric > 0:\n      name: Custom\n      query: SELECT 1",
  filter: { line: 2, text: "status != 'test'", applies: false },
});

/** `2f9a43de2ae47ba9` (schema), Y12: the filter does not apply. */
export const FILTERED_SCHEMA_SOURCE = body({
  check_id: "2f9a43de2ae47ba9",
  path: "checks/sales/filtered.yml",
  start_line: 7,
  end_line: 8,
  text: "  - schema:\n      required_columns: [id]",
  filter: { line: 2, text: "status != 'test'", applies: false },
});

/** `ec91af87c6b3495e` (`one.yml`), Y17: span unavailable, the filter set. */
export const UNAVAILABLE_SOURCE = body({
  check_id: "ec91af87c6b3495e",
  path: "checks/sales/one.yml",
  start_line: null,
  end_line: null,
  text: null,
  filter: { line: 1, text: "status != 'test'", applies: true },
});

// ---- built for P8 and P14 ----------------------------------------------------------

/** P8: a comment that looks like HTML. */
export const HOSTILE_COMMENT = "  # <script>alert(1)</script> <img src=x onerror=alert(1)>";
export const HOSTILE_SOURCE = body({
  check_id: "b1ceb8262d8b5441",
  path: "checks/sales/customers.yml",
  start_line: 5,
  end_line: 7,
  text: `${HOSTILE_COMMENT}\n  - missing_percent(email) < 5%:\n      missing_values: ['', 'N/A']`,
});

/**
 * P14: a comment line holding U+202E, a `name:` line holding U+2028 (Y18's),
 * and a blank line between them, in a file whose path holds U+200B.
 */
export const INVISIBLE_TEXT = "  # amount ‮< 0 is fine\n\n  - row_count > 0:\n      name: \"Row count\"";
export const INVISIBLE_SOURCE = body({
  check_id: "8cc200a22eae9821",
  path: "checks/sales/orders​.yml",
  start_line: 3,
  end_line: 6,
  text: INVISIBLE_TEXT,
});

/**
 * P14: a BOM stays in line 1 of a flow-style file (read as utf-8, not
 * utf-8-sig). `text`, lines and id are what `/source` answered on 2026-09-27
 * for `retail` plus `checks/sales/bom.yml` = BOM + `checks: [row_count > 0]`,
 * `dataset: sales.returns`; the path is changed to hold a C0 control (ESC).
 */
export const BOM_SOURCE = body({
  check_id: "f1b6f7f30337ea68",
  path: "checks/sales/bo\u001Bm.yml",
  start_line: 1,
  end_line: 1,
  text: "﻿checks: [row_count > 0]",
});
