/**
 * Spec 012, check detail polish: "Current" agrees with the band (K), a result
 * with no value says so (L), `between` lines say which end they are and the
 * right labels keep their side and their distance (B), and the Source block's
 * numbers are sticky (N1). N2 is by hand (no layout in jsdom).
 */
import { screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { CheckDetail, HistoryEntry, HistoryPage, Rule } from "../api/types";
import { bands } from "../lib/chart/bands";
import { formatThreshold } from "../lib/chart/format";
import { layoutChart, type ChartModel } from "../lib/chart/layout";
import { LATEST_GAP, LINE_HEIGHT, stackLabels, type Wanted } from "../lib/chart/labels";
import { buildSeries } from "../lib/chart/series";
import CSS from "../styles/app.css?raw";
import { mapLatest } from "./fixtures/derived";
import {
  AVG_ON_NOTHING_ID,
  avgOnNothing,
  detailOf,
  edited,
  EDITED_ID,
  editedPending,
  metricChangedBack,
  page,
  recordedHistory,
  threeRules,
} from "./fixtures/detail";
import { recorded } from "./fixtures/states";
import { CLOCK, notFound, ok, renderCheck, renderOverview, rowFor, setClock, text } from "./render";

beforeEach(() => {
  setClock(CLOCK);
});

afterEach(() => {
  vi.useRealTimers();
});

function historyRows(): HTMLElement[] {
  const table = document.querySelector("table.history-table");
  if (table === null) throw new Error("no history table");
  return Array.from(table.querySelectorAll<HTMLElement>("tbody tr"));
}

/** The Rule column's text for each history row, newest first. */
function ruleCells(): string[] {
  return historyRows().map((r) => text(r.querySelectorAll("td")[4] ?? r));
}

const current = (c: CheckDetail): { metric: string; unit: CheckDetail["unit"]; expression: string } => ({
  metric: c.metric,
  unit: c.unit,
  expression: c.expression,
});

const SAME = "Same as current, before a rule change";

// ---- K: "Current" agrees with the band -----------------------------------------

describe("K1: 'Current' only where the band is", () => {
  it("metricChangedBack: N Current, C same text before a change, M and A different rules", async () => {
    await renderCheck(EDITED_ID, { check: ok(metricChangedBack.check), history: ok(metricChangedBack.history) });
    const [n, m, c, a] = ruleCells();
    expect(n).toBe("Current");
    expect(c).toBe(SAME);
    expect(m).toBe("Different rule missing_count(email) = 0");
    expect(a).toBe("Different rule missing_percent(email) < 5%");
    const cRow = historyRows()[2];
    expect(cRow?.querySelector("[data-other-rule]")).toBeNull();
    expect(text(cRow ?? document.body)).not.toContain("Current");
  });

  it("the chart is unchanged: the band starts at rule change 3 and C's mark is outside it", async () => {
    await renderCheck(EDITED_ID, { check: ok(metricChangedBack.check), history: ok(metricChangedBack.history) });
    const svg = document.querySelector("svg.chart__svg");
    const markers = Array.from(svg?.querySelectorAll(".chart__marker line") ?? []);
    const markerX = Number(markers[2]?.getAttribute("x1"));
    const band = svg?.querySelector(".chart__band--fail");
    expect(Number(band?.getAttribute("x"))).toBe(markerX);
    const cMark = svg?.querySelector('.mark[data-index="2"]');
    const cx = Number(/translate\(([\d.]+)/.exec(cMark?.getAttribute("transform") ?? "")?.[1]) + 6;
    expect(cx).toBeLessThan(markerX);
  });
});

describe("K2: one rule decides the band and 'Current'", () => {
  it.each([
    ["metricChangedBack", metricChangedBack],
    ["edited", edited],
    ["threeRules", threeRules],
  ])("%s: exactly the newest entry is in the current run", (_, f) => {
    const series = buildSeries(f.history.items, current(f.check));
    expect([...series.currentRun]).toEqual([0]);
  });

  it("a longer run: every entry of the newest run under today's text", () => {
    const [c, a] = edited.history.items;
    if (c === undefined || a === undefined) throw new Error("fixture");
    const items = [c, { ...c, run_id: "c2" }, a];
    expect([...buildSeries(items, current(edited.check)).currentRun].sort()).toEqual([0, 1]);
  });

  it("a row in the current run with another dataset keeps its Other dataset flag", async () => {
    const [c, a] = edited.history.items;
    if (c === undefined || a === undefined) throw new Error("fixture");
    const moved: HistoryEntry = { ...c, dataset: "sales.customers_v2" };
    await renderCheck(EDITED_ID, { check: ok(edited.check), history: ok(page([moved, a])) });
    const [row] = historyRows();
    expect(row?.querySelector("[data-other-dataset]")).not.toBeNull();
    expect(ruleCells()[0]).toBe("Other dataset sales.customers_v2");
  });
});

describe("K3: a pending edit", () => {
  it("edited-pending: no band, no row reads Current", async () => {
    await renderCheck(EDITED_ID, { check: ok(editedPending.check), history: ok(editedPending.history) });
    expect(document.querySelectorAll(".chart__band, .chart__boundary")).toHaveLength(0);
    const cells = ruleCells();
    expect(cells).toEqual([
      "Different rule missing_percent(email) < 15%",
      "Different rule missing_percent(email) < 5%",
    ]);
  });

  it("changed back to < 5% and not yet run: no band; C different; A same text before a change", async () => {
    const a = edited.history.items[1];
    if (a === undefined) throw new Error("fixture");
    const rule: Rule = { expect: { kind: "compare", op: "<", value: 5, text: "< 5%" }, warn: null, fail: null };
    const check: CheckDetail = { ...edited.check, expression: a.expression, name: a.expression, rule };
    await renderCheck(EDITED_ID, { check: ok(check), history: ok(edited.history) });
    expect(document.querySelectorAll(".chart__band")).toHaveLength(0);
    expect(ruleCells()).toEqual(["Different rule missing_percent(email) < 15%", SAME]);
  });
});

describe("K4: a check no longer loaded", () => {
  it("rows with the newest entry's text read 'Same as the newest'", async () => {
    await renderCheck(EDITED_ID, { check: notFound(), history: ok(metricChangedBack.history) });
    const [n, , c] = ruleCells();
    expect(n).toBe("Same as the newest");
    expect(c).toBe("Same as the newest");
  });
});

// ---- L: a result with no value says so -------------------------------------------

function latestSection(): HTMLElement {
  return screen.getByRole("region", { name: "Latest result" });
}

describe("L1: Latest result", () => {
  it("avg-on-nothing: 'No value measured' and the message, no dash, badge Fail", async () => {
    await renderCheck(AVG_ON_NOTHING_ID, { check: ok(avgOnNothing.check), history: ok(avgOnNothing.history) });
    const s = latestSection();
    expect(text(s)).toContain("No value measured");
    expect(text(s)).toContain("no non-NULL values in scope");
    expect(text(s)).not.toContain("—");
    expect(within(s).getByText("Fail")).toBeTruthy();
    expect(text(historyRows()[0] ?? document.body)).toContain("No value measured");
  });
});

describe("L2: the overview row", () => {
  it("reads 'No value measured' and the message, with no dash", async () => {
    const id = "366d9254d889c910";
    const state = mapLatest(recorded, (c) => (c.id === id ? avgOnNothing.check.latest : c.latest));
    await renderOverview(state);
    const row = rowFor(id);
    expect(text(row)).toContain("No value measured");
    expect(text(row)).toContain("no non-NULL values in scope");
    expect(text(row)).not.toContain("—");
  });
});

describe("L3: every outcome that can lack a value", () => {
  const withLatest = (fields: Partial<NonNullable<CheckDetail["latest"]>>): CheckDetail => {
    const latest = avgOnNothing.check.latest;
    if (latest === null) throw new Error("fixture");
    return { ...avgOnNothing.check, latest: { ...latest, ...fields } };
  };

  it.each(["warn", "pass"] as const)("%s with no value reads 'No value measured'", async (outcome) => {
    await renderCheck(AVG_ON_NOTHING_ID, { check: ok(withLatest({ outcome })), history: ok(avgOnNothing.history) });
    expect(text(latestSection())).toContain("No value measured");
    expect(text(latestSection())).toContain("no non-NULL values in scope");
    expect(text(latestSection())).not.toContain("—");
  });

  it("without a message, the words alone", async () => {
    await renderCheck(AVG_ON_NOTHING_ID, {
      check: ok(withLatest({ outcome: "pass", message: null })),
      history: ok(avgOnNothing.history),
    });
    expect(text(latestSection())).toContain("No value measured");
  });

  it("error still reads 'Could not evaluate' and skipped 'Skipped'", async () => {
    await renderCheck(AVG_ON_NOTHING_ID, {
      check: ok(withLatest({ outcome: "error", message: "boom" })),
      history: ok(avgOnNothing.history),
    });
    expect(text(latestSection())).toContain("Could not evaluate");
    expect(text(latestSection())).not.toContain("No value measured");
  });

  it("skipped reads 'Skipped'", async () => {
    await renderCheck(AVG_ON_NOTHING_ID, {
      check: ok(withLatest({ outcome: "skipped", message: null })),
      history: ok(avgOnNothing.history),
    });
    expect(text(latestSection())).toContain("Skipped");
    expect(text(latestSection())).not.toContain("No value measured");
  });

  it("a value null only because it was not finite keeps its display_value, in both places", async () => {
    const inf: Partial<HistoryEntry> = { outcome: "fail", value: null, display_value: "inf", message: null };
    const history: HistoryPage = page(avgOnNothing.history.items.map((e) => ({ ...e, ...inf })));
    await renderCheck(AVG_ON_NOTHING_ID, {
      check: ok(withLatest({ display_value: "inf", message: null })),
      history: ok(history),
    });
    expect(text(latestSection())).toContain("inf");
    expect(text(latestSection())).not.toContain("No value measured");
    expect(text(historyRows()[0] ?? document.body)).toContain("inf");
    expect(text(historyRows()[0] ?? document.body)).not.toContain("No value measured");
  });
});

const SOURCES = import.meta.glob<string>("../**/*.{ts,tsx}", { query: "?raw", import: "default", eager: true });
const j = (...parts: string[]): string => parts.join("");

describe("L4: one source for the words", () => {
  it("'No value measured' is written in exactly one module outside test/", () => {
    const words = j("No value ", "measured");
    const app = Object.entries(SOURCES).filter(([p]) => !p.startsWith("./"));
    expect(app.filter(([, s]) => s.includes(words)).map(([p]) => p)).toEqual(["../components/LatestResult.tsx"]);
  });

  it("the chart's own 'Fail: no value measured' is unchanged", async () => {
    await renderCheck(AVG_ON_NOTHING_ID, { check: ok(avgOnNothing.check), history: ok(avgOnNothing.history) });
    const key = screen.getByRole("list", { name: "Chart key" });
    expect(within(key).getByText("Fail: no value measured")).toBeTruthy();
  });
});

// ---- B: boundary labels ------------------------------------------------------------

const RECORDED_366 = "366d9254d889c910";
const RECORDED_CD3 = "cd3e8103b4318809";

const between = (low: number, high: number, negated = false, text = `${negated ? "not " : ""}between ${String(low)} and ${String(high)}`) =>
  ({ kind: "between", low, high, negated, text }) as const;

function modelFor(id: string, rule: Rule): ChartModel {
  const check = detailOf(recorded, id);
  return layoutChart({ entries: recordedHistory(id).items, check: current(check), rule, streak: null });
}

/** Boundary labels in ascending value of their lines (a larger y is a smaller value). */
function boundaryLabelsAscending(model: ChartModel): string[] {
  return model.lines
    .map((l, i) => ({ y: l.y, label: model.rightLabels.find((r) => r.id === `line-${String(i)}`)?.text ?? "?" }))
    .sort((a, b) => b.y - a.y)
    .map((l) => l.label);
}

const labelsOf = (model: ChartModel, kind: "boundary" | "latest" | "off-range"): string[] =>
  model.rightLabels.filter((l) => l.kind === kind).map((l) => l.text);

const B1: Rule = { expect: between(50, 60), warn: null, fail: null };
const B2: Rule = { expect: between(50, 60, true), warn: null, fail: null };

describe("B1: an inclusive between, both ends in range", () => {
  it("labels, in ascending value, are exactly >= 50 and <= 60", () => {
    expect(boundaryLabelsAscending(modelFor(RECORDED_366, B1))).toEqual([">= 50", "<= 60"]);
    expect(bands(B1, [0, 100]).lines.map((l) => [l.value, l.text])).toEqual([
      [50, ">= 50"],
      [60, "<= 60"],
    ]);
  });

  it("on the page: the labels, and the full rule above the chart", async () => {
    const check: CheckDetail = { ...detailOf(recorded, RECORDED_366), rule: B1 };
    await renderCheck(RECORDED_366, { check: ok(check), history: ok(recordedHistory(RECORDED_366)) });
    const svg = document.querySelector("svg.chart__svg");
    const labels = Array.from(svg?.querySelectorAll('[data-label="boundary"]') ?? []).map((l) => l.textContent);
    expect([...labels].sort()).toEqual(["<= 60", ">= 50"]);
    expect(text(document.querySelector(".chart__rule") ?? document.body)).toBe("Current rule: Expected between 50 and 60");
  });
});

describe("B2: not between", () => {
  it("labels are exactly < 50 and > 60", () => {
    expect(boundaryLabelsAscending(modelFor(RECORDED_366, B2))).toEqual(["< 50", "> 60"]);
  });
});

describe("B3: one end off the axis", () => {
  it("366d9254d889c910: >= 10 on the axis, 500 above", () => {
    const model = modelFor(RECORDED_366, detailOf(recorded, RECORDED_366).rule ?? B1);
    expect(labelsOf(model, "boundary")).toEqual([">= 10"]);
    expect(labelsOf(model, "off-range")).toEqual(["500 above"]);
  });

  it("cd3e8103b4318809: >= 1 on the axis, 10,000 above", () => {
    const model = modelFor(RECORDED_CD3, detailOf(recorded, RECORDED_CD3).rule ?? B1);
    expect(labelsOf(model, "boundary")).toEqual([">= 1"]);
    expect(labelsOf(model, "off-range")).toEqual(["10,000 above"]);
  });
});

describe("B4: a trigger; the colour follows the role", () => {
  it("warn between: >= 50 and <= 60 as warn lines", async () => {
    const rule: Rule = { expect: null, warn: between(50, 60), fail: null };
    expect(boundaryLabelsAscending(modelFor(RECORDED_366, rule))).toEqual([">= 50", "<= 60"]);
    const check: CheckDetail = { ...detailOf(recorded, RECORDED_366), rule };
    await renderCheck(RECORDED_366, { check: ok(check), history: ok(recordedHistory(RECORDED_366)) });
    const svg = document.querySelector("svg.chart__svg");
    expect(svg?.querySelectorAll(".chart__boundary--warn")).toHaveLength(2);
    expect(svg?.querySelectorAll(".chart__boundary--fail")).toHaveLength(0);
  });
});

describe("B5: what does not change", () => {
  it("a compare line keeps its text", () => {
    const rule: Rule = { expect: { kind: "compare", op: "<", value: 5, text: "< 5%" }, warn: null, fail: null };
    expect(bands(rule, [0, 25]).lines.map((l) => l.text)).toEqual(["< 5%"]);
  });

  it.each([false, true])("a one-line between (negated %s) keeps its text", (negated) => {
    const rule: Rule = { expect: between(5, 5, negated), warn: null, fail: null };
    expect(bands(rule, [0, 10]).lines.map((l) => l.text)).toEqual([`${negated ? "not " : ""}between 5 and 5`]);
  });
});

describe("B6: labels never round a threshold", () => {
  it("between 0.125 and 100", () => {
    const rule: Rule = { expect: between(0.125, 100), warn: null, fail: null };
    expect(bands(rule, [0, 200], (v) => formatThreshold(v, "number")).lines.map((l) => l.text)).toEqual([">= 0.125", "<= 100"]);
  });

  it("percent and duration", () => {
    const pct: Rule = { expect: between(0.5, 2, false, "between 0.5% and 2%"), warn: null, fail: null };
    expect(bands(pct, [0, 5], (v) => formatThreshold(v, "percent")).lines.map((l) => l.text)).toEqual([">= 0.5%", "<= 2%"]);
    const dur: Rule = { expect: between(3600, 86400, false, "between 1h and 1d"), warn: null, fail: null };
    expect(bands(dur, [0, 100000], (v) => formatThreshold(v, "duration")).lines.map((l) => l.text)).toEqual([">= 1h", "<= 1d"]);
  });

  it("an off-range label uses the same formatter: 0.125 below", () => {
    // Values 1000 and 1010: the axis stays near them, so 0.125 is left off it.
    const check = detailOf(recorded, RECORDED_366);
    const entries = recordedHistory(RECORDED_366).items.map((e, i) => ({
      ...e,
      value: 1000 + 10 * i,
      display_value: String(1000 + 10 * i),
    }));
    const rule: Rule = { expect: between(0.125, 1005), warn: null, fail: null };
    const model = layoutChart({ entries, check: current(check), rule, streak: null });
    expect(labelsOf(model, "off-range")).toEqual(["0.125 below"]);
    expect(labelsOf(model, "boundary")).toEqual(["<= 1,005"]);
  });

  it("formatThreshold keeps every digit the number has", () => {
    expect(formatThreshold(0.125, null)).toBe("0.125");
    expect(formatThreshold(10000, "count")).toBe("10,000");
    expect(formatThreshold(0.1, "number")).toBe("0.1");
  });
});

/** The latest label, and the latest value's mark. */
function latestOf(model: ChartModel): { label: number; mark: number } {
  const label = model.rightLabels.find((l) => l.kind === "latest");
  const newest = model.series.plotted[model.series.plotted.length - 1];
  const mark = model.marks.find((m) => m.point === newest);
  if (label === undefined || mark === undefined) throw new Error("no latest");
  return { label: label.y, mark: mark.y };
}

const B7_FIXTURES: [string, () => ChartModel][] = [
  [RECORDED_CD3, () => modelFor(RECORDED_CD3, detailOf(recorded, RECORDED_CD3).rule ?? B1)],
  [RECORDED_366, () => modelFor(RECORDED_366, detailOf(recorded, RECORDED_366).rule ?? B1)],
  ["B1", () => modelFor(RECORDED_366, B1)],
  ["B2", () => modelFor(RECORDED_366, B2)],
];

describe("B7: an off-range label sits on its side, clear of the latest value", () => {
  it("cd3e8103b4318809: 10,000 above is above 3, at least 20 apart", () => {
    const model = modelFor(RECORDED_CD3, detailOf(recorded, RECORDED_CD3).rule ?? B1);
    const above = model.rightLabels.find((l) => l.text === "10,000 above");
    const latest = model.rightLabels.find((l) => l.kind === "latest");
    expect(latest?.text).toBe("3");
    expect(above?.y).toBeLessThan(latest?.y ?? -Infinity);
    expect((latest?.y ?? 0) - (above?.y ?? 0)).toBeGreaterThanOrEqual(20);
  });

  it.each(B7_FIXTURES)("%s: sides kept; 20 from the latest label, 14 between the others", (_, make) => {
    const model = make();
    const latest = latestOf(model).label;
    for (const l of model.rightLabels) {
      if (l.kind === "latest") continue;
      expect(Math.abs(l.y - latest)).toBeGreaterThanOrEqual(LATEST_GAP);
      if (l.kind === "off-range" && l.text.endsWith(" above")) expect(l.y).toBeLessThan(latest);
      if (l.kind === "off-range" && l.text.endsWith(" below")) expect(l.y).toBeGreaterThan(latest);
    }
    const ys = model.rightLabels.map((l) => l.y).sort((a, b) => a - b);
    for (let i = 1; i < ys.length; i += 1) expect((ys[i] ?? 0) - (ys[i - 1] ?? 0)).toBeGreaterThanOrEqual(LINE_HEIGHT);
  });
});

describe("B8: the latest label stays near its mark (the four B7 fixtures)", () => {
  it.each(B7_FIXTURES)("%s: within 20 units", (_, make) => {
    const { label, mark } = latestOf(make());
    expect(Math.abs(label - mark)).toBeLessThanOrEqual(20);
  });
});

describe("the stack function: ranks and a gap per pair", () => {
  const gap = (a: Wanted, b: Wanted): number => (a.id === "latest" || b.id === "latest" ? LATEST_GAP : LINE_HEIGHT);

  it("a latest value at the top, an above label and two lines near it: order and gaps hold", () => {
    const out = stackLabels(
      [
        { id: "latest", y: 16 },
        { id: "line-0", y: 20 },
        { id: "line-1", y: 18 },
        { id: "above", y: 12, rank: -1 },
        { id: "below", y: 220, rank: 1 },
      ],
      gap,
      12,
      220,
    );
    const get = (id: string): number => out.get(id) ?? NaN;
    expect(get("above")).toBe(12);
    expect(get("latest")).toBeGreaterThanOrEqual(get("above") + LATEST_GAP);
    expect(get("line-1")).toBeGreaterThanOrEqual(get("latest") + LATEST_GAP);
    expect(get("line-0")).toBeGreaterThanOrEqual(get("line-1") + LINE_HEIGHT);
    expect(get("below")).toBe(220);
  });

  it("an above label wanted below the latest value still goes first", () => {
    const out = stackLabels(
      [
        { id: "latest", y: 12 },
        { id: "above", y: 100, rank: -1 },
      ],
      gap,
      12,
      220,
    );
    expect(out.get("above")).toBe(100);
    expect(out.get("latest")).toBe(120);
  });

  it("packed against the bottom, pairs keep their own gaps going back up", () => {
    const out = stackLabels(
      [
        { id: "a", y: 210 },
        { id: "latest", y: 214 },
        { id: "below", y: 220, rank: 1 },
      ],
      gap,
      0,
      220,
    );
    expect(out.get("below")).toBe(220);
    expect(out.get("latest")).toBe(200);
    expect(out.get("a")).toBe(180);
  });

  it("a number gap behaves as before", () => {
    const out = stackLabels(
      [
        { id: "a", y: 100 },
        { id: "b", y: 101 },
      ],
      14,
      0,
      200,
    );
    expect([out.get("a"), out.get("b")]).toEqual([100, 114]);
  });
});

// ---- N1: sticky numbers --------------------------------------------------------------

describe("N1: the numbers are sticky", () => {
  function rule(selector: string): string {
    const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const match = new RegExp(`(?:^|\\n)${escaped}\\s*\\{([^}]*)\\}`).exec(CSS);
    if (match === null) throw new Error(`no rule ${selector}`);
    return match[1] ?? "";
  }

  it("sticky at the left edge, on the block's own surface", () => {
    const numbers = rule(".code-block--lines .line::before");
    expect(numbers).toMatch(/position:\s*sticky;/);
    expect(numbers).toMatch(/(?:^|[\s;])(?:left|inset-inline-start):\s*0;/);
    const surface = /(?:^|\n)\.code-block\s*\{[^}]*background:\s*(var\(--[\w-]+\))/.exec(CSS)?.[1];
    expect(surface).toBe("var(--tw-surface)");
    expect(numbers).toContain(`background: ${surface ?? "?"};`);
    expect(numbers).toMatch(/content:\s*attr\(data-line\);/);
  });

  it("every line box is as wide as the widest line", () => {
    expect(rule(".code-block--lines > code")).toMatch(/width:\s*max-content;/);
    expect(rule(".code-block--lines > code")).toMatch(/min-width:\s*100%;/);
    expect(rule(".code-block--lines .line")).toMatch(/display:\s*block;/);
  });
});

describe("N1: the numbers stay generated content", () => {
  it("textContent is the text exactly; every child of <code> is a line span; no number is a text node", async () => {
    const { render } = await import("@testing-library/react");
    const { SourceBlock } = await import("../components/SourceBlock");
    const source = "  - invalid_count(email) = 0:\n      valid_regex: 'x'\n\n      missing_values: ['', 'N/A']";
    const { container } = render(<SourceBlock text={source} start={10} label="The check's lines" />);
    const code = container.querySelector("code");
    expect(code?.textContent).toBe(source);
    const children = Array.from(code?.childNodes ?? []);
    expect(children.every((n) => n instanceof HTMLElement && n.classList.contains("line"))).toBe(true);
    expect(code?.textContent).not.toMatch(/\b1[0-3]\b/);
  });
});
