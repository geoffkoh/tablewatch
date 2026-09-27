/**
 * Spec 004, adversarial (qa-engineer): the chart's pure functions at their
 * edges, and the route parser against encodings. Builder tests are in
 * chart.test.ts and route.test.ts; these add the cases they leave out.
 */
import { describe, expect, it } from "vitest";
import type { Condition, HistoryEntry, Rule } from "../api/types";
import { bands, intervalText } from "../lib/chart/bands";
import { rawDomain, yAxis } from "../lib/chart/domain";
import { layoutChart } from "../lib/chart/layout";
import { linear } from "../lib/chart/scale";
import { buildSeries, type CurrentCheck } from "../lib/chart/series";
import { chartSummary } from "../lib/chart/summary";
import { niceTicks, timeTicks } from "../lib/chart/ticks";
import { checkHref, parseRoute } from "../lib/route";
import { emailSummary, entry } from "./fixtures/detail";
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

const CURRENT: CurrentCheck = {
  metric: emailSummary.metric,
  unit: emailSummary.unit,
  expression: emailSummary.expression,
};

function at(i: number, fields: Partial<HistoryEntry> = {}): HistoryEntry {
  return entry(emailSummary, "A", {
    run_id: `r${String(i).padStart(31, "0")}`,
    started_at: new Date(Date.parse(STARTED.A) - i * 60_000).toISOString(),
    outcome: "fail",
    value: 20,
    display_value: "20.00%",
    ...fields,
  });
}

// ---- bands -----------------------------------------------------------------

describe("bands: every operator and the awkward domains", () => {
  const TABLE: [string, Rule, [number, number], string[], string[], number[]][] = [
    ["expect <= 5", expect_(cmp("<=", 5)), [0, 25], ["(5, 25]"], [], [5]],
    ["expect >= 5", expect_(cmp(">=", 5)), [0, 25], ["[0, 5)"], [], [5]],
    ["expect != 5 (a single failing value)", expect_(cmp("!=", 5)), [0, 10], [], [], [5]],
    ["expect = 5, boundary below the domain", expect_(cmp("=", 5)), [10, 20], ["[10, 20]"], [], []],
    ["expect = 0, boundary above a negative domain", expect_(cmp("=", 0)), [-3, -1], ["[-3, -1]"], [], []],
    ["expect < 5 over a domain that is all failing", expect_(cmp("<", 5)), [10, 20], ["[10, 20]"], [], []],
    ["expect < 50 over a domain that is all passing", expect_(cmp("<", 50)), [0, 20], [], [], []],
    ["expect not between 5 and 5", expect_(between(5, 5, true)), [0, 10], [], [], [5]],
    ["expect not between -1 and 1", expect_(between(-1, 1, true)), [-5, 5], ["[-1, 1]"], [], [-1, 1]],
    ["expect between -10 and -5", expect_(between(-10, -5)), [-20, 0], ["[-20, -10)", "(-5, 0]"], [], [-10, -5]],
    ["fail != 0 over a negative domain", triggers(null, cmp("!=", 0)), [-2, 3], ["[-2, 0)", "(0, 3]"], [], [0]],
    ["fail = 0 alone", triggers(null, cmp("=", 0)), [0, 3], [], [], [0]],
    ["warn >= 10 under fail > 5: fail covers warn", triggers(cmp(">=", 10), cmp(">", 5)), [0, 20], ["(5, 20]"], [], [5, 10]],
    [
      "warn between 1 and 10, fail not between 0 and 20",
      triggers(between(1, 10), between(0, 20, true)),
      [-5, 25],
      ["[-5, 0)", "(20, 25]"],
      ["[1, 10]"],
      [0, 1, 10, 20],
    ],
    ["a zero-height domain on the boundary", expect_(cmp("<", 5)), [5, 5], [], [], [5]],
  ];

  it.each(TABLE)("%s", (_, rule, domain, fail, warn, lines) => {
    const result = bands(rule, domain);
    expect(result.fail.map(intervalText)).toEqual(fail);
    expect(result.warn.map(intervalText)).toEqual(warn);
    expect(result.lines.map((l) => l.value)).toEqual(lines);
  });

  it("never returns an interval outside the domain, or one without height", () => {
    const rules: Rule[] = [
      expect_(cmp("=", 3)),
      expect_(cmp("!=", 3)),
      expect_(between(2, 4, true)),
      triggers(cmp("<", 2), cmp(">", 8)),
      triggers(between(0, 5), cmp("!=", 7)),
    ];
    for (const rule of rules) {
      for (const domain of [
        [0, 10],
        [-10, 0],
        [3, 3],
        [100, 200],
      ] as [number, number][]) {
        const b = bands(rule, domain);
        for (const i of [...b.fail, ...b.warn]) {
          expect(i.lo).toBeGreaterThanOrEqual(domain[0]);
          expect(i.hi).toBeLessThanOrEqual(domain[1]);
          expect(i.hi).toBeGreaterThan(i.lo);
        }
      }
    }
  });
});

