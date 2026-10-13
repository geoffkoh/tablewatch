/**
 * Retired check fixtures (spec 037 S7–S13): built from a loaded check's
 * summary, as `RetiredCheckSummary.of` would from its last result, or from
 * nothing for one registered but never run (S10).
 */
import type { CheckSummary, RetiredCheckSummary } from "../../api/types";

/** A retired check that did run: its last result still carries what it measured. */
export function retiredOf(check: CheckSummary, overrides: Partial<RetiredCheckSummary> = {}): RetiredCheckSummary {
  return {
    id: check.id,
    name: check.name,
    dataset: check.dataset,
    datasource: check.datasource,
    state: "retired",
    retired_since: check.latest?.since ?? "2026-09-26T06:56:50.000000+00:00",
    enabled: false,
    expression: check.expression,
    metric: check.metric,
    unit: check.unit,
    owner: check.owner,
    tags: check.tags,
    last_known_location: check.source,
    latest: check.latest,
    clauses: check.clauses.map((c) => ({ key: c.key, expression: c.expression, metric: c.metric, unit: c.unit })),
    ...overrides,
  };
}

/** A retired check registered by sync but never run (S10, D3, D7): every recorded field is null or empty. */
export function neverRunRetired(
  id: string,
  name: string,
  dataset: string,
  datasource: string,
  retiredSince: string,
): RetiredCheckSummary {
  return {
    id,
    name,
    dataset,
    datasource,
    state: "retired",
    retired_since: retiredSince,
    enabled: false,
    expression: null,
    metric: null,
    unit: null,
    owner: null,
    tags: [],
    last_known_location: null,
    latest: null,
    clauses: [],
  };
}
