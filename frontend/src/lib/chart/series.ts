/**
 * What the history chart draws, from the history entries (newest first, as
 * the API sends them) and the check as loaded. Pure.
 *
 * - A value is plotted when the entry has one, its outcome is not `error`,
 *   and its recorded `metric` is the axis metric (D20): the check's current
 *   metric, or, for a check no longer loaded, the one metric every entry
 *   shares. A value measured by another metric is not plotted, does not enter
 *   the y-domain, and breaks the line.
 * - `error` entries go in the "Could not evaluate" lane; any other entry
 *   without a value goes in the "No value" lane (decision 10). Neither is
 *   ever plotted as 0.
 * - The line joins consecutive plotted values in history order and breaks at
 *   anything in between (D5).
 * - A rule-change marker sits between every two consecutive entries whose
 *   recorded `expression` (or `dataset`) differs (D7, D20).
 * - The current rule's band covers only the newest run of entries whose
 *   recorded `expression` equals the check's; if the newest entry was judged
 *   by another rule (an edit not yet run), no band is drawn (D7). That run is
 *   `currentRun`, and the history table calls exactly those rows "Current"
 *   (spec 012 K2): one rule for both, so they cannot drift.
 * - Marks keep the recorded outcome (D8). Nothing here evaluates a rule.
 */
import type { HistoryEntry, Outcome, Unit } from "../../api/types";
import { parseTimestamp } from "../time";

export type Lane = "error" | "no-value";

export interface Point {
  /** Index in the API's order (0 = newest). */
  index: number;
  entry: HistoryEntry;
  t: number;
  outcome: Outcome;
  kind: "value" | "lane" | "off-axis";
  value: number | null;
  lane: Lane | null;
}

export interface RuleChange {
  /** 1-based, oldest first. */
  number: number;
  /** Midway between the two runs. */
  t: number;
  older: HistoryEntry;
  newer: HistoryEntry;
  expressionChanged: boolean;
  datasetChanged: boolean;
}

export interface CurrentCheck {
  metric: string;
  unit: Unit;
  expression: string;
}

export interface Series {
  /** Every entry with a readable time, oldest first. */
  points: Point[];
  plotted: Point[];
  /** Runs of consecutive plotted points; a run of one draws no line. */
  segments: Point[][];
  lanes: Record<Lane, Point[]>;
  offAxis: Point[];
  /** Metrics of the values left off the axis, in first-seen order. */
  otherMetrics: string[];
  ruleChanges: RuleChange[];
  /** The metric on the y-axis, or null when nothing can be plotted on one axis. */
  axisMetric: string | null;
  axisUnit: Unit | null;
  /**
   * The band's span: `null` for no band; `{ from: null }` from the start of
   * the chart; `{ from: t }` from the rule change at t.
   */
  band: { from: number | null } | null;
  /**
   * The entries under the band: the newest run judged by the check's current
   * expression, as indexes in the API's order. Empty when no band is drawn.
   */
  currentRun: ReadonlySet<number>;
}

function axisOf(entries: readonly HistoryEntry[], check: CurrentCheck | null): { metric: string | null; unit: Unit | null } {
  if (check !== null) return { metric: check.metric, unit: check.unit };
  const metrics = new Set(entries.map((e) => e.metric));
  if (metrics.size !== 1) return { metric: null, unit: null };
  const units = new Set(entries.map((e) => e.unit));
  const [unit] = [...units];
  return { metric: [...metrics][0] ?? null, unit: units.size === 1 && unit !== undefined ? unit : null };
}

export function buildSeries(entries: readonly HistoryEntry[], check: CurrentCheck | null): Series {
  const axis = axisOf(entries, check);
  const points: Point[] = [];
  entries.forEach((entry, index) => {
    const t = parseTimestamp(entry.started_at);
    if (Number.isNaN(t)) return;
    let kind: Point["kind"];
    let lane: Lane | null = null;
    if (entry.outcome === "error") {
      kind = "lane";
      lane = "error";
    } else if (entry.value === null || !Number.isFinite(entry.value)) {
      kind = "lane";
      lane = "no-value";
    } else if (axis.metric !== null && entry.metric === axis.metric) {
      kind = "value";
    } else {
      kind = "off-axis";
    }
    points.push({
      index,
      entry,
      t,
      outcome: entry.outcome,
      kind,
      value: kind === "value" ? entry.value : null,
      lane,
    });
  });
  // Oldest first; equal times keep history order (older index first).
  points.sort((a, b) => a.t - b.t || b.index - a.index);

  const segments: Point[][] = [];
  let run: Point[] = [];
  for (const p of points) {
    if (p.kind === "value") run.push(p);
    else if (run.length > 0) {
      segments.push(run);
      run = [];
    }
  }
  if (run.length > 0) segments.push(run);

  const ruleChanges: RuleChange[] = [];
  for (let i = 1; i < points.length; i += 1) {
    const older = points[i - 1];
    const newer = points[i];
    if (older === undefined || newer === undefined) continue;
    const expressionChanged = older.entry.expression !== newer.entry.expression;
    const datasetChanged = older.entry.dataset !== newer.entry.dataset;
    if (expressionChanged || datasetChanged) {
      ruleChanges.push({
        number: ruleChanges.length + 1,
        t: (older.t + newer.t) / 2,
        older: older.entry,
        newer: newer.entry,
        expressionChanged,
        datasetChanged,
      });
    }
  }

  let band: Series["band"] = null;
  const currentRun = new Set<number>();
  const newest = points[points.length - 1];
  if (check !== null && newest !== undefined && newest.entry.expression === check.expression) {
    let first = points.length - 1;
    while (first > 0 && points[first - 1]?.entry.expression === check.expression) first -= 1;
    for (const p of points.slice(first)) currentRun.add(p.index);
    const before = points[first - 1];
    const start = points[first];
    band = before === undefined || start === undefined ? { from: null } : { from: (before.t + start.t) / 2 };
  } else if (check !== null && newest === undefined) {
    // No results: the rule still has a place on an empty chart.
    band = { from: null };
  }

  const plotted = points.filter((p) => p.kind === "value");
  const offAxis = points.filter((p) => p.kind === "off-axis");
  return {
    points,
    plotted,
    segments,
    lanes: {
      error: points.filter((p) => p.lane === "error"),
      "no-value": points.filter((p) => p.lane === "no-value"),
    },
    offAxis,
    otherMetrics: [...new Set(offAxis.map((p) => p.entry.metric))],
    ruleChanges,
    axisMetric: axis.metric,
    axisUnit: axis.unit,
    band,
    currentRun,
  };
}
