/**
 * QA attacks on the check explorer (spec 015): odd file paths, URL handling,
 * history, counts after filtering, and the open/closed state across filters.
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { CheckSummary } from "../api/types";
import { App } from "../App";
import { buildTree, commonFolder, EMPTY_QUERY, filterChecks, parseExplorerQuery, type FolderNode, type TreeNode } from "../lib/explorer";
import { parseRoute } from "../lib/route";
import { mapLatest } from "./fixtures/derived";
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

async function open(fixture: OverviewResponses, search = "", path = "/checks"): Promise<void> {
  window.history.replaceState(null, "", `${path}${search}`);
  stubServer(fixture);
  render(<App path={path} search={search} />);
  await vi.waitFor(() => {
    if (screen.getByRole("status").textContent === "Loading…") throw new Error("still loading");
  });
}

function withFiles(base: OverviewResponses, fileOf: (c: CheckSummary, i: number) => string): OverviewResponses {
  const next = structuredClone(base);
  next.checks.items = next.checks.items.map((c, i) => ({ ...c, location: { ...c.location, file: fileOf(c, i) } }));
  return next;
}

function paths(node: TreeNode): string[] {
  return node.kind === "file" ? [node.path] : [node.path, ...node.children.flatMap(paths)];
}

function shownIds(): string[] {
  return [...document.querySelectorAll<HTMLElement>(".tree__check")].map((li) => li.dataset.checkId ?? "?");
}

function box(): HTMLInputElement {
  return screen.getByRole<HTMLInputElement>("searchbox", { name: "Search checks" });
}

function type(value: string): void {
  fireEvent.change(box(), { target: { value } });
}

function url(): string {
  return `${window.location.pathname}${window.location.search}`;
}

function details(path: string): HTMLDetailsElement {
  const found = document.querySelector(`[data-path="${path}"] > details`);
  if (!(found instanceof HTMLDetailsElement)) throw new Error(`no node ${path}`);
  return found;
}

// ---- odd file paths --------------------------------------------------------------

describe("odd file paths", () => {
  const files = (fs: string[]): CheckSummary[] => {
    const base = recorded.checks.items[0];
    if (base === undefined) throw new Error("fixture changed");
    return fs.map((file, i) => ({ ...base, id: `c${String(i)}`, location: { file, line: i + 1, column: 1 } }));
  };

  it("roots absolute paths at their common folder", () => {
    const items = files(["/srv/proj/checks/a.yml", "/srv/proj/checks/b/c.yml"]);
    const tree = buildTree(items, commonFolder(items.map((c) => c.location.file)));
    expect(tree.path).toBe("/srv/proj/checks/");
    expect(paths(tree)).toEqual(["/srv/proj/checks/", "/srv/proj/checks/b/", "/srv/proj/checks/b/c.yml", "/srv/proj/checks/a.yml"]);
  });

  it("keeps every check when absolute and relative paths mix, and node paths stay unique", () => {
    const items = files(["/abs/a.yml", "checks/b.yml", "c.yml", "checks//d.yml"]);
    const tree = buildTree(items, commonFolder(items.map((c) => c.location.file)));
    expect(tree.name).toBe("");
    const all = paths(tree);
    expect(new Set(all).size).toBe(all.length);
    expect(tree.counts.total).toBe(4);
  });

  it("puts files at the project root at the top level, under an unnamed root", async () => {
    await open(withFiles(recorded, (c) => `${c.dataset}.yml`));
    expect(document.querySelector(".tree__total")).not.toBeNull();
    const top = [...(document.querySelector(".tree > ul.tree__children")?.children ?? [])].map(
      (li) => (li as HTMLElement).dataset.path,
    );
    expect(top).toEqual(["inventory.products.yml", "sales.customers.yml", "sales.orders.yml"]);
    expect(shownIds()).toHaveLength(18);
  });

  it("finds unicode folders without case and renders them as text", async () => {
    const consoleError = vi.spyOn(console, "error");
    await open(withFiles(recorded, (c) => (c.dataset === "inventory.products" ? "checks/Données/<b>é</b>.yml" : c.location.file)));
    expect(details("checks/Données/").open).toBe(true);
    expect(document.querySelector("b")).toBeNull();
    type("DONNÉES");
    expect(shownIds()).toHaveLength(4);
    expect(consoleError).not.toHaveBeenCalled();
  });

  it("renders a mixed absolute/relative/double-slash project without React key warnings", async () => {
    const consoleError = vi.spyOn(console, "error");
    const odd = ["/abs/a.yml", "checks/b.yml", "c.yml", "checks//d.yml", "checks/b.yml/"];
    await open(withFiles(recorded, (_c, i) => odd[i % odd.length] ?? "x.yml"));
    expect(shownIds()).toHaveLength(18);
    expect(consoleError).not.toHaveBeenCalled();
  });
});

// ---- URL handling ----------------------------------------------------------------

describe("URL handling", () => {
  it("never pushes a history entry; each change replaces the current one", async () => {
    const push = vi.spyOn(window.history, "pushState");
    const replace = vi.spyOn(window.history, "replaceState");
    await open(recorded);
    type("o");
    type("or");
    fireEvent.click(screen.getByRole("checkbox", { name: /^Fail/ }));
    expect(push).not.toHaveBeenCalled();
    expect(replace).toHaveBeenCalled();
    expect(url()).toBe("/checks?q=or&status=fail");
  });

  it("keeps the trailing slash of /checks/ when rewriting", async () => {
    await open(recorded, "", "/checks/");
    type("orders");
    expect(url()).toBe("/checks/?q=orders");
  });

  it("takes the first of repeated q and writes back one", async () => {
    await open(recorded, "?q=orders&q=customers");
    expect(box().value).toBe("orders");
    expect(url()).toBe("/checks?q=orders");
  });

  it("decodes + and percent escapes once, and survives a malformed escape", async () => {
    expect(parseExplorerQuery("?q=Order+volume").q).toBe("Order volume");
    expect(parseExplorerQuery("?q=%2532").q).toBe("%32");
    await open(recorded, "?q=%E0%A4%A&status=fail");
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Checks");
    expect(screen.getByText("No checks match.")).toBeTruthy();
  });

  it("does not let q inject another parameter", async () => {
    await open(recorded);
    type("x&status=fail");
    const params = new URLSearchParams(window.location.search);
    expect(params.get("q")).toBe("x&status=fail");
    expect(params.getAll("status")).toEqual([]);
  });

  it("cuts q by code point, never splitting an emoji", () => {
    const q = parseExplorerQuery(`?q=${"a".repeat(199)}${encodeURIComponent("😀")}x`).q;
    expect(Array.from(q)).toHaveLength(200);
    expect(q.endsWith("😀")).toBe(true);
  });

  it("keeps the URL's #fragment when a filter changes", async () => {
    window.history.replaceState(null, "", "/checks#sales");
    stubServer(recorded);
    render(<App path="/checks" search="" />);
    await vi.waitFor(() => {
      if (screen.getByRole("status").textContent === "Loading…") throw new Error("still loading");
    });
    type("orders");
    expect(`${url()}${window.location.hash}`).toBe("/checks?q=orders#sales");
  });

  it("drops a spaces-only search from the URL", async () => {
    await open(recorded);
    type("   ");
    expect(url()).toBe("/checks");
    expect(shownIds()).toHaveLength(18);
  });

  it("shows a selected status that no check has, so it can be cleared", async () => {
    await open(recorded, "?status=error");
    expect(screen.getByText("No checks match.")).toBeTruthy();
    const errorToggle = screen.getByRole<HTMLInputElement>("checkbox", { name: "Error 0" });
    expect(errorToggle.checked).toBe(true);
    fireEvent.click(errorToggle);
    expect(shownIds()).toHaveLength(18);
    expect(url()).toBe("/checks");
  });
});

// ---- counts after filtering --------------------------------------------------------

describe("counts after filtering", () => {
  it("counts toggles over the search's matches, and the tree over both filters", async () => {
    await open(recorded);
    type("customers");
    // Scoped to Status: spec 016 added the Tag and Owner filters beside it.
    const status = screen.getByRole("group", { name: "Status" });
    const labels = within(status).getAllByRole("checkbox").map((c) => text(c.closest("label") ?? c));
    expect(labels).toEqual(["Fail 2", "Warn 0", "Pass 3"]);
    fireEvent.click(screen.getByRole("checkbox", { name: "Pass 3" }));
    expect(text(document.querySelector(".explorer__showing") ?? document.body)).toBe("Showing 3 of 18 checks.");
    const root = document.querySelector('[data-path="checks/"] summary');
    expect(text(root ?? document.body)).toBe("checks/ 3 checks · 3 pass");
  });

  it("a filtered tree's counts equal the filtered checks", () => {
    const filtered = filterChecks(recorded.checks.items, { ...EMPTY_QUERY, q: "sales", statuses: ["fail", "pass"] });
    const tree: FolderNode = buildTree(filtered, ["checks"]);
    expect(tree.counts.total).toBe(filtered.length);
    expect(tree.counts.warn).toBe(0);
  });
});

// ---- open/closed across filtering -------------------------------------------------

describe("open state across filtering", () => {
  const quiet = mapLatest(recorded, (c) =>
    c.dataset === "inventory.products" && c.latest !== null ? { ...c.latest, outcome: "pass" } : c.latest,
  );

  it("closes pass-only nodes again once the search is cleared", async () => {
    await open(quiet);
    expect(details("checks/inventory/").open).toBe(false);
    type("products");
    expect(details("checks/inventory/").open).toBe(true);
    type("");
    expect(details("checks/inventory/").open).toBe(false);
    expect(details("checks/sales/").open).toBe(true);
  });
});

// ---- routes ------------------------------------------------------------------------

describe("routes next to the explorer", () => {
  it.each(["/checks//", "/checks///", "/checks/?", "/Checks", "/checks/index.html/x"])("%s is not the explorer", (path) => {
    expect(parseRoute(path)).not.toEqual({ page: "explorer" });
  });

  it("/checks/x is a check page, not the explorer", () => {
    expect(parseRoute("/checks/x")).toEqual({ page: "check", id: "x" });
  });
});
