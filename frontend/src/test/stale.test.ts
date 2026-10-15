/**
 * "Not scanned recently" (spec 042 K-D3), pure parts: K4, K5, K6.
 */
import { describe, expect, it } from "vitest";
import type { LatestResult } from "../api/types";
import { staleDatasets } from "../lib/stale";
import { makeCheck, makeRun } from "./fixtures/dashboard";

function latest(startedAt: string): LatestResult {
  return {
    run_id: "r1",
    started_at: startedAt,
    since: startedAt,
    trigger: "cli",
    outcome: "pass",
    value: 1,
    display_value: "1",
    message: null,
    last_evaluated: null,
  };
}

describe("K4: more than 24 hours before the newest run is stale", () => {
  const newestRun = makeRun({ started_at: "2026-10-15T02:00:00Z" });
  const orders = makeCheck({ id: "orders-1", dataset: "orders", datasource: "lake", latest: latest("2026-10-14T01:00:00Z") });
  const customers = makeCheck({ id: "customers-1", dataset: "customers", datasource: "lake", latest: latest("2026-10-15T02:00:00Z") });

  it("lists the stale dataset and not the fresh one", () => {
    const rows = staleDatasets([orders, customers], newestRun);
    expect(rows.map((r) => r.dataset)).toEqual(["orders"]);
    expect(rows[0]?.lastScanned).toBe("2026-10-14T01:00:00Z");
  });

  it("does not flag exactly 24 hours as stale (more than, not at least)", () => {
    const exact = makeCheck({ id: "exact", dataset: "exact", datasource: "lake", latest: latest("2026-10-14T02:00:00Z") });
    expect(staleDatasets([exact], newestRun)).toEqual([]);
  });
});

describe("K5: never-run enabled checks read 'never scanned'; disabled-only is left out", () => {
  const newestRun = makeRun({ started_at: "2026-10-15T02:00:00Z" });

  it("'never scanned' for a dataset with enabled checks that never ran", () => {
    const neverRun = makeCheck({ id: "never-1", dataset: "returns", datasource: "lake", latest: null, enabled: true });
    const rows = staleDatasets([neverRun], newestRun);
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({ dataset: "returns", datasource: "lake", lastScanned: null });
  });

  it("leaves out a disabled-only dataset", () => {
    const disabledOnly = makeCheck({ id: "disabled-1", dataset: "legacy", datasource: "lake", enabled: false, latest: null });
    expect(staleDatasets([disabledOnly], newestRun)).toEqual([]);
  });
});

describe("K6: no runs at all flags nothing", () => {
  it("returns no stale rows when there is no newest run", () => {
    const neverRun = makeCheck({ id: "never-2", dataset: "returns", datasource: "lake", latest: null, enabled: true });
    expect(staleDatasets([neverRun], null)).toEqual([]);
  });
});

describe("other rules", () => {
  it("groups by (datasource, dataset), and uses only enabled checks for the newest scan", () => {
    const newestRun = makeRun({ started_at: "2026-10-15T02:00:00Z" });
    const enabledStale = makeCheck({
      id: "a",
      dataset: "orders",
      datasource: "lake",
      enabled: true,
      latest: latest("2026-10-14T01:00:00Z"),
    });
    // A disabled check on the same dataset scanned recently must not rescue it from staleness (K-D3).
    const disabledFresh = makeCheck({
      id: "b",
      dataset: "orders",
      datasource: "lake",
      enabled: false,
      latest: latest("2026-10-15T02:00:00Z"),
    });
    const rows = staleDatasets([enabledStale, disabledFresh], newestRun);
    expect(rows).toHaveLength(1);
    expect(rows[0]?.lastScanned).toBe("2026-10-14T01:00:00Z");
  });

  it("sorts oldest (and never-scanned) first", () => {
    const newestRun = makeRun({ started_at: "2026-10-20T00:00:00Z" });
    const a = makeCheck({ id: "a", dataset: "a", datasource: "lake", latest: latest("2026-10-10T00:00:00Z") });
    const b = makeCheck({ id: "b", dataset: "b", datasource: "lake", latest: null });
    const c = makeCheck({ id: "c", dataset: "c", datasource: "lake", latest: latest("2026-10-05T00:00:00Z") });
    const rows = staleDatasets([a, b, c], newestRun);
    expect(rows.map((r) => r.dataset)).toEqual(["b", "c", "a"]);
  });
});
