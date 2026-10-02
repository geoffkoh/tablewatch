/**
 * The explorer's tag, owner and datasource filters, scenario by scenario
 * (spec 016, F1–F16). F17 (docs) is checked in review: Vite denies `?raw`
 * imports outside frontend/.
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { CheckSummary } from "../api/types";
import { App } from "../App";
import { ExplorerTree } from "../components/ExplorerTree";
import { FacetFilter } from "../components/FacetFilter";
import {
  buildTree,
  commonFolder,
  EMPTY_QUERY,
  explorerSearch,
  FACET_KEYS,
  facetOptions,
  filterChecks,
  parseExplorerQuery,
} from "../lib/explorer";
import { recorded, type OverviewResponses } from "./fixtures/states";
import { CLOCK, setClock, stubServer, text } from "./render";

beforeEach(() => {
  setClock(CLOCK);
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  window.history.replaceState(null, "", "/");
});

// ---- helpers -------------------------------------------------------------------

async function open(fixture: OverviewResponses, search = ""): Promise<{ unmount: () => void }> {
  window.history.replaceState(null, "", `/checks${search}`);
  stubServer(fixture);
  const result = render(<App path="/checks" search={search} />);
  await vi.waitFor(() => {
    if (screen.getByRole("status").textContent === "Loading…") throw new Error("still loading");
  });
  return result;
}

function shownIds(): string[] {
  return [...document.querySelectorAll<HTMLElement>(".tree__check")].map((li) => li.dataset.checkId ?? "?");
}

function url(): string {
  return `${window.location.pathname}${window.location.search}`;
}

function group(name: string): HTMLElement {
  return screen.getByRole("group", { name });
}

/** A fieldset's checkboxes as their labels read, in order. */
function labels(name: string): string[] {
  return within(group(name))
    .getAllByRole("checkbox")
    .map((c) => text(c.closest("label") ?? c));
}

function box(name: string, label: string): HTMLInputElement {
  return within(group(name)).getByRole<HTMLInputElement>("checkbox", { name: label });
}

function showing(): string {
  return text(document.querySelector(".explorer__showing") ?? document.body);
}

const ids = (pred: (c: CheckSummary) => boolean): string[] =>
  recorded.checks.items.filter(pred).map((c) => c.id);

const inFile = (file: string): ((c: CheckSummary) => boolean) => (c) => c.location.file === `checks/${file}`;

function mapChecks(base: OverviewResponses, fn: (c: CheckSummary, i: number) => CheckSummary): OverviewResponses {
  const next = structuredClone(base);
  next.checks.items = next.checks.items.map(fn);
  return next;
}

// ---- F1–F2 --------------------------------------------------------------------

describe("F1: the filters on recorded", () => {
  it("lists Tag and Owner after Status with counts, and no Datasource", async () => {
    await open(recorded);
    const legends = [...document.querySelectorAll("fieldset > legend")].map((l) => l.textContent);
    expect(legends).toEqual(["Status", "Tag", "Owner"]);
    expect(labels("Tag")).toEqual(["catalogue 4", "example 18", "sales 14", "tier-1 14"]);
    expect(labels("Owner")).toEqual(["data-platform@example.com 4", "sales-data@example.com 14"]);
    expect(screen.queryByRole("group", { name: "Datasource" })).toBeNull();
    expect(within(group("Tag")).getAllByRole("checkbox").every((c) => !(c as HTMLInputElement).checked)).toBe(true);
  });
});

describe("F2: value order and rendering", () => {
  const mixed = mapChecks(recorded, (c, i) => ({
    ...c,
    tags: i === 0 ? [] : i % 3 === 0 ? ["beta"] : i % 3 === 1 ? ["Alpha", "gamma"] : ["alpha2", "<b>x</b>"],
  }));

  it("sorts by name without case, the none value last", async () => {
    await open(mixed);
    expect(labels("Tag").map((l) => l.replace(/ \d+$/, ""))).toEqual([
      "<b>x</b>",
      "Alpha",
      "alpha2",
      "beta",
      "gamma",
      "No tags",
    ]);
  });

  it("renders values as text, never markup or an href", async () => {
    await open(mixed);
    expect(document.querySelector("fieldset b")).toBeNull();
    expect(within(group("Tag")).queryAllByRole("link")).toHaveLength(0);
  });
});