// ---- domain and ticks ------------------------------------------------------

describe("domain and ticks at the edges", () => {
  it("no values and no boundaries still has height", () => {
    const [lo, hi] = rawDomain([], []);
    expect(hi).toBeGreaterThan(lo);
  });

  it("no values, a negative boundary: the domain holds it and 0", () => {
    expect(rawDomain([], [-5])).toEqual([-5, 0]);
  });

  it("a single negative value is drawn below 0 with 0 in view", () => {
    const [lo, hi] = rawDomain([-5], []);
    expect(lo).toBeLessThanOrEqual(-5);
    expect(hi).toBeGreaterThanOrEqual(0);
  });

  it("drops non-finite values instead of poisoning the domain", () => {
    expect(rawDomain([Number.NaN, Infinity, 3], [])).toEqual(rawDomain([3], []));
  });

  it("a boundary far below the values is an off-range label below", () => {
    const axis = yAxis([9000, 9500], [1, 10000], "count");
    expect(axis.offRange).toEqual([{ value: 1, side: "below" }]);
    expect(axis.lo).toBeLessThanOrEqual(9000);
    expect(axis.hi).toBeGreaterThanOrEqual(10000);
  });

  it.each([
    ["nearly equal averages", [54.35714285714286, 54.357142857142864], "number"],
    ["huge counts", [0, 1.7e308], "count"],
    ["huge durations", [0, 1e20], "duration"],
    ["tiny percents", [1e-9, 2e-9], "percent"],
    ["large, close counts", [1e15, 1e15 + 2], "count"],
  ] as const)("%s: finite round ticks that hold every value", (_, values, unit) => {
    const axis = yAxis([...values], [], unit);
    expect(Number.isFinite(axis.lo)).toBe(true);
    expect(Number.isFinite(axis.hi)).toBe(true);
    expect(axis.hi).toBeGreaterThan(axis.lo);
    expect(axis.values.length).toBeGreaterThanOrEqual(2);
    expect(axis.values.length).toBeLessThanOrEqual(7);
    for (const v of values) {
      expect(v).toBeGreaterThanOrEqual(axis.lo);
      expect(v).toBeLessThanOrEqual(axis.hi);
    }
    for (const t of axis.values) expect(Number.isFinite(t)).toBe(true);
  });

  it("values that differ past 12 significant digits keep an axis with height, and a failing rule stays shaded", () => {
    // avg/sum over large amounts: DuckDB's parallel float sums differ run to
    // run in the last digits even on an unchanged table.
    const entries = [
      at(0, { metric: CURRENT.metric, value: 1234567.8912345, display_value: "1234567.89" }),
      at(1, { metric: CURRENT.metric, value: 1234567.8912346, display_value: "1234567.89" }),
    ];
    const model = layoutChart({ entries, check: CURRENT, rule: expect_(between(10, 500)), streak: null });
    expect(model.axis.hi).toBeGreaterThan(model.axis.lo);
    for (const m of model.marks) {
      expect(m.y).toBeGreaterThanOrEqual(model.plot.y0);
      expect(m.y).toBeLessThanOrEqual(model.plot.y1);
    }
    // Both results fail `between 10 and 500`; white would read as passing (D6).
    expect(model.bands.filter((b) => b.severity === "fail" && b.y1 > b.y0).length).toBeGreaterThan(0);
  });

  it("niceTicks on an empty range still gives an axis", () => {
    const t = niceTicks(7, 7, "count");
    expect(t.hi).toBeGreaterThan(t.lo);
    expect(t.values).toContain(7);
  });

  it("a linear scale over a zero-height domain maps to the middle, never NaN", () => {
    expect(linear([5, 5], [0, 100])(5)).toBe(50);
  });

  it("time ticks over zero span and over years stay bounded", () => {
    const t0 = Date.parse(STARTED.A);
    expect(timeTicks(t0, t0).values.length).toBeLessThanOrEqual(7);
    const years = timeTicks(t0, t0 + 20 * 365 * 86_400_000);
    expect(years.values.length).toBeGreaterThan(1);
    expect(years.values.length).toBeLessThanOrEqual(50);
  });
});

