/**
 * `GET /api/v1/alerts`'s shape (spec 041 P4), typed against the generated
 * contract so a wire change breaks `tsc` here.
 */
import type { Alert, AlertPage } from "../../api/types";

function alert(overrides: Partial<Alert> & Pick<Alert, "event" | "run_id" | "started_at">): Alert {
  return {
    check: {
      id: "sales-orders-row-count",
      name: "row_count between 1 and 10000",
      dataset: "sales.orders",
      datasource: "lake",
      state: "active",
    },
    outcome: "fail",
    previous_outcome: "pass",
    deliveries: null,
    ...overrides,
  };
}

/** Three events, newest first: recovered, erroring, failing — each a different check. */
export const baseAlerts: AlertPage = {
  items: [
    alert({
      event: "recovered",
      outcome: "pass",
      previous_outcome: "fail",
      run_id: "f0000000000000000000000000000004",
      started_at: "2026-09-26T06:56:45.000000+00:00",
      check: {
        id: "sales-customers-freshness",
        name: "freshness under 2 hours",
        dataset: "sales.customers",
        datasource: "lake",
        state: "active",
      },
      deliveries: [{ notifier: "ops", status: "sent", attempts: 1, sent_at: "2026-09-26T06:56:50.000000+00:00" }],
    }),
    alert({
      event: "erroring",
      outcome: "error",
      previous_outcome: "fail",
      run_id: "e0000000000000000000000000000003",
      started_at: "2026-09-26T06:56:30.000000+00:00",
      check: {
        id: "inventory-products-completeness",
        name: "sku completeness",
        dataset: "inventory.products",
        datasource: "lake",
        state: "active",
      },
      deliveries: null,
    }),
    alert({
      event: "failing",
      outcome: "fail",
      previous_outcome: "pass",
      run_id: "b0000000000000000000000000000002",
      started_at: "2026-09-26T06:56:12.000000+00:00",
      deliveries: [],
    }),
  ],
  next_cursor: null,
};
