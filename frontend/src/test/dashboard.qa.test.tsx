/**
 * QA for spec 042's Dashboard panels: stale-panel edges, trend edges, every
 * panel's failure isolation, markup as text in every panel, and the Datasets
 * page after the `lib/datasets.ts` refactor.
 */
import { fireEvent, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { CheckListItem, LatestResult, Run } from "../api/types";
import { checkChangeText } from "../lib/checkChanges";
import { buildDatasets, datasetHref } from "../lib/datasets";
import { staleDatasets } from "../lib/stale";
import {
  buildTrendBars,
  hasTrend,
  layoutTrendBars,
  trendRunLabel,
} from "../lib/trend";
import {
  DASH_PROJECT,
  makeCheck,
  makeCheckChange,
  makeCheckRef,
  makeRun,
} from "./fixtures/dashboard";
import type { OverviewResponses } from "./fixtures/states";
import { ok, renderOverview, setClock, text, UNAVAILABLE } from "./render";

function latest(startedAt: string): LatestResult {
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
  };
}

const NEWEST = makeRun({ started_at: "2026-10-15T02:00:00Z" });

describe("stale: edges", () => {
  it("compares instants, not strings, across UTC offsets", () => {
    // 2026-10-14T09:00+08:00 is 01:00Z: 25 hours before the run, stale.
    const offset = makeCheck({
      dataset: "a",
      latest: latest("2026-10-14T09:00:00.000000+08:00"),
    });
    // 2026-10-14T21:00-05:00 is 02:00Z on the 15th: fresh.
    const west = makeCheck({
      dataset: "b",
      latest: latest("2026-10-14T21:00:00-05:00"),
    });
    expect(staleDatasets([offset, west], NEWEST).map((r) => r.dataset)).toEqual(
      ["a"],
    );
  });

  it("one millisecond over 24 hours is stale, exactly 24 hours is not", () => {
    const exact = makeCheck({
      dataset: "exact",
      latest: latest("2026-10-14T02:00:00.000Z"),
    });
    const over = makeCheck({
      dataset: "over",
      latest: latest("2026-10-14T01:59:59.999Z"),
    });
    expect(staleDatasets([exact, over], NEWEST).map((r) => r.dataset)).toEqual([
      "over",
    ]);
  });

  it("ignores a disabled check's newer scan: only enabled checks count", () => {
    const old = makeCheck({
      dataset: "orders",
      latest: latest("2026-10-13T00:00:00Z"),
    });
    const off = makeCheck({
      dataset: "orders",
      enabled: false,
      latest: latest("2026-10-15T02:00:00Z"),
    });
    const rows = staleDatasets([old, off], NEWEST);
    expect(rows).toEqual([
      {
        dataset: "orders",
        datasource: "lake",
        lastScanned: "2026-10-13T00:00:00Z",
      },
    ]);
  });

  it("a dataset with one enabled check never run and one recent is not stale", () => {
    const never = makeCheck({ dataset: "orders", latest: null });
    const fresh = makeCheck({
      dataset: "orders",
      latest: latest("2026-10-15T02:00:00Z"),
    });
    expect(staleDatasets([never, fresh], NEWEST)).toEqual([]);
  });

  it("a scan newer than the newest run is never stale", () => {
    const ahead = makeCheck({
      dataset: "orders",
      latest: latest("2026-10-16T02:00:00Z"),
    });
    expect(staleDatasets([ahead], NEWEST)).toEqual([]);
  });

  it("the same dataset name on two datasources is two rows; never scanned first, then oldest", () => {
    const checks = [
      makeCheck({
        dataset: "orders",
        datasource: "lake",
        latest: latest("2026-10-13T00:00:00Z"),
      }),
      makeCheck({
        dataset: "orders",
        datasource: "wh",
        latest: latest("2026-10-10T00:00:00Z"),
      }),
      makeCheck({ dataset: "orders", datasource: "pg", latest: null }),
      makeCheck({
        dataset: "orders",
        datasource: "fresh",
        latest: latest("2026-10-15T01:00:00Z"),
      }),
    ];
    expect(staleDatasets(checks, NEWEST).map((r) => r.datasource)).toEqual([
      "pg",
      "wh",
      "lake",
    ]);
  });

  it("an unparseable newest run flags nothing", () => {
    const run = makeRun({ started_at: "not a time" });
    expect(staleDatasets([makeCheck({ latest: null })], run)).toEqual([]);
  });
});

