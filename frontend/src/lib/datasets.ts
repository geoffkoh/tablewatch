/**
 * The Datasets page's pure parts (spec 039, P-D6): one row per
 * (datasource, dataset) built in the browser from the loaded checks (active
 * and disabled), its worst status, counts, last scanned time, owners and
 * tags; searched and sorted problems first.
 */
import type { CheckSummary } from "../api/types";
import { parseTimestamp } from "./time";
import { countStatuses, STATUS_ORDER, statusOf, type Status, type StatusCounts } from "./status";

/** A dataset row's status: an enabled check's status, or "disabled" when every check on it is disabled. */
export type DatasetStatus = Status | "disabled";

/** Problems first, as every other list (D1): the loaded statuses, then "disabled" last — a dataset nobody runs is the least urgent row. */
export const DATASET_STATUS_ORDER: readonly DatasetStatus[] = [...STATUS_ORDER, "disabled"];

export interface DatasetRow {
  dataset: string;
  datasource: string;
  status: DatasetStatus;
  /** Counts over every check on this dataset, enabled and disabled alike. */
  counts: StatusCounts;
  /** The newest `latest.started_at` over its checks; null when none has ever run. */
  lastScanned: string | null;
  /** Distinct owners, name order. */
  owners: string[];
  /** Distinct tags, name order. */
  tags: string[];
}

function compareNames(a: string, b: string): number {
  const la = a.toLowerCase();
  const lb = b.toLowerCase();
  if (la !== lb) return la < lb ? -1 : 1;
  if (a === b) return 0;
  return a < b ? -1 : 1;
}

function groupKey(check: CheckSummary): string {
  return `${check.datasource}\u0000${check.dataset}`;
}

/** The worst status over a dataset's enabled checks (D1, D4); null when every check is disabled. */
function worstStatus(enabled: readonly CheckSummary[]): Status | null {
  for (const status of STATUS_ORDER) {
    if (enabled.some((c) => statusOf(c) === status)) return status;
  }
  return null;
}

function newestStarted(checks: readonly CheckSummary[]): string | null {
  let latest: string | null = null;
  let latestMs = -Infinity;
  for (const check of checks) {
    if (check.latest === null) continue;
    const ms = parseTimestamp(check.latest.started_at);
    if (Number.isNaN(ms) || ms <= latestMs) continue;
    latestMs = ms;
    latest = check.latest.started_at;
  }
  return latest;
}

/** One row per (datasource, dataset) among the loaded checks (D2: the same dataset name on two datasources is two rows). */
export function buildDatasets(checks: readonly CheckSummary[]): DatasetRow[] {
  const groups = new Map<string, CheckSummary[]>();
  for (const check of checks) {
    const key = groupKey(check);
    const list = groups.get(key);
    if (list === undefined) groups.set(key, [check]);
    else list.push(check);
  }
  const rows: DatasetRow[] = [];
  for (const list of groups.values()) {
    const first = list[0];
    if (first === undefined) continue;
    const enabled = list.filter((c) => c.enabled);
    const status: DatasetStatus = worstStatus(enabled) ?? "disabled";
    const owners = [...new Set(list.map((c) => c.owner).filter((o): o is string => o !== null))].sort(compareNames);
    const tags = [...new Set(list.flatMap((c) => c.tags))].sort(compareNames);
    rows.push({
      dataset: first.dataset,
      datasource: first.datasource,
      status,
      counts: countStatuses(list),
      lastScanned: newestStarted(list),
      owners,
      tags,
    });
  }
  return rows;
}

function rank(row: DatasetRow): number {
  const i = DATASET_STATUS_ORDER.indexOf(row.status);
  return i === -1 ? DATASET_STATUS_ORDER.length : i;
}

/** Problems first, then datasource, then dataset (P-D6). */
export function sortDatasets(rows: readonly DatasetRow[]): DatasetRow[] {
  return [...rows].sort(
    (a, b) => rank(a) - rank(b) || compareNames(a.datasource, b.datasource) || compareNames(a.dataset, b.dataset),
  );
}

/** Case-insensitive substring of dataset, datasource, an owner or a tag; leading/trailing spaces ignored (D5). */
export function matchesDatasetText(row: DatasetRow, q: string): boolean {
  const needle = q.trim().toLowerCase();
  if (needle === "") return true;
  const fields = [row.dataset, row.datasource, ...row.owners, ...row.tags];
  return fields.some((field) => field.toLowerCase().includes(needle));
}

export function filterDatasets(rows: readonly DatasetRow[], q: string): DatasetRow[] {
  return rows.filter((row) => matchesDatasetText(row, q));
}

/** A dataset "with problems": its worst status is fail or error (the summary line, P-D6). */
export function hasProblems(row: DatasetRow): boolean {
  return row.status === "fail" || row.status === "error";
}

const SUMMARY_WORDS: Readonly<Record<Status, (n: number) => string>> = {
  fail: (n) => `${String(n)} failing`,
  error: (n) => `${String(n)} ${n === 1 ? "error" : "errors"}`,
  warn: (n) => `${String(n)} ${n === 1 ? "warning" : "warnings"}`,
  none: (n) => `${String(n)} no result`,
  skipped: (n) => `${String(n)} skipped`,
  pass: (n) => `${String(n)} passing`,
};

/** The Checks column: the total, then non-zero counts in the overview's Summary words (P-D6). */
export function datasetCountsText(counts: StatusCounts): string {
  const total = `${String(counts.total)} ${counts.total === 1 ? "check" : "checks"}`;
  const parts = STATUS_ORDER.filter((s) => counts[s] > 0).map((s) => SUMMARY_WORDS[s](counts[s]));
  return parts.length === 0 ? total : `${total} (${parts.join(", ")})`;
}
