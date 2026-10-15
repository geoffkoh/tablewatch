/**
 * "Problems per run" (spec 042 K-D1), pure parts: K1, K2.
 */
import { describe, expect, it } from "vitest";
import { buildTrendBars, hasTrend, layoutTrendBars, runCountsText, trendRunLabel } from "../lib/trend";
import { makeRun } from "./fixtures/dashboard";

describe("K1: one bar per run, oldest left, labelled with its counts", () => {
  // The test environment's TZ is fixed to Asia/Singapore (UTC+8, vite.config.ts).
  const runs = [
    makeRun({ id: "r3", started_at: "2026-10-14T02:00:00Z", outcome: "fail", counts: { fail: 1, pass: 39, total: 40 } }),
    makeRun({ id: "r2", started_at: "2026-10-14T01:00:00Z", outcome: "fail", counts: { fail: 2, error: 1, pass: 37, total: 40 } }),
    makeRun({ id: "r1", started_at: "2026-10-14T00:00:00Z", outcome: "pass", counts: { pass: 40, total: 40 } }),
  ];

  it("reverses the API's newest-first order to oldest left", () => {
    const bars = buildTrendBars(runs);
    expect(bars.map((b) => b.key)).toEqual(["r1", "r2", "r3"]);
  });

  it("heights are fail + error: 0, 3, 1", () => {
    const bars = buildTrendBars(runs);
    expect(bars.map((b) => b.problems)).toEqual([0, 3, 1]);
  });

  it("colours each bar by the run's own outcome", () => {
    const bars = buildTrendBars(runs);
    expect(bars.map((b) => b.outcome)).toEqual(["pass", "fail", "fail"]);
  });

  it("labels each bar with its exact counts", () => {
    const bars = buildTrendBars(runs);
    expect(bars[0]?.label).toBe("Run of 14 Oct 08:00: 40 passing");
    expect(bars[1]?.label).toBe("Run of 14 Oct 09:00: 2 failing, 1 in error, 37 passing");
    expect(bars[2]?.label).toBe("Run of 14 Oct 10:00: 1 failing, 39 passing");
  });

  it("scales bar heights proportionally to the layout's plot height", () => {
    const bars = buildTrendBars(runs);
    const laid = layoutTrendBars(bars, 300, 90);
    expect(laid.map((b) => b.height)).toEqual([0, 90, 30]);
    expect(laid.every((b) => b.height >= 0)).toBe(true);
  });
});

describe("K2: fewer than 2 runs", () => {
  it("is not enough for a trend with one run", () => {
    expect(hasTrend([makeRun()])).toBe(false);
  });

  it("is not enough with no runs at all (K6)", () => {
    expect(hasTrend([])).toBe(false);
  });

  it("is enough with two runs", () => {
    expect(hasTrend([makeRun({ id: "a" }), makeRun({ id: "b" })])).toBe(true);
  });
});

describe("runCountsText", () => {
  it("lists only non-zero counts, problems first", () => {
    expect(runCountsText({ fail: 3, error: 1, warn: 0, pass: 40, skipped: 0, total: 44 })).toBe(
      "3 failing, 1 in error, 40 passing",
    );
  });

  it("singular warning", () => {
    expect(runCountsText({ fail: 0, error: 0, warn: 1, pass: 2, skipped: 0, total: 3 })).toBe("1 warning, 2 passing");
  });

  it("reads '0 checks' for an empty run", () => {
    expect(runCountsText({ fail: 0, error: 0, warn: 0, pass: 0, skipped: 0, total: 0 })).toBe("0 checks");
  });
});

describe("trendRunLabel", () => {
  it("falls back to 'an unknown time' for an unparsable timestamp", () => {
    expect(trendRunLabel(makeRun({ started_at: "not-a-time" }))).toBe("Run of an unknown time: 1 passing");
  });
});
