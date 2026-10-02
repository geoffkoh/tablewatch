/**
 * QA attacks on the explorer's tag, owner and datasource filters (spec 016):
 * "none" values, real values the URL cut would change, case and whitespace,
 * `+` and `@` in URLs, count semantics against brute force, F15's collapse,
 * and parameter order.
 */
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { CheckSummary } from "../api/types";
import { App } from "../App";
import { FacetFilter } from "../components/FacetFilter";
import {
  collapsedOptions,
  EMPTY_QUERY,
  explorerSearch,
  FACET_KEYS,
  facetOptions,
  filterChecks,
  parseExplorerQuery,
  type ExplorerQuery,
  type FacetKey,
} from "../lib/explorer";
import { STATUS_ORDER, statusOf } from "../lib/status";
import { recorded, type OverviewResponses } from "./fixtures/states";
import { CLOCK, setClock, stubServer, text } from "./render";

beforeEach(() => {
  setClock(CLOCK);
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  window.history.replaceState(null, "", "/");
});

async function open(fixture: OverviewResponses, search = ""): Promise<void> {
  window.history.replaceState(null, "", `/checks${search}`);
  stubServer(fixture);
  render(<App path="/checks" search={search} />);
  await vi.waitFor(() => {
    if (screen.getByRole("status").textContent === "Loading…") throw new Error("still loading");
  });
}

function mapChecks(base: OverviewResponses, fn: (c: CheckSummary, i: number) => CheckSummary): OverviewResponses {
  const next = structuredClone(base);
  next.checks.items = next.checks.items.map(fn);
  return next;
}

const shownIds = (): string[] =>
  [...document.querySelectorAll<HTMLElement>(".tree__check")].map((li) => li.dataset.checkId ?? "?");
const url = (): string => `${window.location.pathname}${window.location.search}`;
const group = (name: string): HTMLElement => screen.getByRole("group", { name });
const labels = (name: string): string[] =>
  within(group(name))
    .getAllByRole("checkbox")
    .map((c) => text(c.closest("label") ?? c));
const box = (name: string, label: string): HTMLInputElement =>
  within(group(name)).getByRole<HTMLInputElement>("checkbox", { name: label });
const idsOf = (fixture: OverviewResponses, pred: (c: CheckSummary) => boolean): string[] =>
  fixture.checks.items.filter(pred).map((c) => c.id);

// ---- real values the URL cut must not break -----------------------------------

describe("a real value longer than 200 code points", () => {
  const longOwner = `${"o".repeat(240)}@example.com`;
  const long = mapChecks(recorded, (c) => (c.dataset === "inventory.products" ? { ...c, owner: longOwner } : c));

  it("counts its checks", () => {
    const option = facetOptions(long.checks.items, EMPTY_QUERY, "owner").find((o) => o.value.startsWith("ooo"));
    expect(option?.count).toBe(4);
  });

  it("ticking it shows its checks, not nothing", async () => {
    await open(long);
    const owner = within(group("Owner"))
      .getAllByRole<HTMLInputElement>("checkbox")
      .find((c) => text(c.closest("label") ?? c).startsWith("ooo"));
    if (owner === undefined) throw new Error("no long owner checkbox");
    fireEvent.click(owner);
    expect(shownIds()).toEqual(idsOf(long, (c) => c.owner === longOwner));
  });
});

describe("a tag of \"\" in the data", () => {
  // The loader accepts `tags: [sales, ""]`; such a dataset has a tag, so it is not "No tags".
  const blank = mapChecks(recorded, (c) => (c.dataset === "inventory.products" ? { ...c, tags: ["catalogue", ""] } : c));

  it("does not put a tagged check under No tags", () => {
    const none = facetOptions(blank.checks.items, EMPTY_QUERY, "tag").find((o) => o.value === "");
    expect(none?.count ?? 0).toBe(0);
  });
});

// ---- the "none" values ---------------------------------------------------------

describe("selecting a none value nobody has", () => {
  it("owner= on a project where every check has an owner: No owner 0, ticked, nothing shown", async () => {
    await open(recorded, "?owner=");
    expect(box("Owner", "No owner 0").checked).toBe(true);
    // A filter's own counts ignore its own selection (F6).
    expect(labels("Owner")).toEqual(["data-platform@example.com 4", "sales-data@example.com 14", "No owner 0"]);
    expect(screen.getByText("No checks match.")).toBeTruthy();
    expect(url()).toBe("/checks?owner=");
  });

  it("tag= on checks that all have tags: No tags 0; ticking a tag beside it ORs", async () => {
    await open(recorded, "?tag=");
    expect(box("Tag", "No tags 0").checked).toBe(true);
    fireEvent.click(box("Tag", "catalogue 4"));
    expect(shownIds()).toHaveLength(4);
    expect(url()).toBe("/checks?tag=catalogue&tag=");
  });

  it("an owner of \"\" and a null owner are both No owner (decision 1)", () => {
    const items = recorded.checks.items.map((c, i) => (i === 0 ? { ...c, owner: "" } : i === 1 ? { ...c, owner: null } : c));
    const none = facetOptions(items, EMPTY_QUERY, "owner").filter((o) => o.value === "");
    expect(none.map((o) => [o.label, o.count])).toEqual([["No owner", 2]]);
  });

  it("a filter whose only value is none is hidden", async () => {
    await open(mapChecks(recorded, (c) => ({ ...c, owner: null })));
    expect(screen.queryByRole("group", { name: "Owner" })).toBeNull();
  });
});

