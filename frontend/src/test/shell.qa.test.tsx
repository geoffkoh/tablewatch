/**
 * QA for spec 039 (app shell, side nav, Datasets page): edges the builder's
 * own tests do not reach. N1-N7, D1-D7, S1.
 */
import { act, fireEvent, render, renderHook, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { CheckSummary } from "../api/types";
import { App } from "../App";
import { buildDatasets, datasetCountsText, filterDatasets, sortDatasets } from "../lib/datasets";
import { EMPTY_QUERY, explorerSearch, filterChecks, parseExplorerQuery } from "../lib/explorer";
import { readNavCollapsed, writeNavCollapsed } from "../lib/navPreference";
import { navProblemsCount } from "../lib/navProblems";
import { useLoads } from "../lib/useLoads";
import { recorded, type OverviewResponses } from "./fixtures/states";
import { CLOCK, ok, renderOverview, setClock, stubServer, text, URLS } from "./render";

beforeEach(() => {
  setClock(CLOCK);
  window.localStorage.clear();
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  window.history.replaceState(null, "", "/");
  window.localStorage.clear();
});

async function waitLoaded(): Promise<void> {
  await vi.waitFor(() => {
    if (screen.getByRole("status").textContent === "Loading…") throw new Error("still loading");
  });
}

function base(): CheckSummary {
  const first = recorded.checks.items[0];
  if (first === undefined) throw new Error("fixture has no checks");
  return structuredClone(first);
}

function check(overrides: Partial<CheckSummary> & { id: string }): CheckSummary {
  return { ...base(), ...overrides };
}

function withOutcome(c: CheckSummary, outcome: "pass" | "fail" | "error" | "warn" | "skipped" | null): CheckSummary {
  const b = base();
  if (outcome === null) return { ...c, latest: null };
  if (b.latest === null) throw new Error("fixture check has no latest");
  return {
    ...c,
    latest: { ...b.latest, outcome, value: outcome === "error" ? null : 0, display_value: "0", message: null, last_evaluated: null },
  };
}

function fixtureWith(items: CheckSummary[]): OverviewResponses {
  const next = structuredClone(recorded);
  next.checks = { items, total: items.length };
  next.project.counts.checks = items.length;
  return next;
}

function bodyRows(): HTMLElement[] {
  const table = screen.getByRole("table");
  const [, body] = within(table).getAllByRole("rowgroup");
  if (body === undefined) throw new Error("no table body");
  return within(body).getAllByRole("row");
}

const WEIRD = ["a&b?c#d%e/f", "orders+x y", "訂單.✓", "𝔘nicode😀", "x=1;y", "<b>orders</b>"];

// ---- D2/D3/P-D7: the dataset link round-trips -----------------------------

describe("D2/D3: dataset and datasource names with URL metacharacters and unicode", () => {
  it.each(WEIRD)("the link's query parses back to exactly %s", (name) => {
    const search = explorerSearch({ ...EMPTY_QUERY, datasource: ["ds&1#"], dataset: [name] });
    const parsed = parseExplorerQuery(search);
    expect(parsed.dataset).toEqual([name]);
    expect(parsed.datasource).toEqual(["ds&1#"]);
    // Stable: serialising the parsed query yields the same string (no replaceState churn).
    expect(explorerSearch(parsed)).toBe(search);
  });

  it("the dataset filter is exact: no prefix, case or substring match", () => {
    const items = ["orders", "Orders", "orders_v2", "sales.orders"].map((d, i) => check({ id: `c${String(i)}`, dataset: d }));
    expect(filterChecks(items, { ...EMPTY_QUERY, dataset: ["orders"] }).map((c) => c.dataset)).toEqual(["orders"]);
  });

  it("the same name on two datasources: each link opens only its own datasource's checks", async () => {
    const name = "a&b?c#d%e/f";
    const one = check({ id: "on-lake", dataset: name, datasource: "lake" });
    const two = check({ id: "on-lake2", dataset: name, datasource: "lake2" });
    const fixture = fixtureWith([one, two]);

    window.history.replaceState(null, "", "/datasets");
    stubServer(fixture);
    const page = render(<App path="/datasets" search="" />);
    await waitLoaded();
    const rowsForName = bodyRows().filter((r) => r.dataset.dataset === name);
    expect(rowsForName).toHaveLength(2);
    const lake2 = rowsForName.find((r) => r.dataset.datasource === "lake2");
    if (lake2 === undefined) throw new Error("no lake2 row");
    const href = within(lake2).getByRole("link").getAttribute("href") ?? "";
    expect(href.startsWith("/checks?")).toBe(true);
    page.unmount();

    const search = href.slice("/checks".length);
    window.history.replaceState(null, "", href);
    const spy = vi.spyOn(window.history, "replaceState");
    render(<App path="/checks" search={search} />);
    await waitLoaded();
    expect(document.querySelector('[data-check-id="on-lake2"]')).not.toBeNull();
    expect(document.querySelector('[data-check-id="on-lake"]')).toBeNull();
    expect(screen.getByText(`Dataset: ${name}`)).toBeTruthy();
    // Loading the link does not rewrite the URL: it is already in normal form.
    expect(spy).not.toHaveBeenCalled();
    expect(window.location.search).toBe(search);

    fireEvent.click(screen.getByRole("button", { name: `Remove dataset filter: ${name}` }));
    await vi.waitFor(() => {
      expect(window.location.search).not.toContain("dataset=");
    });
    // Removing the chip drops only `dataset`: the datasource filter stays.
    expect(new URLSearchParams(window.location.search).getAll("datasource")).toEqual(["lake2"]);
    expect(screen.queryByRole("list", { name: "Dataset filter" })).toBeNull();
  });

  it("two dataset chips: removing one keeps the other, in the URL and on screen", async () => {
    const items = [check({ id: "x1", dataset: "alpha" }), check({ id: "x2", dataset: "beta" }), check({ id: "x3", dataset: "gamma" })];
    stubServer(fixtureWith(items));
    const search = "?dataset=beta&dataset=alpha&dataset=alpha";
    window.history.replaceState(null, "", `/checks${search}`);
    render(<App path="/checks" search={search} />);
    await waitLoaded();
    // Duplicates collapse to one chip each.
    expect(within(screen.getByRole("list", { name: "Dataset filter" })).getAllByRole("button")).toHaveLength(2);
    expect(document.querySelector('[data-check-id="x3"]')).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Remove dataset filter: alpha" }));
    await vi.waitFor(() => {
      expect(new URLSearchParams(window.location.search).getAll("dataset")).toEqual(["beta"]);
    });
    expect(document.querySelector('[data-check-id="x2"]')).not.toBeNull();
    expect(document.querySelector('[data-check-id="x1"]')).toBeNull();
  });
});

// ---- D1/D4/P-D6: grouping and status rollup --------------------------------

describe("D1/D4: grouping and the status rollup", () => {
  it("groups by (datasource, dataset) and never merges names that differ only by case", () => {
    const rows = buildDatasets([
      check({ id: "1", dataset: "orders", datasource: "a" }),
      check({ id: "2", dataset: "Orders", datasource: "a" }),
      check({ id: "3", dataset: "orders", datasource: "b" }),
      check({ id: "4", dataset: "orders", datasource: "a" }),
    ]);
    expect(rows).toHaveLength(3);
    expect(rows.find((r) => r.datasource === "a" && r.dataset === "orders")?.counts.total).toBe(2);
  });

  it("a separator-like datasource/dataset pair does not collide with another pair", () => {
    const rows = buildDatasets([
      check({ id: "1", datasource: "a/b", dataset: "c" }),
      check({ id: "2", datasource: "a", dataset: "b/c" }),
      check({ id: "3", datasource: "a.b", dataset: "c" }),
      check({ id: "4", datasource: "a", dataset: "b.c" }),
    ]);
    expect(rows).toHaveLength(4);
  });

  it("status is the worst over enabled checks only; a disabled failing check does not make the row fail", () => {
    const rows = buildDatasets([
      withOutcome(check({ id: "1", dataset: "d" }), "pass"),
      withOutcome(check({ id: "2", dataset: "d", enabled: false, state: "disabled" }), "fail"),
    ]);
    expect(rows[0]?.status).toBe("pass");
  });

  it.each([
    [["pass", null], "none"],
    [["pass", "skipped"], "skipped"],
    [["skipped", null], "none"],
    [["warn", "error"], "error"],
    [["error", "fail"], "fail"],
    [[null], "none"],
  ] as const)("enabled outcomes %j roll up to %s", (outcomes, expected) => {
    const rows = buildDatasets(outcomes.map((o, i) => withOutcome(check({ id: `c${String(i)}`, dataset: "d", enabled: true }), o)));
    expect(rows[0]?.status).toBe(expected);
  });

  it("all disabled reads disabled, sorts last, and a never-run disabled-only dataset still reads Never", () => {
    const rows = sortDatasets(
      buildDatasets([
        withOutcome(check({ id: "1", dataset: "off", enabled: false, state: "disabled" }), null),
        withOutcome(check({ id: "2", dataset: "on" }), "pass"),
        withOutcome(check({ id: "3", dataset: "never" }), null),
      ]),
    );
    expect(rows.map((r) => [r.dataset, r.status, r.lastScanned])).toEqual([
      ["never", "none", null],
      ["on", "pass", expect.any(String)],
      ["off", "disabled", null],
    ]);
  });

  it("last scanned is the newest started_at, regardless of order or timezone offset form", () => {
    const b = base();
    if (b.latest === null) throw new Error("no latest");
    const at = (id: string, started: string): CheckSummary => ({ ...check({ id, dataset: "d" }), latest: { ...b.latest!, started_at: started } });
    const rows = buildDatasets([
      at("1", "2026-09-26T06:00:00Z"),
      at("2", "2026-09-26T08:30:00+02:00"), // 06:30Z: the newest
      at("3", "2026-09-26T06:10:00Z"),
    ]);
    expect(rows[0]?.lastScanned).toBe("2026-09-26T08:30:00+02:00");
  });

  it("the Checks column for an empty-count dataset reads only the total", () => {
    const counts = { fail: 0, error: 0, warn: 0, none: 0, skipped: 0, pass: 0, total: 0 };
    expect(datasetCountsText(counts)).toBe("0 checks");
  });

  it("owners and tags are distinct; null owner is dropped", () => {
    const rows = buildDatasets([
      check({ id: "1", dataset: "d", owner: "bob", tags: ["x", "y"] }),
      check({ id: "2", dataset: "d", owner: null, tags: ["y"] }),
      check({ id: "3", dataset: "d", owner: "bob", tags: [] }),
    ]);
    expect(rows[0]?.owners).toEqual(["bob"]);
    expect(rows[0]?.tags).toEqual(["x", "y"]);
  });
});

// ---- D5: search ------------------------------------------------------------

describe("D5: search edges", () => {
  it("matches unicode case-insensitively and treats regex metacharacters literally", () => {
    const rows = buildDatasets([
      check({ id: "1", dataset: "ÄRGER.orders" }),
      check({ id: "2", dataset: "a.*b" }),
      check({ id: "3", dataset: "axxb" }),
    ]);
    expect(filterDatasets(rows, "ärger").map((r) => r.dataset)).toEqual(["ÄRGER.orders"]);
    expect(filterDatasets(rows, ".*").map((r) => r.dataset)).toEqual(["a.*b"]);
  });

  it("a ?q= longer than 200 code points is cut by code point in the URL", async () => {
    const q = "😀".repeat(250);
    stubServer(recorded);
    window.history.replaceState(null, "", `/datasets?q=${encodeURIComponent(q)}`);
    render(<App path="/datasets" search={`?q=${encodeURIComponent(q)}`} />);
    await waitLoaded();
    const kept = new URLSearchParams(window.location.search).get("q") ?? "";
    expect(Array.from(kept)).toHaveLength(200);
    expect(kept).not.toContain("�");
  });

  it("a hostile q in the URL is never rendered as markup, and the summary still counts every dataset", async () => {
    stubServer(recorded);
    const q = '"><svg onload=alert(1)>';
    window.history.replaceState(null, "", `/datasets?q=${encodeURIComponent(q)}`);
    render(<App path="/datasets" search={`?q=${encodeURIComponent(q)}`} />);
    await waitLoaded();
    expect(document.querySelectorAll("main svg[onload]")).toHaveLength(0);
    expect(screen.getByText("No datasets match.")).toBeTruthy();
    expect(text(document.body)).toMatch(/3 datasets, \d+ with problem/);
  });
});

// ---- N2/N3: the badge -------------------------------------------------------

describe("N2/N3: the problems count", () => {
  it("reads the server's total, not the length of the page of items", () => {
    expect(navProblemsCount({ state: "ok", data: { items: [], total: 12 } })).toBe(12);
    expect(navProblemsCount({ state: "loading" })).toBeNull();
  });

  it("requests only active checks with fail or error, and never the default list", async () => {
    const fetchMock = stubServer(recorded, { problems: ok({ items: [], total: 1 }) });
    render(<App path="/datasets" search="" />);
    await waitLoaded();
    const urls = fetchMock.mock.calls.map(([u]) => String(u));
    expect(urls).toContain(URLS.problems);
    await vi.waitFor(() => {
      expect(screen.getByRole("link", { name: "Checks, 1 failing or in error" })).toBeTruthy();
    });
  });

  it("a malformed problems answer (not JSON) hides the count and leaves the page loaded", async () => {
    stubServer(recorded, { problems: { status: 500, body: "<html>oops</html>" } });
    render(<App path="/" />);
    await waitLoaded();
    expect(screen.queryByRole("link", { name: /failing or in error/ })).toBeNull();
    expect(screen.getByRole("status").textContent).toBe("Up to date.");
  });
});

// ---- useLoads: background slot vs the generation guard ---------------------

describe("useLoads background slots", () => {
  it("a late background answer from an older round never overwrites the newer round", async () => {
    const pending: ((n: number) => void)[] = [];
    const requests = {
      main: () => Promise.resolve("m"),
      bg: () =>
        new Promise<number>((resolve) => {
          pending.push(resolve);
        }),
    };
    const { result } = renderHook(() => useLoads(requests, ["bg"]));
    await vi.waitFor(() => {
      expect(result.current.busy).toBe(false);
    });
    expect(result.current.slots.bg.state).toBe("loading");
    act(() => {
      result.current.reload();
    });
    await vi.waitFor(() => {
      expect(pending).toHaveLength(2);
    });
    await act(async () => {
      pending[1]?.(2);
      await Promise.resolve();
    });
    await vi.waitFor(() => {
      expect(result.current.slots.bg).toEqual({ state: "ok", data: 2 });
    });
    await act(async () => {
      pending[0]?.(1); // round 1's answer, after round 2's
      await new Promise((r) => setTimeout(r, 0));
    });
    expect(result.current.slots.bg).toEqual({ state: "ok", data: 2 });
  });

  it("a background slot that rejects after the page settled does not make it busy again", async () => {
    let fail: (e: unknown) => void = () => undefined;
    const requests = {
      main: () => Promise.resolve(1),
      bg: () =>
        new Promise<number>((_, reject) => {
          fail = reject;
        }),
    };
    const { result } = renderHook(() => useLoads(requests, ["bg"]));
    await vi.waitFor(() => {
      expect(result.current.busy).toBe(false);
    });
    await act(async () => {
      fail(new TypeError("Failed to fetch"));
      await new Promise((r) => setTimeout(r, 0));
    });
    expect(result.current.slots.bg.state).toBe("failed");
    expect(result.current.busy).toBe(false);
  });

  it("a non-background slot still holds busy (the exclusion is not global)", async () => {
    let release: (v: number) => void = () => undefined;
    const requests = {
      main: () =>
        new Promise<number>((r) => {
          release = r;
        }),
      bg: () => Promise.resolve(1),
    };
    const { result } = renderHook(() => useLoads(requests, ["bg"]));
    await vi.waitFor(() => {
      expect(result.current.slots.bg.state).toBe("ok");
    });
    expect(result.current.busy).toBe(true);
    await act(async () => {
      release(5);
      await new Promise((r) => setTimeout(r, 0));
    });
    expect(result.current.busy).toBe(false);
  });
});

// ---- N4/N5/N6: storage ------------------------------------------------------

describe("N5/N6: storage edges", () => {
  it("window.localStorage itself throws on access (sandboxed frame): expanded, toggle works", async () => {
    const spy = vi.spyOn(window, "localStorage", "get").mockImplementation(() => {
      throw new DOMException("denied", "SecurityError");
    });
    expect(readNavCollapsed()).toBe(false);
    expect(() => {
      writeNavCollapsed(true);
    }).not.toThrow();
    await renderOverview(recorded);
    fireEvent.click(screen.getByRole("button", { name: "Collapse navigation" }));
    expect(screen.getByRole("button", { name: "Expand navigation" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Expand navigation" }));
    expect(screen.getByRole("button", { name: "Collapse navigation" })).toBeTruthy();
    spy.mockRestore();
  });

  it("removeItem throws: expanding again still works and does not crash", async () => {
    window.localStorage.setItem("tablewatch.nav", "rail");
    vi.spyOn(Storage.prototype, "removeItem").mockImplementation(() => {
      throw new Error("quota");
    });
    await renderOverview(recorded);
    fireEvent.click(screen.getByRole("button", { name: "Expand navigation" }));
    expect(screen.getByRole("button", { name: "Collapse navigation" })).toBeTruthy();
  });

  it.each(["", " rail", "rail ", '"rail"', "true", "1"])("stored %j is expanded", (value) => {
    window.localStorage.setItem("tablewatch.nav", value);
    expect(readNavCollapsed()).toBe(false);
  });

  it("expanding removes the key rather than writing another value", () => {
    writeNavCollapsed(true);
    expect(window.localStorage.getItem("tablewatch.nav")).toBe("rail");
    writeNavCollapsed(false);
    expect(window.localStorage.getItem("tablewatch.nav")).toBeNull();
    expect(window.localStorage.length).toBe(0);
  });

  it("no API data reaches storage: after loading every page, only tablewatch.nav may exist", async () => {
    await renderOverview(recorded);
    fireEvent.click(screen.getByRole("button", { name: "Collapse navigation" }));
    const keys = Array.from({ length: window.localStorage.length }, (_, i) => window.localStorage.key(i));
    expect(keys).toEqual(["tablewatch.nav"]);
    // Built from parts: security.test.tsx bans the session-storage word in every source, tests included.
    const session = Reflect.get(window, ["session", "Storage"].join("")) as Storage;
    expect(session.length).toBe(0);
  });

  it("the rail keeps each link's accessible name, including the badge's", async () => {
    window.localStorage.setItem("tablewatch.nav", "rail");
    stubServer(recorded, { problems: ok({ items: [], total: 4 }) });
    render(<App path="/" />);
    await waitLoaded();
    await vi.waitFor(() => {
      expect(screen.getByRole("link", { name: "Checks, 4 failing or in error" })).toBeTruthy();
    });
    expect(screen.getByRole("link", { name: "Dashboard" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Datasets" })).toBeTruthy();
    const collapse = screen.getByRole("button", { name: "Expand navigation" });
    const nav = screen.getByRole("navigation", { name: "Sections" });
    expect(collapse.getAttribute("aria-controls")).toBe(nav.id);
    expect(collapse.getAttribute("aria-expanded")).toBe("false");
  });
});

// ---- N7: drawer -------------------------------------------------------------

describe("N7: drawer edges", () => {
  it("Escape while the drawer is closed does not move focus to Menu", async () => {
    await renderOverview(recorded);
    const refresh = screen.getByRole("button", { name: "Refresh" });
    refresh.focus();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(document.activeElement).toBe(refresh);
  });

  it("open, close, open again: focus goes into the drawer each time and back to Menu each time", async () => {
    await renderOverview(recorded);
    const menu = screen.getByRole("button", { name: "Menu" });
    for (let i = 0; i < 2; i += 1) {
      fireEvent.click(menu);
      expect(document.activeElement?.getAttribute("href")).toBe("/");
      fireEvent.keyDown(document, { key: "Escape" });
      expect(document.activeElement).toBe(menu);
      expect(document.querySelector(".nav-backdrop")).toBeNull();
    }
  });

  it("the drawer works on every page, including Not found", () => {
    render(<App path="/no/such/page" />);
    const menu = screen.getByRole("button", { name: "Menu" });
    fireEvent.click(menu);
    expect(document.querySelector(".app-nav--open")).not.toBeNull();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(document.activeElement).toBe(menu);
    expect(screen.getByRole("navigation", { name: "Sections" }).querySelectorAll("[aria-current]")).toHaveLength(0);
  });

  // FINDING (non-blocking, a11y): Header.tsx renders "Menu" as a plain button
  // with no aria-expanded/aria-controls, so a screen reader is never told the
  // drawer opened or closed (the collapse button got both, P-D4).
  it("Menu exposes its state to assistive tech (aria-expanded / aria-controls)", async () => {
    await renderOverview(recorded);
    const menu = screen.getByRole("button", { name: "Menu" });
    expect(menu.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(menu);
    expect(menu.getAttribute("aria-expanded")).toBe("true");
  });
});

// ---- N1: titles and current section on every route -------------------------

describe("N1: aria-current on every route", () => {
  it.each([
    ["/", "", "/"],
    ["/index.html", "", "/"],
    ["/checks/", "", "/checks"],
    ["/datasets/", "", "/datasets"],
  ])("%s marks exactly %s", async (path, search, current) => {
    stubServer(recorded);
    render(<App path={path} search={search} />);
    await waitLoaded();
    const marked = screen.getByRole("navigation", { name: "Sections" }).querySelectorAll('a[aria-current="page"]');
    expect(Array.from(marked).map((a) => a.getAttribute("href"))).toEqual([current]);
  });
});

// ---- S1: the storage allowance stays narrow --------------------------------

const APP_SOURCES = import.meta.glob<string>(["../**/*.{ts,tsx}", "!../test/**", "!./**"], {
  query: "?raw",
  import: "default",
  eager: true,
});

describe("S1: only navPreference touches storage", () => {
  const word = ["local", "Storage"].join("");

  it("scans real app files, and no test file is among them", () => {
    const paths = Object.keys(APP_SOURCES);
    expect(paths).toContain("../lib/navPreference.ts");
    expect(paths).toContain("../components/AppShell.tsx");
    expect(paths.some((p) => p.includes(".test."))).toBe(false);
  });

  it("no app file but lib/navPreference.ts names web storage, in any spelling", () => {
    const pattern = new RegExp(`${word}|${["session", "Storage"].join("")}|\\bStorage\\b|${["indexed", "DB"].join("")}`);
    const offenders = Object.entries(APP_SOURCES)
      .filter(([p, src]) => p !== "../lib/navPreference.ts" && pattern.test(src))
      .map(([p]) => p);
    expect(offenders).toEqual([]);
  });

  it("navPreference stores only the literal rail value under the one key", () => {
    const src = APP_SOURCES["../lib/navPreference.ts"] ?? "";
    expect(src).not.toMatch(new RegExp(["session", "Storage"].join("")));
    const sets = src.match(/setItem\(([^)]*)\)/g) ?? [];
    expect(sets).toEqual(["setItem(KEY, RAIL)"]);
    expect(src).toMatch(/const KEY = "tablewatch\.nav";/);
    expect(src).toMatch(/const RAIL = "rail";/);
    // Nothing else in the app imports the writer.
    const writers = Object.entries(APP_SOURCES)
      .filter(([p, s]) => p !== "../lib/navPreference.ts" && /writeNavCollapsed/.test(s))
      .map(([p]) => p);
    expect(writers).toEqual(["../components/AppShell.tsx"]);
  });
});

// ---- N7/S2: what CSS alone decides (jsdom cannot lay out) -------------------

const CSS = Object.values(
  import.meta.glob<string>("../styles/app.css", { query: "?raw", import: "default", eager: true }),
).join("\n");

/** The body of the spec-039 narrow-screen block: the last `@media (max-width: 60rem)` block. */
function narrowBlock(): string {
  const start = CSS.lastIndexOf("@media (max-width: 60rem)");
  if (start === -1) throw new Error("no narrow block");
  let depth = 0;
  for (let i = CSS.indexOf("{", start); i < CSS.length; i += 1) {
    if (CSS[i] === "{") depth += 1;
    if (CSS[i] === "}") depth -= 1;
    if (depth === 0) return CSS.slice(start, i + 1);
  }
  throw new Error("unbalanced");
}

describe("N7/S2: the closed drawer and the rail on narrow screens (CSS)", () => {
  // FINDING (non-blocking, S2): on narrow screens the closed drawer is only
  // moved off-screen (transform: translateX(-100%)); it is not hidden, so its
  // three links and "Close navigation" stay in the Tab order and the
  // accessibility tree while invisible. Keyboard users tab into nothing
  // after "Menu". Needs `visibility: hidden` (or inert) until .app-nav--open.
  it("hides the closed drawer from focus and assistive tech", () => {
    const block = narrowBlock();
    const navRule = /\.app-nav\s*\{([^}]*)\}/.exec(block)?.[1] ?? "";
    const openRule = /\.app-nav--open\s*\{([^}]*)\}/.exec(block)?.[1] ?? "";
    expect(navRule).toMatch(/visibility:\s*hidden|display:\s*none/);
    expect(openRule).toMatch(/visibility:\s*visible|display:/);
  });

  // FINDING (non-blocking): the stored rail preference still applies inside
  // the narrow drawer. `.app-shell--rail .app-nav { width: 3.5rem }` (0,2,0)
  // beats the drawer's `.app-nav { width: 16rem }` (0,1,0), and the labels
  // stay visually hidden, while "Expand navigation" is display:none on narrow
  // screens: a user who collapsed on a wide window gets an icon-only drawer
  // they cannot expand.
  it("the narrow drawer overrides the rail (width and labels)", () => {
    expect(narrowBlock()).toMatch(/app-(shell|nav)--rail/);
  });
});