// ---- F3–F6 --------------------------------------------------------------------

describe("F3: tick one tag", () => {
  it("shows only its checks and rewrites the URL in place", async () => {
    const push = vi.spyOn(window.history, "pushState");
    const replace = vi.spyOn(window.history, "replaceState");
    await open(recorded);
    fireEvent.click(box("Tag", "catalogue 4"));
    expect(shownIds()).toEqual(ids(inFile("inventory/products.yml")));
    expect(url()).toBe("/checks?tag=catalogue");
    expect(replace).toHaveBeenCalled();
    expect(push).not.toHaveBeenCalled();
  });
});

describe("F4: values in one filter combine with OR", () => {
  it("catalogue or tier-1 shows all 18", async () => {
    await open(recorded);
    fireEvent.click(box("Tag", "catalogue 4"));
    fireEvent.click(box("Tag", "tier-1 14"));
    expect(shownIds()).toHaveLength(18);
    expect(url()).toBe("/checks?tag=catalogue&tag=tier-1");
  });
});

describe("F5: filters combine with AND", () => {
  it("Fail and owner sales-data gives 6, and the search narrows further", async () => {
    await open(recorded);
    fireEvent.click(screen.getByRole("checkbox", { name: "Fail 6" }));
    fireEvent.click(box("Owner", "sales-data@example.com 6"));
    expect(shownIds().sort()).toEqual(
      ids((c) => c.owner === "sales-data@example.com" && c.latest?.outcome === "fail").sort(),
    );
    expect(shownIds()).toHaveLength(6);
    expect(url()).toBe("/checks?status=fail&owner=sales-data%40example.com");
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "customers" } });
    expect(shownIds()).toHaveLength(2);
  });
});

describe("F6: each count follows the search and every other filter", () => {
  it("Owner counts follow Status; a 0 stays listed", async () => {
    await open(recorded);
    fireEvent.click(screen.getByRole("checkbox", { name: "Fail 6" }));
    expect(labels("Owner")).toEqual(["data-platform@example.com 0", "sales-data@example.com 6"]);
    expect(labels("Tag")).toEqual(["catalogue 0", "example 6", "sales 6", "tier-1 6"]);
  });

  it("Status counts follow the tag filter; a filter's own counts ignore it", async () => {
    await open(recorded);
    fireEvent.click(box("Tag", "catalogue 4"));
    expect(labels("Status")).toEqual(["Fail 0", "Warn 1", "Pass 3"]);
    expect(labels("Tag")).toEqual(["catalogue 4", "example 18", "sales 14", "tier-1 14"]);
    expect(labels("Owner")).toEqual(["data-platform@example.com 4", "sales-data@example.com 0"]);
  });

  it("counts a check with two selected tags once per value", () => {
    const options = facetOptions(recorded.checks.items, { ...EMPTY_QUERY, tag: ["sales", "tier-1"] }, "tag");
    expect(options.map((o) => [o.value, o.count, o.checked])).toEqual([
      ["catalogue", 4, false],
      ["example", 18, false],
      ["sales", 14, true],
      ["tier-1", 14, true],
    ]);
  });
});

// ---- F7–F9 --------------------------------------------------------------------

describe("F7: no owner and no tags", () => {
  const unowned = mapChecks(recorded, (c) =>
    c.dataset === "inventory.products" ? { ...c, owner: null, tags: [] } : c,
  );

  it("adds 'No owner' and 'No tags' only when some check has them", async () => {
    await open(unowned);
    expect(labels("Owner")).toEqual(["sales-data@example.com 14", "No owner 4"]);
    expect(labels("Tag")).toEqual(["example 14", "sales 14", "tier-1 14", "No tags 4"]);
    fireEvent.click(box("Owner", "No owner 4"));
    expect(shownIds()).toEqual(ids(inFile("inventory/products.yml")));
    expect(url()).toBe("/checks?owner=");
    fireEvent.click(box("Tag", "No tags 4"));
    expect(url()).toBe("/checks?tag=&owner=");
    expect(shownIds()).toHaveLength(4);
  });

  it("recorded has neither", async () => {
    await open(recorded);
    expect(screen.queryByRole("checkbox", { name: /^No owner/ })).toBeNull();
    expect(screen.queryByRole("checkbox", { name: /^No tags/ })).toBeNull();
  });
});

