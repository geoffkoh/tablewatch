/**
 * The six states a check row can be in, and everything that tells them apart.
 *
 * `error` (tablewatch could not evaluate) and `fail` (the data is bad) go to
 * different people, so each state has its own label, icon and colour; colour
 * is never the only signal.
 */
import type { CheckSummary, Outcome } from "../api/types";

/** A recorded outcome, or `none` when the check has no result in the store. */
export type Status = Outcome | "none";

/** Problems first: the order of every list and every summary (O1). */
export const STATUS_ORDER: readonly Status[] = ["fail", "error", "warn", "none", "skipped", "pass"];

export interface StatusMeta {
  /** The short label, the CLI's word. */
  label: string;
  /** The icon's accessible name: what the state means. */
  meaning: string;
}

export const STATUS_META: Readonly<Record<Status, StatusMeta>> = {
  fail: { label: "Fail", meaning: "Data failed the check" },
  error: { label: "Error", meaning: "Could not evaluate" },
  warn: { label: "Warn", meaning: "Data crossed the warning threshold" },
  none: { label: "No result recorded", meaning: "Unknown: never recorded" },
  skipped: { label: "Skipped", meaning: "Not evaluated: skipped" },
  pass: { label: "Pass", meaning: "Data passed the check" },
};

export function statusOf(check: CheckSummary): Status {
  return check.latest === null ? "none" : check.latest.outcome;
}

/**
 * Checks in problem-first order. The sort is stable, so within a status the
 * API's order (project file order) is kept.
 */
export function sortProblemsFirst(checks: readonly CheckSummary[]): CheckSummary[] {
  const rank = (check: CheckSummary): number => STATUS_ORDER.indexOf(statusOf(check));
  return [...checks].sort((a, b) => rank(a) - rank(b));
}

export type StatusCounts = Record<Status, number> & { total: number };

/** Counts over the loaded checks; they always add up to `total`. */
export function countStatuses(checks: readonly CheckSummary[]): StatusCounts {
  const counts: StatusCounts = { fail: 0, error: 0, warn: 0, none: 0, skipped: 0, pass: 0, total: 0 };
  for (const check of checks) {
    counts[statusOf(check)] += 1;
    counts.total += 1;
  }
  return counts;
}

/** Checks whose latest is an error but whose last evaluated result failed (P7). */
export function errorsLastFailing(checks: readonly CheckSummary[]): number {
  return checks.filter(
    (c) => c.latest?.outcome === "error" && c.latest.last_evaluated?.outcome === "fail",
  ).length;
}
