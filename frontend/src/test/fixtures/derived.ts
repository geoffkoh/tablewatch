/**
 * States derived from the captured ones, each as spec 003 defines it. Built
 * with typed copies, so they stay inside the contract.
 */
import type { CheckSummary, Diagnostic, LatestResult } from "../../api/types";
import { recorded, RUN_ID, STARTED, type OverviewResponses } from "./states";

function clone<T>(value: T): T {
  return structuredClone(value);
}

function withChecks(base: OverviewResponses, items: CheckSummary[]): OverviewResponses {
  const next = clone(base);
  next.checks = { items, total: items.length };
  next.project.counts.checks = items.length;
  return next;
}

function broken(diagnostic: Diagnostic, keep: (c: CheckSummary) => boolean, datasets: number): OverviewResponses {
  const next = withChecks(recorded, clone(recorded.checks.items).filter(keep));
  next.project.ok = false;
  next.project.diagnostics = [diagnostic];
  next.project.counts.datasets = datasets;
  return next;
}

/** `broken`: orders.yml line 11 reads `<<< 1%`; a30dacf7316eef07 drops out. */
export const brokenState = broken(
  {
    severity: "error",
    message: "expected a number, found '<'",
    location: { file: "checks/sales/orders.yml", line: 11, column: 30 },
  },
  (c) => c.id !== "a30dacf7316eef07",
  3,
);

/** `broken-yaml`: a YAML syntax error drops the whole of orders.yml. */
export const brokenYamlState = broken(
  {
    severity: "error",
    message: "invalid YAML: expected ',' or ']', but got '<stream end>'",
    location: { file: "checks/sales/orders.yml", line: 24, column: 1 },
  },
  (c) => c.dataset !== "sales.orders",
  2,
);

/** O3: customers.yml line 6 edited to `< 10%`, so the check has a new id and no result. */
export const renamedState: OverviewResponses = withChecks(
  recorded,
  clone(recorded.checks.items).map((c) =>
    c.id === "b1ceb8262d8b5441"
      ? {
          ...c,
          id: "e41cf32f07f328c3",
          name: "missing_percent(email) < 10%",
          expression: "missing_percent(email) < 10%",
          latest: null,
        }
      : c,
  ),
);

/** A store with no runs for this project. */
export const noRunsState: OverviewResponses = (() => {
  const next = withChecks(
    recorded,
    clone(recorded.checks.items).map((c) => ({ ...c, latest: null })),
  );
  next.runs = { items: [], next_cursor: null };
  return next;
})();

/** Only warnings in the check files, so `ok` is true. */
export const warningsOnlyState: OverviewResponses = (() => {
  const next = clone(recorded);
  next.project.diagnostics = [
    {
      severity: "warning",
      message: "unknown key 'descripton' (did you mean 'description'?)",
      location: { file: "checks/inventory/products.yml", line: 7, column: 7 },
    },
  ];
  return next;
})();

export function mapLatest(
  base: OverviewResponses,
  fn: (c: CheckSummary) => LatestResult | null,
): OverviewResponses {
  return withChecks(
    base,
    clone(base.checks.items).map((c) => ({ ...c, latest: fn(c) })),
  );
}

function passing(c: CheckSummary): LatestResult {
  return {
    run_id: RUN_ID.B,
    started_at: STARTED.B,
    since: STARTED.A,
    trigger: "cli",
    outcome: "pass",
    value: 0,
    display_value: "0",
    message: null,
    last_evaluated: null,
    ...(c.latest === null ? {} : { run_id: c.latest.run_id }),
  };
}

/** Every check passing, the project loaded cleanly. */
export const allPassState = mapLatest(recorded, passing);

/** Every recorded result passing, but a check file is broken. */
export const allPassBrokenState: OverviewResponses = (() => {
  const next = clone(allPassState);
  next.project.ok = false;
  next.project.diagnostics = clone(brokenState.project.diagnostics);
  return next;
})();

/** Every check passing but one, which has no result. */
export const allPassButOneUnknownState = mapLatest(recorded, (c) =>
  c.id === "b1ceb8262d8b5441" ? null : passing(c),
);

/** No checks at all. */
export const emptyState: OverviewResponses = withChecks(allPassState, []);

/** A `skipped` latest result, which the engine does not produce today. */
export const skippedState = mapLatest(recorded, (c) =>
  c.id === "cd3e8103b4318809" && c.latest !== null
    ? { ...c.latest, outcome: "skipped", display_value: "—", value: null, message: "skipped by selection" }
    : c.latest,
);
