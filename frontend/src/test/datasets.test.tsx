/**
 * The Datasets page, `/datasets` (spec 039, P-D6/P-D7, scenarios D1-D7).
 */
import { render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { CheckSummary } from "../api/types";
import { App } from "../App";
import { recorded, type OverviewResponses } from "./fixtures/states";
import { CLOCK, setClock, stubServer, text, UNAVAILABLE, URLS } from "./render";

beforeEach(() => {
  setClock(CLOCK);
});

afterEach(() => {
  vi.useRealTimers();
  window.history.replaceState(null, "", "/");
});

async function waitLoaded(): Promise<void> {
  await vi.waitFor(() => {
    if (screen.getByRole("status").textContent === "Loading…") throw new Error("still loading");
  });
}

function withChecks(base: OverviewResponses, items: CheckSummary[]): OverviewResponses {
  const next = structuredClone(base);
  next.checks = { items, total: items.length };
  next.project.counts.checks = items.length;
  return next;
}

function passResult(c: CheckSummary): CheckSummary["latest"] {
  return c.latest === null
    ? null
    : { ...c.latest, outcome: "pass", display_value: "0", value: 0, message: null, last_evaluated: null };
}

/**
 * `sales.orders` keeps `recorded`'s mix (it has a failing check);
 * `sales.customers` is made to pass throughout; `inventory.products` is made
 * entirely disabled (D1's three rows, in status order: fail, pass, disabled).
 */
function baseFixture(): OverviewResponses {
  const items = structuredClone(recorded.checks.items).map((c) => {
    if (c.dataset === "sales.customers") return { ...c, latest: passResult(c) };
    if (c.dataset === "inventory.products") return { ...c, enabled: false, state: "disabled" as const };
    return c;
  });
  return withChecks(recorded, items);
}

function renderDatasets(fixture: OverviewResponses, search = ""): ReturnType<typeof render> {
  window.history.replaceState(null, "", `/datasets${search}`);
  stubServer(fixture);
  return render(<App path="/datasets" search={search} />);
}

function rows(): HTMLElement[] {
  const table = screen.getByRole("table");
  const [, body] = within(table).getAllByRole("rowgroup");
  if (body === undefined) throw new Error("no table body");
  return within(body).getAllByRole("row");
}

function datasetNames(): string[] {
  return rows().map((r) => r.dataset.dataset ?? "?");
}

describe("D1: one row per dataset, problems first", () => {
  it("orders (fail) before customers (pass) before the disabled-only dataset", async () => {
    renderDatasets(baseFixture());
    await waitLoaded();
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Datasets");
    expect(datasetNames()).toEqual(["sales.orders", "sales.customers", "inventory.products"]);
    const disabledRow = rows().find((r) => r.dataset.dataset === "inventory.products");
    if (disabledRow === undefined) throw new Error("no row");
    expect(text(disabledRow)).toContain("Disabled");
  });
});

describe("D2: the same dataset name on two datasources", () => {
  it("is two rows, each linking to /checks?datasource=<ds>&dataset=<name>", async () => {
    const fixture = baseFixture();
    const sample = fixture.checks.items.find((c) => c.dataset === "sales.customers");
    if (sample === undefined) throw new Error("no sample");
    fixture.checks.items.push({ ...sample, id: "second-datasource-copy", datasource: "lake2", datasource_state: "defined" });
    fixture.checks.total += 1;
    renderDatasets(fixture);
    await waitLoaded();
    const matches = rows().filter((r) => r.dataset.dataset === "sales.customers");
    expect(matches).toHaveLength(2);
    const hrefs = matches.map((r) => within(r).getByRole("link").getAttribute("href")).sort();
    expect(hrefs).toEqual(
      ["/checks?datasource=lake&dataset=sales.customers", "/checks?datasource=lake2&dataset=sales.customers"].sort(),
    );
  });
});

describe("D3: following a Datasets link", () => {
  it("shows only that dataset's checks and a removable Dataset chip", async () => {
    stubServer(recorded);
    window.history.replaceState(null, "", "/checks?datasource=lake&dataset=sales.customers");
    render(<App path="/checks" search="?datasource=lake&dataset=sales.customers" />);
    await waitLoaded();
    expect(screen.getByText("Dataset: sales.customers")).toBeTruthy();
    const ids = recorded.checks.items.filter((c) => c.dataset === "sales.customers").map((c) => c.id);
    for (const id of ids) expect(document.querySelector(`[data-check-id="${id}"]`)).not.toBeNull();
    const other = recorded.checks.items.find((c) => c.dataset !== "sales.customers");
    if (other === undefined) throw new Error("no other check");
    expect(document.querySelector(`[data-check-id="${other.id}"]`)).toBeNull();

    const remove = screen.getByRole("button", { name: "Remove dataset filter: sales.customers" });
    remove.click();
    await vi.waitFor(() => {
      expect(window.location.search).not.toContain("dataset=");
    });
    expect(screen.queryByText("Dataset: sales.customers")).toBeNull();
  });
});

describe("D4: a dataset never run", () => {
  it("reads 'No result recorded' status and 'Never' for Last scanned", async () => {
    const fixture = baseFixture();
    const sample = fixture.checks.items.find((c) => c.dataset === "sales.customers");
    if (sample === undefined) throw new Error("no sample");
    fixture.checks.items.push({
      ...sample,
      id: "never-run-check",
      dataset: "sales.returns",
      datasource: "lake",
      latest: null,
    });
    fixture.checks.total += 1;
    renderDatasets(fixture);
    await waitLoaded();
    const row = rows().find((r) => r.dataset.dataset === "sales.returns");
    if (row === undefined) throw new Error("no row");
    expect(text(row)).toContain("No result recorded");
    expect(text(row)).toContain("Never");
  });
});

describe("D5: search", () => {
  it("?q=ORD matches dataset, datasource, owner or tag containing 'ord', case-insensitively", async () => {
    renderDatasets(baseFixture(), "?q=ORD");
    await waitLoaded();
    expect(datasetNames().sort()).toEqual(["sales.orders"]);
  });

  it("a hostile q creates no element", async () => {
    renderDatasets(baseFixture(), `?q=${encodeURIComponent("<img src=x onerror=alert(1)>")}`);
    await waitLoaded();
    expect(document.querySelectorAll("img").length).toBe(0);
  });
});

describe("D6: empty and failed loads", () => {
  it("no checks at all reads 'No datasets yet.'", async () => {
    renderDatasets(withChecks(recorded, []));
    await waitLoaded();
    expect(screen.getByText("No datasets yet.")).toBeTruthy();
  });

  it("a failing /checks shows the shared LoadError with Retry", async () => {
    stubServer(recorded, { checks: UNAVAILABLE });
    window.history.replaceState(null, "", "/datasets");
    render(<App path="/datasets" />);
    await waitLoaded();
    expect(screen.getByRole("alert")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Try again" })).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
  });
});

describe("D7: a hostile dataset name or owner", () => {
  it("renders as text", async () => {
    const fixture = baseFixture();
    const sample = fixture.checks.items.find((c) => c.dataset === "sales.customers");
    if (sample === undefined) throw new Error("no sample");
    const NAME = "<img src=x onerror=alert(1)>";
    fixture.checks.items.push({
      ...sample,
      id: "hostile-dataset-row",
      dataset: NAME,
      owner: NAME,
      datasource: "lake3",
    });
    fixture.checks.total += 1;
    const alert = vi.fn();
    vi.stubGlobal("alert", alert);
    renderDatasets(fixture);
    await waitLoaded();
    expect(screen.getAllByText(NAME, { exact: false }).length).toBeGreaterThan(0);
    expect(document.querySelectorAll("img, [onerror]").length).toBe(0);
    expect(alert).not.toHaveBeenCalled();
  });
});

describe("the page's own requests and title", () => {
  it("requests /checks, /project and the nav badge, and titles the page", async () => {
    const fetchMock = stubServer(recorded);
    window.history.replaceState(null, "", "/datasets");
    render(<App path="/datasets" />);
    await waitLoaded();
    const urls = fetchMock.mock.calls.map((c) => String(c[0])).sort();
    expect(urls).toEqual([URLS.checks, URLS.project, URLS.problems].sort());
    expect(document.title).toBe("Datasets — retail-example");
  });

  it("marks Datasets current in the nav", async () => {
    renderDatasets(baseFixture());
    await waitLoaded();
    const nav = screen.getByRole("navigation", { name: "Sections" });
    const current = within(nav).getByRole("link", { current: "page" });
    expect(current.textContent).toContain("Datasets");
  });
});

describe("the Checks column's wording", () => {
  it("uses the overview's Summary words, problems first", async () => {
    renderDatasets(baseFixture());
    await waitLoaded();
    const row = rows().find((r) => r.dataset.dataset === "sales.orders");
    if (row === undefined) throw new Error("no row");
    expect(text(row)).toMatch(/\d+ checks? \(.*failing/);
  });
});

describe("Owner and Tags: a gap reads as a dash", () => {
  it("shows '—' when a dataset has no owner or no tags", async () => {
    const fixture = baseFixture();
    const items = fixture.checks.items.map((c) =>
      c.dataset === "sales.orders" ? { ...c, owner: null, tags: [] } : c,
    );
    fixture.checks.items = items;
    renderDatasets(fixture);
    await waitLoaded();
    const row = rows().find((r) => r.dataset.dataset === "sales.orders");
    if (row === undefined) throw new Error("no row");
    const cells = within(row).getAllByRole("cell");
    const ownerCell = cells[cells.length - 2];
    const tagsCell = cells[cells.length - 1];
    expect(ownerCell?.textContent).toBe("—");
    expect(tagsCell?.textContent).toBe("—");
  });
});
