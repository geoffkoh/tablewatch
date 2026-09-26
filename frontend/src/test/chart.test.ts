/**
 * The chart's pure functions (spec 004 chart requirement 7): bands (D6),
 * ticks and domain (D10), series, lanes, rule changes and other metrics
 * (D5, D7, D8, D9, D20), label placement, and the summary (D11).
 */
import { describe, expect, it } from "vitest";
import type { Condition, HistoryEntry, Rule } from "../api/types";
import { bands, intervalText } from "../lib/chart/bands";
import { rawDomain, yAxis } from "../lib/chart/domain";
import { formatDuration, formatTick } from "../lib/chart/format";
import { assignRows, stackLabels } from "../lib/chart/labels";
import { layoutChart, markName, MIN_COLUMN, tooltipBox, tooltipLines } from "../lib/chart/layout";
import { legendItems } from "../lib/chart/legend";
import { buildSeries, type CurrentCheck } from "../lib/chart/series";
import { chartSummary } from "../lib/chart/summary";
import { niceTicks, timeTicks } from "../lib/chart/ticks";
import { ruleBoundaries } from "../lib/rule";
import {
  edited,
  editedPending,
  emailHistory,
  emailSummary,
  entry,
  metricChangedBack,
  RULES,
  rowsHistory,
  threeRules,
} from "./fixtures/detail";
import { STARTED } from "./fixtures/states";

const cmp = (op: "=" | "!=" | "<" | "<=" | ">" | ">=", value: number): Condition => ({
  kind: "compare",
  op,
  value,
  text: `${op} ${String(value)}`,
});
const between = (low: number, high: number, negated = false): Condition => ({
  kind: "between",
  low,
  high,
  negated,
  text: `${negated ? "not " : ""}between ${String(low)} and ${String(high)}`,
});
const expect_ = (c: Condition): Rule => ({ expect: c, warn: null, fail: null });
const triggers = (warn: Condition | null, fail: Condition | null): Rule => ({ expect: null, warn, fail });

describe("D6: the threshold bands", () => {
  // rule | y-domain | fail region(s) | warn region(s) | lines at
  const TABLE: [string, Rule, [number, number], string[], string[], number[]][] = [
    ["expect < 5", expect_(cmp("<", 5)), [0, 25], ["[5, 25]"], [], [5]],
    ["expect > 0", expect_(cmp(">", 0)), [0, 10], [], [], [0]],
    ["expect between 10 and 500", expect_(between(10, 500)), [0, 600], ["[0, 10)", "(500, 600]"], [], [10, 500]],
    ["expect not between 5 and 10", expect_(between(5, 10, true)), [0, 20], ["[5, 10]"], [], [5, 10]],
    ["expect = 0", expect_(cmp("=", 0)), [0, 3], ["(0, 3]"], [], [0]],
    ["expect = 0, negative domain", expect_(cmp("=", 0)), [-2, 3], ["[-2, 0)", "(0, 3]"], [], [0]],
    ["expect != 0", expect_(cmp("!=", 0)), [0, 3], [], [], [0]],
    ["expect between 5 and 5", expect_(between(5, 5)), [0, 10], ["[0, 5)", "(5, 10]"], [], [5]],
    ["warn < 100, fail = 0", triggers(cmp("<", 100), cmp("=", 0)), [0, 120], [], ["[0, 100)"], [0, 100]],
    ["fail != 0", triggers(null, cmp("!=", 0)), [0, 3], ["(0, 3]"], [], [0]],
    [
      "warn > 86400, fail > 604800",
      triggers(cmp(">", 86400), cmp(">", 604800)),
      [0, 700000],
      ["(604800, 700000]"],
      ["(86400, 604800]"],
      [86400, 604800],
    ],
  ];

  it.each(TABLE)("%s", (_, rule, domain, fail, warn, lines) => {
    const result = bands(rule, domain);
    expect(result.fail.map(intervalText)).toEqual(fail);
    expect(result.warn.map(intervalText)).toEqual(warn);
    expect(result.lines.map((l) => l.value)).toEqual(lines);
  });

  it("draws a single failing value as a line in the fail colour", () => {
    const result = bands(expect_(cmp("!=", 0)), [0, 3]);
    expect(result.fail).toEqual([]);
    expect(result.lines).toEqual([{ value: 0, severity: "fail", text: "!= 0" }]);
  });

  it("labels each line with the condition's text from the API, never its numbers", () => {
    const rule: Rule = { expect: { kind: "compare", op: "<", value: 5, text: "< 5%" }, warn: null, fail: null };
    expect(bands(rule, [0, 25]).lines.map((l) => l.text)).toEqual(["< 5%"]);
  });

  it("colours warn lines warn and fail lines fail", () => {
    const result = bands(RULES["41e58afff9c48a46"] ?? expect_(cmp("<", 0)), [0, 700000]);
    expect(result.lines.map((l) => [l.value, l.severity, l.text])).toEqual([
      [86400, "warn", "> 1d"],
      [604800, "fail", "> 7d"],
    ]);
  });
});

