/**
 * Minimal, hand-built fixtures for the Dashboard panels (spec 042): a
 * project, checks and runs small enough to read scenario by scenario,
 * typed against the generated contract so a wire change breaks `tsc` here.
 */
import type { CheckChange, CheckRef, CheckSummary, Project, Run } from "../../api/types";

export const DASH_PROJECT: Project = {
  name: "dash-example",
  version: "0.1.0",
  loaded_at: "2026-10-15T02:00:00.000000+00:00",
  ok: true,
  datasources: [{ name: "lake", type: "duckdb" }],
  counts: { datasets: 1, checks: 1 },
  diagnostics: [],
};

let autoId = 0;

/** A minimal, valid `CheckSummary`; every field can be overridden. */
export function makeCheck(overrides: Partial<CheckSummary> = {}): CheckSummary {
  autoId += 1;
  const id = overrides.id ?? `check-${String(autoId)}`;
  return {
    id,
    name: `row_count > 0 (${id})`,
    expression: "row_count > 0",
    metric: "row_count",
    unit: "count",
    dataset: "sales.orders",
    datasource: "lake",
    datasource_state: "defined",
    owner: null,
    tags: [],
    source: "checks/sales/orders.yml:1:1",
    location: { file: "checks/sales/orders.yml", line: 1, column: 1 },
    clauses: [],
    enabled: true,
    state: "active",
    latest: null,
    ...overrides,
  };
}

/** A minimal, valid `Run`; every field (and `counts` field) can be overridden. */
export function makeRun(overrides: Partial<Omit<Run, "counts">> & { counts?: Partial<Run["counts"]> } = {}): Run {
  const counts: Run["counts"] = {
    total: 1,
    pass: 1,
    warn: 0,
    fail: 0,
    error: 0,
    skipped: 0,
    ...overrides.counts,
  };
  return {
    id: "r0000000000000000000000000000001",
    project: "dash-example",
    started_at: "2026-10-15T02:00:00.000000+00:00",
    finished_at: "2026-10-15T02:00:01.000000+00:00",
    outcome: "pass",
    exit_code: 0,
    trigger: "cli",
    version: "0.1.0",
    selection: {},
    ...overrides,
    counts,
  };
}

/** A minimal, valid `CheckRef`. */
export function makeCheckRef(overrides: Partial<CheckRef> = {}): CheckRef {
  return {
    id: "sales-orders-row-count",
    name: "row_count > 0",
    dataset: "sales.orders",
    datasource: "lake",
    state: "active",
    ...overrides,
  };
}

/** A minimal, valid `CheckChange`. */
export function makeCheckChange(overrides: Partial<CheckChange> = {}): CheckChange {
  return {
    check: makeCheckRef(),
    kind: "added",
    at: "2026-10-15T01:00:00.000000+00:00",
    version: null,
    ...overrides,
  };
}