// ---- series ----------------------------------------------------------------

describe("series: ties, rule round-trips and long histories", () => {
  it("A → B → A at one timestamp: two markers, both entries kept", () => {
    const t = STARTED.A;
    const entries = [
      at(0, { started_at: t, expression: CURRENT.expression }),
      at(1, { started_at: t, expression: "missing_percent(email) < 15%" }),
      at(2, { started_at: t, expression: CURRENT.expression }),
    ];
    const s = buildSeries(entries, CURRENT);
    expect(s.points.map((p) => p.index)).toEqual([2, 1, 0]);
    expect(s.ruleChanges).toHaveLength(2);
    expect(s.band).not.toBeNull();
  });

  it("an error under the current rule keeps the band's segment; an older rule behind it does not join", () => {
    const entries = [
      at(0),
      at(1, { outcome: "error", value: null, display_value: "—" }),
      at(2, { expression: "missing_percent(email) < 1%" }),
    ];
    const s = buildSeries(entries, CURRENT);
    expect(s.ruleChanges).toHaveLength(1);
    const change = s.ruleChanges[0];
    expect(s.band?.from).toBe(change?.t);
  });

  it("an entry of another metric that is also the newest: no band and a pending rule", () => {
    const entries = [
      at(0, { metric: "missing_count", unit: "count", value: 1, display_value: "1", expression: "missing_count(email) = 0" }),
      at(1),
    ];
    const s = buildSeries(entries, CURRENT);
    expect(s.band).toBeNull();
    expect(s.plotted).toHaveLength(1);
    expect(s.offAxis).toHaveLength(1);
  });

  it("a not-loaded check whose single metric has no known unit plots with plain ticks", () => {
    const entries = [at(0, { metric: "custom_metric", unit: null }), at(1, { metric: "custom_metric", unit: null })];
    const s = buildSeries(entries, null);
    expect(s.axisMetric).toBe("custom_metric");
    expect(s.axisUnit).toBeNull();
    expect(s.band).toBeNull();
  });

  it("a not-loaded check whose entries disagree on unit plots with no unit", () => {
    const entries = [at(0, { unit: "percent" }), at(1, { unit: null })];
    expect(buildSeries(entries, null).axisUnit).toBeNull();
  });

  it("201 entries: every one is placed, the line is one segment, the summary counts them all", () => {
    const entries = Array.from({ length: 201 }, (_, i) => at(i));
    const model = layoutChart({ entries, check: CURRENT, rule: expect_(cmp("<", 5)), streak: null });
    expect(model.marks).toHaveLength(201);
    expect(model.paths).toHaveLength(1);
    expect(model.xTicks.length).toBeLessThanOrEqual(7);
    const summary = chartSummary({ entries, series: model.series, rule: expect_(cmp("<", 5)), pending: false, more: true });
    expect(summary).toContain("The latest 201 results");
    expect(summary).toContain("201 fail");
  });

  it("every entry an error: no line, no plotted value, the rule is still said", () => {
    const entries = [0, 1, 2].map((i) => at(i, { outcome: "error", value: null, display_value: "—" }));
    const model = layoutChart({ entries, check: CURRENT, rule: expect_(cmp("<", 5)), streak: null });
    expect(model.paths).toEqual([]);
    expect(model.series.plotted).toEqual([]);
    expect(model.marks.every((m) => m.lane === "error")).toBe(true);
    const summary = chartSummary({ entries, series: model.series, rule: expect_(cmp("<", 5)), pending: false, more: false });
    expect(summary).toContain("3 could not evaluate");
    expect(summary).toContain("No value is plotted.");
    expect(summary).toContain("< 5");
  });
});

