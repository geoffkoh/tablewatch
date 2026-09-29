/**
 * Spec 012, adversarial (qa-engineer): "Current" against the band on
 * awkward histories, "No value measured" across the three places a result
 * is shown, `between` labels and the right-label stack at their edges.
 * Builder tests are in polish.test.tsx; these add the cases they leave out.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { CheckDetail, Condition, HistoryEntry, Rule } from "../api/types";
import { bands } from "../lib/chart/bands";
import { formatThreshold } from "../lib/chart/format";
import { LATEST_GAP, LINE_HEIGHT } from "../lib/chart/labels";
import { layoutChart, type ChartModel } from "../lib/chart/layout";
import { buildSeries } from "../lib/chart/series";
import { mapLatest } from "./fixtures/derived";
import { avgOnNothing, AVG_ON_NOTHING_ID, edited, EDITED_ID, emailSummary, entry, page } from "./fixtures/detail";
import { recorded, STARTED } from "./fixtures/states";
import { CLOCK, ok, renderCheck, renderOverview, rowFor, setClock, text } from "./render";

beforeEach(() => {
  setClock(CLOCK);
});

afterEach(() => {
  vi.useRealTimers();
});

const SAME = "Same as current, before a rule change";
const E5 = "missing_percent(email) < 5%";
const E15 = "missing_percent(email) < 15%";

/** Entry i minutes before A (0 is the newest), judged by `expression`. */
function at(i: number, expression: string, fields: Partial<HistoryEntry> = {}): HistoryEntry {
  return entry({ ...emailSummary, expression, name: expression }, "A", {
    run_id: `q${String(i).padStart(31, "0")}`,
    started_at: new Date(Date.parse(STARTED.A) - i * 60_000).toISOString(),
    outcome: "fail",
    value: 20,
    display_value: "20.00%",
    message: null,
    expression,
    name: expression,
    ...fields,
  });
}

function ruleCells(): string[] {
  const table = document.querySelector("table.history-table");
  if (table === null) throw new Error("no history table");
  return Array.from(table.querySelectorAll<HTMLElement>("tbody tr")).map((r) => text(r.querySelectorAll("td")[4] ?? r));
}

const cur = (c: CheckDetail): { metric: string; unit: CheckDetail["unit"]; expression: string } => ({
  metric: c.metric,
  unit: c.unit,
  expression: c.expression,
});

// ---- K ------------------------------------------------------------------------

describe("K, adversarial: 'Current' is exactly the band's run", () => {
  it("repeated edits (<15, <5, <15, <5, <15): only the newest reads Current", async () => {
    const items = [at(0, E15), at(1, E5), at(2, E15), at(3, E5), at(4, E15)];
    expect([...buildSeries(items, cur(edited.check)).currentRun]).toEqual([0]);
    await renderCheck(EDITED_ID, { check: ok(edited.check), history: ok(page(items)) });
    expect(ruleCells()).toEqual([
      "Current",
      `Different rule ${E5}`,
      SAME,
      `Different rule ${E5}`,
      SAME,
    ]);
  });

  it("a current run of NULL values (no band area) still reads Current (K2 should)", async () => {
    const none = { outcome: "fail", value: null, display_value: "—" } as const;
    const items = [at(0, E15, none), at(1, E15, { ...none, outcome: "error", message: "boom" }), at(2, E5)];
    expect([...buildSeries(items, cur(edited.check)).currentRun].sort()).toEqual([0, 1]);
    await renderCheck(EDITED_ID, { check: ok(edited.check), history: ok(page(items)) });
    expect(ruleCells()).toEqual(["Current", "Current", `Different rule ${E5}`]);
  });

  it("an entry with an unreadable started_at is never Current (K2 guard)", async () => {
    const items = [at(0, E15), at(1, E15, { started_at: "not a time" }), at(2, E15)];
    const run = buildSeries(items, cur(edited.check)).currentRun;
    expect(run.has(1)).toBe(false);
    expect([...run].sort()).toEqual([0, 2]);
  });

  it("equal times keep history order: the run follows the API's newest-first rows", () => {
    const t = STARTED.A;
    const items = [at(0, E15, { started_at: t }), at(1, E5, { started_at: t }), at(2, E15, { started_at: t })];
    // Newest is row 0 (under <15), then a <5 row, so only row 0 is in the run.
    expect([...buildSeries(items, cur(edited.check)).currentRun]).toEqual([0]);
  });
});

