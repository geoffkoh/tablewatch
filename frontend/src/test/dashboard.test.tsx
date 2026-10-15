/**
 * The Dashboard's panels (spec 042, K-D1–K-D5): K1–K6, K11–K13, and the
 * narrow-screen CSS rule (K13). Pure logic is covered in `trend.test.ts`,
 * `stale.test.ts` and `checkChanges.test.ts`; this file is the page.
 */
import { screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { LatestResult } from "../api/types";
import { DASH_PROJECT, makeCheck, makeCheckChange, makeRun } from "./fixtures/dashboard";
import type { OverviewResponses } from "./fixtures/states";
import { ok, renderOverview, setClock, text, UNAVAILABLE } from "./render";

beforeEach(() => {
  setClock("2026-10-15T05:00:00Z");
});

afterEach(() => {
  vi.useRealTimers();
});

function latest(startedAt: string, overrides: Partial<LatestResult> = {}): LatestResult {
  return {
    run_id: "r1",
    started_at: startedAt,
    since: startedAt,
    trigger: "cli",
    outcome: "pass",
    value: 1,
    display_value: "1",
    message: null,
    last_evaluated: null,
    ...overrides,
  };
}

function base(overrides: Partial<OverviewResponses> = {}): OverviewResponses {
  return {
    project: DASH_PROJECT,
    checks: { items: [makeCheck({ id: "c1", dataset: "orders", datasource: "lake", latest: latest("2026-10-15T02:00:00Z") })], total: 1 },
    runs: { items: [makeRun({ id: "r1", started_at: "2026-10-15T02:00:00Z" })], next_cursor: null },
    ...overrides,
  };
}

function panelFor(heading: string): HTMLElement {
  const h = screen.getByRole("heading", { name: heading });
  const section = h.closest("section");
  if (section === null) throw new Error(`no section for ${heading}`);
  return section;
}

describe("K1: the trend's bars, oldest left, each labelled with its counts", () => {
  it("draws 0, 3, 1 in order, coloured by the run's own outcome", async () => {
    const runs = [
      // newest first, as `/runs` sends them
      makeRun({ id: "r-new", started_at: "2026-10-14T02:00:00Z", outcome: "fail", counts: { fail: 1, pass: 39, total: 40 } }),
      makeRun({ id: "r-mid", started_at: "2026-10-14T01:00:00Z", outcome: "error", counts: { fail: 2, error: 1, pass: 37, total: 40 } }),
      makeRun({ id: "r-old", started_at: "2026-10-14T00:00:00Z", outcome: "pass", counts: { pass: 40, total: 40 } }),
    ];
    await renderOverview(base(), { trend: ok({ items: runs, next_cursor: null }) });
    const panel = panelFor("Problems per run");
    const bars = Array.from(panel.querySelectorAll(".dashboard-trend__bar"));
    expect(bars).toHaveLength(3);
    const heightOf = (g: Element): number =>
      Number(g.querySelector("rect:not(.dashboard-trend__hit)")?.getAttribute("height") ?? "-1");
    const heights = bars.map(heightOf);
    expect(heights[0]).toBe(0); // oldest: r-old, 0 problems
    expect(heights[2]).toBeGreaterThan(0);
    expect(heights[1]).toBeGreaterThan(heights[2] ?? 0); // r-mid (3 problems) taller than r-new (1 problem)
    expect(bars.map((g) => g.getAttribute("data-outcome"))).toEqual(["pass", "error", "fail"]);
    expect(bars[1]?.getAttribute("aria-label")).toContain("2 failing, 1 in error, 37 passing");
    expect(bars.every((g) => g.closest("a") === null)).toBe(true); // no link (Runs is I-15)
  });
});

describe("K2: fewer than 2 runs", () => {
  it("reads 'Not enough runs to show a trend yet.' for a single run", async () => {
    await renderOverview(base());
    const panel = panelFor("Problems per run");
    expect(text(panel)).toContain("Not enough runs to show a trend yet.");
    expect(panel.querySelector(".dashboard-trend__bar")).toBeNull();
  });
});

describe("K3: changed recently, worded as the Alerts page", () => {
  it("shows the 5 newest with event wording, and links 'All alerts' to /alerts", async () => {
    const items = Array.from({ length: 5 }, (_, i) => ({
      check: { id: `c${String(i)}`, name: `check ${String(i)}`, dataset: "orders", datasource: "lake", state: "active" as const },
      run_id: `r${String(i)}`,
      started_at: `2026-10-1${String(5 - i)}T02:00:00.000000+00:00`,
      event: "failing" as const,
      outcome: "fail" as const,
      previous_outcome: "pass" as const,
      deliveries: null,
    }));
    await renderOverview(base(), { changed: ok({ items, next_cursor: null }) });
    const panel = panelFor("Changed recently");
    const rows = within(panel).getAllByRole("listitem");
    expect(rows).toHaveLength(5);
    expect(text(rows[0] as HTMLElement)).toContain("Started failing");
    expect(text(rows[0] as HTMLElement)).toContain("was passing");
    const link = within(panel).getByRole("link", { name: "All alerts" });
    expect(link.getAttribute("href")).toBe("/alerts");
  });

  it("reads 'No state changes recorded yet.' with none recorded", async () => {
    await renderOverview(base());
    const panel = panelFor("Changed recently");
    expect(text(panel)).toContain("No state changes recorded yet.");
  });
});

describe("K4: stale datasets, measured against the newest run", () => {
  it("lists a dataset last scanned over 24h before the newest run, not one scanned at the same time", async () => {
    const checks = {
      items: [
        makeCheck({ id: "o1", dataset: "orders", datasource: "lake", latest: latest("2026-10-14T01:00:00Z") }),
        makeCheck({ id: "c1", dataset: "customers", datasource: "lake", latest: latest("2026-10-15T02:00:00Z") }),
      ],
      total: 2,
    };
    const runs = { items: [makeRun({ id: "r1", started_at: "2026-10-15T02:00:00Z" })], next_cursor: null };
    await renderOverview(base({ checks, runs }));
    const panel = panelFor("Not scanned recently");
    expect(text(panel)).toContain("orders");
    expect(text(panel)).not.toContain("customers");
  });
});

describe("K5: never-run enabled checks, and disabled-only datasets", () => {
  it("reads 'never scanned', and leaves out the disabled-only dataset", async () => {
    const checks = {
      items: [
        makeCheck({ id: "n1", dataset: "returns", datasource: "lake", latest: null, enabled: true }),
        makeCheck({ id: "d1", dataset: "legacy", datasource: "lake", latest: null, enabled: false }),
      ],
      total: 2,
    };
    const runs = { items: [makeRun({ id: "r1", started_at: "2026-10-15T02:00:00Z" })], next_cursor: null };
    await renderOverview(base({ checks, runs }));
    const panel = panelFor("Not scanned recently");
    expect(text(panel)).toContain("returns");
    expect(text(panel)).toContain("never scanned");
    expect(text(panel)).not.toContain("legacy");
  });
});

describe("K6: no runs at all", () => {
  it("shows the stale panel's empty sentence and the trend's 'not enough runs'", async () => {
    const checks = { items: [makeCheck({ id: "n1", dataset: "returns", datasource: "lake", latest: null, enabled: true })], total: 1 };
    const runs = { items: [], next_cursor: null };
    await renderOverview(base({ checks, runs }), { trend: ok(runs) });
    expect(text(panelFor("Not scanned recently"))).toContain("Every dataset was scanned within a day of the latest run.");
    expect(text(panelFor("Problems per run"))).toContain("Not enough runs to show a trend yet.");
  });
});

describe("K11: one failed panel never hides the others", () => {
  it("shows only the changed-recently panel's own error, with Retry", async () => {
    await renderOverview(base(), { changed: UNAVAILABLE });
    const panel = panelFor("Changed recently");
    const alert = within(panel).getByRole("alert");
    expect(text(alert)).toBe("Could not load recent changes. Retry");
    expect(within(alert).getByRole("button", { name: "Retry" })).toBeTruthy();
    // The other panels, and the check table, still show.
    expect(text(panelFor("Problems per run"))).not.toMatch(/could not load/i);
    expect(text(panelFor("Not scanned recently"))).not.toMatch(/could not load/i);
    expect(text(panelFor("Check changes"))).not.toMatch(/could not load/i);
    expect(screen.getByRole("table")).toBeTruthy();
  });
});

describe("K12: markup in a name is text, never markup", () => {
  it("renders a dataset name with angle brackets as text (stale panel)", async () => {
    const checks = {
      items: [makeCheck({ id: "x1", dataset: "<b>orders</b>", datasource: "lake", latest: latest("2026-10-14T01:00:00Z") })],
      total: 1,
    };
    const runs = { items: [makeRun({ id: "r1", started_at: "2026-10-15T02:00:00Z" })], next_cursor: null };
    await renderOverview(base({ checks, runs }));
    const panel = panelFor("Not scanned recently");
    expect(panel.querySelector("b")).toBeNull();
    expect(text(panel)).toContain("<b>orders</b>");
  });

  it("renders a check name with angle brackets as text (check changes panel)", async () => {
    const checkChanges = {
      items: [makeCheckChange({ check: { id: "x", name: "<i>name</i>", dataset: "orders", datasource: "lake", state: "active" } })],
    };
    await renderOverview(base(), { checkChanges: ok(checkChanges) });
    const panel = panelFor("Check changes");
    expect(panel.querySelector("i")).toBeNull();
    expect(text(panel)).toContain("<i>name</i>");
  });
});

// ---- K13: one column under 60rem (CSS alone decides) -----------------------

const CSS = Object.values(
  import.meta.glob<string>("../styles/app.css", { query: "?raw", import: "default", eager: true }),
).join("\n");

describe("K13: panels, one column under 60rem", () => {
  it("is a two-column grid at full width", () => {
    const rule = /\.dashboard-panels\s*\{([^}]*)\}/.exec(CSS)?.[1] ?? "";
    expect(rule).toMatch(/grid-template-columns:\s*minmax\(0,\s*1fr\)\s*minmax\(0,\s*1fr\)/);
  });

  it("collapses to one column inside a 60rem media query", () => {
    const match = /@media \(max-width: 60rem\)\s*\{\s*\.dashboard-panels\s*\{([^}]*)\}/.exec(CSS);
    expect(match).not.toBeNull();
    expect(match?.[1] ?? "").toMatch(/grid-template-columns:\s*minmax\(0,\s*1fr\)\s*;/);
  });
});