describe("not_a_name and none under No datasource, on the page", () => {
  const odd = mapChecks(recorded, (c) => {
    if (c.dataset === "sales.orders") return { ...c, datasource: "", datasource_state: "not_a_name" };
    if (c.dataset === "inventory.products") return { ...c, datasource: "", datasource_state: "none" };
    return { ...c, datasource: "staging", datasource_state: "not_defined" };
  });

  it("ticking No datasource shows both kinds, and the URL is datasource=", async () => {
    await open(odd);
    expect(labels("Datasource")).toEqual(["staging (not defined) 5", "No datasource 13"]);
    fireEvent.click(box("Datasource", "No datasource 13"));
    expect(shownIds().sort()).toEqual(idsOf(odd, (c) => c.datasource === "").sort());
    expect(url()).toBe("/checks?datasource=");
  });
});

// ---- case, whitespace, + and @ -------------------------------------------------

describe("values that differ only in case or whitespace", () => {
  const cased = mapChecks(recorded, (c) => {
    if (c.dataset === "inventory.products") return { ...c, tags: ["Sales"] };
    if (c.dataset === "sales.customers") return { ...c, tags: [" sales"] };
    return { ...c, tags: ["sales"] };
  });

  it("are separate checkboxes; ticking one selects only it", async () => {
    await open(cased);
    expect(labels("Tag")).toHaveLength(3);
    fireEvent.click(box("Tag", "sales 9"));
    expect(shownIds().sort()).toEqual(idsOf(cased, (c) => c.dataset === "sales.orders").sort());
    expect(url()).toBe("/checks?tag=sales");
  });

  it("a leading space survives the URL round trip", () => {
    const q = parseExplorerQuery(explorerSearch({ ...EMPTY_QUERY, tag: [" sales"] }));
    expect(q.tag).toEqual([" sales"]);
  });
});

describe("+ and @ in an owner", () => {
  const owner = "sales+ops@example.com";
  const plus = mapChecks(recorded, (c) => (c.dataset === "sales.orders" ? { ...c, owner } : c));

  it("encodes + as %2B so the link reads back the same owner", async () => {
    await open(plus);
    fireEvent.click(box("Owner", `${owner} 9`));
    expect(window.location.search).toBe("?owner=sales%2Bops%40example.com");
    expect(parseExplorerQuery(window.location.search).owner).toEqual([owner]);
  });

  it("ticks the owner from a hand-encoded link, and from a raw @", async () => {
    await open(plus, "?owner=sales%2Bops@example.com");
    expect(box("Owner", `${owner} 9`).checked).toBe(true);
    expect(shownIds()).toHaveLength(9);
    expect(url()).toBe("/checks?owner=sales%2Bops%40example.com");
  });

  it("a raw + in a link is a space, per URL rules: a ticked 0 value, not a crash", async () => {
    await open(plus, "?owner=sales+ops@example.com");
    expect(box("Owner", "sales ops@example.com 0").checked).toBe(true);
  });
});

// ---- counts against brute force ------------------------------------------------