describe("D10: y-axis ticks by unit", () => {
  it.each([
    ["percent", 20, "20%"],
    ["percent", 2.5, "2.5%"],
    ["count", 12000, "12,000"],
    ["duration", 21600, "6h"],
    ["duration", 86400, "1d"],
    ["duration", 90, "1m 30s"],
    ["duration", -25200, "-7h"],
    ["number", 54.3571, "54.36"],
    ["number", -1.5, "-1.5"],
  ] as const)("%s %d reads %s", (unit, value, tick) => {
    expect(formatTick(value, unit)).toBe(tick);
  });

  it("formats a metric of unknown unit as a plain number", () => {
    expect(formatTick(12000, null)).toBe("12,000");
  });

  it("never prints -0", () => {
    expect(formatTick(-0, "count")).toBe("0");
  });

  it("formats durations with at most two adjacent units", () => {
    expect(formatDuration(0)).toBe("0s");
    expect(formatDuration(0.5)).toBe("0.5s");
    expect(formatDuration(93_784)).toBe("1d 2h");
    expect(formatDuration(3_600 + 5)).toBe("1h");
  });

  it("picks round steps: 1-2-5 for numbers, whole counts, clock units for durations", () => {
    expect(niceTicks(0, 25, "percent")).toMatchObject({ lo: 0, hi: 25, step: 5 });
    expect(niceTicks(0, 3, "count").step).toBe(1);
    expect(niceTicks(0, 0.3, "count").step).toBe(1);
    expect(niceTicks(0, 0.3, "number").step).toBe(0.05);
    const d = niceTicks(-25200, 21600, "duration");
    expect(d.step % 3600).toBe(0);
    expect(d.values.map((v) => formatTick(v, "duration", d.step))).toContain("0s");
    expect(niceTicks(0, 700000, "duration").values.map((v) => formatTick(v, "duration"))).toEqual([
      "0s",
      "2d",
      "4d",
      "6d",
      "8d",
      "10d",
    ]);
  });

  it("uses as many decimals as the step needs", () => {
    const t = niceTicks(0, 0.3, "number");
    expect(t.values.map((v) => formatTick(v, "number", t.step))).toEqual(["0", "0.05", "0.1", "0.15", "0.2", "0.25", "0.3"]);
  });
});