describe("trend: edges", () => {
  it("an errors-only run's bar is its error count", () => {
    const run = makeRun({
      outcome: "error",
      counts: { pass: 0, error: 4, total: 4 },
    });
    const [bar] = buildTrendBars([run]);
    expect(bar?.problems).toBe(4);
    expect(bar?.label).toMatch(/: 4 in error$/);
  });

  it("a run with no counts at all draws a zero bar and a sane label", () => {
    const zero = makeRun({ id: "z", counts: { total: 0, pass: 0 } });
    const other = makeRun({ id: "o", counts: { total: 0, pass: 0 } });
    expect(trendRunLabel(zero)).toMatch(/: 0 checks$/);
    const laid = layoutTrendBars(buildTrendBars([zero, other]), 320, 72);
    for (const b of laid) {
      expect(b.height).toBe(0);
      expect(b.y).toBe(72);
      expect(Number.isFinite(b.x) && Number.isFinite(b.width)).toBe(true);
    }
  });

  it("30 runs fit the plot, evenly spaced, oldest left", () => {
    const runs: Run[] = Array.from({ length: 30 }, (_, i) =>
      makeRun({
        id: `r${String(i)}`,
        // newest first, as `/runs` sends them
        started_at: new Date(
          Date.UTC(2026, 9, 15) - i * 3_600_000,
        ).toISOString(),
        counts: { fail: i, total: 40, pass: 40 - i },
      }),
    );
    expect(hasTrend(runs)).toBe(true);
    const laid = layoutTrendBars(buildTrendBars(runs), 320, 72);
    expect(laid).toHaveLength(30);
    expect(laid[0]?.key).toBe("r29");
    expect(laid[29]?.key).toBe("r0");
    for (const b of laid) {
      expect(b.x).toBeGreaterThanOrEqual(0);
      expect(b.x + b.width).toBeLessThanOrEqual(320);
      expect(b.height).toBeGreaterThanOrEqual(0);
      expect(b.height).toBeLessThanOrEqual(72);
    }
    // The tallest is the oldest (29 failing), at full height.
    expect(laid[0]?.height).toBe(72);
  });

  it("a slow-but-zero history is not drawn as a problem", () => {
    const runs = [makeRun({ id: "a" }), makeRun({ id: "b" })];
    expect(
      layoutTrendBars(buildTrendBars(runs), 320, 72).every(
        (b) => b.height === 0,
      ),
    ).toBe(true);
  });
});

describe("check changes: wording", () => {
  it("words every kind as K-D4", () => {
    const kinds = [
      [makeCheckChange({ kind: "added" }), "Added"],
      [
        makeCheckChange({ kind: "redefined", version: 3 }),
        "Definition changed (version 3)",
      ],
      [makeCheckChange({ kind: "disabled" }), "Disabled"],
      [makeCheckChange({ kind: "retired" }), "Retired"],
      [makeCheckChange({ kind: "enabled" }), "Enabled again"],
    ] as const;
    for (const [change, words] of kinds)
      expect(checkChangeText(change)).toBe(words);
  });
});