describe("F6 counts equal a brute-force recount", () => {
  const items = mapChecks(recorded, (c, i) => ({
    ...c,
    owner: i % 4 === 0 ? null : c.owner,
    tags: i % 5 === 0 ? [] : c.tags,
    datasource: ["lake", "", "warehouse"][i % 3] ?? "lake",
    datasource_state: i % 3 === 1 ? "none" : "defined",
  })).checks.items;

  const queries: ExplorerQuery[] = [
    EMPTY_QUERY,
    { ...EMPTY_QUERY, statuses: ["fail"] },
    { ...EMPTY_QUERY, statuses: ["fail", "pass"], tag: ["tier-1", ""], owner: [""] },
    { ...EMPTY_QUERY, q: "orders", datasource: ["", "warehouse"], owner: ["sales-data@example.com"] },
    { q: "e", statuses: ["warn", "pass"], tag: ["catalogue", "sales"], owner: ["", "data-platform@example.com"], datasource: ["lake"] },
  ];

  const values = (c: CheckSummary, key: FacetKey): string[] =>
    key === "tag" ? (c.tags.length === 0 ? [""] : [...c.tags]) : key === "owner" ? [c.owner ?? ""] : [c.datasource];

  it.each(queries.map((q, i) => [i, q] as const))("query %i", (_, query) => {
    for (const key of FACET_KEYS) {
      for (const option of facetOptions(items, query, key)) {
        const expected = filterChecks(items, { ...query, [key]: [] }).filter((c) =>
          values(c, key).includes(option.value),
        ).length;
        expect([key, option.value, option.count]).toEqual([key, option.value, expected]);
        // Ticking only this value in the filter yields exactly `count` checks.
        expect(filterChecks(items, { ...query, [key]: [option.value] })).toHaveLength(option.count);
      }
    }
    for (const status of STATUS_ORDER) {
      const all = filterChecks(items, { ...query, statuses: [] }).filter((c) => statusOf(c) === status);
      expect(filterChecks(items, { ...query, statuses: [status] })).toHaveLength(all.length);
    }
  });

  it("Status counts follow owner and datasource on the page", async () => {
    const split = mapChecks(recorded, (c) =>
      c.dataset === "sales.orders" ? { ...c, datasource: "warehouse" } : c,
    );
    await open(split, "?datasource=warehouse");
    const fail = split.checks.items.filter((c) => c.datasource === "warehouse" && statusOf(c) === "fail").length;
    expect(labels("Status").find((l) => l.startsWith("Fail"))).toBe(`Fail ${String(fail)}`);
    fireEvent.click(box("Owner", "data-platform@example.com 0"));
    expect(labels("Status").every((l) => l.endsWith(" 0"))).toBe(true);
  });
});

// ---- F15 -----------------------------------------------------------------------

describe("F15: ticking while collapsed and expanded", () => {
  const pad = (n: number): string => `t${String(n).padStart(2, "0")}`;
  const many = mapChecks(recorded, (c, i) => {
    const tags = [pad(0)];
    if (i < 9) tags.push(pad(1));
    if (i === 0) for (let n = 2; n < 30; n += 1) tags.push(pad(n));
    return { ...c, tags };
  });

  it("a value ticked from Show all stays visible after Show fewer, and unticking hides it", async () => {
    await open(many);
    fireEvent.click(within(group("Tag")).getByRole("button", { name: "Show all 30" }));
    fireEvent.click(box("Tag", "t25 1"));
    fireEvent.click(within(group("Tag")).getByRole("button", { name: "Show fewer" }));
    expect(labels("Tag")).toHaveLength(11);
    expect(box("Tag", "t25 1").checked).toBe(true);
    expect(url()).toBe("/checks?tag=t25");
    fireEvent.click(box("Tag", "t25 1"));
    expect(labels("Tag")).toHaveLength(10);
    expect(within(group("Tag")).queryByRole("checkbox", { name: /^t25/ })).toBeNull();
  });

  it("ticked unknown values count toward Show all and are always shown", () => {
    const options = facetOptions(many.checks.items, { ...EMPTY_QUERY, tag: ["zz1", "zz2"] }, "tag");
    expect(options).toHaveLength(32);
    const shown = collapsedOptions(options).map((o) => o.value);
    expect(shown).toContain("zz1");
    expect(shown).toContain("zz2");
    expect(shown).toHaveLength(12);
  });

  it("FacetFilter keeps every ticked value when one more is ticked from a collapsed list", () => {
    const onChange = vi.fn();
    const options = facetOptions(many.checks.items, { ...EMPTY_QUERY, tag: ["t29", "t28"] }, "tag");
    render(<FacetFilter facet="tag" options={options} onChange={onChange} />);
    fireEvent.click(box("Tag", "t00 18"));
    expect(onChange).toHaveBeenCalledWith(["t28", "t29", "t00"]);
  });
});

// ---- URL order and Clear ----------------------------------------------------------

describe("the URL's parameter order and Clear", () => {
  it("rewrites a scrambled link into q, status, tag, owner, datasource order", async () => {
    await open(recorded, "?datasource=lake&owner=sales-data%40example.com&tag=tier-1&status=fail&q=orders&tag=sales");
    expect(url()).toBe(
      "/checks?q=orders&status=fail&tag=sales&tag=tier-1&owner=sales-data%40example.com&datasource=lake",
    );
  });

  it("drops unknown parameters and keeps the filters", async () => {
    await open(recorded, "?utm=x&tag=sales");
    expect(url()).toBe("/checks?tag=sales");
  });

  it("Clear lands on /checks with nothing ticked anywhere", async () => {
    await open(recorded, "?q=zzz&status=fail&tag=sales&owner=&datasource=lake");
    const href = screen.getByRole("link", { name: "Clear search and filters" }).getAttribute("href") ?? "";
    cleanup();
    await open(recorded, new URL(href, "http://x").search);
    expect(screen.getAllByRole<HTMLInputElement>("checkbox").some((c) => c.checked)).toBe(false);
    expect(screen.queryByRole("group", { name: "Datasource" })).toBeNull();
    expect(text(document.querySelector(".explorer__showing") ?? document.body)).toBe("Showing all 18 checks.");
    expect(url()).toBe("/checks");
  });
});
