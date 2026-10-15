/**
 * The Dashboard's "Problems per run" trend (spec 042 K-D1): the last 30 runs
 * from `GET /runs?limit=30`, oldest first (the API sends newest first), one
 * bar per run of its `fail + error` count, the bar's mark coloured by the
 * run's own outcome. Fewer than 2 runs is "not enough runs" territory
 * (`hasTrend`); the page shows the empty sentence itself.
 */
import type { Counts, Run } from "../api/types";
import { parseTimestamp } from "./time";

export interface TrendBar {
  key: string;
  /** `fail + error`: how many checks had a problem in this run. */
  problems: number;
  /** The run's own outcome: colours the bar (K-D1). */
  outcome: Run["outcome"];
  /** The accessible label/tooltip: "Run of 14 Oct 02:00: 3 failing, 1 in error, 40 passing". */
  label: string;
}

const DAY_MONTH = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short" });
const TIME = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", hourCycle: "h23" });

function when(iso: string): string {
  const ms = parseTimestamp(iso);
  if (Number.isNaN(ms)) return "an unknown time";
  const d = new Date(ms);
  return `${DAY_MONTH.format(d)} ${TIME.format(d)}`;
}

/** "3 failing, 1 in error, 40 passing": non-zero counts only, problems first. */
export function runCountsText(counts: Counts): string {
  const parts: string[] = [];
  if (counts.fail > 0) parts.push(`${String(counts.fail)} failing`);
  if (counts.error > 0) parts.push(`${String(counts.error)} in error`);
  if (counts.warn > 0) parts.push(`${String(counts.warn)} ${counts.warn === 1 ? "warning" : "warnings"}`);
  if (counts.skipped > 0) parts.push(`${String(counts.skipped)} skipped`);
  if (counts.pass > 0) parts.push(`${String(counts.pass)} passing`);
  return parts.length === 0 ? "0 checks" : parts.join(", ");
}

/** "Run of 14 Oct 02:00: 3 failing, 1 in error, 40 passing" (K-D1). */
export function trendRunLabel(run: Run): string {
  return `Run of ${when(run.started_at)}: ${runCountsText(run.counts)}`;
}

/** At least 2 runs: enough to draw a trend (K-D1, K2). */
export function hasTrend(runs: readonly Run[]): boolean {
  return runs.length >= 2;
}

/** The bars, oldest first (the API's `/runs` sends newest first). */
export function buildTrendBars(runs: readonly Run[]): TrendBar[] {
  return [...runs].reverse().map((run) => ({
    key: run.id,
    problems: run.counts.fail + run.counts.error,
    outcome: run.outcome,
    label: trendRunLabel(run),
  }));
}

export interface LaidOutBar extends TrendBar {
  x: number;
  y: number;
  width: number;
  height: number;
}

const GAP = 4;

/**
 * Pixel positions for `buildTrendBars`' output: evenly spaced columns across
 * `plotWidth`, each bar's height proportional to the largest `problems` count
 * (0 problems draws no bar, never a negative or NaN height).
 */
export function layoutTrendBars(bars: readonly TrendBar[], plotWidth: number, plotHeight: number): LaidOutBar[] {
  const n = bars.length;
  if (n === 0) return [];
  const slot = plotWidth / n;
  const width = Math.max(1, slot - GAP);
  const max = Math.max(1, ...bars.map((b) => b.problems));
  return bars.map((b, i) => {
    const height = b.problems <= 0 ? 0 : (b.problems / max) * plotHeight;
    return { ...b, x: i * slot + GAP / 2, y: plotHeight - height, width, height };
  });
}
