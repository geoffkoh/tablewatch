/**
 * The chart's `<desc>` (spec 004 D11): a short text summary built by one
 * pure function. The history table is the long alternative.
 */
import type { HistoryEntry, Outcome, Rule } from "../../api/types";
import { ruleSentence } from "../rule";
import { absolute } from "../time";
import type { Series } from "./series";

const OUTCOME_WORDS: readonly (readonly [Outcome, string])[] = [
  ["fail", "fail"],
  ["error", "could not evaluate"],
  ["warn", "warn"],
  ["skipped", "skipped"],
  ["pass", "pass"],
];

export interface SummaryInput {
  entries: readonly HistoryEntry[];
  series: Series;
  /** The loaded rule, or null for a check no longer loaded. */
  rule: Rule | null;
  /** True when the newest result was judged by another rule (an edit not yet run). */
  pending: boolean;
  /** True when older results exist beyond those loaded. */
  more: boolean;
}

/** "4 results, from … to …: 3 fail, 1 could not evaluate. Latest value 20.00% (fail). Current rule: Expected < 5%." */
export function chartSummary({ entries, series, rule, pending, more }: SummaryInput): string {
  const n = entries.length;
  if (n === 0) return "No results recorded yet.";
  const counts = new Map<Outcome, number>();
  for (const e of entries) counts.set(e.outcome, (counts.get(e.outcome) ?? 0) + 1);
  const parts = OUTCOME_WORDS.filter(([o]) => (counts.get(o) ?? 0) > 0).map(
    ([o, words]) => `${String(counts.get(o) ?? 0)} ${words}`,
  );
  const oldest = series.points[0];
  const newest = series.points[series.points.length - 1];
  const sentences: string[] = [];
  const span =
    oldest !== undefined && newest !== undefined
      ? `, from ${absolute(oldest.entry.started_at)} to ${absolute(newest.entry.started_at)}`
      : "";
  sentences.push(`${more ? "The latest " : ""}${String(n)} ${n === 1 ? "result" : "results"}${span}: ${parts.join(", ")}.`);
  const latestValue = series.plotted[series.plotted.length - 1];
  if (latestValue !== undefined) {
    sentences.push(`Latest plotted value ${latestValue.entry.display_value} (${latestValue.outcome}).`);
  } else {
    sentences.push("No value is plotted.");
  }
  if (series.offAxis.length > 0) {
    const k = series.offAxis.length;
    sentences.push(
      `${String(k)} ${k === 1 ? "result" : "results"} measured a different metric (${series.otherMetrics.join(", ")}) and ${k === 1 ? "is" : "are"} not plotted.`,
    );
  }
  if (series.ruleChanges.length > 0) {
    const k = series.ruleChanges.length;
    sentences.push(`The rule changed ${k === 1 ? "once" : `${String(k)} times`}.`);
  }
  if (rule !== null) {
    sentences.push(`Current rule: ${ruleSentence(rule)}${pending ? ", not yet used by any run" : ""}.`);
  } else {
    sentences.push("The check is not in the loaded check files, so no rule is drawn.");
  }
  return sentences.join(" ");
}