describe("D10: the y-domain", () => {
  const inside = (axis: { lo: number; hi: number }, v: number): boolean => v >= axis.lo && v <= axis.hi;

  it("values {20}, boundary 5: both inside", () => {
    const axis = yAxis([20], [5], "percent");
    expect(inside(axis, 20) && inside(axis, 5)).toBe(true);
    expect(axis.offRange).toEqual([]);
  });

  it("values {3}, boundaries 1 and 10000: 1 and 3 inside, 10000 off-range above", () => {
    const axis = yAxis([3], [1, 10000], "count");
    expect(inside(axis, 1) && inside(axis, 3)).toBe(true);
    expect(inside(axis, 10000)).toBe(false);
    expect(axis.offRange).toEqual([{ value: 10000, side: "above" }]);
    expect(`${formatTick(10000, "count")} above`).toBe("10,000 above");
  });

  it("values {3, 4, 5, 3}, boundaries 1 and 10000: the values span at least half the height", () => {
    const axis = yAxis([3, 4, 5, 3], [1, 10000], "count");
    expect((5 - 3) / (axis.hi - axis.lo)).toBeGreaterThanOrEqual(0.5);
    expect(axis.offRange.map((o) => o.value)).toEqual([10000]);
  });

  it("no values (every entry an error), boundary 5: the domain contains 5", () => {
    const axis = yAxis([], [5], "percent");
    expect(inside(axis, 5)).toBe(true);
  });

  it("negative freshness {-25200, -21600}, boundary 21600: negatives and 0 inside, never clamped", () => {
    const axis = yAxis([-25200, -21600], [21600], "duration");
    expect(inside(axis, -25200) && inside(axis, -21600) && inside(axis, 0)).toBe(true);
    expect(axis.lo).toBeLessThan(0);
  });

  it("values measured by another metric do not enter the domain (D20)", () => {
    const series = buildSeries(metricChangedBack.history.items, current(metricChangedBack.check));
    expect(series.plotted.map((p) => p.value)).toEqual([20, 20, 20]);
    const axis = yAxis(
      series.plotted.map((p) => p.value ?? 0),
      ruleBoundaries(metricChangedBack.check.rule),
      "percent",
    );
    expect(axis.lo).toBe(0);
    // 1 (missing_count) would pull nothing: the domain is the same without it.
    expect(rawDomain([20, 20, 20], [15])).toEqual(rawDomain(series.plotted.map((p) => p.value ?? 0), [15]));
  });

  it("gives a zero-only history a domain with height", () => {
    expect(yAxis([0, 0], [0], "count")).toMatchObject({ lo: 0, hi: 1 });
  });
});

function current(check: { metric: string; unit: CurrentCheck["unit"]; expression: string }): CurrentCheck {
  return { metric: check.metric, unit: check.unit, expression: check.expression };
}

const EMAIL: CurrentCheck = { metric: "missing_percent", unit: "percent", expression: "missing_percent(email) < 5%" };

describe("D5: series, lanes and line breaks", () => {
  it("interrupted b1ceb8262d8b5441: three values at 20, E in the error lane, the line breaks at E", () => {
    const s = buildSeries(emailHistory.items, EMAIL);
    expect(s.plotted.map((p) => [p.entry.run_id.slice(0, 1), p.value, p.outcome])).toEqual([
      ["a", 20, "fail"],
      ["b", 20, "fail"],
      ["f", 20, "fail"],
    ]);
    expect(s.lanes.error.map((p) => p.entry.run_id.slice(0, 1))).toEqual(["e"]);
    expect(s.lanes["no-value"]).toEqual([]);
    expect(s.segments.map((seg) => seg.map((p) => p.entry.run_id.slice(0, 1)))).toEqual([["a", "b"], ["f"]]);
  });

  it("interrupted 32c8f939b90f6367: three passes at 5 and one error", () => {
    const s = buildSeries(rowsHistory.items, { metric: "row_count", unit: "count", expression: "row_count > 0" });
    expect(s.plotted.map((p) => [p.value, p.outcome])).toEqual([
      [5, "pass"],
      [5, "pass"],
      [5, "pass"],
    ]);
    expect(s.lanes.error).toHaveLength(1);
  });

  it("one result: one mark and no line", () => {
    const model = layoutChart({ entries: emailHistory.items.slice(0, 1), check: EMAIL, rule: RULES.b1ceb8262d8b5441 ?? null, streak: null });
    expect(model.marks).toHaveLength(1);
    expect(model.paths).toEqual([]);
  });

  it("two results at the same time: both kept, in history order", () => {
    const a = entry(emailSummary, "A", { outcome: "fail", value: 20, display_value: "20.00%" });
    const b = { ...a, run_id: "b-same-time", value: 21, display_value: "21.00%" };
    const s = buildSeries([b, a], EMAIL);
    expect(s.plotted.map((p) => p.entry.run_id)).toEqual([a.run_id, "b-same-time"]);
    const model = layoutChart({ entries: [b, a], check: EMAIL, rule: null, streak: null });
    expect(model.marks).toHaveLength(2);
  });

  it("x is time, not run index: uneven gaps stay uneven", () => {
    const model = layoutChart({ entries: emailHistory.items, check: EMAIL, rule: RULES.b1ceb8262d8b5441 ?? null, streak: null });
    const xs = [...model.marks].sort((p, q) => p.x - q.x).map((m) => m.x);
    const gaps = xs.slice(1).map((x, i) => x - (xs[i] ?? 0));
    // A→B is 22 s, B→E 18 s, E→F 15 s.
    expect(gaps[0]).toBeGreaterThan(gaps[2] ?? 0);
  });
});