describe("F8: datasources", () => {
  const split = mapChecks(recorded, (c) => {
    if (c.dataset === "sales.orders") return { ...c, datasource: "warehouse", datasource_state: "defined" };
    if (c.dataset === "sales.customers") return { ...c, datasource: "staging", datasource_state: "not_defined" };
    return { ...c, datasource: "", datasource_state: "none" };
  });

  it("lists each name, marks an undefined one, and puts No datasource last", async () => {
    await open(split);
    expect(labels("Datasource")).toEqual(["staging (not defined) 5", "warehouse 9", "No datasource 4"]);
  });

  it("keeps the name as written in the URL, and empty for No datasource", async () => {
    await open(split);
    fireEvent.click(box("Datasource", "staging (not defined) 5"));
    expect(url()).toBe("/checks?datasource=staging");
    expect(shownIds()).toEqual(ids(inFile("sales/customers.yml")));
    fireEvent.click(box("Datasource", "staging (not defined) 5"));
    fireEvent.click(box("Datasource", "No datasource 4"));
    expect(url()).toBe("/checks?datasource=");
    expect(shownIds()).toEqual(ids(inFile("inventory/products.yml")));
  });

  it("puts not_a_name under No datasource too (decision 4)", () => {
    const odd = mapChecks(split, (c) =>
      c.dataset === "sales.orders" ? { ...c, datasource: "", datasource_state: "not_a_name" } : c,
    );
    const options = facetOptions(odd.checks.items, EMPTY_QUERY, "datasource");
    expect(options.map((o) => [o.label, o.count])).toEqual([
      ["staging", 5],
      ["No datasource", 13],
    ]);
  });
});

describe("F9: a one-value filter", () => {
  it("is hidden with nothing ticked, and shown ticked when the URL selects it", async () => {
    await open(recorded, "?datasource=lake");
    expect(labels("Datasource")).toEqual(["lake 18"]);
    expect(box("Datasource", "lake 18").checked).toBe(true);
    expect(shownIds()).toHaveLength(18);
    expect(url()).toBe("/checks?datasource=lake");
  });
});

// ---- F10–F12: the URL ---------------------------------------------------------

describe("F10: the URL restores the view", () => {
  const search = "?q=orders&status=fail&tag=tier-1&owner=sales-data%40example.com";
  const expected = ids((c) => c.dataset === "sales.orders" && c.latest?.outcome === "fail");

  it("fills the box, ticks each box, and keeps the parameter order", async () => {
    await open(recorded, search);
    expect(screen.getByRole<HTMLInputElement>("searchbox").value).toBe("orders");
    expect(screen.getByRole<HTMLInputElement>("checkbox", { name: "Fail 4" }).checked).toBe(true);
    expect(box("Tag", "tier-1 4").checked).toBe(true);
    expect(box("Owner", "sales-data@example.com 4").checked).toBe(true);
    expect(shownIds()).toEqual(expected);
    expect(url()).toBe(`/checks${search}`);
  });

  it("writes parameters in the order q, status, tag, owner, datasource whatever the click order", () => {
    expect(
      explorerSearch({ q: "x", statuses: ["pass"], datasource: ["lake"], owner: ["o"], tag: ["t", "a"] }),
    ).toBe("?q=x&status=pass&tag=a&tag=t&owner=o&datasource=lake");
    expect(parseExplorerQuery("?datasource=lake&tag=t&owner=o&q=x")).toEqual({
      q: "x",
      statuses: [],
      tag: ["t"],
      owner: ["o"],
      datasource: ["lake"],
    });
  });

  it("comes back the same after a check page and Back", async () => {
    const first = await open(recorded);
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "orders" } });
    fireEvent.click(screen.getByRole("checkbox", { name: "Fail 4" }));
    fireEvent.click(box("Tag", "tier-1 4"));
    fireEvent.click(box("Owner", "sales-data@example.com 4"));
    expect(url()).toBe(`/checks${search}`);
    first.unmount();
    stubServer(recorded);
    render(<App path={window.location.pathname} search={window.location.search} />);
    await vi.waitFor(() => {
      if (screen.getByRole("status").textContent === "Loading…") throw new Error("still loading");
    });
    expect(box("Owner", "sales-data@example.com 4").checked).toBe(true);
    expect(shownIds()).toEqual(expected);
  });
});