// ---- L ------------------------------------------------------------------------

describe("L, adversarial: a non-finite value keeps its display_value on the overview too", () => {
  it("overview row shows 'nan', not 'No value measured'", async () => {
    const id = "366d9254d889c910";
    const base = avgOnNothing.check.latest;
    if (base === null) throw new Error("fixture");
    const state = mapLatest(recorded, (c) => (c.id === id ? { ...base, display_value: "nan", message: null } : c.latest));
    await renderOverview(state);
    expect(text(rowFor(id))).toContain("nan");
    expect(text(rowFor(id))).not.toContain("No value measured");
  });

  it("a no-value result in the history table, pass or warn, reads the words, never a dash", async () => {
    const items = avgOnNothing.history.items.flatMap((e) => [
      { ...e, outcome: "pass" as const, message: null },
      { ...e, outcome: "warn" as const, message: null, run_id: `${e.run_id.slice(0, -1)}9` },
    ]);
    await renderCheck(AVG_ON_NOTHING_ID, { check: ok(avgOnNothing.check), history: ok(page(items)) });
    const table = document.querySelector("table.history-table");
    const values = Array.from(table?.querySelectorAll("tbody tr") ?? []).map((r) => text(r.querySelectorAll("td")[2] ?? r));
    expect(values).toEqual(["No value measured", "No value measured"]);
  });
});

// ---- B: labels ------------------------------------------------------------------

const between = (low: number, high: number, negated = false): Condition => ({
  kind: "between",
  low,
  high,
  negated,
  text: `${negated ? "not " : ""}between ${String(low)} and ${String(high)}`,
});
const cmp = (op: "<" | ">" | "=", value: number): Condition => ({ kind: "compare", op, value, text: `${op} ${String(value)}` });

describe("B, adversarial: threshold labels", () => {
  it("a negated between with a negative low end: < -0.125 and > 60", () => {
    const rule: Rule = { expect: between(-0.125, 60, true), warn: null, fail: null };
    expect(bands(rule, [-1, 100], (v) => formatThreshold(v, "number")).lines.map((l) => l.text)).toEqual(["< -0.125", "> 60"]);
  });

  it("fail and warn betweens together: each line says its own end, in its own colour", () => {
    const rule: Rule = { expect: null, warn: between(52, 58), fail: between(40, 70) };
    const lines = bands(rule, [0, 100], (v) => formatThreshold(v, "number")).lines;
    expect(lines.map((l) => [l.severity, l.text]).sort()).toEqual(
      [
        ["fail", ">= 40"],
        ["fail", "<= 70"],
        ["warn", ">= 52"],
        ["warn", "<= 58"],
      ].sort(),
    );
  });

  it("formatThreshold never rounds a tiny threshold to 0 (B6: 'never round')", () => {
    // 1e-25 prints as "0": `between 1e-25 and 1` would be labelled ">= 0".
    expect(formatThreshold(1e-25, "number")).not.toBe("0");
    expect(formatThreshold(-1e-25, "number")).not.toMatch(/^-?0$/);
  });

  it("formatThreshold never rounds a huge threshold (B6: 'never round')", () => {
    // 1.23456789e21 prints as "1.235E21", which reads back as another number.
    expect(Number(formatThreshold(1.23456789e21, "number").replace(/,/g, ""))).toBe(1.23456789e21);
  });
});

// ---- B: the stack ----------------------------------------------------------------

function at2(i: number, value: number | null): HistoryEntry {
  return entry(emailSummary, "A", {
    run_id: `s${String(i).padStart(31, "0")}`,
    started_at: new Date(Date.parse(STARTED.A) - i * 60_000).toISOString(),
    outcome: "fail",
    value,
    display_value: String(value),
    metric: "avg",
    unit: "number",
  });
}

function chart(values: number[], rule: Rule): ChartModel {
  return layoutChart({
    entries: values.map((v, i) => at2(i, v)),
    check: { metric: "avg", unit: "number", expression: emailSummary.expression },
    rule,
    streak: null,
  });
}