describe("D7: rule changes and the band's span", () => {
  it("edited: one marker between A and C, band only from the marker", () => {
    const s = buildSeries(edited.history.items, current(edited.check));
    expect(s.ruleChanges).toHaveLength(1);
    const change = s.ruleChanges[0];
    expect(change?.older.expression).toBe("missing_percent(email) < 5%");
    expect(change?.newer.expression).toBe("missing_percent(email) < 15%");
    expect(change?.t).toBeGreaterThan(Date.parse(STARTED.A));
    expect(s.band).toEqual({ from: change?.t });
  });

  it("A → B → A gives two markers; the band covers the newest segment only", () => {
    const e = (run: "A" | "B" | "F", expression: string): HistoryEntry =>
      entry(emailSummary, run, { outcome: "fail", value: 20, display_value: "20.00%", expression });
    const hist = [e("F", EMAIL.expression), e("B", "missing_percent(email) < 9%"), e("A", EMAIL.expression)];
    const s = buildSeries(hist, EMAIL);
    expect(s.ruleChanges.map((c) => c.number)).toEqual([1, 2]);
    expect(s.band?.from).toBe(s.ruleChanges[1]?.t);
  });

  it("edited-pending: no band anywhere, the markers are the recorded ones only", () => {
    const s = buildSeries(editedPending.history.items, current(editedPending.check));
    expect(s.band).toBeNull();
    expect(s.ruleChanges).toHaveLength(1);
    const model = layoutChart({ entries: editedPending.history.items, check: current(editedPending.check), rule: editedPending.check.rule, streak: null });
    expect(model.bands).toEqual([]);
    expect(model.lines).toEqual([]);
    expect(model.axis.offRange).toEqual([]);
  });

  it("D20: a dataset change under one id is a marker too", () => {
    const hist = [
      entry(emailSummary, "B", { dataset: "crm.customers", value: 20, display_value: "20.00%" }),
      entry(emailSummary, "A", { value: 20, display_value: "20.00%" }),
    ];
    const s = buildSeries(hist, EMAIL);
    expect(s.ruleChanges).toHaveLength(1);
    expect(s.ruleChanges[0]).toMatchObject({ datasetChanged: true, expressionChanged: false });
  });
});

describe("D8: marks keep the recorded outcome", () => {
  it("A passed under < 25%; its mark is pass although 20 is in today's failing region", () => {
    const model = layoutChart({ entries: threeRules.history.items, check: current(threeRules.check), rule: threeRules.check.rule, streak: null });
    expect(model.marks.map((m) => m.outcome)).toEqual(["pass", "fail", "fail"]);
  });
});

