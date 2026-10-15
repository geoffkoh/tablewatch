/**
 * The Dashboard's "Not scanned recently" panel (spec 042 K-D3): datasets
 * grouped like `lib/datasets.ts`'s `buildDatasets`, whose newest
 * `latest.started_at` over their *enabled* checks is more than 24 hours
 * before the newest run's `started_at`. A disabled-only dataset is left out;
 * a dataset with enabled checks that never ran reads "never scanned"
 * (`lastScanned: null`). Measured against the newest run, not the clock: with
 * no run at all, nothing is flagged stale.
 */
import type { CheckSummary, Run } from "../api/types";
import { groupByDataset, newestStarted } from "./datasets";
import { parseTimestamp } from "./time";

const STALE_MS = 24 * 60 * 60 * 1000;

export interface StaleDataset {
  dataset: string;
  datasource: string;
  /** The newest `latest.started_at` over the dataset's enabled checks; null means "never scanned". */
  lastScanned: string | null;
}

/** Stale datasets, oldest (most overdue, "never scanned" first) first. */
export function staleDatasets(checks: readonly CheckSummary[], newestRun: Run | null): StaleDataset[] {
  if (newestRun === null) return [];
  const newestMs = parseTimestamp(newestRun.started_at);
  if (Number.isNaN(newestMs)) return [];
  const rows: StaleDataset[] = [];
  for (const list of groupByDataset(checks).values()) {
    const enabled = list.filter((c) => c.enabled);
    const first = enabled[0];
    if (first === undefined) continue; // disabled-only: left out
    const lastScanned = newestStarted(enabled);
    if (lastScanned === null) {
      rows.push({ dataset: first.dataset, datasource: first.datasource, lastScanned: null });
      continue;
    }
    const lastMs = parseTimestamp(lastScanned);
    if (!Number.isNaN(lastMs) && newestMs - lastMs > STALE_MS) {
      rows.push({ dataset: first.dataset, datasource: first.datasource, lastScanned });
    }
  }
  return rows.sort((a, b) => {
    const am = a.lastScanned === null ? -Infinity : parseTimestamp(a.lastScanned);
    const bm = b.lastScanned === null ? -Infinity : parseTimestamp(b.lastScanned);
    return am - bm;
  });
}