const STACKS: [string, number[], Rule][] = [
  ["two above", [3, 4], { expect: between(500, 1000), warn: null, fail: null }],
  ["two below", [1000, 1010], { expect: between(0.125, 0.5), warn: null, fail: null }],
  ["latest at top, lines near it", [100, 0], { expect: between(0, 98), warn: null, fail: cmp(">", 99) }],
  ["four lines, latest in the middle", [55, 50], { expect: null, warn: between(52, 58), fail: between(40, 70) }],
  ["four lines, both ends off", [55, 50], { expect: null, warn: between(52, 58), fail: between(-10000, 70000) }],
  ["latest at top, above label", [100, 90], { expect: between(99, 100000), warn: null, fail: null }],
  ["latest at bottom, below label", [0, 10], { expect: between(-100000, 1), warn: null, fail: null }],
  ["latest at top, two lines and above", [99, 0], { expect: between(98, 100000), warn: cmp(">", 97), fail: null }],
];

describe("B7, adversarial: sides and gaps hold on crowded columns", () => {
  it.each(STACKS)("%s", (_, values, rule) => {
    const model = chart(values, rule);
    const latest = model.rightLabels.find((l) => l.kind === "latest");
    if (latest === undefined) throw new Error("no latest");
    for (const l of model.rightLabels) {
      if (l === latest) continue;
      expect(Math.abs(l.y - latest.y)).toBeGreaterThanOrEqual(LATEST_GAP);
      if (l.kind === "off-range" && l.text.endsWith(" above")) expect(l.y).toBeLessThan(latest.y);
      if (l.kind === "off-range" && l.text.endsWith(" below")) expect(l.y).toBeGreaterThan(latest.y);
    }
    const ys = model.rightLabels.map((l) => l.y).sort((a, b) => a - b);
    for (let i = 1; i < ys.length; i += 1) expect((ys[i] ?? 0) - (ys[i - 1] ?? 0)).toBeGreaterThanOrEqual(LINE_HEIGHT);
  });
});

describe("B7, adversarial: two edge labels on one side keep the axis's order", () => {
  const y = (model: ChartModel, label: string): number => model.rightLabels.find((l) => l.text === label)?.y ?? NaN;

  it("'1,000 above' sits above '500 above'", () => {
    const model = chart([3, 4], { expect: between(500, 1000), warn: null, fail: null });
    expect(y(model, "1,000 above")).toBeLessThan(y(model, "500 above"));
  });

  it("'0.125 below' sits below '0.5 below'", () => {
    const model = chart([1000, 1010], { expect: between(0.125, 0.5), warn: null, fail: null });
    expect(y(model, "0.125 below")).toBeGreaterThan(y(model, "0.5 below"));
  });
});

describe("B8, adversarial: the latest label stays within 20 of its mark", () => {
  // REFINE (spec 012 Q1) limited B8 to the four B7 fixtures: where B7 and B8
  // cannot both hold, B7 wins. "two below" is such a column (the latest value
  // sits at the bottom, under two edge labels), so it is asserted apart.
  const B8_HOLDS = STACKS.filter(([name]) => name !== "two below");

  it("two below: B7's sides and gaps hold, and the latest label may be more than 20 from its mark", () => {
    const found = STACKS.find(([name]) => name === "two below");
    if (found === undefined) throw new Error("no 'two below' column");
    const model = chart(found[1], found[2]);
    const latest = model.rightLabels.find((l) => l.kind === "latest");
    if (latest === undefined) throw new Error("no latest");
    for (const l of model.rightLabels) {
      if (l === latest) continue;
      expect(Math.abs(l.y - latest.y)).toBeGreaterThanOrEqual(LATEST_GAP);
      if (l.text.endsWith(" below")) expect(l.y).toBeGreaterThan(latest.y);
    }
    const ys = model.rightLabels.map((l) => l.y).sort((a, b) => a - b);
    for (let i = 1; i < ys.length; i += 1) expect((ys[i] ?? 0) - (ys[i - 1] ?? 0)).toBeGreaterThanOrEqual(LINE_HEIGHT);
    const newest = model.series.plotted[model.series.plotted.length - 1];
    const mark = model.marks.find((m) => m.point === newest);
    expect(Math.abs(latest.y - (mark?.y ?? NaN))).toBeGreaterThan(20);
  });

  it.each(B8_HOLDS)("%s", (_, values, rule) => {
    const model = chart(values, rule);
    const label = model.rightLabels.find((l) => l.kind === "latest");
    const newest = model.series.plotted[model.series.plotted.length - 1];
    const mark = model.marks.find((m) => m.point === newest);
    expect(Math.abs((label?.y ?? NaN) - (mark?.y ?? NaN))).toBeLessThanOrEqual(20);
  });
});
