/**
 * The chart's key: every shape the chart shows, named (D11). One series, so
 * there is no legend box (decision 13): this is an inline key under the
 * chart's title. Boundary lines are labelled directly on the chart.
 */
import type { Outcome } from "../../api/types";
import type { Severity } from "./bands";
import { markName, type ChartModel } from "./layout";

export type KeyItem =
  | { kind: "mark"; key: string; outcome: Outcome; label: string }
  | { kind: "band"; key: string; severity: Severity; label: string }
  | { kind: "marker"; key: string; label: string }
  | { kind: "streak"; key: string; label: string };

const ORDER: readonly Outcome[] = ["fail", "error", "warn", "skipped", "pass"];

export function legendItems(model: ChartModel): KeyItem[] {
  const items: KeyItem[] = [];
  const seen = new Set<string>();
  const marks = [...model.marks].sort(
    (a, b) =>
      Number(a.lane !== null) - Number(b.lane !== null) || ORDER.indexOf(a.outcome) - ORDER.indexOf(b.outcome),
  );
  for (const m of marks) {
    const label = markName(m);
    if (seen.has(label)) continue;
    seen.add(label);
    items.push({ kind: "mark", key: `mark-${label}`, outcome: m.outcome, label });
  }
  if (model.bands.some((b) => b.severity === "fail") || model.lines.some((l) => l.severity === "fail")) {
    items.push({ kind: "band", key: "band-fail", severity: "fail", label: "Fails the current rule" });
  }
  if (model.bands.some((b) => b.severity === "warn") || model.lines.some((l) => l.severity === "warn")) {
    items.push({ kind: "band", key: "band-warn", severity: "warn", label: "Warns under the current rule" });
  }
  if (model.markers.length > 0) items.push({ kind: "marker", key: "marker", label: "Rule changed between two runs" });
  if (model.streak !== null) items.push({ kind: "streak", key: "streak", label: "The current streak" });
  return items;
}