describe("D9: a failure with no value", () => {
  it.each(["no value to evaluate", "no timestamps in scope"])("'%s' goes in the No value lane as a fail", (message) => {
    const fail = entry(emailSummary, "F", { outcome: "fail", value: null, display_value: "—", message });
    const s = buildSeries([fail, ...emailHistory.items.slice(1)], EMAIL);
    expect(s.lanes["no-value"].map((p) => p.outcome)).toEqual(["fail"]);
    expect(s.plotted.map((p) => p.entry.run_id)).not.toContain(fail.run_id);
    expect(markName(s.lanes["no-value"][0] ?? { outcome: "pass", lane: null })).toBe("Fail: no value measured");
    expect(markName(s.lanes.error[0] ?? { outcome: "pass", lane: null })).toBe("Could not evaluate");
  });

  it("a skipped entry sits in the No value lane with its own name, never error or pass", () => {
    const skipped = entry(emailSummary, "F", { outcome: "skipped", value: null, display_value: "—" });
    const s = buildSeries([skipped], EMAIL);
    expect(s.lanes["no-value"].map((p) => p.outcome)).toEqual(["skipped"]);
    expect(markName(s.lanes["no-value"][0] ?? { outcome: "pass", lane: null })).toBe("Skipped");
  });

  it("lanes are drawn only when they have entries, with their names", () => {
    const model = layoutChart({ entries: emailHistory.items, check: EMAIL, rule: null, streak: null });
    expect(model.lanes.map((l) => l.label)).toEqual(["Could not evaluate"]);
    const onlyValues = layoutChart({ entries: [emailHistory.items[0] as HistoryEntry], check: EMAIL, rule: null, streak: null });
    expect(onlyValues.lanes).toEqual([]);
  });
});

describe("D20: values measured by another metric", () => {
  it("plots N, C and A, leaves M off the axis, breaks the line, and keeps the markers", () => {
    const s = buildSeries(metricChangedBack.history.items, current(metricChangedBack.check));
    expect(s.plotted.map((p) => p.entry.metric)).toEqual(["missing_percent", "missing_percent", "missing_percent"]);
    expect(s.offAxis.map((p) => [p.entry.metric, p.entry.display_value])).toEqual([["missing_count", "1"]]);
    expect(s.otherMetrics).toEqual(["missing_count"]);
    expect(s.segments.map((seg) => seg.length)).toEqual([2, 1]);
    expect(s.ruleChanges.map((c) => [c.older.metric, c.newer.metric])).toEqual([
      ["missing_percent", "missing_percent"],
      ["missing_percent", "missing_count"],
      ["missing_count", "missing_percent"],
    ]);
  });

  it("a check no longer loaded plots only when every entry has one metric", () => {
    expect(buildSeries(emailHistory.items, null).axisMetric).toBe("missing_percent");
    expect(buildSeries(emailHistory.items, null).axisUnit).toBe("percent");
    expect(buildSeries(emailHistory.items, null).band).toBeNull();
    const mixed = buildSeries(metricChangedBack.history.items, null);
    expect(mixed.axisMetric).toBeNull();
    expect(mixed.plotted).toEqual([]);
  });
});

describe("label placement", () => {
  it("stacks labels so none overlaps, keeping them inside the column when they fit", () => {
    const out = stackLabels(
      [
        { id: "a", y: 100 },
        { id: "b", y: 102 },
        { id: "c", y: 101 },
        { id: "d", y: 300 },
      ],
      14,
      0,
      200,
    );
    const ys = [...out.values()].sort((p, q) => p - q);
    for (let i = 1; i < ys.length; i += 1) expect((ys[i] ?? 0) - (ys[i - 1] ?? 0)).toBeGreaterThanOrEqual(14);
    expect(Math.max(...ys)).toBeLessThanOrEqual(200);
  });

  it("puts overlapping marker labels on separate rows", () => {
    const rows = assignRows([
      { id: "1", x0: 0, x1: 80 },
      { id: "2", x0: 40, x1: 120 },
      { id: "3", x0: 200, x1: 280 },
    ]);
    expect([rows.get("1"), rows.get("2"), rows.get("3")]).toEqual([0, 1, 0]);
  });
});