// ---- layout: hover columns for dense points --------------------------------

describe("hover columns", () => {
  /** The column the pointer lands on at x: hit rects are drawn in order, so the last one containing x is on top. */
  function columnUnder(model: ReturnType<typeof layoutChart>, x: number): number {
    let found = -1;
    model.columns.forEach((c, i) => {
      if (c.x0 <= x && x <= c.x1) found = i;
    });
    return found;
  }

  it("pointing at a mark shows that mark's result, even when marks are dense", () => {
    // 200 runs a minute apart: marks ~2.7 units apart on a 720-unit chart.
    const entries = Array.from({ length: 200 }, (_, i) => at(i));
    const model = layoutChart({ entries, check: CURRENT, rule: expect_(cmp("<", 5)), streak: null });
    const wrong = model.columns
      .map((c, i) => ({ i, under: columnUnder(model, c.x) }))
      .filter(({ i, under }) => i !== under);
    expect(wrong).toEqual([]);
  });

  it("columns do not overlap each other", () => {
    const entries = Array.from({ length: 30 }, (_, i) => at(i));
    const model = layoutChart({ entries, check: CURRENT, rule: expect_(cmp("<", 5)), streak: null });
    for (let i = 1; i < model.columns.length; i += 1) {
      const prev = model.columns[i - 1];
      const cur = model.columns[i];
      if (prev === undefined || cur === undefined) continue;
      expect(cur.x0).toBeGreaterThanOrEqual(prev.x1);
    }
  });

  it("sparse marks keep columns of at least 24 units, meeting at midpoints", () => {
    const entries = [at(0), at(60), at(120)];
    const model = layoutChart({ entries, check: CURRENT, rule: expect_(cmp("<", 5)), streak: null });
    for (const c of model.columns) expect(c.x1 - c.x0).toBeGreaterThanOrEqual(24);
    expect(model.columns.map((_, i) => columnUnder(model, model.columns[i]?.x ?? 0))).toEqual([0, 1, 2]);
  });
});

// ---- the route parser ------------------------------------------------------

describe("parseRoute against encodings", () => {
  it.each([
    "/checks/.",
    "/checks/%2e",
    "/checks/%2E%2E",
    "/checks/%252e%252e",
    "/checks/a%2F",
    "/checks/%2F",
    "/checks/a%00",
    "/checks/caf%C3%A9",
    "/checks/abc//",
    "/checks/abc%2F",
    "/CHECKS/abc",
    "/checks/./abc",
    "/checks/abc/..",
    `/checks/${"%61".repeat(65)}`,
    "/checks/a%5Cb",
    "/checks/a#b",
  ])("%s is page not found", (path) => {
    expect(parseRoute(path)).toEqual({ page: "not-found" });
  });

  it("64 characters spelled with escapes is still 64 characters", () => {
    expect(parseRoute(`/checks/${"%61".repeat(64)}`)).toEqual({ page: "check", id: "a".repeat(64) });
  });

  it("a colon survives checkHref and parseRoute", () => {
    const id = "sales.orders:volume";
    expect(checkHref(id)).toBe("/checks/sales.orders%3Avolume");
    expect(parseRoute(checkHref(id))).toEqual({ page: "check", id });
  });
});