describe("F11: a value no loaded check has", () => {
  it("is ticked at 0, can be unticked, and nothing matches meanwhile", async () => {
    await open(recorded, "?tag=removed");
    const removed = box("Tag", "removed 0");
    expect(removed.checked).toBe(true);
    expect(screen.getByText("No checks match.")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Clear search and filters" }).getAttribute("href")).toBe("/checks");
    fireEvent.click(removed);
    expect(shownIds()).toHaveLength(18);
    expect(url()).toBe("/checks");
    expect(screen.queryByRole("checkbox", { name: /^removed/ })).toBeNull();
  });
});

describe("F12: hostile and malformed values", () => {
  it("cuts a 2,000-character tag from the URL to 1,000 code points (decision 5)", async () => {
    await open(recorded, `?tag=${"t".repeat(2000)}`);
    expect(new URLSearchParams(window.location.search).get("tag")).toHaveLength(1000);
    expect(box("Tag", `${"t".repeat(1000)} 0`).checked).toBe(true);
    const emoji = parseExplorerQuery(`?owner=${"a".repeat(999)}${encodeURIComponent("😀")}x`).owner[0] ?? "";
    expect(Array.from(emoji)).toHaveLength(1000);
    expect(emoji.endsWith("😀")).toBe(true);
  });

  it("renders markup in a value as text, never in an href", async () => {
    const alert = vi.fn();
    vi.stubGlobal("alert", alert);
    const owner = "<img src=x onerror=alert(1)>";
    await open(recorded, `?owner=${encodeURIComponent(owner)}`);
    expect(box("Owner", `${owner} 0`).checked).toBe(true);
    expect(document.querySelectorAll("img, [onerror]")).toHaveLength(0);
    for (const a of document.querySelectorAll("a")) expect(a.getAttribute("href") ?? "").not.toMatch(/img|onerror|%3C/i);
    expect(alert).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  it("keeps a repeated value once", async () => {
    await open(recorded, "?tag=sales&tag=sales&owner=&owner=");
    expect(labels("Tag").filter((l) => l.startsWith("sales"))).toHaveLength(1);
    expect(labels("Owner").filter((l) => l.startsWith("No owner"))).toHaveLength(1);
    expect(url()).toBe("/checks?tag=sales&owner=");
  });
});

// ---- F13–F14 ------------------------------------------------------------------

describe("F13: the search reads tags, owner and datasource", () => {
  it.each([
    ["tier-1", 14],
    ["TIER-1", 14],
    ["sales-data", 14],
    ["  Data-Platform@  ", 4],
    ["lake", 18],
    ["catalog", 4],
  ])("%j finds %i checks", async (q, n) => {
    await open(recorded);
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: q } });
    expect(shownIds()).toHaveLength(n);
  });

  it("names the new fields in the hint", async () => {
    await open(recorded);
    expect(text(document.querySelector(".explorer__hint") ?? document.body)).toBe(
      "Name, expression, dataset, file, id, tag, owner or datasource",
    );
  });

  it("does not match a null owner as text", () => {
    const unowned = recorded.checks.items.map((c) => ({ ...c, owner: null, tags: [] }));
    expect(filterChecks(unowned, { ...EMPTY_QUERY, q: "null" })).toEqual([]);
  });
});