describe("the layout", () => {
  const model = layoutChart({
    entries: emailHistory.items,
    check: EMAIL,
    rule: RULES.b1ceb8262d8b5441 ?? null,
    streak: { outcome: "fail", since: STARTED.A, latestAt: STARTED.F },
  });

  it("gives every hover column at least 24 units", () => {
    expect(model.columns.length).toBe(4);
    for (const c of model.columns) expect(c.x1 - c.x0).toBeGreaterThanOrEqual(MIN_COLUMN);
  });

  it("shades the failing region from 5 up, with a line at 5 labelled < 5% and the marks inside it", () => {
    const [band] = model.bands;
    const [line] = model.lines;
    expect(band?.severity).toBe("fail");
    expect(line?.text).toBe("< 5%");
    expect(band?.y1).toBe(line?.y);
    for (const m of model.marks.filter((mk) => mk.lane === null)) {
      expect(m.y).toBeGreaterThanOrEqual(band?.y0 ?? Infinity);
      expect(m.y).toBeLessThanOrEqual(band?.y1 ?? -Infinity);
    }
  });

  it("keeps the tooltip inside the chart, value first", () => {
    for (const c of model.columns) {
      const tip = tooltipBox(model, c);
      expect(tip.x).toBeGreaterThanOrEqual(0);
      expect(tip.x + tip.width).toBeLessThanOrEqual(model.width);
      expect(tip.lines[0]?.strong).toBe(true);
    }
    const errorColumn = model.columns.find((c) => c.points.some((p) => p.outcome === "error"));
    expect(tooltipLines(errorColumn?.points ?? []).map((l) => l.text)[0]).toBe("Could not evaluate");
  });

  it("names every shape shown in the key", () => {
    expect(legendItems(model).map((i) => i.label)).toEqual([
      "Fail",
      "Could not evaluate",
      "Fails the current rule",
      "The current streak",
    ]);
  });

  it("states the time zone on the x-axis", () => {
    expect(model.timeNote).toMatch(/times in (GMT\+8|SGT)/);
    expect(model.xTicks.length).toBeGreaterThan(1);
  });
});

describe("x ticks", () => {
  it("are round local times inside the range", () => {
    const t0 = Date.parse("2026-09-26T06:55:50Z");
    const t1 = Date.parse("2026-09-26T06:56:45Z");
    const ticks = timeTicks(t0, t1);
    expect(ticks.step).toBe(15_000);
    for (const t of ticks.values) {
      expect(t).toBeGreaterThanOrEqual(t0);
      expect(t).toBeLessThanOrEqual(t1);
      expect(t % 15_000).toBe(0);
    }
  });

  it("align days on local midnight", () => {
    const ticks = timeTicks(Date.parse("2026-09-20T03:00:00Z"), Date.parse("2026-09-26T03:00:00Z"));
    expect(ticks.step).toBe(86_400_000);
    for (const t of ticks.values) expect(new Date(t).getHours()).toBe(0);
  });
});

describe("D11: the summary", () => {
  it("interrupted b1ceb8262d8b5441: counts, the latest value, the rule and both dates", () => {
    const s = buildSeries(emailHistory.items, EMAIL);
    const text = chartSummary({ entries: emailHistory.items, series: s, rule: RULES.b1ceb8262d8b5441 ?? null, pending: false, more: false });
    expect(text).toContain("4 results");
    expect(text).toContain("3 fail");
    expect(text).toContain("1 could not evaluate");
    expect(text).toContain("20.00%");
    expect(text).toContain("< 5%");
    expect(text).toContain("14:55:50");
    expect(text).toContain("14:56:45");
    expect(text).toContain("Sep 26, 2026");
  });

  it("says when values are left off the axis and when the rule is not yet used", () => {
    const s = buildSeries(metricChangedBack.history.items, current(metricChangedBack.check));
    const text = chartSummary({ entries: metricChangedBack.history.items, series: s, rule: metricChangedBack.check.rule, pending: true, more: true });
    expect(text).toContain("1 result measured a different metric (missing_count) and is not plotted");
    expect(text).toContain("not yet used by any run");
    expect(text).toContain("The latest 4 results");
  });
});