describe("Datasets after the refactor", () => {
  it("datasetHref still filters the explorer by both datasource and dataset", () => {
    const href = datasetHref("lake & co", "sales.orders");
    const url = new URL(href, "http://x");
    expect(url.searchParams.getAll("datasource")).toEqual(["lake & co"]);
    expect(url.searchParams.getAll("dataset")).toEqual(["sales.orders"]);
  });

  it("buildDatasets still groups by (datasource, dataset) with last scanned over every check", () => {
    const rows = buildDatasets([
      makeCheck({
        dataset: "orders",
        datasource: "lake",
        latest: latest("2026-10-13T00:00:00Z"),
      }),
      makeCheck({
        dataset: "orders",
        datasource: "lake",
        enabled: false,
        latest: latest("2026-10-15T00:00:00Z"),
      }),
      makeCheck({ dataset: "orders", datasource: "wh", latest: null }),
    ]);
    expect(rows).toHaveLength(2);
    const lake = rows.find((r) => r.datasource === "lake");
    expect(lake?.lastScanned).toBe("2026-10-15T00:00:00Z");
  });
});

// ---- the page --------------------------------------------------------------

function base(overrides: Partial<OverviewResponses> = {}): OverviewResponses {
  return {
    project: DASH_PROJECT,
    checks: {
      items: [
        makeCheck({
          id: "c1",
          dataset: "orders",
          latest: latest("2026-10-15T02:00:00Z"),
        }),
      ],
      total: 1,
    },
    runs: {
      items: [makeRun({ id: "r1", started_at: "2026-10-15T02:00:00Z" })],
      next_cursor: null,
    },
    ...overrides,
  };
}

function panelFor(heading: string): HTMLElement {
  const section = screen
    .getByRole("heading", { name: heading })
    .closest("section");
  if (section === null) throw new Error(`no section for ${heading}`);
  return section;
}

describe("page: failure isolation (K-D5)", () => {
  beforeEach(() => {
    setClock("2026-10-15T05:00:00Z");
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("all three requested panels failing still shows the stale panel and the check table", async () => {
    await renderOverview(base(), {
      trend: UNAVAILABLE,
      changed: "network-error",
      checkChanges: UNAVAILABLE,
    });
    expect(text(within(panelFor("Problems per run")).getByRole("alert"))).toBe(
      "Could not load the trend. Retry",
    );
    expect(text(within(panelFor("Changed recently")).getByRole("alert"))).toBe(
      "Could not load recent changes. Retry",
    );
    expect(text(within(panelFor("Check changes")).getByRole("alert"))).toBe(
      "Could not load check changes. Retry",
    );
    expect(text(panelFor("Not scanned recently"))).toContain(
      "Every dataset was scanned",
    );
    expect(screen.getByRole("table")).toBeTruthy();
    expect(screen.queryByRole("link", { name: "All alerts" })).toBeNull();
  });

  it("a panel's Retry recovers it and keeps the check table", async () => {
    const fetchMock =
      (await renderOverview(base(), { checkChanges: UNAVAILABLE }),
      vi.mocked(fetch));
    const original = fetchMock.getMockImplementation();
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url =
        typeof input === "string"
          ? input
          : input instanceof URL
            ? input.href
            : input.url;
      if (url === "/api/v1/check-changes?limit=5") {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              items: [
                makeCheckChange({
                  kind: "retired",
                  check: makeCheckRef({ state: "retired" }),
                }),
              ],
            }),
            {
              status: 200,
              headers: { "Content-Type": "application/json" },
            },
          ),
        );
      }
      if (original === undefined) throw new Error("no fetch");
      return original(input);
    });
    fireEvent.click(
      within(panelFor("Check changes")).getByRole("button", { name: "Retry" }),
    );
    await vi.waitFor(() => {
      expect(within(panelFor("Check changes")).queryByRole("alert")).toBeNull();
    });
    const row = within(panelFor("Check changes")).getByRole("listitem");
    expect(text(row)).toContain("Retired");
    expect(screen.getByRole("table")).toBeTruthy();
  });

  it("a malformed panel body never hides the check table", async () => {
    await renderOverview(base(), {
      checkChanges: { status: 500, body: "<html>oops</html>" },
    });
    expect(within(panelFor("Check changes")).getByRole("alert")).toBeTruthy();
    expect(screen.getByRole("table")).toBeTruthy();
  });
});