describe("F14: clearing and the Showing line", () => {
  it("counts every filter in the Showing line", async () => {
    await open(recorded);
    expect(showing()).toBe("Showing all 18 checks.");
    fireEvent.click(box("Owner", "data-platform@example.com 4"));
    expect(showing()).toBe("Showing 4 of 18 checks.");
    fireEvent.click(box("Tag", "tier-1 0"));
    expect(showing()).toBe("Showing 0 of 18 checks.");
  });

  it("clears every filter: the link is /checks, which reads no filter", async () => {
    await open(recorded, "?q=zzz&status=fail&tag=sales&owner=&datasource=lake");
    expect(screen.getByRole("link", { name: "Clear search and filters" }).getAttribute("href")).toBe("/checks");
    expect(parseExplorerQuery("")).toEqual(EMPTY_QUERY);
  });
});

// ---- F15–F16 ------------------------------------------------------------------

describe("F15: a long filter", () => {
  const pad = (n: number): string => `t${String(n).padStart(2, "0")}`;
  // t00 on all 18, t01 on 9, t02 on 3, t03–t59 on the first check only: 60 tags.
  const many = mapChecks(recorded, (c, i) => {
    const tags = [pad(0)];
    if (i < 9) tags.push(pad(1));
    if (i < 3) tags.push(pad(2));
    if (i === 0) for (let n = 3; n < 60; n += 1) tags.push(pad(n));
    return { ...c, tags };
  });

  it("shows the first 10 by count and Show all 60; ticked values always show", async () => {
    await open(many, "?tag=t59");
    const shown = labels("Tag").map((l) => l.split(" ")[0]);
    expect(shown).toEqual(["t00", "t01", "t02", "t03", "t04", "t05", "t06", "t07", "t08", "t09", "t59"]);
    const more = within(group("Tag")).getByRole("button", { name: "Show all 60" });
    expect(more.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(more);
    expect(labels("Tag")).toHaveLength(60);
    const fewer = within(group("Tag")).getByRole("button", { name: "Show fewer" });
    expect(fewer.getAttribute("aria-expanded")).toBe("true");
    fireEvent.click(fewer);
    expect(labels("Tag")).toHaveLength(11);
  });

  it("has no button at 10 values or fewer", async () => {
    await open(recorded);
    expect(within(group("Tag")).queryByRole("button")).toBeNull();
  });
});

describe("F16: 500 checks, 40 tags, 20 owners", () => {
  const base = recorded.checks.items[0];
  if (base === undefined) throw new Error("fixture has no checks");
  const items: CheckSummary[] = Array.from({ length: 500 }, (_, i) => {
    const file = `checks/domain${String(i % 40).padStart(2, "0")}/file${String(i % 4)}.yml`;
    return {
      ...base,
      id: `c${String(i).padStart(15, "0")}`,
      name: `row_count > ${String(i)}`,
      expression: `row_count > ${String(i)}`,
      dataset: `domain${String(i % 40)}.table${String(i % 4)}`,
      owner: `owner${String(i % 20)}@example.com`,
      tags: [`tag${String(i % 40)}`, `tag${String((i * 7) % 40)}`],
      datasource: `ds${String(i % 3)}`,
      location: { file, line: i + 1, column: 5 },
      source: `${file}:${String(i + 1)}:5`,
    };
  });

  /** A first render of the filters and the tree, as the page does it. */
  function renderOnce(checks: readonly CheckSummary[]): number {
    const started = performance.now();
    const query = { ...EMPTY_QUERY, tag: ["tag3"] };
    const root = buildTree(filterChecks(checks, query), commonFolder(checks.map((c) => c.location.file)));
    const { unmount } = render(
      <>
        {FACET_KEYS.map((facet) => (
          <FacetFilter key={facet} facet={facet} options={facetOptions(checks, query, facet)} onChange={() => undefined} />
        ))}
        <ExplorerTree root={root} filtering={false} />
      </>,
    );
    const took = performance.now() - started;
    unmount();
    return took;
  }

  // As E18: the spec's 200 ms holds on a developer machine; the assertion is
  // the portable ceiling a real regression (quadratic counting) would cross.
  it("renders the filters and tree within E18's budget", () => {
    renderOnce(items.slice(0, 5));
    const best = Math.min(renderOnce(items), renderOnce(items), renderOnce(items));
    expect(best).toBeLessThan(600);
  });
});