describe("page: markup is text in every panel (K12)", () => {
  beforeEach(() => {
    setClock("2026-10-15T05:00:00Z");
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("changed recently and check changes render names as text; links stay check links", async () => {
    const evil = "<img src=x onerror=alert(1)>";
    const alerts = {
      items: [
        {
          check: {
            id: "a/b?c",
            name: evil,
            dataset: "<b>d</b>",
            datasource: "lake",
            state: "retired" as const,
          },
          run_id: "r1",
          started_at: "2026-10-15T02:00:00Z",
          event: "failing" as const,
          outcome: "fail" as const,
          previous_outcome: null,
          deliveries: null,
        },
      ],
      next_cursor: null,
    };
    const changes = {
      items: [
        makeCheckChange({ check: makeCheckRef({ id: "x y", name: evil }) }),
      ],
    };
    await renderOverview(base(), {
      changed: ok(alerts),
      checkChanges: ok(changes),
    });
    for (const heading of ["Changed recently", "Check changes"]) {
      const panel = panelFor(heading);
      expect(panel.querySelector("img")).toBeNull();
      expect(text(panel)).toContain(evil);
    }
    const changedLink = within(panelFor("Changed recently")).getByRole("link", {
      name: evil,
    });
    expect(changedLink.getAttribute("href")).toBe(
      `/checks/${encodeURIComponent("a/b?c")}`,
    );
    expect(text(panelFor("Changed recently"))).toMatch(/retired/i);
  });

  it("a stale dataset link names the dataset and datasource", async () => {
    const checks = {
      items: [
        makeCheck({
          id: "s",
          dataset: 'ünïcode "q"',
          datasource: "lake",
          latest: latest("2026-10-13T00:00:00Z"),
        }),
      ],
      total: 1,
    };
    await renderOverview(base({ checks }));
    const link = within(panelFor("Not scanned recently")).getByRole("link");
    expect(text(link)).toBe('ünïcode "q" · lake');
    expect(link.getAttribute("href")).toBe(datasetHref("lake", 'ünïcode "q"'));
  });

  it("a retired check never makes its dataset stale (retired checks are not loaded)", async () => {
    const checks = {
      items: [
        makeCheck({
          id: "live",
          dataset: "orders",
          latest: latest("2026-10-15T02:00:00Z"),
        }),
        // A retired item as `/checks` sends it is a different shape; only `state` matters here.
        {
          ...makeCheck({
            id: "gone",
            dataset: "old_table",
            latest: latest("2026-09-01T00:00:00Z"),
          }),
          state: "retired",
        } as unknown as CheckListItem,
      ],
      total: 2,
    } as unknown as OverviewResponses["checks"];
    await renderOverview(base({ checks }));
    expect(text(panelFor("Not scanned recently"))).not.toContain("old_table");
  });
});

describe("trend: per-bar labels reach assistive technology (K-D1)", () => {
  beforeEach(() => {
    setClock("2026-10-15T05:00:00Z");
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  // ARIA makes an `img`'s descendants presentational: the per-bar
  // `aria-label`s (and their tabIndex=0 focus stops) inside `<svg role="img">`
  // are never announced, so K-D1's per-run accessible label is lost.
  // TrendPanel.tsx:29 needs a role that keeps children, or a hidden list.
  it.fails("no labelled bar sits inside a role=img", async () => {
    const runs = [
      makeRun({ id: "b", started_at: "2026-10-15T02:00:00Z" }),
      makeRun({ id: "a", started_at: "2026-10-14T02:00:00Z" }),
    ];
    await renderOverview(base(), {
      trend: ok({ items: runs, next_cursor: null }),
    });
    const img = within(panelFor("Problems per run")).getByRole("img");
    expect(img.querySelectorAll("[aria-label]")).toHaveLength(0);
  });
});
